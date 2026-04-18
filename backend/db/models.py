"""
数据库模型与会话管理模块，负责 ORM 实体定义、数据库连接与初始化逻辑。
这里的结构定义直接决定了持久化层能够保存哪些业务数据。
"""

from sqlalchemy import create_engine, String, Integer, Float, Boolean, DateTime, Text, JSON, ForeignKey, inspect, text, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Mapped, mapped_column
from datetime import datetime, timezone
from typing import Optional, Any, Dict, List
from fastapi import HTTPException
from loguru import logger
from config.settings import settings
import json
import time
import yaml


engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {},
    pool_size=5,
    max_overflow=10,
    pool_recycle=3600
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# SQL 事件监听：记录慢查询和数据库错误
_SLOW_QUERY_THRESHOLD_MS = 500


@event.listens_for(engine, "before_cursor_execute")
def _before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    """在 SQL 执行前记录起始时间"""
    conn.info.setdefault("query_start_time", []).append(time.perf_counter())


@event.listens_for(engine, "after_cursor_execute")
def _after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    """SQL 执行完成后检测慢查询"""
    start_times = conn.info.get("query_start_time")
    if not start_times:
        return
    start = start_times.pop()
    duration_ms = int((time.perf_counter() - start) * 1000)
    if duration_ms >= _SLOW_QUERY_THRESHOLD_MS:
        logger.bind(
            event="slow_query",
            module="db",
            duration_ms=duration_ms,
        ).warning(f"慢查询 ({duration_ms}ms): {statement[:200]}")


@event.listens_for(engine, "handle_error")
def _handle_db_error(exception_context):
    """数据库层面异常捕获"""
    logger.bind(
        event="db_engine_error",
        module="db",
        error_type=type(exception_context.original_exception).__name__,
    ).opt(exception=True).error(f"数据库引擎错误: {exception_context.original_exception}")


# SQLite 外键约束默认关闭，需要在每次连接时显式启用
if "sqlite" in settings.DATABASE_URL:
    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_conn, connection_record):
        """为每个 SQLite 连接启用外键约束，防止孤立数据和引用完整性违反。"""
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA foreign_keys")
        pragma_value = cursor.fetchone()
        cursor.close()
        if not pragma_value or int(pragma_value[0]) != 1:
            raise RuntimeError("SQLite foreign_keys PRAGMA 未生效，无法保证外键约束")


class Base(DeclarativeBase):
    """
    SQLAlchemy 声明式基类，所有 ORM 模型的公共父类。
    """
    pass


