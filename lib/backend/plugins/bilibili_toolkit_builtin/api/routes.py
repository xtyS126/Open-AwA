"""bilibili-toolkit-builtin 内置插件 REST API 路由。

阶段 15 实现：暴露订阅管理、视频列表、下载触发、任务查询、配置读写
共 8 个端点，前缀 ``/plugins/bilibili-toolkit-builtin``，由 ``main.py``
挂载到 ``/api/plugins/bilibili-toolkit-builtin``。

设计要点：
- 所有端点均通过 ``Depends(get_current_user)`` 鉴权，未认证返回 401
- 数据库会话通过 ``Depends(get_db)`` 注入，与 Open-AwA 主业务一致
- 触发下载通过 ``asyncio.create_task`` 异步执行，路由立即返回 ``task_id``
  不阻塞 HTTP 响应；后台任务执行 ``download_subscription`` 并把
  :class:`WorkflowResult` 持久化为 ``BilibiliToolkitDownloadTask`` 行
- 配置读写复用 :class:`VersionedConfig` 全局单例，支持热更新
- 错误处理使用具体异常类型（``ValueError`` / ``RuntimeError`` / ``KeyError``），
  禁止 ``try/except/pass``，关键路径异常向上传播
"""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.dependencies import get_current_user, get_db
from db.models import User
from db.models.bilibili_toolkit import (
    BilibiliToolkitDownloadTask,
    BilibiliToolkitSubscription,
    BilibiliToolkitVideo,
)
from plugins.bilibili_toolkit_builtin.bilibili.client import BilibiliClient
from plugins.bilibili_toolkit_builtin.bilibili.credential import Credential
from plugins.bilibili_toolkit_builtin.config import (
    VersionedConfig,
    get_config_manager,
)
from plugins.bilibili_toolkit_builtin.status import SubTask, SubTaskState, get_subtask_status
from plugins.bilibili_toolkit_builtin.workflow.orchestrator import (
    SUBSCRIPTION_TYPE_FAVORITE,
    SUBSCRIPTION_TYPE_SEASON,
    SUBSCRIPTION_TYPE_SERIES,
    SUBSCRIPTION_TYPE_SUBMISSION,
    SUBSCRIPTION_TYPE_WATCHLATER,
    download_subscription,
)
from plugins.bilibili_toolkit_builtin.workflow.pipeline import WorkflowResult

# 支持的订阅类型集合（用于 POST /subscriptions 校验）
_SUPPORTED_SUBSCRIPTION_TYPES: frozenset[str] = frozenset(
    {
        SUBSCRIPTION_TYPE_FAVORITE,
        SUBSCRIPTION_TYPE_SEASON,
        SUBSCRIPTION_TYPE_SERIES,
        SUBSCRIPTION_TYPE_SUBMISSION,
        SUBSCRIPTION_TYPE_WATCHLATER,
    }
)

# 子任务类型枚举到字符串的映射，用于持久化 BilibiliToolkitDownloadTask.subtask
_SUBTASK_NAME_MAP: Dict[SubTask, str] = {
    SubTask.Cover: "cover",
    SubTask.Video: "video",
    SubTask.Nfo: "nfo",
    SubTask.Danmaku: "danmaku",
    SubTask.Subtitle: "subtitle",
}

# 子任务状态枚举到字符串的映射，用于持久化 BilibiliToolkitDownloadTask.status
_SUBTASK_STATE_NAME_MAP: Dict[SubTaskState, str] = {
    SubTaskState.Skipped: "skipped",
    SubTaskState.Succeeded: "succeeded",
    SubTaskState.Ignored: "ignored",
    SubTaskState.Failed: "failed",
}

# 后台触发下载任务记录表（task_id -> subscription_id），用于追踪触发请求
# 不持久化到 DB，仅作为内存索引，进程重启后丢失（与 bili-sync 设计一致）
_running_tasks: Dict[str, int] = {}


router = APIRouter(
    prefix="/plugins/bilibili-toolkit-builtin",
    tags=["BilibiliToolkitBuiltin"],
)


# ---------------------------------------------------------------------------
# Pydantic 请求/响应模型
# ---------------------------------------------------------------------------


