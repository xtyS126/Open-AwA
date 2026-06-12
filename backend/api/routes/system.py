"""
系统诊断路由 - 提供各子系统健康检查与状态查询，供测试任务使用。
"""

import ipaddress
import os
import sys
import platform
import time
from typing import Dict, Any, List
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from pydantic import BaseModel, Field, SecretStr
from sqlalchemy import text

from api.dependencies import get_current_user, get_current_admin_user
from db.models import User, SessionLocal
from config.settings import settings

router = APIRouter(prefix="/api/system", tags=["System Diagnostics"])

# 环境变量元数据 — 模块级单一数据源，派生 ALLOWED_ENV_VARS 和 TESTABLE_ENV_VARS
# DATABASE_URL 不允许运行时热更新（修改后需重启连接池），SECRET_KEY 完全不在列表中暴露
ENV_VAR_META = [
    {"name": "OPENAI_API_KEY", "category": "llm", "description": "OpenAI 平台的 API 金钥", "is_sensitive": True, "allow_update": True, "allow_test": True},
    {"name": "ANTHROPIC_API_KEY", "category": "llm", "description": "Anthropic Claude 平台的 API 金钥", "is_sensitive": True, "allow_update": True, "allow_test": True},
    {"name": "DEEPSEEK_API_KEY", "category": "llm", "description": "DeepSeek 平台的 API 金钥", "is_sensitive": True, "allow_update": True, "allow_test": True},
    {"name": "QWEN_API_KEY", "category": "llm", "description": "通义千问平台的 API 金钥", "is_sensitive": True, "allow_update": True, "allow_test": True},
    {"name": "ZHIPU_API_KEY", "category": "llm", "description": "智谱 AI 平台的 API 金钥", "is_sensitive": True, "allow_update": True, "allow_test": True},
    {"name": "MOONSHOT_API_KEY", "category": "llm", "description": "Moonshot Kimi 平台的 API 金钥", "is_sensitive": True, "allow_update": True, "allow_test": True},
    {"name": "OLLAMA_BASE_URL", "category": "llm", "description": "Ollama 本地服务的基础 URL 地址", "is_sensitive": False, "allow_update": True, "allow_test": False},
    {"name": "QWEN_BASE_URL", "category": "llm", "description": "通义千问服务的基础 URL 地址", "is_sensitive": False, "allow_update": True, "allow_test": False},
    {"name": "ZHIPU_BASE_URL", "category": "llm", "description": "智谱 AI 服务的基础 URL 地址", "is_sensitive": False, "allow_update": True, "allow_test": False},
    {"name": "MOONSHOT_BASE_URL", "category": "llm", "description": "Moonshot Kimi 服务的基础 URL 地址", "is_sensitive": False, "allow_update": True, "allow_test": False},
    {"name": "DATABASE_URL", "category": "storage", "description": "主数据库的 SQLAlchemy 连接 URL（运行时修改后需重启服务以重建连接池）", "is_sensitive": True, "allow_update": False, "allow_test": False},
    {"name": "VECTOR_DB_PATH", "category": "storage", "description": "矢量知识库存储文件的绝对路径", "is_sensitive": False, "allow_update": True, "allow_test": False},
    {"name": "ENVIRONMENT", "category": "general", "description": "当前系统的运行环境名称 (development/production)", "is_sensitive": False, "allow_update": True, "allow_test": False},
    {"name": "LOG_LEVEL", "category": "general", "description": "控制台日志的全局输出等级 (DEBUG/INFO/WARNING/ERROR)", "is_sensitive": False, "allow_update": True, "allow_test": False},
]

ALLOWED_ENV_VARS = {v["name"] for v in ENV_VAR_META if v.get("allow_update")}
TESTABLE_ENV_VARS = {v["name"] for v in ENV_VAR_META if v.get("allow_test")}


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
        db = SessionLocal()
        try:
            loader = SkillLoader(db_session=db)
            skills = loader.list_skills()
            enabled_count = sum(1 for s in skills if s.get("enabled", True))
            return {
                "ok": True,
                "total_count": len(skills),
                "enabled_count": enabled_count,
                "error": None,
            }
        finally:
            db.close()
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


class EnvVarUpdatePayload(BaseModel):
    name: str
    value: str = Field(..., min_length=1, max_length=4096, description="环境变量值")


