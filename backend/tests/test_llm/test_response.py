"""
LLM response 模块测试。
"""
import pytest
from llm.response import LLMResponse, TokenUsage


class TestTokenUsage:
    """TokenUsage 数据类测试。"""

    def test_token_usage_auto_total(self):
        """total_tokens 自动计算为 prompt + completion。"""
        usage = TokenUsage(prompt_tokens=100, completion_tokens=50)
        assert usage.prompt_tokens == 100
        assert usage.completion_tokens == 50
        assert usage.total_tokens == 150

    def test_token_usage_explicit_total(self):
        """显式指定 total_tokens 时不被覆盖。"""
        usage = TokenUsage(prompt_tokens=100, completion_tokens=50, total_tokens=200)
        assert usage.total_tokens == 200

    def test_token_usage_defaults(self):
        """默认值均为 0。"""
        usage = TokenUsage()
        assert usage.prompt_tokens == 0
        assert usage.completion_tokens == 0
        assert usage.total_tokens == 0


class TestLLMResponse:
    """LLMResponse 数据类测试。"""

    def test_llm_response_defaults(self):
        """LLMResponse 默认值。"""
        resp = LLMResponse(content="你好")
        assert resp.content == "你好"
        assert resp.success is True
        assert resp.error is None
        assert resp.thinking_content is None
        assert resp.raw_response is None
        assert resp.finish_reason is None
        assert resp.cost == 0.0
        assert resp.latency_ms == 0
        assert resp.model == ""
        assert resp.provider == ""

    def test_llm_response_full(self):
        """LLMResponse 完整字段。"""
        usage = TokenUsage(prompt_tokens=10, completion_tokens=5)
        resp = LLMResponse(
            content="完整响应",
            usage=usage,
            cost=0.01,
            latency_ms=500,
            model="gpt-4",
            provider="openai",
            thinking_content="思考过程...",
            finish_reason="stop",
        )
        assert resp.content == "完整响应"
        assert resp.usage.total_tokens == 15
        assert resp.cost == 0.01
        assert resp.latency_ms == 500
        assert resp.model == "gpt-4"
        assert resp.provider == "openai"
        assert resp.thinking_content == "思考过程..."
        assert resp.finish_reason == "stop"

    def test_llm_response_error_response(self):
        """error_response 类方法创建错误响应。"""
        resp = LLMResponse.error_response(
            "API 调用失败",
            provider="openai",
            model="gpt-4",
        )
        assert resp.content == ""
        assert resp.success is False
        assert resp.error == "API 调用失败"
        assert resp.provider == "openai"
        assert resp.model == "gpt-4"

    def test_llm_response_error_response_defaults(self):
        """error_response 默认参数。"""
        resp = LLMResponse.error_response("通用错误")
        assert resp.success is False
        assert resp.error == "通用错误"
        assert resp.provider == ""
        assert resp.model == ""