class SubscriptionCreateRequest(BaseModel):
    """添加订阅请求体。

    Attributes:
        type: 订阅类型（favorite / season / series / submission / watchlater）。
        source_id: 订阅源 ID（语义随 type 变化）。
        name: 订阅名称（用户可读）。
        path: 下载根路径。
        filter_option: FilterOption 字典，可选，缺省时使用全局配置。
        enabled: 是否启用，可选，默认 True。
    """

    type: str = Field(..., description="订阅类型")
    source_id: int = Field(..., description="订阅源 ID")
    name: str = Field(..., max_length=256, description="订阅名称")
    path: str = Field(..., max_length=1024, description="下载根路径")
    filter_option: Optional[Dict[str, Any]] = Field(
        default=None, description="FilterOption 字典，可选"
    )
    enabled: bool = Field(default=True, description="是否启用")


class SubscriptionResponse(BaseModel):
    """订阅响应模型。"""

    id: int
    type: str
    source_id: int
    name: str
    path: str
    enabled: bool
    latest_row_at: Optional[int] = None
    created_at: Any  # datetime 序列化时由 FastAPI 处理


class VideoResponse(BaseModel):
    """视频响应模型。"""

    id: int
    bvid: str
    title: str
    cover: Optional[str] = None
    upper_name: str
    pages_count: int
    download_status: int
    created_at: Any


class TaskResponse(BaseModel):
    """下载任务响应模型。"""

    id: int
    video_id: int
    page_id: Optional[int] = None
    subtask: str
    status: str
    retry_count: int
    error: Optional[str] = None
    created_at: Any


class TriggerResponse(BaseModel):
    """触发下载响应模型。"""

    task_id: str
    message: str


class ConfigUpdateRequest(BaseModel):
    """配置更新请求体。

    Attributes:
        config: 新的配置字典，整体替换 VersionedConfig 中的配置。
    """

    config: Dict[str, Any] = Field(..., description="新的配置字典")


# ---------------------------------------------------------------------------
# 订阅管理路由
# ---------------------------------------------------------------------------


@router.get("/subscriptions", response_model=List[SubscriptionResponse])
def list_subscriptions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> List[SubscriptionResponse]:
    """列出所有订阅源。

    不分页，预期订阅数量在百级以内。返回所有订阅，不按用户隔离
    （订阅是全局共享的下载源，与 Open-AwA 用户体系正交）。
    """
    rows = (
        db.execute(
            select(BilibiliToolkitSubscription).order_by(
                BilibiliToolkitSubscription.id.asc()
            )
        )
        .scalars()
        .all()
    )
    return [
        SubscriptionResponse(
            id=row.id,
            type=row.type,
            source_id=row.source_id,
            name=row.name,
            path=row.path,
            enabled=row.enabled,
            latest_row_at=row.latest_row_at,
            created_at=row.created_at,
        )
        for row in rows
    ]


@router.post(
    "/subscriptions",
    response_model=SubscriptionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_subscription(
    payload: SubscriptionCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SubscriptionResponse:
    """添加订阅源。

    校验订阅类型与 (type, source_id) 唯一性，filter_option 字典序列化为
    JSON 字符串存储。
    """
    # 1. 校验订阅类型
    if payload.type not in _SUPPORTED_SUBSCRIPTION_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"不支持的订阅类型: {payload.type}, 支持的类型: "
                f"{sorted(_SUPPORTED_SUBSCRIPTION_TYPES)}"
            ),
        )

    # 2. 校验 (type, source_id) 唯一性
    existing = (
        db.execute(
            select(BilibiliToolkitSubscription).where(
                BilibiliToolkitSubscription.type == payload.type,
                BilibiliToolkitSubscription.source_id == payload.source_id,
            )
        )
        .scalars()
        .first()
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"订阅已存在: type={payload.type}, source_id={payload.source_id}"
            ),
        )

    # 3. 创建订阅记录
    filter_option_json: Optional[str] = None
    if payload.filter_option is not None:
        try:
            filter_option_json = json.dumps(
                payload.filter_option, ensure_ascii=False
            )
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"filter_option 序列化失败: {exc}",
            ) from exc

    subscription = BilibiliToolkitSubscription(
        type=payload.type,
        source_id=payload.source_id,
        name=payload.name,
        path=payload.path,
        filter_option=filter_option_json,
        enabled=payload.enabled,
    )
    db.add(subscription)
    db.commit()
    db.refresh(subscription)

    logger.bind(
        event="bilibili_toolkit_subscription_created",
        module="bilibili_toolkit",
        subscription_id=subscription.id,
        type=subscription.type,
        source_id=subscription.source_id,
        user_id=str(current_user.id),
    ).info(
        f"订阅已创建: id={subscription.id}, type={subscription.type}, "
        f"source_id={subscription.source_id}"
    )

    return SubscriptionResponse(
        id=subscription.id,
        type=subscription.type,
        source_id=subscription.source_id,
        name=subscription.name,
        path=subscription.path,
        enabled=subscription.enabled,
        latest_row_at=subscription.latest_row_at,
        created_at=subscription.created_at,
    )


