import re
import math


class CostCalculator:
    CHINESE_CHARS_PER_TOKEN = 1.5
    ENGLISH_CHARS_PER_TOKEN = 4.0
    TOKEN_PER_IMAGE = 1024
    TOKEN_PER_SECOND_AUDIO = 150
    TOKEN_PER_SECOND_VIDEO = 2880

    @staticmethod
    def estimate_text_tokens(text: str) -> int:
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
        return num_images * CostCalculator.TOKEN_PER_IMAGE

    @staticmethod
    def calculate_audio_tokens(duration_seconds: float) -> int:
        return int(duration_seconds * CostCalculator.TOKEN_PER_SECOND_AUDIO)

    @staticmethod
    def calculate_video_tokens(duration_seconds: float) -> int:
        return int(duration_seconds * CostCalculator.TOKEN_PER_SECOND_VIDEO)

    @staticmethod
    def calculate_multimodal_tokens(
        text: str = "",
        num_images: int = 0,
        audio_seconds: float = 0,
        video_seconds: float = 0
    ) -> dict:
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
        cache_hit_price: float = None
    ) -> dict:
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
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        
        return {
            "input_tokens": prompt_tokens,
            "output_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens
        }
