from pydantic import BaseModel


class ExperienceExtractionConfig(BaseModel):
    """经验提取配置"""
    enabled: bool = True
    auto_extract_on_success: bool = True
    auto_extract_on_failure: bool = True
    min_task_complexity: int = 3
    max_experiences_per_session: int = 5
    batch_interval_hours: int = 24
    confidence_threshold: float = 0.3


class ExperienceRetrievalConfig(BaseModel):
    """经验检索配置"""
    enabled: bool = True
    max_experiences: int = 3
    min_confidence: float = 0.3
    include_semantic_search: bool = True
    include_rule_based_search: bool = True


class ExperienceQualityConfig(BaseModel):
    """经验质量配置"""
    auto_archive_threshold: float = 0.2
    review_threshold: float = 0.3
    usage_count_for_archive: int = 20
    confidence_decay_rate: float = 0.95


class ExperienceConfig(BaseModel):
    """经验记忆系统总配置"""
    extraction: ExperienceExtractionConfig = ExperienceExtractionConfig()
    retrieval: ExperienceRetrievalConfig = ExperienceRetrievalConfig()
    quality: ExperienceQualityConfig = ExperienceQualityConfig()


experience_config = ExperienceConfig()
