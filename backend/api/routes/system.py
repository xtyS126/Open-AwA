"""
系统诊断路由 - 提供各子系统健康检查与状态查询，供测试任务使用。
"""

import asyncio
import ipaddress
import os
import sys
import platform
import time
from typing import Dict, Any, List, Optional
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from loguru import logger
from pydantic import BaseModel, Field, SecretStr
from sqlalchemy import text

from api.dependencies import get_current_user, get_current_admin_user
from db.models import User, SessionLocal
from config.settings import settings


def _error_response(status_code: int, code: str, message: str) -> JSONResponse:
    """构造结构化错误响应，绕过全局 http_exception_handler 的 str(detail) 转换。

    全局 http_exception_handler 会将 exc.detail 转为字符串塞进 message，
    导致 dict 形态的 detail 结构化信息（code/message）丢失。初始化端点需要
    向前端传达具体错误码（weak_password/prerequisite_failed/init_lock_contention 等），
    故直接返回 JSONResponse 保留结构。
    """
    return JSONResponse(
        status_code=status_code,
        content={
            "success": False,
            "error": {
                "code": code,
                "message": message,
            },
        },
    )

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

# API Key 环境变量名到供应商标识的映射
_API_KEY_TO_PROVIDER: Dict[str, str] = {
    "OPENAI_API_KEY": "openai",
    "ANTHROPIC_API_KEY": "anthropic",
    "DEEPSEEK_API_KEY": "deepseek",
    "QWEN_API_KEY": "qwen",
    "ZHIPU_API_KEY": "zhipu",
    "MOONSHOT_API_KEY": "moonshot",
}

# 供应商标识到对应 BASE_URL 环境变量名的映射
_PROVIDER_TO_BASE_URL_ENV: Dict[str, str] = {
    "openai": "",       # OpenAI 无自定义 BASE_URL 环境变量
    "anthropic": "",    # Anthropic 无自定义 BASE_URL 环境变量
    "deepseek": "",     # DeepSeek 无自定义 BASE_URL 环境变量
    "qwen": "QWEN_BASE_URL",
    "zhipu": "ZHIPU_BASE_URL",
    "moonshot": "MOONSHOT_BASE_URL",
}

# 供应商默认 API 基础地址
_PROVIDER_DEFAULT_BASE_URL: Dict[str, str] = {
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com",
    "deepseek": "https://api.deepseek.com/v1",
    "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "zhipu": "https://open.bigmodel.cn/api/paas/v4",
    "moonshot": "https://api.moonshot.cn/v1",
}


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
) -> Dict[str, Any]:
    """
    系统综合诊断端点，逐一检查各子系统状态并返回统一报告。
    供前端测试页面和自动化测试任务使用。

    性能：所有 _check_* 函数都是同步阻塞操作（DB 查询、文件遍历、子进程等），
    通过 asyncio.to_thread 并行执行避免阻塞事件循环，整体延迟近似于最慢的一个检查。
    """
    # 各检查函数为同步实现，统一通过 asyncio.to_thread 包装避免阻塞事件循环
    db_status, plugins_status, skills_status, mcp_status, env_info = await asyncio.gather(
        asyncio.to_thread(_check_database),
        asyncio.to_thread(_check_plugins),
        asyncio.to_thread(_check_skills),
        asyncio.to_thread(_check_mcp),
        asyncio.to_thread(_check_environment),
    )

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
async def ping() -> Dict[str, Any]:
    """
    轻量级连通性检查，无需认证。
    用于基础网络可达性验证。
    """
    return {"pong": True, "timestamp": time.time()}


class EnvVarUpdatePayload(BaseModel):
    name: str
    value: str = Field(..., min_length=1, max_length=4096, description="环境变量值")


@router.get("/env-vars")
async def list_env_vars(current_user: User = Depends(get_current_admin_user)) -> Dict[str, Any]:
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
) -> Dict[str, Any]:
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


