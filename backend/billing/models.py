from sqlalchemy import Column, String, Integer, Float, Boolean, DateTime, Text, Date
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime

Base = declarative_base()


class UsageRecord(Base):
    __tablename__ = "usage_records"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    call_id = Column(String, unique=True, nullable=False, index=True)
    user_id = Column(String, index=True)
    session_id = Column(String, index=True)
    provider = Column(String, nullable=False)
    model = Column(String, nullable=False)
    content_type = Column(String, nullable=False)
    input_tokens = Column(Integer, default=0)
    output_tokens = Column(Integer, default=0)
    input_cost = Column(Float, default=0.0)
    output_cost = Column(Float, default=0.0)
    total_cost = Column(Float, default=0.0)
    currency = Column(String, default="USD")
    cache_hit = Column(Boolean, default=False)
    duration_ms = Column(Integer, default=0)
    extra_data = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


class ModelPricing(Base):
    __tablename__ = "model_pricing"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    provider = Column(String, nullable=False, index=True)
    model = Column(String, nullable=False, index=True)
    input_price = Column(Float, nullable=False)
    output_price = Column(Float, nullable=False)
    currency = Column(String, default="USD")
    cache_hit_price = Column(Float)
    token_per_image = Column(Integer, default=1024)
    token_per_second_audio = Column(Integer, default=150)
    token_per_second_video = Column(Integer, default=2880)
    context_window = Column(Integer)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    __table_args__ = (
        {"sqlite_autoincrement": True},
    )


class BudgetConfig(Base):
    __tablename__ = "budget_configs"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    budget_type = Column(String, nullable=False)
    scope_id = Column(String)
    max_amount = Column(Float, nullable=False)
    period_type = Column(String, default="monthly")
    currency = Column(String, default="USD")
    warning_threshold = Column(Float, default=0.8)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class UserUsageSummary(Base):
    __tablename__ = "user_usage_summary"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, nullable=False, index=True)
    period_start = Column(Date, nullable=False)
    period_end = Column(Date, nullable=False)
    total_input_tokens = Column(Integer, default=0)
    total_output_tokens = Column(Integer, default=0)
    total_cost = Column(Float, default=0.0)
    currency = Column(String, default="USD")
    
    __table_args__ = (
        {"sqlite_autoincrement": True},
    )


class ModelConfiguration(Base):
    __tablename__ = "model_configurations"
    from sqlalchemy import UniqueConstraint
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    provider = Column(String, nullable=False, index=True)
    model = Column(String, nullable=False, index=True)
    display_name = Column(String)
    description = Column(Text)
    api_key = Column(Text)
    api_endpoint = Column(String)
    is_active = Column(Boolean, default=True)
    is_default = Column(Boolean, default=False)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    __table_args__ = (
        UniqueConstraint('provider', 'model', name='uq_model_configurations_provider_model'),
        {"sqlite_autoincrement": True},
    )
