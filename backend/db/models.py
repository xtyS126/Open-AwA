"""
数据库模型与会话管理模块，负责 ORM 实体定义、数据库连接与初始化逻辑。
这里的结构定义直接决定了持久化层能够保存哪些业务数据。
"""

from sqlalchemy import create_engine, String, Integer, Float, Boolean, DateTime, Text, JSON, ForeignKey, Index, inspect, text, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Mapped, mapped_column
from datetime import datetime, timezone
from typing import Optional, Any, Dict, List
from fastapi import HTTPException
from loguru import logger
from config.settings import settings
import json
import time
import yaml


_sqlite_connect_args = {}
if "sqlite" in settings.DATABASE_URL:
    _sqlite_connect_args = {
        "check_same_thread": False,
        # WAL 模式提升并发读写性能；busy_timeout 减少 database is locked 错误
        "timeout": 30,
    }

engine = create_engine(
    settings.DATABASE_URL,
    connect_args=_sqlite_connect_args,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_recycle=3600,
    # SQLite 需要 WAL 模式在引擎级别设置（PRAGMA journal_mode=WAL）
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# SQLite 连接配置：使用 'checkout' 事件确保每次从连接池获取时都设置 PRAGMA
# （'connect' 仅在新连接创建时触发，连接池复用时会被跳过）
if "sqlite" in settings.DATABASE_URL:
    @event.listens_for(engine, "checkout")
    def _setup_sqlite_connection(dbapi_connection, connection_record, connection_proxy):
        """确保每次 checkout 的连接都启用 WAL、外键约束和繁忙超时。"""
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

# SQL 事件监听：记录慢查询和数据库错误
# 慢查询阈值从 settings 读取，支持不同部署环境调优
from config.settings import settings as _db_settings
_SLOW_QUERY_THRESHOLD_MS = _db_settings.SLOW_QUERY_THRESHOLD_MS


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


class Base(DeclarativeBase):
    """
    SQLAlchemy 声明式基类，所有 ORM 模型的公共父类。
    """
    pass


class User(Base):
    """
    用户模型，存储用户身份认证信息，包括用户名、密码哈希和角色。
    扩展支持用户画像：头像、昵称、邮箱、电话、AI 画像数据。
    """
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String, default="user")
    avatar_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    nickname: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    profile_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )


class Workspace(Base):
    """
    智能体工作区模型，存储独立智能体的配置、人设、频道和技能绑定。
    每个工作区拥有独立的记忆、对话历史和定时任务，互不干扰。
    """
    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(String(50), primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(String(500), default="")
    agent_type: Mapped[str] = mapped_column(String(50), default="default")  # default / coding / qa / writer / custom
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # JSON 配置：包含模型选择、工具开关、运行参数等
    config_json: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    # 已启用的频道列表
    enabled_channels_json: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    # 技能启用状态 {skill_name: enabled}
    skills_json: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    # 人设文件（AGENTS.md / SOUL.md / PROFILE.md / HEARTBEAT.md 等）
    persona_files_json: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    # 心跳配置
    heartbeat_config_json: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )


class LoginDevice(Base):
    """
    登录设备记录，追踪用户的登录设备和会话信息。
    用于设备管理和远程登出功能。
    """
    __tablename__ = "login_devices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    device_type: Mapped[str] = mapped_column(String(50), default="unknown")
    ip_address: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    logged_in_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    last_active_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    is_online: Mapped[bool] = mapped_column(Boolean, default=True)
    jti: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)


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
    granted_permissions: Mapped[List[str]] = mapped_column(JSON, default=list)
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
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=15)
    auto_start_reply: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )


class WeixinAutoReplyRule(Base):
    """
    微信自动回复规则模型，支持关键词和正则匹配。
    """
    __tablename__ = "weixin_auto_reply_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    rule_name: Mapped[str] = mapped_column(String(100), nullable=False)
    match_type: Mapped[str] = mapped_column(String(20), default="keyword") # keyword, regex
    match_pattern: Mapped[str] = mapped_column(String(500), nullable=False)
    reply_content: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    priority: Mapped[int] = mapped_column(Integer, default=0)
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


class Conversation(Base):
    """
    会话聚合模型，保存聊天会话的标题、摘要、最后消息和软删除状态。
    """
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    user_id: Mapped[str] = mapped_column(String(100), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200), default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    last_message_preview: Mapped[str] = mapped_column(Text, default="")
    last_message_role: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        index=True,
    )
    last_message_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)
    restored_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    purge_after: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)
    conversation_metadata: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)


class ShortTermMemory(Base):
    """
    短期记忆模型，存储会话级别的对话上下文记忆。
    """
    __tablename__ = "short_term_memory"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workspace_id: Mapped[Optional[str]] = mapped_column(String(50), index=True, nullable=True, default="default")
    session_id: Mapped[str] = mapped_column(String, index=True)
    role: Mapped[str] = mapped_column(String)
    content: Mapped[str] = mapped_column(Text)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    # 思维链内容（推理过程文本），用于历史恢复时展示
    reasoning_content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # 工具调用事件列表（JSON），用于历史恢复时重建工具调用展示
    tool_events: Mapped[Optional[List[Dict[str, Any]]]] = mapped_column(JSON, nullable=True)

    __table_args__ = (
        Index("ix_stm_session_workspace_ts", "session_id", "workspace_id", "timestamp"),
    )


class LongTermMemory(Base):
    """
    长期记忆模型，存储用户的持久化学习记忆。
    每条记忆归属于特定用户（user_id），支持多租户隔离。
    支持多层记忆架构：core（核心事实）/episodic（情景记忆）/semantic（语义知识）/working（工作记忆）。
    """
    __tablename__ = "long_term_memory"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workspace_id: Mapped[Optional[str]] = mapped_column(String(50), index=True, nullable=True, default="default")
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
    # 记忆层级：core（核心事实，永久保留）/episodic（情景记忆，时间衰减）/semantic（语义知识，关联强化）/working（工作记忆，会话级）
    memory_layer: Mapped[str] = mapped_column(String(20), default="semantic", index=True, comment="记忆层级：core/episodic/semantic/working")

    __table_args__ = (
        Index("ix_ltm_ws_archive", "workspace_id", "archive_status"),
        Index("ix_ltm_user_layer", "user_id", "memory_layer"),
    )


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
    定时任务模型，保存一次性或每日重复任务的调度信息、提示词与运行状态。
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
    is_daily: Mapped[bool] = mapped_column(Boolean, default=False)
    cron_expression: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    weekdays: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    daily_time: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    task_type: Mapped[str] = mapped_column(String(50), default="ai_prompt")
    plugin_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    command_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    command_params: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
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
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)

    __table_args__ = (
        Index("ix_behavior_user_action_ts", "user_id", "action_type", "timestamp"),
    )


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
    role_name: Mapped[str] = mapped_column(String(50), ForeignKey("roles.name"), nullable=False, index=True)
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


