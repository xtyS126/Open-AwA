"""
多 Agent 讨论任务 REST API 路由层。

提供讨论任务的创建、查询、修订、SSE 流式订阅与紧急旁路执行能力，
对应 spec "三审制" 工作流（critic -> validator -> approver）。

路由前缀：/api/discussions
认证策略：复用 api.dependencies.get_current_user（API Key > JWT Bearer > Cookie）
SSE 鉴权：单独从 Cookie 读取 token，禁止通过 URL query 传递，遵守项目安全约束

模块职责：
1. 定义 Pydantic 请求/响应 schema 与路由端点
2. 维护 DiscussionOrchestrator 模块级单例（线程安全懒加载）
3. 提供内置 LLM 调用包装器，复用 ExecutionLayer 的 Provider 配置解析能力
4. 将讨论模块异常族转换为 HTTPException，避免宽泛 except Exception
5. 后台异步触发讨论轮次，注册回调处理异常避免静默吞错误
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
from datetime import datetime
from typing import Any, AsyncGenerator, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, func as _func
from sqlalchemy.orm import Session

from api.dependencies import get_current_user
from config.security import ACCESS_TOKEN_COOKIE_NAME, decode_access_token, is_token_blacklisted
from core.discussion.definitions import (
    DiscussionExecutionError,
    DiscussionParseError,
    DiscussionRole,
    DiscussionRoundLimitError,
    DiscussionStateError,
    DiscussionTaskData,
    DiscussionVoteData,
    ProposedAction,
)
from core.discussion.orchestrator import DiscussionOrchestrator
from db.models import DiscussionTask, DiscussionVote, SessionLocal, User, get_db


router = APIRouter(prefix="/api/discussions", tags=["discussions"])

# ── Orchestrator 模块级单例 ──────────────────────────────────────────
# 参考 subagents.py 的 _get_orchestrator() 模式：线程锁 + 双重检查
_orchestrator: Optional[DiscussionOrchestrator] = None
_orchestrator_lock = threading.Lock()


def _default_llm_caller(messages: List[Dict[str, str]]) -> str:
    """
    内置 LLM 调用包装器（同步占位）。

    [NOTE] 本函数仅在 _get_orchestrator 初始化时作为 fallback，
    实际异步调用由 _async_default_llm_caller 完成。
    此处保留函数签名仅为类型提示，不会被直接调用。
    """
    raise RuntimeError("同步 LLM 调用入口不应被直接使用，请使用 _async_default_llm_caller")


async def _async_default_llm_caller(messages: List[Dict[str, str]]) -> str:
    """
    默认 LLM 调用实现：复用 ExecutionLayer 的 Provider 配置解析能力。

    将 OpenAI 风格 messages 列表拼接为 prompt 后调用 ExecutionLayer._call_llm_api，
    复用全局已配置的 provider/model/api_key，避免讨论模块重复实现 LLM 适配逻辑。

    Args:
        messages: OpenAI 风格消息列表，至少含 system + user 两条

    Returns:
        LLM 文本输出

    Raises:
        DiscussionExecutionError: 配置缺失或调用失败时抛出
    """
    # 将 messages 拼接为可读 prompt（system + user 内容用分隔符区分）
    parts: List[str] = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        parts.append(f"[{role}]\n{content}")
    prompt = "\n\n".join(parts)

    try:
        from core.executor import ExecutionLayer
    except ImportError as exc:
        raise DiscussionExecutionError(
            f"ExecutionLayer 模块不可用，无法调用 LLM: {exc}"
        ) from exc

    executor = ExecutionLayer()
    llm_db = SessionLocal()
    try:
        # 构造最小调用上下文：使用全局默认模型配置
        llm_ctx: Dict[str, Any] = {"db": llm_db}
        result = await executor._call_llm_api(prompt, llm_ctx)
    except asyncio.TimeoutError as exc:
        raise DiscussionExecutionError(f"LLM 调用超时: {exc}") from exc
    except (ConnectionError, RuntimeError) as exc:
        raise DiscussionExecutionError(f"LLM 调用失败: {exc}") from exc
    finally:
        llm_db.close()

    if not isinstance(result, dict):
        raise DiscussionExecutionError(
            f"LLM 返回结构异常，期望 dict 实际 {type(result).__name__}"
        )
    if not result.get("ok"):
        error_info = result.get("error", {})
        error_msg = (
            error_info.get("message", "未知错误")
            if isinstance(error_info, dict)
            else str(error_info)
        )
        raise DiscussionExecutionError(f"LLM 调用返回错误: {error_msg}")

    return str(result.get("response", "") or "")


def _get_orchestrator() -> DiscussionOrchestrator:
    """
    获取或初始化 DiscussionOrchestrator 单例（线程安全）。

    传入参数：
      - db_session_factory=SessionLocal：复用全局 SQLAlchemy 会话工厂
      - llm_caller=_async_default_llm_caller：复用 ExecutionLayer 的 LLM 调用能力

    [NOTE] DiscussionOrchestrator 未提供 init() 方法注册内置角色 Agent，
    SubTask 3.9 跳过：三个角色（critic/validator/approver）的 system prompt 已由
    core/discussion/roles.py 静态定义，orchestrator 在 run_discussion_round 中
    按顺序调用 build_role_messages 构建 messages，无需运行时注册。
    subagent_delegate 执行器在 orchestrator 内部经 task_runtime.spawn_agent 委派，
    无需在此注入任何子代理管理器。
    """
    global _orchestrator
    if _orchestrator is None:
        with _orchestrator_lock:
            # 双重检查，避免多线程重复初始化
            if _orchestrator is None:
                _orchestrator = DiscussionOrchestrator(
                    db_session_factory=SessionLocal,
                    llm_caller=_async_default_llm_caller,
                )
                logger.bind(
                    event="discussion_orchestrator_initialized",
                    module="discussions",
                ).info("DiscussionOrchestrator 单例已初始化")
    return _orchestrator


def _is_admin_user(user: User) -> bool:
    """
    检查用户是否具备管理员权限。

    优先级：
      1. user.role == "admin"（数据库角色字段，参考 dependencies.get_current_admin_user）
      2. user.id 在环境变量 ADMIN_USER_IDS 中（兼容无 role 字段的部署）

    [NOTE] User 模型未提供 is_admin 布尔字段，故采用 role + 环境变量双路校验。
    """
    if getattr(user, "role", None) == "admin":
        return True
    admin_ids_raw = os.getenv("ADMIN_USER_IDS", "").strip()
    if not admin_ids_raw:
        return False
    admin_ids = [item.strip() for item in admin_ids_raw.split(",") if item.strip()]
    return str(user.id) in admin_ids


def _resolve_sse_user(request: Request, db: Session) -> Optional[User]:
    """
    SSE 端点专用鉴权：从 Cookie 读取 access_token 并解析用户。

    [SECURITY] 不通过 URL query 传 token，遵守项目安全约束
    （URL 可能被代理/浏览器历史记录泄露）。

    Args:
        request: FastAPI 请求对象
        db: 数据库会话

    Returns:
        认证通过返回 User ORM 对象，失败返回 None
    """
    cookie_token = request.cookies.get(ACCESS_TOKEN_COOKIE_NAME, "")
    if not cookie_token or not cookie_token.strip():
        return None

    payload = decode_access_token(cookie_token.strip())
    if payload is None:
        return None

    jti = payload.get("jti")
    if jti and is_token_blacklisted(str(jti), db):
        return None

    username = payload.get("sub")
    if not isinstance(username, str):
        return None

    return db.query(User).filter(User.username == username).first()


# ── Pydantic 请求/响应 Schema ──────────────────────────────────────────


class ProposedActionSchema(BaseModel):
    """提议动作结构，type 标识执行器类型，payload 为执行器特定参数。"""

    type: str = Field(
        ...,
        pattern="^(plugin_command|tool_call|subagent_delegate)$",
        description="执行器类型：plugin_command/tool_call/subagent_delegate",
    )
    payload: Dict[str, Any] = Field(
        default_factory=dict,
        description="执行器特定参数，结构因 type 而异",
    )


class DiscussionCreateRequest(BaseModel):
    """创建讨论任务请求体。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    title: str = Field(..., min_length=1, max_length=200, description="任务标题")
    description: str = Field(..., min_length=1, max_length=5000, description="任务描述")
    proposed_action: ProposedActionSchema = Field(..., description="待评审的提议动作")
    context: Dict[str, Any] = Field(default_factory=dict, description="讨论上下文")
    max_rounds: int = Field(default=3, ge=1, le=5, description="最大讨论轮次，默认 3，上限 5")


