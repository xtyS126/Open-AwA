from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from loguru import logger
import sys
import os

from config.settings import settings
from db.models import init_db, engine
from api.routes import auth, chat, skills, plugins, memory, prompts, behavior, experiences
from billing.models import Base as BillingBase
from billing.routers import billing


logger.remove()
logger.add(
    sys.stderr,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    level=settings.LOG_LEVEL
)

ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "").split(",") if os.getenv("ALLOWED_ORIGINS") else ["http://localhost:5173", "http://localhost:8000"]
logger.info(f"CORS configured with allowed origins: {ALLOWED_ORIGINS}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up Open-AwA AI Agent")
    init_db()
    logger.info("Database initialized")
    BillingBase.metadata.create_all(bind=engine)
    logger.info("Billing tables created")
    from billing.pricing_manager import PricingManager
    from db.models import SessionLocal
    db = SessionLocal()
    try:
        pricing_manager = PricingManager(db)
        pricing_manager.ensure_configuration_schema()
        count = pricing_manager.initialize_default_pricing()
        if count > 0:
            logger.info(f"Initialized {count} model pricing entries")
        removed = pricing_manager.remove_legacy_default_configurations()
        if removed > 0:
            logger.info(f"Removed {removed} legacy default model configurations")

    finally:
        db.close()
    yield
    logger.info("Shutting down Open-AwA AI Agent")


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="AI Agent Framework - Similar to OpenClaw",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(auth.router, prefix=settings.API_V1_STR)
app.include_router(chat.router, prefix=settings.API_V1_STR)
app.include_router(skills.router, prefix=settings.API_V1_STR)
app.include_router(plugins.router, prefix=settings.API_V1_STR)
app.include_router(memory.router, prefix=settings.API_V1_STR)
app.include_router(prompts.router, prefix=settings.API_V1_STR)
app.include_router(behavior.router, prefix=settings.API_V1_STR)
app.include_router(experiences.router, prefix=settings.API_V1_STR)
app.include_router(billing.router)


@app.get("/")
async def root():
    return {
        "name": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "status": "running"
    }


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
