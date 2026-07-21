"""
兴趣推测器。
基于用户画像推测潜在兴趣，生成待确认的兴趣假设。
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from soul.profile import OnionProfile
from soul.taxonomy import INTEREST_CATEGORIES, get_all_categories


@dataclass
class InterestHypothesis:
    """兴趣假设"""
    # 假设内容
    hypothesis: str
    # 兴趣类别（如 "技术"、"运动"）
    category: str
    # 置信度（0.0-1.0）
    confidence: float
    # 推测依据
    reasoning: str
    # 探针问题（用于确认）
    probe_question: str = ""
    # 额外信息
    metadata: Dict[str, Any] = field(default_factory=dict)


class InterestSpeculator:
    """
    兴趣推测器。
    基于用户画像内容推测潜在的、尚未明确的兴趣领域。
    """

    # 推测规则：基于画像关键词匹配兴趣类别
    SPECULATION_RULES: Dict[str, List[str]] = {
        "技术": ["编程", "开发", "代码", "算法", "架构", "开源", "AI", "人工智能"],
        "艺术": ["设计", "绘画", "音乐", "摄影", "创意", "美学", "艺术"],
        "游戏": ["游戏", "电竞", "主机", "PC游戏", "手游", "桌游"],
        "运动": ["运动", "健身", "跑步", "锻炼", "户外", "体育"],
        "科学": ["科学", "研究", "实验", "数据", "分析", "理论"],
        "商业": ["创业", "投资", "商业", "市场", "产品", "运营"],
        "教育": ["学习", "阅读", "课程", "知识", "技能", "培训"],
    }

    def speculate(self, profile: OnionProfile) -> List[InterestHypothesis]:
        """
        基于画像推测潜在兴趣。

        Args:
            profile: 用户五层画像

        Returns:
            List[InterestHypothesis]: 兴趣假设列表
        """
        hypotheses = []

        if not profile:
            return hypotheses

        # 收集画像文本
        profile_text = profile.get_summary().lower()

        if not profile_text:
            return hypotheses

        # 1. 基于关键词匹配推测
        for category, keywords in self.SPECULATION_RULES.items():
            matched = [kw for kw in keywords if kw in profile_text]
            if matched:
                confidence = min(0.3 + len(matched) * 0.1, 0.8)
                hypotheses.append(InterestHypothesis(
                    hypothesis=f"用户可能对 {category} 领域感兴趣",
                    category=category,
                    confidence=confidence,
                    reasoning=f"画像中匹配到关键词: {', '.join(matched[:5])}",
                    probe_question=self._generate_probe_question(category),
                    metadata={"matched_keywords": matched},
                ))

        # 2. 基于兴趣层已有内容推测相邻领域
        existing_interests = profile.interest.structured_data.get("likes", [])
        for interest in existing_interests:
            adjacent = self._find_adjacent_categories(interest)
            for adj in adjacent:
                if not any(h.category == adj for h in hypotheses):
                    hypotheses.append(InterestHypothesis(
                        hypothesis=f"用户可能对 {adj} 领域也感兴趣（基于对 {interest} 的兴趣）",
                        category=adj,
                        confidence=0.3,
                        reasoning=f"基于对 {interest} 的兴趣推测相邻领域",
                        probe_question=self._generate_probe_question(adj),
                    ))

        return hypotheses

    def _find_adjacent_categories(self, keyword: str) -> List[str]:
        """寻找相邻的兴趣类别"""
        keyword_lower = keyword.lower()
        # 相邻关系映射
        adjacent_map = {
            "编程": ["技术", "游戏", "教育"],
            "音乐": ["艺术", "娱乐"],
            "设计": ["艺术", "技术"],
            "健身": ["运动", "生活"],
            "阅读": ["教育", "艺术"],
            "投资": ["商业", "科学"],
        }
        for trigger, adjacents in adjacent_map.items():
            if trigger in keyword_lower:
                return adjacents
        return []

    def _generate_probe_question(self, category: str) -> str:
        """生成探针问题"""
        questions = {
            "技术": "您平时会关注哪些技术领域的最新动态？",
            "艺术": "您对艺术创作或欣赏有特别的偏好吗？",
            "游戏": "您喜欢玩什么类型的游戏？",
            "运动": "您有保持运动的习惯吗？",
            "科学": "您对科学研究和探索感兴趣吗？",
            "商业": "您对创业或商业运作感兴趣吗？",
            "教育": "您最近在学习什么新技能吗？",
        }
        return questions.get(category, f"您对 {category} 领域感兴趣吗？")