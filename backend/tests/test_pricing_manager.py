import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from billing.models import Base, ModelConfiguration
from billing.pricing_manager import PricingManager


@pytest.fixture
def db_session():
    """Create an in-memory database for testing."""
    engine = create_engine('sqlite:///:memory:', echo=False)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def pricing_manager(db_session):
    """Create a PricingManager instance."""
    return PricingManager(db_session)


class TestInitializeDefaultConfigurations:
    """Test the initialize_default_configurations method."""

    def test_initialize_creates_configurations_when_empty(self, pricing_manager, db_session):
        """Should create default configurations when table is empty."""
        count = pricing_manager.initialize_default_configurations()

        assert count == 5, "Should create 5 default configurations"

        configs = db_session.query(ModelConfiguration).all()
        assert len(configs) == 5, "Should have 5 configurations in database"

        providers = [c.provider for c in configs]
        assert "openai" in providers
        assert "anthropic" in providers
        assert "google" in providers
        assert "deepseek" in providers

    def test_initialize_skips_when_configurations_exist(self, pricing_manager, db_session):
        """Should not create configurations when table is not empty."""
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

        assert count == 0, "Should return 0 when configurations exist"
        configs = db_session.query(ModelConfiguration).all()
        assert len(configs) == 1, "Should only have the existing configuration"

    def test_initialize_sets_first_as_default(self, pricing_manager, db_session):
        """First configuration should be set as default."""
        pricing_manager.initialize_default_configurations()

        configs = db_session.query(ModelConfiguration).order_by(ModelConfiguration.sort_order).all()
        default_configs = [c for c in configs if c.is_default]

        assert len(default_configs) == 1, "Should have exactly one default configuration"
        assert default_configs[0].model == "gpt-4", "GPT-4 should be the default"
        assert default_configs[0].provider == "openai"

    def test_initialize_respects_sort_order(self, pricing_manager, db_session):
        """Configurations should be created in correct sort order."""
        pricing_manager.initialize_default_configurations()

        configs = db_session.query(ModelConfiguration).order_by(ModelConfiguration.sort_order).all()

        assert configs[0].sort_order == 0
        assert configs[1].sort_order == 1
        assert configs[2].sort_order == 2
        assert configs[3].sort_order == 3
        assert configs[4].sort_order == 4

    def test_initialize_creates_correct_display_names(self, pricing_manager, db_session):
        """Should create configurations with correct display names."""
        pricing_manager.initialize_default_configurations()

        gpt4 = db_session.query(ModelConfiguration).filter(
            ModelConfiguration.provider == "openai",
            ModelConfiguration.model == "gpt-4"
        ).first()

        assert gpt4 is not None
        assert gpt4.display_name == "GPT-4"
        assert "最强大的通用AI模型" in gpt4.description

    def test_initialize_all_active(self, pricing_manager, db_session):
        """All default configurations should be active."""
        pricing_manager.initialize_default_configurations()

        configs = db_session.query(ModelConfiguration).all()
        inactive = [c for c in configs if not c.is_active]

        assert len(inactive) == 0, "All configurations should be active"

    def test_initialize_idempotent(self, pricing_manager, db_session):
        """Calling initialize multiple times should not create duplicates."""
        pricing_manager.initialize_default_configurations()
        pricing_manager.initialize_default_configurations()
        count2 = pricing_manager.initialize_default_configurations()

        assert count2 == 0, "Second initialization should return 0"
        configs = db_session.query(ModelConfiguration).all()
        assert len(configs) == 5, "Should still have only 5 configurations"

    def test_initialize_no_duplicate_provider_model_combinations(self, pricing_manager, db_session):
        """Should not create duplicate provider:model combinations."""
        pricing_manager.initialize_default_configurations()
        pricing_manager.initialize_default_configurations()

        configs = db_session.query(ModelConfiguration).all()
        seen = set()
        for config in configs:
            key = (config.provider, config.model)
            assert key not in seen, f"Duplicate configuration: {key}"
            seen.add(key)

        assert len(seen) == 5, "Should have 5 unique provider:model combinations"


