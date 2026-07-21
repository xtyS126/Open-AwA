"""基于搜索的内容发现策略。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING

from openbiliclaw.discovery.engine import (
    ContentDiscoveryEngine,
    DiscoveredContent,
    DiscoveryConcurrencyController,
    DiscoveryStrategy,
    SupportsStructuredTask,
    discovery_raw_candidate_mode_enabled,
    trim_candidates_for_llm,
)
from openbiliclaw.discovery.keyword_digest import profile_kw_digest
from openbiliclaw.discovery.strategies._utils import (
    SupportsSearchClient,
    build_query_generation_profile_summary,
    cached_embedding_lookup,
    clean_text,
    interest_anchors,
    normalize_match_text,
    parse_duration,
    search_cooldown_remaining,
    to_int,
)
from openbiliclaw.llm.prompts import build_search_queries_prompt
from openbiliclaw.llm.task_options import without_core_memory_kwargs

if TYPE_CHECKING:
    from openbiliclaw.llm.embedding import SupportsEmbeddingService
    from openbiliclaw.soul.profile import SoulProfile
    from openbiliclaw.storage.database import Database

logger = logging.getLogger(__name__)


@dataclass
class SearchStrategy(DiscoveryStrategy):
    """通过从用户 interest 生成搜索 query 来发现内容。"""

    llm_service: SupportsStructuredTask
    bilibili_client: SupportsSearchClient
    concurrency: DiscoveryConcurrencyController | None = None
    database: Database | None = None
    embedding_service: SupportsEmbeddingService | None = None
    queries_per_run: int = 8
    page_size: int = 10
    max_pages: int = 1
    llm_evaluation: bool = True
    score_threshold: float = 0.60
    last_intermediates: dict[str, object] = field(default_factory=dict)
    query_cache_ttl_seconds: float = 6 * 60 * 60
    _query_cache: dict[str, tuple[float, list[str]]] = field(
        default_factory=dict,
        init=False,
        repr=False,
    )

    @property
    def name(self) -> str:
        return "search"

    async def discover(
        self,
        profile: SoulProfile,
        limit: int = 20,
        *,
        pool_snapshot: object | None = None,
        queries: list[str] | None = None,
        keyword_ids: dict[str, int] | None = None,
    ) -> list[DiscoveredContent]:
        """基于用户 soul 生成搜索 query 并执行它们。

        策略:
        1. 从 soul profile 提取关键 interest
        2. 生成有创意的搜索关键词组合
        3. 通过 Bilibili API 执行搜索
        4. 对照 soul profile 对结果评分

        Args:
            profile: 用户 soul profile。
            limit: 最大结果数。
            pool_snapshot: 可选的当前池分布摘要。
            queries: 可选的调用方提供的搜索 query。当提供 (非 None) 时,
                它们会被原样使用,并跳过内部 LLM query 生成调用
                (统一关键词 planner 注入点)。为 ``None`` 时行为不变。
            keyword_ids: 可选的 ``query → discovery_keywords.id`` 映射
                (P1.8 yield provenance)。提供时,每个产出的候选会被
                盖上产出它的 query 的 id,使 admission 能把来源关键词
                记账。``None`` → 不盖章。

        Returns:
            发现的内容列表。
        """
        cooldown_remaining = search_cooldown_remaining(self.bilibili_client)
        if cooldown_remaining > 0:
            self.last_intermediates = {
                "queries": [],
                "skipped": "search_cooldown",
                "cooldown_remaining_seconds": int(cooldown_remaining),
            }
            logger.info(
                "Search: Bilibili search cooldown active (%.0fs left); skipping query generation",
                cooldown_remaining,
            )
            return []

        if queries is None:
            resolved_queries = await self._generate_queries(profile, pool_snapshot=pool_snapshot)
        else:
            resolved_queries = self._dedupe_queries(queries)
        queries = resolved_queries
        self.last_intermediates = {"queries": list(queries)}
        anchor_list = interest_anchors(profile)
        candidates: list[DiscoveredContent] = []
        candidates_by_query: dict[int, list[DiscoveredContent]] = {}
        seen_bvids: set[str] = set()
        # 遵守 per-strategy search 预算,避免耗尽 IP 级别配额。
        effective_queries = queries
        if self.concurrency is not None:
            budget = self.concurrency.search_budget_per_strategy
            max_queries = budget // max(1, self.max_pages)
            if len(effective_queries) > max_queries:
                logger.debug(
                    "Search: trimming queries from %d to %d (search budget)",
                    len(effective_queries),
                    max_queries,
                )
                effective_queries = effective_queries[:max_queries]

        request_plan = [
            (query_index, query, page)
            for query_index, query in enumerate(effective_queries)
            for page in range(1, self.max_pages + 1)
        ]
        # 使用专用 API client 进行搜索,以避免 B站 session 级别的限流。
        # 共享 client 累积了其他策略 (trending、related_chain、explore)
        # 的请求历史,这会在 search 端点触发 v_voucher 挑战。
        search_client = self._create_search_client()
        try:
            gathered = await self._execute_search_queries(
                search_client,
                request_plan,
            )
        finally:
            if search_client is not self.bilibili_client:
                close = getattr(search_client, "close", None)
                if callable(close):
                    await close()

        api_result_count = 0
        for (query_index, query, page), outcome in zip(request_plan, gathered, strict=True):
            if isinstance(outcome, BaseException):
                logger.error(
                    "Search query failed: %s",
                    query,
                    exc_info=outcome,
                    extra={
                        "strategy": "search",
                        "query": query,
                        "page": page,
                        "error_type": type(outcome).__name__,
                    },
                )
                continue
            if not isinstance(outcome, list):
                logger.warning(
                    "Search query '%s' returned non-list: %s",
                    query,
                    type(outcome).__name__,
                )
                continue
            api_result_count += len(outcome)
            search_results = outcome
            for item_index, item in enumerate(search_results):
                content = self._map_search_result(
                    item,
                    query=query,
                    query_index=query_index,
                    item_index=item_index + (page - 1) * self.page_size,
                    interest_anchors=anchor_list,
                )
                if content is None or content.bvid in seen_bvids:
                    continue
                # P1.8 yield provenance: 盖上产出 query 的 keyword id
                # (统一 planner 注入)。未映射 / 未注入时为 no-op。
                if keyword_ids:
                    content.source_keyword_id = keyword_ids.get(query)
                seen_bvids.add(content.bvid)
                candidates.append(content)
                candidates_by_query.setdefault(query_index, []).append(content)

        logger.info(
            "Search: %d queries, %d API results, %d unique candidates",
            len(queries),
            api_result_count,
            len(candidates),
        )

        if not self.llm_evaluation or discovery_raw_candidate_mode_enabled():
            return candidates[:limit]

        evaluator = ContentDiscoveryEngine(
            llm_service=self.llm_service,
            database=self.database,
            concurrency=self.concurrency,
        )
        eval_candidates = self._interleave_query_candidates(candidates_by_query)
        eval_candidates = trim_candidates_for_llm(
            eval_candidates,
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

        if not results and candidates:
            score_vals = sorted(scores, reverse=True)
            logger.warning(
                "Search: %d candidates all below threshold %.2f. Top-5 scores: %s",
                len(candidates),
                self.score_threshold,
                score_vals[:5],
            )
        return results

    @staticmethod
    def _interleave_query_candidates(
        candidates_by_query: dict[int, list[DiscoveredContent]],
    ) -> list[DiscoveredContent]:
        """轮询候选,使小的 LLM 窗口仍能覆盖每个 query。"""
        ordered_query_indices = sorted(candidates_by_query)
        max_depth = max(
            (len(candidates_by_query[index]) for index in ordered_query_indices),
            default=0,
        )
        interleaved: list[DiscoveredContent] = []
        for depth in range(max_depth):
            for index in ordered_query_indices:
                bucket = candidates_by_query[index]
                if depth < len(bucket):
                    interleaved.append(bucket[depth])
        return interleaved

    def create_backfill_strategy(self) -> DiscoveryStrategy | None:
        return replace(
            self,
            queries_per_run=min(max(self.queries_per_run + 4, self.queries_per_run), 12),
            page_size=min(max(self.page_size, 12), 20),
            max_pages=max(self.max_pages, 2),
            score_threshold=max(0.60, round(self.score_threshold - 0.07, 2)),
            last_intermediates={},
        )

    def _create_search_client(self) -> SupportsSearchClient:
        """创建一个全新的 API client 用于搜索,同时保留 auth。

        B站按 session 对 search 限流。其他策略 (尤其是 explore) 会
        耗尽共享 client 的 search 配额,所以我们用专用 client。Search
        目前对匿名 WBI 请求返回 ``v_voucher``,所以专用 client 必须
        在存在时携带运行时 cookie。创建失败或 bilibili_client 不是
        真实 API client (例如在测试中) 时回退到共享 client。
        """
        from openbiliclaw.bilibili.api import BilibiliAPIClient

        if not isinstance(self.bilibili_client, BilibiliAPIClient):
            return self.bilibili_client
        try:
            return BilibiliAPIClient(
                cookie=str(getattr(self.bilibili_client, "_cookie", "")),
                min_request_interval=0.8,
            )
        except Exception:
            logger.debug("Could not create dedicated search client, using shared")
        return self.bilibili_client

    async def _execute_search_queries(
        self,
        client: SupportsSearchClient,
        request_plan: list[tuple[int, str, int]],
    ) -> list[object]:
        """顺序执行搜索 query,带延迟 + storm backoff。

        v0.3.61+: per-query 延迟现在在 0.5–1.0s 之间 jitter 随机化,
        以避免同步的 WBI 请求波次落入同一个 Bilibili rate-limit 桶。
        ``client.search`` 内部已经重试 v_voucher 挑战 3 次,所以这层
        返回空列表意味着该关键词耗尽了重试且 IP 正在被挑战。连续三次
        空结果 = "storm mode" — 我们中止计划的剩余部分,而不是把
        LLM 生成的 query 烧在当前正被拒绝的 IP 上。剩余 query 用空
        结果填充,使策略仍能优雅地返回它已有的内容,而下一个刷新 tick
        (60s 后) 获得新的尝试机会。
        """
        import random

        storm_trigger = 3
        gathered: list[object] = []
        consecutive_empty = 0
        storm_aborted = False
        for i, (_, query, page) in enumerate(request_plan):
            if storm_aborted:
                gathered.append([])
                continue
            cooldown_remaining = search_cooldown_remaining(client)
            if cooldown_remaining > 0:
                logger.info(
                    "Search: Bilibili search cooldown active (%.0fs left); "
                    "skipping remaining %d query(ies)",
                    cooldown_remaining,
                    len(request_plan) - i,
                )
                gathered.extend([] for _ in range(len(request_plan) - i))
                break
            if i > 0:
                # Jitter 0.5–1.0s。稳态成本: ~0.75s/query;
                # storm 期间: backoff 已在 client.search 内部发生,
                # 所以这纯粹是 query 之间的去同步。
                await asyncio.sleep(0.5 + random.uniform(0.0, 0.5))
            try:
                result = await client.search(
                    query,
                    page=page,
                    page_size=self.page_size,
                )
            except Exception as exc:
                gathered.append(exc)
                # exception 路径不算 v_voucher storm 证据
                # (可能是 412、网络抖动等);重置。
                consecutive_empty = 0
                continue
            gathered.append(result)
            # Storm 检测: 重试已耗尽后的空结果 = IP 正在被限流 *现在*。
            # 烧剩余 query 只会加深坑。
            if isinstance(result, list) and not result:
                cooldown_remaining = search_cooldown_remaining(client)
                if cooldown_remaining > 0:
                    logger.warning(
                        "v_voucher search cooldown detected (%.0fs left) — "
                        "aborting remaining %d query(ies) this round",
                        cooldown_remaining,
                        len(request_plan) - (i + 1),
                    )
                    storm_aborted = True
                    continue
                consecutive_empty += 1
                if consecutive_empty >= storm_trigger:
                    logger.warning(
                        "v_voucher storm detected (%d consecutive empty queries)"
                        " — aborting remaining %d query(ies) this round; "
                        "next refresh tick (60s) gets a fresh attempt",
                        consecutive_empty,
                        len(request_plan) - (i + 1),
                    )
                    storm_aborted = True
            else:
                consecutive_empty = 0
        return gathered

    async def _generate_queries(
        self,
        profile: SoulProfile,
        *,
        pool_snapshot: object | None = None,
    ) -> list[str]:
        pool_hints: dict[str, object] | None = None
        to_prompt_hints = getattr(pool_snapshot, "to_prompt_hints", None)
        if callable(to_prompt_hints):
            try:
                raw_hints = to_prompt_hints()
            except Exception:
                logger.warning(
                    "Search query generation: ignoring invalid pool snapshot hints",
                    exc_info=True,
                )
            else:
                if isinstance(raw_hints, dict):
                    pool_hints = raw_hints
                else:
                    logger.warning(
                        "Search query generation: ignoring non-dict pool snapshot hints: %s",
                        type(raw_hints).__name__,
                    )

        cache_key = self._query_cache_key(profile, pool_hints)
        if cache_key is not None:
            cached = self._cached_queries(cache_key)
            if cached is not None:
                return cached

        try:
            try:
                prompt_messages = build_search_queries_prompt(
                    profile_summary=self._query_profile_summary(profile),
                    pool_hints=pool_hints,
                )
            except (TypeError, ValueError) as exc:
                if pool_hints is None:
                    raise
                logger.warning(
                    "Search query generation: dropping unserializable pool hints: %s",
                    exc,
                )
                prompt_messages = build_search_queries_prompt(
                    profile_summary=self._query_profile_summary(profile),
                    pool_hints=None,
                )
            complete_structured = self.llm_service.complete_structured_task
            response = await complete_structured(
                system_instruction=prompt_messages[0]["content"],
                user_input=prompt_messages[1]["content"],
                max_tokens=1024,
                caller="discovery.search.queries",
                reasoning_effort="",
                **without_core_memory_kwargs(complete_structured),
            )
            queries = self._parse_queries(str(getattr(response, "content", "")))
            if queries:
                if cache_key is not None:
                    self._store_queries(cache_key, queries)
                return queries
        except Exception:
            logger.exception("Search query generation failed; falling back to local queries.")
        return self._fallback_queries(profile)

    def _query_cache_key(
        self,
        profile: SoulProfile,
        pool_hints: dict[str, object] | None,
    ) -> str | None:
        try:
            hints_blob = json.dumps(
                pool_hints or {},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        except TypeError:
            return None
        hints_digest = hashlib.sha256(hints_blob.encode("utf-8")).hexdigest()[:12]
        return f"{profile_kw_digest(profile)}:{hints_digest}"

    def _cached_queries(self, cache_key: str) -> list[str] | None:
        cached = self._query_cache.get(cache_key)
        if cached is None:
            return None
        expires_at, queries = cached
        if time.monotonic() >= expires_at:
            self._query_cache.pop(cache_key, None)
            return None
        return list(queries)

    def _store_queries(self, cache_key: str, queries: list[str]) -> None:
        ttl = max(0.0, float(self.query_cache_ttl_seconds))
        if ttl <= 0:
            return
        self._query_cache[cache_key] = (time.monotonic() + ttl, list(queries))

    @staticmethod
    def _dedupe_queries(queries: list[str]) -> list[str]:
        """strip + 去重调用方注入的 query (无 per-run cap)。"""
        deduped: list[str] = []
        seen: set[str] = set()
        for item in queries:
            query = str(item).strip()
            if not query or query in seen:
                continue
            seen.add(query)
            deduped.append(query)
        return deduped

    def _parse_queries(self, content: str) -> list[str]:
        text = content.strip()
        if not text:
            return []
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            return []
        raw_queries = parsed.get("queries", [])
        if not isinstance(raw_queries, list):
            return []
        queries: list[str] = []
        seen: set[str] = set()
        for item in raw_queries:
            query = str(item).strip()
            if not query or query in seen:
                continue
            seen.add(query)
            queries.append(query)
            if len(queries) >= min(self.queries_per_run, 10):
                break
        return queries

    def _fallback_queries(self, profile: SoulProfile) -> list[str]:
        queries: list[str] = []
        seen: set[str] = set()

        for interest_item in profile.preferences.interests:
            query = str(interest_item.name).strip()
            if not query or query in seen:
                continue
            seen.add(query)
            queries.append(query)
            if len(queries) >= min(self.queries_per_run, 5):
                return queries

        for trait in profile.core_traits:
            query = str(trait).strip()
            if not query or query in seen:
                continue
            seen.add(query)
            queries.append(query)
            if len(queries) >= min(self.queries_per_run, 5):
                break

        return queries

    # ------------------------------------------------------------------
    # 委托静态 helper — 保持向后兼容的 class API
    # ------------------------------------------------------------------

    @staticmethod
    def _profile_summary(profile: SoulProfile) -> dict[str, object]:
        return build_query_generation_profile_summary(profile)

    def _query_profile_summary(self, profile: SoulProfile) -> dict[str, object]:
        return build_query_generation_profile_summary(
            profile,
            embedding_lookup=cached_embedding_lookup(self.embedding_service),
        )

    @staticmethod
    def _interest_anchors(profile: SoulProfile) -> list[tuple[str, float]]:
        return interest_anchors(profile)

    @staticmethod
    def _interest_aliases(name: str) -> set[str]:
        from openbiliclaw.discovery.strategies._utils import interest_aliases

        return interest_aliases(name)

    @staticmethod
    def _clean_text(value: str) -> str:
        return clean_text(value)

    @staticmethod
    def _to_int(raw_value: object) -> int:
        return to_int(raw_value)

    @staticmethod
    def _parse_duration(raw_value: object) -> int:
        return parse_duration(raw_value)

    @staticmethod
    def _normalize_match_text(value: str) -> str:
        return normalize_match_text(value)

    # ------------------------------------------------------------------
    # 实例 helper
    # ------------------------------------------------------------------

    def _map_search_result(
        self,
        item: dict[str, object],
        *,
        query: str,
        query_index: int,
        item_index: int,
        interest_anchors: list[tuple[str, float]],
    ) -> DiscoveredContent | None:
        bvid = str(item.get("bvid", "")).strip()
        if not bvid:
            return None
        title = clean_text(str(item.get("title", "")))
        description = clean_text(str(item.get("description", "")))
        # 预过滤分数: 仅 interest anchor bonus (LLM eval 后续会覆盖)
        anchor_bonus = self._interest_anchor_bonus(
            query=query,
            title=title,
            description=description,
            interest_anchors=interest_anchors,
        )
        pre_score = round(0.1 + anchor_bonus, 4)
        return DiscoveredContent(
            bvid=bvid,
            title=title,
            up_name=clean_text(str(item.get("author", ""))),
            up_mid=to_int(item.get("mid", 0)),
            cover_url=str(item.get("pic", "")),
            duration=parse_duration(item.get("duration", 0)),
            view_count=to_int(item.get("play", 0)),
            like_count=to_int(item.get("like", 0)),
            favorite_count=to_int(item.get("favorites", item.get("favorite", 0))),
            danmaku_count=to_int(item.get("video_review", item.get("danmaku", 0))),
            comment_count=to_int(item.get("review", item.get("reply", 0))),
            share_count=to_int(item.get("share", 0)),
            topic_key=self._topic_key_from_query(query),
            topic_group=self._topic_group_from_query(query),
            description=description,
            style_key=ContentDiscoveryEngine.infer_style_key(
                title=title,
                description=description,
                source_strategy=self.name,
            ),
            source_strategy=self.name,
            relevance_score=min(1.0, pre_score),
        )

    @staticmethod
    def _interest_anchor_bonus(
        *,
        query: str,
        title: str,
        description: str,
        interest_anchors: list[tuple[str, float]],
    ) -> float:
        query_text = normalize_match_text(query)
        title_text = normalize_match_text(title)
        description_text = normalize_match_text(description)
        best_bonus = 0.0
        for anchor, weight in interest_anchors:
            if not anchor:
                continue
            bonus = 0.0
            if anchor in query_text:
                bonus += 0.18 + max(0.0, weight - 0.6) * 0.35
            if anchor in title_text:
                bonus += 0.08
            if anchor in description_text:
                bonus += 0.05
            best_bonus = max(best_bonus, bonus)
        return min(0.42, round(best_bonus, 4))

    @staticmethod
    def _topic_key_from_query(query: str) -> str:
        return re.sub(r"\s+", "", query).strip().lower()

    @staticmethod
    def _topic_group_from_query(query: str) -> str:
        """从搜索 query 提取核心 topic 词。

        "强化学习 游戏ai 决策模型" → "强化学习"
        "纪录片 原理" → "纪录片"
        """
        parts = query.strip().split()
        if parts:
            return re.sub(r"\s+", "", parts[0]).lower()[:8]
        return ""
