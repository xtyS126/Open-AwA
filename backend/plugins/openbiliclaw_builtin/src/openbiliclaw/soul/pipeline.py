"""画像更新流水线 —— 所有影响画像的信号的统一入口。

所有行为事件、反馈、对话洞察和账号同步数据都流经
`ProfileUpdatePipeline.ingest()`。流水线按目标 onion 层对每条信号
分类、缓冲，并在达到阈值时触发各层更新。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import TYPE_CHECKING, Any
from uuid import uuid4

if TYPE_CHECKING:
    from pathlib import Path

    from openbiliclaw.memory.manager import MemoryManager
    from openbiliclaw.soul.avoidance_speculator import AvoidanceSpeculator
    from openbiliclaw.soul.preference_analyzer import PreferenceAnalyzer
    from openbiliclaw.soul.profile_builder import ProfileBuilder
    from openbiliclaw.soul.speculator import InterestSpeculator

from openbiliclaw.soul.dislike_writeback import (
    apply_new_dislikes,
    topics_for_confirmed_avoidance,
)

logger = logging.getLogger(__name__)


def _coerce_int(value: object, *, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return default
    return default


def _coerce_float(value: object, *, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return default
    return default


# ---------------------------------------------------------------------------
# 枚举
# ---------------------------------------------------------------------------


class SignalType(Enum):
    """信号载荷的判别字段。"""

    BEHAVIOR_EVENT = "behavior_event"
    ENGAGEMENT_EVENT = "engagement_event"
    FEEDBACK = "feedback"
    DIALOGUE_INSIGHT = "dialogue_insight"
    DIALOGUE_TURN = "dialogue_turn"
    ACCOUNT_SNAPSHOT = "account_snapshot"
    # 在扩展弹窗里对推荐卡片的显式点击。
    # 用户信任推荐器才会去打开这个视频 —— 这是一个揭示兴趣与
    # 品味的强正向信号。
    RECOMMENDATION_CLICK = "recommendation_click"


class OnionLayer(Enum):
    """五个 onion 层加上跨层综合。"""

    SURFACE = "surface"
    INTEREST = "interest"
    ROLE = "role"
    VALUES = "values"
    CORE = "core"
    PORTRAIT = "portrait"


# ---------------------------------------------------------------------------
# 信号
# ---------------------------------------------------------------------------

# 表示强兴趣信号的参与度事件类型
_ENGAGEMENT_TYPES = frozenset({"like", "coin", "favorite", "comment"})


@dataclass(frozen=True)
class ProfileSignal:
    """一条可能影响用户画像的证据。"""

    id: str
    signal_type: SignalType
    timestamp: str
    source: str
    payload: dict[str, object]
    target_layers: frozenset[OnionLayer]
    confidence: float = 0.0


# ---------------------------------------------------------------------------
# 层缓冲
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LayerThreshold:
    """各层门控配置。"""

    min_signals: int
    min_interval_seconds: int
    max_buffer_size: int


@dataclass
class LayerBuffer:
    """各层信号累加器。"""

    layer: OnionLayer
    signals: list[dict[str, object]] = field(default_factory=list)
    last_updated_at: str = ""
    update_count: int = 0

    def is_ready(
        self,
        threshold: LayerThreshold,
        now: datetime,
        *,
        has_strong_signal: bool = False,
    ) -> bool:
        """检查本缓冲是否已积攒足够信号且已过足够时间。

        如果 *has_strong_signal* 为 True，min_signals 门限降为 1，
        这样反馈与对话信号能立即更新画像。
        """
        effective_min = 1 if has_strong_signal else threshold.min_signals
        if len(self.signals) < effective_min:
            return False
        if self.last_updated_at:
            try:
                last = datetime.fromisoformat(self.last_updated_at)
                elapsed = (now - last).total_seconds()
                if elapsed < threshold.min_interval_seconds:
                    return False
            except ValueError:
                pass
        return True

    def evict(self, max_size: int) -> None:
        """缓冲超过 max_size 时丢弃最旧的信号。"""
        if len(self.signals) > max_size:
            self.signals = self.signals[-max_size:]

    def drain(self) -> list[dict[str, object]]:
        """移除并返回所有已缓冲的信号。"""
        signals = list(self.signals)
        self.signals = []
        return signals

    def to_dict(self) -> dict[str, object]:
        return {
            "layer": self.layer.value,
            "signals": self.signals,
            "last_updated_at": self.last_updated_at,
            "update_count": self.update_count,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> LayerBuffer:
        layer_str = str(data.get("layer", "surface"))
        try:
            layer = OnionLayer(layer_str)
        except ValueError:
            layer = OnionLayer.SURFACE
        raw_signals = data.get("signals")
        signals = [
            s for s in (raw_signals if isinstance(raw_signals, list) else []) if isinstance(s, dict)
        ]
        return cls(
            layer=layer,
            signals=signals,
            last_updated_at=str(data.get("last_updated_at", "")),
            update_count=_coerce_int(data.get("update_count", 0) or 0),
        )


# ---------------------------------------------------------------------------
# 结果
# ---------------------------------------------------------------------------


@dataclass
class LayerUpdateResult:
    """单次层更新周期的结果。"""

    layer: OnionLayer
    changed: bool
    changes: list[str] = field(default_factory=list)
    signals_consumed: int = 0
    trigger: str = ""
    evidence: str = ""
    timestamp: str = ""


@dataclass
class IngestResult:
    """摄入一条或多条信号的结果。"""

    signals_accepted: int = 0
    layers_buffered: list[str] = field(default_factory=list)
    layers_updated: list[LayerUpdateResult] = field(default_factory=list)


@dataclass
class FlushResult:
    """flush（强制更新）各层的结果。"""

    layers_updated: list[LayerUpdateResult] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 信号分类
# ---------------------------------------------------------------------------

_STATIC_LAYER_MAP: dict[SignalType, frozenset[OnionLayer]] = {
    SignalType.BEHAVIOR_EVENT: frozenset(
        {
            OnionLayer.SURFACE,
            OnionLayer.INTEREST,
            OnionLayer.ROLE,
        }
    ),
    SignalType.ENGAGEMENT_EVENT: frozenset(
        {
            OnionLayer.INTEREST,
            OnionLayer.SURFACE,
            OnionLayer.ROLE,
        }
    ),
    SignalType.FEEDBACK: frozenset(
        {
            OnionLayer.INTEREST,
            OnionLayer.SURFACE,
            OnionLayer.VALUES,
        }
    ),
    SignalType.DIALOGUE_TURN: frozenset({OnionLayer.SURFACE, OnionLayer.INTEREST}),
    SignalType.ACCOUNT_SNAPSHOT: frozenset(
        {
            OnionLayer.INTEREST,
            OnionLayer.SURFACE,
            OnionLayer.ROLE,
        }
    ),
    # 点击揭示即时的话题偏好（INTEREST）和内容风格偏好（SURFACE）。
    # 它不触及 ROLE/VALUES —— 单次点击不足以作为人生阶段或价值观的
    # 证据。
    SignalType.RECOMMENDATION_CLICK: frozenset(
        {
            OnionLayer.INTEREST,
            OnionLayer.SURFACE,
        }
    ),
    SignalType.DIALOGUE_INSIGHT: frozenset(),  # 动态，见 classify_signal
}

# 对话洞察 kind → 目标层
_DIALOGUE_INSIGHT_KIND_MAP: dict[str, frozenset[OnionLayer]] = {
    "interest": frozenset({OnionLayer.INTEREST}),
    "dislike": frozenset({OnionLayer.INTEREST}),
    "value": frozenset({OnionLayer.VALUES}),
    "goal": frozenset({OnionLayer.ROLE}),
    "state": frozenset({OnionLayer.CORE}),
}


def classify_signal(signal_type: SignalType, payload: dict[str, object]) -> frozenset[OnionLayer]:
    """判定一条信号可以影响哪些 onion 层。"""
    if signal_type == SignalType.DIALOGUE_INSIGHT:
        kind = str(payload.get("kind", ""))
        return _DIALOGUE_INSIGHT_KIND_MAP.get(kind, frozenset({OnionLayer.INTEREST}))
    return _STATIC_LAYER_MAP.get(signal_type, frozenset())


# ---------------------------------------------------------------------------
# 默认阈值
# ---------------------------------------------------------------------------

DEFAULT_THRESHOLDS: dict[OnionLayer, LayerThreshold] = {
    OnionLayer.SURFACE: LayerThreshold(
        min_signals=3,
        min_interval_seconds=300,
        max_buffer_size=200,
    ),
    OnionLayer.INTEREST: LayerThreshold(
        min_signals=3,
        min_interval_seconds=600,
        max_buffer_size=200,
    ),
    OnionLayer.ROLE: LayerThreshold(
        min_signals=5,
        min_interval_seconds=86400,
        max_buffer_size=50,
    ),
    OnionLayer.VALUES: LayerThreshold(
        min_signals=5,
        min_interval_seconds=86400,
        max_buffer_size=50,
    ),
    OnionLayer.CORE: LayerThreshold(
        min_signals=8,
        min_interval_seconds=172800,
        max_buffer_size=30,
    ),
}

# 发生变更时触发画像重生成的层
_PORTRAIT_TRIGGER_LAYERS = frozenset({OnionLayer.CORE, OnionLayer.VALUES})

# 参与缓冲的层（PORTRAIT 是条件触发，不缓冲）
_BUFFERED_LAYERS = frozenset(
    {
        OnionLayer.SURFACE,
        OnionLayer.INTEREST,
        OnionLayer.ROLE,
        OnionLayer.VALUES,
        OnionLayer.CORE,
    }
)

# 携带显式用户意图的信号类型。
# 对这些类型，min_signals 门限降为 1，画像立即更新。
_STRONG_SIGNAL_TYPES: frozenset[SignalType] = frozenset(
    {
        SignalType.FEEDBACK,
        SignalType.DIALOGUE_TURN,
        SignalType.DIALOGUE_INSIGHT,
        SignalType.RECOMMENDATION_CLICK,
    }
)
_STRONG_TYPE_VALUES: frozenset[str] = frozenset(st.value for st in _STRONG_SIGNAL_TYPES)


# ---------------------------------------------------------------------------
# 信号工厂辅助函数
# ---------------------------------------------------------------------------


def _make_signal(
    signal_type: SignalType,
    source: str,
    payload: dict[str, object],
    confidence: float = 0.0,
) -> ProfileSignal:
    """创建 ProfileSignal，自动生成 id、时间戳并完成分类。"""
    return ProfileSignal(
        id=uuid4().hex[:12],
        signal_type=signal_type,
        timestamp=datetime.now().isoformat(),
        source=source,
        payload=payload,
        target_layers=classify_signal(signal_type, payload),
        confidence=confidence,
    )


def signals_from_events(events: list[dict[str, Any]]) -> list[ProfileSignal]:
    """把原始行为事件转换为 ProfileSignal 列表。"""
    result: list[ProfileSignal] = []
    for event in events:
        event_type = str(event.get("event_type") or event.get("type") or "")
        if event_type in _ENGAGEMENT_TYPES:
            sig_type = SignalType.ENGAGEMENT_EVENT
        else:
            sig_type = SignalType.BEHAVIOR_EVENT
        result.append(_make_signal(sig_type, "events", dict(event)))
    return result


def signal_from_feedback(
    feedback_type: str,
    title: str,
    note: str = "",
) -> ProfileSignal:
    """把一次推荐反馈动作转换为 ProfileSignal。"""
    return _make_signal(
        SignalType.FEEDBACK,
        "feedback",
        {"feedback_type": feedback_type, "title": title, "note": note},
    )


def signals_from_dialogue(
    candidates: list[dict[str, object]],
) -> list[ProfileSignal]:
    """把对话衍生的洞察候选转换为 ProfileSignal 列表。

    只有达到就绪阈值（confidence >= 0.8 或 occurrences >= 2）的候选
    才应传入这里。
    """
    result: list[ProfileSignal] = []
    for candidate in candidates:
        confidence = _coerce_float(candidate.get("confidence", 0.0) or 0.0)
        result.append(
            _make_signal(
                SignalType.DIALOGUE_INSIGHT,
                "dialogue",
                dict(candidate),
                confidence=confidence,
            )
        )
    return result


def signal_from_dialogue_turn(
    user_message: str,
    assistant_reply: str,
) -> ProfileSignal:
    """把一次原始对话轮次转换为 Surface 层信号。"""
    return _make_signal(
        SignalType.DIALOGUE_TURN,
        "dialogue",
        {"user_message": user_message, "assistant_reply": assistant_reply},
    )


def signals_from_account_sync(events: list[dict[str, Any]]) -> list[ProfileSignal]:
    """把账号同步事件转换为 ProfileSignal 列表。"""
    result: list[ProfileSignal] = []
    for event in events:
        result.append(_make_signal(SignalType.ACCOUNT_SNAPSHOT, "account_sync", dict(event)))
    return result


def signal_from_recommendation_click(
    bvid: str,
    title: str = "",
    *,
    recommendation_id: int | None = None,
    topic_label: str = "",
    up_name: str = "",
    content_id: str = "",
    content_url: str = "",
    source_platform: str = "",
) -> ProfileSignal:
    """把一次推荐点击转换为强画像信号。

    用户主动从推荐中点开这个视频 —— 这是对话题（interest）和呈现
    风格（surface）的高信号正向投票。此信号绕过 min_signals 门限，
    画像立即更新。
    """
    payload: dict[str, object] = {
        "bvid": bvid,
        "title": title,
        "event_type": "recommendation_click",
    }
    if recommendation_id is not None:
        payload["recommendation_id"] = recommendation_id
    if topic_label:
        payload["topic_label"] = topic_label
    if up_name:
        payload["up_name"] = up_name
    if content_id:
        payload["content_id"] = content_id
    if content_url:
        payload["content_url"] = content_url
    if source_platform:
        payload["source_platform"] = source_platform
    return _make_signal(SignalType.RECOMMENDATION_CLICK, "recommendation", payload)


# ---------------------------------------------------------------------------
# 流水线状态持久化
# ---------------------------------------------------------------------------


def _serialize_signal(signal: ProfileSignal) -> dict[str, object]:
    """把 ProfileSignal 转为 JSON 可序列化的 dict 以便缓冲存储。"""
    return {
        "id": signal.id,
        "signal_type": signal.signal_type.value,
        "timestamp": signal.timestamp,
        "source": signal.source,
        "payload": signal.payload,
        "confidence": signal.confidence,
    }


def load_pipeline_state(data_dir: Path) -> dict[str, LayerBuffer]:
    """从磁盘加载流水线缓冲状态。"""
    state_path = data_dir / "memory" / "pipeline_state.json"
    buffers: dict[str, LayerBuffer] = {}
    for layer in _BUFFERED_LAYERS:
        buffers[layer.value] = LayerBuffer(layer=layer)

    if not state_path.exists():
        return buffers

    try:
        with open(state_path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return buffers

    raw_buffers = data.get("buffers")
    if not isinstance(raw_buffers, dict):
        return buffers

    for key, raw_buf in raw_buffers.items():
        if isinstance(raw_buf, dict) and key in buffers:
            buffers[key] = LayerBuffer.from_dict(raw_buf)

    return buffers


def save_pipeline_state(
    data_dir: Path,
    buffers: dict[str, LayerBuffer],
    total_ingested: int = 0,
) -> None:
    """把流水线缓冲状态持久化到磁盘。"""
    memory_dir = data_dir / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    state_path = memory_dir / "pipeline_state.json"

    payload = {
        "version": 1,
        "buffers": {key: buf.to_dict() for key, buf in buffers.items()},
        "last_saved_at": datetime.now().isoformat(),
        "total_signals_ingested": total_ingested,
    }
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# ProfileUpdatePipeline
# ---------------------------------------------------------------------------


class ProfileUpdatePipeline:
    """把所有画像更新信号汇聚到一个统一入口。

    用法：
        pipeline = ProfileUpdatePipeline(memory=..., preference_analyzer=..., ...)
        await pipeline.ingest(signal)       # 缓冲一条信号
        await pipeline.tick()               # 检查并更新就绪的层
        await pipeline.flush()              # 强制更新所有层（初始化）
    """

    def __init__(
        self,
        *,
        memory: MemoryManager,
        preference_analyzer: PreferenceAnalyzer,
        profile_builder: ProfileBuilder,
        thresholds: dict[OnionLayer, LayerThreshold] | None = None,
        speculator: InterestSpeculator | None = None,
        avoidance_speculator: AvoidanceSpeculator | None = None,
        embedding_service: Any | None = None,
        cognition_cycle: Any | None = None,
        speculator_idle_interval_minutes: int = 30,
        profile_consolidator: Any | None = None,
    ) -> None:
        self._memory = memory
        self._preference_analyzer = preference_analyzer
        self._profile_builder = profile_builder
        self._thresholds = thresholds or dict(DEFAULT_THRESHOLDS)
        self._speculator = speculator
        self._avoidance_speculator = avoidance_speculator
        self._embedding_service = embedding_service
        self._cognition_cycle = cognition_cycle
        self._profile_consolidator = profile_consolidator
        data_dir = getattr(memory, "_data_dir", None)
        self._buffers = (
            load_pipeline_state(data_dir)
            if data_dir
            else {layer.value: LayerBuffer(layer=layer) for layer in _BUFFERED_LAYERS}
        )
        self._total_ingested = 0
        # 记录上次运行 speculator tick 的时间，用于在 idle tick 上做节流，
        # 同时仍允许层更新触发新的 speculator pass。详见 `tick()` 主体。
        self._last_speculator_tick_at: datetime | None = None
        # 没有层被更新时，两次 speculator tick 之间的最小间隔。
        # Pipeline.tick 本身每分钟跑一次，但 speculator 只需要周期性
        # expire/promote 检查；30 分钟的 idle 节奏已经足够。
        self._speculator_idle_min_interval = timedelta(minutes=speculator_idle_interval_minutes)

    def set_embedding_service(self, embedding_service: Any) -> None:
        """挂载或替换用于语义操作的 embedding 服务。"""
        self._embedding_service = embedding_service

    def set_cognition_cycle(self, cognition_cycle: Any) -> None:
        """挂载或替换认知周期运行器。"""
        self._cognition_cycle = cognition_cycle

    # -- 公共 API -----------------------------------------------------------

    async def ingest(self, signal: ProfileSignal) -> IngestResult:
        """摄入单条信号：分类、缓冲并检查阈值。"""
        return await self.ingest_batch([signal])

    async def ingest_batch(self, signals: list[ProfileSignal]) -> IngestResult:
        """摄入多条信号，然后检查所有缓冲的就绪状态。"""
        result = IngestResult()
        layers_touched: set[str] = set()

        for signal in signals:
            for layer in signal.target_layers:
                if layer not in _BUFFERED_LAYERS:
                    continue
                buf = self._buffers.get(layer.value)
                if buf is None:
                    continue
                buf.signals.append(_serialize_signal(signal))
                threshold = self._thresholds.get(layer)
                if threshold:
                    buf.evict(threshold.max_buffer_size)
                layers_touched.add(layer.value)

            result.signals_accepted += 1
            self._total_ingested += 1

        result.layers_buffered = sorted(layers_touched)

        # Speculator 观察（轻量关键词匹配）
        if self._speculator or self._avoidance_speculator:
            raw_events = [
                sig.get("payload", {}) if isinstance(sig.get("payload"), dict) else {}
                for signal in signals
                for sig in [{"payload": signal.payload}]
            ]
        else:
            raw_events = []
        if self._speculator:
            self._speculator.observe(raw_events)
        if self._avoidance_speculator:
            self._avoidance_speculator.observe(raw_events)

        # 检查阈值并更新就绪的层。
        # 强信号类型（反馈、对话）绕过 min_signals 门限。
        now = datetime.now()
        for layer in _BUFFERED_LAYERS:
            buf = self._buffers.get(layer.value)
            threshold = self._thresholds.get(layer)
            has_strong = buf is not None and any(
                s.get("signal_type") in _STRONG_TYPE_VALUES for s in buf.signals
            )
            if buf and threshold and buf.is_ready(threshold, now, has_strong_signal=has_strong):
                update_result = await self._update_layer(layer, buf)
                if update_result:
                    result.layers_updated.append(update_result)

        self._save_state()
        return result

    async def tick(self) -> FlushResult:
        """周期性检查：更新任何缓冲已就绪的层。"""
        result = FlushResult()
        now = datetime.now()
        for layer in _BUFFERED_LAYERS:
            buf = self._buffers.get(layer.value)
            threshold = self._thresholds.get(layer)
            has_strong = buf is not None and any(
                s.get("signal_type") in _STRONG_TYPE_VALUES for s in buf.signals
            )
            if buf and threshold and buf.is_ready(threshold, now, has_strong_signal=has_strong):
                update_result = await self._update_layer(layer, buf)
                if update_result:
                    result.layers_updated.append(update_result)

        # Speculator tick：expire → promote → generate。
        # Pipeline.tick 每分钟跑一次，但 speculator 在稳态下不需要
        # 这个节奏 —— 一旦 active 满了且没有变化，再 tick 只是烧 I/O
        # 和制造日志噪音。仅当下列条件成立时才运行：
        #   (a) 这次 pipeline pass 真的 flush 了一个层 —— 画像发生了
        #       实质性变化，可能 probe 已经过时
        #   (b) 距离上次 tick 已经过了一个 idle 间隔（30 分钟）——
        #       兜底机制，让画像稳定但仍与 probe 交互的用户的
        #       expire/promote 仍然能跑
        if self._speculator or self._avoidance_speculator:
            should_tick_speculator = bool(result.layers_updated) or (
                self._last_speculator_tick_at is None
                or now - self._last_speculator_tick_at >= self._speculator_idle_min_interval
            )
            if should_tick_speculator:
                if self._speculator:
                    await self._run_speculator_tick(result)
                if self._avoidance_speculator:
                    try:
                        await self._run_avoidance_speculator_tick(result)
                    except Exception:
                        logger.warning("Avoidance speculator tick failed", exc_info=True)
                self._last_speculator_tick_at = now

        # 认知周期：节流的 awareness + insight 重新生成。
        # 至多每个配置间隔（默认 12h）运行一次。
        if self._cognition_cycle is not None:
            try:
                cog_result = await self._cognition_cycle.run_if_due()
                if cog_result.ran and (
                    cog_result.awareness_generated or cog_result.insight_generated
                ):
                    cog_update = LayerUpdateResult(
                        layer=OnionLayer.PORTRAIT,
                        changed=True,
                        changes=[
                            f"新增观察 {cog_result.awareness_generated} 条，"
                            f"新增洞察 {cog_result.insight_generated} 条",
                        ],
                        trigger="半日深度反思",
                        timestamp=datetime.now().isoformat(),
                    )
                    result.layers_updated.append(cog_update)
            except Exception:
                logger.exception("Cognition cycle failed during pipeline tick")

        # 画像整理：节流的 LLM 裁定的 like/dislike 主题去重，在 64-cap
        # 边界触发（默认每 12h；dirty-check + no-merge memory 让稳态
        # 画像的 tick 几乎零开销）。
        if self._profile_consolidator is not None:
            try:
                cons_report = await self._profile_consolidator.run_if_due()
                if getattr(cons_report, "merges", None) or getattr(
                    cons_report, "rule_merges", None
                ):
                    self._record_consolidation_cognition(cons_report)
                    cons_update = LayerUpdateResult(
                        layer=OnionLayer.INTEREST,
                        changed=True,
                        changes=[
                            f"画像整理: 合并 {len(cons_report.merges)} 组同义主题、"
                            f"{len(cons_report.rule_merges)} 组同名标签",
                        ],
                        trigger="12小时画像整理",
                        timestamp=datetime.now().isoformat(),
                    )
                    result.layers_updated.append(cons_update)
            except Exception:
                logger.exception("Profile consolidation failed during pipeline tick")

        self._save_state()
        return result

    def _record_consolidation_cognition(self, report: Any) -> None:
        """把一次已应用的整理运行展示为一张认知更新卡片。"""
        loader = getattr(self._memory, "load_cognition_updates", None)
        saver = getattr(self._memory, "save_cognition_updates", None)
        if not callable(loader) or not callable(saver):
            return
        merges = list(getattr(report, "merges", []) or [])
        rule_count = len(getattr(report, "rule_merges", []) or [])
        like_count = sum(1 for m in merges if m.get("scope") == "likes")
        dislike_count = sum(1 for m in merges if m.get("scope") == "dislikes")
        parts: list[str] = []
        if like_count or rule_count:
            parts.append(f"兴趣合并 {like_count + rule_count} 组")
        if dislike_count:
            parts.append(f"避雷合并 {dislike_count} 组")
        if not parts:
            return
        examples = "；".join(
            f"{' / '.join(str(x) for x in m.get('members', [])[:2])} → {m.get('canonical')}"
            for m in merges[:2]
        )
        try:
            updates = loader()
            updates.insert(
                0,
                {
                    "id": f"cognition-{uuid4()}",
                    "kind": "profile_consolidation",
                    "summary": f"帮你把画像里重复的主题整理了一下：{'、'.join(parts)}",
                    "impact": "进推荐的兴趣/避雷名额不再被同义重复占用",
                    "reasoning": examples,
                    "evidence": "",
                    "context_line": "12 小时画像整理",
                    "confidence": 1.0,
                    "created_at": datetime.now().isoformat(),
                    "source": "consolidation",
                    "source_label": "画像整理",
                    "expand_hint": "summary_only",
                    "notified": False,
                },
            )
            saver(updates)
        except Exception:
            logger.debug("Failed to record consolidation cognition update", exc_info=True)

    async def flush(
        self,
        *,
        layers: frozenset[OnionLayer] | None = None,
    ) -> FlushResult:
        """无视阈值强制更新指定层。"""
        result = FlushResult()
        target_layers = layers or _BUFFERED_LAYERS
        for layer in target_layers:
            buf = self._buffers.get(layer.value)
            if buf and buf.signals:
                update_result = await self._update_layer(layer, buf)
                if update_result:
                    result.layers_updated.append(update_result)
        self._save_state()
        return result

    # -- 内部 ---------------------------------------------------------------

    async def _update_layer(
        self,
        layer: OnionLayer,
        buf: LayerBuffer,
    ) -> LayerUpdateResult | None:
        """执行层特定的更新并记录结果。"""
        from openbiliclaw.soul.layer_updaters import update_layer

        signals = buf.drain()
        if not signals:
            return None

        try:
            profile = self._load_profile()
            update_result = await update_layer(
                layer=layer,
                signals=signals,
                profile=profile,
                memory=self._memory,
                preference_analyzer=self._preference_analyzer,
                profile_builder=self._profile_builder,
                embedding_service=self._embedding_service,
                llm_service=getattr(self._preference_analyzer, "registry", None),
            )
        except Exception:
            logger.exception("Failed to update layer %s", layer.value)
            # 把信号放回，避免丢失
            buf.signals = signals + buf.signals
            return None

        buf.last_updated_at = datetime.now().isoformat()
        buf.update_count += 1

        if update_result.changed:
            self._save_profile(profile)
            self._record_changelog(update_result)

            # 深层变更时触发画像重生成
            if layer in _PORTRAIT_TRIGGER_LAYERS:
                await self._regenerate_portrait(profile)

        return update_result

    def _load_profile(self) -> Any:
        """从 soul 层加载当前 OnionProfile。"""
        from openbiliclaw.soul.profile import OnionProfile

        soul_data = self._memory.get_layer("soul").data
        if not soul_data:
            return OnionProfile()
        return OnionProfile.from_dict(soul_data)

    def _save_profile(self, profile: Any) -> None:
        """把画像持久化到 soul 层并同步文件。"""
        soul_layer = self._memory.get_layer("soul")
        soul_layer.data.clear()
        soul_layer.data.update(profile.to_dict())
        soul_layer.save()
        self._memory.sync_profile_files(profile)

    async def _regenerate_portrait(self, profile: Any) -> None:
        """在 Core/Values 变更后重新生成 personality_portrait。"""
        from openbiliclaw.soul.layer_updaters import regenerate_portrait

        try:
            new_portrait = await regenerate_portrait(
                profile=profile,
                profile_builder=self._profile_builder,
                memory=self._memory,
            )
            if new_portrait:
                profile.personality_portrait = new_portrait
                self._save_profile(profile)
        except Exception:
            logger.exception("Failed to regenerate portrait")

    def _record_changelog(self, result: LayerUpdateResult) -> None:
        """为一次层更新写一条变更日志。"""
        from openbiliclaw.soul.profile_renderer import render_changelog_entry

        entry = render_changelog_entry(
            timestamp=result.timestamp or datetime.now().isoformat(),
            layer=result.layer.value,
            changes=result.changes,
            trigger=result.trigger,
            evidence=result.evidence,
        )
        self._memory.append_changelog(entry)

    async def _run_speculator_tick(self, result: FlushResult) -> None:
        """运行 speculator 生命周期：expire、promote、generate。"""
        from openbiliclaw.soul.interest_writeback import merge_confirmed_interest

        profile = self._load_profile()
        load_runtime_state = getattr(self._memory, "load_discovery_runtime_state", None)

        def _load_feedback_history() -> object:
            if not callable(load_runtime_state):
                return []
            try:
                runtime_state = load_runtime_state()
                if isinstance(runtime_state, dict):
                    return runtime_state.get("probe_feedback_history", [])
            except Exception:
                logger.debug("Failed to load probe feedback history", exc_info=True)
            return []

        feedback_history = _load_feedback_history()
        tick = self._speculator.tick  # type: ignore[union-attr]
        try:
            tick_result = await tick(
                profile,
                feedback_history=feedback_history,
                feedback_history_loader=_load_feedback_history,
            )
        except TypeError:
            try:
                tick_result = await tick(profile, feedback_history=feedback_history)
            except TypeError:
                tick_result = await tick(profile)

        # 把已确认的猜测兴趣提升进 interest 层
        if tick_result.promoted:
            for spec in tick_result.promoted:
                specifics = [
                    str(getattr(specific, "name", "")).strip()
                    for specific in getattr(spec, "specifics", [])
                    if str(getattr(specific, "name", "")).strip()
                ]
                source = str(getattr(spec, "confirmation_source", "") or "speculated")
                merge_confirmed_interest(
                    profile,
                    domain=str(getattr(spec, "domain", "")),
                    specifics=specifics,
                    source=source,
                    first_seen=str(getattr(spec, "created_at", "")),
                    last_seen=str(getattr(spec, "confirmed_at", "")) or datetime.now().isoformat(),
                )

            self._save_profile(profile)
            changes = [f"猜测兴趣转正: {s.domain}" for s in tick_result.promoted]
            update_result = LayerUpdateResult(
                layer=OnionLayer.INTEREST,
                changed=True,
                changes=changes,
                signals_consumed=0,
                trigger="猜测兴趣确认",
                evidence=", ".join(
                    f"{s.domain}({s.confirmation_count}次确认)" for s in tick_result.promoted
                ),
                timestamp=datetime.now().isoformat(),
            )
            result.layers_updated.append(update_result)
            self._record_changelog(update_result)

    async def _run_avoidance_speculator_tick(self, result: FlushResult) -> None:
        """运行避雷 speculator 生命周期并回写已确认的主题。"""
        profile = self._load_profile()
        load_runtime_state = getattr(self._memory, "load_discovery_runtime_state", None)

        def _load_feedback_history() -> object:
            if not callable(load_runtime_state):
                return []
            try:
                runtime_state = load_runtime_state()
                if isinstance(runtime_state, dict):
                    return runtime_state.get("avoidance_probe_feedback_history", [])
            except Exception:
                logger.debug("Failed to load avoidance probe feedback history", exc_info=True)
            return []

        feedback_history = _load_feedback_history()
        tick = self._avoidance_speculator.tick  # type: ignore[union-attr]
        try:
            tick_result = await tick(
                profile,
                feedback_history=feedback_history,
                feedback_history_loader=_load_feedback_history,
            )
        except TypeError:
            try:
                tick_result = await tick(profile, feedback_history=feedback_history)
            except TypeError:
                tick_result = await tick(profile)

        if not tick_result.promoted:
            return

        topics: list[str] = []
        for avoidance in tick_result.promoted:
            topics.extend(topics_for_confirmed_avoidance(avoidance))
        if not topics:
            return

        changes = await apply_new_dislikes(
            memory=self._memory,
            database=getattr(self._memory, "_database", None),
            embedding_service=self._embedding_service,
            llm_service=getattr(self._preference_analyzer, "registry", None),
            topics=topics,
        )
        if not changes:
            return

        update_result = LayerUpdateResult(
            layer=OnionLayer.INTEREST,
            changed=True,
            changes=changes,
            signals_consumed=0,
            trigger="避雷方向确认",
            evidence=", ".join(
                f"{item.domain}({item.confirmation_count}次确认)" for item in tick_result.promoted
            ),
            timestamp=datetime.now().isoformat(),
        )
        result.layers_updated.append(update_result)
        self._record_changelog(update_result)

    def _save_state(self) -> None:
        """把缓冲状态持久化到磁盘。"""
        data_dir = getattr(self._memory, "_data_dir", None)
        if data_dir:
            save_pipeline_state(data_dir, self._buffers, self._total_ingested)
