"""
偏好分析器（第一层分析）。
从行为事件中提取用户的偏好表达（喜欢/不喜欢/中性）。
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from loguru import logger
from soul.event import BehaviorEvent


@dataclass
class PreferenceUpdate:
    """偏好更新结果"""
    # 偏好类型：like（喜欢）/dislike（不喜欢）/neutral（中性）
    preference_type: str
    # 偏好目标（如 "编程语言"、"音乐类型"）
    target: str
    # 偏好详情
    detail: str
    # 置信度（0.0-1.0）
    confidence: float
    # 来源事件类型
    source_event_type: str
    # 额外信息
    metadata: Dict[str, Any] = field(default_factory=dict)


class PreferenceAnalyzer:
    """
    偏好分析器。
    从用户行为事件中提取偏好表达，用于更新画像的 surface 和 interest 层。
    """

    # 积极关键词
    POSITIVE_KEYWORDS = {
        "喜欢", "热爱", "推荐", "好用", "方便", "优秀", "出色", "不错",
        "高效", "简洁", "优雅", "强大", "实用", "有趣", "满意", "棒",
    }

    # 消极关键词
    NEGATIVE_KEYWORDS = {
        "不喜欢", "讨厌", "不推荐", "难用", "麻烦", "差", "糟糕", "不好",
        "低效", "复杂", "冗余", "弱", "没用", "无聊", "不满意", "差劲",
    }

    async def analyze(self, event: BehaviorEvent) -> List[PreferenceUpdate]:
        """
        分析行为事件，提取偏好表达。

        Args:
            event: 用户行为事件

        Returns:
            List[PreferenceUpdate]: 偏好更新列表
        """
        updates = []

        # 1. 基于关键词的简单分析
        keyword_updates = self._analyze_by_keywords(event)
        updates.extend(keyword_updates)

        # 2. 基于事件类型的分析
        type_updates = self._analyze_by_event_type(event)
        updates.extend(type_updates)

        if updates:
            logger.bind(
                event_type=event.event_type,
                user_id=event.user_id,
                update_count=len(updates),
            ).debug("偏好分析完成")

        return updates

    def _analyze_by_keywords(self, event: BehaviorEvent) -> List[PreferenceUpdate]:
        """基于关键词的偏好分析"""
        updates = []
        content_lower = event.content.lower()

        # 检测积极关键词
        found_positive = [kw for kw in self.POSITIVE_KEYWORDS if kw in content_lower]
        if found_positive:
            updates.append(PreferenceUpdate(
                preference_type="like",
                target=event.event_type,
                detail=f"用户表达了正面评价: {', '.join(found_positive[:3])}",
                confidence=0.6,
                source_event_type=event.event_type,
                metadata={"keywords": found_positive[:5]},
            ))

        # 检测消极关键词
        found_negative = [kw for kw in self.NEGATIVE_KEYWORDS if kw in content_lower]
        if found_negative:
            updates.append(PreferenceUpdate(
                preference_type="dislike",
                target=event.event_type,
                detail=f"用户表达了负面评价: {', '.join(found_negative[:3])}",
                confidence=0.6,
                source_event_type=event.event_type,
                metadata={"keywords": found_negative[:5]},
            ))

        return updates

    def _analyze_by_event_type(self, event: BehaviorEvent) -> List[PreferenceUpdate]:
        """基于事件类型的偏好分析"""
        updates = []

        if event.event_type == "tool_call":
            updates.append(PreferenceUpdate(
                preference_type="like",
                target="tool_usage",
                detail=f"用户使用了工具: {event.content[:100]}",
                confidence=0.4,
                source_event_type=event.event_type,
            ))

        elif event.event_type == "content_consumption":
            sentiment = event.sentiment
            pref_type = "like" if sentiment == "positive" else "dislike" if sentiment == "negative" else "neutral"
            updates.append(PreferenceUpdate(
                preference_type=pref_type,
                target="content",
                detail=f"用户消费内容: {event.content[:100]}",
                confidence=0.5,
                source_event_type=event.event_type,
            ))

        return updates