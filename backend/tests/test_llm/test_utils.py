"""
LLM utils 模块测试。
"""
import pytest
from llm.utils import build_thinking_params, normalize_provider_name


class TestBuildThinkingParams:
    """build_thinking_params 函数测试。"""

    def test_build_thinking_params_openai(self):
        """OpenAI o1 模型思考参数。"""
        result = build_thinking_params(
            provider="openai",
            model="o1",
            thinking_depth=2,
        )
        assert result == {"reasoning_effort": "medium"}

    def test_build_thinking_params_openai_high(self):
        """OpenAI 高深度思考参数。"""
        result = build_thinking_params(
            provider="openai",
            model="o1",
            thinking_depth=5,
        )
        assert result == {"reasoning_effort": "high"}

    def test_build_thinking_params_openai_low(self):
        """OpenAI 低深度思考参数。"""
        result = build_thinking_params(
            provider="openai",
            model="o1",
            thinking_depth=1,
        )
        assert result == {"reasoning_effort": "low"}

    def test_build_thinking_params_claude_old(self):
        """Claude 旧版模型思考参数。"""
        result = build_thinking_params(
            provider="anthropic",
            model="claude-3-opus",
            thinking_depth=3,
        )
        assert result["thinking"]["type"] == "enabled"
        assert result["thinking"]["budget_tokens"] == 12000

    def test_build_thinking_params_claude_adaptive(self):
        """Claude 4.6 系列 Adaptive thinking 参数。"""
        result = build_thinking_params(
            provider="anthropic",
            model="claude-sonnet-4-6",
            thinking_depth=4,
        )
        assert result["thinking"]["type"] == "adaptive"
        assert result["output_config"]["effort"] == "xhigh"

    def test_build_thinking_params_disabled(self):
        """thinking_enabled=False 时返回禁用参数。"""
        result = build_thinking_params(
            provider="deepseek",
            model="deepseek-r1",
            thinking_depth=3,
            thinking_enabled=False,
        )
        assert result["extra_body"]["thinking"]["type"] == "disabled"

    def test_build_thinking_params_disabled_openai(self):
        """OpenAI 不支持显式关闭思考，返回空。"""
        result = build_thinking_params(
            provider="openai",
            model="gpt-4",
            thinking_depth=3,
            thinking_enabled=False,
        )
        assert result == {}

    def test_build_thinking_params_empty_model(self):
        """空模型返回空字典。"""
        result = build_thinking_params(
            provider="openai",
            model="",
            thinking_depth=3,
        )
        assert result == {}

    def test_build_thinking_params_depth_zero(self):
        """深度为 0 且未显式启用思考时返回空。"""
        result = build_thinking_params(
            provider="openai",
            model="o1",
            thinking_depth=0,
        )
        assert result == {}  # depth < 1 and not enabled

    def test_build_thinking_params_gemini(self):
        """Gemini 模型思考参数。"""
        result = build_thinking_params(
            provider="google",
            model="gemini-2.5-pro",
            thinking_depth=2,
        )
        assert result == {"reasoning_effort": "medium"}

    def test_build_thinking_params_unknown_provider(self):
        """未知 Provider 返回空字典。"""
        result = build_thinking_params(
            provider="unknown_provider",
            model="some-model",
            thinking_depth=5,
        )
        assert result == {}


class TestNormalizeProviderName:
    """normalize_provider_name 函数测试。"""

    def test_normalize_provider_name_anthropic(self):
        """anthropic 标准化为 claude。"""
        assert normalize_provider_name("anthropic") == "claude"

    def test_normalize_provider_name_google(self):
        """google 标准化为 gemini。"""
        assert normalize_provider_name("google") == "gemini"

    def test_normalize_provider_name_deepseek(self):
        """deepseek 标准化为 openai。"""
        assert normalize_provider_name("deepseek") == "openai"

    def test_normalize_provider_name_azure(self):
        """azure 标准化为 openai。"""
        assert normalize_provider_name("azure") == "openai"

    def test_normalize_provider_name_unknown(self):
        """未知 Provider 返回原名。"""
        assert normalize_provider_name("some_provider") == "some_provider"

    def test_normalize_provider_name_case_insensitive(self):
        """大小写不敏感。"""
        assert normalize_provider_name("Anthropic") == "claude"
        assert normalize_provider_name("GOOGLE") == "gemini"

    def test_normalize_provider_name_strip(self):
        """去除首尾空白。"""
        assert normalize_provider_name("  anthropic  ") == "claude"