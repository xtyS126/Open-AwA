"""
浏览器工具增强，在现有 fetch_url 基础上增加截图和页面内容感知能力。
参考 OpenHanako lib/tools/browser-tool.js 和 web-fetch.js 设计。

提供操作：
- screenshot：截取页面截图（需要 Playwright）
- snapshot：获取 JS 渲染后的页面文本快照
- navigate：导航到 URL 并返回渲染后的文本

设计原则：
- 不引入额外依赖，Playwright 为可选增强
- 优先使用 Playwright 如果可用，否则使用 httpx 作为降级
- SSRF 防护（禁止访问内网/私有IP）
- 与现有 WebSearchSkill.fetch_url 互补：
  - fetch_url：DuckDuckGo 纯文本 HTML 获取（轻量、无外部依赖）
  - BrowserExtendedSkill.screenshot/snapshot：Playwright 驱动的富交互页面能力
"""

from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
import urllib.parse
from typing import Any, Dict, List, Optional

from loguru import logger

# ── 常量 ──────────────────────────────────────────────────────────

# 浏览器操作的最大超时（秒）
BROWSER_ACTION_TIMEOUT = 30
# 页面导航的最大超时（秒）
BROWSER_NAVIGATION_TIMEOUT = 30
# 快照文本的最大长度（字符）
MAX_SNAPSHOT_LENGTH = 10000

# SSRF 防护：禁止访问的内网 IP 前缀
BLOCKED_PREFIXES = [
    ipaddress.ip_network("10.0.0.0/8"),       # 私有 A 类
    ipaddress.ip_network("172.16.0.0/12"),    # 私有 B 类
    ipaddress.ip_network("192.168.0.0/16"),   # 私有 C 类
    ipaddress.ip_network("127.0.0.0/8"),      # 回环
    ipaddress.ip_network("169.254.0.0/16"),   # 链路本地
    ipaddress.ip_network("0.0.0.0/8"),        # 当前网络
    ipaddress.ip_network("::1/128"),          # IPv6 回环
    ipaddress.ip_network("fc00::/7"),         # IPv6 唯一本地
    ipaddress.ip_network("fe80::/10"),        # IPv6 链路本地
]


async def _is_private_host(host: str) -> bool:
    """
    SSRF 安全检查：判断主机名是否指向内网/私有地址。

    先尝试直接解析为 IP，失败则通过 DNS 解析后检查。
    返回 True 表示需要拦截该主机。
    使用 asyncio.to_thread 包装 socket.getaddrinfo，避免阻塞事件循环。
    """
    # 第一步：尝试直接将 host 解析为 IP 地址
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        # host 是域名，需要 DNS 解析（在线程池中执行，避免阻塞事件循环）
        try:
            resolved = await asyncio.to_thread(socket.getaddrinfo, host, None)
            if not resolved:
                return True
            addr = ipaddress.ip_address(resolved[0][4][0])
        except (socket.gaierror, OSError):
            # DNS 解析失败，保守拒绝
            return True

    # 第二步：检查解析后的 IP 是否属于内网/私有地址段
    for prefix in BLOCKED_PREFIXES:
        if addr in prefix:
            return True
    return False


async def _validate_url(url: str) -> Optional[str]:
    """
    验证 URL 安全性的工具函数。

    检查项：
    1. URL 格式有效性
    2. 协议白名单（仅 http/https）
    3. 主机名存在性
    4. SSRF 防护（禁止内网地址）

    返回 None 表示 URL 通过校验，否则返回错误描述字符串。
    """
    # 检查 URL 格式
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:
        return "URL 格式无效"

    # 协议白名单：仅允许 http/https
    if parsed.scheme not in ("http", "https"):
        return f"不支持的协议: {parsed.scheme}"

    # 主机名必须存在
    host = parsed.hostname
    if not host:
        return "URL 缺少主机名"

    # SSRF 防护检查
    if await _is_private_host(host):
        return f"禁止访问内网地址: {host}"

    return None


