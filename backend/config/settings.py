"""
配置管理模块，负责系统运行参数、安全策略或日志行为的统一定义。
配置项通常会在多个子模块中生效，因此理解其字段含义非常重要。
"""

from pathlib import Path
from pydantic_settings import BaseSettings
from pydantic import SecretStr
from typing import Optional
import os
import secrets


def is_production_environment(environment: Optional[str]) -> bool:
    """
    统一识别生产环境别名，避免因环境值写法差异绕过安全检查。
    """
    normalized = str(environment or "development").strip().lower()
    return normalized in {"production", "prod", "live"}


def generate_secret_key() -> str:
    """
    生成或加载 SECRET_KEY。
    生产环境必须通过环境变量显式配置；
    开发环境自动生成后持久化到 .env.local，跨重启保持一致，避免 JWT token 全部失效。
    """
    from loguru import logger
    
    env_key = os.getenv("SECRET_KEY")
    environment = os.getenv("ENVIRONMENT", "development")
    
    if is_production_environment(environment) and not env_key:
        logger.error("SECRET_KEY environment variable is required in production environment")
        raise ValueError("SECRET_KEY environment variable is required in production environment")
    
    if env_key:
        return env_key
    
    # 开发环境：尝试从 .env.local 加载已生成的 key，保持跨重启一致性
    env_local_path = Path(__file__).resolve().parents[1] / ".env.local"
    if env_local_path.exists():
        with open(env_local_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("SECRET_KEY="):
                    persisted_key = line[len("SECRET_KEY="):]
                    if persisted_key:
                        return persisted_key
    
    # 首次启动：生成新 key 并持久化到 .env.local
    new_key = secrets.token_urlsafe(32)
    logger.warning(
        "SECRET_KEY not set, generating new key and persisting to .env.local. "
        "This is not secure for production!"
    )
    try:
        with open(env_local_path, "a", encoding="utf-8") as f:
            f.write(f"\nSECRET_KEY={new_key}\n")
    except OSError as e:
        logger.warning(f"无法持久化 SECRET_KEY 到 .env.local: {e}")
    return new_key


def build_default_database_url() -> str:
    """
    构造稳定的默认 SQLite 连接地址。
    这里显式锚定到 backend 目录，避免服务从仓库根目录启动时误连到错误的空库。
    """
    backend_dir = Path(__file__).resolve().parents[1]
    database_path = (backend_dir / "openawa.db").resolve()
    return f"sqlite:///{database_path.as_posix()}"


class Settings(BaseSettings):
    """
    封装与Settings相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    PROJECT_NAME: str = "Open-AwA AI Agent"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api"
    
    # 默认固定到 backend/openawa.db 的绝对路径，避免受进程启动目录影响。
    DATABASE_URL: str = build_default_database_url()
    
    SECRET_KEY: str = generate_secret_key()
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24
    
    OPENAI_API_KEY: Optional[SecretStr] = None
    ANTHROPIC_API_KEY: Optional[SecretStr] = None
    DEEPSEEK_API_KEY: Optional[SecretStr] = None
    
    # Ollama 本地模型配置
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    
    # 通义千问配置
    QWEN_API_KEY: SecretStr = SecretStr("")
    QWEN_BASE_URL: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    
    # 智谱AI配置
    ZHIPU_API_KEY: SecretStr = SecretStr("")
    ZHIPU_BASE_URL: str = "https://open.bigmodel.cn/api/paas/v4"
    
    # Kimi/Moonshot配置
    MOONSHOT_API_KEY: SecretStr = SecretStr("")
    MOONSHOT_BASE_URL: str = "https://api.moonshot.cn/v1"
    
    # 矢量数据库路径，基于 backend 目录碟定绝对路径，避免工作目录不同导致路径错误
    VECTOR_DB_PATH: str = str(Path(__file__).resolve().parents[1] / "data" / "vector_db")

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