class DiscussionReviseRequest(BaseModel):
    """提交修订请求体。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    proposed_action: ProposedActionSchema = Field(..., description="修订后的提议动作")
    reason: str = Field(..., min_length=1, max_length=2000, description="修订理由")


class DiscussionForceExecuteRequest(BaseModel):
    """紧急旁路执行请求体（仅 admin 可调用）。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    reason: str = Field(..., min_length=1, max_length=2000, description="旁路执行理由")


class DiscussionVoteResponse(BaseModel):
    """投票记录响应模型。"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    role: str
    round: int
    vote: str
    reason: Optional[str] = None
    transcript: List[Any] = Field(default_factory=list)
    created_at: Optional[datetime] = None


class VoteSummaryResponse(BaseModel):
    """各角色最新投票摘要，按角色聚合。"""

    critic: Optional[DiscussionVoteResponse] = None
    validator: Optional[DiscussionVoteResponse] = None
    approver: Optional[DiscussionVoteResponse] = None


class DiscussionTaskResponse(BaseModel):
    """讨论任务详情响应模型。"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    description: str
    proposed_action: Dict[str, Any]
    context: Dict[str, Any]
    status: str
    round: int
    max_rounds: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    votes: List[DiscussionVoteResponse] = Field(default_factory=list, description="所有轮次投票记录")


