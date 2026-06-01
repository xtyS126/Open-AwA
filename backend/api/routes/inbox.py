"""
收件箱 API 路由。
提供审批通知、任务结果推送和系统通知的集中管理。
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.dependencies import get_current_user

router = APIRouter(
    prefix="/api/inbox",
    tags=["inbox"],
    dependencies=[Depends(get_current_user)],
)

# 内存中的收件箱存储（后续可迁移到 DB 模型）
_inbox_store: list[dict] = []


class InboxMessageCreate(BaseModel):
    """创建收件箱消息。"""
    title: str
    content: str
    category: str = "notification"  # notification / approval / task_result
    action_url: Optional[str] = None
    action_label: Optional[str] = None


@router.get("")
def list_messages(
    category: Optional[str] = None,
    unread_only: bool = False,
    limit: int = 50,
):
    """
    获取收件箱消息列表。
    支持按类别筛选和仅未读过滤。
    """
    # 复制列表避免排序副作用影响全局状态
    messages = list(_inbox_store)
    if category:
        messages = [m for m in messages if m["category"] == category]
    if unread_only:
        messages = [m for m in messages if not m["read"]]

    messages.sort(key=lambda m: m["created_at"], reverse=True)
    return {
        "messages": messages[:limit],
        "total": len(messages),
        "unread": sum(1 for m in _inbox_store if not m["read"]),
    }


@router.post("")
def create_message(body: InboxMessageCreate):
    """
    创建收件箱消息（由系统内部调用）。
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
    _inbox_store.insert(0, msg)

    # 保持最多 200 条消息
    while len(_inbox_store) > 200:
        _inbox_store.pop()

    return {"message": "消息已创建", "id": msg["id"]}


@router.post("/{message_id}/read")
def mark_as_read(message_id: str):
    """
    标记消息为已读。
    """
    for msg in _inbox_store:
        if msg["id"] == message_id:
            msg["read"] = True
            return {"message": "已标记为已读"}
    raise HTTPException(status_code=404, detail="消息不存在")


@router.post("/read-all")
def mark_all_read(category: Optional[str] = None):
    """
    标记所有（或指定类别）消息为已读。
    """
    count = 0
    for msg in _inbox_store:
        if (not category or msg["category"] == category) and not msg["read"]:
            msg["read"] = True
            count += 1
    return {"message": f"已标记 {count} 条消息为已读", "count": count}


@router.delete("/{message_id}")
def delete_message(message_id: str):
    """
    删除收件箱消息。
    """
    global _inbox_store
    before = len(_inbox_store)
    _inbox_store = [m for m in _inbox_store if m["id"] != message_id]
    if len(_inbox_store) == before:
        raise HTTPException(status_code=404, detail="消息不存在")
    return {"message": "消息已删除"}


@router.get("/count")
def get_unread_count():
    """
    获取未读消息数量。
    """
    count = sum(1 for m in _inbox_store if not m["read"])
    return {"unread": count}


# ---- 辅助函数 ----

def add_notification(title: str, content: str, category: str = "notification", action_url: Optional[str] = None):
    """内部通知推送函数。"""
    return create_message(InboxMessageCreate(
        title=title,
        content=content,
        category=category,
        action_url=action_url,
    ))


def add_approval_notification(tool_name: str, approval_id: str):
    """添加工具审批通知。"""
    return add_notification(
        title=f"工具调用审批: {tool_name}",
        content=f"工具 '{tool_name}' 请求执行，等待审批。",
        category="approval",
        action_url=f"/inbox?approval={approval_id}",
    )


def add_task_result_notification(task_name: str, success: bool, summary: str = ""):
    """添加任务结果通知。"""
    status = "成功" if success else "失败"
    return add_notification(
        title=f"任务{status}: {task_name}",
        content=summary or f"任务 '{task_name}' 已{status}完成。",
        category="task_result",
    )
