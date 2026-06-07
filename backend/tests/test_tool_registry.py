"""
ToolRegistry 和 HookManager 单元测试。
"""

import asyncio
import pytest

from core.tool_registry import (
    ToolRegistry,
    ToolDefinition,
    ToolPriority,
    ToolStatus,
    ToolExecutionResult,
)


class TestToolDefinition:
    """工具定义测试"""

    def test_basic_definition(self):
        """基本工具定义"""
        tool = ToolDefinition(
            name="test_tool",
            description="A test tool",
            parameters_schema={"type": "object", "properties": {}},
        )
        assert tool.name == "test_tool"
        assert tool.permission_action == "test_tool"  # 自动使用 name

    def test_openai_format(self):
        """OpenAI 格式转换"""
        tool = ToolDefinition(
            name="read",
            description="Read a file",
            parameters_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path"},
                },
                "required": ["path"],
            },
        )
        func_def = tool.to_openai_function()
        assert func_def["type"] == "function"
        assert func_def["function"]["name"] == "read"
        assert func_def["function"]["description"] == "Read a file"
        assert "path" in func_def["function"]["parameters"]["properties"]

    def test_custom_permission(self):
        """自定义权限设置"""
        tool = ToolDefinition(
            name="my_tool",
            description="Custom tool",
            permission_action="custom_action",
            permission_resource="custom_resource",
        )
        assert tool.permission_action == "custom_action"
        assert tool.permission_resource == "custom_resource"


