"""
BehaviorEvent 行为事件模型单元测试。
"""

import pytest
from datetime import datetime
from soul.event import BehaviorEvent


class TestBehaviorEvent:
    """BehaviorEvent 行为事件测试套件。"""

    def test_create_valid_event_dialogue(self):
        """测试创建 dialogue 类型事件"""
        event = BehaviorEvent(
            event_type="dialogue",
            content="用户询问Python问题",
            user_id="user_001",
        )
        assert event.event_type == "dialogue"
        assert event.content == "用户询问Python问题"
        assert event.user_id == "user_001"
        assert event.sentiment == "neutral"
        assert event.topics == []
        assert event.metadata == {}

    def test_create_valid_event_tool_call(self):
        """测试创建 tool_call 类型事件"""
        event = BehaviorEvent(
            event_type="tool_call",
            content="用户调用了搜索工具",
            user_id="user_002",
            sentiment="positive",
        )
        assert event.event_type == "tool_call"
        assert event.sentiment == "positive"

    def test_create_valid_event_content_consumption(self):
        """测试创建 content_consumption 类型事件"""
        event = BehaviorEvent(
            event_type="content_consumption",
            content="用户阅读了技术文章",
            user_id="user_003",
            sentiment="positive",
            topics=["技术", "Python"],
        )
        assert event.event_type == "content_consumption"
        assert event.topics == ["技术", "Python"]

    def test_create_valid_event_feedback(self):
        """测试创建 feedback 类型事件"""
        event = BehaviorEvent(
            event_type="feedback",
            content="用户给出了正面反馈",
            sentiment="positive",
        )
        assert event.event_type == "feedback"

    def test_create_event_invalid_type(self):
        """测试创建无效事件类型时抛出异常"""
        with pytest.raises(ValueError, match="无效的事件类型"):
            BehaviorEvent(event_type="invalid_type", content="测试")

    def test_create_event_invalid_sentiment(self):
        """测试创建无效情感类型时抛出异常"""
        with pytest.raises(ValueError, match="无效的情感类型"):
            BehaviorEvent(
                event_type="dialogue",
                content="测试",
                sentiment="angry",
            )

    def test_to_dict_and_from_dict(self):
        """测试序列化和反序列化"""
        event = BehaviorEvent(
            event_type="dialogue",
            content="测试内容",
            user_id="user_001",
            sentiment="positive",
            topics=["技术"],
            metadata={"source": "test"},
        )
        data = event.to_dict()
        restored = BehaviorEvent.from_dict(data)
        assert restored.event_type == "dialogue"
        assert restored.content == "测试内容"
        assert restored.user_id == "user_001"
        assert restored.sentiment == "positive"
        assert restored.topics == ["技术"]
        assert restored.metadata == {"source": "test"}

    def test_timestamp_is_datetime(self):
        """测试 timestamp 是 datetime 类型"""
        event = BehaviorEvent(event_type="dialogue", content="测试")
        assert isinstance(event.timestamp, datetime)

    def test_from_dict_with_defaults(self):
        """测试从缺少字段的字典创建事件"""
        data = {"event_type": "dialogue", "content": "测试"}
        restored = BehaviorEvent.from_dict(data)
        assert restored.event_type == "dialogue"
        assert restored.user_id == ""
        assert restored.sentiment == "neutral"
        assert restored.topics == []
        assert restored.metadata == {}

    def test_all_valid_event_types(self):
        """测试所有有效事件类型均可创建"""
        for event_type in BehaviorEvent.VALID_EVENT_TYPES:
            event = BehaviorEvent(event_type=event_type, content="测试")
            assert event.event_type == event_type

    def test_all_valid_sentiments(self):
        """测试所有有效情感类型均可创建"""
        for sentiment in BehaviorEvent.VALID_SENTIMENTS:
            event = BehaviorEvent(
                event_type="dialogue",
                content="测试",
                sentiment=sentiment,
            )
            assert event.sentiment == sentiment