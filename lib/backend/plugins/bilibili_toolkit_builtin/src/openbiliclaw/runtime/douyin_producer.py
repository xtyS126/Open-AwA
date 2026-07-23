"""运行时 Douyin 发现 producer。

持续刷新控制器拥有内容池配额。本 producer 在 Douyin 平台族
仍处于配额内时，负责对可复用 Douyin 发现服务做节流调用。
"""

from __future__ import annotations

import logging
import math
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from openbiliclaw.discovery.douyin import DouyinDiscoveryOptions, DouyinDiscoveryResult
from openbiliclaw.runtime.keyword_fetch import PLATFORM_DOUYIN as _PLATFORM_DOUYIN
from openbiliclaw.sources.douyin_plugin_search import (
    DouyinBudgetExhausted as _DouyinBudgetExhausted,
)

logger = logging.getLogger(__name__)

DouyinDiscoverCallable = Callable[[Any, DouyinDiscoveryOptions], Awaitable[DouyinDiscoveryResult]]
_DOUYIN_SCORE_THRESHOLDS = {
    "search": 0.60,
    "hot": 0.60,
    "feed": 0.60,
}
_DOUYIN_DEFAULT_SCORE_THRESHOLD = _DOUYIN_SCORE_THRESHOLDS["search"]


def douyin_runtime_hot_budget(*, base_budget: int, requested_limit: int) -> int:
    """返回单次运行时补货使用的有效热榜任务预算。"""
    configured = int(base_budget)
    if configured <= 0:
        return 0
    requested = max(1, int(requested_limit))
    if requested < 10:
        return configured
    return max(configured, min(60, requested))


