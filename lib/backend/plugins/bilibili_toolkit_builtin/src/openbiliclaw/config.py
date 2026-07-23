"""OpenBiliClaw 的配置管理。

从 TOML 文件加载配置，支持环境变量覆盖。
SchedulerConfig.enabled 是后台 LLM 循环的权威开关。
"""

from __future__ import annotations

import os
import shutil
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

if TYPE_CHECKING:
    from collections.abc import Callable

# 默认配置搜索路径
_CONFIG_FILENAMES = ["config.toml", "config.local.toml"]
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_PROJECT_ROOT_ENV = "OPENBILICLAW_PROJECT_ROOT"
_SUPPORTED_AUTH_METHODS = {"cookie", "qrcode", "none"}
_SUPPORTED_OPENAI_AUTH_MODES = {"", "api_key", "codex_oauth"}
_MIN_POOL_TARGET_COUNT = 1
_MAX_POOL_TARGET_COUNT = 600
_DEFAULT_EXTENSION_DISCONNECT_GRACE_SECONDS = 90
_DEFAULT_REFRESH_CHECK_INTERVAL_SECONDS = 60
_DEFAULT_SIGNAL_EVENT_THRESHOLD = 6
_DEFAULT_TRENDING_REFRESH_HOURS = 3
_DEFAULT_EXPLORE_REFRESH_HOURS = 12
_DEFAULT_DISCOVERY_LIMIT = 30
_DEFAULT_DELIGHT_QUEUE_LIMIT = 20
_DEFAULT_PROACTIVE_PUSH_INTERVAL_SECONDS = 120
_DEFAULT_SPECULATOR_IDLE_INTERVAL_MINUTES = 30
_DEFAULT_FEEDBACK_BATCH_THRESHOLD = 3
# 统一关键词规划器（Discover 背压重构 P1，spec §6）。
# 所有默认值都是 owner 批准的起始基线；参见
# docs/plans/2026-06-14-discover-backpressure-refactor-design.md §6 和
# docs/plans/2026-06-14-discover-backpressure-P1-plan.md §P1.0。
_DEFAULT_UNIFIED_KEYWORD_PLANNER_ENABLED = True
_DEFAULT_KW_CACHE_HIGH = 30
_DEFAULT_KW_CACHE_LOW = 10
_DEFAULT_GEN_BATCH = 30
_DEFAULT_FETCH_BATCH = 5
_DEFAULT_HISTORY_WINDOW_SIZE = 150
_DEFAULT_HISTORY_WINDOW_HOURS = 48
_DEFAULT_CLAIM_LEASE_MINUTES = 10
_DEFAULT_PLANNER_POLL_SECONDS = 120
_DEFAULT_PLAN_TTL_HOURS = 12
_DEFAULT_ADMISSION_MIN_SCORE = 0.60
_DEFAULT_MULTIMODAL_BATCH_SIZE = 8
_DEFAULT_MULTIMODAL_IMAGE_MAX_PX = 384
_DEFAULT_MULTIMODAL_IMAGE_QUALITY = 72
_DEFAULT_MULTIMODAL_IMAGE_TIMEOUT_SECONDS = 6
DEFAULT_LLM_CONCURRENCY = 3
_MIN_LLM_CONCURRENCY = 1
_MAX_LLM_CONCURRENCY = 16
_DEFAULT_LLM_TIMEOUT = 300
_MIN_LLM_TIMEOUT = 10
_DEFAULT_POOL_SOURCE_SHARES = {
    "bilibili": 5,
    "xiaohongshu": 1,
    "douyin": 1,
    "youtube": 1,
    "twitter": 1,
    "zhihu": 1,
}
_DEFAULT_AUTO_UPDATE_ALLOWED_REMOTES = [
    "https://github.com/whiteguo233/OpenBiliClaw.git",
    "git@github.com:whiteguo233/OpenBiliClaw.git",
]
_REMOTE_PROVIDER_FIELDS = {
    "openai": "llm.openai.api_key",
    "claude": "llm.claude.api_key",
    "gemini": "llm.gemini.api_key",
    "deepseek": "llm.deepseek.api_key",
    "openrouter": "llm.openrouter.api_key",
    # v0.3.32+ — 通用的 OpenAI 协议兼容 provider（Groq /
    # Together / Azure OpenAI / vLLM / 自托管 等）。与
    # ``openai`` 区分开，以便用户并行运行两者（chat = openai 用
    # gpt-5-nano，openai_compatible = Groq 用于快速 Llama 起草）。
    "openai_compatible": "llm.openai_compatible.api_key",
}


class ConfigError(ValueError):
    """运行时所需配置缺失或非法时抛出。"""


@dataclass(frozen=True)
class ConfigIssue:
    """面向用户的配置问题。"""

    field: str
    message: str
    severity: str = "warning"


@dataclass
class ConfigDiagnostics:
    """配置加载过程中收集的补充信息。"""

    config_path: Path | None = None
    created_default_config: bool = False
    messages: list[str] = field(default_factory=list)
    issues: list[ConfigIssue] = field(default_factory=list)


@dataclass
class LLMProviderConfig:
    """单个 LLM provider 的配置。"""

    api_key: str = ""
    model: str = ""
    base_url: str = ""
    auth_mode: str = ""
    http_referer: str = ""
    x_title: str = ""
    # DeepSeek v4 thinking 模式控制。"" 禁用；"high" / "max" 启用
    # 推理。v0.3.31 默认 = "max"——配合 v0.3.29 的 prompt-cache
    # 重构（system 100% 静态，DeepSeek 自动缓存 90% 关闭），
    # reasoning-token 成本变得可承受，且 LLM 产出的标签明显更好
    # （franchise_key 在批次内一致，score_threshold=0.70 仍能保持
    # 健康的池吞吐量）。若单日花费过高，可设为 "" 以标签质量换预算。
    # 不接受 ``thinking`` / ``reasoning_effort`` 的 provider 会忽略此项。
    reasoning_effort: str = "max"
    # 仅 Ollama 使用：上下文窗口（token 数）。0 = 通过 OpenAI 兼容的
    # ``/v1`` shim 使用 Ollama 服务端默认值（通常 4096）。>0 时，chat
    # 走 Ollama 原生 ``/api/chat`` 以便 ``options.num_ctx`` 真正生效——
    # ``/v1`` shim 会静默忽略该参数，截断大批量 prompt 并破坏结构化
    # JSON 输出。其他 provider 均忽略此项。参见 OllamaProvider._complete_native。
    num_ctx: int = 0


@dataclass
class EmbeddingConfig:
    """Embedding 模型配置。

    v0.3.32+ 自带 ``api_key`` / ``base_url``，使 embedding provider
    完全独立于 ``[llm].default_provider`` 和 chat 侧的
    ``[llm.<name>]`` 配置块。回退到其他 embedding provider 或 chat 侧
    凭据需通过 ``fallback_enabled`` 显式开启。
    """

    provider: str = ""  # 留空 = 在显式配置前禁用 embedding
    model: str = "gemini-embedding-001"
    api_key: str = ""
    base_url: str = ""
    output_dimensionality: int = 1024
    similarity_threshold: float = 0.82
    fallback_enabled: bool = False
    fallback_provider: str = ""


@dataclass
class ModuleLLMConfig:
    """按模块覆盖的 LLM 配置。空字符串 = 使用全局默认。"""

    provider: str = ""
    model: str = ""


@dataclass
class LLMConfig:
    """LLM 配置，包含全局默认值和按模块覆盖。"""

    default_provider: str = "deepseek"
    concurrency: int = DEFAULT_LLM_CONCURRENCY
    timeout: int = _DEFAULT_LLM_TIMEOUT
    fallback_enabled: bool = False
    fallback_provider: str = ""
    openai: LLMProviderConfig = field(default_factory=LLMProviderConfig)
    claude: LLMProviderConfig = field(default_factory=LLMProviderConfig)
    gemini: LLMProviderConfig = field(default_factory=LLMProviderConfig)
    deepseek: LLMProviderConfig = field(default_factory=LLMProviderConfig)
    ollama: LLMProviderConfig = field(default_factory=LLMProviderConfig)
    openrouter: LLMProviderConfig = field(default_factory=LLMProviderConfig)
    # v0.3.32+ 通用的 OpenAI 协议兼容 provider。始终
    # 需要显式 base_url（否则就等同于 ``openai``）。
    openai_compatible: LLMProviderConfig = field(default_factory=LLMProviderConfig)
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    # 按模块覆盖（留空 = 使用全局默认）
    soul: ModuleLLMConfig = field(default_factory=ModuleLLMConfig)
    discovery: ModuleLLMConfig = field(default_factory=ModuleLLMConfig)
    recommendation: ModuleLLMConfig = field(default_factory=ModuleLLMConfig)
    evaluation: ModuleLLMConfig = field(default_factory=ModuleLLMConfig)


def _gemini_api_key_from_env() -> str:
    """从官方环境变量返回 Gemini API key。"""
    google_api_key = os.environ.get("GOOGLE_API_KEY", "").strip()
    gemini_api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    return google_api_key or gemini_api_key


@dataclass
class BilibiliConfig:
    """Bilibili 连接配置。"""

    auth_method: str = "cookie"
    cookie: str = ""
    browser_executable: str = ""
    browser_headed: bool = False


@dataclass
class SchedulerConfig:
    """调度器配置。"""

    enabled: bool = True
    pause_on_extension_disconnect: bool = False
    extension_disconnect_grace_seconds: int = _DEFAULT_EXTENSION_DISCONNECT_GRACE_SECONDS
    discovery_cron: str = "0 */8 * * *"
    pool_target_count: int = 300
    pool_source_shares: dict[str, int] = field(
        default_factory=lambda: dict(_DEFAULT_POOL_SOURCE_SHARES)
    )
    account_sync_interval_hours: int = 6
    refresh_check_interval_seconds: int = _DEFAULT_REFRESH_CHECK_INTERVAL_SECONDS
    signal_event_threshold: int = _DEFAULT_SIGNAL_EVENT_THRESHOLD
    trending_refresh_hours: int = _DEFAULT_TRENDING_REFRESH_HOURS
    explore_refresh_hours: int = _DEFAULT_EXPLORE_REFRESH_HOURS
    discovery_limit: int = _DEFAULT_DISCOVERY_LIMIT
    delight_queue_limit: int = _DEFAULT_DELIGHT_QUEUE_LIMIT
    proactive_push_interval_seconds: int = _DEFAULT_PROACTIVE_PUSH_INTERVAL_SECONDS
    speculator_idle_interval_minutes: int = _DEFAULT_SPECULATOR_IDLE_INTERVAL_MINUTES
    # LLM 判定的喜欢/不喜欢话题合并（soul/consolidator.py）。
    # 由 pipeline tick 触发，每个 interval 至多一次；脏检查
    # 和无合并对的内存使稳态运行几乎零成本。
    profile_consolidation_enabled: bool = True
    profile_consolidation_interval_hours: int = 12
    profile_consolidation_like_target_upper: int = 512
    profile_consolidation_like_target_soft: int = 450
    profile_consolidation_archive_enabled: bool = True
    speculation_interval_minutes: int = 10
    speculation_ttl_days: int = 3
    speculation_cooldown_days: int = 7
    speculation_confirmation_threshold: int = 3
    speculation_max_active: int = 5
    speculation_max_primary_interests: int = 15
    speculation_max_secondary_interests: int = 60
    avoidance_speculation_interval_minutes: int = 10
    avoidance_speculation_ttl_days: int = 3
    avoidance_speculation_cooldown_days: int = 7
    avoidance_speculation_confirmation_threshold: int = 3
    avoidance_speculation_max_active: int = 5
    feedback_batch_threshold: int = _DEFAULT_FEEDBACK_BATCH_THRESHOLD
    # 默认关闭。自动更新器从 GitHub releases 拉取并在检测到
    # 新版本时重启后端，但历史上当本地
    # ``openbiliclaw.__version__`` 与已发布 release tag 不一致时
    # 会触发重启循环。仅 opt-in——待发布流水线稳定后在
    # config.toml 中设为 ``true``。
    auto_update_enabled: bool = False
    auto_update_check_interval_hours: int = 6
    auto_update_allow_prerelease: bool = False
    auto_update_allowed_remotes: list[str] = field(
        default_factory=lambda: list(_DEFAULT_AUTO_UPDATE_ALLOWED_REMOTES)
    )


