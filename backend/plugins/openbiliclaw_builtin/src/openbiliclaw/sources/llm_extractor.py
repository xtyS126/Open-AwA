"""基于 LLM 的原始页面文本内容抽取。

使用 LLM 将非结构化网页文本转换为结构化的 DiscoveredContent
对象，以识别标题、作者、摘要与 URL。
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from openbiliclaw.discovery.engine import DiscoveredContent

logger = logging.getLogger(__name__)

_EXTRACTION_SYSTEM_PROMPT = """\
<task>
你是一个内容提取助手。给定一段网页文本，从中提取所有独立的内容条目。
</task>

<rules>
1. 输出必须是严格 JSON 数组。
2. 每个条目包含以下字段：
   - title: 内容标题（必填）
   - author: 作者名（如有）
   - summary: 内容摘要，50-200字（如有）
   - url: 内容链接（如有，必须是完整URL）
   - content_id: 内容的唯一标识（从URL提取，如笔记ID、帖子ID等）
3. 只提取真正的内容条目（文章、帖子、笔记、视频等），忽略导航、广告、页脚。
4. 如果页面文本中没有可提取的内容条目，返回空数组 []。
5. 最多提取 20 条。
</rules>

<output_schema>
[
  {
    "title": "标题",
    "author": "作者",
    "summary": "摘要",
    "url": "https://example.com/post/123",
    "content_id": "123"
  }
]
</output_schema>
"""


async def extract_content_from_page(
    page_text: str,
    *,
    source_platform: str,
    llm_service: Any,
    base_url: str = "",
) -> list[DiscoveredContent]:
    """使用 LLM 从原始页面文本中抽取结构化内容条目。

    Args:
        page_text: 网页原始可见文本。
        source_platform: 平台标识（例如 "xiaohongshu"、"web"）。
        llm_service: 提供 ``complete_structured_task()`` 的 LLM 服务。
        base_url: 用于解析相对链接的基础 URL。

    Returns:
        从页面中抽取的 DiscoveredContent 条目列表。
    """
    from openbiliclaw.discovery.engine import DiscoveredContent

    if not page_text or len(page_text.strip()) < 50:
        logger.debug("Page text too short for extraction (%d chars)", len(page_text))
        return []

    # 截断过长的页面，以保持在 LLM 上下文上限内
    truncated = page_text[:8000] if len(page_text) > 8000 else page_text

    user_prompt = (
        f"<platform>{source_platform}</platform>\n\n<page_text>\n{truncated}\n</page_text>"
    )

    try:
        response = await llm_service.complete_structured_task(
            system_instruction=_EXTRACTION_SYSTEM_PROMPT,
            user_input=user_prompt,
            temperature=0.3,
            max_tokens=4096,
            caller=f"sources.{source_platform}.extract",
        )
    except Exception:
        logger.exception("LLM extraction failed for %s page", source_platform)
        return []

    try:
        items_raw = json.loads(response.content)
    except (json.JSONDecodeError, TypeError):
        logger.warning("LLM extraction returned invalid JSON: %.200s", response.content)
        return []

    if not isinstance(items_raw, list):
        logger.warning("LLM extraction returned non-list: %s", type(items_raw))
        return []

    results: list[DiscoveredContent] = []
    for item in items_raw:
        if not isinstance(item, dict):
            continue
        # LLM 常对缺失字段返回 JSON null —— 此时 ``item.get(key, "")``
        # 取到的是 ``None``（值），而非默认值，且 ``str(None)``
        # 会产生字符串 ``"None"``，使下游每个真值检查都视为已填充。
        # 在 strip 前强制转为 ""。
        title = str(item.get("title") or "").strip()
        if not title:
            continue

        content_id = str(item.get("content_id") or "").strip()
        content_url = str(item.get("url") or "").strip()

        # 若未提供 content_id，则从 URL 生成
        if not content_id and content_url:
            content_id = content_url.rstrip("/").rsplit("/", 1)[-1]
        if not content_id:
            content_id = title[:32]

        results.append(
            DiscoveredContent(
                content_id=content_id,
                content_url=content_url,
                source_platform=source_platform,
                title=title,
                author_name=str(item.get("author") or "").strip(),
                description=str(item.get("summary") or "").strip(),
                source_strategy="web_extract",
            )
        )

    logger.info(
        "Extracted %d content items from %s page (%d chars)",
        len(results),
        source_platform,
        len(page_text),
    )
    return results
