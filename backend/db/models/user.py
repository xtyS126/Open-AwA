"""
用户域 ORM 模型：用户身份、登录设备、用户画像、角色与权限关联、AI 角色定义等。
所有模型继承 db.models.base.Base，与主业务模型共享同一 Metadata。
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from db.models.base import Base


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


# ---- Soul Engine 用户画像系统 ----


class UserProfile(Base):
    """
    用户五层画像模型，存储从行为中推断的用户特征。
    五层结构：surface（行为表象）/interest（兴趣偏好）/role（角色认同）/values（价值驱动）/core（核心人格）。

    profile_json 字段为 SoulEngine 持久化层使用的 OnionProfile JSON 序列化结果，
    与 profile_data（旧字段，保留以向后兼容）并存，新写入路径只使用 profile_json。
    """
    __tablename__ = "user_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True, nullable=False)
    # 五层画像 JSON 数据（旧字段，保留以向后兼容）
    profile_data: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    # OnionProfile 序列化后的 JSON 文本（SoulEngine 持久化层主存储字段）
    profile_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}", server_default="{}")
    # 画像版本号，每次更新递增（乐观锁/缓存失效依据）
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
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


class ProfileExtractionState(Base):
    """
    用户画像提取状态模型，存储每用户的提取计数器、触发阈值与探针标志。

    与 ProfileExtractionLog（每次提取的日志记录）不同，本表为每用户单行状态记录，
    用于支撑 PRD 中"低置信度/新兴趣/周期性复审"三类探针触发逻辑的状态机。
    """
    __tablename__ = "profile_extraction_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"),
        unique=True, index=True, nullable=False,
    )
    # 自上次提取以来的对话轮数计数器
    turns_since_last_extract: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # 触发提取的轮数阈值（达到后自动触发提取）
    n_threshold: Mapped[int] = mapped_column(Integer, nullable=False, default=5, server_default="5")
    # 上次提取时间（用于周期性复审判断）
    last_extracted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # 探针触发标志位 JSON：
    # {"low_confidence": True, "new_interest": True, "periodic_review": False}
    probe_flags: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")