class DiscussionListItemResponse(BaseModel):
    """讨论任务列表项响应模型。"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    status: str
    round: int
    max_rounds: int
    created_at: Optional[datetime] = None
    vote_summary: VoteSummaryResponse = Field(default_factory=VoteSummaryResponse)


class DiscussionListResponse(BaseModel):
    """讨论任务分页列表响应。"""

    items: List[DiscussionListItemResponse]
    total: int
    page: int
    page_size: int


# ── 辅助函数：ORM -> 响应模型转换 ──────────────────────────────────────


def _vote_to_response(vote: DiscussionVote) -> DiscussionVoteResponse:
    """将 DiscussionVote ORM 对象转为响应模型。"""
    return DiscussionVoteResponse(
        id=vote.id,
        role=vote.role,
        round=vote.round,
        vote=vote.vote,
        reason=vote.reason,
        transcript=list(vote.transcript) if vote.transcript else [],
        created_at=vote.created_at,
    )


def _build_vote_summary(
    db: Session, discussion_id: str
) -> VoteSummaryResponse:
    """
    构建各角色最新投票摘要。

    对每个角色取 round 最大的一条投票记录作为最新投票。

    Args:
        db: 数据库会话
        discussion_id: 讨论任务 ID

    Returns:
        VoteSummaryResponse 含三个角色最新投票，无投票记录时对应字段为 None
    """
    summary = VoteSummaryResponse()
    role_field_map = {
        DiscussionRole.CRITIC.value: "critic",
        DiscussionRole.VALIDATOR.value: "validator",
        DiscussionRole.APPROVER.value: "approver",
    }
    for role_value, field_name in role_field_map.items():
        # 取该角色 round 最大的一条记录
        vote = (
            db.query(DiscussionVote)
            .filter(
                DiscussionVote.discussion_id == discussion_id,
                DiscussionVote.role == role_value,
            )
            .order_by(DiscussionVote.round.desc())
            .first()
        )
        if vote is not None:
            setattr(summary, field_name, _vote_to_response(vote))
    return summary


def _build_vote_summaries_batch(
    db: Session, discussion_ids: list[str]
) -> dict[str, VoteSummaryResponse]:
    """
    批量构建多个讨论任务的投票摘要，避免 N+1 查询。

    通过 SQL 子查询一次性获取所有任务各角色的最新投票（round 最大），
    替代原来对每个任务调用 _build_vote_summary 的 3 次查询模式。

    Args:
        db: 数据库会话
        discussion_ids: 讨论任务 ID 列表

    Returns:
        dict: {discussion_id: VoteSummaryResponse}，未命中任务返回空 summary
    """
    if not discussion_ids:
        return {}

    role_field_map = {
        DiscussionRole.CRITIC.value: "critic",
        DiscussionRole.VALIDATOR.value: "validator",
        DiscussionRole.APPROVER.value: "approver",
    }

    # 子查询：每个 (discussion_id, role) 的最大 round
    subq = (
        db.query(
            DiscussionVote.discussion_id.label("did"),
            DiscussionVote.role.label("r"),
            _func.max(DiscussionVote.round).label("max_round"),
        )
        .filter(DiscussionVote.discussion_id.in_(discussion_ids))
        .group_by(DiscussionVote.discussion_id, DiscussionVote.role)
        .subquery()
    )

    # 关联原表取完整记录（join 条件：同 discussion_id + role + round=最大round）
    votes = (
        db.query(DiscussionVote)
        .join(
            subq,
            (DiscussionVote.discussion_id == subq.c.did)
            & (DiscussionVote.role == subq.c.r)
            & (DiscussionVote.round == subq.c.max_round),
        )
        .all()
    )

    # 按 discussion_id 分组装填 summary
    result: dict[str, VoteSummaryResponse] = {
        did: VoteSummaryResponse() for did in discussion_ids
    }
    for vote in votes:
        summary = result.get(vote.discussion_id)
        if summary is None:
            continue
        field_name = role_field_map.get(vote.role)
        # 同 (discussion_id, role, max_round) 可能有多条，仅取第一条
        if field_name and getattr(summary, field_name) is None:
            setattr(summary, field_name, _vote_to_response(vote))
    return result


def _task_to_detail_response(
    db: Session, task: DiscussionTask
) -> DiscussionTaskResponse:
    """
    将 DiscussionTask ORM 对象转为详情响应模型，附带所有轮次投票。

    Args:
        db: 数据库会话（用于查询投票记录）
        task: 讨论任务 ORM 对象

    Returns:
        DiscussionTaskResponse 含完整讨论历史
    """
    votes = (
        db.query(DiscussionVote)
        .filter(DiscussionVote.discussion_id == task.id)
        .order_by(DiscussionVote.round, DiscussionVote.created_at)
        .all()
    )
    return DiscussionTaskResponse(
        id=task.id,
        title=task.title,
        description=task.description,
        proposed_action=dict(task.proposed_action) if task.proposed_action else {},
        context=dict(task.context) if task.context else {},
        status=task.status,
        round=task.round,
        max_rounds=task.max_rounds,
        created_at=task.created_at,
        updated_at=task.updated_at,
        completed_at=task.completed_at,
        votes=[_vote_to_response(v) for v in votes],
    )


def _task_to_list_item(
    db: Session, task: DiscussionTask, vote_summary: Optional[VoteSummaryResponse] = None
) -> DiscussionListItemResponse:
    """将 DiscussionTask ORM 对象转为列表项响应模型。

    Args:
        db: 数据库会话（仅在 vote_summary 未提供时用于查询）
        task: 讨论任务 ORM 对象
        vote_summary: 预计算的投票摘要，提供时跳过 DB 查询避免 N+1
    """
    if vote_summary is None:
        vote_summary = _build_vote_summary(db, task.id)
    return DiscussionListItemResponse(
        id=task.id,
        title=task.title,
        status=task.status,
        round=task.round,
        max_rounds=task.max_rounds,
        created_at=task.created_at,
        vote_summary=vote_summary,
    )


def _on_background_round_done(task_id: str, fut: asyncio.Future) -> None:
    """
    后台讨论轮次完成回调，记录异常避免静默吞错误。

    [NOTE] orchestrator._safe_run_discussion_round 内部已捕获业务异常并转 failed，
    此处仅作为兜底日志，捕获 asyncio.CancelledError 与未预期异常。

    Args:
        task_id: 讨论任务 ID
        fut: 后台 task 的 Future 对象
    """
    try:
        # 调用 result() 会重新抛出 task 内的异常（如未在 _safe 包装中捕获）
        exc = fut.exception()
    except asyncio.CancelledError:
        logger.bind(
            event="discussion_background_cancelled",
            module="discussions",
            task_id=task_id,
        ).info(f"后台讨论轮次被取消: {task_id}")
        return
    if exc is not None:
        logger.bind(
            event="discussion_background_unexpected",
            module="discussions",
            task_id=task_id,
            error=str(exc),
            error_type=type(exc).__name__,
        ).error(f"后台讨论轮次未预期异常: {task_id} - {exc}")


# ── 路由端点 ──────────────────────────────────────────────────────────


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="创建讨论任务",
    description="提交待评审任务，自动触发首轮三方讨论（critic/validator/approver）。",
)
async def create_discussion(
    payload: DiscussionCreateRequest,
    current_user: User = Depends(get_current_user),
) -> Dict[str, str]:
    """
    创建讨论任务并异步触发首轮讨论。

    流程：
      1. 校验请求体（Pydantic schema 校验 title/description/proposed_action）
      2. 调用 orchestrator.create_task 写入数据库并触发首轮讨论
      3. orchestrator.create_task 内部已用 asyncio.create_task 异步触发讨论，
         不阻塞本响应；返回 201 与 discussion_id

    Returns:
        {"discussion_id": str, "status": "created"}
    """
    orchestrator = _get_orchestrator()

    # 将 Pydantic schema 转为内部 dataclass
    proposed_action = ProposedAction(
        type=payload.proposed_action.type,
        payload=dict(payload.proposed_action.payload),
    )

    try:
        discussion_id = await orchestrator.create_task(
            user_id=str(current_user.id),
            title=payload.title,
            description=payload.description,
            proposed_action=proposed_action,
            context=dict(payload.context),
            max_rounds=payload.max_rounds,
        )
    except ValueError as exc:
        # create_task 内部对 title/description/max_rounds 有基础校验，
        # Pydantic 已挡住大部分非法输入，这里兜底返回 400
        logger.bind(
            event="discussion_create_validation_error",
            module="discussions",
            user_id=str(current_user.id),
            error=str(exc),
        ).warning(f"创建讨论任务参数校验失败: {exc}")
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # [NOTE] orchestrator.create_task 内部已通过 asyncio.create_task
    # 异步触发首轮讨论（_safe_run_discussion_round），此处无需重复触发。
    # 但为满足 SubTask 3.2 "后台异步触发 orchestrator.run_discussion_round"
    # 的要求，且避免 orchestrator 内部 create_task 改为同步时丢失异步性，
    # 此处显式再注册一个后台任务作为兜底（_safe_run_discussion_round 内部幂等：
    # 若已在讨论中会抛 DiscussionStateError 并被捕获）。
    # 实际上 orchestrator.create_task 已异步触发，此处跳过避免重复触发。

    logger.bind(
        event="discussion_created",
        module="discussions",
        action="create",
        status="success",
        user_id=str(current_user.id),
        discussion_id=discussion_id,
        max_rounds=payload.max_rounds,
    ).info(f"讨论任务已创建: {discussion_id}")

    return {"discussion_id": discussion_id, "status": "created"}


@router.get(
    "",
    response_model=DiscussionListResponse,
    summary="查询讨论任务列表",
    description="分页查询当前用户的讨论任务，支持 status 过滤。",
)
async def list_discussions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    page: int = Query(default=1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页数量，最大 100"),
    status_filter: Optional[str] = Query(default=None, alias="status", description="按状态过滤"),
) -> Dict[str, Any]:
    """
    分页查询当前用户的讨论任务列表。

    仅返回当前用户创建的任务，按 created_at 倒序排列。
    每项含 vote_summary，聚合各角色最新投票。
    """
    user_id = str(current_user.id)

    # 构建基础查询
    query = db.query(DiscussionTask).filter(DiscussionTask.user_id == user_id)
    if status_filter:
        query = query.filter(DiscussionTask.status == status_filter)

    # 总数
    total = query.count()

    # 分页查询
    offset = (page - 1) * page_size
    tasks = (
        query.order_by(DiscussionTask.created_at.desc())
        .offset(offset)
        .limit(page_size)
        .all()
    )

    # 批量预计算所有任务的投票摘要，避免 N+1 查询（原 3 次查询/任务 → 2 次查询/列表）
    if tasks:
        vote_summaries = _build_vote_summaries_batch(db, [t.id for t in tasks])
        items = [_task_to_list_item(db, task, vote_summaries.get(task.id)) for task in tasks]
    else:
        items = []

    logger.bind(
        event="discussion_list",
        module="discussions",
        action="list",
        user_id=user_id,
        page=page,
        page_size=page_size,
        total=total,
        status_filter=status_filter,
    ).debug(f"查询讨论列表: 返回 {len(items)} 条")

    return DiscussionListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/{discussion_id}",
    response_model=DiscussionTaskResponse,
    summary="查询讨论任务详情",
    description="返回完整任务详情，含所有轮次讨论历史与投票记录。",
)
async def get_discussion(
    discussion_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    查询单个讨论任务详情。

    校验任务归属：仅任务创建者可查看，避免越权访问。
    返回所有轮次的投票记录，按 round 与 created_at 正序排列。
    """
    task = db.get(DiscussionTask, discussion_id)
    if task is None:
        raise HTTPException(status_code=404, detail="讨论任务不存在")

    if task.user_id != str(current_user.id):
        logger.bind(
            event="discussion_access_denied",
            module="discussions",
            user_id=str(current_user.id),
            discussion_id=discussion_id,
            owner_id=task.user_id,
        ).warning(f"用户越权访问讨论任务: {discussion_id}")
        raise HTTPException(status_code=403, detail="无权访问该讨论任务")

    return _task_to_detail_response(db, task)


