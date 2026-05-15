"""
billing/calculator.py 单元测试。
覆盖 CostCalculator 的 Token 估算、多模态计算、费用计算和 API 解析等全部方法。
"""

import pytest
from billing.calculator import CostCalculator


# ==================== 分词器比率查询测试 ====================

class TestGetTokenizerRatios:
    """测试 get_tokenizer_ratios 方法：供应商分词器字符/Token 比率查询"""

    def test_openai_returns_tiktoken_ratios(self):
        """已知供应商 openai 返回对应的中文/英文比率"""
        ratios = CostCalculator.get_tokenizer_ratios("openai")
        assert ratios["chinese_chars_per_token"] == 1.0
        assert ratios["english_chars_per_token"] == 3.5

    def test_deepseek_returns_llama_bpe_ratios(self):
        """已知供应商 deepseek 返回对应的中文/英文比率"""
        ratios = CostCalculator.get_tokenizer_ratios("deepseek")
        assert ratios["chinese_chars_per_token"] == 2.0
        assert ratios["english_chars_per_token"] == 5.5

    def test_anthropic_returns_custom_bpe_ratios(self):
        """已知供应商 anthropic 返回对应的比率"""
        ratios = CostCalculator.get_tokenizer_ratios("anthropic")
        assert ratios["chinese_chars_per_token"] == 0.8
        assert ratios["english_chars_per_token"] == 3.8

    def test_provider_case_insensitive(self):
        """供应商名称大小写不敏感"""
        lower = CostCalculator.get_tokenizer_ratios("openai")
        upper = CostCalculator.get_tokenizer_ratios("OPENAI")
        assert lower == upper

    def test_provider_with_whitespace(self):
        """供应商名称前后空格不影响匹配"""
        ratios = CostCalculator.get_tokenizer_ratios("  openai  ")
        assert ratios["chinese_chars_per_token"] == 1.0

    def test_unknown_provider_returns_defaults(self):
        """未知供应商返回默认比率"""
        ratios = CostCalculator.get_tokenizer_ratios("unknown_provider")
        assert ratios["chinese_chars_per_token"] == 1.5
        assert ratios["english_chars_per_token"] == 4.0

    def test_none_provider_returns_defaults(self):
        """provider 为 None 时返回默认比率"""
        ratios = CostCalculator.get_tokenizer_ratios(None)
        assert ratios["chinese_chars_per_token"] == 1.5
        assert ratios["english_chars_per_token"] == 4.0

    def test_empty_provider_returns_defaults(self):
        """空字符串供应商返回默认比率"""
        ratios = CostCalculator.get_tokenizer_ratios("")
        assert ratios["chinese_chars_per_token"] == 1.5

    def test_all_known_providers_have_ratios(self):
        """所有已知供应商都有中文和英文比率键"""
        for provider in CostCalculator.TOKENIZER_RATIOS:
            ratios = CostCalculator.get_tokenizer_ratios(provider)
            assert "chinese_chars_per_token" in ratios
            assert "english_chars_per_token" in ratios
            assert ratios["chinese_chars_per_token"] > 0
            assert ratios["english_chars_per_token"] > 0


# ==================== 分词器家族查询测试 ====================

class TestGetTokenizerFamily:
    """测试 get_tokenizer_family 方法"""

    def test_openai_family_is_tiktoken(self):
        """openai 分词器家族为 tiktoken"""
        assert CostCalculator.get_tokenizer_family("openai") == "tiktoken"

    def test_deepseek_family_is_llama_bpe(self):
        """deepseek 分词器家族为 llama_bpe"""
        assert CostCalculator.get_tokenizer_family("deepseek") == "llama_bpe"

    def test_unknown_provider_returns_unknown(self):
        """未知供应商返回 unknown"""
        assert CostCalculator.get_tokenizer_family("unknown") == "unknown"

    def test_none_provider_returns_unknown(self):
        """None 供应商返回 unknown"""
        assert CostCalculator.get_tokenizer_family(None) == "unknown"


# ==================== 文本 Token 估算测试 ====================

