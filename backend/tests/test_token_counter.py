"""billing/token_counter.py 单元测试。

覆盖四层 token 计数策略：
1. count_from_usage - 解析 OpenAI / Anthropic usage 字段
2. count_from_stream - 累计流式 chunk 的 usage
3. estimate_with_tiktoken - tiktoken 估算（按 model 选 encoding）
4. estimate_with_ratio - 字符比率兜底
以及统一入口 count_tokens 的优先级调度。
"""

import sys
from unittest.mock import patch

import pytest

from billing.token_counter import (
    TokenBreakdown,
    count_from_stream,
    count_from_usage,
    count_tokens,
    estimate_with_ratio,
    estimate_with_tiktoken,
)


# ==================== count_from_usage 测试 ====================


class TestCountFromUsage:
    """测试 count_from_usage：从 API 响应 usage 字段解析 token 数"""

    def test_count_from_usage_openai_format(self):
        """OpenAI 格式 usage：prompt_tokens / completion_tokens / cached / reasoning"""
        usage = {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150,
            "prompt_tokens_details": {"cached_tokens": 20},
            "completion_tokens_details": {"reasoning_tokens": 10},
        }
        breakdown = count_from_usage(usage)
        assert breakdown.input_tokens == 100
        assert breakdown.output_tokens == 50
        assert breakdown.cache_read_tokens == 20
        assert breakdown.thoughts_tokens == 10
        assert breakdown.cache_write_tokens == 0
        assert breakdown.method == "api_usage"
        assert breakdown.estimated is False
        assert breakdown.total_tokens == 150

    def test_count_from_usage_anthropic_format(self):
        """Anthropic 格式 usage：input_tokens / output_tokens / cache_read / cache_creation"""
        usage = {
            "input_tokens": 200,
            "output_tokens": 80,
            "cache_read_input_tokens": 40,
            "cache_creation_input_tokens": 5,
        }
        breakdown = count_from_usage(usage)
        assert breakdown.input_tokens == 200
        assert breakdown.output_tokens == 80
        assert breakdown.cache_read_tokens == 40
        assert breakdown.cache_write_tokens == 5
        assert breakdown.thoughts_tokens == 0
        assert breakdown.method == "api_usage"
        assert breakdown.estimated is False

    def test_count_from_usage_mixed(self):
        """混合格式：同时存在 OpenAI 与 Anthropic 字段时累加"""
        usage = {
            "prompt_tokens": 100,
            "input_tokens": 50,
            "completion_tokens": 30,
            "output_tokens": 20,
            "prompt_tokens_details": {"cached_tokens": 10},
            "cache_read_input_tokens": 15,
            "cache_creation_input_tokens": 3,
            "completion_tokens_details": {"reasoning_tokens": 5},
        }
        breakdown = count_from_usage(usage)
        # input = prompt_tokens(100) + input_tokens(50) = 150
        assert breakdown.input_tokens == 150
        # output = completion_tokens(30) + output_tokens(20) = 50
        assert breakdown.output_tokens == 50
        # cache_read = cached_tokens(10) + cache_read_input_tokens(15) = 25
        assert breakdown.cache_read_tokens == 25
        assert breakdown.cache_write_tokens == 3
        assert breakdown.thoughts_tokens == 5

    def test_count_from_usage_none(self):
        """usage 为 None 时返回零值 breakdown"""
        breakdown = count_from_usage(None)
        assert breakdown.input_tokens == 0
        assert breakdown.output_tokens == 0
        assert breakdown.method == "api_usage"
        assert breakdown.estimated is False

    def test_count_from_usage_empty_dict(self):
        """usage 为空字典时返回零值 breakdown"""
        breakdown = count_from_usage({})
        assert breakdown.input_tokens == 0
        assert breakdown.output_tokens == 0
        assert breakdown.method == "api_usage"


# ==================== count_from_stream 测试 ====================


