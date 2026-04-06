"""
ExecutionLayer 单元测试模块。
测试执行层的核心逻辑，包括工具注册、LLM配置和错误处理。
"""

import pytest
from unittest.mock import MagicMock, patch
from core.executor import ExecutionLayer


class TestExecutionLayerInit:
    """测试 ExecutionLayer 初始化"""

    def test_init_default_values(self):
        """测试默认初始化值"""
        executor = ExecutionLayer()
        
        assert executor.tools == {}
        assert executor.llm_api_url is None
        assert executor.llm_api_key is None
        assert executor._max_tool_execution_cache == 256

    def test_init_default_provider_endpoints(self):
        """测试默认供应商端点配置"""
        executor = ExecutionLayer()
        
        assert "openai" in executor.default_provider_endpoints
        assert "anthropic" in executor.default_provider_endpoints
        assert "deepseek" in executor.default_provider_endpoints
        assert executor.default_provider_endpoints["openai"] == "https://api.openai.com/v1/chat/completions"


class TestExecutionLayerConfigureLLM:
    """测试 LLM 配置"""

    def test_configure_llm_with_url_only(self):
        """测试仅配置URL"""
        executor = ExecutionLayer()
        
        executor.configure_llm("https://api.example.com/v1/chat")
        
        assert executor.llm_api_url == "https://api.example.com/v1/chat"
        assert executor.llm_api_key is None

    def test_configure_llm_with_url_and_key(self):
        """测试配置URL和API密钥"""
        executor = ExecutionLayer()
        
        executor.configure_llm("https://api.example.com/v1/chat", "test-api-key")
        
        assert executor.llm_api_url == "https://api.example.com/v1/chat"
        assert executor.llm_api_key == "test-api-key"


class TestExecutionLayerRegisterTool:
    """测试工具注册"""

    def test_register_single_tool(self):
        """测试注册单个工具"""
        executor = ExecutionLayer()
        
        def test_tool(x: int) -> int:
            return x * 2
        
        executor.register_tool("double", test_tool)
        
        assert "double" in executor.tools
        assert executor.tools["double"] == test_tool
        assert executor.tools["double"](5) == 10

    def test_register_multiple_tools(self):
        """测试注册多个工具"""
        executor = ExecutionLayer()
        
        def tool_one(x: int) -> int:
            return x + 1
        
        def tool_two(x: int) -> int:
            return x - 1
        
        executor.register_tool("add", tool_one)
        executor.register_tool("subtract", tool_two)
        
        assert len(executor.tools) == 2
        assert "add" in executor.tools
        assert "subtract" in executor.tools

    def test_register_tool_overwrite(self):
        """测试工具覆盖注册"""
        executor = ExecutionLayer()
        
        def tool_v1(x: int) -> int:
            return x + 1
        
        def tool_v2(x: int) -> int:
            return x + 2
        
        executor.register_tool("test", tool_v1)
        executor.register_tool("test", tool_v2)
        
        assert executor.tools["test"] == tool_v2


class TestExecutionLayerBuildError:
    """测试错误构建"""

    def test_build_error_basic(self):
        """测试基本错误构建"""
        executor = ExecutionLayer()
        
        error = executor._build_error("TEST_ERROR", "Test error message")
        
        assert error["error"]["code"] == "TEST_ERROR"
        assert error["error"]["message"] == "Test error message"
        assert "request_id" in error["error"]

    def test_build_error_with_details(self):
        """测试带详情的错误构建"""
        executor = ExecutionLayer()
        
        details = {"field": "value", "count": 42}
        error = executor._build_error("TEST_ERROR", "Test error", details)
        
        assert error["error"]["details"] == details


class TestExecutionLayerToolIdempotencyKey:
    """测试工具幂等键生成"""

    def test_build_idempotency_key_with_explicit_key(self):
        """测试显式幂等键"""
        executor = ExecutionLayer()
        
        step = {"idempotency_key": "explicit-key-123"}
        context = {"session_id": "test-session"}
        
        key = executor._build_tool_idempotency_key(step, context)
        
        assert key == "explicit-key-123"

    def test_build_idempotency_key_from_context(self):
        """测试从上下文获取幂等键"""
        executor = ExecutionLayer()
        
        step = {}
        context = {"session_id": "test-session", "idempotency_key": "context-key-456"}
        
        key = executor._build_tool_idempotency_key(step, context)
        
        assert key == "context-key-456"

    def test_build_idempotency_key_generated(self):
        """测试自动生成幂等键"""
        executor = ExecutionLayer()
        
        step = {"action": "test_action", "params": {"arg": "value"}}
        context = {"session_id": "test-session"}
        
        key = executor._build_tool_idempotency_key(step, context)
        
        assert isinstance(key, str)
        assert len(key) > 0


class TestExecutionLayerClose:
    """测试资源清理"""

    def test_close_sets_closed_flag(self):
        """测试关闭设置closed标志"""
        executor = ExecutionLayer()
        
        assert executor._closed is False
        
        executor.close()
        
        assert executor._closed is True

    def test_close_clears_tools(self):
        """测试关闭清空工具"""
        executor = ExecutionLayer()
        executor.register_tool("test", lambda x: x)
        
        executor.close()
        
        assert executor.tools == {}