class LoginRateLimit(Base):
    """
    登录限流记录模型，持久化存储登录失败计数和封禁状态。
    支持多 worker 部署时限流状态共享，替代进程内存字典方案。
    每条记录以 rate_limit_key（IP + 用户名哈希）唯一标识。
    """
    __tablename__ = "login_rate_limits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rate_limit_key: Mapped[str] = mapped_column(String(300), unique=True, nullable=False, index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    first_attempt_at: Mapped[float] = mapped_column(Float, default=0.0)
    blocked_until: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )


class UserFeedback(Base):
    """
    用户对助手消息的显式反馈记录，支持点赞/点踩及可选备注。
    """
    __tablename__ = "user_feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True, comment="会话 ID")
    message_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True, comment="消息 ID")
    user_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True, comment="用户 ID")
    rating: Mapped[int] = mapped_column(Integer, nullable=False, comment="评分：1=点赞，-1=点踩")
    comment: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True, comment="反馈备注")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), comment="反馈时间")


class AgentRole(Base):
    """AI 角色定义模型，存储角色的性格、专长、工具权限和模型配置。"""
    __tablename__ = "agent_roles"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    avatar_url: Mapped[str] = mapped_column(String(500), default="")

    # 角色核心定义
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    personality: Mapped[dict] = mapped_column(JSON, default=dict)
    expertise: Mapped[dict] = mapped_column(JSON, default=dict)

    # 知识绑定
    knowledge_base_ids: Mapped[dict] = mapped_column(JSON, default=list)

    # 工具权限
    allowed_tools: Mapped[dict] = mapped_column(JSON, default=list)
    allowed_skills: Mapped[dict] = mapped_column(JSON, default=list)

    # 模型配置
    model_config: Mapped[dict] = mapped_column(JSON, default=dict)

    # 元数据
    creator_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    is_public: Mapped[bool] = mapped_column(Boolean, default=False)
    usage_count: Mapped[int] = mapped_column(Integer, default=0)
    is_preset: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc)
    )


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


class ConversationData(Base):
    """对话数据收集模型，记录完整对话上下文和角色信息。"""
    __tablename__ = "conversation_data"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(String(64), index=True)
    role_id: Mapped[str] = mapped_column(String(64), default="")
    user_message: Mapped[str] = mapped_column(Text)
    assistant_message: Mapped[str] = mapped_column(Text)
    tools_used: Mapped[dict] = mapped_column(JSON, default=list)
    model_used: Mapped[str] = mapped_column(String(100), default="")
    token_count: Mapped[dict] = mapped_column(JSON, default=dict)
    response_time_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), index=True
    )


class ToolCallData(Base):
    """工具调用数据收集模型，记录工具名、参数、结果和耗时。"""
    __tablename__ = "tool_call_data"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(String(64), index=True)
    role_id: Mapped[str] = mapped_column(String(64), default="")
    tool_name: Mapped[str] = mapped_column(String(100))
    tool_params: Mapped[dict] = mapped_column(JSON)
    result_summary: Mapped[str] = mapped_column(Text, default="")
    success: Mapped[bool] = mapped_column(Boolean)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), index=True
    )


class ExecutionTrace(Base):
    """执行轨迹模型，记录规划-执行-反馈完整链路。"""
    __tablename__ = "execution_trace"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(String(64), index=True)
    role_id: Mapped[str] = mapped_column(String(64), default="")
    plan_steps: Mapped[dict] = mapped_column(JSON)
    executed_steps: Mapped[dict] = mapped_column(JSON)
    error_steps: Mapped[dict] = mapped_column(JSON, default=list)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    rollback_count: Mapped[int] = mapped_column(Integer, default=0)
    total_duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), index=True
    )


class RoleSwitchEvent(Base):
    """角色切换事件模型，记录角色切换时间和原因。"""
    __tablename__ = "role_switch_event"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    from_role_id: Mapped[str] = mapped_column(String(64), default="")
    to_role_id: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), index=True
    )


class PromptConfig(Base):
    """
    提示词配置模型，存储系统提示词模板及其变量定义。
    """
    __tablename__ = "prompt_configs"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String)
    content: Mapped[str] = mapped_column(Text)
    variables: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), index=True
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
    # 消息唯一 ID，用于 JSONL 旁路日志与数据库记录的关联（可选，向后兼容）
    uuid: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    # 父消息 UUID，形成消息父链，支持子 Agent 旁路链回溯（可选，向后兼容）
    parent_uuid: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    # 是否为子 Agent 旁路链消息，默认 False 表示主链消息
    is_sidechain: Mapped[bool] = mapped_column(Boolean, default=False)

    __table_args__ = (
        Index("ix_conversations_user_ts", "user_id", "timestamp"),
    )


class TokenBlacklist(Base):
    """
    JWT 令牌黑名单模型，持久化存储已登出令牌，防止服务器重启后黑名单丢失。
    """
    __tablename__ = "token_blacklist"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    jti: Mapped[str] = mapped_column(String(36), unique=True, index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class TaskAgentDefinition(Base):
    """
    代理类型定义持久化模型，存储用户自定义代理类型的静态配置。
    内置代理类型（Explore/Plan/general-purpose）仍由代码定义，用户可通过此表扩展。
    """
    __tablename__ = "task_agent_definitions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    scope: Mapped[str] = mapped_column(String(20), default="user")  # system / project / user / plugin
    description: Mapped[str] = mapped_column(String(500), default="")
    system_prompt: Mapped[str] = mapped_column(Text, default="")
    tools_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    disallowed_tools_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    model: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    permission_mode: Mapped[str] = mapped_column(String(30), default="default")
    memory_mode: Mapped[str] = mapped_column(String(20), default="none")
    background_default: Mapped[bool] = mapped_column(Boolean, default=False)
    isolation_mode: Mapped[str] = mapped_column(String(20), default="inherit")
    color: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    metadata_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )


