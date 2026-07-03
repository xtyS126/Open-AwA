"""
收件箱 API 路由。
提供审批通知、任务结果推送和系统通知的集中管理。

安全说明：
- 收件箱存储按 user_id 隔离，防止跨用户 IDOR
- 所有端点强制注入 current_user，仅操作归属当前用户的消息
"""
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.dependencies import get_current_user
from db.models import User

router = APIRouter(
    prefix="/api/inbox",
    tags=["inbox"],
    dependencies=[Depends(get_current_user)],
)

# 内存中的收件箱存储（按 user_id 隔离），后续可迁移到 DB 模型
# 结构: { user_id: [ { id, title, content, ... }, ... ] }
_inbox_store: dict[str, list[dict]] = {}
_inbox_lock = threading.Lock()


def _get_user_messages(user_id: str) -> list[dict]:
    """线程安全地获取指定用户的消息列表副本。"""
    with _inbox_lock:
        return list(_inbox_store.get(user_id, []))


def _save_user_messages(user_id: str, messages: list[dict]) -> None:
    """线程安全地保存指定用户的消息列表。"""
    with _inbox_lock:
        _inbox_store[user_id] = messages


class InboxMessageCreate(BaseModel):
    """创建收件箱消息。"""
    title: str
    content: str
    category: str = "notification"  # notification / approval / task_result
    action_url: Optional[str] = None
    action_label: Optional[str] = None


@router.get("")
def list_messages(
    current_user: User = Depends(get_current_user),
    category: Optional[str] = None,
    unread_only: bool = False,
    limit: int = 50,
) -> Dict[str, Any]:
    """
    获取收件箱消息列表。
    支持按类别筛选和仅未读过滤，仅返回当前用户的消息。
    """
    messages = _get_user_messages(current_user.id)
    if category:
        messages = [m for m in messages if m["category"] == category]
    if unread_only:
        messages = [m for m in messages if not m["read"]]

    messages.sort(key=lambda m: m["created_at"], reverse=True)
    return {
        "messages": messages[:limit],
        "total": len(messages),
        "unread": sum(1 for m in messages if not m["read"]),
    }


@router.post("")
def create_message(
    body: InboxMessageCreate,
    current_user: User = Depends(get_current_user),
) -> Dict[str, str]:
    """
    创建收件箱消息（由系统内部调用，归属当前用户）。
    """
    msg = {
        "id": str(uuid.uuid4())[:12],
        "title": body.title,
        "content": body.content,
        "category": body.category,
        "action_url": body.action_url,
        "action_label": body.action_label,
        "read": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    with _inbox_lock:
        user_msgs = _inbox_store.setdefault(current_user.id, [])
        user_msgs.insert(0, msg)
        # 保持每用户最多 200 条消息
        while len(user_msgs) > 200:
            user_msgs.pop()

    return {"message": "消息已创建", "id": msg["id"]}


@router.post("/{message_id}/read")
def mark_as_read(
    message_id: str,
    current_user: User = Depends(get_current_user),
) -> Dict[str, str]:
    """
    标记消息为已读（仅限当前用户的消息）。
    """
    messages = _get_user_messages(current_user.id)
    for msg in messages:
        if msg["id"] == message_id:
            msg["read"] = True
            _save_user_messages(current_user.id, messages)
            return {"message": "已标记为已读"}
    raise HTTPException(status_code=404, detail="消息不存在")


@router.post("/read-all")
def mark_all_read(
    current_user: User = Depends(get_current_user),
    category: Optional[str] = None,
) -> Dict[str, Any]:
    """
    标记所有（或指定类别）消息为已读（仅限当前用户的消息）。
    """
    messages = _get_user_messages(current_user.id)
    count = 0
    for msg in messages:
        if (not category or msg["category"] == category) and not msg["read"]:
            msg["read"] = True
            count += 1
    _save_user_messages(current_user.id, messages)
    return {"message": f"已标记 {count} 条消息为已读", "count": count}


@router.delete("/{message_id}")
def delete_message(
    message_id: str,
    current_user: User = Depends(get_current_user),
) -> Dict[str, str]:
    """
    删除收件箱消息（仅限当前用户的消息）。
    """
    messages = _get_user_messages(current_user.id)
    before = len(messages)
    new_messages = [m for m in messages if m["id"] != message_id]
    if len(new_messages) == before:
        raise HTTPException(status_code=404, detail="消息不存在")
    _save_user_messages(current_user.id, new_messages)
    return {"message": "消息已删除"}


@router.get("/count")
def get_unread_count(
    current_user: User = Depends(get_current_user),
) -> Dict[str, int]:
    """
    获取未读消息数量（仅限当前用户）。
    """
    messages = _get_user_messages(current_user.id)
    count = sum(1 for m in messages if not m["read"])
    return {"unread": count}


# ---- 辅助函数 ----

def add_notification(
    title: str,
    content: str,
    category: str = "notification",
    action_url: Optional[str] = None,
    user_id: Optional[str] = None,
) -> Optional[str]:
    """
    内部通知推送函数。

    需要 user_id 才能正确归属消息；未提供 user_id 时返回 None（避免误归到错误用户）。
    """
    if not user_id:
        return None
    msg_id = str(uuid.uuid4())[:12]
    msg = {
        "id": msg_id,
        "title": title,
        "content": content,
        "category": category,
        "action_url": action_url,
        "action_label": None,
        "read": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    with _inbox_lock:
        user_msgs = _inbox_store.setdefault(user_id, [])
        user_msgs.insert(0, msg)
        while len(user_msgs) > 200:
            user_msgs.pop()
    return msg_id


def add_approval_notification(tool_name: str, approval_id: str, user_id: Optional[str] = None) -> Optional[str]:
    """添加工具审批通知（需指定 user_id）。"""
    return add_notification(
        title=f"工具调用审批: {tool_name}",
        content=f"工具 '{tool_name}' 请求执行，等待审批。",
        category="approval",
        action_url=f"/inbox?approval={approval_id}",
        user_id=user_id,
    )


def add_task_result_notification(
    task_name: str,
    success: bool,
    summary: str = "",
    user_id: Optional[str] = None,
) -> Optional[str]:
    """添加任务结果通知（需指定 user_id）。"""
    status = "成功" if success else "失败"
    return add_notification(
        title=f"任务{status}: {task_name}",
        content=summary or f"任务 '{task_name}' 已{status}完成。",
        category="task_result",
        user_id=user_id,
    )
