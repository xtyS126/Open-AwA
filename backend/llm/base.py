"""
LLM Provider 抽象基类，定义统一的 LLM 调用接口。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Type, TypeVar
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


@dataclass
class LLMRequest:
    """LLM 请求参数"""
    prompt: str
    system_prompt: Optional[str] = None
    max_tokens: int = 1000
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    top_k: Optional[float] = None
    stream: bool = False
    stop_sequences: Optional[List[str]] = None
    # 扩展思考参数（用于支持推理模型）
    thinking_budget_tokens: Optional[int] = None
    thinking_enabled: bool = False
    # 额外参数（Provider 特定）
    extra_params: Dict[str, Any] = field(default_factory=dict)


class LLMProvider(ABC):
    """
    LLM Provider 抽象基类。
    所有 Provider（OpenAI、Claude、Gemini 等）必须实现此接口。
    """

    def __init__(self, provider_name: str, model: str, api_key: str, **kwargs):
        """
        初始化 Provider。

        Args:
            provider_name: Provider 名称（如 "openai"、"claude"）
            model: 模型名称（如 "gpt-4"、"claude-3-opus"）
            api_key: API 密钥
            **kwargs: Provider 特定参数（如 base_url、timeout 等）
        """
        self.provider_name = provider_name
        self.model = model
        self.api_key = api_key
        self.config = kwargs

    @abstractmethod
    async def generate(self, request: LLMRequest) -> "LLMResponse":
        """
        生成文本响应。

        Args:
            request: LLM 请求参数

        Returns:
            LLMResponse: 包含生成内容、token 用量等信息

        Raises:
            LLMError: LLM 调用失败
            RateLimitError: 触发速率限制
        """
        pass

    @abstractmethod
    async def generate_structured(
        self, request: LLMRequest, schema: Type[T]
    ) -> T:
        """
        生成结构化输出（JSON 格式）。

        Args:
            request: LLM 请求参数
            schema: Pydantic 模型类，用于验证输出

        Returns:
            T: 符合 schema 的 Pydantic 模型实例

        Raises:
            StructuredOutputError: 结构化输出解析失败
            LLMError: LLM 调用失败
        """
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """
        检查 Provider 健康状态。

        Returns:
            bool: True 表示健康，False 表示不可用
        """
        pass

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} provider={self.provider_name} model={self.model}>"


# 延迟导入，避免循环依赖
from llm.response import LLMResponse
