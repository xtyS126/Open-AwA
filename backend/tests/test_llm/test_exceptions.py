"""
LLM exceptions 模块测试。
"""
import pytest
from llm.exceptions import (
    LLMError,
    ProviderNotFoundError,
    RateLimitError,
    StructuredOutputError,
    AuthenticationError,
    TimeoutError,
)


class TestLLMExceptions:
    """LLM 异常类单元测试。"""

    def test_llm_error_creation(self):
        """LLMError 基础异常创建。"""
        error = LLMError("测试错误", provider="openai", model="gpt-4")
        assert error.message == "测试错误"
        assert error.provider == "openai"
        assert error.model == "gpt-4"
        assert str(error) == "测试错误"

    def test_llm_error_defaults(self):
        """LLMError 默认参数。"""
        error = LLMError("错误")
        assert error.provider == ""
        assert error.model == ""

    def test_provider_not_found_error(self):
        """ProviderNotFoundError 创建和属性。"""
        error = ProviderNotFoundError("claude")
        assert error.provider_name == "claude"
        assert error.provider == "claude"
        assert "claude" in str(error)

    def test_rate_limit_error(self):
        """RateLimitError 创建和属性。"""
        error = RateLimitError(
            "速率限制触发",
            provider="openai",
            model="gpt-4",
            retry_after=30.0,
        )
        assert error.provider == "openai"
        assert error.model == "gpt-4"
        assert error.retry_after == 30.0

    def test_rate_limit_error_defaults(self):
        """RateLimitError 默认参数。"""
        error = RateLimitError()
        assert error.message == "触发速率限制"
        assert error.retry_after is None

    def test_structured_output_error(self):
        """StructuredOutputError 创建和属性。"""
        error = StructuredOutputError(
            "解析失败",
            raw_output='{"partial": "data"',
            reason="extraction_failed",
            provider="openai",
            model="gpt-4",
        )
        assert error.raw_output == '{"partial": "data"'
        assert error.reason == "extraction_failed"
        assert error.provider == "openai"
        assert error.model == "gpt-4"

    def test_structured_output_error_defaults(self):
        """StructuredOutputError 默认参数。"""
        error = StructuredOutputError("解析失败")
        assert error.raw_output == ""
        assert error.reason == ""

    def test_authentication_error(self):
        """AuthenticationError 创建和属性。"""
        error = AuthenticationError("API 密钥无效", provider="openai")
        assert error.provider == "openai"
        assert "API 密钥无效" in str(error)

    def test_authentication_error_default_message(self):
        """AuthenticationError 默认消息。"""
        error = AuthenticationError()
        assert "API 密钥无效或已过期" in str(error)

    def test_timeout_error(self):
        """TimeoutError 创建和属性。"""
        error = TimeoutError("请求超时", provider="openai", model="gpt-4", timeout=30.0)
        assert error.provider == "openai"
        assert error.model == "gpt-4"
        assert error.timeout == 30.0

    def test_timeout_error_default_message(self):
        """TimeoutError 默认消息。"""
        error = TimeoutError()
        assert "请求超时" in str(error)

    def test_exception_inheritance(self):
        """所有异常继承自 LLMError。"""
        assert issubclass(ProviderNotFoundError, LLMError)
        assert issubclass(RateLimitError, LLMError)
        assert issubclass(StructuredOutputError, LLMError)
        assert issubclass(AuthenticationError, LLMError)
        assert issubclass(TimeoutError, LLMError)