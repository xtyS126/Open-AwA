"""
计费与用量管理模块，负责价格配置、预算控制、用量追踪与报表能力。
这一部分直接关联成本核算、调用统计以及运维观测。
"""

from sqlalchemy import Column, String, Integer, Float, Boolean, DateTime, Text, Date, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from datetime import datetime, timezone


class Base(DeclarativeBase):
    """
    封装与Base相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    pass


class UsageRecord(Base):
    """
    封装与UsageRecord相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
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


class ModelPricing(Base):
    """
    封装与ModelPricing相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
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
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (
        {"sqlite_autoincrement": True},
    )


class BudgetConfig(Base):
    """
    封装与BudgetConfig相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
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
    """
    封装与UserUsageSummary相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
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


class ModelConfiguration(Base):
    """
    封装与ModelConfiguration相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    __tablename__ = "model_configurations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String, nullable=False, index=True)
    model: Mapped[str] = mapped_column(String, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String, nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    icon: Mapped[str] = mapped_column(String, nullable=True)
    api_key: Mapped[str] = mapped_column(Text, nullable=True)
    api_endpoint: Mapped[str] = mapped_column(String, nullable=True)
    selected_models: Mapped[str] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (
        UniqueConstraint("provider", "model", name="uq_model_configurations_provider_model"),
        {"sqlite_autoincrement": True},
    )
