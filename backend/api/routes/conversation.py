"""
后端接口路由模块，负责接收请求、校验输入并协调业务层返回统一响应。
这些路由函数通常是前端或外部调用与后端内部能力之间的第一层行为边界。
"""

from datetime import datetime, timedelta, timezone
import json
from typing import Any, Dict, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from loguru import logger
from sqlalchemy import or_
from sqlalchemy.orm import Session

from api.dependencies import get_current_user
from api.schemas import (
    ConversationSessionBatchDeleteRequest,
    ConversationSessionCreate,
    ConversationSessionListResponse,
    ConversationSessionRenameRequest,
    ConversationSessionResponse,
)
from core.conversation_sessions import (
    DEFAULT_CONVERSATION_TITLE,
    ensure_conversation,
    get_conversation_or_404,
    restore_conversation,
    soft_delete_conversation,
)
from core.conversation_recorder import conversation_recorder
from db.models import Conversation, ConversationRecord, User, get_db


router = APIRouter(prefix="/conversations", tags=["Conversations"])


def _safe_deserialize(value: Optional[str]) -> Any:
    """
    处理safe、deserialize相关逻辑，并为调用方返回对应结果。
    阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
    """
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _to_dict(record: ConversationRecord) -> Dict[str, Any]:
    """
    处理to、dict相关逻辑，并为调用方返回对应结果。
    阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
    """
    return {
        "id": record.id,
        "session_id": record.session_id,
        "user_id": record.user_id,
        "node_type": record.node_type,
        "user_message": record.user_message,
        "timestamp": record.timestamp.isoformat() if record.timestamp else None,
        "provider": record.provider,
        "model": record.model,
        "llm_input": _safe_deserialize(record.llm_input),
        "llm_output": _safe_deserialize(record.llm_output),
        "llm_tokens_used": record.llm_tokens_used,
        "execution_duration_ms": record.execution_duration_ms,
        "status": record.status,
        "error_message": record.error_message,
        "metadata": _safe_deserialize(record.record_metadata),
    }


def _serialize_conversation(conversation: Conversation) -> Dict[str, Any]:
    """
    将会话聚合对象序列化为前端所需结构。
    """
    return {
        "session_id": conversation.session_id,
        "user_id": conversation.user_id,
        "title": (conversation.title or "").strip() or DEFAULT_CONVERSATION_TITLE,
        "summary": conversation.summary or "",
        "last_message_preview": conversation.last_message_preview or "",
        "last_message_role": conversation.last_message_role,
        "message_count": int(conversation.message_count or 0),
        "created_at": conversation.created_at,
        "updated_at": conversation.updated_at,
        "last_message_at": conversation.last_message_at,
        "deleted_at": conversation.deleted_at,
        "restored_at": conversation.restored_at,
        "purge_after": conversation.purge_after,
        "conversation_metadata": conversation.conversation_metadata or {},
    }