@dataclass
class DouyinDiscoveryProducer:
    """从运行时循环中对 Douyin 发现做节流调用。"""

    soul_engine: Any
    discover: DouyinDiscoverCallable
    enabled: bool = True
    min_interval_minutes: int = 30
    sources: tuple[str, ...] = ("search", "hot", "feed")
    evaluate: bool = True
    candidate_pipeline: Any | None = None
    per_source_limit: int = 20
    # 统一关键词规划器抓取协调器（P1.7）。当其接入且开关打开时，
    # producer 的 search 源会从关键词存储中 claim 单词，并走内联准入
    # 生命周期（used / failed / budget-rollback）。``None``（默认 /
    # 测试 / 开关关闭）→ 走旧路径。
    keyword_fetch: Any | None = None
    _last_run_at: datetime | None = field(default=None, init=False)
    _last_skip_reason: str = field(default="", init=False)

    async def produce_if_due(self, *, limit: int | None = None) -> dict[str, object]:
        """启用且到期时，运行一次 Douyin 发现循环。"""
        if not self.enabled:
            return self._skip("disabled")
        if not self._is_due():
            return self._skip("throttled")
        if self._candidate_pool_full():
            return self._skip("pool_full")

        try:
            profile = await self.soul_engine.get_profile()
        except Exception as exc:
            logger.debug("douyin producer: soul profile unavailable: %s", exc)
            return self._skip("no_profile")
        if profile is None:
            return self._skip("no_profile")

        requested_limit = max(1, int(limit or self.per_source_limit))
        selected_sources = self._sources_for_limit(requested_limit)
        per_source_limit = max(
            1,
            min(
                self.per_source_limit,
                math.ceil(requested_limit / max(1, len(selected_sources))),
            ),
        )
        use_candidate_pipeline = self.candidate_pipeline is not None

        # 统一关键词规划器抓取路径（P1.7，开关控制）。仅当本次运行
        # 真的包含 ``search`` 源时才走——纯 hot/feed 运行绝不触碰
        # 关键词存储。缺口闸门在上游强制（控制器只在 douyin 处于
        # 配额内时才调用 producer）；最小间隔底线由上方
        # ``_is_due`` 的 ``min_interval`` 提供。
        claimed: list[Any] = []
        coordinator = self.keyword_fetch
        flag_on_search = (
            coordinator is not None
            and bool(getattr(coordinator, "should_claim", lambda: False)())
            and "search" in selected_sources
        )
        if flag_on_search and coordinator is not None:
            claimed = coordinator.claim(_PLATFORM_DOUYIN)
            if not claimed:
                # 开关打开但存储中没有可 claim 的待处理词 → 本轮跳过
                # search 抓取（由规划器再补充）；不要绕开规划器跑一次
                # 旧路径的自生成搜索。
                return self._skip("no_keywords")

        options = DouyinDiscoveryOptions(
            limit=requested_limit,
            sources=selected_sources,
            cache=not use_candidate_pipeline,
            evaluate=False if use_candidate_pipeline else self.evaluate,
            per_source_limit=per_source_limit,
            keywords_per_run=1,
            keywords=tuple(item.keyword for item in claimed) if claimed else (),
            # P1.8：把产出词的 id 透传到每条 search 候选上，便于准入
            # 时回填 yield。
            keyword_ids={item.keyword: int(item.id) for item in claimed} if claimed else {},
            raise_on_budget=bool(claimed),
        )
        try:
            result = await self.discover(profile, options)
        except _DouyinBudgetExhausted:
            # 已 claim 但插件搜索预算耗尽 → 没有 search 实际跑过 →
            # 把每个 claimed 词回滚为 pending（不要当作 used 烧掉）。
            if coordinator is not None:
                for item in claimed:
                    coordinator.rollback(item)
            return self._skip("budget_exhausted")
        except Exception as exc:
            logger.warning("douyin producer failed: %s", exc)
            if claimed and coordinator is not None:
                coordinator.mark_failed(claimed)
            return self._skip("error")

        # 内联准入生命周期：成功返回且产出了候选 → 把所有 claimed 词
        # 标记为 ``used``；空抓取 → 标记为 ``failed``（重试）。
        # yield 回填属于 P1.8，与 ``used`` 解耦。
        if claimed and coordinator is not None:
            if result.items:
                coordinator.mark_used(claimed)
            else:
                coordinator.mark_failed(claimed)

        self._last_run_at = datetime.now(UTC)
        payload: dict[str, object] = {
            "discovered": len(result.items),
            "source_counts": dict(result.source_counts),
            "reason": "ok",
        }
        if self.candidate_pipeline is None:
            payload["cached"] = result.cached
            return payload

        self._stamp_candidate_score_thresholds(result.items)
        enqueued = int(
            self.candidate_pipeline.enqueue_candidates(
                list(result.items),
                source_context="douyin",
            )
        )
        payload["enqueued"] = enqueued
        if enqueued > 0:
            drain_result = await self.candidate_pipeline.drain_pending(
                profile=profile,
                batch_size=requested_limit,
            )
            payload.update(drain_result)
        return payload

    def _is_due(self) -> bool:
        if self.min_interval_minutes <= 0:
            return True
        if self._last_run_at is None:
            return True
        return datetime.now(UTC) - self._last_run_at >= timedelta(minutes=self.min_interval_minutes)

    def _sources_for_limit(self, requested_limit: int) -> tuple[str, ...]:
        configured = tuple(source for source in self.sources if str(source).strip())
        if requested_limit >= 10:
            selected = tuple(source for source in ("search", "hot") if source in configured)
            if selected:
                return selected
            return configured[:1] or ("search",)

        preferred = ("feed",) if requested_limit <= 3 else ("hot", "feed")
        selected = tuple(source for source in preferred if source in configured)
        if selected:
            return selected

        non_search = tuple(source for source in configured if source != "search")
        if non_search:
            return non_search[:1]
        return configured[:1] or ("search",)

    def _candidate_pool_full(self) -> bool:
        if self.candidate_pipeline is None:
            return False
        pool_full = getattr(self.candidate_pipeline, "pool_full", None)
        if not callable(pool_full):
            return False
        try:
            return bool(pool_full())
        except Exception:
            logger.debug("douyin producer: candidate pool fullness unavailable", exc_info=True)
            return False

    def _stamp_candidate_score_thresholds(self, items: list[Any]) -> None:
        for item in items:
            try:
                if float(getattr(item, "score_threshold", 0.0) or 0.0) > 0:
                    continue
                item.score_threshold = self._score_threshold_for_item(item)
            except Exception:
                logger.debug("douyin producer: failed to stamp score threshold", exc_info=True)

    @staticmethod
    def _score_threshold_for_item(item: Any) -> float:
        strategy = str(getattr(item, "source_strategy", "") or "").strip().lower()
        for key, threshold in _DOUYIN_SCORE_THRESHOLDS.items():
            if key in strategy:
                return threshold
        return _DOUYIN_DEFAULT_SCORE_THRESHOLD

    def _skip(self, reason: str) -> dict[str, object]:
        if reason != self._last_skip_reason:
            logger.info("douyin producer skip: reason=%s", reason)
        self._last_skip_reason = reason
        return {"discovered": 0, "reason": reason}


