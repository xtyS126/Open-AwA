"""
配置管理模块，负责系统运行参数、安全策略或日志行为的统一定义。
配置项通常会在多个子模块中生效，因此理解其字段含义非常重要。
"""

from pydantic_settings import BaseSettings
from typing import Optional
import os
import secrets


def generate_secret_key() -> str:
    """
    处理generate、secret、key相关逻辑，并为调用方返回对应结果。
    阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
    """
    from loguru import logger
    
    env_key = os.getenv("SECRET_KEY")
    environment = os.getenv("ENVIRONMENT", "development")
    
    if environment == "production" and not env_key:
        logger.error("SECRET_KEY environment variable is required in production environment")
        raise ValueError("SECRET_KEY environment variable is required in production environment")
    
    if not env_key:
        logger.warning("SECRET_KEY not set, using randomly generated key. This is not secure for production!")
        return secrets.token_urlsafe(32)
    
    return env_key


class Settings(BaseSettings):
    """
    封装与Settings相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    PROJECT_NAME: str = "Open-AwA AI Agent"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api"
    
    # SQLite 数据库文件路径，使用相对路径时会相对于 backend 目录解析，亦即以 main.py 所在目录为基准。
    DATABASE_URL: str = "sqlite:///./openawa.db"
    
    SECRET_KEY: str = generate_secret_key()
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24
    
    OPENAI_API_KEY: Optional[str] = None
    ANTHROPIC_API_KEY: Optional[str] = None
    DEEPSEEK_API_KEY: Optional[str] = None
    
    # Ollama 本地模型配置
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    
    # 通义千问配置
    QWEN_API_KEY: str = ""
    QWEN_BASE_URL: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    
    # 智谱AI配置
    ZHIPU_API_KEY: str = ""
    ZHIPU_BASE_URL: str = "https://open.bigmodel.cn/api/paas/v4"
    
    # Kimi/Moonshot配置
    MOONSHOT_API_KEY: str = ""
    MOONSHOT_BASE_URL: str = "https://api.moonshot.cn/v1"
    
    VECTOR_DB_PATH: str = "./data/vector_db"

    # 微信集成配置
    WEIXIN_DEFAULT_BASE_URL: str = "https://ilinkai.weixin.qq.com"
    WEIXIN_DEFAULT_BOT_TYPE: str = "3"
    WEIXIN_DEFAULT_CHANNEL_VERSION: str = "1.0.2"
    WEIXIN_SESSION_TIMEOUT_SECONDS: int = 3600
    WEIXIN_TOKEN_REFRESH_ENABLED: bool = True

    USAGE_RETENTION_DAYS: int = 365
    
    MAX_UPLOAD_SIZE: int = 10 * 1024 * 1024
    ALLOWED_EXTENSIONS: set = {".txt", ".md", ".py", ".js", ".json", ".yaml", ".yml"}
    
    SANDBOX_TIMEOUT: int = 30
    SANDBOX_MEMORY_LIMIT: str = "512m"
    
    LOG_LEVEL: str = "INFO"
    LOG_SERIALIZE: bool = True
    LOG_SERVICE_NAME: str = "openawa-backend"
    # 日志文件持久化配置
    LOG_DIR: str = "./logs"
    LOG_FILE_ROTATION: str = "10 MB"
    LOG_FILE_RETENTION: str = "30 days"
    LOG_FILE_COMPRESSION: str = "gz"
    # 开发环境脱敏开关（True 时禁用脱敏，方便调试）
    LOG_DISABLE_SANITIZE: bool = False
    
    experience_extraction_enabled: bool = True
    experience_retrieval_enabled: bool = True
    
    class Config:
        """
        封装与Config相关的核心逻辑与运行状态。
        该类通常是当前文件中组织数据与调度行为的主要封装单元。
        """
        env_file = ".env"
        case_sensitive = True


settings = Settings()
