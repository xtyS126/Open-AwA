"""
后端服务主入口，负责应用初始化、中间件注册、路由挂载与基础健康检查。
阅读本文件时，建议优先关注启动顺序、生命周期管理、请求链路上下文以及全局异常处理方式。
"""

from contextlib import asynccontextmanager
import errno
import inspect
import os
import time
from typing import Optional

from fastapi import FastAPI, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.exceptions import HTTPException as FastAPIHTTPException
from fastapi.staticfiles import StaticFiles
from loguru import logger
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address

from api.routes import auth, chat, skills, plugins, memory, prompts, behavior, experiences, conversation, experience_files, logs, mcp, models, workflows, scheduled_tasks
from api.dependencies import get_current_user
from api.routes.diary import router as diary_router
from api.routes.marketplace import router as marketplace_router
from api.routes.security import router as security_router
from api.routes.weixin import router as weixin_router
from api.routes.tools import router as tools_router
from api.routes.subagents import router as subagents_router
from api.routes.user import router as user_router
from api.routes.user_profile import router as user_profile_router
from api.routes.system import router as system_router
from api.routes.task_runtime import router as task_runtime_router
from api.routes.test_runner import router as test_runner_router
from api.routes.workspace import router as workspace_router
from api.routes.coding import router as coding_router
from api.routes.inbox import router as inbox_router
from api.routes.magic_commands import router as magic_commands_router
from api.routes.heartbeat import router as heartbeat_router
from api.routes.tts import router as tts_router

from billing.routers import billing
from config.logging import (
    REQUEST_ID_HEADER,
    clear_request_id,
    generate_request_id,
    init_logging,
    sanitize_for_logging,
    set_request_id,
)
from core.metrics import prometheus_registry
from core.model_service import (
    CLIENT_VERSION_HEADER,
    SERVER_VERSION_HEADER,
    VERSION_STATUS_HEADER,
    build_standard_error,
    close_shared_client,
    negotiate_version_status,
)
from core.litellm_adapter import is_litellm_available
from core.scheduled_task_manager import scheduled_task_manager
from core.startup.profiler import StartupProfiler
from config.security import generate_csrf_token, verify_csrf_token
from config.settings import is_production_environment, settings
from db.models import engine, init_db


init_logging(
    log_level=settings.LOG_LEVEL,
    service_name=settings.LOG_SERVICE_NAME,
    log_serialize=settings.LOG_SERIALIZE,
    log_dir=settings.LOG_DIR,
    log_file_rotation=settings.LOG_FILE_ROTATION,
    log_file_retention=settings.LOG_FILE_RETENTION,
    log_file_compression=settings.LOG_FILE_COMPRESSION,
)

def _resolve_allowed_origins() -> list[str]:
    """
    统一解析 CORS 白名单。
    生产环境必须显式配置，避免默认开发域名带入生产。
    """
    raw_origins = os.getenv("ALLOWED_ORIGINS", "")
    origins = [item.strip() for item in raw_origins.split(",") if item.strip()]
    if origins:
        return origins

    if is_production_environment(os.getenv("ENVIRONMENT", "development")):
        raise ValueError("ALLOWED_ORIGINS environment variable is required in production environment")

    return ["http://localhost:5173", "http://localhost:8000"]


ALLOWED_ORIGINS = _resolve_allowed_origins()
logger.bind(event="cors_configured", module="main", allowed_origins=sanitize_for_logging(ALLOWED_ORIGINS)).info("cors configured")


# ==================== 启动步骤拆分 ====================
# 将原 lifespan 中的初始化逻辑按职责拆分为独立函数：
#   1. 基础设施（LiteLLM 依赖检测）
#   2. 数据初始化（DB 建表、计费、RBAC、用户同步）
#   3. 插件系统（市场种子、插件发现与加载）
#   4. 后台任务（定时任务、微信自动回复）
#
# 每步失败有独立日志和错误上下文，便于排障和单元测试。