def _build_snapshot_text(page_content: str, url: str) -> str:
    """
    构建页面快照文本：将 HTML 内容转换为可读的纯文本。

    处理步骤：
    1. 移除 script、style、head、nav、footer 标签及其内容
    2. 块级标签替换为换行
    3. 移除其余 HTML 标签
    4. 清理多余空白
    5. 超长内容截断
    """
    # 移除脚本、样式和元数据区域
    cleaned = re.sub(
        r'<script[^>]*>.*?</script>', '',
        page_content, flags=re.DOTALL | re.IGNORECASE
    )
    cleaned = re.sub(
        r'<style[^>]*>.*?</style>', '',
        cleaned, flags=re.DOTALL | re.IGNORECASE
    )
    cleaned = re.sub(
        r'<head[^>]*>.*?</head>', '',
        cleaned, flags=re.DOTALL | re.IGNORECASE
    )
    cleaned = re.sub(
        r'<nav[^>]*>.*?</nav>', '',
        cleaned, flags=re.DOTALL | re.IGNORECASE
    )
    cleaned = re.sub(
        r'<footer[^>]*>.*?</footer>', '',
        cleaned, flags=re.DOTALL | re.IGNORECASE
    )

    # 块级标签替换为换行，保留文本结构
    cleaned = re.sub(
        r'</?(?:p|div|br|h[1-6]|li|tr|blockquote|section|article|header)[^>]*>',
        '\n', cleaned, flags=re.IGNORECASE
    )

    # 保留链接：提取 href 和链接文本
    cleaned = re.sub(
        r'<a[^>]*href="([^"]*)"[^>]*>([\s\S]*?)</a>',
        r'\2 (\1)', cleaned, flags=re.IGNORECASE
    )

    # 移除所有剩余的 HTML 标签
    text = re.sub(r'<[^>]+>', ' ', cleaned)

    # 解码 HTML 实体
    text = text.replace('&nbsp;', ' ').replace('&amp;', '&')
    text = text.replace('&lt;', '<').replace('&gt;', '>')
    text = text.replace('&quot;', '"')

    # 清理连续空白
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = text.strip()

    # 截断超长内容（保留前 MAX_SNAPSHOT_LENGTH 字符）
    if len(text) > MAX_SNAPSHOT_LENGTH:
        text = text[:MAX_SNAPSHOT_LENGTH] + f"\n\n... [内容已截断，原长度 {len(text)} 字符]"

    # 添加页面来源头部
    header = f"# 页面快照\nURL: {url}\n\n"
    return header + text