class User(Base):
    """
    用户模型，存储用户身份认证信息，包括用户名、密码哈希和角色。
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
    技能模型，记录已注册的 AI 技能信息，包含配置、版本和使用统计。
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
    插件模型，存储插件的基本信息、启用状态和依赖关系。
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
    技能执行日志，记录每次技能调用的输入、输出、状态和执行时间。
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


class WeixinBinding(Base):
    """
    微信绑定模型，存储用户与微信账号的绑定关系及连接参数。
    binding_status 取值: unbound / bound / expired
    """
    __tablename__ = "weixin_bindings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    weixin_account_id: Mapped[str] = mapped_column(String(200), nullable=False)
    token: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    base_url: Mapped[str] = mapped_column(String(500), default="https://ilinkai.weixin.qq.com")
    bot_type: Mapped[str] = mapped_column(String(10), default="3")
    channel_version: Mapped[str] = mapped_column(String(20), default="1.0.2")
    binding_status: Mapped[str] = mapped_column(String(50), default="unbound")
    weixin_user_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )


class PluginExecutionLog(Base):
    """
    插件执行日志，记录插件方法调用的详细信息。
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
    短期记忆模型，存储会话级别的对话上下文记忆。
    """
    __tablename__ = "short_term_memory"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String, index=True)
    role: Mapped[str] = mapped_column(String)
    content: Mapped[str] = mapped_column(Text)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class LongTermMemory(Base):
    """
    长期记忆模型，存储用户的持久化学习记忆。
    每条记忆归属于特定用户（user_id），支持多租户隔离。
    """
    __tablename__ = "long_term_memory"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[str]] = mapped_column(String, index=True, nullable=True)
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[Optional[List[float]]] = mapped_column(JSON, nullable=True)
    importance: Mapped[float] = mapped_column(Float, default=0.5)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    access_count: Mapped[int] = mapped_column(Integer, default=0)
    last_access: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    confidence: Mapped[float] = mapped_column(Float, default=0.5, index=True)
    quality_score: Mapped[float] = mapped_column(Float, default=0.0)
    archive_status: Mapped[str] = mapped_column(String(50), default="active", index=True)
    memory_metadata: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)


class Workflow(Base):
    """
    工作流定义模型，存储用户创建的自动化流程与原始定义。
    """
    __tablename__ = "workflows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String, index=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    format: Mapped[str] = mapped_column(String(20), default="yaml")
    definition: Mapped[Dict[str, Any]] = mapped_column(JSON)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )


class WorkflowStep(Base):
    """
    工作流步骤模型，按顺序持久化顶层步骤定义，便于调试与审计。
    """
    __tablename__ = "workflow_steps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workflow_id: Mapped[int] = mapped_column(Integer, index=True)
    step_key: Mapped[str] = mapped_column(String(100), index=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    step_type: Mapped[str] = mapped_column(String(50), index=True)
    step_order: Mapped[int] = mapped_column(Integer, default=0)
    definition: Mapped[Dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class WorkflowExecution(Base):
    """
    工作流执行记录模型，保存输入、输出、状态与错误信息。
    """
    __tablename__ = "workflow_executions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workflow_id: Mapped[Optional[int]] = mapped_column(Integer, index=True, nullable=True)
    workflow_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    user_id: Mapped[Optional[str]] = mapped_column(String, index=True, nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="pending", index=True)
    input_payload: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    output_payload: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    execution_metadata: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class ScheduledTask(Base):
    """
    定时任务模型，保存一次性任务的触发时间、提示词与运行状态。
    """
    __tablename__ = "scheduled_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200), default="")
    prompt: Mapped[str] = mapped_column(Text)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    status: Mapped[str] = mapped_column(String(50), default="pending", index=True)
    provider: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    model: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    last_error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    task_metadata: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class ScheduledTaskExecution(Base):
    """
    定时任务执行记录模型，保存每次调度触发后的输出结果与错误信息。
    """
    __tablename__ = "scheduled_task_executions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(Integer, ForeignKey("scheduled_tasks.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    task_title: Mapped[str] = mapped_column(String(200), default="")
    prompt: Mapped[str] = mapped_column(Text)
    scheduled_for: Mapped[datetime] = mapped_column(DateTime, index=True)
    status: Mapped[str] = mapped_column(String(50), default="running", index=True)
    response: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    provider: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    model: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    request_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    execution_metadata: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class BehaviorLog(Base):
    """
    用户行为埋点日志，记录用户操作类型和详情。
    """
    __tablename__ = "behavior_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String, index=True)
    action_type: Mapped[str] = mapped_column(String)
    details: Mapped[Dict[str, Any]] = mapped_column(JSON)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class ExperienceMemory(Base):
    """
    经验记忆模型，存储从任务执行中提取的可复用经验，支持置信度和使用统计。
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


