"""SpeculationEvaluator — 推测兴趣质量的多维评分。

跨 7 个维度评估推测：合理性、新颖性、具体性、
确认率、非幻觉、多样性和人格共鸣。支持自动化（LLM + persona judge）、
模拟事件和人工反馈三种评估模式。
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field
from datetime import datetime
from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from openbiliclaw.eval.persona_judge import PersonaJudgment
    from openbiliclaw.soul.profile import OnionProfile
    from openbiliclaw.soul.speculator import SpeculativeInterest

logger = logging.getLogger(__name__)

# 总分的维度权重
_DIM_WEIGHTS: dict[str, float] = {
    "plausibility": 0.20,
    "novelty": 0.15,
    "specificity": 0.10,
    "confirmation_rate": 0.15,
    "no_hallucination": 0.10,
    "diversity": 0.15,
    "persona_resonance": 0.15,
}

# 所有维度都映射到同一个 prompt（唯一的 LLM 可控变量）
SPECULATION_FIELD_TO_PARAM: dict[str, str] = {
    k: "speculation_generation_prompt" for k in _DIM_WEIGHTS
}


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


@dataclass
class SpeculationScore:
    """单个推测的评分。"""

    domain: str = ""
    plausibility: float = 0.0
    novelty: float = 0.0
    specificity: float = 0.0
    no_hallucination: float = 0.0
    persona_resonance: float = 0.0
    overall: float = 0.0
    details: str = ""


@dataclass
class SpeculationEvalReport:
    """一次推测生成运行的完整评估报告。"""

    speculation_scores: list[SpeculationScore] = field(default_factory=list)
    confirmation_rate: float = 0.0
    diversity_score: float = 0.0
    mean_plausibility: float = 0.0
    mean_novelty: float = 0.0
    mean_specificity: float = 0.0
    mean_no_hallucination: float = 0.0
    mean_persona_resonance: float = 0.0
    overall_score: float = 0.0
    worst_dimensions: list[dict[str, Any]] = field(default_factory=list)
    attributions: list[str] = field(default_factory=list)
    persona_id: str = ""
    timestamp: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "overall_score": self.overall_score,
            "confirmation_rate": self.confirmation_rate,
            "diversity_score": self.diversity_score,
            "mean_plausibility": self.mean_plausibility,
            "mean_novelty": self.mean_novelty,
            "mean_specificity": self.mean_specificity,
            "mean_no_hallucination": self.mean_no_hallucination,
            "mean_persona_resonance": self.mean_persona_resonance,
            "speculation_scores": [
                {
                    "domain": s.domain,
                    "plausibility": s.plausibility,
                    "novelty": s.novelty,
                    "specificity": s.specificity,
                    "no_hallucination": s.no_hallucination,
                    "persona_resonance": s.persona_resonance,
                    "overall": s.overall,
                    "details": s.details,
                }
                for s in self.speculation_scores
            ],
            "worst_dimensions": self.worst_dimensions,
            "attributions": self.attributions,
            "persona_id": self.persona_id,
            "timestamp": self.timestamp,
        }


# ---------------------------------------------------------------------------
# 评分辅助函数
# ---------------------------------------------------------------------------


def _no_hallucination_score(
    domain: str,
    confirmed_domains: list[str],
) -> float:
    """检查推测是否复述了已有确认兴趣。0.0 = 幻觉。"""
    domain_lower = domain.lower()
    for confirmed in confirmed_domains:
        confirmed_lower = confirmed.lower()
        if domain_lower in confirmed_lower or confirmed_lower in domain_lower:
            return 0.0
    # token 重叠检查
    from openbiliclaw.soul.speculator import _tokenize

    domain_tokens = _tokenize(domain)
    for confirmed in confirmed_domains:
        conf_tokens = _tokenize(confirmed)
        if domain_tokens and conf_tokens:
            overlap = len(domain_tokens & conf_tokens) / len(domain_tokens)
            if overlap >= 0.6:
                return 0.2
    return 1.0


def _confirmation_rate_score(rate: float) -> float:
    """对确认率评分。目标是 0.3-0.7；两端都惩罚。"""
    return max(0.0, 1.0 - 2.0 * abs(rate - 0.5))


def _score_diversity(speculations: list[SpeculativeInterest]) -> float:
    """评估推测在不同类别间的分散程度。

    将类别熵（在类别间的分布）与
    两两 domain 距离（domain 名称的差异程度）结合。
    """
    if len(speculations) <= 1:
        return 1.0

    # 1. 类别熵（唯一类别数越多 → 分数越高）
    categories = [s.category.strip().lower() for s in speculations if s.category.strip()]
    if categories:
        cat_counts: dict[str, int] = {}
        for cat in categories:
            cat_counts[cat] = cat_counts.get(cat, 0) + 1
        total = len(categories)
        entropy = -sum((c / total) * math.log2(c / total) for c in cat_counts.values() if c > 0)
        max_entropy = math.log2(total) if total > 1 else 1.0
        cat_score = entropy / max_entropy if max_entropy > 0 else 0.0
    else:
        cat_score = 0.0

    # 2. 两两 domain 距离（针对中文的字符级重叠）
    domains = [s.domain for s in speculations]
    pair_scores: list[float] = []
    for i in range(len(domains)):
        for j in range(i + 1, len(domains)):
            pair_scores.append(_domain_distance(domains[i], domains[j]))

    dist_score = sum(pair_scores) / len(pair_scores) if pair_scores else 1.0

    return round(cat_score * 0.5 + dist_score * 0.5, 4)


def _domain_distance(a: str, b: str) -> float:
    """两个 domain 名称之间的字符级距离。0=相同，1=无重叠。"""
    a_lower = re.sub(r"\s+", "", a.lower())
    b_lower = re.sub(r"\s+", "", b.lower())
    if not a_lower or not b_lower:
        return 1.0
    if a_lower == b_lower:
        return 0.0
    # 子串包含
    if a_lower in b_lower or b_lower in a_lower:
        shorter = min(len(a_lower), len(b_lower))
        longer = max(len(a_lower), len(b_lower))
        return min(1.0, (longer - shorter) / max(longer, 1) * 1.5)
    # 字符集重叠（中文无需分词即可工作）
    chars_a = set(a_lower)
    chars_b = set(b_lower)
    overlap = len(chars_a & chars_b) / max(len(chars_a | chars_b), 1)
    return 1.0 - overlap


async def _llm_eval_speculation(
    spec_domain: str,
    spec_reason: str,
    profile_context: str,
) -> dict[str, float]:
    """使用 LLM 对合理性、新颖性、具体性评分。"""
    try:
        from openbiliclaw.eval.agents import collect_json

        agent_options = import_module("claude_agent_sdk").ClaudeAgentOptions

        result = await collect_json(
            prompt=(
                f"评估以下推测兴趣的质量。\n\n"
                f"用户画像:\n{profile_context[:1000]}\n\n"
                f"推测方向: {spec_domain}\n"
                f"推理依据: {spec_reason}\n\n"
                f"请从三个维度评分 (0-1):\n"
                f"1. plausibility: 心理桥接推理是否合理？能否从已有兴趣自然推导出来？\n"
                f"2. novelty: 是否真正跨域？(0.1=已有兴趣的简单延伸, 0.9=创造性的交叉推理)\n"
                f"3. specificity: 能否在B站搜到这类内容？(0.1=太抽象, 0.9=可直接搜索)\n\n"
                f'{{"plausibility": 0.0, "novelty": 0.0, "specificity": 0.0, '
                f'"reasoning": "简要说明"}}'
            ),
            options=agent_options(
                system_prompt=(
                    "你是推测兴趣质量评估器。客观评分：完全合理=0.8+，"
                    "部分合理=0.5-0.7，不合理=0-0.4。只返回 JSON。"
                ),
                max_turns=1,
            ),
            max_retries=1,
            label="spec_llm_eval",
        )
        return {
            "plausibility": max(0.0, min(1.0, float(result.get("plausibility", 0.5)))),
            "novelty": max(0.0, min(1.0, float(result.get("novelty", 0.5)))),
            "specificity": max(0.0, min(1.0, float(result.get("specificity", 0.5)))),
        }
    except Exception:
        logger.warning("LLM eval failed for %s, using defaults", spec_domain)
        return {"plausibility": 0.5, "novelty": 0.5, "specificity": 0.5}


# ---------------------------------------------------------------------------
# SpeculationEvaluator
# ---------------------------------------------------------------------------


class SpeculationEvaluator:
    """评估推测兴趣生成质量。"""

    def __init__(self, *, dim_weights: dict[str, float] | None = None) -> None:
        self._weights = dim_weights or dict(_DIM_WEIGHTS)

    async def evaluate(
        self,
        speculations: list[SpeculativeInterest],
        profile: OnionProfile,
        confirmation_results: dict[str, bool] | None = None,
        persona_judgment: PersonaJudgment | None = None,
    ) -> SpeculationEvalReport:
        """对推测相对于画像进行全面自动化评估。

        Args:
            speculations: 待评估的生成推测兴趣。
            profile: 用于生成的人格画像。
            confirmation_results: 可选的 domain → promoted 映射，
                来自模拟事件观察。
            persona_judgment: 可选的 PersonaJudgment（来自 persona_judge）。
                提供时使用每个推测的共鸣分数。
                未提供时 persona_resonance 默认为 0.5。
        """
        if not speculations:
            return SpeculationEvalReport(timestamp=datetime.now().isoformat())

        # 收集已确认兴趣的 domain 用于幻觉检查
        confirmed_domains = [d.domain for d in profile.interest.likes]
        profile_ctx = profile.to_llm_context()

        # 从人格判断构建共鸣查找表
        resonance_map: dict[str, float] = {}
        if persona_judgment is not None:
            for verdict in persona_judgment.verdicts:
                resonance_map[verdict.domain] = verdict.resonance_score

        scores: list[SpeculationScore] = []
        for spec in speculations:
            # LLM 对合理性/新颖性/具体性评分
            llm_scores = await _llm_eval_speculation(
                spec.domain,
                spec.reason,
                profile_ctx,
            )
            # 算法化的非幻觉检查
            nh = _no_hallucination_score(spec.domain, confirmed_domains)
            # 人格共鸣
            resonance = resonance_map.get(spec.domain, 0.5)

            per_spec_overall = (
                llm_scores["plausibility"] * 0.30
                + llm_scores["novelty"] * 0.25
                + llm_scores["specificity"] * 0.15
                + nh * 0.10
                + resonance * 0.20
            )
            scores.append(
                SpeculationScore(
                    domain=spec.domain,
                    plausibility=llm_scores["plausibility"],
                    novelty=llm_scores["novelty"],
                    specificity=llm_scores["specificity"],
                    no_hallucination=nh,
                    persona_resonance=resonance,
                    overall=round(per_spec_overall, 4),
                )
            )

        # 确认率
        conf_rate = 0.5  # 无模拟数据时的默认值
        if confirmation_results:
            total = len(confirmation_results)
            promoted = sum(1 for v in confirmation_results.values() if v)
            conf_rate = promoted / total if total > 0 else 0.5
        conf_rate_score = _confirmation_rate_score(conf_rate)

        # 多样性（算法化）
        diversity = _score_diversity(speculations)

        # 均值
        n = len(scores)
        mean_p = sum(s.plausibility for s in scores) / n
        mean_n = sum(s.novelty for s in scores) / n
        mean_s = sum(s.specificity for s in scores) / n
        mean_nh = sum(s.no_hallucination for s in scores) / n
        mean_pr = sum(s.persona_resonance for s in scores) / n

        overall = (
            self._weights["plausibility"] * mean_p
            + self._weights["novelty"] * mean_n
            + self._weights["specificity"] * mean_s
            + self._weights["confirmation_rate"] * conf_rate_score
            + self._weights["no_hallucination"] * mean_nh
            + self._weights["diversity"] * diversity
            + self._weights["persona_resonance"] * mean_pr
        )

        # 最差维度
        dim_scores: list[tuple[str, float]] = [
            ("plausibility", mean_p),
            ("novelty", mean_n),
            ("specificity", mean_s),
            ("confirmation_rate", conf_rate_score),
            ("no_hallucination", mean_nh),
            ("diversity", diversity),
            ("persona_resonance", mean_pr),
        ]
        dim_scores.sort(key=lambda t: t[1])
        worst: list[dict[str, Any]] = [
            {"dimension": name, "score": score} for name, score in dim_scores[:3]
        ]

        attributions = [
            f"{d['dimension']} ({d['score']:.2f}) -> speculation_generation_prompt"
            for d in worst
            if d["score"] < 0.7
        ]

        return SpeculationEvalReport(
            speculation_scores=scores,
            confirmation_rate=round(conf_rate, 4),
            diversity_score=round(diversity, 4),
            mean_plausibility=round(mean_p, 4),
            mean_novelty=round(mean_n, 4),
            mean_specificity=round(mean_s, 4),
            mean_no_hallucination=round(mean_nh, 4),
            mean_persona_resonance=round(mean_pr, 4),
            overall_score=round(overall, 4),
            worst_dimensions=worst,
            attributions=attributions,
            timestamp=datetime.now().isoformat(),
        )

    async def evaluate_with_human(
        self,
        speculations: list[SpeculativeInterest],
        human_feedback: dict[str, dict[str, float]],
    ) -> SpeculationEvalReport:
        """根据人工逐推测反馈构建报告。

        human_feedback 格式：
        {
            "博弈论科普": {"plausibility": 0.8, "novelty": 0.6, "specificity": 0.9},
            ...
        }
        """
        scores: list[SpeculationScore] = []
        for spec in speculations:
            fb = human_feedback.get(spec.domain, {})
            if not isinstance(fb, dict):
                continue
            p = float(fb.get("plausibility", 0.5))
            n = float(fb.get("novelty", 0.5))
            s = float(fb.get("specificity", 0.5))
            pr = float(fb.get("persona_resonance", 0.5))
            per_overall = p * 0.30 + n * 0.25 + s * 0.15 + pr * 0.30
            scores.append(
                SpeculationScore(
                    domain=spec.domain,
                    plausibility=p,
                    novelty=n,
                    specificity=s,
                    no_hallucination=1.0,  # 人工审阅默认无幻觉
                    persona_resonance=pr,
                    overall=round(per_overall, 4),
                    details=str(fb.get("note", "")),
                )
            )

        if not scores:
            return SpeculationEvalReport(timestamp=datetime.now().isoformat())

        diversity = _score_diversity(speculations)
        count = len(scores)
        mean_p = sum(s.plausibility for s in scores) / count
        mean_n = sum(s.novelty for s in scores) / count
        mean_s = sum(s.specificity for s in scores) / count
        mean_pr = sum(s.persona_resonance for s in scores) / count
        overall = mean_p * 0.30 + mean_n * 0.20 + mean_s * 0.15 + mean_pr * 0.20 + diversity * 0.15

        human_dim_scores: list[tuple[str, float]] = [
            ("plausibility", mean_p),
            ("novelty", mean_n),
            ("specificity", mean_s),
            ("diversity", diversity),
            ("persona_resonance", mean_pr),
        ]
        human_dim_scores.sort(key=lambda t: t[1])
        worst_h: list[dict[str, Any]] = [
            {"dimension": name, "score": score} for name, score in human_dim_scores[:3]
        ]

        return SpeculationEvalReport(
            speculation_scores=scores,
            diversity_score=round(diversity, 4),
            mean_plausibility=round(mean_p, 4),
            mean_novelty=round(mean_n, 4),
            mean_specificity=round(mean_s, 4),
            mean_no_hallucination=1.0,
            mean_persona_resonance=round(mean_pr, 4),
            overall_score=round(overall, 4),
            worst_dimensions=worst_h,
            attributions=[
                f"{d['dimension']} ({d['score']:.2f}) -> speculation_generation_prompt"
                for d in worst_h
                if d["score"] < 0.7
            ],
            timestamp=datetime.now().isoformat(),
        )
