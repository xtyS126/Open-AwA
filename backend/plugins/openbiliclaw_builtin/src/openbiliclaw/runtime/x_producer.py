"""Runtime X (Twitter) 发现 producer —— fetch-only。

X 稳态发现是服务端 cookie 重放（与 Bilibili / Douyin-direct 一样）。
每个节流窗口一次，此 producer：

  1. 读取当前的 SoulProfile。
  2. 通过 :class:`XAdapter` 运行三个注入的策略：
     ``search``（soul 驱动的关键词）、``feed``（For-You 主页时间线，
     节流到低每日节拍）和 ``creator``（每个订阅到期通过
     :class:`XCreatorStore` 进行 fetch）。
  3. 将产生的 :class:`DiscoveredContent` 入队到
     ``discovery_candidates`` pending 池。

**Fetch-only 契约（统一池规范）。** producer 永不评估，永不写入
``content_cache``。它只入队原始候选；共享的混合源评估器（由刷新循环
的 drain 驱动）拥有评分和 admission。这里没有 ``drain_pending`` 调用。

**懒加载。** 禁用路径是纯 no-op，不从 ``twitter_cli`` 导入任何内容
—— 注入的 ``XAdapter`` / ``XClient`` 在自己的网络接口上拥有懒加载，
此模块在加载时永不引用它们。

**源健康（规范 §7）。** 每个周期前 producer 会查询持久化的
:class:`XSourceHealthStore`：当处于重新登录状态
（``missing_cookie`` / ``expired_cookie`` / ``blocked``）或未过期的
速率限制冷却中时完全跳过，并在重复的 For-You 失败自动暂停后跳过
（高曝光度的）For-You feed。每次策略运行记录成功 / 错误，以便状态机
和状态 API 保持最新。
"""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from openbiliclaw.discovery.candidate_pool import discovered_content_to_candidate_write
from openbiliclaw.runtime.keyword_fetch import PLATFORM_TWITTER as _PLATFORM_TWITTER

if TYPE_CHECKING:
    from openbiliclaw.discovery.engine import DiscoveredContent
    from openbiliclaw.sources.x_tasks import XCreatorStore
    from openbiliclaw.storage.x_health import XSourceHealthStore

logger = logging.getLogger(__name__)

# 三个服务端 X 发现策略。adapter 在 ``recipe.strategy`` 上 dispatch；
# 这些名称与 XAdapter.fetch 匹配。
SEARCH = "search"
FEED = "feed"
CREATOR = "creator"
X_DISCOVERY_STRATEGIES = (SEARCH, FEED, CREATOR)

_X_SCORE_THRESHOLDS = {
    SEARCH: 0.60,
    FEED: 0.60,
    CREATOR: 0.60,
}


