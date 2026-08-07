"""
配置管理模块，负责系统运行参数、安全策略或日志行为的统一定义。
配置项通常会在多个子模块中生效，因此理解其字段含义非常重要。
"""

from pathlib import Path
import os
import secrets
from typing import Iterable, Optional

from dotenv import dotenv_values
from loguru import logger
from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from config.runtime_paths import (
    BACKEND_DIR,
    DATA_DIR,
    LOG_DIR,
    PETS_DATA_DIR,
    PLUGINS_DATA_DIR,
    PROJECT_ROOT,
    UPLOADS_DIR,
    VAR_DIR,
    WORKSPACE_DIR,
    ensure_runtime_directories,
)


# 路径锚点（绝对路径）：
#   __file__ = backend/config/settings.py
#   parents[0] = backend/config/
#   parents[1] = backend/
#   parents[2] = 项目根/
_BACKEND_DIR = BACKEND_DIR
_PROJECT_DIR = PROJECT_ROOT
_VAR_DIR = VAR_DIR
_DATA_DIR = DATA_DIR
_LOG_DIR_ABS = LOG_DIR
_WORKSPACE_DIR = WORKSPACE_DIR
_PLUGINS_DATA_DIR = PLUGINS_DATA_DIR
_PETS_DATA_DIR = PETS_DATA_DIR
_UPLOADS_DIR = UPLOADS_DIR

