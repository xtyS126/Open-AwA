"""
后端测试模块，负责验证对应功能在正常、边界或异常场景下的行为是否符合预期。
保持测试注释清晰，有助于快速分辨各个用例所覆盖的场景。
"""

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker
from db.models import Base
from billing.models import ModelConfiguration, ModelPricing, ProviderCredential
from billing.pricing_manager import PricingManager
from billing.routers.billing import serialize_configuration


def _create_pricing_session_with_schema(include_capability_columns: bool):
    """
    创建指定 model_pricing 结构的数据库会话，用于兼容性回归测试。
    """
    engine = create_engine('sqlite:///:memory:', echo=False)
    if include_capability_columns:
        Base.metadata.create_all(engine)
        return sessionmaker(bind=engine)()

    capability_columns = """
    """

    with engine.begin() as conn:
        conn.execute(text(f"""
            CREATE TABLE model_pricing (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                provider VARCHAR NOT NULL,
                model VARCHAR NOT NULL,
                input_price FLOAT NOT NULL,
                output_price FLOAT NOT NULL,
                currency VARCHAR NOT NULL,
                cache_hit_price FLOAT,
                token_per_image INTEGER NOT NULL,
                token_per_second_audio INTEGER NOT NULL,
                token_per_second_video INTEGER NOT NULL,
                context_window INTEGER,
                is_active BOOLEAN NOT NULL,
                {capability_columns}
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL
            )
        """))

    SessionLocal = sessionmaker(bind=engine)
    return SessionLocal()


@pytest.fixture
def db_session():
    engine = create_engine('sqlite:///:memory:', echo=False)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def pricing_manager(db_session):
    return PricingManager(db_session)