class ConnectivityTestRequest(BaseModel):
    """连通性测试请求体，支持两种模式：基于环境变量名或基于供应商。"""
    # 模式一：基于环境变量名（兼容旧接口）
    env_var_name: Optional[str] = Field(None, description="环境变量名，如 OPENAI_API_KEY")
    # 模式二：基于供应商（推荐）
    provider: Optional[str] = Field(None, description="供应商标识，如 openai、deepseek")
    api_key: Optional[str] = Field(None, description="待测试的 API Key（明文，优先级高于环境变量）")
    base_url: Optional[str] = Field(None, description="自定义 Base URL（可选，不传则使用默认地址）")


def _build_models_url(provider: str, base_url: str) -> str:
    """根据供应商和 base_url 构建 /models 端点完整 URL。"""
    base = base_url.rstrip("/")
    # Anthropic 使用 /v1/models 端点
    if provider == "anthropic":
        return f"{base}/v1/models"
    # 如果 base_url 已包含 /v1 后缀，直接追加 /models
    if base.endswith("/v1"):
        return f"{base}/models"
    # 否则追加 /v1/models
    return f"{base}/v1/models"


def _validate_connectivity_url(url: str) -> Optional[str]:
    """
    SSRF 防护：校验连通性测试 URL 不指向内网/回环/保留/云元数据地址。
    返回 None 表示通过；返回字符串表示拒绝原因。
    """
    import socket

    try:
        parsed = urlparse(url)
    except ValueError as exc:
        return f"URL 解析失败: {exc}"

    hostname = parsed.hostname
    if not hostname:
        return "URL 缺少主机名"

    # 强制 HTTPS（生产环境）
    if settings.ENVIRONMENT == "production" and parsed.scheme != "https":
        return f"生产环境仅允许 HTTPS，当前协议: {parsed.scheme}"

    # 云元数据地址黑名单
    cloud_metadata_hosts = {"169.254.169.254", "metadata.google.internal"}
    if hostname.lower() in cloud_metadata_hosts:
        return f"禁止访问云元数据地址: {hostname}"

    # 解析主机名为 IP，校验是否为私有/回环/保留地址
    try:
        # 直接解析为 IP（如果是 IP 字面量）
        ip = ipaddress.ip_address(hostname)
        if ip.is_private or ip.is_loopback or ip.is_reserved or ip.is_link_local:
            return f"禁止访问内网/回环/保留地址: {ip}"
        if ip.is_multicast:
            return f"禁止访问组播地址: {ip}"
    except ValueError:
        # 不是 IP 字面量，解析域名
        try:
            addrinfos = socket.getaddrinfo(hostname, None)
        except socket.gaierror as exc:
            return f"域名解析失败: {hostname} ({exc})"

        for addrinfo in addrinfos:
            addr = addrinfo[4][0]
            try:
                ip = ipaddress.ip_address(addr)
                if ip.is_private or ip.is_loopback or ip.is_reserved or ip.is_link_local:
                    return f"域名 {hostname} 解析到内网地址: {ip}"
                if ip.is_multicast:
                    return f"域名 {hostname} 解析到组播地址: {ip}"
            except ValueError:
                continue

    return None


def _classify_http_error(status_code: int) -> str:
    """根据 HTTP 状态码返回用户友好的中文错误描述。"""
    if status_code == 401:
        return "API Key 无效或已过期"
    if status_code == 403:
        return "API Key 权限不足"
    if status_code == 404:
        return "API 端点不存在，请检查 Base URL"
    return f"未知错误: HTTP {status_code}"


