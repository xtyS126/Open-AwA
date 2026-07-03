# -*- coding: utf-8 -*-
"""
通知 HTTP API 路由。

为前端与外部工具（如 Claude Code hooks）提供统一的通知发送、订阅与查询接口。
所有端点强制鉴权（Depends(get_current_user)），按 user_id 隔离通知存储与订阅队列。

## 端点概览

- `POST /api/notifications`         发送一条通知，存入用户级环形缓冲并推送给所有订阅者
- `GET  /api/notifications`         列出当前用户最近 N 条通知（默认 50，最大 100）
- `GET  /api/notifications/stream`  SSE 长连接，实时推送通知，30s 心跳

## Claude Code Hooks 集成

用户可在 Claude Code 的 settings.json 中配置 hooks，将工具事件通过 curl 推送到本接口。
模板见 `backend/static/claude-code-hooks.json`，运行时需将 `$OPENAWA_TOKEN` 替换为
本地用户的有效访问令牌（与登录后获得的 access_token 相同）。

示例命令：

    curl -s -X POST http://127.0.0.1:8000/api/notifications \
        -H "Content-Type: application/json" \
        -H "Authorization: Bearer $OPENAWA_TOKEN" \
        -d '{"title":"Claude Code Stopped","body":"Task completed","notification_type":"success"}'

## 安全策略

1. 所有端点强制 Depends(get_current_user)，按 user_id 隔离数据
2. title 非空校验；notification_type 限定为 info/warning/error/success
3. SSE 连接断开时立即从订阅者集合移除 Queue，避免资源泄露
4. 每用户环形缓冲上限 100 条，超出自动丢弃最旧的（deque 语义）
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Deque, Dict, Optional, Set

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from loguru import logger
from pydantic import BaseModel, Field

from api.dependencies import get_current_user
from db.models import User


router = APIRouter(prefix="/api/notifications", tags=["notifications"])


# ==================== 全局状态（按 user_id 隔离） ====================

# 每用户的通知环形缓冲：deque(maxlen=100)，末尾是最新
# key 是 current_user.id（User.id 为字符串类型，与 acp.py 保持一致）
_notifications_store: Dict[str, Deque[Dict[str, object]]] = {}

# 每用户的订阅队列集合：每个 SSE 连接对应一个 asyncio.Queue
# put 通知时遍历所有 Queue 推送，断开时从集合移除
_notification_subscribers: Dict[str, Set[asyncio.Queue]] = {}

# 单用户最大保留通知数（环形缓冲容量）
_MAX_NOTIFICATIONS_PER_USER = 100

# P0-14: 模块级字典容量上限，防止单用户创建海量订阅触发 OOM
# 全局最大用户数（通知存储与订阅字典的容量上限）
_MAX_NOTIFICATION_USERS = 1000
# 单用户最大 SSE 订阅数
_MAX_SSE_SUBSCRIBERS_PER_USER = 10

# 允许的通知类型白名单
_ALLOWED_NOTIFICATION_TYPES = {"info", "warning", "error", "success"}

# SSE 心跳间隔（秒）
_SSE_HEARTBEAT_INTERVAL = 30.0


# ==================== 请求/响应 Schema ====================


class NotificationCreateRequest(BaseModel):
    """POST / 请求体：发送一条通知。"""

    title: str = Field(..., min_length=1, description="通知标题，不可为空")
    body: str = Field(default="", description="通知正文，可空")
    pane_id: str | None = Field(default=None, description="关联的面板 ID，可空")
    notification_type: str = Field(
        default="info",
        description="通知类型，必须为 info/warning/error/success 之一",
    )


class NotificationCreateResponse(BaseModel):
    """POST / 响应。"""

    ok: bool = Field(default=True, description="是否成功")
    id: str = Field(..., description="通知 ID（uuid4 hex）")


class NotificationInfo(BaseModel):
    """单条通知的展示信息。"""

    id: str = Field(..., description="通知 ID")
    title: str = Field(..., description="通知标题")
    body: str = Field(..., description="通知正文")
    pane_id: str | None = Field(default=None, description="关联的面板 ID")
    notification_type: str = Field(..., description="通知类型")
    created_at: str = Field(..., description="创建时间（ISO 格式）")


class NotificationListResponse(BaseModel):
    """GET / 响应。"""

    notifications: list[NotificationInfo] = Field(default_factory=list)
    count: int = Field(..., description="本次返回的通知条数")
    total: int = Field(..., description="用户当前缓冲区内的通知总数")


# ==================== 工具函数 ====================


def _now_iso() -> str:
    """返回当前 UTC 时间的 ISO 格式字符串。"""
    return datetime.now(timezone.utc).isoformat()


def _evict_oldest_notification_user() -> None:
    """淘汰最久未活跃用户的通知缓冲。

    P0-14: 在全局用户数达到 _MAX_NOTIFICATION_USERS 时调用。
    按 deque 末尾（最新通知）的 created_at 时间戳排序，淘汰最久未活跃的用户。
    """
    if not _notifications_store:
        return

    oldest_user = None
    oldest_time: Optional[str] = None
    for uid, buf in _notifications_store.items():
        if not buf:
            # 空缓冲视为最旧，直接淘汰
            oldest_user = uid
            break
        # deque 末尾是最新通知
        latest_time = str(buf[-1].get("created_at", ""))
        if oldest_time is None or latest_time < oldest_time:
            oldest_time = latest_time
            oldest_user = uid

    if oldest_user is not None:
        _notifications_store.pop(oldest_user, None)
        # 同步清理订阅集合（如果存在）
        _notification_subscribers.pop(oldest_user, None)
        logger.warning(
            f"全局通知用户数已达上限 {_MAX_NOTIFICATION_USERS}，"
            f"已淘汰最久未活跃用户: {oldest_user}"
        )


def _get_user_buffer(user_id: str) -> Deque[Dict[str, object]]:
    """获取（必要时创建）指定用户的通知环形缓冲。

    P0-14: 全局用户数达到上限时淘汰最旧用户的通知缓冲，防止字典无界增长。
    """
    buf = _notifications_store.get(user_id)
    if buf is None:
        # 全局用户数上限：超出时淘汰最旧用户的通知缓冲
        if len(_notifications_store) >= _MAX_NOTIFICATION_USERS:
            _evict_oldest_notification_user()
        buf = deque(maxlen=_MAX_NOTIFICATIONS_PER_USER)
        _notifications_store[user_id] = buf
    return buf


def _get_user_subscribers(user_id: str) -> Set[asyncio.Queue]:
    """获取（必要时创建）指定用户的订阅队列集合。"""
    subs = _notification_subscribers.get(user_id)
    if subs is None:
        subs = set()
        _notification_subscribers[user_id] = subs
    return subs


def _broadcast_notification(user_id: str, notification: Dict[str, object]) -> None:
    """向指定用户的所有订阅队列推送通知（非阻塞，跳过已满的队列）。"""
    subs = _notification_subscribers.get(user_id)
    if not subs:
        return
    for queue in subs:
        try:
            queue.put_nowait(notification)
        except asyncio.QueueFull:
            # 队列已满，丢弃该通知避免阻塞其他订阅者
            logger.bind(
                event="notification_subscriber_queue_full",
                module="notifications",
                user_id=user_id,
            ).warning("订阅队列已满，丢弃该通知")


def _format_sse(notification: Dict[str, object]) -> str:
    """构造 SSE 帧：event: notification\\ndata: <json>\\n\\n。"""
    return (
        "event: notification\n"
        f"data: {json.dumps(notification, ensure_ascii=False)}\n\n"
    )


# ==================== 端点实现 ====================


@router.post("", response_model=NotificationCreateResponse)
async def create_notification(
    request: NotificationCreateRequest,
    current_user: User = Depends(get_current_user),
) -> NotificationCreateResponse:
    """发送一条通知。

    流程：
    1. 校验 notification_type 在白名单内
    2. 生成 id（uuid4 hex）与 created_at（ISO 时间戳）
    3. 存入用户级环形缓冲（deque maxlen=100，自动丢弃最旧的）
    4. 推送给所有订阅 SSE 的客户端（向每个 Queue put_nowait）
    """
    if request.notification_type not in _ALLOWED_NOTIFICATION_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"非法的 notification_type: {request.notification_type}，"
                f"允许值: {sorted(_ALLOWED_NOTIFICATION_TYPES)}"
            ),
        )

    user_id = str(current_user.id)
    notification: Dict[str, object] = {
        "id": uuid.uuid4().hex,
        "title": request.title,
        "body": request.body,
        "pane_id": request.pane_id,
        "notification_type": request.notification_type,
        "created_at": _now_iso(),
    }

    # 存入环形缓冲
    buf = _get_user_buffer(user_id)
    buf.append(notification)

    # 推送给所有订阅者
    _broadcast_notification(user_id, notification)

    logger.bind(
        event="notification_created",
        module="notifications",
        user_id=user_id,
        notification_id=notification["id"],
        notification_type=notification["notification_type"],
    ).info(f"通知已创建: {notification['title']}")

    return NotificationCreateResponse(ok=True, id=str(notification["id"]))


@router.get("", response_model=NotificationListResponse)
async def list_notifications(
    current_user: User = Depends(get_current_user),
    limit: int = Query(default=50, ge=1, le=100, description="返回最近 N 条通知"),
) -> NotificationListResponse:
    """列出当前用户最近 N 条通知。

    deque 末尾是最新，因此从右端反向取 limit 条后再反转，使响应顺序为「最新在前」。
    """
    user_id = str(current_user.id)
    buf = _notifications_store.get(user_id)
    if not buf:
        return NotificationListResponse(notifications=[], count=0, total=0)

    # 取最近 limit 条（buf[-limit:] 后反转，使最新在前）
    recent = list(buf)[-limit:][::-1]
    infos = [NotificationInfo(**item) for item in recent]
    return NotificationListResponse(
        notifications=infos,
        count=len(infos),
        total=len(buf),
    )


@router.get("/stream")
async def stream_notifications(
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """SSE 长连接：实时推送当前用户的通知。

    每个连接创建独立 asyncio.Queue 加入订阅集合，循环 await queue.get() 取通知。
    30s 无通知发送心跳 `: keep-alive\\n\\n`。
    客户端断开时从订阅集合移除 Queue，避免资源泄露。

    P0-14: 单用户 SSE 订阅数上限 _MAX_SSE_SUBSCRIBERS_PER_USER，超出返回 429。
    """
    user_id = str(current_user.id)
    queue: asyncio.Queue = asyncio.Queue()
    subs = _get_user_subscribers(user_id)
    # P0-14: per-user 订阅数上限，防止单用户创建海量 SSE 连接触发 OOM
    if len(subs) >= _MAX_SSE_SUBSCRIBERS_PER_USER:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"SSE 订阅数已达上限 {_MAX_SSE_SUBSCRIBERS_PER_USER}，"
                f"请关闭旧连接后重试"
            ),
        )
    subs.add(queue)

    logger.bind(
        event="notification_sse_subscribe",
        module="notifications",
        user_id=user_id,
    ).info(f"SSE 订阅建立: user_id={user_id}, 当前订阅数={len(subs)}")

    async def event_generator():
        """SSE 事件生成器：循环取通知并推送，超时发送心跳。"""
        try:
            while True:
                try:
                    notification = await asyncio.wait_for(
                        queue.get(), timeout=_SSE_HEARTBEAT_INTERVAL
                    )
                except asyncio.TimeoutError:
                    # 心跳保持连接活跃
                    yield ": keep-alive\n\n"
                    continue
                yield _format_sse(notification)
        except asyncio.CancelledError:
            # 客户端断开，正常退出
            raise
        finally:
            # 无论以何种方式退出，都必须从订阅集合移除 Queue，避免资源泄露
            subs.discard(queue)
            logger.bind(
                event="notification_sse_unsubscribe",
                module="notifications",
                user_id=user_id,
            ).info(
                f"SSE 订阅断开: user_id={user_id}, 剩余订阅数={len(subs)}"
            )

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
