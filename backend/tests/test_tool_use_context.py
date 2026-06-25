"""
ToolUseContext 单元测试：验证显式依赖注入容器的字段、默认值、工厂方法与回调集成。

覆盖：
- ToolUseContext dataclass 必填字段与可选字段
- 默认值（abort_controller/content_replacement_state/回调均为 None，metadata 为空 dict）
- create_default 工厂方法
- 集成 AbortController（可被 abort 且不影响其他实例）
- 集成 ContentReplacementState
- record_usage / record_latency / spawn_subagent 回调可被调用
- metadata 字段独立性（default_factory 不共享引用）
"""

import pytest

from core.abort_controller import AbortController
from core.content_replacement import ContentReplacementState
from core.tool_use_context import ToolUseContext, create_default


# ==================== dataclass 字段测试 ====================


class TestToolUseContextDataclass:
    """验证 ToolUseContext dataclass 的字段赋值。"""

    def test_tool_use_context_dataclass(self):
        """验证必填字段与可选字段均能正确赋值。"""
        abort_controller = AbortController()
        content_replacement_state = ContentReplacementState()
        usage_log: list = []

        def _record_usage(usage: dict) -> None:
            usage_log.append(usage)

        def _record_latency(tool_name: str, latency: float) -> None:
            pass

        def _spawn_subagent(agent_type: str, params: dict) -> str:
            return "subagent-1"

        ctx = ToolUseContext(
            session_id="session-123",
            user_id="user-456",
            agent_id="agent-789",
            abort_controller=abort_controller,
            content_replacement_state=content_replacement_state,
            record_usage=_record_usage,
            record_latency=_record_latency,
            spawn_subagent=_spawn_subagent,
            metadata={"key": "value"},
        )

        assert ctx.session_id == "session-123"
        assert ctx.user_id == "user-456"
        assert ctx.agent_id == "agent-789"
        assert ctx.abort_controller is abort_controller
        assert ctx.content_replacement_state is content_replacement_state
        assert ctx.record_usage is _record_usage
        assert ctx.record_latency is _record_latency
        assert ctx.spawn_subagent is _spawn_subagent
        assert ctx.metadata == {"key": "value"}


# ==================== 默认值测试 ====================


class TestToolUseContextDefaultValues:
    """验证 ToolUseContext 可选字段的默认值。"""

    def test_tool_use_context_default_values(self):
        """仅传入必填字段时，可选字段应为 None 或空容器。"""
        ctx = ToolUseContext(
            session_id="session-1",
            user_id="user-1",
            agent_id="agent-1",
        )

        assert ctx.session_id == "session-1"
        assert ctx.user_id == "user-1"
        assert ctx.agent_id == "agent-1"
        # 可选字段默认为 None
        assert ctx.abort_controller is None
        assert ctx.content_replacement_state is None
        assert ctx.record_usage is None
        assert ctx.record_latency is None
        assert ctx.spawn_subagent is None
        # metadata 默认为空 dict
        assert ctx.metadata == {}


# ==================== 工厂方法测试 ====================


class TestCreateDefault:
    """验证 create_default 工厂方法。"""

    def test_create_default(self):
        """工厂方法应构造仅含必填字段的 ToolUseContext，可选字段为默认值。"""
        ctx = create_default(
            session_id="sess-factory",
            user_id="user-factory",
            agent_id="agent-factory",
        )

        assert isinstance(ctx, ToolUseContext)
        assert ctx.session_id == "sess-factory"
        assert ctx.user_id == "user-factory"
        assert ctx.agent_id == "agent-factory"
        # 工厂方法构造的实例可选字段应为默认值
        assert ctx.abort_controller is None
        assert ctx.content_replacement_state is None
        assert ctx.record_usage is None
        assert ctx.record_latency is None
        assert ctx.spawn_subagent is None
        assert ctx.metadata == {}


# ==================== AbortController 集成测试 ====================


