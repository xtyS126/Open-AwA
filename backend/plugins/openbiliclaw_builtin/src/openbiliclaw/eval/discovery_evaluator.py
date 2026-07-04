"""DiscoveryEvaluator — 发现策略的多维质量评分。

按 7 个质量维度评估每个策略发现的内容，
以及跨策略多样性。支持自动（LLM-as-judge）
和人工参与两种评估模式。
"""

from __future__ import annotations

import json
import logging
import math
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from openbiliclaw.discovery.engine import DiscoveredContent
    from openbiliclaw.soul.profile import OnionProfile

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Prompt 归因：维度 → 负责的 prompt
# ---------------------------------------------------------------------------

DISCOVERY_FIELD_TO_PARAM: dict[str, str] = {
    # SearchStrategy — 搜索词生成相关维度 → search_queries_prompt
    #                   内容评估相关维度 → content_evaluation_prompt
    "search.query_quality": "search_queries_prompt",
    "search.diversity": "search_queries_prompt",
    "search.no_echo_chamber": "search_queries_prompt",
    "search.relevance": "content_evaluation_prompt",
    "search.specificity": "content_evaluation_prompt",
    "search.filter_precision": "content_evaluation_prompt",
    # TrendingStrategy
    "trending.relevance": "content_evaluation_prompt",
    "trending.rid_selection": "trending_rids_prompt",
    "trending.explanation_quality": "content_evaluation_prompt",
    "trending.specificity": "content_evaluation_prompt",
    # RelatedChainStrategy
    "related_chain.relevance": "content_evaluation_prompt",
    "related_chain.explanation_quality": "content_evaluation_prompt",
    "related_chain.diversity": "content_evaluation_prompt",
    # ExploreStrategy
    "explore.query_quality": "explore_domains_prompt",
    "explore.novelty": "explore_domains_prompt",
    "explore.relevance": "content_evaluation_prompt",
    "explore.explanation_quality": "content_evaluation_prompt",
    # 跨策略
    "cross.diversity": "explore_domains_prompt",
}

DISCOVERY_FIELD_TO_PIPELINE: dict[str, str] = {
    "trending.relevance": "discovery/engine.py:evaluate_content",
    "related_chain.relevance": "discovery/engine.py:evaluate_content",
    "explore.novelty": "discovery/strategies/strategies.py:ExploreStrategy",
    "cross.diversity": "discovery/engine.py:_compress_topic_repeats",
}


# ---------------------------------------------------------------------------
# 维度权重
# ---------------------------------------------------------------------------

_DEFAULT_DIM_WEIGHTS: dict[str, float] = {
    "relevance": 0.25,
    "diversity": 0.15,
    "specificity": 0.12,
    "query_quality": 0.10,
    "explanation_quality": 0.10,
    "novelty": 0.10,
    "no_echo_chamber": 0.10,
    "filter_precision": 0.08,
}

# 各策略的维度权重覆盖。
# Explore 优先考虑新颖性而非信息茧房控制（探索就是其使命）。
# Trending 的信息茧房得分是结构性的（排行数据高度集中），因此降低其权重。
_STRATEGY_DIM_OVERRIDES: dict[str, dict[str, float]] = {
    "explore": {
        "relevance": 0.20,
        "novelty": 0.25,
        "query_quality": 0.15,
        "diversity": 0.15,
        "specificity": 0.10,
        "explanation_quality": 0.10,
        "no_echo_chamber": 0.05,
    },
    "trending": {
        "relevance": 0.30,
        "specificity": 0.15,
        "explanation_quality": 0.15,
        "diversity": 0.15,
        "novelty": 0.15,
        "no_echo_chamber": 0.10,
    },
}

_DEFAULT_STRATEGY_WEIGHTS: dict[str, float] = {
    "search": 0.25,
    "trending": 0.25,
    "related_chain": 0.25,
    "explore": 0.25,
}

# 各维度适用的策略
_STRATEGY_DIMENSIONS: dict[str, list[str]] = {
    "search": [
        "relevance",
        "diversity",
        "specificity",
        "query_quality",
        "no_echo_chamber",
        "filter_precision",
    ],
    "trending": [
        "relevance",
        "diversity",
        "specificity",
        "explanation_quality",
        "novelty",
        "no_echo_chamber",
    ],
    "related_chain": ["relevance", "diversity", "explanation_quality", "no_echo_chamber"],
    "explore": [
        "relevance",
        "diversity",
        "specificity",
        "query_quality",
        "explanation_quality",
        "novelty",
        "no_echo_chamber",
    ],
}


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


