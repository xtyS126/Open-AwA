from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional
from datetime import datetime, timedelta
from db.models import get_db, BehaviorLog
from api.dependencies import get_current_user
from api.schemas import BehaviorStats


router = APIRouter(prefix="/behaviors", tags=["Behavior Analysis"])


@router.get("/stats", response_model=BehaviorStats)
async def get_behavior_stats(
    days: int = Query(7, ge=1, le=90),
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    start_date = datetime.utcnow() - timedelta(days=days)
    
    total_interactions = db.query(func.count(BehaviorLog.id)).filter(
        BehaviorLog.timestamp >= start_date
    ).scalar()
    
    tool_logs = db.query(BehaviorLog).filter(
        BehaviorLog.timestamp >= start_date,
        BehaviorLog.action_type == "tool_usage"
    ).all()
    total_tools_used = len(tool_logs)
    
    error_logs = db.query(BehaviorLog).filter(
        BehaviorLog.timestamp >= start_date,
        BehaviorLog.action_type == "error"
    ).all()
    total_errors = len(error_logs)
    
    tool_counts = {}
    for log in tool_logs:
        details = log.details or ""
        tool_name = details.split(":")[0] if ":" in details else "unknown"
        tool_counts[tool_name] = tool_counts.get(tool_name, 0) + 1
    
    top_tools = [
        {"tool": tool, "count": count}
        for tool, count in sorted(tool_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    ]
    
    intent_counts = {}
    intent_logs = db.query(BehaviorLog).filter(
        BehaviorLog.timestamp >= start_date,
        BehaviorLog.action_type == "intent"
    ).all()
    
    for log in intent_logs:
        details = log.details or "unknown"
        intent_counts[details] = intent_counts.get(details, 0) + 1
    
    top_intents = [
        {"intent": intent, "count": count}
        for intent, count in sorted(intent_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    ]
    
    avg_response_time = 1.5
    
    return BehaviorStats(
        total_interactions=total_interactions or 0,
        total_tools_used=total_tools_used,
        total_errors=total_errors,
        top_tools=top_tools,
        top_intents=top_intents,
        average_response_time=avg_response_time
    )


@router.get("/logs")
async def get_behavior_logs(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    action_type: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    query = db.query(BehaviorLog)
    
    if action_type:
        query = query.filter(BehaviorLog.action_type == action_type)
    
    logs = query.order_by(BehaviorLog.timestamp.desc()).offset(skip).limit(limit).all()
    
    return [
        {
            "id": log.id,
            "user_id": log.user_id,
            "action_type": log.action_type,
            "details": log.details,
            "timestamp": log.timestamp
        }
        for log in logs
    ]


@router.post("/log")
async def log_behavior(
    action_type: str,
    details: str,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    log_entry = BehaviorLog(
        user_id=current_user.id,
        action_type=action_type,
        details=details
    )
    
    db.add(log_entry)
    db.commit()
    
    return {"message": "Behavior logged successfully"}
