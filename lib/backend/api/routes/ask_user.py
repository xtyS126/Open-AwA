"""
ask_user 提问工具路由模块。

提供 PendingAskUser 载体、enqueue_ask_user_request 入队函数、
以及 POST /api/chat/ask-user/reply 回答提交端点。

参考 backend/api/routes/security.py 的 PendingPermissionRequest 模式实现：
- 工具调用端通过 enqueue 创建 Future 并阻塞等待
- 用户通过 reply 端点提交回答后 Future 完成
- 超时自动返回 [TIMEOUT] 占位字符串
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api.dependencies import get_current_user, get_db
from db.models import User


router = APIRouter(prefix="/api/chat", tags=["AskUser"])


class PendingAskUser:
    """待回答的 ask_user 请求条目。

    持有 asyncio.Future，工具调用端 await 此 Future 阻塞等待用户回答。
    用户提交回答后通过 _reply_future.set_result() 恢复执行。
    """

    def __init__(
        self,
        request_id: str,
        user_id: str,
        session_id: str,
        question: str,
        options: list[str],
        allow_multiple: bool,
        allow_free_text: bool,
        placeholder: str,
        timeout: int,
    ) -> None:
        self.request_id = request_id
        self.user_id = user_id
        self.session_id = session_id
        self.question = question
        self.options = options
        self.allow_multiple = allow_multiple
        self.allow_free_text = allow_free_text
        self.placeholder = placeholder
        self.timeout = timeout
        self.created_at = datetime.now(timezone.utc).timestamp()
        # 用于等待回复的 Future，reply 端设置结果后工具即可拿到回答
        self._reply_future: asyncio.Future[dict[str, Any]] = asyncio.get_event_loop().create_future()
        # 标记是否已被回答（用于重复提交检测）
        self._answered = False

    def to_payload(self) -> dict[str, Any]:
        """序列化为前端可消费的 ask_user 事件载荷。"""
        return {
            "request_id": self.request_id,
            "session_id": self.session_id,
            "question": self.question,
            "options": self.options,
            "allow_multiple": self.allow_multiple,
            "allow_free_text": self.allow_free_text,
            "placeholder": self.placeholder,
            "timeout": self.timeout,
            "created_at": self.created_at,
        }


# 内存队列：request_id -> PendingAskUser
# 按 request_id 索引而非 user_id，因为 ask_user 是会话内交互，
# 同一时刻最多只有一个挂起的 ask_user（is_concurrency_safe=False 保证）
_pending_ask_user_requests: dict[str, PendingAskUser] = {}


def enqueue_ask_user_request(
    user_id: str,
    session_id: str,
    question: str,
    options: Optional[list[str]] = None,
    allow_multiple: bool = False,
    allow_free_text: bool = True,
    placeholder: str = "",
    timeout: int = 300,
) -> tuple[str, asyncio.Future[dict[str, Any]]]:
    """
    将 ask_user 请求加入队列，返回 (request_id, Future)。

    调用方 await Future 即可阻塞等待用户回答。
    超时后 Future 自动以 [TIMEOUT] 结果结束。

    参数:
        user_id: 目标用户 ID
        session_id: 会话 ID
        question: 向用户展示的问题文本
        options: 预设选项列表
        allow_multiple: 是否允许多选
        allow_free_text: 是否允许自由文本输入
        placeholder: 输入框占位提示
        timeout: 超时秒数（60-600，默认 300）

    返回:
        (request_id, asyncio.Future[dict]) - Future 结果为 {"answer": str, "selected_options": list[str]}
    """
    # 钳制超时范围
    timeout = max(60, min(600, int(timeout)))

    request_id = uuid.uuid4().hex[:16]
    entry = PendingAskUser(
        request_id=request_id,
        user_id=user_id,
        session_id=session_id,
        question=question,
        options=options or [],
        allow_multiple=allow_multiple,
        allow_free_text=allow_free_text,
        placeholder=placeholder,
        timeout=timeout,
    )
    _pending_ask_user_requests[request_id] = entry

    logger.bind(
        event="ask_user_enqueued",
        user_id=user_id,
        session_id=session_id,
        request_id=request_id,
    ).info(f"ask_user 请求已入队: {request_id}")

    # 设置超时自动返回 [TIMEOUT]
    async def _timeout_result() -> None:
        await asyncio.sleep(timeout)
        if not entry._reply_future.done():
            timeout_payload = {
                "answer": "[TIMEOUT] 用户未在规定时间内回答",
                "selected_options": [],
            }
            entry._reply_future.set_result(timeout_payload)
            entry._answered = True
            # 从队列中移除已超时的请求
            _pending_ask_user_requests.pop(request_id, None)
            logger.bind(
                event="ask_user_timeout",
                request_id=request_id,
            ).warning(f"ask_user 请求超时: {request_id}")

    asyncio.create_task(_timeout_result())

    return request_id, entry._reply_future


def resolve_pending_ask_user(
    request_id: str,
    session_id: str,
    answer: str,
    selected_options: list[str],
) -> bool:
    """
    解析待回答的 ask_user 请求。

    校验 session_id 匹配后设置 Future 结果。
    返回 (成功与否, 错误码)。
    错误码: "not_found" / "session_mismatch" / "already_answered"
    """
    entry = _pending_ask_user_requests.get(request_id)
    if entry is None:
        return False, "not_found"

    if entry.session_id != session_id:
        return False, "session_mismatch"

    if entry._answered or entry._reply_future.done():
        return False, "already_answered"

    payload = {
        "answer": answer,
        "selected_options": selected_options,
    }
    entry._reply_future.set_result(payload)
    entry._answered = True
    _pending_ask_user_requests.pop(request_id, None)

    logger.bind(
        event="ask_user_resolved",
        request_id=request_id,
    ).info(f"ask_user 请求已回答: {request_id}")
    return True, None


# -------- 回答提交端点 --------


class AskUserReplyRequest(BaseModel):
    """ask_user 回答提交请求体。"""

    request_id: str = Field(..., description="ask_user 事件中的 request_id")
    session_id: str = Field(..., description="会话 ID，用于鉴权校验")
    answer: str = Field(..., max_length=10000, description="用户回答文本")
    selected_options: list[str] = Field(
        default_factory=list, description="选中的选项文本列表"
    )


class AskUserReplyResponse(BaseModel):
    """ask_user 回答提交响应体。"""

    ok: bool = True
    message: str = "回答已提交"


@router.post("/ask-user/reply", response_model=AskUserReplyResponse)
async def reply_ask_user(
    request: AskUserReplyRequest,
    current_user: User = Depends(get_current_user),
) -> AskUserReplyResponse:
    """
    提交用户对 ask_user 工具的回答。

    校验 request_id 存在性、session_id 匹配性、是否已被回答，
    通过后设置 Future 结果恢复工具执行。
    """
    success, error_code = resolve_pending_ask_user(
        request_id=request.request_id,
        session_id=request.session_id,
        answer=request.answer,
        selected_options=request.selected_options,
    )

    if success:
        return AskUserReplyResponse()

    if error_code == "not_found":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="请求不存在或已超时",
        )
    if error_code == "session_mismatch":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="会话不匹配",
        )
    if error_code == "already_answered":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="该问题已被回答",
        )
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="未知错误",
    )