async def _fetch_with_httpx(url: str, timeout: int = BROWSER_ACTION_TIMEOUT) -> Dict[str, Any]:
    """
    使用 httpx 获取页面内容（Playwright 不可用时的降级方案）。

    Args:
        url: 目标网页 URL
        timeout: 请求超时（秒）

    Returns:
        包含 content、status_code、headers 的响应字典
    """
    import httpx

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        response = await client.get(url, headers={
            "User-Agent": "Mozilla/5.0 (compatible; Open-AwA/1.0)",
            "Accept": "text/html,application/json,text/plain,*/*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        })
        response.raise_for_status()
        return {
            "content": response.text,
            "status_code": response.status_code,
            "headers": dict(response.headers),
        }


async def _screenshot_with_playwright(url: str, timeout: int = BROWSER_ACTION_TIMEOUT) -> Dict[str, Any]:
    """
    使用 Playwright 截取页面截图。

    启动无头 Chromium，导航到目标页面，截图并返回 base64 编码的 PNG。

    Args:
        url: 目标网页 URL
        timeout: 操作超时（秒）

    Returns:
        包含 success、screenshot_base64、page_title、url 的结果字典
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return {"success": False, "error": "Playwright 未安装。请运行: pip install playwright && playwright install chromium"}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            # 导航到目标页面，等待 DOM 加载完成
            await page.goto(url, timeout=timeout * 1000, wait_until="domcontentloaded")

            # 截取可视区域截图（非全页）
            screenshot_bytes = await page.screenshot(full_page=False, type="png")
            import base64
            screenshot_b64 = base64.b64encode(screenshot_bytes).decode("utf-8")

            page_title = await page.title()

            return {
                "success": True,
                "screenshot_base64": screenshot_b64,
                "page_title": page_title,
                "url": url,
            }
        finally:
            # 确保浏览器实例被关闭，防止资源泄露
            await browser.close()


async def _snapshot_with_playwright(url: str, timeout: int = BROWSER_ACTION_TIMEOUT) -> Dict[str, Any]:
    """
    使用 Playwright 获取 JS 渲染后的页面文本快照。

    与 fetch_url 不同的是，此方法会等待 JS 执行完毕后再获取页面内容，
    适合 JS 密集型页面（SPA、动态渲染页面等）。

    Args:
        url: 目标网页 URL
        timeout: 操作超时（秒）

    Returns:
        包含 success、snapshot、page_title、url、render_engine 的结果字典
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return {"success": False, "error": "Playwright 未安装。请运行: pip install playwright && playwright install chromium"}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            # 等待 DOM 内容加载完成（不等待所有资源）
            await page.goto(url, timeout=timeout * 1000, wait_until="domcontentloaded")

            # 获取 JS 渲染后的完整 HTML
            html_content = await page.content()
            page_title = await page.title()

            # 构建可读文本快照
            snapshot_text = _build_snapshot_text(html_content, url)

            return {
                "success": True,
                "snapshot": snapshot_text[:MAX_SNAPSHOT_LENGTH],
                "page_title": page_title,
                "url": url,
                "render_engine": "playwright",
            }
        finally:
            await browser.close()


class BrowserExtendedSkill:
    """
    浏览器扩展技能。

    提供截图和 JS 渲染后的页面快照能力。
    与现有的 WebSearchSkill（DuckDuckGo 纯文本抓取）互补：
    - WebSearchSkill.fetch_url：轻量级 HTML 文本获取，无外部依赖
    - BrowserExtendedSkill.screenshot/snapshot：Playwright 驱动的富交互页面能力

    核心操作：
    - screenshot：截取页面截图（base64 PNG），用于视觉检查
    - snapshot：获取 JS 渲染后的页面文本，适合动态/SPA 页面
    - navigate：同 snapshot 别名，导航到 URL 获取渲染内容
    """

    name: str = "browser_extended"
    version: str = "1.0.0"
    description: str = "浏览器扩展工具（截图和页面快照）"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """初始化浏览器扩展技能。"""
        self.config = config or {}
        self.timeout = self.config.get("timeout", BROWSER_ACTION_TIMEOUT)
        self._initialized = False

    async def initialize(self) -> bool:
        """异步初始化技能。"""
        logger.info(f"BrowserExtendedSkill 已初始化 timeout={self.timeout}")
        self._initialized = True
        return True

    def is_initialized(self) -> bool:
        """检查技能是否已初始化。"""
        return self._initialized

    async def execute(self, **kwargs) -> Dict[str, Any]:
        """
        执行浏览器操作的主入口。

        根据 action 参数分发到具体的处理方法：
        - screenshot：截取页面截图
        - snapshot：获取页面文本快照
        - navigate：导航并返回渲染内容（同 snapshot）

        Args:
            action: 操作名称（screenshot/snapshot/navigate）
            url: 目标网页 URL

        Returns:
            包含执行结果的字典，success 字段指示是否成功
        """
        if not self._initialized:
            return {"success": False, "error": "浏览器工具未初始化"}

        action = kwargs.get("action", "snapshot")
        url = kwargs.get("url", "")

        # 参数校验：URL 必填
        if not url:
            return {"success": False, "error": "URL 参数不能为空"}

        # URL 安全校验（协议白名单 + SSRF 防护，异步调用）
        error = await _validate_url(url)
        if error:
            return {"success": False, "error": error}

        # 分发到具体操作
        if action == "screenshot":
            return await self._screenshot(url)
        elif action == "snapshot":
            return await self._snapshot(url)
        elif action == "navigate":
            return await self._navigate(url)
        else:
            return {"success": False, "error": f"未知浏览器操作: {action}"}

    async def _screenshot(self, url: str) -> Dict[str, Any]:
        """
        截取页面截图。

        使用 Playwright 启动无头浏览器截取页面可视区域为 PNG，
        返回 base64 编码后的图像数据。
        """
        logger.info(f"浏览器截图: {url}")
        return await _screenshot_with_playwright(url, self.timeout)

    async def _snapshot(self, url: str) -> Dict[str, Any]:
        """
        获取页面文本快照。

        优先使用 Playwright 获取 JS 渲染后的内容；
        如果 Playwright 不可用，降级为 httpx 直接获取 HTML。
        """
        logger.info(f"浏览器快照: {url}")

        # 主路径：Playwright 渲染
        result = await _snapshot_with_playwright(url, self.timeout)
        if result.get("success"):
            return result

        # 降级路径：httpx 直接获取 HTML
        logger.info(f"Playwright 快照不可用，降级为 httpx: {url}")
        try:
            resp = await _fetch_with_httpx(url, self.timeout)
            snapshot_text = _build_snapshot_text(resp["content"], url)
            return {
                "success": True,
                "snapshot": snapshot_text[:MAX_SNAPSHOT_LENGTH],
                "page_title": "",
                "url": url,
                "render_engine": "httpx",
            }
        except Exception as e:
            logger.error(f"页面快照失败: url={url}, error={e}")
            return {"success": False, "error": f"页面快照失败: {str(e)}"}

    async def _navigate(self, url: str) -> Dict[str, Any]:
        """
        导航到 URL 并返回渲染后的页面内容。

        与 snapshot 行为一致，提供别名方便 LLM 调用。
        """
        logger.info(f"浏览器导航: {url}")
        return await self._snapshot(url)

    def get_tools(self) -> List[Dict[str, Any]]:
        """
        返回技能提供的工具定义列表。

        供 manager.py 的 list_tools 方法使用，
        在 /api/tools/list 接口中展示。
        """
        return [
            {
                "name": "screenshot",
                "description": "截取网页截图，返回 base64 编码的 PNG 图像（需要 Playwright 支持）",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "要截图的网页 URL（必须 http/https）"
                        },
                    },
                    "required": ["url"],
                },
            },
            {
                "name": "snapshot",
                "description": "获取页面文本快照（JS 渲染后的内容），适合动态/SPA 页面",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "要获取快照的网页 URL（必须 http/https）"
                        },
                    },
                    "required": ["url"],
                },
            },
            {
                "name": "navigate",
                "description": "导航到指定 URL 并返回渲染后的页面内容（同 snapshot）",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "要导航到的网页 URL（必须 http/https）"
                        },
                    },
                    "required": ["url"],
                },
            },
        ]

    def cleanup(self):
        """清理技能资源。"""
        self._initialized = False
        logger.info(f"{self.name} skill cleaned up")