@dataclass
class DiscoveryConfig:
    """统一关键词规划器配置（Discover 背压，P1）。

    管控双缓冲关键词存储 + 合并关键词规划器，后者取代了
    各平台独立的搜索关键词生成器。所有旋钮都由
    ``unified_keyword_planner_enabled`` 把控（v0.3.124 起默认开启；设为
    ``false`` 可逐字节回退到旧的各平台 LLM 生成路径）。参见
    ``docs/plans/2026-06-14-discover-backpressure-refactor-design.md`` §6
    中的参数表，这些默认值即来源于此。``fetch_floor`` 不是这里的
    字段——规划器复用各平台既有的 ``min_interval``。
    """

    # 主功能开关。True（默认，v0.3.124+）运行合并规划器 /
    # 关键词存储；False 回退到旧的各平台搜索关键词生成器
    # （该路径保持休眠，回退行为逐字节一致）。
    unified_keyword_planner_enabled: bool = _DEFAULT_UNIFIED_KEYWORD_PLANNER_ENABLED
    # 各平台关键词缓存高/低水位。当 pending < low 且确实存在缺口时
    # 触发生成；补充至 high。
    kw_cache_high: int = _DEFAULT_KW_CACHE_HIGH
    kw_cache_low: int = _DEFAULT_KW_CACHE_LOW
    # 每次合并 LLM 调用为每个平台生成的关键词数。
    gen_batch: int = _DEFAULT_GEN_BATCH
    # 每次获取原子性认领的关键词数。
    fetch_batch: int = _DEFAULT_FETCH_BATCH
    # 去重历史窗口：最多这么多个近期关键词、在这么多个小时内，
    # 会被作为"勿重复"提供给规划器。
    history_window_size: int = _DEFAULT_HISTORY_WINDOW_SIZE
    history_window_hours: int = _DEFAULT_HISTORY_WINDOW_HOURS
    # 认领租约：超过此时长（分钟）的已认领/执行中关键词会被回收为
    # pending（防止 loop/task 崩溃导致在途行泄漏）。
    claim_lease_minutes: int = _DEFAULT_CLAIM_LEASE_MINUTES
    # 关键词规划器轮询间隔（秒）。空闲轮询近乎零成本。
    planner_poll_seconds: int = _DEFAULT_PLANNER_POLL_SECONDS
    # 计划陈旧兜底：超过此时长（小时）的 pending 关键词会过期，
    # 即使 profile digest 未变化。
    plan_ttl_hours: int = _DEFAULT_PLAN_TTL_HOURS
    # 统一推荐池准入下限。来源/溯源元数据绝不能绕过此限制；
    # 显式策略阈值存在于 candidates 上。
    admission_min_score: float = _DEFAULT_ADMISSION_MIN_SCORE
    # 可选的封面图评估。默认关闭，因为它会改变 LLM
    # 成本/延迟，并要求评估模型具备视觉能力。
    multimodal_evaluation_enabled: bool = False
    # 携带图片的评估调用使用更小批量。
    multimodal_batch_size: int = _DEFAULT_MULTIMODAL_BATCH_SIZE
    # 发送给评估器前的封面图预处理边界。
    multimodal_image_max_px: int = _DEFAULT_MULTIMODAL_IMAGE_MAX_PX
    multimodal_image_quality: int = _DEFAULT_MULTIMODAL_IMAGE_QUALITY
    multimodal_image_timeout_seconds: int = _DEFAULT_MULTIMODAL_IMAGE_TIMEOUT_SECONDS


@dataclass
class AutostartConfig:
    """开机自启动配置。"""

    enabled: bool = False
    manage_ollama: bool = True


@dataclass
class XiaohongshuSourceConfig:
    """小红书源特定配置。

    内容发现与元数据抽取完全在用户浏览器中通过 Chrome 扩展完成
    （被动采集 + 后台标签页任务）。无需 sidecar 或后端爬取。
    """

    # 小红书是 opt-in 的，因为它需要浏览器扩展和已登录的
    # 浏览器会话。Init --yes-xhs 或设置页可在之后启用。
    enabled: bool = False
    # 后端每日可入队的 Soul 驱动搜索任务上限。
    daily_search_budget: int = 0
    # 每日创作者订阅拉取任务上限。
    daily_creator_budget: int = 0
    # 扩展分发器在任务之间的等待秒数。
    task_interval_seconds: int = 45


@dataclass
class DouyinSourceConfig:
    """抖音直连 cookie 发现配置。

    初始化引导仍使用浏览器扩展。这些设置仅控制可选的
    后端发现任务，从环境变量读取用户提供的抖音 cookie。
    """

    enabled: bool = False
    mode: str = "direct"
    cookie_env: str = "OPENBILICLAW_DOUYIN_COOKIE"
    daily_search_budget: int = 0
    daily_hot_budget: int = 0
    daily_feed_budget: int = 0
    request_interval_seconds: int = 2


@dataclass
class YoutubeSourceConfig:
    """YouTube 源特定配置。

    YouTube 稳态发现通过后端直连 runtime producer 运行。
    预算旋钮为每日执行单元设置上限：搜索查询、
    热门拉取广度、订阅频道广度。
    """

    enabled: bool = False
    daily_search_budget: int = 0
    daily_trending_budget: int = 0
    daily_channel_budget: int = 0
    request_interval_seconds: int = 2
    min_interval_minutes: int = 60


@dataclass
class TwitterSourceConfig:
    """X (Twitter) 直连 cookie 发现配置。

    稳态发现为服务端 cookie 重放（搜索 / For-You /
    创作者），镜像抖音直连路径。X producer 读取下方的
    预算 / 间隔旋钮来为三种策略限流，并将高曝光的 For-You
    feed 控制在低每日频率。``0`` 日预算表示"无每日上限"
    （每次到期运行由 runtime 缺口界定），与抖音 / YouTube
    producer 约定一致。
    """

    enabled: bool = False
    mode: str = "cookie"
    cookie_env: str = "OPENBILICLAW_X_COOKIE"
    daily_search_budget: int = 0
    daily_feed_budget: int = 0
    daily_creator_budget: int = 0
    request_interval_seconds: int = 3
    min_interval_minutes: int = 60


@dataclass
class ZhihuSourceConfig:
    """知乎插件驱动的发现配置。

    知乎发现在浏览器扩展中运行，以便复用用户已登录的
    浏览器会话。后端仅入队搜索任务并将返回的候选存入
    统一发现池。
    """

    enabled: bool = False
    source_modes: tuple[str, ...] = ("search", "hot", "feed", "creator", "related")
    daily_search_budget: int = 0
    daily_hot_budget: int = 0
    daily_feed_budget: int = 0
    daily_creator_budget: int = 0
    daily_related_budget: int = 0
    request_interval_seconds: int = 3
    min_interval_minutes: int = 60


@dataclass
class BilibiliSourceConfig:
    """Bilibili 发现源开关。"""

    enabled: bool = True


@dataclass
class SourcesConfig:
    """多源内容适配器配置。

    包含平台级发现开关以及非 Bilibili web 适配器的通用浏览器
    选项。这里的浏览器选项独立于 ``bilibili.browser``
    （后者控制 Bilibili 登录/二维码流程使用的 agent-browser CLI）。
    """

    # 预启动的 Chrome DevTools 端点 URL，例如
    # ``http://127.0.0.1:9222``。设置后，web 适配器通过
    # Playwright ``chromium.connect_over_cdp`` 连接并复用该 Chrome
    # 已登录的会话。留空则回退到 agent-browser CLI。
    browser_cdp_url: str = ""
    # 是否启动带界面的 agent-browser（仅回退路径）。
    browser_headed: bool = False
    bilibili: BilibiliSourceConfig = field(default_factory=BilibiliSourceConfig)
    xiaohongshu: XiaohongshuSourceConfig = field(default_factory=XiaohongshuSourceConfig)
    douyin: DouyinSourceConfig = field(default_factory=DouyinSourceConfig)
    youtube: YoutubeSourceConfig = field(default_factory=YoutubeSourceConfig)
    twitter: TwitterSourceConfig = field(default_factory=TwitterSourceConfig)
    zhihu: ZhihuSourceConfig = field(default_factory=ZhihuSourceConfig)


@dataclass
class StorageConfig:
    """存储配置。"""

    db_path: str = "data/openbiliclaw.db"


@dataclass
class LoggingConfig:
    """日志配置。"""

    level: str = "INFO"
    file_level: str = "DEBUG"
    directory: str = "logs"
    filename: str = "openbiliclaw.log"
    # v0.3.30+ 默认 100 MB(从 1024 降下来)。daemon 长跑场景历史 1 GB 太大,
    # 本机磁盘动辄被占几 GB。100 MB × 2 备份 = 200 MB,足够 1-2 周的 INFO 级日志。
    # 调试时可调高到 500-1024;>0 时启用轮转,设为 0 表示不轮转(仅调试用)。
    max_file_size_mb: int = 100
    # 保留的历史日志份数;至少为 1 才会真正轮转(0 会让 RotatingFileHandler 完全不轮转)。
    # 默认 1:每个 file_path 磁盘占用封顶在 `max_file_size_mb * 2`。
    backup_count: int = 1
    # v0.3.30+: ``logs/`` 目录里的 *unmanaged* 文件(start 脚本 stdout
    # redirect / 一次性 init 日志 / 旧版本残留 等)的总磁盘预算(MB)。启动
    # 时如果整个 logs/ 目录(含 unmanaged)超过这个值,从最老的 unmanaged
    # 文件开始删,直到回到预算内。设 0 关闭。默认 500 MB。
    aggregate_budget_mb: int = 500
    # 单个 unmanaged 日志文件超过这个 MB 数,启动时直接 truncate 到 0。
    # 抓 ``backend-restart.log`` 这类被脚本无限 append 但项目代码控制不到的
    # 文件。设 0 关闭。默认 200 MB。
    unmanaged_truncate_mb: int = 200
    # ``logs/`` 目录里超过这个天数的 *unmanaged* 文件,启动时直接删除。
    # 设 0 关闭。默认 30 天。
    unmanaged_max_age_days: int = 30

    @property
    def directory_path(self) -> Path:
        """解析后的日志目录路径。"""
        path = Path(self.directory)
        if not path.is_absolute():
            path = _project_root() / path
        return path

    @property
    def file_path(self) -> Path:
        """解析后的完整日志文件路径。"""
        return self.directory_path / self.filename


