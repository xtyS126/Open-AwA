from datetime import datetime, timedelta, timezone
import json
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from api.dependencies import get_current_user
from core.conversation_recorder import conversation_recorder
from db.models import ConversationRecord, User, get_db


router = APIRouter(prefix="/conversations", tags=["Conversations"])


def _safe_deserialize(value: Optional[str]) -> Any:
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _to_dict(record: ConversationRecord) -> Dict[str, Any]:
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


@router.get("/records")
async def get_records_preview(
    limit: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    records = (
        db.query(ConversationRecord)
        .filter(ConversationRecord.user_id == current_user.id)
        .order_by(ConversationRecord.timestamp.desc())
        .limit(limit)
        .all()
    )

    return {
        "records": [_to_dict(item) for item in records],
        "count": len(records),
        "limit": limit,
    }


@router.get("/export")
async def export_records_jsonl(
    start_time: Optional[datetime] = Query(None),
    end_time: Optional[datetime] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(ConversationRecord).filter(ConversationRecord.user_id == current_user.id)

    if start_time is not None:
        query = query.filter(ConversationRecord.timestamp >= start_time)
    if end_time is not None:
        query = query.filter(ConversationRecord.timestamp <= end_time)

    query = query.order_by(ConversationRecord.timestamp.asc())

    def iter_jsonl():
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
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    deleted = (
        db.query(ConversationRecord)
        .filter(ConversationRecord.user_id == current_user.id)
        .filter(ConversationRecord.timestamp < cutoff)
        .delete(synchronize_session=False)
    )
    db.commit()

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
    return {
        "enabled": conversation_recorder.is_collection_enabled(current_user=current_user),
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
    updated = conversation_recorder.set_collection_enabled(enabled=enabled, current_user=current_user)
    if not updated:
        raise HTTPException(status_code=400, detail="更新收集开关失败")

    return {
        "success": True,
        "enabled": conversation_recorder.is_collection_enabled(current_user=current_user),
    }