@router.post("/connectivity-test")
async def test_connectivity(
    payload: ConnectivityTestRequest,
    current_user: User = Depends(get_current_admin_user),
) -> Dict[str, Any]:
    """
    对 LLM 供应商执行真实的 API 连通性测试。
    通过调用供应商的 /v1/models 端点验证 API Key 是否有效以及网络是否可达。
    支持两种调用模式：
      1. 基于环境变量名（env_var_name）— 从环境变量读取 Key 和 Base URL
      2. 基于供应商（provider + api_key + base_url）— 直接传入参数
    """
    # 确定供应商标识
    provider: Optional[str] = None
    api_key: Optional[str] = None
    base_url: Optional[str] = None

    if payload.provider:
        # 模式二：基于供应商
        provider = payload.provider.strip().lower()
        api_key = (payload.api_key or "").strip()
        base_url = (payload.base_url or "").strip() or None
    elif payload.env_var_name:
        # 模式一：基于环境变量名
        env_name = payload.env_var_name.strip()
        if env_name not in TESTABLE_ENV_VARS:
            raise HTTPException(status_code=422, detail="暂不支持以此属性开展连通性检测")
        provider = _API_KEY_TO_PROVIDER.get(env_name)
        if not provider:
            return {
                "success": False,
                "model_count": None,
                "error_message": f"无法识别环境变量 {env_name} 对应的供应商",
                "latency_ms": 0,
                "provider": "unknown",
            }
        # 读取环境变量中的 API Key
        raw_val = os.environ.get(env_name)
        if raw_val is None:
            raw_val = getattr(settings, env_name, "")
        if isinstance(raw_val, SecretStr):
            raw_val = raw_val.get_secret_value()
        api_key = str(raw_val or "").strip()
        # 读取对应的 BASE_URL 环境变量
        base_url_env = _PROVIDER_TO_BASE_URL_ENV.get(provider, "")
        if base_url_env:
            raw_base = os.environ.get(base_url_env)
            if raw_base is None:
                raw_base = getattr(settings, base_url_env, "")
            base_url = str(raw_base or "").strip() or None
    else:
        raise HTTPException(status_code=422, detail="必须提供 provider 或 env_var_name 参数")

    # 校验必要参数
    if not provider:
        raise HTTPException(status_code=422, detail="无法确定供应商标识")
    if not api_key:
        return {
            "success": False,
            "model_count": None,
            "error_message": "未提供 API Key",
            "latency_ms": 0,
            "provider": provider,
        }

    # 确定 Base URL：优先使用传入值，其次使用默认值
    effective_base_url = base_url or _PROVIDER_DEFAULT_BASE_URL.get(provider)
    if not effective_base_url:
        return {
            "success": False,
            "model_count": None,
            "error_message": f"未配置 {provider} 的 Base URL，且无默认地址",
            "latency_ms": 0,
            "provider": provider,
        }

    # 构建模型列表端点 URL
    models_url = _build_models_url(provider, effective_base_url)

    # SSRF 防护：校验 base_url 不指向内网/回环/云元数据地址
    ssrf_error = _validate_connectivity_url(models_url)
    if ssrf_error:
        logger.bind(
            event="connectivity_test",
            module="system",
            provider=provider,
            status="ssrf_blocked",
        ).warning(f"连通性测试被 SSRF 策略拒绝: {ssrf_error}")
        return {
            "success": False,
            "model_count": None,
            "error_message": f"Base URL 被安全策略拒绝: {ssrf_error}",
            "latency_ms": 0,
            "provider": provider,
        }

    # 构建请求头
    headers: Dict[str, str] = {}
    if provider == "anthropic":
        headers["x-api-key"] = api_key
        headers["anthropic-version"] = "2023-06-01"
    else:
        headers["Authorization"] = f"Bearer {api_key}"

    # 发起真实 API 请求
    start_time = time.time()
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(models_url, headers=headers)
        elapsed_ms = int((time.time() - start_time) * 1000)

        if response.status_code == 200:
            # 解析模型数量
            model_count = None
            try:
                data = response.json()
                model_list = data.get("data", [])
                if isinstance(model_list, list):
                    model_count = len(model_list)
            except (ValueError, KeyError):
                pass

            logger.bind(
                event="connectivity_test",
                module="system",
                provider=provider,
                status="success",
                latency_ms=elapsed_ms,
            ).info(f"连通性测试成功: provider={provider}, latency={elapsed_ms}ms")

            return {
                "success": True,
                "model_count": model_count,
                "error_message": None,
                "latency_ms": elapsed_ms,
                "provider": provider,
            }
        else:
            error_msg = _classify_http_error(response.status_code)
            logger.bind(
                event="connectivity_test",
                module="system",
                provider=provider,
                status="error",
                status_code=response.status_code,
                latency_ms=elapsed_ms,
            ).warning(f"连通性测试失败: provider={provider}, status={response.status_code}")

            return {
                "success": False,
                "model_count": None,
                "error_message": error_msg,
                "latency_ms": elapsed_ms,
                "provider": provider,
            }
    except httpx.TimeoutException:
        elapsed_ms = int((time.time() - start_time) * 1000)
        logger.bind(
            event="connectivity_test",
            module="system",
            provider=provider,
            status="timeout",
            latency_ms=elapsed_ms,
        ).warning(f"连通性测试超时: provider={provider}")
        return {
            "success": False,
            "model_count": None,
            "error_message": "连接超时（5秒），请检查网络或 Base URL",
            "latency_ms": elapsed_ms,
            "provider": provider,
        }
    except httpx.ConnectError:
        elapsed_ms = int((time.time() - start_time) * 1000)
        logger.bind(
            event="connectivity_test",
            module="system",
            provider=provider,
            status="connect_error",
            latency_ms=elapsed_ms,
        ).warning(f"连通性测试连接失败: provider={provider}")
        return {
            "success": False,
            "model_count": None,
            "error_message": "无法连接到服务器，请检查 Base URL",
            "latency_ms": elapsed_ms,
            "provider": provider,
        }
    except Exception as e:
        elapsed_ms = int((time.time() - start_time) * 1000)
        logger.bind(
            event="connectivity_test",
            module="system",
            provider=provider,
            status="error",
            error_type=type(e).__name__,
            latency_ms=elapsed_ms,
        ).error(f"连通性测试异常: provider={provider}, error={e}")
        return {
            "success": False,
            "model_count": None,
            "error_message": f"未知错误: {type(e).__name__}",
            "latency_ms": elapsed_ms,
            "provider": provider,
        }