def build_douyin_discovery_producer(
    *,
    config: Any,
    database: Any,
    soul_engine: Any,
    discovery_engine: Any,
    candidate_pipeline: Any | None = None,
    keyword_fetch: Any | None = None,
) -> DouyinDiscoveryProducer | None:
    """当 Douyin 发现启用时构建运行时 Douyin producer。"""
    dy_cfg = getattr(getattr(config, "sources", None), "douyin", None)
    if dy_cfg is None or not bool(getattr(dy_cfg, "enabled", False)):
        return None
    if str(getattr(dy_cfg, "mode", "direct")).strip().lower() != "direct":
        logger.info("douyin producer disabled: unsupported mode=%r", getattr(dy_cfg, "mode", ""))
        return None
    if not hasattr(database, "conn"):
        logger.info("douyin producer disabled: database does not expose task tables")
        return None

    async def _discover(profile: Any, options: DouyinDiscoveryOptions) -> DouyinDiscoveryResult:
        from openbiliclaw.discovery.douyin import DouyinDiscoveryService
        from openbiliclaw.sources.douyin_auth import resolve_douyin_cookie
        from openbiliclaw.sources.douyin_direct import DouyinDirectClient
        from openbiliclaw.sources.douyin_plugin_search import DouyinPluginSearchClient

        cookie_env = str(getattr(dy_cfg, "cookie_env", "OPENBILICLAW_DOUYIN_COOKIE"))
        cookie = resolve_douyin_cookie(
            data_dir=config.data_path,
            cookie_env=cookie_env,
        )
        if not cookie:
            raise RuntimeError(
                f"missing Douyin cookie; set {cookie_env} or keep the browser extension online"
            )

        async with DouyinDirectClient(cookie=cookie) as direct_client:
            client: Any = direct_client
            if any(source in options.sources for source in ("search", "hot", "feed")):
                wait_seconds = float(
                    os.environ.get("OPENBILICLAW_DY_DISCOVERY_SEARCH_WAIT_SECONDS", "180")
                )
                client = DouyinPluginSearchClient(
                    database=database,
                    direct_client=direct_client,
                    wait_seconds=wait_seconds,
                    daily_search_budget=int(getattr(dy_cfg, "daily_search_budget", 0)),
                    daily_hot_budget=douyin_runtime_hot_budget(
                        base_budget=int(getattr(dy_cfg, "daily_hot_budget", 0)),
                        requested_limit=options.limit,
                    ),
                    daily_feed_budget=int(getattr(dy_cfg, "daily_feed_budget", 0)),
                    # 统一关键词规划器抓取路径：把预算耗尽暴露成可区分
                    # 信号，使 claimed 词被回滚而不是被烧掉（P1.7）。
                    raise_on_budget=bool(getattr(options, "raise_on_budget", False)),
                )
            service = DouyinDiscoveryService(
                client=client,
                discovery_engine=discovery_engine,
            )
            return await service.discover(profile, options)

    scheduler = getattr(config, "scheduler", None)
    return DouyinDiscoveryProducer(
        soul_engine=soul_engine,
        discover=_discover,
        enabled=bool(getattr(scheduler, "enabled", True)),
        min_interval_minutes=30,
        sources=("search", "hot", "feed"),
        candidate_pipeline=candidate_pipeline,
        per_source_limit=20,
        keyword_fetch=keyword_fetch,
    )
