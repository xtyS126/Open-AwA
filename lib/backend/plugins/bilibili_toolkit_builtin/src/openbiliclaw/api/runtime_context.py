"""可变运行时组件容器，支持配置热重载。

所有 FastAPI 端点闭包都通过单一的 ``RuntimeContext`` 实例访问运行时
组件。当配置在运行时变更（通过 ``PUT /api/config``）时，context 原子地
重建每个可交换组件，使新设置立即生效 —— 无需重启服务。

**稳定组件**（从不重建）：
  - ``database`` —— 持有 SQLite 连接
  - ``memory_manager`` —— 持有文件-backed 的记忆层
  - ``event_hub`` —— 持有活跃的 WebSocket 订阅者队列
  - ``presence`` —— 跟踪共享的扩展 runtime-stream 在线状态

**可交换组件**（热重载时重建）：
  - ``llm_registry``、``llm_service``、``bilibili_client``
  - ``soul_engine``、``dialogue``
  - ``discovery_engine``、``recommendation_engine``
  - ``runtime_controller``、``account_sync_service``
  - ``auto_update_service``
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast

from openbiliclaw.config import llm_concurrency_from_config as _llm_concurrency_from_config
from openbiliclaw.runtime.presence import PresenceTracker
from openbiliclaw.runtime.presence import background_llm_work_allowed as _gate
from openbiliclaw.runtime.source_policy import effective_pool_source_shares
from openbiliclaw.runtime.task_registry import BackgroundTaskRegistry

if TYPE_CHECKING:
    from fastapi import FastAPI

    from openbiliclaw.config import Config
    from openbiliclaw.storage.database import Database

logger = logging.getLogger(__name__)


def _pool_source_shares_from_config(config: Any) -> dict[str, int]:
    return effective_pool_source_shares(config)


def build_youtube_discovery_strategies(
    *,
    config: Any,
    client: Any,
    llm_service: Any,
    memory: Any,
    concurrency: Any,
    database: Database | None = None,
    strategy_unit_budget: dict[str, int] | None = None,
) -> list[Any]:
    """根据 `[sources.youtube]` 配置构建 YouTube 发现策略。"""

    from openbiliclaw.discovery.strategies.youtube import (
        YoutubeChannelStrategy,
        YoutubeSearchStrategy,
        YoutubeTrendingStrategy,
    )

    yt_cfg = getattr(getattr(config, "sources", None), "youtube", None)
    budgets = strategy_unit_budget or {}
    scheduler = getattr(config, "scheduler", None)
    default_run_budget = max(1, int(getattr(scheduler, "discovery_limit", 30)))

    def _strategy_budget(strategy: str, attr: str) -> int:
        if strategy in budgets:
            return int(budgets[strategy])
        configured = int(getattr(yt_cfg, attr, 0))
        return default_run_budget if configured <= 0 else configured

    search_budget = _strategy_budget("yt_search", "daily_search_budget")
    trending_budget = _strategy_budget("yt_trending", "daily_trending_budget")
    channel_budget = _strategy_budget("yt_channel", "daily_channel_budget")
    return [
        YoutubeSearchStrategy(
            client=client,
            llm_service=llm_service,
            concurrency=concurrency,
            database=database,
            queries_per_run=max(0, search_budget),
        ),
        YoutubeTrendingStrategy(
            client=client,
            llm_service=llm_service,
            concurrency=concurrency,
            database=database,
            fetch_limit=max(0, trending_budget),
        ),
        YoutubeChannelStrategy(
            client=client,
            llm_service=llm_service,
            memory=memory,
            concurrency=concurrency,
            database=database,
            max_channels=max(0, channel_budget),
        ),
    ]


def _youtube_strategy_units_used(strategy: Any, *, fallback: int) -> int:
    """返回一次 YouTube 策略运行所消耗的执行单元数。"""
    name = str(getattr(strategy, "name", ""))
    intermediates = getattr(strategy, "last_intermediates", {}) or {}
    if name == "yt_search":
        queries = intermediates.get("queries")
        if isinstance(queries, list):
            return len(queries)
    if name == "yt_trending":
        fetched = intermediates.get("fetched")
        if isinstance(fetched, int):
            return fetched
    if name == "yt_channel":
        channel_ids = intermediates.get("channel_ids")
        if isinstance(channel_ids, list):
            return len(channel_ids)
    return max(0, int(fallback))


def _build_yt_scraper_client() -> Any:
    from openbiliclaw.youtube.client import YtScraperClient

    return YtScraperClient()


def build_youtube_discovery_producer(
    *,
    config: Any,
    database: Any,
    soul_engine: Any,
    discovery_engine: Any,
    llm_service: Any,
    memory: Any,
    concurrency: Any,
    candidate_pipeline: Any | None = None,
    keyword_fetch: Any | None = None,
) -> Any | None:
    """若启用了 YouTube 发现，则构建运行时 YouTube producer。"""
    yt_cfg = getattr(getattr(config, "sources", None), "youtube", None)
    if yt_cfg is None or not bool(getattr(yt_cfg, "enabled", False)):
        return None
    scheduler = getattr(config, "scheduler", None)
    if not bool(getattr(scheduler, "enabled", True)):
        return None
    if not hasattr(database, "conn"):
        logger.info("youtube producer disabled: database does not expose sqlite connection")
        return None

    from openbiliclaw.runtime.youtube_producer import (
        YoutubeDiscoveryProducer,
        YoutubeStrategyRunResult,
    )

    try:
        yt_client = _build_yt_scraper_client()
    except ImportError as exc:
        logger.info("youtube producer disabled: YouTube dependencies unavailable: %s", exc)
        return None

    async def _discover(
        profile: Any,
        *,
        strategy: str,
        unit_budget: int,
        result_limit: int,
        queries: list[str] | None = None,
        keyword_ids: dict[str, int] | None = None,
    ) -> YoutubeStrategyRunResult:
        strategies = build_youtube_discovery_strategies(
            config=config,
            client=yt_client,
            llm_service=llm_service,
            memory=memory,
            concurrency=concurrency,
            database=database,
            strategy_unit_budget={strategy: unit_budget},
        )
        selected = [item for item in strategies if item.name == strategy]
        if not selected:
            return YoutubeStrategyRunResult(items=[], units_used=0, source_counts={})

        selected_strategy = selected[0]
        discovery_engine.register_strategy(selected_strategy)
        # 统一关键词规划器注入（P1.7）：将认领的词作为 ``keywords`` 转发给
        # engine；engine 将其映射到策略的 ``queries`` 参数（仅 ``yt_search``
        # 声明了该参数）。``None`` 保持 legacy 自生成行为字节一致。
        inject: dict[str, Any] = {}
        if queries is not None:
            inject["keywords"] = list(queries)
        # P1.8 yield provenance：转发 keyword→id 映射，使 engine 为每个
        # 产出项的 ``source_keyword_id`` 盖章，供准入时回填使用。
        if keyword_ids:
            inject["keyword_ids"] = dict(keyword_ids)
        produce_fn = getattr(discovery_engine, "produce_candidates", None)
        if callable(produce_fn):
            raw_items = await produce_fn(
                profile,
                strategies=[strategy],
                limit=max(1, int(result_limit)),
                **inject,
            )
        else:
            raw_items = await discovery_engine.discover(
                profile,
                strategies=[strategy],
                limit=max(1, int(result_limit)),
                **inject,
            )
        items = [
            item
            for item in raw_items
            if str(getattr(item, "source_platform", "")) == "youtube"
            or str(getattr(item, "source_strategy", "")).startswith("yt_")
        ]
        units_used = _youtube_strategy_units_used(
            selected_strategy,
            fallback=max(0, int(unit_budget)),
        )
        return YoutubeStrategyRunResult(
            items=items,
            units_used=units_used,
            source_counts={strategy: len(items)},
        )

    return YoutubeDiscoveryProducer(
        database=database,
        soul_engine=soul_engine,
        discover=_discover,
        enabled=True,
        min_interval_minutes=int(getattr(yt_cfg, "min_interval_minutes", 60)),
        daily_search_budget=int(getattr(yt_cfg, "daily_search_budget", 0)),
        daily_trending_budget=int(getattr(yt_cfg, "daily_trending_budget", 0)),
        daily_channel_budget=int(getattr(yt_cfg, "daily_channel_budget", 0)),
        candidate_pipeline=candidate_pipeline,
        keyword_fetch=keyword_fetch,
    )


@dataclass
class RuntimeContext:
    """API 端点使用的所有运行时组件的可变持有者。"""

    # ── 稳定（从不重建） ──────────────────────────────────────
    database: Any = None
    memory_manager: Any = None
    event_hub: Any = None
    presence: PresenceTracker = field(default_factory=PresenceTracker)
    # v0.3.63+：跟踪运行时派生的每个 detached ``asyncio.create_task``
    # （refresh manual / per-strategy precompute、recommendation engine
    # classify+delight、prewarm helpers、per-event triggers）。在
    # ``rebuild_from_config`` 时这些任务会在新运行时对象构造之前被取消，
    # 防止旧的 detached 工作与新建的运行时竞争 SQLite 写入 / LLM token。
    task_registry: BackgroundTaskRegistry = field(default_factory=BackgroundTaskRegistry)
    # 懒加载的 guided-init 协调器（gui-init spec §5）。不是构造参数；
    # 在首次访问时创建并绑定到 THIS ctx，因此即使热重载交换了
    # database / runtime_controller，它也始终读取当前的
    # （review R2 A-1）。三条构造路径都通过该 property 继承它。
    _init_coordinator: Any = field(default=None, init=False, repr=False, compare=False)
    _init_prereqs: Any = field(default=None, init=False, repr=False, compare=False)

    # ── 可交换（热重载时重建） ───────────────────────────
    config: Any = None
    degraded: bool = False
    degraded_reason: str = ""
    degraded_issues: list[Any] = field(default_factory=list)
    llm_registry: Any = None
    llm_service: Any = None
    bilibili_client: Any = None
    soul_engine: Any = None
    dialogue: Any = None
    discovery_engine: Any = None
    recommendation_engine: Any = None
    runtime_controller: Any = None
    account_sync_service: Any = None
    auto_update_service: Any = None

    @property
    def init_coordinator(self) -> Any:
        """绑定到此 ctx 的 guided-init 协调器（懒加载单例，spec §5）。"""
        if self._init_coordinator is None:
            from openbiliclaw.runtime.init_coordinator import InitCoordinator

            self._init_coordinator = InitCoordinator(self)
        return self._init_coordinator

    @property
    def init_prereqs(self) -> Any:
        """绑定到此 ctx 的、缓存的 guided-init 前置探针（spec §3）。"""
        if self._init_prereqs is None:
            from openbiliclaw.runtime.init_prereqs import InitPrereqs

            self._init_prereqs = InitPrereqs(self)
        return self._init_prereqs

    def background_llm_work_allowed(self) -> bool:
        """返回 daemon 持有的后台 LLM / embedding 工作是否可以运行。

        当 guided init 处于活跃状态时，所有 daemon 持有的后台循环
        （account_sync、continuous refresh、soul pipeline ticks）都会暂停，
        防止它们与 init 的显式 analyze/build/backfill 竞争或重复处理
        信号（gui-init D1）。Init 自身的工作绕过此 gate —— 它直接调用
        ``soul_engine`` / ``run_init_backfill``，二者都不查询
        ``llm_work_allowed``。
        """
        try:
            if self.database is not None and self.init_coordinator.init_active():
                return False
        except Exception:
            pass
        scheduler = getattr(getattr(self, "config", None), "scheduler", None)
        return _gate(scheduler, self.presence)

    async def rebuild_from_config(self, new_config: Config) -> None:
        """根据 *new_config* 重建所有可交换组件。

        v0.3.63+：此方法现在为 ``async``，以便调用方可以在构造新运行时
        对象之前 ``await`` 后台任务注册表的 ``cancel_all``。如果没有这一步，
        由旧 recommendation engine / refresh controller 派生的 detached
        任务（per-event triggers、per-strategy precompute、prewarm helpers）
        在重建后仍会继续运行，并在数秒内与新运行时竞争 SQLite 写入与
        LLM token。

        构造本身仍是同步的，并完全先写入局部变量 —— 仅当**每个**组件
        都成功后才赋值属性，因此保留了失败时的原子回滚。asyncio 事件循环
        是单线程的，因此在属性赋值扫掠期间不会有端点 handler 交错执行。
        """
        # 让运行中的 guided-init 任务在 rebuild 期间存活 —— 配置写入在
        # init 期间被 gate，但这是 belt-and-suspenders 豁免，确保进行中的
        # init 不会被静默取消（gui-init spec §5c）。
        cancelled = await self.task_registry.cancel_all(exclude=frozenset({"guided_init"}))
        if cancelled:
            logger.info(
                "Hot-reload: cancelled %d background task(s) before rebuild",
                cancelled,
            )
        self._rebuild_components(new_config)

    def _rebuild_components(self, new_config: Config) -> None:
        """热重载与启动共享的同步组件构造。

        ``rebuild_from_config``（async）在取消进行中的后台任务后调用此方法。
        ``build_runtime_context`` 在初始构造期间直接调用此方法 —— 此时
        注册表为空，因此无需取消步骤，且保持同步可简化本身同步的
        FastAPI 启动路径。
        """
        from openbiliclaw.bilibili.api import BilibiliAPIClient
        from openbiliclaw.bilibili.auth import resolve_runtime_cookie
        from openbiliclaw.discovery.engine import (
            ContentDiscoveryEngine,
            DiscoveryConcurrencyController,
        )
        from openbiliclaw.discovery.strategies.strategies import (
            ExploreStrategy,
            RelatedChainStrategy,
            SearchStrategy,
            TrendingStrategy,
        )
        from openbiliclaw.llm import build_llm_registry
        from openbiliclaw.llm.registry import build_embedding_service
        from openbiliclaw.llm.service import LLMService, module_overrides_from_config
        from openbiliclaw.llm.usage_recorder import UsageRecorder
        from openbiliclaw.recommendation.engine import RecommendationEngine
        from openbiliclaw.runtime.account_sync import AccountSyncService
        from openbiliclaw.runtime.refresh import ContinuousRefreshController
        from openbiliclaw.runtime.updater import AutoUpdateService
        from openbiliclaw.soul.dialogue import SocraticDialogue
        from openbiliclaw.soul.engine import SoulEngine

        # 1. LLM 层（带 usage ledger，使 ``openbiliclaw cost`` 有数据可用）
        new_registry = build_llm_registry(new_config)
        new_usage_recorder = UsageRecorder(sink=self.database)
        new_module_overrides = module_overrides_from_config(new_config)
        llm_concurrency = _llm_concurrency_from_config(new_config)
        new_llm_service = LLMService(
            registry=new_registry,
            memory=self.memory_manager,
            usage_recorder=new_usage_recorder,
            module_overrides=new_module_overrides,
            concurrency=llm_concurrency,
        )

        # 2. Bilibili client
        new_bilibili_client = BilibiliAPIClient(
            cookie=resolve_runtime_cookie(
                data_dir=new_config.data_path,
                configured_cookie=new_config.bilibili.cookie,
            )
        )

        # 3. Soul engine（复用稳定的 memory_manager）
        # usage_recorder 被转发，使 SoulEngine 内部构建的 LLMService
        # （被 preference / awareness / insight / profile_builder
        # / speculator 使用）以 caller 标签写入 cost ledger。在此
        # 接通之前，``soul.*`` 调用方完全缺失于
        # ``openbiliclaw cost --by caller``，且 speculator 失败
        # 以静默的"0 new"而非显式 WARN 出现。
        # 防御性 getattr 链：legacy 测试 fixture 和部分
        # config stub 可能不暴露新的 `soul.preference` 块。
        # 字段缺失时默认为 True：quick-exit 行不应自我喂入偏好，
        # 而显式 dislike 仍可作为负面证据使用。
        soul_cfg = getattr(new_config, "soul", None)
        preference_cfg = getattr(soul_cfg, "preference", None) if soul_cfg else None
        satisfaction_filter_enabled = bool(
            getattr(preference_cfg, "satisfaction_filter_enabled", True)
        )
        new_soul_engine = SoulEngine(
            llm=new_registry,
            memory=self.memory_manager,
            usage_recorder=new_usage_recorder,
            satisfaction_filter_enabled=satisfaction_filter_enabled,
            module_overrides=new_module_overrides,
            llm_concurrency=llm_concurrency,
            speculation_interval_minutes=int(
                getattr(new_config.scheduler, "speculation_interval_minutes", 10)
            ),
            speculation_ttl_days=int(getattr(new_config.scheduler, "speculation_ttl_days", 3)),
            speculation_cooldown_days=int(
                getattr(new_config.scheduler, "speculation_cooldown_days", 7)
            ),
            speculation_confirmation_threshold=int(
                getattr(new_config.scheduler, "speculation_confirmation_threshold", 3)
            ),
            speculation_max_active=int(getattr(new_config.scheduler, "speculation_max_active", 5)),
            speculation_max_primary_interests=int(
                getattr(new_config.scheduler, "speculation_max_primary_interests", 15)
            ),
            speculation_max_secondary_interests=int(
                getattr(new_config.scheduler, "speculation_max_secondary_interests", 60)
            ),
            avoidance_speculation_interval_minutes=int(
                getattr(new_config.scheduler, "avoidance_speculation_interval_minutes", 10)
            ),
            avoidance_speculation_ttl_days=int(
                getattr(new_config.scheduler, "avoidance_speculation_ttl_days", 3)
            ),
            avoidance_speculation_cooldown_days=int(
                getattr(new_config.scheduler, "avoidance_speculation_cooldown_days", 7)
            ),
            avoidance_speculation_confirmation_threshold=int(
                getattr(new_config.scheduler, "avoidance_speculation_confirmation_threshold", 3)
            ),
            avoidance_speculation_max_active=int(
                getattr(new_config.scheduler, "avoidance_speculation_max_active", 5)
            ),
            speculator_idle_interval_minutes=int(
                getattr(new_config.scheduler, "speculator_idle_interval_minutes", 30)
            ),
            profile_consolidation_enabled=bool(
                getattr(new_config.scheduler, "profile_consolidation_enabled", True)
            ),
            profile_consolidation_interval_hours=int(
                getattr(new_config.scheduler, "profile_consolidation_interval_hours", 12)
            ),
            profile_consolidation_like_target_upper=int(
                getattr(new_config.scheduler, "profile_consolidation_like_target_upper", 512)
            ),
            profile_consolidation_like_target_soft=int(
                getattr(new_config.scheduler, "profile_consolidation_like_target_soft", 450)
            ),
            profile_consolidation_archive_enabled=bool(
                getattr(new_config.scheduler, "profile_consolidation_archive_enabled", True)
            ),
            feedback_batch_threshold=int(
                getattr(new_config.scheduler, "feedback_batch_threshold", 3)
            ),
        )

        # 4. Embedding service
        new_embedding_service = build_embedding_service(new_config, new_registry)

        # 5. 与 soul pipeline 共享 embedding service，用于语义清理
        set_emb = getattr(new_soul_engine, "set_embedding_service", None)
        if callable(set_emb):
            set_emb(new_embedding_service)

        # 6. Recommendation engine
        from openbiliclaw.recommendation.curator import PoolCurator

        new_curator = PoolCurator(self.database)

        def _xhs_self_info_provider() -> dict[str, object] | None:
            state = self.memory_manager.load_discovery_runtime_state()
            info = state.get("xhs_self_info")
            return info if isinstance(info, dict) else None

        new_recommendation_engine = RecommendationEngine(
            llm=new_llm_service,
            database=self.database,
            curator=new_curator,
            embedding_service=new_embedding_service,
            task_registry=self.task_registry,
            xhs_self_info_provider=_xhs_self_info_provider,
        )

        # 7. Discovery engine + strategies
        concurrency = DiscoveryConcurrencyController(
            bilibili_request_concurrency=2,
            llm_evaluation_concurrency=2,
        )
        discovery_cfg = getattr(new_config, "discovery", None)
        new_discovery_engine = ContentDiscoveryEngine(
            llm_service=new_llm_service,
            database=self.database,
            concurrency=concurrency,
            embedding_service=new_embedding_service,
            multimodal_evaluation_enabled=bool(
                getattr(discovery_cfg, "multimodal_evaluation_enabled", False)
            ),
            multimodal_batch_size=int(getattr(discovery_cfg, "multimodal_batch_size", 8)),
            multimodal_image_max_px=int(getattr(discovery_cfg, "multimodal_image_max_px", 384)),
            multimodal_image_quality=int(getattr(discovery_cfg, "multimodal_image_quality", 72)),
            multimodal_image_timeout_seconds=(
                int(getattr(discovery_cfg, "multimodal_image_timeout_seconds", 6))
            ),
        )
        search_strategy = SearchStrategy(
            llm_service=new_llm_service,
            bilibili_client=new_bilibili_client,
            concurrency=concurrency,
            database=self.database,
            embedding_service=new_embedding_service,
        )
        trending_strategy = TrendingStrategy(
            bilibili_client=new_bilibili_client,
            llm_service=new_llm_service,
            concurrency=concurrency,
            database=self.database,
            embedding_service=new_embedding_service,
        )
        related_strategy = RelatedChainStrategy(
            bilibili_client=new_bilibili_client,
            llm_service=new_llm_service,
            memory_manager=cast("Any", self.memory_manager),
            search_strategy=search_strategy,
            trending_strategy=trending_strategy,
            concurrency=concurrency,
            database=self.database,
        )
        explore_strategy = ExploreStrategy(
            llm_service=new_llm_service,
            bilibili_client=new_bilibili_client,
            concurrency=concurrency,
            embedding_service=new_embedding_service,
            database=cast("Any", self.database),
        )
        new_discovery_engine.register_strategy(search_strategy)
        new_discovery_engine.register_strategy(trending_strategy)
        new_discovery_engine.register_strategy(related_strategy)
        new_discovery_engine.register_strategy(explore_strategy)

        # 7b. 注册 Bilibili 源适配器（multi-source Phase 1）
        from openbiliclaw.sources.bilibili_adapter import BilibiliAdapter

        bilibili_adapter = BilibiliAdapter(
            search=search_strategy,
            trending=trending_strategy,
            related_chain=related_strategy,
            explore=explore_strategy,
        )
        new_discovery_engine.register_adapter(bilibili_adapter)

        # 注册小红书 adapter —— 内容通过扩展的 API 端点
        # （POST /api/sources/xhs/observed-urls）进入池，而非通过
        # adapter.fetch()。adapter 是一个 stub，使注册表知道
        # "xiaohongshu" 是有效的源类型。
        from openbiliclaw.sources.xiaohongshu_adapter import XiaohongshuAdapter

        xiaohongshu_adapter = XiaohongshuAdapter()
        new_discovery_engine.register_adapter(xiaohongshu_adapter)

        # 注册 X (Twitter) adapter —— 服务端 cookie replay，类似
        # Bilibili / 抖音-direct（真实的 fetch()，不是 extension stub）。
        # 受 [sources.twitter].enabled 门控。该分支是 twitter_cli /
        # x_client 被导入的唯一位置，因此未安装 X 的环境（缺少可选的
        # ``openbiliclaw[x]`` extra）永远不会触碰它们。
        twitter_cfg = getattr(getattr(new_config, "sources", None), "twitter", None)
        if twitter_cfg is not None and bool(getattr(twitter_cfg, "enabled", False)):
            from openbiliclaw.discovery.strategies.x import (
                XCreatorStrategy,
                XForYouStrategy,
                XSearchStrategy,
            )
            from openbiliclaw.sources.twitter_adapter import XAdapter
            from openbiliclaw.sources.x_auth import resolve_x_cookie
            from openbiliclaw.sources.x_client import XClient

            x_cookie = resolve_x_cookie(
                data_dir=new_config.data_path,
                cookie_env=str(getattr(twitter_cfg, "cookie_env", "OPENBILICLAW_X_COOKIE")),
            )
            x_client = XClient(cookie=x_cookie)
            twitter_adapter = XAdapter(
                client=x_client,
                search=XSearchStrategy(client=x_client, llm_service=new_llm_service),
                feed=XForYouStrategy(client=x_client),
                creator=XCreatorStrategy(client=x_client),
            )
            new_discovery_engine.register_adapter(twitter_adapter)

        # 8. Continuous refresh controller
        from openbiliclaw.discovery.candidate_pipeline import DiscoveryCandidatePipeline

        discovery_cfg = getattr(new_config, "discovery", None)
        admission_min_score = float(getattr(discovery_cfg, "admission_min_score", 0.60) or 0.60)
        set_admission_min_score = getattr(self.database, "set_admission_min_score", None)
        if callable(set_admission_min_score):
            set_admission_min_score(admission_min_score)
        new_candidate_pipeline = DiscoveryCandidatePipeline(
            database=self.database,
            discovery_engine=new_discovery_engine,
            pool_target_count=new_config.scheduler.pool_target_count,
            admission_min_score=admission_min_score,
            min_eval_batch_size=8,
            max_eval_wait_seconds=120,
            candidate_fetch_oversample=4,
            xhs_self_nickname_provider=lambda: str(
                (_xhs_self_info_provider() or {}).get("nickname", "") or ""
            ).strip(),
        )
        # P1.7：统一关键词规划器 FETCH 协调器 —— claim-from-store +
        # word-lifecycle 助手，被 5 个搜索 fetch 站点共享（4 个 producer
        # + controller 中的 B站 search 路径）。持有 keyword-store DAO
        # （即 database）+ discovery config（flag + ``fetch_batch``）。
        # flag 关闭（默认）时每个站点的 ``should_claim`` 都返回 False，
        # 因此接入它是零行为变更。
        from openbiliclaw.config import DiscoveryConfig
        from openbiliclaw.runtime.keyword_fetch import KeywordFetchCoordinator

        new_keyword_fetch = KeywordFetchCoordinator(
            database=self.database,
            # 真实 ``Config`` 始终携带 ``discovery``（一个 dataclass 字段）；
            # 轻量测试 stub（SimpleNamespace）可能不携带 —— 回退到
            # 默认值（flag 关闭）以使 coordinator 保持 inert。
            discovery_config=discovery_cfg or DiscoveryConfig(),
        )

        new_bilibili_producer: Any = None
        new_xhs_producer: Any = None
        new_douyin_producer: Any = None
        new_youtube_producer: Any = None
        new_x_producer: Any = None
        new_zhihu_producer: Any = None
        if hasattr(self.database, "conn"):
            from openbiliclaw.runtime.bilibili_producer import BilibiliExtensionSearchProducer
            from openbiliclaw.runtime.xhs_producer import XhsTaskProducer
            from openbiliclaw.sources.bili_tasks import BiliTaskQueue
            from openbiliclaw.sources.xhs_tasks import XhsTaskQueue

            bili_cfg = getattr(new_config.sources, "bilibili", None)
            xhs_cfg = getattr(new_config.sources, "xiaohongshu", None)
            sched_cfg = getattr(new_config, "scheduler", None)
            bili_enabled = bool(getattr(bili_cfg, "enabled", True)) and bool(
                getattr(sched_cfg, "enabled", True)
            )
            xhs_enabled = bool(getattr(xhs_cfg, "enabled", False)) and bool(
                getattr(sched_cfg, "enabled", True)
            )

            async def _kick_bili_extension() -> None:
                publish = getattr(getattr(self, "event_hub", None), "publish", None)
                if callable(publish):
                    with suppress(Exception):
                        await publish({"type": "bili_task_available", "source": "task_kick"})

            new_bilibili_producer = BilibiliExtensionSearchProducer(
                task_queue=BiliTaskQueue(self.database),
                soul_engine=new_soul_engine,
                llm_service=new_llm_service,
                bilibili_client=new_bilibili_client,
                presence=self.presence,
                enabled=bili_enabled,
                daily_budget=int(getattr(bili_cfg, "daily_search_budget", 0)),
                min_interval_minutes=int(getattr(bili_cfg, "min_interval_minutes", 30)),
                keywords_per_cycle=int(getattr(bili_cfg, "keywords_per_cycle", 3)),
                page_size=int(getattr(bili_cfg, "page_size", 20)),
                presence_grace_seconds=int(
                    getattr(sched_cfg, "extension_disconnect_grace_seconds", 90)
                ),
                candidate_pipeline=new_candidate_pipeline,
                keyword_fetch=new_keyword_fetch,
                kick=_kick_bili_extension,
            )
            new_xhs_producer = XhsTaskProducer(
                task_queue=XhsTaskQueue(self.database),
                soul_engine=new_soul_engine,
                llm_service=new_llm_service,
                enabled=xhs_enabled,
                daily_budget=int(getattr(xhs_cfg, "daily_search_budget", 0)),
                keyword_fetch=new_keyword_fetch,
            )
            from openbiliclaw.runtime.douyin_producer import build_douyin_discovery_producer

            new_douyin_producer = build_douyin_discovery_producer(
                config=new_config,
                database=self.database,
                soul_engine=new_soul_engine,
                discovery_engine=new_discovery_engine,
                candidate_pipeline=new_candidate_pipeline,
                keyword_fetch=new_keyword_fetch,
            )
            new_youtube_producer = build_youtube_discovery_producer(
                config=new_config,
                database=self.database,
                soul_engine=new_soul_engine,
                discovery_engine=new_discovery_engine,
                candidate_pipeline=new_candidate_pipeline,
                llm_service=new_llm_service,
                memory=cast("Any", self.memory_manager),
                concurrency=concurrency,
                keyword_fetch=new_keyword_fetch,
            )
            # X (Twitter) producer —— 仅 fetch；入队到 discovery_candidates
            # 且从不 evaluate / 写 content_cache（unified-pool spec）。
            # 受 [sources.twitter].enabled 门控；禁用路径不导入 twitter_cli。
            from openbiliclaw.runtime.x_producer import build_x_discovery_producer

            new_x_producer = build_x_discovery_producer(
                config=new_config,
                database=self.database,
                soul_engine=new_soul_engine,
                llm_service=new_llm_service,
                keyword_fetch=new_keyword_fetch,
            )
            from openbiliclaw.runtime.zhihu_producer import build_zhihu_discovery_producer

            async def _kick_zhihu_extension() -> None:
                publish = getattr(getattr(self, "event_hub", None), "publish", None)
                if callable(publish):
                    with suppress(Exception):
                        await publish({"type": "zhihu_task_available", "source": "task_kick"})

            new_zhihu_producer = build_zhihu_discovery_producer(
                config=new_config,
                database=self.database,
                soul_engine=new_soul_engine,
                candidate_pipeline=new_candidate_pipeline,
                keyword_fetch=new_keyword_fetch,
                kick=_kick_zhihu_extension,
            )

        # P1.6：统一关键词规划器 —— deficit-pulled 合并关键词生成。
        # 作为独立对象构建（controller 没有 llm_service 字段），持有
        # llm_service + database + config，然后传给 controller，后者在
        # run_forever 中启动循环并注入自己的 deficit / catalyst 口径。
        # flag 关闭（默认）→ 循环 no-op → 零行为变更。
        from openbiliclaw.runtime.keyword_planner import KeywordPlanner

        new_keyword_planner = KeywordPlanner(
            llm_service=new_llm_service,
            database=self.database,
            config=new_config,
            soul_engine=new_soul_engine,
            pool_target_count=new_config.scheduler.pool_target_count,
            signal_event_threshold=int(getattr(new_config.scheduler, "signal_event_threshold", 6)),
            embedding_service=new_embedding_service,
        )

        new_runtime_controller = ContinuousRefreshController(
            memory_manager=self.memory_manager,
            database=self.database,
            soul_engine=new_soul_engine,
            discovery_engine=new_discovery_engine,
            recommendation_engine=new_recommendation_engine,
            discovery_candidate_pipeline=new_candidate_pipeline,
            keyword_planner=new_keyword_planner,
            keyword_fetch=new_keyword_fetch,
            pool_target_count=new_config.scheduler.pool_target_count,
            pool_source_shares=_pool_source_shares_from_config(new_config),
            signal_event_threshold=int(getattr(new_config.scheduler, "signal_event_threshold", 6)),
            trending_refresh_hours=int(getattr(new_config.scheduler, "trending_refresh_hours", 3)),
            explore_refresh_hours=int(getattr(new_config.scheduler, "explore_refresh_hours", 12)),
            check_interval_seconds=int(
                getattr(new_config.scheduler, "refresh_check_interval_seconds", 60)
            ),
            proactive_push_interval_seconds=int(
                getattr(new_config.scheduler, "proactive_push_interval_seconds", 120)
            ),
            discovery_limit=int(getattr(new_config.scheduler, "discovery_limit", 30)),
            event_hub=self.event_hub,
            bilibili_producer=new_bilibili_producer,
            xhs_producer=new_xhs_producer,
            douyin_producer=new_douyin_producer,
            youtube_producer=new_youtube_producer,
            x_producer=new_x_producer,
            zhihu_producer=new_zhihu_producer,
            scheduler_config=new_config.scheduler,
            presence=self.presence,
            # gui-init D1：当 guided init 活跃时暂停 controller 的后台循环
            # （account_sync 已基于同一谓词门控）。
            # init 自身的 run_init_backfill 绕过 _llm_work_allowed。
            init_active_check=lambda: self.init_coordinator.init_active(),
            task_registry=self.task_registry,
        )

        # 9. Account sync
        new_account_sync = AccountSyncService(
            memory_manager=self.memory_manager,
            bilibili_client=new_bilibili_client,
            soul_engine=new_soul_engine,
            sync_interval_hours=new_config.scheduler.account_sync_interval_hours,
            llm_work_allowed=self.background_llm_work_allowed,
        )

        # 10. Dialogue (with source management tools)
        from openbiliclaw.sources.tools import SOURCE_TOOLS, SourceToolDispatcher

        source_tool_dispatcher = SourceToolDispatcher(self.database)
        new_dialogue = SocraticDialogue(
            llm=None,
            soul_engine=new_soul_engine,
            llm_service=new_llm_service,
            session="popup",
            tools=SOURCE_TOOLS,
            tool_dispatcher=source_tool_dispatcher,
        )

        # 11. Auto-update service
        try:

            new_auto_update = AutoUpdateService(
                enabled=new_config.scheduler.auto_update_enabled,
                check_interval_hours=new_config.scheduler.auto_update_check_interval_hours,
                allow_prerelease=new_config.scheduler.auto_update_allow_prerelease,
                allowed_remotes=new_config.scheduler.auto_update_allowed_remotes,
                event_publisher=getattr(self.event_hub, "publish", None),
            )
        except Exception:
            new_auto_update = AutoUpdateService(
                enabled=False,
                event_publisher=getattr(self.event_hub, "publish", None),
            )

        # 保留上一次 update-check 结果 —— 配置保存（会重建此 service）不应
        # 让设置页从"发现新版本"回退到"尚未检查更新"，直到下一次定时检查。
        old_auto_update = getattr(self, "auto_update_service", None)
        if old_auto_update is not None:
            with suppress(Exception):
                new_auto_update.adopt_status_from(old_auto_update)

        # ── 原子交换 ─────────────────────────────────────────────
        # 所有构造均成功 → 赋值属性。
        self.config = new_config
        self.llm_registry = new_registry
        self.llm_service = new_llm_service
        self.bilibili_client = new_bilibili_client
        self.soul_engine = new_soul_engine
        self.dialogue = new_dialogue
        self.discovery_engine = new_discovery_engine
        self.recommendation_engine = new_recommendation_engine
        self.runtime_controller = new_runtime_controller
        self.account_sync_service = new_account_sync
        self.auto_update_service = new_auto_update
        # 丢弃缓存的 init 前置探针（chat/bilibili）—— 配置或 cookie 刚刚
        # 变更，因此下一次 /api/init 预检必须重新探针新的 provider/cookie，
        # 而不是使用陈旧的 TTL 值（gui-init review）。InitCoordinator 故意
        # 不重置：它持有当前 run handle 并懒读取 ctx 组件，因此它在 rebuild
        # 中存活（rebuild 也会把 guided_init 任务排除在 cancel 之外）。
        self._init_prereqs = None

        logger.info(
            "Hot-reload complete — rebuilt %d swappable components",
            11,
        )

    async def restart_background_tasks(
        self,
        app: FastAPI,
        *,
        run_post_reload_llm_work: bool = True,
    ) -> None:
        """取消旧的后台任务，从当前组件启动新任务。"""
        # 取消已存在的任务
        for attr in ("refresh_task", "account_sync_task", "auto_update_task"):
            task = getattr(app.state, attr, None)
            if task is not None:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

        # 从刚构建好的组件启动新任务。
        # v0.3.63+：通过 ``self.task_registry.track`` 路由，使下一次热重载的
        # ``cancel_all`` 也能干净地停止它们。
        if run_post_reload_llm_work:
            run_forever = getattr(self.runtime_controller, "run_forever", None)
            app.state.refresh_task = (
                self.task_registry.track("refresh_loop", run_forever())
                if callable(run_forever)
                else None
            )

            sync_forever = getattr(self.account_sync_service, "run_forever", None)
            app.state.account_sync_task = (
                self.task_registry.track("account_sync_loop", sync_forever())
                if callable(sync_forever)
                else None
            )
        else:
            app.state.refresh_task = None
            app.state.account_sync_task = None

        update_forever = getattr(self.auto_update_service, "run_forever", None)
        app.state.auto_update_task = (
            self.task_registry.track("auto_update_loop", update_forever())
            if callable(update_forever)
            else None
        )

        llm_work_allowed = run_post_reload_llm_work and self.background_llm_work_allowed()

        # 触发 speculator 以播种 speculative interests / avoidances
        if self.soul_engine is not None and llm_work_allowed:
            try:
                profile = await self.soul_engine.get_profile()
                runtime_state: dict[str, object] = {}
                load_runtime_state = getattr(
                    self.memory_manager,
                    "load_discovery_runtime_state",
                    None,
                )
                if callable(load_runtime_state):
                    loaded = load_runtime_state()
                    if isinstance(loaded, dict):
                        runtime_state = loaded

                speculator = getattr(self.soul_engine, "_speculator", None)
                if speculator is not None:
                    feedback_history: object = runtime_state.get("probe_feedback_history", [])
                    self.task_registry.track(
                        "post_reload_speculate",
                        self._safe_post_reload_speculate(
                            speculator,
                            profile,
                            feedback_history,
                            "probe_feedback_history",
                            self.memory_manager,
                        ),
                    )
                    logger.debug("post-reload speculator scheduled as background task")

                avoidance_speculator = getattr(self.soul_engine, "_avoidance_speculator", None)
                if avoidance_speculator is not None:
                    avoidance_feedback: object = runtime_state.get(
                        "avoidance_probe_feedback_history", []
                    )
                    self.task_registry.track(
                        "post_reload_avoidance_speculate",
                        self._safe_post_reload_speculate(
                            avoidance_speculator,
                            profile,
                            avoidance_feedback,
                            "avoidance_probe_feedback_history",
                            self.memory_manager,
                        ),
                    )
                    logger.debug("post-reload avoidance speculator scheduled as background task")

                # v0.3.124+（lever 2a）：rebuild_from_config 中的 cancel_all
                # 也会杀掉任何 in-flight 的 classify_pool_backlog /
                # precompute_pool_copy / delight scoring。如果不 re-kick，
                # 用户在冷启动中途保存配置会把 pool-fill 卡住，直到下一次
                # 60s refresh tick —— 或者如果用户持续保存则无限卡住。
                # 在刚构建好的 engine 上 re-kick classify→copy→delight drain，
                # 使 pool-fill 立即恢复。
                # precompute_pool_copy 内部 detached 派生 classify + delight，
                # 因此一次调用即可重启整个三件套。
                precompute = getattr(self.recommendation_engine, "precompute_pool_copy", None)
                if callable(precompute):
                    self.task_registry.track(
                        "post_reload_precompute_pool_copy",
                        self._safe_post_reload_precompute(precompute, profile),
                    )
                    logger.debug("post-reload classify/copy drain scheduled as background task")
            except Exception:
                pass  # profile 尚未初始化 —— 静默跳过

        # v0.3.45+：为现有 pool 预热 recommendation MMR embedding L2 缓存。
        # per-item warm hook 只能捕获在此代码上线*之后*新增的 item；
        # 如果不做启动扫描，部署第 1 天首次弹窗"换一批"会冷抓 ~10-60s。
        # detached 执行，不阻塞 API 就绪。
        prewarm_pool = getattr(self.recommendation_engine, "prewarm_pool_mmr_embeddings", None)
        if callable(prewarm_pool) and llm_work_allowed:
            self.task_registry.track(
                "prewarm_pool_mmr_embeddings",
                self._safe_prewarm_pool_mmr_embeddings(prewarm_pool),
            )

        if run_post_reload_llm_work:
            logger.info("Background tasks restarted after hot-reload")
        else:
            logger.info("Background LLM tasks suspended after setup config hot-reload")

    @staticmethod
    async def _safe_post_reload_speculate(
        speculator: Any,
        profile: Any,
        feedback_history: object,
        feedback_history_key: str,
        memory_manager: Any,
    ) -> None:
        """执行 post-reload speculation，不阻塞配置 PUT。"""
        load_runtime_state = getattr(memory_manager, "load_discovery_runtime_state", None)

        def _load_feedback_history() -> object:
            if not callable(load_runtime_state):
                return []
            runtime_state = load_runtime_state()
            if not isinstance(runtime_state, dict):
                return []
            return runtime_state.get(feedback_history_key, [])

        try:
            try:
                await speculator.force_tick(
                    profile,
                    feedback_history=feedback_history,
                    feedback_history_loader=_load_feedback_history,
                )
            except TypeError:
                try:
                    await speculator.force_tick(
                        profile,
                        feedback_history=feedback_history,
                    )
                except TypeError:
                    await speculator.force_tick(profile)
        except Exception:
            pass

    @staticmethod
    async def _safe_post_reload_precompute(precompute_callable: Any, profile: Any) -> None:
        """在热重载后重新触发 classify→copy→delight drain。

        ``rebuild_from_config`` 的 ``cancel_all`` 会停止任何 in-flight 的
        classify_pool_backlog / precompute_pool_copy / delight scoring（它们
        持有现已换出的 engine 的引用）。一次 ``precompute_pool_copy`` 调用
        即可在新 engine 上重启整个三件套 —— 它自己的 ``_expression_lock``
        防止其与 refresh loop 的周期性 drain 竞争，后者仍是兜底。失败
        会被记录日志，对配置 PUT 不是致命的。
        """
        try:
            await precompute_callable(profile=profile)
        except Exception:
            logger.exception("post-reload precompute_pool_copy failed")

    @staticmethod
    async def _safe_prewarm_pool_mmr_embeddings(prewarm_callable: Any) -> None:
        """执行启动 MMR 预热，并在覆盖率低时重试。

        v0.3.54+：生产日志（2026-05-05）显示 daemon 启动后
        ``MMR embedding fetch: coverage=0/40`` 持续了 31 分钟 ——
        Ollama 在预热窗口期间 502，单次启动任务直接放弃。改用
        指数退避循环，使慢速 Ollama warmup 不会把缓存锁死半小时。
        5 次尝试（≈31s）后停止，或当预热返回 >0（即一些 embedding
        已落地）时停止。失败被静默吞掉，因此如果 5 次尝试真的全
        失败，pool MMR 缓存会通过正常流量懒填充。

        v0.3.124+（lever 4）：重试循环只在"有东西可预热但失败了"
        （后端 warming up / down）时才有意义。``prewarm`` 现在当
        没东西可预热（空 pool / 无 embedding service）时返回 ``-1``
        —— 良性冷启动，非失败 —— 因此我们仅平淡记录并停止，而不是
        在每次全新部署上烧 5 行刺眼的"warmed=0 — retry"日志（这些
        日志与真实 Ollama 故障读起来一模一样）。``0`` 且有候选项存在
        才是真正的"后端不可达"场景，保留 retry-then-warn 行为。
        """
        delay = 2.0
        for attempt in range(1, 6):
            try:
                warmed = await prewarm_callable()
                if isinstance(warmed, int):
                    if warmed > 0:
                        return
                    if warmed < 0:
                        # 暂无东西可预热 —— 良性冷启动；重试无意义
                        # （缓存会随 pool 填充懒加载）。
                        logger.info(
                            "Startup prewarm_pool_mmr_embeddings: nothing to warm yet "
                            "(empty pool or embedding service off) — skipping retries; "
                            "cache will lazy-fill from serve()/discovery traffic"
                        )
                        return
                logger.info(
                    "Startup prewarm_pool_mmr_embeddings attempt %d embedded 0 items "
                    "(candidates present — embedding backend may be warming up/down) "
                    "— retry in %.1fs",
                    attempt,
                    delay,
                )
            except Exception:
                logger.warning(
                    "Startup prewarm_pool_mmr_embeddings attempt %d failed; retry in %.1fs",
                    attempt,
                    delay,
                    exc_info=True,
                )
            if attempt >= 5:
                break
            await asyncio.sleep(delay)
            delay *= 2
        logger.warning(
            "Startup prewarm_pool_mmr_embeddings gave up after retries — the embedding "
            "backend stayed unreachable (candidates were present but none embedded; "
            "e.g. Ollama down). MMR diversity degrades; cache will lazy-fill if it recovers"
        )


def build_runtime_context(
    config: Config,
    *,
    memory_manager: Any | None = None,
    database: Any | None = None,
    event_hub: Any | None = None,
) -> RuntimeContext:
    """根据 ``Config`` 构造一个完整接线的 ``RuntimeContext``。

    稳定组件（``database``、``memory_manager``、``event_hub``）在未提供时
    在此创建。所有可交换组件通过委托给 ``RuntimeContext.rebuild_from_config``
    构建。
    """
    from openbiliclaw.memory.manager import MemoryManager
    from openbiliclaw.runtime.events import RuntimeEventHub
    from openbiliclaw.storage.database import Database

    # ── 稳定组件 ───────────────────────────────────────────
    created_runtime_database = False
    if database is None:
        database = Database(config.data_path / "openbiliclaw.db")
        database.initialize()
        created_runtime_database = True
    if memory_manager is None:
        # 只有当数据库 handle 是我们自己创建时，才与 memory_manager 共享
        # —— 与原始 create_app() 契约一致：注入自己的 database 的调用方
        # 不期望它被共享。
        shared_database = database if created_runtime_database else None
        memory_manager = MemoryManager(config.data_path, database=shared_database)
        memory_manager.initialize()
    if event_hub is None:
        event_hub = RuntimeEventHub()

    # 接通 soul-layer 变更回调，使任何更新 profile 的代码路径
    # （init、cognition cycle、dialogue ingestion、manual rebuild ……）
    # 自动通过 WebSocket 广播 ``profile_updated`` 事件。弹窗监听并
    # 重新拉取，无需手动 ``init_completed`` 戳一下。
    setter = getattr(memory_manager, "set_profile_change_callback", None)
    if callable(setter):

        async def _on_profile_changed() -> None:
            publish = getattr(event_hub, "publish", None)
            if callable(publish):
                with suppress(Exception):
                    await publish(
                        {
                            "type": "profile_updated",
                            "phase": "ready",
                            "message": "画像已更新",
                        }
                    )

        setter(_on_profile_changed)

    ctx = RuntimeContext(
        database=database,
        memory_manager=memory_manager,
        event_hub=event_hub,
    )

    # 通过与热重载相同的路径构建所有可交换组件。
    # ``_rebuild_components`` 是与 ``rebuild_from_config`` 共享的同步部分；
    # async wrapper 的 ``cancel_all`` 在这里是 no-op，因为注册表刚创建
    # 且为空。
    ctx._rebuild_components(config)
    return ctx


def build_degraded_runtime_context(
    config: Config,
    *,
    memory_manager: Any | None = None,
    database: Any | None = None,
    event_hub: Any | None = None,
    exc: Exception | None = None,
) -> RuntimeContext:
    """构造一个能服务 config recovery 端点的最小 context。

    ``build_runtime_context`` 故意保持严格。此降级构造器仅由 FastAPI 启动
    在 registry 构造失败后使用，使弹窗仍能读取并修复 config.toml。
    """
    from openbiliclaw.config import ConfigIssue
    from openbiliclaw.memory.manager import MemoryManager
    from openbiliclaw.runtime.events import RuntimeEventHub
    from openbiliclaw.runtime.updater import AutoUpdateService
    from openbiliclaw.storage.database import Database

    created_runtime_database = False
    if database is None:
        database = Database(config.data_path / "openbiliclaw.db")
        database.initialize()
        created_runtime_database = True
    if memory_manager is None:
        shared_database = database if created_runtime_database else None
        memory_manager = MemoryManager(config.data_path, database=shared_database)
        memory_manager.initialize()
    if event_hub is None:
        event_hub = RuntimeEventHub()

    setter = getattr(memory_manager, "set_profile_change_callback", None)
    if callable(setter):

        async def _on_profile_changed() -> None:
            publish = getattr(event_hub, "publish", None)
            if callable(publish):
                with suppress(Exception):
                    await publish(
                        {
                            "type": "profile_updated",
                            "phase": "ready",
                            "message": "画像已更新",
                        }
                    )

        setter(_on_profile_changed)

    # 在降级模式下保留 update check / apply —— 一个无法构建 LLM registry
    # 的后端正是用户可能想拉取携带修复的 release 的时候。构造廉价且不
    # 联网；绝不让它破坏降级 recovery context。
    degraded_auto_update: AutoUpdateService | None = None
    with suppress(Exception):
        degraded_auto_update = AutoUpdateService(
            enabled=config.scheduler.auto_update_enabled,
            check_interval_hours=config.scheduler.auto_update_check_interval_hours,
            allow_prerelease=config.scheduler.auto_update_allow_prerelease,
            allowed_remotes=config.scheduler.auto_update_allowed_remotes,
            event_publisher=getattr(event_hub, "publish", None),
        )

    message = str(exc) if exc is not None else "LLM registry unavailable"
    return RuntimeContext(
        database=database,
        memory_manager=memory_manager,
        event_hub=event_hub,
        config=config,
        auto_update_service=degraded_auto_update,
        degraded=True,
        degraded_reason="llm_registry_unavailable",
        degraded_issues=[
            ConfigIssue(
                field="llm",
                message=f"LLM registry unavailable: {message}",
                severity="blocking",
            )
        ],
    )
