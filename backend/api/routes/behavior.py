"""
后端接口路由模块，负责接收请求、校验输入并协调业务层返回统一响应。
这些路由函数通常是前端或外部调用与后端内部能力之间的第一层行为边界。
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, Integer
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta, timezone
from loguru import logger
from db.models import get_db, BehaviorLog, User
from api.dependencies import get_current_user
from api.schemas import BehaviorStats


router = APIRouter(prefix="/behaviors", tags=["Behavior Analysis"])


@router.get("/stats", response_model=BehaviorStats)
async def get_behavior_stats(
    days: int = Query(7, ge=1, le=90),
    tz_offset: int = Query(
        0,
        ge=-720,
        le=840,
        description="用户时区相对 UTC 的分钟偏移（如 UTC+8 传 480），用于按本地时区聚合按天图表，避免 UTC 日期错位",
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    获取当前用户的行为统计数据，按用户ID过滤防止信息泄露。
    调用方通常依赖该结果继续进行后续判断、渲染或业务编排。

    时区处理：tz_offset 用于将 UTC 时间戳转换为用户本地时区后再按天聚合，
    避免 UTC+8 用户在凌晨 0-8 点产生的行为被错误归到前一天。
    SQL 层通过 SQLite ``datetime(timestamp, '+N minutes')`` 修饰符实现时区偏移。
    """
    import json
    # 多提前 1 天，避免用户本地"7天前 0 点"对应 UTC 的边界数据丢失
    start_date = datetime.now(timezone.utc) - timedelta(days=days + 1)
    
    # 性能优化：将 3 次独立 COUNT 查询合并为 1 次 GROUP BY 查询
    # 原实现 3 次往返 DB 各扫一遍索引，合并后单次扫描完成
    count_rows = db.query(
        BehaviorLog.action_type,
        func.count(BehaviorLog.id)
    ).filter(
        BehaviorLog.user_id == current_user.id,
        BehaviorLog.timestamp >= start_date,
        BehaviorLog.action_type.in_(["llm_call", "tool_usage", "error"])
    ).group_by(BehaviorLog.action_type).all()
    counts = {row[0]: row[1] for row in count_rows}

    # 所有查询添加用户ID过滤，防止跨用户数据泄露
    total_interactions = counts.get("llm_call", 0)
    total_tools_used = counts.get("tool_usage", 0)
    total_errors = counts.get("error", 0)
    
    # 工具使用分布统计 — 使用 SQL GROUP BY 替代 Python 循环分组
    tool_rows = db.query(
        BehaviorLog.details,
        func.count(BehaviorLog.id).label('cnt')
    ).filter(
        BehaviorLog.user_id == current_user.id,
        BehaviorLog.timestamp >= start_date,
        BehaviorLog.action_type == "tool_usage"
    ).group_by(BehaviorLog.details).order_by(func.count(BehaviorLog.id).desc()).limit(50).all()
    tool_counts: dict[str, int] = {}
    for details, cnt in tool_rows:
        tool_name = (details or "").split(":")[0] if ":" in (details or "") else "unknown"
        tool_counts[tool_name] = tool_counts.get(tool_name, 0) + cnt
    
    top_tools = [
        {"tool": tool, "count": count}
        for tool, count in sorted(tool_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    ]
    
    # 意图分布统计 — 使用 SQL GROUP BY 替代 Python 循环分组
    intent_rows = db.query(
        BehaviorLog.details,
        func.count(BehaviorLog.id).label('cnt')
    ).filter(
        BehaviorLog.user_id == current_user.id,
        BehaviorLog.timestamp >= start_date,
        BehaviorLog.action_type == "intent"
    ).group_by(BehaviorLog.details).order_by(func.count(BehaviorLog.id).desc()).limit(50).all()
    intent_counts: dict[str, int] = {}
    for details, cnt in intent_rows:
        intent_counts[details or "unknown"] = intent_counts.get(details or "unknown", 0) + cnt
    
    top_intents = [
        {"intent": intent, "count": count}
        for intent, count in sorted(intent_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    ]
    
    # LLM 调用统计 — 使用 SQL 聚合替代全量加载 + Python JSON 解析循环
    # 1. 按天聚合交互次数（chart_data）
    # 时区处理：通过 SQLite datetime(timestamp, '+N minutes') 修饰符将 UTC 时间戳
    # 转换为用户本地时区后再提取日期，避免凌晨 0-8 点行为被归到前一天
    tz_modifier = f"+{tz_offset} minutes" if tz_offset >= 0 else f"{tz_offset} minutes"
    local_day_expr = func.date(func.datetime(BehaviorLog.timestamp, tz_modifier))
    chart_rows = db.query(
        local_day_expr.label('day'),
        func.count(BehaviorLog.id).label('cnt')
    ).filter(
        BehaviorLog.user_id == current_user.id,
        BehaviorLog.timestamp >= start_date,
        BehaviorLog.action_type == "llm_call"
    ).group_by(local_day_expr).all()
    chart_data_map: dict[str, int] = {}
    # 用户本地时区的当前时间（UTC + tz_offset）
    now_local = datetime.now(timezone.utc) + timedelta(minutes=tz_offset)
    for i in range(days):
        day_str = (now_local - timedelta(days=i)).strftime("%Y-%m-%d")
        chart_data_map[day_str] = 0
    for row in chart_rows:
        day_str = str(row.day)
        # 仅保留最近 days 天的桶，超出范围（如多提前 1 天查到的数据）忽略
        if day_str in chart_data_map:
            chart_data_map[day_str] = row.cnt
    chart_data = [
        {"day": day, "interactions": count}
        for day, count in sorted(chart_data_map.items())
    ]

    # 2. 使用 SQLite json_extract 从 details JSON 中提取 model/provider 并分组
    model_rows = db.query(
        func.json_extract(BehaviorLog.details, '$.provider').label('provider'),
        func.json_extract(BehaviorLog.details, '$.model').label('model'),
        func.count(BehaviorLog.id).label('cnt')
    ).filter(
        BehaviorLog.user_id == current_user.id,
        BehaviorLog.timestamp >= start_date,
        BehaviorLog.action_type == "llm_call",
        BehaviorLog.details.isnot(None)
    ).group_by(
        func.json_extract(BehaviorLog.details, '$.provider'),
        func.json_extract(BehaviorLog.details, '$.model')
    ).order_by(func.count(BehaviorLog.id).desc()).limit(20).all()
    model_counts: dict[str, int] = {}
    for row in model_rows:
        provider = row.provider or "unknown"
        model_name = row.model or "unknown"
        display_name = f"{provider}/{model_name}"
        model_counts[display_name] = model_counts.get(display_name, 0) + row.cnt
    top_models = [
        {"tool": model, "count": count}
        for model, count in sorted(model_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    ]

    # 3. SQL 聚合计算平均响应时间
    duration_agg = db.query(
        func.avg(
            func.cast(func.json_extract(BehaviorLog.details, '$.duration_ms'), Integer)
        ).label('avg_duration_ms'),
        func.count(
            func.json_extract(BehaviorLog.details, '$.duration_ms')
        ).label('valid_count')
    ).filter(
        BehaviorLog.user_id == current_user.id,
        BehaviorLog.timestamp >= start_date,
        BehaviorLog.action_type == "llm_call",
        BehaviorLog.details.isnot(None)
    ).first()
    avg_duration_ms = float(duration_agg.avg_duration_ms or 0)
    avg_response_time = round(avg_duration_ms / 1000.0, 2)
    
    return {
        "total_interactions": total_interactions,
        "total_tools_used": total_tools_used,
        "total_errors": total_errors,
        "top_tools": top_tools,
        "top_models": top_models,
        "top_intents": top_intents,
        "average_response_time": avg_response_time,
        "chart_data": chart_data
    }


@router.get(
    "/logs",
    summary="获取行为日志",
    description="分页返回行为日志，可按行为类型筛选。"
)
async def get_behavior_logs(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    action_type: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> List[Dict[str, Any]]:
    """
    获取当前用户的行为日志，按用户ID过滤防止信息泄露。
    支持分页和按行为类型筛选。
    """
    query = db.query(BehaviorLog).filter(BehaviorLog.user_id == current_user.id)
    
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


@router.post(
    "/log",
    summary="记录行为日志",
    description="写入一条新的行为日志记录。"
)
async def log_behavior(
    action_type: str,
    details: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Dict[str, Any]:
    # 输入校验：防止超长字段写入
    if not action_type or len(action_type) > 64:
        raise HTTPException(status_code=400, detail="action_type 长度须为 1-64 个字符")
    if not details or len(details) > 4096:
        raise HTTPException(status_code=400, detail="details 长度须为 1-4096 个字符")

    log_entry = BehaviorLog(
        user_id=current_user.id,
        action_type=action_type,
        details=details
    )

    try:
        db.add(log_entry)
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.bind(error_type=type(exc).__name__).opt(exception=True).error(
            "行为日志写入失败"
        )
        raise HTTPException(status_code=500, detail="行为日志写入失败，请稍后重试") from exc

    return {"message": "Behavior logged successfully"}