@dataclass
class SoulPreferenceConfig:
    """偏好层开关。

    ``satisfaction_filter_enabled``：v0.3.x 事件满意度信号——
    为 True 时，偏好分析器忽略被动负向事件（如快速退出），
    但保留显式不喜欢反馈作为 disliked_topics 证据。
    """

    satisfaction_filter_enabled: bool = True


@dataclass
class SoulConfig:
    """Soul 引擎旋钮。当前仅包含 preference 子段。"""

    preference: SoulPreferenceConfig = field(default_factory=SoulPreferenceConfig)


@dataclass
class ApiAuthConfig:
    """可选的局域网/远程访问密码门禁（参见
    ``docs/plans/2026-05-30-web-password-auth-design.md``）。

    仅当 ``enabled`` 为 true *且* 请求不是可信本地请求
    （无 forwarding 头的回环，参见 §4.1）时生效。
    ``session_secret`` 在首次启用时自动生成。吊销纪元
    （``auth_epoch``）和密码指纹存于 SQLite，不在此处（§4.7）。
    """

    enabled: bool = False
    password_hash: str = ""
    session_secret: str = ""
    session_ttl_hours: int = 0
    trust_loopback: bool = True
    trusted_proxies: list[str] = field(default_factory=list)
    allowed_bearer_origins: list[str] = field(default_factory=list)


@dataclass
class ApiConfig:
    """后端 API 服务器设置。

    ``host`` 控制服务器绑定到哪个网络接口。
    ``0.0.0.0``（默认）绑定所有接口，以便同局域网的移动设备
    可访问 ``/m/`` 移动端网页。``127.0.0.1`` 仅限本机访问。
    """

    host: str = "0.0.0.0"
    port: int = 8420
    auth: ApiAuthConfig = field(default_factory=ApiAuthConfig)


