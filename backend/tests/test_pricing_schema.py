"""
ModelPricing schema 扩展字段测试：验证 cherry-studio 兼容字段（缓存定价、模态、能力等）
在 CRUD 全链路中正确读写，且旧记录的新字段为 NULL。
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.models import Base
from billing.models import ModelPricing
from billing.pricing_manager import PricingManager


@pytest.fixture
def db_session():
    """创建内存 SQLite 数据库并通过 Base.metadata.create_all 建表（包含新字段）。"""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def pricing_manager(db_session):
    """构造 PricingManager 实例，复用 db_session fixture。"""
    return PricingManager(db_session)


# 新字段清单，与 ORM 模型 / Alembic 迁移保持一致
NEW_FIELDS = [
    "cache_read_price",
    "cache_write_price",
    "per_image_price",
    "per_minute_price",
    "owned_by",
    "family",
    "capabilities",
    "input_modalities",
    "output_modalities",
    "max_output_tokens",
]


def test_create_pricing_with_new_fields(pricing_manager, db_session):
    """创建含全部新字段的定价记录，读回后验证字段值一致。"""
    pricing_data = {
        "provider": "anthropic",
        "model": "claude-3-5-sonnet",
        "input_price": 3.0,
        "output_price": 15.0,
        # cherry-studio 兼容字段
        "cache_read_price": 0.3,
        "cache_write_price": 3.75,
        "per_image_price": 0.004,
        "per_minute_price": 0.06,
        "owned_by": "anthropic",
        "family": "claude-3",
        "capabilities": ["tools", "vision", "code"],
        "input_modalities": ["text", "image"],
        "output_modalities": ["text"],
        "max_output_tokens": 8192,
    }

    created = pricing_manager.create_pricing(pricing_data)

    # 验证返回的 ORM 实例包含新字段且值一致
    assert created.cache_read_price == 0.3
    assert created.cache_write_price == 3.75
    assert created.per_image_price == 0.004
    assert created.per_minute_price == 0.06
    assert created.owned_by == "anthropic"
    assert created.family == "claude-3"
    assert created.capabilities == ["tools", "vision", "code"]
    assert created.input_modalities == ["text", "image"]
    assert created.output_modalities == ["text"]
    assert created.max_output_tokens == 8192

    # 从数据库重新查询，验证持久化正确
    db_record = db_session.query(ModelPricing).filter(ModelPricing.id == created.id).first()
    assert db_record is not None
    assert db_record.cache_read_price == 0.3
    assert db_record.cache_write_price == 3.75
    assert db_record.per_image_price == 0.004
    assert db_record.per_minute_price == 0.06
    assert db_record.owned_by == "anthropic"
    assert db_record.family == "claude-3"
    assert db_record.capabilities == ["tools", "vision", "code"]
    assert db_record.input_modalities == ["text", "image"]
    assert db_record.output_modalities == ["text"]
    assert db_record.max_output_tokens == 8192


def test_update_pricing_cache_read_price(pricing_manager, db_session):
    """创建记录后更新 cache_read_price 字段，验证更新生效。"""
    # 先创建一条不含新字段的记录
    created = pricing_manager.create_pricing({
        "provider": "openai",
        "model": "gpt-4o",
        "input_price": 2.5,
        "output_price": 10.0,
    })
    assert created.cache_read_price is None

    # 更新 cache_read_price 与 max_output_tokens
    updated = pricing_manager.update_pricing(created.id, {
        "cache_read_price": 1.25,
        "max_output_tokens": 16384,
    })

    assert updated is not None
    assert updated.cache_read_price == 1.25
    assert updated.max_output_tokens == 16384
    # 未更新的字段保持原值
    assert updated.input_price == 2.5
    assert updated.output_price == 10.0

    # 从数据库重新查询验证持久化
    db_record = db_session.query(ModelPricing).filter(ModelPricing.id == created.id).first()
    assert db_record.cache_read_price == 1.25
    assert db_record.max_output_tokens == 16384


def test_query_pricing_returns_new_fields(pricing_manager, db_session):
    """通过 get_pricing 查询返回的 ORM 实例自动包含新字段。"""
    pricing_manager.create_pricing({
        "provider": "google",
        "model": "gemini-1.5-pro",
        "input_price": 1.25,
        "output_price": 5.0,
        "cache_read_price": 0.3125,
        "cache_write_price": 1.25,
        "owned_by": "google",
        "family": "gemini",
        "capabilities": ["vision", "code", "long_context"],
        "input_modalities": ["text", "image", "audio"],
        "output_modalities": ["text"],
        "max_output_tokens": 8192,
    })

    result = pricing_manager.get_pricing("google", "gemini-1.5-pro")

    assert result is not None
    # 验证新字段在查询结果中可访问
    assert result.cache_read_price == 0.3125
    assert result.cache_write_price == 1.25
    assert result.owned_by == "google"
    assert result.family == "gemini"
    assert result.capabilities == ["vision", "code", "long_context"]
    assert result.input_modalities == ["text", "image", "audio"]
    assert result.output_modalities == ["text"]
    assert result.max_output_tokens == 8192


def test_old_records_have_null_new_fields(pricing_manager, db_session):
    """仅写入旧字段的记录，新字段在数据库中为 NULL。"""
    created = pricing_manager.create_pricing({
        "provider": "deepseek",
        "model": "deepseek-chat",
        "input_price": 0.14,
        "output_price": 0.28,
    })

    # 直接查 ORM 实例验证新字段为 None
    db_record = db_session.query(ModelPricing).filter(ModelPricing.id == created.id).first()
    assert db_record is not None
    for field in NEW_FIELDS:
        assert getattr(db_record, field) is None, f"字段 {field} 应为 NULL"

    # 通过 get_pricing 查询也应返回 None
    result = pricing_manager.get_pricing("deepseek", "deepseek-chat")
    assert result is not None
    for field in NEW_FIELDS:
        assert getattr(result, field) is None, f"字段 {field} 应为 NULL"
