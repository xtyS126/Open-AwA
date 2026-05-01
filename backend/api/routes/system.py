"""
系统诊断路由 - 提供各子系统健康检查与状态查询，供测试任务使用。
"""

import os
import sys
import platform
import time
from typing import Dict, Any, List

from fastapi import APIRouter, Depends
from loguru import logger
from sqlalchemy import text

from api.dependencies import get_current_user
from db.models import User, SessionLocal
from config.settings import settings

router = APIRouter(prefix="/api/system", tags=["System Diagnostics"])


def _check_database() -> Dict[str, Any]:
    """
    检查数据库连接是否正常。
    """
    start = time.time()
    try:
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
        elapsed_ms = round((time.time() - start) * 1000, 2)
        return {"ok": True, "latency_ms": elapsed_ms, "error": None}
    except Exception as e:
        elapsed_ms = round((time.time() - start) * 1000, 2)
        logger.warning(f"数据库健康检查失败: {e}")
        return {"ok": False, "latency_ms": elapsed_ms, "error": str(e)}


def _check_plugins() -> Dict[str, Any]:
    """
    检查插件系统状态。
    """
    try:
        from plugins.plugin_instance import get
        manager = get()
        loaded_names = list(manager.loaded_plugins.keys())
        discovered = manager.discover_plugins()
        return {
            "ok": True,
            "loaded_count": len(loaded_names),
            "loaded_plugins": loaded_names,
            "discovered_count": len(discovered),
            "error": None,
        }
    except Exception as e:
        logger.warning(f"插件系统检查失败: {e}")
        return {"ok": False, "loaded_count": 0, "loaded_plugins": [], "discovered_count": 0, "error": str(e)}


def _check_skills() -> Dict[str, Any]:
    """
    检查技能系统状态。
    """
    try:
        from skills.skill_loader import SkillLoader
        loader = SkillLoader()
        skills = loader.list_skills()
        enabled_count = sum(1 for s in skills if s.get("enabled", True))
        return {
            "ok": True,
            "total_count": len(skills),
            "enabled_count": enabled_count,
            "error": None,
        }
    except Exception as e:
        logger.warning(f"技能系统检查失败: {e}")
        return {"ok": False, "total_count": 0, "enabled_count": 0, "error": str(e)}


def _check_mcp() -> Dict[str, Any]:
    """
    检查MCP服务器状态。
    """
    try:
        from mcp.manager import MCPManager
        manager = MCPManager()
        servers = manager.get_all_servers()
        connected = [s for s in servers if s.get("status") == "connected"]
        return {
            "ok": True,
            "total_servers": len(servers),
            "connected_count": len(connected),
            "error": None,
        }
    except Exception as e:
        logger.warning(f"MCP系统检查失败: {e}")
        return {"ok": False, "total_servers": 0, "connected_count": 0, "error": str(e)}


def _check_environment() -> Dict[str, Any]:
    """
    收集运行环境信息。
    """
    return {
        "python_version": sys.version,
        "platform": platform.platform(),
        "cwd": os.getcwd(),
        "env_mode": getattr(settings, "ENV_MODE", None) or os.environ.get("ENV_MODE", "unknown"),
    }


@router.get("/diagnostics")
async def system_diagnostics(
    current_user: User = Depends(get_current_user),
):
    """
    系统综合诊断端点，逐一检查各子系统状态并返回统一报告。
    供前端测试页面和自动化测试任务使用。
    """
    db_status = _check_database()
    plugins_status = _check_plugins()
    skills_status = _check_skills()
    mcp_status = _check_mcp()
    env_info = _check_environment()

    checks: List[Dict[str, Any]] = [
        {"name": "server", "label": "服务器基础健康", "ok": True, "detail": None},
        {"name": "database", "label": "数据库连接", "ok": db_status["ok"], "detail": db_status},
        {"name": "plugins", "label": "插件系统", "ok": plugins_status["ok"], "detail": plugins_status},
        {"name": "skills", "label": "技能系统", "ok": skills_status["ok"], "detail": skills_status},
        {"name": "mcp", "label": "MCP服务", "ok": mcp_status["ok"], "detail": mcp_status},
    ]

    all_ok = all(c["ok"] for c in checks)
    passed_count = sum(1 for c in checks if c["ok"])

    logger.bind(
        event="system_diagnostics",
        module="system",
        action="diagnostics",
        status="success" if all_ok else "warning",
        user_id=current_user.id,
        passed=passed_count,
        total=len(checks),
    ).info(f"系统诊断完成: {passed_count}/{len(checks)} 项通过")

    return {
        "timestamp": time.time(),
        "overall": "healthy" if all_ok else "degraded",
        "passed": passed_count,
        "total": len(checks),
        "checks": checks,
    }


@router.get("/ping")
async def ping():
    """
    轻量级连通性检查，无需认证。
    用于基础网络可达性验证。
    """
    return {"pong": True, "timestamp": time.time()}