class TaskAgentSession(Base):
    """
    代理运行实例模型，记录每一次子代理派生的会话状态、运行模式与结果摘要。
    支持显式事务领取与超时回收，确保分布式场景下的运行权安全。
    """
    __tablename__ = "task_agent_sessions"

    agent_id: Mapped[str] = mapped_column(String(50), primary_key=True, index=True)
    parent_session_id: Mapped[Optional[str]] = mapped_column(String(100), index=True, nullable=True)
    root_chat_session_id: Mapped[Optional[str]] = mapped_column(String(100), index=True, nullable=True)
    agent_type: Mapped[str] = mapped_column(String(100), default="general-purpose")
    state: Mapped[str] = mapped_column(String(50), default="created", index=True)
    run_mode: Mapped[str] = mapped_column(String(20), default="foreground")
    isolation_mode: Mapped[str] = mapped_column(String(20), default="inherit")
    transcript_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    lease_owner: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    lease_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class SubagentDefinition(Base):
    """
    子智能体图定义持久化模型。

    存储用户自定义的 Agent 图结构（节点、边、入口、出口），
    服务重启后可从数据库恢复，避免运行时态丢失。
    """
    __tablename__ = "subagent_definitions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    # 图结构 JSON：{nodes: [...], edges: [...], entry_point, finish_points}
    graph_definition: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    # 创建者用户 ID（多租户隔离）
    user_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    # 是否为内置图（内置图不可删除）
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    # 标签（用于分类和搜索）
    tags: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (
        Index("ix_subagent_def_user_name", "user_id", "name"),
    )


class SubagentExecutionHistory(Base):
    """
    子智能体执行历史记录模型。

    持久化每次图执行的结果，便于后续查询、审计和回放。
    """
    __tablename__ = "subagent_execution_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 关联的图定义名称（可为内置图名）
    graph_name: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    # 执行触发者用户 ID
    user_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    # 执行模式：graph / sequential / parallel / delegate
    execution_mode: Mapped[str] = mapped_column(String(20), default="graph")
    # 初始上下文（JSON）
    initial_context: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    # 执行结果（JSON）
    results: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    # 错误信息（JSON）
    errors: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    # 执行日志（节点级执行记录）
    execution_log: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, default=list)
    # 是否成功
    success: Mapped[bool] = mapped_column(Boolean, default=False)
    # 执行耗时（秒）
    duration_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)


class TaskItem(Base):
    """
    共享任务清单项模型，记录任务主题、描述、状态、依赖与执行结果。
    支持多代理协同更新同一任务清单。
    """
    __tablename__ = "task_items"

    task_id: Mapped[str] = mapped_column(String(50), primary_key=True, index=True)
    list_id: Mapped[Optional[str]] = mapped_column(String(100), index=True, nullable=True)
    subject: Mapped[str] = mapped_column(String(300), default="")
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="pending", index=True)
    dependencies_json: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    owner_agent_id: Mapped[Optional[str]] = mapped_column(String(50), index=True, nullable=True)
    result_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    output_ref: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class TaskEvent(Base):
    """
    任务事件审计模型，记录代理生命周期与任务状态变更的结构化日志。
    """
    __tablename__ = "task_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(100), index=True)
    entity_type: Mapped[str] = mapped_column(String(50), index=True)
    entity_id: Mapped[str] = mapped_column(String(100), index=True)
    payload_json: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)


class TaskTeam(Base):
    """
    代理团队元数据模型，记录团队的 lead、状态与共享任务清单。
    支持实验性多代理协作场景。
    """
    __tablename__ = "task_teams"

    team_id: Mapped[str] = mapped_column(String(50), primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    lead_agent_id: Mapped[Optional[str]] = mapped_column(String(50), index=True, nullable=True)
    state: Mapped[str] = mapped_column(String(50), default="starting", index=True)
    task_list_id: Mapped[Optional[str]] = mapped_column(String(100), index=True, nullable=True)
    member_snapshot_json: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )


class TaskTeamMember(Base):
    """
    团队成员模型，记录成员代理 ID、角色与当前状态。
    """
    __tablename__ = "task_team_members"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    team_id: Mapped[str] = mapped_column(String(50), ForeignKey("task_teams.team_id"), index=True)
    agent_id: Mapped[str] = mapped_column(String(50), index=True)
    name: Mapped[str] = mapped_column(String(100), default="")
    role: Mapped[str] = mapped_column(String(50), default="teammate")  # lead / teammate
    state: Mapped[str] = mapped_column(String(50), default="active")  # active / idle / stopped
    joined_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class TaskMailboxMessage(Base):
    """
    代理间消息模型，记录队友之间的消息传递与送达状态。
    支持 SendMessage 的 team 通信路径。
    """
    __tablename__ = "task_mailbox_messages"

    message_id: Mapped[str] = mapped_column(String(50), primary_key=True, index=True)
    from_agent_id: Mapped[str] = mapped_column(String(50), index=True)
    to_agent_id: Mapped[str] = mapped_column(String(50), index=True)
    team_id: Mapped[Optional[str]] = mapped_column(String(50), index=True, nullable=True)
    payload_json: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    delivered: Mapped[bool] = mapped_column(Boolean, default=False)
    read_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)


class ProfileFact(Base):
    """
    用户画像事实模型，存储从对话和行为中提取的结构化用户特征信息。
    每条事实是原子的、可独立验证的、带置信度和生命周期元数据的。
    """
    __tablename__ = "profile_facts"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), index=True, nullable=False)

    # 画像维度分类
    category: Mapped[str] = mapped_column(String, nullable=False, index=True)
    # 可选值: identity, preference, expertise, behavior, goal,
    #         communication_style, emotional_state, context, custom

    # 事实的键值对
    fact_key: Mapped[str] = mapped_column(String, nullable=False)
    # 示例: "programming_language", "preferred_response_style", "active_timezone"
    fact_value: Mapped[str] = mapped_column(Text, nullable=False)
    # 示例: "Python", "简洁技术向", "UTC+8"

    # 置信度与生命周期
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    # 0.0-1.0，1.0 表示用户明确确认的事实
    source_type: Mapped[str] = mapped_column(String, default="inferred")
    # explicit(用户明确声明), inferred(LLM推断), behavioral(行为分析),
    # feedback(从反馈学习), manual(手动添加)

    # 时间戳
    first_observed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False,
                                                         default=lambda: datetime.now(timezone.utc))
    last_updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False,
                                                       default=lambda: datetime.now(timezone.utc))
    last_accessed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # 访问与验证
    access_count: Mapped[int] = mapped_column(Integer, default=0)
    verification_count: Mapped[int] = mapped_column(Integer, default=0)
    # 用户确认/否定次数

    # 来源引用
    source_session_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    source_message_ids: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True)
    # 可追溯到具体的对话轮次

    # 元数据
    fact_metadata: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    # 扩展字段: { "decay_rate": 0.01, "tags": [...], "language": "zh" }

    # 状态
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # False 表示已衰减至无效或被用户删除

    __table_args__ = (
        Index("ix_profile_facts_user_category", "user_id", "category"),
        Index("ix_profile_facts_user_active", "user_id", "is_active"),
        Index("ix_profile_facts_user_confidence", "user_id", "confidence"),
    )


