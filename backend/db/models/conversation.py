"""
会话域 ORM 模型：会话聚合、短期/长期记忆、会话记录、对话数据收集、
工具调用数据、执行轨迹、角色切换事件、提示词配置等。
所有模型继承 db.models.base.Base，与主业务模型共享同一 Metadata。
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from db.models.base import Base


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


class ConversationData(Base):
    """对话数据收集模型，记录完整对话上下文和角色信息。"""
    __tablename__ = "conversation_data"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(String(64), index=True)
    # role_id 索引：按角色聚合统计对话数据是高频分析场景
    role_id: Mapped[str] = mapped_column(String(64), default="", index=True)
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
    # role_id 索引：按角色分析工具使用模式
    role_id: Mapped[str] = mapped_column(String(64), default="", index=True)
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
    # role_id 索引：按角色分析执行轨迹
    role_id: Mapped[str] = mapped_column(String(64), default="", index=True)
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
