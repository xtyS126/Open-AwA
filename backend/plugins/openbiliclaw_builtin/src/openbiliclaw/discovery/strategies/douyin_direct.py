"""抖音直连 cookie 发现策略。"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

from openbiliclaw.discovery.engine import (
    ContentDiscoveryEngine,
    DiscoveredContent,
    DiscoveryConcurrencyController,
    DiscoveryStrategy,
    SupportsStructuredTask,
    discovery_raw_candidate_mode_enabled,
    trim_candidates_for_llm,
)
from openbiliclaw.discovery.strategies._utils import build_profile_summary
from openbiliclaw.llm.json_utils import parse_llm_json_tolerant
from openbiliclaw.llm.task_options import without_core_memory_kwargs
from openbiliclaw.sources.douyin_direct import normalize_aweme_item

if TYPE_CHECKING:
    from openbiliclaw.soul.profile import SoulProfile
    from openbiliclaw.storage.database import Database

logger = logging.getLogger(__name__)


class SupportsDouyinDirectClient(Protocol):
    async def search_aweme(self, keyword: str, *, limit: int = 30) -> list[dict[str, object]]: ...
    async def get_hot_board(self, *, limit: int = 30) -> list[dict[str, object]]: ...

    async def get_creator_posts(
        self,
        sec_uid: str,
        *,
        limit: int = 30,
    ) -> list[dict[str, object]]: ...

    async def get_recommend_feed(self, *, limit: int = 30) -> list[dict[str, object]]: ...


# 抖音风格的关键词生成。镜像 x.py / xhs_keyword_gen: 
# 字节静态的 system prompt (prompt-cache 约定),所有每次调用的数据
# (build_profile_summary dict) 放在 user message 里。
_DOUYIN_KEYWORDS_SYSTEM_PROMPT = """\
你要为抖音内容发现生成一组适合抖音搜索的关键词。

抖音风格的关键词特征：
- 口语化、具体、贴近大众日常，不要宽泛的学科 / 品类词
- 偏话题 / 场景 / 热点表达（"教程 / 合集 / 名场面 / 挑战 / vlog / 测评"等尾词常见）
- 2~10 个字为主，中文为主
- 避免只给单字类目词（"科技""游戏"），要加限定词

规则：
1. 输出必须是严格 JSON，不要附带解释。
2. 数量 3 到 6 个，覆盖用户画像中不同兴趣领域，避开 disliked_topics。

