"""
计费模型唯一性约束测试（从 test_final_validation.py 重构为 pytest）。
覆盖数据库约束、代码层面重复检测和正常初始化流程。
"""

from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from billing.models import Base, ModelConfiguration
from billing.pricing_manager import PricingManager


@pytest.fixture
def memory_db():
    """创建独立内存数据库"""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    engine.dispose()


class TestDatabaseUniqueness:
    """数据库唯一约束测试"""

    def test_duplicate_insert_rejected(self, memory_db):
        """模型配置的重复插入应被数据库拒绝"""
        config1 = ModelConfiguration(
            provider="test",
            model="unique_test",
            is_active=True,
            is_default=True,
        )
        memory_db.add(config1)
        memory_db.commit()

        # 尝试插入重复项
        config2 = ModelConfiguration(
            provider="test",
            model="unique_test",
            is_active=True,
            is_default=False,
        )
        memory_db.add(config2)

        with pytest.raises(Exception):
            memory_db.commit()
        memory_db.rollback()

    def test_first_insert_succeeds(self, memory_db):
        """首次插入应成功"""
        config = ModelConfiguration(
            provider="openai",
            model="gpt-4-test",
            is_active=True,
            is_default=True,
        )
        memory_db.add(config)
        memory_db.commit()

        saved = (
            memory_db.query(ModelConfiguration)
            .filter(ModelConfiguration.provider == "openai")
            .first()
        )
        assert saved is not None
        assert saved.model == "gpt-4-test"


class TestCodeLevelValidation:
    """代码层面重复检测测试"""

    def test_duplicate_configs_raise_value_error(self, memory_db):
        """重复的默认配置应抛出 ValueError"""
        duplicate_configs = [
            {
                "provider": "openai",
                "model": "dup-model",
                "display_name": "Dup GPT",
                "description": "Original",
                "is_active": True,
                "is_default": True,
                "sort_order": 0,
            },
            {
                "provider": "openai",
                "model": "dup-model",
                "display_name": "Dup GPT 2",
                "description": "Duplicate",
                "is_active": True,
                "is_default": False,
                "sort_order": 99,
            },
        ]

        with patch(
            "config.config_loader.config_loader.load_default_configurations",
            return_value=duplicate_configs,
        ):
            manager = PricingManager(memory_db)
            with pytest.raises(ValueError):
                manager.initialize_default_configurations()

    def test_unique_configs_initialize_successfully(self, memory_db):
        """无重复配置时初始化成功"""
        unique_configs = [
            {
                "provider": "openai",
                "model": "gpt-4",
                "display_name": "GPT-4",
                "description": "OpenAI GPT-4",
                "is_active": True,
                "is_default": True,
                "sort_order": 0,
            },
            {
                "provider": "openai",
                "model": "gpt-3.5-turbo",
                "display_name": "GPT-3.5",
                "description": "OpenAI GPT-3.5",
                "is_active": True,
                "is_default": False,
                "sort_order": 1,
            },
        ]

        with patch(
            "config.config_loader.config_loader.load_default_configurations",
            return_value=unique_configs,
        ):
            manager = PricingManager(memory_db)
            count = manager.initialize_default_configurations()
            assert count == 2

            configs = memory_db.query(ModelConfiguration).all()
            assert len(configs) == 2


class TestNormalInitialization:
    """正常初始化流程测试"""

    def test_default_configurations_are_unique(self):
        """DEFAULT_CONFIGURATIONS 中没有重复项"""
        is_unique, duplicates = PricingManager.validate_default_configurations()
        assert is_unique, f"发现重复配置: {duplicates}"

    def test_initialize_creates_no_duplicates(self, memory_db):
        """初始化后数据库中无重复记录"""
        manager = PricingManager(memory_db)
        try:
            count = manager.initialize_default_configurations()
        except ValueError:
            pytest.skip("DEFAULT_CONFIGURATIONS 中存在重复")

        assert count > 0
        configs = memory_db.query(ModelConfiguration).all()
        seen = set()
        for cfg in configs:
            key = (cfg.provider, cfg.model)
            assert key not in seen, f"数据库中发现重复: {key}"
            seen.add(key)
