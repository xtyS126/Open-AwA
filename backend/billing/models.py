"""
计费与用量管理模块，负责价格配置、预算控制、用量追踪与报表能力。
计费模型统一使用 db.models.Base 作为声明式基类，与主业务模型共享同一套 Metadata，
确保迁移治理在单条链路上执行，避免表结构漂移。
"""

from sqlalchemy import Column, String, Integer, Float, Boolean, DateTime, Text, Date, UniqueConstraint, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column
from datetime import datetime, timezone

from db.models import Base


class UsageRecord(Base):
    """LLM 调用用量明细记录：单次 API 调用的 token 量、费用、耗时等信息。"""
    __tablename__ = "usage_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    call_id: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String, index=True)
    session_id: Mapped[str] = mapped_column(String, index=True)
    provider: Mapped[str] = mapped_column(String, nullable=False)
    model: Mapped[str] = mapped_column(String, nullable=False)
    content_type: Mapped[str] = mapped_column(String, nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    input_cost: Mapped[float] = mapped_column(Float, default=0.0)
    output_cost: Mapped[float] = mapped_column(Float, default=0.0)
    total_cost: Mapped[float] = mapped_column(Float, default=0.0)
    currency: Mapped[str] = mapped_column(String, default="USD")
    cache_hit: Mapped[bool] = mapped_column(Boolean, default=False)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    extra_data: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index("ix_usage_records_user_created", "user_id", "created_at"),
    )


class ModelPricing(Base):
    """模型定价配置：按 provider/model 维护的输入/输出/缓存价格及多模态 token 折算规则。"""
    __tablename__ = "model_pricing"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String, nullable=False, index=True)
    model: Mapped[str] = mapped_column(String, nullable=False, index=True)
    input_price: Mapped[float] = mapped_column(Float, nullable=False)
    output_price: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String, default="USD")
    cache_hit_price: Mapped[float] = mapped_column(Float, nullable=True)
    token_per_image: Mapped[int] = mapped_column(Integer, default=1024)
    token_per_second_audio: Mapped[int] = mapped_column(Integer, default=150)
    token_per_second_video: Mapped[int] = mapped_column(Integer, default=2880)
    context_window: Mapped[int] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    supports_vision: Mapped[bool] = mapped_column(Boolean, default=False)
    is_multimodal: Mapped[bool] = mapped_column(Boolean, default=False)
    # 模态标签：输入/输出方向各自支持的模态列表（JSON 数组，如 ["text","image"]）
    input_modality: Mapped[str] = mapped_column(Text, nullable=True)
    output_modality: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (
        {"sqlite_autoincrement": True},
    )


class BudgetConfig(Base):
    """预算配置：按用户/工作区维度设置的用量预算上限、周期和告警阈值。"""
    __tablename__ = "budget_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    budget_type: Mapped[str] = mapped_column(String, nullable=False)
    scope_id: Mapped[str] = mapped_column(String, nullable=True)
    max_amount: Mapped[float] = mapped_column(Float, nullable=False)
    period_type: Mapped[str] = mapped_column(String, default="monthly")
    currency: Mapped[str] = mapped_column(String, default="USD")
    warning_threshold: Mapped[float] = mapped_column(Float, default=0.8)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc)
    )


class UserUsageSummary(Base):
    """用户用量月度汇总：按月聚合的 token 量和费用统计，通过原子 UPDATE 避免并发写冲突。"""
    __tablename__ = "user_usage_summary"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    period_start: Mapped[Date] = mapped_column(Date, nullable=False)
    period_end: Mapped[Date] = mapped_column(Date, nullable=False)
    total_input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_cost: Mapped[float] = mapped_column(Float, default=0.0)
    currency: Mapped[str] = mapped_column(String, default="USD")

    __table_args__ = (
        {"sqlite_autoincrement": True},
    )


class ProviderCredential(Base):
    """Provider 凭据表：独立存储各 AI 供应商的 API Key、Endpoint 等认证信息。
    与 ModelConfiguration 分离，消除 custom-model 占位 hack。
    """
    __tablename__ = "provider_credentials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=True)
    api_key: Mapped[str] = mapped_column(Text, nullable=True)     # Fernet 加密存储
    api_endpoint: Mapped[str] = mapped_column(String(500), nullable=True)
    icon: Mapped[str] = mapped_column(String(500), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (
        {"sqlite_autoincrement": True},
    )


class ModelConfiguration(Base):
    """模型端点配置：各 provider/model 的运行参数（温度、top_k 等）。
    API 凭据通过 credential_id 外键关联到 ProviderCredential 表。
    """
    __tablename__ = "model_configurations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String, nullable=False, index=True)
    model: Mapped[str] = mapped_column(String, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String, nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    icon: Mapped[str] = mapped_column(String, nullable=True)
    # [Legacy] 以下两个字段保留用于向后兼容，新代码应通过 credential_id → ProviderCredential 获取
    api_key: Mapped[str] = mapped_column(Text, nullable=True)
    api_endpoint: Mapped[str] = mapped_column(String, nullable=True)
    # Provider 凭据外键
    credential_id: Mapped[int] = mapped_column(Integer, ForeignKey("provider_credentials.id"), nullable=True)
    selected_models: Mapped[str] = mapped_column(Text, nullable=True)
    max_tokens: Mapped[int] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, index=True)

    # Model parameter fields
    temperature: Mapped[float] = mapped_column(Float, nullable=True, default=0.7)
    top_k: Mapped[float] = mapped_column(Float, nullable=True, default=0.9)
    top_p: Mapped[float] = mapped_column(Float, nullable=True)
    max_tokens_limit: Mapped[int] = mapped_column(Integer, nullable=True)
    frequency_penalty: Mapped[float] = mapped_column(Float, nullable=True, default=None)
    presence_penalty: Mapped[float] = mapped_column(Float, nullable=True, default=None)
    timeout: Mapped[int] = mapped_column(Integer, nullable=True, default=None)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=True, default=None)

    # Model capability flags
    supports_temperature: Mapped[bool] = mapped_column(Boolean, default=True)
    supports_top_k: Mapped[bool] = mapped_column(Boolean, default=True)
    supports_vision: Mapped[bool] = mapped_column(Boolean, default=False)
    is_multimodal: Mapped[bool] = mapped_column(Boolean, default=False)

    # 模态标签：输入/输出方向各自支持的模态列表（JSON 数组，如 ["text","image"]）
    input_modality: Mapped[str] = mapped_column(Text, nullable=True)
    output_modality: Mapped[str] = mapped_column(Text, nullable=True)

    # Model metadata
    model_spec: Mapped[str] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (
        UniqueConstraint("provider", "model", name="uq_model_configurations_provider_model"),
        {"sqlite_autoincrement": True},
    )