class TestInitializeDefaultConfigurations:

    def test_initialize_creates_configurations_when_empty(self, pricing_manager, db_session):
        """
        验证initialize、creates、configurations、when、empty相关场景的行为是否符合预期。
        通过断言结果可以帮助定位实现与预期行为之间的偏差。
        """
        count = pricing_manager.initialize_default_configurations()

        assert count == 7, "Should create seven current provider defaults"

        configs = db_session.query(ModelConfiguration).all()
        assert len(configs) == 7, "Should have seven configurations in database"

        providers = [c.provider for c in configs]
        assert "openai" in providers
        assert "anthropic" in providers
        assert "google" in providers
        assert "deepseek" in providers
        assert "alibaba" in providers
        assert "moonshot" in providers
        assert "zhipu" in providers

    def test_default_catalog_models_exist_in_pricing_and_capabilities(self):
        """默认模型必须同时存在于定价和能力目录，确保聊天调用可解析。"""
        from config.config_loader import config_loader

        config_loader.invalidate_cache()
        default_configs = config_loader.load_default_configurations()
        pricing_keys = {
            (item["provider"], item["model"])
            for item in config_loader.load_pricing_data()
        }
        capability_keys = set(config_loader.load_model_capabilities())

        assert {(item["provider"], item["model"]) for item in default_configs} == {
            ("openai", "gpt-5.5"),
            ("anthropic", "claude-sonnet-4-6"),
            ("google", "gemini-3.1-pro"),
            ("deepseek", "deepseek-v4-pro"),
            ("alibaba", "qwen3.5-plus"),
            ("moonshot", "kimi-k2.6"),
            ("zhipu", "glm-5"),
        }
        for item in default_configs:
            key = (item["provider"], item["model"])
            assert key in pricing_keys
            assert key in capability_keys

    def test_provider_recovery_uses_default_catalog(self):
        """厂商凭据恢复时必须从同一默认目录取得模型。"""
        expected_models = {
            "openai": "gpt-5.5",
            "anthropic": "claude-sonnet-4-6",
            "google": "gemini-3.1-pro",
            "deepseek": "deepseek-v4-pro",
            "alibaba": "qwen3.5-plus",
            "moonshot": "kimi-k2.6",
            "zhipu": "glm-5",
        }

        for provider, expected_model in expected_models.items():
            recovered = PricingManager._get_default_models_for_provider(provider)
            assert len(recovered) == 1
            assert recovered[0]["model"] == expected_model
            assert recovered[0]["is_default"] is (provider == "openai")

    def test_initialize_skips_when_configurations_exist(self, pricing_manager, db_session):
        """
        验证initialize、skips、when、configurations、exist相关场景的行为是否符合预期。
        通过断言结果可以帮助定位实现与预期行为之间的偏差。
        """
        existing_config = ModelConfiguration(
            provider="openai",
            model="gpt-4",
            display_name="Existing GPT-4",
            is_active=True,
            is_default=True
        )
        db_session.add(existing_config)
        db_session.commit()

        count = pricing_manager.initialize_default_configurations()

        assert count == 0, "Should preserve existing user configurations"
        configs = db_session.query(ModelConfiguration).all()
        assert len(configs) == 1, "Should only have the existing configuration"

    def test_legacy_cleanup_preserves_selected_models_then_adds_current_defaults(
        self, pricing_manager, db_session
    ):
        """旧种子仅在未配置凭据、端点和已选模型时清理。"""
        stale_config = ModelConfiguration(
            provider="openai",
            model="gpt-4.1",
            display_name="GPT-4.1",
            is_active=True,
            is_default=True,
        )
        selected_config = ModelConfiguration(
            provider="deepseek",
            model="deepseek-chat",
            display_name="DeepSeek Chat",
            selected_models='["deepseek-v4-pro"]',
            is_active=True,
            is_default=False,
        )
        db_session.add_all([stale_config, selected_config])
        db_session.commit()

        assert pricing_manager.remove_legacy_default_configurations() == 1
        assert db_session.query(ModelConfiguration).filter(
            ModelConfiguration.provider == "openai",
            ModelConfiguration.model == "gpt-4.1",
        ).first() is None
        assert db_session.query(ModelConfiguration).filter(
            ModelConfiguration.provider == "deepseek",
            ModelConfiguration.model == "deepseek-chat",
        ).first() is not None

        assert pricing_manager.initialize_default_configurations(add_missing=True) == 7
        current_default = pricing_manager.get_default_configuration()
        assert current_default is not None
        assert (current_default.provider, current_default.model) == ("openai", "gpt-5.5")

    def test_legacy_selection_refreshes_first_model_and_preserves_choices(
        self, pricing_manager, db_session
    ):
        """旧首选模型应替换为当前模板，后续模型顺序保持可追溯。"""
        config = ModelConfiguration(
            provider="deepseek",
            model="deepseek-chat",
            display_name="DeepSeek Chat",
            selected_models='["deepseek-v3", "deepseek-r1", "deepseek-v4-pro"]',
            is_active=True,
            is_default=True,
        )
        db_session.add(config)
        db_session.commit()

        assert pricing_manager.refresh_legacy_default_model_selections() == 1
        db_session.refresh(config)
        assert pricing_manager.parse_selected_models(config.selected_models) == [
            "deepseek-v4-pro",
            "deepseek-v3",
            "deepseek-r1",
        ]

    def test_initialize_sets_first_as_default(self, pricing_manager, db_session):
        """
        验证initialize、sets、first、as、default相关场景的行为是否符合预期。
        通过断言结果可以帮助定位实现与预期行为之间的偏差。
        """
        pricing_manager.initialize_default_configurations()

        configs = db_session.query(ModelConfiguration).order_by(ModelConfiguration.sort_order).all()
        default_configs = [c for c in configs if c.is_default]

        assert len(default_configs) == 1, "Should have exactly one default configuration"
        assert default_configs[0].model == "gpt-5.5", "GPT-5.5 should be the default"
        assert default_configs[0].provider == "openai"

    def test_initialize_respects_sort_order(self, pricing_manager, db_session):
        """
        验证initialize、respects、sort、order相关场景的行为是否符合预期。
        通过断言结果可以帮助定位实现与预期行为之间的偏差。
        """
        pricing_manager.initialize_default_configurations()

        configs = db_session.query(ModelConfiguration).order_by(ModelConfiguration.sort_order).all()

        assert configs[0].sort_order == 0
        assert configs[1].sort_order == 1
        assert configs[2].sort_order == 2
        assert configs[3].sort_order == 3
        assert configs[4].sort_order == 4

    def test_initialize_creates_correct_display_names(self, pricing_manager, db_session):
        """
        验证initialize、creates、correct、display、names相关场景的行为是否符合预期。
        通过断言结果可以帮助定位实现与预期行为之间的偏差。
        """
        pricing_manager.initialize_default_configurations()

        gpt55 = db_session.query(ModelConfiguration).filter(
            ModelConfiguration.provider == "openai",
            ModelConfiguration.model == "gpt-5.5"
        ).first()

        assert gpt55 is not None
        assert gpt55.display_name == "GPT-5.5"
        assert "多模态输入与工具调用" in gpt55.description

    def test_initialize_all_active(self, pricing_manager, db_session):
        """
        验证initialize、all、active相关场景的行为是否符合预期。
        通过断言结果可以帮助定位实现与预期行为之间的偏差。
        """
        pricing_manager.initialize_default_configurations()

        configs = db_session.query(ModelConfiguration).all()
        inactive = [c for c in configs if not c.is_active]

        assert len(inactive) == 0, "All configurations should be active"

    def test_initialize_idempotent(self, pricing_manager, db_session):
        """
        验证initialize、idempotent相关场景的行为是否符合预期。
        通过断言结果可以帮助定位实现与预期行为之间的偏差。
        """
        pricing_manager.initialize_default_configurations()
        pricing_manager.initialize_default_configurations()
        count2 = pricing_manager.initialize_default_configurations()

        assert count2 == 0, "Second initialization should return 0"
        configs = db_session.query(ModelConfiguration).all()
        assert len(configs) == 7, "Should still have seven configurations"

    def test_initialize_no_duplicate_provider_model_combinations(self, pricing_manager, db_session):
        """
        验证initialize、no、duplicate、provider、model、combinations相关场景的行为是否符合预期。
        通过断言结果可以帮助定位实现与预期行为之间的偏差。
        """
        pricing_manager.initialize_default_configurations()
        pricing_manager.initialize_default_configurations()

        configs = db_session.query(ModelConfiguration).all()
        seen = set()
        for config in configs:
            key = (config.provider, config.model)
            assert key not in seen, f"Duplicate configuration: {key}"
            seen.add(key)

        assert len(seen) == 7, "Should have seven unique provider:model combinations"


