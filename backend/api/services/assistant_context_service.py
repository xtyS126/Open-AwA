"""会话级助手上下文的持久化、资源校验与 Agent 装配服务。"""

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Mapping

from sqlalchemy.orm import Session

from db.models import AgentRole, Conversation, LongTermMemory, Workspace


ASSISTANT_CONTEXT_METADATA_KEY = "assistant_context"
DEFAULT_WORKSPACE_ID = "default"


class AssistantContextResourceError(ValueError):
    """助手上下文引用了当前用户不可见或不存在的资源。"""


def _normalize_memory_ids(values: Any) -> list[int]:
    """把持久化值收敛为顺序稳定的正整数列表。"""
    if not isinstance(values, list):
        return []
    normalized: list[int] = []
    for value in values:
        if isinstance(value, bool):
            continue
        try:
            memory_id = int(value)
        except (TypeError, ValueError):
            continue
        if memory_id > 0 and memory_id not in normalized:
            normalized.append(memory_id)
    return normalized


def _normalize_optional_text(value: Any) -> str | None:
    """把可选标识规范为非空字符串或 None。"""
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def get_assistant_context(conversation: Conversation) -> Dict[str, Any]:
    """读取会话助手上下文；旧会话返回兼容默认值。"""
    metadata = conversation.conversation_metadata
    raw_context = metadata.get(ASSISTANT_CONTEXT_METADATA_KEY) if isinstance(metadata, dict) else None
    if not isinstance(raw_context, dict):
        raw_context = {}
    return {
        "role_id": _normalize_optional_text(raw_context.get("role_id")),
        "workspace_id": _normalize_optional_text(raw_context.get("workspace_id")) or DEFAULT_WORKSPACE_ID,
        "selected_memory_ids": _normalize_memory_ids(raw_context.get("selected_memory_ids")),
        "speaker_id": _normalize_optional_text(raw_context.get("speaker_id")),
    }


def _has_stored_assistant_context(conversation: Conversation) -> bool:
    """判断会话是否已有明确的助手上下文配置。"""
    metadata = conversation.conversation_metadata
    return isinstance(metadata, dict) and isinstance(
        metadata.get(ASSISTANT_CONTEXT_METADATA_KEY),
        dict,
    )


def _validate_role(db: Session, role_id: str | None, user_id: str) -> None:
    """角色仅允许预设、公开或当前用户创建的条目。"""
    if role_id is None:
        return
    role = db.query(AgentRole).filter(AgentRole.id == role_id).first()
    is_owner = role is not None and str(role.creator_id or "") == str(user_id)
    if role is None or not (role.is_preset or role.is_public or is_owner):
        raise AssistantContextResourceError("Assistant role is not available")


def _validate_workspace(db: Session, workspace_id: str, user_id: str) -> None:
    """工作区必须启用；声明 owner 的工作区还必须属于当前用户。"""
    workspace = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if workspace is None and workspace_id == DEFAULT_WORKSPACE_ID:
        return
    if workspace is None or not workspace.is_enabled:
        raise AssistantContextResourceError("Assistant workspace is not available")
    config = workspace.config_json if isinstance(workspace.config_json, dict) else {}
    owner_id = config.get("owner_id") or config.get("user_id")
    if owner_id is not None and str(owner_id) != str(user_id):
        raise AssistantContextResourceError("Assistant workspace is not available")


def _validate_memories(
    db: Session,
    memory_ids: Iterable[int],
    user_id: str,
    workspace_id: str,
) -> None:
    """所选记忆必须全部属于当前用户和工作区，且仍可注入模型。"""
    normalized_ids = list(memory_ids)
    if not normalized_ids:
        return
    visible_rows = (
        db.query(LongTermMemory.id)
        .filter(
            LongTermMemory.id.in_(normalized_ids),
            LongTermMemory.user_id == str(user_id),
            LongTermMemory.workspace_id == workspace_id,
            LongTermMemory.archive_status.notin_(["archived", "deprecated"]),
            LongTermMemory.state.notin_(["archived", "deprecated"]),
        )
        .all()
    )
    visible_ids = {int(row.id) for row in visible_rows}
    if visible_ids != set(normalized_ids):
        raise AssistantContextResourceError("Selected memory is not available")


def validate_assistant_context(
    db: Session,
    context: Mapping[str, Any],
    user_id: str,
    *,
    validate_workspace: bool = True,
) -> None:
    """集中校验上下文引用，供写入和聊天装配共同复用。"""
    role_id = _normalize_optional_text(context.get("role_id"))
    workspace_id = _normalize_optional_text(context.get("workspace_id")) or DEFAULT_WORKSPACE_ID
    memory_ids = _normalize_memory_ids(context.get("selected_memory_ids"))
    _validate_role(db, role_id, str(user_id))
    if validate_workspace:
        _validate_workspace(db, workspace_id, str(user_id))
    _validate_memories(db, memory_ids, str(user_id), workspace_id)


def patch_assistant_context(
    db: Session,
    conversation: Conversation,
    user_id: str,
    updates: Mapping[str, Any],
) -> Dict[str, Any]:
    """增量合并并持久化助手上下文，不覆盖其他会话元数据。"""
    current = get_assistant_context(conversation)
    if not updates:
        return current

    merged = dict(current)
    for key, value in updates.items():
        if key == "workspace_id":
            merged[key] = _normalize_optional_text(value) or DEFAULT_WORKSPACE_ID
        elif key == "selected_memory_ids":
            merged[key] = _normalize_memory_ids(value)
        elif key in {"role_id", "speaker_id"}:
            merged[key] = _normalize_optional_text(value)

    validate_workspace = (
        "workspace_id" in updates
        or bool(merged["selected_memory_ids"])
        or _has_stored_assistant_context(conversation)
    )
    validate_assistant_context(
        db,
        merged,
        str(user_id),
        validate_workspace=validate_workspace,
    )

    metadata = dict(conversation.conversation_metadata or {})
    metadata[ASSISTANT_CONTEXT_METADATA_KEY] = merged
    conversation.conversation_metadata = metadata
    conversation.updated_at = datetime.now(timezone.utc)
    return merged


def build_conversation_agent_context(
    db: Session,
    conversation: Conversation,
    user_id: str,
    base_context: Mapping[str, Any],
) -> Dict[str, Any]:
    """把已保存的角色、工作区和记忆选择装配到 Agent context。"""
    assistant_context = get_assistant_context(conversation)
    if _has_stored_assistant_context(conversation):
        validate_assistant_context(db, assistant_context, str(user_id))
    merged = dict(base_context)
    merged.update(
        {
            "role_id": assistant_context["role_id"],
            "workspace_id": assistant_context["workspace_id"],
            "selected_memory_ids": assistant_context["selected_memory_ids"],
        }
    )
    return merged


def build_session_agent_context(
    db: Session,
    session_id: str,
    user_id: str,
    base_context: Mapping[str, Any],
) -> Dict[str, Any]:
    """按会话标识装配 Agent 上下文，并保持首次会话的兼容默认值。"""
    conversation = (
        db.query(Conversation)
        .filter(Conversation.session_id == session_id)
        .first()
    )
    if conversation is None:
        merged = dict(base_context)
        merged.update(
            {
                "role_id": None,
                "workspace_id": DEFAULT_WORKSPACE_ID,
                "selected_memory_ids": [],
            }
        )
        return merged
    if str(conversation.user_id) != str(user_id):
        raise AssistantContextResourceError("Conversation is not available")
    return build_conversation_agent_context(
        db,
        conversation,
        str(user_id),
        base_context,
    )