class TestEstimateTextTokens:
    """测试 estimate_text_tokens 方法：纯文本 token 估算"""

    def test_empty_text_returns_zero(self):
        """空文本返回 0 token"""
        assert CostCalculator.estimate_text_tokens("") == 0

    def test_chinese_only_text_with_openai(self):
        """纯中文使用 openai 比率估算"""
        text = "你好世界"
        tokens = CostCalculator.estimate_text_tokens(text, provider="openai")
        # 4 个中文字 / 1.0 = 4，向上取整为 4
        assert tokens == 4

    def test_english_only_text_with_openai(self):
        """纯英文使用 openai 比率估算"""
        text = "Hello world"
        tokens = CostCalculator.estimate_text_tokens(text, provider="openai")
        # 11 个英文字符 / 3.5 ≈ 3.14 → 向上取整 4
        assert tokens == 4

    def test_mixed_cn_en_text(self):
        """中英文混合估算结果为正数"""
        text = "你好 world 测试 hello"
        tokens = CostCalculator.estimate_text_tokens(text, provider="openai")
        assert tokens >= 1

    def test_zero_cn_ratio_handles_gracefully(self):
        """中文比率为 0 时不引发除零错误"""
        tokens = CostCalculator.estimate_text_tokens(
            "测试", chinese_chars_per_token=0
        )
        assert tokens >= 0

    def test_zero_en_ratio_handles_gracefully(self):
        """英文比率为 0 时不引发除零错误"""
        tokens = CostCalculator.estimate_text_tokens(
            "test", english_chars_per_token=0
        )
        assert tokens >= 0

    def test_deepseek_more_efficient_for_chinese(self):
        """DeepSeek 对中文的分词效率更高（chars_per_token 更大 → 更少 token）"""
        text = "这是很长的一段中文测试文本内容"
        openai_tokens = CostCalculator.estimate_text_tokens(text, provider="openai")
        deepseek_tokens = CostCalculator.estimate_text_tokens(text, provider="deepseek")
        assert deepseek_tokens < openai_tokens

    def test_explicit_ratios_override_provider(self):
        """显式传入比率覆盖 supplier 匹配值"""
        text = "hello"
        default = CostCalculator.estimate_text_tokens(text, provider="openai")
        overridden = CostCalculator.estimate_text_tokens(
            text,
            provider="openai",
            english_chars_per_token=10.0
        )
        assert overridden < default

    def test_long_text_estimation(self):
        """极大文本的 token 估算应合理"""
        text = "A" * 100000
        tokens = CostCalculator.estimate_text_tokens(text, provider="openai")
        assert tokens > 0
        assert tokens <= 100000  # 不会超出字符总数

    def test_one_char_returns_one_token(self):
        """单字符估算结果至少为 1"""
        tokens = CostCalculator.estimate_text_tokens("x", provider="openai")
        assert tokens == 1

    def test_no_provider_uses_defaults(self):
        """不传 provider 使用默认比率"""
        tokens = CostCalculator.estimate_text_tokens("hello")
        assert tokens > 0


# ==================== 图片 Token 计算测试 ====================

class TestCalculateImageTokens:
    """测试 calculate_image_tokens 方法"""

    def test_zero_images_returns_zero(self):
        """0 张图片返回 0 token"""
        assert CostCalculator.calculate_image_tokens(0) == 0

    def test_single_image_default(self):
        """单张图片使用默认每张 token 数"""
        tokens = CostCalculator.calculate_image_tokens(1)
        assert tokens == 1024

    def test_multiple_images(self):
        """多张图片正确累乘"""
        tokens = CostCalculator.calculate_image_tokens(5)
        assert tokens == 5 * 1024

    def test_custom_token_per_image(self):
        """自定义每张图片 token 数"""
        tokens = CostCalculator.calculate_image_tokens(3, token_per_image=512)
        assert tokens == 3 * 512

    def test_large_number_of_images(self):
        """大量图片 token 数"""
        tokens = CostCalculator.calculate_image_tokens(1000)
        assert tokens == 1000 * 1024


# ==================== 音频 Token 计算测试 ====================

class TestCalculateAudioTokens:
    """测试 calculate_audio_tokens 方法"""

    def test_zero_duration_returns_zero(self):
        """0 秒音频返回 0"""
        assert CostCalculator.calculate_audio_tokens(0) == 0

    def test_short_audio_default(self):
        """短音频使用默认比率"""
        tokens = CostCalculator.calculate_audio_tokens(10)
        assert tokens == 10 * 150

    def test_fractional_seconds(self):
        """带小数的秒数"""
        tokens = CostCalculator.calculate_audio_tokens(1.5)
        assert tokens == int(1.5 * 150)

    def test_custom_token_per_second(self):
        """自定义每秒音频 token 数"""
        tokens = CostCalculator.calculate_audio_tokens(60, token_per_second=200)
        assert tokens == 60 * 200


