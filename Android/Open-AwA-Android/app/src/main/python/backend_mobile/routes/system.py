"""
系统路由 - 健康检查、系统信息

与桌面版 backend/api/routes/system.py 的差异：
- 移除环境变量管理（移动端不暴露环境变量）
- 移除插件系统检查（移动端无插件系统）
- 移除向量库检查（移动端使用远程后端做向量检索）
"""

import platform
import sys
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter

from ..config import get_settings
from ..db import get_engine

router = APIRouter(prefix="/api/system", tags=["System"])


@router.get("/ping")
async def ping() -> Dict[str, Any]:
    """健康检查端点"""
    settings = get_settings()
    return {
        "status": "ok",
        "platform": settings.platform,
        "backend": "embedded",
        "version": settings.version,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/info")
async def system_info() -> Dict[str, Any]:
    """系统信息端点"""
    settings = get_settings()
    return {
        "platform": settings.platform,
        "python_version": sys.version,
        "platform_detail": platform.platform(),
        "backend_mode": "embedded",
        "version": settings.version,
        "environment": settings.environment,
        "data_dir": str(settings.data_dir),
        "features": {
            "auth": True,
            "chat": True,
            "memory": False,  # 阶段 2 暂未实现
            "skills": False,
            "billing": False,
            "plugins": False,  # 桌面专属
            "terminal": False,  # 桌面专属
            "acp": False,  # 桌面专属
        },
    }


@router.get("/health")
async def health() -> Dict[str, Any]:
    """
    健康检查（含数据库连通性）

    返回各子系统的健康状态。
    """
    checks: Dict[str, Any] = {}

    # 数据库检查
    try:
        engine = get_engine()
        from sqlalchemy import text
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        checks["database"] = {"ok": True, "error": None}
    except Exception as e:
        checks["database"] = {"ok": False, "error": str(e)}

    # 综合状态
    all_ok = all(c.get("ok", False) for c in checks.values())
    return {
        "status": "ok" if all_ok else "degraded",
        "checks": checks,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