class TestToolRegistry:
    """工具注册中心测试"""

    @pytest.fixture
    def registry(self):
        """创建空注册中心"""
        reg = ToolRegistry()
        return reg

    def test_register(self, registry):
        """注册工具"""
        tool = ToolDefinition(
            name="test",
            description="Test tool",
            priority=ToolPriority.APPLICATION,
        )
        registry.register(tool)
        assert registry.get("test") is not None
        assert registry.get("test").name == "test"

    def test_register_priority_ordering(self, registry):
        """优先级排序测试"""
        loc_tool = ToolDefinition(
            name="bash",
            description="Location bash tool",
            priority=ToolPriority.LOCATION,
        )
        app_tool = ToolDefinition(
            name="bash",
            description="Application bash tool",
            priority=ToolPriority.APPLICATION,
        )
        mcp_tool = ToolDefinition(
            name="bash",
            description="MCP bash tool",
            priority=ToolPriority.MCP,
        )
        registry.register(app_tool)
        registry.register(mcp_tool)
        registry.register(loc_tool)

        # 应该返回最高优先级的 LOCATION 版本
        tool = registry.get("bash")
        assert tool is not None
        assert tool.priority == ToolPriority.LOCATION
        assert tool.description == "Location bash tool"

    def test_unregister(self, registry):
        """注销工具"""
        tool = ToolDefinition(name="test", description="Test")
        registry.register(tool)
        assert registry.get("test") is not None

        registry.unregister("test")
        assert registry.get("test") is None

    def test_unregister_by_priority(self, registry):
        """按优先级注销"""
        loc_tool = ToolDefinition(
            name="bash", description="Location", priority=ToolPriority.LOCATION,
        )
        app_tool = ToolDefinition(
            name="bash", description="Application", priority=ToolPriority.APPLICATION,
        )
        registry.register(app_tool)
        registry.register(loc_tool)

        # 注销 APPLICATION 优先级
        registry.unregister("bash", ToolPriority.APPLICATION)
        tool = registry.get("bash")
        assert tool is not None
        assert tool.priority == ToolPriority.LOCATION

    def test_list_all(self, registry):
        """列出所有工具"""
        registry.register(ToolDefinition(name="tool1", description="First"))
        registry.register(ToolDefinition(name="tool2", description="Second"))
        all_tools = registry.list_all()
        assert len(all_tools) == 2

    def test_get_definitions_for_llm(self, registry):
        """生成 LLM 工具定义"""
        registry.register(ToolDefinition(
            name="read",
            description="Read a file",
            priority=ToolPriority.LOCATION,
        ))
        registry.register(ToolDefinition(
            name="write",
            description="Write a file",
            priority=ToolPriority.LOCATION,
        ))

        definitions = registry.get_definitions_for_llm()
        assert len(definitions) == 2
        assert definitions[0]["type"] == "function"

    def test_get_definitions_permission_filter(self, registry):
        """权限过滤测试"""
        registry.register(ToolDefinition(
            name="read", description="Read", permission_action="read",
        ))
        registry.register(ToolDefinition(
            name="write", description="Write", permission_action="write",
        ))

        # 使用 deny write 规则
        permissions = [{"action": "write", "resource": "*", "effect": "deny"}]
        definitions = registry.get_definitions_for_llm(permissions)
        assert len(definitions) == 1
        assert definitions[0]["function"]["name"] == "read"

    @pytest.mark.asyncio
    async def test_execute_sync(self, registry):
        """执行同步工具"""
        def sync_handler(params, ctx):
            return {"result": params.get("x", 0) * 2}

        registry.register(ToolDefinition(
            name="double",
            description="Double a number",
            execute=sync_handler,
        ))
        result = await registry.execute("double", {"x": 21})
        assert result.status == ToolStatus.COMPLETED
        assert result.result["result"] == 42

    @pytest.mark.asyncio
    async def test_execute_async(self, registry):
        """执行异步工具"""
        async def async_handler(params, ctx):
            await asyncio.sleep(0.01)
            return {"message": f"Hello, {params.get('name', 'World')}!"}

        registry.register(ToolDefinition(
            name="greet",
            description="Greet someone",
            execute=async_handler,
        ))
        result = await registry.execute("greet", {"name": "Test"})
        assert result.status == ToolStatus.COMPLETED
        assert "Hello, Test!" in result.result["message"]

    @pytest.mark.asyncio
    async def test_execute_unknown_tool(self, registry):
        """执行未知工具"""
        result = await registry.execute("nonexistent", {})
        assert result.status == ToolStatus.ERROR
        assert result.error is not None
        assert "nonexistent" in result.error

    @pytest.mark.asyncio
    async def test_execute_truncation(self, registry):
        """输出截断测试"""
        def big_output_handler(params, ctx):
            return {"data": "X" * 20_000}  # 超过 MAX_OUTPUT_CHARS

        registry.register(ToolDefinition(
            name="big_output",
            description="Generate big output",
            execute=big_output_handler,
        ))
        result = await registry.execute("big_output", {})
        assert result.status == ToolStatus.COMPLETED
        assert result.truncated is True
        assert result.output_path is not None

    @pytest.mark.asyncio
    async def test_stats(self, registry):
        """统计测试：通过 execute 触发统计更新"""
        # 正常执行会更新 completed 统计
        registry.register(ToolDefinition(
            name="tool1", description="Stats tool",
            execute=lambda params, ctx: {"ok": True},
        ))
        await registry.execute("tool1", {})
        await registry.execute("tool1", {})

        # 异常执行会更新 error 统计
        def error_handler(params, ctx):
            raise RuntimeError("fail")
        registry.register(ToolDefinition(
            name="tool2", description="Error tool",
            execute=error_handler,
        ))
        await registry.execute("tool2", {})

        stats1 = registry.get_stats("tool1")
        assert stats1["completed"] >= 1
        assert stats1["total"] >= 1

        stats2 = registry.get_stats("tool2")
        assert stats2["error"] == 1


class TestToolExecutionResult:
    """工具执行结果测试"""

    def test_success_result(self):
        """成功结果"""
        result = ToolExecutionResult(
            tool_name="test",
            status=ToolStatus.COMPLETED,
            result={"ok": True},
            execution_time_ms=100,
        )
        d = result.to_dict()
        assert d["ok"] is True
        assert d["tool_name"] == "test"
        assert d["execution_time_ms"] == 100

    def test_error_result(self):
        """错误结果"""
        result = ToolExecutionResult(
            tool_name="test",
            status=ToolStatus.ERROR,
            error="Something went wrong",
        )
        d = result.to_dict()
        assert d["ok"] is False
        assert d["error"] == "Something went wrong"
