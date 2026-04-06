"""
数据库模型与会话管理模块，负责 ORM 实体定义、数据库连接与初始化逻辑。
这里的结构定义直接决定了持久化层能够保存哪些业务数据。
"""

from sqlalchemy import create_engine, String, Integer, Float, Boolean, DateTime, Text, JSON, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Mapped, mapped_column
from datetime import datetime, timezone
from typing import Optional, Any, Dict, List
from loguru import logger
from config.settings import settings


engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {},
    pool_size=5,
    max_overflow=10,
    pool_recycle=3600
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """
    封装与Base相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    pass


class User(Base):
    """
    封装与User相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String, default="user")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )


class Skill(Base):
    """
    封装与Skill相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    __tablename__ = "skills"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    version: Mapped[str] = mapped_column(String)
    description: Mapped[str] = mapped_column(Text)
    config: Mapped[Dict[str, Any]] = mapped_column(JSON)
    category: Mapped[str] = mapped_column(String, default="general")
    tags: Mapped[List[str]] = mapped_column(JSON)
    dependencies: Mapped[List[str]] = mapped_column(JSON)
    author: Mapped[str] = mapped_column(String)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    usage_count: Mapped[int] = mapped_column(Integer, default=0)
    installed_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class Plugin(Base):
    """
    封装与Plugin相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    __tablename__ = "plugins"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String)
    version: Mapped[str] = mapped_column(String)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    config: Mapped[Dict[str, Any]] = mapped_column(JSON)
    category: Mapped[str] = mapped_column(String, default="general")
    author: Mapped[str] = mapped_column(String)
    source: Mapped[str] = mapped_column(String)
    dependencies: Mapped[List[str]] = mapped_column(JSON)
    installed_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class SkillExecutionLog(Base):
    """
    封装与SkillExecutionLog相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    __tablename__ = "skill_execution_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    skill_id: Mapped[str] = mapped_column(String, index=True)
    skill_name: Mapped[str] = mapped_column(String, index=True)
    inputs: Mapped[Dict[str, Any]] = mapped_column(JSON)
    outputs: Mapped[Dict[str, Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String)
    execution_time: Mapped[float] = mapped_column(Float)
    error_message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class PluginExecutionLog(Base):
    """
    封装与PluginExecutionLog相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    __tablename__ = "plugin_execution_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    plugin_id: Mapped[str] = mapped_column(String, index=True)
    plugin_name: Mapped[str] = mapped_column(String, index=True)
    method: Mapped[str] = mapped_column(String)
    inputs: Mapped[Dict[str, Any]] = mapped_column(JSON)
    outputs: Mapped[Dict[str, Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String)
    execution_time: Mapped[float] = mapped_column(Float)
    error_message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class ShortTermMemory(Base):
    """
    封装与ShortTermMemory相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    __tablename__ = "short_term_memory"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String, index=True)
    role: Mapped[str] = mapped_column(String)
    content: Mapped[str] = mapped_column(Text)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class LongTermMemory(Base):
    """
    封装与LongTermMemory相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    __tablename__ = "long_term_memory"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[List[float]] = mapped_column(JSON)
    importance: Mapped[float] = mapped_column(Float, default=0.5)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    access_count: Mapped[int] = mapped_column(Integer, default=0)
    last_access: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class BehaviorLog(Base):
    """
    封装与BehaviorLog相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    __tablename__ = "behavior_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String, index=True)
    action_type: Mapped[str] = mapped_column(String)
    details: Mapped[Dict[str, Any]] = mapped_column(JSON)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class ExperienceMemory(Base):
    """
    封装与ExperienceMemory相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    __tablename__ = "experience_memory"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String, index=True)
    experience_type: Mapped[str] = mapped_column(String, index=True)
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text)
    trigger_conditions: Mapped[Dict[str, Any]] = mapped_column(JSON)
    success_metrics: Mapped[float] = mapped_column(Float, default=0.0)
    usage_count: Mapped[int] = mapped_column(Integer, default=0)
    success_count: Mapped[int] = mapped_column(Integer, default=0)
    source_task: Mapped[str] = mapped_column(String, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    last_access: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    confidence: Mapped[float] = mapped_column(Float, default=0.5, index=True)
    experience_metadata: Mapped[Dict[str, Any]] = mapped_column(JSON)


class AuditLog(Base):
    """
    封装与AuditLog相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String, index=True)
    action: Mapped[str] = mapped_column(String)
    resource: Mapped[str] = mapped_column(String)
    result: Mapped[str] = mapped_column(String)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class ExperienceExtractionLog(Base):
    """
    封装与ExperienceExtractionLog相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    __tablename__ = "experience_extraction_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String, index=True)
    session_id: Mapped[str] = mapped_column(String, index=True)
    task_summary: Mapped[str] = mapped_column(Text)
    extracted_experience: Mapped[str] = mapped_column(Text)
    extraction_trigger: Mapped[str] = mapped_column(String)
    extraction_quality: Mapped[float] = mapped_column(Float, default=0.0)
    reviewed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class PromptConfig(Base):
    """
    封装与PromptConfig相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    __tablename__ = "prompt_configs"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String)
    content: Mapped[str] = mapped_column(Text)
    variables: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )


class ConversationRecord(Base):
    """
    封装与ConversationRecord相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    __tablename__ = "conversation_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String, index=True)
    user_id: Mapped[str] = mapped_column(String, index=True)
    node_type: Mapped[str] = mapped_column(String, index=True)
    user_message: Mapped[str] = mapped_column(Text)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    provider: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    model: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    llm_input: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    llm_output: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    llm_tokens_used: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    execution_duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String, default="success")
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    record_metadata: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