@dataclass
class DimensionScore:
    """单个质量维度的评分。"""

    dimension: str
    score: float = 0.0
    details: str = ""
    severity: str = "correct"  # "correct" / "partial" / "wrong"


@dataclass
class StrategyEvalReport:
    """单个发现策略的评估报告。"""

    strategy_name: str
    dimension_scores: list[DimensionScore] = field(default_factory=list)
    overall_score: float = 0.0
    item_count: int = 0
    worst_dimensions: list[DimensionScore] = field(default_factory=list)
    attributions: list[str] = field(default_factory=list)


@dataclass
class DiscoveryEvalReport:
    """跨所有策略的完整发现评估报告。"""

    strategy_reports: dict[str, StrategyEvalReport] = field(default_factory=dict)
    cross_strategy_scores: list[DimensionScore] = field(default_factory=list)
    overall_score: float = 0.0
    worst_dimensions: list[DimensionScore] = field(default_factory=list)
    attributions: list[str] = field(default_factory=list)
    persona_id: str = ""
    timestamp: str = ""


# ---------------------------------------------------------------------------
# LLM 协议
# ---------------------------------------------------------------------------


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
    ) -> object: ...


# ---------------------------------------------------------------------------
# 评估器
# ---------------------------------------------------------------------------


class DiscoveryEvaluator:
    """内容发现策略的多维质量评估器。"""

    def __init__(
        self,
        llm_service: SupportsStructuredTask | None = None,
        *,
        dim_weights: dict[str, float] | None = None,
        strategy_weights: dict[str, float] | None = None,
    ) -> None:
        self._llm = llm_service
        self._dim_weights = dim_weights or dict(_DEFAULT_DIM_WEIGHTS)
        self._strategy_weights = strategy_weights or dict(_DEFAULT_STRATEGY_WEIGHTS)

    async def evaluate_strategy(
        self,
        strategy_name: str,
        results: list[DiscoveredContent],
        persona: OnionProfile,
        intermediates: dict[str, object] | None = None,
    ) -> StrategyEvalReport:
        """评估单个策略的输出。"""
        applicable_dims = _STRATEGY_DIMENSIONS.get(strategy_name, list(self._dim_weights))
        intermediates = intermediates or {}

        scores: list[DimensionScore] = []
        for dim in applicable_dims:
            score = await self._score_dimension(
                dim,
                strategy_name=strategy_name,
                results=results,
                persona=persona,
                intermediates=intermediates,
            )
            scores.append(score)

        # 如有策略特定的权重覆盖，则使用
        dim_weights = _STRATEGY_DIM_OVERRIDES.get(strategy_name, self._dim_weights)
        total_weight = sum(
            dim_weights.get(s.dimension, self._dim_weights.get(s.dimension, 0.0)) for s in scores
        )
        overall = 0.0
        if total_weight > 0:
            overall = (
                sum(
                    s.score * dim_weights.get(s.dimension, self._dim_weights.get(s.dimension, 0.0))
                    for s in scores
                )
                / total_weight
            )

        worst = sorted(scores, key=lambda s: s.score)[:3]
        attributions = [
            f"{strategy_name}.{d.dimension} → "
            f"{DISCOVERY_FIELD_TO_PARAM.get(f'{strategy_name}.{d.dimension}', 'unknown')}"
            for d in worst
            if d.score < 0.7
        ]

        return StrategyEvalReport(
            strategy_name=strategy_name,
            dimension_scores=scores,
            overall_score=round(overall, 4),
            item_count=len(results),
            worst_dimensions=worst,
            attributions=attributions,
        )

    async def evaluate_all(
        self,
        strategy_results: dict[str, list[DiscoveredContent]],
        persona: OnionProfile,
        intermediates: dict[str, dict[str, object]] | None = None,
    ) -> DiscoveryEvalReport:
        """评估所有策略并生成综合报告。"""
        intermediates = intermediates or {}
        reports: dict[str, StrategyEvalReport] = {}

        for name, results in strategy_results.items():
            reports[name] = await self.evaluate_strategy(
                name,
                results,
                persona,
                intermediates=intermediates.get(name),
            )

        # 跨策略多样性
        all_items: list[DiscoveredContent] = []
        for items in strategy_results.values():
            all_items.extend(items)
        cross_diversity = _score_diversity(all_items)
        cross_scores = [
            DimensionScore(
                dimension="cross.diversity",
                score=cross_diversity,
                severity=_severity(cross_diversity),
            )
        ]

        # 加权总分
        total_weight = 0.0
        weighted_sum = 0.0
        for name, report in reports.items():
            w = self._strategy_weights.get(name, 0.25)
            weighted_sum += report.overall_score * w
            total_weight += w

        cross_weight = 0.1
        weighted_sum += cross_diversity * cross_weight
        total_weight += cross_weight

        overall = weighted_sum / total_weight if total_weight > 0 else 0.0

        # 收集所有策略中最差的维度
        all_dims: list[DimensionScore] = []
        for report in reports.values():
            for dim in report.dimension_scores:
                all_dims.append(
                    DimensionScore(
                        dimension=f"{report.strategy_name}.{dim.dimension}",
                        score=dim.score,
                        details=dim.details,
                        severity=dim.severity,
                    )
                )
        all_dims.extend(cross_scores)
        worst = sorted(all_dims, key=lambda d: d.score)[:5]

        attributions = [
            f"{d.dimension} → {DISCOVERY_FIELD_TO_PARAM.get(d.dimension, 'unknown')}"
            for d in worst
            if d.score < 0.7
        ]

        return DiscoveryEvalReport(
            strategy_reports=reports,
            cross_strategy_scores=cross_scores,
            overall_score=round(overall, 4),
            worst_dimensions=worst,
            attributions=attributions,
            timestamp=datetime.now(tz=UTC).isoformat(),
        )

    async def evaluate_with_human(
        self,
        strategy_results: dict[str, list[DiscoveredContent]],
        human_feedback: dict[str, dict[str, object]],
    ) -> DiscoveryEvalReport:
        """根据人工按维度反馈构建 DiscoveryEvalReport。

        human_feedback 格式：
        {
            "search.relevance": {"score": 0.7, "note": "Too many gaming results"},
            "search.query_quality": {"score": 0.5, "note": "Queries too generic"},
            ...
        }
        """
        reports: dict[str, StrategyEvalReport] = {}
        strategy_names = set(strategy_results.keys())

        for strategy_name in strategy_names:
            scores: list[DimensionScore] = []
            for dimension_name in _STRATEGY_DIMENSIONS.get(strategy_name, []):
                key = f"{strategy_name}.{dimension_name}"
                entry = human_feedback.get(key, {})
                if not isinstance(entry, dict):
                    entry = {}
                raw_score = entry.get("score", 0.5)
                score = _clamp(float(raw_score) if isinstance(raw_score, (int, float)) else 0.5)
                note = str(entry.get("note", ""))
                scores.append(
                    DimensionScore(
                        dimension=dimension_name,
                        score=score,
                        details=note,
                        severity=_severity(score),
                    )
                )

            total_weight = sum(self._dim_weights.get(s.dimension, 0.0) for s in scores)
            overall = 0.0
            if total_weight > 0:
                overall = (
                    sum(s.score * self._dim_weights.get(s.dimension, 0.0) for s in scores)
                    / total_weight
                )

            worst = sorted(scores, key=lambda s: s.score)[:3]
            reports[strategy_name] = StrategyEvalReport(
                strategy_name=strategy_name,
                dimension_scores=scores,
                overall_score=round(overall, 4),
                item_count=len(strategy_results.get(strategy_name, [])),
                worst_dimensions=worst,
                attributions=[
                    f"{strategy_name}.{d.dimension} → "
                    f"{DISCOVERY_FIELD_TO_PARAM.get(f'{strategy_name}.{d.dimension}', 'unknown')}"
                    for d in worst
                    if d.score < 0.7
                ],
            )

        # 从人工反馈得到的跨策略得分
        cross_entry = human_feedback.get("cross.diversity", {})
        cross_raw_score = cross_entry.get("score") if isinstance(cross_entry, dict) else None
        cross_score = _clamp(
            float(cross_raw_score) if isinstance(cross_raw_score, (int, float)) else 0.5
        )
        cross_scores = [
            DimensionScore(
                dimension="cross.diversity",
                score=cross_score,
                severity=_severity(cross_score),
            )
        ]

        total_weight = 0.0
        weighted_sum = 0.0
        for name, report in reports.items():
            w = self._strategy_weights.get(name, 0.25)
            weighted_sum += report.overall_score * w
            total_weight += w
        weighted_sum += cross_score * 0.1
        total_weight += 0.1
        overall = weighted_sum / total_weight if total_weight > 0 else 0.0

        all_dims: list[DimensionScore] = []
        for report in reports.values():
            for dimension_score in report.dimension_scores:
                all_dims.append(
                    DimensionScore(
                        dimension=f"{report.strategy_name}.{dimension_score.dimension}",
                        score=dimension_score.score,
                        details=dimension_score.details,
                        severity=dimension_score.severity,
                    )
                )
        all_dims.extend(cross_scores)
        worst = sorted(all_dims, key=lambda d: d.score)[:5]

        return DiscoveryEvalReport(
            strategy_reports=reports,
            cross_strategy_scores=cross_scores,
            overall_score=round(overall, 4),
            worst_dimensions=worst,
            attributions=[
                f"{d.dimension} → {DISCOVERY_FIELD_TO_PARAM.get(d.dimension, 'unknown')}"
                for d in worst
                if d.score < 0.7
            ],
            timestamp=datetime.now(tz=UTC).isoformat(),
        )

    # ------------------------------------------------------------------
    # 维度评分分发
    # ------------------------------------------------------------------

    async def _score_dimension(
        self,
        dimension: str,
        *,
        strategy_name: str,
        results: list[DiscoveredContent],
        persona: OnionProfile,
        intermediates: dict[str, object],
    ) -> DimensionScore:
        if not results:
            return DimensionScore(
                dimension=dimension, score=0.0, severity="wrong", details="No results to evaluate"
            )

        if dimension == "relevance":
            score = await self._score_relevance(results, persona)
        elif dimension == "diversity":
            score = _score_diversity(results)
        elif dimension == "specificity":
            score = await self._score_specificity(results, persona)
        elif dimension == "query_quality":
            queries = intermediates.get("queries") or intermediates.get("domains")
            score = await self._score_query_quality(queries, persona)
        elif dimension == "explanation_quality":
            score = _score_explanation_quality(results)
        elif dimension == "novelty":
            score = _score_novelty(results, persona)
        elif dimension == "no_echo_chamber":
            score = _score_no_echo_chamber(results)
        elif dimension == "filter_precision":
            ground_truth = intermediates.get("relevance_labels")
            score = _score_filter_precision(results, ground_truth)
        else:
            score = 0.5

        return DimensionScore(
            dimension=dimension,
            score=round(score, 4),
            severity=_severity(score),
        )

    # ------------------------------------------------------------------
    # LLM-judge 评分函数
    # ------------------------------------------------------------------

    async def _score_relevance(
        self,
        results: list[DiscoveredContent],
        persona: OnionProfile,
    ) -> float:
        if self._llm is None:
            return _fallback_relevance(results)

        sample = results[:8]
        persona_ctx = _persona_context(persona)
        items_text = "\n".join(
            f"- 《{item.title}》 by {item.up_name} | 理由: {item.relevance_reason}"
            for item in sample
        )

        try:
            response = await self._llm.complete_structured_task(
                system_instruction=(
                    "你是内容推荐质量评审员。评估以下内容列表与用户画像的匹配度。\n"
                    '输出严格 JSON: {"score": 0.0-1.0, "reason": "一句话"}'
                ),
                user_input=f"用户画像:\n{persona_ctx}\n\n候选内容:\n{items_text}",
                temperature=0.3,
                max_tokens=256,
                caller="eval.relevance",
            )
            parsed = json.loads(str(getattr(response, "content", "")).strip())
            if isinstance(parsed, dict):
                return _clamp(parsed.get("score", 0.5))
        except Exception:
            logger.exception("LLM relevance scoring failed")
        return _fallback_relevance(results)

    async def _score_specificity(
        self,
        results: list[DiscoveredContent],
        persona: OnionProfile,
    ) -> float:
        if self._llm is None:
            return 0.5

        sample = results[:8]
        persona_ctx = _persona_context(persona)
        items_text = "\n".join(f"- 《{item.title}》" for item in sample)

        try:
            response = await self._llm.complete_structured_task(
                system_instruction=(
                    "评估这些内容是否针对此用户个人定制，而非泛热门内容。\n"
                    "1.0 = 高度个性化，0.0 = 完全是泛热门。\n"
                    '输出严格 JSON: {"score": 0.0-1.0, "reason": "一句话"}'
                ),
                user_input=f"用户画像:\n{persona_ctx}\n\n内容列表:\n{items_text}",
                temperature=0.3,
                max_tokens=256,
                caller="eval.specificity",
            )
            parsed = json.loads(str(getattr(response, "content", "")).strip())
            if isinstance(parsed, dict):
                return _clamp(parsed.get("score", 0.5))
        except Exception:
            logger.exception("LLM specificity scoring failed")
        return 0.5

    async def _score_query_quality(
        self,
        queries_or_domains: object,
        persona: OnionProfile,
    ) -> float:
        if self._llm is None or not queries_or_domains:
            return 0.5

        persona_ctx = _persona_context(persona)
        if isinstance(queries_or_domains, list):
            items_text = "\n".join(
                f"- {json.dumps(q, ensure_ascii=False) if isinstance(q, dict) else str(q)}"
                for q in queries_or_domains[:10]
            )
        else:
            items_text = str(queries_or_domains)

        try:
            response = await self._llm.complete_structured_task(
                system_instruction=(
                    "评估这些搜索词/探索方向是否有创造性、针对性，能为此用户找到好内容。\n"
                    "1.0 = 创造性强且精准，0.0 = 过于泛泛或与用户无关。\n"
                    '输出严格 JSON: {"score": 0.0-1.0, "reason": "一句话"}'
                ),
                user_input=f"用户画像:\n{persona_ctx}\n\n搜索词/方向:\n{items_text}",
                caller="eval.query_quality",
                temperature=0.3,
                max_tokens=256,
            )
            parsed = json.loads(str(getattr(response, "content", "")).strip())
            if isinstance(parsed, dict):
                return _clamp(parsed.get("score", 0.5))
        except Exception:
            logger.exception("LLM query quality scoring failed")
        return 0.5