class Role(Base):
    """
    角色模型，定义系统中的角色及其对应的权限集合。
    """
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    display_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    permissions: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class UserRole(Base):
    """
    用户角色关联模型，记录用户与角色的绑定关系。
    """
    __tablename__ = "user_roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    role_name: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    assigned_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class AuditLog(Base):
    """
    审计日志模型，记录用户对资源的操作历史，包含操作详情和来源 IP。
    """
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[str]] = mapped_column(String(100), index=True, nullable=True)
    action: Mapped[str] = mapped_column(String(200), nullable=False)
    resource: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    result: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class ExperienceExtractionLog(Base):
    """
    经验提取日志，记录每次经验自动提取的过程和质量评估。
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
    提示词配置模型，存储系统提示词模板及其变量定义。
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
    会话记录模型，完整记录每次会话各节点的执行情况和 LLM 调用详情。
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


def _migrate_conversation_record_metadata_column(use_engine=None):
    """
    迁移 conversation_records 表的 metadata 列到 record_metadata 列。
    支持传入自定义 engine，确保在测试或多库场景下迁移操作落到正确数据库。
    """
    target_engine = use_engine or engine
    inspector = inspect(target_engine)
    table_names = inspector.get_table_names()
    if "conversation_records" not in table_names:
        return

    columns = {column["name"] for column in inspector.get_columns("conversation_records")}
    with target_engine.begin() as connection:
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


def _migrate_plugin_columns(use_engine=None):
    """
    迁移 plugins 表，补齐缺失的列。
    支持传入自定义 engine，确保迁移操作落到正确数据库。
    """
    target_engine = use_engine or engine
    inspector = inspect(target_engine)
    table_names = inspector.get_table_names()
    if "plugins" not in table_names:
        return

    columns = {column["name"] for column in inspector.get_columns("plugins")}
    with target_engine.begin() as connection:
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


def _migrate_long_term_memory_user_id(use_engine=None):
    """
    为 long_term_memory 表补齐 user_id 列，实现多租户隔离。
    支持传入自定义 engine，确保迁移操作落到正确数据库。
    """
    target_engine = use_engine or engine
    inspector = inspect(target_engine)
    table_names = inspector.get_table_names()
    if "long_term_memory" not in table_names:
        return

    columns = {column["name"] for column in inspector.get_columns("long_term_memory")}
    if "user_id" not in columns:
        with target_engine.begin() as connection:
            connection.execute(text("ALTER TABLE long_term_memory ADD COLUMN user_id VARCHAR"))
            logger.info("Migrated long_term_memory: added user_id column for multi-tenant isolation")


def _migrate_long_term_memory_enhancements(use_engine=None):
    """
    为长期记忆补齐质量评估、归档和元数据字段，支持增强记忆工作流。
    """
    target_engine = use_engine or engine
    inspector = inspect(target_engine)
    table_names = inspector.get_table_names()
    if "long_term_memory" not in table_names:
        return

    columns = {column["name"] for column in inspector.get_columns("long_term_memory")}
    with target_engine.begin() as connection:
        if "confidence" not in columns:
            connection.execute(text("ALTER TABLE long_term_memory ADD COLUMN confidence FLOAT DEFAULT 0.5"))
            connection.execute(text("UPDATE long_term_memory SET confidence = 0.5 WHERE confidence IS NULL"))
        if "quality_score" not in columns:
            connection.execute(text("ALTER TABLE long_term_memory ADD COLUMN quality_score FLOAT DEFAULT 0.0"))
            connection.execute(text("UPDATE long_term_memory SET quality_score = 0.0 WHERE quality_score IS NULL"))
        if "archive_status" not in columns:
            connection.execute(text("ALTER TABLE long_term_memory ADD COLUMN archive_status VARCHAR(50) DEFAULT 'active'"))
            connection.execute(text("UPDATE long_term_memory SET archive_status = 'active' WHERE archive_status IS NULL OR archive_status = ''"))
        if "memory_metadata" not in columns:
            connection.execute(text("ALTER TABLE long_term_memory ADD COLUMN memory_metadata TEXT DEFAULT '{}'"))
            connection.execute(text("UPDATE long_term_memory SET memory_metadata = '{}' WHERE memory_metadata IS NULL OR memory_metadata = ''"))


def _migrate_audit_log_columns(use_engine=None):
    """
    为 audit_logs 表补齐 details、ip_address、created_at 列，
    同时将旧的 timestamp 列数据迁移到 created_at。
    """
    target_engine = use_engine or engine
    inspector = inspect(target_engine)
    table_names = inspector.get_table_names()
    if "audit_logs" not in table_names:
        return

    columns = {column["name"] for column in inspector.get_columns("audit_logs")}
    with target_engine.begin() as connection:
        if "details" not in columns:
            connection.execute(text("ALTER TABLE audit_logs ADD COLUMN details TEXT"))
        if "ip_address" not in columns:
            connection.execute(text("ALTER TABLE audit_logs ADD COLUMN ip_address VARCHAR(50)"))
        if "created_at" not in columns:
            connection.execute(text("ALTER TABLE audit_logs ADD COLUMN created_at DATETIME"))
            if "timestamp" in columns:
                connection.execute(text("UPDATE audit_logs SET created_at = timestamp WHERE created_at IS NULL"))
            logger.info("Migrated audit_logs: added created_at column")


def _normalize_legacy_json_column_value(raw_value: Any, expected_type: type, default_value: Any) -> str:
    """
    将历史遗留的 JSON 文本、YAML 文本或空值统一转换为合法 JSON 字符串。
    skills 表在早期版本中曾直接存储 YAML，若继续按 JSON 列读取会在 ORM 阶段报错。
    """
    def _dump_json(value: Any) -> str:
        """
        统一 JSON 序列化策略。
        历史 YAML 中可能含有 date/datetime 等 Python 标量，这里转成字符串以保证迁移可落库。
        """
        return json.dumps(value, ensure_ascii=False, default=str)

    if raw_value is None:
        return _dump_json(default_value)
    if isinstance(raw_value, expected_type):
        return _dump_json(raw_value)

    text_value = str(raw_value).strip()
    if not text_value:
        return json.dumps(default_value, ensure_ascii=False)

    try:
        loaded = json.loads(text_value)
    except Exception:
        loaded = None
    if isinstance(loaded, expected_type):
        return _dump_json(loaded)

    try:
        loaded = yaml.safe_load(text_value)
    except Exception:
        loaded = None
    if isinstance(loaded, expected_type):
        return _dump_json(loaded)

    return _dump_json(default_value)


def _migrate_skill_json_columns(use_engine=None):
    """
    将 skills 表中的历史 YAML/文本配置迁移为合法 JSON，避免 ORM 读取时抛出 JSONDecodeError。
    """
    target_engine = use_engine or engine
    inspector = inspect(target_engine)
    table_names = inspector.get_table_names()
    if "skills" not in table_names:
        return

    columns = {column["name"] for column in inspector.get_columns("skills")}
    required_columns = {"id", "config", "tags", "dependencies"}
    if not required_columns.issubset(columns):
        return

    with target_engine.begin() as connection:
        rows = connection.execute(
            text("SELECT id, config, tags, dependencies FROM skills")
        ).mappings().all()
        for row in rows:
            normalized_config = _normalize_legacy_json_column_value(
                row.get("config"),
                dict,
                {},
            )
            normalized_tags = _normalize_legacy_json_column_value(
                row.get("tags"),
                list,
                [],
            )
            normalized_dependencies = _normalize_legacy_json_column_value(
                row.get("dependencies"),
                list,
                [],
            )
            connection.execute(
                text(
                    "UPDATE skills "
                    "SET config = :config, tags = :tags, dependencies = :dependencies "
                    "WHERE id = :id"
                ),
                {
                    "id": row["id"],
                    "config": normalized_config,
                    "tags": normalized_tags,
                    "dependencies": normalized_dependencies,
                },
            )


def init_db(bind_engine=None):
    """
    初始化数据库表结构并执行必要的迁移操作。
    支持自定义 engine，便于测试环境使用独立数据库。
    """
    use_engine = bind_engine or engine
    Base.metadata.create_all(bind=use_engine)
    _migrate_conversation_record_metadata_column(use_engine=use_engine)
    _migrate_plugin_columns(use_engine=use_engine)
    _migrate_long_term_memory_user_id(use_engine=use_engine)
    _migrate_long_term_memory_enhancements(use_engine=use_engine)
    _migrate_audit_log_columns(use_engine=use_engine)
    _migrate_skill_json_columns(use_engine=use_engine)


def get_db():
    """
    获取db相关数据或当前状态。
    调用方通常依赖该结果继续进行后续判断、渲染或业务编排。
    """
    db = SessionLocal()
    try:
        yield db
    except HTTPException as e:
        # 鉴权失败等 HTTP 异常属于请求级拒绝，不应误记为数据库会话故障。
        if e.status_code in {401, 403}:
            logger.bind(
                event="db_session_http_exception",
                module="db",
                status_code=e.status_code,
                error_type=type(e).__name__,
            ).info(f"数据库会话提前结束（鉴权拒绝）: {e.detail}")
        else:
            logger.bind(
                event="db_session_http_exception",
                module="db",
                status_code=e.status_code,
                error_type=type(e).__name__,
            ).warning(f"数据库会话提前结束（HTTP 异常）: {e.detail}")
        db.rollback()
        raise
    except Exception as e:
        logger.bind(
            event="db_session_error",
            module="db",
            error_type=type(e).__name__,
        ).opt(exception=True).error(f"数据库会话异常: {e}")
        db.rollback()
        raise
    finally:
        db.close()
