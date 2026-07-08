"""
backend_mobile 数据库模块

使用 SQLAlchemy + SQLite，与桌面版 backend/db/models.py 共享 schema 子集。
仅移植核心表：users / sessions / messages / skills / billing_records
"""

import threading
from datetime import datetime
from typing import Generator, Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    """SQLAlchemy ORM 基类"""
    pass


class User(Base):
    """用户表（与桌面版 schema 兼容子集）"""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(64), unique=True, nullable=False, index=True)
    password_hash = Column(String(256), nullable=False)
    email = Column(String(128), nullable=True)
    role = Column(String(32), default="user", nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_login_at = Column(DateTime, nullable=True)


class SessionModel(Base):
    """会话表"""

    __tablename__ = "sessions"

    id = Column(String(64), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String(256), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class Message(Base):
    """消息表"""

    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(64), ForeignKey("sessions.id"), nullable=False, index=True)
    role = Column(String(32), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class Skill(Base):
    """技能表（本地缓存）"""

    __tablename__ = "skills"

    id = Column(String(64), primary_key=True)
    name = Column(String(128), nullable=False)
    description = Column(Text, nullable=True)
    content = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class BillingRecord(Base):
    """计费记录表（本地缓存）"""

    __tablename__ = "billing_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    amount = Column(Integer, nullable=False)
    description = Column(String(256), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class UserPreference(Base):
    """
    用户偏好表（key-value 存储）

    与桌面版 backend/db/models.py 的 user_preferences 对齐。
    前端 modelStore 通过 /api/user/preferences 读写 selectedModel 等偏好。
    """

    __tablename__ = "user_preferences"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    key = Column(String(128), nullable=False)
    value = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


# 引擎与 Session 工厂（懒加载）
_engine = None
_SessionLocal: Optional[sessionmaker] = None
_db_lock = threading.Lock()


def get_engine():
    """获取 SQLAlchemy 引擎（懒加载，线程安全）"""
    global _engine
    if _engine is None:
        with _db_lock:
            if _engine is None:
                settings = get_settings()
                _engine = create_engine(
                    settings.database_url,
                    connect_args={"check_same_thread": False},
                    echo=False,
                    pool_pre_ping=True,
                )
    return _engine


def get_session_factory() -> sessionmaker:
    """获取 Session 工厂"""
    global _SessionLocal
    if _SessionLocal is None:
        with _db_lock:
            if _SessionLocal is None:
                _SessionLocal = sessionmaker(
                    bind=get_engine(),
                    autoflush=False,
                    expire_on_commit=False,
                )
    return _SessionLocal


def init_db() -> None:
    """初始化数据库：创建所有表"""
    Base.metadata.create_all(bind=get_engine())


def get_db() -> Generator[Session, None, None]:
    """FastAPI 依赖：提供数据库 Session"""
    db = get_session_factory()()
    try:
        yield db
    finally:
        db.close()


def ensure_owner_user() -> None:
    """
    确保默认管理员账号存在（首次启动时自动创建）

    与桌面版 backend/db/init_db.py 的 ensure_owner_user 对齐。
    """
    from .security import hash_password

    settings = get_settings()
    init_db()

    db = get_session_factory()()
    try:
        existing = db.query(User).filter(
            User.username == settings.default_admin_username
        ).first()
        if existing is None:
            admin = User(
                username=settings.default_admin_username,
                password_hash=hash_password(settings.default_admin_password),
                email=None,
                role="admin",
                is_active=True,
            )
            db.add(admin)
            db.commit()
    finally:
        db.close()
