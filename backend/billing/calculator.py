"""
计费与用量管理模块，负责价格配置、预算控制、用量追踪与报表能力。
这一部分直接关联成本核算、调用统计以及运维观测。
"""

import re
import math
from typing import Optional, Dict, Tuple


class CostCalculator:
    """
    Token 估算与成本计算器。

    核心功能：
    1. 文本 token 数估算（多语言字符统计，支持不同分词器类型）
    2. 多模态 token 数计算（图片/音频/视频）
    3. API 费用计算

    分词器类型对中文文本影响显著：
    - BPE (DeepSeek/Llama): 中文每字约 0.6-0.9 token，英文每 token 约 3-3.5 字符
    - tiktoken (OpenAI/Qwen): 中文每字约 0.9-1.1 token，英文每 token 约 3.5 字符
    - SentencePiece (Google): 中文每字约 0.8-1.2 token，英文每 token 约 3.5 字符
    - Anthropic (custom): 中文每字约 0.7-0.9 token，英文每 token 约 3.8 字符

    chars_per_token 值越高 = 分词越高效（同样文字产生更少 token）。
    """

    # 默认值（通用估算，适用于未知分词器）
    DEFAULT_CHINESE_CHARS_PER_TOKEN = 1.5
    DEFAULT_ENGLISH_CHARS_PER_TOKEN = 4.0

    # 已知分词器类型的字符/Token 比率
    # 键格式: provider 或 provider:tokenizer_family
    TOKENIZER_RATIOS: Dict[str, Dict[str, float]] = {
        "openai": {
            "chinese_chars_per_token": 1.0,
            "english_chars_per_token": 3.5,
            "family": "tiktoken",
        },
        "anthropic": {
            "chinese_chars_per_token": 0.8,
            "english_chars_per_token": 3.8,
            "family": "custom_bpe",
        },
        "deepseek": {
            "chinese_chars_per_token": 2.0,
            "english_chars_per_token": 5.5,
            "family": "llama_bpe",
        },
        "google": {
            "chinese_chars_per_token": 1.0,
            "english_chars_per_token": 3.5,
            "family": "sentencepiece",
        },
        "alibaba": {
            "chinese_chars_per_token": 1.0,
            "english_chars_per_token": 3.5,
            "family": "tiktoken_like",
        },
        "moonshot": {
            "chinese_chars_per_token": 0.9,
            "english_chars_per_token": 3.5,
            "family": "custom",
        },
        "zhipu": {
            "chinese_chars_per_token": 0.8,
            "english_chars_per_token": 3.5,
            "family": "custom",
        },
        "ollama": {
            "chinese_chars_per_token": 0.7,
            "english_chars_per_token": 3.2,
            "family": "llama_bpe",
        },
    }

    # 多模态默认常量（各模型可能不同，优先使用 ModelPricing 中的值）
    TOKEN_PER_IMAGE = 1024
    TOKEN_PER_SECOND_AUDIO = 150
    TOKEN_PER_SECOND_VIDEO = 2880

    # ---- 分词器比率查询 ----

    @classmethod
    def get_tokenizer_ratios(cls, provider: Optional[str] = None) -> Dict[str, float]:
        """
        获取指定 provider 的分词器字符/Token 比率。
        未识别的 provider 退回默认值。

        Args:
            provider: 供应商名称（可选）。

        Returns:
            包含 chinese_chars_per_token 和 english_chars_per_token 的字典。
        """
        if provider:
            normalized = (provider or "").strip().lower()
            if normalized in cls.TOKENIZER_RATIOS:
                return {
                    "chinese_chars_per_token": cls.TOKENIZER_RATIOS[normalized]["chinese_chars_per_token"],
                    "english_chars_per_token": cls.TOKENIZER_RATIOS[normalized]["english_chars_per_token"],
                }
        return {
            "chinese_chars_per_token": cls.DEFAULT_CHINESE_CHARS_PER_TOKEN,
            "english_chars_per_token": cls.DEFAULT_ENGLISH_CHARS_PER_TOKEN,
        }

    @classmethod
    def get_tokenizer_family(cls, provider: Optional[str] = None) -> str:
        """
        获取指定 provider 的分词器家族名称。

        Args:
            provider: 供应商名称。

        Returns:
            分词器家族名，未知返回 "unknown"。
        """
        if provider:
            normalized = (provider or "").strip().lower()
            entry = cls.TOKENIZER_RATIOS.get(normalized)
            if entry:
                return entry.get("family", "unknown")
        return "unknown"

    # ---- 文本 Token 估算 ----

    @staticmethod
    def estimate_text_tokens(
        text: str,
        provider: Optional[str] = None,
        chinese_chars_per_token: Optional[float] = None,
        english_chars_per_token: Optional[float] = None,
    ) -> int:
        """
        估算纯文本的 token 数量。

        优先使用显式传入的比率参数，否则根据 provider 查表，最后退回默认值。

        Args:
            text: 待估算的文本。
            provider: 供应商名称，用于匹配分词器比率。
            chinese_chars_per_token: 中文每 token 字符数（可选覆盖）。
            english_chars_per_token: 英文每 token 字符数（可选覆盖）。

        Returns:
            估算 token 数（向上取整）。
        """
        if not text:
            return 0

        ratios = CostCalculator.get_tokenizer_ratios(provider)
        cn_ratio = chinese_chars_per_token if chinese_chars_per_token is not None else ratios["chinese_chars_per_token"]
        en_ratio = english_chars_per_token if english_chars_per_token is not None else ratios["english_chars_per_token"]

        chinese_chars = len(re.findall(r"[一-鿿]", text))
        english_chars = len(re.findall(r"[a-zA-Z0-9\s]", text))
        other_chars = len(text) - chinese_chars - english_chars

        chinese_tokens = chinese_chars / cn_ratio if cn_ratio > 0 else 0
        english_tokens = english_chars / en_ratio if en_ratio > 0 else 0
        other_tokens = other_chars / en_ratio if en_ratio > 0 else 0

        return math.ceil(chinese_tokens + english_tokens + other_tokens)

    # ---- 多模态 Token 计算 ----

    @staticmethod
    def calculate_image_tokens(
        num_images: int,
        token_per_image: Optional[int] = None,
    ) -> int:
        """
        计算图片 token 数。

        Args:
            num_images: 图片数量。
            token_per_image: 每张图片 token 数，默认使用类常量。
        """
        return num_images * (token_per_image if token_per_image is not None else CostCalculator.TOKEN_PER_IMAGE)

    @staticmethod
    def calculate_audio_tokens(
        duration_seconds: float,
        token_per_second: Optional[int] = None,
    ) -> int:
        """
        计算音频 token 数。

        Args:
            duration_seconds: 音频时长（秒）。
            token_per_second: 每秒音频 token 数，默认使用类常量。
        """
        return int(duration_seconds * (token_per_second if token_per_second is not None else CostCalculator.TOKEN_PER_SECOND_AUDIO))

    @staticmethod
    def calculate_video_tokens(
        duration_seconds: float,
        token_per_second: Optional[int] = None,
    ) -> int:
        """
        计算视频 token 数。

        Args:
            duration_seconds: 视频时长（秒）。
            token_per_second: 每秒视频 token 数，默认使用类常量。
        """
        return int(duration_seconds * (token_per_second if token_per_second is not None else CostCalculator.TOKEN_PER_SECOND_VIDEO))

    @staticmethod
    def calculate_multimodal_tokens(
        text: str = "",
        num_images: int = 0,
        audio_seconds: float = 0,
        video_seconds: float = 0,
        provider: Optional[str] = None,
        token_per_image: Optional[int] = None,
        token_per_second_audio: Optional[int] = None,
        token_per_second_video: Optional[int] = None,
    ) -> dict:
        """
        计算多模态内容的 token 分布。

        Args:
            text: 文本内容。
            num_images: 图片数量。
            audio_seconds: 音频时长（秒）。
            video_seconds: 视频时长（秒）。
            provider: 供应商名称，影响文本 token 估算比率。
            token_per_image: 每张图片 token 数（可选，覆盖默认值）。
            token_per_second_audio: 每秒音频 token 数（可选）。
            token_per_second_video: 每秒视频 token 数（可选）。

        Returns:
            包含各类 token 数和 content_breakdown 的字典。
        """
        text_tokens = CostCalculator.estimate_text_tokens(text, provider=provider)
        image_tokens = CostCalculator.calculate_image_tokens(num_images, token_per_image=token_per_image)
        audio_tokens = CostCalculator.calculate_audio_tokens(audio_seconds, token_per_second=token_per_second_audio)
        video_tokens = CostCalculator.calculate_video_tokens(video_seconds, token_per_second=token_per_second_video)

        total_tokens = text_tokens + image_tokens + audio_tokens + video_tokens

        return {
            "text_tokens": text_tokens,
            "image_tokens": image_tokens,
            "audio_tokens": audio_tokens,
            "video_tokens": video_tokens,
            "total_tokens": total_tokens,
            "content_breakdown": {
                "text": text_tokens,
                "image": num_images,
                "audio_seconds": audio_seconds,
                "video_seconds": video_seconds,
            },
        }

    # ---- 费用计算 ----

    @staticmethod
    def calculate_cost(
        input_tokens: int,
        output_tokens: int,
        input_price: float,
        output_price: float,
        cache_hit: bool = False,
        cache_hit_price: Optional[float] = None,
    ) -> dict:
        """
        计算 API 调用费用。

        所有价格均以「每百万 token」为单位，公式：
            cost = (tokens / 1_000_000) * price_per_million

        Args:
            input_tokens: 输入 token 数。
            output_tokens: 输出 token 数。
            input_price: 输入价格（每百万 token）。
            output_price: 输出价格（每百万 token）。
            cache_hit: 是否命中缓存。
            cache_hit_price: 缓存命中时的输入价格（每百万 token）。

        Returns:
            包含 input_cost / output_cost / total_cost 的字典。
        """
        if cache_hit and cache_hit_price is not None:
            effective_input_price = cache_hit_price
        else:
            effective_input_price = input_price

        input_cost = (input_tokens / 1_000_000) * effective_input_price
        output_cost = (output_tokens / 1_000_000) * output_price
        total_cost = input_cost + output_cost

        return {
            "input_cost": round(input_cost, 6),
            "output_cost": round(output_cost, 6),
            "total_cost": round(total_cost, 6),
            "cache_hit": cache_hit,
            "effective_input_price": effective_input_price,
        }

    # ---- API 返回解析 ----

    @staticmethod
    def parse_api_response_tokens(usage: dict) -> dict:
        """
        从 API 返回的 usage 中解析 token 数量。

        兼容多种字段命名：
        - prompt_tokens / completion_tokens（OpenAI 风格）
        - input_tokens / output_tokens（Anthropic 风格）
        - total_tokens（通用字段）

        Args:
            usage: API 返回的 usage 字典。

        Returns:
            规范化为 input_tokens / output_tokens / total_tokens 的字典。
        """
        input_tokens = usage.get("prompt_tokens") or usage.get("input_tokens") or 0
        output_tokens = usage.get("completion_tokens") or usage.get("output_tokens") or 0

        return {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        }

    # ---- 综合估算（用于没有 API usage 返回时的兜底） ----

    @classmethod
    def estimate_cost_from_text(
        cls,
        input_text: str,
        output_text: str,
        provider: str,
        model: str,
        input_price: float,
        output_price: float,
        cache_hit: bool = False,
        cache_hit_price: Optional[float] = None,
    ) -> dict:
        """
        纯文本调用场景下的端到端费用估算。
        当 API 未返回 usage 信息时使用此方法兜底。

        Args:
            input_text: 输入文本。
            output_text: 输出文本。
            provider: 供应商名称。
            model: 模型名称。
            input_price: 每百万 token 输入价格。
            output_price: 每百万 token 输出价格。
            cache_hit: 是否命中缓存。
            cache_hit_price: 缓存命中时的输入价格。

        Returns:
            包含估算 token 数和费用的字典。
        """
        input_tokens = cls.estimate_text_tokens(input_text, provider=provider)
        output_tokens = cls.estimate_text_tokens(output_text, provider=provider)

        cost = cls.calculate_cost(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            input_price=input_price,
            output_price=output_price,
            cache_hit=cache_hit,
            cache_hit_price=cache_hit_price,
        )

        return {
            "provider": provider,
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "input_cost": cost["input_cost"],
            "output_cost": cost["output_cost"],
            "total_cost": cost["total_cost"],
            "currency": "USD",
            "estimation_method": "character_based",
            "tokenizer_family": cls.get_tokenizer_family(provider),
        }
