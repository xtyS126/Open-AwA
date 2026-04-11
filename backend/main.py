"""
后端服务主入口，负责应用初始化、中间件注册、路由挂载与基础健康检查。
阅读本文件时，建议优先关注启动顺序、生命周期管理、请求链路上下文以及全局异常处理方式。
"""

from contextlib import asynccontextmanager
import os
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.exceptions import HTTPException as FastAPIHTTPException
from loguru import logger

from api.routes import auth, chat, skills, plugins, memory, prompts, behavior, experiences, conversation, experience_files, logs
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
    negotiate_version_status,
)
from config.settings import settings
from db.models import engine, init_db


init_logging(
    log_level=settings.LOG_LEVEL,
    service_name=settings.LOG_SERVICE_NAME,
    log_serialize=settings.LOG_SERIALIZE,
)

ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "").split(",") if os.getenv("ALLOWED_ORIGINS") else ["http://localhost:5173", "http://localhost:8000"]
logger.bind(event="cors_configured", module="main", allowed_origins=sanitize_for_logging(ALLOWED_ORIGINS)).info("cors configured")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    管理应用启动与关闭阶段的全局生命周期。
    启动时会初始化主数据库、计费表与默认定价配置；关闭时负责输出应用停止日志，为后续扩展统一资源清理入口。
    """
    logger.bind(event="app_startup", module="main").info("starting up openawa")
    if not os.getenv("SKIP_INIT_DB"):
        init_db()
        logger.bind(event="db_initialized", module="main").info("database initialized")
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
    yield
    logger.bind(event="app_shutdown", module="main").info("shutting down openawa")


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="AI Agent Framework - Similar to OpenClaw",
    lifespan=lifespan,
)


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
    ).info("request started")

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
        ).info("request completed")
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
    allow_headers=["Authorization", "Content-Type", REQUEST_ID_HEADER, CLIENT_VERSION_HEADER],
)

app.include_router(auth.router, prefix=settings.API_V1_STR)
app.include_router(chat.router, prefix=settings.API_V1_STR)
app.include_router(skills.router, prefix=settings.API_V1_STR)
app.include_router(plugins.router, prefix=settings.API_V1_STR)
app.include_router(memory.router, prefix=settings.API_V1_STR)
app.include_router(prompts.router, prefix=settings.API_V1_STR)
app.include_router(behavior.router, prefix=settings.API_V1_STR)
app.include_router(experiences.router, prefix=settings.API_V1_STR)
app.include_router(experience_files.router, prefix=settings.API_V1_STR)
app.include_router(conversation.router, prefix=settings.API_V1_STR)
app.include_router(logs.router, prefix=settings.API_V1_STR)
app.include_router(billing.router)


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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
