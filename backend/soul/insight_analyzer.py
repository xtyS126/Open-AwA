"""
洞察分析器（第三层分析）。
基于浅层画像推断深层心理特征，包括 MBTI 和认知风格推断。
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from loguru import logger
from soul.profile import OnionProfile


@dataclass
class InsightUpdate:
    """洞察更新结果"""
    # 洞察类型：mbti（性格类型）/cognitive_style（认知风格）/psychological_trait（心理特征）
    insight_type: str
    # 洞察值
    value: str
    # 洞察描述
    description: str
    # 置信度（0.0-1.0）
    confidence: float
    # 推断依据
    reasoning: str
    # 额外信息
    metadata: Dict[str, Any] = field(default_factory=dict)


class InsightAnalyzer:
    """
    洞察分析器。
    基于浅层画像（surface、interest、role、values）推断深层心理特征。
    """

    # MBTI 推断规则（基于行为模式的关键词映射）
    MBTI_RULES = {
        "INTJ": {
            "keywords": ["战略", "独立", "系统", "架构", "规划", "分析", "逻辑"],
            "weight": 0.0,
        },
        "INTP": {
            "keywords": ["创新", "理论", "探索", "抽象", "概念", "好奇", "研究"],
            "weight": 0.0,
        },
        "ENTJ": {
            "keywords": ["领导", "决策", "目标", "效率", "组织", "管理", "执行"],
            "weight": 0.0,
        },
        "INFJ": {
            "keywords": ["理想", "意义", "洞察", "和谐", "成长", "帮助", "理解"],
            "weight": 0.0,
        },
        "ISTJ": {
            "keywords": ["务实", "可靠", "细节", "规则", "稳定", "传统", "计划"],
            "weight": 0.0,
        },
    }

    # 认知风格推断规则
    COGNITIVE_RULES = {
        "analytical": {
            "keywords": ["分析", "逻辑", "数据", "推理", "论证", "系统性"],
            "description": "分析型 - 善于逻辑推理和系统性思考",
        },
        "creative": {
            "keywords": ["创意", "创新", "灵感", "想象", "设计", "艺术"],
            "description": "创造型 - 善于发散思维和创新构想",
        },
        "practical": {
            "keywords": ["实践", "动手", "工程", "实现", "解决", "操作"],
            "description": "实践型 - 善于动手操作和解决实际问题",
        },
    }

    async def analyze(self, profile: OnionProfile) -> List[InsightUpdate]:
        """
        基于画像推断深层心理特征。

        Args:
            profile: 用户五层画像

        Returns:
            List[InsightUpdate]: 洞察更新列表
        """
        updates = []

        if not profile:
            return updates

        # 收集所有层的描述文本
        all_text = " ".join([
            profile.surface.description,
            profile.interest.description,
            profile.role.description,
            profile.values.description,
        ])

        if not all_text.strip():
            return updates

        # 1. 推断 MBTI
        mbti_update = self._infer_mbti(all_text)
        if mbti_update:
            updates.append(mbti_update)

        # 2. 推断认知风格
        cognitive_update = self._infer_cognitive_style(all_text)
        if cognitive_update:
            updates.append(cognitive_update)

        if updates:
            logger.bind(
                user_id=profile.user_id,
                update_count=len(updates),
            ).debug("洞察分析完成")

        return updates

    def _infer_mbti(self, text: str) -> Optional[InsightUpdate]:
        """基于文本推断 MBTI"""
        scores = {}
        for mbti_type, rules in self.MBTI_RULES.items():
            score = 0
            for keyword in rules["keywords"]:
                if keyword in text:
                    score += 1
            scores[mbti_type] = score

        if not scores:
            return None

        best_mbti = max(scores, key=scores.get)
        best_score = scores[best_mbti]

        if best_score < 2:  # 至少匹配2个关键词
            return None

        confidence = min(0.3 + best_score * 0.1, 0.7)

        return InsightUpdate(
            insight_type="mbti",
            value=best_mbti,
            description=f"推断 MBTI 类型为 {best_mbti}",
            confidence=confidence,
            reasoning=f"基于画像文本中匹配到 {best_score} 个 {best_mbti} 相关的关键词",
            metadata={"matched_keywords": best_score, "all_scores": scores},
        )

    def _infer_cognitive_style(self, text: str) -> Optional[InsightUpdate]:
        """基于文本推断认知风格"""
        scores = {}
        for style, rules in self.COGNITIVE_RULES.items():
            score = 0
            for keyword in rules["keywords"]:
                if keyword in text:
                    score += 1
            scores[style] = score

        if not scores:
            return None

        best_style = max(scores, key=scores.get)
        best_score = scores[best_style]

        if best_score < 2:
            return None

        confidence = min(0.3 + best_score * 0.1, 0.7)

        return InsightUpdate(
            insight_type="cognitive_style",
            value=best_style,
            description=self.COGNITIVE_RULES[best_style]["description"],
            confidence=confidence,
            reasoning=f"基于画像文本中匹配到 {best_score} 个 {best_style} 相关的关键词",
            metadata={"matched_keywords": best_score, "all_scores": scores},
        )