"""
Token 预算管理器 — 追踪和管理对话上下文中的 Token 使用量。
支持不同模型的 Token 限制配置。
"""
from typing import Optional


# 常见模型的近似 Token 上限（实际 limits 因模型而异）
DEFAULT_MODEL_LIMITS = {
    "gpt-4o": 128000,
    "gpt-4": 8192,
    "gpt-4-turbo": 128000,
    "gpt-3.5-turbo": 16385,
    "claude-3-opus": 200000,
    "claude-3-sonnet": 200000,
    "claude-3-haiku": 200000,
    "claude-3.5-sonnet": 200000,
    "deepseek-v3": 1000000,
    "deepseek-r1": 128000,
    "qwen-max": 128000,
    "qwen-plus": 128000,
    "qwen-turbo": 128000,
    "default": 128000,
}


class TokenBudget:
    """
    Token 预算管理器。
    估算文本 Token 数，追踪使用量，判断是否需要压缩。
    """

    def __init__(self, model_name: str = "default", budget_ratio: float = 0.8):
        self.model_name = model_name
        self.budget_ratio = budget_ratio
        self._total_used: int = 0

    @property
    def max_tokens(self) -> int:
        """获取当前模型的 Token 上限。"""
        return DEFAULT_MODEL_LIMITS.get(self.model_name, 128000)

    @property
    def budget(self) -> int:
        """获取当前可用的 Token 预算。"""
        return int(self.max_tokens * self.budget_ratio)

    @property
    def usage_ratio(self) -> float:
        """获取当前使用率。"""
        if self.max_tokens <= 0:
            return 0.0
        return self._total_used / self.max_tokens

    def estimate_tokens(self, text: str) -> int:
        """
        估算文本的 Token 数量。
        使用启发式方法：英文 ~4 字符/token，中文 ~1.5 字符/token。
        """
        if not text:
            return 0

        chinese_chars = sum(1 for c in text if '一' <= c <= '鿿')
        other_chars = len(text) - chinese_chars

        # 中文字符约 1.5 字/token（实际因模型差异）
        # 英文约 4 字符/token
        return int(chinese_chars / 1.5 + other_chars / 4)

    def count_messages(self, messages: list[dict]) -> int:
        """
        计算消息列表的总 Token 数。
        """
        total = 0
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                total += self.estimate_tokens(content)
            elif isinstance(content, list):
                # 多模态消息
                for part in content:
                    if isinstance(part, dict) and "text" in part:
                        total += self.estimate_tokens(part["text"])
        return total

    def track(self, tokens: int):
        """追踪已使用的 Token。"""
        self._total_used += tokens

    def reset(self):
        """重置计数器。"""
        self._total_used = 0

    def should_compress(self) -> bool:
        """
        判断是否应该压缩上下文。
        """
        return self._total_used >= self.budget

    def remaining(self) -> int:
        """返回剩余 Token 预算。"""
        return max(0, self.budget - self._total_used)

    def get_stats(self) -> dict:
        """获取统计信息。"""
        return {
            "model": self.model_name,
            "max_tokens": self.max_tokens,
            "budget": self.budget,
            "used": self._total_used,
            "remaining": self.remaining(),
            "usage_ratio": round(self.usage_ratio, 3),
        }
