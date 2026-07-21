"""
news 内置技能 — RSS/Atom 新闻聚合与摘要。
支持从 RSS 源获取新闻、关键词搜索和内容摘要。
"""
from typing import Any, Optional
from datetime import datetime, timezone
from loguru import logger

SKILL_NAME = "news"
SKILL_DESCRIPTION = "RSS/Atom 新闻聚合，支持获取头条、关键词搜索和内容摘要"

try:
    import xml.etree.ElementTree as ET
    HAS_XML = True
except ImportError:
    HAS_XML = False

try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False

# 预置常用中文 RSS 源
DEFAULT_FEEDS = {
    "zhihu_daily": "https://www.zhihu.com/rss",
    "36kr": "https://36kr.com/feed",
    "solidot": "https://www.solidot.org/index.rss",
    "cnbeta": "https://www.cnbeta.com/backend.php",
}

# 内存缓存（简单实现，避免频繁请求）
_cache: dict[str, dict] = {}


def _parse_rss(xml_text: str) -> list[dict[str, Any]]:
    """解析 RSS/Atom XML 为条目列表。"""
    items = []
    try:
        root = ET.fromstring(xml_text)

        # RSS 2.0 格式
        for item in root.iter("item"):
            title = ""
            link = ""
            description = ""
            pub_date = ""
            for child in item:
                tag = child.tag.lower() if "}" not in child.tag else child.tag.split("}", 1)[1]
                if tag == "title":
                    title = (child.text or "").strip()
                elif tag == "link":
                    link = (child.text or child.get("href", "")).strip()
                elif tag in ("description", "summary"):
                    description = (child.text or "").strip()
                elif tag in ("pubdate", "published"):
                    pub_date = (child.text or "").strip()
            if title:
                items.append({
                    "title": title,
                    "link": link,
                    "description": description[:200] if description else "",
                    "pub_date": pub_date,
                })

        # Atom 格式
        if not items:
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            for entry in root.findall(".//atom:entry", ns) or root.findall(".//entry"):
                title_el = entry.find("title") or entry.find("atom:title", ns)
                link_el = entry.find("link") or entry.find("atom:link", ns)
                summary_el = entry.find("summary") or entry.find("atom:summary", ns)
                published_el = entry.find("published") or entry.find("atom:published", ns)
                title = (title_el.text or "").strip() if title_el is not None else ""
                link = ""
                if link_el is not None:
                    link = link_el.get("href", "") or link_el.text or ""
                description = (summary_el.text or "").strip() if summary_el is not None else ""
                pub_date = (published_el.text or "").strip() if published_el is not None else ""
                if title:
                    items.append({
                        "title": title,
                        "link": link.strip(),
                        "description": description[:200] if description else "",
                        "pub_date": pub_date,
                    })

    except ET.ParseError as e:
        logger.warning(f"RSS 解析失败: {str(e)}")

    return items


async def execute(
    action: str = "fetch_headlines",
    source: str = "zhihu_daily",
    query: Optional[str] = None,
    url: Optional[str] = None,
    max_items: int = 10,
    **kwargs: Any,
) -> dict[str, Any]:
    """
    执行新闻聚合操作。

    Args:
        action: 操作类型（fetch_headlines/search/summarize/list_sources）
        source: RSS 源标识（zhihu_daily/36kr/solidot/cnbeta）
        query: 搜索关键词
        url: 自定义 RSS 源 URL
        max_items: 最大返回条数

    Returns:
        新闻条目列表及元数据
    """
    if not HAS_XML:
        return {"success": False, "error": "缺少 xml 解析库"}

    valid_actions = {"fetch_headlines", "search", "summarize", "list_sources"}
    if action not in valid_actions:
        return {"success": False, "error": f"不支持的操作: {action}，支持: {', '.join(sorted(valid_actions))}"}

    # ---- 列出可用源 ----
    if action == "list_sources":
        return {
            "success": True,
            "action": "list_sources",
            "sources": [
                {"id": sid, "url": surl}
                for sid, surl in DEFAULT_FEEDS.items()
            ],
        }

    # ---- 获取 RSS 内容 ----
    feed_url = url or DEFAULT_FEEDS.get(source)
    if not feed_url:
        return {
            "success": False,
            "error": f"未知的 RSS 源: {source}，可用源: {', '.join(DEFAULT_FEEDS.keys())}",
        }

    # 检查缓存（5 分钟内有效）
    cache_key = f"{feed_url}"
    now = datetime.now(timezone.utc)
    if cache_key in _cache:
        cached = _cache[cache_key]
        if (now - cached["fetched_at"]).total_seconds() < 300:
            items = cached["items"]
        else:
            items = []
    else:
        items = []

    # 从远程获取
    if not items:
        try:
            if HAS_HTTPX:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.get(feed_url, headers={"User-Agent": "Open-AwA/1.0"})
                    if resp.status_code == 200:
                        items = _parse_rss(resp.text)
                        _cache[cache_key] = {"items": items, "fetched_at": now}
                    else:
                        return {"success": False, "error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
            else:
                return {"success": False, "error": "缺少 httpx 依赖"}
        except Exception as e:
            return {"success": False, "error": f"获取 RSS 失败: {str(e)}"}

    # ---- 获取头条 ----
    if action == "fetch_headlines":
        result = items[:max_items]
        return {
            "success": True,
            "action": "fetch_headlines",
            "source": source,
            "count": len(result),
            "items": result,
        }

    # ---- 搜索 ----
    elif action == "search":
        if not query:
            return {"success": False, "error": "搜索需要提供 query"}
        matched = [
            item for item in items
            if query.lower() in item["title"].lower() or query.lower() in item["description"].lower()
        ]
        return {
            "success": True,
            "action": "search",
            "source": source,
            "query": query,
            "count": len(matched[:max_items]),
            "items": matched[:max_items],
        }

    # ---- 摘要 ----
    elif action == "summarize":
        headlines = [item["title"] for item in items[:max_items]]
        summary = f"来自 {source} 的最新 {len(headlines)} 条新闻:\n" + "\n".join(f"- {h}" for h in headlines)
        return {
            "success": True,
            "action": "summarize",
            "source": source,
            "count": len(headlines),
            "summary": summary,
        }

    return {"success": False, "error": "未识别的操作"}