# ---------------------------------------------------------------------------
# 算法评分函数（零 LLM 成本）
# ---------------------------------------------------------------------------


def _score_diversity(results: list[Any]) -> float:
    """基于 topic_key + style_key 的香农熵，归一化到 [0, 1]。"""
    if len(results) <= 1:
        return 0.0

    labels: list[str] = []
    for item in results:
        topic = getattr(item, "topic_key", "") or ""
        style = getattr(item, "style_key", "") or ""
        labels.append(f"{topic}|{style}")

    counts = Counter(labels)
    total = len(labels)
    max_entropy = math.log(min(total, len(counts))) if len(counts) > 1 else 1.0

    entropy = -sum((c / total) * math.log(c / total) for c in counts.values() if c > 0)
    return _clamp(entropy / max_entropy if max_entropy > 0 else 0.0)


def _score_novelty(results: list[Any], persona: Any) -> float:
    """topic 不在 persona 顶部兴趣中的结果所占比例。"""
    if not results:
        return 0.0

    known_topics: set[str] = set()
    prefs = getattr(persona, "preferences", None)
    if prefs is None:
        # OnionProfile：尝试兴趣层
        interest = getattr(persona, "interest", None)
        if interest is not None:
            likes = getattr(interest, "likes", [])
            for domain in likes:
                name = (
                    getattr(domain, "name", "")
                    if hasattr(domain, "name")
                    else str(domain.get("name", ""))
                )
                if name:
                    known_topics.add(name.strip().lower())
    else:
        for interest in getattr(prefs, "interests", [])[:10]:
            name = getattr(interest, "name", "")
            if name:
                known_topics.add(name.strip().lower())

    if not known_topics:
        return 0.5

    novel_count = 0
    for item in results:
        topic = (getattr(item, "topic_key", "") or "").strip().lower()
        if not topic or not any(k in topic or topic in k for k in known_topics):
            novel_count += 1

    return _clamp(novel_count / len(results))


