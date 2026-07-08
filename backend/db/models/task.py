"""
任务域 ORM 模型：工作流、定时任务、Task Agent 定义与会话、子智能体图、
共享任务清单、团队与消息邮箱、多 Agent 讨论任务等。
所有模型继承 db.models.base.Base，与主业务模型共享同一 Metadata。
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from db.models.base import Base


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


class DiscussionTask(Base):
    """
    多 Agent 讨论任务模型，记录待评审的提议动作、讨论上下文、当前轮次与状态。
    状态机：created -> discussing -> pending_approval -> approved/rejected -> executing -> completed/failed
    proposed_action 结构：{"type": "plugin_command"|"tool_call"|"subagent_delegate", "payload": {...}}
    """
    __tablename__ = "discussion_tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    # 发起用户（外键到 users.id；users.id 为 String 类型，故此处使用 String 以保证外键约束有效）
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    # 提议动作：{"type": "plugin_command"|"tool_call"|"subagent_delegate", "payload": {...}}
    proposed_action: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
    # 讨论上下文，默认空 dict
    context: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    # 任务状态：created/discussing/pending_approval/approved/rejected/executing/completed/failed
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="created")
    # 当前讨论轮次
    round: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # 最大讨论轮次
    max_rounds: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        Index("idx_discussion_user_status", "user_id", "status"),
        Index("idx_discussion_created_at", "created_at"),
    )


class DiscussionVote(Base):
    """
    讨论任务投票记录，每个角色（critic/validator/approver）每轮投出一票。
    transcript 存储该角色本轮发言的消息序列，便于回放完整讨论过程。
    """
    __tablename__ = "discussion_votes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    # 所属讨论任务（外键级联删除）
    discussion_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("discussion_tasks.id", ondelete="CASCADE"), nullable=False
    )
    # 投票角色：critic/validator/approver
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    # 轮次序号
    round: Mapped[int] = mapped_column(Integer, nullable=False)
    # 投票决策：approve/reject/abstain
    vote: Mapped[str] = mapped_column(String(16), nullable=False)
    # 投票理由
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # 该角色本轮发言消息序列，默认空 list
    transcript: Mapped[List[Any]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint("discussion_id", "role", "round", name="uq_discussion_vote_role_round"),
    )
