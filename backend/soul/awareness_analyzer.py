"""
觉察分析器（第二层分析）。
识别用户行为模式，从偏好中提取觉察层面的认知。
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List
from loguru import logger
from soul.event import BehaviorEvent


@dataclass
class AwarenessUpdate:
    """觉察更新结果"""
    # 行为模式类型
    pattern_type: str
    # 模式描述
    description: str
    # 置信度（0.0-1.0）
    confidence: float
    # 支持此模式的事件数量
    evidence_count: int
    # 额外信息
    metadata: Dict[str, Any] = field(default_factory=dict)


class AwarenessAnalyzer:
    """
    觉察分析器。
    从多个行为事件中识别重复模式，形成对用户行为的觉察认知。
    """

    def __init__(self):
        self._event_buffer: Dict[str, List[BehaviorEvent]] = {}

    async def analyze(self, events: List[BehaviorEvent]) -> List[AwarenessUpdate]:
        """
        分析一组行为事件，识别行为模式。

        Args:
            events: 行为事件列表

        Returns:
            List[AwarenessUpdate]: 觉察更新列表
        """
        updates = []

        if not events:
            return updates

        # 1. 按事件类型统计
        type_counts = self._count_event_types(events)
        for event_type, count in type_counts.items():
            if count >= 3:  # 同一类型事件出现3次以上形成模式
                updates.append(AwarenessUpdate(
                    pattern_type="frequent_behavior",
                    description=f"用户频繁进行 {event_type} 类型的操作（{count}次）",
                    confidence=min(0.3 + count * 0.1, 0.8),
                    evidence_count=count,
                    metadata={"event_type": event_type, "count": count},
                ))

        # 2. 按情感倾向分析
        sentiment_counts = self._count_sentiments(events)
        dominant_sentiment = max(sentiment_counts, key=sentiment_counts.get)
        if sentiment_counts[dominant_sentiment] >= len(events) * 0.6:
            sentiment_name = {"positive": "积极", "negative": "消极", "neutral": "中性"}.get(dominant_sentiment, dominant_sentiment)
            updates.append(AwarenessUpdate(
                pattern_type="sentiment_tendency",
                description=f"用户近期呈现{sentiment_name}倾向",
                confidence=min(0.4 + sentiment_counts[dominant_sentiment] * 0.05, 0.7),
                evidence_count=sentiment_counts[dominant_sentiment],
                metadata={"sentiment": dominant_sentiment, "count": sentiment_counts[dominant_sentiment]},
            ))

        if updates:
            logger.bind(
                user_id=events[0].user_id if events else "",
                event_count=len(events),
                update_count=len(updates),
            ).debug("觉察分析完成")

        return updates

    def _count_event_types(self, events: List[BehaviorEvent]) -> Dict[str, int]:
        """统计事件类型分布"""
        counts: Dict[str, int] = {}
        for event in events:
            counts[event.event_type] = counts.get(event.event_type, 0) + 1
        return counts

    def _count_sentiments(self, events: List[BehaviorEvent]) -> Dict[str, int]:
        """统计情感分布"""
        counts: Dict[str, int] = {"positive": 0, "negative": 0, "neutral": 0}
        for event in events:
            if event.sentiment in counts:
                counts[event.sentiment] += 1
        return counts