@dataclass
class XDiscoveryProducer:
    """在 runtime 循环中对 X 发现进行节流和调用（fetch-only）。"""

    database: Any
    soul_engine: Any
    adapter: Any  # XAdapter（结构化：.fetch(recipe, profile, limit), .source_type）
    creator_store: XCreatorStore
    health_store: XSourceHealthStore
    enabled: bool = True
    min_interval_minutes: int = 60
    daily_search_budget: int = 0
    daily_feed_budget: int = 0
    daily_creator_budget: int = 0
    request_interval_seconds: int = 3
    creator_refresh_hours: int = 24
    # 可选 —— 仅用于检测候选池已满状态。永不用于评估或 admission
    # （fetch-only）；访问 evaluator 方法将是 bug，
    # ``tests/test_x_producer.py`` 断言了一个 exploding stub 防止此情况。
    discovery_engine: Any | None = None
    # 统一关键词规划器 fetch coordinator (P1.7)。当已接入且开关
    # 打开时，search 策略从关键词 store claim 词并通过
    # ``recipe.config["queries"]`` 注入；当原始候选移交给
    # ``discovery_candidates`` 后，这些词被标记为 ``used``
    # （fetch-only：admission 在下游）。``None``（默认 / 开关关闭）→ 传统路径。
    keyword_fetch: Any | None = None
    _last_run_at: datetime | None = field(default=None, init=False)
    _last_skip_reason: str = field(default="", init=False)

    async def produce_if_due(self, *, limit: int | None = None) -> dict[str, object]:
        """如果已启用、到期、健康且在预算内，则运行一个 X 发现周期。"""
        if not self.enabled:
            return self._skip("disabled")
        if not self._is_due():
            return self._skip("throttled")
        if not self.health_store.is_ready():
            # missing/expired cookie、block 或未过期的速率限制冷却。
            return self._skip("unhealthy")

        is_ready_fn = getattr(self.soul_engine, "is_profile_ready", None)
        if callable(is_ready_fn) and not is_ready_fn():
            logger.debug("x producer: soul profile not ready yet")
            return self._skip("no_profile")
        try:
            profile = await self.soul_engine.get_profile()
        except Exception as exc:
            logger.debug("x producer: soul profile unavailable: %s", exc)
            return self._skip("no_profile")
        if profile is None:
            return self._skip("no_profile")

        requested_limit = max(1, int(limit or 10))
        items: list[DiscoveredContent] = []

        # 1. Search —— soul 驱动的关键词（adapter 的 search 策略
        #    在没有显式 query 时从 profile 生成关键词）。
        #    统一关键词规划器 fetch 路径 (P1.7，开关受控)：从 store
        #    claim 词并通过 recipe.config["queries"] 注入。缺口门控在
        #    上游（controller 只在 X 低于配额时调用 producer）；区分
        #    下限是上面的 ``min_interval`` / ``_is_due``；每日 search
        #    预算仍然门控本次运行。
        claimed_search: list[Any] = []
        if self._strategy_budget_remaining(SEARCH, requested_limit) > 0:
            coordinator = self.keyword_fetch
            if coordinator is not None and bool(
                getattr(coordinator, "should_claim", lambda: False)()
            ):
                claimed_search = coordinator.claim(_PLATFORM_TWITTER)
                if claimed_search:
                    # P1.8：将生产关键词的 id 串接到每个候选，
                    # 以便 admit-time yield 回填记入正确的词。
                    search_config = {
                        "queries": [item.keyword for item in claimed_search],
                        "keyword_ids": {item.keyword: int(item.id) for item in claimed_search},
                    }
                    items += await self._run_strategy(
                        SEARCH, profile, config=search_config, limit=requested_limit
                    )
                # 开关打开但 store 为空 → 本周期跳过 search fetch
                # （planner 会重新填充）；下面的 feed/creator 仍然运行。
            else:
                items += await self._run_strategy(SEARCH, profile, config={}, limit=requested_limit)

        # 2. For-You —— 高曝光度；节流到低每日节拍，并且
        #    在重复 feed 失败后自动暂停。
        if (
            self.health_store.feed_allowed()
            and self._strategy_budget_remaining(FEED, requested_limit) > 0
        ):
            items += await self._run_strategy(FEED, profile, config={}, limit=requested_limit)

        # 3. Creators —— 每个到期刷新的订阅。
        items += await self._run_creators(profile, requested_limit)

        enqueued = self._enqueue(items)
        # Fetch-only 生命周期：claimed 的 search 词在上面原始候选移交给
        # ``discovery_candidates`` 时被消耗 —— 将它们标记为
        # ``used``（admission 在下游；yield 回填是 P1.8）。
        if claimed_search and self.keyword_fetch is not None:
            self.keyword_fetch.mark_used(claimed_search)
        self._last_run_at = datetime.now(UTC)
        return {"enqueued": enqueued, "discovered": len(items), "reason": "ok"}

    # ── 策略执行 ───────────────────────────────────────────

    async def _run_strategy(
        self,
        strategy: str,
        profile: Any,
        *,
        config: dict[str, Any],
        limit: int,
    ) -> list[DiscoveredContent]:
        """通过 adapter fetch 一个策略，记录健康 + 预算。"""
        from openbiliclaw.sources.protocol import SourceRecipe

        recipe = SourceRecipe(
            id=f"x-{strategy}",
            source_type=getattr(self.adapter, "source_type", "twitter"),
            name=f"X-{strategy}",
            strategy=strategy,
            config=dict(config),
        )
        await self._jitter()
        try:
            items = await self.adapter.fetch(recipe, profile, limit)
        except Exception as exc:  # noqa: BLE001 - 规范化为健康状态
            self.health_store.record_error(exc, strategy=strategy)
            logger.warning("x producer strategy failed: strategy=%s error=%s", strategy, exc)
            return []
        self.health_store.record_success(strategy=strategy)
        self._record_run(strategy)
        self._stamp_score_thresholds(items, strategy=strategy)
        return list(items)

    async def _run_creators(self, profile: Any, limit: int) -> list[DiscoveredContent]:
        """在预算内 fetch 每个到期刷新的订阅，最旧的优先。"""
        if self._strategy_budget_remaining(CREATOR, limit) <= 0:
            return []
        try:
            due = self.creator_store.due_for_fetch(hours=self.creator_refresh_hours)
        except Exception:
            logger.debug("x producer: creator due-list unavailable", exc_info=True)
            return []
        out: list[DiscoveredContent] = []
        for sub in due:
            if self._strategy_budget_remaining(CREATOR, limit) <= 0:
                break
            handle = str(sub.get("handle", "") or "").strip()
            if not handle:
                continue
            fetched = await self._run_strategy(
                CREATOR, profile, config={"handle": handle}, limit=limit
            )
            out += fetched
            sub_id = int(sub.get("id", 0) or 0)
            if sub_id > 0:
                self.creator_store.mark_fetched(sub_id)
        return out

    # ── 候选入队（fetch-only） ───────────────────────────────

    def _enqueue(self, items: list[DiscoveredContent]) -> int:
        """将原始项入队到 ``discovery_candidates``（永不写入 content_cache）。"""
        if not items:
            return 0
        writes = [
            discovered_content_to_candidate_write(item, source_context=item.source_strategy)
            for item in items
        ]
        try:
            return int(self.database.enqueue_discovery_candidates(writes))
        except Exception:
            logger.warning("x producer: candidate enqueue failed", exc_info=True)
            return 0

    @staticmethod
    def _stamp_score_thresholds(items: list[DiscoveredContent], *, strategy: str) -> None:
        threshold = _X_SCORE_THRESHOLDS.get(strategy, 0.60)
        for item in items:
            try:
                if float(getattr(item, "score_threshold", 0.0) or 0.0) > 0:
                    continue
                item.score_threshold = threshold
            except Exception:
                logger.debug("x producer: failed to stamp score threshold", exc_info=True)

    # ── 预算 + 间隔 ───────────────────────────────────────────

    def _strategy_budget_remaining(self, strategy: str, per_run_budget: int) -> int:
        """返回今日某策略的可运行单元数。

        ``daily_*_budget == 0`` 表示无每日上限（受 runtime deficit
        ``per_run_budget`` 约束）。``< 0`` 完全禁用该策略。
        镜像 YouTube producer 约定。
        """
        budget = {
            SEARCH: int(self.daily_search_budget),
            FEED: int(self.daily_feed_budget),
            CREATOR: int(self.daily_creator_budget),
        }.get(strategy, 0)
        if budget == 0:
            return max(1, int(per_run_budget))
        if budget < 0:
            return 0
        return max(0, budget - self._consumed_today(strategy))

    def _consumed_today(self, strategy: str) -> int:
        self._ensure_ledger_table()
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        row = self.database.conn.execute(
            "SELECT COUNT(*) FROM x_discovery_runs WHERE strategy = ? AND created_at >= ?",
            (strategy, today),
        ).fetchone()
        return int(row[0] if row is not None else 0)

    def _record_run(self, strategy: str) -> None:
        self._ensure_ledger_table()
        self.database.conn.execute(
            "INSERT INTO x_discovery_runs(strategy) VALUES (?)",
            (strategy,),
        )
        self.database.conn.commit()

    def _ensure_ledger_table(self) -> None:
        self.database.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS x_discovery_runs (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                strategy   TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_x_discovery_runs_strategy_created
                ON x_discovery_runs(strategy, created_at);
            """
        )
        self.database.conn.commit()

    def _is_due(self) -> bool:
        if self.min_interval_minutes <= 0:
            return True
        if self._last_run_at is None:
            return True
        return datetime.now(UTC) - self._last_run_at >= timedelta(minutes=self.min_interval_minutes)

    async def _jitter(self) -> None:
        """在 X 请求之间 sleep ``request_interval_seconds``（+ jitter）。"""
        base = max(0, int(self.request_interval_seconds))
        if base <= 0:
            return
        await asyncio.sleep(base + random.uniform(0, base))

    def _skip(self, reason: str) -> dict[str, object]:
        if reason != self._last_skip_reason:
            logger.info("x producer skip: reason=%s", reason)
        self._last_skip_reason = reason
        return {"enqueued": 0, "discovered": 0, "reason": reason}


def build_x_discovery_producer(
    *,
    config: Any,
    database: Any,
    soul_engine: Any,
    llm_service: Any,
    keyword_fetch: Any | None = None,
) -> XDiscoveryProducer | None:
    """如果 X 源已启用则构建 runtime X producer。

    当 X 被禁用或 scheduler 关闭时返回 ``None``（并不从 ``twitter_cli``
    导入任何内容）—— 为非 X 安装保留懒加载契约。在启用路径上它构造
    单个 :class:`XClient` + :class:`XAdapter` 之后的三个策略
    （服务端 cookie 重放），以及用于按 code 退避的
    :class:`XSourceHealthStore`。
    """
    x_cfg = getattr(getattr(config, "sources", None), "twitter", None)
    if x_cfg is None or not bool(getattr(x_cfg, "enabled", False)):
        return None
    sched_cfg = getattr(config, "scheduler", None)
    if not bool(getattr(sched_cfg, "enabled", True)):
        return None
    if not hasattr(database, "conn"):
        logger.info("x producer disabled: database does not expose task tables")
        return None

    # 懒加载 —— 仅在启用路径上到达。
    from openbiliclaw.discovery.strategies.x import (
        XCreatorStrategy,
        XForYouStrategy,
        XSearchStrategy,
    )
    from openbiliclaw.sources.twitter_adapter import XAdapter
    from openbiliclaw.sources.x_auth import resolve_x_cookie
    from openbiliclaw.sources.x_client import XClient
    from openbiliclaw.sources.x_tasks import XCreatorStore
    from openbiliclaw.storage.x_health import XSourceHealthStore

    cookie = resolve_x_cookie(
        data_dir=config.data_path,
        cookie_env=str(getattr(x_cfg, "cookie_env", "OPENBILICLAW_X_COOKIE")),
    )
    x_client = XClient(cookie=cookie)
    adapter = XAdapter(
        client=x_client,
        search=XSearchStrategy(client=x_client, llm_service=llm_service),
        feed=XForYouStrategy(client=x_client),
        creator=XCreatorStrategy(client=x_client),
    )
    return XDiscoveryProducer(
        database=database,
        soul_engine=soul_engine,
        adapter=adapter,
        creator_store=XCreatorStore(database),
        health_store=XSourceHealthStore(database),
        enabled=True,
        min_interval_minutes=int(getattr(x_cfg, "min_interval_minutes", 60)),
        daily_search_budget=int(getattr(x_cfg, "daily_search_budget", 0)),
        daily_feed_budget=int(getattr(x_cfg, "daily_feed_budget", 0)),
        daily_creator_budget=int(getattr(x_cfg, "daily_creator_budget", 0)),
        request_interval_seconds=int(getattr(x_cfg, "request_interval_seconds", 3)),
        keyword_fetch=keyword_fetch,
    )
