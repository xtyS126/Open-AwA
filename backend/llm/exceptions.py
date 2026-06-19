"""
LLM 相关异常类定义。
"""

from typing import Optional


class LLMError(Exception):
    """LLM 调用基础异常"""

    def __init__(self, message: str, provider: str = "", model: str = ""):
        super().__init__(message)
        self.message = message
        self.provider = provider
        self.model = model


class ProviderNotFoundError(LLMError):
    """Provider 未找到异常"""

    def __init__(self, provider_name: str):
        super().__init__(
            f"Provider '{provider_name}' 未注册或不可用",
            provider=provider_name,
        )
        self.provider_name = provider_name


class RateLimitError(LLMError):
    """速率限制异常"""

    def __init__(self, message: str = "触发速率限制", provider: str = "", model: str = "", retry_after: Optional[float] = None):
        super().__init__(message, provider=provider, model=model)
        self.retry_after = retry_after


class StructuredOutputError(LLMError):
    """结构化输出解析异常"""

    def __init__(
        self,
        message: str,
        raw_output: str = "",
        reason: str = "",
        provider: str = "",
        model: str = "",
    ):
        super().__init__(message, provider=provider, model=model)
        self.raw_output = raw_output
        self.reason = reason


class AuthenticationError(LLMError):
    """认证失败异常"""

    def __init__(self, message: str = "API 密钥无效或已过期", provider: str = "", model: str = ""):
        super().__init__(message, provider=provider, model=model)


class TimeoutError(LLMError):
    """请求超时异常"""

    def __init__(self, message: str = "请求超时", provider: str = "", model: str = "", timeout: float = 0):
        super().__init__(message, provider=provider, model=model)
        self.timeout = timeout