class TestInitializeDefaultPricing:

    def test_initialize_handles_non_nullable_capability_columns(self):
        """
        验证旧库已包含非空能力列时，默认定价初始化仍可成功写入。
        """
        from config.config_loader import config_loader
        session = _create_pricing_session_with_schema(include_capability_columns=True)
        try:
            pricing_manager = PricingManager(session)

            count = pricing_manager.initialize_default_pricing()

            # 初始化条目数应与 pricing_data.json 一致
            assert count == len(config_loader.load_pricing_data())
            gemini = session.query(ModelPricing).filter(
                ModelPricing.provider == "google",
                ModelPricing.model == "gemini-2.5-flash"
            ).first()
            assert gemini is not None
            assert gemini.supports_vision is True
            assert gemini.is_multimodal is True
        finally:
            session.close()

    def test_initialize_requires_migrated_capability_columns(self):
        """
        验证旧库缺少能力列时，运行时不会执行 DDL，必须先执行 Alembic 迁移。
        """
        session = _create_pricing_session_with_schema(include_capability_columns=False)
        try:
            pricing_manager = PricingManager(session)

            with pytest.raises(OperationalError):
                pricing_manager.initialize_default_pricing()

            session.rollback()
            columns = {row[1] for row in session.execute(text("PRAGMA table_info(model_pricing)"))}
            assert "supports_vision" not in columns
        finally:
            session.close()


class TestGetActiveConfigurations:

    def test_get_active_only_returns_active(self, pricing_manager, db_session):
        """
        验证get、active、only、returns、active相关场景的行为是否符合预期。
        通过断言结果可以帮助定位实现与预期行为之间的偏差。
        """
        pricing_manager.initialize_default_configurations()

        active = pricing_manager.get_active_configurations()

        assert len(active) == 7
        for config in active:
            assert config.is_active is True

    def test_get_active_excludes_inactive(self, pricing_manager, db_session):
        """
        验证get、active、excludes、inactive相关场景的行为是否符合预期。
        通过断言结果可以帮助定位实现与预期行为之间的偏差。
        """
        pricing_manager.initialize_default_configurations()

        config = db_session.query(ModelConfiguration).first()
        config.is_active = False
        db_session.commit()

        active = pricing_manager.get_active_configurations()

        assert len(active) == 6
        inactive_ids = [c.id for c in db_session.query(ModelConfiguration).filter(
            ModelConfiguration.is_active == False
        ).all()]
        for a in active:
            assert a.id not in inactive_ids

    def test_get_active_ordered_by_sort_order(self, pricing_manager, db_session):
        """
        验证get、active、ordered、by、sort、order相关场景的行为是否符合预期。
        通过断言结果可以帮助定位实现与预期行为之间的偏差。
        """
        pricing_manager.initialize_default_configurations()

        active = pricing_manager.get_active_configurations()

        for i in range(len(active) - 1):
            assert active[i].sort_order <= active[i + 1].sort_order


