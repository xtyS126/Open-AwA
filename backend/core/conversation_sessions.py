"""
会话聚合服务，负责会话标题生成、摘要更新、软删除与恢复。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger
from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.conversation_recorder import replay_transcript
from core.task_runtime.message_filters import (
    filter_orphaned_thinking_only_messages,
    filter_unresolved_tool_uses,
    filter_whitespace_only_assistant_messages,
)
from db.models import Conversation, ConversationRecord, SessionLocal, ShortTermMemory


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
            increment_message_count=False,
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
        ShortTermMemory.session_id == conversation.session_id,
        ShortTermMemory.workspace_id == "default",
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


# ---------------------------------------------------------------------------
# 会话恢复（--resume）相关实现
# ---------------------------------------------------------------------------


def load_conversation_for_resume(
    session_id: str,
    *,
    base_dir: Optional[str] = None,
    transcript_only: bool = False,
) -> List[Dict[str, Any]]:
    """
    从 JSONL 文件加载会话消息用于恢复，文件不存在时回退到数据库。

    优先使用 replay_transcript 从 JSONL 旁路日志加载完整消息列表；
    若 JSONL 文件不存在（返回空列表），则从 ConversationRecord 表按时间顺序
    构造消息列表作为回退。transcript_only=True 时跳过数据库回退（仅消费
    JSONL 旁路日志，供 agent 对话历史恢复路径使用，避免与短期记忆数据源漂移）。

    Args:
        session_id: 会话 ID。
        base_dir: JSONL 文件存放目录，默认为 None 时使用 replay_transcript 默认值。
        transcript_only: 为 True 时 JSONL 不存在直接返回空列表，不触发数据库回退。

    Returns:
        消息字典列表，每个字典至少包含 {role, content}；
        若会话为空或不存在则返回空列表。
    """
    normalized_session_id = _normalize_session_id(session_id)
    if not normalized_session_id:
        return []

    # 优先从 JSONL 文件加载
    transcript_records = replay_transcript(
        normalized_session_id,
        **({"base_dir": base_dir} if base_dir is not None else {}),
    )
    if transcript_records:
        return [
            _convert_transcript_record_to_message(record)
            for record in transcript_records
        ]

    if transcript_only:
        # 仅消费 JSONL 旁路日志，不触发数据库回退
        return []

    # JSONL 文件不存在时回退到数据库
    return _load_messages_from_db(normalized_session_id)


def _convert_transcript_record_to_message(record: Dict[str, Any]) -> Dict[str, Any]:
    """
    将 JSONL 记录转换为消息格式，type 字段映射为 role。

    Args:
        record: JSONL 记录，包含 {uuid, parent_uuid, type, content, timestamp}。

    Returns:
        消息字典，包含 {role, content} 及可选的 uuid/parent_uuid/timestamp。
    """
    message: Dict[str, Any] = {
        "role": record.get("type"),
        "content": record.get("content"),
    }
    if "uuid" in record:
        message["uuid"] = record["uuid"]
    if "parent_uuid" in record:
        message["parent_uuid"] = record["parent_uuid"]
    if "timestamp" in record:
        message["timestamp"] = record["timestamp"]
    return message


def _load_messages_from_db(session_id: str) -> List[Dict[str, Any]]:
    """
    从数据库 ConversationRecord 表加载会话消息作为回退。

    按 timestamp、id 升序遍历记录，每条记录贡献一条 user 消息（来自 user_message）
    和一条 assistant 消息（来自 llm_output）。

    Args:
        session_id: 会话 ID。

    Returns:
        消息字典列表。
    """
    db = SessionLocal()
    try:
        records = (
            db.query(ConversationRecord)
            .filter(ConversationRecord.session_id == session_id)
            .order_by(
                ConversationRecord.timestamp.asc(),
                ConversationRecord.id.asc(),
            )
            .all()
        )
        messages: List[Dict[str, Any]] = []
        for record in records:
            if record.user_message:
                messages.append({"role": "user", "content": record.user_message})
            if record.llm_output is not None:
                assistant_content = _extract_assistant_content(record.llm_output)
                if assistant_content is not None:
                    messages.append(
                        {"role": "assistant", "content": assistant_content}
                    )
        return messages
    finally:
        db.close()


def _extract_assistant_content(llm_output: Any) -> Any:
    """
    从 llm_output 中提取助手消息内容。

    llm_output 可能是 dict（JSON 列自动解析）或 str（序列化字符串）。
    对于 dict，优先提取 content/text/response 字段；对于 JSON 字符串，
    先解析再提取；对于普通字符串直接返回。

    Args:
        llm_output: 数据库中存储的 LLM 输出。

    Returns:
        提取后的助手消息内容。
    """
    if isinstance(llm_output, str):
        try:
            parsed = json.loads(llm_output)
            return _extract_assistant_content(parsed)
        except (json.JSONDecodeError, TypeError):
            return llm_output
    if isinstance(llm_output, dict):
        for key in ("content", "text", "response"):
            if key in llm_output:
                return llm_output[key]
        return llm_output
    return llm_output


def deserialize_messages_with_interrupt_detection(
    messages: List[Dict[str, Any]],
    session_id: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], bool]:
    """
    五层过滤管道，依次执行附件迁移、未完成 tool_use 过滤、孤立 thinking 过滤、
    空白 assistant 过滤，并检测会话中断。中断时在末尾注入续接 prompt。

    五层管道：
    1. 迁移旧附件格式（顶层 attachments 字段转换为 content 内容块）
    2. filter_unresolved_tool_uses: 移除未完成的 tool_use 块
    3. filter_orphaned_thinking_only_messages: 移除只含 thinking 的孤立消息
    4. filter_whitespace_only_assistant_messages: 移除空白助手消息
    5. 检测中断：最后一条为 user 消息或 assistant 含未完成 tool_use

    注意：中断检测在过滤前执行，因为 filter_unresolved_tool_uses 会移除
    未完成 tool_use 块，过滤后无法再检测到该中断场景。

    Args:
        messages: 原始消息列表。
        session_id: 会话 ID，用于日志记录（可选）。

    Returns:
        (filtered_messages, was_interrupted) 元组：
        - filtered_messages: 过滤后的消息列表，中断时末尾含续接 prompt。
        - was_interrupted: 是否检测到中断。
    """
    # 第 1 层：迁移旧附件格式
    migrated = _migrate_legacy_attachments(messages)

    # 第 5 层：检测中断（在过滤前检测，以便捕获未完成 tool_use）
    was_interrupted = _detect_interruption(migrated)

    # 第 2 层：过滤未完成 tool_use
    filtered = filter_unresolved_tool_uses(migrated)

    # 第 3 层：过滤孤立 thinking
    filtered = filter_orphaned_thinking_only_messages(filtered)

    # 第 4 层：过滤空白 assistant
    filtered = filter_whitespace_only_assistant_messages(filtered)

    # 中断时注入续接 prompt
    if was_interrupted:
        filtered = list(filtered)
        filtered.append(
            {"role": "user", "content": "Continue from where you left off."}
        )
        normalized_session_id = _normalize_session_id(session_id)
        logger.info(
            f"检测到会话中断，注入续接 prompt，session_id={normalized_session_id}"
        )

    return filtered, was_interrupted


def _migrate_legacy_attachments(
    messages: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    迁移旧附件格式，将消息顶层 attachments 字段转换为 content 内容块。

    旧格式: {"role": "user", "content": "文本", "attachments": [...]}
    新格式: {"role": "user", "content": [{"type": "text", "text": "文本"}, {"type": "image", ...}]}

    无 attachments 字段的消息直接浅拷贝保留，不修改原列表。

    Args:
        messages: 原始消息列表。

    Returns:
        迁移后的新消息列表，原列表不会被修改。
    """
    migrated: List[Dict[str, Any]] = []
    for message in messages:
        attachments = message.get("attachments")
        # 无附件或附件格式异常，直接浅拷贝保留
        if not attachments or not isinstance(attachments, list):
            migrated.append(dict(message))
            continue

        # 构造新消息，移除顶层 attachments 字段
        new_message = {k: v for k, v in message.items() if k != "attachments"}
        content = new_message.get("content")

        # 将 content 转为内容块列表
        content_blocks: List[Dict[str, Any]] = []
        if isinstance(content, str) and content:
            content_blocks.append({"type": "text", "text": content})
        elif isinstance(content, list):
            content_blocks.extend(content)

        # 将附件追加为内容块（采用 Anthropic 风格格式）
        for att in attachments:
            if not isinstance(att, dict):
                continue
            att_type = att.get("type", "")
            mime = att.get("mime_type", "")
            data = att.get("data", "")
            if att_type in ("image", "audio", "video"):
                content_blocks.append(
                    {
                        "type": att_type,
                        "source": {
                            "type": "base64",
                            "media_type": mime,
                            "data": data,
                        },
                    }
                )

        new_message["content"] = content_blocks
        migrated.append(new_message)

    return migrated