class TestCountFromStream:
    """测试 count_from_stream：累计流式 chunk 的 usage"""

    def test_count_from_stream_openai(self):
        """OpenAI 流式：最终 chunk 携带完整 usage，取最后一份"""
        chunks = [
            {"content": "Hello"},
            {"content": " world"},
            {"content": "", "usage": {"prompt_tokens": 100, "completion_tokens": 50}},
        ]
        breakdown = count_from_stream(chunks)
        assert breakdown.input_tokens == 100
        assert breakdown.output_tokens == 50
        assert breakdown.method == "stream"
        assert breakdown.estimated is False

    def test_count_from_stream_anthropic(self):
        """Anthropic 流式：message_delta.usage 为累积值，取最后一份覆盖"""
        chunks = [
            {"content": "Hello"},
            {"type": "message_delta", "usage": {"input_tokens": 50, "output_tokens": 20}},
            {"type": "message_delta", "usage": {"input_tokens": 100, "output_tokens": 50}},
        ]
        breakdown = count_from_stream(chunks)
        # 覆盖式取最后一份
        assert breakdown.input_tokens == 100
        assert breakdown.output_tokens == 50
        assert breakdown.method == "stream"
        assert breakdown.estimated is False

    def test_count_from_stream_no_usage(self):
        """所有 chunk 均未携带 usage 时返回零值，estimated=True 以便上层降级"""
        chunks = [
            {"content": "Hello"},
            {"content": " world"},
        ]
        breakdown = count_from_stream(chunks)
        assert breakdown.input_tokens == 0
        assert breakdown.output_tokens == 0
        assert breakdown.method == "stream"
        assert breakdown.estimated is True

    def test_count_from_stream_empty_list(self):
        """空 chunk 列表返回零值 breakdown"""
        breakdown = count_from_stream([])
        assert breakdown.input_tokens == 0
        assert breakdown.method == "stream"

    def test_count_from_stream_anthropic_with_cache(self):
        """Anthropic 流式 chunk 含 cache 字段时正确解析"""
        chunks = [
            {"content": "Hello"},
            {
                "type": "message_delta",
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "cache_read_input_tokens": 30,
                    "cache_creation_input_tokens": 8,
                },
            },
        ]
        breakdown = count_from_stream(chunks)
        assert breakdown.input_tokens == 100
        assert breakdown.output_tokens == 50
        assert breakdown.cache_read_tokens == 30
        assert breakdown.cache_write_tokens == 8


# ==================== estimate_with_tiktoken 测试 ====================


class TestEstimateWithTiktoken:
    """测试 estimate_with_tiktoken：tiktoken 估算"""

    def test_estimate_with_tiktoken_gpt4o(self):
        """gpt-4o 使用 o200k_base encoding，能正确编码英文文本"""
        tokens = estimate_with_tiktoken("Hello world, this is a test.", "gpt-4o")
        assert tokens > 0
        # o200k_base 编码 "Hello world, this is a test." 应在 6-10 token 之间
        assert 6 <= tokens <= 10

    def test_estimate_with_tiktoken_gpt35(self):
        """gpt-3.5-turbo 使用 cl100k_base encoding，能正确编码英文文本"""
        tokens = estimate_with_tiktoken("Hello world, this is a test.", "gpt-3.5-turbo")
        assert tokens > 0
        # cl100k_base 编码同一段文本也应在合理范围
        assert 6 <= tokens <= 10

    def test_estimate_with_tiktoken_unavailable(self):
        """tiktoken import 失败时返回 0"""
        # 通过 sys.modules 注入 None 模拟 tiktoken 未安装
        with patch.dict(sys.modules, {"tiktoken": None}):
            tokens = estimate_with_tiktoken("Hello world", "gpt-4o")
            assert tokens == 0

    def test_estimate_with_tiktoken_empty_text(self):
        """空文本返回 0"""
        assert estimate_with_tiktoken("", "gpt-4o") == 0

    def test_estimate_with_tiktoken_o1_series(self):
        """o1 系列使用 o200k_base encoding"""
        tokens = estimate_with_tiktoken("Hello world", "o1-mini")
        assert tokens > 0

    def test_estimate_with_tiktoken_gpt4_turbo(self):
        """gpt-4-turbo 使用 cl100k_base encoding"""
        tokens = estimate_with_tiktoken("Hello world", "gpt-4-turbo")
        assert tokens > 0

    def test_estimate_with_tiktoken_chinese_text(self):
        """中文文本能被正确编码"""
        tokens = estimate_with_tiktoken("你好世界，这是一段测试文本", "gpt-4o")
        assert tokens > 0


# ==================== estimate_with_ratio 测试 ====================


