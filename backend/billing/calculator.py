"""
计费与用量管理模块，负责价格配置、预算控制、用量追踪与报表能力。
这一部分直接关联成本核算、调用统计以及运维观测。
"""

import re
import math
from typing import Optional


class CostCalculator:
    """
    封装与CostCalculator相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    CHINESE_CHARS_PER_TOKEN = 1.5
    ENGLISH_CHARS_PER_TOKEN = 4.0
    TOKEN_PER_IMAGE = 1024
    TOKEN_PER_SECOND_AUDIO = 150
    TOKEN_PER_SECOND_VIDEO = 2880

    @staticmethod
    def estimate_text_tokens(text: str) -> int:
        """
        处理estimate、text、tokens相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        if not text:
            return 0
        
        chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
        english_chars = len(re.findall(r'[a-zA-Z0-9\s]', text))
        other_chars = len(text) - chinese_chars - english_chars
        
        chinese_tokens = chinese_chars / CostCalculator.CHINESE_CHARS_PER_TOKEN
        english_tokens = english_chars / CostCalculator.ENGLISH_CHARS_PER_TOKEN
        other_tokens = other_chars / CostCalculator.ENGLISH_CHARS_PER_TOKEN
        
        return math.ceil(chinese_tokens + english_tokens + other_tokens)

    @staticmethod
    def calculate_image_tokens(num_images: int) -> int:
        """
        处理calculate、image、tokens相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        return num_images * CostCalculator.TOKEN_PER_IMAGE

    @staticmethod
    def calculate_audio_tokens(duration_seconds: float) -> int:
        """
        处理calculate、audio、tokens相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        return int(duration_seconds * CostCalculator.TOKEN_PER_SECOND_AUDIO)

    @staticmethod
    def calculate_video_tokens(duration_seconds: float) -> int:
        """
        处理calculate、video、tokens相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        return int(duration_seconds * CostCalculator.TOKEN_PER_SECOND_VIDEO)

    @staticmethod
    def calculate_multimodal_tokens(
        text: str = "",
        num_images: int = 0,
        audio_seconds: float = 0,
        video_seconds: float = 0
    ) -> dict:
        """
        处理calculate、multimodal、tokens相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        text_tokens = CostCalculator.estimate_text_tokens(text)
        image_tokens = CostCalculator.calculate_image_tokens(num_images)
        audio_tokens = CostCalculator.calculate_audio_tokens(audio_seconds)
        video_tokens = CostCalculator.calculate_video_tokens(video_seconds)
        
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
                "video_seconds": video_seconds
            }
        }

    @staticmethod
    def calculate_cost(
        input_tokens: int,
        output_tokens: int,
        input_price: float,
        output_price: float,
        cache_hit: bool = False,
        cache_hit_price: Optional[float] = None
    ) -> dict:
        """
        处理calculate、cost相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
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
            "effective_input_price": effective_input_price
        }

    @staticmethod
    def parse_api_response_tokens(usage: dict) -> dict:
        """
        解析api、response、tokens相关输入内容，并转换为内部可用结构。
        它常用于屏蔽外部协议差异并统一上层业务使用的数据格式。
        """
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        
        return {
            "input_tokens": prompt_tokens,
            "output_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens
        }