def _detect_interruption(messages: List[Dict[str, Any]]) -> bool:
    """
    检测会话是否被中断。

    中断条件：
    1. 最后一条消息是 user 消息（用户发送后未收到 AI 响应）。
    2. 最后一条消息是 assistant 消息且含未完成 tool_use
       （AI 调用工具时被中断，没有对应的 tool 结果消息）。

    Args:
        messages: 待检测的消息列表。

    Returns:
        检测到中断返回 True，否则返回 False。
    """
    if not messages:
        return False

    last_message = messages[-1]
    last_role = last_message.get("role")

    # 条件 1: 最后一条是 user 消息
    if last_role == "user":
        return True

    # 条件 2: 最后一条是 assistant 消息且含未完成 tool_use
    if last_role == "assistant":
        content = last_message.get("content")
        if isinstance(content, list):
            # 收集所有已存在的 tool 结果 ID
            resolved_tool_call_ids: set = {
                msg.get("tool_call_id")
                for msg in messages
                if msg.get("role") == "tool"
                and msg.get("tool_call_id") is not None
            }
            for item in content:
                if (
                    isinstance(item, dict)
                    and item.get("type") == "tool_use"
                ):
                    tool_use_id = item.get("id")
                    if tool_use_id not in resolved_tool_call_ids:
                        return True

    return False