class TestGetActiveConfigurations:
    """Test the get_active_configurations method."""

    def test_get_active_only_returns_active(self, pricing_manager, db_session):
        """Should only return active configurations."""
        pricing_manager.initialize_default_configurations()

        active = pricing_manager.get_active_configurations()

        assert len(active) == 5
        for config in active:
            assert config.is_active is True

    def test_get_active_excludes_inactive(self, pricing_manager, db_session):
        """Should exclude inactive configurations."""
        pricing_manager.initialize_default_configurations()

        config = db_session.query(ModelConfiguration).first()
        config.is_active = False
        db_session.commit()

        active = pricing_manager.get_active_configurations()

        assert len(active) == 4
        inactive_ids = [c.id for c in db_session.query(ModelConfiguration).filter(
            ModelConfiguration.is_active == False
        ).all()]
        for a in active:
            assert a.id not in inactive_ids

    def test_get_active_ordered_by_sort_order(self, pricing_manager, db_session):
        """Should return configurations ordered by sort_order."""
        pricing_manager.initialize_default_configurations()

        active = pricing_manager.get_active_configurations()

        for i in range(len(active) - 1):
            assert active[i].sort_order <= active[i + 1].sort_order


class TestDefaultConfiguration:
    """Test the get_default_configuration method."""

    def test_get_default_returns_default_config(self, pricing_manager, db_session):
        """Should return the default configuration."""
        pricing_manager.initialize_default_configurations()

        default = pricing_manager.get_default_configuration()

        assert default is not None
        assert default.is_default is True
        assert default.model == "gpt-4"

    def test_get_default_returns_none_when_no_default(self, pricing_manager, db_session):
        """Should return None when no default is set."""
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
    """Test the configuration uniqueness validation methods."""

    def test_validate_configurations_uniqueness_with_unique_data(self):
        """Should pass validation with unique configurations."""
        configs = [
            {"provider": "openai", "model": "gpt-4"},
            {"provider": "anthropic", "model": "claude-3.5-sonnet"},
        ]
        
        is_unique, duplicates = PricingManager._validate_configurations_uniqueness(configs)
        
        assert is_unique is True
        assert len(duplicates) == 0

    def test_validate_configurations_uniqueness_with_duplicates(self):
        """Should detect duplicate configurations."""
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
        """Should detect multiple duplicate configurations."""
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
        """validate_default_configurations should pass with current DEFAULT_CONFIGURATIONS."""
        is_unique, duplicates = PricingManager.validate_default_configurations()
        
        assert is_unique is True, f"DEFAULT_CONFIGURATIONS should be unique, but found duplicates: {duplicates}"
        assert len(duplicates) == 0

    def test_initialize_raises_error_on_duplicate_configurations(self, pricing_manager, db_session):
        """Should raise ValueError when DEFAULT_CONFIGURATIONS contains duplicates."""
        original_data = PricingManager.DEFAULT_CONFIGURATIONS.copy()
        try:
            PricingManager.DEFAULT_CONFIGURATIONS.extend([
                {"provider": "openai", "model": "gpt-4", "display_name": "Duplicate", "description": "Test", "is_active": True, "is_default": False, "sort_order": 99}
            ])
            
            with pytest.raises(ValueError) as excinfo:
                pricing_manager.initialize_default_configurations()
            
            assert "duplicate" in str(excinfo.value).lower()
            assert "openai/gpt-4" in str(excinfo.value)
        finally:
            PricingManager.DEFAULT_CONFIGURATIONS[:] = original_data

    def test_initialize_creates_unique_constraint_index(self, db_session):
        """Database should have unique constraint on provider+model."""
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
        """Database should prevent duplicate provider:model combinations."""
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