async def _startup_infrastructure(profiler: StartupProfiler) -> None:
    """基础设施层初始化：依赖检测。"""
    with profiler.step("litellm_check"):
        if is_litellm_available():
            logger.bind(event="litellm_available", module="main").info("LiteLLM dependency detected, unified LLM gateway enabled")
        else:
            logger.bind(event="litellm_missing", module="main").warning(
                "LiteLLM dependency not installed. "
                "Please run `pip install litellm` to enable unified LLM gateway. "
                "Model API requests will fail until LiteLLM is installed."
            )


async def _startup_data_init(profiler: StartupProfiler) -> None:
    """数据层初始化：DB 建表、计费配置、RBAC 角色、本地用户同步。"""
    from db.models import SessionLocal

    # rate_limit_store 不依赖 DB（memory 后端），即使跳过 DB 初始化也能正常工作
    from security.rate_limit_store import init_rate_limit_store
    with profiler.step("rate_limit_store_init"):
        init_rate_limit_store(
            backend=settings.RATE_LIMIT_BACKEND,
            db_session_factory=SessionLocal,
        )

    if os.getenv("SKIP_INIT_DB"):
        return

    with profiler.step("db_init"):
        try:
            init_db()
            logger.bind(event="db_initialized", module="main").info("database initialized")
        except Exception as exc:
            logger.bind(event="db_init_error", module="main").error(f"数据库初始化失败: {exc}")
            raise RuntimeError(f"数据库初始化失败，服务无法启动: {exc}") from exc

    with profiler.step("billing_tables"):
        logger.bind(event="billing_tables_initialized", module="main").info("billing tables initialized")

    from billing.pricing_manager import PricingManager
    with profiler.step("pricing_init"):
        db = SessionLocal()
        try:
            pricing_manager = PricingManager(db)
            pricing_manager.ensure_configuration_schema()
            count = pricing_manager.initialize_default_pricing()
            if count > 0:
                logger.bind(event="pricing_initialized", module="main", count=count).info("initialized model pricing entries")
            config_count = pricing_manager.initialize_default_configurations()
            if config_count > 0:
                logger.bind(event="configurations_initialized", module="main", count=config_count).info("initialized default model configurations")
            removed = pricing_manager.remove_legacy_default_configurations()
            if removed > 0:
                logger.bind(event="legacy_pricing_removed", module="main", removed=removed).info("removed legacy default model configurations")
        finally:
            db.close()

    from security.rbac import RBACManager
    with profiler.step("rbac_init"):
        db = SessionLocal()
        try:
            rbac = RBACManager(db)
            rbac.ensure_built_in_roles()
        finally:
            db.close()

    from config.local_users import sync_local_users_to_db
    with profiler.step("local_users_sync"):
        db = SessionLocal()
        try:
            sync_stats = sync_local_users_to_db(db)
            logger.bind(event="local_users_synced", module="main", **sync_stats).info("local users synced from config")
        finally:
            db.close()


