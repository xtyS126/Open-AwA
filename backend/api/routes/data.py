"""
交互数据查询和导出 API 路由。
"""

import csv
import io
import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from loguru import logger
from sqlalchemy import func
from sqlalchemy.orm import Session

from api.dependencies import get_current_user, get_db
from db.models import (
    ConversationData,
    ToolCallData,
    ExecutionTrace,
    RoleSwitchEvent,
    UserFeedback,
)

router = APIRouter(prefix="/data", tags=["data"])


@router.get("/stats")
async def get_stats(
    db: Session = Depends(get_db),
    current_user: Dict = Depends(get_current_user),
):
    """数据统计概览。"""
    conversation_count = db.query(func.count(ConversationData.id)).scalar() or 0
    tool_call_count = db.query(func.count(ToolCallData.id)).scalar() or 0
    trace_count = db.query(func.count(ExecutionTrace.id)).scalar() or 0
    feedback_count = db.query(func.count(UserFeedback.id)).scalar() or 0

    # 平均响应时间
    avg_response_time = db.query(
        func.avg(ConversationData.response_time_ms)
    ).scalar() or 0

    # 角色使用分布
    role_usage = (
        db.query(
            ConversationData.role_id,
            func.count(ConversationData.id).label("count")
        )
        .group_by(ConversationData.role_id)
        .all()
    )

    return {
        "conversation_count": conversation_count,
        "tool_call_count": tool_call_count,
        "trace_count": trace_count,
        "feedback_count": feedback_count,
        "avg_response_time_ms": round(avg_response_time, 1) if avg_response_time else 0,
        "role_usage": [
            {"role_id": r.role_id or "default", "count": r.count}
            for r in role_usage
        ],
    }


@router.get("/conversations")
async def list_conversations(
    role_id: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: Dict = Depends(get_current_user),
):
    """对话记录查询。"""
    query = db.query(ConversationData)

    if role_id:
        query = query.filter(ConversationData.role_id == role_id)
    if start_date:
        query = query.filter(ConversationData.created_at >= start_date)
    if end_date:
        query = query.filter(ConversationData.created_at <= end_date)

    total = query.count()
    items = query.order_by(ConversationData.created_at.desc()).offset(
        (page - 1) * page_size
    ).limit(page_size).all()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "id": item.id,
                "conversation_id": item.conversation_id,
                "role_id": item.role_id,
                "user_message": item.user_message[:200] if item.user_message else "",
                "assistant_message": item.assistant_message[:200] if item.assistant_message else "",
                "tools_used": item.tools_used,
                "model_used": item.model_used,
                "token_count": item.token_count,
                "response_time_ms": item.response_time_ms,
                "created_at": str(item.created_at) if item.created_at else None,
            }
            for item in items
        ],
    }


@router.get("/tool-calls")
async def list_tool_calls(
    role_id: Optional[str] = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: Dict = Depends(get_current_user),
):
    """工具调用日志查询。"""
    query = db.query(ToolCallData)

    if role_id:
        query = query.filter(ToolCallData.role_id == role_id)

    total = query.count()
    items = query.order_by(ToolCallData.created_at.desc()).offset(
        (page - 1) * page_size
    ).limit(page_size).all()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "id": item.id,
                "conversation_id": item.conversation_id,
                "role_id": item.role_id,
                "tool_name": item.tool_name,
                "tool_params": item.tool_params,
                "result_summary": item.result_summary[:200] if item.result_summary else "",
                "success": item.success,
                "duration_ms": item.duration_ms,
                "created_at": str(item.created_at) if item.created_at else None,
            }
            for item in items
        ],
    }


@router.get("/execution-traces")
async def list_execution_traces(
    role_id: Optional[str] = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: Dict = Depends(get_current_user),
):
    """执行轨迹查询。"""
    query = db.query(ExecutionTrace)

    if role_id:
        query = query.filter(ExecutionTrace.role_id == role_id)

    total = query.count()
    items = query.order_by(ExecutionTrace.created_at.desc()).offset(
        (page - 1) * page_size
    ).limit(page_size).all()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "id": item.id,
                "conversation_id": item.conversation_id,
                "role_id": item.role_id,
                "plan_steps": item.plan_steps,
                "executed_steps": item.executed_steps,
                "error_steps": item.error_steps,
                "retry_count": item.retry_count,
                "rollback_count": item.rollback_count,
                "total_duration_ms": item.total_duration_ms,
                "created_at": str(item.created_at) if item.created_at else None,
            }
            for item in items
        ],
    }


@router.get("/feedback")
async def list_feedback(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: Dict = Depends(get_current_user),
):
    """用户反馈查询。"""
    query = db.query(UserFeedback)

    total = query.count()
    items = query.order_by(UserFeedback.created_at.desc()).offset(
        (page - 1) * page_size
    ).limit(page_size).all()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "id": item.id,
                "session_id": item.session_id,
                "message_id": item.message_id,
                "user_id": item.user_id,
                "rating": item.rating,
                "comment": item.comment,
                "conversation_id": getattr(item, "conversation_id", ""),
                "role_id": getattr(item, "role_id", ""),
                "feedback_type": getattr(item, "feedback_type", ""),
                "created_at": str(item.created_at) if item.created_at else None,
            }
            for item in items
        ],
    }


@router.post("/export")
async def export_data(
    format: str = Query(default="json", description="导出格式: json 或 csv"),
    data_type: str = Query(default="conversations", description="数据类型"),
    role_id: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: Dict = Depends(get_current_user),
):
    """数据导出。"""
    if data_type == "conversations":
        query = db.query(ConversationData)
    elif data_type == "tool_calls":
        query = db.query(ToolCallData)
    elif data_type == "traces":
        query = db.query(ExecutionTrace)
    else:
        raise HTTPException(status_code=400, detail=f"不支持的数据类型: {data_type}")

    if role_id:
        query = query.filter(getattr(query.column_descriptions[0]["entity"], "role_id") == role_id)
    if start_date:
        query = query.filter(getattr(query.column_descriptions[0]["entity"], "created_at") >= start_date)
    if end_date:
        query = query.filter(getattr(query.column_descriptions[0]["entity"], "created_at") <= end_date)

    items = query.limit(1000).all()

    if format == "csv":
        output = io.StringIO()
        if items:
            writer = csv.DictWriter(output, fieldnames=items[0].__mapper__.columns.keys())
            writer.writeheader()
            for item in items:
                row = {c: getattr(item, c, "") for c in items[0].__mapper__.columns.keys()}
                writer.writerow(row)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={data_type}.csv"},
        )
    else:
        result = []
        for item in items:
            row = {}
            for c in item.__mapper__.columns.keys():
                val = getattr(item, c, None)
                if isinstance(val, datetime):
                    val = val.isoformat()
                row[c] = val
            result.append(row)
        return {"data": result, "count": len(result)}