class ProfileExtractionLog(Base):
    """
    用户画像提取日志，记录每次画像提取的过程、结果和质量指标。
    用于审计追踪和质量监控。
    """
    __tablename__ = "profile_extraction_logs"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), index=True, nullable=False)

    # 提取参数
    trigger_type: Mapped[str] = mapped_column(String, default="auto")
    # auto(自动触发), manual(用户手动), scheduled(定时任务)

    # 提取统计
    source_session_ids: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True)
    conversation_turns_analyzed: Mapped[int] = mapped_column(Integer, default=0)
    behavior_logs_analyzed: Mapped[int] = mapped_column(Integer, default=0)

    # 提取结果
    facts_added: Mapped[int] = mapped_column(Integer, default=0)
    facts_updated: Mapped[int] = mapped_column(Integer, default=0)
    facts_deleted: Mapped[int] = mapped_column(Integer, default=0)
    facts_unchanged: Mapped[int] = mapped_column(Integer, default=0)

    # 质量指标
    llm_model_used: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    llm_tokens_used: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    extraction_duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # 状态与错误
    status: Mapped[str] = mapped_column(String, default="success")
    # success, partial, failed, skipped
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # 时间戳
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)

    # 扩展元数据
    log_metadata: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)


class PluginVersion(Base):
    """
    插件版本历史模型，记录每个插件的版本发布信息。
    支持版本对比、升级检测、回滚操作。
    """
    __tablename__ = "plugin_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    plugin_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    changelog: Mapped[str] = mapped_column(Text, default="")
    download_url: Mapped[str] = mapped_column(String(500), default="")
    sha256_checksum: Mapped[str] = mapped_column(String(64), default="")
    min_platform_version: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    max_platform_version: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    is_published: Mapped[bool] = mapped_column(Boolean, default=True)
    published_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    # 兼容性标记：stable/beta/dev
    release_channel: Mapped[str] = mapped_column(String(20), default="stable")

    __table_args__ = (
        Index("ix_plugin_version_plugin_id_version", "plugin_id", "version", unique=True),
    )


class PluginRating(Base):
    """
    插件评分模型，每个用户对每个插件仅保留一条评分记录（覆盖更新）。
    """
    __tablename__ = "plugin_ratings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    plugin_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    user_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)  # 1-5 星
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        Index("ix_plugin_rating_plugin_user", "plugin_id", "user_id", unique=True),
    )


class PluginReview(Base):
    """
    插件评论模型，用户可对插件发表评论并附带评分。
    """
    __tablename__ = "plugin_reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    plugin_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    user_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    username: Mapped[str] = mapped_column(String(100), default="")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    rating: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # 1-5 星，可选
    is_hidden: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class PluginDownloadLog(Base):
    """
    插件下载日志模型，记录每次下载操作的状态与来源。
    """
    __tablename__ = "plugin_download_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    plugin_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    version: Mapped[str] = mapped_column(String(50), default="")
    user_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="started")
    # started/success/failed/cancelled
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source_type: Mapped[str] = mapped_column(String(20), default="remote")
    # remote/local/cache
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)


# -------- P2 安全增强：细粒度权限与主动防御 --------


class CustomRole(Base):
    """
    自定义角色模型，支持用户创建具有细粒度权限的角色。
    与内置 Role 表互补，permissions 字段存储 resource:action 格式的权限列表。
    """
    __tablename__ = "custom_roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(100), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    # 权限列表 JSON 数组，格式: ["plugin:install", "skill:execute", "model:use", "billing:view"]
    permissions: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    # 创建者用户 ID
    created_by: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class IpAccessList(Base):
    """
    IP 白名单/黑名单模型，支持单 IP 和 CIDR 网段。
    list_type: whitelist（白名单，优先级最高）/ blacklist（黑名单）
    """
    __tablename__ = "ip_access_list"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # IP 地址或 CIDR 网段，如 "192.168.1.1" 或 "10.0.0.0/8"
    ip_cidr: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    list_type: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    # whitelist / blacklist
    reason: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    # 过期时间，None 表示永不过期
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)

    __table_args__ = (
        Index("ix_ip_access_list_type_cidr", "list_type", "ip_cidr", unique=True),
    )


class AnomalyEvent(Base):
    """
    异常行为事件模型，记录检测到的异常请求模式。
    event_type: rate_burst（速率突发）/ repeated_failure（重复失败）/ suspicious_pattern（可疑模式）
    """
    __tablename__ = "anomaly_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    user_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    # 触发阈值描述，如 "100 requests in 60s"
    trigger_detail: Mapped[str] = mapped_column(Text, default="")
    # 实际观测值，如 "120 requests"
    observed_value: Mapped[str] = mapped_column(Text, default="")
    # 处置动作：warn/throttle/block
    action_taken: Mapped[str] = mapped_column(String(20), default="warn")
    is_resolved: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class CsrfToken(Base):
    """
    CSRF token 模型，支持 token 自动轮换与一次性使用。
    """
    __tablename__ = "csrf_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    token: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    user_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    session_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    is_used: Mapped[bool] = mapped_column(Boolean, default=False)
    is_revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


# -------- P3 Chain-of-Thought 推理审计 --------


