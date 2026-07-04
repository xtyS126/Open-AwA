"""Bilibili 源适配器 —— 封装既有的四种发现策略。"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from openbiliclaw.discovery.engine import DiscoveredContent, DiscoveryStrategy
    from openbiliclaw.soul.profile import SoulProfile
    from openbiliclaw.sources.protocol import SourceRecipe

logger = logging.getLogger(__name__)


class BilibiliAdapter:
    """委托给既有 Bilibili 发现策略的适配器。

    这是一个薄封装，使基于策略的遗留流水线可以通过统一的
    :class:`SourceAdapter` 接口访问，无需重写任何策略逻辑。
    """

    def __init__(
        self,
        *,
        search: DiscoveryStrategy | None = None,
        trending: DiscoveryStrategy | None = None,
        related_chain: DiscoveryStrategy | None = None,
        explore: DiscoveryStrategy | None = None,
    ) -> None:
        self._strategies: dict[str, DiscoveryStrategy] = {}
        if search is not None:
            self._strategies["search"] = search
        if trending is not None:
            self._strategies["trending"] = trending
        if related_chain is not None:
            self._strategies["related_chain"] = related_chain
        if explore is not None:
            self._strategies["explore"] = explore

    # ── SourceAdapter 协议 ──────────────────────────────────────

    @property
    def source_type(self) -> str:
        return "bilibili"

    async def fetch(
        self,
        recipe: SourceRecipe,
        profile: SoulProfile,
        limit: int = 20,
    ) -> list[DiscoveredContent]:
        """委托给由 ``recipe.strategy`` 指定的策略。"""
        strategy = self._strategies.get(recipe.strategy)
        if strategy is None:
            logger.warning(
                "BilibiliAdapter: unknown strategy %r (available: %s)",
                recipe.strategy,
                list(self._strategies),
            )
            return []

        items = await strategy.discover(profile, limit=limit)

        # 确保每条数据的多源字段均已填充
        for item in items:
            if not item.source_platform:
                item.source_platform = "bilibili"
            if not item.content_id and item.bvid:
                item.content_id = item.bvid
            if not item.content_url and item.bvid:
                item.content_url = f"https://www.bilibili.com/video/{item.bvid}"
            if not item.author_name and item.up_name:
                item.author_name = item.up_name

        return items

    # ── 便捷辅助方法 ─────────────────────────────────────────

    @property
    def available_strategies(self) -> list[str]:
        """本适配器可处理的策略名称。"""
        return list(self._strategies)
