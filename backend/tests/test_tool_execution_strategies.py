"""
工具执行策略模块的单元测试：验证四种策略的注册和分发。
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from core.tool_execution.base import ToolExecutionContext, ToolExecutionResult, ToolExecutionStrategy
from core.tool_execution.registry import ToolExecutionStrategyRegistry
from core.tool_execution.builtin_strategy import BuiltinToolStrategy
from core.tool_execution.plugin_strategy import PluginToolStrategy
from core.tool_execution.mcp_strategy import MCPToolStrategy
from core.tool_execution.task_strategy import TaskToolStrategy


class TestToolExecutionStrategyRegistry:
    """测试策略注册表的核心功能"""

    def test_register_and_get_strategy(self):
        """测试注册策略后可通过前缀匹配获取"""
        registry = ToolExecutionStrategyRegistry()
        mock_strategy = MagicMock(spec=ToolExecutionStrategy)
        mock_strategy.can_handle = MagicMock(return_value=True)

        registry.register("plugin_", mock_strategy)
        result = registry.get_strategy("plugin_test_tool")
        assert result is mock_strategy

    def test_get_strategy_longest_match_first(self):
        """测试最长前缀匹配优先"""
        registry = ToolExecutionStrategyRegistry()
        short_strategy = MagicMock(spec=ToolExecutionStrategy)
        long_strategy = MagicMock(spec=ToolExecutionStrategy)

        registry.register("builtin_", short_strategy)
        registry.register("builtin_task_", long_strategy)

        result = registry.get_strategy("builtin_task_spawn")
        assert result is long_strategy

    def test_get_strategy_no_match_returns_none(self):
        """测试无匹配前缀时返回 None"""
        registry = ToolExecutionStrategyRegistry()
        result = registry.get_strategy("unknown_tool_name")
        assert result is None

    def test_unregister_removes_strategy(self):
        """测试注销策略后无法获取"""
        registry = ToolExecutionStrategyRegistry()
        mock_strategy = MagicMock(spec=ToolExecutionStrategy)
        registry.register("test_", mock_strategy)
        registry.unregister("test_")
        result = registry.get_strategy("test_tool")
        assert result is None

    def test_get_all_prefixes(self):
        """测试获取所有已注册前缀"""
        registry = ToolExecutionStrategyRegistry()
        registry.register("plugin_", MagicMock(spec=ToolExecutionStrategy))
        registry.register("mcp_", MagicMock(spec=ToolExecutionStrategy))
        prefixes = registry.get_all_prefixes()
        assert "plugin_" in prefixes
        assert "mcp_" in prefixes

    @pytest.mark.asyncio
    async def test_execute_dispatches_to_correct_strategy(self):
        """测试 execute 方法正确分发到匹配的策略"""
        registry = ToolExecutionStrategyRegistry()
        mock_strategy = MagicMock(spec=ToolExecutionStrategy)
        mock_strategy.can_handle = MagicMock(return_value=True)
        mock_strategy.check_permission = AsyncMock(return_value=True)
        mock_strategy.apply_pre_hooks = AsyncMock(return_value=None)
        mock_strategy.apply_post_hooks = AsyncMock(
            return_value=ToolExecutionResult(output={"ok": True, "result": "done"})
        )
        mock_strategy.execute = AsyncMock(
            return_value=ToolExecutionResult(output={"ok": True, "result": "done"})
        )

        registry.register("builtin_", mock_strategy)

        context = ToolExecutionContext(
            session_id="test_session",
            user_id=1,
            tool_name="builtin_read_file",
            tool_input={"path": "/test.txt"},
            tool_call_id="call_1",
        )

        result = await registry.execute(context)
        assert result.output == {"ok": True, "result": "done"}
        mock_strategy.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_no_strategy_returns_error(self):
        """测试无匹配策略时返回错误"""
        registry = ToolExecutionStrategyRegistry()
        context = ToolExecutionContext(
            session_id="test_session",
            user_id=1,
            tool_name="unknown_tool",
            tool_input={},
            tool_call_id="call_1",
        )
        result = await registry.execute(context)
        assert result.error is not None
        assert "未找到工具" in result.error

    @pytest.mark.asyncio
    async def test_execute_permission_denied(self):
        """测试权限检查拒绝时返回错误"""
        registry = ToolExecutionStrategyRegistry()
        mock_strategy = MagicMock(spec=ToolExecutionStrategy)
        mock_strategy.can_handle = MagicMock(return_value=True)
        mock_strategy.check_permission = AsyncMock(return_value=False)

        registry.register("builtin_", mock_strategy)

        context = ToolExecutionContext(
            session_id="test_session",
            user_id=1,
            tool_name="builtin_write_file",
            tool_input={"path": "/test.txt"},
            tool_call_id="call_1",
        )

        result = await registry.execute(context)
        assert result.error is not None
        assert result.needs_permission is True


class TestBuiltinToolStrategy:
    """测试内置工具策略"""

    def test_can_handle_builtin_prefix(self):
        """测试能处理 builtin_ 前缀的工具"""
        strategy = BuiltinToolStrategy()
        assert strategy.can_handle("builtin_read_file") is True
        assert strategy.can_handle("builtin_write_file") is True

    def test_can_handle_unprefixed_tool(self):
        """测试能处理无前缀的工具（作为兜底）"""
        strategy = BuiltinToolStrategy()
        assert strategy.can_handle("read_file") is True
        assert strategy.can_handle("write_file") is True

    def test_can_handle_plugin_prefix_returns_false(self):
        """测试不处理 plugin_ 前缀的工具"""
        strategy = BuiltinToolStrategy()
        assert strategy.can_handle("plugin_test_tool") is False

    def test_can_handle_mcp_prefix_returns_false(self):
        """测试不处理 mcp_ 前缀的工具"""
        strategy = BuiltinToolStrategy()
        assert strategy.can_handle("mcp_server__tool") is False

    def test_can_handle_task_prefix_returns_false(self):
        """测试不处理 task_ 前缀的工具"""
        strategy = BuiltinToolStrategy()
        assert strategy.can_handle("task_spawn_agent") is False


class TestPluginToolStrategy:
    """测试插件工具策略"""

    def test_can_handle_plugin_prefix(self):
        """测试能处理 plugin_ 前缀的工具"""
        strategy = PluginToolStrategy()
        assert strategy.can_handle("plugin_myplugin__mytool") is True

    def test_can_handle_non_plugin_returns_false(self):
        """测试不处理非 plugin_ 前缀的工具"""
        strategy = PluginToolStrategy()
        assert strategy.can_handle("builtin_read_file") is False
        assert strategy.can_handle("mcp_test__tool") is False
        assert strategy.can_handle("task_spawn_agent") is False


class TestMCPToolStrategy:
    """测试 MCP 工具策略"""

    def test_can_handle_mcp_prefix(self):
        """测试能处理 mcp_ 前缀的工具"""
        strategy = MCPToolStrategy()
        assert strategy.can_handle("mcp_server__tool") is True

    def test_can_handle_non_mcp_returns_false(self):
        """测试不处理非 mcp_ 前缀的工具"""
        strategy = MCPToolStrategy()
        assert strategy.can_handle("builtin_read_file") is False
        assert strategy.can_handle("plugin_test__tool") is False
        assert strategy.can_handle("task_spawn_agent") is False


class TestTaskToolStrategy:
    """测试任务工具策略"""

    def test_can_handle_task_prefix(self):
        """测试能处理 task_ 前缀的工具"""
        strategy = TaskToolStrategy()
        assert strategy.can_handle("task_spawn_agent") is True
        assert strategy.can_handle("task_create_task") is True
        assert strategy.can_handle("task_todo_write") is True

    def test_can_handle_non_task_returns_false(self):
        """测试不处理非 task_ 前缀的工具"""
        strategy = TaskToolStrategy()
        assert strategy.can_handle("builtin_read_file") is False
        assert strategy.can_handle("plugin_test__tool") is False
        assert strategy.can_handle("mcp_server__tool") is False


class TestToolExecutionContext:
    """测试工具执行上下文数据类"""

    def test_default_values(self):
        """测试默认值"""
        ctx = ToolExecutionContext(
            session_id="s1",
            user_id=1,
            tool_name="test",
            tool_input={},
            tool_call_id="c1",
        )
        assert ctx.permission_mode == "auto"
        assert ctx.abort_controller is None
        assert ctx.raw_context == {}
        assert ctx.extra == {}

    def test_extra_fields(self):
        """测试扩展字段"""
        ctx = ToolExecutionContext(
            session_id="s1",
            user_id=1,
            tool_name="test",
            tool_input={},
            tool_call_id="c1",
            extra={"key": "value"},
            raw_context={"db": "mock"},
        )
        assert ctx.extra["key"] == "value"
        assert ctx.raw_context["db"] == "mock"


class TestToolExecutionResult:
    """测试工具执行结果数据类"""

    def test_basic_result(self):
        """测试基本结果"""
        result = ToolExecutionResult(output={"ok": True, "result": "done"})
        assert result.output == {"ok": True, "result": "done"}
        assert result.error is None

    def test_error_result(self):
        """测试错误结果"""
        result = ToolExecutionResult(output=None, error="something went wrong")
        assert result.output is None
        assert result.error == "something went wrong"

    def test_permission_result(self):
        """测试权限相关结果"""
        result = ToolExecutionResult(
            output=None,
            error="permission denied",
            needs_permission=True,
            permission_message="需要用户授权",
        )
        assert result.needs_permission is True
        assert result.permission_message == "需要用户授权"