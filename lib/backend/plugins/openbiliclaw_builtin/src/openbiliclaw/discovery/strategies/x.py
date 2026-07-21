"""X (Twitter) 发现策略 — 仅抓取的生产者。

三个策略驱动服务端 ``XClient`` (在 ``twitter-cli`` 上重放 cookie),
并将原始 ``tweet_to_dict`` dict 归一化为
:class:`DiscoveredContent`:

``XSearchStrategy``
    LLM 从 Soul profile 生成 X 风格的搜索关键词 (复用
    ``xhs_keyword_gen`` 方式) → ``XClient.search`` → ``normalize_tweet``。
    显式的 ``query`` (来自 recipe / subscription) 会短路关键词
    生成。

``XForYouStrategy``
    读取用户的 "For You" 主页时间线 (``XClient.for_you``)。

``XCreatorStrategy``
    按 handle 读取创作者最近的推文 (``XClient.user_tweets``)。

这些策略是 **仅抓取的**: 它们返回归一化的候选,并
不评分 / 写 ``content_cache``。共享的多源评估器在下游拥有
那部分职责 (按统一池 spec)。``normalize_tweet`` → ``None``
的 item (墓碑 / 不可用推文) 会被丢弃。

懒加载说明: 本模块从不在模块加载时导入 ``twitter_cli``。
``XClient`` 仅用于类型提示 (``TYPE_CHECKING``);具体
client 由运行时在 enabled 路径上注入。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

from openbiliclaw.discovery.strategies._utils import build_profile_summary
from openbiliclaw.discovery.x_normalize import normalize_tweet
from openbiliclaw.llm.json_utils import parse_llm_json_tolerant
from openbiliclaw.llm.task_options import without_core_memory_kwargs

if TYPE_CHECKING:
    from openbiliclaw.discovery.engine import DiscoveredContent
    from openbiliclaw.soul.profile import SoulProfile

logger = logging.getLogger(__name__)

# Source-strategy 标签,携带在每个归一化 item 上 (并被生产者 / 池
# 用来把 X 候选归因到正确的子策略)。
SEARCH_STRATEGY_TAG = "x-search"
FEED_STRATEGY_TAG = "x-feed"
CREATOR_STRATEGY_TAG = "x-creator"


class SupportsXRead(Protocol):
    """策略驱动的 :class:`XClient` 子集 (测试注入 fake)。"""

    async def search(
        self, query: str, *, limit: int, product: str = "Top"
    ) -> list[dict[str, Any]]: ...

    async def for_you(self, *, limit: int) -> list[dict[str, Any]]: ...

    async def user_tweets(self, handle: str, *, limit: int) -> list[dict[str, Any]]: ...


class SupportsStructuredTask(Protocol):
    async def complete_structured_task(
        self,
        *,
        system_instruction: str,
        user_input: str,
        history: list[dict[str, str]] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        caller: str = "",
        reasoning_effort: str | None = None,
    ) -> object: ...


# X 风格的关键词生成。镜像 ``xhs_keyword_gen``: 字节静态的
# system prompt (prompt-cache 约定),所有每次调用的数据放在 user
# message 里。
_KEYWORDS_SYSTEM_PROMPT = """\
你要为 X(Twitter)内容发现生成一组适合 X 搜索的关键词。

规则：
1. 输出必须是严格 JSON，不要附带解释。
2. query 是 1-4 个词的短语，适合直接在 X 搜索框输入。
3. 优先英文(X 上英文内容更多),技术/小众话题尤其如此;华语圈话题可用中文。
4. 数量 3 到 6 个,覆盖用户画像中不同兴趣领域。
5. 避免过于宽泛的单词,带上限定词。

