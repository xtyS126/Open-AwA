"""
安全路由 - 权限请求 SSE 兼容端点

阶段 2 实现说明：
- 移动端没有 ACP 子进程，不会真正产生权限请求事件
- 提供端点兼容前端 usePermissionRequest hook，避免 404 触发重连
- sse-ticket 返回一次性 ticket（60s TTL，内存存储）
- stream 返回 keep-alive SSE 流（30s 心跳），保持连接但不发事件
"""

import asyncio
import secrets
import threading
import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import User, get_db
from .auth import get_current_user

router = APIRouter(prefix="/api/security", tags=["Security"])


# ============================================================================
# 一次性 SSE ticket 内存存储
#
# 移动端单用户场景，无需分布式存储。threading.Lock 保护并发安全。
# ticket 60s 过期，使用后立即删除。当存储数量超过 256 时触发惰性清理。
# ============================================================================


_TICKET_TTL_SECONDS: int = 60
_TICKET_CLEANUP_THRESHOLD: int = 256

_sse_tickets: Dict[str, Dict[str, Any]] = {}
_sse_tickets_lock = threading.Lock()


def _issue_ticket() -> str:
    """签发一次性 SSE ticket，返回 token 字符串"""
    ticket = secrets.token_urlsafe(32)
    now = time.time()
    with _sse_tickets_lock:
        # 惰性清理过期 ticket
        if len(_sse_tickets) > _TICKET_CLEANUP_THRESHOLD:
            expired_keys = [
                k for k, v in _sse_tickets.items()
                if now - float(v.get("issued_at", 0)) > _TICKET_TTL_SECONDS
            ]
            for k in expired_keys:
                _sse_tickets.pop(k, None)
        _sse_tickets[ticket] = {
            "issued_at": now,
            "used": False,
        }
    return ticket


def _consume_ticket(ticket: str) -> bool:
    """消费一次性 ticket，返回是否有效"""
    with _sse_tickets_lock:
        entry = _sse_tickets.pop(ticket, None)
    if entry is None:
        return False
    now = time.time()
    if now - float(entry.get("issued_at", 0)) > _TICKET_TTL_SECONDS:
        return False
    return True


@router.post("/permissions/sse-ticket")
async def request_sse_ticket(
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    申请一次性 SSE ticket

    前端 usePermissionRequest hook 在已选会话时调用本接口换取 ticket，
    再以 ?ticket=<ticket> 连接 /api/security/permissions/stream。
    ticket 一次性使用，60s 过期。
    """
    ticket = _issue_ticket()
    return {
        "ticket": ticket,
        "expires_in": _TICKET_TTL_SECONDS,
    }


@router.get("/permissions/stream")
async def permission_stream(
    db: Session = Depends(get_db),
    ticket: Optional[str] = Query(None, description="一次性 SSE ticket"),
    api_key: Optional[str] = Query(None, description="向后兼容的 API Key（不推荐）"),
) -> StreamingResponse:
    """
    权限请求 SSE 流

    移动端没有 ACP 子进程，不会真正产生权限请求事件。
    本端点保持连接并发送 30s 心跳注释，避免前端 onerror 重连。
    前端断开后会自动释放连接。

    认证：优先校验 ticket；无 ticket 时回退校验 api_key（向后兼容）。
    """
    settings = get_settings()

    # 认证校验
    if ticket:
        if not _consume_ticket(ticket):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="ticket 无效或已过期",
            )
    elif api_key:
        if api_key != settings.api_key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="API Key 无效",
            )
    else:
        # 无凭据，拒绝（EventSource 无法携带 Authorization header，前端必须用 ticket 或 api_key）
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未提供 ticket 或 api_key",
        )

    async def event_generator():
        """SSE 事件生成器：每 30s 发送注释心跳，保持连接"""
        try:
            # 初始心跳，确认连接建立
            yield b": connected\n\n"
            while True:
                await asyncio.sleep(30)
                yield b": keep-alive\n\n"
        except asyncio.CancelledError:
            # 客户端断开连接，正常退出
            raise

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.get("/permissions/saved")
async def list_saved_permissions(
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    获取已保存的权限列表（兼容端点）

    移动端没有 ACP 子进程，不会保存任何权限。返回空列表。
    """
    return {
        "items": [],
        "total": 0,
        "page": 1,
        "page_size": 50,
    }


@router.delete("/permissions/saved/{permission_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_saved_permission(
    permission_id: str,
    current_user: User = Depends(get_current_user),
) -> None:
    """删除单条已保存权限（兼容端点，移动端无数据可删）"""
    return None


@router.delete("/permissions/saved", status_code=status.HTTP_204_NO_CONTENT)
async def delete_all_saved_permissions(
    current_user: User = Depends(get_current_user),
) -> None:
    """删除所有已保存权限（兼容端点，移动端无数据可删）"""
    return None


@router.post("/permissions/reply")
async def reply_to_permission(
    payload: Dict[str, Any],
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    回复权限请求（兼容端点）

    移动端没有 ACP 子进程，不会有待回复的权限请求。返回 ok 但不执行任何操作。
    """
    return {"ok": True, "message": "移动端无 ACP 子进程，权限请求已忽略"}
