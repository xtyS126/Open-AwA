"""本地后端 API 的 Pydantic 模型。"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field


class BehaviorEventIn(BaseModel):
    """由扩展上报的单个行为事件。"""

    type: str
    url: str = ""
    title: str = ""
    timestamp: int
    source_platform: str = "bilibili"
    context: dict[str, object] = Field(default_factory=dict)
    metadata: dict[str, object] = Field(default_factory=dict)
    # v0.3.x event-satisfaction 信号：视频页退出时的 dwell。顶层
    # 或 `metadata.watch_seconds` 均可接受；端点在持久化前把顶层
    # 折叠进 metadata，使 storage 分类器从单一规范位置读取。
    watch_seconds: float | None = None
    video_duration_seconds: float | None = None


class BehaviorEventBatchIn(BaseModel):
    """service worker 使用的批量载荷。"""

    events: list[BehaviorEventIn]


class HealthResponse(BaseModel):
    """健康检查响应。"""

    status: str
    service: str
    profile_ready: bool | None = None
    lan_ip: str | None = None
    # v0.3.95+：暴露 embedding service 是否构建成功。
    # ``False`` 表示语义去重 / 多样性降级（推荐可能在不同 id 下重复
    # 近似内容）—— 弹窗据此显示一键"启用本地 Ollama"横幅。
    embedding_ready: bool | None = None


class InitStageOut(BaseModel):
    """guided init 的一个阶段（gui-init spec API 形状）。"""

    n: int
    label: str
    status: str  # pending | running | ok | warning | failed
    reason: str | None = None


class InitPrerequisitesOut(BaseModel):
    """呈现给 UI 的预初始化检查清单。"""

    bilibili_logged_in: bool = False
    bilibili_check: str = "checking"  # ok | failed | checking
    llm_ready: bool = False
    embedding_ready: bool = False
    embedding_required: bool = False
    enabled_platforms: list[str] = Field(default_factory=list)


class InitStatusOut(BaseModel):
    """权威的 guided-init 状态/进度（gui-init spec API 形状）。"""

    initialized: bool = False
    running: bool = False
    run_id: str | None = None
    sequence: int = 0
    current_stage: int = 0
    total_stages: int = 4
    stages: list[InitStageOut] = Field(default_factory=list)
    partial_success: bool = False
    can_start: bool = False
    can_manage: bool = False
    prerequisites: InitPrerequisitesOut = Field(default_factory=InitPrerequisitesOut)
    reason: str = "none"
    detail: str = ""


class RecommendationOut(BaseModel):
    """暴露给弹窗的推荐载荷。"""

    id: int
    bvid: str
    title: str = ""
    up_name: str = ""
    cover_url: str = ""
    expression: str = ""
    topic_label: str = ""
    presented: bool = False
    feedback_type: str = ""
    # 多源字段（附加、向后兼容）
    content_id: str = ""
    content_url: str = ""
    source_platform: str = ""
    # 文本优先源（X tweet/thread）：当 content_type 为 tweet/thread 或
    # cover_url 为空时，弹窗根据 body_text/title 渲染无封面的文本卡片。
    content_type: str = "video"
    body_text: str = ""


class RecommendationListResponse(BaseModel):
    """推荐列表的包装响应。"""

    items: list[RecommendationOut]


class RecommendationReshuffleResponse(BaseModel):
    """即时推荐重洗结果。"""

    items: list[RecommendationOut]


class RecommendationAppendIn(BaseModel):
    """追加下一页推荐的请求载荷。"""

    excluded_bvids: list[str] = Field(default_factory=list)


class RecommendationRefreshResponse(BaseModel):
    """一次显式推荐刷新请求的结果。"""

    ok: bool
    accepted: bool
    state: str = "idle"
    reason: str = ""


class RuntimeStatusResponse(BaseModel):
    """供弹窗和后台状态检查使用的运行时摘要。"""

    initialized: bool
    recommendation_count: int
    pending_signal_events: int
    last_refresh_at: str = ""
    last_notification_at: str = ""
    unread_count: int
    pool_available_count: int = 0
    pool_raw_count: int = 0
    pool_pending_count: int = 0
    pool_pending_eval_count: int = 0
    pool_evaluated_pending_count: int = 0
    pool_target_count: int = 0
    last_discovered_count: int = 0
    last_replenished_count: int = 0
    recent_pool_topics: list[str] = Field(default_factory=list)
    manual_refresh_state: str = "idle"
    manual_refresh_message: str = ""
    last_account_sync_at: str = ""
    last_account_sync_error: str = ""
    auto_update_enabled: bool = False
    install_mode: str = ""
    current_version: str = ""
    latest_remote_version: str = ""
    last_update_check_at: str = ""
    last_update_error: str = ""
    backend_update_state: str = "unknown"
    backend_update_reason: str = "none"


class ActivityFeedItemOut(BaseModel):
    """弹窗中一项近期的用户可见活动条目。"""

    id: str
    kind: str
    summary: str
    detail: str = ""
    created_at: str = ""
    tone: str = "info"


class ActivityFeedResponse(BaseModel):
    """弹窗活动卡片的聚合活动流。"""

    live_summary: str = ""
    headline: str = ""
    items: list[ActivityFeedItemOut] = Field(default_factory=list)
    has_more: bool = False
    next_cursor: str = ""


class PendingNotificationOut(BaseModel):
    """一条值得通知的推荐。"""

    recommendation_id: int
    bvid: str
    title: str = ""
    reason: str = ""


class PendingNotificationResponse(BaseModel):
    """待处理通知候选项的包装。"""

    item: PendingNotificationOut | None = None


class PendingCognitionUpdateOut(BaseModel):
    """一条值得在扩展中通知的认知更新。"""

    id: str
    kind: str
    summary: str


class PendingCognitionUpdateResponse(BaseModel):
    """待处理认知更新的包装。"""

    item: PendingCognitionUpdateOut | None = None


class PendingDelightOut(BaseModel):
    """一条主动 delight 推荐。"""

    bvid: str
    title: str = ""
    delight_reason: str = ""
    delight_score: float = 0.0
    delight_hook: str = ""
    cover_url: str = ""
    content_url: str = ""
    source_platform: str = ""


class PendingDelightResponse(BaseModel):
    """待处理 delight 候选项的包装。"""

    item: PendingDelightOut | None = None


class DelightAckIn(BaseModel):
    """确认收到 delight 通知。"""

    bvid: str


class DelightAckResponse(BaseModel):
    """将 delight 通知标记为已送达后的响应。"""

    ok: bool
    bvid: str


class BilibiliCookieIn(BaseModel):
    """来自浏览器扩展的 Cookie 同步载荷。

    允许扩展将用户实时的 bilibili.com 会话 cookie 推送到
    后端（写入 data/bilibili_cookie.json + config.toml 的
    [bilibili].cookie）。替代手工的 F12 → 复制 → 粘贴流程。
    """

    cookie: str = Field(
        ...,
        description="Cookie header string ('SESSDATA=...; bili_jct=...; ...').",
        min_length=1,
    )
    source: str = Field(
        default="extension",
        description="Where the cookie came from. Used for telemetry only.",
    )
    validate_with_bilibili: bool = Field(
        default=True,
        description="If true, hit the Bilibili nav endpoint before saving "
        "to confirm the cookie is actually authenticated.",
    )


class BilibiliCookieResponse(BaseModel):
    """一次 cookie 同步尝试的结果。

    ``error_code`` 让扩展选择智能的重试节奏
    （网络错误 → 快速重试，cookie 过期 → 等待下次登录）。
    当 ``ok=True`` 时为空。
    """

    ok: bool
    authenticated: bool
    username: str = ""
    user_id: int = 0
    message: str = ""
    # v0.3.42+ 机器可读代码，供扩展分支重试逻辑使用。取值之一：
    #   ""                       — 成功
    #   "empty_cookie"           — 载荷为空
    #   "cookie_invalid"         — Bilibili 报告 cookie 无效/过期
    #   "validation_network"     — 后端无法访问 api.bilibili.com
    error_code: str = ""


class DouyinCookieIn(BaseModel):
    """抖音 direct-cookie 发现模式的 Cookie 同步载荷。"""

    cookie: str = Field(
        ...,
        description="Cookie header string from douyin.com.",
        min_length=1,
    )
    source: str = Field(
        default="extension",
        description="Where the cookie came from. Used for telemetry only.",
    )


class DouyinCookieResponse(BaseModel):
    """同步抖音 Cookie header 的结果。"""

    ok: bool
    has_cookie: bool
    cookie_names: list[str] = Field(default_factory=list)
    message: str = ""
    error_code: str = ""


class XCookieIn(BaseModel):
    """X (Twitter) 服务端 cookie-replay 发现的 Cookie 同步载荷。"""

    cookie: str = Field(
        ...,
        description="Cookie header string from x.com.",
        min_length=1,
    )
    source: str = Field(
        default="extension",
        description="Where the cookie came from. Used for telemetry only.",
    )


class XCookieResponse(BaseModel):
    """同步 X (Twitter) Cookie header 的结果。

    仅当 ``auth_token`` 和 ``ct0`` 同时存在时 ``has_cookie`` 才为
    true —— twitter-cli 需要二者才能认证。
    """

    ok: bool
    has_cookie: bool
    cookie_names: list[str] = Field(default_factory=list)
    message: str = ""
    error_code: str = ""


class XStatusResponse(BaseModel):
    """X (Twitter) 源的当前健康状态（spec §7）。

    ``state`` 取值为 ``ok`` / ``missing_cookie`` / ``expired_cookie`` /
    ``rate_limited`` / ``blocked`` 之一。当 For-You 反复失败自动暂停
    高可见度的 home-timeline 拉取时，``feed_paused`` 为 true。
    """

    state: str = "ok"
    consecutive_failures: int = 0
    feed_paused: bool = False
    cooldown_until: str = ""
    detail: str = ""
    updated_at: str = ""


class SourceStatusItem(BaseModel):
    """统一的按源登录/cookie 就绪状态（设置页）。

    ``state`` 是粗粒度、与源无关的状态，因此每个平台都能渲染同样的 chip：

    - ``ok``         —— 凭证存在且经过实时验证（仅 X，来自 health store）。
    - ``ready``      —— 凭证存在且结构有效，但未实时验证（带登录字段的
      B站 cookie、存在的抖音 cookie、新鲜度窗口内同步的小红书 access token）。
    - ``partial``    —— 凭证存在但结构不完整，可能已损坏（B站 cookie 缺少
      部分核心登录字段）。
    - ``stale``      —— 凭证之前同步过但已不新鲜，可能已过期（小红书 token
      早于新鲜度窗口）。
    - ``missing``    —— 源已启用但没有可用凭证。
    - ``unverified`` —— 插件支撑的源已启用，但本地任务历史尚不能证明近期
      有成功或失败的登录态运行。
    - ``expired`` / ``rate_limited`` / ``blocked`` —— X 实时健康状态。
    - ``no_auth``    —— 源无需登录（YouTube，公开）。

    ``logged_in`` 是一个便捷标志（``state in {ok, ready, no_auth}``），
    让 UI 无需重新推导规则即可选择点的颜色。
    """

    enabled: bool = False
    state: str = "missing"
    detail: str = ""
    logged_in: bool = False
    feed_paused: bool = False


class SourcesStatusResponse(BaseModel):
    """每个内容源的登录/cookie 就绪状态，按平台为键。

    支撑桌面 Web 与扩展设置页上显示的统一状态 chip。完全由本地信号
    推导（config cookie 字段、X health store、抖音 cookie file/env、
    以及携带 token 的小红书 cache 行的新鲜度）—— 无任何出站平台调用。
    """

    bilibili: SourceStatusItem = Field(default_factory=SourceStatusItem)
    xiaohongshu: SourceStatusItem = Field(default_factory=SourceStatusItem)
    douyin: SourceStatusItem = Field(default_factory=SourceStatusItem)
    youtube: SourceStatusItem = Field(default_factory=SourceStatusItem)
    twitter: SourceStatusItem = Field(default_factory=SourceStatusItem)
    zhihu: SourceStatusItem = Field(default_factory=SourceStatusItem)


class SourceCredentialItem(BaseModel):
    """源设置页的当前本地凭证快照。"""

    label: str = "Cookie"
    value: str = ""
    available: bool = False
    detail: str = ""


class SourcesCredentialsResponse(BaseModel):
    """源设置页的当前本地 Cookie / token 值。"""

    bilibili: SourceCredentialItem = Field(default_factory=SourceCredentialItem)
    xiaohongshu: SourceCredentialItem = Field(default_factory=SourceCredentialItem)
    douyin: SourceCredentialItem = Field(default_factory=SourceCredentialItem)
    youtube: SourceCredentialItem = Field(default_factory=SourceCredentialItem)
    twitter: SourceCredentialItem = Field(default_factory=SourceCredentialItem)
    zhihu: SourceCredentialItem = Field(default_factory=SourceCredentialItem)


class NotificationAckIn(BaseModel):
    """确认一条浏览器通知的送达。"""

    bvid: str


class NotificationAckResponse(BaseModel):
    """将通知标记为已送达后的响应。"""

    ok: bool
    bvid: str


class CognitionUpdateSeenIn(BaseModel):
    """确认一条认知更新已查看/已通知。"""

    id: str


class CognitionUpdateSeenResponse(BaseModel):
    """将认知更新标记为已查看后的响应。"""

    ok: bool
    id: str


class CognitionUpdateSummary(BaseModel):
    """弹窗 profile 标签页中展示的结构化认知卡片。"""

    summary: str
    context_line: str = ""
    impact: str = ""
    reasoning: str = ""
    evidence: str = ""
    source: str = ""
    source_label: str = ""
    expand_hint: str = "summary_only"
    created_at: str = ""


class SpeculativeSpecificOut(BaseModel):
    """推测领域内的一个窄主题。"""

    name: str = ""
    confirmation_count: int = 0


class SpeculativeInterestOut(BaseModel):
    """一个推测的兴趣方向，带两级结构。"""

    domain: str = ""
    reason: str = ""
    confidence: float = 0.0
    probe_mode: str = "near"
    challenge: bool = False
    confirmation_count: int = 0
    confirmation_threshold: int = 3
    status: str = "active"
    specifics: list[SpeculativeSpecificOut] = Field(default_factory=list)


class SpeculativeAvoidanceOut(BaseModel):
    """一个推测的回避方向，带两级结构。"""

    domain: str = ""
    reason: str = ""
    confidence: float = 0.0
    source_mode: str = ""
    source_signal: str = ""
    confirmation_count: int = 0
    confirmation_threshold: int = 3
    status: str = "active"
    specifics: list[SpeculativeSpecificOut] = Field(default_factory=list)


class MBTIDimensionOut(BaseModel):
    """单个 MBTI 维度极向及其强度。"""

    pole: str = ""
    strength: float = 0.5


class MBTIOut(BaseModel):
    """MBTI 人格类型及其维度分解。"""

    type: str = ""
    dimensions: dict[str, MBTIDimensionOut] = Field(default_factory=dict)
    confidence: float = 0.0


class InterestSpecificOut(BaseModel):
    """一个领域内的窄兴趣。"""

    name: str = ""
    weight: float = 0.5


class InterestDomainOut(BaseModel):
    """一个宽泛的兴趣领域，可带可选的具体子兴趣。"""

    domain: str = ""
    weight: float = 0.5
    specifics: list[InterestSpecificOut] = Field(default_factory=list)


class StylePreferenceOut(BaseModel):
    """内容风格偏好。"""

    preferred_duration: str = ""
    preferred_pace: str = ""
    quality_sensitivity: float = 0.5
    humor_preference: float = 0.5
    depth_preference: float = 0.5


class ContextModeOut(BaseModel):
    """上下文使用模式。"""

    weekday_patterns: str = ""
    weekend_patterns: str = ""
    time_of_day_patterns: str = ""
    session_type: str = ""


class AwarenessNoteOut(BaseModel):
    """来自 soul 层的一条觉察观察。"""

    date: str = ""
    observation: str = ""
    trend: str = ""
    emotion_guess: str = ""


class InsightHypothesisOut(BaseModel):
    """关于用户的一条活跃洞察或假设。"""

    hypothesis: str = ""
    evidence: list[str] = Field(default_factory=list)
    confidence: float = 0.5
    validated: bool = False
    created_at: str = ""


class ProfileSummaryResponse(BaseModel):
    """暴露给弹窗的完整 soul profile —— 全部五层 Onion。"""

    initialized: bool
    personality_portrait: str = ""
    # Core 层
    core_traits: list[str] = Field(default_factory=list)
    deep_needs: list[str] = Field(default_factory=list)
    mbti: MBTIOut = Field(default_factory=MBTIOut)
    # Values 层
    values: list[str] = Field(default_factory=list)
    motivational_drivers: list[str] = Field(default_factory=list)
    # Interest 层
    likes: list[InterestDomainOut] = Field(default_factory=list)
    dislikes: list[InterestDomainOut] = Field(default_factory=list)
    favorite_up_users: list[str] = Field(default_factory=list)
    # Role 层
    life_stage: str = ""
    current_phase: str = ""
    # Surface 层
    cognitive_style: list[str] = Field(default_factory=list)
    style: StylePreferenceOut = Field(default_factory=StylePreferenceOut)
    context: ContextModeOut = Field(default_factory=ContextModeOut)
    exploration_openness: float = 0.5
    # 横切关注点
    speculative_interests: list[SpeculativeInterestOut] = Field(default_factory=list)
    speculative_avoidances: list[SpeculativeAvoidanceOut] = Field(default_factory=list)
    recent_cognition_updates: list[CognitionUpdateSummary] = Field(default_factory=list)
    has_more_cognition_updates: bool = False
    next_cognition_cursor: str = ""
    active_insights: list[InsightHypothesisOut] = Field(default_factory=list)
    recent_awareness: list[AwarenessNoteOut] = Field(default_factory=list)
    # 用户编写的覆盖（ProfileOverrides.to_dict()），使展示 UI
    # 可对已编辑/已钉住字段加徽章。用户未做编辑时为空。
    overrides: dict[str, object] = Field(default_factory=dict)


class EventRejectedOut(BaseModel):
    """批量 ingest 时跳过的一条事件。"""

    index: int
    type: str
    reason: str


class EventIngestResponse(BaseModel):
    """接收一批事件后的响应。"""

    accepted: int
    rejected: list[EventRejectedOut] = Field(default_factory=list)


ExtensionE2EPlatform = Literal["douyin", "xiaohongshu", "twitter"]
ExtensionE2EAction = Literal[
    "snapshot",
    "scroll",
    "click",
    "like",
    "favorite",
    "share",
    "follow",
    "repost",
    "bookmark",
]
ExtensionE2EActionList = Annotated[list[ExtensionE2EAction], Field(min_length=1)]
ExtensionE2EActionStatus = Literal["ok", "skipped", "failed"]
ExtensionE2ERunStatus = Literal["ok", "partial", "failed", "timeout"]


def _default_extension_e2e_platforms() -> list[ExtensionE2EPlatform]:
    return ["douyin", "xiaohongshu", "twitter"]


class ExtensionE2ERunIn(BaseModel):
    """运行本地浏览器扩展 E2E 模拟的请求。"""

    platforms: list[ExtensionE2EPlatform] = Field(
        default_factory=_default_extension_e2e_platforms,
        min_length=1,
    )
    actions: dict[ExtensionE2EPlatform, ExtensionE2EActionList] = Field(default_factory=dict)
    allow_state_changing: bool = False
    timeout_seconds: int = Field(default=45, ge=5, le=180)


class ExtensionE2EActionResultIn(BaseModel):
    """扩展 E2E runner 上报的单个动作结果。"""

    action: ExtensionE2EAction
    status: ExtensionE2EActionStatus
    detail: str = ""


class ExtensionE2EPlatformResultIn(BaseModel):
    """扩展上报的按平台动作结果。"""

    platform: ExtensionE2EPlatform
    actions: list[ExtensionE2EActionResultIn] = Field(default_factory=list)
    detail: str = ""


class ExtensionE2EResultIn(BaseModel):
    """本地 E2E run 的已签名扩展回调载荷。"""

    run_id: str
    token: str
    platforms: list[ExtensionE2EPlatformResultIn] = Field(default_factory=list)
    error: str = ""


class ExtensionE2EEventMatchOut(BaseModel):
    """与一个所请求扩展动作匹配的、自然产生的后端事件。"""

    event_id: int
    event_type: str
    url: str = ""
    title: str = ""


class ExtensionE2EActionReportOut(BaseModel):
    """单个所请求动作的最终报告。"""

    action: ExtensionE2EAction
    extension_status: ExtensionE2EActionStatus = "skipped"
    extension_executed: bool = False
    extension_detail: str = ""
    backend_event_matched: bool = False
    backend_event: ExtensionE2EEventMatchOut | None = None


class ExtensionE2EPlatformReportOut(BaseModel):
    """单个所请求平台的最终报告。"""

    platform: ExtensionE2EPlatform
    actions: list[ExtensionE2EActionReportOut] = Field(default_factory=list)
    detail: str = ""


class ExtensionE2ERunOut(BaseModel):
    """本地 E2E run 的最终报告。"""

    run_id: str
    status: ExtensionE2ERunStatus
    platforms: list[ExtensionE2EPlatformReportOut] = Field(default_factory=list)
    error: str = ""
    timeout_seconds: int


class FeedbackIn(BaseModel):
    """从 CLI 兼容客户端提交的反馈载荷。"""

    recommendation_id: int
    feedback_type: str
    note: str = ""


class FeedbackResponse(BaseModel):
    """接收推荐反馈后的响应。"""

    ok: bool
    recommendation_id: int
    feedback_type: str


class InsightFeedbackIn(BaseModel):
    """用户对一条具体 insight 假设的确认/拒绝（insight 卡片）。"""

    hypothesis: str
    signal: str  # confirm/like/support (positive) or reject/dislike/deny


class InsightFeedbackResponse(BaseModel):
    """根据用户反馈校准一条 insight 假设后的结果。"""

    ok: bool
    matched: bool
    hypothesis: str = ""
    signal: str = ""
    validated: bool = False
    confidence: float = 0.0


class ProfileEditIn(BaseModel):
    """用户对 AI 生成 profile 覆盖层的一次编辑。

    ``target`` 是一个 onion 字段路径（如 ``core.core_traits``）或一个
    兴趣极性（``likes`` / ``dislikes``）。``op`` ∈
    {set, add, remove, reset}。``parent`` 定位到某个兴趣领域下的具体项；
    ``weight`` 钉住某个兴趣领域的权重。
    """

    target: str
    op: str
    value: str | float | None = None
    parent: str = ""
    weight: float | None = None


class WatchLaterAddIn(BaseModel):
    """将视频加入稍后再看的载荷。"""

    bvid: str
    note: str = ""


class WatchLaterStateResponse(BaseModel):
    """单个视频是否已加入稍后再看，以及总数。"""

    saved: bool
    total: int


class WatchLaterItem(BaseModel):
    """稍后再看列表中的一项。"""

    bvid: str
    title: str = ""
    up_name: str = ""
    cover_url: str = ""
    content_url: str = ""
    source_platform: str = ""
    added_at: str = ""


class WatchLaterListResponse(BaseModel):
    """分页的稍后再看列表。"""

    items: list[WatchLaterItem]
    total: int


class FavoriteAddIn(BaseModel):
    """将视频加入收藏 (收藏) 的载荷。"""

    bvid: str
    note: str = ""


class FavoriteStateResponse(BaseModel):
    """单个视频是否已收藏，以及总数。"""

    saved: bool
    total: int


class FavoriteItem(BaseModel):
    """收藏列表中的一项。"""

    bvid: str
    title: str = ""
    up_name: str = ""
    cover_url: str = ""
    content_url: str = ""
    source_platform: str = ""
    added_at: str = ""


class FavoriteListResponse(BaseModel):
    """分页的收藏列表。"""

    items: list[FavoriteItem]
    total: int


class RecommendationClickIn(BaseModel):
    """来自扩展弹窗的推荐点击穿透载荷。"""

    recommendation_id: int | None = None
    bvid: str = ""
    content_id: str = ""
    content_url: str = ""
    source_platform: str = ""
    title: str = ""
    topic_label: str = ""
    up_name: str = ""
    # v0.3.x event-satisfaction 信号：推荐点击穿透的可选 dwell。
    # 当存在时，这些值流入持久化 click 事件的 metadata，使 storage
    # 分类器可在推荐内容上区分 meaningful_dwell 与 quick_exit。
    watch_seconds: float | None = None
    video_duration_seconds: float | None = None


class RecommendationClickResponse(BaseModel):
    """接收一条推荐点击穿透后的响应。"""

    ok: bool
    bvid: str
    layers_updated: list[str]


class ChatIn(BaseModel):
    """弹窗聊天请求。"""

    message: str


class ChatResponse(BaseModel):
    """弹窗聊天响应。"""

    reply: str


class ChatTurnIn(BaseModel):
    """持久化的弹窗聊天 turn 请求。

    弹窗使用此端点进行生命周期安全的聊天。POST
    快速返回一个 pending turn；后端在后台完成它，
    弹窗在 reload 后通过 ``turn_id`` 轮询。
    """

    message: str
    turn_id: str = ""
    session: str = "popup"
    scope: str = "chat"
    subject_id: str = ""
    subject_title: str = ""


class ChatTurnOut(BaseModel):
    """一个持久化的弹窗聊天 turn。"""

    turn_id: str
    session: str = "popup"
    scope: str = "chat"
    subject_id: str = ""
    subject_title: str = ""
    message: str = ""
    reply: str = ""
    status: str = "pending"
    error: str = ""
    created_at: str = ""
    updated_at: str = ""


class ChatTurnListResponse(BaseModel):
    """持久化的弹窗聊天历史。"""

    items: list[ChatTurnOut]


# --- Configuration API models ---


class LLMProviderConfigOut(BaseModel):
    """LLM provider 配置（默认对 key 做掩码）。"""

    api_key: str = ""
    model: str = ""
    base_url: str = ""
    auth_mode: str = ""
    http_referer: str = ""
    x_title: str = ""
    reasoning_effort: str = ""


class EmbeddingConfigOut(BaseModel):
    provider: str = ""
    model: str = ""
    # v0.3.32+ embedding 拥有自己的凭证；api_key 已做掩码。
    api_key: str = ""
    base_url: str = ""
    output_dimensionality: int = 1024
    similarity_threshold: float = 0.82
    fallback_enabled: bool = False
    fallback_provider: str = ""


class ModuleLLMConfigOut(BaseModel):
    provider: str = ""
    model: str = ""


class LLMConfigOut(BaseModel):
    default_provider: str = "deepseek"
    concurrency: int = 3
    timeout: int = 300
    fallback_enabled: bool = False
    fallback_provider: str = ""
    openai: LLMProviderConfigOut = Field(default_factory=LLMProviderConfigOut)
    claude: LLMProviderConfigOut = Field(default_factory=LLMProviderConfigOut)
    gemini: LLMProviderConfigOut = Field(default_factory=LLMProviderConfigOut)
    deepseek: LLMProviderConfigOut = Field(default_factory=LLMProviderConfigOut)
    ollama: LLMProviderConfigOut = Field(default_factory=LLMProviderConfigOut)
    openrouter: LLMProviderConfigOut = Field(default_factory=LLMProviderConfigOut)
    # v0.3.32+ —— 通用 OpenAI 协议兼容 provider。
    openai_compatible: LLMProviderConfigOut = Field(default_factory=LLMProviderConfigOut)
    embedding: EmbeddingConfigOut = Field(default_factory=EmbeddingConfigOut)
    soul: ModuleLLMConfigOut = Field(default_factory=ModuleLLMConfigOut)
    discovery: ModuleLLMConfigOut = Field(default_factory=ModuleLLMConfigOut)
    recommendation: ModuleLLMConfigOut = Field(default_factory=ModuleLLMConfigOut)
    evaluation: ModuleLLMConfigOut = Field(default_factory=ModuleLLMConfigOut)


class BilibiliConfigOut(BaseModel):
    auth_method: str = "cookie"
    cookie: str = ""
    browser_executable: str = ""
    browser_headed: bool = False


class SourcesBrowserConfigOut(BaseModel):
    cdp_url: str = ""
    headed: bool = False


class BilibiliSourceConfigOut(BaseModel):
    enabled: bool = True


class XiaohongshuSourceConfigOut(BaseModel):
    enabled: bool = False
    daily_search_budget: int = 0
    daily_creator_budget: int = 0
    task_interval_seconds: int = 45


class DouyinSourceConfigOut(BaseModel):
    enabled: bool = False
    mode: str = "direct"
    # 已解析的 Cookie header（env 覆盖，否则 data/douyin_cookie.json）。
    # 设置页的只读镜像 —— 除非 reveal_keys 否则做掩码。
    # PUT 将非空值路由到 DouyinCookieManager，从不写入 config.toml。
    cookie: str = ""
    cookie_env: str = "OPENBILICLAW_DOUYIN_COOKIE"
    daily_search_budget: int = 0
    daily_hot_budget: int = 0
    daily_feed_budget: int = 0
    request_interval_seconds: int = 2


class YoutubeSourceConfigOut(BaseModel):
    enabled: bool = False
    daily_search_budget: int = 0
    daily_trending_budget: int = 0
    daily_channel_budget: int = 0
    request_interval_seconds: int = 2
    min_interval_minutes: int = 60


class TwitterSourceConfigOut(BaseModel):
    enabled: bool = False
    mode: str = "cookie"
    # 已解析的 Cookie header（env 覆盖，否则 data/x_cookie.json）。
    # 设置页的只读镜像 —— 除非 reveal_keys 否则做掩码。
    # PUT 将非空值路由到 XCookieManager，从不写入 config.toml。
    cookie: str = ""
    cookie_env: str = "OPENBILICLAW_X_COOKIE"
    daily_search_budget: int = 0
    daily_feed_budget: int = 0
    daily_creator_budget: int = 0
    request_interval_seconds: int = 3
    min_interval_minutes: int = 60


class ZhihuSourceConfigOut(BaseModel):
    enabled: bool = False
    source_modes: list[str] = Field(
        default_factory=lambda: ["search", "hot", "feed", "creator", "related"]
    )
    daily_search_budget: int = 0
    daily_hot_budget: int = 0
    daily_feed_budget: int = 0
    daily_creator_budget: int = 0
    daily_related_budget: int = 0
    request_interval_seconds: int = 3
    min_interval_minutes: int = 60


class SourcesConfigOut(BaseModel):
    browser: SourcesBrowserConfigOut = Field(default_factory=SourcesBrowserConfigOut)
    bilibili: BilibiliSourceConfigOut = Field(default_factory=BilibiliSourceConfigOut)
    xiaohongshu: XiaohongshuSourceConfigOut = Field(default_factory=XiaohongshuSourceConfigOut)
    douyin: DouyinSourceConfigOut = Field(default_factory=DouyinSourceConfigOut)
    youtube: YoutubeSourceConfigOut = Field(default_factory=YoutubeSourceConfigOut)
    twitter: TwitterSourceConfigOut = Field(default_factory=TwitterSourceConfigOut)
    zhihu: ZhihuSourceConfigOut = Field(default_factory=ZhihuSourceConfigOut)


class SchedulerConfigOut(BaseModel):
    enabled: bool = True
    pause_on_extension_disconnect: bool = False
    extension_disconnect_grace_seconds: int = 90
    discovery_cron: str = "0 */8 * * *"
    pool_target_count: int = 300
    pool_source_shares: dict[str, int] = Field(default_factory=dict)
    account_sync_interval_hours: int = 6
    refresh_check_interval_seconds: int = 60
    signal_event_threshold: int = 6
    feedback_batch_threshold: int = 3
    trending_refresh_hours: int = 3
    explore_refresh_hours: int = 12
    discovery_limit: int = 30
    delight_queue_limit: int = 20
    proactive_push_interval_seconds: int = 120
    speculator_idle_interval_minutes: int = 30
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
    auto_update_enabled: bool = False
    auto_update_check_interval_hours: int = 6
    auto_update_allow_prerelease: bool = False
    auto_update_allowed_remotes: list[str] = Field(default_factory=list)


class DiscoveryConfigOut(BaseModel):
    unified_keyword_planner_enabled: bool = True
    kw_cache_high: int = 30
    kw_cache_low: int = 10
    gen_batch: int = 30
    fetch_batch: int = 5
    history_window_size: int = 150
    history_window_hours: int = 48
    claim_lease_minutes: int = 10
    planner_poll_seconds: int = 120
    plan_ttl_hours: int = 12
    admission_min_score: float = 0.60
    multimodal_evaluation_enabled: bool = False
    multimodal_batch_size: int = 8
    multimodal_image_max_px: int = 384
    multimodal_image_quality: int = 72
    multimodal_image_timeout_seconds: int = 6


class BackendUpdateStatusOut(BaseModel):
    state: str = "unknown"
    auto_update_enabled: bool = False
    install_mode: str = ""
    current_version: str = ""
    latest_version: str = ""
    latest_tag: str = ""
    last_check_at: str = ""
    last_error: str = ""
    reason: str = "none"


class UpdateStatusResponse(BaseModel):
    backend: BackendUpdateStatusOut


class UpdateCheckIn(BaseModel):
    include_backend: bool = True


class UpdateApplyIn(BaseModel):
    target: Literal["backend"]
    tag: str = ""


class UpdateApplyResponse(BaseModel):
    target: str = "backend"
    state: str
    reason: str = "none"
    accepted: bool
    observe_via: str = "runtime-stream"


class StorageConfigOut(BaseModel):
    db_path: str = "data/openbiliclaw.db"


class LoggingConfigOut(BaseModel):
    level: str = "INFO"
    file_level: str = "DEBUG"
    directory: str = "logs"
    filename: str = "openbiliclaw.log"
    file_path: str = "logs/openbiliclaw.log"
    max_file_size_mb: int = 100
    backup_count: int = 1
    aggregate_budget_mb: int = 500
    unmanaged_truncate_mb: int = 200
    unmanaged_max_age_days: int = 30


class AutostartConfigOut(BaseModel):
    enabled: bool = False
    manage_ollama: bool = True


class AutostartStatusOut(BaseModel):
    supported: bool
    enabled: bool
    registered: bool
    can_manage: bool
    platform: str
    mechanism: str
    manage_ollama: bool
    ollama_required: bool
    reason: str = "none"
    detail: str = ""


class AutostartApplyIn(BaseModel):
    enabled: bool


class ConfigIssueOut(BaseModel):
    field: str
    message: str
    severity: str = "warning"


class ConfigResponse(BaseModel):
    """完整的配置响应。"""

    language: str = "zh"
    data_dir: str = "data"
    degraded: bool = False
    degraded_reason: str = ""
    llm: LLMConfigOut = Field(default_factory=LLMConfigOut)
    bilibili: BilibiliConfigOut = Field(default_factory=BilibiliConfigOut)
    sources: SourcesConfigOut = Field(default_factory=SourcesConfigOut)
    scheduler: SchedulerConfigOut = Field(default_factory=SchedulerConfigOut)
    discovery: DiscoveryConfigOut = Field(default_factory=DiscoveryConfigOut)
    autostart: AutostartConfigOut = Field(default_factory=AutostartConfigOut)
    storage: StorageConfigOut = Field(default_factory=StorageConfigOut)
    logging: LoggingConfigOut = Field(default_factory=LoggingConfigOut)
    issues: list[ConfigIssueOut] = Field(default_factory=list)


class ConfigUpdateIn(BaseModel):
    """部分配置更新。仅更新提供的字段。"""

    language: str | None = None
    data_dir: str | None = None
    reset_fields: list[str] | None = None
    suppress_background_llm_work: bool | None = None
    llm: dict[str, object] | None = None
    bilibili: dict[str, object] | None = None
    sources: dict[str, object] | None = None
    scheduler: dict[str, object] | None = None
    discovery: dict[str, object] | None = None
    storage: dict[str, object] | None = None
    logging: dict[str, object] | None = None


class ConfigServiceProbeIn(BaseModel):
    """不写入的请求，用于探测提交的 LLM 或 embedding 配置。"""

    kind: Literal["llm", "embedding"]
    config: dict[str, object] = Field(default_factory=dict)


class ConfigServiceProbeResponse(BaseModel):
    """用户触发的 provider 连通性探测结果。"""

    ok: bool
    kind: Literal["llm", "embedding"]
    provider: str = ""
    model: str = ""
    message: str = ""
    error: str = ""
    latency_ms: int = 0


class SourceShareSuggestionIn(BaseModel):
    """来自尚未保存的设置表单的可选覆盖项。"""

    enabled_sources: dict[str, bool] | None = None
    configured_shares: dict[str, int] | None = None


class ConfigUpdateResponse(BaseModel):
    """配置保存后的响应。"""

    ok: bool = True
    config: ConfigResponse
    message: str = ""
    reloaded: bool = False
    rollback_applied: bool = False
    restart_required: bool = False


class SourceShareSuggestionResponse(BaseModel):
    """基于观察到的源事件计数建议的 source shares。"""

    event_counts: dict[str, int] = Field(default_factory=dict)
    enabled_sources: dict[str, bool] = Field(default_factory=dict)
    suggested_shares: dict[str, int] = Field(default_factory=dict)