# 确保运行时数据目录存在（开发环境首次启动；生产环境由 Docker entrypoint 创建）
ensure_runtime_directories()

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
    这里显式锚定到项目根 var/data 目录，避免服务从任意工作目录启动时误连到错误的空库。
    """
    database_path = _DATA_DIR / "openawa.db"
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
    # 版本规则：0.XX，每次修复小数点后 +1；整数位保持 0（除非用户明确提升）
    VERSION: str = "0.03"
    API_V1_STR: str = "/api"
    ENVIRONMENT: str = "development"
    
    # 默认固定到 var/data/openawa.db 的绝对路径，避免受进程启动目录影响。
    DATABASE_URL: str = build_default_database_url()

    # 数据库连接池配置，可通过环境变量覆盖（DB_POOL_SIZE / DB_MAX_OVERFLOW）
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10
    
    # 三密钥独立配置：JWT 签名、CSRF 签名、Fernet 对称加密各自独立可轮换
    # 详见 apply_runtime_defaults 校验器
    # JWT 签名专用密钥（HS256），生产环境长度 >= 32
    JWT_SECRET_KEY: str = ""
    # CSRF token 签名派生专用密钥，生产环境长度 >= 32
    CSRF_SECRET_KEY: str = ""
    # Fernet 对称加密专用密钥（base64-urlsafe 32 字节格式）
    ENCRYPTION_KEY: str = ""
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
    
    # 矢量数据库路径，锚定到项目根 var/data/qdrant 绝对路径，避免工作目录不同导致路径错误
    # Qdrant 嵌入式模式使用该目录持久化数据（替代 ChromaDB）
    VECTOR_DB_PATH: str = str(_DATA_DIR / "qdrant")

    # API Key 认证配置（单用户模式）
    # 全局 API Key，未设置时启动时自动生成并写入 .env.local
    OPENAWA_API_KEY: SecretStr = SecretStr("")
    # Owner 用户名（默认 admin）
    OPENAWA_OWNER_USERNAME: str = "admin"
    # Owner 密码（未设置时自动生成，仅用于 JWT 兼容路径）
    OPENAWA_OWNER_PASSWORD: SecretStr = SecretStr("")
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
    AGENT_WORKSPACE_UNRESTRICTED_COMMANDS: bool = True

    # Agent 运行时配置
    MAX_TOOL_CALL_ROUNDS: int = 12        # 工具调用回环最大轮数
    MAX_ACTIVE_AGENT_TASKS: int = 1000    # 活跃 Agent 任务容量上限
    TOOL_EXECUTION_CACHE_SIZE: int = 256  # 工具执行幂等缓存上限
    RECORD_SEMAPHORE_SIZE: int = 20       # 并发记录任务信号量上限

    # 记忆巩固运行器配置（Spec memory-quality-and-short-term-recovery）
    # 每 N 轮对话触发一次巩固，从短期记忆中提炼高价值信息写入长期记忆
    CONSOLIDATION_CONVERSATION_THRESHOLD: int = 10
    # 单次巩固批量大小：限制单次处理的短期记忆数量，避免 LLM 上下文过长
    CONSOLIDATION_BATCH_SIZE: int = 50
    # 巩固 LLM 提炼模型（优先级：DB 默认配置 > 此处显式配置 > 空）
    # 留空时使用 PricingManager.get_default_configuration 解析的 DB 默认模型
    CONSOLIDATION_EXTRACT_PROVIDER: str = ""
    CONSOLIDATION_EXTRACT_MODEL: str = ""
    # 巩固 LLM 单次调用最大 token 数
    CONSOLIDATION_EXTRACT_MAX_TOKENS: int = 2048

    # 向量模型配置（Spec memory-model-config-chain）
    # 嵌入提供方：local（本地 sentence-transformers）| cloud（OpenAI 兼容 API）| hash（降级）| 空=自动
    MEMORY_EMBEDDING_PROVIDER: str = ""
    # 嵌入模型名（本地用 sentence-transformers 模型名，云端用 API 模型名；空=注册表默认）
    MEMORY_EMBEDDING_MODEL: str = ""
    # 云端嵌入 API 配置（OpenAI 兼容 /embeddings 接口）
    MEMORY_EMBEDDING_API_KEY: str = ""
    MEMORY_EMBEDDING_API_ENDPOINT: str = ""
    # 重排提供方：local（本地 CrossEncoder）| cloud（API）| off（关闭）
    MEMORY_RERANK_PROVIDER: str = ""
    # 重排模型名（本地用 cross-encoder 模型名，云端用 API 模型名；空=注册表默认）
    MEMORY_RERANK_MODEL: str = ""
    # 云端重排 API 配置
    MEMORY_RERANK_API_KEY: str = ""
    MEMORY_RERANK_API_ENDPOINT: str = ""
    # 模型服务独立进程（Spec 模型进程化）：本地嵌入/重排模型在独立子进程中
    # 加载推理，主进程不占用模型内存；空闲 MODEL_IDLE_UNLOAD_MINUTES 分钟自动
    # 卸载（kill 子进程），下次调用时按需重新加载。关闭时回退主进程内加载。
    MODEL_SERVICE_ENABLED: bool = True
    # 模型服务端口（0=自动分配空闲端口）
    MODEL_SERVICE_PORT: int = 0
    # 模型空闲卸载阈值（分钟，0=不自动卸载）
    MODEL_IDLE_UNLOAD_MINUTES: int = 15
    # 模型下载源：modelscope（默认，国内网络友好）| huggingface
    MODEL_DOWNLOAD_SOURCE: str = "modelscope"
    # 本地嵌入模型名（兼容旧配置 MEMORY_LOCAL_EMBEDDING_MODEL）
    MEMORY_LOCAL_EMBEDDING_MODEL: str = ""

    # 受信代理 IP/CIDR 列表，用逗号分隔。仅来自这些代理的 X-Forwarded-For / X-Real-IP 头会被信任。
    # 默认信任本地回环和私有地址段（适用于单机部署和 Docker 网络）。
    TRUSTED_PROXIES: str = "127.0.0.1,::1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"

    # ACP/Terminal 子进程允许的工作目录白名单（逗号分隔的绝对路径）。
    # 安全策略：避免任意用户指定任意路径作为子进程 cwd，从而访问受保护文件。
    # 默认允许 var/workspace 与 Open-AwA 项目根目录；可在 .env 通过 ACP_ALLOWED_WORKDIRS=path1,path2 覆盖。
    ACP_ALLOWED_WORKDIRS: str = ""

    LOG_LEVEL: str = "INFO"
    LOG_SERIALIZE: bool = True
    LOG_SERVICE_NAME: str = "openawa-backend"
    # 日志文件持久化配置，锚定到项目根 var/logs 绝对路径
    LOG_DIR: str = str(_LOG_DIR_ABS)
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

    # 熔断器配置（保护 LLM/DB 等外部依赖，防止级联故障）
    # 连续失败多少次后进入 open 状态
    LLM_CB_FAILURE_THRESHOLD: int = 5
    # open 状态持续多少秒后进入 half_open 探测
    LLM_CB_RECOVERY_TIMEOUT: float = 30.0
    # half_open 状态允许的最大探测请求数
    LLM_CB_HALF_OPEN_MAX_CALLS: int = 1

    # 数据库熔断器配置
    DB_CB_FAILURE_THRESHOLD: int = 10
    DB_CB_RECOVERY_TIMEOUT: float = 15.0
    DB_CB_HALF_OPEN_MAX_CALLS: int = 2

    experience_extraction_enabled: bool = True
    experience_retrieval_enabled: bool = True

    # 计费与模型目录同步配置
    # 计费总开关，关闭后不计算 token 用量与扣费
    ENABLE_BILLING: bool = True
    # tiktoken 开关，离线环境可关闭以避免下载编码表
    TIKTOKEN_ENABLED: bool = True
    # 模型目录定时同步开关，开启后按 MODEL_CATALOG_SYNC_CRON 定时拉取上游
    MODEL_CATALOG_SYNC_ENABLED: bool = False
    # 模型目录定时同步 cron 表达式（默认每周一 03:00 UTC）
    MODEL_CATALOG_SYNC_CRON: str = "0 3 * * 1"
    # models.dev 上游 API 地址
    MODELS_DEV_URL: str = "https://models.dev/api.json"
    # openrouter 上游 API 地址
    OPENROUTER_MODELS_URL: str = "https://openrouter.ai/api/v1/models"

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

        三密钥独立校验策略：
        - 生产环境：JWT_SECRET_KEY / CSRF_SECRET_KEY / ENCRYPTION_KEY 任一缺失或长度不足 32，
          各自独立生成一次性随机密钥保证服务可启动，并独立记录 CRITICAL 日志。
        - 开发环境：ENCRYPTION_KEY 为空时自动生成保证 Fernet 可初始化；
          JWT_SECRET_KEY / CSRF_SECRET_KEY 为空时使用固定开发默认值并记录 INFO 日志。
        """
        environment = str(self.ENVIRONMENT or "development").strip() or "development"

        if environment != self.ENVIRONMENT:
            object.__setattr__(self, "ENVIRONMENT", environment)

        if is_production_environment(environment):
            # 生产环境：三个密钥各自独立校验，互不影响
            # 安全策略：默认 fail-fast，拒绝使用自动生成的不稳定密钥启动生产服务。
            # 原因：自动生成的一次性密钥在重启后失效，会导致所有已签发 JWT/CSRF token 失效、
            # 已加密的 API Key 无法解密，且掩盖了运维未配置密钥的严重事故。
            # 若需紧急启动（如临时回滚），显式设置 ALLOW_AUTO_GENERATED_SECRETS=true。
            allow_auto = os.getenv("ALLOW_AUTO_GENERATED_SECRETS", "").lower() == "true"
            missing_keys: list[str] = []
            if not self.JWT_SECRET_KEY or len(self.JWT_SECRET_KEY) < 32:
                missing_keys.append("JWT_SECRET_KEY")
            if not self.CSRF_SECRET_KEY or len(self.CSRF_SECRET_KEY) < 32:
                missing_keys.append("CSRF_SECRET_KEY")
            if not self.ENCRYPTION_KEY or len(self.ENCRYPTION_KEY) < 32:
                missing_keys.append("ENCRYPTION_KEY")

            if missing_keys:
                msg = (
                    f"生产环境缺少或长度不足（< 32）的密钥: {', '.join(missing_keys)}。"
                    "请显式设置对应环境变量。如需紧急启动，可设置 ALLOW_AUTO_GENERATED_SECRETS=true "
                    "（不推荐，重启后所有 token 与加密数据将失效）。"
                )
                if allow_auto:
                    logger.critical(msg + " 已检测到 ALLOW_AUTO_GENERATED_SECRETS=true，将生成一次性随机密钥启动。")
                    # 延迟导入避免模块加载阶段对 cryptography 的强依赖
                    from cryptography.fernet import Fernet
                    if "JWT_SECRET_KEY" in missing_keys:
                        object.__setattr__(self, "JWT_SECRET_KEY", secrets.token_urlsafe(64))
                    if "CSRF_SECRET_KEY" in missing_keys:
                        object.__setattr__(self, "CSRF_SECRET_KEY", secrets.token_urlsafe(64))
                    if "ENCRYPTION_KEY" in missing_keys:
                        object.__setattr__(self, "ENCRYPTION_KEY", Fernet.generate_key().decode("utf-8"))
                else:
                    # 默认拒绝启动，强制运维显式配置密钥
                    raise RuntimeError(msg)
        else:
            # 开发环境：使用一次性随机密钥，避免硬编码可预测默认值
            # 历史问题：曾使用固定字符串 "openawa-dev-jwt-default-..." 等可被外部预测
            from cryptography.fernet import Fernet
            if not self.JWT_SECRET_KEY:
                object.__setattr__(self, "JWT_SECRET_KEY", secrets.token_urlsafe(64))
                logger.info(
                    "开发环境未配置 JWT_SECRET_KEY，已生成一次性随机密钥。"
                    "生产环境请显式设置 JWT_SECRET_KEY 环境变量（长度 >= 32）。"
                )
            if not self.CSRF_SECRET_KEY:
                object.__setattr__(self, "CSRF_SECRET_KEY", secrets.token_urlsafe(64))
                logger.info(
                    "开发环境未配置 CSRF_SECRET_KEY，已生成一次性随机密钥。"
                    "生产环境请显式设置 CSRF_SECRET_KEY 环境变量（长度 >= 32）。"
                )
            if not self.ENCRYPTION_KEY:
                # 开发环境使用一次性随机密钥；注意：重启后已加密数据将无法解密
                # 如需跨重启持久化，请在 .env.local 中设置 ENCRYPTION_KEY（base64-urlsafe 32 字节）
                object.__setattr__(self, "ENCRYPTION_KEY", Fernet.generate_key().decode("utf-8"))
                logger.info(
                    "开发环境未配置 ENCRYPTION_KEY，已生成一次性随机密钥（重启后已加密数据无法解密）。"
                    "生产环境请显式设置 ENCRYPTION_KEY 环境变量（base64-urlsafe 32 字节）。"
                )

        return self


settings = Settings()
