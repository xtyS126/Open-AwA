"""可复用的抖音发现编排逻辑。

本模块让抖音 direct-cookie 发现在 CLI、运行时生产者、测试以及
未来的 API 端点中都能使用，而无需在每个调用方重复构造策略。
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from openbiliclaw.discovery.engine import DiscoveredContent
from openbiliclaw.discovery.strategies.douyin_direct import (
    DouyinDirectStrategy,
    SupportsDouyinDirectClient,
)

if TYPE_CHECKING:
    from openbiliclaw.soul.profile import SoulProfile


@dataclass(frozen=True)
class DouyinDiscoveryOptions:
    """一次抖音 direct 发现运行的选项。"""

    limit: int = 30
    sources: tuple[str, ...] = ("search", "hot", "feed")
    keywords: tuple[str, ...] = ()
    # P1.8 yield provenance: ``keyword text → discovery_keywords.id`` 映射，
    # 用于 ``keywords`` 中已认领的搜索词。旧版本 / 非 planner 运行时为空；
    # 由已映射 keyword 产生的搜索候选会带上其 id 用于回填。
    keyword_ids: dict[str, int] = field(default_factory=dict)
    creator_sec_uids: tuple[str, ...] = ()
    cache: bool = True
    evaluate: bool = True
    per_source_limit: int = 20
    keywords_per_run: int = 5
    # 统一 keyword planner 拉取路径 (P1.7): 让 plugin-search client
    # 在预算耗尽时抛出 ``DouyinBudgetExhausted``，这样已认领的 keyword
    # 会回滚而不是被烧掉。关闭 → 旧行为不变。
    raise_on_budget: bool = False


@dataclass(frozen=True)
class DouyinDiscoveryResult:
    """一次抖音发现运行的结果摘要。"""

    items: list[DiscoveredContent]
    cached: bool
    source_counts: dict[str, int]


class DouyinDiscoveryService:
    """通过可复用的服务边界运行抖音 direct 发现。"""

    def __init__(
        self,
        *,
        client: SupportsDouyinDirectClient,
        discovery_engine: Any | None = None,
        llm_service: Any | None = None,
        concurrency: Any | None = None,
        database: Any | None = None,
    ) -> None:
        self._client = client
        self._discovery_engine = discovery_engine
        self._llm_service = llm_service
        self._concurrency = concurrency
        self._database = database

    async def discover(
        self,
        profile: SoulProfile,
        options: DouyinDiscoveryOptions | None = None,
    ) -> DouyinDiscoveryResult:
        """运行一次抖音发现周期。"""
        opts = options or DouyinDiscoveryOptions()
        limit = max(1, opts.limit)
        strategy = self._build_strategy(opts)

        if opts.cache and self._discovery_engine is not None:
            self._discovery_engine.register_strategy(strategy)
            raw_items = await self._discovery_engine.discover(
                profile,
                strategies=[strategy.name],
                limit=limit,
            )
            items = _douyin_items(raw_items)
            return DouyinDiscoveryResult(
                items=items,
                cached=True,
                source_counts=_source_counts(items),
            )

        items = await strategy.discover(profile, limit=limit)
        return DouyinDiscoveryResult(
            items=items,
            cached=False,
            source_counts=_source_counts(items),
        )

    def _build_strategy(self, opts: DouyinDiscoveryOptions) -> DouyinDirectStrategy:
        llm_service = self._llm_service
        concurrency = self._concurrency
        database = self._database
        if self._discovery_engine is not None:
            llm_service = llm_service or getattr(self._discovery_engine, "_llm_service", None)
            concurrency = concurrency or getattr(self._discovery_engine, "_concurrency", None)
            database = database or getattr(self._discovery_engine, "_database", None)

        return DouyinDirectStrategy(
            client=self._client,
            llm_service=llm_service,
            concurrency=concurrency,
            database=database,
            sources=opts.sources,
            seed_keywords=opts.keywords,
            seed_keyword_ids=dict(opts.keyword_ids),
            creator_sec_uids=opts.creator_sec_uids,
            keywords_per_run=max(1, opts.keywords_per_run),
            per_source_limit=max(1, opts.per_source_limit),
            llm_evaluation=opts.evaluate,
        )


def split_csv_values(values: list[str] | tuple[str, ...] | None) -> tuple[str, ...]:
    """拆分可能包含逗号分隔条目的重复 CLI/env 值。"""
    if not values:
        return ()
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        for part in str(value).split(","):
            token = part.strip()
            if not token or token in seen:
                continue
            seen.add(token)
            result.append(token)
    return tuple(result)


def _source_counts(items: list[DiscoveredContent]) -> dict[str, int]:
    counts = Counter(str(item.source_strategy or "douyin_direct") for item in items)
    return dict(counts)


def _douyin_items(raw_items: list[Any]) -> list[DiscoveredContent]:
    return [
        item
        for item in raw_items
        if isinstance(item, DiscoveredContent) and item.source_platform == "douyin"
    ]