@router.get("/env-vars/{name}/test")
async def test_env_variable(
    name: str,
    current_user: User = Depends(get_current_admin_user)
) -> Dict[str, Any]:
    """
    针对选定的 API 环境变量执行真实连通性测试。
    通过调用对应 LLM 供应商的 /v1/models 端点验证 Key 有效性和网络可达性。
    """
    if name not in TESTABLE_ENV_VARS:
        raise HTTPException(status_code=422, detail="暂不支持以此属性开展连通性检测")

    # 复用连通性测试逻辑
    request = ConnectivityTestRequest(env_var_name=name)
    return await test_connectivity(request, current_user)


# ============================================================================
# 首次部署初始化端点
# ============================================================================

class InitRequest(BaseModel):
    """初始化请求体。

    Attributes:
        username: owner 用户名，1-32 字符，仅含字母、数字、下划线、短横线。
        password: owner 密码，8-128 字符，需含大小写字母和数字。
        email: owner 邮箱（可选），最长 128 字符。
        nickname: owner 昵称（可选），最长 32 字符。
        force: 跳过前置检查（默认 False）。
        regenerate_secrets: 强制重新生成三密钥与 API Key（需配合 force=True）。
    """
    username: str = Field(..., min_length=1, max_length=32, pattern=r"^[a-zA-Z0-9_-]+$")
    password: str = Field(..., min_length=8, max_length=128)
    email: Optional[str] = Field(default=None, max_length=128)
    nickname: Optional[str] = Field(default=None, max_length=32)
    force: bool = Field(default=False)
    regenerate_secrets: bool = Field(default=False)


