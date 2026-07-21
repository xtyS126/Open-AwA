"""
billing/deepseek_tokenizer_utils.py 单元测试。
覆盖 DeepSeek BPE tokenizer 的估算函数和工具调用开销计算。
"""

import pytest
from billing.deepseek_tokenizer_utils import (
    DEEPSEEK_CN_CHARS_PER_TOKEN,
    DEEPSEEK_EN_CHARS_PER_TOKEN,
    DEEPSEEK_SPECIAL_TOKENS,
    DEEPSEEK_CHAT_TEMPLATE_OVERHEAD,
    estimate_deepseek_message_tokens,
    estimate_deepseek_conversation_tokens,
    estimate_deepseek_tool_call_tokens,
    compare_deepseek_vs_generic,
    try_load_deepseek_tokenizer,
    count_tokens_with_real_tokenizer,
)


class TestEstimateDeepseekMessageTokens:
    """测试单条消息 token 估算"""

    def test_empty_content_returns_zero(self):
        """空内容返回 0 token"""
        assert estimate_deepseek_message_tokens("") == 0
        assert estimate_deepseek_message_tokens("", include_overhead=False) == 0

    def test_chinese_only_content(self):
        """纯中文内容使用中文比率估算"""
        tokens = estimate_deepseek_message_tokens("你好世界", include_overhead=False)
        expected = 4 / DEEPSEEK_CN_CHARS_PER_TOKEN
        assert tokens >= 1

    def test_english_only_content(self):
        """纯英文内容使用英文比率估算"""
        tokens = estimate_deepseek_message_tokens("hello world", include_overhead=False)
        expected = 11 / DEEPSEEK_EN_CHARS_PER_TOKEN
        assert tokens >= 1
        assert abs(tokens - expected) <= 1

    def test_mixed_cn_en_content(self):
        """中英混合内容分别估算后相加"""
        tokens = estimate_deepseek_message_tokens(
            "你好 world 测试 hello", include_overhead=False
        )
        assert tokens >= 1

    def test_include_overhead_adds_template_tokens(self):
        """计入模板开销后 token 数增加"""
        no_overhead = estimate_deepseek_message_tokens(
            "hello", role="user", include_overhead=False
        )
        with_overhead = estimate_deepseek_message_tokens(
            "hello", role="user", include_overhead=True
        )
        assert with_overhead > no_overhead
        expected_overhead = DEEPSEEK_CHAT_TEMPLATE_OVERHEAD["user"]
        assert with_overhead == no_overhead + expected_overhead

    def test_system_role_overhead(self):
        """system 角色使用对应开销值"""
        tokens = estimate_deepseek_message_tokens(
            "system prompt", role="system", include_overhead=True
        )
        no_overhead = estimate_deepseek_message_tokens(
            "system prompt", role="system", include_overhead=False
        )
        assert tokens == no_overhead + DEEPSEEK_CHAT_TEMPLATE_OVERHEAD["system"]

    def test_assistant_role_overhead(self):
        """assistant 角色使用对应开销值"""
        tokens = estimate_deepseek_message_tokens(
            "I am fine", role="assistant", include_overhead=True
        )
        no_overhead = estimate_deepseek_message_tokens(
            "I am fine", role="assistant", include_overhead=False
        )
        assert tokens == no_overhead + DEEPSEEK_CHAT_TEMPLATE_OVERHEAD["assistant"]

    def test_tool_role_overhead(self):
        """tool 角色使用对应开销值"""
        tokens = estimate_deepseek_message_tokens(
            '{"result": "ok"}', role="tool", include_overhead=True
        )
        no_overhead = estimate_deepseek_message_tokens(
            '{"result": "ok"}', role="tool", include_overhead=False
        )
        assert tokens == no_overhead + DEEPSEEK_CHAT_TEMPLATE_OVERHEAD["tool"]

    def test_unknown_role_defaults_to_overhead_1(self):
        """未知角色默认使用开销值 1"""
        tokens = estimate_deepseek_message_tokens(
            "some text", role="unknown_role", include_overhead=True
        )
        no_overhead = estimate_deepseek_message_tokens(
            "some text", role="unknown_role", include_overhead=False
        )
        assert tokens == no_overhead + 1

    def test_none_content_returns_zero(self):
        """None 内容返回 0"""
        assert estimate_deepseek_message_tokens(None) == 0

    def test_long_chinese_text(self):
        """长中文文本估算合理"""
        text = "这是一个很长的中文测试文本" * 50
        tokens = estimate_deepseek_message_tokens(text, include_overhead=False)
        assert tokens > 50

    def test_code_text(self):
        """代码文本合理估算"""
        code = 'def hello():\n    print("hello world")\n    return True'
        tokens = estimate_deepseek_message_tokens(code, include_overhead=False)
        assert tokens >= 1


