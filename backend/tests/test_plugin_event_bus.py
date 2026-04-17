"""
插件事件总线的单元测试。
覆盖事件订阅、发布、优先级、取消订阅和错误处理逻辑。
"""

import pytest

from plugins.event_bus import PluginEventBus, EventResult


class TestPluginEventBus:
    """测试 PluginEventBus"""

    def setup_method(self):
        """每个测试方法前创建新的事件总线实例"""
        self.bus = PluginEventBus()

    def test_subscribe_and_emit(self):
        """订阅事件后触发应调用处理器"""
        received = []

        def handler(data):
            received.append(data)

        self.bus.subscribe("test:event", "plugin_a", handler)
        result = self.bus.emit("test:event", {"key": "value"})

        assert result.handler_count == 1
        assert result.success is True
        assert len(received) == 1
        assert received[0]["key"] == "value"

    def test_emit_no_subscribers(self):
        """触发无订阅者的事件应返回空结果"""
        result = self.bus.emit("unknown:event", {"key": "value"})
        assert result.handler_count == 0
        assert result.success is True

    def test_emit_with_none_data(self):
        """触发事件时未传入数据应默认传空字典"""
        received = []

        def handler(data):
            received.append(data)

        self.bus.subscribe("test:event", "plugin_a", handler)
        self.bus.emit("test:event")

        assert len(received) == 1
        assert received[0] == {}

    def test_priority_ordering(self):
        """高优先级处理器应先于低优先级执行"""
        order = []

        def low_handler(data):
            order.append("low")

        def high_handler(data):
            order.append("high")

        def medium_handler(data):
            order.append("medium")

        self.bus.subscribe("test:event", "plugin_low", low_handler, priority=1)
        self.bus.subscribe("test:event", "plugin_high", high_handler, priority=10)
        self.bus.subscribe("test:event", "plugin_medium", medium_handler, priority=5)

        self.bus.emit("test:event")

        assert order == ["high", "medium", "low"]

    def test_unsubscribe_specific_event(self):
        """取消特定事件订阅后不再触发"""
        received = []

        def handler(data):
            received.append("called")

        self.bus.subscribe("test:event", "plugin_a", handler)
        removed = self.bus.unsubscribe("test:event", "plugin_a")
        assert removed == 1

        self.bus.emit("test:event")
        assert len(received) == 0

    def test_unsubscribe_all(self):
        """取消插件全部订阅"""
        received_a = []
        received_b = []

        self.bus.subscribe("event_1", "plugin_a", lambda d: received_a.append("e1"))
        self.bus.subscribe("event_2", "plugin_a", lambda d: received_a.append("e2"))
        self.bus.subscribe("event_1", "plugin_b", lambda d: received_b.append("e1"))

        total = self.bus.unsubscribe_all("plugin_a")
        assert total == 2

        self.bus.emit("event_1")
        self.bus.emit("event_2")

        assert len(received_a) == 0
        assert len(received_b) == 1

    def test_handler_error_isolation(self):
        """单个处理器异常不影响其他处理器执行"""
        results = []

        def error_handler(data):
            raise ValueError("test error")

        def ok_handler(data):
            results.append("ok")

        self.bus.subscribe("test:event", "plugin_error", error_handler, priority=10)
        self.bus.subscribe("test:event", "plugin_ok", ok_handler, priority=1)

        result = self.bus.emit("test:event")

        assert result.handler_count == 2
        assert result.success is False
        assert len(result.errors) == 1
        assert result.errors[0]["plugin_name"] == "plugin_error"
        assert len(results) == 1

    def test_multiple_handlers_same_plugin(self):
        """同一插件可多次订阅同一事件"""
        count = []

        self.bus.subscribe("test:event", "plugin_a", lambda d: count.append(1))
        self.bus.subscribe("test:event", "plugin_a", lambda d: count.append(2))

        self.bus.emit("test:event")
        assert len(count) == 2

    def test_list_events(self):
        """列出所有已注册事件"""
        self.bus.subscribe("event_1", "plugin_a", lambda d: None)
        self.bus.subscribe("event_2", "plugin_b", lambda d: None)

        events = self.bus.list_events()
        assert "event_1" in events
        assert "event_2" in events
        assert events["event_1"][0]["plugin_name"] == "plugin_a"

    def test_list_plugin_subscriptions(self):
        """列出指定插件的所有订阅"""
        self.bus.subscribe("event_1", "plugin_a", lambda d: None)
        self.bus.subscribe("event_2", "plugin_a", lambda d: None)
        self.bus.subscribe("event_1", "plugin_b", lambda d: None)

        subs = self.bus.list_plugin_subscriptions("plugin_a")
        assert len(subs) == 2
        event_names = {s["event_name"] for s in subs}
        assert event_names == {"event_1", "event_2"}

    def test_event_result_to_dict(self):
        """EventResult 序列化正常"""
        self.bus.subscribe("test:event", "plugin_a", lambda d: "result")
        result = self.bus.emit("test:event")

        result_dict = result.to_dict()
        assert result_dict["event_name"] == "test:event"
        assert result_dict["handler_count"] == 1
        assert result_dict["success"] is True

    def test_handler_return_value_captured(self):
        """处理器返回值应被捕获"""
        def handler(data):
            return {"processed": True}

        self.bus.subscribe("test:event", "plugin_a", handler)
        result = self.bus.emit("test:event")

        assert len(result.results) == 1
        assert result.results[0]["result"] == {"processed": True}
