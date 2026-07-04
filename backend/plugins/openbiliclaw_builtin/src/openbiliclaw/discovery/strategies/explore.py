"""跨域探索发现策略。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Protocol, cast

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
    interest_aliases,
    interest_anchors,
    search_cooldown_remaining,
)
from openbiliclaw.discovery.strategies.search import SearchStrategy
from openbiliclaw.llm.prompts import build_explore_domains_prompt
from openbiliclaw.llm.task_options import without_core_memory_kwargs

if TYPE_CHECKING:
    from openbiliclaw.llm.embedding import SupportsEmbeddingService
    from openbiliclaw.soul.profile import SoulProfile
    from openbiliclaw.storage.database import Database


# 最小契约 — explore 只需要 topic-group-coverage 查询
# 且不应依赖完整 Database 表面 (保持单元测试轻量、
# 使注入简单)。
class _SupportsTopicCoverage(Protocol):
    """策略从 Database-like 对象所需的最小协议。"""

    def get_active_pool_topic_groups(self, *, limit: int = 30, min_count: int = 2) -> list[str]: ...


logger = logging.getLogger(__name__)


@dataclass
class ExploreStrategy(DiscoveryStrategy):
    """跨域惊喜发现 — 找到意想不到的内容。"""

    llm_service: SupportsStructuredTask
    bilibili_client: SupportsSearchClient
    concurrency: DiscoveryConcurrencyController | None = None
    embedding_service: SupportsEmbeddingService | None = None
    # v0.3.31+: 可选的 database handle,使策略能查询
    # active pool 里哪些 topic_groups 已饱和。
    # LLM domain 生成器避免重新提议这些,这是
    # "explore 返回 30 个 item / 8 个 distinct
    # topic_groups" 病理的主要修复 — 大部分塌缩来自
    # 生成器建议的 domain 在 eval LLM 标注时映射到了
    # 已覆盖的 topic_groups。
    database: _SupportsTopicCoverage | None = None
    # Explore 可以略低于正常 0.60 的准入门槛,因为
    # 其目的是受控的新奇,但不能成为常规推荐池准入的
    # 宽松低分绕过通道。
    score_threshold: float = 0.58
    llm_evaluation: bool = True
    queries_per_domain: int = 3
    max_domains: int = 5
    last_intermediates: dict[str, object] = field(default_factory=dict)
    domain_cache_ttl_seconds: float = 6 * 60 * 60
    _domain_cache: dict[str, tuple[float, list[dict[str, object]]]] = field(
        default_factory=dict,
        init=False,
        repr=False,
    )

    @property
    def name(self) -> str:
        return "explore"

    def create_backfill_strategy(self) -> DiscoveryStrategy | None:
        if self.score_threshold <= 0.55:
            return None
        return replace(
            self,
            score_threshold=max(0.55, round(self.score_threshold - 0.03, 2)),
            queries_per_domain=max(self.queries_per_domain, 3),
            max_domains=max(self.max_domains, 6),
            last_intermediates={},
        )

    async def discover(self, profile: SoulProfile, limit: int = 20) -> list[DiscoveredContent]:
        """刻意探索用户尚未尝试的领域。

        使用 soul profile 的 deep needs 和 latent interests
        来假设哪些新领域可能产生共鸣。

        Args:
            profile: 用户 soul profile。
            limit: 最大结果数。

        Returns:
            发现的内容列表。
        """
        cooldown_remaining = search_cooldown_remaining(self.bilibili_client)
        if cooldown_remaining > 0:
            self.last_intermediates = {
                "domains": [],
                "skipped": "search_cooldown",
                "cooldown_remaining_seconds": int(cooldown_remaining),
            }
            logger.info(
                "Explore: Bilibili search cooldown active (%.0fs left); skipping domain generation",
                cooldown_remaining,
            )
            return []

        domains = await self._generate_domains(profile)
        self.last_intermediates = {"domains": list(domains)}
        if not domains:
            return []

        evaluator = ContentDiscoveryEngine(
            llm_service=self.llm_service,
            database=cast("Database | None", self.database),
            concurrency=self.concurrency,
        )
        search_strategy = SearchStrategy(
            llm_service=self.llm_service,
            bilibili_client=self.bilibili_client,
            concurrency=self.concurrency,
        )
        anchor_list = interest_anchors(profile)
        request_plan: list[tuple[str, float, bool, str]] = []
        for domain in domains:
            novelty_level = self._clamp_novelty(domain.get("novelty_level", 0.5))
            interest_anchored = bool(domain.get("interest_anchored", False))
            domain_name = str(domain.get("domain", "")).strip()
            for query in self._clean_queries(domain.get("queries", [])):
                request_plan.append((query, novelty_level, interest_anchored, domain_name))

        # 遵守单策略搜索预算,避免耗尽 IP 级配额。
        if self.concurrency is not None:
            budget = self.concurrency.search_budget_per_strategy
            if len(request_plan) > budget:
                logger.debug(
                    "Explore: trimming request_plan from %d to %d (search budget)",
                    len(request_plan),
                    budget,
                )
                request_plan = request_plan[:budget]

        # 使用专用无 cookie client 并按顺序带延迟执行,
        # 避免触发 IP 级 v_voucher 限流。
        search_client = self._create_search_client()
        try:
            search_outcomes = await self._execute_search_sequential(
                search_client,
                request_plan,
            )
        finally:
            if search_client is not self.bilibili_client:
                close = getattr(search_client, "close", None)
                if callable(close):
                    await close()

        # 按 domain_label 分桶,使下游 eval 硬上限
        # (30) 不会饿死后面的 domain: 没有分桶,前 1-2 个
        # domain 的 query 结果就会吞掉整个 eval 窗口。
        domain_order: list[str] = []
        per_domain: dict[str, list[tuple[DiscoveredContent, float, bool]]] = {}
        seen_bvids: set[str] = set()
        for (query, novelty_level, interest_anchored, domain_label), outcome in zip(
            request_plan, search_outcomes, strict=True
        ):
            if isinstance(outcome, BaseException):
                logger.error(
                    "Explore query failed: %s",
                    query,
                    exc_info=outcome,
                    extra={
                        "strategy": "explore",
                        "query": query,
                        "novelty_level": novelty_level,
                        "error_type": type(outcome).__name__,
                    },
                )
                continue
            if not isinstance(outcome, list):
                continue
            bucket_key = domain_label or query
            if bucket_key not in per_domain:
                per_domain[bucket_key] = []
                domain_order.append(bucket_key)
            for item_index, item in enumerate(outcome):
                content = search_strategy._map_search_result(
                    item,
                    query=query,
                    query_index=0,
                    item_index=item_index,
                    interest_anchors=anchor_list,
                )
                if content is None or content.bvid in seen_bvids:
                    continue
                seen_bvids.add(content.bvid)
                content.source_strategy = self.name
                if domain_label:
                    normalized_domain = re.sub(r"\s+", "", domain_label).lower()[:16]
                    content.topic_group = normalized_domain
                    # 使用 domain 级粒度作为 topic_key,使来自
                    # 同一探索 domain 的内容正确分组
                    content.topic_key = normalized_domain
                per_domain[bucket_key].append((content, novelty_level, interest_anchored))

        # 跨 domain 轮询交错,使每个 domain 在 30-item
        # eval 窗口里有公平的代表权。
        candidates: list[tuple[DiscoveredContent, float, bool]] = []
        max_depth = max((len(per_domain[k]) for k in domain_order), default=0)
        for depth in range(max_depth):
            for key in domain_order:
                bucket = per_domain[key]
                if depth < len(bucket):
                    candidates.append(bucket[depth])
        candidates = trim_candidates_for_llm(
            candidates,
            limit=limit,
            source_context=self.name,
        )
        if not self.llm_evaluation or discovery_raw_candidate_mode_enabled():
            return [content for content, _, _ in candidates[:limit]]

        scores = await evaluator.evaluate_content_batch(
            [content for content, _, _ in candidates],
            profile,
        )
        results: list[DiscoveredContent] = []
        for (
            content,
            novelty_level,
            _interest_anchored,
        ), score in zip(candidates, scores, strict=True):
            bonus = self._exploration_bonus(
                novelty_level=novelty_level,
                openness=profile.preferences.exploration_openness,
            )
            # Explore 使用比之前更温和的混合公式:
            # - 原始 LLM 分数权重 0.60 (之前是 0.75),为 bonus 留出空间
            # - bonus 权重 0.40 (之前是 0.25),让 novelty/openness 更重要
            # - 无 distance_penalty: 非 anchored 才是 explore 的目的
            content.relevance_score = max(
                0.0,
                min(1.0, round(score * 0.60 + bonus * 0.40, 4)),
            )
            # Explore 可以用略低的策略门槛,但不是
            # 旧的 0.25 折扣 (那会放行普通低分内容)。
            explore_threshold = max(0.55, min(1.0, self.score_threshold))
            if content.relevance_score < explore_threshold:
                continue
            results.append(content)
            if len(results) >= limit:
                return self._sort_results(results)

        return self._sort_results(results)

    def _create_search_client(self) -> SupportsSearchClient:
        """为 explore 搜索创建无 cookie 的 API client。

        避免与其他策略共享 authenticated client 的 session/cookie,
        否则会导致 IP 级 v_voucher 限流。
        对非 API client (例如测试中) 回退到共享 client。
        """
        from openbiliclaw.bilibili.api import BilibiliAPIClient

        if not isinstance(self.bilibili_client, BilibiliAPIClient):
            return self.bilibili_client
        try:
            return BilibiliAPIClient(cookie="", min_request_interval=0.8)
        except Exception:
            logger.debug("Could not create dedicated explore search client, using shared")
        return self.bilibili_client

    async def _execute_search_sequential(
        self,
        client: SupportsSearchClient,
        request_plan: list[tuple[str, float, bool, str]],
    ) -> list[object]:
        """按顺序带延迟执行搜索 query,避免限流。"""
        results: list[object] = []
        for i, (query, _, _, _) in enumerate(request_plan):
            cooldown_remaining = search_cooldown_remaining(client)
            if cooldown_remaining > 0:
                logger.info(
                    "Explore: Bilibili search cooldown active (%.0fs left); "
                    "skipping remaining %d query(ies)",
                    cooldown_remaining,
                    len(request_plan) - i,
                )
                results.extend([] for _ in range(len(request_plan) - i))
                break
            if i > 0:
                await asyncio.sleep(0.6)
            try:
                result = await client.search(query, page=1, page_size=10)
                results.append(result)
            except Exception as exc:
                results.append(exc)
        return results

    async def _generate_domains(self, profile: SoulProfile) -> list[dict[str, object]]:
        # v0.3.31+: 把已饱和的 topic_groups 喂给 LLM 作为
        # "blind-spot guide",使其不重新提议已覆盖的
        # 区域。任何 DB 错误时软失败为 None;prompt 的
        # 默认分支 (无 covered_topic_groups) 是向后兼容
        # 路径。
        covered_topic_groups: list[str] | None = None
        if self.database is not None:
            try:
                # 与 prompt 端上限匹配 (12) — 从 DB 拉更多
                # 只会被 prompt builder 丢弃。min_count=2
                # 避免把一次性长尾 topic 塞进 avoid 列表。
                covered_topic_groups = self.database.get_active_pool_topic_groups(
                    limit=12,
                    min_count=2,
                )
            except Exception:
                logger.debug(
                    "explore: failed to load covered_topic_groups, falling back",
                    exc_info=True,
                )
        if covered_topic_groups:
            logger.info(
                "explore: feeding %d covered topic_groups to domain generator (top 5: %s)",
                len(covered_topic_groups),
                ", ".join(covered_topic_groups[:5]),
            )

        cache_key = self._domain_cache_key(profile, covered_topic_groups)
        cached = self._cached_domains(cache_key)
        if cached is not None:
            return cached

        messages = build_explore_domains_prompt(
            profile_summary=build_query_generation_profile_summary(
                profile,
                embedding_lookup=cached_embedding_lookup(self.embedding_service),
            )
            | {"exploration_openness": profile.preferences.exploration_openness},
            covered_topic_groups=covered_topic_groups,
        )
        try:
            complete_structured = self.llm_service.complete_structured_task
            response = await complete_structured(
                system_instruction=messages[0]["content"],
                user_input=messages[1]["content"],
                max_tokens=2048,
                caller="discovery.explore.queries",
                reasoning_effort="",
                **without_core_memory_kwargs(complete_structured),
            )
            parsed = json.loads(str(getattr(response, "content", "")).strip())
        except Exception:
            logger.exception("Explore domain generation failed.")
            return []

        if not isinstance(parsed, dict) or not isinstance(parsed.get("domains"), list):
            return []

        current_interests = {
            self._normalize_domain_key(interest_item.name)
            for interest_item in profile.preferences.interests[:10]
            if interest_item.name.strip()
        }
        anchor_set = self._interest_anchor_set(profile)
        domains: list[dict[str, object]] = []
        seen_domains: set[str] = set()
        for item in parsed["domains"]:
            if not isinstance(item, dict):
                continue
            domain = str(item.get("domain", "")).strip()
            normalized = self._normalize_domain_key(domain)
            if not domain or normalized in seen_domains:
                continue
            if await self._looks_too_similar_async(normalized, current_interests):
                continue
            seen_domains.add(normalized)
            domains.append(
                {
                    "domain": domain,
                    "why_it_might_resonate": str(item.get("why_it_might_resonate", "")).strip(),
                    "novelty_level": self._clamp_novelty(item.get("novelty_level", 0.5)),
                    "queries": self._clean_queries(item.get("queries", [])),
                }
            )
            if len(domains) >= self.max_domains:
                break
        prioritized = self._prioritize_domains(domains, anchor_set)
        result = [domain for domain in prioritized if domain["queries"]]
        self._store_domains(cache_key, result)
        return result

    def _domain_cache_key(
        self,
        profile: SoulProfile,
        covered_topic_groups: list[str] | None,
    ) -> str:
        payload = {
            "profile": profile_kw_digest(profile),
            "covered_topic_groups": [str(item) for item in (covered_topic_groups or [])],
            "max_domains": int(self.max_domains),
            "queries_per_domain": int(self.queries_per_domain),
        }
        blob = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]

    def _cached_domains(self, cache_key: str) -> list[dict[str, object]] | None:
        cached = self._domain_cache.get(cache_key)
        if cached is None:
            return None
        expires_at, domains = cached
        if time.monotonic() >= expires_at:
            self._domain_cache.pop(cache_key, None)
            return None
        return [dict(domain) for domain in domains]

    def _store_domains(self, cache_key: str, domains: list[dict[str, object]]) -> None:
        ttl = max(0.0, float(self.domain_cache_ttl_seconds))
        if ttl <= 0:
            return
        self._domain_cache[cache_key] = (
            time.monotonic() + ttl,
            [dict(domain) for domain in domains],
        )

    async def _looks_too_similar_async(self, domain: str, current_interests: set[str]) -> bool:
        """检查 domain 是否与现有兴趣过于相似。

        可用时使用 embedding 余弦相似度,否则回退到子串检查。
        "过于相似"的阈值为 0.75 (比 dedup 的 0.82 更严格 —
        我们希望 explore 是真正的新奇)。
        """
        if not domain:
            return False
        # 快速路径: 精确或近精确字符串匹配
        for interest_val in current_interests:
            if not interest_val:
                continue
            if domain == interest_val:
                return True
            if interest_val in domain and len(domain) - len(interest_val) < 3:
                return True
            if domain in interest_val and len(interest_val) - len(domain) < 3:
                return True

        # 语义检查: 捕获近义词如 "AI应用" vs "人工智能"
        # 阈值 0.85 = 只拒绝非常接近的同义词,不拒绝松散相关的主题
        # (0.75 太严格 — 用户兴趣广泛时拒绝了大部分 domain)
        if self.embedding_service is not None:
            from openbiliclaw.llm.embedding import cosine_similarity

            similarity_reject_threshold = 0.85
            try:
                domain_vec = await self.embedding_service.embed(domain)
                if domain_vec:
                    for interest_val in current_interests:
                        if not interest_val:
                            continue
                        interest_vec = await self.embedding_service.embed(interest_val)
                        if (
                            interest_vec
                            and cosine_similarity(domain_vec, interest_vec)
                            >= similarity_reject_threshold
                        ):
                            logger.debug(
                                "Explore domain rejected (semantic): %r ≈ %r",
                                domain,
                                interest_val,
                            )
                            return True
            except Exception:
                pass  # embedding 失败时落入 False
        return False

    @staticmethod
    def _normalize_domain_key(value: str) -> str:
        return re.sub(r"\s+", "", value).strip().lower()

    def _interest_anchor_set(self, profile: SoulProfile) -> set[str]:
        anchors: set[str] = set()
        for interest_item in profile.preferences.interests[:5]:
            anchors.update(interest_aliases(str(interest_item.name)))
        return {anchor for anchor in anchors if anchor}

    def _prioritize_domains(
        self,
        domains: list[dict[str, object]],
        anchor_set: set[str],
    ) -> list[dict[str, object]]:
        if not domains:
            return []
        anchored: list[dict[str, object]] = []
        loose: list[dict[str, object]] = []
        for domain in domains:
            anchored_domain = self._is_interest_anchored(domain, anchor_set)
            domain["interest_anchored"] = anchored_domain
            if anchored_domain:
                anchored.append(domain)
            else:
                loose.append(domain)

        if not anchored:
            return domains[: self.max_domains]

        # 优先 loose (新奇) domain 以对抗 echo chamber:
        # 可用时至少 3 个 loose domain,与 anchored 交错
        loose_cap = max(3, (self.max_domains + 1) // 2)
        anchored_cap = max(1, self.max_domains - min(loose_cap, len(loose)))
        prioritized = [*loose[:loose_cap], *anchored[:anchored_cap]]
        return prioritized[: self.max_domains]

    def _is_interest_anchored(
        self,
        domain: dict[str, object],
        anchor_set: set[str],
    ) -> bool:
        raw_queries = domain.get("queries", [])
        queries = raw_queries if isinstance(raw_queries, list) else []
        haystacks = [
            self._normalize_domain_key(str(domain.get("domain", ""))),
            self._normalize_domain_key(str(domain.get("why_it_might_resonate", ""))),
            *[
                self._normalize_domain_key(str(query))
                for query in queries
                if isinstance(query, str)
            ],
        ]
        for anchor in anchor_set:
            if anchor and any(anchor in haystack for haystack in haystacks):
                return True
        return False

    def _clean_queries(self, raw_value: object) -> list[str]:
        if not isinstance(raw_value, list):
            return []
        queries: list[str] = []
        seen: set[str] = set()
        for item in raw_value:
            query = str(item).strip()
            lowered = query.lower()
            if not query or lowered in seen:
                continue
            if any(bad in lowered for bad in ("热门", "推荐", "必看")):
                continue
            seen.add(lowered)
            queries.append(query)
            if len(queries) >= self.queries_per_domain:
                break
        return queries

    @staticmethod
    def _clamp_novelty(raw_value: object) -> float:
        value = ContentDiscoveryEngine._clamp_score(raw_value)
        return min(0.8, max(0.4, value))

    @staticmethod
    def _exploration_bonus(*, novelty_level: float, openness: float) -> float:
        return round(novelty_level * max(0.0, min(1.0, openness)), 4)

    @staticmethod
    def _sort_results(results: list[DiscoveredContent]) -> list[DiscoveredContent]:
        results.sort(key=lambda item: item.relevance_score, reverse=True)
        return results
