"""
插件上下文注入和依赖解析器的单元测试。
"""

import pytest

from plugins.plugin_context import PluginContext, build_plugin_context
from plugins.dependency_resolver import DependencyResolver, DependencyNode


class TestPluginContext:
    """测试 PluginContext 数据类"""

    def test_empty_context(self):
        """空上下文应有合理默认值"""
        ctx = PluginContext()
        assert ctx.user == {}
        assert ctx.db_session_factory is None
        assert ctx.event_bus is None
        assert ctx.get_user_id() is None
        assert ctx.get_username() is None
        assert ctx.get_user_role() is None

    def test_context_with_user(self):
        """注入用户信息后应正确读取"""
        ctx = PluginContext(user={"id": "u1", "username": "alice", "role": "admin"})
        assert ctx.get_user_id() == "u1"
        assert ctx.get_username() == "alice"
        assert ctx.get_user_role() == "admin"

    def test_get_db_session_raises_without_factory(self):
        """未注入数据库工厂时获取会话应抛出异常"""
        ctx = PluginContext()
        with pytest.raises(RuntimeError, match="未注入数据库会话工厂"):
            ctx.get_db_session()

    def test_get_db_session_with_factory(self):
        """注入数据库工厂后应正常返回会话"""
        mock_session = {"mock": True}
        ctx = PluginContext(db_session_factory=lambda: mock_session)
        session = ctx.get_db_session()
        assert session == mock_session

    def test_emit_event_without_bus(self):
        """无事件总线时 emit_event 应返回 None"""
        ctx = PluginContext()
        result = ctx.emit_event("test:event", {"key": "value"})
        assert result is None

    def test_emit_event_with_bus(self):
        """有事件总线时 emit_event 应正常转发"""
        from plugins.event_bus import PluginEventBus
        bus = PluginEventBus()
        received = []
        bus.subscribe("test:event", "test_plugin", lambda d: received.append(d))

        ctx = PluginContext(event_bus=bus)
        ctx.emit_event("test:event", {"key": "value"})

        assert len(received) == 1
        assert received[0]["key"] == "value"

    def test_to_dict_hides_sensitive_fields(self):
        """序列化应隐藏 password_hash 等敏感字段"""
        ctx = PluginContext(
            user={"id": "u1", "username": "alice", "password_hash": "secret"},
            metadata={"request_id": "req-123"},
        )
        d = ctx.to_dict()
        assert "password_hash" not in d["user"]
        assert d["user"]["username"] == "alice"
        assert "request_id" in d["metadata_keys"]


class TestBuildPluginContext:
    """测试 build_plugin_context 工厂函数"""

    def test_build_from_dict(self):
        """从字典构建上下文"""
        ctx = build_plugin_context(
            user={"id": "u1", "username": "bob", "role": "user"},
            plugin_config={"key": "value"},
        )
        assert ctx.get_username() == "bob"
        assert ctx.plugin_config["key"] == "value"

    def test_build_from_orm_object(self):
        """从 ORM 风格对象构建上下文"""
        class MockUser:
            id = "u2"
            username = "charlie"
            role = "admin"

        ctx = build_plugin_context(user=MockUser())
        assert ctx.get_user_id() == "u2"
        assert ctx.get_username() == "charlie"
        assert ctx.get_user_role() == "admin"

    def test_build_with_none_user(self):
        """不传用户时上下文 user 应为空"""
        ctx = build_plugin_context()
        assert ctx.user == {}


class TestDependencyResolver:
    """测试 DependencyResolver"""

    def setup_method(self):
        self.resolver = DependencyResolver()

    def test_no_dependencies(self):
        """无依赖的插件按任意顺序加载"""
        plugins = {
            "a": DependencyNode(name="a", version="1.0.0"),
            "b": DependencyNode(name="b", version="1.0.0"),
        }
        result = self.resolver.resolve(plugins)
        assert result.success is True
        assert set(result.load_order) == {"a", "b"}

    def test_linear_dependency_chain(self):
        """线性依赖链应正确排序"""
        plugins = {
            "a": DependencyNode(name="a", version="1.0.0"),
            "b": DependencyNode(name="b", version="1.0.0", dependencies=["a"]),
            "c": DependencyNode(name="c", version="1.0.0", dependencies=["b"]),
        }
        result = self.resolver.resolve(plugins)
        assert result.success is True
        assert result.load_order.index("a") < result.load_order.index("b")
        assert result.load_order.index("b") < result.load_order.index("c")

    def test_diamond_dependency(self):
        """菱形依赖应正确排序"""
        plugins = {
            "base": DependencyNode(name="base", version="1.0.0"),
            "left": DependencyNode(name="left", version="1.0.0", dependencies=["base"]),
            "right": DependencyNode(name="right", version="1.0.0", dependencies=["base"]),
            "top": DependencyNode(name="top", version="1.0.0", dependencies=["left", "right"]),
        }
        result = self.resolver.resolve(plugins)
        assert result.success is True
        assert result.load_order.index("base") < result.load_order.index("left")
        assert result.load_order.index("base") < result.load_order.index("right")
        assert result.load_order.index("left") < result.load_order.index("top")
        assert result.load_order.index("right") < result.load_order.index("top")

    def test_missing_dependency(self):
        """缺失依赖应报告冲突"""
        plugins = {
            "a": DependencyNode(name="a", version="1.0.0", dependencies=["nonexistent"]),
        }
        result = self.resolver.resolve(plugins)
        assert result.success is False
        assert len(result.conflicts) == 1
        assert result.conflicts[0].missing_dependency == "nonexistent"

    def test_circular_dependency(self):
        """循环依赖应报告冲突"""
        plugins = {
            "a": DependencyNode(name="a", version="1.0.0", dependencies=["b"]),
            "b": DependencyNode(name="b", version="1.0.0", dependencies=["c"]),
            "c": DependencyNode(name="c", version="1.0.0", dependencies=["a"]),
        }
        result = self.resolver.resolve(plugins)
        assert result.success is False
        assert len(result.conflicts) == 1
        assert result.conflicts[0].circular_path is not None

    def test_partial_circular_dependency(self):
        """部分循环依赖不影响无循环的部分"""
        plugins = {
            "independent": DependencyNode(name="independent", version="1.0.0"),
            "a": DependencyNode(name="a", version="1.0.0", dependencies=["b"]),
            "b": DependencyNode(name="b", version="1.0.0", dependencies=["a"]),
        }
        result = self.resolver.resolve(plugins)
        assert result.success is False
        # 冲突应只涉及循环部分
        conflict_names = set()
        for c in result.conflicts:
            conflict_names.update(c.plugin_name.split(", "))
        assert "independent" not in conflict_names

    def test_empty_plugins(self):
        """空插件集应返回成功且空加载顺序"""
        result = self.resolver.resolve({})
        assert result.success is True
        assert result.load_order == []

    def test_resolution_result_to_dict(self):
        """ResolutionResult 序列化正常"""
        plugins = {
            "a": DependencyNode(name="a", version="1.0.0"),
        }
        result = self.resolver.resolve(plugins)
        d = result.to_dict()
        assert d["success"] is True
        assert "a" in d["load_order"]
        assert d["conflicts"] == []