class ReasoningAudit(Base):
    """
    推理审计模型，记录每次推理过程的元数据、耗时与 token 统计。
    用于推理质量分析、性能优化和成本追踪。
    """
    __tablename__ = "reasoning_audits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 会话 ID，关联 short_term_memory
    session_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    # 用户 ID
    user_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    # 模型提供商
    provider: Mapped[str] = mapped_column(String(50), default="")
    # 模型名称
    model: Mapped[str] = mapped_column(String(100), default="")
    # 推理深度（0-5）
    thinking_depth: Mapped[int] = mapped_column(Integer, default=0)
    # 复杂度等级（simple/moderate/complex）
    complexity: Mapped[str] = mapped_column(String(20), default="simple")
    # 复杂度评分（0-100）
    complexity_score: Mapped[int] = mapped_column(Integer, default=0)
    # 是否用户手动覆盖深度
    is_user_override: Mapped[bool] = mapped_column(Boolean, default=False)
    # 推理内容长度（字符数）
    reasoning_length: Mapped[int] = mapped_column(Integer, default=0)
    # 推理 token 数（区分于输出 token）
    reasoning_tokens: Mapped[int] = mapped_column(Integer, default=0)
    # 输出 token 数
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    # 输入 token 数
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    # 推理耗时（毫秒）
    reasoning_duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    # 总耗时（毫秒）
    total_duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    # 首 token 时间（毫秒，从请求开始到首个 token 返回）
    ttft_ms: Mapped[int] = mapped_column(Integer, default=0)
    # 是否成功完成
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    # 错误信息（失败时）
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # 审计元数据（JSON，存储评估原因等）
    audit_metadata: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), index=True
    )


# -------- Soul Engine 用户画像系统 --------


class UserProfile(Base):
    """
    用户五层画像模型，存储从行为中推断的用户特征。
    五层结构：surface（行为表象）/interest（兴趣偏好）/role（角色认同）/values（价值驱动）/core（核心人格）。
    """
    __tablename__ = "user_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True, nullable=False)
    # 五层画像 JSON 数据
    profile_data: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    # MBTI 类型（如 INTJ、ENFP 等）
    mbti: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    # 认知风格（如 analytical、creative、practical 等）
    cognitive_style: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    # 画像更新时间
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )
    # 画像置信度（0.0-1.0）
    confidence: Mapped[float] = mapped_column(Float, default=0.5)


class UserProfileOverride(Base):
    """
    用户画像覆盖层，存储用户手动编辑的画像信息。
    用户编辑优先于 AI 推断，实现"用户编辑 ⊕ AI 画像"的合并逻辑。
    """
    __tablename__ = "user_profile_overrides"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True, nullable=False)
    # 覆盖层 JSON 数据
    overrides: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )


class InterestProbe(Base):
    """
    兴趣推测探针，存储系统推测的用户潜在兴趣，等待用户确认或拒绝。
    通过苏格拉底式对话向用户确认，确认后写入正式画像。
    """
    __tablename__ = "interest_probes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    # 推测的兴趣假设
    hypothesis: Mapped[str] = mapped_column(Text, nullable=False)
    # 推测依据（JSON，如 {"source": "behavior_analysis", "confidence": 0.7}）
    reasoning: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    # 状态：pending（待确认）/confirmed（已确认）/rejected（已拒绝）
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    # 探针问题（苏格拉底式提问）
    probe_question: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    responded_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class MemoryDecayConfig(Base):
    """
    记忆衰减配置，存储各层记忆的衰减参数。
    支持按记忆层级配置不同的衰减函数和半衰期。
    """
    __tablename__ = "memory_decay_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 记忆层级：core/episodic/semantic/working
    layer: Mapped[str] = mapped_column(String(20), unique=True, index=True, nullable=False)
    # 衰减函数：exponential（指数衰减）/linear（线性衰减）/none（不衰减）
    decay_function: Mapped[str] = mapped_column(String(20), default="exponential")
    # 半衰期（天）
    half_life_days: Mapped[int] = mapped_column(Integer, default=30)
    # 衰减阈值（低于此值归档）
    threshold: Mapped[float] = mapped_column(Float, default=0.1)
    # 是否启用衰减
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )


class LLMUsage(Base):
    """
    LLM 用量记录，追踪每次 LLM 调用的 token 用量、成本和延迟。
    支持按用户/任务/Provider 维度统计。
    """
    __tablename__ = "llm_usage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[str]] = mapped_column(String, index=True, nullable=True)
    # 任务类型（如 soul、discovery、recommendation、evaluation、agent 等）
    task_type: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    # Provider 名称（如 openai、claude、gemini 等）
    provider: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    # 模型名称
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    # Token 用量
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    # 成本（美元）
    cost: Mapped[float] = mapped_column(Float, default=0.0)
    # 延迟（毫秒）
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    # 是否成功
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    # 错误信息
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)

    __table_args__ = (
        Index("ix_llm_usage_user_task", "user_id", "task_type"),
        Index("ix_llm_usage_provider_model", "provider", "model"),
    )


def _migrate_profile_facts_table(use_engine=None):
    """
    迁移：创建 profile_facts 和 profile_extraction_logs 表（如不存在）。
    支持传入自定义 engine，确保迁移操作落到正确数据库。
    """
    target_engine = use_engine or engine
    inspector = inspect(target_engine)
    table_names = inspector.get_table_names()
    with target_engine.begin() as connection:
        if "profile_facts" not in table_names:
            ProfileFact.__table__.create(target_engine)
            logger.info("已创建 profile_facts 表")
        if "profile_extraction_logs" not in table_names:
            ProfileExtractionLog.__table__.create(target_engine)
            logger.info("已创建 profile_extraction_logs 表")


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
        if "granted_permissions" not in columns:
            connection.execute(text("ALTER TABLE plugins ADD COLUMN granted_permissions TEXT DEFAULT '[]'"))


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


def _migrate_conversation_record_sidechain_columns(use_engine=None):
    """
    为 conversation_records 表补齐旁路链相关字段：uuid、parent_uuid、is_sidechain。
    这些字段用于 JSONL 旁路日志与数据库记录的关联，以及子 Agent 旁路链回溯。
    """
    target_engine = use_engine or engine
    inspector = inspect(target_engine)
    table_names = inspector.get_table_names()
    if "conversation_records" not in table_names:
        return

    columns = {column["name"] for column in inspector.get_columns("conversation_records")}
    with target_engine.begin() as connection:
        if "uuid" not in columns:
            connection.execute(text("ALTER TABLE conversation_records ADD COLUMN uuid VARCHAR"))
        if "parent_uuid" not in columns:
            connection.execute(text("ALTER TABLE conversation_records ADD COLUMN parent_uuid VARCHAR"))
        if "is_sidechain" not in columns:
            connection.execute(text("ALTER TABLE conversation_records ADD COLUMN is_sidechain BOOLEAN DEFAULT 0"))
            connection.execute(text("UPDATE conversation_records SET is_sidechain = 0 WHERE is_sidechain IS NULL"))


