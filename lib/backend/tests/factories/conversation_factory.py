"""
测试会话数据工厂，生成标准化的 Conversation 模型实例或字典。
"""
import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, Any


def create_test_conversation(
    session_id: Optional[str] = None,
    user_id: str = "test-user-001",
    title: str = "测试会话",
    message_count: int = 0,
    deleted_at: Optional[datetime] = None,
) -> Dict[str, Any]:
    """
    创建测试会话字典。

    参数：
        session_id: 会话 ID，默认自动生成
        user_id: 所属用户 ID
        title: 会话标题
        message_count: 消息数量
        deleted_at: 软删除时间，None 表示未删除
    """
    sid = session_id or f"test-session-{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc)
    return {
        "session_id": sid,
        "user_id": user_id,
        "title": title,
        "summary": f"{title}的摘要",
        "last_message_preview": "最后一条消息预览...",
        "last_message_role": "user",
        "message_count": message_count,
        "created_at": now,
        "updated_at": now,
        "last_message_at": now,
        "deleted_at": deleted_at,
        "restored_at": None,
        "purge_after": None,
        "conversation_metadata": {},
    }


def create_test_conversation_dict(
    session_id: Optional[str] = None,
    user_id: str = "test-user-001",
    title: str = "测试会话",
) -> Dict[str, Any]:
    """创建轻量测试会话字典（用于 API 请求体）。"""
    return {
        "session_id": session_id or f"test-session-{uuid.uuid4().hex[:12]}",
        "user_id": user_id,
        "title": title,
    }
