"""
配置管理模块，负责系统运行参数、安全策略或日志行为的统一定义。
配置项通常会在多个子模块中生效，因此理解其字段含义非常重要。
"""

from pydantic import BaseModel


class ExperienceExtractionConfig(BaseModel):
    """
    封装与ExperienceExtractionConfig相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    enabled: bool = True
    auto_extract_on_success: bool = True
    auto_extract_on_failure: bool = True
    min_task_complexity: int = 3
    max_experiences_per_session: int = 5
    batch_interval_hours: int = 24
    confidence_threshold: float = 0.3


class ExperienceRetrievalConfig(BaseModel):
    """
    封装与ExperienceRetrievalConfig相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    enabled: bool = True
    max_experiences: int = 3
    min_confidence: float = 0.3
    include_semantic_search: bool = True
    include_rule_based_search: bool = True


class ExperienceQualityConfig(BaseModel):
    """
    封装与ExperienceQualityConfig相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    auto_archive_threshold: float = 0.2
    review_threshold: float = 0.3
    usage_count_for_archive: int = 20
    confidence_decay_rate: float = 0.95


class ExperienceConfig(BaseModel):
    """
    封装与ExperienceConfig相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    extraction: ExperienceExtractionConfig = ExperienceExtractionConfig()
    retrieval: ExperienceRetrievalConfig = ExperienceRetrievalConfig()
    quality: ExperienceQualityConfig = ExperienceQualityConfig()


experience_config = ExperienceConfig()
