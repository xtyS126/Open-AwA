"""
后端服务主入口，负责应用初始化、中间件注册、路由挂载与基础健康检查。
阅读本文件时，建议优先关注启动顺序、生命周期管理、请求链路上下文以及全局异常处理方式。
"""

from contextlib import asynccontextmanager
import errno
import inspect
import os
import secrets as secrets_module
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.exceptions import HTTPException as FastAPIHTTPException
from fastapi.staticfiles import StaticFiles
from loguru import logger
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address

from api.routes import auth, chat, skills, plugins, memory, prompts, behavior, experiences, conversation, experience_files, logs, mcp, models, workflows, scheduled_tasks
from api.routes.marketplace import router as marketplace_router
from api.routes.security import router as security_router
from api.routes.weixin import router as weixin_router
from api.routes.tools import router as tools_router
from api.routes.subagents import router as subagents_router
from api.routes.user import router as user_router
from api.routes.system import router as system_router
from api.routes.task_runtime import router as task_runtime_router
from api.routes.test_runner import router as test_runner_router
from billing.models import Base as BillingBase
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    管理应用启动与关闭阶段的全局生命周期。
    启动时会初始化主数据库、计费表与默认定价配置；关闭时负责输出应用停止日志，为后续扩展统一资源清理入口。
    """
    logger.bind(event="app_startup", module="main").info("starting up openawa")
    # LiteLLM 依赖检测：启动时检查是否已安装
    if is_litellm_available():
        logger.bind(event="litellm_available", module="main").info("LiteLLM dependency detected, unified LLM gateway enabled")
    else:
        logger.bind(event="litellm_missing", module="main").warning(
            "LiteLLM dependency not installed. "
            "Please run `pip install litellm` to enable unified LLM gateway. "
            "Model API requests will fail until LiteLLM is installed."
        )
    if not os.getenv("SKIP_INIT_DB"):
        try:
            init_db()
            logger.bind(event="db_initialized", module="main").info("database initialized")
        except Exception as exc:
            logger.bind(event="db_init_error", module="main").error(f"数据库初始化失败: {exc}")
            raise RuntimeError(f"数据库初始化失败，服务无法启动: {exc}") from exc
        BillingBase.metadata.create_all(bind=engine)
        logger.bind(event="billing_tables_initialized", module="main").info("billing tables initialized")
        from billing.pricing_manager import PricingManager
        from db.models import SessionLocal

        db = SessionLocal()
        try:
            pricing_manager = PricingManager(db)
            pricing_manager.ensure_configuration_schema()
            count = pricing_manager.initialize_default_pricing()
            if count > 0:
                logger.bind(event="pricing_initialized", module="main", count=count).info("initialized model pricing entries")
            removed = pricing_manager.remove_legacy_default_configurations()
            if removed > 0:
                logger.bind(event="legacy_pricing_removed", module="main", removed=removed).info("removed legacy default model configurations")
        finally:
            db.close()
        # 初始化内置 RBAC 角色
        from security.rbac import RBACManager

        db = SessionLocal()
        try:
            rbac = RBACManager(db)
            rbac.ensure_built_in_roles()
        finally:
            db.close()
        # 从本地配置文件同步用户到数据库
        from config.local_users import sync_local_users_to_db

        db = SessionLocal()
        try:
            sync_stats = sync_local_users_to_db(db)
            logger.bind(event="local_users_synced", module="main", **sync_stats).info("local users synced from config")
        finally:
            db.close()
    # 初始化插件市场内置插件
    from plugins.marketplace.registry import marketplace_registry
    marketplace_registry.seed_built_in_plugins()

    # 初始化插件管理器：发现插件并加载数据库中已启用的插件
    from plugins.plugin_manager import PluginManager
    from plugins import plugin_instance
    from db.models import SessionLocal
    plugin_instance.init(PluginManager(db_session_factory=SessionLocal))
    pm = plugin_instance.get()
    pm.discover_plugins()
    if not os.getenv("SKIP_INIT_DB"):
        from db.models import Plugin as PluginModel
        db = SessionLocal()
        try:
            enabled_plugins = db.query(PluginModel).filter(PluginModel.enabled == True).all()
            for p in enabled_plugins:
                if p.name in pm.plugin_metadata:
                    try:
                        pm.load_plugin(p.name)
                        logger.bind(event="plugin_loaded", module="main", plugin=p.name).info(f"plugin loaded: {p.name}")
                    except Exception as exc:
                        logger.bind(event="plugin_load_error", module="main", plugin=p.name).warning(f"plugin load failed: {exc}")
            logger.bind(event="plugins_initialized", module="main", count=len(pm.loaded_plugins)).info("plugin system initialized")
        finally:
            db.close()

    await scheduled_task_manager.start()

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

# CSRF 保护 cookie 名称和 header 名称
_CSRF_COOKIE_NAME = "csrf_token"
_CSRF_HEADER_NAME = "X-CSRF-Token"
# 不需要 CSRF 校验的路径前缀（公开只读接口）
_CSRF_EXEMPT_PATHS = {"/api/auth/login", "/api/auth/register", "/api/logs/client-errors", "/api/auth/csrf-token"}
# 需要 CSRF 校验的请求方法
_CSRF_CHECKED_METHODS = {"POST", "PUT", "DELETE", "PATCH"}

# 服务端 CSRF token 存储（单例模式，定期轮换）
_csrf_server_secret: str = secrets_module.token_urlsafe(32)


@app.get("/api/auth/csrf-token")
async def get_csrf_token():
    """返回当前有效的 CSRF token，前端在页面加载时调用一次并存于 JS 内存。"""
    return {"csrf_token": _csrf_server_secret}


@app.middleware("http")
async def csrf_protection_middleware(request: Request, call_next):
    """
    服务端 Token 模式的 CSRF 保护中间件。
    GET/HEAD 请求在响应中注入 HttpOnly 的 csrf_token cookie（仅作防御纵深标记）；
    POST/PUT/DELETE/PATCH 请求校验 X-CSRF-Token header 与服务端存储的 token 是否匹配。
    WebSocket 和豁免路径跳过校验。
    """
    path = request.url.path
    method = request.method

    # WebSocket 连接跳过 CSRF 校验（通过 token query 参数认证）
    if "websocket" in path.lower() or request.headers.get("upgrade", "").lower() == "websocket":
        return await call_next(request)

    # 测试环境跳过 CSRF 校验
    if os.getenv("TESTING", "").lower() == "true":
        return await call_next(request)

    if method in _CSRF_CHECKED_METHODS and path not in _CSRF_EXEMPT_PATHS:
        header_token = request.headers.get(_CSRF_HEADER_NAME, "")
        if not header_token or not secrets_module.compare_digest(header_token, _csrf_server_secret):
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=403,
                content={"error": "invalid_csrf_token", "message": "CSRF token 验证失败"},
            )

    response = await call_next(request)

    # 在响应中设置 HttpOnly CSRF cookie（仅作标记，前端通过 API 获取 token）
    if _CSRF_COOKIE_NAME not in request.cookies:
        response.set_cookie(
            key=_CSRF_COOKIE_NAME,
            value="1",
            httponly=True,
            samesite="lax",
            secure=os.getenv("ENVIRONMENT", "development") == "production",
            path="/",
        )

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
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", REQUEST_ID_HEADER, CLIENT_VERSION_HEADER, _CSRF_HEADER_NAME],
)

# Rate Limiting 配置
limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"])
app.state.limiter = limiter
app.add_exception_handler(429, _rate_limit_exceeded_handler)

app.include_router(auth.router, prefix=settings.API_V1_STR)
app.include_router(chat.router, prefix=settings.API_V1_STR)
app.include_router(skills.router, prefix=settings.API_V1_STR)
app.include_router(plugins.router, prefix=settings.API_V1_STR)
app.include_router(memory.router, prefix=settings.API_V1_STR)
app.include_router(workflows.router, prefix=settings.API_V1_STR)
app.include_router(scheduled_tasks.router, prefix=settings.API_V1_STR)
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
app.include_router(system_router)
app.include_router(test_runner_router)

# 挂载用户头像静态文件目录
from pathlib import Path as FsPath
_avatars_dir = FsPath("uploads/avatars")
_avatars_dir.mkdir(parents=True, exist_ok=True)
app.mount("/api/user/avatar", StaticFiles(directory=str(_avatars_dir)), name="user_avatar")


@app.get("/")
async def root():
    """
    处理root相关逻辑，并为调用方返回对应结果。
    阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
    """
    return {
        "name": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "status": "running",
    }


@app.get("/health")
async def health_check():
    """
    处理health、check相关逻辑，并为调用方返回对应结果。
    阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
    """
    return {"status": "healthy"}


@app.get("/metrics")
async def metrics():
    """
    导出简易 Prometheus 指标，便于基础观测与排障。
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
    """
    run_kwargs = {
        "host": host,
        "port": port,
        "access_log": debug_mode,
        "log_level": "debug" if debug_mode else "warning",
    }

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
    # 在此处切换本地调试模式：True 启用 debug/reload/access_log，False 使用常规启动参数。
    DEBUG_MODE = True
    run_server(debug_mode=DEBUG_MODE)