class TestDefaultConfiguration:

    def test_get_default_returns_default_config(self, pricing_manager, db_session):
        """
        验证get、default、returns、default、config相关场景的行为是否符合预期。
        通过断言结果可以帮助定位实现与预期行为之间的偏差。
        """
        pricing_manager.initialize_default_configurations()

        default = pricing_manager.get_default_configuration()

        assert default is not None
        assert default.is_default is True
        assert default.model == "gpt-5.5"

    def test_get_default_returns_none_when_no_default(self, pricing_manager, db_session):
        """
        验证get、default、returns、none、when、no、default相关场景的行为是否符合预期。
        通过断言结果可以帮助定位实现与预期行为之间的偏差。
        """
        config = ModelConfiguration(
            provider="openai",
            model="test",
            is_active=True,
            is_default=False
        )
        db_session.add(config)
        db_session.commit()
        
        default = pricing_manager.get_default_configuration()
        
        assert default is None


class TestConfigurationUniquenessValidation:

    def test_validate_configurations_uniqueness_with_unique_data(self):
        """
        验证validate、configurations、uniqueness、with、unique、data相关场景的行为是否符合预期。
        通过断言结果可以帮助定位实现与预期行为之间的偏差。
        """
        configs = [
            {"provider": "openai", "model": "gpt-4"},
            {"provider": "anthropic", "model": "claude-3.5-sonnet"},
        ]
        
        is_unique, duplicates = PricingManager._validate_configurations_uniqueness(configs)
        
        assert is_unique is True
        assert len(duplicates) == 0

    def test_validate_configurations_uniqueness_with_duplicates(self):
        """
        验证validate、configurations、uniqueness、with、duplicates相关场景的行为是否符合预期。
        通过断言结果可以帮助定位实现与预期行为之间的偏差。
        """
        configs = [
            {"provider": "openai", "model": "gpt-4"},
            {"provider": "openai", "model": "gpt-4"},
            {"provider": "anthropic", "model": "claude-3.5-sonnet"},
        ]
        
        is_unique, duplicates = PricingManager._validate_configurations_uniqueness(configs)
        
        assert is_unique is False
        assert len(duplicates) == 1
        assert ("openai", "gpt-4") in duplicates

    def test_validate_configurations_uniqueness_with_multiple_duplicates(self):
        """
        验证validate、configurations、uniqueness、with、multiple、duplicates相关场景的行为是否符合预期。
        通过断言结果可以帮助定位实现与预期行为之间的偏差。
        """
        configs = [
            {"provider": "openai", "model": "gpt-4"},
            {"provider": "anthropic", "model": "claude-3.5-sonnet"},
            {"provider": "openai", "model": "gpt-4"},
            {"provider": "anthropic", "model": "claude-3.5-sonnet"},
            {"provider": "google", "model": "gemini-2.0-flash"},
        ]
        
        is_unique, duplicates = PricingManager._validate_configurations_uniqueness(configs)
        
        assert is_unique is False
        assert len(duplicates) == 2
        assert ("openai", "gpt-4") in duplicates
        assert ("anthropic", "claude-3.5-sonnet") in duplicates

    def test_validate_default_configurations_with_valid_data(self):
        """
        验证validate、default、configurations、with、valid、data相关场景的行为是否符合预期。
        通过断言结果可以帮助定位实现与预期行为之间的偏差。
        """
        is_unique, duplicates = PricingManager.validate_default_configurations()
        
        assert is_unique is True, f"DEFAULT_CONFIGURATIONS should be unique, but found duplicates: {duplicates}"
        assert len(duplicates) == 0

    def test_initialize_raises_error_on_duplicate_configurations(self, pricing_manager, db_session):
        """
        验证initialize、raises、error、on、duplicate、configurations相关场景的行为是否符合预期。
        通过断言结果可以帮助定位实现与预期行为之间的偏差。
        """
        from unittest.mock import patch

        duplicate_configs = [
            {"provider": "openai", "model": "gpt-4", "display_name": "GPT-4", "description": "Original", "is_active": True, "is_default": True, "sort_order": 0},
            {"provider": "openai", "model": "gpt-4", "display_name": "GPT-4 Duplicate", "description": "Duplicate", "is_active": True, "is_default": False, "sort_order": 99},
        ]

        with patch("config.config_loader.config_loader.load_default_configurations", return_value=duplicate_configs):
            with pytest.raises(ValueError) as excinfo:
                pricing_manager.initialize_default_configurations()

            assert "duplicate" in str(excinfo.value).lower()
            assert "openai/gpt-4" in str(excinfo.value)

    def test_initialize_creates_unique_constraint_index(self, db_session):
        """
        验证initialize、creates、unique、constraint、index相关场景的行为是否符合预期。
        通过断言结果可以帮助定位实现与预期行为之间的偏差。
        """
        from sqlalchemy import inspect

        inspector = inspect(db_session.bind)
        constraints = inspector.get_unique_constraints('model_configurations')

        has_unique_constraint = any(
            constraint.get('name') == 'uq_model_configurations_provider_model'
            and set(constraint.get('column_names', [])) == {'provider', 'model'}
            for constraint in constraints
        )

        assert has_unique_constraint, "Should have unique constraint on provider+model"

    def test_cannot_insert_duplicate_provider_model_via_database(self, db_session):
        """
        验证cannot、insert、duplicate、provider、model、via、database相关场景的行为是否符合预期。
        通过断言结果可以帮助定位实现与预期行为之间的偏差。
        """
        config1 = ModelConfiguration(
            provider="test",
            model="duplicate",
            is_active=True,
            is_default=True
        )
        db_session.add(config1)
        db_session.commit()
        
        config2 = ModelConfiguration(
            provider="test",
            model="duplicate",
            is_active=True,
            is_default=False
        )
        db_session.add(config2)
        
        from sqlalchemy.exc import IntegrityError
        with pytest.raises(IntegrityError):
            db_session.commit()