class TestToolUseContextWithAbortController:
    """验证 ToolUseContext 集成 AbortController。"""

    def test_tool_use_context_with_abort_controller(self):
        """abort_controller 字段应能持有 AbortController 实例并暴露其方法。"""
        controller = AbortController()
        ctx = ToolUseContext(
            session_id="s1",
            user_id="u1",
            agent_id="a1",
            abort_controller=controller,
        )

        assert ctx.abort_controller is controller
        assert ctx.abort_controller.is_aborted() is False
        assert ctx.abort_controller.reason is None

    def test_tool_use_context_immutable_abort(self):
        """验证 abort_controller 可被 abort，且不影响其他 ToolUseContext 实例。"""
        controller_a = AbortController()
        controller_b = AbortController()
        ctx_a = ToolUseContext(
            session_id="s1", user_id="u1", agent_id="a1",
            abort_controller=controller_a,
        )
        ctx_b = ToolUseContext(
            session_id="s2", user_id="u2", agent_id="a2",
            abort_controller=controller_b,
        )

        # 中止 ctx_a 的控制器
        ctx_a.abort_controller.abort(reason="user_cancelled")

        # ctx_a 已中止
        assert ctx_a.abort_controller.is_aborted() is True
        assert ctx_a.abort_controller.reason == "user_cancelled"
        # ctx_b 不受影响
        assert ctx_b.abort_controller.is_aborted() is False
        assert ctx_b.abort_controller.reason is None


# ==================== ContentReplacementState 集成测试 ====================


class TestToolUseContextWithContentReplacement:
    """验证 ToolUseContext 集成 ContentReplacementState。"""

    def test_tool_use_context_with_content_replacement(self):
        """content_replacement_state 字段应能持有状态实例并保持其内部数据。"""
        state = ContentReplacementState()
        state.seen_ids.add("call_1")
        state.replacements["call_1"] = "[cleared]"

        ctx = ToolUseContext(
            session_id="s1",
            user_id="u1",
            agent_id="a1",
            content_replacement_state=state,
        )

        assert ctx.content_replacement_state is state
        assert "call_1" in ctx.content_replacement_state.seen_ids
        assert ctx.content_replacement_state.replacements["call_1"] == "[cleared]"


# ==================== 回调测试 ====================


class TestToolUseContextCallbacks:
    """验证 record_usage / record_latency / spawn_subagent 回调。"""

    def test_record_usage_callback(self):
        """record_usage 回调应能被调用并接收 usage dict。"""
        received: list = []
        ctx = ToolUseContext(
            session_id="s1",
            user_id="u1",
            agent_id="a1",
            record_usage=lambda usage: received.append(usage),
        )

        ctx.record_usage({"total_tokens": 100, "prompt_tokens": 80})

        assert len(received) == 1
        assert received[0] == {"total_tokens": 100, "prompt_tokens": 80}

    def test_record_latency_callback(self):
        """record_latency 回调应能被调用并接收工具名与延迟值。"""
        received: list = []
        ctx = ToolUseContext(
            session_id="s1",
            user_id="u1",
            agent_id="a1",
            record_latency=lambda tool_name, latency: received.append((tool_name, latency)),
        )

        ctx.record_latency("read_file", 12.5)

        assert len(received) == 1
        assert received[0] == ("read_file", 12.5)

    def test_spawn_subagent_callback(self):
        """spawn_subagent 回调应能被调用并返回子 Agent ID。"""
        ctx = ToolUseContext(
            session_id="s1",
            user_id="u1",
            agent_id="a1",
            spawn_subagent=lambda agent_type, params: f"sub-{agent_type}-{params.get('id', '0')}",
        )

        result = ctx.spawn_subagent("Explore", {"id": 42})

        assert result == "sub-Explore-42"


# ==================== metadata 字段测试 ====================


class TestToolUseContextMetadata:
    """验证 metadata 字段的独立性与可写性。"""

    def test_metadata_field(self):
        """metadata 默认为空 dict，且不同实例的 metadata 互不影响。"""
        ctx_a = ToolUseContext(session_id="s1", user_id="u1", agent_id="a1")
        ctx_b = ToolUseContext(session_id="s2", user_id="u2", agent_id="a2")

        # 默认均为空 dict
        assert ctx_a.metadata == {}
        assert ctx_b.metadata == {}

        # 修改 ctx_a 的 metadata 不影响 ctx_b
        ctx_a.metadata["custom"] = "value"
        assert ctx_a.metadata == {"custom": "value"}
        assert ctx_b.metadata == {}

    def test_metadata_field_accepts_arbitrary_keys(self):
        """metadata 应能接受任意键值对。"""
        ctx = ToolUseContext(
            session_id="s1",
            user_id="u1",
            agent_id="a1",
            metadata={"trace_id": "trace-xyz", "priority": 1, "tags": ["a", "b"]},
        )

        assert ctx.metadata["trace_id"] == "trace-xyz"
        assert ctx.metadata["priority"] == 1
        assert ctx.metadata["tags"] == ["a", "b"]