@dataclass
class Config:
    """OpenBiliClaw 的根配置。"""

    language: str = "zh"
    data_dir: str = "data"
    api: ApiConfig = field(default_factory=ApiConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    bilibili: BilibiliConfig = field(default_factory=BilibiliConfig)
    sources: SourcesConfig = field(default_factory=SourcesConfig)
    scheduler: SchedulerConfig = field(default_factory=SchedulerConfig)
    # 顶层 ``[discovery]`` 承载统一关键词规划器 / 背压
    # 旋钮（P1）。与 ``[llm.discovery]``（按模块 provider 覆盖）不同。
    discovery: DiscoveryConfig = field(default_factory=DiscoveryConfig)
    autostart: AutostartConfig = field(default_factory=AutostartConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    # 顶层 ``[soul]`` 与 ``[llm.soul]``（按模块
    # provider 覆盖）不同：此处承载 soul 引擎行为开关。
    soul: SoulConfig = field(default_factory=SoulConfig)

    @property
    def data_path(self) -> Path:
        """解析后的数据目录路径。"""
        p = Path(self.data_dir)
        if not p.is_absolute():
            p = _project_root() / p
        return p


def _project_root() -> Path:
    """返回用于配置、数据和日志的运行时项目根目录。"""
    env_root = os.environ.get(_PROJECT_ROOT_ENV, "").strip()
    if env_root:
        return Path(env_root).expanduser().resolve()

    if _looks_like_project_root(_PROJECT_ROOT):
        return _PROJECT_ROOT

    cwd = Path.cwd().resolve()
    if any((cwd / filename).exists() for filename in [*_CONFIG_FILENAMES, "config.example.toml"]):
        return cwd

    return _PROJECT_ROOT


def _looks_like_project_root(path: Path) -> bool:
    """判断路径是否类似于仓库/运行时根目录。"""
    return any(
        (path / marker).exists()
        for marker in ["pyproject.toml", "config.example.toml", "config.toml"]
    )


def _default_config_path() -> Path:
    """返回默认的 config.toml 路径。"""
    return _project_root() / "config.toml"


def _config_example_path() -> Path:
    """返回仓库的配置示例路径。"""
    return _project_root() / "config.example.toml"


def _ensure_default_config_file(diagnostics: ConfigDiagnostics) -> None:
    """当 config.toml 缺失时从示例文件创建。"""
    config_path = _default_config_path()
    diagnostics.config_path = config_path

    if config_path.exists():
        return

    example_path = _config_example_path()
    if not example_path.exists():
        diagnostics.messages.append(
            "未检测到 config.toml，且缺少 config.example.toml，当前使用内置默认配置。"
        )
        return

    shutil.copyfile(example_path, config_path)
    diagnostics.created_default_config = True
    diagnostics.messages.append(f"未检测到 config.toml，已自动生成模板文件：{config_path}。")


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """深度合并两个字典，override 中的值优先。"""
    merged = base.copy()
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _apply_env_overrides(raw: dict[str, Any]) -> dict[str, Any]:
    """应用环境变量覆盖。

    环境变量遵循如下模式：OPENBILICLAW_SECTION_KEY
    例如 OPENBILICLAW_LLM_DEFAULT_PROVIDER=claude
    """
    prefix = "OPENBILICLAW_"
    for env_key, env_value in os.environ.items():
        if not env_key.startswith(prefix):
            continue
        # Auth 变量是多词的（PASSWORD_HASH、SESSION_TTL_HOURS ……）；朴素的
        # ``_`` 切分会把它们错误嵌套——例如 PASSWORD_HASH → api.auth.password.hash，
        # 会在 auth.password 处注入一个 dict（后续按其 repr 哈希），
        # 或在磁盘上存在明文 `password` 字符串时深入访问而抛 TypeError。
        # `_build_api_auth` 显式读取每个 API_AUTH_ENV_VARS 变量，因此这里
        # 完全跳过它们（评审 r7#1）。
        if env_key in API_AUTH_ENV_VARS:
            continue
        parts = env_key[len(prefix) :].lower().split("_")
        current = raw
        for part in parts[:-1]:
            current = current.setdefault(part, {})
        current[parts[-1]] = env_value
    return raw


def _build_config(raw: dict[str, Any]) -> Config:
    """从原始 dict 构建 Config dataclass。"""
    general = raw.get("general", {})
    api_raw = raw.get("api", {}) if isinstance(raw.get("api"), dict) else {}
    llm_raw = raw.get("llm", {})
    bili_raw = raw.get("bilibili", {})
    sources_raw = raw.get("sources", {})
    sched_raw = dict(raw.get("scheduler", {}))
    discovery_raw = raw.get("discovery", {})
    if not isinstance(discovery_raw, dict):
        discovery_raw = {}
    autostart_raw = raw.get("autostart", {})
    if not isinstance(autostart_raw, dict):
        autostart_raw = {}
    store_raw = raw.get("storage", {})
    logging_raw = raw.get("logging", {})

    embedding_raw = llm_raw.get("embedding", {})
    llm = LLMConfig(
        default_provider=llm_raw.get("default_provider", "deepseek"),
        concurrency=_normalize_llm_concurrency(llm_raw.get("concurrency")),
        timeout=_normalize_llm_timeout(llm_raw.get("timeout")),
        fallback_enabled=bool(llm_raw.get("fallback_enabled", False)),
        fallback_provider=llm_raw.get("fallback_provider", ""),
        openai=LLMProviderConfig(**llm_raw.get("openai", {})),
        claude=LLMProviderConfig(**llm_raw.get("claude", {})),
        gemini=LLMProviderConfig(**llm_raw.get("gemini", {})),
        deepseek=LLMProviderConfig(**llm_raw.get("deepseek", {})),
        ollama=LLMProviderConfig(**llm_raw.get("ollama", {})),
        openrouter=LLMProviderConfig(**llm_raw.get("openrouter", {})),
        openai_compatible=LLMProviderConfig(**llm_raw.get("openai_compatible", {})),
        embedding=EmbeddingConfig(
            **{
                k: v
                for k, v in embedding_raw.items()
                if k
                in (
                    "provider",
                    "model",
                    "api_key",
                    "base_url",
                    "output_dimensionality",
                    "similarity_threshold",
                    "fallback_enabled",
                    "fallback_provider",
                )
            }
        ),
        soul=ModuleLLMConfig(
            **{k: v for k, v in llm_raw.get("soul", {}).items() if k in ("provider", "model")}
        ),
        discovery=ModuleLLMConfig(
            **{k: v for k, v in llm_raw.get("discovery", {}).items() if k in ("provider", "model")}
        ),
        recommendation=ModuleLLMConfig(
            **{
                k: v
                for k, v in llm_raw.get("recommendation", {}).items()
                if k in ("provider", "model")
            }
        ),
        evaluation=ModuleLLMConfig(
            **{k: v for k, v in llm_raw.get("evaluation", {}).items() if k in ("provider", "model")}
        ),
    )

    browser_raw = bili_raw.pop("browser", {})
    bilibili = BilibiliConfig(
        auth_method=bili_raw.get("auth_method", "cookie"),
        cookie=bili_raw.get("cookie", ""),
        browser_executable=browser_raw.get("executable", ""),
        browser_headed=browser_raw.get("headed", False),
    )

    sources_browser_raw = sources_raw.get("browser", {})
    bilibili_source_raw = sources_raw.get("bilibili", {})
    xhs_raw = sources_raw.get("xiaohongshu", {})
    douyin_raw = sources_raw.get("douyin", {})
    youtube_raw = sources_raw.get("youtube", {})
    twitter_raw = sources_raw.get("twitter", {})
    zhihu_raw = sources_raw.get("zhihu", {})
    sources = SourcesConfig(
        browser_cdp_url=sources_browser_raw.get("cdp_url", ""),
        browser_headed=sources_browser_raw.get("headed", False),
        bilibili=BilibiliSourceConfig(
            enabled=bool(bilibili_source_raw.get("enabled", True)),
        ),
        xiaohongshu=XiaohongshuSourceConfig(
            enabled=bool(xhs_raw.get("enabled", False)),
            daily_search_budget=int(xhs_raw.get("daily_search_budget", 0)),
            daily_creator_budget=int(xhs_raw.get("daily_creator_budget", 0)),
            task_interval_seconds=int(xhs_raw.get("task_interval_seconds", 45)),
        ),
        douyin=DouyinSourceConfig(
            enabled=bool(douyin_raw.get("enabled", False)),
            mode=str(douyin_raw.get("mode", "direct")),
            cookie_env=str(douyin_raw.get("cookie_env", "OPENBILICLAW_DOUYIN_COOKIE")),
            daily_search_budget=int(douyin_raw.get("daily_search_budget", 0)),
            daily_hot_budget=int(douyin_raw.get("daily_hot_budget", 0)),
            daily_feed_budget=int(douyin_raw.get("daily_feed_budget", 0)),
            request_interval_seconds=int(douyin_raw.get("request_interval_seconds", 2)),
        ),
        youtube=YoutubeSourceConfig(
            enabled=bool(youtube_raw.get("enabled", False)),
            daily_search_budget=int(youtube_raw.get("daily_search_budget", 0)),
            daily_trending_budget=int(youtube_raw.get("daily_trending_budget", 0)),
            daily_channel_budget=int(youtube_raw.get("daily_channel_budget", 0)),
            request_interval_seconds=int(youtube_raw.get("request_interval_seconds", 2)),
            min_interval_minutes=max(0, int(youtube_raw.get("min_interval_minutes", 60))),
        ),
        twitter=TwitterSourceConfig(
            enabled=bool(twitter_raw.get("enabled", False)),
            mode=str(twitter_raw.get("mode", "cookie")),
            cookie_env=str(twitter_raw.get("cookie_env", "OPENBILICLAW_X_COOKIE")),
            daily_search_budget=int(twitter_raw.get("daily_search_budget", 0)),
            daily_feed_budget=int(twitter_raw.get("daily_feed_budget", 0)),
            daily_creator_budget=int(twitter_raw.get("daily_creator_budget", 0)),
            request_interval_seconds=int(twitter_raw.get("request_interval_seconds", 3)),
            min_interval_minutes=max(0, int(twitter_raw.get("min_interval_minutes", 60))),
        ),
        zhihu=ZhihuSourceConfig(
            enabled=bool(zhihu_raw.get("enabled", False)),
            source_modes=tuple(
                mode
                for mode in _coerce_str_list(
                    zhihu_raw.get("source_modes", ["search", "hot", "feed", "creator", "related"])
                )
                if mode in {"search", "hot", "feed", "creator", "related"}
            )
            or ("search",),
            daily_search_budget=int(zhihu_raw.get("daily_search_budget", 0)),
            daily_hot_budget=int(zhihu_raw.get("daily_hot_budget", 0)),
            daily_feed_budget=int(zhihu_raw.get("daily_feed_budget", 0)),
            daily_creator_budget=int(zhihu_raw.get("daily_creator_budget", 0)),
            daily_related_budget=int(zhihu_raw.get("daily_related_budget", 0)),
            request_interval_seconds=int(zhihu_raw.get("request_interval_seconds", 3)),
            min_interval_minutes=max(0, int(zhihu_raw.get("min_interval_minutes", 60))),
        ),
    )

    soul_raw = raw.get("soul", {}) if isinstance(raw.get("soul"), dict) else {}
    soul_preference_raw = (
        soul_raw.get("preference", {}) if isinstance(soul_raw.get("preference"), dict) else {}
    )
    soul = SoulConfig(
        preference=SoulPreferenceConfig(
            satisfaction_filter_enabled=bool(
                soul_preference_raw.get("satisfaction_filter_enabled", True)
            ),
        ),
    )

    api_auth = _build_api_auth(api_raw)

    return Config(
        language=general.get("language", "zh"),
        data_dir=general.get("data_dir", "data"),
        api=ApiConfig(
            host=str(api_raw.get("host", "0.0.0.0") or "0.0.0.0").strip() or "0.0.0.0",
            port=_normalize_api_port(api_raw.get("port", 8420)),
            auth=api_auth,
        ),
        llm=llm,
        bilibili=bilibili,
        sources=sources,
        scheduler=SchedulerConfig(
            **{
                **sched_raw,
                "extension_disconnect_grace_seconds": _normalize_extension_disconnect_grace(
                    sched_raw.get("extension_disconnect_grace_seconds")
                ),
                "pool_source_shares": _normalize_pool_source_shares(
                    sched_raw.get("pool_source_shares")
                ),
                "refresh_check_interval_seconds": _normalize_scheduler_int(
                    sched_raw.get("refresh_check_interval_seconds"),
                    default=_DEFAULT_REFRESH_CHECK_INTERVAL_SECONDS,
                    min_value=15,
                ),
                "signal_event_threshold": _normalize_scheduler_int(
                    sched_raw.get("signal_event_threshold"),
                    default=_DEFAULT_SIGNAL_EVENT_THRESHOLD,
                    min_value=1,
                ),
                "trending_refresh_hours": _normalize_scheduler_int(
                    sched_raw.get("trending_refresh_hours"),
                    default=_DEFAULT_TRENDING_REFRESH_HOURS,
                    min_value=1,
                ),
                "explore_refresh_hours": _normalize_scheduler_int(
                    sched_raw.get("explore_refresh_hours"),
                    default=_DEFAULT_EXPLORE_REFRESH_HOURS,
                    min_value=1,
                ),
                "discovery_limit": _normalize_scheduler_int(
                    sched_raw.get("discovery_limit"),
                    default=_DEFAULT_DISCOVERY_LIMIT,
                    min_value=1,
                    max_value=60,
                ),
                "delight_queue_limit": _normalize_scheduler_int(
                    sched_raw.get("delight_queue_limit"),
                    default=_DEFAULT_DELIGHT_QUEUE_LIMIT,
                    min_value=1,
                    max_value=100,
                ),
                "proactive_push_interval_seconds": _normalize_scheduler_int(
                    sched_raw.get("proactive_push_interval_seconds"),
                    default=_DEFAULT_PROACTIVE_PUSH_INTERVAL_SECONDS,
                    min_value=30,
                ),
                "speculator_idle_interval_minutes": _normalize_scheduler_int(
                    sched_raw.get("speculator_idle_interval_minutes"),
                    default=_DEFAULT_SPECULATOR_IDLE_INTERVAL_MINUTES,
                    min_value=5,
                ),
                "profile_consolidation_interval_hours": _normalize_scheduler_int(
                    sched_raw.get("profile_consolidation_interval_hours"),
                    default=12,
                    min_value=1,
                ),
                "profile_consolidation_like_target_upper": _normalize_scheduler_int(
                    sched_raw.get("profile_consolidation_like_target_upper"),
                    default=512,
                    min_value=1,
                ),
                "profile_consolidation_like_target_soft": _normalize_scheduler_int(
                    sched_raw.get("profile_consolidation_like_target_soft"),
                    default=450,
                    min_value=1,
                ),
                "profile_consolidation_archive_enabled": _coerce_bool(
                    sched_raw.get("profile_consolidation_archive_enabled"),
                    default=True,
                ),
                "avoidance_speculation_interval_minutes": _normalize_scheduler_int(
                    sched_raw.get("avoidance_speculation_interval_minutes"),
                    default=10,
                    min_value=1,
                ),
                "avoidance_speculation_ttl_days": _normalize_scheduler_int(
                    sched_raw.get("avoidance_speculation_ttl_days"),
                    default=3,
                    min_value=1,
                ),
                "avoidance_speculation_cooldown_days": _normalize_scheduler_int(
                    sched_raw.get("avoidance_speculation_cooldown_days"),
                    default=7,
                    min_value=1,
                ),
                "avoidance_speculation_confirmation_threshold": _normalize_scheduler_int(
                    sched_raw.get("avoidance_speculation_confirmation_threshold"),
                    default=3,
                    min_value=1,
                ),
                "avoidance_speculation_max_active": _normalize_scheduler_int(
                    sched_raw.get("avoidance_speculation_max_active"),
                    default=5,
                    min_value=1,
                ),
                "auto_update_allowed_remotes": _normalize_auto_update_allowed_remotes(
                    sched_raw.get("auto_update_allowed_remotes")
                ),
            }
        ),
        discovery=_build_discovery(discovery_raw),
        autostart=AutostartConfig(
            enabled=_coerce_bool(autostart_raw.get("enabled"), default=False),
            manage_ollama=_coerce_bool(autostart_raw.get("manage_ollama"), default=True),
        ),
        storage=StorageConfig(**store_raw),
        logging=LoggingConfig(**logging_raw),
        soul=soul,
    )


def _build_discovery(discovery_raw: dict[str, Any]) -> DiscoveryConfig:
    """从原始 ``[discovery]`` 表组装 ``DiscoveryConfig``。

    每个数值旋钮都经过 ``_normalize_scheduler_int``（与 scheduler 字段
    使用的有界正整数强制转换相同），因此非法 / 缺失 / 越界的值会回退
    到 spec §6 默认值。``_coerce_bool`` 处理功能开关，这意味着
    环境字符串覆盖（``OPENBILICLAW_DISCOVERY_*``）与 TOML 值的规范化
    方式完全一致。
    """
    return DiscoveryConfig(
        unified_keyword_planner_enabled=_coerce_bool(
            discovery_raw.get("unified_keyword_planner_enabled"),
            default=_DEFAULT_UNIFIED_KEYWORD_PLANNER_ENABLED,
        ),
        kw_cache_high=_normalize_scheduler_int(
            discovery_raw.get("kw_cache_high"),
            default=_DEFAULT_KW_CACHE_HIGH,
            min_value=1,
        ),
        kw_cache_low=_normalize_scheduler_int(
            discovery_raw.get("kw_cache_low"),
            default=_DEFAULT_KW_CACHE_LOW,
            min_value=1,
        ),
        gen_batch=_normalize_scheduler_int(
            discovery_raw.get("gen_batch"),
            default=_DEFAULT_GEN_BATCH,
            min_value=1,
        ),
        fetch_batch=_normalize_scheduler_int(
            discovery_raw.get("fetch_batch"),
            default=_DEFAULT_FETCH_BATCH,
            min_value=1,
        ),
        history_window_size=_normalize_scheduler_int(
            discovery_raw.get("history_window_size"),
            default=_DEFAULT_HISTORY_WINDOW_SIZE,
            min_value=1,
        ),
        history_window_hours=_normalize_scheduler_int(
            discovery_raw.get("history_window_hours"),
            default=_DEFAULT_HISTORY_WINDOW_HOURS,
            min_value=1,
        ),
        claim_lease_minutes=_normalize_scheduler_int(
            discovery_raw.get("claim_lease_minutes"),
            default=_DEFAULT_CLAIM_LEASE_MINUTES,
            min_value=1,
        ),
        planner_poll_seconds=_normalize_scheduler_int(
            discovery_raw.get("planner_poll_seconds"),
            default=_DEFAULT_PLANNER_POLL_SECONDS,
            min_value=1,
        ),
        plan_ttl_hours=_normalize_scheduler_int(
            discovery_raw.get("plan_ttl_hours"),
            default=_DEFAULT_PLAN_TTL_HOURS,
            min_value=1,
        ),
        admission_min_score=_normalize_probability(
            discovery_raw.get("admission_min_score"),
            default=_DEFAULT_ADMISSION_MIN_SCORE,
        ),
        multimodal_evaluation_enabled=_coerce_bool(
            discovery_raw.get("multimodal_evaluation_enabled"),
            default=False,
        ),
        multimodal_batch_size=_normalize_scheduler_int(
            discovery_raw.get("multimodal_batch_size"),
            default=_DEFAULT_MULTIMODAL_BATCH_SIZE,
            min_value=1,
            max_value=12,
        ),
        multimodal_image_max_px=_normalize_scheduler_int(
            discovery_raw.get("multimodal_image_max_px"),
            default=_DEFAULT_MULTIMODAL_IMAGE_MAX_PX,
            min_value=128,
            max_value=768,
        ),
        multimodal_image_quality=_normalize_scheduler_int(
            discovery_raw.get("multimodal_image_quality"),
            default=_DEFAULT_MULTIMODAL_IMAGE_QUALITY,
            min_value=40,
            max_value=90,
        ),
        multimodal_image_timeout_seconds=_normalize_scheduler_int(
            discovery_raw.get("multimodal_image_timeout_seconds"),
            default=_DEFAULT_MULTIMODAL_IMAGE_TIMEOUT_SECONDS,
            min_value=1,
            max_value=20,
        ),
    )


def _normalize_probability(value: object, *, default: float) -> float:
    """将 TOML 概率值规范化到开区间 ``(0, 1]``。"""
    if isinstance(value, bool):
        return default
    if not isinstance(value, (int, float, str)):
        return default
    try:
        score = float(value)
    except (TypeError, ValueError):
        return default
    if score <= 0.0 or score > 1.0:
        return default
    return score


def _coerce_bool(value: object, *, default: bool = False) -> bool:
    """将 TOML/env 值强制转换为 bool。env 值以字符串形式传入。"""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ("1", "true", "yes", "on"):
            return True
        if text in ("0", "false", "no", "off", ""):
            return False
        return default
    if isinstance(value, int | float):
        return bool(value)
    return default


def _coerce_ttl_hours(value: object) -> int:
    """将会话 TTL（TOML int/float 或 env 字符串）强制转换为非负
    int，缺失或格式非法时回退为 0。

    由 ``_build_api_auth``（加载）和 ``_api_auth_lines``（env 管理
    保存时保留）共享，因此被保留的磁盘值能往返还原为加载器计算出的
    完全一致的结果。
    """
    if isinstance(value, int | float):  # bool 是 int 子类：int(True) == 1
        try:
            return max(0, int(value))  # int(nan) → ValueError, int(inf) → OverflowError
        except (ValueError, OverflowError):
            return 0
    if isinstance(value, str):
        try:
            return max(0, int(value.strip()))
        except ValueError:
            return 0
    return 0


def config_local_auth_keys() -> set[str]:
    """固定在 ``config.local.toml`` 中的 ``[api.auth]`` 键（``load_config``
    会把该层覆盖合并到 ``config.toml`` 之上，local 优先）。

    写入 ``config.toml``（admin endpoint / ``set-password``）无法改变
    被 ``config.local.toml`` 遮蔽的字段——该值在下次重启时会静默回退。
    调用方据此显式拒绝此类写入，而非报告虚假成功（评审 r9）。
    当无 local 文件或无 ``[api.auth]`` 段时返回空集。
    """
    local = _project_root() / "config.local.toml"
    if not local.exists():
        return set()
    try:
        with local.open("rb") as handle:
            data = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        return set()
    api = data.get("api")
    auth = api.get("auth") if isinstance(api, dict) else None
    return set(auth) if isinstance(auth, dict) else set()


def _hash_matches_plaintext(plaintext: object, password_hash: str) -> bool:
    """当且仅当 ``password_hash`` 是 ``plaintext`` 的 scrypt 哈希时返回 True。

    用于保存时判断磁盘上的明文 ``password`` 键是否仍代表当前凭据
    （若是则原样保留，保持 reconcile 指纹基稳定），还是在内存中被
    故意修改（若是则必须丢弃陈旧明文以适配新哈希）。防御性：格式
    非法的哈希绝不抛异常，仅视为"不匹配" → 写入该哈希。
    """
    text = str(plaintext) if plaintext is not None else ""
    if not text.strip() or not password_hash.strip():
        return False
    from openbiliclaw.auth_core import verify_password

    try:
        return verify_password(text, password_hash)
    except Exception:
        return False


def _coerce_str_list(value: object) -> list[str]:
    """将 TOML 列表（或逗号分隔字符串）强制转换为干净的列表。"""
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


# 单一权威来源：``_build_api_auth`` 为 ``[api.auth]`` 而认可的所有 env 变量。
# 门禁的 "env-managed" 守卫（api/auth.py）会导入此项，因此对
# 每一个 env 覆盖会重启后静默夺回的字段，配置文件编辑（CLI / 本地 admin
# endpoint）都会被拒绝——而不仅仅是 password。下方新增 override 必须同步
# 增加此处的名称；``test_config`` 强制校验。
API_AUTH_ENV_VARS: tuple[str, ...] = (
    "OPENBILICLAW_API_AUTH_PASSWORD",
    "OPENBILICLAW_API_AUTH_PASSWORD_HASH",
    "OPENBILICLAW_API_AUTH_ENABLED",
    "OPENBILICLAW_API_AUTH_SESSION_SECRET",
    "OPENBILICLAW_API_AUTH_SESSION_TTL_HOURS",
    "OPENBILICLAW_API_AUTH_TRUST_LOOPBACK",
)


def _build_api_auth(api_raw: dict[str, Any]) -> ApiAuthConfig:
    """从原始配置 + 专用 env 变量组装 ``ApiAuthConfig``。

    多词字段无法使用通用的 ``OPENBILICLAW_A_B_C`` 覆盖
    （它按 ``_`` 切分），因此安全敏感字段在此显式读取。
    参见 ``docs/plans/2026-05-30-web-password-auth-design.md`` §5.2。
    此处读取的变量集合由上方的 ``API_AUTH_ENV_VARS`` 镜像。
    """
    from openbiliclaw.auth_core import hash_password

    raw = api_raw.get("auth", {})
    auth_raw: dict[str, Any] = raw if isinstance(raw, dict) else {}

    def _env(name: str) -> str | None:
        value = os.environ.get(name)
        return value if value and value.strip() else None

    # 显式凭据优先级（评审 r7#1）：
    #   env PASSWORD > env PASSWORD_HASH > 磁盘明文 password > 磁盘 hash。
    # 高优先级来源会完全遮蔽低优先级来源，因此 env hash 轮换
    # 绝不会被陈旧的磁盘明文 password 覆盖。
    env_plain = _env("OPENBILICLAW_API_AUTH_PASSWORD")
    env_hash = _env("OPENBILICLAW_API_AUTH_PASSWORD_HASH")
    disk_plain = auth_raw.get("password")
    if env_plain:
        password_hash = hash_password(env_plain)
    elif env_hash:
        password_hash = env_hash
    elif disk_plain and str(disk_plain).strip():
        password_hash = hash_password(str(disk_plain))
    else:
        password_hash = str(auth_raw.get("password_hash", ""))

    ttl_raw = _env("OPENBILICLAW_API_AUTH_SESSION_TTL_HOURS")
    if ttl_raw is None:
        ttl_raw = auth_raw.get("session_ttl_hours", 0)
    session_ttl_hours = _coerce_ttl_hours(ttl_raw)

    return ApiAuthConfig(
        enabled=_coerce_bool(
            _env("OPENBILICLAW_API_AUTH_ENABLED") or auth_raw.get("enabled", False)
        ),
        password_hash=password_hash,
        session_secret=(
            _env("OPENBILICLAW_API_AUTH_SESSION_SECRET") or str(auth_raw.get("session_secret", ""))
        ),
        session_ttl_hours=session_ttl_hours,
        trust_loopback=_coerce_bool(
            _env("OPENBILICLAW_API_AUTH_TRUST_LOOPBACK") or auth_raw.get("trust_loopback", True),
            default=True,
        ),
        trusted_proxies=_coerce_str_list(auth_raw.get("trusted_proxies", [])),
        allowed_bearer_origins=_coerce_str_list(auth_raw.get("allowed_bearer_origins", [])),
    )


def get_auth_plain_password() -> str | None:
    """返回明文 auth 密码（env 优先，其次配置文件）。

    供启动指纹 reconcile（§4.7）使用：指纹必须基于*稳定*凭据材料
    派生，而非新加盐的 scrypt 哈希，否则未变更的密码在每次重启时
    都会错误地吊销会话。无论明文来自 ``OPENBILICLAW_API_AUTH_PASSWORD``
    （Docker/env）还是 config.toml 中的 ``[api.auth].password`` 行，
    跨重启都是稳定的。当仅使用持久化的 hash 时返回 ``None``
    （此时 hash 字符串本身即为稳定的指纹材料）。
    """
    env_value = os.environ.get("OPENBILICLAW_API_AUTH_PASSWORD")
    if env_value and env_value.strip():
        return env_value
    # 当一个 env PASSWORD_HASH 管控凭据时（且无 env PASSWORD），不存在
    # 稳定的明文——生效密码是 env hash，它优先于任何磁盘明文
    # （见 _build_api_auth 优先级）。返回 None 以便 reconcile 指纹由
    # "ph:"+hash 派生，而非来自已失效的磁盘明文（评审 r7#1）。
    env_hash = os.environ.get("OPENBILICLAW_API_AUTH_PASSWORD_HASH")
    if env_hash and env_hash.strip():
        return None
    # 回退到 config.toml 中持久化的明文密码，使该路径同样指纹稳定
    # （评审 r1#3）。
    try:
        raw: dict[str, Any] = {}
        for filename in _CONFIG_FILENAMES:
            path = _project_root() / filename
            if path.exists():
                with open(path, "rb") as f:
                    raw = _deep_merge(raw, tomllib.load(f))
        api = raw.get("api", {})
        auth = api.get("auth", {}) if isinstance(api, dict) else {}
        value = auth.get("password") if isinstance(auth, dict) else None
        return str(value) if value and str(value).strip() else None
    except Exception:
        return None


def _normalize_api_port(value: object) -> int:
    """将 API 端口值规范化到有效 TCP 端口范围。"""
    if isinstance(value, bool):
        return 8420
    if isinstance(value, int | float):
        port = int(value)
    elif isinstance(value, str):
        try:
            port = int(value.strip())
        except ValueError:
            return 8420
    else:
        return 8420
    return port if 1 <= port <= 65535 else 8420


def _normalize_llm_concurrency(value: object) -> int:
    """规范化共享 LLM 请求并发上限。"""
    if isinstance(value, bool):
        return DEFAULT_LLM_CONCURRENCY
    if isinstance(value, int | float):
        normalized = int(value)
    elif isinstance(value, str):
        try:
            normalized = int(value.strip())
        except ValueError:
            return DEFAULT_LLM_CONCURRENCY
    else:
        return DEFAULT_LLM_CONCURRENCY

    if not (_MIN_LLM_CONCURRENCY <= normalized <= _MAX_LLM_CONCURRENCY):
        return DEFAULT_LLM_CONCURRENCY
    return normalized


def _normalize_llm_timeout(value: object) -> int:
    """规范化 LLM 请求超时（秒）。"""
    if isinstance(value, bool):
        return _DEFAULT_LLM_TIMEOUT
    if isinstance(value, int | float):
        normalized = int(value)
    elif isinstance(value, str):
        try:
            normalized = int(value.strip())
        except ValueError:
            return _DEFAULT_LLM_TIMEOUT
    else:
        return _DEFAULT_LLM_TIMEOUT

    if normalized < _MIN_LLM_TIMEOUT:
        return _DEFAULT_LLM_TIMEOUT
    return normalized


def llm_concurrency_from_config(config: object) -> int:
    """从 config 对象提取 LLM 并发数，带有安全回退。

    同时兼容完整的 ``Config`` 实例和裸
    ``types.SimpleNamespace``（供测试桩和热重载路径使用）。
    """
    llm_section = getattr(config, "llm", None)
    raw = getattr(llm_section, "concurrency", DEFAULT_LLM_CONCURRENCY)
    return _normalize_llm_concurrency(raw)


def _normalize_pool_source_shares(value: object) -> dict[str, int]:
    """将 TOML 中的调度器池来源份额规范化为正整数。"""
    if not isinstance(value, dict):
        return dict(_DEFAULT_POOL_SOURCE_SHARES)

    shares: dict[str, int] = dict(_DEFAULT_POOL_SOURCE_SHARES)
    for key, raw_share in value.items():
        source = str(key).strip().lower()
        if not source:
            continue
        try:
            share = int(raw_share)
        except (TypeError, ValueError):
            continue
        if share <= 0:
            continue
        shares[source] = share
    return shares or dict(_DEFAULT_POOL_SOURCE_SHARES)


def _normalize_extension_disconnect_grace(value: object) -> int:
    """将扩展断连宽限期（秒）规范化为正整数。"""
    if isinstance(value, int | float):
        grace = int(value)
    elif isinstance(value, str):
        try:
            grace = int(value.strip())
        except ValueError:
            return _DEFAULT_EXTENSION_DISCONNECT_GRACE_SECONDS
    else:
        return _DEFAULT_EXTENSION_DISCONNECT_GRACE_SECONDS

    if grace <= 0:
        return _DEFAULT_EXTENSION_DISCONNECT_GRACE_SECONDS
    return grace


def _normalize_scheduler_int(
    value: object,
    *,
    default: int,
    min_value: int,
    max_value: int | None = None,
) -> int:
    """将调度器调优值规范化为有界正整数。"""
    if isinstance(value, int | float):
        normalized = int(value)
    elif isinstance(value, str):
        try:
            normalized = int(value.strip())
        except ValueError:
            return default
    else:
        return default

    if normalized < min_value:
        return default
    if max_value is not None and normalized > max_value:
        return default
    return normalized


def _normalize_auto_update_allowed_remotes(value: object) -> list[str]:
    """将自动更新远程白名单规范化为非空字符串 URL 列表。"""
    if not isinstance(value, list):
        return list(_DEFAULT_AUTO_UPDATE_ALLOWED_REMOTES)
    remotes = [str(item).strip() for item in value if str(item).strip()]
    return remotes or list(_DEFAULT_AUTO_UPDATE_ALLOWED_REMOTES)


def _collect_config_issues(config: Config) -> list[ConfigIssue]:
    """收集非致命配置问题，作为指引展示。"""
    issues: list[ConfigIssue] = []

    if config.api.auth.enabled and not config.api.auth.password_hash.strip():
        issues.append(
            ConfigIssue(
                field="api.auth.password_hash",
                message=(
                    "已开启 `api.auth.enabled` 但未设置密码。"
                    "请用 `openbiliclaw set-password` 设置，或关闭门禁。"
                ),
                severity="blocking",
            )
        )

    if config.bilibili.auth_method not in _SUPPORTED_AUTH_METHODS:
        supported = ", ".join(sorted(_SUPPORTED_AUTH_METHODS))
        issues.append(
            ConfigIssue(
                field="bilibili.auth_method",
                message=f"`bilibili.auth_method` 仅支持: {supported}。",
            )
        )

    provider_name = config.llm.default_provider
    provider_configs: dict[str, LLMProviderConfig] = {
        "openai": config.llm.openai,
        "claude": config.llm.claude,
        "gemini": config.llm.gemini,
        "deepseek": config.llm.deepseek,
        "ollama": config.llm.ollama,
        "openrouter": config.llm.openrouter,
        "openai_compatible": config.llm.openai_compatible,
    }

    provider_config = provider_configs.get(provider_name)
    if provider_config is None:
        issues.append(
            ConfigIssue(
                field="llm.default_provider",
                message=f"不支持的默认 provider: `{provider_name}`。",
            )
        )
        return issues

    openai_auth_mode = config.llm.openai.auth_mode.strip().lower()
    if openai_auth_mode not in _SUPPORTED_OPENAI_AUTH_MODES:
        issues.append(
            ConfigIssue(
                field="llm.openai.auth_mode",
                message='`llm.openai.auth_mode` 仅支持: "", "api_key", "codex_oauth"。',
                severity="blocking",
            )
        )

    if openai_auth_mode == "codex_oauth":
        if config.llm.openai.api_key.strip():
            issues.append(
                ConfigIssue(
                    field="llm.openai.api_key",
                    message='`auth_mode = "codex_oauth"` 时 `api_key` 会被忽略。',
                )
            )
        if not _is_openai_official_base_url(config.llm.openai.base_url):
            issues.append(
                ConfigIssue(
                    field="llm.openai.base_url",
                    message=(
                        '`auth_mode = "codex_oauth"` 只允许留空 base_url '
                        "或使用 OpenAI 官方 API 域名，避免泄露 ChatGPT token。"
                    ),
                    severity="blocking",
                )
            )
        try:
            from openbiliclaw.llm.codex_auth import codex_credentials_exist

            has_codex_credentials = codex_credentials_exist()
        except Exception:
            has_codex_credentials = False
        if not has_codex_credentials:
            issues.append(
                ConfigIssue(
                    field="llm.openai.codex_oauth",
                    message="未找到 Codex OAuth 凭据，请先运行 `openbiliclaw login codex`。",
                )
            )

    required_field = _REMOTE_PROVIDER_FIELDS.get(provider_name)
    has_env_fallback = provider_name == "gemini" and bool(_gemini_api_key_from_env())
    provider_uses_codex_oauth = provider_name == "openai" and openai_auth_mode == "codex_oauth"
    if (
        required_field
        and not provider_config.api_key.strip()
        and not has_env_fallback
        and not provider_uses_codex_oauth
    ):
        issues.append(
            ConfigIssue(
                field=required_field,
                message=(
                    f"默认 provider `{provider_name}` 缺少 `api_key`，请在 config.toml 中填写。"
                ),
            )
        )

    # openai_compatible 没有显式 base_url 是无意义的——
    # 那只是多了几步的 ``openai``。在此提示用户填写
    # ``[llm.openai_compatible].base_url``（Groq:
    # https://api.groq.com/openai/v1, vLLM: http://your-vllm:8000/v1, ...）。
    if provider_name == "openai_compatible" and not config.llm.openai_compatible.base_url.strip():
        issues.append(
            ConfigIssue(
                field="llm.openai_compatible.base_url",
                message=(
                    "默认 provider `openai_compatible` 必须填 `base_url` "
                    "(例如 Groq: https://api.groq.com/openai/v1)。"
                ),
            )
        )

    if not (_MIN_POOL_TARGET_COUNT <= config.scheduler.pool_target_count <= _MAX_POOL_TARGET_COUNT):
        issues.append(
            ConfigIssue(
                field="scheduler.pool_target_count",
                message=(
                    "`scheduler.pool_target_count` 必须在 "
                    f"{_MIN_POOL_TARGET_COUNT}..{_MAX_POOL_TARGET_COUNT} 之间。"
                ),
            )
        )

    return issues


def _is_openai_official_base_url(base_url: str) -> bool:
    raw = base_url.strip()
    if not raw:
        return True
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    return parsed.scheme == "https" and (parsed.hostname or "").lower() == "api.openai.com"


def load_config_with_diagnostics(
    config_path: str | Path | None = None,
    *,
    ensure_default_file: bool = True,
) -> tuple[Config, ConfigDiagnostics]:
    """从 TOML 文件加载配置。

    解析顺序：
    1. 显式路径（若提供）
    2. 项目根目录下的 config.toml
    3. config.local.toml 覆盖（若存在）
    4. 环境变量覆盖

    Args:
        config_path: 可选的显式配置文件路径。

    Returns:
        填充好的 Config 实例及诊断信息。
    """
    diagnostics = ConfigDiagnostics()
    raw: dict[str, Any] = {}

    if config_path:
        path = Path(config_path)
        diagnostics.config_path = path
        if path.exists():
            with open(path, "rb") as f:
                raw = tomllib.load(f)
        else:
            diagnostics.messages.append(f"未找到配置文件：{path}，当前使用默认配置。")
    else:
        if ensure_default_file:
            _ensure_default_config_file(diagnostics)
        else:
            diagnostics.config_path = _default_config_path()
        for filename in _CONFIG_FILENAMES:
            path = _project_root() / filename
            if path.exists():
                with open(path, "rb") as f:
                    file_data = tomllib.load(f)
                raw = _deep_merge(raw, file_data)

    raw = _apply_env_overrides(raw)
    config = _build_config(raw)
    diagnostics.issues.extend(_collect_config_issues(config))
    return config, diagnostics


def load_config(config_path: str | Path | None = None) -> Config:
    """仅加载配置，不返回诊断信息。"""
    config, _ = load_config_with_diagnostics(config_path, ensure_default_file=False)
    return config


def _auth_env_field_overrides() -> dict[str, bool]:
    """当前被 env 覆盖的可渲染 ``[api.auth]`` 字段。

    将每个持久化字段映射到当前是否有 ``OPENBILICLAW_API_AUTH_*`` 变量
    管控它（``PASSWORD`` 和 ``PASSWORD_HASH`` 都注入
    ``password_hash``）。``trusted_proxies`` / ``allowed_bearer_origins``
    没有 env 覆盖（仅 TOML），因此从不出现在此。
    """

    def _set(name: str) -> bool:
        return bool((os.environ.get(name) or "").strip())

    return {
        "enabled": _set("OPENBILICLAW_API_AUTH_ENABLED"),
        "password_hash": _set("OPENBILICLAW_API_AUTH_PASSWORD")
        or _set("OPENBILICLAW_API_AUTH_PASSWORD_HASH"),
        "session_secret": _set("OPENBILICLAW_API_AUTH_SESSION_SECRET"),
        "session_ttl_hours": _set("OPENBILICLAW_API_AUTH_SESSION_TTL_HOURS"),
        "trust_loopback": _set("OPENBILICLAW_API_AUTH_TRUST_LOOPBACK"),
    }


# 将每个 ``config.local.toml`` ``[api.auth]`` 键映射到它所遮蔽的
# ``config.toml`` 渲染字段（``password`` / ``password_hash`` 都注入凭据）。
_LOCAL_AUTH_KEY_TO_FIELD = {
    "password": "password_hash",
    "password_hash": "password_hash",
    "enabled": "enabled",
    "session_secret": "session_secret",
    "session_ttl_hours": "session_ttl_hours",
    "trust_loopback": "trust_loopback",
    "trusted_proxies": "trusted_proxies",
    "allowed_bearer_origins": "allowed_bearer_origins",
}


def _auth_overridden_fields(*, consult_local: bool) -> set[str]:
    """被 ``config.toml`` 之上的覆盖层（环境变量 OR ``config.local.toml``，
    两者在 ``load_config`` 中都胜出）管控的 ``[api.auth]`` 渲染字段。

    ``save_config`` 绝不能把这些字段的合并内存值烘焙进
    ``config.toml``：那会作为陈旧字面值持久化该层的值，一旦移除该层
    就会静默偏移生效的 auth（评审 r4#1 / r9 / r10）。此类字段应从
    ``config.toml`` 自身的磁盘值写入，或省略（由层在运行时继续管控）。

    env 变量对每次加载都生效，因此 env 管控的字段始终计入。但
    ``config.local.toml`` 仅在 ``load_config`` 无显式路径运行时合并
    （生产 / 默认路径场景）；``load_config(explicit_path)`` 只读取
    该文件本身。因此对不相关文件的显式路径保存，``consult_local``
    必须为 False，否则会基于一个从未合并进当前保存配置的项目根
    local 层来保留/省略字段（评审 r11）。
    """
    fields = {field for field, on in _auth_env_field_overrides().items() if on}
    if consult_local:
        for key in config_local_auth_keys():
            mapped = _LOCAL_AUTH_KEY_TO_FIELD.get(key)
            if mapped is not None:
                fields.add(mapped)
    return fields


def _read_on_disk_auth(path: Path) -> dict[str, Any]:
    """返回当前持久化在 ``path`` 的原始 ``[api.auth]`` 表（无则为 {}）。"""
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    api = data.get("api")
    auth = api.get("auth") if isinstance(api, dict) else None
    return auth if isinstance(auth, dict) else {}


def _read_on_disk_autostart(path: Path) -> dict[str, Any]:
    """返回当前持久化在 ``path`` 的原始 ``[autostart]`` 表（无则为 {}）。"""
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    autostart = data.get("autostart")
    return autostart if isinstance(autostart, dict) else {}


def _api_auth_lines(
    config: Config, on_disk_auth: dict[str, Any] | None, *, consult_local: bool
) -> list[str]:
    """渲染 ``[api.auth]`` 块，保留磁盘上的凭据溯源。

    ``on_disk_auth`` 是当前磁盘上的原始 ``[api.auth]`` 表（仅在无文件时
    为 ``None``）。两条保留规则避免无关写入静默改变生效的 auth：

    1. **覆盖层字段（评审 r4#1 / r9 / r10）。** 任何被 ``config.toml`` 之上
       的覆盖层——``OPENBILICLAW_API_AUTH_*`` env 变量或
       ``config.local.toml`` ``[api.auth]`` 键（两者在 ``load_config`` 中均
       胜出）——管控的字段，绝不能从合并后的内存 Config 重新渲染：那会
       把该层的值烘焙进 ``config.toml`` 作为陈旧字面值，一旦移除该层就会
       偏移信任边界 / 会话生命周期。此类字段应从 ``config.toml`` 自身的
       磁盘值写入（与加载器强制转换方式一致，评审 r5#1），或省略（回退到
       默认值；该层在运行时继续管控）。
    2. **明文密码便利性（评审 r8）。** 当凭据未被层管控，且操作员使用
       磁盘明文 ``password`` 键而内存 hash 仍能校验通过时，凭据未变更 →
       保留明文行以使 reconcile 指纹基保持 ``pw:``，避免无关保存将其
       翻转为 ``ph:`` 并在重启时错误地吊销记住的会话。

    所有写入路径（启动 secret-gen 的 `save_config`、`PUT /api/config`、
    cookie 同步、admin、CLI）都经过此处，因此保护是集中的。（意图变更
    auth 的层遮蔽写入，例如 admin endpoint，还会额外做一次生效重载校验
    并拒绝——见评审 r9。）
    """
    auth = config.api.auth
    overridden = _auth_overridden_fields(consult_local=consult_local)
    disk = on_disk_auth or {}
    lines = ["[api.auth]"]

    def emit(field: str, mem_line: str, disk_repr: Callable[[Any], str]) -> None:
        if field in overridden:
            if field in disk:
                # 通过加载器的强制转换重新渲染基础文件自身的值
                # （评审 r5#1）——绝不持久化覆盖层的值。
                lines.append(f"{field} = {disk_repr(disk[field])}")
            # 否则：省略——基础文件无值；加载时回退到默认值
        else:
            lines.append(mem_line)

    emit("enabled", f"enabled = {_toml_bool(auth.enabled)}", lambda v: _toml_bool(_coerce_bool(v)))
    # 密码凭据从 env PASSWORD / _PASSWORD_HASH 与 config.local 的
    # `password` / `password_hash` 键映射到渲染字段
    # `password_hash`；_build_api_auth 接受磁盘明文 `password`
    # （哈希后，优先）或 `password_hash`。
    if "password_hash" in overridden:
        # 某层管控凭据 → 保留操作员在 config.toml 中写入的磁盘键
        # 以便移除该层后恢复其自己的密码，而不是留下 `enabled = true`
        # 但无凭据（r6#1）。
        disk_pw = disk.get("password")
        if disk_pw is not None and str(disk_pw).strip():
            lines.append(f"password = {_toml_string(str(disk_pw))}")
        disk_hash = disk.get("password_hash")
        if disk_hash is not None and str(disk_hash).strip():
            lines.append(f"password_hash = {_toml_string(str(disk_hash))}")
        # 两者均无 → 省略（无磁盘凭据可保留）
    elif _hash_matches_plaintext(disk.get("password"), auth.password_hash):
        # 未变更的明文背书凭据 → 保留明文行以使 reconcile 指纹基
        # 在跨重启时保持 "pw:"+plain（r8）。
        lines.append(f"password = {_toml_string(str(disk['password']))}")
    else:
        # 无磁盘明文，或明文已不匹配（密码在内存中被修改，例如
        # set-password）→ 持久化内存 hash。
        lines.append(f"password_hash = {_toml_string(auth.password_hash)}")
    emit(
        "session_secret",
        f"session_secret = {_toml_string(auth.session_secret)}",
        lambda v: _toml_string(str(v)),
    )
    emit(
        "session_ttl_hours",
        f"session_ttl_hours = {auth.session_ttl_hours}",
        lambda v: str(_coerce_ttl_hours(v)),
    )
    emit(
        "trust_loopback",
        f"trust_loopback = {_toml_bool(auth.trust_loopback)}",
        lambda v: _toml_bool(_coerce_bool(v, default=True)),
    )
    # 这两个字段没有 env 覆盖，但 config.local.toml 可以遮蔽它们，因此
    # 也通过 emit 处理（保留基础文件的列表，或省略）。
    emit(
        "trusted_proxies",
        f"trusted_proxies = {_toml_str_list(auth.trusted_proxies)}",
        lambda v: _toml_str_list(_coerce_str_list(v)),
    )
    emit(
        "allowed_bearer_origins",
        f"allowed_bearer_origins = {_toml_str_list(auth.allowed_bearer_origins)}",
        lambda v: _toml_str_list(_coerce_str_list(v)),
    )
    return lines


def _autostart_lines(
    config: Config,
    on_disk_autostart: dict[str, Any] | None,
    *,
    autostart_authoritative: bool,
) -> list[str]:
    """渲染 ``[autostart]``，不破坏 OS 注册意图。

    普通全文件写入可能持有陈旧的 ``Config`` 快照，因此保留磁盘上的
    ``enabled`` 值。Apply/CLI 写入器传入 ``autostart_authoritative``，
    成为唯一允许修改它的代码路径。``manage_ollama`` 无 OS 副作用，
    始终从内存渲染。
    """
    lines = ["[autostart]"]
    if autostart_authoritative:
        lines.append(f"enabled = {_toml_bool(config.autostart.enabled)}")
    else:
        disk = on_disk_autostart or {}
        if "enabled" in disk:
            lines.append(f"enabled = {_toml_bool(_coerce_bool(disk['enabled'], default=False))}")
    lines.append(f"manage_ollama = {_toml_bool(config.autostart.manage_ollama)}")
    return lines


def save_config(
    config: Config,
    config_path: str | Path | None = None,
    *,
    autostart_authoritative: bool = False,
) -> Path:
    """将 Config dataclass 持久化为 TOML。"""
    path = Path(config_path) if config_path is not None else _default_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # 捕获磁盘上的 [api.auth] 表，以便渲染器保留凭据溯源：
    # env 覆盖字段（评审 r4#1）和未变更明文 `password` 便利键
    # （评审 r8）。每次保存都读取（非仅 env 管控时），以便普通
    # 设置/cookie 写入不会丢失明文密码并翻转 reconcile 指纹基。
    on_disk_auth = _read_on_disk_auth(path) if path.exists() else None
    on_disk_autostart = _read_on_disk_autostart(path) if path.exists() else None
    # config.local.toml 仅在 load_config 无显式路径运行时合并
    # （生产 / 默认路径）。保存到任何其他显式文件时它从未被合并，
    # 因此其覆盖不应管控此次渲染（评审 r11）。
    consult_local = config_path is None or path.resolve() == _default_config_path().resolve()
    path.write_text(
        _render_config_toml(
            config,
            on_disk_auth=on_disk_auth,
            on_disk_autostart=on_disk_autostart,
            autostart_authoritative=autostart_authoritative,
            consult_local=consult_local,
        ),
        encoding="utf-8",
    )
    return path


def _render_config_toml(
    config: Config,
    *,
    on_disk_auth: dict[str, Any] | None = None,
    on_disk_autostart: dict[str, Any] | None = None,
    autostart_authoritative: bool = False,
    consult_local: bool = False,
) -> str:
    """将 Config dataclass 渲染为 TOML。"""
    lines = [
        "[general]",
        f"language = {_toml_string(config.language)}",
        f"data_dir = {_toml_string(config.data_dir)}",
        "",
        "[api]",
        f"host = {_toml_string(config.api.host)}",
        f"port = {config.api.port}",
        "",
        *_api_auth_lines(config, on_disk_auth, consult_local=consult_local),
        "",
        "[llm]",
        f"default_provider = {_toml_string(config.llm.default_provider)}",
        f"concurrency = {_normalize_llm_concurrency(config.llm.concurrency)}",
        f"timeout = {_normalize_llm_timeout(config.llm.timeout)}",
        f"fallback_enabled = {_toml_bool(config.llm.fallback_enabled)}",
        f"fallback_provider = {_toml_string(config.llm.fallback_provider)}",
        "",
    ]
    lines.extend(_render_provider_section("openai", config.llm.openai))
    lines.extend(_render_provider_section("claude", config.llm.claude))
    lines.extend(_render_provider_section("gemini", config.llm.gemini))
    lines.extend(_render_provider_section("deepseek", config.llm.deepseek))
    lines.extend(_render_provider_section("ollama", config.llm.ollama))
    lines.extend(_render_provider_section("openrouter", config.llm.openrouter))
    lines.extend(_render_provider_section("openai_compatible", config.llm.openai_compatible))
    lines.extend(
        [
            "[llm.embedding]",
            f"provider = {_toml_string(config.llm.embedding.provider)}",
            f"model = {_toml_string(config.llm.embedding.model)}",
            f"api_key = {_toml_string(config.llm.embedding.api_key)}",
            f"base_url = {_toml_string(config.llm.embedding.base_url)}",
            f"output_dimensionality = {max(0, int(config.llm.embedding.output_dimensionality))}",
            f"similarity_threshold = {config.llm.embedding.similarity_threshold}",
            f"fallback_enabled = {_toml_bool(config.llm.embedding.fallback_enabled)}",
            f"fallback_provider = {_toml_string(config.llm.embedding.fallback_provider)}",
            "",
            "# 按模块 LLM 覆盖（留空 = 使用全局默认）",
            "[llm.soul]",
            f"provider = {_toml_string(config.llm.soul.provider)}",
            f"model = {_toml_string(config.llm.soul.model)}",
            "",
            "[llm.discovery]",
            f"provider = {_toml_string(config.llm.discovery.provider)}",
            f"model = {_toml_string(config.llm.discovery.model)}",
            "",
            "[llm.recommendation]",
            f"provider = {_toml_string(config.llm.recommendation.provider)}",
            f"model = {_toml_string(config.llm.recommendation.model)}",
            "",
            "[llm.evaluation]",
            f"provider = {_toml_string(config.llm.evaluation.provider)}",
            f"model = {_toml_string(config.llm.evaluation.model)}",
            "",
        ]
    )
    lines.extend(
        [
            "[bilibili]",
            f"auth_method = {_toml_string(config.bilibili.auth_method)}",
            f"cookie = {_toml_string(config.bilibili.cookie)}",
            "",
            "[bilibili.browser]",
            f"executable = {_toml_string(config.bilibili.browser_executable)}",
            f"headed = {_toml_bool(config.bilibili.browser_headed)}",
            "",
            "[sources.browser]",
            f"cdp_url = {_toml_string(config.sources.browser_cdp_url)}",
            f"headed = {_toml_bool(config.sources.browser_headed)}",
            "",
            "[sources.bilibili]",
            f"enabled = {_toml_bool(config.sources.bilibili.enabled)}",
            "",
            "[sources.xiaohongshu]",
            f"enabled = {_toml_bool(config.sources.xiaohongshu.enabled)}",
            f"daily_search_budget = {config.sources.xiaohongshu.daily_search_budget}",
            f"daily_creator_budget = {config.sources.xiaohongshu.daily_creator_budget}",
            f"task_interval_seconds = {config.sources.xiaohongshu.task_interval_seconds}",
            "",
            "[sources.douyin]",
            f"enabled = {_toml_bool(config.sources.douyin.enabled)}",
            f"mode = {_toml_string(config.sources.douyin.mode)}",
            f"cookie_env = {_toml_string(config.sources.douyin.cookie_env)}",
            f"daily_search_budget = {config.sources.douyin.daily_search_budget}",
            f"daily_hot_budget = {config.sources.douyin.daily_hot_budget}",
            f"daily_feed_budget = {config.sources.douyin.daily_feed_budget}",
            f"request_interval_seconds = {config.sources.douyin.request_interval_seconds}",
            "",
            "[sources.youtube]",
            f"enabled = {_toml_bool(config.sources.youtube.enabled)}",
            f"daily_search_budget = {config.sources.youtube.daily_search_budget}",
            f"daily_trending_budget = {config.sources.youtube.daily_trending_budget}",
            f"daily_channel_budget = {config.sources.youtube.daily_channel_budget}",
            f"request_interval_seconds = {config.sources.youtube.request_interval_seconds}",
            f"min_interval_minutes = {config.sources.youtube.min_interval_minutes}",
            "",
            "[sources.twitter]",
            f"enabled = {_toml_bool(config.sources.twitter.enabled)}",
            f"mode = {_toml_string(config.sources.twitter.mode)}",
            f"cookie_env = {_toml_string(config.sources.twitter.cookie_env)}",
            f"daily_search_budget = {config.sources.twitter.daily_search_budget}",
            f"daily_feed_budget = {config.sources.twitter.daily_feed_budget}",
            f"daily_creator_budget = {config.sources.twitter.daily_creator_budget}",
            f"request_interval_seconds = {config.sources.twitter.request_interval_seconds}",
            f"min_interval_minutes = {config.sources.twitter.min_interval_minutes}",
            "",
            "[sources.zhihu]",
            f"enabled = {_toml_bool(config.sources.zhihu.enabled)}",
            f"source_modes = {_toml_str_list(list(config.sources.zhihu.source_modes))}",
            f"daily_search_budget = {config.sources.zhihu.daily_search_budget}",
            f"daily_hot_budget = {config.sources.zhihu.daily_hot_budget}",
            f"daily_feed_budget = {config.sources.zhihu.daily_feed_budget}",
            f"daily_creator_budget = {config.sources.zhihu.daily_creator_budget}",
            f"daily_related_budget = {config.sources.zhihu.daily_related_budget}",
            f"request_interval_seconds = {config.sources.zhihu.request_interval_seconds}",
            f"min_interval_minutes = {config.sources.zhihu.min_interval_minutes}",
            "",
            "[scheduler]",
            f"enabled = {_toml_bool(config.scheduler.enabled)}",
            "pause_on_extension_disconnect = "
            f"{_toml_bool(config.scheduler.pause_on_extension_disconnect)}",
            "extension_disconnect_grace_seconds = "
            f"{config.scheduler.extension_disconnect_grace_seconds}",
            f"discovery_cron = {_toml_string(config.scheduler.discovery_cron)}",
            f"pool_target_count = {config.scheduler.pool_target_count}",
            f"account_sync_interval_hours = {config.scheduler.account_sync_interval_hours}",
            f"refresh_check_interval_seconds = {config.scheduler.refresh_check_interval_seconds}",
            f"signal_event_threshold = {config.scheduler.signal_event_threshold}",
            f"trending_refresh_hours = {config.scheduler.trending_refresh_hours}",
            f"explore_refresh_hours = {config.scheduler.explore_refresh_hours}",
            f"discovery_limit = {config.scheduler.discovery_limit}",
            f"delight_queue_limit = {config.scheduler.delight_queue_limit}",
            f"proactive_push_interval_seconds = {config.scheduler.proactive_push_interval_seconds}",
            "speculator_idle_interval_minutes = "
            f"{config.scheduler.speculator_idle_interval_minutes}",
            f"speculation_interval_minutes = {config.scheduler.speculation_interval_minutes}",
            f"speculation_ttl_days = {config.scheduler.speculation_ttl_days}",
            f"speculation_cooldown_days = {config.scheduler.speculation_cooldown_days}",
            "speculation_confirmation_threshold = "
            f"{config.scheduler.speculation_confirmation_threshold}",
            f"speculation_max_active = {config.scheduler.speculation_max_active}",
            "speculation_max_primary_interests = "
            f"{config.scheduler.speculation_max_primary_interests}",
            "speculation_max_secondary_interests = "
            f"{config.scheduler.speculation_max_secondary_interests}",
            "avoidance_speculation_interval_minutes = "
            f"{config.scheduler.avoidance_speculation_interval_minutes}",
            f"avoidance_speculation_ttl_days = {config.scheduler.avoidance_speculation_ttl_days}",
            "avoidance_speculation_cooldown_days = "
            f"{config.scheduler.avoidance_speculation_cooldown_days}",
            "avoidance_speculation_confirmation_threshold = "
            f"{config.scheduler.avoidance_speculation_confirmation_threshold}",
            "avoidance_speculation_max_active = "
            f"{config.scheduler.avoidance_speculation_max_active}",
            f"auto_update_enabled = {_toml_bool(config.scheduler.auto_update_enabled)}",
            "auto_update_check_interval_hours = "
            f"{config.scheduler.auto_update_check_interval_hours}",
            "auto_update_allow_prerelease = "
            f"{_toml_bool(config.scheduler.auto_update_allow_prerelease)}",
            "auto_update_allowed_remotes = "
            f"{_toml_str_list(config.scheduler.auto_update_allowed_remotes)}",
            "",
            "[scheduler.pool_source_shares]",
            f"bilibili = {int(config.scheduler.pool_source_shares.get('bilibili', 5))}",
            f"xiaohongshu = {int(config.scheduler.pool_source_shares.get('xiaohongshu', 1))}",
            f"douyin = {int(config.scheduler.pool_source_shares.get('douyin', 1))}",
            f"youtube = {int(config.scheduler.pool_source_shares.get('youtube', 1))}",
            f"twitter = {int(config.scheduler.pool_source_shares.get('twitter', 1))}",
            f"zhihu = {int(config.scheduler.pool_source_shares.get('zhihu', 1))}",
            "",
            "[discovery]",
            "unified_keyword_planner_enabled = "
            f"{_toml_bool(config.discovery.unified_keyword_planner_enabled)}",
            f"kw_cache_high = {config.discovery.kw_cache_high}",
            f"kw_cache_low = {config.discovery.kw_cache_low}",
            f"gen_batch = {config.discovery.gen_batch}",
            f"fetch_batch = {config.discovery.fetch_batch}",
            f"history_window_size = {config.discovery.history_window_size}",
            f"history_window_hours = {config.discovery.history_window_hours}",
            f"claim_lease_minutes = {config.discovery.claim_lease_minutes}",
            f"planner_poll_seconds = {config.discovery.planner_poll_seconds}",
            f"plan_ttl_hours = {config.discovery.plan_ttl_hours}",
            f"admission_min_score = {config.discovery.admission_min_score:g}",
            "multimodal_evaluation_enabled = "
            f"{_toml_bool(config.discovery.multimodal_evaluation_enabled)}",
            f"multimodal_batch_size = {config.discovery.multimodal_batch_size}",
            f"multimodal_image_max_px = {config.discovery.multimodal_image_max_px}",
            f"multimodal_image_quality = {config.discovery.multimodal_image_quality}",
            "multimodal_image_timeout_seconds = "
            f"{config.discovery.multimodal_image_timeout_seconds}",
            "",
            *_autostart_lines(
                config,
                on_disk_autostart,
                autostart_authoritative=autostart_authoritative,
            ),
            "",
            "[storage]",
            f"db_path = {_toml_string(config.storage.db_path)}",
            "",
            "[logging]",
            f"level = {_toml_string(config.logging.level)}",
            f"file_level = {_toml_string(config.logging.file_level)}",
            f"directory = {_toml_string(config.logging.directory)}",
            f"filename = {_toml_string(config.logging.filename)}",
            f"max_file_size_mb = {config.logging.max_file_size_mb}",
            f"backup_count = {config.logging.backup_count}",
            f"aggregate_budget_mb = {config.logging.aggregate_budget_mb}",
            f"unmanaged_truncate_mb = {config.logging.unmanaged_truncate_mb}",
            f"unmanaged_max_age_days = {config.logging.unmanaged_max_age_days}",
            "",
            "[soul.preference]",
            "# v0.3.x 事件满意度信号。为 true 时，偏好",
            "# 分析忽略被动负向事件如 quick_exit。",
            "# 显式不喜欢反馈仍保留为 disliked_topics",
            "# 证据，而非被学习为正向兴趣。",
            "satisfaction_filter_enabled = "
            f"{_toml_bool(config.soul.preference.satisfaction_filter_enabled)}",
            "",
        ]
    )
    return "\n".join(lines)


def _render_provider_section(name: str, provider: LLMProviderConfig) -> list[str]:
    """渲染单个 provider 子段。"""
    lines = [f"[llm.{name}]"]
    lines.append(f"api_key = {_toml_string(provider.api_key)}")
    lines.append(f"model = {_toml_string(provider.model)}")
    if name in {"openai", "deepseek", "ollama", "openrouter", "openai_compatible"}:
        lines.append(f"base_url = {_toml_string(provider.base_url)}")
    if name == "openai":
        lines.append(f"auth_mode = {_toml_string(provider.auth_mode)}")
    if name == "deepseek":
        lines.append(f"reasoning_effort = {_toml_string(provider.reasoning_effort)}")
    if name == "openrouter":
        lines.append(f"http_referer = {_toml_string(provider.http_referer)}")
        lines.append(f"x_title = {_toml_string(provider.x_title)}")
    lines.append("")
    return lines


def _toml_string(value: str) -> str:
    """渲染 TOML 字符串字面值。"""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _toml_bool(value: bool) -> str:
    """渲染 TOML 布尔字面值。"""
    return "true" if value else "false"


def _toml_str_list(values: list[str]) -> str:
    """渲染 TOML 字符串数组。"""
    return "[" + ", ".join(_toml_string(item) for item in values) + "]"


def validate_runtime_config(config: Config) -> None:
    """运行时关键配置非法时抛出 ConfigError。"""
    issues = _collect_config_issues(config)
    if issues:
        issue = issues[0]
        raise ConfigError(f"{issue.field}: {issue.message}")
