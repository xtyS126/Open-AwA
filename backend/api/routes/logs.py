"""
后端接口路由模块，负责接收请求、校验输入并协调业务层返回统一响应。
这些路由函数通常是前端或外部调用与后端内部能力之间的第一层行为边界。
"""

import time
from datetime import datetime, timezone
import json
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse
from loguru import logger
from pydantic import BaseModel, Field

from api.dependencies import get_current_user, get_optional_current_user
from config.logging import (
    get_error_summary,
    get_log_file_list,
    query_log_buffer,
    query_logs_by_request_id,
)
from db.models import User


router = APIRouter(prefix="/logs", tags=["System Logs"])


# 客户端错误上报速率限制：基于内存计数器实现，每 IP 每分钟最多上报次数
# 注：未认证端点暴露给匿名用户，必须限制速率以防止磁盘耗尽 DoS
_CLIENT_ERROR_RATE_LIMIT = 30
_CLIENT_ERROR_WINDOW_SECONDS = 60
# IP -> 该 IP 在窗口期内的时间戳列表
_client_error_timestamps: Dict[str, List[float]] = {}


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
    """
    处理query、logs相关逻辑，并为调用方返回对应结果。
    阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
    """
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
    """
    处理export、logs相关逻辑，并为调用方返回对应结果。
    阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
    """
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
        """
        处理iter、jsonl相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        for item in result["records"]:
            yield json.dumps(item, ensure_ascii=False, default=str) + "\n"

    filename = f"system_logs_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.jsonl"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(iter_jsonl(), media_type="application/x-ndjson", headers=headers)


@router.get("/trace/{request_id}")
async def trace_by_request_id(
    request_id: str,
    current_user: User = Depends(get_current_user),
):
    """
    根据 request_id 追踪单次请求的全部日志，
    用于排查某个请求从接收到响应的完整调用链路。
    """
    records = query_logs_by_request_id(request_id)
    logger.bind(
        event="logs_trace",
        module="logs",
        action="trace",
        request_id=request_id,
        user_id=current_user.id,
        result_count=len(records),
    ).info(f"按 request_id 追踪日志: {request_id}")
    return {"request_id": request_id, "total": len(records), "records": records}


@router.get("/errors/summary")
async def get_errors_summary(
    hours: int = Query(24, ge=1, le=720, description="统计最近 N 小时内的错误"),
    current_user: User = Depends(get_current_user),
):
    """
    汇总最近指定时间范围内的错误日志统计，
    包含错误数量、按模块分组、高频错误类型等。
    """
    summary = get_error_summary(hours=hours)
    logger.bind(
        event="logs_error_summary",
        module="logs",
        action="error_summary",
        user_id=current_user.id,
        hours=hours,
    ).info(f"查询错误摘要: 最近 {hours} 小时")
    return summary


@router.get("/files")
async def list_log_files(
    current_user: User = Depends(get_current_user),
):
    """
    列出日志目录中所有的日志文件，包含文件名、大小和修改时间。
    """
    files = get_log_file_list()
    return {"total": len(files), "files": files}


@router.get("/files/{filename}")
async def download_log_file(
    filename: str,
    current_user: User = Depends(get_current_user),
):
    """
    下载指定的日志文件。文件名仅允许合法字符，防止路径穿越攻击。
    """
    import os
    import re

    from config.settings import settings

    # 校验文件名：只允许字母、数字、下划线、连字符、点号
    if not re.match(r'^[\w\-\.]+$', filename):
        raise HTTPException(status_code=400, detail="文件名包含非法字符")

    log_dir = settings.LOG_DIR
    file_path = os.path.join(log_dir, filename)
    # 确保路径不会逃逸出日志目录
    real_log_dir = os.path.realpath(log_dir)
    real_file_path = os.path.realpath(file_path)
    if not real_file_path.startswith(real_log_dir):
        raise HTTPException(status_code=400, detail="非法文件路径")

    if not os.path.isfile(real_file_path):
        raise HTTPException(status_code=404, detail="日志文件不存在")

    return FileResponse(
        real_file_path,
        filename=filename,
        media_type="application/octet-stream",
    )


class ClientErrorReport(BaseModel):
    """前端错误上报数据模型"""
    # SEC-19: 所有字符串字段必须限制最大长度，防止未认证用户注入超长字符串导致磁盘耗尽
    level: str = Field(default="error", max_length=20)
    message: str = Field(..., max_length=5000)
    source: str = Field(default="", max_length=500)
    stack: str = Field(default="", max_length=20000)
    url: str = Field(default="", max_length=2000)
    user_agent: str = Field(default="", max_length=500)
    timestamp: str = Field(default="", max_length=100)
    extra: dict = Field(default_factory=dict)


@router.post("/client-errors")
async def report_client_error(
    request: Request,
    report: ClientErrorReport,
    current_user: Optional[User] = Depends(get_optional_current_user),
):
    """
    接收前端上报的错误信息，统一写入后端日志系统。
    使前端的 console.error 级别错误也能在后端日志中查看和分析。
    未登录用户也可上报错误，user_id 为 None。
    """
    # SEC-19: 基于 client IP 的速率限制，防止未认证用户高频上报导致磁盘耗尽
    client_ip = request.client.host if request.client else "unknown"
    now = time.time()
    window = _CLIENT_ERROR_WINDOW_SECONDS
    timestamps = _client_error_timestamps.get(client_ip, [])
    # 清理超出时间窗口的过期时间戳
    timestamps = [ts for ts in timestamps if now - ts < window]
    if len(timestamps) >= _CLIENT_ERROR_RATE_LIMIT:
        logger.bind(
            event="client_error_rate_limited",
            module="logs",
            client_ip=client_ip,
        ).warning(f"客户端错误上报被速率限制: {client_ip}")
        raise HTTPException(status_code=429, detail="错误上报过于频繁，请稍后再试")
    timestamps.append(now)
    _client_error_timestamps[client_ip] = timestamps

    # SEC-19: 限制 extra 字段序列化后字节数，防止超大字典导致日志膨胀
    extra_bytes = len(
        json.dumps(report.extra, ensure_ascii=False, default=str).encode("utf-8")
    )
    if extra_bytes > 10000:
        raise HTTPException(status_code=413, detail="extra 字段过大")

    level_name = str(report.level or "ERROR").strip().upper() or "ERROR"
    if level_name not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        level_name = "ERROR"

    logger.bind(
        event="client_error",
        module="frontend",
        error_source=report.source,
        url=report.url,
        user_id=current_user.id if current_user else None,
        user_agent=report.user_agent,
        client_timestamp=report.timestamp,
        client_extra=report.extra,
    ).log(level_name, f"[前端错误] {report.message}\n{report.stack}")
    return {"status": "received"}