class TestDeleteProviderConfigurations:
    def test_delete_provider_configurations_hard_deletes_all_provider_rows(self, pricing_manager, db_session):
        """
        验证delete、provider、configurations、soft、deletes、active、rows相关场景的行为是否符合预期。
        通过断言结果可以帮助定位实现与预期行为之间的偏差。
        """
        db_session.add_all([
            ModelConfiguration(provider="deepseek", model="deepseek-chat", is_active=True, is_default=False),
            ModelConfiguration(provider="deepseek", model="deepseek-r1", is_active=True, is_default=False),
            ModelConfiguration(provider="deepseek", model="deepseek-v3", is_active=False, is_default=False),
            ModelConfiguration(provider="openai", model="gpt-4o-mini", is_active=True, is_default=True),
        ])
        db_session.commit()

        deleted_count = pricing_manager.delete_provider_configurations("deepseek")

        assert deleted_count == 3
        deepseek_rows = db_session.query(ModelConfiguration).filter(
            ModelConfiguration.provider == "deepseek"
        ).all()
        assert deepseek_rows == []

        openai_row = db_session.query(ModelConfiguration).filter(
            ModelConfiguration.provider == "openai",
            ModelConfiguration.model == "gpt-4o-mini"
        ).first()
        assert openai_row is not None
        assert openai_row.is_active is True

    def test_delete_provider_configurations_returns_zero_when_provider_not_found(self, pricing_manager):
        """
        验证delete、provider、configurations、returns、zero、when、provider、not、found相关场景的行为是否符合预期。
        通过断言结果可以帮助定位实现与预期行为之间的偏差。
        """
        deleted_count = pricing_manager.delete_provider_configurations("not-exists")
        assert deleted_count == 0

    def test_delete_provider_configurations_normalizes_provider(self, pricing_manager, db_session):
        """
        验证delete、provider、configurations、normalizes、provider相关场景的行为是否符合预期。
        通过断言结果可以帮助定位实现与预期行为之间的偏差。
        """
        db_session.add(
            ModelConfiguration(provider="deepseek", model="deepseek-chat", is_active=True, is_default=False)
        )
        db_session.commit()

        deleted_count = pricing_manager.delete_provider_configurations("  DeepSeek  ")

        assert deleted_count == 1


