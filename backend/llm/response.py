"""
LLM 响应数据结构，统一不同 Provider 的返回格式。
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class TokenUsage:
    """Token 用量统计"""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    def __post_init__(self):
        if self.total_tokens == 0:
            self.total_tokens = self.prompt_tokens + self.completion_tokens


@dataclass
class LLMResponse:
    """
    LLM 统一响应结构。
    所有 Provider 的返回都会被转换为这个格式。
    """
    # 生成的文本内容
    content: str
    # Token 用量
    usage: TokenUsage = field(default_factory=TokenUsage)
    # 成本（美元）
    cost: float = 0.0
    # 延迟（毫秒）
    latency_ms: int = 0
    # 模型名称
    model: str = ""
    # Provider 名称
    provider: str = ""
    # 是否成功
    success: bool = True
    # 错误信息（失败时）
    error: Optional[str] = None
    # 思维链内容（推理模型的思考过程）
    thinking_content: Optional[str] = None
    # 原始响应（Provider 特定数据）
    raw_response: Optional[Dict[str, Any]] = None
    # 完成原因（stop reason）
    finish_reason: Optional[str] = None

    @classmethod
    def error_response(cls, error_msg: str, provider: str = "", model: str = "") -> "LLMResponse":
        """创建错误响应"""
        return cls(
            content="",
            success=False,
            error=error_msg,
            provider=provider,
            model=model,
        )