def _score_no_echo_chamber(results: list[Any]) -> float:
    """当结果集中在过少 topic 时进行惩罚。"""
    if len(results) <= 1:
        return 1.0

    topics: list[str] = []
    for item in results:
        # 优先使用 topic_group（粗粒度、LLM 分配、embedding 归一化）
        # 而非 topic_key（原始查询字符串、按查询而非按结果）
        topic = (
            getattr(item, "topic_group", "").strip()
            or getattr(item, "topic_key", "").strip()
            or "unknown"
        )
        topics.append(topic.lower())

    counts = Counter(topics)
    if not counts:
        return 1.0

    most_common_fraction = counts.most_common(1)[0][1] / len(topics)
    unique_ratio = len(counts) / len(topics)

    # 当主导 topic > 60% 时进行惩罚
    if most_common_fraction > 0.6:
        return _clamp(0.3 * unique_ratio)

    return _clamp(0.5 + 0.5 * unique_ratio)


def _score_explanation_quality(results: list[Any]) -> float:
    """根据结果是否具有非空、实质性的 relevance_reason 进行评分。"""
    if not results:
        return 0.0

    good_count = 0
    for item in results:
        reason = (getattr(item, "relevance_reason", "") or "").strip()
        if len(reason) >= 10:
            good_count += 1

    return _clamp(good_count / len(results))


