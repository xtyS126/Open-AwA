"""
backend_mobile.main

内嵌后端 FastAPI 入口

与桌面版 backend/main.py 的差异：
- 移除桌面中间件（ACP/Terminal/Coding/TTS 等路由）
- 移除插件系统初始化
- 移除向量库初始化
- 数据库使用应用私有目录的 SQLite
- 密钥在首次启动时生成并持久化
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from .config import get_settings
from .db import ensure_owner_user, init_db
from .routes import auth, chat, security, system, user


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    应用生命周期：启动时初始化数据库与默认管理员
    """
    logger.info("启动内嵌后端初始化")
    init_db()
    ensure_owner_user()
    logger.info("内嵌后端初始化完成")
    yield
    logger.info("内嵌后端关闭")


def create_app() -> FastAPI:
    """创建内嵌后端 FastAPI 应用"""
    settings = get_settings()

    app = FastAPI(
        title="Open-AwA Mobile Backend",
        description="Android 内嵌后端（阶段 2 模块化版）",
        version=settings.version,
        lifespan=lifespan,
    )

    # CORS 中间件：允许 WebView 跨域访问
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_credentials=settings.cors_allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 注册路由
    app.include_router(system.router)
    app.include_router(auth.router)
    app.include_router(user.router)
    app.include_router(chat.router)
    app.include_router(chat.conversations_router)
    app.include_router(security.router)

    # 根路径
    @app.get("/")
    async def root():
        return {
            "name": "Open-AwA Mobile Backend",
            "version": settings.version,
            "docs": "/docs",
        }

    return app


# 用于 uvicorn 直接启动：uvicorn backend_mobile.main:app
app = create_app()
