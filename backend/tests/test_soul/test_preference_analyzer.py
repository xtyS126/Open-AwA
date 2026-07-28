"""
PreferenceAnalyzer 偏好分析器单元测试。
"""

import pytest
from soul.event import BehaviorEvent
from soul.preference_analyzer import PreferenceAnalyzer, PreferenceUpdate


class TestPreferenceUpdate:
    """PreferenceUpdate 数据模型测试套件。"""

    def test_create_preference_update(self):
        """测试创建偏好更新"""
        update = PreferenceUpdate(
            preference_type="like",
            target="编程",
            detail="用户喜欢编程",
            confidence=0.8,
            source_event_type="dialogue",
        )
        assert update.preference_type == "like"
        assert update.target == "编程"
        assert update.detail == "用户喜欢编程"
        assert update.confidence == 0.8
        assert update.source_event_type == "dialogue"
        assert update.metadata == {}


class TestPreferenceAnalyzer:
    """PreferenceAnalyzer 偏好分析器测试套件。"""

    @pytest.fixture
    def analyzer(self):
        """创建偏好分析器实例"""
        return PreferenceAnalyzer()

    @pytest.mark.asyncio
    async def test_analyze_positive_keywords(self, analyzer):
        """测试识别积极关键词"""
        event = BehaviorEvent(
            event_type="dialogue",
            content="这个工具非常好用，我很喜欢它的简洁设计",
            user_id="user_001",
            sentiment="positive",
        )
        updates = await analyzer.analyze(event)
        assert len(updates) >= 1
        # 应包含 like 类型的更新
        like_updates = [u for u in updates if u.preference_type == "like"]
        assert len(like_updates) >= 1
        assert like_updates[0].confidence == 0.6

    @pytest.mark.asyncio
    async def test_analyze_negative_keywords(self, analyzer):
        """测试识别消极关键词"""
        event = BehaviorEvent(
            event_type="dialogue",
            content="这个功能太难用了，我很讨厌这种设计",
            user_id="user_001",
            sentiment="negative",
        )
        updates = await analyzer.analyze(event)
        assert len(updates) >= 1
        # 应包含 dislike 类型的更新
        dislike_updates = [u for u in updates if u.preference_type == "dislike"]
        assert len(dislike_updates) >= 1
        assert dislike_updates[0].confidence == 0.6

    @pytest.mark.asyncio
    async def test_analyze_tool_call_event(self, analyzer):
        """测试分析工具调用事件"""
        event = BehaviorEvent(
            event_type="tool_call",
            content="用户使用了代码搜索工具查找Python相关代码",
            user_id="user_001",
        )
        updates = await analyzer.analyze(event)
        # 工具调用应产生 like 偏好（基于事件类型）
        tool_updates = [u for u in updates if u.target == "tool_usage"]
        assert len(tool_updates) >= 1
        assert tool_updates[0].confidence == 0.4

    @pytest.mark.asyncio
    async def test_analyze_content_consumption_positive(self, analyzer):
        """测试分析正面内容消费事件"""
        event = BehaviorEvent(
            event_type="content_consumption",
            content="用户阅读了深度学习教程",
            user_id="user_001",
            sentiment="positive",
        )
        updates = await analyzer.analyze(event)
        content_updates = [u for u in updates if u.target == "content"]
        assert len(content_updates) >= 1
        assert content_updates[0].preference_type == "like"

    @pytest.mark.asyncio
    async def test_analyze_content_consumption_negative(self, analyzer):
        """测试分析负面内容消费事件"""
        event = BehaviorEvent(
            event_type="content_consumption",
            content="用户阅读了一篇低质量文章",
            user_id="user_001",
            sentiment="negative",
        )
        updates = await analyzer.analyze(event)
        content_updates = [u for u in updates if u.target == "content"]
        assert len(content_updates) >= 1
        assert content_updates[0].preference_type == "dislike"

    @pytest.mark.asyncio
    async def test_analyze_no_keywords(self, analyzer):
        """测试无关键词匹配的内容"""
        event = BehaviorEvent(
            event_type="dialogue",
            content="今天天气怎么样",
            user_id="user_001",
        )
        updates = await analyzer.analyze(event)
        # 关键词无匹配，但 dialogue 类型不产生基于类型的更新
        # 所以应返回空列表
        assert len(updates) == 0

    @pytest.mark.asyncio
    async def test_analyze_empty_content(self, analyzer):
        """测试空内容事件"""
        event = BehaviorEvent(
            event_type="dialogue",
            content="",
            user_id="user_001",
        )
        updates = await analyzer.analyze(event)
        assert len(updates) == 0

    @pytest.mark.asyncio
    async def test_analyze_multiple_keywords(self, analyzer):
        """测试同时包含积极和消极关键词"""
        event = BehaviorEvent(
            event_type="dialogue",
            content="这个工具好用但是有些功能难用",
            user_id="user_001",
        )
        updates = await analyzer.analyze(event)
        # 应同时包含 like 和 dislike
        types = {u.preference_type for u in updates}
        assert "like" in types
        assert "dislike" in types