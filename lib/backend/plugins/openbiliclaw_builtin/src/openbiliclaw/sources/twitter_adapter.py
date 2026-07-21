"""X (Twitter) 内容源适配器 —— 服务端 Cookie 回放式发现。

与小红书桩适配器（其内容通过扩展 API 端点进入）不同，X 内容源像
Bilibili / Douyin-direct 一样运行**真实的** ``fetch()``：三个注入的策略
驱动一个 :class:`XClient`（通过 ``twitter-cli`` 进行 Cookie 回放）并返回
规范化的 :class:`DiscoveredContent`。

``fetch()`` 按 ``recipe.strategy`` 分发：

* ``"search"``  → ``XSearchStrategy``  （来自 Soul 画像 / recipe ``query`` 的关键词）
* ``"feed"``    → ``XForYouStrategy``  （"For You" 主页时间线）
* ``"creator"`` → ``XCreatorStrategy`` （来自 ``recipe.config["handle"]`` 的订阅 handle）

适配器从不导入 ``twitter_cli`` —— 注入的 ``XClient`` 在网络边界拥有
惰性导入，策略仅通过结构化协议引用它。因此在 ``enabled=false`` 路径上
构造/注册此适配器是安全的。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from openbiliclaw.discovery.engine import DiscoveredContent
    from openbiliclaw.soul.profile import SoulProfile
    from openbiliclaw.sources.protocol import SourceRecipe

logger = logging.getLogger(__name__)

_SOURCE_TYPE = "twitter"


def _coerce_keyword_list(value: Any) -> list[str] | None:
    """将 recipe 配置中的 ``keywords`` 值强制转换为干净的字符串列表。

    当 recipe 不携带 ``keywords`` 时返回 ``None``（这样适配器保持逐字节
    兼容遗留的单 ``query`` 调用路径）。存在但为空/全空白的列表返回
    ``[]``（显式表示"无关键词"注入）。
    """
    if value is None:
        return None
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, (list, tuple)):
        items = list(value)
    else:
        return None
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        text = str(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _coerce_keyword_id_map(value: Any) -> dict[str, int]:
    """将 recipe 配置中的 ``keyword_ids`` 值强制转换为 ``{str: int}`` 映射。

    容忍缺失/格式错误的输入（返回 ``{}``），因此没有 P1.8 溯源的 recipe
    会干净地成为无操作。只有格式良好的 ``keyword → int`` 键值对会被保留。
    """
    if not isinstance(value, dict):
        return {}
    out: dict[str, int] = {}
    for raw_key, raw_id in value.items():
        key = str(raw_key).strip()
        if not key:
            continue
        try:
            out[key] = int(raw_id)
        except (TypeError, ValueError):
            continue
    return out


class _SupportsDiscover(Protocol):
    """三个注入策略可调用对象的结构化类型。

    每个策略接受画像、一个 ``limit`` 和策略特定的关键字参数
    （search 用 ``query``，creator 用 ``handle``）。
    """

    async def discover(
        self, profile: Any, *, limit: int = 20, **kwargs: Any
    ) -> list[DiscoveredContent]: ...


class XAdapter:
    """通过三个服务端策略获取 X 内容的适配器。

    ``client`` 被保留是为了与其他真实适配器保持生命周期一致
    （并让运行时拥有单个 :class:`XClient`）；实际的网络调用通过
    注入的策略进行，策略自身持有对同一 client 的引用。
    """

    def __init__(
        self,
        *,
        client: Any,
        search: _SupportsDiscover,
        feed: _SupportsDiscover,
        creator: _SupportsDiscover,
    ) -> None:
        self._client = client
        self._search = search
        self._feed = feed
        self._creator = creator

    # ── SourceAdapter 协议 ──────────────────────────────────────────

    @property
    def source_type(self) -> str:
        return _SOURCE_TYPE

    async def fetch(
        self,
        recipe: SourceRecipe,
        profile: SoulProfile,
        limit: int = 20,
    ) -> list[DiscoveredContent]:
        """按 ``recipe.strategy`` 分发到对应策略。"""
        config = recipe.config if isinstance(recipe.config, dict) else {}
        strategy = recipe.strategy

        if strategy == "search":
            query = str(config.get("query", "") or "")
            # ``queries`` 是统一规划器注入的键 —— 它映射到真实的
            # ``XSearchStrategy.discover(queries=)`` 参数。``keywords``
            # 仍是遗留的配置键（作为 ``keywords=`` 转发），真实策略会
            # 忽略它；两者都保留以向后兼容。
            queries = _coerce_keyword_list(config.get("queries"))
            keywords = _coerce_keyword_list(config.get("keywords"))
            # P1.8 产出溯源：可选的 ``keyword → id`` 映射随 ``queries`` 一起
            # 转发。仅在存在时传递，以使非规划器 recipe 的调用形式保持
            # 逐字节一致。
            keyword_ids = _coerce_keyword_id_map(config.get("keyword_ids"))
            extra_ids: dict[str, Any] = {"keyword_ids": keyword_ids} if keyword_ids else {}
            if queries is not None:
                items = await self._search.discover(
                    profile, limit=limit, query=query, queries=queries, **extra_ids
                )
            elif keywords is not None:
                items = await self._search.discover(
                    profile, limit=limit, query=query, keywords=keywords, **extra_ids
                )
            else:
                items = await self._search.discover(profile, limit=limit, query=query)
        elif strategy == "feed":
            items = await self._feed.discover(profile, limit=limit)
        elif strategy == "creator":
            handle = str(config.get("handle", "") or "")
            items = await self._creator.discover(profile, limit=limit, handle=handle)
        else:
            logger.warning(
                "XAdapter: unknown strategy %r (expected search/feed/creator)",
                strategy,
            )
            return []

        # 防御性处理：每个 X item 必须携带 source_platform="twitter"，
        # 这样即使某个策略遗漏了，混合源池也能正确归因。
        for item in items:
            if not item.source_platform:
                item.source_platform = _SOURCE_TYPE
        return items
