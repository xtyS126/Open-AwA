from contextlib import asynccontextmanager
import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
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
    logger.bind(event="app_startup", module="main").info("starting up openawa")
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
    incoming_request_id = request.headers.get(REQUEST_ID_HEADER, "")
    request_id = str(incoming_request_id or generate_request_id()).strip() or generate_request_id()
    set_request_id(request_id)
    request.state.request_id = request_id

    path = request.url.path
    method = request.method

    logger.bind(
        event="http_request_started",
        module="api",
        request_id=request_id,
        http_method=method,
        path=path,
    ).info("request started")

    try:
        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request_id
        logger.bind(
            event="http_request_completed",
            module="api",
            request_id=request_id,
            http_method=method,
            path=path,
            status=response.status_code,
        ).info("request completed")
        return response
    except Exception as exc:
        logger.bind(
            event="http_request_failed",
            module="api",
            request_id=request_id,
            http_method=method,
            path=path,
            error_type=type(exc).__name__,
            error_message=sanitize_for_logging(str(exc)),
        ).exception("request failed")
        raise
    finally:
        clear_request_id()


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
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

    response = JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "request_id": request_id},
    )
    response.headers[REQUEST_ID_HEADER] = request_id
    return response


app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", REQUEST_ID_HEADER],
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
    return {
        "name": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "status": "running",
    }


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