class TestCreateConfiguration:
    """
    覆盖新增模型配置时的重复保护与软删除重建场景。
    """

    def test_create_configuration_raises_value_error_when_active_duplicate_exists(self, pricing_manager, db_session):
        """
        已有激活配置时再次创建相同 provider/model，应返回明确业务错误而不是数据库 500。
        """
        db_session.add(
            ModelConfiguration(
                provider="deepseek",
                model="deepseek-chat",
                display_name="DeepSeek Chat",
                is_active=True,
                is_default=False,
            )
        )
        db_session.commit()

        with pytest.raises(ValueError) as excinfo:
            pricing_manager.create_configuration({
                "provider": "deepseek",
                "model": "deepseek-chat",
                "display_name": "DeepSeek Chat Duplicate",
                "api_endpoint": "https://api.deepseek.com/v1",
                "is_default": False,
            })

        assert "already exists" in str(excinfo.value)

    def test_create_configuration_reuses_soft_deleted_record(self, pricing_manager, db_session):
        """
        软删除后重新创建相同 provider/model，应复用原记录并重新激活，避免唯一索引冲突。
        """
        deleted_config = ModelConfiguration(
            provider="deepseek",
            model="deepseek-chat",
            display_name="旧配置",
            api_endpoint="https://old.example.com/v1",
            is_active=False,
            is_default=False,
        )
        db_session.add(deleted_config)
        db_session.commit()
        deleted_id = deleted_config.id

        recreated = pricing_manager.create_configuration({
            "provider": "deepseek",
            "model": "deepseek-chat",
            "display_name": "DeepSeek Chat",
            "api_endpoint": "https://api.deepseek.com/v1",
            "is_default": False,
        })

        assert recreated.id == deleted_id
        assert recreated.is_active is True
        assert recreated.display_name == "DeepSeek Chat"
        assert recreated.api_endpoint == "https://api.deepseek.com/v1"

        rows = db_session.query(ModelConfiguration).filter(
            ModelConfiguration.provider == "deepseek",
            ModelConfiguration.model == "deepseek-chat",
        ).all()
        assert len(rows) == 1


class TestGetProviderCatalog:
    """
    覆盖供应商目录合并逻辑：数据库供应商优先、pricing_data 供应商补充。
    """

    def test_get_provider_catalog_returns_database_providers(self, pricing_manager, db_session):
        """
        验证数据库中已配置的供应商出现在目录中，source 为 database。
        """
        from billing.models import ProviderCredential
        db_session.add(ProviderCredential(
            provider="openai",
            display_name="OpenAI",
            api_key="test-key",
            api_endpoint="https://api.openai.com/v1",
            is_active=True,
        ))
        db_session.add(ModelConfiguration(
            provider="openai",
            model="gpt-4o",
            is_active=True,
            is_default=True,
        ))
        db_session.commit()

        catalog = pricing_manager.get_provider_catalog()

        assert len(catalog) >= 1
        openai_entry = next((p for p in catalog if p["id"] == "openai"), None)
        assert openai_entry is not None
        assert openai_entry["source"] == "database"
        assert openai_entry["has_api_key"] is True

    def test_get_provider_catalog_includes_pricing_data_providers(self, pricing_manager, db_session):
        """
        验证 include_pricing_data=True 时，pricing_data.json 中未配置的供应商出现在目录中。
        """
        catalog = pricing_manager.get_provider_catalog(include_pricing_data=True)

        # pricing_data.json 包含 openai/anthropic/google/deepseek/alibaba/moonshot/zhipu
        # 数据库为空，所以所有供应商都应标记为 pricing_data
        pricing_data_entries = [p for p in catalog if p["source"] == "pricing_data"]
        assert len(pricing_data_entries) >= 1, "应至少包含一个 pricing_data 供应商"

        # 验证 pricing_data 供应商有 base_url 和 models
        for entry in pricing_data_entries:
            assert entry["base_url"], f"供应商 {entry['id']} 应有 base_url"
            assert isinstance(entry["models"], list), f"供应商 {entry['id']} 应有 models 列表"
            assert entry["model_count"] == len(entry["models"])

    def test_database_provider_takes_precedence(self, pricing_manager, db_session):
        """
        验证数据库中已配置的供应商优先级高于 pricing_data，source 为 database。
        """
        from billing.models import ProviderCredential
        db_session.add(ProviderCredential(
            provider="openai",
            display_name="My OpenAI",
            api_key="test-key",
            api_endpoint="https://custom.openai.com/v1",
            is_active=True,
        ))
        db_session.add(ModelConfiguration(
            provider="openai",
            model="gpt-4o",
            is_active=True,
            is_default=True,
        ))
        db_session.commit()

        catalog = pricing_manager.get_provider_catalog(include_pricing_data=True)

        openai_entry = next((p for p in catalog if p["id"] == "openai"), None)
        assert openai_entry is not None
        assert openai_entry["source"] == "database", "数据库供应商应优先"
        assert openai_entry["display_name"] == "My OpenAI", "应使用数据库中的 display_name"

    def test_get_provider_catalog_without_pricing_data_no_extra_fields(self, pricing_manager, db_session):
        """
        验证 include_pricing_data=False（默认）时不包含 models 和 model_count 字段。
        """
        from billing.models import ProviderCredential
        db_session.add(ProviderCredential(
            provider="deepseek",
            display_name="DeepSeek",
            is_active=True,
        ))
        db_session.add(ModelConfiguration(
            provider="deepseek",
            model="deepseek-chat",
            is_active=True,
            is_default=True,
        ))
        db_session.commit()

        catalog = pricing_manager.get_provider_catalog(include_pricing_data=False)

        deepseek_entry = next((p for p in catalog if p["id"] == "deepseek"), None)
        assert deepseek_entry is not None
        assert "models" not in deepseek_entry, "不包含 pricing_data 时不应有 models 字段"
        assert "model_count" not in deepseek_entry, "不包含 pricing_data 时不应有 model_count 字段"

    def test_load_pricing_data_providers_returns_grouped_data(self):
        """
        验证 _load_pricing_data_providers 静态方法正确解析 pricing_data.json。
        """
        result = PricingManager._load_pricing_data_providers()

        assert isinstance(result, dict)
        # pricing_data.json 至少包含 openai 和 anthropic
        assert "openai" in result
        assert "anthropic" in result
        assert "name" in result["openai"]
        assert "base_url" in result["openai"]
        assert "models" in result["openai"]
        assert len(result["openai"]["models"]) > 0, "OpenAI 应至少有一个模型"

    def test_pricing_data_provider_has_correct_model_structure(self):
        """
        验证 pricing_data 中每个模型条目包含必要字段。
        """
        result = PricingManager._load_pricing_data_providers()

        for provider_id, data in result.items():
            for model in data["models"]:
                assert "name" in model, f"供应商 {provider_id} 的模型缺少 name 字段"
                assert "input_price" in model, f"供应商 {provider_id} 模型 {model['name']} 缺少 input_price"
                assert "output_price" in model, f"供应商 {provider_id} 模型 {model['name']} 缺少 output_price"
                assert "currency" in model, f"供应商 {provider_id} 模型 {model['name']} 缺少 currency"