class TestEstimateWithRatio:
    """测试 estimate_with_ratio：字符比率兜底"""

    def test_estimate_with_ratio(self):
        """字符比率估算返回正数"""
        tokens = estimate_with_ratio("Hello world, this is a test.", provider="openai")
        assert tokens > 0

    def test_estimate_with_ratio_empty_text(self):
        """空文本返回 0"""
        assert estimate_with_ratio("", provider="openai") == 0

    def test_estimate_with_ratio_chinese(self):
        """中文文本按 provider 比率估算"""
        tokens = estimate_with_ratio("你好世界", provider="openai")
        assert tokens > 0

    def test_estimate_with_ratio_unknown_provider(self):
        """未知 provider 使用默认比率"""
        tokens = estimate_with_ratio("Hello world", provider="unknown_provider")
        assert tokens > 0


# ==================== count_tokens 优先级测试 ====================


class TestCountTokensPriority:
    """测试 count_tokens 统一入口的四层优先级"""

    def test_count_tokens_priority_usage(self):
        """usage 非 None 时优先使用 count_from_usage"""
        usage = {"prompt_tokens": 100, "completion_tokens": 50}
        breakdown = count_tokens(
            text="Hello world",
            provider="openai",
            model="gpt-4o",
            usage=usage,
            stream_chunks=[{"usage": {"prompt_tokens": 999}}],
        )
        assert breakdown.method == "api_usage"
        assert breakdown.input_tokens == 100
        assert breakdown.output_tokens == 50
        assert breakdown.estimated is False

    def test_count_tokens_priority_stream(self):
        """无 usage 但 stream_chunks 携带 usage 时使用 count_from_stream"""
        chunks = [
            {"content": "Hello"},
            {"usage": {"prompt_tokens": 80, "completion_tokens": 40}},
        ]
        breakdown = count_tokens(
            text="Hello world",
            provider="openai",
            model="gpt-4o",
            stream_chunks=chunks,
        )
        assert breakdown.method == "stream"
        assert breakdown.input_tokens == 80
        assert breakdown.output_tokens == 40
        assert breakdown.estimated is False

    def test_count_tokens_priority_tiktoken(self):
        """无 usage/stream 且 provider 含 openai 时使用 tiktoken"""
        breakdown = count_tokens(
            text="Hello world, this is a test.",
            provider="openai",
            model="gpt-4o",
        )
        assert breakdown.method == "tiktoken"
        assert breakdown.input_tokens > 0
        assert breakdown.estimated is True

    def test_count_tokens_priority_ratio(self):
        """非 openai provider 且无 usage/stream 时使用字符比率兜底"""
        breakdown = count_tokens(
            text="Hello world, this is a test.",
            provider="anthropic",
            model="claude-3-5-sonnet",
        )
        assert breakdown.method == "ratio"
        assert breakdown.input_tokens > 0
        assert breakdown.estimated is True

    def test_count_tokens_stream_without_usage_falls_through(self):
        """stream_chunks 提供但未携带 usage 时降级到 tiktoken/ratio"""
        chunks = [{"content": "Hello"}, {"content": " world"}]
        breakdown = count_tokens(
            text="Hello world",
            provider="openai",
            model="gpt-4o",
            stream_chunks=chunks,
        )
        # 流中没有 usage，降级到 tiktoken（openai provider）
        assert breakdown.method == "tiktoken"
        assert breakdown.input_tokens > 0

    def test_count_tokens_empty_text_no_usage(self):
        """空文本且无 usage/stream 时返回 0"""
        breakdown = count_tokens(
            text="",
            provider="anthropic",
            model="claude-3-5-sonnet",
        )
        assert breakdown.method == "ratio"
        assert breakdown.input_tokens == 0


# ==================== TokenBreakdown dataclass 测试 ====================


class TestTokenBreakdown:
    """测试 TokenBreakdown dataclass 基本行为"""

    def test_total_tokens_property(self):
        """total_tokens 属性 = input_tokens + output_tokens"""
        breakdown = TokenBreakdown(
            input_tokens=100,
            output_tokens=50,
            method="api_usage",
            estimated=False,
        )
        assert breakdown.total_tokens == 150

    def test_default_values(self):
        """默认值为零且 method=ratio, estimated=True"""
        breakdown = TokenBreakdown()
        assert breakdown.input_tokens == 0
        assert breakdown.output_tokens == 0
        assert breakdown.cache_read_tokens == 0
        assert breakdown.cache_write_tokens == 0
        assert breakdown.thoughts_tokens == 0
        assert breakdown.method == "ratio"
        assert breakdown.estimated is True
        assert breakdown.total_tokens == 0