@router.get("", response_model=ConversationSessionListResponse)
async def list_sessions(
    search: Optional[str] = Query(None),
    sort_by: str = Query("last_message_at", pattern="^(title|created_at|updated_at|last_message_at|message_count)$"),
    sort_order: str = Query("desc", pattern="^(asc|desc)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    include_deleted: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    返回当前用户的会话列表，支持搜索、排序与分页。
    """
    query = db.query(Conversation).filter(Conversation.user_id == current_user.id)
    if not include_deleted:
        query = query.filter(Conversation.deleted_at.is_(None))

    normalized_search = str(search or "").strip()
    if normalized_search:
        like_pattern = f"%{normalized_search}%"
        query = query.filter(
            or_(
                Conversation.title.ilike(like_pattern),
                Conversation.summary.ilike(like_pattern),
                Conversation.last_message_preview.ilike(like_pattern),
                Conversation.session_id.ilike(like_pattern),
            )
        )

    sort_column = {
        "title": Conversation.title,
        "created_at": Conversation.created_at,
        "updated_at": Conversation.updated_at,
        "last_message_at": Conversation.last_message_at,
        "message_count": Conversation.message_count,
    }[sort_by]
    order_expression = sort_column.asc() if sort_order == "asc" else sort_column.desc()
    query = query.order_by(order_expression, Conversation.updated_at.desc(), Conversation.id.desc())

    total = query.count()
    offset = (page - 1) * page_size
    items = query.offset(offset).limit(page_size).all()

    logger.bind(
        event="conversation_session_list_loaded",
        module="conversation",
        action="list_sessions",
        status="success",
        user_id=current_user.id,
        total=total,
        page=page,
        page_size=page_size,
        include_deleted=include_deleted,
    ).info("conversation session list loaded")

    return {
        "items": [_serialize_conversation(item) for item in items],
        "total": total,
        "page": page,
        "page_size": page_size,
        "has_more": offset + len(items) < total,
    }


@router.post("", response_model=ConversationSessionResponse)
async def create_session(
    payload: ConversationSessionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    创建新的用户会话，或在指定会话存在时返回该会话。
    """
    requested_session_id = str(payload.session_id or "").strip()
    if not requested_session_id or requested_session_id == "default":
        requested_session_id = uuid.uuid4().hex

    conversation = ensure_conversation(
        db,
        session_id=requested_session_id,
        user_id=current_user.id,
        title=payload.title,
    )
    if conversation is None:
        raise HTTPException(status_code=400, detail="Failed to create conversation")

    normalized_title = str(payload.title or "").strip()
    if normalized_title:
        conversation.title = normalized_title[:200]
        conversation.updated_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(conversation)

    logger.bind(
        event="conversation_session_created",
        module="conversation",
        action="create_session",
        status="success",
        user_id=current_user.id,
        session_id=conversation.session_id,
    ).info("conversation session created")

    return _serialize_conversation(conversation)


@router.get("/records")
async def get_records_preview(
    limit: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    获取records、preview相关数据或当前状态。
    调用方通常依赖该结果继续进行后续判断、渲染或业务编排。
    """
    records = (
        db.query(ConversationRecord)
        .filter(ConversationRecord.user_id == current_user.id)
        .order_by(ConversationRecord.timestamp.desc())
        .limit(limit)
        .all()
    )

    logger.bind(
        event="conversation_records_preview",
        module="conversation",
        action="records_preview",
        status="success",
        user_id=current_user.id,
        count=len(records),
        limit=limit,
    ).info("conversation records preview loaded")

    return {
        "records": [_to_dict(item) for item in records],
        "count": len(records),
        "limit": limit,
    }


@router.post("/batch-delete", response_model=ConversationSessionListResponse)
async def batch_delete_sessions(
    payload: ConversationSessionBatchDeleteRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    批量软删除会话，并返回本次更新后的会话条目。
    """
    updated_items = []
    for session_id in payload.session_ids:
        conversation = soft_delete_conversation(
            db,
            session_id=session_id,
            user_id=current_user.id,
            retention_days=payload.retention_days,
        )
        updated_items.append(conversation)

    db.commit()
    for conversation in updated_items:
        db.refresh(conversation)

    logger.bind(
        event="conversation_session_batch_deleted",
        module="conversation",
        action="batch_delete_sessions",
        status="success",
        user_id=current_user.id,
        count=len(updated_items),
    ).info("conversation sessions batch deleted")

    return {
        "items": [_serialize_conversation(item) for item in updated_items],
        "total": len(updated_items),
        "page": 1,
        "page_size": len(updated_items),
        "has_more": False,
    }


@router.get("/export")
async def export_records_jsonl(
    start_time: Optional[datetime] = Query(None),
    end_time: Optional[datetime] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    处理export、records、jsonl相关逻辑，并为调用方返回对应结果。
    阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
    """
    query = db.query(ConversationRecord).filter(ConversationRecord.user_id == current_user.id)

    if start_time is not None:
        query = query.filter(ConversationRecord.timestamp >= start_time)
    if end_time is not None:
        query = query.filter(ConversationRecord.timestamp <= end_time)

    query = query.order_by(ConversationRecord.timestamp.asc())

    logger.bind(
        event="conversation_export_started",
        module="conversation",
        action="export_jsonl",
        status="start",
        user_id=current_user.id,
        has_start_time=bool(start_time),
        has_end_time=bool(end_time),
    ).info("conversation export started")

    def iter_jsonl():
        """
        处理iter、jsonl相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        for record in query.yield_per(200):
            payload = _to_dict(record)
            yield json.dumps(payload, ensure_ascii=False, default=str) + "\n"

    filename = f"conversation_records_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.jsonl"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}

    return StreamingResponse(iter_jsonl(), media_type="application/x-ndjson", headers=headers)


@router.delete(
    "/records/cleanup",
    summary="清理会话记录",
    description="删除指定天数之前的会话采集记录。"
)
async def cleanup_records(
    days: int = Query(30, ge=0, le=3650),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    处理cleanup、records相关逻辑，并为调用方返回对应结果。
    阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    deleted = (
        db.query(ConversationRecord)
        .filter(ConversationRecord.user_id == current_user.id)
        .filter(ConversationRecord.timestamp < cutoff)
        .delete(synchronize_session=False)
    )
    db.commit()

    logger.bind(
        event="conversation_cleanup_done",
        module="conversation",
        action="cleanup",
        status="success",
        user_id=current_user.id,
        days=days,
        deleted_count=deleted,
    ).info("conversation cleanup completed")

    return {
        "success": True,
        "deleted_count": deleted,
        "days": days,
    }


@router.get(
    "/collection-status",
    summary="获取采集状态",
    description="返回当前用户的会话数据采集开关状态与运行时统计。"
)
async def get_collection_status(current_user: User = Depends(get_current_user)):
    """
    获取collection、status相关数据或当前状态。
    调用方通常依赖该结果继续进行后续判断、渲染或业务编排。
    """
    enabled = conversation_recorder.is_collection_enabled(current_user=current_user)
    logger.bind(
        event="conversation_collection_status",
        module="conversation",
        action="get_collection_status",
        status="success",
        user_id=current_user.id,
        enabled=enabled,
    ).info("conversation collection status loaded")

    return {
        "enabled": enabled,
        "stats": conversation_recorder.get_runtime_stats(),
    }


@router.put(
    "/collection-status",
    summary="更新采集状态",
    description="开启或关闭当前用户的会话数据采集功能。"
)
async def update_collection_status(
    enabled: bool,
    current_user: User = Depends(get_current_user),
):
    """
    更新collection、status相关数据、配置或状态。
    阅读时需要重点关注覆盖规则、副作用以及更新后的数据一致性。
    """
    updated = conversation_recorder.set_collection_enabled(enabled=enabled, current_user=current_user)
    if not updated:
        logger.bind(
            event="conversation_collection_status_update_failed",
            module="conversation",
            action="set_collection_status",
            status="failure",
            user_id=current_user.id,
            enabled=enabled,
        ).warning("conversation collection status update failed")
        raise HTTPException(status_code=400, detail="更新收集开关失败")

    logger.bind(
        event="conversation_collection_status_updated",
        module="conversation",
        action="set_collection_status",
        status="success",
        user_id=current_user.id,
        enabled=enabled,
    ).info("conversation collection status updated")

    return {
        "success": True,
        "enabled": conversation_recorder.is_collection_enabled(current_user=current_user),
    }


@router.patch("/{session_id}", response_model=ConversationSessionResponse)
async def rename_session(
    session_id: str,
    payload: ConversationSessionRenameRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    更新指定会话标题。
    """
    title = payload.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="Conversation title cannot be empty")

    conversation = get_conversation_or_404(db, session_id, current_user.id, include_deleted=True)
    conversation.title = title[:200]
    conversation.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(conversation)

    logger.bind(
        event="conversation_session_renamed",
        module="conversation",
        action="rename_session",
        status="success",
        user_id=current_user.id,
        session_id=session_id,
    ).info("conversation session renamed")

    return _serialize_conversation(conversation)


@router.delete("/{session_id}", response_model=ConversationSessionResponse)
async def delete_session(
    session_id: str,
    retention_days: int = Query(30, ge=1, le=3650),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    软删除指定会话。
    """
    conversation = soft_delete_conversation(
        db,
        session_id=session_id,
        user_id=current_user.id,
        retention_days=retention_days,
    )
    db.commit()
    db.refresh(conversation)

    logger.bind(
        event="conversation_session_deleted",
        module="conversation",
        action="delete_session",
        status="success",
        user_id=current_user.id,
        session_id=session_id,
        retention_days=retention_days,
    ).info("conversation session deleted")

    return _serialize_conversation(conversation)


@router.post("/{session_id}/restore", response_model=ConversationSessionResponse)
async def restore_session_route(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    恢复已软删除的会话。
    """
    conversation = restore_conversation(db, session_id, current_user.id)
    db.commit()
    db.refresh(conversation)

    logger.bind(
        event="conversation_session_restored",
        module="conversation",
        action="restore_session",
        status="success",
        user_id=current_user.id,
        session_id=session_id,
    ).info("conversation session restored")

    return _serialize_conversation(conversation)