async def _startup_plugin_system(profiler: StartupProfiler) -> None:
    """插件系统初始化：市场种子、插件发现、已启用插件加载。"""
    from db.models import SessionLocal

    with profiler.step("marketplace_seed"):
        from plugins.marketplace.registry import marketplace_registry
        marketplace_registry.seed_built_in_plugins()

    with profiler.step("plugin_discover"):
        from plugins.plugin_manager import PluginManager
        from plugins import plugin_instance
        plugin_instance.init(PluginManager(db_session_factory=SessionLocal))
        pm = plugin_instance.get()
        pm.discover_plugins()

    if os.getenv("SKIP_INIT_DB"):
        return

    with profiler.step("plugin_load_enabled"):
        from db.models import Plugin as PluginModel, Skill
        import uuid
        db = SessionLocal()
        try:
            # 迁移：删除已由 system-tools 插件接管的内置技能记录
            for skill_name in ["file_manager", "terminal_executor"]:
                old_skill = db.query(Skill).filter(Skill.name == skill_name).first()
                if old_skill:
                    db.delete(old_skill)
                    logger.bind(event="skill_migrated", module="main", skill=skill_name).info(
                        f"已迁移内置技能 {skill_name} 至 system-tools 插件"
                    )
            db.commit()

            # 注册 system-tools 系统内置插件（如不存在）
            existing_plugin = db.query(PluginModel).filter(PluginModel.name == "system-tools").first()
            if not existing_plugin:
                new_plugin = PluginModel(
                    id=str(uuid.uuid4()),
                    name="system-tools",
                    version="1.0.0",
                    enabled=True,
                    config={},
                    category="builtin",
                    author="Open-AwA Team",
                    source="builtin",
                    dependencies=[],
                )
                db.add(new_plugin)
                db.commit()
                logger.bind(event="builtin_plugin_seeded", module="main", plugin="system-tools").info(
                    "已注册系统内置插件 system-tools"
                )
        except Exception as exc:
            logger.bind(event="builtin_plugin_seed_error", module="main").warning(f"内置插件注册失败: {exc}")
            db.rollback()
        finally:
            db.close()

        pm = plugin_instance.get()
        db = SessionLocal()
        try:
            enabled_plugins = db.query(PluginModel).filter(PluginModel.enabled == True).all()
            for p in enabled_plugins:
                if p.name in pm.plugin_metadata:
                    try:
                        pm.load_plugin(p.name)
                        logger.bind(event="plugin_loaded", module="main", plugin=p.name).info(f"plugin loaded: {p.name}")
                        granted = p.granted_permissions or []
                        if granted:
                            pm.restore_plugin_permissions(p.name, granted)
                    except Exception as exc:
                        logger.bind(event="plugin_load_error", module="main", plugin=p.name).warning(f"plugin load failed: {exc}")
            logger.bind(event="plugins_initialized", module="main", count=len(pm.loaded_plugins)).info("plugin system initialized")
        finally:
            db.close()