class TestSerializeConfigurationApiKeyStatus:
    """
    覆盖 serialize_configuration 在不同 API Key 前缀下返回的
    has_api_key / api_key_status 字段，确保 SECRET_KEY 拆分后
    旧 enc: 密文被正确标记为 stale，引导用户重新录入。
    """

    def test_serialize_configuration_returns_stale_for_legacy_enc_prefix(
        self, pricing_manager, db_session
    ):
        """
        旧 enc: 前缀密文已失效，应返回 has_api_key=False, api_key_status="stale"。
        """
        # 准备旧算法密文的 ProviderCredential
        db_session.add(ProviderCredential(
            provider="deepseek",
            display_name="DeepSeek",
            api_key="enc:legacy_encrypted_payload_that_should_be_invalid",
            api_endpoint="https://api.deepseek.com/v1",
            is_active=True,
        ))
        db_session.add(ModelConfiguration(
            provider="deepseek",
            model="deepseek-chat",
            is_active=True,
            is_default=False,
        ))
        db_session.commit()

        config = db_session.query(ModelConfiguration).filter(
            ModelConfiguration.provider == "deepseek",
            ModelConfiguration.model == "deepseek-chat",
        ).first()

        payload = serialize_configuration(config, pricing_manager)

        assert payload["has_api_key"] is False
        assert payload["api_key_status"] == "stale"

    def test_serialize_configuration_returns_active_for_enc2_prefix(
        self, pricing_manager, db_session
    ):
        """
        enc2: 新前缀密文应返回 has_api_key=True, api_key_status="active"。
        """
        from config.security import encrypt_secret_value

        # 使用新算法加密真实 API Key
        encrypted_key = encrypt_secret_value("sk-real-deepseek-key-12345")
        assert encrypted_key.startswith("enc2:")

        db_session.add(ProviderCredential(
            provider="deepseek",
            display_name="DeepSeek",
            api_key=encrypted_key,
            api_endpoint="https://api.deepseek.com/v1",
            is_active=True,
        ))
        db_session.add(ModelConfiguration(
            provider="deepseek",
            model="deepseek-chat",
            is_active=True,
            is_default=False,
        ))
        db_session.commit()

        config = db_session.query(ModelConfiguration).filter(
            ModelConfiguration.provider == "deepseek",
            ModelConfiguration.model == "deepseek-chat",
        ).first()

        payload = serialize_configuration(config, pricing_manager)

        assert payload["has_api_key"] is True
        assert payload["api_key_status"] == "active"

    def test_serialize_configuration_returns_active_for_plain_text_key(
        self, pricing_manager, db_session
    ):
        """
        无前缀明文（历史兼容）应返回 has_api_key=True, api_key_status="active"。
        """
        db_session.add(ProviderCredential(
            provider="openai",
            display_name="OpenAI",
            api_key="sk-plain-legacy-key-without-prefix",
            api_endpoint="https://api.openai.com/v1",
            is_active=True,
        ))
        db_session.add(ModelConfiguration(
            provider="openai",
            model="gpt-4o",
            is_active=True,
            is_default=False,
        ))
        db_session.commit()

        config = db_session.query(ModelConfiguration).filter(
            ModelConfiguration.provider == "openai",
            ModelConfiguration.model == "gpt-4o",
        ).first()

        payload = serialize_configuration(config, pricing_manager)

        assert payload["has_api_key"] is True
        assert payload["api_key_status"] == "active"

    def test_serialize_configuration_returns_missing_for_empty_api_key(
        self, pricing_manager, db_session
    ):
        """
        ProviderCredential 存在但 api_key 为空时，应返回
        has_api_key=False, api_key_status="missing"。
        """
        db_session.add(ProviderCredential(
            provider="anthropic",
            display_name="Anthropic",
            api_key="",  # 显式空字符串
            api_endpoint="https://api.anthropic.com",
            is_active=True,
        ))
        db_session.add(ModelConfiguration(
            provider="anthropic",
            model="claude-3-5-sonnet",
            is_active=True,
            is_default=False,
        ))
        db_session.commit()

        config = db_session.query(ModelConfiguration).filter(
            ModelConfiguration.provider == "anthropic",
            ModelConfiguration.model == "claude-3-5-sonnet",
        ).first()

        payload = serialize_configuration(config, pricing_manager)

        assert payload["has_api_key"] is False
        assert payload["api_key_status"] == "missing"

    def test_serialize_configuration_returns_missing_for_null_api_key(
        self, pricing_manager, db_session
    ):
        """
        ProviderCredential 存在但 api_key 为 None 时，应返回
        has_api_key=False, api_key_status="missing"。
        """
        db_session.add(ProviderCredential(
            provider="google",
            display_name="Google",
            api_key=None,  # 显式 None
            api_endpoint="https://generativelanguage.googleapis.com",
            is_active=True,
        ))
        db_session.add(ModelConfiguration(
            provider="google",
            model="gemini-2.0-flash",
            is_active=True,
            is_default=False,
        ))
        db_session.commit()

        config = db_session.query(ModelConfiguration).filter(
            ModelConfiguration.provider == "google",
            ModelConfiguration.model == "gemini-2.0-flash",
        ).first()

        payload = serialize_configuration(config, pricing_manager)

        assert payload["has_api_key"] is False
        assert payload["api_key_status"] == "missing"

    def test_serialize_configuration_returns_missing_when_no_credential(
        self, pricing_manager, db_session
    ):
        """
        无 ProviderCredential 记录时，应返回
        has_api_key=False, api_key_status="missing"。
        """
        db_session.add(ModelConfiguration(
            provider="moonshot",
            model="moonshot-v1-32k",
            is_active=True,
            is_default=False,
        ))
        db_session.commit()

        config = db_session.query(ModelConfiguration).filter(
            ModelConfiguration.provider == "moonshot",
            ModelConfiguration.model == "moonshot-v1-32k",
        ).first()

        payload = serialize_configuration(config, pricing_manager)

        assert payload["has_api_key"] is False
        assert payload["api_key_status"] == "missing"

    def test_serialize_configuration_uses_cred_map_to_skip_n_plus_1(
        self, pricing_manager, db_session
    ):
        """
        传入 cred_map 时应使用映射表而非逐个查询，且仍能正确识别 enc: 旧密文。
        """
        db_session.add(ProviderCredential(
            provider="zhipu",
            display_name="Zhipu",
            api_key="enc:legacy_zhipu_key_should_be_stale",
            api_endpoint="https://open.bigmodel.cn/api/paas/v4",
            is_active=True,
        ))
        db_session.add(ModelConfiguration(
            provider="zhipu",
            model="glm-4",
            is_active=True,
            is_default=False,
        ))
        db_session.commit()

        config = db_session.query(ModelConfiguration).filter(
            ModelConfiguration.provider == "zhipu",
            ModelConfiguration.model == "glm-4",
        ).first()

        # 构造预加载映射表
        normalized = pricing_manager.normalize_provider("zhipu")
        cred = pricing_manager.get_provider_credential(normalized)
        cred_map = {normalized: cred}

        payload = serialize_configuration(config, pricing_manager, cred_map=cred_map)

        assert payload["has_api_key"] is False
        assert payload["api_key_status"] == "stale"
