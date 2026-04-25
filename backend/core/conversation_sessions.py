"""
会话聚合服务，负责会话标题生成、摘要更新、软删除与恢复。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from db.models import Conversation, ConversationRecord, ShortTermMemory


DEFAULT_CONVERSATION_TITLE = "新对话"


def _normalize_session_id(session_id: Optional[str]) -> str:
    return str(session_id or "").strip()


def _is_default_session(session_id: Optional[str]) -> bool:
    return _normalize_session_id(session_id) in {"", "default"}


def _normalize_user_id(user_id: Optional[str]) -> str:
    return str(user_id or "").strip()


def _get_conversation_by_session_id(
    db: Session,
    session_id: str,
    *,
    include_deleted: bool = False,
) -> Optional[Conversation]:
    normalized_session_id = _normalize_session_id(session_id)
    if not normalized_session_id:
        return None
    query = db.query(Conversation).filter(Conversation.session_id == normalized_session_id)
    if not include_deleted:
        query = query.filter(Conversation.deleted_at.is_(None))
    return query.first()


def _get_record_owner(db: Session, session_id: str) -> str:
    normalized_session_id = _normalize_session_id(session_id)
    if not normalized_session_id:
        return ""
    record = (
        db.query(ConversationRecord)
        .filter(ConversationRecord.session_id == normalized_session_id)
        .order_by(ConversationRecord.timestamp.desc(), ConversationRecord.id.desc())
        .first()
    )
    if record is None:
        return ""
    return _normalize_user_id(record.user_id)


def _reconcile_conversation_owner(
    db: Session,
    conversation: Conversation,
    user_id: Optional[str],
    *,
    record_owner: str = "",
) -> Conversation:
    normalized_user_id = _normalize_user_id(user_id)
    normalized_conversation_owner = _normalize_user_id(conversation.user_id)
    resolved_owner = normalized_conversation_owner or record_owner

    if normalized_user_id and resolved_owner and resolved_owner != normalized_user_id:
        raise HTTPException(status_code=403, detail="Access denied: session does not belong to current user")

    target_owner = normalized_user_id or resolved_owner
    if target_owner and normalized_conversation_owner != target_owner:
        conversation.user_id = target_owner
        db.flush()

    return conversation


def build_conversation_title(content: Optional[str], fallback: str = DEFAULT_CONVERSATION_TITLE) -> str:
    text = str(content or "").strip()
    if not text:
        return fallback
    first_line = text.splitlines()[0].strip()
    if not first_line:
        return fallback
    return first_line[:80]


def build_conversation_preview(content: Optional[str], limit: int = 160) -> str:
    text = " ".join(str(content or "").split())
    return text[:limit]


def get_conversation(
    db: Session,
    session_id: str,
    user_id: Optional[str],
    *,
    include_deleted: bool = False,
) -> Optional[Conversation]:
    conversation = _get_conversation_by_session_id(db, session_id, include_deleted=include_deleted)
    if conversation is None:
        return None
    try:
        return _reconcile_conversation_owner(
            db,
            conversation,
            user_id,
            record_owner=_get_record_owner(db, session_id),
        )
    except HTTPException as exc:
        if exc.status_code == 403:
            return None
        raise


def get_conversation_or_404(
    db: Session,
    session_id: str,
    user_id: Optional[str],
    *,
    include_deleted: bool = False,
) -> Conversation:
    normalized_user_id = _normalize_user_id(user_id)
    conversation = _get_conversation_by_session_id(db, session_id, include_deleted=include_deleted)
    if conversation is None:
        record_owner = _get_record_owner(db, session_id)
        if record_owner and record_owner != normalized_user_id:
            raise HTTPException(status_code=403, detail="Access denied: session does not belong to current user")
        raise HTTPException(status_code=404, detail="Conversation not found")

    return _reconcile_conversation_owner(
        db,
        conversation,
        normalized_user_id,
        record_owner=_get_record_owner(db, session_id),
    )


def _apply_conversation_updates(
    db: Session,
    conversation: Conversation,
    *,
    generated_title: str,
    preview: str,
    role: Optional[str],
    occurred_at: datetime,
    increment_message_count: bool,
) -> Conversation:
    if conversation.deleted_at is not None:
        conversation.deleted_at = None
        conversation.restored_at = occurred_at
        conversation.purge_after = None

    if not conversation.title or conversation.title == DEFAULT_CONVERSATION_TITLE:
        conversation.title = generated_title
    if preview:
        conversation.summary = preview[:200]
        conversation.last_message_preview = preview[:500]
        conversation.last_message_role = role
        conversation.last_message_at = occurred_at
    if increment_message_count:
        conversation.message_count = int(conversation.message_count or 0) + 1
    conversation.updated_at = occurred_at
    db.flush()
    return conversation


def _raise_session_ownership_error() -> None:
        raise HTTPException(status_code=403, detail="Access denied: session does not belong to current user")


def ensure_conversation(
    db: Session,
    session_id: str,
    user_id: Optional[str],
    *,
    title: Optional[str] = None,
    content: Optional[str] = None,
    role: Optional[str] = None,
    occurred_at: Optional[datetime] = None,
    increment_message_count: bool = False,
) -> Optional[Conversation]:
    normalized_session_id = _normalize_session_id(session_id)
    normalized_user_id = _normalize_user_id(user_id)
    if _is_default_session(normalized_session_id):
        return None

    now = occurred_at or datetime.now(timezone.utc)
    record_owner = _get_record_owner(db, normalized_session_id)
    conversation = _get_conversation_by_session_id(db, normalized_session_id, include_deleted=True)
    generated_title = build_conversation_title(title or content)
    preview = build_conversation_preview(content)

    if conversation is None:
        if normalized_user_id and record_owner and record_owner != normalized_user_id:
            _raise_session_ownership_error()

        resolved_owner = normalized_user_id or record_owner
        if not resolved_owner:
            return None

        conversation = Conversation(
            session_id=normalized_session_id,
            user_id=resolved_owner,
            title=generated_title,
            summary=preview,
            last_message_preview=preview,
            last_message_role=role,
            message_count=1 if increment_message_count else 0,
            created_at=now,
            updated_at=now,
            last_message_at=now if preview else None,
            conversation_metadata={},
        )
        db.add(conversation)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            conversation = _get_conversation_by_session_id(db, normalized_session_id, include_deleted=True)
            if conversation is None:
                raise
            conversation = _reconcile_conversation_owner(
                db,
                conversation,
                normalized_user_id,
                record_owner=record_owner,
            )
        return _apply_conversation_updates(
            db,
            conversation,
            generated_title=generated_title,
            preview=preview,
            role=role,
            occurred_at=now,
            increment_message_count=increment_message_count,
        )

    conversation = _reconcile_conversation_owner(
        db,
        conversation,
        normalized_user_id,
        record_owner=record_owner,
    )
    return _apply_conversation_updates(
        db,
        conversation,
        generated_title=generated_title,
        preview=preview,
        role=role,
        occurred_at=now,
        increment_message_count=increment_message_count,
    )


def sync_conversation_message_count(db: Session, conversation: Conversation) -> Conversation:
    count = db.query(func.count(ShortTermMemory.id)).filter(
        ShortTermMemory.session_id == conversation.session_id
    ).scalar() or 0
    conversation.message_count = int(count)
    db.flush()
    return conversation


def soft_delete_conversation(
    db: Session,
    session_id: str,
    user_id: str,
    *,
    retention_days: int = 30,
) -> Conversation:
    conversation = get_conversation_or_404(db, session_id, user_id, include_deleted=True)
    now = datetime.now(timezone.utc)
    conversation.deleted_at = now
    conversation.purge_after = now + timedelta(days=max(1, retention_days))
    conversation.updated_at = now
    db.flush()
    return conversation


def restore_conversation(db: Session, session_id: str, user_id: str) -> Conversation:
    conversation = get_conversation_or_404(db, session_id, user_id, include_deleted=True)
    if conversation.deleted_at is None:
        return conversation
    now = datetime.now(timezone.utc)
    conversation.deleted_at = None
    conversation.restored_at = now
    conversation.purge_after = None
    conversation.updated_at = now
    db.flush()
    return conversation