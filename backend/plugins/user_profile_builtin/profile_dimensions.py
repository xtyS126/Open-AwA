"""
用户画像维度定义，描述画像分类体系和每类包含的具体字段。
"""

PROFILE_CATEGORIES = {
    "identity": {
        "label": "身份特征",
        "description": "用户的基本身份信息和人口统计特征",
        "priority": 1,  # 上下文注入优先级（1最高）
        "decay_rate": 0.005,  # 身份信息衰减很慢
        "fact_keys": [
            "name", "age_range", "location", "occupation", "organization",
            "education_level", "primary_language", "timezone", "experience_level",
        ],
    },
    "preference": {
        "label": "偏好设置",
        "description": "用户对工具、技术、交互方式的显式和隐式偏好",
        "priority": 2,
        "decay_rate": 0.01,
        "fact_keys": [
            "programming_language", "framework", "tool_preference",
            "code_style", "documentation_language", "test_framework",
            "deployment_method", "database_preference", "ai_model_preference",
        ],
    },
    "expertise": {
        "label": "知识水平",
        "description": "用户在特定领域的技术深度和熟练程度",
        "priority": 3,
        "decay_rate": 0.008,
        "fact_keys": [
            "primary_domain", "skill_level", "years_of_experience",
            "known_technologies", "learning_goals", "knowledge_gaps",
            "certifications",
        ],
    },
    "behavior": {
        "label": "行为模式",
        "description": "用户的使用习惯、活跃模式和任务偏好",
        "priority": 4,
        "decay_rate": 0.02,
        "fact_keys": [
            "active_hours", "session_duration", "task_frequency",
            "common_actions", "workflow_pattern", "error_frequency",
            "feedback_behavior", "tool_usage_frequency",
        ],
    },
    "goal": {
        "label": "目标与意图",
        "description": "用户的长期目标和短期任务意图",
        "priority": 3,
        "decay_rate": 0.015,
        "fact_keys": [
            "current_project", "long_term_goals", "learning_objectives",
            "pain_points", "success_criteria", "upcoming_tasks",
        ],
    },
    "communication_style": {
        "label": "沟通风格",
        "description": "用户的表达方式和交互偏好",
        "priority": 2,
        "decay_rate": 0.015,
        "fact_keys": [
            "verbosity_level", "response_style", "question_pattern",
            "technical_jargon_tolerance", "emoji_usage", "formality_level",
            "language_mixing", "feedback_style",
        ],
    },
    "emotional_state": {
        "label": "情感状态",
        "description": "用户的情绪趋势和满意度指标（瞬时态，高频衰减）",
        "priority": 5,
        "decay_rate": 0.05,  # 情绪衰减最快
        "fact_keys": [
            "sentiment_trend", "satisfaction_level", "frustration_topics",
            "engagement_level", "stress_indicators",
        ],
    },
    "context": {
        "label": "环境上下文",
        "description": "用户的设备、网络和物理环境信息",
        "priority": 5,
        "decay_rate": 0.02,
        "fact_keys": [
            "primary_device", "os", "browser", "network_environment",
            "working_environment", "team_context",
        ],
    },
    "custom": {
        "label": "自定义维度",
        "description": "管理员或用户自定义的画像维度",
        "priority": 6,
        "decay_rate": 0.01,
        "fact_keys": [],  # 自定义维度无预定义键
    },
}

# 来源类型的基础置信度
SOURCE_BASE_CONFIDENCE = {
    "explicit": 0.95,
    "manual": 0.90,
    "feedback": 0.80,
    "inferred": 0.50,
    "behavioral": 0.55,
}

# 置信度等级
CONFIDENCE_HIGH = 0.75
CONFIDENCE_MEDIUM = 0.40
CONFIDENCE_ARCHIVE = 0.15
