"""多源内容抓取的通用浏览器自动化层。

两个可互换的后端：

设置了 ``cdp_url``（推荐）
    通过 Playwright ``connect_over_cdp`` 连接到预先启动的 Chrome。
    用户使用 ``--remote-debugging-port=9222`` 启动一次 Chrome，
    登录目标平台并保持运行。每次适配器调用都复用该登录态 ——
    这是小红书等源在不被限流的前提下正常工作的唯一方式。

``cdp_url`` 为空（兜底）
    封装既有的 agent-browser CLI。无登录态 ——
    适用于简单的匿名页面，但大部分真实源会受阻。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from importlib import import_module
from typing import Any

logger = logging.getLogger(__name__)

# 在页面内执行的 JS。同时返回可见 body 文本和所有可点击锚点
# （格式为 {text, href}）。LLM 抽取器仅处理内部文本，
# 但调用方使用锚点列表回填 ``content_url`` 字段 ——
# innerText 单独使用会丢失所有 href，否则被抽取的条目
# 无法回链到源。
_PAGE_SNAPSHOT_SCRIPT = """\
() => {
  const text = (document.body && document.body.innerText) || '';
  const seen = new Set();
  const anchors = [];
  for (const a of document.querySelectorAll('a[href]')) {
    const href = a.href || '';
    if (!href || href.startsWith('javascript:') || seen.has(href)) continue;
    const t = ((a.innerText || a.textContent || '') + '').trim();
    if (!t) continue;
    seen.add(href);
    anchors.push({text: t.slice(0, 200), href: href});
  }
  return {text: text, anchors: anchors};
}
"""


@dataclass
class PageSnapshot:
    """单次往返中抓取的页面内容与锚点元数据。

    ``text`` 镜像 ``document.body.innerText``（LLM 抽取器处理对象）。
    ``anchors`` 保留 innerText 丢弃的 ``(visible_text, href)`` 对 ——
    调用方使用它们为抽取器输出的条目重建 URL。
    """

    text: str
    anchors: list[tuple[str, str]] = field(default_factory=list)


def _async_playwright() -> Any:
    """懒加载 ``playwright.async_api.async_playwright``。

    作为模块级函数保留，便于测试在不触碰可选 playwright 依赖的情况下
    对其进行 monkey-patch。
    """
    try:
        async_playwright = import_module("playwright.async_api").async_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Playwright not installed. Install with: "
            "pip install 'openbiliclaw[browser]' "
            "and then: playwright install chromium"
        ) from exc
    return async_playwright()


class BrowserManager:
    """管理非 Bilibili 内容源的浏览器会话。

    Args:
        executable: agent-browser 可执行文件路径（仅兜底后端使用）。
        headed: 是否以有头模式启动 agent-browser（仅兜底后端使用）。
        cdp_url: 预先启动 Chrome 的 CDP WebSocket/HTTP 端点。
            例如：``http://127.0.0.1:9222``。设置后该后端优先级
            高于 agent-browser。
    """

    def __init__(
        self,
        executable: str = "",
        headed: bool = False,
        cdp_url: str = "",
    ) -> None:
        self._cdp_url = cdp_url.strip()

        if not self._cdp_url:
            from openbiliclaw.bilibili.browser import BilibiliBrowser

            self._browser: Any = BilibiliBrowser(
                executable=executable,
                headed=headed,
                cookie="",
            )
        else:
            self._browser = None

    @property
    def is_available(self) -> bool:
        """所选后端是否可调用。

        对于 CDP 后端，可用性在调用时懒判断
        （若 Chrome 实例未运行，连接仍可能失败）；
        对于 agent-browser 后端，委托给其自身的检查。
        """
        if self._cdp_url:
            return True
        return bool(self._browser and self._browser.is_available)

    @property
    def backend(self) -> str:
        """后端标识：``"cdp"`` 或 ``"agent-browser"``。"""
        return "cdp" if self._cdp_url else "agent-browser"

    async def get_page_snapshot(self, url: str) -> PageSnapshot:
        """导航至 ``url`` 并返回文本与锚点。

        CDP 后端在单次 JS evaluate 中同时抓取两者；agent-browser
        兜底仅暴露文本，因此 ``anchors`` 返回空。
        """
        if self._cdp_url:
            return await self._get_page_snapshot_cdp(url)
        assert self._browser is not None
        text: str = await self._browser.get_page_content(url)
        return PageSnapshot(text=text, anchors=[])

    async def get_page_text(self, url: str) -> str:
        """导航至 ``url`` 并仅返回可见页面文本。

    对 :meth:`get_page_snapshot` 的薄封装，供不需要锚点数据的
    调用方使用。
        """
        snapshot = await self.get_page_snapshot(url)
        return snapshot.text

    async def close(self) -> None:
        """关闭兜底后端；CDP 后端按调用逐次分离。"""
        if self._cdp_url:
            return
        if self._browser is not None:
            await self._browser.close()

    async def _get_page_snapshot_cdp(self, url: str) -> PageSnapshot:
        """通过 CDP 连接到运行中的 Chrome，导航并返回快照。"""
        async with _async_playwright() as pw:
            browser = await pw.chromium.connect_over_cdp(self._cdp_url)
            try:
                context = browser.contexts[0] if browser.contexts else await browser.new_context()
                page = await context.new_page()
                try:
                    await page.goto(url, wait_until="domcontentloaded")
                    try:
                        await page.wait_for_load_state("networkidle", timeout=5000)
                    except Exception:
                        # 许多 SPA 信息流永远不会进入 idle 状态 ——
                        # DOMContentLoaded 足以为 JS 抽取器提供可处理内容。
                        logger.debug("networkidle timeout for %s; proceeding", url)
                    raw = await page.evaluate(_PAGE_SNAPSHOT_SCRIPT)
                finally:
                    try:
                        await page.close()
                    except Exception:
                        logger.debug("failed to close CDP page", exc_info=True)
            finally:
                # 对 CDP 连接的浏览器调用 ``close()`` 仅分离连接 ——
                # 不会终止宿主 Chrome。
                try:
                    await browser.close()
                except Exception:
                    logger.debug("failed to detach CDP browser", exc_info=True)

        if not isinstance(raw, dict):
            raise RuntimeError(f"CDP backend returned non-dict snapshot: {type(raw)!r}")
        text = raw.get("text", "")
        if not isinstance(text, str):
            raise RuntimeError(f"CDP snapshot .text is not a string: {type(text)!r}")
        anchors_raw = raw.get("anchors", []) or []
        anchors: list[tuple[str, str]] = []
        for entry in anchors_raw:
            if not isinstance(entry, dict):
                continue
            t = str(entry.get("text") or "").strip()
            h = str(entry.get("href") or "").strip()
            if t and h:
                anchors.append((t, h))
        return PageSnapshot(text=text, anchors=anchors)
