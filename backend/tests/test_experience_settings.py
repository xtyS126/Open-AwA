"""
config/experience_settings.py 单元测试。
覆盖经验提取、检索和质量配置的默认值与自定义值。
"""

import pytest
from pydantic import BaseModel


class TestExperienceExtractionConfig:
    """测试经验提取配置"""

    def test_default_values(self):
        from config.experience_settings import ExperienceExtractionConfig

        config = ExperienceExtractionConfig()
        assert config.enabled is True
        assert config.auto_extract_on_success is True
        assert config.auto_extract_on_failure is True
        assert config.min_task_complexity == 3
        assert config.max_experiences_per_session == 5
        assert config.batch_interval_hours == 24
        assert config.confidence_threshold == 0.3

    def test_custom_values(self):
        from config.experience_settings import ExperienceExtractionConfig

        config = ExperienceExtractionConfig(
            enabled=False,
            min_task_complexity=5,
            max_experiences_per_session=10,
        )
        assert config.enabled is False
        assert config.min_task_complexity == 5
        assert config.max_experiences_per_session == 10
        # 未设置的保留默认值
        assert config.auto_extract_on_success is True

    def test_field_types(self):
        from config.experience_settings import ExperienceExtractionConfig

        config = ExperienceExtractionConfig()
        assert isinstance(config.enabled, bool)
        assert isinstance(config.min_task_complexity, int)
        assert isinstance(config.confidence_threshold, float)


class TestExperienceRetrievalConfig:
    """测试经验检索配置"""

    def test_default_values(self):
        from config.experience_settings import ExperienceRetrievalConfig

        config = ExperienceRetrievalConfig()
        assert config.enabled is True
        assert config.max_experiences == 3
        assert config.min_confidence == 0.3
        assert config.include_semantic_search is True
        assert config.include_rule_based_search is True

    def test_custom_values(self):
        from config.experience_settings import ExperienceRetrievalConfig

        config = ExperienceRetrievalConfig(
            max_experiences=10,
            min_confidence=0.5,
            include_semantic_search=False,
        )
        assert config.max_experiences == 10
        assert config.min_confidence == 0.5
        assert config.include_semantic_search is False
        assert config.include_rule_based_search is True


class TestExperienceQualityConfig:
    """测试经验质量配置"""

    def test_default_values(self):
        from config.experience_settings import ExperienceQualityConfig

        config = ExperienceQualityConfig()
        assert config.auto_archive_threshold == 0.2
        assert config.review_threshold == 0.3
        assert config.usage_count_for_archive == 20
        assert config.confidence_decay_rate == 0.95

    def test_custom_values(self):
        from config.experience_settings import ExperienceQualityConfig

        config = ExperienceQualityConfig(
            review_threshold=0.5,
            usage_count_for_archive=50,
        )
        assert config.review_threshold == 0.5
        assert config.usage_count_for_archive == 50
        assert config.auto_archive_threshold == 0.2


class TestExperienceConfig:
    """测试经验配置聚合"""

    def test_default_nesting(self):
        from config.experience_settings import ExperienceConfig

        config = ExperienceConfig()
        assert config.extraction.enabled is True
        assert config.retrieval.enabled is True
        assert config.quality.auto_archive_threshold == 0.2

    def test_partial_override(self):
        from config.experience_settings import (
            ExperienceConfig,
            ExperienceExtractionConfig,
        )

        config = ExperienceConfig(
            extraction=ExperienceExtractionConfig(enabled=False),
        )
        assert config.extraction.enabled is False
        # 其他子配置保持默认
        assert config.retrieval.enabled is True
        assert config.quality.auto_archive_threshold == 0.2

    def test_full_override(self):
        from config.experience_settings import (
            ExperienceConfig,
            ExperienceExtractionConfig,
            ExperienceRetrievalConfig,
            ExperienceQualityConfig,
        )

        config = ExperienceConfig(
            extraction=ExperienceExtractionConfig(enabled=False),
            retrieval=ExperienceRetrievalConfig(max_experiences=10),
            quality=ExperienceQualityConfig(review_threshold=0.8),
        )
        assert config.extraction.enabled is False
        assert config.retrieval.max_experiences == 10
        assert config.quality.review_threshold == 0.8


def test_module_level_singleton_exists():
    """模块级单例 experience_config 存在且可访问"""
    from config.experience_settings import experience_config, ExperienceConfig

    assert experience_config is not None
    assert isinstance(experience_config, ExperienceConfig)
    assert experience_config.extraction.enabled is True