async def _startup_background_tasks(profiler: StartupProfiler) -> None:
    """后台任务初始化：定时任务管理器、微信自动回复。"""
    from db.models import SessionLocal

    with profiler.step("scheduled_task_start"):
        await scheduled_task_manager.start()

    if os.getenv("SKIP_INIT_DB"):
        return

    with profiler.step("weixin_auto_reply"):
        from db.models import WeixinBinding
        from api.services.weixin_auto_reply import get_auto_reply_manager
        db = SessionLocal()
        try:
            bindings = db.query(WeixinBinding).filter(
                WeixinBinding.binding_status == "bound",
                WeixinBinding.auto_start_reply == True
            ).all()
            if bindings:
                manager = get_auto_reply_manager()
                for binding in bindings:
                    try:
                        await manager.start(binding.user_id)
                        logger.bind(event="weixin_auto_reply_autostart", module="main", user_id=binding.user_id).info("自动启动微信自动回复")
                    except ValueError as e:
                        logger.bind(event="weixin_auto_reply_autostart_failed", module="main", user_id=binding.user_id).warning(f"自动启动微信自动回复失败（配置错误）: {e}")
                    except Exception as e:
                        logger.bind(event="weixin_auto_reply_autostart_error", module="main", user_id=binding.user_id).error(f"自动启动微信自动回复异常: {e}")
        finally:
            db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    管理应用启动与关闭阶段的全局生命周期。
    启动步骤已拆分为四个独立函数：基础设施 → 数据初始化 → 插件系统 → 后台任务。
    每步失败有独立日志和错误上下文，便于排障。
    """
    logger.bind(event="app_startup", module="main").info("starting up openawa")

    profiler = StartupProfiler()
    profiler.start()

    try:
        await _startup_infrastructure(profiler)
        await _startup_data_init(profiler)
        await _startup_plugin_system(profiler)
        await _startup_background_tasks(profiler)
    except Exception:
        logger.bind(event="app_startup_failed", module="main").error("启动过程发生异常，服务将终止")
        raise

    profiler.finish()

    yield
    await scheduled_task_manager.stop()
    await close_shared_client()
    logger.bind(event="app_shutdown", module="main").info("shutting down openawa")


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="AI Agent Framework - Similar to OpenClaw",
    lifespan=lifespan,
)

# CSRF 保护 — per-session 签名 token 模式
# 参考: Django CSRF 中间件 https://github.com/django/django/blob/main/django/middleware/csrf.py
_CSRF_HEADER_NAME = "X-CSRF-Token"
# 不需要 CSRF 校验的路径前缀（公开只读接口）
_CSRF_EXEMPT_PATHS = {"/api/auth/login", "/api/auth/register", "/api/logs/client-errors", "/api/auth/csrf-token"}
# 需要 CSRF 校验的请求方法
_CSRF_CHECKED_METHODS = {"POST", "PUT", "DELETE", "PATCH"}

# CSRF 签名密钥由 security._derive_csrf_signing_key() 从 SECRET_KEY 派生
# 确保多 Worker 部署时签名一致（不再使用进程级随机密钥）


async def _extract_user_id_from_request(request: Request) -> Optional[str]:
    """
    从请求中提取认证用户 ID（用于 CSRF 校验时与 token 中绑定的用户比对）。

    优先从 JWT payload 的 uid 字段直接读取（高效路径），
    其次回退到通过 username 查 DB 的兼容路径（支持旧版不含 uid 的令牌）。

    User.id 为字符串类型，所有路径统一返回 str 或 None。
    不会抛出异常，解析失败返回 None。
    """
    from config.security import decode_access_token, ACCESS_TOKEN_COOKIE_NAME

    token: Optional[str] = None
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
    if not token:
        token = request.cookies.get(ACCESS_TOKEN_COOKIE_NAME, "")
    if not token:
        return None

    payload = decode_access_token(token)
    if payload is None:
        return None

    # 优先从 JWT payload 直接读取 uid（高效路径，User.id 为字符串类型）
    uid = payload.get("uid")
    if isinstance(uid, str) and uid:
        return uid

    # 兼容旧版令牌：通过 username 查 DB（降级路径）
    username = payload.get("sub")
    if not isinstance(username, str):
        return None

    try:
        import asyncio
        from api.dependencies import _load_user_by_username

        user = await asyncio.to_thread(_load_user_by_username, username)
        return user.id if user else None
    except Exception:
        return None


@app.get("/api/auth/csrf-token")
async def get_csrf_token(request: Request):
    """
    返回当前用户会话的 CSRF token（需认证）。

    前端在登录后调用此接口获取 per-session CSRF token，
    存储在 JS 内存中，在状态变更请求时通过 X-CSRF-Token header 发送。
    """
    user_id = await _extract_user_id_from_request(request)
    if user_id is None:
        raise FastAPIHTTPException(status_code=401, detail="Authentication required")
    csrf_token = generate_csrf_token(user_id)
    return {"csrf_token": csrf_token}


@app.middleware("http")
async def csrf_protection_middleware(request: Request, call_next):
    """
    Per-session 签名 Token 模式的 CSRF 保护中间件。

    对 POST/PUT/DELETE/PATCH 请求校验 X-CSRF-Token header：
    1. 验证 token 签名和有效期
    2. 提取 token 中绑定的 user_id
    3. 与请求中认证用户的 user_id 比对，确保一一对应

    WebSocket 连接和豁免路径跳过校验。
    """
    path = request.url.path
    method = request.method

    # WebSocket 连接跳过 CSRF 校验（通过 token query 参数认证）
    if "websocket" in path.lower() or request.headers.get("upgrade", "").lower() == "websocket":
        return await call_next(request)

    # 测试环境跳过 CSRF 校验（仅通过 pytest conftest 设置的专用环境变量开启）
    if os.getenv("SKIP_CSRF_FOR_TEST", "").lower() == "true":
        return await call_next(request)

    if method in _CSRF_CHECKED_METHODS and path not in _CSRF_EXEMPT_PATHS:
        header_token = request.headers.get(_CSRF_HEADER_NAME, "")
        if not header_token:
            return JSONResponse(
                status_code=403,
                content={
                    "error": "missing_csrf_token",
                    "message": "缺少 CSRF token",
                    "detail": "Missing X-CSRF-Token header",
                },
            )

        # 验证 CSRF token 签名和有效期
        csrf_payload = verify_csrf_token(header_token)
        if csrf_payload is None:
            return JSONResponse(
                status_code=403,
                content={
                    "error": "invalid_csrf_token",
                    "message": "CSRF token 无效或已过期",
                    "detail": "CSRF token verification failed",
                },
            )

        # 提取请求中的认证用户 ID 并与 CSRF token 中绑定的用户比对
        request_user_id = await _extract_user_id_from_request(request)
        if request_user_id is None or request_user_id != csrf_payload["sub"]:
            return JSONResponse(
                status_code=403,
                content={
                    "error": "csrf_user_mismatch",
                    "message": "CSRF token 与当前用户不匹配",
                    "detail": "CSRF token user mismatch",
                },
            )

    response = await call_next(request)
    return response


@app.middleware("http")
async def request_context_middleware(request: Request, call_next):
    """
    为每个 HTTP 请求建立统一的请求上下文与链路追踪信息。
    中间件会生成或继承请求 ID、写入请求状态与日志上下文、在响应头回传请求 ID，并记录请求开始、结束与异常日志。
    """
    incoming_request_id = request.headers.get(REQUEST_ID_HEADER, "")
    incoming_client_version = request.headers.get(CLIENT_VERSION_HEADER, "")
    request_id = str(incoming_request_id or generate_request_id()).strip() or generate_request_id()
    version_status = negotiate_version_status(incoming_client_version, settings.VERSION)
    set_request_id(request_id)
    request.state.request_id = request_id
    request.state.client_version = incoming_client_version
    request.state.version_status = version_status

    path = request.url.path
    method = request.method

    logger.bind(
        event="http_request_started",
        module="api",
        request_id=request_id,
        http_method=method,
        path=path,
    ).debug("request started")

    start_time = time.monotonic()

    try:
        response = await call_next(request)
        duration_ms = round((time.monotonic() - start_time) * 1000, 2)
        response.headers[REQUEST_ID_HEADER] = request_id
        response.headers[SERVER_VERSION_HEADER] = settings.VERSION
        response.headers[VERSION_STATUS_HEADER] = version_status
        if incoming_client_version:
            response.headers[CLIENT_VERSION_HEADER] = incoming_client_version
        logger.bind(
            event="http_request_completed",
            module="api",
            request_id=request_id,
            http_method=method,
            path=path,
            status=response.status_code,
            duration_ms=duration_ms,
        ).info(f"{method} {path} -> {response.status_code} ({duration_ms}ms) rid={request_id}")
        return response
    except Exception as exc:
        duration_ms = round((time.monotonic() - start_time) * 1000, 2)
        logger.bind(
            event="http_request_failed",
            module="api",
            request_id=request_id,
            http_method=method,
            path=path,
            error_type=type(exc).__name__,
            error_message=sanitize_for_logging(str(exc)),
            duration_ms=duration_ms,
        ).exception("request failed")
        raise
    finally:
        clear_request_id()


@app.exception_handler(FastAPIHTTPException)
async def http_exception_handler(request: Request, exc: FastAPIHTTPException):
    """
    将显式 HTTP 异常统一包装为带错误码与 request_id 的结构。
    """

    request_id = getattr(request.state, "request_id", "") or generate_request_id()
    error = build_standard_error(
        code=f"http_{exc.status_code}",
        message=str(exc.detail),
        request_id=request_id,
        status_code=exc.status_code,
        retryable=exc.status_code >= 500,
    )
    response = JSONResponse(status_code=exc.status_code, content={"error": error})
    response.headers[REQUEST_ID_HEADER] = request_id
    response.headers[SERVER_VERSION_HEADER] = settings.VERSION
    response.headers[VERSION_STATUS_HEADER] = getattr(request.state, "version_status", "server_only")
    client_version = getattr(request.state, "client_version", "")
    if client_version:
        response.headers[CLIENT_VERSION_HEADER] = client_version
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """
    处理unhandled、exception、handler相关逻辑，并为调用方返回对应结果。
    阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
    """
    request_id = getattr(request.state, "request_id", "") or generate_request_id()
    logger.bind(
        event="unhandled_exception",
        module="api",
        request_id=request_id,
        http_method=request.method,
        path=request.url.path,
        error_type=type(exc).__name__,
        error_message=sanitize_for_logging(str(exc)),
    ).exception("unhandled exception")

    error = build_standard_error(
        code="internal_server_error",
        message="Internal server error",
        request_id=request_id,
        status_code=500,
        retryable=False,
    )
    response = JSONResponse(
        status_code=500,
        content={"error": error},
    )
    response.headers[REQUEST_ID_HEADER] = request_id
    response.headers[SERVER_VERSION_HEADER] = settings.VERSION
    response.headers[VERSION_STATUS_HEADER] = getattr(request.state, "version_status", "server_only")
    client_version = getattr(request.state, "client_version", "")
    if client_version:
        response.headers[CLIENT_VERSION_HEADER] = client_version
    return response


app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", REQUEST_ID_HEADER, CLIENT_VERSION_HEADER, _CSRF_HEADER_NAME],
)

# Content-Security-Policy 中间件 — 添加安全头防止 XSS 和数据注入攻击
@app.middleware("http")
async def _add_csp_header(request: Request, call_next):
    """
    为所有响应添加 Content-Security-Policy 头。
    CSP 作为 XSS 攻击的第二道防线，在默认 React 转义基础上提供额外保护。
    script-src 禁止 unsafe-inline，通过 Trusted Types + nonce 方案防御 XSS。
    style-src 在调试模式下保留 unsafe-inline 以兼容 React 热更新样式注入。
    """
    response = await call_next(request)
    # 调试模式下 React 开发服务器需要内联样式注入；脚本内联始终禁止
    _debug = os.getenv("DEBUG_MODE", "").lower() == "true"
    style_src = "'self' 'unsafe-inline' https://fonts.googleapis.com" if _debug else "'self' https://fonts.googleapis.com"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        f"script-src 'self'; "
        f"style-src {style_src}; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data: blob: https:; "
        "connect-src 'self' ws: wss:; "
        "frame-src 'self'; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "form-action 'self'"
    )
    return response

# Rate Limiting 配置
# 使用代理感知的 key_func，仅当请求来自受信代理时才信任 X-Forwarded-For / X-Real-IP 头，
# 防止客户端伪造代理头绕过速率限制。
_TRUSTED_PROXY_NETWORKS: list = []
try:
    import ipaddress as _ipaddress_mod
    _raw_proxies = str(settings.TRUSTED_PROXIES or "").strip()
    if _raw_proxies:
        for _entry in _raw_proxies.split(","):
            _entry = _entry.strip()
            if _entry:
                try:
                    _TRUSTED_PROXY_NETWORKS.append(_ipaddress_mod.ip_network(_entry, strict=False))
                except ValueError:
                    logger.bind(event="invalid_trusted_proxy", module="main", entry=_entry).warning(
                        f"无效的受信代理条目，已跳过: {_entry}"
                    )
except ImportError:
    pass


def _get_client_ip(request: Request) -> str:
    """从请求中提取真实客户端 IP。
    仅当直连 IP 属于受信代理时，才读取 X-Forwarded-For / X-Real-IP 头；
    否则直接返回直连 IP，防止客户端伪造代理头绕过速率限制。
    """
    # 获取直连 IP（反向代理场景下为代理 IP）
    direct_ip = get_remote_address(request)
    if not _TRUSTED_PROXY_NETWORKS:
        return direct_ip

    try:
        _addr = _ipaddress_mod.ip_address(direct_ip)
        _trusted = any(_addr in _net for _net in _TRUSTED_PROXY_NETWORKS)
    except (ValueError, TypeError):
        _trusted = False

    if not _trusted:
        return direct_ip

    # 受信代理：从 X-Forwarded-For 获取客户端真实 IP
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    # 其次使用 X-Real-IP
    real_ip = request.headers.get("X-Real-IP", "")
    if real_ip:
        return real_ip.strip()
    return direct_ip

limiter = Limiter(key_func=_get_client_ip, default_limits=["60/minute"])
app.state.limiter = limiter
app.add_exception_handler(429, _rate_limit_exceeded_handler)

app.include_router(auth.router, prefix=settings.API_V1_STR)
app.include_router(chat.router, prefix=settings.API_V1_STR)
# 微信相关路由已合并至 skills 路由模块中（/skills/weixin/*）
app.include_router(skills.router, prefix=settings.API_V1_STR)
app.include_router(plugins.router, prefix=settings.API_V1_STR)
app.include_router(memory.router, prefix=settings.API_V1_STR)
app.include_router(workflows.router, prefix=settings.API_V1_STR)
app.include_router(scheduled_tasks.router, prefix=settings.API_V1_STR)
app.include_router(diary_router, prefix=settings.API_V1_STR)
app.include_router(prompts.router, prefix=settings.API_V1_STR)
app.include_router(behavior.router, prefix=settings.API_V1_STR)
app.include_router(experiences.router, prefix=settings.API_V1_STR)
app.include_router(experience_files.router, prefix=settings.API_V1_STR)
app.include_router(conversation.router, prefix=settings.API_V1_STR)
app.include_router(logs.router, prefix=settings.API_V1_STR)
app.include_router(mcp.router)
app.include_router(models.router)
app.include_router(billing.router)
app.include_router(marketplace_router)
app.include_router(security_router)
app.include_router(weixin_router)
app.include_router(tools_router)
app.include_router(subagents_router)
app.include_router(task_runtime_router)
app.include_router(user_router, prefix=settings.API_V1_STR)
app.include_router(user_profile_router, prefix=settings.API_V1_STR)
app.include_router(system_router)
app.include_router(test_runner_router)
app.include_router(workspace_router)
app.include_router(heartbeat_router)
app.include_router(coding_router)
app.include_router(inbox_router)
app.include_router(magic_commands_router, prefix=settings.API_V1_STR)
app.include_router(tts_router)

# 挂载用户头像静态文件目录
from pathlib import Path as FsPath
_avatars_dir = FsPath("uploads/avatars")
_avatars_dir.mkdir(parents=True, exist_ok=True)
app.mount("/api/user/avatar", StaticFiles(directory=str(_avatars_dir)), name="user_avatar")

# ---- 前端静态文件服务（生产模式）----
_project_root = FsPath(__file__).resolve().parent.parent
_FRONTEND_DIST = _project_root / "frontend" / "dist"
_HAS_FRONTEND = _FRONTEND_DIST.is_dir() and (_FRONTEND_DIST / "index.html").exists()

if _HAS_FRONTEND and is_production_environment(settings.ENVIRONMENT):
    app.mount("/assets", StaticFiles(directory=str(_FRONTEND_DIST / "assets")), name="frontend_assets")

    @app.get("/{full_path:path}")
    async def serve_frontend_spa(full_path: str, request: Request):
        """
        SPA 回退路由：非 API 路径返回 index.html。
        """
        if full_path.startswith("api/") or full_path.startswith("ws/"):
            from fastapi.responses import JSONResponse
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        index_path = _FRONTEND_DIST / "index.html"
        if not index_path.exists():
            from fastapi.responses import JSONResponse
            return JSONResponse({"detail": "Frontend not built"}, status_code=503)
        from fastapi.responses import FileResponse
        return FileResponse(str(index_path), media_type="text/html")


# 静态资源缓存策略：为带哈希的文件名设置长期缓存
@app.middleware("http")
async def add_cache_headers(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path
    # 带哈希的静态资源（JS/CSS/字体/图片）设置 1 年缓存
    if any(ext in path for ext in ('.js', '.css', '.woff', '.woff2', '.ttf', '.png', '.jpg', '.svg', '.ico')):
        # Vite/Rollup 输出的文件名包含哈希（如 index-a1b2c3d4.js），可安全长期缓存
        if any(c.isdigit() for c in path.split('/')[-1].split('.')[0][-8:]):
            response.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
    return response


@app.get("/")
async def root():
    """
    根路径健康探活端点，返回项目名称、版本和运行状态。
    """
    return {
        "name": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "status": "running",
    }


@app.get("/health")
async def health_check():
    """
    轻量级健康检查端点，无需认证。用于负载均衡器和监控系统的存活探测。
    """
    return {"status": "healthy"}


@app.get("/metrics")
async def metrics(current_user = Depends(get_current_user)):
    """
    导出简易 Prometheus 指标，便于基础观测与排障。
    需要认证访问，防止运行指标、请求量和错误统计被未授权获取。
    """

    return PlainTextResponse(
        prometheus_registry.render(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


def get_server_host() -> str:
    """
    读取后端服务监听主机配置。
    优先使用环境变量中的 BACKEND_HOST，其次兼容 HOST，未配置时回退到默认值。
    """
    return (os.getenv("BACKEND_HOST") or os.getenv("HOST") or "0.0.0.0").strip() or "0.0.0.0"


def get_server_port() -> int:
    """
    读取后端服务监听端口配置。
    优先使用环境变量中的 BACKEND_PORT，其次兼容 PORT，未配置时回退到默认值。
    如果端口值不是合法整数，则抛出带明确信息的异常，便于快速排查配置问题。
    """
    raw_port = (os.getenv("BACKEND_PORT") or os.getenv("PORT") or "8000").strip() or "8000"
    try:
        return int(raw_port)
    except ValueError as exc:
        raise ValueError(f"无效的端口配置: {raw_port}") from exc


def _run_uvicorn_server(uvicorn_module, host: str, port: int, debug_mode: bool = False) -> None:
    """
    统一封装 uvicorn.run 调用。
    真实启动时保留默认日志参数，测试中的精简桩函数也能兼容。
    当 settings 中配置了 SSL 证书和私钥时自动启用 HTTPS。
    """
    run_kwargs = {
        "host": host,
        "port": port,
        "access_log": debug_mode,
        "log_level": "debug" if debug_mode else "warning",
    }

    # HTTPS 配置：证书和私钥同时存在时自动启用 TLS
    if settings.is_ssl_enabled():
        run_kwargs["ssl_certfile"] = settings.SSL_CERTFILE
        run_kwargs["ssl_keyfile"] = settings.SSL_KEYFILE
        if settings.SSL_KEYFILE_PASSWORD:
            run_kwargs["ssl_keyfile_password"] = settings.SSL_KEYFILE_PASSWORD
        if settings.SSL_CA_CERTS:
            run_kwargs["ssl_ca_certs"] = settings.SSL_CA_CERTS

    # uvicorn 的热重载依赖导入字符串形式的 app 目标，直接传入 app 对象时无法启用 reload。
    # 这里在调试模式下切换为模块导入路径，便于通过修改 DEBUG_MODE 快速开启本地调试体验。
    app_target = "main:app" if debug_mode else app
    if debug_mode:
        run_kwargs["reload"] = True

    try:
        signature = inspect.signature(uvicorn_module.run)
    except (TypeError, ValueError):
        signature = None

    if signature is not None:
        has_var_kwargs = any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD
            for parameter in signature.parameters.values()
        )
        if not has_var_kwargs:
            run_kwargs = {
                key: value
                for key, value in run_kwargs.items()
                if key in signature.parameters
            }

    uvicorn_module.run(app_target, **run_kwargs)


def run_server(debug_mode: bool = False) -> None:
    """
    启动后端 HTTP 服务并处理常见启动异常。
    发生端口占用时输出更友好的提示，帮助调用方快速定位冲突端口或调整配置。
    """
    import uvicorn

    host = get_server_host()
    port = get_server_port()
    logger.bind(
        event="server_starting",
        module="main",
        host=host,
        port=port,
        debug_mode=debug_mode,
        use_tls=settings.is_ssl_enabled(),
    ).info("starting backend server")
    try:
        _run_uvicorn_server(uvicorn, host, port, debug_mode=debug_mode)
    except OSError as exc:
        if exc.errno == errno.EADDRINUSE:
            message = f"后端服务启动失败：端口 {port} 已被占用，请关闭占用进程或通过 BACKEND_PORT/PORT 更换端口后重试。"
            logger.bind(event="server_bind_conflict", module="main", host=host, port=port).error(message)
            raise RuntimeError(message) from exc
        raise


if __name__ == "__main__":
    # 调试模式仅通过环境变量显式开启，生产环境默认关闭。
    # 设置 DEBUG_MODE=true 可启用 uvicorn reload/access_log 与调试级日志。
    DEBUG_MODE = os.getenv("DEBUG_MODE", "").lower() == "true"
    if DEBUG_MODE:
        logger.bind(event="debug_mode_enabled", module="main").warning("调试模式已开启，生产环境请确保 DEBUG_MODE 未设置")
    run_server(debug_mode=DEBUG_MODE)