@router.post(
    "/{discussion_id}/revise",
    response_model=DiscussionTaskResponse,
    summary="提交修订",
    description="提交修订后的提议动作，触发新一轮讨论。",
)
async def revise_discussion(
    discussion_id: str,
    payload: DiscussionReviseRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    提交修订后的提议动作，触发新一轮讨论。

    校验规则：
      1. 任务必须存在且属于当前用户
      2. 当前状态为 discussing 或 pending_approval，否则返回 409 Conflict
      3. round < max_rounds，否则返回 422 Unprocessable Entity

    orchestrator.revise_action 内部会校验状态与轮次，并异步触发新一轮讨论。
    """
    task = db.get(DiscussionTask, discussion_id)
    if task is None:
        raise HTTPException(status_code=404, detail="讨论任务不存在")

    if task.user_id != str(current_user.id):
        raise HTTPException(status_code=403, detail="无权修订该讨论任务")

    # 预校验状态与轮次，提前返回明确的 HTTP 状态码
    if task.status not in ("discussing", "pending_approval"):
        raise HTTPException(
            status_code=409,
            detail=f"当前状态 {task.status} 不允许修订，仅 discussing/pending_approval 可修订",
        )
    if task.round >= task.max_rounds:
        raise HTTPException(
            status_code=422,
            detail=f"已超过最大讨论轮次 {task.max_rounds}，无法继续修订",
        )

    orchestrator = _get_orchestrator()
    new_proposed_action = ProposedAction(
        type=payload.proposed_action.type,
        payload=dict(payload.proposed_action.payload),
    )

    try:
        await orchestrator.revise_action(discussion_id, new_proposed_action)
    except DiscussionStateError as exc:
        # 状态校验失败（可能是并发修订导致状态已变化）
        logger.bind(
            event="discussion_revise_state_error",
            module="discussions",
            discussion_id=discussion_id,
            error=str(exc),
        ).warning(f"修订状态校验失败: {exc}")
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except DiscussionRoundLimitError as exc:
        logger.bind(
            event="discussion_revise_round_limit",
            module="discussions",
            discussion_id=discussion_id,
            error=str(exc),
        ).warning(f"修订超过轮次上限: {exc}")
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except DiscussionExecutionError as exc:
        logger.bind(
            event="discussion_revise_execution_error",
            module="discussions",
            discussion_id=discussion_id,
            error=str(exc),
        ).error(f"修订执行失败: {exc}")
        raise HTTPException(status_code=500, detail="修订执行失败，请稍后重试") from exc

    logger.bind(
        event="discussion_revised",
        module="discussions",
        action="revise",
        status="success",
        user_id=str(current_user.id),
        discussion_id=discussion_id,
        new_round=task.round + 1,
        reason_length=len(payload.reason),
    ).info(f"讨论任务已修订: {discussion_id}")

    # 重新加载任务以获取最新状态
    db.refresh(task)
    return _task_to_detail_response(db, task)


@router.get(
    "/{discussion_id}/stream",
    summary="SSE 订阅讨论流",
    description="实时推送 discussion_message/vote_cast/status_changed 三类事件，5 分钟超时自动关闭。",
)
async def stream_discussion(
    discussion_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    SSE 端点：实时推送指定讨论任务的事件流。

    [SECURITY] 鉴权使用 Cookie（ACCESS_TOKEN_COOKIE_NAME），不通过 URL query 传 token，
    避免令牌被代理日志/浏览器历史记录泄露。

    推送事件类型：
      - discussion_message：角色发言片段（thinking/spoken 阶段）
      - vote_cast：投票完成
      - status_changed：状态转换
      - heartbeat：心跳保活（30s 无事件时发送）
      - discussion_error：错误事件

    连接超时：5 分钟（300 秒）自动关闭，由 orchestrator.stream_discussion_events 控制。
    """
    # Cookie 鉴权
    user = _resolve_sse_user(request, db)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Cookie 鉴权失败，请提供有效的 access_token Cookie",
        )

    # 校验任务存在且属于当前用户
    task = db.get(DiscussionTask, discussion_id)
    if task is None:
        raise HTTPException(status_code=404, detail="讨论任务不存在")
    if task.user_id != str(user.id):
        raise HTTPException(status_code=403, detail="无权订阅该讨论任务")

    user_id = str(user.id)
    logger.bind(
        event="discussion_stream_connected",
        module="discussions",
        action="stream",
        status="connected",
        user_id=user_id,
        discussion_id=discussion_id,
    ).info(f"SSE 连接已建立: {discussion_id}")

    orchestrator = _get_orchestrator()

    async def event_generator() -> AsyncGenerator[str, None]:
        """
        SSE 事件生成器。

        订阅 orchestrator.stream_discussion_events 异步生成器，
        将事件 dict 序列化为 SSE 格式（event: + data: + 空行分隔）。
        """
        try:
            async for event in orchestrator.stream_discussion_events(
                discussion_id, timeout=300.0
            ):
                event_type = event.get("type", "message")
                event_data = event.get("data", {})
                # 序列化时禁用 ASCII 转义，确保中文可读
                data_json = json.dumps(event_data, ensure_ascii=False, default=str)
                yield f"event: {event_type}\ndata: {data_json}\n\n"
        except asyncio.CancelledError:
            # 客户端断开连接
            logger.bind(
                event="discussion_stream_cancelled",
                module="discussions",
                discussion_id=discussion_id,
                user_id=user_id,
            ).info(f"SSE 连接被客户端取消: {discussion_id}")
        except Exception as exc:
            # 兜底捕获，避免生成器异常导致连接挂起
            logger.bind(
                event="discussion_stream_error",
                module="discussions",
                discussion_id=discussion_id,
                user_id=user_id,
                error=str(exc),
                error_type=type(exc).__name__,
            ).error(f"SSE 流异常: {discussion_id} - {exc}")
            # 推送错误事件后关闭连接
            error_payload = json.dumps(
                {"task_id": discussion_id, "error": str(exc), "error_type": type(exc).__name__},
                ensure_ascii=False,
            )
            yield f"event: discussion_error\ndata: {error_payload}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.post(
    "/{discussion_id}/force-execute",
    summary="紧急旁路执行",
    description="跳过未完成投票直接进入执行状态，仅 admin 可调用，记录审计日志。",
)
async def force_execute_discussion(
    discussion_id: str,
    payload: DiscussionForceExecuteRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    紧急旁路执行：跳过未完成投票，直接触发 execute_approved_action。

    权限要求：admin 角色（user.role == "admin" 或 user.id 在 ADMIN_USER_IDS 环境变量中）。
    审计要求：记录旁路理由、操作者身份、目标任务 ID 到审计日志。

    流程：
      1. 校验 admin 权限
      2. 校验任务存在
      3. 写入审计日志（force_execute_bypass）
      4. 调用 orchestrator.execute_approved_action 跳过投票直接执行
      5. 后台异步触发执行，返回执行中状态
    """
    # 1. 校验 admin 权限
    if not _is_admin_user(current_user):
        logger.bind(
            event="force_execute_permission_denied",
            module="discussions",
            user_id=str(current_user.id),
            discussion_id=discussion_id,
            user_role=getattr(current_user, "role", "unknown"),
        ).warning(f"非 admin 用户尝试旁路执行: {discussion_id}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="仅 admin 用户可调用紧急旁路执行",
        )

    # 2. 校验任务存在
    task = db.get(DiscussionTask, discussion_id)
    if task is None:
        raise HTTPException(status_code=404, detail="讨论任务不存在")

    user_id = str(current_user.id)

    # 3. 写入审计日志
    # [NOTE] AuditLogger 需要 db session，复用当前请求级 session
    # 审计不可用时 fail-closed：拒绝旁路执行，禁止绕过审计放行高危操作
    try:
        from security.audit import AuditLogger

        audit_logger = AuditLogger(db)
        await audit_logger.log(
            user_id=user_id,
            action="force_execute_bypass",
            resource=f"discussion:{discussion_id}",
            result="success",
            details={
                "reason": payload.reason,
                "task_title": task.title,
                "task_status_before": task.status,
                "task_round": task.round,
            },
            ip_address=None,
        )
    except Exception as exc:
        logger.bind(
            event="force_execute_audit_failed",
            module="discussions",
            discussion_id=discussion_id,
            user_id=user_id,
            error=str(exc),
            error_type=type(exc).__name__,
        ).error(f"审计日志写入失败，旁路执行已拒绝: {exc}")
        raise HTTPException(
            status_code=500,
            detail="审计日志写入失败，旁路执行已拒绝",
        ) from exc

    # 4. 调用 orchestrator 跳过投票直接执行
    orchestrator = _get_orchestrator()

    # 先将状态强制转为 approved（若已是终态则跳过）
    # [NOTE] orchestrator.execute_approved_action 要求状态为 approved 才能转为 executing，
    # 此处先调用 _transition_task_status 内部方法绕过投票校验。
    # 为避免直接访问私有方法，改为直接更新数据库状态。
    if task.status not in ("approved", "executing", "completed"):
        try:
            with SessionLocal() as admin_db:
                db_task = admin_db.get(DiscussionTask, discussion_id)
                if db_task is not None:
                    db_task.status = "approved"
                    db_task.updated_at = datetime.utcnow()
                    admin_db.commit()
        except Exception as exc:
            logger.bind(
                event="force_execute_status_update_failed",
                module="discussions",
                discussion_id=discussion_id,
                error=str(exc),
            ).error(f"旁路执行状态更新失败: {exc}")
            raise HTTPException(
                status_code=500,
                detail="旁路执行状态更新失败，请稍后重试",
            ) from exc

    # 5. 后台异步触发执行，避免阻塞响应
    # [NOTE] 使用 asyncio.create_task 异步触发，注册回调处理异常避免静默吞错误
    background_task = asyncio.create_task(
        orchestrator.execute_approved_action(discussion_id)
    )
    background_task.add_done_callback(
        lambda fut: _on_background_round_done(discussion_id, fut)
    )

    logger.bind(
        event="force_execute_triggered",
        module="discussions",
        action="force_execute",
        status="triggered",
        user_id=user_id,
        discussion_id=discussion_id,
        reason=payload.reason,
    ).info(f"紧急旁路执行已触发: {discussion_id}")

    return {
        "discussion_id": discussion_id,
        "status": "executing",
        "bypassed_by": user_id,
        "reason": payload.reason,
        "message": "旁路执行已异步触发，请通过 SSE 或详情接口查看执行结果",
    }
