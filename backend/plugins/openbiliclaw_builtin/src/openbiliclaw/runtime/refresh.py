"""本地 API runtime 的持续刷新控制器。"""

from __future__ import annotations

import asyncio
import inspect
import logging
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Protocol, cast

from openbiliclaw.config import SchedulerConfig
from openbiliclaw.discovery.pool_snapshot import (
    build_cold_start_pool_snapshot,
    build_pool_distribution_snapshot,
)
from openbiliclaw.recommendation.delight import DEFAULT_DELIGHT_THRESHOLD
from openbiliclaw.runtime.image_cache import (
    cleanup_image_cache,
    prefetch_cover,
    select_prefetch_targets,
)
from openbiliclaw.runtime.keyword_fetch import PLATFORM_BILIBILI as _KW_PLATFORM_BILIBILI
from openbiliclaw.runtime.presence import PresenceTracker, background_llm_work_allowed
from openbiliclaw.soul.avoidance_speculator import choose_next_avoidance_candidate
from openbiliclaw.soul.speculator import (
    _normalize_probe_mode,
    build_probe_axis,
    choose_next_probe_candidate,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from openbiliclaw.runtime.task_registry import BackgroundTaskRegistry

logger = logging.getLogger(__name__)

_MAX_DISCOVERY_BACKFILL_PER_REFRESH = 60
_DEFAULT_CANDIDATE_EVAL_BATCH_SIZE = 45
_DISCOVERY_REPLENISH_LOW_WATERMARK_RATIO = 0.90
_BILIBILI_EXPENSIVE_DISCOVERY_GAP_RATIO = 0.20
_BILIBILI_EXPENSIVE_DISCOVERY_MIN_GAP = 20
# 封面图磁盘缓存被清理（已消费 + 未保存封面）的频率。
# 批量一次性清理在 API 启动时运行；这是稳态扫描。
_IMAGE_CACHE_CLEANUP_INTERVAL_SECONDS = 6 * 60 * 60
# Discovery 时封面预取：在 CDN token 仍新鲜时缓存封面
# （XHS 签名 URL 快速过期）。频繁运行，按最新优先扫描最近发现，
# 且每 tick 有界因此永不淹没 CDN。
_COVER_PREFETCH_INTERVAL_SECONDS = 60
_COVER_PREFETCH_RECENT_HOURS = 12
_COVER_PREFETCH_SCAN = 300
_COVER_PREFETCH_MAX_FETCH = 40
_DEFAULT_PLATFORM_SOURCE_SHARES: dict[str, int] = {
    "bilibili": 5,
}
_PLATFORM_SOURCE_ORDER = ("bilibili", "xiaohongshu", "douyin", "youtube", "twitter", "zhihu")
_BILIBILI_DISCOVERY_SOURCES = ("search", "related_chain", "trending", "explore")
_PROBE_CHALLENGE_MODES = {"lateral", "bridge", "wildcard"}


def _call_accepts_limit(fn: Any) -> bool:
    """返回一个 producer callable 是否接受 ``limit=`` 关键字参数。"""
    try:
        signature = inspect.signature(fn)
    except (TypeError, ValueError):
        return True
    return "limit" in signature.parameters or any(
        param.kind is inspect.Parameter.VAR_KEYWORD for param in signature.parameters.values()
    )


def _call_accepts_strategy_limits(fn: Any) -> bool:
    """返回一个 discovery callable 是否接受 ``strategy_limits=``。"""
    try:
        signature = inspect.signature(fn)
    except (TypeError, ValueError):
        return True
    return "strategy_limits" in signature.parameters or any(
        param.kind is inspect.Parameter.VAR_KEYWORD for param in signature.parameters.values()
    )


def _call_accepts_pool_snapshot(fn: Any) -> bool:
    """返回一个 discovery callable 是否接受 ``pool_snapshot=``。"""
    try:
        signature = inspect.signature(fn)
    except (TypeError, ValueError):
        return True
    return "pool_snapshot" in signature.parameters or any(
        param.kind is inspect.Parameter.VAR_KEYWORD for param in signature.parameters.values()
    )


def _call_accepts_keywords(fn: Any) -> bool:
    """返回一个 discovery callable 是否接受 ``keywords=`` 关键字参数。

    用于 direct-engine B 站 search 回退路径，使统一 keyword
    planner 注入的词仅转发给声明了该 kwarg 的 engine/stub ——
    未声明它的 stub 保持字节兼容（flag 关闭 / 测试）。
    """
    try:
        signature = inspect.signature(fn)
    except (TypeError, ValueError):
        return True
    return "keywords" in signature.parameters or any(
        param.kind is inspect.Parameter.VAR_KEYWORD for param in signature.parameters.values()
    )


def _call_accepts_keyword_ids(fn: Any) -> bool:
    """返回一个 discovery callable 是否接受 ``keyword_ids=`` 关键字参数。

    :func:`_call_accepts_keywords` 的 P1.8 并行版本，用于 direct-engine
    B 站 search 回退，使 keyword→id 溯源 map 仅转发给声明了它的 engine；
    未声明它的 stub 保持字节兼容。
    """
    try:
        signature = inspect.signature(fn)
    except (TypeError, ValueError):
        return True
    return "keyword_ids" in signature.parameters or any(
        param.kind is inspect.Parameter.VAR_KEYWORD for param in signature.parameters.values()
    )


def _string_state_map(value: object) -> dict[str, str]:
    """将一个 JSON 对象字段规范化为 string-to-string map。"""
    if not isinstance(value, dict):
        return {}
    return {str(key): str(item) for key, item in value.items()}


class SupportsRuntimeState(Protocol):
    def load_discovery_runtime_state(self) -> dict[str, object]: ...
    def save_discovery_runtime_state(self, state: dict[str, object]) -> None: ...
    def update_discovery_runtime_state(
        self,
        mutator: Callable[[dict[str, object]], dict[str, object] | None],
    ) -> dict[str, object]: ...
    def get_layer(self, name: str) -> Any: ...


class SupportsEventDatabase(Protocol):
    def query_events_since(
        self,
        *,
        after_event_id: int,
        event_types: list[str],
    ) -> list[dict[str, Any]]: ...
    def get_latest_event_id(self) -> int: ...
    def count_recommendations(self) -> int: ...
    def count_unread_recommendations(self) -> int: ...
    def count_pool_candidates(self, *, xhs_self_nickname: str = "") -> int: ...
    def count_pool_readiness(self, *, xhs_self_nickname: str = "") -> dict[str, int]: ...
    def count_pool_candidates_by_source(self) -> dict[str, int]: ...
    def count_pool_available_candidates_by_source(
        self, *, max_per_topic_group: int = 3, xhs_self_nickname: str = ""
    ) -> dict[str, int]: ...
    def count_pool_raw_material_candidates(self) -> int: ...
    def count_pool_raw_material_by_source(self) -> dict[str, int]: ...
    def get_pool_distribution_counts(self) -> dict[str, dict[str, int]]: ...
    def trim_explore_cluster_overflow(self, *, max_per_cluster: int = 3) -> int: ...
    def trim_topic_group_overflow(self, *, max_per_group: int) -> int: ...
    def trim_pool_to_target_count(
        self,
        *,
        target: int,
        source_share_quotas: dict[str, int] | None = None,
    ) -> int: ...
    def trim_pool_source_overflow(self, *, source_share_quotas: dict[str, int]) -> int: ...
    def reactivate_under_quota_pool_sources(
        self,
        *,
        target: int,
        source_share_quotas: dict[str, int],
        raw_source_share_quotas: dict[str, int] | None = None,
    ) -> int: ...
    def evict_stale_pool_items(self, *, max_age_days: int = 14) -> int: ...
    def iter_cover_lifecycle(self) -> list[tuple[str, str, bool]]: ...
    def iter_servable_cover_urls(
        self, *, recent_hours: int = 12, limit: int = 300
    ) -> list[str]: ...
    def get_notification_candidate(
        self,
        *,
        min_confidence: float = 0.82,
    ) -> dict[str, Any] | None: ...
    def mark_notification_sent(self, bvid: str) -> None: ...
    def get_delight_candidate(
        self,
        *,
        min_delight_score: float = DEFAULT_DELIGHT_THRESHOLD,
    ) -> dict[str, Any] | None: ...
    def get_delight_candidates(
        self,
        *,
        min_delight_score: float = DEFAULT_DELIGHT_THRESHOLD,
        limit: int = 20,
    ) -> list[dict[str, Any]]: ...
    def mark_delight_notified(self, bvid: str) -> None: ...
    def count_delight_candidates(
        self,
        *,
        min_delight_score: float = DEFAULT_DELIGHT_THRESHOLD,
    ) -> int: ...


class SupportsProfileEngine(Protocol):
    async def get_profile(self) -> Any: ...

    # 有效 disliked topics（AI dislikes + 平铺 preference dislikes，已应用
    # user override）。被 proactive-delight 硬过滤器使用，使手动添加的
    # dislike 生效过滤，手动移除的不生效。
    def get_effective_disliked_topics(self) -> list[str]: ...

    # 可选：soul engine 暴露一个 ProfileUpdatePipeline，refresh loop
    # 周期性 tick。该属性在较老的 test double 上可能缺失，因此调用方应
    # `getattr(..., "pipeline", None)`。
    @property
    def pipeline(self) -> Any: ...


class SupportsDiscoveryEngine(Protocol):
    async def discover(
        self,
        profile: Any,
        strategies: list[str] | None = None,
        limit: int = 30,
        *,
        strategy_limits: dict[str, int] | None = None,
        pool_snapshot: Any | None = None,
        fully_parallel: bool = False,
    ) -> list[Any]: ...


class SupportsRecommendationEngine(Protocol):
    async def generate_recommendations(
        self,
        discovered: list[Any] | None,
        profile: Any,
        limit: int = 10,
    ) -> list[Any]: ...

    async def precompute_pool_copy(
        self,
        *,
        profile: Any,
        limit: int,
    ) -> int: ...

    async def prewarm_supergroup_embeddings(self) -> int: ...

    async def prewarm_pool_mmr_embeddings(self, *, limit: int = 200) -> int: ...


# guided-init 池回填的分阶段 strategy plan（gui-init spec §5d）。
# 镜像 cli._INIT_DISCOVERY_PLAN；B2 整合 CLI 复用此 plan。
_INIT_DISCOVERY_PLAN: list[list[str]] = [
    ["search", "trending", "related_chain", "explore"],
]


@dataclass
class ContinuousRefreshController:
    """在 API runtime 期间保持 discovery 缓存和推荐新鲜。"""

    memory_manager: SupportsRuntimeState
    database: SupportsEventDatabase
    soul_engine: SupportsProfileEngine
    discovery_engine: SupportsDiscoveryEngine
    recommendation_engine: SupportsRecommendationEngine
    event_hub: Any | None = None
    discovery_candidate_pipeline: Any | None = None
    bilibili_producer: Any | None = None
    xhs_producer: Any | None = None
    douyin_producer: Any | None = None
    youtube_producer: Any | None = None
    x_producer: Any | None = None
    zhihu_producer: Any | None = None
    scheduler_config: Any = field(default_factory=SchedulerConfig)
    presence: PresenceTracker = field(default_factory=PresenceTracker)
    # gui-init D1：可选的 init 感知门控。当它返回 True（一个 guided init
    # 处于活动状态）时，所有后台 loop 暂停以免与 init 的显式
    # analyze/build 竞争。``run_init_backfill`` 绕过此门控（它从不调用
    # ``_llm_work_allowed``），因此 init 自身的 discovery 不会被自身阻塞。
    init_active_check: Callable[[], bool] | None = None
    signal_event_threshold: int = 6
    event_refresh_minutes: int = 0
    trending_refresh_hours: int = 3
    explore_refresh_hours: int = 12
    notification_cooldown_hours: int = 2
    delight_cooldown_hours: int = 4
    check_interval_seconds: int = 60
    # Proactive probe-push loop 运行频率比主 refresh loop 低得多。
    # Probe 不是流式内容 —— 一旦 active set 已交付，再次 push 的唯一
    # 理由是 slot 轮换（用户反馈 / TTL）。10 min 足以浮现新生成的
    # probe 而不会轰炸用户。
    # 2026-05-04 之前默认是 600s（10 min）。在那个节奏下新 delight
    # 需要长达 10 分钟才能在弹窗浮现，加上 proactive_push 每 tick
    # 仅发送一个候选。120s 是一个更紧的回退，同时保持 chrome-notification
    # 冷却不变（它们有自己的去重窗口）。主要 push 路径仍然是在
    # ``_run_refresh_plan`` 结束时一旦新候选评分完成就立即发送的
    # ``delight.refreshed`` 事件 —— 此 interval 是无 refresh 窗口通过
    # 其他路径（手动 rescore、init）产生 delight 时的安全网。
    proactive_push_interval_seconds: int = 120
    # Soul pipeline tick 每分钟运行以排空 buffer，但 pipeline 内的
    # speculator 不需要那个节奏 —— 它的门控现在上游在 pipeline.tick()
    # 中处理。保留显式以便测试中可调。
    discovery_limit: int = 30
    pool_target_count: int = 300
    pool_source_shares: dict[str, int] = field(
        default_factory=lambda: dict(_DEFAULT_PLATFORM_SOURCE_SHARES)
    )
    # v0.3.63+：可选注册表，使 detached 任务（manual-refresh 后台工作、
    # per-strategy precompute fire-and-forget）可被
    # ``RuntimeContext.rebuild_from_config`` 在下一个 runtime 启动前
    # 取消。``_track_task`` 在此为 ``None`` 时使用裸 ``create_task``，
    # 使直接构建 controller 而不注入注册表的现有测试继续工作。
    task_registry: BackgroundTaskRegistry | None = None
    # P1.6：统一 keyword planner（deficit-pulled 合并 keyword 生成）。
    # 在 ``api/runtime_context.py`` 中作为独立对象构造，因为 controller
    # 不持有 ``llm_service``。其 loop 由 ``run_forever`` 启动；feature
    # flag 关闭时（默认）loop 是纯 no-op，因此接入它是零行为变更。
    # ``None``（默认，由直接构建 controller 的测试使用）意味着 planner
    # loop 立即返回。
    keyword_planner: Any | None = None
    # P1.7：统一 keyword planner FETCH 协调器。在 flag 开启时驱动 B 站
    # search inline-admit 生命周期（claim → 注入为 ``queries`` →
    # used / failed）。在 ``api/runtime_context.py`` 中构造；``None``
    # （测试 / flag 关闭）→ B 站 search 保持其 legacy 自生成路径。
    keyword_fetch: Any | None = None
    _manual_refresh_task: asyncio.Task[None] | None = None
    _discovery_drain_lock: asyncio.Lock = field(
        default_factory=asyncio.Lock,
        init=False,
        repr=False,
    )
    # v0.3.62+ 全局 "skip-if-busy" 门控。直接 refresh 执行被有意集中化：
    # 周期性 tick 调用 ``refresh_if_needed``；用户/手动补货调用
    # ``force_refresh``。Event/feedback/init 路径仅 queue 一个 reason
    # 并等待统一调度器。
    # 没有这个锁，一个慢的周期性 tick（WBI 速率限制下 10+ 分钟）可能
    # 与手动 refresh + per-event 机会性 refresh 并发运行，放大对 Bilibili
    # 的负载并导致 SQLite 写竞争。在 ``refresh_if_needed`` 内通过
    # ``async with`` 获取；如果已被持有，新调用方立即以
    # ``{"skipped": True, ...}`` 退出而非排队。
    _refresh_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)
    _manual_refresh_state: str = "idle"
    _manual_refresh_message: str = ""
    _manual_refresh_started_at: str = ""
    _manual_refresh_finished_at: str = ""
    _pending_replenishment_reasons: set[str] = field(default_factory=set, init=False)
    # 上次 tick 的 pool maintenance 状态指纹，用于将每分钟的
    # "reactivated=N" / "trim dropped=N top=X" 日志行降级到 DEBUG
    # 当自上次 tick 以来没有实际变化时。INFO 仅在计数或 top-group
    # 轮换时触发。
    _last_pool_maintenance_fingerprint: tuple[int, int, str] = (-1, -1, "")
    _warned_pool_count_fallbacks: set[str] = field(default_factory=set, init=False)
    # 上次通过 runtime 事件流发送的 pool_available 计数，使弹窗侧的
    # ``mergeRuntimeStatusEvent`` 仅在数字实际变化时才重新渲染 ——
    # 见 ``_publish_pool_status_if_changed``。
    _last_published_pool_count: int = -1
    # soul profile 首次检测到时从 false 翻转为 true。被 ``_loop_refresh``
    # 用于在 init 的 analyze_events 完成那一刻触发一次性的
    # ``classify_pool_backlog`` —— 否则在约 7 分钟 init 窗口期间摄入
    # 的项会一直未分类直到下一个自然 refresh tick（而 recommendation
    # summary 会打印回退的 ``topic_group="title[:N]"`` 直到那时）。
    _profile_ready_observed: bool = False
    # v0.3.61+：daemon 启动后跳过第一次 ``refresh_if_needed`` 调用，
    # 给 Bilibili 一个 30s 冷却窗口。Init 的同步块（history 获取 +
    # favorites + following）在前 ~10s 内重击 WBI search 后端；
    # 紧接着触发 discovery search 查询会例行触发 v_voucher 风暴。
    # 一次 refresh tick 的宽限 = 头半小时内大幅减少耗尽重试。
    _init_grace_consumed: bool = False
    _last_llm_gate_allowed: bool = field(default=True, init=False)

    _signal_event_types = [
        "view",
        "search",
        "favorite",
        "like",
        "coin",
        "comment",
        "feedback",
    ]

    def _llm_work_allowed(self) -> bool:
        """返回 daemon 拥有的后台 LLM / embedding 工作是否可以运行。"""
        # guided init 活动时暂停所有后台 loop（gui-init D1）——
        # continuous refresh / soul-pipeline / producer tick 都门控于此，
        # 因此 init 的显式 analyze/build/backfill 无竞争运行。
        if self.init_active_check is not None:
            try:
                if self.init_active_check():
                    return False
            except Exception:
                pass
        allowed = background_llm_work_allowed(self.scheduler_config, self.presence)
        if allowed != self._last_llm_gate_allowed:
            logger.info(
                "Background LLM work gate %s",
                "allowed" if allowed else "blocked",
            )
            self._last_llm_gate_allowed = allowed
        return allowed

    def _xhs_self_nickname(self) -> str:
        """返回持久化的 XHS self 昵称用于 pool 守卫。"""
        try:
            state = self.memory_manager.load_discovery_runtime_state()
        except Exception:
            return ""
        info = state.get("xhs_self_info")
        if not isinstance(info, dict):
            return ""
        return str(info.get("nickname", "") or "").strip()

    def _pool_readiness_counts(self) -> dict[str, int]:
        """为 status payload 返回规范化的 pool readiness 计数。"""
        nickname = self._xhs_self_nickname()
        try:
            readiness = self.database.count_pool_readiness(xhs_self_nickname=nickname)
            available = int(readiness.get("available", 0))
            return {
                "available": max(0, available),
                "raw": max(0, int(readiness.get("raw", available))),
                "pending": max(0, int(readiness.get("pending", 0))),
                "pending_eval": max(0, int(readiness.get("pending_eval", 0))),
                "evaluated_pending": max(0, int(readiness.get("evaluated_pending", 0))),
            }
        except Exception:
            available = int(self.database.count_pool_candidates(xhs_self_nickname=nickname))
            return {
                "available": max(0, available),
                "raw": max(0, available),
                "pending": 0,
                "pending_eval": 0,
                "evaluated_pending": 0,
            }

    @staticmethod
    def _pool_count_payload(counts: dict[str, int]) -> dict[str, int]:
        return {
            "pool_available_count": int(counts.get("available", 0)),
            "pool_raw_count": int(counts.get("raw", counts.get("available", 0))),
            "pool_pending_count": int(counts.get("pending", 0)),
            "pool_pending_eval_count": int(counts.get("pending_eval", 0)),
            "pool_evaluated_pending_count": int(counts.get("evaluated_pending", 0)),
        }

    def get_runtime_status(self) -> dict[str, object]:
        """为弹窗或诊断构建轻量级 runtime 摘要。"""
        state = self.memory_manager.load_discovery_runtime_state()
        refresh_values = [
            str(state.get("last_event_refresh_at", "")),
            str(state.get("last_trending_refresh_at", "")),
            str(state.get("last_explore_refresh_at", "")),
        ]
        parsed_refresh_values: list[datetime] = []
        for value in refresh_values:
            parsed = self._parse_iso_datetime(value)
            if parsed is not None:
                parsed_refresh_values.append(parsed)
        last_refresh_at = max(parsed_refresh_values).isoformat() if parsed_refresh_values else ""
        pending_delight_count = 0
        with suppress(Exception):
            pending_delight_count = self.database.count_delight_candidates(
                min_delight_score=DEFAULT_DELIGHT_THRESHOLD,
            )
        pool_counts = self._pool_readiness_counts()
        return {
            "initialized": self._is_initialized(),
            "recommendation_count": self.database.count_recommendations(),
            "pending_signal_events": self._pending_signal_events_count(state),
            "last_refresh_at": last_refresh_at,
            "last_notification_at": str(state.get("last_notification_at", "")),
            "unread_count": self.database.count_unread_recommendations(),
            **self._pool_count_payload(pool_counts),
            "pool_target_count": self.pool_target_count,
            "last_discovered_count": self._int_state_value(state, "last_discovered_count"),
            "last_replenished_count": self._int_state_value(state, "last_replenished_count"),
            "recent_pool_topics": self._list_state_value(state, "recent_pool_topics"),
            "manual_refresh_state": self._manual_refresh_state,
            "manual_refresh_message": self._manual_refresh_message,
            "pending_delight_count": pending_delight_count,
            "last_delight_notification_at": str(state.get("last_delight_notification_at", "")),
        }

    async def refresh_if_needed(self) -> dict[str, object]:
        """当阈值满足时刷新 discovery 候选。

        Runtime 补货现在有一个决策路径：周期性调度器调用此方法，
        而 event / feedback / init hook 仅通过 ``request_replenishment``
        queue 一个 reason。一个模块级 ``_refresh_lock``（一个
        ``asyncio.Lock``）在最顶部检查：如果另一个 refresh 已在进行中，
        此调用立即返回 ``{"skipped": True, "reason": "another refresh holds lock"}``
        而非排队。剩余主体在 ``async with self._refresh_lock:`` 内运行，
        因此即使异常路径锁也被释放。

        内部 helper（``_run_refresh_plan``、``force_refresh``）有意不
        获取此锁 —— 仅公共 ``refresh_if_needed`` 入口获取，因此从不同
        路径到达它的调用方不会双重获取。
        """
        if not self._llm_work_allowed():
            return {"refreshed": False, "strategies": [], "reason": "llm_paused"}

        if self._refresh_lock.locked():
            logger.debug("refresh_if_needed skipped: another refresh in flight")
            return {"skipped": True, "reason": "another refresh holds lock"}

        async with self._refresh_lock:
            state = self.memory_manager.load_discovery_runtime_state()
            queued_reasons = self._consume_replenishment_reasons()

            def _result(payload: dict[str, object]) -> dict[str, object]:
                if queued_reasons:
                    payload["queued_reasons"] = queued_reasons
                return payload

            if not self._is_initialized():
                return _result({"refreshed": False, "strategies": [], "reason": "not_initialized"})

            pool_at_cap = self._enforce_pool_cap()
            await self._publish_pool_status_if_changed()
            if pool_at_cap:
                return _result({"refreshed": False, "strategies": [], "reason": "pool_at_cap"})

            profile = await self.soul_engine.get_profile()
            plan = self._build_refresh_plan(state)
            if not plan:
                return _result({"refreshed": False, "strategies": [], "reason": "below_threshold"})

            return await self._run_refresh_plan(
                state=state,
                profile=profile,
                plan=plan,
                reason="triggered",
            )

    async def run_init_backfill(
        self,
        profile: Any,
        target_pool_count: int,
        *,
        fully_parallel: bool = True,
    ) -> int:
        """为 guided init 回填初始 discovery 池。

        持有 ``_refresh_lock`` 使其与 continuous refresh 串行化并永不
        与其在 ``content_cache`` 上竞争（gui-init spec §5d）。镜像 CLI
        的分阶段 ``_INIT_DISCOVERY_PLAN`` 回填，但针对此 controller 的
        实时 ``discovery_engine``/``database``。协作式取消：``async with``
        在 ``CancelledError`` 时释放锁。返回发现的项总数。
        """
        discovered_count = 0
        async with self._refresh_lock:
            for strategies in _INIT_DISCOVERY_PLAN:
                current = self.database.count_pool_candidates()
                if current >= target_pool_count:
                    break
                request_limit = max(20, target_pool_count - current)
                pool_snapshot = self._build_init_pool_snapshot(
                    profile,
                    current_pool_count=current,
                    target_pool_count=target_pool_count,
                )
                discovered = await self.discovery_engine.discover(
                    profile,
                    strategies=strategies,
                    limit=request_limit,
                    fully_parallel=fully_parallel,
                    pool_snapshot=pool_snapshot,
                )
                discovered_count += len(discovered)
        return discovered_count

    def _build_init_pool_snapshot(
        self,
        profile: Any,
        *,
        current_pool_count: int,
        target_pool_count: int,
    ) -> Any | None:
        if current_pool_count <= 0:
            return build_cold_start_pool_snapshot(
                profile,
                pool_target_count=target_pool_count,
                source_targets=self._source_target_counts(total=target_pool_count),
            )
        try:
            return build_pool_distribution_snapshot(
                self.database,
                pool_target_count=target_pool_count,
                source_targets=self._source_target_counts(total=target_pool_count),
            )
        except Exception:
            logger.debug("init backfill pool snapshot unavailable", exc_info=True)
            return None

    async def force_refresh(self) -> dict[str, object]:
        """立即运行完整 refresh，绕过 runtime 阈值。

        在单次 discover() 调用中运行全部 4 个 Bilibili strategy，使它们
        通过 asyncio.gather 并发执行，最大化池多样性。池 target 仍作为
        硬上限应用 —— 如果池已满，不运行 discovery 并修剪溢出。

        v0.3.62+：也获取 ``_refresh_lock`` 使手动 refresh（调用
        ``force_refresh`` 而非 ``refresh_if_needed``）尊重全局
        skip-if-busy 门控。没有这个，周期性 + 手动 / pool-low refresh
        过去通过不同代码路径运行，放大 Bilibili API 负载和 SQLite 写
        竞争。Skip 语义匹配 ``refresh_if_needed``：立即返回
        ``{"refreshed": False, "reason": "another refresh holds lock"}``
        而非排队。
        """
        if self._refresh_lock.locked():
            logger.debug("force_refresh skipped: another refresh in flight")
            return {
                "refreshed": False,
                "strategies": [],
                "reason": "another refresh holds lock",
            }
        async with self._refresh_lock:
            return await self._force_refresh_locked()

    async def _force_refresh_locked(self) -> dict[str, object]:
        state = self.memory_manager.load_discovery_runtime_state()
        queued_reasons = self._consume_replenishment_reasons()

        def _result(payload: dict[str, object]) -> dict[str, object]:
            if queued_reasons:
                payload["queued_reasons"] = queued_reasons
            return payload

        if not self._is_initialized():
            return _result({"refreshed": False, "strategies": [], "reason": "not_initialized"})

        pool_at_cap = self._enforce_pool_cap()
        await self._publish_pool_status_if_changed()
        if pool_at_cap:
            return _result({"refreshed": False, "strategies": [], "reason": "pool_at_cap"})

        profile = await self.soul_engine.get_profile()
        plan = self._build_source_replenishment_plan()
        if not plan:
            return _result({"refreshed": False, "strategies": [], "reason": "below_threshold"})
        refresh_result = await self._run_refresh_plan(
            state=state,
            profile=profile,
            plan=plan,
            reason="manual",
        )
        return _result(refresh_result)

    def _enforce_pool_cap(self) -> bool:
        """运行池维护并报告前端可用性是否达到 target。

        ``pool_target_count`` 是前端可见的可用性下限，不是 raw 素材
        cap。Raw 行可能超过它直到 ``_raw_material_ceiling``。
        """
        source_targets = self._source_target_counts()
        raw_source_targets = self._raw_source_target_counts()

        # 跨源 topic_group 配额每个 tick 运行，不仅在 _run_refresh_plan
        # 内：当池在 cap 时，refresh 在 discover 前退出，因此 plan 内的
        # trim 永不触发，预先存在的 topic 集中将无限持续。此调用是
        # 廉价的 SQL group-by + UPDATE，无条件运行是安全的。
        try:
            self.database.trim_topic_group_overflow(
                max_per_group=max(3, self.pool_target_count // 10),
            )
        except Exception:
            logger.exception("trim_topic_group_overflow failed")

        reactivate_fn = getattr(self.database, "reactivate_under_quota_pool_sources", None)
        if callable(reactivate_fn):
            try:
                reactivated = reactivate_fn(
                    target=self.pool_target_count,
                    source_share_quotas=source_targets,
                    raw_source_share_quotas=raw_source_targets,
                )
                if reactivated > 0:
                    # 当计数与上次 tick 相同时降级到 DEBUG —— 池处于
                    # 稳态，每分钟相同的 N 个项 reactivating 是噪声，
                    # 不是信号。INFO 仅在 N 变化时触发（真实状态转换：
                    # 池排空以重新填充，或新源激增）。
                    last_reactivated = self._last_pool_maintenance_fingerprint[1]
                    log_fn = logger.info if reactivated != last_reactivated else logger.debug
                    log_fn(
                        "enforce_pool_cap: reactivated=%s under-quota source items",
                        reactivated,
                    )
                    self._last_pool_maintenance_fingerprint = (
                        self._last_pool_maintenance_fingerprint[0],
                        reactivated,
                        self._last_pool_maintenance_fingerprint[2],
                    )
                    self.database.trim_topic_group_overflow(
                        max_per_group=max(3, self.pool_target_count // 10),
                    )
            except Exception:
                logger.exception("reactivate_under_quota_pool_sources failed")

        pool_available = self.database.count_pool_candidates(
            xhs_self_nickname=self._xhs_self_nickname()
        )

        trim_source_overflow_fn = getattr(self.database, "trim_pool_source_overflow", None)
        if callable(trim_source_overflow_fn) and pool_available >= self.pool_target_count:
            try:
                source_overflow_suppressed = trim_source_overflow_fn(
                    source_share_quotas=raw_source_targets,
                )
                if source_overflow_suppressed > 0:
                    logger.info(
                        "enforce_pool_cap: suppressed=%s over-quota source items",
                        source_overflow_suppressed,
                    )
                    self.database.trim_topic_group_overflow(
                        max_per_group=max(3, self.pool_target_count // 10),
                    )
            except Exception:
                logger.exception("trim_pool_source_overflow failed")
        elif callable(trim_source_overflow_fn):
            logger.debug(
                "enforce_pool_cap: skipped source overflow trim below target "
                "pool_available=%s target=%s",
                pool_available,
                self.pool_target_count,
            )
        raw_ceiling = self._raw_material_ceiling()
        trimmed = 0
        try:
            trimmed = self.database.trim_pool_to_target_count(
                target=raw_ceiling,
                source_share_quotas=raw_source_targets,
            )
        except Exception:
            logger.exception("trim_pool_to_target_count failed")
        if trimmed > 0:
            pool_available = self.database.count_pool_candidates(
                xhs_self_nickname=self._xhs_self_nickname()
            )
            logger.info(
                "enforce_pool_cap: raw_trimmed=%s, pool_available=%s, target=%s, raw_ceiling=%s",
                trimmed,
                pool_available,
                self.pool_target_count,
                raw_ceiling,
            )
        else:
            logger.debug(
                "enforce_pool_cap: no raw trim needed, "
                "pool_available=%s, target=%s, raw_ceiling=%s",
                pool_available,
                self.pool_target_count,
                raw_ceiling,
            )
        return pool_available >= self.pool_target_count

    async def trigger_manual_refresh(self, *, reason: str = "manual") -> dict[str, object]:
        """调度一个后台手动 refresh 而不阻塞调用方。"""
        normalized_reason = self._normalize_replenishment_reason(reason)
        if not self._is_initialized():
            return {"accepted": False, "state": "idle", "reason": "not_initialized"}
        if self._manual_refresh_task is not None and not self._manual_refresh_task.done():
            return {"accepted": True, "state": "running", "reason": "already_running"}

        self._manual_refresh_state = "running"
        self._manual_refresh_message = "正在补货…"
        self._manual_refresh_started_at = self._now().isoformat()
        self._manual_refresh_finished_at = ""
        logger.info("Manual replenishment requested: reason=%s", normalized_reason)
        self._manual_refresh_task = self._track_task(
            "manual_refresh",
            self._complete_manual_refresh(),
        )
        return {"accepted": True, "state": "running", "reason": "started"}

    def _track_task(
        self,
        name: str,
        coro: Any,
    ) -> asyncio.Task[Any]:
        """Spawn 一个 detached 任务，可用时通过注册表路由。

        v0.3.63+：当 ``self.task_registry`` 被接入时（由
        ``RuntimeContext`` 在启动时），任务被注册以便
        ``rebuild_from_config`` 的 ``cancel_all`` 可在新 runtime 启动前
        取消它。直接构造 controller（无注册表）的测试回退到裸
        ``asyncio.create_task`` 以保持向后兼容。
        """
        registry = self.task_registry
        if registry is not None:
            return registry.track(name, coro)
        return asyncio.create_task(coro, name=name)

    def _update_discovery_runtime_state(
        self,
        mutator: Callable[[dict[str, object]], dict[str, object] | None],
    ) -> dict[str, object]:
        update_state = getattr(self.memory_manager, "update_discovery_runtime_state", None)
        if callable(update_state):
            return cast("dict[str, object]", update_state(mutator))
        state = self.memory_manager.load_discovery_runtime_state()
        result = mutator(state)
        next_state = state if result is None else result
        self.memory_manager.save_discovery_runtime_state(next_state)
        return next_state

    def get_pending_notification(self) -> dict[str, object] | None:
        """返回一个浏览器通知的推荐候选。"""
        state = self.memory_manager.load_discovery_runtime_state()
        last_notification_at = self._parse_iso_datetime(str(state.get("last_notification_at", "")))
        if last_notification_at is not None and self._now() - last_notification_at < timedelta(
            hours=self.notification_cooldown_hours
        ):
            return None
        candidate = self.database.get_notification_candidate(min_confidence=0.82)
        if candidate is None:
            return None
        return {
            "recommendation_id": int(candidate["id"]),
            "bvid": str(candidate.get("bvid", "")),
            "title": str(candidate.get("title", "")),
            "reason": str(candidate.get("expression", "")),
        }

    def mark_notification_sent(self, bvid: str) -> None:
        """持久化通知送达标记。"""
        self.database.mark_notification_sent(bvid)
        now = self._now().isoformat()
        self._update_discovery_runtime_state(
            lambda state: state.update({"last_notification_at": now})
        )

    def get_pending_delight(self) -> dict[str, object] | None:
        """返回一个 proactive delight 候选用于浏览器通知。

        尊重用户的 ``disliked_topics``（来自 preference 层）作为硬
        过滤器 —— 标题包含 disliked topic 短语的视频即使其
        delight_score 否则合格也会被跳过。
        """
        state = self.memory_manager.load_discovery_runtime_state()
        last_delight_at = self._parse_iso_datetime(
            str(state.get("last_delight_notification_at", ""))
        )
        if last_delight_at is not None and self._now() - last_delight_at < timedelta(
            hours=self.delight_cooldown_hours
        ):
            return None

        # 拉取小批量并在 Python 中过滤 disliked topic —— 通常只有
        # 少数高分数候选且 disliked list 很短，因此开销可忽略。
        candidates = self.database.get_delight_candidates(
            min_delight_score=DEFAULT_DELIGHT_THRESHOLD,
            limit=20,
        )
        if not candidates:
            return None

        disliked_phrases = self._load_disliked_topic_phrases()
        candidate: dict[str, Any] | None = None
        for row in candidates:
            title = str(row.get("title", "")).lower()
            tags_raw = str(row.get("tags", "")).lower()
            haystack = f"{title} {tags_raw}"
            if any(phrase in haystack for phrase in disliked_phrases if phrase):
                continue
            candidate = row
            break
        if candidate is None:
            return None
        return {
            "bvid": str(candidate.get("bvid", "")),
            "title": str(candidate.get("title", "")),
            "delight_reason": str(candidate.get("delight_reason", "")),
            "delight_score": float(candidate.get("delight_score", 0.0) or 0.0),
            "delight_hook": str(candidate.get("delight_hook", "")),
            "cover_url": str(candidate.get("cover_url", "")),
            "content_url": str(candidate.get("content_url", "")),
            "source_platform": str(candidate.get("source_platform", "") or "bilibili"),
        }

    def _load_disliked_topic_phrases(self) -> list[str]:
        """返回小写的 *有效* disliked-topic 子串。

        从 soul engine 的 ``get_effective_disliked_topics`` 获取 ——
        AI dislikes ∪ 平铺 preference dislikes，已应用 user override
        （base-then-overlay），因此手动添加的 dislike 在此处过滤，
        手动移除的不过滤。短语是针对 title + tags 的不区分大小写子串
        匹配。对缺乏该方法的较老 soul-engine double 回退到原始
        preference 层。
        """
        getter = getattr(self.soul_engine, "get_effective_disliked_topics", None)
        if callable(getter):
            try:
                return [str(item).strip().lower() for item in getter() if str(item).strip()]
            except Exception:
                return []
        try:
            layer = self.memory_manager.get_layer("preference")
        except Exception:
            return []
        data = getattr(layer, "data", None)
        if not isinstance(data, dict):
            return []
        raw = data.get("disliked_topics")
        if not isinstance(raw, list):
            return []
        return [str(item).strip().lower() for item in raw if str(item).strip()]

    def mark_delight_sent(self, bvid: str) -> None:
        """持久化 delight 通知送达标记。"""
        self.database.mark_delight_notified(bvid)
        now = self._now().isoformat()
        self._update_discovery_runtime_state(
            lambda state: state.update({"last_delight_notification_at": now})
        )

    async def prepare_delight_candidates(self) -> int:
        """即使没有 refresh 运行也预热 ready-to-push delight 候选。"""
        if not self._is_initialized():
            return 0
        profile = await self.soul_engine.get_profile()
        return await self.recommendation_engine.precompute_pool_copy(
            profile=profile,
            limit=0,
        )

    @staticmethod
    def _normalize_replenishment_reason(reason: str) -> str:
        normalized = str(reason or "").strip().lower().replace("-", "_").replace(" ", "_")
        return normalized or "unknown"

    def _queue_replenishment_reason(self, reason: str) -> dict[str, object]:
        normalized = self._normalize_replenishment_reason(reason)
        self._pending_replenishment_reasons.add(normalized)
        return {
            "refreshed": False,
            "strategies": [],
            "reason": "queued",
            "queued_reason": normalized,
        }

    def _consume_replenishment_reasons(self) -> list[str]:
        reasons = sorted(self._pending_replenishment_reasons)
        self._pending_replenishment_reasons.clear()
        return reasons

    async def request_replenishment(
        self,
        *,
        reason: str,
        force: bool = False,
    ) -> dict[str, object]:
        """补货请求的单一公共入口。

        Non-force 请求仅记录为何下次调度器 pass 应重新检查池。Force
        请求保留给显式用户操作或刚消耗可见池的 UI 路径。
        """
        normalized = self._normalize_replenishment_reason(reason)
        if force:
            return await self.trigger_manual_refresh(reason=normalized)
        queued = self._queue_replenishment_reason(normalized)
        return {
            "accepted": True,
            "state": "queued",
            "reason": normalized,
            "refresh": queued,
        }

    async def _safe_precompute_pool_copy(self, *, profile: Any) -> int:
        """运行 ``precompute_pool_copy``，吞掉任何异常。

        v0.3.47+ 从 ``_run_refresh_plan`` 中的 per-strategy
        fire-and-forget 任务使用此方法。engine 内的锁将并发调用排队，
        使两个 strategy 不会双重花费 LLM token；此 wrapper 存在以使
        单个失败的 expression 批次不会拖垮整个 refresh 轮次（调用方
        对 gather 执行 ``return_exceptions=True``，但从一个地方记录
        warning 比散布 try/except 更干净）。
        """
        try:
            return await self.recommendation_engine.precompute_pool_copy(
                profile=profile,
                limit=_MAX_DISCOVERY_BACKFILL_PER_REFRESH,
            )
        except Exception:
            logger.exception("precompute_pool_copy task failed")
            return 0

    async def _safe_prewarm_pool_mmr_embeddings(self) -> int:
        """预热 MMR embedding 而不阻塞 refresh 完成。"""
        try:
            return int(await self.recommendation_engine.prewarm_pool_mmr_embeddings())
        except Exception:
            logger.exception("prewarm_pool_mmr_embeddings failed")
            return 0

    async def _safe_prewarm_supergroup_embeddings(self) -> int:
        """预热 topic-supergroup embedding 而不阻塞 refresh 完成。"""
        try:
            return int(await self.recommendation_engine.prewarm_supergroup_embeddings())
        except Exception:
            logger.exception("prewarm_supergroup_embeddings failed")
            return 0

    async def run_forever(self) -> None:
        """将所有后台任务作为独立并发 loop 启动。

        每个任务在自己的 timer 上运行，使一个慢的 discovery refresh
        （B 站 API 每个请求挑战时 10+ 分钟）永不阻塞 proactive
        notification、soul pipeline tick 或 XHS keyword 生产。

        架构::

            ┌─ _loop_refresh()           60s   LLM 重量级，可能耗时数分钟
            ├─ _loop_pool_precompute()   60s   v0.3.60+ — 排空 pool_expression
            ├─ _loop_candidate_eval()    60s   排空 pending raw 候选
            ├─ _loop_soul_pipeline()     60s   profile 更新、speculator
            ├─ _loop_bilibili_producer() 60s   冷却下 Bili 扩展 search 回退
            ├─ _loop_xhs_producer()      60s   xhs keyword 生成
            ├─ _loop_douyin_producer()   60s   配额下 Douyin discovery
            ├─ _loop_youtube_producer()  60s   配额下 YouTube discovery
            ├─ _loop_x_producer()        60s   配额下 X (Twitter) discovery
            ├─ _loop_zhihu_producer()    60s   配额下 Zhihu discovery
            ├─ _loop_proactive_push()    60s   delight + interest probe
            ├─ _loop_keyword_planner()  120s   P1.6 — 合并 keyword 生成（flag 门控）
            ├─ _loop_image_cache_cleanup() 6h  清理已消费+未保存封面
            └─ _loop_cover_prefetch()    60s   缓存 fresh-token 封面（XHS）
        """
        if self._llm_work_allowed():
            with suppress(Exception):
                await self.prepare_delight_candidates()
        self._warn_on_stranded_source_shares()
        # P1.6：给 keyword planner controller 的 deficit / catalyst 口径，
        # 使其共享驱动池补货的确切 in-flight + raw-headroom 核算
        # （它从不重新计数可见池行）。
        if self.keyword_planner is not None:
            with suppress(Exception):
                self.keyword_planner.bind_deficit_source(self)
            bind_soul = getattr(self.keyword_planner, "bind_soul_engine", None)
            if callable(bind_soul):
                with suppress(Exception):
                    bind_soul(self.soul_engine)
        tasks = [
            asyncio.create_task(self._loop_refresh()),
            asyncio.create_task(self._loop_pool_precompute()),
            asyncio.create_task(self._loop_candidate_eval()),
            asyncio.create_task(self._loop_soul_pipeline()),
            asyncio.create_task(self._loop_bilibili_producer()),
            asyncio.create_task(self._loop_xhs_producer()),
            asyncio.create_task(self._loop_douyin_producer()),
            asyncio.create_task(self._loop_youtube_producer()),
            asyncio.create_task(self._loop_x_producer()),
            asyncio.create_task(self._loop_zhihu_producer()),
            asyncio.create_task(self._loop_proactive_push()),
            asyncio.create_task(self._loop_keyword_planner()),
            asyncio.create_task(self._loop_image_cache_cleanup()),
            asyncio.create_task(self._loop_cover_prefetch()),
        ]
        try:
            await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _loop_refresh(self) -> None:
        """Discovery refresh —— 填充候选池。"""
        while True:
            # v0.3.61+：30s init 宽限期。daemon 启动后第一个 refresh
            # tick 落在 Bilibili 的 WBI 速率限制桶仍被 init 的
            # history / favorites / following 突发饱和之时 —— 立即触发
            # discovery search 产生约 50% v_voucher 耗尽。跳过第一次
            # refresh_if_needed 给 IP 一个 tick 冷却，再让 discovery
            # 开始重击。
            if not self._init_grace_consumed:
                self._init_grace_consumed = True
                logger.info(
                    "Init grace period — skipping first refresh tick to let "
                    "Bilibili WBI bucket cool down (next tick will run normally)"
                )
            elif not self._llm_work_allowed():
                await asyncio.sleep(self.check_interval_seconds)
                continue
            else:
                with suppress(Exception):
                    await self._on_profile_ready_if_first_time()
                with suppress(Exception):
                    await self.refresh_if_needed()
            await asyncio.sleep(self.check_interval_seconds)

    async def _loop_pool_precompute(self) -> None:
        """v0.3.60+：独立排空 pool_expression / pool_topic_label。

        v0.3.59 将 ``_drain_pool_precompute_backlog`` 添加到 ``_loop_refresh``
        但放在了 ``await self.refresh_if_needed()`` 之后。2026-05-05 的
        生产调试（PID 32644 daemon，22:35:12 启动）发现 runtime 卡在
        ``manual_refresh_state="running"``，因为 B 站 v_voucher 速率
        限制使 refresh_if_needed pending 数分钟 —— 排在其后的 drain 永不
        执行，即使有 184 个新项在池中等待 expression 拷贝。

        将 drain 拆分到自己的 loop 匹配 ``run_forever`` 契约（每个其他
        ticker 遵守）：慢的 refresh 必须永不阻塞独立维护工作。Engine 的
        ``_precompute_lock`` 仍然对 ``_run_refresh_plan`` 排队的
        per-strategy fire-and-forget 任务去重，因此无 LLM token 双重花费。
        """
        while True:
            if not self._llm_work_allowed():
                await asyncio.sleep(self.check_interval_seconds)
                continue
            with suppress(Exception):
                await self._drain_pool_precompute_backlog()
            await asyncio.sleep(self.check_interval_seconds)

    async def _loop_candidate_eval(self) -> None:
        """独立于 refresh plan 排空 pending discovery-candidate raw 行。"""
        while True:
            if not self._llm_work_allowed():
                logger.debug("candidate eval drain skipped: reason=llm_paused")
                await asyncio.sleep(self.check_interval_seconds)
                continue
            with suppress(Exception):
                await self._drain_discovery_candidates_and_precompute(
                    reason="periodic",
                )
            await asyncio.sleep(self.check_interval_seconds)

    async def _drain_pool_precompute_backlog(self) -> None:
        """v0.3.59+：独立 precompute drain。

        如果 soul profile 已就绪，每个 refresh-loop tick（60s）触发一次
        ``precompute_pool_copy``。engine 的 ``_precompute_lock`` 对
        ``_run_refresh_plan`` 排队的 per-strategy fire-and-forget 任务
        去重，使背对背触发不会双重花费 LLM token。
        """
        engine = self.recommendation_engine
        if engine is None:
            return
        if not self._is_initialized():
            return
        try:
            profile = await self.soul_engine.get_profile()
        except Exception:
            return
        if profile is None:
            return
        try:
            before_pool_count = int(
                self.database.count_pool_candidates(xhs_self_nickname=self._xhs_self_nickname())
            )
        except Exception:
            before_pool_count = -1
        try:
            await engine.precompute_pool_copy(
                profile=profile,
                limit=_MAX_DISCOVERY_BACKFILL_PER_REFRESH,
            )
        except Exception:
            logger.exception("Periodic precompute drain failed")
            return
        if before_pool_count >= 0:
            await self._publish_precompute_replenishment_if_needed(
                before_pool_count=before_pool_count,
            )

    async def _publish_precompute_replenishment_if_needed(
        self,
        *,
        before_pool_count: int,
    ) -> None:
        """报告独立 drain 期间变为可用的候选。"""
        try:
            after_pool_counts = self._pool_readiness_counts()
            after_pool_count = int(after_pool_counts["available"])
        except Exception:
            return
        replenished_count = max(0, after_pool_count - int(before_pool_count))
        if replenished_count <= 0:
            return

        state = self._update_discovery_runtime_state(
            lambda runtime_state: runtime_state.update(
                {"last_replenished_count": replenished_count}
            )
        )
        discovered_count = self._int_state_value(state, "last_discovered_count")
        recent_pool_topics = self._list_state_value(state, "recent_pool_topics")
        self._last_published_pool_count = after_pool_count
        logger.info(
            "Periodic precompute made %s pool candidates available (pool_available %s -> %s)",
            replenished_count,
            before_pool_count,
            after_pool_count,
        )
        await self._publish_event(
            {
                "type": "refresh.pool_updated",
                "phase": "done",
                "message": f"刚补进 {replenished_count} 条新的",
                **self._pool_count_payload(after_pool_counts),
                "last_discovered_count": discovered_count,
                "last_replenished_count": replenished_count,
                "recent_pool_topics": recent_pool_topics,
            }
        )

    async def _on_profile_ready_if_first_time(self) -> None:
        """soul profile 首次出现后那个 tick 触发的一次性 hook。

        排空在 init 的 analyze_events 窗口期间堆积的未分类池 backlog。
        没有这个，profile-ready 之前进入池的项（XHS bootstrap 笔记、
        B 站 history 获取）会一直带着空的 ``topic_group`` /
        ``style_key`` 直到下一个自然 refresh tick —— 而 recommendation
        summary 日志会显示回退的 ``topic_group=title[:N]``（我们在
        2026-05-05 看到的丑陋 "屎屎/165/三花" debug）。
        """
        if not self._llm_work_allowed():
            return
        if self._profile_ready_observed:
            return
        if not self._is_initialized():
            return
        self._profile_ready_observed = True
        engine = self.recommendation_engine
        classify_fn = getattr(engine, "classify_pool_backlog", None) if engine else None
        if not callable(classify_fn):
            return
        try:
            profile = await self.soul_engine.get_profile()
        except Exception:
            # Race：_is_initialized 为 true 但 get_profile 抛出。
            # 重置 flag 使下次 tick 干净重试。
            self._profile_ready_observed = False
            return
        logger.info(
            "Soul profile became ready — kicking classify_pool_backlog to drain init-window backlog"
        )
        try:
            await classify_fn(profile=profile, limit=100)
        except Exception:
            logger.exception("profile-ready classify_pool_backlog failed")

    async def _loop_soul_pipeline(self) -> None:
        """Soul profile pipeline —— buffer 刷新、speculator、cognition。"""
        while True:
            if not self._llm_work_allowed():
                await asyncio.sleep(self.check_interval_seconds)
                continue
            with suppress(Exception):
                await self._tick_soul_pipeline()
            await asyncio.sleep(self.check_interval_seconds)

    async def _loop_xhs_producer(self) -> None:
        """XHS keyword 生产 —— Soul 驱动的 search 任务生成。"""
        while True:
            if not self._llm_work_allowed():
                await asyncio.sleep(self.check_interval_seconds)
                continue
            with suppress(Exception):
                await self._tick_xhs_producer()
            await asyncio.sleep(self.check_interval_seconds)

    async def _loop_bilibili_producer(self) -> None:
        """Bilibili 扩展兜底 —— 仅在 API 搜索冷却期间入队。"""
        while True:
            if not self._llm_work_allowed():
                await asyncio.sleep(self.check_interval_seconds)
                continue
            with suppress(Exception):
                await self._tick_bilibili_producer()
            await asyncio.sleep(self.check_interval_seconds)

    async def _loop_douyin_producer(self) -> None:
        """抖音生产 —— 抖音低于配额时的插件/直连发现。"""
        while True:
            if not self._llm_work_allowed():
                await asyncio.sleep(self.check_interval_seconds)
                continue
            with suppress(Exception):
                await self._tick_douyin_producer()
            await asyncio.sleep(self.check_interval_seconds)

    async def _loop_youtube_producer(self) -> None:
        """YouTube 生产 —— YouTube 低于配额时的后端直连发现。"""
        while True:
            if not self._llm_work_allowed():
                await asyncio.sleep(self.check_interval_seconds)
                continue
            with suppress(Exception):
                await self._tick_youtube_producer()
            await asyncio.sleep(self.check_interval_seconds)

    async def _loop_x_producer(self) -> None:
        """X (Twitter) 生产 —— 低于配额时的服务端 cookie 重放发现。"""
        while True:
            if not self._llm_work_allowed():
                await asyncio.sleep(self.check_interval_seconds)
                continue
            with suppress(Exception):
                await self._tick_x_producer()
            await asyncio.sleep(self.check_interval_seconds)

    async def _loop_zhihu_producer(self) -> None:
        """知乎生产 —— 低于配额时的插件支撑发现。"""
        while True:
            if not self._llm_work_allowed():
                await asyncio.sleep(self.check_interval_seconds)
                continue
            with suppress(Exception):
                await self._tick_zhihu_producer()
            await asyncio.sleep(self.check_interval_seconds)

    async def _loop_keyword_planner(self) -> None:
        """P1.6: 缺口拉动的合并关键词生成（功能开关控制）。

        拥有独立的轮询节奏（``planner_poll_seconds``），避免慢的合并
        LLM 调用阻塞 60 秒的 producer / refresh 循环。控制器按 tick 驱动
        planner（而不是 await ``planner.run()``），从而可以应用其它 LLM
        循环都遵循的同一道 ``_llm_work_allowed`` 门控 —— 在 guided init
        运行或扩展离线时暂停规划。当 ``keyword_planner`` 为 ``None``
        （测试中直接构造控制器）或功能开关关闭时，本方法为空操作。
        """
        planner = self.keyword_planner
        if planner is None:
            return
        poll_seconds = max(1, int(getattr(planner, "poll_seconds", 120)))
        while True:
            if not bool(getattr(planner, "enabled", False)):
                await asyncio.sleep(poll_seconds)
                continue
            if not self._llm_work_allowed():
                await asyncio.sleep(poll_seconds)
                continue
            with suppress(Exception):
                planner.reclaim_leases()
            with suppress(Exception):
                await planner.run_once()
            await asyncio.sleep(poll_seconds)

    async def _loop_proactive_push(self) -> None:
        """Delight + interest probe 推送 —— 轻量，绝不阻塞。

        运行节奏比主 refresh 循环更慢，因为 probes/delight 不是流式内容 ——
        一旦活跃集合已投递，几分钟内重复推送只会增加通知疲劳。
        """
        while True:
            if not self._llm_work_allowed():
                await asyncio.sleep(self.proactive_push_interval_seconds)
                continue
            # 即使 discovery refresh tick 提前退出（pool_at_cap 或
            # below_threshold），也要对池中未评分项打分。没有这步的话，
            # 稳态停在容量上限的池会静默饿死 delight 评分 —— 2026-05-04
            # 观察：评分最后运行于守护进程启动时 03:15，随后停滞 9.5 小时，
            # 因为 _run_refresh_plan 始终没进到 precompute_pool_copy 分支。
            # ``prepare_delight_candidates`` 以 limit=0 调用
            # precompute_pool_copy，仍会对至多 50 条未评分项
            # （relevance >= 0.55）执行 precompute_delight_scores。
            with suppress(Exception):
                await self.prepare_delight_candidates()
            # 在 prepare 之前快照 delight 数量，以便检测到净新增的
            # 超阈值 delight（popup 重新拉取触发条件）。
            delight_count_before = self._safe_count_delight_candidates()
            with suppress(Exception):
                await self._publish_delight_if_available()
            with suppress(Exception):
                await self._publish_probe_if_available()
            delight_count_after = self._safe_count_delight_candidates()
            net_new_delights = max(0, delight_count_after - delight_count_before)
            if net_new_delights > 0:
                with suppress(Exception):
                    await self._publish_event(
                        {
                            "type": "delight.refreshed",
                            "phase": "ready",
                            "count": net_new_delights,
                            "total_pending": delight_count_after,
                            "message": (
                                f"刚发现 {net_new_delights} 条新的惊喜推荐"
                                if net_new_delights > 1
                                else "刚发现一条新的惊喜推荐"
                            ),
                        }
                    )
            await asyncio.sleep(self.proactive_push_interval_seconds)

    async def _loop_image_cache_cleanup(self) -> None:
        """周期性清理封面图磁盘缓存。

        驱逐已消费、未保存内容（用户看过且放过、且不在收藏 / 稍后再看里）的
        缓存封面。已保存或仍待处理内容的封面会被保留；不可重取的封面
        （XHS 轮换 token URL）受保护 —— 一旦上游 token 过期，缓存副本就是
        它们唯一持久可用的来源。批量首遍扫描在 API 启动时执行；本循环是
        稳态扫除。
        """
        while True:
            await asyncio.sleep(_IMAGE_CACHE_CLEANUP_INTERVAL_SECONDS)
            try:
                result = cleanup_image_cache(database=self.database)
            except Exception:
                logger.debug("image cache cleanup tick failed", exc_info=True)
                continue
            if result.removed:
                logger.info(
                    "image cache cleanup: removed %d cover files (%.1f MB freed; "
                    "%d consumed, %d aged orphans, %d unrefetchable protected)",
                    result.removed,
                    result.freed_bytes / (1024 * 1024),
                    result.removed_consumed,
                    result.removed_aged_orphans,
                    result.protected_unrefetchable,
                )

    async def _prefetch_uncached_covers(
        self,
        *,
        scan: int = _COVER_PREFETCH_SCAN,
        max_fetch: int = _COVER_PREFETCH_MAX_FETCH,
    ) -> int:
        """为最近发现、仍可服务的内容缓存封面。

        修复 «封面 502» 故障模式：封面图此前只在卡片展示时才拉取，而那时
        短命的 XHS 签名 token 往往已过期。发现后立即预取可在 token 仍新鲜时
        保存图片。不可重取的（XHS 轮换 token）封面优先尝试，因为可重取的
        （Bilibili 等）封面永不过期。尽力而为且有上界。
        """
        candidates = self.database.iter_servable_cover_urls(
            recent_hours=_COVER_PREFETCH_RECENT_HOURS,
            limit=scan,
        )
        targets = select_prefetch_targets(candidates, max_fetch=max_fetch)
        fetched = 0
        for url in targets:
            if await prefetch_cover(url):
                fetched += 1
        return fetched

    async def _loop_cover_prefetch(self) -> None:
        """在 CDN token 仍新鲜时周期性缓存已发现的封面。"""
        while True:
            try:
                cached = await self._prefetch_uncached_covers()
            except Exception:
                logger.debug("cover prefetch tick failed", exc_info=True)
                cached = 0
            if cached:
                logger.info("cover prefetch: cached %d new covers", cached)
            await asyncio.sleep(_COVER_PREFETCH_INTERVAL_SECONDS)

    async def _tick_xhs_producer(self) -> None:
        """若配置了 xhs search 任务 producer，则调用它。"""
        producer = self.xhs_producer
        if producer is None:
            return
        deficit = self._source_deficit("xiaohongshu")
        if deficit <= 0:
            return
        limit = max(1, min(deficit, self.discovery_limit))
        produce_fn = getattr(producer, "produce_if_due", None)
        if not callable(produce_fn):
            return
        if _call_accepts_limit(produce_fn):
            await produce_fn(limit=limit)
        else:
            await produce_fn()

    async def _tick_bilibili_producer(self) -> None:
        """若 Bilibili 低于配额，则调用 Bili 扩展兜底 producer。"""
        producer = self.bilibili_producer
        if producer is None:
            return
        if not self._is_initialized():
            return
        deficit = self._source_deficit("bilibili")
        if deficit <= 0:
            return
        produce_fn = getattr(producer, "produce_if_due", None)
        if not callable(produce_fn):
            return
        limit = max(1, min(deficit, self.discovery_limit))
        if _call_accepts_limit(produce_fn):
            await produce_fn(limit=limit)
        else:
            await produce_fn()

    async def _tick_douyin_producer(self) -> None:
        """若抖音低于配额，则调用抖音发现 producer。"""
        producer = self.douyin_producer
        if producer is None:
            return
        if not self._is_initialized():
            return
        deficit = self._source_deficit("douyin")
        if deficit <= 0:
            return
        produce_fn = getattr(producer, "produce_if_due", None)
        if not callable(produce_fn):
            return
        limit = max(1, min(deficit, self.discovery_limit))
        if _call_accepts_limit(produce_fn):
            await produce_fn(limit=limit)
        else:
            await produce_fn()

    async def _tick_youtube_producer(self) -> None:
        """若 YouTube 低于配额，则调用 YouTube 发现 producer。"""
        producer = self.youtube_producer
        if producer is None:
            return
        if not self._is_initialized():
            return
        deficit = self._source_deficit("youtube")
        if deficit <= 0:
            return
        produce_fn = getattr(producer, "produce_if_due", None)
        if not callable(produce_fn):
            return
        limit = max(1, min(deficit, self.discovery_limit))
        if _call_accepts_limit(produce_fn):
            await produce_fn(limit=limit)
        else:
            await produce_fn()

    async def _tick_x_producer(self) -> None:
        """若 X 低于配额，则调用 X (Twitter) 发现 producer。"""
        producer = self.x_producer
        if producer is None:
            return
        if not self._is_initialized():
            return
        deficit = self._source_deficit("twitter")
        if deficit <= 0:
            return
        produce_fn = getattr(producer, "produce_if_due", None)
        if not callable(produce_fn):
            return
        limit = max(1, min(deficit, self.discovery_limit))
        if _call_accepts_limit(produce_fn):
            await produce_fn(limit=limit)
        else:
            await produce_fn()

    async def _tick_zhihu_producer(self) -> None:
        """若知乎低于配额，则调用知乎发现 producer。"""
        producer = self.zhihu_producer
        if producer is None:
            return
        if not self._is_initialized():
            return
        deficit = self._source_deficit("zhihu")
        if deficit <= 0:
            return
        produce_fn = getattr(producer, "produce_if_due", None)
        if not callable(produce_fn):
            return
        limit = max(1, min(deficit, self.discovery_limit))
        if _call_accepts_limit(produce_fn):
            await produce_fn(limit=limit)
        else:
            await produce_fn()

    async def _tick_soul_pipeline(self) -> None:
        """若 soul engine 暴露了 ProfileUpdatePipeline.tick()，则调用它。

        拆成独立的辅助方法，便于在测试和手动单次循环 runner 中廉价调用。
        """
        pipeline = getattr(self.soul_engine, "pipeline", None)
        if pipeline is None:
            return
        tick_fn = getattr(pipeline, "tick", None)
        if not callable(tick_fn):
            return
        await tick_fn()

    def _pending_signal_events_count(self, state: dict[str, object]) -> int:
        return len(
            self.database.query_events_since(
                after_event_id=self._int_state_value(state, "last_processed_event_id"),
                event_types=self._signal_event_types,
            )
        )

    def _build_refresh_plan(
        self,
        state: dict[str, object],
    ) -> list[tuple[list[str], int]]:
        pending_events = self._pending_signal_events_count(state)
        pool_available = self.database.count_pool_candidates(
            xhs_self_nickname=self._xhs_self_nickname()
        )
        pool_below_target = pool_available < self.pool_target_count

        if pool_below_target:
            if not self._pool_below_replenishment_watermark(pool_available):
                return []
            source_plan = self._build_source_replenishment_plan()
            if source_plan:
                return source_plan
            # 当 Bilibili 已达其平台配额时，缺失的容量属于已启用的
            # 非 Bilibili 平台 producer。此处再跑 Bilibili 兜底会立即
            # 违反配置的 pool-source 比例。
            self._log_empty_refresh_plan_diagnostics(pool_available=pool_available)
            return []

        if "bilibili" not in self._normalized_pool_source_shares():
            return []

        plan: list[tuple[list[str], int]] = []
        if pending_events >= self.signal_event_threshold:
            plan.append((["search", "related_chain"], self.discovery_limit))
        if self._is_due(
            str(state.get("last_trending_refresh_at", "")),
            hours=self.trending_refresh_hours,
        ):
            plan.append((["trending"], self.discovery_limit))
        if self._is_due(
            str(state.get("last_explore_refresh_at", "")),
            hours=self.explore_refresh_hours,
        ):
            plan.append((["explore"], self.discovery_limit))
        return plan

    def _pool_below_replenishment_watermark(self, pool_available: int) -> bool:
        target = max(1, int(self.pool_target_count))
        low_watermark = int(target * _DISCOVERY_REPLENISH_LOW_WATERMARK_RATIO)
        return int(pool_available) < low_watermark

    def _log_empty_refresh_plan_diagnostics(self, *, pool_available: int) -> None:
        try:
            readiness = self._pool_readiness_counts()
        except Exception:
            logger.debug("refresh plan empty readiness diagnostics failed", exc_info=True)
            readiness = {}
        try:
            source_available = self._count_pool_available_candidates_by_source()
        except Exception:
            logger.debug("refresh plan empty source available diagnostics failed", exc_info=True)
            source_available = {}
        try:
            source_raw = self._count_pool_raw_material_by_source()
        except Exception:
            logger.debug("refresh plan empty source raw diagnostics failed", exc_info=True)
            source_raw = {}
        source_targets = self._source_target_counts()
        raw_targets = self._raw_source_target_counts()
        requested_by_source: dict[str, int] = {}
        sources = sorted(
            set(source_targets)
            | set(raw_targets)
            | set(source_available)
            | set(source_raw)
            | set(_PLATFORM_SOURCE_ORDER)
        )
        for source in sources:
            try:
                requested_by_source[source] = self._source_requested_count(
                    source,
                    source_available_counts=source_available,
                    source_raw_counts=source_raw,
                    target_counts=source_targets,
                    raw_target_counts=raw_targets,
                )
            except Exception:
                logger.debug(
                    "refresh plan empty requested_by_source diagnostics failed for %s",
                    source,
                    exc_info=True,
                )
                requested_by_source[source] = -1

        logger.info(
            "refresh plan empty: pool_available=%s raw=%s pending=%s "
            "source_available=%s source_raw=%s source_targets=%s raw_targets=%s "
            "requested_by_source=%s",
            pool_available,
            readiness.get("raw", "?"),
            readiness.get("pending", "?"),
            source_available,
            source_raw,
            source_targets,
            raw_targets,
            requested_by_source,
        )

    async def refresh_after_event_ingest(self) -> dict[str, object]:
        """兼容垫片：事件入库只是标记需求，调度器稍后再 refresh。"""
        return self._queue_replenishment_reason("event_ingest")

    async def refresh_after_feedback(self) -> dict[str, object]:
        """兼容垫片：反馈只是标记需求，调度器稍后再 refresh。"""
        return self._queue_replenishment_reason("feedback")

    async def refresh_after_init(self) -> dict[str, object]:
        """兼容垫片：init 完成应立即触发补货。"""
        return await self.request_replenishment(reason="init_completed", force=True)

    async def drain_discovery_candidates_once(
        self,
        *,
        batch_size: int | None = None,
        reason: str = "manual",
    ) -> dict[str, int]:
        """通过共享 evaluator 排空一批待处理的 discovery-candidate。"""

        return await self._drain_discovery_candidates_and_precompute(
            reason=reason,
            batch_size=batch_size,
            precompute=False,
        )

    async def _drain_discovery_candidates_and_precompute(
        self,
        *,
        reason: str,
        batch_size: int | None = None,
        profile: Any | None = None,
        precompute: bool = True,
    ) -> dict[str, int]:
        """排空一批待处理的 raw-candidate，并可选地对其进行 precompute。"""

        pipeline = self.discovery_candidate_pipeline
        if pipeline is None:
            logger.debug("candidate eval drain skipped: reason=no_pipeline caller=%s", reason)
            return {"evaluated": 0, "cached": 0, "rejected": 0}
        if self._discovery_drain_lock.locked():
            logger.debug("candidate eval drain skipped: reason=locked caller=%s", reason)
            return {"evaluated": 0, "cached": 0, "rejected": 0}
        async with self._discovery_drain_lock:
            try:
                pool_available = self.database.count_pool_candidates(
                    xhs_self_nickname=self._xhs_self_nickname()
                )
            except TypeError:
                pool_available = self.database.count_pool_candidates()
            before_pool_count = int(pool_available)
            if int(pool_available) >= self.pool_target_count:
                logger.debug(
                    "candidate eval drain skipped: reason=pool_at_cap "
                    "pool_available=%s target=%s caller=%s",
                    pool_available,
                    self.pool_target_count,
                    reason,
                )
                return {"evaluated": 0, "cached": 0, "rejected": 0}
            if profile is None:
                try:
                    profile = await self.soul_engine.get_profile()
                except Exception as exc:
                    logger.info(
                        "candidate eval drain skipped: reason=no_profile caller=%s error=%s",
                        reason,
                        exc,
                    )
                    return {"evaluated": 0, "cached": 0, "rejected": 0}
            if profile is None:
                logger.info("candidate eval drain skipped: reason=no_profile caller=%s", reason)
                return {"evaluated": 0, "cached": 0, "rejected": 0}
            result = await pipeline.drain_pending(
                profile=profile,
                batch_size=self._candidate_eval_drain_batch_size(batch_size),
            )
            drain_result = cast("dict[str, int]", result)
            evaluated = int(drain_result.get("evaluated", 0) or 0)
            cached = int(drain_result.get("cached", 0) or 0)
            rejected = int(drain_result.get("rejected", 0) or 0)
            failed = int(drain_result.get("failed", 0) or 0)
            waiting = int(drain_result.get("waiting", 0) or 0)
        if cached > 0 and precompute:
            await self._safe_precompute_pool_copy(profile=profile)
            await self._publish_precompute_replenishment_if_needed(
                before_pool_count=before_pool_count,
            )
        if evaluated or cached or rejected or failed:
            logger.info(
                "candidate eval drain done: caller=%s evaluated=%s cached=%s rejected=%s failed=%s",
                reason,
                evaluated,
                cached,
                rejected,
                failed,
            )
        elif waiting:
            logger.info(
                "candidate eval drain skipped: reason=batch_waiting pending=%s caller=%s",
                waiting,
                reason,
            )
        else:
            logger.debug("candidate eval drain skipped: reason=no_pending caller=%s", reason)
        return drain_result

    async def _complete_manual_refresh(self) -> None:
        try:
            refresh_result = await self.force_refresh()
        except Exception as exc:
            self._manual_refresh_state = "failed"
            self._manual_refresh_message = f"这次补货没跑通：{exc}"
            self._manual_refresh_finished_at = self._now().isoformat()
            await self._publish_event(
                {
                    "type": "refresh.failed",
                    "phase": "failed",
                    "message": self._manual_refresh_message,
                    **self._pool_count_payload(self._pool_readiness_counts()),
                }
            )
            return
        self._manual_refresh_state = "success"
        if bool(refresh_result.get("refreshed")):
            runtime_state = self.memory_manager.load_discovery_runtime_state()
            last_discovered = self._int_state_value(runtime_state, "last_discovered_count")
            last_replenished = self._int_state_value(runtime_state, "last_replenished_count")
        else:
            last_discovered = 0
            last_replenished = 0
        self._manual_refresh_message = (
            "刚给你补了一批新的。"
            if last_replenished > 0
            else (
                "这轮找到了内容，但可立即换的库存没变。"
                if last_discovered > 0
                else "这轮没补进新的候选。"
            )
        )
        self._manual_refresh_finished_at = self._now().isoformat()
        await self._publish_event(
            {
                "type": "refresh.pool_updated",
                "phase": "done",
                "message": self._manual_refresh_message,
                **self._pool_count_payload(self._pool_readiness_counts()),
            }
        )

    async def _run_refresh_plan(
        self,
        *,
        state: dict[str, object],
        profile: Any,
        plan: list[tuple[list[str], int]],
        reason: str,
    ) -> dict[str, object]:
        before_pool_counts = self._pool_readiness_counts()
        before_pool_count = before_pool_counts["available"]
        initial_pool_below_target = before_pool_count < self.pool_target_count
        all_discovered: list[Any] = []
        pipeline_discovered_count = 0
        flattened_strategies: list[str] = []
        replenished_topics: list[str] = []
        # v0.3.47+: 每策略 expression precompute 任务。每个策略的
        # `discover()` 会阻塞在一个慢的 LLM eval 批次上（生产环境观测
        # 8-16 分钟）。没有这步的话，popup 文案 precompute 必须等
        # 所有策略都跑完才开始 —— 也就是新鲜内容要 ~30 分钟延迟。
        # 现在：只要某个策略产出内容就立刻发起 precompute 任务；
        # ``RecommendationEngine`` 内部的 ``self._precompute_lock``
        # 会串行化它们，避免两个任务对同一批未 precompute 的候选
        # 重复花费 LLM token。
        precompute_tasks: list[asyncio.Task[Any]] = []

        await self._publish_event(
            {
                "type": "refresh.started",
                "phase": "running",
                "message": "开始给你补候选了",
                **self._pool_count_payload(before_pool_counts),
            }
        )

        for strategies, requested_limit in plan:
            current_pool_counts = self._pool_readiness_counts()
            current_pool_count = current_pool_counts["available"]
            if current_pool_count >= self.pool_target_count:
                break

            await self._publish_event(
                {
                    "type": "refresh.strategy",
                    "phase": "running",
                    "strategy": "+".join(strategies),
                    "message": self._strategy_message(strategies),
                    **self._pool_count_payload(current_pool_counts),
                }
            )

            effective_limit = self._requested_refresh_limit(
                requested_limit=requested_limit,
                current_pool_count=current_pool_count,
                pool_below_target=initial_pool_below_target,
            )
            strategy_limits = self._requested_strategy_limits(
                strategies=strategies,
                requested_limit=requested_limit,
                effective_limit=effective_limit,
                current_pool_count=current_pool_count,
                pool_below_target=initial_pool_below_target,
            )
            try:
                pool_snapshot = build_pool_distribution_snapshot(
                    self.database,
                    pool_target_count=self.pool_target_count,
                    source_targets=self._source_target_counts(),
                )
            except Exception:
                logger.exception("Failed to build pool distribution snapshot")
                pool_snapshot = None
            # 统一 keyword planner 取词路径（P1.7，功能开关控制）。B站 search
            # 是 inline-admit：本次 plan 迭代在同一次调用内完成 fetch + drain
            # （admit）。当开关打开且本条目包含 ``search`` 时，从 store 中
            # claim 词并作为 ``keywords`` 注入（engine 会把它们映射到 search
            # 策略的 ``queries`` 参数）；admit 成功则标记为 ``used``，空 / 失败
            # 迭代则标记为 ``failed``。同一条目里的非 search 子策略不受影响
            # （它们永远不会收到注入的词）。
            claimed_search: list[Any] = []
            coordinator = self.keyword_fetch
            if (
                "search" in strategies
                and coordinator is not None
                and bool(getattr(coordinator, "should_claim", lambda: False)())
                and int(current_pool_counts.get("pending_eval", 0) or 0) < effective_limit
            ):
                claimed_search = coordinator.claim(_KW_PLATFORM_BILIBILI)
            injected_keywords = (
                [item.keyword for item in claimed_search] if claimed_search else None
            )
            # P1.8 yield provenance：被 claim 词的 ``query → keyword id`` 映射，
            # 让每条产出的候选都带上 ``source_keyword_id``，供 admit 时回填
            # yield。开关关闭路径下为空 / None。
            injected_keyword_ids = (
                {item.keyword: int(item.id) for item in claimed_search} if claimed_search else None
            )

            pipeline = self.discovery_candidate_pipeline
            discovered: list[Any] = []
            topic_items: list[Any] = []
            discovered_count = 0
            admitted_count = 0
            iteration_failed = False
            try:
                if pipeline is not None:
                    produce_kwargs: dict[str, Any] = {
                        "profile": profile,
                        "strategies": strategies,
                        "limit": effective_limit,
                        "strategy_limits": strategy_limits,
                        "pool_snapshot": pool_snapshot,
                    }
                    if injected_keywords is not None:
                        produce_kwargs["keywords"] = injected_keywords
                    if injected_keyword_ids:
                        produce_kwargs["keyword_ids"] = injected_keyword_ids
                    ensure_supply = getattr(pipeline, "ensure_pending_supply", None)
                    if callable(ensure_supply):
                        supply_result = await ensure_supply(
                            **produce_kwargs,
                            target_pending=effective_limit,
                        )
                        produced_count = int(
                            dict(supply_result).get("inserted", 0)
                            if isinstance(supply_result, dict)
                            else 0
                        )
                    else:
                        produced_count = await pipeline.produce_and_enqueue(**produce_kwargs)
                    drain_result = await self._drain_discovery_candidates_and_precompute(
                        reason="refresh",
                        profile=profile,
                        batch_size=effective_limit,
                        precompute=False,
                    )
                    discovered_count = int(produced_count or 0)
                    admitted_count = int(drain_result.get("cached", 0) or 0)
                    if admitted_count > 0:
                        topic_items = list(getattr(pipeline, "last_admitted_items", []) or [])
                    pipeline_discovered_count += discovered_count
                else:
                    discover_fn = self.discovery_engine.discover
                    discover_kwargs: dict[str, Any] = {
                        "strategies": strategies,
                        "limit": effective_limit,
                    }
                    if strategy_limits and _call_accepts_strategy_limits(discover_fn):
                        discover_kwargs["strategy_limits"] = strategy_limits
                    if _call_accepts_pool_snapshot(discover_fn):
                        discover_kwargs["pool_snapshot"] = pool_snapshot
                    if injected_keywords is not None and _call_accepts_keywords(discover_fn):
                        discover_kwargs["keywords"] = injected_keywords
                    if injected_keyword_ids and _call_accepts_keyword_ids(discover_fn):
                        discover_kwargs["keyword_ids"] = injected_keyword_ids
                    discovered = await discover_fn(profile, **discover_kwargs)
                    topic_items = discovered
                    discovered_count = len(discovered)
                    admitted_count = discovered_count
            except Exception:
                iteration_failed = True
                if claimed_search and coordinator is not None:
                    coordinator.mark_failed(claimed_search)
                raise
            finally:
                if claimed_search and coordinator is not None and not iteration_failed:
                    # Inline-admit 终态：驱动了一次产出候选的 fetch 的词标为
                    # ``used``；空 fetch 则标为 ``failed``（重试）。yield 回填
                    # 属于 P1.8，与 ``used`` 解耦。
                    if discovered_count > 0:
                        coordinator.mark_used(claimed_search)
                    else:
                        coordinator.mark_failed(claimed_search)
            all_discovered.extend(discovered)
            flattened_strategies.extend(strategies)

            if admitted_count > 0:
                replenished_topics.extend(self._extract_topics(topic_items))
                # 立即触发 expression precompute（与下一个策略的 discovery
                # LLM 调用并行）。engine 内部的锁会在前一个任务仍在运行时
                # 把这次排队。
                precompute_tasks.append(
                    self._track_task(
                        "precompute_pool_copy",
                        self._safe_precompute_pool_copy(profile=profile),
                    )
                )

        if flattened_strategies:
            self.database.trim_explore_cluster_overflow(max_per_cluster=3)
            # 把每个 topic_group 上限设为池目标的约 10%，避免单个热门
            # topic（如 related_chain 来的"人工智能"）在多轮里堆积数百条
            # 新候选并饿死其它来源 / topic。下限 3 保证小池仍可用。
            self.database.trim_topic_group_overflow(
                max_per_group=max(3, self.pool_target_count // 10),
            )
            self.database.evict_stale_pool_items(max_age_days=14)
            # 在 precompute 之前快照 delight 数量，以便检测到净新增的
            # 超阈值 delight 并向 popup 推送 refresh 事件（不做逐项
            # chrome 通知 —— popup 在事件触发时重新拉取
            # /api/delight/pending-batch）。
            delight_count_before = self._safe_count_delight_candidates()
            # v0.3.47+: 排空上面提前发起的每策略 precompute 任务。它们
            # 早已与后续策略的 discovery 并行运行，因此这里只是 await
            # 仍挂起的部分，而不是从头开始。如果 discovery 循环没产出
            # 任何可 precompute 的内容（例如全部在 eval 阶段被拒），
            # 则回退为一次同步调用，保证更早周期的 backlog 仍能被清掉。
            if precompute_tasks:
                await asyncio.gather(*precompute_tasks, return_exceptions=True)
            else:
                await self._safe_precompute_pool_copy(profile=profile)
            # 预热 supergroup-merge embeddings，让 popup 的"换一批"热路径
            # 始终命中 L1/L2 缓存。本轮 refresh 新增的标签会在用户点击前
            # 被预热。
            # 在后台预热 embedding 派生缓存。它们是对后续 serve() 调用
            # 的延迟优化，并非本轮 refresh 结果可见的前提条件。让它们
            # 脱离 refresh 锁，可避免慢的本地 embedding 后端把 popup
            # 卡在"正在补货"。
            self._track_task(
                "prewarm_supergroup_embeddings",
                self._safe_prewarm_supergroup_embeddings(),
            )
            self._track_task(
                "prewarm_pool_mmr_embeddings",
                self._safe_prewarm_pool_mmr_embeddings(),
            )
            delight_count_after = self._safe_count_delight_candidates()
            net_new_delights = max(0, delight_count_after - delight_count_before)
            if net_new_delights > 0:
                await self._publish_event(
                    {
                        "type": "delight.refreshed",
                        "phase": "ready",
                        "count": net_new_delights,
                        "total_pending": delight_count_after,
                        "message": (
                            f"刚发现 {net_new_delights} 条新的惊喜推荐"
                            if net_new_delights > 1
                            else "刚发现一条新的惊喜推荐"
                        ),
                    }
                )
            await self._publish_delight_if_available()
            await self._publish_probe_if_available()

            # v0.3.66+: 在每个 refresh plan 结束时强制执行池绝对上限。更早
            # 的 trim_topic_group_overflow / trim_explore_cluster_overflow /
            # evict_stale 调用只限制单轴集中度（topic、cluster、age）—— 它们
            # 都不限制总数。长跑的 discovery 周期（LLM eval 批次 10-30 分钟）
            # 还会阻塞 run_forever 中周期性的 _enforce_pool_cap tick，导致
            # popup 经常看到 pool_available_count 远超 pool_target_count
            # （例如生产环境 target=600 时出现 668）。_enforce_pool_cap 还会
            # 运行 reactivate_under_quota 和感知 source-share 的 trim，因此
            # 这里是把刚发现的候选落定到最终形态、供 popup 重新拉取的正确位置。
            try:
                self._enforce_pool_cap()
            except Exception:
                logger.exception("post-refresh enforce_pool_cap failed")

        now = self._now().isoformat()
        latest_event_id = self.database.get_latest_event_id()
        runtime_updates: dict[str, object] = {}
        if "search" in flattened_strategies or "related_chain" in flattened_strategies:
            runtime_updates["last_event_refresh_at"] = now
            runtime_updates["last_processed_event_id"] = latest_event_id
        if "trending" in flattened_strategies:
            runtime_updates["last_trending_refresh_at"] = now
        if "explore" in flattened_strategies:
            runtime_updates["last_explore_refresh_at"] = now
        after_pool_counts = self._pool_readiness_counts()
        after_pool_count = after_pool_counts["available"]
        runtime_updates["last_discovered_count"] = len(all_discovered) + pipeline_discovered_count
        runtime_updates["last_replenished_count"] = max(0, after_pool_count - before_pool_count)
        if replenished_topics:
            runtime_updates["recent_pool_topics"] = self._dedupe_topics(replenished_topics)[:3]
        state = self._update_discovery_runtime_state(
            lambda runtime_state: runtime_state.update(runtime_updates)
        )
        discovered_count = self._int_state_value(state, "last_discovered_count")
        replenished_count = self._int_state_value(state, "last_replenished_count")
        await self._publish_event(
            {
                "type": "refresh.pool_updated",
                "phase": "done",
                "message": (
                    f"刚补进 {replenished_count} 条新的"
                    if replenished_count > 0
                    else (
                        "这轮找到了内容，但可立即换的库存没变"
                        if discovered_count > 0
                        else "这轮没补进新的候选"
                    )
                ),
                **self._pool_count_payload(after_pool_counts),
                "last_discovered_count": discovered_count,
                "last_replenished_count": replenished_count,
                "recent_pool_topics": self._list_state_value(state, "recent_pool_topics"),
            }
        )
        return {
            "refreshed": bool(flattened_strategies),
            "strategies": flattened_strategies,
            "reason": reason,
            "recommendation_count": 0,
        }

    async def _publish_pool_status_if_changed(self) -> None:
        """当池计数发生变化时发出 ``pool_status`` runtime 事件。

        池计数最常通过 ``enforce_pool_cap`` 重新激活被压制项或修剪溢出来
        变更 —— 这条路径不会走 refresh 结束时的 ``refresh.pool_updated``
        事件。没有这个钩子，popup 的池计数 UI 只在一次完整 refresh 波次
        完成时才会刷新；现在它能在任意 pool 状态变化后数秒内保持同步。

        仅在计数与上次发出值不同时才发出，避免稳态 tick 刷屏 WebSocket
        流。
        """
        try:
            pool_counts = self._pool_readiness_counts()
            current = int(pool_counts["available"])
        except Exception:
            return
        if current == self._last_published_pool_count:
            return
        self._last_published_pool_count = current
        await self._publish_event(
            {
                "type": "pool_status",
                **self._pool_count_payload(pool_counts),
                "pool_target_count": int(self.pool_target_count),
            }
        )

    def _safe_count_delight_candidates(self) -> int:
        """尽力统计待处理 delight 候选数量（任意错误都返回 0，让调用方可以
        做基于增量的比较而不会拖垮 refresh tick）。"""
        from openbiliclaw.recommendation.delight import DEFAULT_DELIGHT_THRESHOLD

        try:
            return int(
                self.database.count_delight_candidates(min_delight_score=DEFAULT_DELIGHT_THRESHOLD)
            )
        except Exception:
            return 0

    async def _publish_event(self, event: dict[str, object]) -> bool:
        publish = getattr(self.event_hub, "publish", None)
        if callable(publish):
            result = await publish(event)
            return True if result is None else bool(result)
        return False

    async def _publish_delight_if_available(self) -> None:
        """检查是否有待处理的 delight 候选，并通过 WebSocket 推送。"""
        candidate = self.get_pending_delight()
        if candidate is None:
            return
        await self._publish_event(
            {
                "type": "delight.candidate",
                "phase": "ready",
                "message": "发现了一条你可能会意外喜欢的内容",
                "bvid": candidate.get("bvid", ""),
                "title": candidate.get("title", ""),
                "delight_reason": candidate.get("delight_reason", ""),
                "delight_score": candidate.get("delight_score", 0.0),
                "delight_hook": candidate.get("delight_hook", ""),
                "cover_url": candidate.get("cover_url", ""),
                "content_url": candidate.get("content_url", ""),
                "source_platform": candidate.get("source_platform", "bilibili"),
            }
        )

    _PROBE_COOLDOWN_HOURS = 4  # 在此窗口内不重复推送同一 domain

    async def _publish_interest_probe_if_available(self) -> bool:
        """通过 WebSocket 推送最靠前的 speculative-interest 假设。

        当 speculator 持有一个 active 假设、需要 agent 让用户确认时，
        触发 ``interest.probe`` 事件。

        去重：每个 domain 在一个冷却窗口（``_PROBE_COOLDOWN_HOURS``）内
        最多推送一次。已 probe 过的 domain 记录在
        ``discovery_runtime_state["probed_domains"]`` 中。
        """
        speculator = getattr(self.soul_engine, "_speculator", None)
        get_active = getattr(speculator, "get_active_speculations", None)
        if not callable(get_active):
            return False
        specs = [
            spec
            for spec in get_active()
            if str(getattr(spec, "status", "active")).strip().lower() == "active"
        ]
        if not specs:
            return False

        # 从 runtime state 加载 probe 历史
        state = self.memory_manager.load_discovery_runtime_state()
        probed: dict[str, str] = state.get("probed_domains", {})  # type: ignore[assignment]
        probed_axes: dict[str, str] = state.get("probed_axes", {})  # type: ignore[assignment]
        probed_distance_bands: dict[str, str] = state.get("probed_distance_bands", {})  # type: ignore[assignment]
        # 清理过期条目
        now = self._now()
        cutoff = (now - timedelta(hours=self._PROBE_COOLDOWN_HOURS)).isoformat()
        probed = {d: t for d, t in probed.items() if t > cutoff}
        probed_axes = {axis: t for axis, t in probed_axes.items() if t > cutoff}
        probed_distance_bands = {mode: t for mode, t in probed_distance_bands.items() if t > cutoff}

        top = choose_next_probe_candidate(
            specs,
            probed_domains=set(probed),
            probed_axes=set(probed_axes),
            probed_probe_modes=set(probed_distance_bands),
            feedback_history=state.get("probe_feedback_history", []),
        )
        if top is None:
            return False  # 所有 active specs 最近都已被 probe

        domain = str(getattr(top, "domain", "")).strip()
        if not domain:
            return False

        probe_mode = _normalize_probe_mode(getattr(top, "probe_mode", ""))
        challenge = probe_mode in _PROBE_CHALLENGE_MODES
        with suppress(Exception):
            challenge = challenge or bool(getattr(top, "challenge", False))
        axis = build_probe_axis(
            experience_mode=getattr(top, "experience_mode", ""),
            entry_load=getattr(top, "entry_load", ""),
        )
        reason = str(getattr(top, "reason", "")).strip()
        specifics = [
            str(getattr(item, "name", "")).strip()
            for item in getattr(top, "specifics", [])
            if str(getattr(item, "name", "")).strip()
        ][:5]
        specific_hint = ""
        if specifics:
            specific_hint = "（比如：" + "、".join(specifics[:3]) + "）"
        question = (
            f"我从你最近的轨迹里嗅到你可能对【{domain}】{specific_hint}感兴趣"
            f"——{reason} 这个方向你自己认不认？"
            if reason
            else f"我感觉你可能对【{domain}】{specific_hint}有潜在兴趣，这个方向你自己认不认？"
        )
        delivered = await self._publish_event(
            {
                "type": "interest.probe",
                "phase": "ready",
                "message": "有一个猜测兴趣方向想确认",
                "domain": domain,
                "category": str(getattr(top, "category", "")),
                "reason": reason,
                "confidence": float(getattr(top, "confidence", 0.0) or 0.0),
                "weight": float(getattr(top, "weight", 0.0) or 0.0),
                "experience_mode": str(getattr(top, "experience_mode", "")),
                "entry_load": str(getattr(top, "entry_load", "")),
                "probe_mode": probe_mode,
                "challenge": challenge,
                "specifics": specifics,
                "question": question,
            }
        )
        if not delivered:
            logger.debug("interest probe skipped: no runtime-stream subscriber")
            return False

        # 只有在至少到达一个 runtime stream 之后才记录这次 probe。
        delivered_at = now.isoformat()

        def _record_probe(runtime_state: dict[str, object]) -> None:
            latest_probed = _string_state_map(runtime_state.get("probed_domains"))
            latest_probed[domain.lower()] = delivered_at
            runtime_state["probed_domains"] = latest_probed
            latest_axes = _string_state_map(runtime_state.get("probed_axes"))
            if axis:
                latest_axes[axis] = delivered_at
            runtime_state["probed_axes"] = latest_axes
            latest_bands = _string_state_map(runtime_state.get("probed_distance_bands"))
            latest_bands[probe_mode] = delivered_at
            runtime_state["probed_distance_bands"] = latest_bands

        self._update_discovery_runtime_state(_record_probe)
        return True

    async def _publish_avoidance_probe_if_available(self) -> bool:
        """通过 WebSocket 推送最靠前的 speculative-avoidance 假设。"""
        speculator = getattr(self.soul_engine, "_avoidance_speculator", None)
        get_active = getattr(speculator, "get_active_avoidances", None)
        if not callable(get_active):
            return False
        avoidances = [
            avoidance
            for avoidance in get_active()
            if str(getattr(avoidance, "status", "active")).strip().lower() == "active"
        ]
        if not avoidances:
            return False

        state = self.memory_manager.load_discovery_runtime_state()
        probed = _string_state_map(state.get("probed_avoidance_domains"))
        probed_axes = _string_state_map(state.get("probed_avoidance_axes"))
        now = self._now()
        cutoff = (now - timedelta(hours=self._PROBE_COOLDOWN_HOURS)).isoformat()
        probed = {d: t for d, t in probed.items() if t > cutoff}
        probed_axes = {axis: t for axis, t in probed_axes.items() if t > cutoff}

        top = choose_next_avoidance_candidate(
            avoidances,
            probed_domains=set(probed),
            probed_axes=set(probed_axes),
            feedback_history=state.get("avoidance_probe_feedback_history", []),
        )
        if top is None:
            return False

        domain = str(getattr(top, "domain", "")).strip()
        if not domain:
            return False

        axis = build_probe_axis(
            experience_mode=getattr(top, "experience_mode", ""),
            entry_load=getattr(top, "entry_load", ""),
        )
        reason = str(getattr(top, "reason", "")).strip()
        specifics = [
            str(getattr(item, "name", "")).strip()
            for item in getattr(top, "specifics", [])
            if str(getattr(item, "name", "")).strip()
        ][:5]
        specific_hint = ""
        if specifics:
            specific_hint = "（比如：" + "、".join(specifics[:3]) + "）"
        question = (
            f"我猜【{domain}】{specific_hint}可能是你想避开的方向——{reason} 这个判断准不准？"
            if reason
            else f"我感觉【{domain}】{specific_hint}可能不是你想看的方向，这个判断准不准？"
        )
        delivered = await self._publish_event(
            {
                "type": "avoidance.probe",
                "phase": "ready",
                "message": "有一个可能想避开的方向想确认",
                "domain": domain,
                "reason": reason,
                "confidence": float(getattr(top, "confidence", 0.0) or 0.0),
                "weight": float(getattr(top, "weight", 0.0) or 0.0),
                "source_mode": str(getattr(top, "source_mode", "")),
                "source_signal": str(getattr(top, "source_signal", "")),
                "experience_mode": str(getattr(top, "experience_mode", "")),
                "entry_load": str(getattr(top, "entry_load", "")),
                "specifics": specifics,
                "question": question,
            }
        )
        if not delivered:
            logger.debug("avoidance probe skipped: no runtime-stream subscriber")
            return False

        delivered_at = now.isoformat()

        def _record_avoidance_probe(runtime_state: dict[str, object]) -> None:
            latest_probed = _string_state_map(runtime_state.get("probed_avoidance_domains"))
            latest_probed[domain.lower()] = delivered_at
            runtime_state["probed_avoidance_domains"] = latest_probed
            latest_axes = _string_state_map(runtime_state.get("probed_avoidance_axes"))
            if axis:
                latest_axes[axis] = delivered_at
            runtime_state["probed_avoidance_axes"] = latest_axes

        self._update_discovery_runtime_state(_record_avoidance_probe)
        return True

    async def _publish_probe_if_available(self) -> bool:
        """至多发布一条主动 probe，interest 与 avoidance 交替。"""
        state = self.memory_manager.load_discovery_runtime_state()
        last_kind = str(state.get("last_probe_kind", "")).strip().lower()
        order = (
            ("avoidance", self._publish_avoidance_probe_if_available),
            ("interest", self._publish_interest_probe_if_available),
        )
        if last_kind != "interest":
            order = (
                ("interest", self._publish_interest_probe_if_available),
                ("avoidance", self._publish_avoidance_probe_if_available),
            )

        for kind, publish in order:
            delivered = await publish()
            if not delivered:
                continue

            def _record_last_probe_kind(
                runtime_state: dict[str, object],
                *,
                probe_kind: str = kind,
            ) -> None:
                runtime_state["last_probe_kind"] = probe_kind

            self._update_discovery_runtime_state(_record_last_probe_kind)
            return True
        return False

    def _strategy_message(self, strategies: list[str]) -> str:
        if strategies == ["search", "related_chain"]:
            return "先从你刚刚的口味里搜一轮"
        if strategies == ["trending"]:
            return "顺手看看站内热榜里有没有你会吃的"
        if strategies == ["explore"]:
            return "再给你探一点你可能会意外喜欢的"
        return "正在继续给你补候选"

    def _build_source_replenishment_plan(self) -> list[tuple[list[str], int]]:
        source_available_counts = self._count_pool_available_candidates_by_source()
        source_raw_counts = self._count_pool_raw_material_by_source()
        target_counts = self._source_target_counts()
        raw_target_counts = self._raw_source_target_counts()
        plan: list[tuple[list[str], int]] = []
        for source in _PLATFORM_SOURCE_ORDER:
            requested = self._source_requested_count(
                source,
                source_available_counts=source_available_counts,
                source_raw_counts=source_raw_counts,
                target_counts=target_counts,
                raw_target_counts=raw_target_counts,
            )
            if requested <= 0:
                continue
            if source == "bilibili":
                # Bilibili 现在是平台配额，但其实现仍扇出到四个既定策略名。
                plan.append((list(_BILIBILI_DISCOVERY_SOURCES), requested))
        return plan

    def _raw_material_ceiling(self) -> int:
        return max(self.pool_target_count * 2, self.pool_target_count + 120)

    def _source_target_counts(self, *, total: int | None = None) -> dict[str, int]:
        target_total = self.pool_target_count if total is None else max(0, int(total))
        shares = self._normalized_pool_source_shares()
        total_share = sum(shares.values())
        remaining = target_total
        targets: dict[str, int] = {}
        items = list(shares.items())
        for index, (source, share) in enumerate(items):
            if index == len(items) - 1:
                targets[source] = remaining
                break
            count = round(target_total * share / total_share)
            count = min(remaining, count)
            targets[source] = count
            remaining -= count
        return targets

    def _raw_source_target_counts(self) -> dict[str, int]:
        return self._source_target_counts(total=self._raw_material_ceiling())

    def _source_deficit(self, source_family: str) -> int:
        return self._source_requested_count(source_family)

    # ── keyword planner deficit / catalyst口径 (P1.6) ─────────────────────
    # 统一 keyword planner 复用这些方法，使其"真实 deficit"共享驱动池补货
    # 的同一道 available-pool deficit 口径，而不是简单地数可见池行数。
    # 原料余量仍会限制正常请求大小，但不能把低于目标的 available 池
    # 判定为"无 deficit"。

    def keyword_planner_real_deficit(self, platform: str) -> int:
        """单个平台的真实 search deficit。

        包装 ``_source_requested_count`` —— 即
        ``_build_source_replenishment_plan`` 使用的同一口径。``> 0`` 表示
        该平台确实需要更多 search 供给。
        """
        try:
            return int(self._source_requested_count(str(platform).strip()))
        except Exception:
            logger.exception("keyword_planner_real_deficit failed for %s", platform)
            return 0

    def keyword_planner_bilibili_catalyst(self) -> bool:
        """B站的额外 catalyst：池低于目标 OR 信号事件数 ≥ 阈值。

        镜像 ``_build_refresh_plan`` —— 当池低于目标（其四个策略会一起触发）
        或累计 ≥ ``signal_event_threshold`` 个信号事件（profile 可能刚刚漂移）
        时，即使 B站的 keyword 缓存还没低于低水位，B站 search 也会重新
        生成关键词。
        """
        try:
            pool_available = self.database.count_pool_candidates(
                xhs_self_nickname=self._xhs_self_nickname()
            )
        except TypeError:
            pool_available = self.database.count_pool_candidates()
        except Exception:
            logger.exception("keyword_planner_bilibili_catalyst pool count failed")
            return False
        if int(pool_available) < self.pool_target_count:
            return True
        try:
            state = self.memory_manager.load_discovery_runtime_state()
            pending_events = self._pending_signal_events_count(state)
        except Exception:
            logger.exception("keyword_planner_bilibili_catalyst signal count failed")
            return False
        return pending_events >= self.signal_event_threshold

    def _source_requested_count(
        self,
        source_family: str,
        *,
        source_available_counts: dict[str, int] | None = None,
        source_raw_counts: dict[str, int] | None = None,
        target_counts: dict[str, int] | None = None,
        raw_target_counts: dict[str, int] | None = None,
    ) -> int:
        if source_available_counts is None:
            source_available_counts = self._count_pool_available_candidates_by_source()
        if source_raw_counts is None:
            source_raw_counts = self._count_pool_raw_material_by_source()
        if target_counts is None:
            target_counts = self._source_target_counts()
        if raw_target_counts is None:
            raw_target_counts = self._raw_source_target_counts()

        available_target = int(target_counts.get(source_family, 0))
        current_available = self._platform_source_count(source_available_counts, source_family)
        available_deficit = max(0, available_target - current_available)
        try:
            current_global_available = self.database.count_pool_candidates(
                xhs_self_nickname=self._xhs_self_nickname()
            )
        except TypeError:
            current_global_available = self.database.count_pool_candidates()
        global_available_deficit = max(0, self.pool_target_count - int(current_global_available))
        raw_target = int(raw_target_counts.get(source_family, 0))
        current_raw = self._platform_source_count(source_raw_counts, source_family)
        raw_headroom = max(0, raw_target - current_raw)
        requested_by_available = max(0, min(available_deficit, global_available_deficit))
        if requested_by_available <= 0:
            return 0
        if raw_headroom > 0:
            return min(requested_by_available, raw_headroom)
        # 原料上限是修剪护栏，不是补货的硬停止。一个池可能原料充足，
        # 但仍远低于前端可服务的目标，因为已有行被 topic 窗口、可链接性、
        # 复制文本 / 分类就绪度或推荐历史挡住。在这种状态下返回 0 会
        # 把待处理关键词卡死，让调度器活着却无法发起搜索。
        return requested_by_available

    def _count_pool_available_candidates_by_source(self) -> dict[str, int]:
        count_fn = getattr(self.database, "count_pool_available_candidates_by_source", None)
        if callable(count_fn):
            try:
                counts = count_fn(xhs_self_nickname=self._xhs_self_nickname())
            except TypeError:
                counts = count_fn()
            return {str(source): int(count) for source, count in dict(counts).items()}
        self._warn_pool_count_fallback_once("available_by_source")
        return self.database.count_pool_candidates_by_source()

    def _count_pool_raw_material_by_source(self) -> dict[str, int]:
        count_fn = getattr(self.database, "count_pool_raw_material_by_source", None)
        if callable(count_fn):
            counts = count_fn()
            return {str(source): int(count) for source, count in dict(counts).items()}
        self._warn_pool_count_fallback_once("raw_material_by_source")
        return self.database.count_pool_candidates_by_source()

    def _warn_pool_count_fallback_once(self, key: str) -> None:
        if key in self._warned_pool_count_fallbacks:
            return
        self._warned_pool_count_fallbacks.add(key)
        logger.warning(
            "pool source count fallback used for %s; production should expose available/raw "
            "source counters to avoid raw-count deadlocks",
            key,
        )

    def _platform_source_count(self, source_counts: dict[str, int], source_family: str) -> int:
        if source_family == "bilibili":
            if "bilibili" in source_counts:
                return int(source_counts.get("bilibili", 0))
            return sum(int(source_counts.get(source, 0)) for source in _BILIBILI_DISCOVERY_SOURCES)
        return int(source_counts.get(source_family, 0))

    def _warn_on_stranded_source_shares(self) -> None:
        """启动时若任一配置了份额的来源没有对应 producer，则警告一次。

        ``runtime.source_policy.effective_pool_source_shares`` 已经剔除
        ``enabled`` 标志为 False 的来源，因此此处出现搁浅份额意味着用户
        保留了来源开关但未接上对应 producer（缺 build_*_producer、
        scheduler.enabled=False 等）。没有这个警告，池会永远停在
        ``pool_target_count`` 以下，而缺失的余量不可见。
        """
        shares = self._normalized_pool_source_shares()
        targets = self._source_target_counts()
        stranded: list[str] = []
        for source, target in targets.items():
            if target <= 0:
                continue
            if source == "bilibili":
                continue  # 始终由四个 discovery 策略服务
            if source == "xiaohongshu" and self.xhs_producer is None:
                stranded.append("xiaohongshu")
            elif source == "douyin" and self.douyin_producer is None:
                stranded.append("douyin")
            elif source == "youtube" and self.youtube_producer is None:
                stranded.append("youtube")
            elif source == "twitter" and self.x_producer is None:
                stranded.append("twitter")
            elif source == "zhihu" and self.zhihu_producer is None:
                stranded.append("zhihu")
            elif source not in {
                "bilibili",
                "xiaohongshu",
                "douyin",
                "youtube",
                "twitter",
                "zhihu",
            }:
                # 未知来源族却带显式份额。
                stranded.append(source)
        if stranded:
            logger.warning(
                "pool_source_shares allocate quota to sources without an "
                "active producer (will leave pool under target): sources=%s "
                "shares=%s",
                stranded,
                {s: shares.get(s) for s in stranded},
            )

    def _normalized_pool_source_shares(self) -> dict[str, int]:
        raw = self.pool_source_shares or _DEFAULT_PLATFORM_SOURCE_SHARES
        normalized: dict[str, int] = {}
        for source in _PLATFORM_SOURCE_ORDER:
            try:
                share = int(raw.get(source, 0))
            except (TypeError, ValueError):
                share = 0
            if share > 0:
                normalized[source] = share
        for source, raw_share in raw.items():
            source_key = str(source).strip().lower()
            if not source_key or source_key in normalized:
                continue
            try:
                share = int(raw_share)
            except (TypeError, ValueError):
                continue
            if share > 0:
                normalized[source_key] = share
        return normalized or dict(_DEFAULT_PLATFORM_SOURCE_SHARES)

    def _requested_refresh_limit(
        self,
        *,
        requested_limit: int,
        current_pool_count: int,
        pool_below_target: bool,
    ) -> int:
        """决定一次分组 discovery 调用应瞄准多少候选。

        v0.3.24+ 池感知 sizing。修复前每次分组调用强制 ``discovery_limit``
        (30) 的绝对下限，即使池在 595/600 只差 5 条也照办。4 个策略 × 30
        = 120 条候选要 LLM eval —— 而 suppress 阶段只留 ~20 条 —— 意味着
        ~80% 的 LLM eval 成本花在被立即压制的候选上。修复后每个策略的
        limit 取池总缺口与请求来源缺口的较小者（对低于评分阈值的项 1.5x
        超采样，下限 5 保证小缺口下分组调用仍可产出），并用
        ``discovery_limit`` 设上限，避免 init 后的突发补货变成一波单次巨浪。
        """
        if pool_below_target:
            total_gap = max(0, self.pool_target_count - current_pool_count)
            requested_gap = max(1, int(requested_limit))
            gap = min(total_gap, requested_gap)
            # 2-phase plan 按组派发策略；每策略目标约为
            # gap // (每阶段典型策略数 = 2)，并 1.5x 超采样以应对阈值过滤。
            # 下限 5，避免只找到 2 条感兴趣项的策略把池彻底饿死。
            per_strategy_target = max(5, gap * 3 // 4)
            # 用 discovery_limit 设上限，在缺口巨大时（如刚 init、刚修剪的池）
            # 保留原行为。
            effective_limit = min(self.discovery_limit, per_strategy_target)
            min_eval_batch = self._candidate_eval_batch_floor()
            if min_eval_batch > 1:
                effective_limit = max(effective_limit, min_eval_batch)
        else:
            effective_limit = max(self.discovery_limit, requested_limit)
        return min(_MAX_DISCOVERY_BACKFILL_PER_REFRESH, max(1, effective_limit))

    def _candidate_eval_batch_floor(self) -> int:
        pipeline = self.discovery_candidate_pipeline
        if pipeline is None:
            return 1
        try:
            configured = int(getattr(pipeline, "min_eval_batch_size", 1) or 1)
        except (TypeError, ValueError):
            configured = 1
        return min(_MAX_DISCOVERY_BACKFILL_PER_REFRESH, max(1, configured))

    def _candidate_eval_drain_batch_size(self, batch_size: int | None) -> int:
        default = min(
            _MAX_DISCOVERY_BACKFILL_PER_REFRESH,
            max(self.discovery_limit, _DEFAULT_CANDIDATE_EVAL_BATCH_SIZE),
        )
        if batch_size is None:
            return default
        try:
            requested = int(batch_size)
        except (TypeError, ValueError):
            return default
        if requested <= 0:
            return default
        return requested

    def _requested_strategy_limits(
        self,
        *,
        strategies: list[str],
        requested_limit: int,
        effective_limit: int,
        current_pool_count: int,
        pool_below_target: bool,
    ) -> dict[str, int] | None:
        """把一次分组 Bilibili refresh 预算切分到各策略。"""
        if not pool_below_target or len(strategies) <= 1:
            return None
        if not all(strategy in _BILIBILI_DISCOVERY_SOURCES for strategy in strategies):
            return None
        total_gap = max(1, self.pool_target_count - current_pool_count)
        requested_budget = max(1, int(requested_limit))
        if pool_below_target:
            min_eval_batch = self._candidate_eval_batch_floor()
            total_gap = max(total_gap, min_eval_batch)
            requested_budget = max(requested_budget, min_eval_batch)
        shared_budget = min(
            requested_budget,
            max(1, int(effective_limit)),
            total_gap,
        )
        if set(strategies) == set(_BILIBILI_DISCOVERY_SOURCES) and (
            self._should_defer_expensive_bilibili_strategies(total_gap)
        ):
            cheap = ["search", "related_chain"]
            cheap_limits = self._split_budget_across_strategies(cheap, shared_budget)
            return {strategy: cheap_limits.get(strategy, 0) for strategy in strategies}
        return self._split_budget_across_strategies(strategies, shared_budget)

    def _should_defer_expensive_bilibili_strategies(self, total_gap: int) -> bool:
        threshold = max(
            _BILIBILI_EXPENSIVE_DISCOVERY_MIN_GAP,
            int(self.pool_target_count * _BILIBILI_EXPENSIVE_DISCOVERY_GAP_RATIO),
        )
        return int(total_gap) < threshold

    @staticmethod
    def _split_budget_across_strategies(
        strategies: list[str],
        budget: int,
    ) -> dict[str, int]:
        if not strategies:
            return {}
        safe_budget = max(0, int(budget))
        base, extra = divmod(safe_budget, len(strategies))
        return {
            strategy: base + (1 if index < extra else 0)
            for index, strategy in enumerate(strategies)
        }

    def _is_initialized(self) -> bool:
        try:
            soul_layer = self.memory_manager.get_layer("soul")
        except Exception:
            return False
        data = getattr(soul_layer, "data", {})
        return isinstance(data, dict) and bool(data)

    @staticmethod
    def _parse_iso_datetime(value: str) -> datetime | None:
        if not value:
            return None
        with suppress(ValueError):
            return datetime.fromisoformat(value)
        return None

    @staticmethod
    def _int_state_value(state: dict[str, object], key: str) -> int:
        value = state.get(key, 0)
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str):
            with suppress(ValueError):
                return int(value)
        return 0

    def _is_due(self, value: str, *, hours: int) -> bool:
        if hours <= 0:
            return True
        last_run = self._parse_iso_datetime(value)
        if last_run is None:
            return True
        return self._now() - last_run >= timedelta(hours=hours)

    @staticmethod
    def _now() -> datetime:
        return datetime.now()

    @staticmethod
    def _list_state_value(state: dict[str, object], key: str) -> list[str]:
        raw_value = state.get(key, [])
        if not isinstance(raw_value, list):
            return []
        return [str(item).strip() for item in raw_value if str(item).strip()]

    @staticmethod
    def _extract_topics(discovered: list[Any]) -> list[str]:
        topics: list[str] = []
        strategy_map = {
            "search": "相近兴趣",
            "related_chain": "相关推荐",
            "trending": "站内热榜",
            "explore": "跨圈探索",
        }
        for item in discovered:
            tags: Any = (
                item.get("tags", []) if isinstance(item, dict) else getattr(item, "tags", [])
            )
            if isinstance(tags, list):
                for tag in tags:
                    text = str(tag).strip()
                    if text:
                        topics.append(text)
            if isinstance(item, dict):
                source_strategy = str(item.get("source_strategy", "")).strip()
            else:
                source_strategy = str(getattr(item, "source_strategy", "")).strip()
            if source_strategy:
                topics.append(strategy_map.get(source_strategy, source_strategy))
        return topics

    @staticmethod
    def _dedupe_topics(topics: list[str]) -> list[str]:
        seen: set[str] = set()
        ordered: list[str] = []
        for topic in topics:
            text = topic.strip()
            if not text or text in seen:
                continue
            seen.add(text)
            ordered.append(text)
        return ordered