def _migrate_conversation_columns(use_engine=None):
    """
    为 conversations 表补齐会话聚合所需字段，并从历史记录中回填缺失会话。
    """
    target_engine = use_engine or engine
    inspector = inspect(target_engine)
    table_names = inspector.get_table_names()
    if "conversations" not in table_names:
        return

    columns = {column["name"] for column in inspector.get_columns("conversations")}
    with target_engine.begin() as connection:
        if "summary" not in columns:
            connection.execute(text("ALTER TABLE conversations ADD COLUMN summary TEXT DEFAULT ''"))
        if "last_message_preview" not in columns:
            connection.execute(text("ALTER TABLE conversations ADD COLUMN last_message_preview TEXT DEFAULT ''"))
        if "last_message_role" not in columns:
            connection.execute(text("ALTER TABLE conversations ADD COLUMN last_message_role VARCHAR(20)"))
        if "message_count" not in columns:
            connection.execute(text("ALTER TABLE conversations ADD COLUMN message_count INTEGER DEFAULT 0"))
            connection.execute(text("UPDATE conversations SET message_count = 0 WHERE message_count IS NULL"))
        if "created_at" not in columns:
            connection.execute(text("ALTER TABLE conversations ADD COLUMN created_at DATETIME"))
            connection.execute(text("UPDATE conversations SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL"))
        if "updated_at" not in columns:
            connection.execute(text("ALTER TABLE conversations ADD COLUMN updated_at DATETIME"))
            connection.execute(text("UPDATE conversations SET updated_at = CURRENT_TIMESTAMP WHERE updated_at IS NULL"))
        if "last_message_at" not in columns:
            connection.execute(text("ALTER TABLE conversations ADD COLUMN last_message_at DATETIME"))
        if "deleted_at" not in columns:
            connection.execute(text("ALTER TABLE conversations ADD COLUMN deleted_at DATETIME"))
        if "restored_at" not in columns:
            connection.execute(text("ALTER TABLE conversations ADD COLUMN restored_at DATETIME"))
        if "purge_after" not in columns:
            connection.execute(text("ALTER TABLE conversations ADD COLUMN purge_after DATETIME"))
        if "conversation_metadata" not in columns:
            connection.execute(text("ALTER TABLE conversations ADD COLUMN conversation_metadata TEXT DEFAULT '{}'"))
            connection.execute(
                text(
                    "UPDATE conversations "
                    "SET conversation_metadata = '{}' "
                    "WHERE conversation_metadata IS NULL OR conversation_metadata = ''"
                )
            )

    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=target_engine)
    db = session_factory()
    try:
        existing_session_ids = {
            session_id
            for session_id, in db.query(Conversation.session_id).all()
        }
        latest_records = (
            db.query(ConversationRecord)
            .order_by(ConversationRecord.timestamp.asc())
            .all()
        )
        pending_rows: Dict[str, Conversation] = {}
        for record in latest_records:
            if record.session_id in existing_session_ids:
                continue
            preview = (record.user_message or "").strip()
            title = preview.splitlines()[0][:80] if preview else "新对话"
            conversation = pending_rows.get(record.session_id)
            if conversation is None:
                conversation = Conversation(
                    session_id=record.session_id,
                    user_id=record.user_id,
                    title=title or "新对话",
                    summary=preview[:200],
                    last_message_preview=preview[:500],
                    last_message_role="user",
                    message_count=0,
                    created_at=record.timestamp or datetime.now(timezone.utc),
                    updated_at=record.timestamp or datetime.now(timezone.utc),
                    last_message_at=record.timestamp,
                    conversation_metadata={},
                )
                pending_rows[record.session_id] = conversation
            else:
                conversation.last_message_preview = preview[:500]
                conversation.summary = preview[:200]
                conversation.last_message_at = record.timestamp
                conversation.updated_at = record.timestamp or conversation.updated_at

        if pending_rows:
            short_term_counts = {
                session_id: count
                for session_id, count in db.query(
                    ShortTermMemory.session_id,
                    text("COUNT(*)")
                ).group_by(ShortTermMemory.session_id).all()
            }
            for conversation in pending_rows.values():
                conversation.message_count = int(short_term_counts.get(conversation.session_id, 0))
                db.add(conversation)
            db.commit()
    finally:
        db.close()


def _migrate_user_profile_columns(use_engine=None):
    """
    为 users 表补齐用户画像相关字段（头像、昵称、邮箱、电话、画像数据）。
    """
    target_engine = use_engine or engine
    inspector = inspect(target_engine)
    table_names = inspector.get_table_names()
    if "users" not in table_names:
        return
    columns = {column["name"] for column in inspector.get_columns("users")}
    with target_engine.begin() as connection:
        if "avatar_url" not in columns:
            connection.execute(text("ALTER TABLE users ADD COLUMN avatar_url VARCHAR(500)"))
        if "nickname" not in columns:
            connection.execute(text("ALTER TABLE users ADD COLUMN nickname VARCHAR(100)"))
        if "email" not in columns:
            connection.execute(text("ALTER TABLE users ADD COLUMN email VARCHAR(200)"))
        if "phone" not in columns:
            connection.execute(text("ALTER TABLE users ADD COLUMN phone VARCHAR(50)"))
        if "profile_data" not in columns:
            connection.execute(text("ALTER TABLE users ADD COLUMN profile_data TEXT DEFAULT '{}'"))


def _migrate_task_runtime_columns(use_engine=None):
    """
    为 task runtime 相关表补齐历史缺失列，兼容旧版本地数据库。
    当前重点修复 task_items 缺失 started_at/completed_at 时导致任务创建失败的问题。
    """
    target_engine = use_engine or engine
    inspector = inspect(target_engine)
    table_names = inspector.get_table_names()

    if "task_items" in table_names:
        columns = {column["name"] for column in inspector.get_columns("task_items")}
        with target_engine.begin() as connection:
            if "started_at" not in columns:
                connection.execute(text("ALTER TABLE task_items ADD COLUMN started_at DATETIME"))
            if "completed_at" not in columns:
                connection.execute(text("ALTER TABLE task_items ADD COLUMN completed_at DATETIME"))