输出格式：
{"keywords": ["rust async runtime", "machine learning papers", ...]}
"""


def _parse_keywords(content: str, *, count: int) -> list[str]:
    payload = parse_llm_json_tolerant(content)
    if payload is None:
        try:
            payload = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            logger.warning("x keyword LLM returned non-JSON: %r", content[:200])
            return []
    if not isinstance(payload, dict):
        return []
    raw_keywords = payload.get("keywords", [])
    if not isinstance(raw_keywords, list):
        return []

    seen: set[str] = set()
    keywords: list[str] = []
    for item in raw_keywords:
        text = str(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        keywords.append(text)
        if len(keywords) >= count:
            break
    return keywords


def _dedupe_keywords(keywords: list[str]) -> list[str]:
    """strip + 去重调用方注入的关键词 (统一 planner 注入)。"""
    seen: set[str] = set()
    out: list[str] = []
    for item in keywords:
        text = str(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _normalize_raw(
    raw_tweets: list[dict[str, Any]],
    *,
    source_strategy: str,
) -> list[DiscoveredContent]:
    """归一化原始 ``tweet_to_dict`` dict,丢弃墓碑和重复。"""
    seen: set[str] = set()
    out: list[DiscoveredContent] = []
    for raw in raw_tweets:
        content = normalize_tweet(raw, source_strategy=source_strategy)
        if content is None:
            continue
        key = content.content_id
        if key in seen:
            continue
        seen.add(key)
        out.append(content)
    return out


# ── XSearchStrategy ──────────────────────────────────────────────────


@dataclass
class XSearchStrategy:
    """通过 (LLM 生成的) 关键词搜索发现 X 内容。"""

    client: SupportsXRead
    llm_service: SupportsStructuredTask | None = None
    keywords_per_run: int = 4
    product: str = "Top"
    last_intermediates: dict[str, object] = field(default_factory=dict)

    async def discover(
        self,
        profile: SoulProfile,
        *,
        limit: int = 20,
        query: str = "",
        queries: list[str] | None = None,
        keyword_ids: dict[str, int] | None = None,
        **_: object,
    ) -> list[DiscoveredContent]:
        explicit = (query or "").strip()
        if explicit:
            keywords = [explicit]
        elif queries is not None:
            # 统一关键词 planner 注入: 搜索每个提供的关键词,
            # 跳过内部 LLM 关键词生成。
            keywords = _dedupe_keywords(queries)
        else:
            keywords = await self._generate_keywords(profile)
        self.last_intermediates = {"keywords": list(keywords)}
        if not keywords:
            return []

        seen: set[str] = set()
        results: list[DiscoveredContent] = []
        for keyword in keywords:
            # P1.8 yield provenance: 当前正在搜索的词的 id
            # (统一 planner 注入)。未映射 / 未注入时为 ``None``。
            keyword_id = keyword_ids.get(keyword) if keyword_ids else None
            raw = await self.client.search(keyword, limit=limit, product=self.product)
            for content in _normalize_raw(raw, source_strategy=SEARCH_STRATEGY_TAG):
                if content.content_id in seen:
                    continue
                content.source_keyword_id = keyword_id
                seen.add(content.content_id)
                results.append(content)
                if len(results) >= limit:
                    return results
        return results

    async def _generate_keywords(self, profile: SoulProfile) -> list[str]:
        if not profile.preferences.interests:
            return []
        keywords = await self._llm_keywords(profile)
        # LLM 不可用 / 失败 / 返回空时的确定性回退 —
        # 这样统一 planner (以及旧路径) 永远不会因为
        # 暂时性失败而失去 X (镜像 B站/YouTube/抖音)。
        return keywords or _x_interest_fallback(profile, self.keywords_per_run)

    async def _llm_keywords(self, profile: SoulProfile) -> list[str]:
        if self.llm_service is None:
            return []
        try:
            complete_structured = self.llm_service.complete_structured_task
            response = await complete_structured(
                system_instruction=_KEYWORDS_SYSTEM_PROMPT,
                user_input=_build_keyword_user_prompt(profile, self.keywords_per_run),
                temperature=0.8,
                max_tokens=512,
                caller="discovery.x.keyword_gen",
                **without_core_memory_kwargs(complete_structured),
            )
        except Exception as exc:  # noqa: BLE001 - 降级到回退
            logger.warning("x keyword LLM call failed: %s", exc)
            return []

        content = getattr(response, "content", response)
        text = str(content).strip()
        return _parse_keywords(text, count=self.keywords_per_run)


def _build_keyword_user_prompt(profile: SoulProfile, count: int) -> str:
    # 与其他所有发现 prompt 看到的相同结构化 profile
    # (B站 / YouTube query-gen、全平台 evaluation) — 没有
    # 分歧的表示。确定性 dump 保持 prompt-cache prefix 稳定。
    summary = build_profile_summary(profile)
    return (
        "<profile_summary>\n"
        + json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n</profile_summary>\n\n"
        + "请基于上面画像里的兴趣（interests / interest_domains），结合 disliked_topics 避雷，"
        + f"输出 {count} 个适合 X 搜索的关键词。"
    )


def _x_interest_fallback(profile: SoulProfile, count: int) -> list[str]:
    """确定性的 interest 名关键词 (镜像 B站/YouTube/抖音 回退)。"""
    ranked = sorted(
        profile.preferences.interests, key=lambda tag: float(tag.weight or 0.0), reverse=True
    )
    seen: set[str] = set()
    out: list[str] = []
    for tag in ranked:
        name = str(tag.name).strip()
        if not name or name in seen:
            continue
        seen.add(name)
        out.append(name)
        if len(out) >= count:
            break
    return out


# ── XForYouStrategy ──────────────────────────────────────────────────


@dataclass
class XForYouStrategy:
    """从用户的 "For You" 主页时间线发现 X 内容。"""

    client: SupportsXRead

    async def discover(
        self,
        profile: SoulProfile,
        *,
        limit: int = 20,
        **_: object,
    ) -> list[DiscoveredContent]:
        raw = await self.client.for_you(limit=limit)
        return _normalize_raw(raw, source_strategy=FEED_STRATEGY_TAG)[:limit]


# ── XCreatorStrategy ─────────────────────────────────────────────────


@dataclass
class XCreatorStrategy:
    """从订阅创作者的最近推文发现 X 内容。"""

    client: SupportsXRead

    async def discover(
        self,
        profile: SoulProfile,
        *,
        limit: int = 20,
        handle: str = "",
        **_: object,
    ) -> list[DiscoveredContent]:
        target = (handle or "").strip()
        if not target:
            return []
        raw = await self.client.user_tweets(target, limit=limit)
        return _normalize_raw(raw, source_strategy=CREATOR_STRATEGY_TAG)[:limit]