@router.get(
    "/init-csrf-token",
    summary="获取首次初始化 CSRF token",
    description="仅在系统尚未初始化时签发双提交 CSRF token，用于保护首次部署请求。",
)
async def get_init_csrf_token() -> JSONResponse:
    """为未初始化系统签发首次部署所需的双提交 CSRF token。"""
    from core.initialization import get_initialization_status
    from security.csrf_manager import generate_csrf_token_pair

    if get_initialization_status().get("initialized"):
        return _error_response(
            status_code=409,
            code="system_already_initialized",
            message="系统已初始化，不能再申请首次部署 token",
        )

    raw_token, signed_token = generate_csrf_token_pair()
    response = JSONResponse(content={"csrf_token": raw_token})
    from security.csrf_manager import get_csrf_protect
    get_csrf_protect().set_csrf_cookie(signed_token, response)
    return response


@router.post(
    "/init",
    summary="执行首次部署初始化",
    description=(
        "无需认证。创建 owner 用户、生成密钥、写入 .env.local、创建标记文件。"
        "首次部署前可调用；已初始化后调用需带 force=true。"
    ),
)
async def init_system(payload: InitRequest) -> Dict[str, Any]:
    """触发首次部署初始化流程。

    流程：
    1. 密码强度校验（大小写 + 数字）
    2. 调用 `core.bootstrap.initialize_system()` 执行 6 步流程
    3. 按异常类型映射 HTTP 状态码（PrerequisiteError → 409，其他 BootstrapError → 500）

    Args:
        payload: 初始化请求体。

    Returns:
        {"success": True, "data": {"user_id", "username", "secrets_generated", "api_key_generated"}}
    """
    # 密码强度校验：大小写 + 数字（与 auth.py 规则一致）
    if not (
        any(c.isupper() for c in payload.password)
        and any(c.islower() for c in payload.password)
        and any(c.isdigit() for c in payload.password)
    ):
        return _error_response(
            status_code=422,
            code="weak_password",
            message="密码至少 8 位，需含大小写字母和数字",
        )

    # 延迟导入避免循环依赖
    from core.bootstrap import (
        initialize_system,
        PrerequisiteError,
        LockAcquireError,
        BootstrapError,
    )

    try:
        result = await asyncio.to_thread(
            initialize_system,
            username=payload.username,
            password=payload.password,
            email=payload.email,
            nickname=payload.nickname,
            force=payload.force,
            regenerate_secrets=payload.regenerate_secrets,
        )
    except PrerequisiteError as e:
        return _error_response(
            status_code=409,
            code="prerequisite_failed",
            message=str(e),
        )
    except LockAcquireError as e:
        return _error_response(
            status_code=409,
            code="init_lock_contention",
            message=str(e),
        )
    except BootstrapError as e:
        logger.bind(
            event="init_failed",
            module="api.routes.system",
            error_type=type(e).__name__,
            error_message=str(e),
        ).error(f"初始化失败: {e}")
        return _error_response(
            status_code=500,
            code=type(e).__name__,
            message=str(e),
        )

    return {"success": True, "data": result}


@router.get(
    "/init-status",
    summary="查询系统初始化状态",
    description="无需认证，返回系统首次部署初始化状态。",
)
async def get_init_status() -> Dict[str, Any]:
    """返回初始化状态与数据库用户存在性。

    Returns:
        {
            "success": True,
            "data": {
                "initialized": bool,
                "initialized_at": str | None,
                "version": int | None,
                "steps_completed": list[str],
                "has_users": bool | None,  # DB 不可用时为 null
                "db_error": str  # 仅在 DB 不可用时存在
            }
        }
    """
    # 延迟导入避免循环依赖
    from core.initialization import get_initialization_status, has_any_user

    status = get_initialization_status()

    try:
        with SessionLocal() as db:
            has_users = has_any_user(db)
        db_error = None
    except Exception as e:
        has_users = None
        db_error = "database_unavailable"
        logger.bind(
            event="init_status_db_unavailable",
            module="api.routes.system",
            error_type=type(e).__name__,
            error_message=str(e),
        ).warning(f"init-status 数据库不可用: {e}")

    data: Dict[str, Any] = {
        **status,
        "has_users": has_users,
    }
    if db_error:
        data["db_error"] = db_error

    return {"success": True, "data": data}