def _fallback_relevance(results: list[Any]) -> float:
    """从已有的 relevance_score 值回退得到相关性得分。"""
    if not results:
        return 0.0
    scores = [getattr(item, "relevance_score", 0.0) or 0.0 for item in results]
    return _clamp(sum(scores) / len(scores))


def _score_filter_precision(
    results: list[Any],
    ground_truth: object,
) -> float:
    """将 evaluate_content 得分与场景真实标签进行对比。

    衡量 LLM 评估 prompt 是否正确区分相关和不相关内容。
    在预测和真实标签上都使用 0.5 阈值计算精确率和召回率。

    返回 F1 分数；若无真实标签可用则返回 0.5。
    """
    if not isinstance(ground_truth, dict) or not results:
        return 0.5

    labels: dict[str, float] = ground_truth
    tp = fp = fn = 0
    for item in results:
        bvid = getattr(item, "bvid", "")
        predicted_score = getattr(item, "relevance_score", 0.0) or 0.0
        gt_score = labels.get(bvid)
        if gt_score is None:
            continue

        predicted_positive = predicted_score >= 0.5
        actual_positive = gt_score >= 0.5

        if predicted_positive and actual_positive:
            tp += 1
        elif predicted_positive and not actual_positive:
            fp += 1
        elif not predicted_positive and actual_positive:
            fn += 1

    if tp == 0:
        return 0.0 if (fp + fn) > 0 else 0.5

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    if precision + recall == 0:
        return 0.0
    f1 = 2 * precision * recall / (precision + recall)
    return _clamp(f1)


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


def _persona_context(persona: Any) -> str:
    """从 OnionProfile 或 SoulProfile 中提取紧凑文本摘要。"""
    if hasattr(persona, "to_llm_context"):
        ctx = persona.to_llm_context()
        if isinstance(ctx, str) and ctx:
            return ctx[:1500]

    parts: list[str] = []
    portrait = getattr(persona, "personality_portrait", "")
    if portrait:
        parts.append(f"人格: {portrait[:300]}")
    traits = getattr(persona, "core_traits", [])
    if traits:
        parts.append(f"特质: {', '.join(str(t) for t in traits[:5])}")
    needs = getattr(persona, "deep_needs", [])
    if needs:
        parts.append(f"需求: {', '.join(str(n) for n in needs[:5])}")

    prefs = getattr(persona, "preferences", None)
    if prefs:
        interests = getattr(prefs, "interests", [])
        if interests:
            parts.append("兴趣: " + ", ".join(f"{getattr(i, 'name', '')}" for i in interests[:8]))
    return "\n".join(parts) or "No profile context available"


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _severity(score: float) -> str:
    if score >= 0.8:
        return "correct"
    if score >= 0.5:
        return "partial"
    return "wrong"
