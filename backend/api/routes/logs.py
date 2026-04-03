from datetime import datetime, timezone
import json
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from loguru import logger

from api.dependencies import get_current_user
from config.logging import query_log_buffer
from db.models import User


router = APIRouter(prefix="/logs", tags=["System Logs"])


@router.get("")
async def query_logs(
    start_time: Optional[datetime] = Query(None),
    end_time: Optional[datetime] = Query(None),
    level: Optional[str] = Query(None),
    keyword: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
):
    result = query_log_buffer(
        start_time=start_time,
        end_time=end_time,
        level=level or "",
        keyword=keyword or "",
        limit=limit,
        offset=offset,
    )
    logger.bind(
        event="logs_query",
        module="logs",
        action="query",
        status="success",
        user_id=current_user.id,
        limit=limit,
        offset=offset,
        result_count=len(result["records"]),
    ).info("system logs queried")
    return result


@router.get("/export")
async def export_logs(
    start_time: Optional[datetime] = Query(None),
    end_time: Optional[datetime] = Query(None),
    level: Optional[str] = Query(None),
    keyword: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
):
    result = query_log_buffer(
        start_time=start_time,
        end_time=end_time,
        level=level or "",
        keyword=keyword or "",
        limit=5000,
        offset=0,
    )

    logger.bind(
        event="logs_export",
        module="logs",
        action="export",
        status="success",
        user_id=current_user.id,
        export_count=len(result["records"]),
    ).info("system logs exported")

    def iter_jsonl():
        for item in result["records"]:
            yield json.dumps(item, ensure_ascii=False, default=str) + "\n"

    filename = f"system_logs_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.jsonl"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(iter_jsonl(), media_type="application/x-ndjson", headers=headers)