# ==================== 视频 Token 计算测试 ====================

class TestCalculateVideoTokens:
    """测试 calculate_video_tokens 方法"""

    def test_zero_duration_returns_zero(self):
        """0 秒视频返回 0"""
        assert CostCalculator.calculate_video_tokens(0) == 0

    def test_short_video_default(self):
        """短视频使用默认比率"""
        tokens = CostCalculator.calculate_video_tokens(30)
        assert tokens == 30 * 2880

    def test_custom_token_per_second(self):
        """自定义每秒视频 token 数"""
        tokens = CostCalculator.calculate_video_tokens(15, token_per_second=3000)
        assert tokens == 15 * 3000


# ==================== 多模态 Token 计算测试 ====================

class TestCalculateMultimodalTokens:
    """测试 calculate_multimodal_tokens 方法：综合多模态 token 计算"""

    def test_text_only_multimodal(self):
        """仅文本输入的多模态计算"""
        result = CostCalculator.calculate_multimodal_tokens(
            text="Hello world", provider="openai"
        )
        assert result["text_tokens"] > 0
        assert result["image_tokens"] == 0
        assert result["audio_tokens"] == 0
        assert result["video_tokens"] == 0
        assert result["total_tokens"] == result["text_tokens"]

    def test_mixed_multimodal_content(self):
        """文本 + 图片 + 音频 + 视频混合"""
        result = CostCalculator.calculate_multimodal_tokens(
            text="Describe this image",
            num_images=2,
            audio_seconds=30,
            video_seconds=10,
            provider="openai"
        )
        assert result["text_tokens"] > 0
        assert result["image_tokens"] == 2 * 1024
        assert result["audio_tokens"] == 30 * 150
        assert result["video_tokens"] == 10 * 2880
        total = (result["text_tokens"] + result["image_tokens"]
                 + result["audio_tokens"] + result["video_tokens"])
        assert result["total_tokens"] == total

    def test_content_breakdown_structure(self):
        """返回的 content_breakdown 结构正确"""
        result = CostCalculator.calculate_multimodal_tokens(
            text="test", num_images=1, audio_seconds=5, video_seconds=3
        )
        breakdown = result["content_breakdown"]
        assert "text" in breakdown
        assert "image" in breakdown
        assert "audio_seconds" in breakdown
        assert "video_seconds" in breakdown
        assert breakdown["image"] == 1
        assert breakdown["audio_seconds"] == 5
        assert breakdown["video_seconds"] == 3

    def test_all_zero_inputs(self):
        """全部为 0 的输入返回全零结果"""
        result = CostCalculator.calculate_multimodal_tokens()
        assert result["total_tokens"] == 0
        assert result["text_tokens"] == 0

    def test_custom_multimodal_parameters(self):
        """自定义多模态参数覆盖默认值"""
        result = CostCalculator.calculate_multimodal_tokens(
            text="test",
            num_images=1,
            token_per_image=512,
            token_per_second_audio=200,
            token_per_second_video=3000,
        )
        assert result["image_tokens"] == 512
        assert result["audio_tokens"] == 0
        assert result["video_tokens"] == 0


# ==================== API 费用计算测试 ====================

