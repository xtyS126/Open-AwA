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
    resolve_concurrency_safe,
)
from core.tool_factory import (
    build_tool,
    is_command_read_only,
    TOOL_DEFAULTS,
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


class TestToolDefinitionConcurrencyFields:
    """ToolDefinition 并发属性字段测试"""

    def test_tool_definition_new_fields_default(self):
        """验证新字段默认值（失败关闭：默认偏向不并发执行）"""
        tool = ToolDefinition(
            name="test_tool",
            description="A test tool",
        )
        # 失败关闭默认值
        assert tool.is_concurrency_safe is False
        assert tool.is_read_only is False
        assert tool.is_destructive is False
        assert tool.should_defer is False
        assert tool.always_load is False
        assert tool.max_result_size_chars is None
        assert tool.interrupt_behavior == "cancel"

    def test_resolve_concurrency_safe_bool(self):
        """验证 bool 类型的并发安全判定"""
        # is_concurrency_safe=True
        tool_safe = ToolDefinition(
            name="safe_tool",
            description="safe",
            is_concurrency_safe=True,
        )
        assert resolve_concurrency_safe(tool_safe, {}) is True

        # is_concurrency_safe=False
        tool_unsafe = ToolDefinition(
            name="unsafe_tool",
            description="unsafe",
            is_concurrency_safe=False,
        )
        assert resolve_concurrency_safe(tool_unsafe, {}) is False

    def test_resolve_concurrency_safe_callable(self):
        """验证 callable 类型的并发安全判定"""
        def judge(params: dict) -> bool:
            return params.get("read_only", False)

        tool = ToolDefinition(
            name="callable_tool",
            description="callable judge",
            is_concurrency_safe=judge,
        )
        # callable 返回 True
        assert resolve_concurrency_safe(tool, {"read_only": True}) is True
        # callable 返回 False
        assert resolve_concurrency_safe(tool, {"read_only": False}) is False

    def test_resolve_concurrency_safe_callable_exception(self):
        """验证 callable 抛异常时返回 False（失败关闭）"""
        def bad_judge(params: dict) -> bool:
            raise RuntimeError("judge failed")

        tool = ToolDefinition(
            name="bad_tool",
            description="bad judge",
            is_concurrency_safe=bad_judge,
        )
        # callable 抛异常时应返回 False
        assert resolve_concurrency_safe(tool, {}) is False


class TestToolFactory:
    """工具工厂 build_tool 测试"""

    def test_build_tool_defaults(self):
        """验证工厂构造使用 TOOL_DEFAULTS 默认值"""
        tool = build_tool({
            "name": "default_tool",
            "description": "uses defaults",
        })
        assert tool.name == "default_tool"
        assert tool.description == "uses defaults"
        # 验证并发属性回退到 TOOL_DEFAULTS
        assert tool.is_concurrency_safe == TOOL_DEFAULTS["is_concurrency_safe"]
        assert tool.is_read_only == TOOL_DEFAULTS["is_read_only"]
        assert tool.is_destructive == TOOL_DEFAULTS["is_destructive"]
        assert tool.should_defer == TOOL_DEFAULTS["should_defer"]
        assert tool.always_load == TOOL_DEFAULTS["always_load"]
        assert tool.max_result_size_chars == TOOL_DEFAULTS["max_result_size_chars"]
        assert tool.interrupt_behavior == TOOL_DEFAULTS["interrupt_behavior"]

    def test_build_tool_custom_values(self):
        """验证工厂构造自定义值"""
        tool = build_tool({
            "name": "custom_tool",
            "description": "custom values",
            "is_read_only": True,
            "is_concurrency_safe": True,
            "is_destructive": False,
            "should_defer": True,
            "always_load": True,
            "max_result_size_chars": 5000,
            "interrupt_behavior": "wait",
        })
        assert tool.is_read_only is True
        assert tool.is_concurrency_safe is True
        assert tool.is_destructive is False
        assert tool.should_defer is True
        assert tool.always_load is True
        assert tool.max_result_size_chars == 5000
        assert tool.interrupt_behavior == "wait"

    def test_build_tool_invalid_interrupt_behavior(self):
        """验证无效 interrupt_behavior 抛 ValueError"""
        with pytest.raises(ValueError, match="interrupt_behavior"):
            build_tool({
                "name": "bad_interrupt",
                "description": "invalid interrupt",
                "interrupt_behavior": "invalid_value",
            })

    def test_build_tool_invalid_concurrency_safe_type(self):
        """验证 is_concurrency_safe 非法类型抛 ValueError"""
        with pytest.raises(ValueError, match="is_concurrency_safe"):
            build_tool({
                "name": "bad_safe",
                "description": "invalid safe type",
                "is_concurrency_safe": "not_a_bool",  # 字符串非法
            })

    def test_build_tool_callable_concurrency_safe(self):
        """验证 is_concurrency_safe 接受 callable"""
        def judge(params: dict) -> bool:
            return True

        tool = build_tool({
            "name": "callable_tool",
            "description": "callable safe",
            "is_concurrency_safe": judge,
        })
        assert callable(tool.is_concurrency_safe)


class TestIsCommandReadOnly:
    """run_command 输入驱动判定函数测试"""

    def test_is_command_read_only_ls(self):
        """验证 ls 命令只读"""
        assert is_command_read_only({"command": "ls"}) is True
        assert is_command_read_only({"command": "ls -la /tmp"}) is True

    def test_is_command_read_only_rm(self):
        """验证 rm 命令非只读"""
        assert is_command_read_only({"command": "rm -rf /tmp"}) is False

    def test_is_command_read_only_git_status(self):
        """验证 git status 命令只读"""
        assert is_command_read_only({"command": "git status"}) is True
        assert is_command_read_only({"command": "git log --oneline"}) is True
        assert is_command_read_only({"command": "git diff"}) is True

    def test_is_command_read_only_cat_grep(self):
        """验证 cat/grep/find 命令只读"""
        assert is_command_read_only({"command": "cat /etc/hosts"}) is True
        assert is_command_read_only({"command": "grep foo bar.txt"}) is True
        assert is_command_read_only({"command": "find . -name '*.py'"}) is True

    def test_is_command_read_only_empty_command(self):
        """验证空命令返回 False（失败关闭）"""
        assert is_command_read_only({"command": ""}) is False
        assert is_command_read_only({}) is False

    def test_is_command_read_only_non_dict_input(self):
        """验证非字典输入返回 False（失败关闭）"""
        assert is_command_read_only("ls") is False  # type: ignore[arg-type]
        assert is_command_read_only(None) is False  # type: ignore[arg-type]

    def test_is_command_read_only_prefix_not_match(self):
        """验证前缀相似但不匹配的命令非只读（避免 lsv 误匹配 ls）"""
        assert is_command_read_only({"command": "lsv"}) is False
        assert is_command_read_only({"command": "catapult"}) is False


class TestBuiltinToolsConcurrencyAttributes:
    """内置工具并发属性测试"""

    def test_builtin_tools_concurrency_attributes(self):
        """验证内置工具注册后并发属性正确声明"""
        from core.tool_entries import register_builtin_tools

        registry = ToolRegistry()
        register_builtin_tools(registry)

        # 只读文件操作：is_read_only=True, is_concurrency_safe=True
        read_tool = registry.get("builtin_read_file")
        assert read_tool is not None
        assert read_tool.is_read_only is True
        assert read_tool.is_concurrency_safe is True

        list_tool = registry.get("builtin_list_files")
        assert list_tool is not None
        assert list_tool.is_read_only is True
        assert list_tool.is_concurrency_safe is True

        exists_tool = registry.get("builtin_file_exists")
        assert exists_tool is not None
        assert exists_tool.is_read_only is True
        assert exists_tool.is_concurrency_safe is True

        # 破坏性文件操作：is_destructive=True, is_concurrency_safe=False
        write_tool = registry.get("builtin_write_file")
        assert write_tool is not None
        assert write_tool.is_destructive is True
        assert write_tool.is_concurrency_safe is False

        delete_tool = registry.get("builtin_delete_file")
        assert delete_tool is not None
        assert delete_tool.is_destructive is True
        assert delete_tool.is_concurrency_safe is False

        # 命令执行：is_concurrency_safe 为 callable（输入驱动判定）
        cmd_tool = registry.get("builtin_run_command")
        assert cmd_tool is not None
        assert callable(cmd_tool.is_concurrency_safe)
        # 只读命令应判定为并发安全
        assert resolve_concurrency_safe(cmd_tool, {"command": "ls"}) is True
        # 非只读命令应判定为不并发安全
        assert resolve_concurrency_safe(cmd_tool, {"command": "rm -rf /"}) is False

        # 只读网络操作：is_read_only=True, is_concurrency_safe=True
        web_tool = registry.get("builtin_web_search")
        assert web_tool is not None
        assert web_tool.is_read_only is True
        assert web_tool.is_concurrency_safe is True
