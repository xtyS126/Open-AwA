"""Pool Curator —— 推荐侧评分，独立于 Discovery。

位于 RecommendationEngine 和数据库之间，计算一个复合 ``rec_score``，
考虑新鲜度、话题疲劳、来源单调、惊喜和反馈信号 —— 这些是 Discovery 的
relevance_score 未捕获的因素。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from openbiliclaw.discovery.engine import DiscoveredContent
    from openbiliclaw.llm.embedding import SupportsEmbeddingService
    from openbiliclaw.storage.database import Database


# ---------------------------------------------------------------------------
# 不可变配置与上下文
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScoringWeights:
    """复合 rec_score 的可调权重。

    Serendipity 权重较高 (0.20) 以确保跨域探索内容出现在推荐中，
    而不仅是高相关性的安全选择。

    ``topic_fatigue`` 从 0.15 提升到 0.25 是在观察到"洛克王国"/"动漫"
    等高相关性候选持续赢得 top-K reshuffle 批次之后，因为每键疲劳惩罚
    (~0.045) 无法克服相关性权重优势 (~0.28)。结合更陡的疲劳曲线
    （现在是 ``count^1.5/len*5``）和新的 topic_group 轴，同一个候选
    在最近历史中出现 ≥2 次时现在受到 3-4 倍更重的打击。
    """

    relevance: float = 0.30
    freshness: float = 0.20
    topic_fatigue: float = 0.25
    source_monotony: float = 0.15
    serendipity: float = 0.20


@dataclass(frozen=True)
class FeedbackSignals:
    """用于评分调整的最近反馈的不可变快照。"""

    disliked_up_mids: frozenset[int] = field(default_factory=frozenset)
    disliked_topic_keys: frozenset[str] = field(default_factory=frozenset)
    liked_topic_keys: frozenset[str] = field(default_factory=frozenset)
    # 从 dislike 项的标题通过 :mod:`openbiliclaw.recommendation.franchise`
    # 提取的 franchise（例如 原神 / 星穹铁道）。没有这个轴，dislike 一个
    # 原神视频只会阻止那个确切的 bvid；related_chain 的其他原神候选
    # 仍会不断出现。有了它，curator 对标题命中同一 franchise 的任何
    # 候选减去一个软惩罚。
    disliked_franchises: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class ScoringContext:
    """最近推荐历史的不可变快照。"""

    recent_topic_keys: tuple[str, ...] = ()
    recent_topic_groups: tuple[str, ...] = ()
    recent_sources: tuple[str, ...] = ()
    feedback: FeedbackSignals = field(default_factory=FeedbackSignals)
    newly_confirmed_amplification_keys: frozenset[str] = field(default_factory=frozenset)
    over_budget_amplification_keys: frozenset[str] = field(default_factory=frozenset)
    now: datetime = field(default_factory=lambda: datetime.now(UTC))


# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

_FRESHNESS_HALF_LIFE_DAYS: float = 3.0
_FEEDBACK_DISLIKE_UP_PENALTY: float = 0.20
_FEEDBACK_DISLIKE_TOPIC_PENALTY: float = 0.10
# 比话题惩罚更软 —— franchise 传播是一个启发式
# （标题上的子串匹配），因此我们不希望单个原神 dislike
# 永久破坏所有游戏内容。结合疲劳 + 话题惩罚，
# 这 0.07 足以将原神候选推到其他新鲜内容之下，
# 但不会完全抑制。
_FEEDBACK_DISLIKE_FRANCHISE_PENALTY: float = 0.07
_FEEDBACK_LIKE_TOPIC_BONUS: float = 0.05
_POOL_LOW_THRESHOLD: int = 50
_DEFAULT_WEIGHTS = ScoringWeights()


def normalize_amplification_key(value: str) -> str:
    """规范化 amplification guard 使用的话题/域标签。"""
    return " ".join(value.strip().lower().split())


def candidate_amplification_keys(item: DiscoveredContent) -> set[str]:
    """返回推荐候选的 v1 amplification 键。"""
    keys = {
        normalize_amplification_key(str(getattr(item, "topic_group", "") or "")),
        normalize_amplification_key(str(getattr(item, "topic_key", "") or "")),
    }
    return {key for key in keys if key}


# ---------------------------------------------------------------------------
# PoolCurator
# ---------------------------------------------------------------------------


class PoolCurator:
    """管理推荐侧评分和池健康。

    curator 永不 mutate 其输入 —— 它返回新的评分映射，
    由引擎用作原始候选之上的 overlay。
    """

    def __init__(
        self,
        database: Database,
        *,
        weights: ScoringWeights = _DEFAULT_WEIGHTS,
        history_window: int = 30,
    ) -> None:
        self._database = database
        self._weights = weights
        self._history_window = history_window

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------

    def build_context(
        self,
        *,
        newly_confirmed_amplification_keys: set[str] | frozenset[str] | None = None,
        rolling_window_hours: int = 24,
    ) -> ScoringContext:
        """从最近推荐历史构建评分上下文。"""
        signals = self._database.get_recent_recommendation_signals(
            limit=self._history_window,
        )
        topic_keys = tuple(
            str(row.get("topic_key", "")).strip()
            for row in signals
            if str(row.get("topic_key", "")).strip()
        )
        topic_groups = tuple(
            str(row.get("topic_group", "")).strip()
            for row in signals
            if str(row.get("topic_group", "")).strip()
        )
        sources = tuple(
            str(row.get("source", "")).strip()
            for row in signals
            if str(row.get("source", "")).strip()
        )

        feedback_rows = self._database.get_feedback_signals(
            limit=self._history_window,
        )
        disliked_ups: set[int] = set()
        disliked_topics: set[str] = set()
        liked_topics: set[str] = set()
        # ``franchise_key`` 是 content_cache 上的 LLM 标记的 IP / franchise /
        # 系列列（在 v0.3.18 中添加）。当用户 dislike 任何项时，每个共享
        # 相同 franchise_key 的其他候选在 _feedback_adjustment 中获得
        # 一个软惩罚 —— 因此 dislike 一个原神视频也会降级
        # 提瓦特、蒙德等。
        disliked_franchises: set[str] = set()
        for row in feedback_rows:
            ftype = str(row.get("feedback_type", "")).strip()
            if ftype == "dislike":
                up_mid = row.get("up_mid")
                if isinstance(up_mid, int) and up_mid > 0:
                    disliked_ups.add(up_mid)
                topic = str(row.get("topic_key", "")).strip()
                if topic:
                    disliked_topics.add(topic)
                franchise = str(row.get("franchise_key", "")).strip()
                if franchise:
                    disliked_franchises.add(franchise)
            elif ftype in ("like", "save"):
                topic = str(row.get("topic_key", "")).strip()
                if topic:
                    liked_topics.add(topic)

        normalized_amplification_keys = frozenset(
            key
            for key in (
                normalize_amplification_key(value)
                for value in (newly_confirmed_amplification_keys or set())
            )
            if key
        )
        over_budget_keys: set[str] = set()
        if normalized_amplification_keys:
            since = datetime.now(UTC) - timedelta(hours=rolling_window_hours)
            recent_rows = self._database.get_recent_recommendation_signals_since(
                since=since,
            )
            total_recent = max(1, len(recent_rows))
            for key in normalized_amplification_keys:
                matching = 0
                for row in recent_rows:
                    row_keys = {
                        normalize_amplification_key(str(row.get("topic_key", "") or "")),
                        normalize_amplification_key(str(row.get("topic_group", "") or "")),
                    }
                    if key in row_keys:
                        matching += 1
                if matching / total_recent >= 0.25:
                    over_budget_keys.add(key)

        return ScoringContext(
            recent_topic_keys=topic_keys,
            recent_topic_groups=topic_groups,
            recent_sources=sources,
            feedback=FeedbackSignals(
                disliked_up_mids=frozenset(disliked_ups),
                disliked_topic_keys=frozenset(disliked_topics),
                liked_topic_keys=frozenset(liked_topics),
                disliked_franchises=frozenset(disliked_franchises),
            ),
            newly_confirmed_amplification_keys=normalized_amplification_keys,
            over_budget_amplification_keys=frozenset(over_budget_keys),
        )

    def score_candidates(
        self,
        candidates: list[DiscoveredContent],
        context: ScoringContext,
    ) -> dict[str, float]:
        """为给定候选返回 bvid → rec_score 映射。

        返回的 dict 可以作为 ``score_override`` 传递给引擎的
        多样化批次选择器。
        """
        w = self._weights
        scores: dict[str, float] = {}
        for item in candidates:
            base = item.relevance_score * w.relevance
            fresh = (
                self._freshness_score(
                    item.discovered_at or item.last_scored_at,
                    context.now,
                )
                * w.freshness
            )
            fatigue = self._combined_topic_fatigue(item, context) * w.topic_fatigue
            monotony = (
                self._source_monotony(
                    item.source_strategy,
                    context.recent_sources,
                )
                * w.source_monotony
            )
            bonus = self._serendipity_bonus(item.source_strategy) * w.serendipity

            score = base + fresh - fatigue - monotony + bonus

            # 反馈调整（加性，在权重系统之外）
            score += self._feedback_adjustment(item, context.feedback)
            if candidate_amplification_keys(item) & context.over_budget_amplification_keys:
                score -= 0.35

            scores[item.bvid] = max(0.0, score)
        return scores

    def needs_replenishment(self, *, threshold: int = _POOL_LOW_THRESHOLD) -> bool:
        """当池变薄时为 True。"""
        return self._database.count_pool_candidates() < threshold

    def pool_count(self) -> int:
        """新鲜池候选的当前数量。"""
        return self._database.count_pool_candidates()

    # ------------------------------------------------------------------
    # 评分组件（全是纯函数）
    # ------------------------------------------------------------------

    @staticmethod
    def _freshness_score(timestamp_str: str, now: datetime) -> float:
        """Sigmoid 衰减：age 0 时 ~1.0，半衰期时 ~0.5，2× 半衰期时 ~0.1。"""
        if not timestamp_str:
            return 0.5
        try:
            discovered = datetime.fromisoformat(
                timestamp_str.replace(" ", "T"),
            )
            if discovered.tzinfo is None:
                discovered = discovered.replace(tzinfo=UTC)
        except ValueError:
            return 0.5
        age_days = max(0.0, (now - discovered).total_seconds() / 86400.0)
        return 1.0 / (1.0 + math.exp((age_days - _FRESHNESS_HALF_LIFE_DAYS) / 1.0))

    @staticmethod
    def _topic_fatigue(topic: str, recent_topics: tuple[str, ...]) -> float:
        """来自 *topic* 在最近历史中出现频率的饱和疲劳。

        曲线（以 ``len(recent)=30`` 为标准）：
          count=0 → 0.0          count=1 → 0.17
          count=2 → 0.47         count=3 → 0.87
          count≥4 → 饱和于 1.0

        从 ``count^1.5 / len * 5`` 推导：首次出现的线性成本，
        但之后是二次方增长，所以一个已经被服务两次的话题比
        只被服务一次的话题受到明显更大的惩罚。之前的
        ``count/len*3`` 曲线仅在 count≈10/30 时达到 1.0，
        这让高相关性候选即使在连续出现 3 次后仍能无限重新获胜。
        """
        if not topic or not recent_topics:
            return 0.0
        count = sum(1 for t in recent_topics if t == topic)
        if count == 0:
            return 0.0
        return float(min(1.0, (count**1.5) / max(1, len(recent_topics)) * 5.0))

    @classmethod
    def _combined_topic_fatigue(
        cls,
        item: DiscoveredContent,
        context: ScoringContext,
    ) -> float:
        """跨 topic_key（细粒度）和 topic_group（粗粒度）的疲劳。

        任一轴将候选标记为"我们最近展示过这类内容很多"就足够了
        —— 因此我们取 max。这捕获了 ``topic_key`` 兄弟
        （动漫杂谈 / 动漫补番 / 动漫解说）持续逃避每键疲劳但
        一起饱和用户对一个 ``topic_group`` 的容忍度的情况。
        """
        key_fatigue = cls._topic_fatigue(
            (item.topic_key or "").strip(),
            context.recent_topic_keys,
        )
        group_fatigue = cls._topic_fatigue(
            (item.topic_group or "").strip(),
            context.recent_topic_groups,
        )
        return max(key_fatigue, group_fatigue)

    @staticmethod
    def _source_monotony(source: str, recent_sources: tuple[str, ...]) -> float:
        """source 在最近推荐中的归一化频率。"""
        if not source or not recent_sources:
            return 0.0
        count = sum(1 for s in recent_sources if s == source)
        return min(1.0, count / max(1, len(recent_sources)) * 2.5)

    @staticmethod
    def _serendipity_bonus(source_strategy: str) -> float:
        """为带来惊喜/新颖的内容给予 bonus。

        explore 获得完整 bonus（跨域发现），
        trending 获得部分 bonus（流行但可能是新话题）。
        """
        if source_strategy == "explore":
            return 1.0
        if source_strategy == "trending":
            return 0.5
        return 0.0

    @staticmethod
    def _feedback_adjustment(
        item: DiscoveredContent,
        feedback: FeedbackSignals,
    ) -> float:
        """基于最近用户反馈的加性评分调整。

        Franchise 惩罚（自 v0.3.18 起）：如果用户 dislike 了任何
        ``franchise_key`` 为 X 的项，每个具有相同 ``franchise_key``
        的候选受到软打击。没有这一层，dislike 一个原神视频只会
        阻止那个确切的 bvid；related_chain 策略持续浮现其他原神内容。

        ``franchise_key`` 是 ``content_cache`` 上的 LLM 标记的 IP / 系列
        列（由内容评估器填充）。它对一般兴趣内容（例如 番茄炒蛋 教程）
        为空，因此大多数行支付零 franchise 惩罚 —— 仅匹配的 IP 支付。
        """
        adj = 0.0
        if item.up_mid and item.up_mid in feedback.disliked_up_mids:
            adj -= _FEEDBACK_DISLIKE_UP_PENALTY
        topic = (item.topic_group or item.topic_key).strip()
        if topic and topic in feedback.disliked_topic_keys:
            adj -= _FEEDBACK_DISLIKE_TOPIC_PENALTY
        if topic and topic in feedback.liked_topic_keys:
            adj += _FEEDBACK_LIKE_TOPIC_BONUS
        item_franchise = (getattr(item, "franchise_key", "") or "").strip()
        if item_franchise and item_franchise in feedback.disliked_franchises:
            adj -= _FEEDBACK_DISLIKE_FRANCHISE_PENALTY
        return adj

    async def score_candidates_async(
        self,
        candidates: list[DiscoveredContent],
        context: ScoringContext,
        *,
        embedding_service: SupportsEmbeddingService | None = None,
    ) -> dict[str, float]:
        """score_candidates 的异步版本，支持基于 embedding 的疲劳/反馈。

        当 embedding_service 可用时，使用 embedding 余弦相似度代替
        精确字符串匹配进行 topic_fatigue 和 feedback_adjustment。
        """
        w = self._weights
        scores: dict[str, float] = {}

        # 预嵌入最近的话题和反馈话题以便复用
        _recent_vecs: dict[str, list[float]] = {}
        _disliked_vecs: dict[str, list[float]] = {}
        _liked_vecs: dict[str, list[float]] = {}
        if embedding_service is not None:
            for t in set(context.recent_topic_keys):
                if t.strip():
                    vec = await embedding_service.embed(t)
                    if vec:
                        _recent_vecs[t] = vec
            for t in context.feedback.disliked_topic_keys:
                vec = await embedding_service.embed(t)
                if vec:
                    _disliked_vecs[t] = vec
            for t in context.feedback.liked_topic_keys:
                vec = await embedding_service.embed(t)
                if vec:
                    _liked_vecs[t] = vec

        from openbiliclaw.llm.embedding import cosine_similarity

        for item in candidates:
            base = item.relevance_score * w.relevance
            fresh = (
                self._freshness_score(
                    item.discovered_at or item.last_scored_at,
                    context.now,
                )
                * w.freshness
            )
            monotony = (
                self._source_monotony(
                    item.source_strategy,
                    context.recent_sources,
                )
                * w.source_monotony
            )
            bonus = self._serendipity_bonus(item.source_strategy) * w.serendipity

            # 基于 embedding 的话题疲劳（当可用时）或
            # 精确字符串回退。任一路径都采用两个轴（topic_key
            # 细粒度，topic_group 粗粒度）并使用 max —— 因此
            # 如果候选的具体话题 OR 其更宽泛的集群最近被服务
            # 太多次，候选就会触发疲劳。
            topic_label = (item.topic_group or item.topic_key).strip()
            if embedding_service is not None and topic_label:
                topic_vec = await embedding_service.embed(topic_label)
                if topic_vec and _recent_vecs:
                    sim_count = sum(
                        cosine_similarity(topic_vec, rv) >= embedding_service.similarity_threshold
                        for rv in _recent_vecs.values()
                    )
                    fatigue = min(
                        1.0,
                        (sim_count**1.5) / max(1, len(context.recent_topic_keys)) * 5.0,
                    )
                else:
                    fatigue = self._combined_topic_fatigue(item, context)
            else:
                fatigue = self._combined_topic_fatigue(item, context)
            fatigue *= w.topic_fatigue

            score = base + fresh - fatigue - monotony + bonus

            # 基于 embedding 的反馈调整
            if embedding_service is not None and topic_label:
                topic_vec = await embedding_service.embed(topic_label)
                adj = 0.0
                if item.up_mid and item.up_mid in context.feedback.disliked_up_mids:
                    adj -= _FEEDBACK_DISLIKE_UP_PENALTY
                if topic_vec:
                    for dv in _disliked_vecs.values():
                        if (
                            cosine_similarity(topic_vec, dv)
                            >= embedding_service.similarity_threshold
                        ):
                            adj -= _FEEDBACK_DISLIKE_TOPIC_PENALTY
                            break
                    for lv in _liked_vecs.values():
                        if (
                            cosine_similarity(topic_vec, lv)
                            >= embedding_service.similarity_threshold
                        ):
                            adj += _FEEDBACK_LIKE_TOPIC_BONUS
                            break
                score += adj
            else:
                score += self._feedback_adjustment(item, context.feedback)

            scores[item.bvid] = max(0.0, score)
        return scores
