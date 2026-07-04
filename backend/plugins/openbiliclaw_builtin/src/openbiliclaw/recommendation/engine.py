"""推荐引擎 —— 排序、表达和交付。

处理最后阶段：将发现的内容以温暖、朋友式的方式呈现给用户，
并附带深度的个人洞察。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal, Protocol

from openbiliclaw.discovery.style_keys import VALID_STYLE_KEYS, normalize_style_key
from openbiliclaw.llm.json_utils import extract_llm_json_list, extract_llm_json_object
from openbiliclaw.llm.prompt_cache import PromptLayerRenderCache, profile_prompt_layers
from openbiliclaw.llm.service import is_llm_rate_limit_error
from openbiliclaw.llm.task_options import without_core_memory_kwargs
from openbiliclaw.soul.tone import ToneProfile, build_tone_profile

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    from openbiliclaw.discovery.engine import DiscoveredContent
    from openbiliclaw.llm.base import LLMResponse
    from openbiliclaw.recommendation.curator import PoolCurator
    from openbiliclaw.runtime.task_registry import BackgroundTaskRegistry
    from openbiliclaw.soul.profile import InterestTag, SoulProfile
    from openbiliclaw.storage.database import Database

logger = logging.getLogger(__name__)
_DEFAULT_EXPRESSION_BATCH_SIZE = 30
_DEFAULT_EXPRESSION_BATCH_CONCURRENCY = 2


def _interests_by_weight(profile: SoulProfile) -> list[InterestTag]:
    """按权重降序排序的兴趣标签，这样截断时保留最强的。"""
    return sorted(profile.preferences.interests, key=lambda tag: tag.weight, reverse=True)


def _profile_style_summary(profile: SoulProfile) -> dict[str, object]:
    style = profile.preferences.style
    return {
        "preferred_duration": style.preferred_duration,
        "preferred_pace": style.preferred_pace,
        "humor_preference": style.humor_preference,
        "depth_preference": style.depth_preference,
    }


def _recommendation_profile_summary(
    profile: SoulProfile,
    *,
    interests: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    """推荐 prompt 的统一 profile 输入。

    委托给 :func:`build_profile_summary`，因此推荐向 LLM 喂入与
    discovery 完全相同的结构化 profile：不含 ``personality_portrait``
    叙事，其他字段全部包含。传入 ``interests`` 可用 embedding 选出的、
    与内容相关的 tag 列表替代默认的按权重排序的列表。
    """
    from openbiliclaw.discovery.strategies._utils import build_profile_summary

    return build_profile_summary(profile, interests=interests)


def _content_result_keys(content: DiscoveredContent) -> set[str]:
    """可能在批次 LLM 结果中标识内容项的稳定键。"""
    return {
        key
        for key in {
            str(getattr(content, "bvid", "") or "").strip(),
            str(getattr(content, "content_id", "") or "").strip(),
        }
        if key
    }


def _batch_results_by_content_key(
    payload: list[dict[str, Any]],
    batch: list[DiscoveredContent],
) -> dict[str, dict[str, Any]] | None:
    """当 LLM 提供了 ID 时，返回以 content ID 为键的 payload 条目。

    ``None`` 表示没有可用的 ID，因此调用方仅在响应长度完整时
    才可回退到传统的索引匹配。
    """
    valid_keys: set[str] = set()
    for content in batch:
        valid_keys.update(_content_result_keys(content))

    matched: dict[str, dict[str, Any]] = {}
    saw_identifier = False
    for item in payload:
        raw_key = str(item.get("bvid") or item.get("content_id") or "").strip()
        if not raw_key:
            continue
        saw_identifier = True
        if raw_key not in valid_keys:
            continue
        matched[raw_key] = item

    return matched if saw_identifier else None


class SupportsCoreMemoryTask(Protocol):
    """具备 core memory 感知能力的结构化 LLM 任务执行器协议。"""

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
        inject_core_memory: bool = True,
    ) -> LLMResponse: ...


class SupportsEmbeddingService(Protocol):
    """推荐 helper 使用的 embedding 服务协议。"""

    similarity_threshold: float

    async def embed(self, text: str) -> list[float]: ...


@dataclass
class Recommendation:
    """准备呈现给用户的推荐。"""

    content: DiscoveredContent
    recommendation_id: int = 0
    expression: str = ""  # 朋友式推荐理由
    topic_label: str = ""  # 个人话题（非通用分类）
    confidence: float = 0.0  # agent 对此推荐的信心度
    presented: bool = False
    feedback: str | None = None  # 用户看到后的反馈


@dataclass
class PersonalTopic:
    """深度个性化的推荐话题。

    不是通用标签如"周末放松包"，而是个人化的，例如：
    "你最近在探索摄影——这几个视频从你习惯的'搞明白原理'的角度讲构图"
    """

    title: str = ""
    description: str = ""
    recommendations: list[Recommendation] = field(default_factory=list)


class RecommendationEngine:
    """产出温暖、个性化的推荐。

    引擎将发现的内容转换为朋友式的推荐，附带：
    - "我觉得" —— 主观、个人化的判断
    - "我理解你" —— 展现深度理解
    - 将内容与用户 soul 连接的个人洞察
    """

    def __init__(
        self,
        llm: SupportsCoreMemoryTask,
        database: Database,
        *,
        curator: PoolCurator | None = None,
        embedding_service: SupportsEmbeddingService | None = None,
        task_registry: BackgroundTaskRegistry | None = None,
        xhs_self_info_provider: Callable[[], dict[str, object] | None] | None = None,
        expression_batch_concurrency: int = _DEFAULT_EXPRESSION_BATCH_CONCURRENCY,
    ) -> None:
        self._llm = llm
        self._database = database
        self._curator = curator
        self._embedding_service = embedding_service
        self._xhs_self_info_provider = xhs_self_info_provider
        self._expression_batch_concurrency = max(1, min(16, int(expression_batch_concurrency)))
        # v0.3.63+：可选的注册表，用于分离的 fire-and-forget 任务
        # （classify_pool_backlog_detached、precompute_delight_scores_detached）。
        # 提供时，这些任务注册到这里，以便 RuntimeContext 的热重载
        # 可以在新 runtime 启动前取消它们。
        # 为 None 时，引擎回退到裸 asyncio.create_task ——
        # 未注入注册表的测试继续不受影响地工作。
        self.task_registry: BackgroundTaskRegistry | None = task_registry
        self._classify_lock = asyncio.Lock()
        self._profile_prompt_caches: defaultdict[str, PromptLayerRenderCache] = defaultdict(
            PromptLayerRenderCache
        )
        # v0.3.47+：串行化 precompute_pool_copy，这样多个
        # per-strategy fire-and-forget 任务（现在从
        # _run_refresh_plan 在每个 strategy 完成后创建）不会加载
        # 相同的未预计算候选并重复花费 LLM token。
        #
        # v0.3.62+：将之前的单个 ``_precompute_lock`` 拆分为两个
        # 独立锁。旧的共享锁串行化了 expression 生成和 delight 评分
        # —— 当 delight 评分慢（LLM 退避或大量未评分 backlog）时，
        # 下一个 expression 批次必须在其后等待，即使 expression 完全
        # 不触碰 delight 状态。现在 expression 生成持有
        # ``_expression_lock``，而 delight 评分在由 ``_delight_lock``
        # 守护的分离任务中运行，因此两个流程独立推进，而连续的
        # precompute 调用仍然避免重复花费 delight LLM token。
        self._expression_lock = asyncio.Lock()
        self._delight_lock = asyncio.Lock()
        # 后台计算的 supergroup 规范映射。由 refresh tick 期间的
        # prewarm_supergroup_embeddings() 填充；由 serve() 的
        # _merge_topic_supergroups 消费以进行即时查找。
        # 键/值已规范化（strip+lower）。
        self._supergroup_canonical_map: dict[str, str] = {}
        # v0.3.31+：跟踪上一个服务批次的 bvid，以便 debug-summary
        # 日志可以计算 carryover（新批次中有多少项也在上一个批次中）。
        # 高 carryover 信号表明池陈旧 / 疲劳绕过。
        self._last_served_bvids: frozenset[str] = frozenset()

    def _profile_blocks(
        self,
        profile_summary: dict[str, object],
        *,
        cache_key: str,
    ) -> list[str]:
        """为一个推荐任务渲染缓存的 profile prompt 层。"""

        return self._profile_prompt_caches[cache_key].render_json_layers(
            profile_prompt_layers(profile_summary)
        )

    def _xhs_self_nickname(self) -> str:
        """返回持久化的 XHS self 昵称用于 pool 守卫。"""
        if self._xhs_self_info_provider is None:
            return ""
        try:
            info = self._xhs_self_info_provider() or {}
        except Exception:
            logger.exception("Failed to load xhs self_info for pool guard")
            return ""
        if not isinstance(info, dict):
            return ""
        return str(info.get("nickname", "") or "").strip()

    def _pool_readiness_counts(self) -> dict[str, int]:
        nickname = self._xhs_self_nickname()
        readiness_fn = getattr(self._database, "count_pool_readiness", None)
        if callable(readiness_fn):
            try:
                counts = readiness_fn(xhs_self_nickname=nickname)
                available = int(counts.get("available", 0))
                return {
                    "available": max(0, available),
                    "raw": max(0, int(counts.get("raw", available))),
                    "pending": max(0, int(counts.get("pending", 0))),
                }
            except Exception:
                logger.exception("Failed to load pool readiness counts")
        available = int(self._database.count_pool_candidates(xhs_self_nickname=nickname))
        return {"available": max(0, available), "raw": max(0, available), "pending": 0}

    async def serve(
        self,
        profile: SoulProfile,
        *,
        limit: int = 5,
        excluded_bvids: frozenset[str] = frozenset(),
        expression_mode: Literal["realtime", "precomputed"] = "precomputed",
    ) -> list[Recommendation]:
        """统一推荐入口 —— 始终从池中挑选。

        所有推荐路径（generate、reshuffle、append）在此汇聚。
        引擎与 Discovery 完全解耦：它只从 content_cache 的候选池读取。

        Args:
            profile: 用户 soul profile 用于个性化。
            limit: 最大推荐数。
            excluded_bvids: 已展示给用户的 BVID（用于分页）。
            expression_mode: ``"precomputed"`` 使用池缓存副本（快），
                ``"realtime"`` 通过 LLM 生成新 expression（慢但
                质量更高）。

        Returns:
            个性化推荐列表。
        """
        label = "realtime" if expression_mode == "realtime" else "pool"
        multiplier = 4 if excluded_bvids else 3
        pool_readiness = self._pool_readiness_counts()
        servable_pool_count = pool_readiness["available"]
        raw_pool_count = pool_readiness["raw"]
        pending_pool_count = pool_readiness["pending"]
        if servable_pool_count <= 0:
            logger.info(
                "serve(/%s) skipped: no servable pool candidates (raw=%d pending=%d)",
                label,
                raw_pool_count,
                pending_pool_count,
            )
            self._last_served_bvids = frozenset()
            return []

        candidates = self._load_pool_candidates(limit=max(limit * multiplier, 40))
        loaded_count = len(candidates)
        if excluded_bvids:
            candidates = [c for c in candidates if c.bvid not in excluded_bvids]
        after_exclude_count = len(candidates)
        candidates = self._exclude_disliked_topic_candidates(candidates, profile)
        after_disliked_count = len(candidates)
        if after_disliked_count < after_exclude_count:
            logger.info(
                "serve(/%s) filtered %d candidate(s) by profile disliked_topics",
                label,
                after_exclude_count - after_disliked_count,
            )
        candidates = self._exclude_recently_viewed(candidates)
        after_viewed_count = len(candidates)
        if after_viewed_count == 0:
            logger.warning(
                "serve(/%s) loaded 0 usable candidates from servable=%d "
                "(raw=%d pending=%d) after filters: loaded=%d "
                "after_exclude=%d after_disliked=%d after_viewed=%d. Skipping curator, "
                "MMR embeddings, and recommendation writes.",
                label,
                servable_pool_count,
                raw_pool_count,
                pending_pool_count,
                loaded_count,
                after_exclude_count,
                after_disliked_count,
                after_viewed_count,
            )
            self._last_served_bvids = frozenset()
            return []

        # 在线 supergroup 合并 —— 将本批次中语义等价的 topic_group
        # （如 动漫/动漫产业/动漫文化）折叠，使 diversifier 将它们视为
        # 单个桶。为热路径增加 50-200ms 的 embedding I/O，换取批次级
        # 的丰富度，这是任何离线预计算在 serve 时都无法保证的。
        await self._merge_topic_supergroups(candidates)

        prev_bvids = self._last_served_bvids

        # 暴露"池说 N 但 serve 加载更少"的不匹配，附带足够的 readiness
        # 细节以区分 pending 素材与查询漂移。
        if servable_pool_count != loaded_count:
            logger.info(
                "serve(/%s) pool/load mismatch: count=%d → loaded=%d"
                " → after_exclude=%d → after_disliked=%d → after_viewed=%d "
                "(raw=%d pending=%d)",
                label,
                servable_pool_count,
                loaded_count,
                after_exclude_count,
                after_disliked_count,
                after_viewed_count,
                raw_pool_count,
                pending_pool_count,
            )

        logger.info(
            "Recommendation candidate summary (serve/%s): %s",
            label,
            json.dumps(
                self._build_debug_summary(candidates, prev_bvids=prev_bvids),
                ensure_ascii=False,
            ),
        )

        score_override: dict[str, float] | None = None
        amplification_guard: frozenset[str] = frozenset()
        if self._curator is not None:
            context = self._curator.build_context()
            score_override = self._curator.score_candidates(candidates, context)
            amplification_guard = context.over_budget_amplification_keys

        # v0.3.44+：为基于 MMR 的多样化预取 embedding。
        # v0.3.45+ 的 discovery 和 classify_pool_backlog 会预先将这些
        # 预热到 L2 SQLite 缓存，因此在热路径上这应当接近零。
        # 下面的 elapsed/coverage 日志使缓存预热的回归可见 —— 持续的
        # "elapsed > 500ms" 或 "coverage < 100%" 意味着 warm hook
        # 遗漏了项。
        import time as _time

        _embed_t0 = _time.monotonic()
        embeddings = await self._fetch_candidate_embeddings(candidates)
        _embed_elapsed_ms = (_time.monotonic() - _embed_t0) * 1000.0
        if candidates:
            logger.info(
                "MMR embedding fetch: coverage=%d/%d elapsed=%.0fms",
                len(embeddings),
                len(candidates),
                _embed_elapsed_ms,
            )

        ranked = self._select_diversified_batch(
            candidates,
            limit=limit,
            score_override=score_override,
            embeddings=embeddings,
            amplification_guard=amplification_guard,
        )
        logger.info(
            "Recommendation picked summary (serve/%s): %s",
            label,
            json.dumps(
                self._build_debug_summary(ranked, prev_bvids=prev_bvids),
                ensure_ascii=False,
            ),
        )
        # 为下一次调用做快照。仅用 bvid —— title 可能在不同 bvid 间
        # 合法地重复，我们希望 carryover 信号在 canonical-id 级别。
        self._last_served_bvids = frozenset(item.bvid for item in ranked if item.bvid)

        recommendations: list[Recommendation] = []
        for item in ranked:
            rec = Recommendation(
                content=item,
                confidence=item.relevance_score,
                presented=False,
            )
            if expression_mode == "precomputed":
                rec.expression = item.pool_expression.strip()
                rec.topic_label = item.pool_topic_label.strip()
                # v0.3.57+：pool gate（get_pool_candidates SQL）现在要求
                # pool_expression / pool_topic_label 非空才将一行视为
                # in-pool，因此此回退路径在生产中不应触发。将其保留为
                # 竞争窗口安全网，并在触发时大声日志 —— 警告是金丝雀。
                if not rec.expression:
                    logger.warning(
                        "Pool gate leak: bvid=%s pool_expression empty at "
                        "serve time (expected to be filtered out by "
                        "get_pool_candidates SQL). Falling back to template.",
                        item.bvid,
                    )
                    rec.expression = self._fallback_expression(item)
                if not rec.topic_label:
                    rec.topic_label = self._fallback_topic_label(profile)
            recommendations.append(rec)

        # 关键路径写：仅 insert（我们需要 ID 用于响应）。单事务，单 fsync。
        ids = self._database.batch_insert_recommendations(
            [
                {
                    "bvid": rec.content.bvid,
                    "expression": rec.expression,
                    "topic": rec.topic_label,
                    "confidence": rec.confidence,
                    "presented": 0,
                }
                for rec in recommendations
            ]
        )
        for rec, rec_id in zip(recommendations, ids, strict=True):
            rec.recommendation_id = rec_id

        if expression_mode == "realtime":
            for rec, item in zip(recommendations, ranked, strict=True):
                rec.expression, rec.topic_label = await self.generate_expression(
                    item,
                    profile,
                )
                self._database.update_recommendation_content(
                    rec.recommendation_id,
                    expression=rec.expression,
                    topic=rec.topic_label,
                )

        # v0.3.45+：将 pool_status='shown' 更新从响应关键路径分离。
        # 在 refresh-tick 写竞争下（例如 _enforce_pool_cap 重新激活
        # 300+ 行），此 UPDATE 可能等待 0.5-1.5s 获取 SQLite 写锁，
        # 突破 <1s 预算。会话内双击保护已由
        # `_last_served_bvids`（内存中）提供，因此让持久标志稍后
        # 提交是安全的。
        ranked_bvids = [item.bvid for item in ranked]
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._mark_pool_shown_async(ranked_bvids))
        except RuntimeError:
            # serve() 通常从事件循环调用；只有罕见的 sync-test
            # 路径会落到这里。
            self._database.mark_pool_items_shown(ranked_bvids)
        return recommendations

    async def _mark_pool_shown_async(self, bvids: list[str]) -> None:
        """Fire-and-forget 的池标记 helper。永不抛异常。"""
        try:
            self._database.mark_pool_items_shown(bvids)
        except Exception:
            logger.exception(
                "mark_pool_items_shown (detached) failed for %d bvids",
                len(bvids),
            )

    # 在线 supergroup 合并的混合规则：
    #   - 仅严格 embedding：sim >= 0.90（捕获自走棋↔金铲铲之战
    #     0.902 跨名称边界）。
    #   - 共享 2 字符前缀 + 宽松 embedding：sim >= 0.80（捕获
    #     动漫族 0.80-0.88、游戏族 0.84-0.87 —— 局部性信号保护
    #     防止将 40-group 批次折叠成一个桶的传递桥接）。
    # 对实时池探测：应合并带 0.80-0.92，应分离带在 0.82 附近封顶。
    # 仅 embedding 在 0.83 处通过 union-find 级联；前缀门控宽松带合并。
    _SUPERGROUP_STRICT_THRESHOLD = 0.90
    _SUPERGROUP_LOOSE_THRESHOLD = 0.80
    _SUPERGROUP_PREFIX_LEN = 2

    async def _merge_topic_supergroups(
        self,
        candidates: list[DiscoveredContent],
    ) -> None:
        """将预计算的 supergroup 规范映射应用到候选。

        实际的语义合并在 :meth:`prewarm_supergroup_embeddings` 中
        发生，它在每个 refresh tick 运行并使用 ``"label | sample_titles"``
        对短中文标签进行准确消歧（仅标签 embedding 的"赛博朋克" vs
        "动漫"可能落在 sim ≥ 0.90，错误地将整个娱乐族折叠到一个桶中）。

        Serve-time 现在是纯 dict 查找 —— 无 embedding API 调用，
        无两两比较。当映射为空（冷启动，或预热器尚未运行）时，
        此方法是 no-op，因此我们不会从即时的仅标签 embedding 产生
        假阳性合并。
        """
        if not self._supergroup_canonical_map or len(candidates) < 2:
            return

        canonical_map = self._supergroup_canonical_map
        merges: list[tuple[str, str]] = []
        for item in candidates:
            key = (item.topic_group or "").strip().lower()
            if not key:
                continue
            canonical = canonical_map.get(key)
            if canonical and canonical != key:
                merges.append((key, canonical))
                item.topic_group = canonical

        if merges:
            # 去重日志行 —— 每个 (src, dst) 对只显示一次。
            unique_merges = sorted({m for m in merges})
            logger.info(
                "Topic supergroup merges (serve, cached): %s",
                ", ".join(f"{src}→{dst}" for src, dst in unique_merges),
            )

    async def _select_relevant_interests(
        self,
        content: DiscoveredContent,
        profile: SoulProfile,
        *,
        top_k: int = 5,
    ) -> list[dict[str, object]]:
        """通过 embedding 相似度选择与此内容最相关的兴趣。

        当 embedding 服务不可用时回退到按权重排序的 top-K。
        """
        # 与 profile summary 的 interest cap（256）对齐的候选池：
        # 头部排名之外的小众兴趣在它与此内容是最佳语义匹配时
        # 仍应可选。top_k（5）仍约束实际到达 prompt 的数量，因此
        # 更宽的池在不增加 prompt 大小的情况下提升覆盖。
        all_interests = [
            {"name": item.name, "category": item.category, "weight": item.weight}
            for item in _interests_by_weight(profile)[:256]
        ]
        if not all_interests:
            return []
        if self._embedding_service is None:
            return all_interests[:top_k]

        from openbiliclaw.llm.embedding import cosine_similarity

        content_text = f"{content.title} {content.description or ''}"
        content_vec = await self._embedding_service.embed(content_text)
        if not content_vec:
            return all_interests[:top_k]

        scored: list[tuple[dict[str, object], float]] = []
        for interest in all_interests:
            raw_weight = interest.get("weight", 0.0)
            weight = float(raw_weight) if isinstance(raw_weight, int | float | str) else 0.0
            interest_vec = await self._embedding_service.embed(str(interest["name"]))
            if not interest_vec:
                scored.append((interest, weight))
                continue
            sim = cosine_similarity(content_vec, interest_vec)
            # 将 embedding 相似度与权重混合用于排名
            blended = sim * 0.7 + weight * 0.3
            scored.append((interest, blended))

        scored.sort(key=lambda x: -x[1])
        return [item for item, _ in scored[:top_k]]

    async def prewarm_supergroup_embeddings(self) -> int:
        """计算供弹窗热路径使用的 supergroup 规范映射。

        为新池中每个不同的 ``topic_group`` embedding
        ``"{label} | {top-5 titles}"``，然后运行 union-find 合并
        （严格 0.90，宽松 0.80 带共享 2 字符前缀）并将结果
        ``label → canonical`` 映射存储到
        ``self._supergroup_canonical_map``。``serve()`` 然后将此映射
        作为纯 dict 查找消费 —— 在用户"换一批"点击时无 API 调用、
        无两两比较。

        标题上下文在此很重要：短中文标签在原始 embedding 空间中
        具有欺骗性的相似性（无标题时 赛博朋克 ≈ 动漫 在 sim ≥ 0.90），
        该 bug 在生产日志中看起来像"40 个候选中的 30 个属于一个桶"。
        标题进行消歧。

        返回考虑的标签数。
        """
        if self._embedding_service is None:
            self._supergroup_canonical_map = {}
            return 0

        groups = self._database.get_topic_group_samples()
        logger.info(
            "Topic supergroup prewarm: %d groups (top-by-population)",
            len(groups),
        )
        if len(groups) < 2:
            self._supergroup_canonical_map = {}
            return len(groups)

        from openbiliclaw.llm.embedding import cosine_similarity

        embedding_service = self._embedding_service

        async def _embed_with_titles(label: str, titles: list[str]) -> tuple[str, list[float]]:
            text = f"{label} | {' | '.join(titles)}" if titles else label
            vec = await embedding_service.embed(text)
            return label.lower(), vec

        results = await asyncio.gather(
            *(_embed_with_titles(label, titles) for label, titles in groups)
        )
        embeddings: dict[str, list[float]] = {label: vec for label, vec in results if vec}
        if len(embeddings) < 2:
            self._supergroup_canonical_map = {}
            return len(embeddings)

        # 在 embedding 上运行 union-find 以派生规范标签
        labels = list(embeddings.keys())
        parent: dict[str, str] = {label: label for label in labels}

        def find(x: str) -> str:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a: str, b: str) -> None:
            ra, rb = find(a), find(b)
            if ra == rb:
                return
            if rb < ra:
                ra, rb = rb, ra
            parent[rb] = ra

        strict = self._SUPERGROUP_STRICT_THRESHOLD
        loose = self._SUPERGROUP_LOOSE_THRESHOLD
        prefix_len = self._SUPERGROUP_PREFIX_LEN
        for i, ga in enumerate(labels):
            for gb in labels[i + 1 :]:
                sim = cosine_similarity(embeddings[ga], embeddings[gb])
                shared_prefix = ga[:prefix_len] == gb[:prefix_len] and len(ga) >= prefix_len
                if sim >= strict or (shared_prefix and sim >= loose):
                    union(ga, gb)

        new_map: dict[str, str] = {}
        for label in labels:
            canonical = find(label)
            if canonical != label:
                new_map[label] = canonical
        self._supergroup_canonical_map = new_map

        if new_map:
            logger.info(
                "Topic supergroup canonical map rebuilt (prewarm): %d labels, %d merges",
                len(labels),
                len(new_map),
            )
            # v0.3.56+：也将现有池行更新为规范形式。没有这个，
            # ``Recommendation candidate summary`` 日志显示"动漫" /
            # "动漫杂谈" / "动漫二次元" 为 3 个独立的 topic_group，
            # 即使映射说它们是同义词，因为合并只在 serve 时运行。
            # 批量更新使下游 SQL（`get_topic_group_samples`、
            # `count_pool_by_franchise` 等价的 group-by 分析、
            # 弹窗状态显示）看到 serve 时会看到的相同规范形式。
            canonicalize = getattr(self._database, "canonicalize_topic_groups", None)
            if callable(canonicalize):
                try:
                    rewritten = canonicalize(new_map)
                    if rewritten:
                        logger.info(
                            "Topic supergroup canonical map applied to pool: %d row(s) rewritten",
                            rewritten,
                        )
                except Exception:
                    logger.exception(
                        "canonicalize_topic_groups failed; pool topic_group "
                        "values will lazy-merge at serve time only"
                    )
        return len(labels)

    async def prewarm_pool_mmr_embeddings(self, *, limit: int = 200) -> int:
        """为当前池预热 MMR embedding L2 缓存。

        ``warm_mmr_embeddings`` 的伴侣（后者在 discovery / 分类时
        per-item 触发）—— 此方法处理迁移 / 冷重启情况，即池已包含
        早于预热 hook 的项。从 refresh 循环和启动时调用，因此下一次
        ``serve()`` 即使在部署第 1 天也是 L2 命中。

        ``limit`` 默认 200 —— 覆盖 ``serve()`` 实际拉取的候选窗口，
        大小使得针对慢速本地 embedding provider（Ollama）的新重启
        预热在几分钟内完成。幂等：``EmbeddingService.embed`` 在
        L2 命中时短路。

        返回契约（lever 4 可观测性 —— 让调用方区分良性冷启动与
        损坏的 embedding 后端）：
          * ``>0`` —— 项已预热。
          * ``0``  —— 有候选但无 embedding → embedding 后端不可达
            （例如 Ollama 宕机）。值得重试。
          * ``-1`` —— 无需预热（无 embedding 服务，或池空）；
            重试无意义 —— 缓存随池填充而懒填。
        """
        if self._embedding_service is None:
            logger.debug("Pool MMR prewarm skipped: embedding service not configured")
            return -1
        candidates = self._load_pool_candidates(limit=limit)
        if not candidates:
            logger.debug(
                "Pool MMR prewarm skipped: pool has no servable candidates yet — "
                "nothing to warm (cache lazy-fills as discovery classifies the pool)"
            )
            return -1
        warmed = await self.warm_mmr_embeddings(candidates)
        if warmed == 0:
            logger.warning(
                "Pool MMR prewarm: 0/%d items embedded — the embedding backend "
                "looks unreachable (e.g. Ollama down). Recommendation diversity "
                "(MMR) degrades until it recovers; see embed-failure debug logs.",
                len(candidates),
            )
        else:
            logger.info(
                "Pool MMR embedding prewarm: %d/%d items warmed",
                warmed,
                len(candidates),
            )
        return warmed

    async def precompute_pool_copy(
        self,
        *,
        profile: SoulProfile,
        limit: int = 20,
        delight_limit: int = 30,
        batch_size: int = _DEFAULT_EXPRESSION_BATCH_SIZE,
    ) -> int:
        """为新池候选预计算快路径弹窗文案。

        v0.3.47+：通过 ``asyncio.gather`` 并行分发批次，由
        ``expression_batch_concurrency``（默认 2）约束，
        ``batch_size`` 默认 30。真实 provider 并发测试显示 45 偶尔
        在推荐文案上产生畸形批次 JSON，因此此路径保持保守，
        而 discovery 评估使用更大的文本批次。
        使用之前的 serial × ``batch_size=8`` 形状，60 项 backlog
        需要 8 次 LLM 调用和 8 次顺序往返。新形状需要 2 次并发
        运行的 LLM 调用 —— 弹窗文案赶上速度快几分钟。

        v0.3.62+：expression 生成由 ``self._expression_lock`` 守护；
        delight 评分在带自己 ``self._delight_lock`` 的分离
        ``asyncio.create_task`` 中运行。之前的单个
        ``_precompute_lock`` 在一个门下持有两个流程，因此慢的
        delight pass 会拖延下一个 expression 批次，即使池项已经
        需要 ``pool_expression``。拆分锁让 expression 和 delight
        独立推进，同时 per-flow 锁仍防止连续触发在同一项上重复
        花费 LLM token。

        因此从 ``_run_refresh_plan`` 排队的 per-strategy
        fire-and-forget 任务不能为 expression 生成两次加载相同的
        未预计算候选。

        也在未评分候选上运行 delight 评分，并为超过 delight 阈值的
        项生成 delight 理由。

        Args:
            profile: 用于个性化的当前 soul profile。
            limit: 为其生成 expression 文案的最大池候选数。
            delight_limit: 评估 delight 潜力的最大未评分候选数。
                与 ``limit`` 独立，因为 delight 扫描整个池查找缺失
                分数，而不仅是需要 expression 文案的项 —— 共享一个
                limit 会在文案队列短时饿死 delight 评分。
            batch_size: expression 生成 LLM 调用的批次大小。
        """
        # v0.3.59+：classify_pool_backlog 作为分离任务触发而非
        # await。之前 precompute 在读取候选前等待 classify 完成 ——
        # 在 v_voucher 速率限制下这串行化了整个管道，因为 classify
        # backlog 每周期可能耗时数分钟。生产日志（2026-05-05
        # 21:15-21:36）显示 pool_available 在 16+ 分钟内卡在 0，
        # 因为 precompute 排在 classify 之后。现在两者以自己的节奏
        # 运行；precompute 读取当前可用的内容，周期性 refresh-loop
        # 排空（runtime/refresh.py:_drain_pool_precompute_backlog）
        # 在下一个 tick 拾取新分类的项。
        try:
            self._spawn_detached_task(
                "classify_pool_backlog_detached",
                self._safe_classify_pool_backlog(profile=profile, limit=limit),
            )
        except Exception:
            logger.exception("classify_pool_backlog detach failed, continuing with precompute")

        # v0.3.62+：delight 评分分离运行，因此它不阻塞 expression
        # 生成或调用方。它自己的 _delight_lock（在
        # _safe_precompute_delight_scores 内获取）防止连续触发
        # 重新评分相同项。
        def _spawn_delight() -> None:
            try:
                self._spawn_detached_task(
                    "precompute_delight_scores_detached",
                    self._safe_precompute_delight_scores(
                        profile=profile,
                        limit=delight_limit,
                    ),
                )
            except Exception:
                logger.exception("precompute_delight_scores detach failed")

        completed = await self._drain_expression_copy(
            profile=profile, limit=limit, batch_size=batch_size
        )

        # 在 expression 锁外触发 delight 评分，因此下一个 expression
        # 批次可以立即开始，而 delight 赶上。
        _spawn_delight()
        return completed

    async def _drain_expression_copy(
        self,
        *,
        profile: SoulProfile,
        limit: int,
        batch_size: int = _DEFAULT_EXPRESSION_BATCH_SIZE,
    ) -> int:
        """为已分类但未拷贝的池候选生成弹窗文案。

        仅文案：与 :meth:`precompute_pool_copy` 不同，它不 spawn
        classify / delight，因此 post-classify hook
        （:meth:`_safe_classify_pool_backlog`，lever 2b）可以在新分类
        项变为文案合格的瞬间调用它 —— 在同一周期排空它们的
        expression 文案而非等待下一个 refresh-loop tick —— 而不
        重新进入 classify。共享的 ``_expression_lock`` 将其与常规
        precompute pass 串行化，因此相同项永不重复花费 LLM token。
        """
        async with self._expression_lock:
            candidates = self._load_pool_candidates_needing_copy(limit=max(0, limit))
            if not candidates:
                return 0

            batches = [
                candidates[i : i + batch_size] for i in range(0, len(candidates), batch_size)
            ]
            results: list[int | Exception | None] = [None] * len(batches)
            next_batch_index = 0
            worker_count = min(self._expression_batch_concurrency, len(batches))

            async def _worker() -> None:
                nonlocal next_batch_index
                while next_batch_index < len(batches):
                    batch_index = next_batch_index
                    next_batch_index += 1
                    try:
                        results[batch_index] = await self._precompute_batch_with_split_retry(
                            batches[batch_index],
                            profile,
                        )
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        results[batch_index] = exc

            await asyncio.gather(*(_worker() for _ in range(worker_count)))
            completed = 0
            for r in results:
                if isinstance(r, Exception):
                    logger.warning("Expression batch failed: %s", r)
                    continue
                completed += int(r or 0)
        return completed

    # ── 与源无关的内容分类 ───────────────────────
    #
    # 来自任何源（bilibili、xiaohongshu、web 等）的内容在进入
    # 多样性/排名管道前必须携带相同的内容特征集（style_key、
    # topic_group、relevance_score）。缺少这些特征的项会使
    # _select_diversified_batch 崩溃 —— 全部共享"unknown" style 和
    # 单个回退 topic token。
    #
    # classify_pool_backlog() 现在是 legacy/recovery 门：它拾取已
    # 在 content_cache 中但没有内容特征的旧行（例如，在
    # discovery_candidates 暂存表存在之前插入的行），通过 discovery
    # 使用的相同 LLM 评估运行它们，并将结果写回。正常源摄入应先
    # 进入 discovery_candidates 并在 content_cache 之前被评估。

    def _spawn_detached_task(
        self,
        name: str,
        coro: Coroutine[Any, Any, Any],
    ) -> asyncio.Task[Any]:
        """Spawn 分离任务，在可用时通过注册表路由。

        v0.3.63+：当 ``self.task_registry`` 被连接时（由
        ``RuntimeContext`` 在启动时），任务被注册，因此
        ``rebuild_from_config`` 的 ``cancel_all`` 可以在新 runtime
        启动前取消它。直接构造 ``RecommendationEngine``（无注册表）
        的测试回退到裸 ``asyncio.create_task`` 以保持向后兼容。
        """
        registry = self.task_registry
        if registry is not None:
            return registry.track(name, coro)
        return asyncio.create_task(coro, name=name)

    async def _safe_classify_pool_backlog(
        self,
        *,
        profile: SoulProfile,
        limit: int = 30,
    ) -> int:
        """classify_pool_backlog 的分离任务包装器（v0.3.59+）。

        ``precompute_pool_copy`` 将此调度为 ``asyncio.create_task``
        而非直接 ``await`` classify_pool_backlog。之前的串行耦合让
        慢的 classify（在 v_voucher 退避或大量新 XHS 笔记下）拖延
        precompute 数分钟；现在 precompute 读取当前已分类就绪的内容，
        而 classify 并行赶上。

        v0.3.124+（lever 2b）：当 classify 实际标记新项时，立即排空
        它们的 expression 文案，而非留给下一个 refresh-loop precompute
        tick。这关闭了"已分类但尚不可服务"的缺口（项仍需要
        ``pool_expression`` / ``pool_topic_label`` 才能被池可用性门
        计入）。排空仅文案，因此不能重新进入 classify，且共享的
        ``_expression_lock`` 将其与进行中的 precompute pass 串行化。
        """
        try:
            classified = await self.classify_pool_backlog(profile=profile, limit=limit)
        except Exception:
            logger.exception("classify_pool_backlog (detached) failed")
            return 0
        if classified > 0:
            try:
                await self._drain_expression_copy(profile=profile, limit=max(limit, classified))
            except Exception:
                logger.exception("post-classify expression drain failed")
        return classified

    async def _safe_precompute_delight_scores(
        self,
        *,
        profile: SoulProfile,
        limit: int,
    ) -> int:
        """precompute_delight_scores 的分离任务包装器（v0.3.62+）。

        ``precompute_pool_copy`` 将此调度为 ``asyncio.create_task``
        而非内联 await。之前的共享 ``_precompute_lock`` 使 delight
        评分在 LLM 对 delight 调用慢时拖延下一个 expression 批次
        —— 池项会坐等 ``pool_expression`` 即使 expression 生成本身
        空闲。将工作拆分为带自己 ``_delight_lock`` 的分离任务
        防止 delight 阻塞 expression，同时仍防止两次 precompute
        触发重新评分相同项。
        """
        if self._delight_lock.locked():
            return 0
        async with self._delight_lock:
            try:
                return await self.precompute_delight_scores(profile=profile, limit=limit)
            except Exception:
                logger.exception("precompute_delight_scores (detached) failed")
                return 0

    async def classify_pool_backlog(
        self,
        *,
        profile: SoulProfile,
        limit: int = 30,
        batch_size: int = 10,
    ) -> int:
        """缺少 style / topic / score 的缓存行的 legacy/recovery 路径。

        正常源摄入现在写入 ``discovery_candidates`` 并在行进入
        ``content_cache`` 之前使用共享的 discovery-candidate 管道。
        此方法仍作为遗留数据库和恢复作业的安全网存在，那里行已缓存
        但仍缺少 ``style_key``、``topic_group`` 或 ``relevance_score``。

        Returns:
            已分类的项数。
        """
        if self._classify_lock.locked():
            return 0  # 另一个 classify 任务已在运行
        async with self._classify_lock:
            return await self._classify_pool_backlog_locked(
                profile=profile,
                limit=limit,
                batch_size=batch_size,
            )

    async def _classify_pool_backlog_locked(
        self,
        *,
        profile: SoulProfile,
        limit: int,
        batch_size: int,
    ) -> int:
        """classify_pool_backlog 的内部实现，在锁下调用。"""
        rows = self._database.get_pool_candidates_needing_evaluation(
            limit=limit, xhs_self_nickname=self._xhs_self_nickname()
        )
        if not rows:
            return 0

        items = self._rows_to_discovered(rows)
        logger.info(
            "classify_pool_backlog: %d un-classified items (platforms: %s)",
            len(items),
            ", ".join(sorted({item.source_platform or "unknown" for item in items})),
        )

        classified = 0
        for batch_start in range(0, len(items), batch_size):
            batch = items[batch_start : batch_start + batch_size]
            try:
                await self._classify_batch(batch, profile)
            except Exception:
                logger.exception(
                    "classify_pool_backlog: batch failed (%d items)",
                    len(batch),
                )
                continue

            # 将结果持久化回池。
            persisted: list[DiscoveredContent] = []
            for item in batch:
                # 当原始值为空时使用 topic_group 作为 topic_key ——
                # 多样性 token 回退到 topic_key，因此这很关键。
                if not item.topic_key and item.topic_group:
                    item.topic_key = item.topic_group
                try:
                    self._database.cache_content(
                        item.bvid,
                        **item.to_cache_kwargs(),
                    )
                    classified += 1
                    persisted.append(item)
                except Exception:
                    logger.exception(
                        "classify_pool_backlog: failed to persist %s",
                        item.bvid,
                    )

            # 预热 MMR embedding 缓存，因此下一次 reshuffle 是 L2 命中
            # 而非在 serve() 中为串行 API 调用支付约 150ms × N。
            # 尽力而为 —— 失败回退到 serve 时的仅 string-cap 路径。
            if persisted:
                await self.warm_mmr_embeddings(persisted)

        logger.info(
            "classify_pool_backlog: %d/%d items classified (styles: %s, topics: %s)",
            classified,
            len(items),
            ", ".join(sorted({i.style_key or "unknown" for i in items})),
            ", ".join(sorted({i.topic_group or "unknown" for i in items})),
        )
        return classified

    async def _classify_batch(
        self,
        batch: list[DiscoveredContent],
        profile: SoulProfile,
    ) -> None:
        """对一组未分类项运行批处理 LLM 评估。

        就地 mutate 每项：设置 ``relevance_score``、
        ``relevance_reason``、``topic_group`` 和 ``style_key``。
        """
        from openbiliclaw.llm.prompts import build_batch_content_evaluation_prompt

        profile_data = _recommendation_profile_summary(profile)
        content_items = [
            {
                "bvid": c.bvid,
                "content_id": c.content_id or c.bvid,
                "title": c.title,
                "up_name": c.up_name or c.author_name,
                "description": (c.description or "")[:400],
                "duration": c.duration,
                "view_count": c.view_count,
                "source_strategy": c.source_strategy,
                "content_type": c.content_type,
                # 文本优先项（X tweets/threads）在此携带完整文本 ——
                # 这些项的 title 信息量低，因此 LLM 需要 body_text 来
                # 判断相关性。对视频源为空。
                "body_text": c.body_text,
            }
            for c in batch
        ]
        # 获取最近的负样本，使 Rule 11 模式匹配同样适用于
        # 非 bilibili 池项（如 xiaohongshu）。
        negative_examples: list[dict[str, object]] | None = None
        try:
            from openbiliclaw.soul.negative_exemplars import recent_negative_exemplars

            negative_examples = recent_negative_exemplars(self._database) or None
        except Exception:
            logger.debug("classify_batch: negative_exemplars unavailable", exc_info=True)

        # 确定 prompt 上下文的主导平台
        platform = (batch[0].source_platform or "bilibili") if batch else "bilibili"
        messages = build_batch_content_evaluation_prompt(
            profile_summary=profile_data,
            profile_blocks=self._profile_blocks(profile_data, cache_key="evaluate_batch"),
            content_items=content_items,
            source_context=batch[0].source_strategy if batch else "",
            source_platform=platform,
            negative_examples=negative_examples,
        )

        complete_structured = self._llm.complete_structured_task
        response = await complete_structured(
            system_instruction=messages[0]["content"],
            user_input=messages[1]["content"],
            max_tokens=8192,
            # v0.3.51+：结构化 XHS 分类 —— 纯分数 + 分类字段，
            # 不从推理链中受益。
            reasoning_effort="",
            caller="recommendation.evaluate_batch",
            **without_core_memory_kwargs(complete_structured),
        )
        raw = str(getattr(response, "content", "")).strip()
        payload = extract_llm_json_list(
            raw,
            wrapper_keys=("results", "items", "evaluations", "scores", "data"),
            allow_singleton=True,
            item_predicate=lambda item: "score" in item,
        )
        if payload is None:
            raise ValueError("Expected classification JSON array or compatible wrapper.")

        if len(payload) != len(batch):
            logger.warning(
                "LLM returned %d results for %d items in classification batch",
                len(payload),
                len(batch),
            )

        payload_by_id = _batch_results_by_content_key(payload, batch)
        if payload_by_id is None and len(payload) != len(batch):
            logger.warning(
                "Classification batch result count mismatch without IDs; marking %d items failed",
                len(batch),
            )
            for content in batch:
                content.relevance_score = 0.01
                content.relevance_reason = "classification_failed"
            return

        for i, content in enumerate(batch):
            if payload_by_id is None:
                result = payload[i] if i < len(payload) else None
            else:
                result = next(
                    (
                        payload_by_id[key]
                        for key in _content_result_keys(content)
                        if key in payload_by_id
                    ),
                    None,
                )
            if not isinstance(result, dict):
                # 标记为已尝试，以便 get_pool_candidates_needing_evaluation
                # 不会永远重试此项。0.01 分数信号表示"分类已尝试但无
                # 可用结果"。
                content.relevance_score = 0.01
                content.relevance_reason = "classification_failed"
                continue
            score_value = result.get("score", 0.0)
            if not isinstance(score_value, (int, float, str)):
                score_value = 0.0
            score = max(0.0, min(1.0, float(score_value)))
            reason = str(result.get("reason", "")).strip()
            topic_group = str(result.get("topic_group", "")).strip()
            style_key = normalize_style_key(result.get("style_key", ""))

            content.relevance_score = score or 0.01  # 永不留在 0.0
            content.relevance_reason = reason
            if topic_group:
                content.topic_group = topic_group
            if style_key in VALID_STYLE_KEYS:
                content.style_key = style_key

    async def precompute_delight_scores(
        self,
        *,
        profile: SoulProfile,
        limit: int = 50,
    ) -> int:
        """为未评分的池候选评分主动 delight 潜力。

        两阶段检索：
          1. 粗：``get_pool_candidates_needing_delight_score`` 按
             ``relevance_score >= 0.55`` 过滤并按 relevance DESC 排序，
             封顶 ``limit``（默认 50）。免费 —— 使用 discovery 的
             ``evaluate_batch`` 已计算的分数。
          2. 精：``LLMDelightScorer.score_batch`` 对那 50 项进行
             delight rubric 的 LLM 判定（跨域桥接 / 隐藏需求 / 质量，
             而非朴素相似度）。

        默认 ``limit=50``（一旦 relevance gate 落地，从 30 提升）：
        为 LLM 找到真正 delight 留更多头部空间，而不在弱匹配垃圾上
        烧周期。成本：50/5 = 10 批次 × ~¥0.01 ≈ ¥0.10/周期，
        8 周期 ¥0.80/天。
        """
        from openbiliclaw.recommendation.delight import LLMDelightScorer

        scorer = LLMDelightScorer(llm_service=self._llm)

        prefs = getattr(profile, "preferences", None)
        exploration_openness = float(getattr(prefs, "exploration_openness", 0.5))
        effective_threshold = scorer.effective_threshold(exploration_openness)
        rows = self._database.get_pool_candidates_needing_delight_score(
            limit=limit,
            min_delight_score_for_reason=effective_threshold,
            xhs_self_nickname=self._xhs_self_nickname(),
        )
        if not rows:
            return 0

        candidates = self._rows_to_discovered(rows)

        # 这里返回的所有 ``rows`` 要么缺 delight_score，要么有
        # embedding 时代评分器的陈旧分数（我们选择用 LLM 重新判定
        # 而非信任）。将它们全部通过一次批处理 LLM 评分 pass ——
        # 无特殊情况的回填循环。
        scored_count = 0
        to_score: list[Any] = list(candidates)

        try:
            scored = await scorer.score_batch(to_score, profile)
        except Exception:
            logger.exception("Delight LLM batch scoring failed for %d candidates", len(to_score))
            return 0

        for candidate in to_score:
            result = scored.get(candidate.bvid)
            if result is None:
                # LLM 丢弃了此项 —— 用哨兵分数标记，使其下周期不再被
                # 选中，但不记录任何正向内容。
                self._database.update_delight_score(
                    candidate.bvid,
                    delight_score=0.01,
                    delight_reason="",
                    delight_hook="",
                )
                continue

            persisted_score = max(0.01, result.score)
            if result.score < effective_threshold:
                # 低于阈值 —— 持久化分数但无 reason/hook
                self._database.update_delight_score(
                    candidate.bvid,
                    delight_score=persisted_score,
                    delight_reason="",
                    delight_hook="",
                )
                scored_count += 1
                continue

            # 高于阈值 —— LLM 已在同一调用中提供 rationale + hook，
            # 无需额外 LLM 跳。
            self._database.update_delight_score(
                candidate.bvid,
                delight_score=persisted_score,
                delight_reason=result.rationale or "",
                delight_hook=result.hook or "意外契合",
            )
            scored_count += 1
            logger.info(
                "Delight candidate found: %s (score=%.3f, hook=%s)",
                candidate.bvid,
                persisted_score,
                result.hook,
            )

        return scored_count

    async def _generate_delight_reason(
        self,
        content: DiscoveredContent,
        profile: SoulProfile,
        reason_stub: str,
    ) -> tuple[str, str]:
        """通过 LLM 生成 delight 理由解释。

        Returns:
            (delight_reason, delight_hook) 元组。
        """
        from openbiliclaw.llm.prompts import build_delight_reason_prompt

        tone_profile = self._expression_tone_profile(profile, content)
        profile_summary = _recommendation_profile_summary(profile)
        messages = build_delight_reason_prompt(
            profile_summary=profile_summary,
            profile_blocks=self._profile_blocks(profile_summary, cache_key="delight_reason"),
            content_summary={
                "title": content.title,
                "up_name": content.up_name,
                "description": (content.description or "")[:400],
                "source_strategy": content.source_strategy,
                "style_key": normalize_style_key(content.style_key),
                "topic_group": content.topic_group,
                "relevance_score": content.relevance_score,
                "content_type": content.content_type,
                "body_text": content.body_text,
            },
            reason_stub=reason_stub,
            tone_profile=tone_profile,
            source_platform=content.source_platform or "bilibili",
        )
        try:
            complete_structured = self._llm.complete_structured_task
            response = await complete_structured(
                system_instruction=messages[0]["content"],
                user_input=messages[1]["content"],
                caller="recommendation.delight_reason",
                **without_core_memory_kwargs(complete_structured),
            )
            payload = extract_llm_json_object(
                str(response.content),
                wrapper_keys=("result", "item", "data", "output"),
                item_predicate=lambda item: "delight_reason" in item or "delight_hook" in item,
            )
            if payload is None:
                raise ValueError("Delight reason response must be a JSON object.")
            reason = str(payload.get("delight_reason", "")).strip()
            hook = str(payload.get("delight_hook", "")).strip()
            if reason and hook:
                return (reason, hook)
        except Exception:
            logger.exception(
                "Failed to generate delight reason for %s",
                content.bvid,
            )
        # 回退
        return ("这条可能会给你意外的惊喜", "意外惊喜")

    async def _precompute_batch(
        self,
        batch: list[DiscoveredContent],
        profile: SoulProfile,
        *,
        fallback_to_single: bool = True,
    ) -> int:
        """通过一次 LLM 调用为一个批次生成 expression。"""
        from openbiliclaw.llm.prompts import build_batch_expression_prompt

        tone_profile = build_tone_profile(
            profile=profile,
            preference_summary={
                "exploration_openness": profile.preferences.exploration_openness,
            },
            recent_feedback=[],
        )
        content_items = [
            {
                "bvid": item.bvid,
                "content_id": item.content_id or item.bvid,
                "title": item.title,
                "up_name": item.up_name,
                "description": (item.description or "")[:400],
                "source_strategy": item.source_strategy,
                "style_key": normalize_style_key(item.style_key),
                "topic_group": item.topic_group,
                "relevance_score": item.relevance_score,
                "content_type": item.content_type,
                "body_text": item.body_text,
            }
            for item in batch
        ]
        profile_summary = _recommendation_profile_summary(profile)
        messages = build_batch_expression_prompt(
            profile_summary=profile_summary,
            profile_blocks=self._profile_blocks(profile_summary, cache_key="batch_expression"),
            content_items=content_items,
            tone_profile=tone_profile,
            source_platform=batch[0].source_platform if batch else "bilibili",
        )

        try:
            complete_structured = self._llm.complete_structured_task
            response = await complete_structured(
                system_instruction=messages[0]["content"],
                user_input=messages[1]["content"],
                max_tokens=8192,
                # v0.3.51+：expression 生成是 per-item 的短文案写作
                # —— 推理链只会膨胀输出（带推理的 write_expression 成本
                # 约为不带的 3 倍，质量无差异）。
                reasoning_effort="",
                caller="recommendation.write_expression",
                **without_core_memory_kwargs(complete_structured),
            )
            payload = extract_llm_json_list(
                str(response.content),
                wrapper_keys=("results", "items", "expressions", "data"),
                allow_singleton=True,
                item_predicate=lambda item: "expression" in item or "topic_label" in item,
            )
            if payload is None:
                raise ValueError("Expected expression JSON array or compatible wrapper.")
        except Exception as exc:
            if is_llm_rate_limit_error(exc):
                logger.warning(
                    "Batch expression generation skipped single-item fallback for %d items "
                    "because the LLM provider is rate-limited or cooling down: %s",
                    len(batch),
                    exc,
                )
                return 0
            if not fallback_to_single:
                logger.warning(
                    "Batch expression generation failed for %d items; will split retry",
                    len(batch),
                )
                raise
            logger.warning(
                "Batch expression generation failed for %d items, falling back to single",
                len(batch),
            )
            return await self._precompute_single_fallback(batch, profile)

        payload_by_id = _batch_results_by_content_key(payload, batch)
        if payload_by_id is None and len(batch) > 1:
            # prompt 要求每个条目回显其 bvid / content_id（rule 2）并
            # 保留输入顺序（rule 1）。当一个*多项*响应不带标识符时，
            # 我们无法验证对齐：重排或重复的数组会静默地为每个视频
            # 附加错误的（或相同的）理由。弱本地模型（如 qwen:7b 在
            # 截断上下文窗口下）持续触发此情况，对用户呈现为"每个推荐
            # 理由都相同且与视频不匹配"。改为 per-item 重新生成 ——
            # 每个单次调用恰好携带一个内容项，不能错位。（1 项批次无
            # 排序歧义，因此下面的位置匹配对它仍然安全。）
            if not fallback_to_single:
                logger.warning(
                    "Batch expression response carried no bvid/content_id for %d "
                    "items; positional matching is unreliable, will split retry",
                    len(batch),
                )
                raise ValueError(
                    f"Batch expression response carried no bvid/content_id for {len(batch)} items"
                )
            logger.warning(
                "Batch expression response carried no bvid/content_id for %d "
                "items; positional matching is unreliable, falling back to "
                "single generation",
                len(batch),
            )
            return await self._precompute_single_fallback(batch, profile)

        # 先收集候选（键匹配，或对顺序无歧义的单项使用位置匹配），
        # 这样我们可以拒绝在多个不同视频间重复相同 expression 的退化
        # 批次（违反 rule 6；表现为相同的推荐语）。为不同视频服务重复
        # 文案比不服务更糟 —— 池门只是跳过未拷贝项，直到更健康的重新
        # 生成填充它们。
        gathered: list[tuple[DiscoveredContent, str, str]] = []
        for i, item in enumerate(batch):
            if payload_by_id is None:
                result = payload[i] if i < len(payload) else None
            else:
                result = next(
                    (
                        payload_by_id[key]
                        for key in _content_result_keys(item)
                        if key in payload_by_id
                    ),
                    None,
                )
            if not isinstance(result, dict):
                continue
            expression = str(result.get("expression", "")).strip()
            topic_label = str(result.get("topic_label", "")).strip()
            if not expression or not topic_label:
                continue
            gathered.append((item, expression, topic_label))

        bvids_by_expression: dict[str, set[str]] = defaultdict(set)
        for item, expression, _ in gathered:
            bvids_by_expression[expression].add(item.bvid)
        duplicated = {
            expression for expression, bvids in bvids_by_expression.items() if len(bvids) > 1
        }
        if duplicated:
            if not fallback_to_single and len(batch) > 1:
                logger.warning(
                    "Batch expression produced %d expression(s) shared across "
                    "distinct videos (model likely repeating itself); will split retry",
                    len(duplicated),
                )
                raise ValueError(
                    f"Batch expression produced duplicate expressions for {len(batch)} items"
                )
            logger.warning(
                "Batch expression produced %d expression(s) shared across "
                "distinct videos (model likely repeating itself); dropping them",
                len(duplicated),
            )

        completed = 0
        for item, expression, topic_label in gathered:
            if expression in duplicated:
                continue
            self._database.update_pool_copy(
                item.bvid,
                expression=expression,
                topic_label=topic_label,
            )
            item.pool_expression = expression
            item.pool_topic_label = topic_label
            completed += 1
        return completed

    async def _precompute_batch_with_split_retry(
        self,
        batch: list[DiscoveredContent],
        profile: SoulProfile,
    ) -> int:
        """尝试一个批次，拆分失败的大批次，然后回退到单项。

        拆分重试在当前 expression worker 内运行。它们不创建嵌套任务，
        因此 ``expression_batch_concurrency`` 仍是单一并发控制点。
        """
        if len(batch) <= 1:
            return await self._precompute_batch(batch, profile, fallback_to_single=True)
        try:
            return await self._precompute_batch(batch, profile, fallback_to_single=False)
        except asyncio.CancelledError:
            raise
        except Exception:
            midpoint = max(1, len(batch) // 2)
            logger.warning(
                "Expression batch split retry: size=%d -> %d/%d",
                len(batch),
                midpoint,
                len(batch) - midpoint,
            )
            left = await self._precompute_batch_with_split_retry(batch[:midpoint], profile)
            right = await self._precompute_batch_with_split_retry(batch[midpoint:], profile)
            return left + right

    async def _precompute_single_fallback(
        self,
        batch: list[DiscoveredContent],
        profile: SoulProfile,
    ) -> int:
        """回退：逐项生成 expression。"""
        completed = 0
        for item in batch:
            generated = await self._try_generate_expression(item, profile)
            if generated is None:
                continue
            expression, topic_label = generated
            self._database.update_pool_copy(
                item.bvid,
                expression=expression,
                topic_label=topic_label,
            )
            item.pool_expression = expression
            item.pool_topic_label = topic_label
            completed += 1
        return completed

    async def generate_recommendations(
        self,
        discovered: list[DiscoveredContent] | None,
        profile: SoulProfile,
        limit: int = 10,
    ) -> list[Recommendation]:
        """通过实时 LLM expression 生成朋友式推荐。

        委托给 :meth:`serve` 并带 ``expression_mode="realtime"``。
        *discovered* 参数为向后兼容而接受但被忽略 —— 引擎始终从
        候选池挑选。
        """
        return await self.serve(profile, limit=limit, expression_mode="realtime")

    async def reshuffle_recommendations(
        self,
        *,
        profile: SoulProfile,
        limit: int = 5,
    ) -> list[Recommendation]:
        """从 discovery 池即时挑选新批次。

        委托给 :meth:`serve` 并带 ``expression_mode="precomputed"``。
        """
        return await self.serve(profile, limit=limit, expression_mode="precomputed")

    async def append_recommendations(
        self,
        *,
        profile: SoulProfile,
        excluded_bvids: list[str],
        limit: int = 10,
    ) -> list[Recommendation]:
        """从 discovery 池追加另一页推荐。

        委托给 :meth:`serve` 并带 excluded BVIDs 用于分页。
        """
        excluded = frozenset(b.strip() for b in excluded_bvids if b and b.strip())
        return await self.serve(
            profile,
            limit=limit,
            excluded_bvids=excluded,
            expression_mode="precomputed",
        )

    async def generate_personal_topic(
        self,
        recommendations: list[Recommendation],
        profile: SoulProfile,
    ) -> PersonalTopic:
        """创建深度个性化的推荐话题。

        话题对用户唯一 —— 不是"周末放松包"，而是连接到他们具体
        性格和当前状态的内容。

        Args:
            recommendations: 分组到一个话题的推荐。
            profile: 用户 soul profile。

        Returns:
            带自定义标题和描述的 PersonalTopic。
        """
        # TODO：使用 LLM 创建个人话题叙事
        return PersonalTopic()

    async def generate_expression(
        self,
        content: DiscoveredContent,
        profile: SoulProfile,
    ) -> tuple[str, str]:
        """生成朋友式推荐 expression。

        expression 应当感觉像一位密友推荐某事：温暖、有洞察力、
        个人化，对为什么这个具体的人会享受这个具体的内容有真正
        的理解。

        Args:
            content: 被推荐的内容。
            profile: 用户 soul profile。

        Returns:
            Expression 文本和一个轻度个性化的 topic 标签。
        """
        generated = await self._try_generate_expression(content, profile)
        if generated is not None:
            return generated
        return self._fallback_expression(content), self._fallback_topic_label(profile)

    async def _try_generate_expression(
        self,
        content: DiscoveredContent,
        profile: SoulProfile,
    ) -> tuple[str, str] | None:
        """尝试生成个性化文案而不应用通用回退。"""
        from openbiliclaw.llm.prompts import build_recommendation_expression_prompt

        tone_profile = self._expression_tone_profile(profile, content)
        # 通过 embedding 相似度选择与此内容最相关的兴趣
        interests_for_prompt = await self._select_relevant_interests(content, profile)

        profile_summary = _recommendation_profile_summary(
            profile,
            interests=interests_for_prompt,
        )
        messages = build_recommendation_expression_prompt(
            profile_summary=profile_summary,
            profile_blocks=self._profile_blocks(profile_summary, cache_key="expression"),
            content_summary={
                "title": content.title,
                "up_name": content.up_name,
                "description": content.description,
                "source_strategy": content.source_strategy,
                "style_key": normalize_style_key(content.style_key),
                "topic_group": content.topic_group,
                "relevance_score": content.relevance_score,
                "content_type": content.content_type,
                "body_text": content.body_text,
            },
            tone_profile=tone_profile,
            source_platform=content.source_platform or "bilibili",
        )
        try:
            complete_structured = self._llm.complete_structured_task
            response = await complete_structured(
                system_instruction=messages[0]["content"],
                user_input=messages[1]["content"],
                caller="recommendation.expression",
                **without_core_memory_kwargs(complete_structured),
            )
            payload = extract_llm_json_object(
                str(response.content),
                wrapper_keys=("result", "item", "expression", "data", "output"),
                item_predicate=lambda item: "expression" in item or "topic_label" in item,
            )
            if payload is None:
                raise ValueError("Expression response must be a JSON object.")
            expression = str(payload.get("expression", "")).strip()
            topic_label = str(payload.get("topic_label", "")).strip()
            if expression and topic_label:
                return (expression, topic_label)
        except Exception:
            logger.exception("Failed to generate recommendation expression: %s", content.bvid)
        return None

    @staticmethod
    def _expression_tone_profile(
        profile: SoulProfile,
        content: DiscoveredContent,
    ) -> ToneProfile:
        tone = build_tone_profile(
            profile=profile,
            preference_summary={
                "style": _profile_style_summary(profile),
                "exploration_openness": profile.preferences.exploration_openness,
            },
            recent_feedback=[],
        )
        return tone

    def mark_presented(self, recommendation_ids: list[int]) -> None:
        """标记推荐行为已展示。"""
        ids = [item for item in recommendation_ids if item > 0]
        if not ids:
            return
        self._database.mark_recommendations_presented(ids)

    async def record_feedback(
        self,
        recommendation_id: int,
        *,
        feedback_type: str,
        note: str = "",
    ) -> None:
        """持久化推荐的显式用户反馈。"""
        self._database.update_recommendation_feedback(
            recommendation_id,
            feedback_type=feedback_type,
            feedback_note=note,
        )

    def get_recommendation(self, recommendation_id: int) -> dict[str, object] | None:
        """为 CLI 或反馈工作流加载推荐行。"""
        return self._database.get_recommendation_by_id(recommendation_id)

    @staticmethod
    def _ranking_key(item: DiscoveredContent) -> tuple[int, float, float, int, str]:
        return (
            0 if item.candidate_tier == "primary" else 1,
            -item.relevance_score,
            -RecommendationEngine._timestamp_score(item.last_scored_at or item.discovered_at),
            -item.view_count,
            item.bvid,
        )

    @staticmethod
    def _timestamp_score(value: str) -> float:
        if not value:
            return 0.0
        try:
            return datetime.fromisoformat(value.replace(" ", "T")).timestamp()
        except ValueError:
            return 0.0

    @staticmethod
    def _fallback_expression(content: DiscoveredContent) -> str:
        title = content.title or "这条内容"
        style_key = normalize_style_key(content.style_key)
        if style_key == "deep_focus":
            return f"《{title}》偏需要认真看进去，但会把结构和原理讲清楚。"
        if style_key == "quick_scan":
            return f"《{title}》适合快速抓重点，先把发生了什么和关键变化过一遍。"
        if style_key == "hands_on":
            return f"《{title}》偏能照着用的实操内容，不只是概念。"
        if style_key == "decision_support":
            return f"《{title}》适合用来做判断，能帮你快速比较重点和取舍。"
        if style_key == "story_immersion":
            return f"《{title}》更像进入一个故事，信息会跟着人物和事件一起展开。"
        if style_key == "opinion_sparring":
            return f"《{title}》偏观点碰撞，适合拿来校准一下自己的判断。"
        if style_key == "social_chat":
            return f"《{title}》胜在像有人把话讲开，适合随手点开听一会儿。"
        if style_key == "daily_wander":
            return f"《{title}》是低目标的生活流，看起来不费劲，氛围也顺。"
        if style_key == "mood_release":
            return f"《{title}》偏轻松释放，拿来换个脑子刚好。"
        if style_key == "aesthetic_browse":
            return f"《{title}》更偏审美浏览，适合先让画面和气质带你进去。"
        if style_key == "ambient_companion":
            return f"《{title}》适合当背景陪伴，不一定要一直盯着看。"
        if style_key == "live_pulse":
            return f"《{title}》偏现场和即时感，节奏会更直接。"
        if style_key == "curiosity_spark":
            return f"《{title}》胜在切口新鲜，适合点开看看这个陌生角度。"
        return f"《{title}》这条切口挺顺的，先丢给你看看，说不定正好能对上你当下的兴趣。"

    @staticmethod
    def _fallback_topic_label(profile: SoulProfile) -> str:
        if profile.core_traits:
            return f"你最近那股偏{profile.core_traits[0]}的状态"
        return "想先丢给你的一条"

    @staticmethod
    def _mmr_embedding_text(content: DiscoveredContent) -> str:
        """MMR embedding 缓存键的规范文本形状。

        保留为单一真相源，使 warm-time 和 serve-time 在缓存键上
        达成一致 —— 否则 warm 端用一种形状填充 L2，而 serve()
        查找另一种形状并永不命中。
        """
        return (f"{content.title or ''} {(content.description or '')[:160]}").strip()[:200]

    async def _fetch_candidate_embeddings(
        self,
        candidates: list[DiscoveredContent],
    ) -> dict[str, list[float]]:
        """仅缓存 embedding 查找用于 MMR 多样化。

        **永不触发 provider API 调用** —— 这是 ``serve()`` 在每次
        "换一批"点击时运行的热路径，我们签订亚秒预算。缓存中缺失
        的项直接落到仅 string-cap 的 diversifier 路径；预热器
        （``warm_mmr_embeddings``，来自 discovery / classify / refresh /
        startup）负责填充 L2 SQLite 缓存，使此查找下次命中。

        仅返回已缓存项的 ``{bvid: vector}``。纯同步-via-async；无 I/O。
        """
        if self._embedding_service is None or not candidates:
            return {}
        lookup = getattr(self._embedding_service, "lookup_cached", None)
        if not callable(lookup):
            return {}
        result: dict[str, list[float]] = {}
        for c in candidates:
            text = self._mmr_embedding_text(c)
            if not text:
                continue
            vec = lookup(text)
            if vec:
                result[c.bvid] = vec
        return result

    async def warm_mmr_embeddings(
        self,
        items: list[DiscoveredContent],
    ) -> int:
        """为进入池的项预热 embedding 缓存。

        由 discovery 和池分类路径调用，因此推荐热路径
        （``serve`` → ``_fetch_candidate_embeddings``）是 L2 缓存命中
        而非 30× 顺序 API 往返。返回实际预热的项数（缓存命中 +
        成功 API 调用）。幂等 —— ``EmbeddingService.embed`` 在
        L1/L2 命中时短路。
        """
        embedding_service = self._embedding_service
        if embedding_service is None or not items:
            return 0

        async def _warm(c: DiscoveredContent) -> bool:
            text = self._mmr_embedding_text(c)
            if not text:
                return False
            try:
                vec = await embedding_service.embed(text)
            except Exception:
                logger.debug(
                    "warm_mmr_embeddings: embed failed for %s",
                    c.bvid,
                    exc_info=True,
                )
                return False
            return bool(vec)

        results = await asyncio.gather(*(_warm(c) for c in items))
        return sum(1 for ok in results if ok)

    @classmethod
    def _select_diversified_batch(
        cls,
        candidates: list[DiscoveredContent],
        *,
        limit: int,
        score_override: dict[str, float] | None = None,
        embeddings: dict[str, list[float]] | None = None,
        amplification_guard: set[str] | frozenset[str] | None = None,
        mmr_alpha: float = 0.5,
        mmr_beta: float = 0.5,
    ) -> list[DiscoveredContent]:
        if score_override:
            ranked = sorted(
                candidates,
                key=lambda item: -score_override.get(item.bvid, 0.0),
            )
        else:
            ranked = sorted(candidates, key=cls._ranking_key)
        if limit <= 1 or len(ranked) <= 1:
            return ranked[:limit]

        # MMR 路径（v0.3.44+）：当 embedding 可用时，将简单的
        # relevance-ordered 贪心选择替换为 Maximum Marginal Relevance
        # —— 每次挑选平衡"高相关性"与"与已挑项的低相似度"通过 embedding
        # 余弦。这捕获 topic_group / style_key string cap 遗漏的
        # "相同话题、不同 LLM 字符串标签"重复（例如三行标记
        # "人工智能" / "AI 趋势" / "AI 应用"在语义上是相同内容层）。
        if embeddings:
            return cls._select_with_mmr(
                ranked,
                limit=limit,
                score_override=score_override,
                embeddings=embeddings,
                amplification_guard=amplification_guard,
                alpha=mmr_alpha,
                beta=mmr_beta,
            )

        def _finalize(items: list[DiscoveredContent]) -> list[DiscoveredContent]:
            items = cls._ensure_accessible_entry(
                ranked=ranked,
                selected=items[:limit],
                limit=limit,
                score_override=score_override,
            )
            return cls._interleave_by_topic(items[:limit])

        per_topic_cap = cls._topic_cap(limit)
        soft_topic_cap = cls._soft_topic_cap(limit)
        per_style_cap = cls._style_cap(limit)
        broad_cap = cls._broad_topic_cap(limit)
        amplification_cap = cls._amplification_cap(limit)
        guard = cls._normalize_amplification_guard(amplification_guard)
        selected: list[DiscoveredContent] = []
        deferred: list[DiscoveredContent] = []
        topic_counts: dict[str, int] = {}
        broad_topic_counts: dict[str, int] = {}
        style_counts: dict[str, int] = {}
        amplification_counts: dict[str, int] = {}

        def _exceeds_broad_cap(item: DiscoveredContent) -> bool:
            bt = cls._broad_topic_token(item)
            return bool(bt) and broad_topic_counts.get(bt, 0) >= broad_cap

        def _track_broad(item: DiscoveredContent) -> None:
            bt = cls._broad_topic_token(item)
            if bt:
                broad_topic_counts[bt] = broad_topic_counts.get(bt, 0) + 1

        def _exceeds_amplification_cap(item: DiscoveredContent) -> bool:
            return any(
                amplification_counts.get(key, 0) >= amplification_cap
                for key in cls._candidate_amplification_keys(item) & guard
            )

        def _track_amplification(item: DiscoveredContent) -> None:
            for key in cls._candidate_amplification_keys(item) & guard:
                amplification_counts[key] = amplification_counts.get(key, 0) + 1

        for item in ranked:
            tokens = cls._diversity_tokens(item)
            style_token = cls._style_token(item)
            if _exceeds_amplification_cap(item):
                deferred.append(item)
                continue
            if tokens and any(topic_counts.get(token, 0) >= per_topic_cap for token in tokens):
                deferred.append(item)
                continue
            if _exceeds_broad_cap(item):
                deferred.append(item)
                continue
            if style_counts.get(style_token, 0) >= per_style_cap:
                deferred.append(item)
                continue
            selected.append(item)
            for token in tokens:
                topic_counts[token] = topic_counts.get(token, 0) + 1
            _track_broad(item)
            _track_amplification(item)
            style_counts[style_token] = style_counts.get(style_token, 0) + 1
            if len(selected) >= limit:
                return _finalize(selected)

        def try_fill(
            pool: list[DiscoveredContent],
            *,
            topic_cap: int,
            enforce_style_cap: bool,
            enforce_broad_cap: bool,
        ) -> list[DiscoveredContent]:
            remaining: list[DiscoveredContent] = []
            for item in pool:
                tokens = cls._diversity_tokens(item)
                style_token = cls._style_token(item)
                if _exceeds_amplification_cap(item):
                    remaining.append(item)
                    continue
                if tokens and any(topic_counts.get(token, 0) >= topic_cap for token in tokens):
                    remaining.append(item)
                    continue
                if enforce_broad_cap and _exceeds_broad_cap(item):
                    remaining.append(item)
                    continue
                if enforce_style_cap and style_counts.get(style_token, 0) >= per_style_cap:
                    remaining.append(item)
                    continue
                selected.append(item)
                for token in tokens:
                    topic_counts[token] = topic_counts.get(token, 0) + 1
                _track_broad(item)
                _track_amplification(item)
                style_counts[style_token] = style_counts.get(style_token, 0) + 1
                if len(selected) >= limit:
                    return []
            return remaining

        remaining = try_fill(
            deferred,
            topic_cap=per_topic_cap,
            enforce_style_cap=False,
            enforce_broad_cap=True,
        )
        if len(selected) < limit:
            remaining = try_fill(
                remaining,
                topic_cap=soft_topic_cap,
                enforce_style_cap=False,
                enforce_broad_cap=True,  # 永不放宽 broad_cap
            )
        if len(selected) < limit:
            # 最终回退：topic 多样性仍在放宽的天花板（2× 紧的
            # broad_cap）下保持。话题是内容丰富度的真实信号 ——
            # 如果 10 项共享相同 broad topic，无论 style 或 source
            # 如何，批次都感觉重复。无 topic（bt == ""）的项自由
            # 通过，因此当池薄但合法时我们仍能达到 `limit`。
            fallback_broad_cap = broad_cap * 2
            for item in remaining:
                bt = cls._broad_topic_token(item)
                style_token = cls._style_token(item)
                if _exceeds_amplification_cap(item):
                    continue
                if bt and broad_topic_counts.get(bt, 0) >= fallback_broad_cap:
                    continue
                selected.append(item)
                if bt:
                    broad_topic_counts[bt] = broad_topic_counts.get(bt, 0) + 1
                _track_amplification(item)
                style_counts[style_token] = style_counts.get(style_token, 0) + 1
                if len(selected) >= limit:
                    break
        return _finalize(selected)

    @staticmethod
    def _amplification_cap(limit: int) -> int:
        import math

        return max(1, math.floor(limit * 0.25))

    @staticmethod
    def _normalize_amplification_guard(
        amplification_guard: set[str] | frozenset[str] | None,
    ) -> frozenset[str]:
        if not amplification_guard:
            return frozenset()
        from openbiliclaw.recommendation.curator import normalize_amplification_key

        return frozenset(
            key
            for key in (normalize_amplification_key(value) for value in amplification_guard)
            if key
        )

    @staticmethod
    def _candidate_amplification_keys(item: DiscoveredContent) -> set[str]:
        from openbiliclaw.recommendation.curator import candidate_amplification_keys

        return candidate_amplification_keys(item)

    @classmethod
    def _select_with_mmr(
        cls,
        ranked: list[DiscoveredContent],
        *,
        limit: int,
        score_override: dict[str, float] | None,
        embeddings: dict[str, list[float]],
        amplification_guard: set[str] | frozenset[str] | None,
        alpha: float,
        beta: float,
    ) -> list[DiscoveredContent]:
        """带现有 string cap 的贪心 Maximum Marginal Relevance 挑选。

        每步选择最大化
        ``alpha * relevance - beta * max_cosine_to_picked`` 的候选。

        ``alpha = beta = 0.5``（默认）给出平衡的相关性 / 多样性
        折中。提升 ``beta``（或降低 ``alpha``）以相关性为代价产生
        更激进变化的批次。基于 string 的 cap（``per_topic_cap`` /
        ``per_style_cap`` / ``broad_topic_cap``）仍门控每次挑选 ——
        违反它们的项进入 ``deferred``，仅在 MMR 用完合规候选时
        重新考虑。
        """
        from openbiliclaw.llm.embedding import cosine_similarity

        per_topic_cap = cls._topic_cap(limit)
        soft_topic_cap = cls._soft_topic_cap(limit)
        per_style_cap = cls._style_cap(limit)
        broad_cap = cls._broad_topic_cap(limit)
        amplification_cap = cls._amplification_cap(limit)
        guard = cls._normalize_amplification_guard(amplification_guard)
        topic_counts: dict[str, int] = {}
        broad_topic_counts: dict[str, int] = {}
        style_counts: dict[str, int] = {}
        amplification_counts: dict[str, int] = {}

        def _exceeds_broad_cap(item: DiscoveredContent) -> bool:
            bt = cls._broad_topic_token(item)
            return bool(bt) and broad_topic_counts.get(bt, 0) >= broad_cap

        def _track(item: DiscoveredContent) -> None:
            for token in cls._diversity_tokens(item):
                topic_counts[token] = topic_counts.get(token, 0) + 1
            bt = cls._broad_topic_token(item)
            if bt:
                broad_topic_counts[bt] = broad_topic_counts.get(bt, 0) + 1
            style_counts[cls._style_token(item)] = style_counts.get(cls._style_token(item), 0) + 1
            for key in cls._candidate_amplification_keys(item) & guard:
                amplification_counts[key] = amplification_counts.get(key, 0) + 1

        def _exceeds_amplification_cap(item: DiscoveredContent) -> bool:
            return any(
                amplification_counts.get(key, 0) >= amplification_cap
                for key in cls._candidate_amplification_keys(item) & guard
            )

        def _violates_caps(item: DiscoveredContent, *, topic_cap: int) -> bool:
            if _exceeds_amplification_cap(item):
                return True
            tokens = cls._diversity_tokens(item)
            if tokens and any(topic_counts.get(t, 0) >= topic_cap for t in tokens):
                return True
            if _exceeds_broad_cap(item):
                return True
            return style_counts.get(cls._style_token(item), 0) >= per_style_cap

        def _relevance(item: DiscoveredContent) -> float:
            if score_override:
                return float(score_override.get(item.bvid, 0.0))
            return float(item.relevance_score or 0.0)

        def _max_cos_to_picked(
            cand: DiscoveredContent,
            picked: list[DiscoveredContent],
        ) -> float:
            cand_vec = embeddings.get(cand.bvid)
            if not cand_vec or not picked:
                return 0.0
            best = 0.0
            for p in picked:
                p_vec = embeddings.get(p.bvid)
                if not p_vec:
                    continue
                sim = cosine_similarity(cand_vec, p_vec)
                if sim > best:
                    best = sim
            return best

        selected: list[DiscoveredContent] = []
        deferred: list[DiscoveredContent] = []
        remaining = list(ranked)

        # 首次挑选：最高相关性的合规项（MMR 的"锚点" ——
        # 由于 picked 为空，没有惩罚）。
        # 后续挑选：argmax(alpha*relevance - beta*max_cos_to_picked)。
        while len(selected) < limit and remaining:
            best_idx = -1
            best_score = -1e9
            for idx, cand in enumerate(remaining):
                rel = _relevance(cand)
                penalty = _max_cos_to_picked(cand, selected)
                mmr = alpha * rel - beta * penalty
                if mmr > best_score:
                    best_score = mmr
                    best_idx = idx
            if best_idx < 0:
                break
            cand = remaining.pop(best_idx)
            if _violates_caps(cand, topic_cap=per_topic_cap):
                deferred.append(cand)
                continue
            selected.append(cand)
            _track(cand)

        # 如果合规项用尽则从 deferred 重新填充 ——
        # 逐步放松 topic cap，最后丢弃 style cap，
        # 镜像 legacy fallback 链。broad_cap 保持硬性。
        if len(selected) < limit:
            still_deferred: list[DiscoveredContent] = []
            for cand in deferred:
                if len(selected) >= limit:
                    still_deferred.append(cand)
                    continue
                if _violates_caps(cand, topic_cap=soft_topic_cap):
                    still_deferred.append(cand)
                    continue
                selected.append(cand)
                _track(cand)
            deferred = still_deferred

        if len(selected) < limit:
            for cand in deferred:
                if len(selected) >= limit:
                    break
                # 最终放松：只有 broad_cap 仍然约束。
                if _exceeds_amplification_cap(cand):
                    continue
                if _exceeds_broad_cap(cand):
                    continue
                selected.append(cand)
                _track(cand)

        # 日志 —— 每次调用暴露 MMR 效果，以便我们能区分它
        # 实际是否轮换了话题组合 vs 仅相关性路径。
        if selected:
            picked_topics = Counter(
                cls._normalize_topic_token(item.topic_group) or "unknown" for item in selected
            )
            top_share = picked_topics.most_common(1)[0][1] / len(selected)
            logger.info(
                "MMR diversifier: picked %d/%d, alpha=%.2f beta=%.2f, "
                "unique_topics=%d top_topic_share=%.0f%%",
                len(selected),
                limit,
                alpha,
                beta,
                len(picked_topics),
                top_share * 100,
            )

        # 复用 legacy 终结化（accessible_entry + interleave）。
        finalized = cls._ensure_accessible_entry(
            ranked=ranked,
            selected=selected[:limit],
            limit=limit,
            score_override=score_override,
        )
        return cls._interleave_by_topic(finalized[:limit])

    @classmethod
    def _ensure_accessible_entry(
        cls,
        *,
        ranked: list[DiscoveredContent],
        selected: list[DiscoveredContent],
        limit: int,
        score_override: dict[str, float] | None,
    ) -> list[DiscoveredContent]:
        """当一个完整批次统一较难时注入一个更易入口的项。

        仅对 5+ 项的完整批次激活，且仅当池中已存在一个有合理竞争力
        的轻量风格选项时。
        """
        if limit < 5 or len(selected) < limit:
            return selected
        if any(cls._accessible_style_priority(item) > 0 for item in selected):
            return selected

        selected_ids = {item.bvid for item in selected}
        selected_topic_counts: Counter[str] = Counter()
        for item in selected:
            selected_topic_counts.update(cls._diversity_tokens(item))

        weakest_score = min(cls._effective_score(item, score_override) for item in selected)
        min_candidate_score = max(0.0, weakest_score - 0.10)

        candidates = [
            item
            for item in ranked
            if item.bvid not in selected_ids
            and cls._accessible_style_priority(item) > 0
            and cls._effective_score(item, score_override) >= min_candidate_score
        ]
        candidates.sort(
            key=lambda item: (
                -cls._accessible_style_priority(item),
                -cls._effective_score(item, score_override),
                cls._ranking_key(item),
            ),
        )

        topic_cap = cls._topic_cap(limit)
        for candidate in candidates:
            candidate_tokens = cls._diversity_tokens(candidate)
            replacement_idx: int | None = None
            for idx in range(len(selected) - 1, -1, -1):
                current = selected[idx]
                if cls._accessible_style_priority(current) > 0:
                    continue
                remaining_topics = Counter(selected_topic_counts)
                remaining_topics.subtract(cls._diversity_tokens(current))
                if candidate_tokens and any(
                    remaining_topics.get(token, 0) >= topic_cap for token in candidate_tokens
                ):
                    continue
                replacement_idx = idx
                break
            if replacement_idx is not None:
                swapped = list(selected)
                swapped[replacement_idx] = candidate
                return swapped
        return selected

    @staticmethod
    def _effective_score(
        item: DiscoveredContent,
        score_override: dict[str, float] | None,
    ) -> float:
        if score_override is None:
            return item.relevance_score
        return score_override.get(item.bvid, item.relevance_score)

    @staticmethod
    def _accessible_style_priority(item: DiscoveredContent) -> int:
        style_key = RecommendationEngine._style_token(item)
        if style_key in {"ambient_companion", "daily_wander", "mood_release"}:
            return 7
        if style_key in {"social_chat", "aesthetic_browse", "live_pulse"}:
            return 6
        if style_key in {"curiosity_spark", "decision_support"}:
            return 4
        if style_key in {"story_immersion", "opinion_sparring"}:
            return 3
        if style_key in {"quick_scan", "hands_on"}:
            return 2
        if style_key == "deep_focus":
            return 1
        return 0

    @staticmethod
    def _diversity_tokens(item: DiscoveredContent) -> set[str]:
        """使用 topic_group（粗粒度语义分类）作为 diversity 分桶。"""
        topic_group = RecommendationEngine._normalize_topic_token(item.topic_group)
        if topic_group:
            return {topic_group}

        topic_key = RecommendationEngine._normalize_topic_token(item.topic_key)
        if topic_key:
            return {topic_key}

        tokens = {
            RecommendationEngine._normalize_topic_token(tag)
            for tag in item.tags
            if RecommendationEngine._normalize_topic_token(tag)
        }
        if tokens:
            return tokens

        # 回退：使用作者 + 标题关键词作为 diversity 信号。
        # NOTE：source_strategy 被故意排除 —— 当许多项共享同一
        # source_strategy（如 "xhs-extension-task"）时，将其用作
        # topic token 会使 diversity 机制将它们视为"同一话题"并将
        # 整个批次折叠进一个桶。
        fallback_fields = [item.up_name]
        title = item.title
        fallback_fields.extend(re.findall(r"[A-Za-z0-9]{2,}", title))
        # 还从标题中提取中文连续字符作为回退 topic 信号 ——
        # 对于缺乏正确分类的内容，这些远比 source_strategy 更具区分性。
        fallback_fields.extend(m for m in re.findall(r"[\u4e00-\u9fff]{2,4}", title))
        return {
            RecommendationEngine._normalize_topic_token(value)
            for value in fallback_fields
            if RecommendationEngine._normalize_topic_token(value)
        }

    @staticmethod
    def _style_token(item: DiscoveredContent) -> str:
        """将 style_key 规范化为受 cap 跟踪的桶。

        空/缺失的 style_key 映射到哨兵值 ``"unknown"``，使未分类内容
        （xhs 笔记常见，它们缺乏 bilibili style 分类）仍参与 per-style
        cap。没有这个，未分类项都会绕过 style_counts 并可能用视觉上
        单调的行淹没一个批次。
        """
        token = RecommendationEngine._normalize_topic_token(normalize_style_key(item.style_key))
        return token or "unknown"

    @staticmethod
    def _broad_topic_token(item: DiscoveredContent) -> str:
        """为跨变体分组提取宽泛话题类别。

        可用时直接使用 topic_group（已经是粗粒度）。
        对 legacy 数据回退到 topic_key 的前 4 个字符。
        """
        group = RecommendationEngine._normalize_topic_token(item.topic_group)
        if group:
            return group
        raw = RecommendationEngine._normalize_topic_token(item.topic_key)
        if not raw:
            return ""
        if raw.startswith("related:"):
            return "related"
        return raw[:4]

    @staticmethod
    def _broad_topic_cap(limit: int) -> int:
        """共享相同宽泛话题类别的最大项数。"""
        if limit <= 5:
            return 2
        if limit <= 10:
            return 3
        return 4

    @classmethod
    def _interleave_by_topic(
        cls,
        items: list[DiscoveredContent],
    ) -> list[DiscoveredContent]:
        """重排项使相同话题内容最大程度地分散开。

        使用按大小排序的组（最大优先）的 round-robin。
        """
        if len(items) <= 2:
            return items
        groups: dict[str, list[DiscoveredContent]] = {}
        for item in items:
            key = cls._broad_topic_token(item) or item.bvid
            groups.setdefault(key, []).append(item)
        buckets = sorted(groups.values(), key=len, reverse=True)
        result: list[DiscoveredContent] = []
        while buckets:
            for bucket in buckets:
                if bucket:
                    result.append(bucket.pop(0))
            buckets = [b for b in buckets if b]
        return result

    @staticmethod
    def _normalize_topic_token(value: str) -> str:
        text = value.strip().lower()
        if not text:
            return ""
        compact = re.sub(r"\s+", "", text)
        return compact[:24]

    @staticmethod
    def _topic_cap(limit: int) -> int:
        return 1 if limit <= 5 else 2

    @staticmethod
    def _soft_topic_cap(limit: int) -> int:
        return 2 if limit <= 5 else 3

    @staticmethod
    def _style_cap(limit: int) -> int:
        return max(1, min(3, (limit + 1) // 3))

    @staticmethod
    def _platform_token(item: DiscoveredContent) -> str:
        """平台标签仅供可观测性 —— 不用于过滤挑选。

        Diversity 和 cap 由内容特征（topic 和 style）驱动。在
        ``_build_debug_summary`` 中暴露以便日志读者仍能看到每轮的
        平台分布。
        """
        platform = (item.source_platform or "").strip().lower()
        return platform or "bilibili"

    def _rows_to_discovered(
        self,
        rows: list[dict[str, Any]],
    ) -> list[DiscoveredContent]:
        """将原始 DB pool 行映射到 ``DiscoveredContent`` dataclass。

        row → dataclass 字段映射的唯一真相源，因此添加/移除一个
        pool 列只需一处编辑。
        """
        from openbiliclaw.discovery.engine import DiscoveredContent

        return [
            DiscoveredContent(
                bvid=str(row.get("bvid", "")),
                title=str(row.get("title", "")),
                up_name=str(row.get("up_name", "")),
                up_mid=int(row.get("up_mid", 0) or 0),
                duration=int(row.get("duration", 0) or 0),
                description=str(row.get("description", "")),
                cover_url=str(row.get("cover_url", "")),
                view_count=int(row.get("view_count", 0) or 0),
                like_count=int(row.get("like_count", 0) or 0),
                tags=self._parse_tags(row.get("tags", "[]")),
                topic_key=str(row.get("topic_key", "")),
                topic_group=str(row.get("topic_group", "")),
                style_key=str(row.get("style_key", "")),
                source_strategy=str(row.get("source", "")),
                relevance_score=float(row.get("relevance_score", 0.0) or 0.0),
                relevance_reason=str(row.get("relevance_reason", "")),
                pool_expression=str(row.get("pool_expression", "")),
                pool_topic_label=str(row.get("pool_topic_label", "")),
                candidate_tier=str(row.get("candidate_tier", "primary") or "primary"),
                discovered_at=str(row.get("discovered_at", "")),
                last_scored_at=str(row.get("last_scored_at", "")),
                content_id=str(row.get("content_id", "") or row.get("bvid", "")),
                content_url=str(row.get("content_url", "")),
                source_platform=str(row.get("source_platform", "") or "bilibili"),
                content_type=str(row.get("content_type", "") or "video"),
                body_text=str(row.get("body_text", "") or ""),
            )
            for row in rows
        ]

    def _load_pool_candidates(self, *, limit: int) -> list[DiscoveredContent]:
        rows = self._database.get_pool_candidates(
            limit=limit, xhs_self_nickname=self._xhs_self_nickname()
        )
        return self._rows_to_discovered(rows)

    def _load_pool_candidates_needing_copy(self, *, limit: int) -> list[DiscoveredContent]:
        rows = self._database.get_pool_candidates_needing_copy(
            limit=limit, xhs_self_nickname=self._xhs_self_nickname()
        )
        return self._rows_to_discovered(rows)

    def _exclude_recently_viewed(
        self,
        candidates: list[DiscoveredContent],
    ) -> list[DiscoveredContent]:
        viewed_bvids = self._database.get_recent_viewed_bvids()
        if not viewed_bvids:
            return candidates
        return [item for item in candidates if item.bvid not in viewed_bvids]

    @classmethod
    def _exclude_disliked_topic_candidates(
        cls,
        candidates: list[DiscoveredContent],
        profile: SoulProfile,
    ) -> list[DiscoveredContent]:
        terms = cls._normalized_disliked_topics(profile)
        if not terms:
            return candidates
        return [item for item in candidates if not cls._matches_disliked_topic(item, terms)]

    @classmethod
    def _normalized_disliked_topics(cls, profile: SoulProfile) -> list[str]:
        raw_topics = getattr(getattr(profile, "preferences", None), "disliked_topics", []) or []
        result: list[str] = []
        seen: set[str] = set()
        for topic in raw_topics:
            term = cls._normalize_dislike_match_text(topic)
            if len(term) < 2 or term in seen:
                continue
            seen.add(term)
            result.append(term)
        return result

    @classmethod
    def _matches_disliked_topic(
        cls,
        item: DiscoveredContent,
        disliked_terms: list[str],
    ) -> bool:
        exact_fields = [
            cls._normalize_dislike_match_text(item.topic_key),
            cls._normalize_dislike_match_text(item.topic_group),
            cls._normalize_dislike_match_text(item.pool_topic_label),
        ]
        search_fields = [
            cls._normalize_dislike_match_text(item.title),
            cls._normalize_dislike_match_text(item.pool_topic_label),
            cls._normalize_dislike_match_text(item.description),
            cls._normalize_dislike_match_text(item.up_name),
            cls._normalize_dislike_match_text((item.body_text or "")[:800]),
            *[cls._normalize_dislike_match_text(tag) for tag in item.tags],
        ]
        for term in disliked_terms:
            if term in exact_fields:
                return True
            if any(term in field for field in search_fields if field):
                return True
        return False

    @staticmethod
    def _normalize_dislike_match_text(value: object) -> str:
        text = str(value or "").strip().lower()
        if not text:
            return ""
        return re.sub(r"\s+", "", text)

    @staticmethod
    def _parse_tags(value: object) -> list[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if not isinstance(value, str) or not value.strip():
            return []
        try:
            payload = json.loads(value)
        except json.JSONDecodeError:
            return []
        if not isinstance(payload, list):
            return []
        return [str(item).strip() for item in payload if str(item).strip()]

    @classmethod
    def _build_debug_summary(
        cls,
        candidates: list[DiscoveredContent],
        *,
        prev_bvids: frozenset[str] | None = None,
    ) -> dict[str, object]:
        """为一个批次构建聚焦内容多样性的 debug 负载。

        v0.3.31+：丰富以暴露对"这个批次是否多样"诊断真正重要的内容：

        - ``unique_topics`` / ``unique_franchises``：总计不同值数，
          不只是 top-5。之前摘要的 top-5 隐藏了尾部多样性。
        - ``top_topic_share`` / ``top_style_share`` /
          ``top_franchise_share``：主导比（max-bucket-count /
          total）。任一 >0.4 = "此批次内容集中"，<0.2 = "分布良好"。
        - ``carryover_from_prev``：此批次中有多少项也在上一个批次中
          出现（当给定 ``prev_bvids`` 时）。告诉你推荐器是否持续
          重复服务相同内容。
        - ``unique_titles_ratio``：不同标题数 / 计数。<1.0 意味着
          同一标题在一个批次中出现多次（数据质量问题；相同内容
          跨源）。
        """
        n = len(candidates)
        if n == 0:
            return {"count": 0}

        style_counts = Counter(cls._style_token(item) or "unknown" for item in candidates)
        source_counts = Counter(
            cls._normalize_topic_token(item.source_strategy) or "unknown" for item in candidates
        )
        platform_counts = Counter(cls._platform_token(item) for item in candidates)

        # Topic group 计数。v0.3.46+：当某项没有合适的
        # ``topic_group`` / ``topic_key`` / tags（即 classify_pool_backlog
        # 尚未运行）时，将其归入 ``"_unclassified_"`` 而非依赖
        # ``_diversity_tokens()`` 的标题前缀回退 ——
        # 否则摘要日志会打印看起来像假的话题，如
        # ``"165"``、``"屎屎"`` 或 ``"三花"``，这些是从原始标题中
        # 在 LLM 评估器分配真实类别之前提取出来的。
        # 分桶路径（由实际 diversifier 使用）保留回退，使未分类项
        # 不会全部坍塌进一个桶 —— 但摘要不应对存在的内容撒谎。
        topic_counts: Counter[str] = Counter()
        for item in candidates:
            primary = cls._normalize_topic_token(item.topic_group) or cls._normalize_topic_token(
                item.topic_key
            )
            if primary:
                topic_counts[primary] += 1
                continue
            tag_tokens = {
                cls._normalize_topic_token(tag)
                for tag in item.tags
                if cls._normalize_topic_token(tag)
            }
            if tag_tokens:
                topic_counts[sorted(tag_tokens)[0]] += 1
            else:
                topic_counts["_unclassified_"] += 1

        # Franchise key —— 排除空值（非 IP 内容）。这是我们
        # 对"一个批次中 5 个不同原神角度视频"（相同 franchise，
        # 不同 topic_group）的守卫。
        franchise_counts: Counter[str] = Counter(
            (getattr(item, "franchise_key", "") or "").strip().lower() for item in candidates
        )
        del franchise_counts[""]  # 不计入非 franchise 内容

        # 与上一个批次的 carryover —— 用户抱怨的最大"陈旧推荐"
        # 信号。存储在引擎上跨调用保留。
        carryover = 0
        if prev_bvids is not None:
            carryover = sum(1 for item in candidates if item.bvid in prev_bvids)

        unique_titles = len({item.title.strip() for item in candidates if item.title})

        def _share(counts: Counter[str]) -> float:
            if not counts:
                return 0.0
            return round(counts.most_common(1)[0][1] / n, 3)

        return {
            "count": n,
            "platforms": dict(platform_counts.most_common()),
            "styles": dict(style_counts.most_common(5)),
            "sources": dict(source_counts.most_common(5)),
            "topics": dict(topic_counts.most_common(5)),
            # 新的 v0.3.31 内容多样性字段
            "unique_topics": len(topic_counts),
            "unique_franchises": len(franchise_counts),
            "top_topic_share": _share(topic_counts),
            "top_style_share": _share(style_counts),
            "top_franchise_share": _share(franchise_counts),
            "top_franchise": (franchise_counts.most_common(1)[0][0] if franchise_counts else ""),
            "carryover_from_prev": carryover,
            "unique_titles_ratio": round(unique_titles / n, 3),
            "sample_titles": [item.title for item in candidates[:5]],
        }