@router.get("/env-vars")
async def list_env_vars(current_user: User = Depends(get_current_admin_user)):
    """
    获取系统环境变量列表（基于模块级 ENV_VAR_META 单一数据源）。
    """
    result = []
    for var in ENV_VAR_META:
        name = var["name"]
        raw_val = os.environ.get(name)
        if raw_val is None:
            raw_val = getattr(settings, name, "")
        if isinstance(raw_val, SecretStr):
            raw_val = raw_val.get_secret_value()

        raw_val = str(raw_val or "")

        # 敏感信息脱敏
        if var["is_sensitive"] and raw_val:
            masked_val = "******"
        else:
            masked_val = raw_val

        result.append({
            "name": name,
            "value": masked_val,
            "description": var["description"],
            "category": var["category"],
            "is_sensitive": var["is_sensitive"],
            "allow_update": var.get("allow_update", False),
            "allow_test": var.get("allow_test", False),
        })

    return {"vars": result}


@router.put("/env-vars")
async def update_env_variable(
    payload: EnvVarUpdatePayload,
    current_user: User = Depends(get_current_admin_user)
):
    """
    临时更新环境变量并动态修改 runtime 内存设置。
    """
    name = payload.name
    value = payload.value

    # 校验是否属于可用环境变量白名单
    if name not in ALLOWED_ENV_VARS:
        raise HTTPException(status_code=422, detail="不支持修改此环境变量")

    # 值格式校验 + 归一化
    if name == "ENVIRONMENT":
        normalized = value.strip().lower()
        if normalized not in {"development", "production", "prod", "live"}:
            raise HTTPException(status_code=422, detail="ENVIRONMENT 须为 development/production")
        value = "production" if normalized in {"prod", "live"} else normalized
    elif name == "LOG_LEVEL":
        normalized = value.strip().upper()
        if normalized not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise HTTPException(status_code=422, detail="LOG_LEVEL 须为 DEBUG/INFO/WARNING/ERROR/CRITICAL")
        value = normalized
    elif name.endswith("_BASE_URL"):
        value = value.strip()
        parsed = urlparse(value)
        if parsed.scheme not in ("http", "https"):
            raise HTTPException(status_code=422, detail="BASE_URL 须使用 http 或 https 协议")
        if not parsed.netloc:
            raise HTTPException(status_code=422, detail="BASE_URL 格式无效，缺少主机部分")
        # 阻止内网/本地/链路本地/云元数据 IP，防止 SSRF 攻击
        hostname = (parsed.hostname or "").lower().rstrip(".")
        if hostname:
            try:
                addr = ipaddress.ip_address(hostname)
                if addr.is_private or addr.is_loopback or addr.is_link_local:
                    raise HTTPException(status_code=422, detail="不允许设置内网或本地地址")
            except ValueError:
                pass  # 主机名非 IP 地址，放行
    elif name == "VECTOR_DB_PATH":
        normalized = os.path.realpath(value.strip())
        if ".." in value or not os.path.isabs(normalized):
            raise HTTPException(status_code=422, detail="VECTOR_DB_PATH 须为合法的绝对路径")
        value = normalized

    # 先更新 settings 对象，成功后再写 os.environ（避免状态不一致）
    meta = next((v for v in ENV_VAR_META if v["name"] == name), None)
    if meta and meta.get("is_sensitive"):
        object.__setattr__(settings, name, SecretStr(value))
    else:
        object.__setattr__(settings, name, value)

    os.environ[name] = value

    logger.bind(
        event="update_env_var",
        module="system",
        action="update_env",
        status="success",
    ).info(f"环境变量 {name} 已动态更新。")

    return {"success": True}


@router.get("/env-vars/{name}/test")
async def test_env_variable(
    name: str,
    current_user: User = Depends(get_current_admin_user)
):
    """
    针对选定的 API 环境变量执行格式校验（仅检查 Key 长度≥10 字符，不发起真实的 API 连通性请求）。
    TODO: 集成为真实的连通性测试，例如调用对应 LLM 的 /v1/models 端点。
    """
    if name not in TESTABLE_ENV_VARS:
        raise HTTPException(status_code=422, detail="暂不支持以此属性开展连通性检测")

    raw_val = os.environ.get(name)
    if raw_val is None:
        raw_val = getattr(settings, name, "")
    if isinstance(raw_val, SecretStr):
        raw_val = raw_val.get_secret_value()

    raw_val = str(raw_val or "").strip()
    if not raw_val:
        return {"success": False, "message": f"未设置该 API Key {name}"}

    if len(raw_val) < 10:
        return {"success": False, "message": "API Key 格式不正确(字符太短)"}

    return {"success": True, "message": "格式预检通过（长度≥10字符），请注意此测试不验证 Key 的有效性"}
