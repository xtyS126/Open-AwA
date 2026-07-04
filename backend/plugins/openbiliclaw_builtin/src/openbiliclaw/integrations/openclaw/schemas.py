"""OpenClaw 集成的协议无关请求/响应 DTO。"""

from __future__ import annotations

from dataclasses import dataclass, field

from .errors import AdapterValidationError

_VALID_FEEDBACK_TYPES = {"like", "dislike", "comment", "dismiss"}
_VALID_AVOIDANCE_RESPONSES = {"confirm", "reject", "chat"}


@dataclass(slots=True)
class ProfileResponse:
    """暴露给 OpenClaw 的精简画像摘要。"""

    initialized: bool
    personality_portrait: str = ""
    core_traits: list[str] = field(default_factory=list)
    deep_needs: list[str] = field(default_factory=list)
    top_interests: list[str] = field(default_factory=list)


@dataclass(slots=True)
class RecommendationItem:
    """暴露给 OpenClaw 的单条推荐项。"""

    recommendation_id: int
    bvid: str
    title: str = ""
    up_name: str = ""
    cover_url: str = ""
    reason: str = ""
    topic_label: str = ""
    confidence: float = 0.0


@dataclass(slots=True)
class RecommendationResponse:
    """返回给 OpenClaw 的推荐结果。"""

    items: list[RecommendationItem] = field(default_factory=list)


@dataclass(slots=True)
class FeedbackRequest:
    """从 OpenClaw 接收的规范化反馈载荷。"""

    recommendation_id: int
    feedback_type: str
    note: str = ""

    def __post_init__(self) -> None:
        if self.recommendation_id <= 0:
            raise AdapterValidationError("recommendation_id must be positive.")
        self.feedback_type = self.feedback_type.strip().lower()
        self.note = self.note.strip()
        if self.feedback_type not in _VALID_FEEDBACK_TYPES:
            raise AdapterValidationError(f"Unsupported feedback type: {self.feedback_type}")
        if self.feedback_type == "comment" and not self.note:
            raise AdapterValidationError("Comment feedback requires note.")


@dataclass(slots=True)
class FeedbackResponse:
    """返回给 OpenClaw 的反馈受理结果。"""

    ok: bool
    recommendation_id: int
    feedback_type: str


@dataclass(slots=True)
class RuntimeStatusResponse:
    """暴露给 OpenClaw 的精简运行时状态摘要。"""

    initialized: bool
    recommendation_count: int
    pending_signal_events: int
    unread_count: int
    pool_available_count: int = 0
    pool_target_count: int = 0
    last_discovered_count: int = 0
    last_refresh_at: str = ""
    last_account_sync_at: str = ""
    last_account_sync_error: str = ""


@dataclass(slots=True)
class SyncAccountResponse:
    """返回给 OpenClaw 的账号同步摘要。"""

    synced: bool
    new_event_count: int
    errors: list[str] = field(default_factory=list)


@dataclass(slots=True)
class DelightItem:
    """暴露给 OpenClaw 的单条主动惊喜推荐。"""

    bvid: str
    title: str = ""
    delight_reason: str = ""
    delight_score: float = 0.0
    delight_hook: str = ""
    cover_url: str = ""


@dataclass(slots=True)
class DelightResponse:
    """返回给 OpenClaw 的主动惊喜推荐结果。"""

    item: DelightItem | None = None


@dataclass(slots=True)
class ChatRequest:
    """从 OpenClaw 接收的规范化对话载荷。"""

    message: str
    session: str = "openclaw"

    def __post_init__(self) -> None:
        self.message = self.message.strip()
        self.session = self.session.strip() or "openclaw"
        if not self.message:
            raise AdapterValidationError("chat message must not be empty.")


@dataclass(slots=True)
class ChatResponse:
    """返回给 OpenClaw 的苏格拉底式对话回复。"""

    reply: str
    session: str = "openclaw"


@dataclass(slots=True)
class InterestProbeItem:
    """agent 想让用户确认的单个推测性兴趣假设。

    ``question`` 是 OpenClaw 可以原样抛给用户的现成提示；
    ``domain`` / ``category`` / ``reason`` / ``confidence`` / ``specifics``
    暴露原始假设数据，以便 agent 在偏好时可以重新表述。
    """

    domain: str
    category: str = ""
    reason: str = ""
    confidence: float = 0.0
    weight: float = 0.0
    experience_mode: str = ""
    entry_load: str = ""
    specifics: list[str] = field(default_factory=list)
    question: str = ""


@dataclass(slots=True)
class InterestProbeResponse:
    """返回给 OpenClaw 的下一个兴趣确认探测。"""

    probe: InterestProbeItem | None = None


@dataclass(slots=True)
class AvoidanceProbeItem:
    """agent 想让用户确认的单个推测性避雷假设。"""

    domain: str
    reason: str = ""
    confidence: float = 0.0
    weight: float = 0.0
    source_mode: str = ""
    source_signal: str = ""
    experience_mode: str = ""
    entry_load: str = ""
    specifics: list[str] = field(default_factory=list)
    question: str = ""


@dataclass(slots=True)
class AvoidanceProbeResponse:
    """返回给 OpenClaw 的下一个避雷确认探测。"""

    probe: AvoidanceProbeItem | None = None


@dataclass(slots=True)
class AvoidanceProbeFeedbackRequest:
    """用户对推测性避雷探测的回复。"""

    domain: str
    response: str
    message: str = ""

    def __post_init__(self) -> None:
        self.domain = self.domain.strip()
        self.response = self.response.strip().lower()
        self.message = self.message.strip()
        if not self.domain:
            raise AdapterValidationError("avoidance probe domain must not be empty.")
        if self.response not in _VALID_AVOIDANCE_RESPONSES:
            allowed = ", ".join(sorted(_VALID_AVOIDANCE_RESPONSES))
            raise AdapterValidationError(f"avoidance probe response must be one of: {allowed}.")


@dataclass(slots=True)
class AvoidanceProbeFeedbackResponse:
    """记录用户对推测性避雷探测反馈的结果。"""

    ok: bool
    action: str
    domain: str
    reply: str = ""
