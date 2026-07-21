"""通用 Web 内容源适配器 —— 从任意网页获取并提取内容。

使用浏览器后端（Playwright CDP 或 agent-browser）加载页面，
并用 LLM 提取结构化内容。适用于任何没有专用 API 适配器的平台。
"""

from __future__ import annotations

import logging
from contextlib import suppress
from typing import TYPE_CHECKING, Any

from openbiliclaw.sources.browser import BrowserManager
from openbiliclaw.sources.llm_extractor import extract_content_from_page

if TYPE_CHECKING:
    from openbiliclaw.discovery.engine import DiscoveredContent
    from openbiliclaw.soul.profile import SoulProfile
    from openbiliclaw.sources.protocol import SourceRecipe

logger = logging.getLogger(__name__)


class WebSourceAdapter:
    """使用浏览器 + LLM 提取的通用 Web 内容适配器。

    Recipe 配置键：
        url_template: URL 模式，可包含 ``{query}`` 占位符。
        query: 搜索查询（替换到 url_template 中）。
        url: 直接获取的 URL（未设置 url_template 时使用）。
    """

    def __init__(
        self,
        *,
        llm_service: Any,
        browser_executable: str = "",
        browser_headed: bool = False,
        browser_cdp_url: str = "",
    ) -> None:
        self._llm_service = llm_service
        self._browser_executable = browser_executable
        self._browser_headed = browser_headed
        self._browser_cdp_url = browser_cdp_url

    @property
    def source_type(self) -> str:
        return "web"

    async def fetch(
        self,
        recipe: SourceRecipe,
        profile: SoulProfile,
        limit: int = 20,
    ) -> list[DiscoveredContent]:
        """从 recipe 定义的网页获取内容。"""
        url = self._build_url(recipe)
        if not url:
            logger.warning("WebSourceAdapter: no URL for recipe %s", recipe.id)
            return []

        browser = BrowserManager(
            executable=self._browser_executable,
            headed=self._browser_headed,
            cdp_url=self._browser_cdp_url,
        )

        if not browser.is_available:
            logger.warning(
                "WebSourceAdapter: agent-browser not available, skipping recipe %s",
                recipe.id,
            )
            return []

        try:
            snapshot = await browser.get_page_snapshot(url)
        except Exception:
            logger.exception("WebSourceAdapter: failed to fetch %s", url)
            return []
        finally:
            with suppress(Exception):
                await browser.close()

        items = await extract_content_from_page(
            snapshot.text,
            source_platform=recipe.source_type,
            llm_service=self._llm_service,
            base_url=url,
        )

        # 应用 recipe 的 source_type，并从捕获的锚点回填 URL/ID。
        for item in items:
            if not item.source_platform:
                item.source_platform = recipe.source_type
            if not item.content_url:
                matched = _match_anchor_by_title(snapshot.anchors, item.title)
                if matched:
                    item.content_url = matched
            if item.content_url and (not item.content_id or item.content_id == item.title[:32]):
                derived = _extract_content_id(item.content_url)
                if derived:
                    item.content_id = derived

        return items[:limit]

    @staticmethod
    def _build_url(recipe: SourceRecipe) -> str:
        """根据 recipe 配置构建目标 URL。"""
        config = recipe.config or {}
        url_template = str(config.get("url_template", "") or "")
        query = str(config.get("query", "") or "")
        url = str(config.get("url", "") or "")

        if url_template and query:
            return url_template.replace("{query}", query)
        if url:
            return url
        if url_template:
            return url_template
        return ""


def _match_anchor_by_title(
    anchors: list[tuple[str, str]],
    title: str,
) -> str:
    """返回文本与 ``title`` 最佳匹配的锚点的 href。

    匹配刻意简单：大小写不敏感的子串匹配（任一方向包含即可）。
    对于小红书 / v2ex / 知乎的卡片来说这已经足够 —— 锚点的可见
    文本就是卡片标题。
    """
    if not title or not anchors:
        return ""
    needle = title.strip().lower()
    if not needle:
        return ""
    # 优先精确子串命中，然后是部分重叠，这样标题是某个更长锚点
    # 前缀的卡片仍能胜出。
    best_exact = ""
    best_partial = ""
    for text, href in anchors:
        candidate = text.strip().lower()
        if not candidate:
            continue
        if (candidate == needle or needle in candidate) and not best_exact:
            best_exact = href
        elif candidate in needle and not best_partial:
            best_partial = href
    return best_exact or best_partial


def _extract_content_id(url: str) -> str:
    """从 ``url`` 中提取最后一个非空路径段。

    适用于小红书（``/explore/{note_id}``、``/discovery/item/{id}``）、
    v2ex（``/t/{topic_id}``）、知乎（``/question/{id}``）等。未找到
    可用段时返回 "" —— 调用方应保留原始 ID。
    """
    if not url:
        return ""
    try:
        from urllib.parse import urlparse

        path = urlparse(url).path.strip("/")
    except Exception:
        return ""
    if not path:
        return ""
    last = path.rsplit("/", 1)[-1]
    return last