输出格式：
{"keywords": ["露营装备测评", "和田玉鉴别教程", ...]}
"""


def _build_douyin_keyword_user_prompt(profile: SoulProfile, count: int) -> str:
    # 与其他所有发现 prompt 看到的相同结构化 profile
    # (B站 / YouTube / X / 小红书 query-gen、全平台 evaluation) — 没有
    # 分歧的表示。确定性 dump 保持 cache prefix 稳定。
    summary = build_profile_summary(profile)
    return (
        "<profile_summary>\n"
        + json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n</profile_summary>\n\n"
        + "请基于上面画像里的兴趣（interests / interest_domains），避开 disliked_topics，"
        + f"输出 {count} 个适合抖音搜索的关键词。"
    )


def _parse_douyin_keywords(content: str, *, count: int) -> list[str]:
    payload = parse_llm_json_tolerant(content)
    if payload is None:
        try:
            payload = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            logger.warning("douyin keyword LLM returned non-JSON: %r", content[:200])
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


@dataclass
class DouyinDirectStrategy(DiscoveryStrategy):
    """使用后端直连 cookie Web 请求发现抖音候选。"""

    client: SupportsDouyinDirectClient
    llm_service: SupportsStructuredTask | None = None
    concurrency: DiscoveryConcurrencyController | None = None
    database: Database | None = None
    sources: tuple[str, ...] = ("search", "hot", "feed")
    seed_keywords: tuple[str, ...] = ()
    # P1.8 yield provenance: ``keyword text → discovery_keywords.id`` 用于
    # 注入的搜索词。旧 run 为空。由映射关键词产出的搜索候选携带其 id,
    # 以便 admission 能回填 yield。
    seed_keyword_ids: dict[str, int] = field(default_factory=dict)
    creator_sec_uids: tuple[str, ...] = ()
    keywords_per_run: int = 5
    per_source_limit: int = 20
    llm_evaluation: bool = True
    score_threshold: float = 0.60
    last_intermediates: dict[str, object] = field(default_factory=dict)

    @property
    def name(self) -> str:
        return "douyin_direct"

    async def discover(self, profile: SoulProfile, limit: int = 20) -> list[DiscoveredContent]:
        # 每个 raw item 携带 (source_strategy, raw_dict, source_keyword_id)。
        # 只有 search item 拿到非 None 的 keyword id (P1.8 yield provenance);
        # hot / feed / creator item 无归因 (None)。
        raw_items: list[tuple[str, dict[str, object], int | None]] = []
        # 只有当 search source 激活时才合成 / LLM 生成搜索关键词。
        # 仅 hot/feed/creator 模式绝不应为它们永远不会搜索的关键词
        # 烧一次 LLM 调用 (或回退到 interest 名)。
        keywords = await self._keywords(profile) if "search" in self.sources else []
        self.last_intermediates = {
            "sources": list(self.sources),
            "keywords": list(keywords),
            "creator_sec_uids": list(self.creator_sec_uids),
        }

        if "search" in self.sources:
            search_source_strategy = str(
                getattr(self.client, "search_source_strategy", "dy-direct-search")
                or "dy-direct-search"
            )
            for keyword in keywords:
                keyword_id = self.seed_keyword_ids.get(keyword) if self.seed_keyword_ids else None
                for item in await self.client.search_aweme(
                    keyword,
                    limit=min(self.per_source_limit, max(1, limit)),
                ):
                    raw_items.append((search_source_strategy, item, keyword_id))

        if "hot" in self.sources:
            hot_limit = min(self.per_source_limit, max(1, limit))
            hot_source_strategy = str(
                getattr(self.client, "hot_source_strategy", "dy-direct-hot") or "dy-direct-hot"
            )
            for item in await self.client.get_hot_board(limit=hot_limit):
                raw_items.append((hot_source_strategy, item, None))

        if "feed" in self.sources:
            feed_limit = min(self.per_source_limit, max(1, limit))
            feed_source_strategy = str(
                getattr(self.client, "feed_source_strategy", "dy-direct-feed") or "dy-direct-feed"
            )
            for item in await self.client.get_recommend_feed(limit=feed_limit):
                raw_items.append((feed_source_strategy, item, None))

        if "creator" in self.sources:
            for sec_uid in self.creator_sec_uids:
                for item in await self.client.get_creator_posts(
                    sec_uid,
                    limit=min(self.per_source_limit, max(1, limit)),
                ):
                    raw_items.append(("dy-direct-creator", item, None))

        candidates = self._normalize_and_dedupe(raw_items)
        if not candidates:
            return []

        if (
            not self.llm_evaluation
            or discovery_raw_candidate_mode_enabled()
            or self.llm_service is None
        ):
            return candidates[:limit]

        evaluator = ContentDiscoveryEngine(
            llm_service=self.llm_service,
            database=self.database,
            concurrency=self.concurrency,
        )
        eval_candidates = trim_candidates_for_llm(
            candidates,
            limit=limit,
            source_context=self.name,
        )
        scores = await evaluator.evaluate_content_batch(eval_candidates, profile)
        results: list[DiscoveredContent] = []
        for content, score in zip(eval_candidates, scores, strict=True):
            if score < self.score_threshold:
                continue
            results.append(content)
            if len(results) >= limit:
                break
        return results

    async def _keywords(self, profile: SoulProfile) -> list[str]:
        # 显式 recipe 关键词优先 — 无需合成。
        seeds = self._dedupe_cap([str(k).strip() for k in self.seed_keywords])
        if seeds:
            return seeds
        # LLM 关键词生成,与 B站 / 小红书 / X 对齐: 喂给相同的
        # build_profile_summary dict,改写成抖音原生搜索词。
        llm_keywords = await self._generate_keywords_llm(profile)
        if llm_keywords:
            return llm_keywords
        # 回退 (未注入 llm_service / 调用失败 / 空): 原始 interest
        # 名 — 最初的确定性行为,使 Douyin 在没有 LLM 注入时仍能
        # 持续发现。
        return self._dedupe_cap([str(i.name).strip() for i in profile.preferences.interests])

    def _dedupe_cap(self, candidates: list[str]) -> list[str]:
        seen: set[str] = set()
        deduped: list[str] = []
        for keyword in candidates:
            if not keyword or keyword in seen:
                continue
            seen.add(keyword)
            deduped.append(keyword)
            if len(deduped) >= self.keywords_per_run:
                break
        return deduped

    async def _generate_keywords_llm(self, profile: SoulProfile) -> list[str]:
        if self.llm_service is None or not profile.preferences.interests:
            return []
        try:
            complete_structured = self.llm_service.complete_structured_task
            response = await complete_structured(
                system_instruction=_DOUYIN_KEYWORDS_SYSTEM_PROMPT,
                user_input=_build_douyin_keyword_user_prompt(profile, self.keywords_per_run),
                temperature=0.8,
                max_tokens=512,
                caller="discovery.douyin.keyword_gen",
                **without_core_memory_kwargs(complete_structured),
            )
        except Exception as exc:  # noqa: BLE001 - 降级到确定性回退
            logger.warning("douyin keyword LLM call failed: %s", exc)
            return []
        content = getattr(response, "content", response)
        return _parse_douyin_keywords(str(content).strip(), count=self.keywords_per_run)

    @staticmethod
    def _normalize_and_dedupe(
        raw_items: list[tuple[str, dict[str, object], int | None]],
    ) -> list[DiscoveredContent]:
        seen: set[str] = set()
        normalized: list[DiscoveredContent] = []
        for source_strategy, item, source_keyword_id in raw_items:
            content = normalize_aweme_item(item, source_strategy=source_strategy)
            if content is None:
                continue
            key = content.content_id or content.bvid
            if key in seen:
                continue
            # P1.8 yield provenance — search item 携带产出关键词的
            # id; hot/feed/creator 传 None (无归因)。
            if source_keyword_id is not None:
                content.source_keyword_id = source_keyword_id
            seen.add(key)
            normalized.append(content)
        return normalized
