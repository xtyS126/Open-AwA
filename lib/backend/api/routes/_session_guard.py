"""
共享的会话归属校验模块。

HTTP chat 路由与 WebSocket 路径复用同一校验逻辑，防止用户 A 越权使用
用户 B 的 session_id 污染记忆或访问他人会话数据。

校验策略与 WebSocket 路径（chat.py 的 _ws_load_session_owner_id）保持一致：
- session_id 为空或 'default' 时跳过（前端首次发消息时尚未创建会话）
- 查到 ConversationRecord 但 user_id 与当前用户不匹配时 raise 403
- 未查到记录时放行（首次消息会创建记录）
"""
from fastapi import HTTPException
from sqlalchemy.orm import Session

from db.models import ConversationRecord


def assert_session_owner(db: Session, session_id: str, user_id: int) -> None:
    """校验 session 归属于当前用户，不属于时 raise 403 session_owner_mismatch。

    Args:
        db: 请求级数据库会话
        session_id: 会话标识，为空或 'default' 时跳过校验
        user_id: 当前认证用户 ID

    Raises:
        HTTPException: 403 当会话记录存在且 user_id 与当前用户不匹配时
    """
    if not session_id or session_id == "default":
        return
    record = db.query(ConversationRecord).filter(
        ConversationRecord.session_id == session_id
    ).first()
    record_owner_id = str(getattr(record, "user_id", "") or "").strip()
    if record_owner_id and record_owner_id != str(user_id):
        raise HTTPException(
            status_code=403,
            detail={"code": "session_owner_mismatch", "message": "会话不属于当前用户"}
        )