class TestCalculateCost:
    """测试 calculate_cost 方法：API 调用费用计算"""

    def test_normal_gpt4o_cost(self):
        """GPT-4o 正常计费：input=$2.50/M, output=$10.00/M"""
        result = CostCalculator.calculate_cost(
            input_tokens=1000,
            output_tokens=500,
            input_price=2.50,
            output_price=10.00,
        )
        # (1000 / 1_000_000) * 2.50 = 0.0025
        assert result["input_cost"] == pytest.approx(0.0025)
        # (500 / 1_000_000) * 10.00 = 0.005
        assert result["output_cost"] == pytest.approx(0.005)
        assert result["total_cost"] == pytest.approx(0.0075)
        assert result["cache_hit"] is False

    def test_normal_deepseek_cost(self):
        """DeepSeek 正常计费：input=$0.14/M, output=$0.28/M"""
        result = CostCalculator.calculate_cost(
            input_tokens=10000,
            output_tokens=5000,
            input_price=0.14,
            output_price=0.28,
        )
        assert result["input_cost"] == pytest.approx(0.0014)
        assert result["output_cost"] == pytest.approx(0.0014)
        assert result["total_cost"] == pytest.approx(0.0028)

    def test_zero_tokens_zero_cost(self):
        """0 Token 调用费用为 0"""
        result = CostCalculator.calculate_cost(
            input_tokens=0,
            output_tokens=0,
            input_price=2.50,
            output_price=10.00,
        )
        assert result["input_cost"] == 0.0
        assert result["output_cost"] == 0.0
        assert result["total_cost"] == 0.0

    def test_zero_input_tokens_only_output(self):
        """仅 0 输入 Token，输出正常计费"""
        result = CostCalculator.calculate_cost(
            input_tokens=0,
            output_tokens=1000,
            input_price=2.50,
            output_price=10.00,
        )
        assert result["input_cost"] == 0.0
        assert result["output_cost"] == pytest.approx(0.01)

    def test_zero_output_tokens_only_input(self):
        """仅 0 输出 Token，输入正常计费"""
        result = CostCalculator.calculate_cost(
            input_tokens=1000,
            output_tokens=0,
            input_price=2.50,
            output_price=10.00,
        )
        assert result["input_cost"] == pytest.approx(0.0025)
        assert result["output_cost"] == 0.0

    def test_large_token_count(self):
        """极大 Token 数调用：百万级"""
        result = CostCalculator.calculate_cost(
            input_tokens=1_000_000,
            output_tokens=500_000,
            input_price=2.50,
            output_price=10.00,
        )
        assert result["input_cost"] == pytest.approx(2.50)
        assert result["output_cost"] == pytest.approx(5.00)
        assert result["total_cost"] == pytest.approx(7.50)

    def test_cache_hit_reduces_input_cost(self):
        """缓存命中时使用更低的输入价格"""
        result = CostCalculator.calculate_cost(
            input_tokens=10000,
            output_tokens=5000,
            input_price=2.50,
            output_price=10.00,
            cache_hit=True,
            cache_hit_price=1.25,
        )
        assert result["cache_hit"] is True
        # (10000 / 1_000_000) * 1.25 = 0.0125
        assert result["input_cost"] == pytest.approx(0.0125)

    def test_cache_hit_without_cache_price_uses_normal(self):
        """缓存命中但未提供缓存价格时使用正常输入价格"""
        result = CostCalculator.calculate_cost(
            input_tokens=1000,
            output_tokens=500,
            input_price=2.50,
            output_price=10.00,
            cache_hit=True,
            cache_hit_price=None,
        )
        assert result["cache_hit"] is True
        assert result["input_cost"] == pytest.approx(0.0025)

    def test_rounding_precision(self):
        """费用结果保留 6 位小数"""
        result = CostCalculator.calculate_cost(
            input_tokens=1,
            output_tokens=1,
            input_price=0.0001,
            output_price=0.0001,
        )
        # 验证舍入精度
        assert result["input_cost"] == round(1 / 1_000_000 * 0.0001, 6)
        assert result["output_cost"] == round(1 / 1_000_000 * 0.0001, 6)

    def test_effective_input_price_in_result(self):
        """结果中包含 effective_input_price 字段"""
        result = CostCalculator.calculate_cost(
            input_tokens=1000,
            output_tokens=500,
            input_price=2.50,
            output_price=10.00,
        )
        assert result["effective_input_price"] == 2.50


# ==================== API 返回解析测试 ====================

class TestParseApiResponseTokens:
    """测试 parse_api_response_tokens 方法：API usage 字段解析"""

    def test_openai_style_fields(self):
        """OpenAI 风格字段：prompt_tokens / completion_tokens"""
        usage = {"prompt_tokens": 150, "completion_tokens": 80, "total_tokens": 230}
        result = CostCalculator.parse_api_response_tokens(usage)
        assert result["input_tokens"] == 150
        assert result["output_tokens"] == 80
        assert result["total_tokens"] == 230

    def test_anthropic_style_fields(self):
        """Anthropic 风格字段：input_tokens / output_tokens"""
        usage = {"input_tokens": 200, "output_tokens": 100}
        result = CostCalculator.parse_api_response_tokens(usage)
        assert result["input_tokens"] == 200
        assert result["output_tokens"] == 100
        assert result["total_tokens"] == 300

    def test_missing_fields_default_to_zero(self):
        """缺失字段默认为 0"""
        usage = {}
        result = CostCalculator.parse_api_response_tokens(usage)
        assert result["input_tokens"] == 0
        assert result["output_tokens"] == 0
        assert result["total_tokens"] == 0

    def test_null_values_default_to_zero(self):
        """字段值为 None 时默认为 0"""
        usage = {"prompt_tokens": None, "completion_tokens": None}
        result = CostCalculator.parse_api_response_tokens(usage)
        assert result["input_tokens"] == 0
        assert result["output_tokens"] == 0

    def test_mixed_field_styles_prefers_openai(self):
        """同时存在两种风格字段时优先使用 OpenAI 风格"""
        usage = {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "input_tokens": 999,
            "output_tokens": 888,
        }
        result = CostCalculator.parse_api_response_tokens(usage)
        # prompt_tokens 优先于 input_tokens
        assert result["input_tokens"] == 100
        assert result["output_tokens"] == 50