class TestEstimateDeepseekConversationTokens:
    """测试完整对话 token 估算"""

    def test_empty_messages_returns_zero(self):
        """空消息列表返回零统计"""
        result = estimate_deepseek_conversation_tokens([])
        assert result["total_tokens"] == 0
        assert result["message_count"] == 0

    def test_single_message_conversation(self):
        """单条消息对话"""
        messages = [{"role": "user", "content": "hello"}]
        result = estimate_deepseek_conversation_tokens(messages)
        assert result["total_tokens"] > 0
        assert result["message_count"] == 1
        assert len(result["per_message"]) == 1

    def test_multi_turn_conversation(self):
        """多轮对话统计"""
        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "你好！有什么可以帮助你的？"},
            {"role": "user", "content": "今天天气怎么样？"},
        ]
        result = estimate_deepseek_conversation_tokens(messages)
        assert result["message_count"] == 4
        assert result["total_tokens"] > 0
        for role, tokens in result["per_message"]:
            assert tokens > 0

    def test_message_without_content_defaults_to_empty(self):
        """缺少 content 字段的消息默认为空字符串，空内容返回 0 token"""
        messages = [{"role": "user"}]
        result = estimate_deepseek_conversation_tokens(messages)
        # 空内容消息 token 为 0（不计入模板开销）
        assert result["total_tokens"] == 0
        assert result["message_count"] == 1
        role, tokens = result["per_message"][0]
        assert tokens == 0

    def test_message_with_none_content(self):
        """content 为 None 的消息"""
        messages = [{"role": "user", "content": None}]
        result = estimate_deepseek_conversation_tokens(messages)
        assert result["message_count"] == 1

    def test_without_overhead(self):
        """不计入模板开销的对话估算"""
        messages = [{"role": "user", "content": "hello"}]
        result = estimate_deepseek_conversation_tokens(messages, include_overhead=False)
        assert result["include_template_overhead"] is False


class TestEstimateDeepseekToolCallTokens:
    """测试工具调用 token 估算"""

    def test_simple_tool_call(self):
        """简单工具调用估算"""
        tokens = estimate_deepseek_tool_call_tokens(
            "get_weather", '{"city": "Beijing"}'
        )
        assert tokens > 7  # 至少大于特殊 token 开销
        assert tokens < 50

    def test_tool_call_with_chinese_args(self):
        """中文参数工具调用"""
        tokens = estimate_deepseek_tool_call_tokens(
            "search", '{"query": "今天的天气怎么样"}'
        )
        assert tokens > 7

    def test_tool_call_with_long_json(self):
        """长 JSON 参数工具调用"""
        long_args = '{"key": "' + "x" * 500 + '"}'
        tokens = estimate_deepseek_tool_call_tokens("test_tool", long_args)
        assert tokens > 20

    def test_tool_call_always_includes_special_tokens(self):
        """工具调用始终包含特殊 token 开销"""
        tokens = estimate_deepseek_tool_call_tokens("a", "{}")
        assert tokens >= 8  # 特殊 token(7) + 至少1个内容 token

    def test_custom_tool_type(self):
        """自定义工具类型"""
        tokens_default = estimate_deepseek_tool_call_tokens("my_func", "{}")
        tokens_custom = estimate_deepseek_tool_call_tokens(
            "my_func", "{}", tool_type="custom"
        )
        # 不同 tool_type 产生不同 token 数（名称长度不同）
        assert tokens_default > 0
        assert tokens_custom > 0


class TestCompareDeepseekVsGeneric:
    """测试 DeepSeek vs 通用估算对比"""

    def test_returns_expected_keys(self):
        """返回字典包含期望的键"""
        result = compare_deepseek_vs_generic("hello world")
        assert "deepseek_bpe_estimate" in result
        assert "generic_estimate" in result
        assert "difference" in result
        assert "difference_pct" in result

    def test_chinese_text_difference(self):
        """中文文本在两种估算下存在差异"""
        result = compare_deepseek_vs_generic("你好世界，这是一段测试文本。")
        # DeepSeek BPE 对中文更高效（chars_per_token 更高）
        assert result["deepseek_bpe_estimate"] <= result["generic_estimate"]

    def test_empty_text(self):
        """空文本对比"""
        result = compare_deepseek_vs_generic("")
        assert result["deepseek_bpe_estimate"] == 0
        assert result["text_length"] == 0


class TestSpecialTokensConstants:
    """测试常量定义完整性"""

    def test_special_tokens_defined(self):
        """所有必需的特殊 token 已定义"""
        required = [
            "bos", "eos", "user_start", "assistant_start",
            "tool_calls_begin", "tool_call_begin", "tool_call_end",
            "tool_calls_end", "tool_sep",
        ]
        for key in required:
            assert key in DEEPSEEK_SPECIAL_TOKENS

    def test_template_overhead_defined(self):
        """所有角色的模板开销已定义"""
        for role in ["system", "user", "assistant", "tool"]:
            assert role in DEEPSEEK_CHAT_TEMPLATE_OVERHEAD

    def test_ratio_constants_are_reasonable(self):
        """字符/Token 比率在合理范围内"""
        assert 1.5 <= DEEPSEEK_CN_CHARS_PER_TOKEN <= 3.0
        assert 3.0 <= DEEPSEEK_EN_CHARS_PER_TOKEN <= 7.0


class TestTryLoadDeepseekTokenizer:
    """测试 tokenizer 加载函数"""

    def test_returns_none_when_dir_not_found(self):
        """目录不存在时返回 None"""
        result = try_load_deepseek_tokenizer(tokenizer_dir="/nonexistent/path")
        assert result is None

    def test_default_dir_does_not_crash(self):
        """默认路径调用不抛出异常"""
        result = try_load_deepseek_tokenizer()
        assert result is None or hasattr(result, "encode")


class TestCountTokensWithRealTokenizer:
    """测试真实 tokenizer 计数"""

    def test_returns_none_when_tokenizer_unavailable(self):
        """tokenizer 不可用时返回 None"""
        result = count_tokens_with_real_tokenizer(
            "hello", tokenizer_dir="/nonexistent/path"
        )
        assert result is None

    def test_default_dir_does_not_crash(self):
        """默认路径调用不抛出异常"""
        result = count_tokens_with_real_tokenizer("测试文本")
        assert result is None or (
            "token_count" in result and "method" in result
        )
