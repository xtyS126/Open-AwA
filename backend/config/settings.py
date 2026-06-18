"""
配置管理模块，负责系统运行参数、安全策略或日志行为的统一定义。
配置项通常会在多个子模块中生效，因此理解其字段含义非常重要。
"""

from pathlib import Path
import os
from typing import Iterable, Optional

from dotenv import dotenv_values
from loguru import logger
from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


_BACKEND_DIR = Path(__file__).resolve().parents[1]
_PROJECT_DIR = _BACKEND_DIR.parent
_ENV_FILE_PRIORITY = (
    _BACKEND_DIR / ".env.local",
    _PROJECT_DIR / ".env.local",
    _BACKEND_DIR / ".env",
    _PROJECT_DIR / ".env",
)


def _resolve_existing_env_files(env_files: Optional[Iterable[Path]] = None) -> tuple[Path, ...]:
    """
    按优先级筛选存在的环境文件，并去除重复路径。
    """
    resolved_files = []
    seen_paths = set()
    for env_file in env_files or _ENV_FILE_PRIORITY:
        resolved_path = Path(env_file).resolve()
        if not resolved_path.exists() or resolved_path in seen_paths:
            continue
        seen_paths.add(resolved_path)
        resolved_files.append(resolved_path)
    return tuple(resolved_files)


def preload_environment_variables(env_files: Optional[Iterable[Path]] = None) -> tuple[Path, ...]:
    """
    将环境文件预加载到进程环境中，兼容仍直接使用 os.getenv 的旧代码路径。
    """
    loaded_files = _resolve_existing_env_files(env_files)
    for env_file in loaded_files:
        for key, value in dotenv_values(env_file).items():
            if key and value is not None:
                os.environ.setdefault(key, value)
    return loaded_files


_LOADED_ENV_FILES = preload_environment_variables()
_SETTINGS_ENV_FILES = tuple(str(path) for path in reversed(_LOADED_ENV_FILES))


def is_production_environment(environment: Optional[str]) -> bool:
    """
    统一识别生产环境别名，避免因环境值写法差异绕过安全检查。
    """
    normalized = str(environment or "development").strip().lower()
    return normalized in {"production", "prod", "live"}



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
    model_config = SettingsConfigDict(
        env_file=_SETTINGS_ENV_FILES or None,
        case_sensitive=True,
        extra="ignore",
    )

    PROJECT_NAME: str = "Open-AwA AI Agent"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api"
    ENVIRONMENT: str = "development"
    
    # 默认固定到 backend/openawa.db 的绝对路径，避免受进程启动目录影响。
    DATABASE_URL: str = build_default_database_url()

    # 数据库连接池配置，可通过环境变量覆盖（DB_POOL_SIZE / DB_MAX_OVERFLOW）
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10
    
    SECRET_KEY: str = "openawa-dev-default"
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

    # API Key 认证配置（单用户模式）
    # 全局 API Key，未设置时启动时自动生成并写入 .env.local
    OPENAWA_API_KEY: str = ""
    # Owner 用户名（默认 admin）
    OPENAWA_OWNER_USERNAME: str = "admin"
    # Owner 密码（未设置时自动生成，仅用于 JWT 兼容路径）
    OPENAWA_OWNER_PASSWORD: str = ""
    # Owner 昵称（可选，用于用户画像初始化）
    OPENAWA_OWNER_NICKNAME: str = ""
    # Owner 邮箱（可选，用于用户画像初始化）
    OPENAWA_OWNER_EMAIL: str = ""

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
    SANDBOX_BACKEND: str = "restricted_python"

    # Agent 运行时配置
    MAX_TOOL_CALL_ROUNDS: int = 12        # 工具调用回环最大轮数
    MAX_ACTIVE_AGENT_TASKS: int = 1000    # 活跃 Agent 任务容量上限
    TOOL_EXECUTION_CACHE_SIZE: int = 256  # 工具执行幂等缓存上限
    RECORD_SEMAPHORE_SIZE: int = 20       # 并发记录任务信号量上限

    # 受信代理 IP/CIDR 列表，用逗号分隔。仅来自这些代理的 X-Forwarded-For / X-Real-IP 头会被信任。
    # 默认信任本地回环和私有地址段（适用于单机部署和 Docker 网络）。
    TRUSTED_PROXIES: str = "127.0.0.1,::1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"
    
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

    # 登录限流后端配置：memory（单进程） | database（多 worker 分布式）
    RATE_LIMIT_BACKEND: str = "memory"

    # 数据库监控配置
    SLOW_QUERY_THRESHOLD_MS: int = 500    # 慢查询检测阈值（毫秒）

    # 可选 HTTPS 配置，证书和私钥同时提供时启用 TLS。
    SSL_CERTFILE: Optional[str] = None
    SSL_KEYFILE: Optional[str] = None
    SSL_KEYFILE_PASSWORD: Optional[str] = None
    SSL_CA_CERTS: Optional[str] = None
    
    # --- Agent 引擎增强配置 ---

    # 自主纠错最大轮数（超出则请求人工介入）
    AGENT_SELF_CORRECTION_MAX_ROUNDS: int = 3

    # 单步骤超时（秒）
    AGENT_STEP_TIMEOUT_SECONDS: int = 30

    # 单任务全局超时（秒）
    AGENT_TASK_TIMEOUT_SECONDS: int = 300

    # 指数退避重试基础间隔（秒）
    AGENT_RETRY_BASE_INTERVAL: float = 2.0

    # 指数退避重试最大间隔（秒）
    AGENT_RETRY_MAX_INTERVAL: float = 60.0

    # 指数退避随机抖动系数（0.0-1.0）
    AGENT_RETRY_JITTER: float = 0.1

    # 步骤快照最大保留数量（防止内存泄漏）
    AGENT_SNAPSHOT_MAX_COUNT: int = 50

    # 模型降级策略：主模型失败时是否自动切换备用模型
    AGENT_MODEL_FALLBACK_ENABLED: bool = True

    experience_extraction_enabled: bool = True
    experience_retrieval_enabled: bool = True

    def is_ssl_enabled(self) -> bool:
        """
        判断当前配置是否具备启用 HTTPS 的最小条件。
        只有证书和私钥都已配置时，启动流程才会向 uvicorn 传递 TLS 参数。
        """
        certfile = (self.SSL_CERTFILE or "").strip()
        keyfile = (self.SSL_KEYFILE or "").strip()
        return bool(certfile and keyfile)

    @model_validator(mode="after")
    def apply_runtime_defaults(self) -> "Settings":
        """
        在完成环境加载后补齐运行期默认值，避免导入阶段绕过环境文件配置。
        """
        environment = str(self.ENVIRONMENT or "development").strip() or "development"

        if environment != self.ENVIRONMENT:
            object.__setattr__(self, "ENVIRONMENT", environment)

        if is_production_environment(environment) and self.SECRET_KEY == "openawa-dev-default":
            logger.error("SECRET_KEY must be explicitly set in production environment")
            raise ValueError("SECRET_KEY must be explicitly set in production environment")

        return self


settings = Settings()