# ==================== 端到端文本费用估算测试 ====================

class TestEstimateCostFromText:
    """测试 estimate_cost_from_text 方法：纯文本端到端费用估算"""

    def test_basic_openai_estimation(self):
        """OpenAI GPT-4o 基本文本调用估算"""
        result = CostCalculator.estimate_cost_from_text(
            input_text="What is the capital of France?",
            output_text="The capital of France is Paris.",
            provider="openai",
            model="gpt-4o",
            input_price=2.50,
            output_price=10.00,
        )
        assert result["provider"] == "openai"
        assert result["model"] == "gpt-4o"
        assert result["input_tokens"] > 0
        assert result["output_tokens"] > 0
        assert result["total_cost"] > 0
        assert result["currency"] == "USD"
        assert result["estimation_method"] == "character_based"
        assert result["tokenizer_family"] == "tiktoken"

    def test_empty_input_text(self):
        """空输入文本的估算"""
        result = CostCalculator.estimate_cost_from_text(
            input_text="",
            output_text="Hello",
            provider="openai",
            model="gpt-4o",
            input_price=2.50,
            output_price=10.00,
        )
        assert result["input_tokens"] == 0
        assert result["output_tokens"] > 0

    def test_empty_output_text(self):
        """空输出文本的估算"""
        result = CostCalculator.estimate_cost_from_text(
            input_text="Hello",
            output_text="",
            provider="openai",
            model="gpt-4o",
            input_price=2.50,
            output_price=10.00,
        )
        assert result["input_tokens"] > 0
        assert result["output_tokens"] == 0

    def test_deepseek_estimation(self):
        """DeepSeek 模型估算"""
        result = CostCalculator.estimate_cost_from_text(
            input_text="什么是深度学习？",
            output_text="深度学习是机器学习的一个分支。",
            provider="deepseek",
            model="deepseek-chat",
            input_price=0.14,
            output_price=0.28,
        )
        assert result["provider"] == "deepseek"
        assert result["tokenizer_family"] == "llama_bpe"

    def test_cache_hit_estimation(self):
        """缓存命中时的估算"""
        result = CostCalculator.estimate_cost_from_text(
            input_text="Hello world",
            output_text="Hi there!",
            provider="openai",
            model="gpt-4o",
            input_price=2.50,
            output_price=10.00,
            cache_hit=True,
            cache_hit_price=1.25,
        )
        assert result["input_cost"] < result["output_cost"]

    def test_chinese_text_estimation(self):
        """纯中文文本的估算"""
        result = CostCalculator.estimate_cost_from_text(
            input_text="请介绍一下人工智能的发展历史。",
            output_text="人工智能的发展可以追溯到20世纪50年代。",
            provider="openai",
            model="gpt-4o",
            input_price=2.50,
            output_price=10.00,
        )
        assert result["input_tokens"] > 0
        assert result["output_tokens"] > 0

    def test_different_providers_give_different_token_counts(self):
        """不同供应商对相同文本估算出不同 token 数"""
        text = "你好世界，这是一段中文测试文本"
        openai_result = CostCalculator.estimate_cost_from_text(
            input_text=text,
            output_text="ok",
            provider="openai",
            model="gpt-4o",
            input_price=2.50,
            output_price=10.00,
        )
        deepseek_result = CostCalculator.estimate_cost_from_text(
            input_text=text,
            output_text="ok",
            provider="deepseek",
            model="deepseek-chat",
            input_price=0.14,
            output_price=0.28,
        )
        assert openai_result["input_tokens"] != deepseek_result["input_tokens"]