def _migrate_conversation_record_metadata_column():
    """
    处理migrate、conversation、record、metadata、column相关逻辑，并为调用方返回对应结果。
    阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
    """
    inspector = inspect(engine)
    table_names = inspector.get_table_names()
    if "conversation_records" not in table_names:
        return

    columns = {column["name"] for column in inspector.get_columns("conversation_records")}
    with engine.begin() as connection:
        if "record_metadata" not in columns and "metadata" in columns:
            connection.execute(text("ALTER TABLE conversation_records RENAME COLUMN metadata TO record_metadata"))
            logger.info("Migrated conversation_records.metadata column to record_metadata")
        elif "record_metadata" in columns and "metadata" in columns:
            connection.execute(
                text(
                    "UPDATE conversation_records "
                    "SET record_metadata = COALESCE(record_metadata, metadata)"
                )
            )
            logger.info("Merged data from conversation_records.metadata into record_metadata")


def _migrate_plugin_columns():
    """
    处理migrate、plugin、columns相关逻辑，并为调用方返回对应结果。
    阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
    """
    inspector = inspect(engine)
    table_names = inspector.get_table_names()
    if "plugins" not in table_names:
        return

    columns = {column["name"] for column in inspector.get_columns("plugins")}
    with engine.begin() as connection:
        if "category" not in columns:
            connection.execute(text("ALTER TABLE plugins ADD COLUMN category VARCHAR DEFAULT 'general'"))
        if "author" not in columns:
            connection.execute(text("ALTER TABLE plugins ADD COLUMN author VARCHAR DEFAULT ''"))
        if "source" not in columns:
            connection.execute(text("ALTER TABLE plugins ADD COLUMN source VARCHAR DEFAULT ''"))
        if "dependencies" not in columns:
            connection.execute(text("ALTER TABLE plugins ADD COLUMN dependencies TEXT DEFAULT ''"))
        if "installed_at" not in columns:
            now = datetime.now(timezone.utc).isoformat()
            connection.execute(text("ALTER TABLE plugins ADD COLUMN installed_at DATETIME"))
            connection.execute(text("UPDATE plugins SET installed_at = :installed_at WHERE installed_at IS NULL"), {"installed_at": now})


def init_db():
    """
    初始化db相关运行上下文、配置或默认数据。
    这些步骤往往是其他能力能够正常运行的前置条件。
    """
    Base.metadata.create_all(bind=engine)
    _migrate_conversation_record_metadata_column()
    _migrate_plugin_columns()


def get_db():
    """
    获取db相关数据或当前状态。
    调用方通常依赖该结果继续进行后续判断、渲染或业务编排。
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
