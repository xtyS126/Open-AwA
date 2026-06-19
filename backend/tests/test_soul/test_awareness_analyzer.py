"""
AwarenessAnalyzer 觉察分析器单元测试。
"""

import pytest
from soul.event import BehaviorEvent
from soul.awareness_analyzer import AwarenessAnalyzer, AwarenessUpdate


class TestAwarenessUpdate:
    """AwarenessUpdate 数据模型测试套件。"""

    def test_create_awareness_update(self):
        """测试创建觉察更新"""
        update = AwarenessUpdate(
            pattern_type="frequent_behavior",
            description="用户频繁进行对话",
            confidence=0.6,
            evidence_count=5,
            metadata={"event_type": "dialogue", "count": 5},
        )
        assert update.pattern_type == "frequent_behavior"
        assert update.description == "用户频繁进行对话"
        assert update.confidence == 0.6
        assert update.evidence_count == 5
        assert update.metadata == {"event_type": "dialogue", "count": 5}


class TestAwarenessAnalyzer:
    """AwarenessAnalyzer 觉察分析器测试套件。"""

    @pytest.fixture
    def analyzer(self):
        """创建觉察分析器实例"""
        return AwarenessAnalyzer()

    def _create_dialogue_events(self, count: int, user_id: str = "user_001") -> list:
        """创建多个对话事件用于测试"""
        return [
            BehaviorEvent(
                event_type="dialogue",
                content=f"对话内容 {i}",
                user_id=user_id,
                sentiment="neutral",
            )
            for i in range(count)
        ]

    @pytest.mark.asyncio
    async def test_analyze_empty_events(self, analyzer):
        """测试分析空事件列表"""
        updates = await analyzer.analyze([])
        assert len(updates) == 0

    @pytest.mark.asyncio
    async def test_analyze_frequent_behavior_pattern(self, analyzer):
        """测试识别频繁行为模式（>=3次同类型事件）"""
        events = self._create_dialogue_events(5)
        updates = await analyzer.analyze(events)
        # 5次对话事件应触发 frequent_behavior 模式
        frequent_updates = [u for u in updates if u.pattern_type == "frequent_behavior"]
        assert len(frequent_updates) >= 1
        assert frequent_updates[0].evidence_count == 5

    @pytest.mark.asyncio
    async def test_analyze_sentiment_tendency_positive(self, analyzer):
        """测试识别积极情感倾向（>=60%相同情感）"""
        events = []
        for i in range(5):
            events.append(BehaviorEvent(
                event_type="dialogue",
                content=f"内容 {i}",
                user_id="user_001",
                sentiment="positive",
            ))
        for i in range(2):
            events.append(BehaviorEvent(
                event_type="dialogue",
                content=f"内容 {i+5}",
                user_id="user_001",
                sentiment="neutral",
            ))
        updates = await analyzer.analyze(events)
        sentiment_updates = [u for u in updates if u.pattern_type == "sentiment_tendency"]
        assert len(sentiment_updates) >= 1
        assert sentiment_updates[0].metadata["sentiment"] == "positive"

    @pytest.mark.asyncio
    async def test_analyze_insufficient_events(self, analyzer):
        """测试事件不足时不会触发频繁行为模式"""
        events = self._create_dialogue_events(2)
        updates = await analyzer.analyze(events)
        # 2次事件不足以触发 frequent_behavior（需要>=3）
        frequent_updates = [u for u in updates if u.pattern_type == "frequent_behavior"]
        assert len(frequent_updates) == 0

    @pytest.mark.asyncio
    async def test_analyze_mixed_sentiments_no_tendency(self, analyzer):
        """测试混合情感不触发情感倾向"""
        events = [
            BehaviorEvent(
                event_type="dialogue",
                content="内容1",
                user_id="user_001",
                sentiment="positive",
            ),
            BehaviorEvent(
                event_type="dialogue",
                content="内容2",
                user_id="user_001",
                sentiment="negative",
            ),
            BehaviorEvent(
                event_type="dialogue",
                content="内容3",
                user_id="user_001",
                sentiment="neutral",
            ),
        ]
        updates = await analyzer.analyze(events)
        # 不存在超过60%的情感，不应触发情感倾向
        sentiment_updates = [u for u in updates if u.pattern_type == "sentiment_tendency"]
        assert len(sentiment_updates) == 0

    @pytest.mark.asyncio
    async def test_analyze_confidence_increases_with_events(self, analyzer):
        """测试置信度随事件数量增加而增加"""
        # 3个事件
        events_3 = self._create_dialogue_events(3)
        updates_3 = await analyzer.analyze(events_3)
        freq_3 = [u for u in updates_3 if u.pattern_type == "frequent_behavior"]
        assert len(freq_3) >= 1

        # 创建新分析器，7个事件
        new_analyzer = AwarenessAnalyzer()
        events_7 = self._create_dialogue_events(7)
        updates_7 = await new_analyzer.analyze(events_7)
        freq_7 = [u for u in updates_7 if u.pattern_type == "frequent_behavior"]
        assert len(freq_7) >= 1
        # 更多事件应有更高置信度
        assert freq_7[0].confidence >= freq_3[0].confidence