def _migrate_scheduled_task_daily_columns(use_engine=None):
    """
    为 scheduled_tasks 表补齐每日执行相关字段。
    """
    target_engine = use_engine or engine
    inspector = inspect(target_engine)
    table_names = inspector.get_table_names()
    if "scheduled_tasks" not in table_names:
        return
    columns = {column["name"] for column in inspector.get_columns("scheduled_tasks")}
    with target_engine.begin() as connection:
        if "is_daily" not in columns:
            connection.execute(text("ALTER TABLE scheduled_tasks ADD COLUMN is_daily BOOLEAN DEFAULT 0"))
        if "cron_expression" not in columns:
            connection.execute(text("ALTER TABLE scheduled_tasks ADD COLUMN cron_expression VARCHAR(100)"))
        if "weekdays" not in columns:
            connection.execute(text("ALTER TABLE scheduled_tasks ADD COLUMN weekdays VARCHAR(50)"))
        if "daily_time" not in columns:
            connection.execute(text("ALTER TABLE scheduled_tasks ADD COLUMN daily_time VARCHAR(10)"))


# 注册额外模型到 Base.metadata（create_all 时自动创建表）
# 注意：以下导入与 db/permission_models.py / core/event_log.py 存在循环依赖
# 依赖 Python 模块缓存机制（import 位于 Base 定义之后）。请勿移至文件顶部。
from db.permission_models import PermissionSaved  # noqa: E402
import core.event_log  # noqa: E402, F401  # 仅用于注册 EventLog 模型到 Base.metadata


def _migrate_permission_saved(use_engine=None):
    """
    确保 permission_saved 表存在。
    通常由 init_db 开头的 create_all 统一创建，此处作为防御性兜底。
    仅创建 permission_saved 表，避免 create_all 引入不合预期的副作用。
    """
    target_engine = use_engine or engine
    inspector = inspect(target_engine)
    table_names = inspector.get_table_names()
    if "permission_saved" not in table_names:
        PermissionSaved.__table__.create(bind=target_engine, checkfirst=True)
        logger.info("已创建 permission_saved 表用于持久化权限决策")


def _migrate_short_term_memory_rich_fields(use_engine=None):
    """
    为 short_term_memory 表补齐富文本字段：思维链内容和工具调用事件列表。
    用于在历史记录恢复时保留思维链和工具调用展示数据。
    """
    target_engine = use_engine or engine
    inspector = inspect(target_engine)
    table_names = inspector.get_table_names()
    if "short_term_memory" not in table_names:
        return
    columns = {column["name"] for column in inspector.get_columns("short_term_memory")}
    with target_engine.begin() as connection:
        if "reasoning_content" not in columns:
            connection.execute(text("ALTER TABLE short_term_memory ADD COLUMN reasoning_content TEXT"))
            logger.info("Migrated short_term_memory: added reasoning_content column")
        if "tool_events" not in columns:
            connection.execute(text("ALTER TABLE short_term_memory ADD COLUMN tool_events TEXT"))
            logger.info("Migrated short_term_memory: added tool_events column")


def _migrate_agent_roles(inspector, conn) -> None:
    """迁移：创建 agent_roles 表。"""
    if "agent_roles" not in inspector.get_table_names():
        conn.execute(text("""
            CREATE TABLE agent_roles (
                id VARCHAR(64) PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                description TEXT DEFAULT '',
                avatar_url VARCHAR(500) DEFAULT '',
                system_prompt TEXT NOT NULL,
                personality JSON DEFAULT '{}',
                expertise JSON DEFAULT '{}',
                knowledge_base_ids JSON DEFAULT '[]',
                allowed_tools JSON DEFAULT '[]',
                allowed_skills JSON DEFAULT '[]',
                model_config JSON DEFAULT '{}',
                creator_id INTEGER REFERENCES users(id),
                is_public BOOLEAN DEFAULT 0,
                usage_count INTEGER DEFAULT 0,
                is_preset BOOLEAN DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """))


def _migrate_conversation_data(inspector, conn) -> None:
    """迁移：创建 conversation_data 表。"""
    if "conversation_data" not in inspector.get_table_names():
        conn.execute(text("""
            CREATE TABLE conversation_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id VARCHAR(64),
                role_id VARCHAR(64) DEFAULT '',
                user_message TEXT,
                assistant_message TEXT,
                tools_used JSON DEFAULT '[]',
                model_used VARCHAR(100) DEFAULT '',
                token_count JSON DEFAULT '{}',
                response_time_ms INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """))
        conn.execute(text("CREATE INDEX ix_conversation_data_conversation_id ON conversation_data(conversation_id)"))
        conn.execute(text("CREATE INDEX ix_conversation_data_created_at ON conversation_data(created_at)"))


def _migrate_tool_call_data(inspector, conn) -> None:
    """迁移：创建 tool_call_data 表。"""
    if "tool_call_data" not in inspector.get_table_names():
        conn.execute(text("""
            CREATE TABLE tool_call_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id VARCHAR(64),
                role_id VARCHAR(64) DEFAULT '',
                tool_name VARCHAR(100),
                tool_params JSON,
                result_summary TEXT DEFAULT '',
                success BOOLEAN,
                duration_ms INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """))
        conn.execute(text("CREATE INDEX ix_tool_call_data_conversation_id ON tool_call_data(conversation_id)"))
        conn.execute(text("CREATE INDEX ix_tool_call_data_created_at ON tool_call_data(created_at)"))


def _migrate_execution_trace(inspector, conn) -> None:
    """迁移：创建 execution_trace 表。"""
    if "execution_trace" not in inspector.get_table_names():
        conn.execute(text("""
            CREATE TABLE execution_trace (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id VARCHAR(64),
                role_id VARCHAR(64) DEFAULT '',
                plan_steps JSON,
                executed_steps JSON,
                error_steps JSON DEFAULT '[]',
                retry_count INTEGER DEFAULT 0,
                rollback_count INTEGER DEFAULT 0,
                total_duration_ms INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """))
        conn.execute(text("CREATE INDEX ix_execution_trace_conversation_id ON execution_trace(conversation_id)"))
        conn.execute(text("CREATE INDEX ix_execution_trace_created_at ON execution_trace(created_at)"))


def _migrate_role_switch_event(inspector, conn) -> None:
    """迁移：创建 role_switch_event 表。"""
    if "role_switch_event" not in inspector.get_table_names():
        conn.execute(text("""
            CREATE TABLE role_switch_event (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_role_id VARCHAR(64) DEFAULT '',
                to_role_id VARCHAR(64),
                reason TEXT DEFAULT '',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """))
        conn.execute(text("CREATE INDEX ix_role_switch_event_created_at ON role_switch_event(created_at)"))