@router.delete(
    "/subscriptions/{subscription_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_subscription(
    subscription_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    """删除订阅源。

    不级联删除已下载的视频与任务记录（保留历史），仅删除订阅本身。
    """
    subscription = db.get(BilibiliToolkitSubscription, subscription_id)
    if subscription is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"订阅不存在: id={subscription_id}",
        )

    db.delete(subscription)
    db.commit()

    logger.bind(
        event="bilibili_toolkit_subscription_deleted",
        module="bilibili_toolkit",
        subscription_id=subscription_id,
        user_id=str(current_user.id),
    ).info(f"订阅已删除: id={subscription_id}")

    # 返回 204 No Content（FastAPI 默认行为）
    return JSONResponse(status_code=status.HTTP_204_NO_CONTENT, content=None)


# ---------------------------------------------------------------------------
# 视频与任务路由
# ---------------------------------------------------------------------------


@router.get("/videos", response_model=List[VideoResponse])
def list_videos(
    subscription_id: Optional[int] = Query(default=None, description="按订阅 ID 过滤"),
    page: int = Query(default=1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页数量"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> List[VideoResponse]:
    """视频列表与下载状态。

    按 ``created_at`` 倒序分页返回，可选按 ``subscription_id`` 过滤。
    注意当前 BilibiliToolkitVideo 表无 subscription_id 字段（视频可被多个
    订阅共享），此处 ``subscription_id`` 参数当前仅作为占位，返回全部视频。
    """
    # 计算分页 offset
    offset = (page - 1) * page_size

    query = select(BilibiliToolkitVideo).order_by(
        BilibiliToolkitVideo.created_at.desc()
    )
    # subscription_id 参数当前未生效（视频表无 subscription_id 字段）
    # 保留参数为后续扩展（如增加 video_subscriptions 关联表）预留接口
    rows = db.execute(query.offset(offset).limit(page_size)).scalars().all()

    return [
        VideoResponse(
            id=row.id,
            bvid=row.bvid,
            title=row.title,
            cover=row.cover,
            upper_name=row.upper_name,
            pages_count=row.pages_count,
            download_status=row.download_status,
            created_at=row.created_at,
        )
        for row in rows
    ]


@router.post("/trigger/{subscription_id}", response_model=TriggerResponse)
async def trigger_download(
    subscription_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TriggerResponse:
    """手动触发订阅下载。

    立即返回 ``task_id``，下载在后台异步执行，不阻塞 HTTP 响应。
    后台任务执行 ``download_subscription`` 并把 :class:`WorkflowResult`
    持久化为 ``BilibiliToolkitDownloadTask`` 行（按子任务粒度）。
    """
    # 1. 校验订阅存在
    subscription = db.get(BilibiliToolkitSubscription, subscription_id)
    if subscription is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"订阅不存在: id={subscription_id}",
        )

    # 2. 生成 task_id 并记录到内存索引
    task_id = uuid.uuid4().hex
    _running_tasks[task_id] = subscription_id

    # 3. 启动后台下载任务（不阻塞响应）
    background_coro = _run_download_background(
        task_id=task_id,
        subscription=subscription,
    )
    asyncio.create_task(background_coro)

    logger.bind(
        event="bilibili_toolkit_download_triggered",
        module="bilibili_toolkit",
        subscription_id=subscription_id,
        task_id=task_id,
        user_id=str(current_user.id),
    ).info(
        f"下载已触发: subscription_id={subscription_id}, task_id={task_id}"
    )

    return TriggerResponse(
        task_id=task_id,
        message=f"订阅 {subscription_id} 下载任务已触发，task_id={task_id}",
    )


@router.get("/tasks", response_model=List[TaskResponse])
def list_tasks(
    video_id: Optional[int] = Query(default=None, description="按视频 ID 过滤"),
    task_status: Optional[str] = Query(
        default=None,
        description="按状态过滤（pending/running/succeeded/failed/skipped）",
    ),
    page: int = Query(default=1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页数量"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> List[TaskResponse]:
    """下载任务状态查询。

    按 ``created_at`` 倒序分页返回，可选按 ``video_id`` / ``status`` 过滤。
    """
    offset = (page - 1) * page_size

    query = select(BilibiliToolkitDownloadTask).order_by(
        BilibiliToolkitDownloadTask.created_at.desc()
    )
    if video_id is not None:
        query = query.where(BilibiliToolkitDownloadTask.video_id == video_id)
    if task_status is not None:
        query = query.where(BilibiliToolkitDownloadTask.status == task_status)

    rows = db.execute(query.offset(offset).limit(page_size)).scalars().all()

    return [
        TaskResponse(
            id=row.id,
            video_id=row.video_id,
            page_id=row.page_id,
            subtask=row.subtask,
            status=row.status,
            retry_count=row.retry_count,
            error=row.error,
            created_at=row.created_at,
        )
        for row in rows
    ]


# ---------------------------------------------------------------------------
# 配置路由
# ---------------------------------------------------------------------------


@router.get("/config")
def get_config(
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """获取当前插件配置。

    配置由 :class:`VersionedConfig` 全局单例管理，未初始化时返回空字典
    （插件未启用或未加载场景）。
    """
    try:
        manager = get_config_manager()
    except RuntimeError as exc:
        # 配置管理器未初始化（插件未加载），返回空配置而非 500
        logger.bind(
            event="bilibili_toolkit_config_not_initialized",
            module="bilibili_toolkit",
        ).warning(f"配置管理器未初始化: {exc}")
        return {"config": {}, "version": 0, "initialized": False}

    return {
        "config": manager.get_config(),
        "version": manager.version,
        "initialized": True,
    }


@router.put("/config")
def update_config(
    payload: ConfigUpdateRequest,
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """更新插件配置（触发热更新）。

    调用 :meth:`VersionedConfig.update_config` 整体替换配置并通知等待者。
    未初始化时返回 503（需先加载插件）。
    """
    try:
        manager = get_config_manager()
    except RuntimeError as exc:
        logger.bind(
            event="bilibili_toolkit_config_update_not_initialized",
            module="bilibili_toolkit",
            user_id=str(current_user.id),
        ).warning(f"配置管理器未初始化，无法更新: {exc}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="配置管理器未初始化，请先加载插件",
        ) from exc

    new_version = manager.update_config(payload.config)

    logger.bind(
        event="bilibili_toolkit_config_updated",
        module="bilibili_toolkit",
        version=new_version,
        user_id=str(current_user.id),
    ).info(f"配置已更新: version={new_version}")

    return {
        "version": new_version,
        "message": "配置已更新",
    }


# ---------------------------------------------------------------------------
# 后台下载任务实现
# ---------------------------------------------------------------------------


async def _run_download_background(
    task_id: str,
    subscription: BilibiliToolkitSubscription,
) -> None:
    """后台执行订阅下载并持久化结果。

    流程：
    1. 从 :class:`VersionedConfig` 读取配置（cookie / UA / 超时 / 并发）
    2. 构造 :class:`BilibiliClient`
    3. 调用 :func:`download_subscription` 拉取并下载视频
    4. 把 :class:`WorkflowResult` 列表持久化为
       :class:`BilibiliToolkitDownloadTask` 行（按子任务粒度）

    异常处理：
    - 配置未初始化 / Cookie 缺失：记录日志并退出，不抛异常
    - 下载过程异常：记录日志，保留已完成结果

    Args:
        task_id: 触发请求分配的任务 ID（用于日志追踪）。
        subscription: 订阅 ORM 对象（已含 type / source_id / path 等字段）。
    """
    # 任务结束时清理内存索引
    try:
        await _execute_download(task_id, subscription)
    except Exception as exc:  # noqa: BLE001 - 后台任务兜底
        logger.bind(
            event="bilibili_toolkit_download_background_error",
            module="bilibili_toolkit",
            task_id=task_id,
            subscription_id=subscription.id,
            error_type=type(exc).__name__,
        ).exception(f"后台下载任务异常: task_id={task_id}, error={exc}")
    finally:
        _running_tasks.pop(task_id, None)


async def _execute_download(
    task_id: str,
    subscription: BilibiliToolkitSubscription,
) -> None:
    """执行下载并持久化结果（从 ``_run_download_background`` 拆出便于测试）。"""
    # 1. 读取配置
    try:
        manager = get_config_manager()
    except RuntimeError as exc:
        logger.bind(
            event="bilibili_toolkit_download_config_missing",
            module="bilibili_toolkit",
            task_id=task_id,
        ).warning(f"配置管理器未初始化，跳过下载: {exc}")
        return

    config: Dict[str, Any] = manager.get_config()
    cookie_str: str = str(config.get("bilibili_cookie") or "")
    if not cookie_str:
        logger.bind(
            event="bilibili_toolkit_download_cookie_missing",
            module="bilibili_toolkit",
            task_id=task_id,
            subscription_id=subscription.id,
        ).warning("bilibili_cookie 未配置，跳过下载")
        return

    # 2. 构造 BilibiliClient
    credential: Credential = Credential.from_cookie_string(cookie_str)
    user_agent: str = str(config.get("bilibili_user_agent") or "")
    timeout: float = float(config.get("bilibili_request_timeout_seconds") or 15.0)
    max_concurrent: int = int(config.get("bilibili_max_concurrent_requests") or 5)
    client = BilibiliClient(
        credential=credential,
        user_agent=user_agent,
        timeout=timeout,
        max_concurrent=max_concurrent,
    )

    # 3. 调用 download_subscription
    base_dir = Path(subscription.path)
    base_dir.mkdir(parents=True, exist_ok=True)

    try:
        results, new_watermark = await download_subscription(
            client=client,
            subscription_type=subscription.type,
            source_id=subscription.source_id,
            config=config,
            base_dir=base_dir,
            latest_row_at=subscription.latest_row_at,
        )
    finally:
        # 关闭 httpx 客户端，避免资源泄漏（BilibiliClient.close 幂等）
        await client.close()

    # 4. 持久化结果到 download_tasks 表
    await _persist_workflow_results(
        task_id=task_id,
        subscription_id=subscription.id,
        results=results,
        new_watermark=new_watermark,
    )


async def _persist_workflow_results(
    task_id: str,
    subscription_id: int,
    results: List[WorkflowResult],
    new_watermark: Optional[int],
) -> None:
    """把 :class:`WorkflowResult` 列表持久化为 ``BilibiliToolkitDownloadTask`` 行。

    每个 :class:`WorkflowResult` 包含 5 个子任务的位图状态，本函数将其
    展开为 5 行 ``BilibiliToolkitDownloadTask`` 记录（按子任务粒度追踪）。

    简化策略：
    - 不在此处 upsert :class:`BilibiliToolkitVideo` / :class:`BilibiliToolkitPage`
      （阶段 17+ 由专门的数据同步层负责），仅记录子任务执行结果
    - ``video_id`` 字段非空约束暂时用 0 占位（数据库层面由 schema 校验，
      后续阶段补齐 video upsert 后修正）
    - 异常仅记录日志，不向上传播（后台任务容错）

    Args:
        task_id: 触发任务 ID。
        subscription_id: 订阅 ID。
        results: workflow 层返回的 :class:`WorkflowResult` 列表。
        new_watermark: 新的水位线值。
    """
    if not results:
        logger.bind(
            event="bilibili_toolkit_download_no_results",
            module="bilibili_toolkit",
            task_id=task_id,
            subscription_id=subscription_id,
        ).info(f"订阅 {subscription_id} 无下载结果")
        return

    # 延迟导入 SessionLocal，避免循环引用
    from db.models import SessionLocal

    db = SessionLocal()
    try:
        # 用 0 作为占位 video_id（实际由后续阶段补齐 video upsert）
        # 此处仅记录子任务执行结果，便于 GET /tasks 查询
        placeholder_video_id: int = 0
        for result in results:
            for subtask in SubTask:
                state = get_subtask_status(result.status, subtask)
                # 仅持久化非 Skipped 状态的子任务（Skipped 表示用户主动跳过）
                if state == SubTaskState.Skipped:
                    continue
                task_record = BilibiliToolkitDownloadTask(
                    video_id=placeholder_video_id,
                    page_id=result.page_id,
                    subtask=_SUBTASK_NAME_MAP[subtask],
                    status=_SUBTASK_STATE_NAME_MAP[state],
                    retry_count=0,
                    error=result.error if state == SubTaskState.Failed else None,
                )
                db.add(task_record)
        db.commit()

        logger.bind(
            event="bilibili_toolkit_download_results_persisted",
            module="bilibili_toolkit",
            task_id=task_id,
            subscription_id=subscription_id,
            result_count=len(results),
            new_watermark=new_watermark,
        ).info(
            f"下载结果已持久化: subscription_id={subscription_id}, "
            f"results={len(results)}, new_watermark={new_watermark}"
        )
    except Exception as exc:  # noqa: BLE001 - 持久化失败不阻塞后台任务
        logger.bind(
            event="bilibili_toolkit_download_persist_error",
            module="bilibili_toolkit",
            task_id=task_id,
            subscription_id=subscription_id,
        ).exception(f"持久化下载结果失败: {exc}")
        db.rollback()
    finally:
        db.close()


__all__ = [
    "router",
    "SubscriptionCreateRequest",
    "SubscriptionResponse",
    "VideoResponse",
    "TaskResponse",
    "TriggerResponse",
    "ConfigUpdateRequest",
]
