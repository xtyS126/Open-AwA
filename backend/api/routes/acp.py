# -*- coding: utf-8 -*-
"""
ACP (Agent Client Protocol) HTTP API 路由。

为前端提供 ACP Agent 会话管理与流式 prompt 接口，所有端点强制鉴权。

安全策略：
1. 所有 HTTP 端点强制 Depends(get_current_user)
2. cwd 参数必须位于允许的工作区根目录内（路径越权防护）
3. agent 标识必须在 discover_agents() 列表中且 enabled=True
4. SSE 流式端点用 asyncio.to_thread 包裹同步探测，避免阻塞事件循环
5. 客户端断开时调用 ACPService.cancel_turn 取消未完成的 prompt

会话与 ACPService 桥接：
- 用 chat_id = f"{user_id}:{session_id}" 作为 ACPService 的 chat_id
- 通过 get_acp_service(agent) 获取对应 Agent 的 service 实例
- acp SDK 未安装时 run_turn 抛 ACPConfigurationError，SSE 流中捕获并推送 error 事件
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from loguru import logger
from pydantic import BaseModel, Field

from acp_host import get_acp_service
from acp_host.core import ACPConfigurationError, ACPSessionError
from acp_host.agents import discover_agents, is_agent_available
from api.dependencies import get_current_user
from db.models import User


router = APIRouter(prefix="/api/acp", tags=["acp"])


# 允许作为 cwd 的根目录白名单（与 terminal.py 保持一致：当前工作目录及其下级子目录）
_ALLOWED_WORKSPACE_ROOTS: List[str] = [os.path.abspath(os.getcwd())]


# 会话元数据：以 (user_id, session_id) 为键
# 元数据结构：{"agent": str, "cwd": str, "created_at": str}
_acp_user_sessions: Dict[Tuple[str, str], Dict[str, Any]] = {}

# P0-14: 模块级字典容量上限，防止单用户创建海量会话触发 OOM
# 单用户最大并发会话数
_MAX_ACP_SESSIONS_PER_USER = 10
# 全局最大会话总数
_MAX_TOTAL_ACP_SESSIONS = 1000


def _evict_oldest_acp_session() -> None:
    """淘汰全局最旧的 ACP 会话（按 created_at 时间戳）。

    在全局会话数达到 _MAX_TOTAL_ACP_SESSIONS 时调用。
    """
    if not _acp_user_sessions:
        return
    oldest_key = min(
        _acp_user_sessions.keys(),
        key=lambda k: _acp_user_sessions[k].get("created_at", ""),
    )
    evicted_meta = _acp_user_sessions.pop(oldest_key, None)
    if evicted_meta is not None:
        logger.warning(
            f"全局 ACP 会话数已达上限 {_MAX_TOTAL_ACP_SESSIONS}，"
            f"已淘汰最旧会话: user_id={oldest_key[0]}, session_id={oldest_key[1]}"
        )


def _add_acp_session(user_id: str, session_id: str, meta: Dict[str, Any]) -> None:
    """添加 ACP 会话到全局字典，强制 per-user 与全局容量上限。

    超出上限时按 created_at 时间戳淘汰最旧的会话，防止单用户创建海量会话触发 OOM。

    Args:
        user_id: 用户 ID。
        session_id: 会话 ID。
        meta: 会话元数据（必须含 created_at 字段用于淘汰排序）。
    """
    # 全局容量上限：超出时淘汰最旧的会话
    if len(_acp_user_sessions) >= _MAX_TOTAL_ACP_SESSIONS:
        _evict_oldest_acp_session()

    # per-user 容量上限：超出时淘汰该用户最旧的会话
    user_sessions = [
        (sid, m) for (uid, sid), m in _acp_user_sessions.items() if uid == user_id
    ]
    if len(user_sessions) >= _MAX_ACP_SESSIONS_PER_USER:
        # 按 created_at 排序，淘汰最旧的
        user_sessions.sort(key=lambda x: x[1].get("created_at", ""))
        oldest_sid = user_sessions[0][0]
        _acp_user_sessions.pop((user_id, oldest_sid), None)
        logger.warning(
            f"用户 {user_id} 的 ACP 会话数已达上限 {_MAX_ACP_SESSIONS_PER_USER}，"
            f"已淘汰最旧会话: {oldest_sid}"
        )

    _acp_user_sessions[(user_id, session_id)] = meta


def _validate_cwd(cwd: Optional[str]) -> str:
    """校验 cwd 路径必须位于允许的工作区根目录内。

    复制自 terminal.py 的 _validate_cwd 实现，避免跨路由模块导入副作用。

    Args:
        cwd: 用户传入的工作目录参数。

    Returns:
        校验通过后的绝对路径字符串。

    Raises:
        HTTPException: 400 当 cwd 为空字符串、路径无效或越权时。
    """
    if not cwd:
        return os.getcwd()

    cwd_str = cwd.strip()
    if not cwd_str:
        raise HTTPException(status_code=400, detail="cwd 不能为空字符串")

    try:
        cwd_path = Path(cwd_str).resolve()
    except (OSError, ValueError) as exc:
        logger.warning(f"cwd 路径解析失败: {cwd_str}, 错误: {exc}")
        raise HTTPException(status_code=400, detail="cwd 路径无效")

    for root in _ALLOWED_WORKSPACE_ROOTS:
        try:
            cwd_path.relative_to(Path(root).resolve())
            return str(cwd_path)
        except ValueError:
            continue

    logger.warning(f"cwd 路径越权: {cwd_str} 不在允许的工作区内")
    raise HTTPException(status_code=400, detail="cwd 路径不在允许的工作区内")


# ==================== 请求/响应 Schema ====================


class AgentInfo(BaseModel):
    """单个 ACP Agent 的展示信息。"""

    id: str = Field(..., description="Agent 唯一标识")
    name: str = Field(..., description="Agent 展示名称")
    command: str = Field(..., description="启动 Agent 子进程的命令")
    enabled: bool = Field(..., description="配置中是否启用")
    available: bool = Field(..., description="本地是否安装了对应 CLI 命令")


class AgentListResponse(BaseModel):
    """GET /agents 响应：返回所有已注册 agent 列表。"""

    agents: List[AgentInfo] = Field(default_factory=list)
    count: int = Field(..., description="Agent 总数")


class SessionCreateRequest(BaseModel):
    """POST /sessions 请求体：创建 ACP 会话。"""

    agent: str = Field(..., description="Agent 标识")
    cwd: str = Field(..., description="工作目录")


class SessionCreateResponse(BaseModel):
    """POST /sessions 响应。"""

    session_id: str = Field(..., description="会话 ID")
    config_options: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="可选的会话配置项，暂返回空列表",
    )


class SessionInfo(BaseModel):
    """单个会话的展示信息。"""

    session_id: str = Field(..., description="会话 ID")
    agent: str = Field(..., description="Agent 标识")
    cwd: str = Field(..., description="工作目录")
    created_at: str = Field(..., description="创建时间（ISO 格式）")


class SessionListResponse(BaseModel):
    """GET /sessions 响应。"""

    sessions: List[SessionInfo] = Field(default_factory=list)
    count: int = Field(..., description="当前用户的活动会话数")


class PromptRequest(BaseModel):
    """POST /sessions/{session_id}/prompt 请求体。"""

    prompt: str = Field(..., min_length=1, max_length=32000, description="用户 prompt 内容")
    restart: bool = Field(default=False, description="是否重启会话")


class PermissionResponseRequest(BaseModel):
    """POST /sessions/{session_id}/permission 请求体。"""

    option_id: str = Field(..., description="用户选择的审批选项 ID")


class PermissionResponseResponse(BaseModel):
    """POST /sessions/{session_id}/permission 响应。"""

    status: str = Field(..., description="权限恢复结果状态")


class CancelResponse(BaseModel):
    """POST /sessions/{session_id}/cancel 响应。"""

    cancelled: bool = Field(..., description="是否已取消当前 prompt")


class SessionCloseResponse(BaseModel):
    """DELETE /sessions/{session_id} 响应。"""

    closed: bool = Field(..., description="是否已关闭并移除会话")


# ==================== 端点实现 ====================


@router.get("/agents", response_model=AgentListResponse)
async def list_agents(
    current_user: User = Depends(get_current_user),
) -> AgentListResponse:
    """返回所有已注册 ACP Agent 列表。

    available 字段通过 is_agent_available(agent_id) 探测本地 CLI 是否安装。
    探测是同步阻塞操作，通过 asyncio.to_thread 包裹避免阻塞事件循环。
    """
    del current_user  # 仅用于鉴权，不参与业务逻辑
    agents = discover_agents()
    agent_infos: List[AgentInfo] = []
    for agent_id, config in agents.items():
        # 同步探测放到线程池中执行
        available = await asyncio.to_thread(is_agent_available, agent_id, agents)
        agent_infos.append(
            AgentInfo(
                id=config.agent_id,
                name=config.name,
                command=config.command,
                enabled=config.enabled,
                available=available,
            )
        )
    return AgentListResponse(agents=agent_infos, count=len(agent_infos))


@router.post("/sessions", response_model=SessionCreateResponse)
async def create_session(
    request: SessionCreateRequest,
    current_user: User = Depends(get_current_user),
) -> SessionCreateResponse:
    """创建 ACP 会话。

    流程：
    1. 校验 agent 在 discover_agents() 中且 enabled=True，否则 404/400
    2. 校验 cwd 位于允许的工作区根目录内
    3. 生成 session_id（uuid4），存入 _acp_user_sessions 字典
    4. 返回 session_id 与空 config_options

    注意：实际 ACP 子进程会话由 ACPService.run_turn 在首次 prompt 时创建。
    """
    agents = discover_agents()
    agent_config = agents.get(request.agent)
    if agent_config is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"未知的 ACP agent: {request.agent}",
        )
    if not agent_config.enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"ACP agent '{request.agent}' 已禁用",
        )

    safe_cwd = _validate_cwd(request.cwd)

    session_id = str(uuid.uuid4())
    # 用 chat_id = f"{user_id}:{session_id}" 作为 ACPService 的 chat_id
    # P0-14: 通过 _add_acp_session 强制容量上限，防止单用户创建海量会话触发 OOM
    _add_acp_session(
        user_id=str(current_user.id),
        session_id=session_id,
        meta={
            "agent": request.agent,
            "cwd": safe_cwd,
            "created_at": _now_iso(),
        },
    )

    logger.bind(
        event="acp_session_created",
        module="acp",
        session_id=session_id,
        user_id=current_user.id,
        agent=request.agent,
    ).info(f"ACP 会话已创建: agent={request.agent}, session_id={session_id}")

    return SessionCreateResponse(session_id=session_id, config_options=[])


@router.get("/sessions", response_model=SessionListResponse)
async def list_sessions(
    current_user: User = Depends(get_current_user),
) -> SessionListResponse:
    """列出当前用户的活动 ACP 会话。"""
    user_id = str(current_user.id)
    sessions: List[SessionInfo] = []
    for (uid, sid), meta in _acp_user_sessions.items():
        if uid != user_id:
            continue
        sessions.append(
            SessionInfo(
                session_id=sid,
                agent=meta["agent"],
                cwd=meta["cwd"],
                created_at=meta["created_at"],
            )
        )
    return SessionListResponse(sessions=sessions, count=len(sessions))


@router.post("/sessions/{session_id}/prompt")
async def prompt_session(
    session_id: str,
    request: PromptRequest,
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """对指定 ACP 会话发起一轮 prompt（SSE 流式响应）。

    Content-Type: text/event-stream

    SSE 事件类型：
    - text: 文本块输出
    - tool: 工具调用相关事件
    - status: 状态变更
    - permission: 权限审批请求挂起
    - usage: 用量统计
    - result: 一轮 prompt 结束
    - error: 错误信息（SDK 缺失等）

    客户端断开时调用 ACPService.cancel_turn 取消未完成的 prompt。
    """
    user_id = str(current_user.id)
    meta = _acp_user_sessions.get((user_id, session_id))
    if meta is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"ACP 会话不存在: {session_id}",
        )

    agent = meta["agent"]
    cwd = meta["cwd"]
    chat_id = f"{user_id}:{session_id}"
    service = get_acp_service(agent)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"ACP service 未初始化: agent={agent}",
        )

    prompt_blocks = [{"type": "text", "text": request.prompt}]

    async def event_generator():
        """SSE 事件生成器：把 ACPService 事件转为 SSE 帧推送。"""
        # 队列承载所有要推送的事件，避免 await service.run_turn 阻塞流
        queue: asyncio.Queue[Optional[str]] = asyncio.Queue()
        # 标记 run_turn 是否已完成
        run_turn_task: Optional[asyncio.Task[Any]] = None
        cancel_event = asyncio.Event()

        async def on_message(payload: Dict[str, Any], is_last: bool) -> None:
            """ACPService 事件回调：把事件转为 SSE 帧后放入队列。"""
            event_type = _resolve_event_type(payload)
            sse_frame = _format_sse(event_type, payload)
            await queue.put(sse_frame)

        async def _run_turn_wrapper() -> None:
            """包裹 service.run_turn，捕获异常并推送 error 事件。"""
            try:
                result = await service.run_turn(
                    chat_id=chat_id,
                    agent=agent,
                    prompt_blocks=prompt_blocks,
                    cwd=cwd,
                    on_message=on_message,
                    restart=request.restart,
                )
                # 推送最终结果事件
                status_value = result.get("status", "completed")
                if status_value == "permission_required":
                    suspended = result.get("suspended_permission")
                    perm_payload: Dict[str, Any] = {}
                    if suspended is not None:
                        perm_payload = _suspended_permission_to_dict(suspended)
                    await queue.put(_format_sse("permission", perm_payload))
                await queue.put(_format_sse("result", {"status": status_value}))
            except ACPConfigurationError as exc:
                logger.bind(
                    event="acp_prompt_config_error",
                    module="acp",
                    session_id=session_id,
                    agent=agent,
                    error_message=str(exc),
                ).warning(f"ACP 配置错误: {exc}")
                await queue.put(
                    _format_sse("error", {"message": str(exc)})
                )
            except ACPSessionError as exc:
                logger.bind(
                    event="acp_prompt_session_error",
                    module="acp",
                    session_id=session_id,
                    agent=agent,
                    error_message=str(exc),
                ).warning(f"ACP 会话错误: {exc}")
                await queue.put(
                    _format_sse("error", {"message": str(exc)})
                )
            except Exception as exc:
                logger.bind(
                    event="acp_prompt_error",
                    module="acp",
                    session_id=session_id,
                    agent=agent,
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                ).error(f"ACP prompt 异常: {exc}")
                await queue.put(
                    _format_sse("error", {"message": f"内部错误: {exc}"})
                )
            finally:
                # 哨兵：通知生成器退出
                await queue.put(None)

        run_turn_task = asyncio.create_task(_run_turn_wrapper())

        try:
            while True:
                # 客户端断开时 asyncio.CancelledError 由 try/except 捕获
                if cancel_event.is_set():
                    break
                try:
                    frame = await asyncio.wait_for(queue.get(), timeout=30.0)
                except asyncio.TimeoutError:
                    # 心跳保持连接活跃
                    yield ": heartbeat\n\n"
                    continue
                if frame is None:
                    break
                yield frame
        except asyncio.CancelledError:
            # 客户端断开连接，取消未完成的 prompt
            logger.bind(
                event="acp_prompt_cancelled",
                module="acp",
                session_id=session_id,
                agent=agent,
            ).info(f"客户端断开，取消 ACP prompt: {session_id}")
            cancel_event.set()
            try:
                await service.cancel_turn(chat_id=chat_id, agent=agent)
            except Exception as exc:
                logger.warning(f"取消 ACP prompt 失败: {exc}")
            raise
        finally:
            if run_turn_task is not None and not run_turn_task.done():
                run_turn_task.cancel()
                try:
                    await run_turn_task
                except (asyncio.CancelledError, Exception):
                    pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.post("/sessions/{session_id}/permission", response_model=PermissionResponseResponse)
async def respond_permission(
    session_id: str,
    request: PermissionResponseRequest,
    current_user: User = Depends(get_current_user),
) -> PermissionResponseResponse:
    """响应当前挂起的权限审批请求。

    通过 session_id 找到会话，再通过 ACPService.resume_permission 恢复执行。
    """
    user_id = str(current_user.id)
    meta = _acp_user_sessions.get((user_id, session_id))
    if meta is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"ACP 会话不存在: {session_id}",
        )

    agent = meta["agent"]
    chat_id = f"{user_id}:{session_id}"
    service = get_acp_service(agent)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"ACP service 未初始化: agent={agent}",
        )

    # 通过 get_session 拿到 _Conversation 实例，从中取 acp_session_id
    conversation = await service.get_session(chat_id=chat_id, agent=agent)
    if conversation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="ACP 会话未建立，请先发起一次 prompt",
        )
    # 校验存在挂起的权限请求
    pending = await service.get_pending_permission(chat_id=chat_id, agent=agent)
    if pending is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="当前没有挂起的权限请求",
        )
    # _Conversation 含 acp_session_id 字段
    acp_session_id = getattr(conversation, "acp_session_id", None)
    if not isinstance(acp_session_id, str) or not acp_session_id:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="无法获取 ACP 会话 ID",
        )

    async def _noop_on_message(payload: Dict[str, Any], is_last: bool) -> None:
        """resume_permission 需要事件回调，此端点为非流式，丢弃事件即可。"""
        del payload, is_last

    try:
        result = await service.resume_permission(
            acp_session_id=acp_session_id,
            option_id=request.option_id,
            on_message=_noop_on_message,
        )
    except ACPConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )
    except ACPSessionError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    status_value = str(result.get("status", "completed"))
    return PermissionResponseResponse(status=status_value)


@router.post("/sessions/{session_id}/cancel", response_model=CancelResponse)
async def cancel_session_turn(
    session_id: str,
    current_user: User = Depends(get_current_user),
) -> CancelResponse:
    """取消指定会话当前正在进行的 prompt 任务。"""
    user_id = str(current_user.id)
    meta = _acp_user_sessions.get((user_id, session_id))
    if meta is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"ACP 会话不存在: {session_id}",
        )

    agent = meta["agent"]
    chat_id = f"{user_id}:{session_id}"
    service = get_acp_service(agent)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"ACP service 未初始化: agent={agent}",
        )

    try:
        cancelled = await service.cancel_turn(chat_id=chat_id, agent=agent)
    except Exception as exc:
        logger.warning(f"取消 ACP prompt 异常: {exc}")
        cancelled = False
    return CancelResponse(cancelled=cancelled)


@router.delete("/sessions/{session_id}", response_model=SessionCloseResponse)
async def close_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
) -> SessionCloseResponse:
    """关闭并移除指定 ACP 会话。

    调用 ACPService.close_chat_session 清理子进程资源，并从 _acp_user_sessions 移除元数据。
    """
    user_id = str(current_user.id)
    meta = _acp_user_sessions.pop((user_id, session_id), None)
    if meta is None:
        # 不存在视为已关闭
        return SessionCloseResponse(closed=True)

    agent = meta["agent"]
    chat_id = f"{user_id}:{session_id}"
    service = get_acp_service(agent)
    if service is not None:
        try:
            await service.close_chat_session(chat_id=chat_id, agent=agent)
        except Exception as exc:
            logger.warning(f"关闭 ACP 会话失败: {exc}")

    logger.bind(
        event="acp_session_closed",
        module="acp",
        session_id=session_id,
        user_id=current_user.id,
        agent=agent,
    ).info(f"ACP 会话已关闭: {session_id}")

    return SessionCloseResponse(closed=True)


# ==================== 工具函数 ====================


def _now_iso() -> str:
    """返回当前时间的 ISO 格式字符串（含时区）。"""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _format_sse(event_type: str, payload: Dict[str, Any]) -> str:
    """构造 SSE 帧：event: <type>\\ndata: <json>\\n\\n。

    Args:
        event_type: 事件类型（text/tool/status/permission/usage/result/error）。
        payload: 事件数据。

    Returns:
        合法的 SSE 帧字符串。
    """
    return f"event: {event_type}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _resolve_event_type(payload: Dict[str, Any]) -> str:
    """根据 ACPService 事件 payload 推断 SSE 事件类型。

    Args:
        payload: ACPService 事件回调收到的字典。

    Returns:
        SSE 事件类型字符串。
    """
    # payload 中可能包含 type 字段（如 text/tool_call/tool_result/usage/status）
    payload_type = payload.get("type") or payload.get("event")
    if isinstance(payload_type, str):
        normalized = payload_type.lower()
        if normalized in ("text", "tool", "tool_call", "tool_result", "status", "permission", "usage", "result", "error"):
            if normalized in ("tool_call", "tool_result"):
                return "tool"
            return normalized
    # 默认归为 status 事件
    return "status"


def _suspended_permission_to_dict(suspended: Any) -> Dict[str, Any]:
    """把 SuspendedPermission 实例转为可序列化的字典。

    Args:
        suspended: acp_host.core.SuspendedPermission 实例。

    Returns:
        包含 agent/tool_name/tool_kind/target/action/summary/command/paths/options 的字典。
    """
    if suspended is None:
        return {}
    if isinstance(suspended, dict):
        return suspended
    # dataclass 实例
    fields = (
        "agent",
        "tool_name",
        "tool_kind",
        "target",
        "action",
        "summary",
        "command",
        "paths",
        "options",
        "requires_user_confirmation",
    )
    result: Dict[str, Any] = {}
    for field_name in fields:
        value = getattr(suspended, field_name, None)
        if value is None:
            continue
        # options 是 list[dict]，paths 是 list[str]，直接保留
        result[field_name] = value
    return result