def _migrate_user_feedback_add_columns(inspector, conn) -> None:
    """迁移：为 user_feedback 表添加 conversation_id、role_id、feedback_type 列。"""
    columns = [col["name"] for col in inspector.get_columns("user_feedback")]
    if "conversation_id" not in columns:
        conn.execute(text("ALTER TABLE user_feedback ADD COLUMN conversation_id VARCHAR(64) DEFAULT ''"))
    if "role_id" not in columns:
        conn.execute(text("ALTER TABLE user_feedback ADD COLUMN role_id VARCHAR(64) DEFAULT ''"))
    if "feedback_type" not in columns:
        conn.execute(text("ALTER TABLE user_feedback ADD COLUMN feedback_type VARCHAR(20) DEFAULT ''"))


def init_db(bind_engine=None):
    """
    初始化数据库表结构并执行必要的迁移操作。
    支持自定义 engine，便于测试环境使用独立数据库。
    """
    use_engine = bind_engine or engine
    # 计费模型已统一使用 db.models.Base，与主业务模型共享同一 Metadata
    Base.metadata.create_all(bind=use_engine)
    _migrate_conversation_record_metadata_column(use_engine=use_engine)
    _migrate_conversation_record_sidechain_columns(use_engine=use_engine)
    _migrate_plugin_columns(use_engine=use_engine)
    _migrate_long_term_memory_user_id(use_engine=use_engine)
    _migrate_long_term_memory_enhancements(use_engine=use_engine)
    _migrate_audit_log_columns(use_engine=use_engine)
    _migrate_skill_json_columns(use_engine=use_engine)
    _migrate_conversation_columns(use_engine=use_engine)
    _migrate_user_profile_columns(use_engine=use_engine)
    _migrate_task_runtime_columns(use_engine=use_engine)
    _migrate_scheduled_task_daily_columns(use_engine=use_engine)
    _migrate_short_term_memory_rich_fields(use_engine=use_engine)
    _migrate_workspace_columns(use_engine=use_engine)
    _migrate_profile_facts_table(use_engine=use_engine)
    _migrate_user_role_fk(use_engine=use_engine)
    _migrate_model_configuration_new_params(use_engine=use_engine)
    _migrate_permission_saved(use_engine=use_engine)
    # Agent 角色与数据收集相关迁移
    _inspector = inspect(use_engine)
    with use_engine.begin() as _conn:
        _migrate_agent_roles(_inspector, _conn)
        _migrate_conversation_data(_inspector, _conn)
        _migrate_tool_call_data(_inspector, _conn)
        _migrate_execution_trace(_inspector, _conn)
        _migrate_role_switch_event(_inspector, _conn)
        _migrate_user_feedback_add_columns(_inspector, _conn)


def _migrate_user_role_fk(use_engine=None):
    """
    清理 user_roles 中引用不存在角色的孤立记录，并确保新数据库包含外键约束。
    SQLite 不支持 ALTER TABLE ADD CONSTRAINT，因此仅在数据层面做完整性清理。
    外键约束在 Base.metadata.create_all() 创建新表时生效。
    """
    target_engine = use_engine or engine
    inspector = inspect(target_engine)
    table_names = inspector.get_table_names()

    if "user_roles" not in table_names or "roles" not in table_names:
        return

    with target_engine.begin() as connection:
        # 清理引用不存在角色的孤立记录
        result = connection.execute(
            text(
                "DELETE FROM user_roles WHERE role_name NOT IN "
                "(SELECT name FROM roles)"
            )
        )
        if result.rowcount > 0:
            logger.info(
                f"已清理 {result.rowcount} 条引用不存在角色的孤立 user_roles 记录"
            )


def _migrate_workspace_columns(use_engine=None):
    """
    为现有表补齐 workspace_id 列，支持多智能体工作区隔离。
    """
    target_engine = use_engine or engine
    inspector = inspect(target_engine)
    table_names = inspector.get_table_names()

    migrations = [
        ("short_term_memory", "workspace_id", "VARCHAR(50) DEFAULT 'default'"),
        ("long_term_memory", "workspace_id", "VARCHAR(50) DEFAULT 'default'"),
    ]

    for table_name, col_name, col_type in migrations:
        if table_name not in table_names:
            continue
        columns = {c["name"] for c in inspector.get_columns(table_name)}
        if col_name not in columns:
            with target_engine.begin() as connection:
                connection.execute(text(
                    f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_type}"
                ))
                logger.info(f"Migrated {table_name}: added {col_name} column")


def _migrate_model_configuration_new_params(use_engine=None):
    """
    为 model_configurations 表补齐 frequency_penalty、presence_penalty、timeout、retry_count 字段，
    支持每个模型的独立参数配置。
    """
    target_engine = use_engine or engine
    inspector = inspect(target_engine)
    table_names = inspector.get_table_names()
    if "model_configurations" not in table_names:
        return

    columns = {c["name"] for c in inspector.get_columns("model_configurations")}
    # 需要新增的字段及类型
    new_columns = [
        ("frequency_penalty", "FLOAT"),
        ("presence_penalty", "FLOAT"),
        ("timeout", "INTEGER"),
        ("retry_count", "INTEGER"),
    ]
    with target_engine.begin() as connection:
        for col_name, col_type in new_columns:
            if col_name not in columns:
                connection.execute(text(
                    f"ALTER TABLE model_configurations ADD COLUMN {col_name} {col_type}"
                ))
                logger.info(f"Migrated model_configurations: added {col_name} column")


def get_db():
    """
    获取db相关数据或当前状态。
    调用方通常依赖该结果继续进行后续判断、渲染或业务编排。
    """
    db = SessionLocal()
    try:
        yield db
    except HTTPException as e:
        # 鉴权拒绝（401/403）：正常的请求级拒绝，不应误记为错误
        if e.status_code in {401, 403}:
            logger.bind(
                event="db_session_http_exception",
                module="db",
                status_code=e.status_code,
                error_type=type(e).__name__,
            ).info(f"数据库会话提前结束（鉴权拒绝）: {e.detail}")
        elif e.status_code >= 500:
            # 服务端错误：应引起关注
            logger.bind(
                event="db_session_http_exception",
                module="db",
                status_code=e.status_code,
                error_type=type(e).__name__,
            ).error(f"数据库会话提前结束（服务端错误）: {e.detail}")
        else:
            logger.bind(
                event="db_session_http_exception",
                module="db",
                status_code=e.status_code,
                error_type=type(e).__name__,
            ).warning(f"数据库会话提前结束（HTTP 异常）: {e.detail}")
        db.rollback()
        raise
    except (KeyboardInterrupt, SystemExit):
        # 系统信号：不回滚，让进程正常退出
        db.close()
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
        if db.is_active:
            db.close()
