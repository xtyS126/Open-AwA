"""
Anthropic Claude Provider 适配器。

实现 LLMProvider 接口，支持 Claude 3.5/3.0 系列模型的流式/非流式调用、
扩展思考（extended thinking）、结构化输出解析、指数退避重试。
"""

from __future__ import annotations

import asyncio
import random
import time
from typing import Any, AsyncGenerator, Dict, List, Optional, Type, TypeVar

from loguru import logger
from pydantic import BaseModel

from llm.base import LLMProvider, LLMRequest
from llm.exceptions import (
    AuthenticationError,
    LLMError,
    RateLimitError,
    StructuredOutputError,
    TimeoutError,
)
from llm.json_utils import parse_structured_output
from llm.response import LLMResponse, TokenUsage

T = TypeVar("T", bound=BaseModel)

# Anthropic SDK 可选导入，未安装时给出明确提示
try:
    import anthropic
    from anthropic import AsyncAnthropic, APIError, APITimeoutError, RateLimitError as AnthropicRateLimit
    _ANTHROPIC_AVAILABLE = True
except ImportError:
    _ANTHROPIC_AVAILABLE = False
    anthropic = None  # type: ignore
    AsyncAnthropic = None  # type: ignore
    APIError = Exception  # type: ignore
    APITimeoutError = Exception  # type: ignore
    AnthropicRateLimit = Exception  # type: ignore

# Claude 3.5/3.0 系列模型名称前缀，用于校验模型兼容性
CLAUDE_MODEL_PREFIXES = (
    "claude-3",
    "claude-3.5",
)

# 默认 API 端点
DEFAULT_API_BASE = "https://api.anthropic.com"

# 重试配置
DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 1.0
DEFAULT_MAX_DELAY = 30.0

# 默认请求超时（秒）
DEFAULT_TIMEOUT = 120.0


def _check_anthropic_available() -> None:
    """检查 Anthropic SDK 是否已安装。"""
    if not _ANTHROPIC_AVAILABLE:
        raise RuntimeError(
            "Anthropic SDK 未安装，无法使用 Claude Provider。"
            "请执行 `pip install anthropic` 安装。"
        )


def _is_claude_model(model: str) -> bool:
    """判断模型名称是否属于 Claude 3.0/3.5 系列。"""
    normalized = model.strip().lower()
    return any(normalized.startswith(prefix) for prefix in CLAUDE_MODEL_PREFIXES)


async def _exponential_backoff(
    attempt: int,
    base_delay: float = DEFAULT_BASE_DELAY,
    max_delay: float = DEFAULT_MAX_DELAY,
    retry_after: Optional[float] = None,
) -> None:
    """
    指数退避等待。

    计算公式: delay = clamp(base_delay * 2^attempt + random_jitter, 0, max_delay)
    如果提供了 retry_after，优先使用服务端建议的等待时间。
    """
    if retry_after is not None and retry_after > 0:
        delay = min(retry_after + random.uniform(0, 0.5), max_delay)
    else:
        delay = base_delay * (2 ** attempt) + random.uniform(0, 0.5)
        delay = min(delay, max_delay)
    await asyncio.sleep(delay)


def _extract_retry_after(exc: Exception) -> Optional[float]:
    """
    从异常的响应头中提取 Retry-After 值（秒）。
    Anthropic SDK 的 RateLimitError 可能携带 retry_after 属性。
    """
    # Anthropic SDK RateLimitError 有 retry_after 属性
    retry_after = getattr(exc, "retry_after", None)
    if retry_after is not None:
        try:
            return float(retry_after)
        except (ValueError, TypeError):
            pass

    # 尝试从 response headers 中提取
    response = getattr(exc, "response", None)
    if response is not None:
        headers = getattr(response, "headers", None)
        if headers is not None:
            raw = headers.get("Retry-After") or headers.get("retry-after")
            if raw is not None:
                try:
                    return float(raw)
                except (ValueError, TypeError):
                    pass
    return None


def _map_anthropic_error(
    exc: Exception,
    provider: str,
    model: str,
) -> LLMError:
    """
    将 Anthropic SDK 异常映射为项目统一的 LLMError 子类。

    Args:
        exc: Anthropic SDK 抛出的异常
        provider: Provider 名称
        model: 模型名称

    Returns:
        LLMError: 映射后的统一异常
    """
    status_code = getattr(exc, "status_code", None)

    # 认证错误
    if status_code == 401:
        return AuthenticationError(
            message="Claude API 认证失败，请检查 API Key 配置",
            provider=provider,
            model=model,
        )

    # 速率限制
    if status_code == 429 or isinstance(exc, AnthropicRateLimit):
        retry_after = _extract_retry_after(exc)
        return RateLimitError(
            message="Claude API 请求频率超限，请稍后重试",
            provider=provider,
            model=model,
            retry_after=retry_after,
        )

    # 超时
    if isinstance(exc, APITimeoutError):
        return TimeoutError(
            message="Claude API 请求超时",
            provider=provider,
            model=model,
            timeout=DEFAULT_TIMEOUT,
        )

    # 其他 API 错误
    error_message = str(exc)
    if hasattr(exc, "message"):
        error_message = str(exc.message)
    return LLMError(
        message=f"Claude API 调用失败: {error_message[:500]}",
        provider=provider,
        model=model,
    )


def _build_messages(prompt: str) -> List[Dict[str, Any]]:
    """
    将纯文本 prompt 转换为 Anthropic Messages API 所需的 messages 格式。

    Args:
        prompt: 用户输入的文本

    Returns:
        符合 Anthropic messages 格式的消息列表
    """
    return [{"role": "user", "content": prompt}]


def _build_thinking_config(request: LLMRequest) -> Dict[str, Any]:
    """
    根据请求参数构建 extended thinking 配置。

    Claude 的 extended thinking 需要传入 thinking 参数块，
    包含 type="enabled" 和 budget_tokens。

    Args:
        request: LLM 请求参数

    Returns:
        thinking 配置字典，未启用时返回空字典
    """
    if not request.thinking_enabled:
        return {}

    # budget_tokens 默认取 max_tokens 的 80%，最少 1024
    budget = request.thinking_budget_tokens
    if budget is None:
        budget = max(1024, int(request.max_tokens * 0.8))

    return {
        "thinking": {
            "type": "enabled",
            "budget_tokens": budget,
        }
    }


def _extract_response_text(response: Any) -> str:
    """
    从 Anthropic API 响应中提取文本内容。

    Claude Messages API 的响应结构:
    {
        "content": [
            {"type": "text", "text": "..."},
            {"type": "thinking", "thinking": "..."}  # 当启用 extended thinking 时
        ]
    }
    """
    content_blocks = getattr(response, "content", [])
    text_parts: List[str] = []
    for block in content_blocks:
        block_type = getattr(block, "type", None)
        if block_type == "text":
            text_parts.append(getattr(block, "text", ""))
    return "".join(text_parts)


def _extract_thinking_content(response: Any) -> Optional[str]:
    """
    从 Anthropic API 响应中提取 extended thinking 内容。
    """
    content_blocks = getattr(response, "content", [])
    thinking_parts: List[str] = []
    for block in content_blocks:
        block_type = getattr(block, "type", None)
        if block_type == "thinking":
            thinking_parts.append(getattr(block, "thinking", ""))
    if thinking_parts:
        return "".join(thinking_parts)
    return None


def _extract_usage(response: Any) -> TokenUsage:
    """
    从 Anthropic API 响应中提取 token 用量。

    Claude 的 usage 结构:
    {
        "input_tokens": int,
        "output_tokens": int
    }
    """
    usage = getattr(response, "usage", None)
    if usage is None:
        return TokenUsage()

    prompt_tokens = getattr(usage, "input_tokens", 0)
    completion_tokens = getattr(usage, "output_tokens", 0)
    return TokenUsage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )


class ClaudeProvider(LLMProvider):
    """
    Anthropic Claude Provider 适配器。

    支持 Claude 3.5/3.0 系列模型，提供:
    - 流式和非流式文本生成
    - Extended thinking（扩展思考）
    - 结构化输出（JSON + Pydantic 校验）
    - 指数退避重试
    - 健康检查
    """

    def __init__(
        self,
        model: str,
        api_key: str,
        api_base: Optional[str] = None,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        **kwargs: Any,
    ):
        """
        初始化 Claude Provider。

        Args:
            model: 模型名称（如 "claude-3-5-sonnet-20241022"、"claude-3-opus-20240229"）
            api_key: Anthropic API 密钥
            api_base: 自定义 API 端点（可选，默认 https://api.anthropic.com）
            timeout: 请求超时时间（秒）
            max_retries: 最大重试次数
            **kwargs: 传递给基类的额外参数
        """
        _check_anthropic_available()

        super().__init__(
            provider_name="anthropic",
            model=model,
            api_key=api_key,
            **kwargs,
        )

        self.api_base = api_base or DEFAULT_API_BASE
        self.timeout = timeout
        self.max_retries = max_retries

        # 创建 AsyncAnthropic 客户端实例
        self._client = AsyncAnthropic(
            api_key=api_key,
            base_url=self.api_base,
            timeout=timeout,
        )

        logger.bind(
            module="claude_provider",
            event="provider_init",
            model=model,
            api_base=self.api_base,
        ).debug(f"Claude Provider 初始化完成: model={model}")

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """
        生成文本响应，支持流式和非流式两种模式。

        Args:
            request: LLM 请求参数

        Returns:
            LLMResponse: 包含生成内容、token 用量、延迟等信息

        Raises:
            LLMError: LLM 调用失败（含重试耗尽）
            RateLimitError: 触发速率限制
            TimeoutError: 请求超时
        """
        if request.stream:
            return await self._generate_stream(request)
        return await self._generate_non_streaming(request)

    async def _generate_non_streaming(self, request: LLMRequest) -> LLMResponse:
        """
        非流式生成实现，带指数退避重试。
        """
        request_id = request.extra_params.get("request_id", "")
        messages = _build_messages(request.prompt)
        thinking_config = _build_thinking_config(request)

        # 构建 API 调用参数
        call_kwargs: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": request.max_tokens,
            **thinking_config,
        }
        if request.system_prompt:
            call_kwargs["system"] = request.system_prompt
        if request.temperature is not None:
            call_kwargs["temperature"] = request.temperature
        if request.top_p is not None:
            call_kwargs["top_p"] = request.top_p
        if request.top_k is not None:
            call_kwargs["top_k"] = request.top_k
        if request.stop_sequences:
            call_kwargs["stop_sequences"] = request.stop_sequences

        last_error: Optional[LLMError] = None

        for attempt in range(self.max_retries):
            started_at = time.perf_counter()
            try:
                logger.bind(
                    module="claude_provider",
                    event="api_request",
                    model=self.model,
                    attempt=attempt + 1,
                    request_id=request_id,
                ).info(f"发起 Claude API 请求: model={self.model}, attempt={attempt + 1}")

                response = await self._client.messages.create(**call_kwargs)
                duration_ms = int((time.perf_counter() - started_at) * 1000)

                # 提取响应内容
                content = _extract_response_text(response)
                thinking_content = _extract_thinking_content(response)
                usage = _extract_usage(response)
                stop_reason = getattr(response, "stop_reason", None)

                logger.bind(
                    module="claude_provider",
                    event="api_response",
                    model=self.model,
                    duration_ms=duration_ms,
                    prompt_tokens=usage.prompt_tokens,
                    completion_tokens=usage.completion_tokens,
                    request_id=request_id,
                ).info(f"Claude API 请求完成: duration={duration_ms}ms, tokens={usage.total_tokens}")

                return LLMResponse(
                    content=content,
                    usage=usage,
                    latency_ms=duration_ms,
                    model=self.model,
                    provider=self.provider_name,
                    success=True,
                    thinking_content=thinking_content,
                    finish_reason=stop_reason,
                    raw_response={"id": getattr(response, "id", None)},
                )

            except (APITimeoutError, asyncio.TimeoutError) as exc:
                duration_ms = int((time.perf_counter() - started_at) * 1000)
                logger.bind(
                    module="claude_provider",
                    event="api_timeout",
                    model=self.model,
                    attempt=attempt + 1,
                    duration_ms=duration_ms,
                    request_id=request_id,
                ).error(f"Claude API 请求超时: model={self.model}")

                last_error = TimeoutError(
                    message=f"Claude API 请求超时（{self.timeout}s）",
                    provider=self.provider_name,
                    model=self.model,
                    timeout=self.timeout,
                )

            except AnthropicRateLimit as exc:
                duration_ms = int((time.perf_counter() - started_at) * 1000)
                retry_after = _extract_retry_after(exc)
                logger.bind(
                    module="claude_provider",
                    event="api_rate_limit",
                    model=self.model,
                    attempt=attempt + 1,
                    duration_ms=duration_ms,
                    retry_after=retry_after,
                    request_id=request_id,
                ).warning(f"Claude API 速率限制: model={self.model}")

                last_error = RateLimitError(
                    message="Claude API 请求频率超限",
                    provider=self.provider_name,
                    model=self.model,
                    retry_after=retry_after,
                )

                # 速率限制时执行退避后重试
                if attempt < self.max_retries - 1:
                    await _exponential_backoff(attempt, retry_after=retry_after)
                continue

            except APIError as exc:
                duration_ms = int((time.perf_counter() - started_at) * 1000)
                status_code = getattr(exc, "status_code", None)
                logger.bind(
                    module="claude_provider",
                    event="api_error",
                    model=self.model,
                    attempt=attempt + 1,
                    duration_ms=duration_ms,
                    status_code=status_code,
                    request_id=request_id,
                ).error(f"Claude API 调用失败: {type(exc).__name__}: {str(exc)[:300]}")

                mapped_error = _map_anthropic_error(exc, self.provider_name, self.model)
                last_error = mapped_error

                # 认证错误不可重试，直接抛出
                if isinstance(mapped_error, AuthenticationError):
                    raise mapped_error

                # 可重试的状态码（429/500/502/503/504）继续重试
                retryable_codes = {408, 409, 425, 429, 500, 502, 503, 504}
                if status_code not in retryable_codes:
                    raise mapped_error

            except Exception as exc:
                duration_ms = int((time.perf_counter() - started_at) * 1000)
                logger.bind(
                    module="claude_provider",
                    event="api_unexpected_error",
                    model=self.model,
                    attempt=attempt + 1,
                    duration_ms=duration_ms,
                    error_type=type(exc).__name__,
                    request_id=request_id,
                ).error(f"Claude API 未知异常: {type(exc).__name__}: {str(exc)[:300]}")

                last_error = LLMError(
                    message=f"Claude API 调用异常: {str(exc)[:500]}",
                    provider=self.provider_name,
                    model=self.model,
                )
                # 未知异常不可重试，直接抛出
                raise last_error

            # 指数退避（非速率限制场景）
            if attempt < self.max_retries - 1 and not isinstance(last_error, RateLimitError):
                await _exponential_backoff(attempt)

        # 重试耗尽，抛出最后一次错误
        if last_error is not None:
            logger.bind(
                module="claude_provider",
                event="retries_exhausted",
                model=self.model,
                max_retries=self.max_retries,
                request_id=request_id,
            ).error(f"Claude API 重试耗尽: model={self.model}, max_retries={self.max_retries}")
            raise last_error

        # 理论上不会到达此处
        raise LLMError(
            message="Claude API 调用异常：未知状态",
            provider=self.provider_name,
            model=self.model,
        )

    async def _generate_stream(self, request: LLMRequest) -> LLMResponse:
        """
        流式生成实现。

        流式模式下，通过 SSE 逐块接收响应并拼接完整内容，
        最终返回一个聚合的 LLMResponse。
        注意：流式场景下调用方通常通过 async generator 消费 chunk，
        此方法返回的是流结束后的完整聚合结果。
        """
        request_id = request.extra_params.get("request_id", "")
        messages = _build_messages(request.prompt)
        thinking_config = _build_thinking_config(request)

        call_kwargs: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": request.max_tokens,
            **thinking_config,
        }
        if request.system_prompt:
            call_kwargs["system"] = request.system_prompt
        if request.temperature is not None:
            call_kwargs["temperature"] = request.temperature
        if request.top_p is not None:
            call_kwargs["top_p"] = request.top_p
        if request.top_k is not None:
            call_kwargs["top_k"] = request.top_k
        if request.stop_sequences:
            call_kwargs["stop_sequences"] = request.stop_sequences

        started_at = time.perf_counter()
        content_parts: List[str] = []
        thinking_parts: List[str] = []
        usage = TokenUsage()
        stop_reason: Optional[str] = None

        try:
            logger.bind(
                module="claude_provider",
                event="stream_request",
                model=self.model,
                request_id=request_id,
            ).info(f"发起 Claude 流式请求: model={self.model}")

            async with self._client.messages.stream(**call_kwargs) as stream:
                async for text in stream.text_stream:
                    content_parts.append(text)

                # 流结束后获取最终消息以提取 usage 和 thinking 内容
                final_message = await stream.get_final_message()
                thinking_content = _extract_thinking_content(final_message)
                usage = _extract_usage(final_message)
                stop_reason = getattr(final_message, "stop_reason", None)

            duration_ms = int((time.perf_counter() - started_at) * 1000)
            content = "".join(content_parts)

            logger.bind(
                module="claude_provider",
                event="stream_complete",
                model=self.model,
                duration_ms=duration_ms,
                prompt_tokens=usage.prompt_tokens,
                completion_tokens=usage.completion_tokens,
                request_id=request_id,
            ).info(f"Claude 流式请求完成: duration={duration_ms}ms, tokens={usage.total_tokens}")

            return LLMResponse(
                content=content,
                usage=usage,
                latency_ms=duration_ms,
                model=self.model,
                provider=self.provider_name,
                success=True,
                thinking_content=thinking_content,
                finish_reason=stop_reason,
            )

        except (APITimeoutError, asyncio.TimeoutError) as exc:
            duration_ms = int((time.perf_counter() - started_at) * 1000)
            logger.bind(
                module="claude_provider",
                event="stream_timeout",
                model=self.model,
                duration_ms=duration_ms,
                request_id=request_id,
            ).error(f"Claude 流式请求超时: model={self.model}")
            raise TimeoutError(
                message=f"Claude API 流式请求超时（{self.timeout}s）",
                provider=self.provider_name,
                model=self.model,
                timeout=self.timeout,
            )

        except AnthropicRateLimit as exc:
            retry_after = _extract_retry_after(exc)
            logger.bind(
                module="claude_provider",
                event="stream_rate_limit",
                model=self.model,
                request_id=request_id,
            ).warning(f"Claude 流式请求速率限制: model={self.model}")
            raise RateLimitError(
                message="Claude API 流式请求频率超限",
                provider=self.provider_name,
                model=self.model,
                retry_after=retry_after,
            )

        except APIError as exc:
            duration_ms = int((time.perf_counter() - started_at) * 1000)
            logger.bind(
                module="claude_provider",
                event="stream_api_error",
                model=self.model,
                duration_ms=duration_ms,
                request_id=request_id,
            ).error(f"Claude 流式请求失败: {type(exc).__name__}: {str(exc)[:300]}")
            raise _map_anthropic_error(exc, self.provider_name, self.model)

        except Exception as exc:
            duration_ms = int((time.perf_counter() - started_at) * 1000)
            logger.bind(
                module="claude_provider",
                event="stream_unexpected_error",
                model=self.model,
                duration_ms=duration_ms,
                error_type=type(exc).__name__,
                request_id=request_id,
            ).error(f"Claude 流式请求未知异常: {type(exc).__name__}: {str(exc)[:300]}")
            raise LLMError(
                message=f"Claude 流式调用异常: {str(exc)[:500]}",
                provider=self.provider_name,
                model=self.model,
            )

    async def generate_structured(
        self, request: LLMRequest, schema: Type[T]
    ) -> T:
        """
        生成结构化输出（JSON 格式）。

        在 prompt 中附加 JSON 格式要求，调用 generate() 获取文本响应，
        然后使用 json_utils 容错解析并通过 Pydantic schema 验证。

        Args:
            request: LLM 请求参数
            schema: Pydantic 模型类，用于验证输出

        Returns:
            T: 符合 schema 的 Pydantic 模型实例

        Raises:
            StructuredOutputError: 结构化输出解析失败
            LLMError: LLM 调用失败
        """
        request_id = request.extra_params.get("request_id", "")

        # 在 prompt 中追加 JSON 输出指令
        schema_name = schema.__name__
        json_instruction = (
            "\n\n请以严格的 JSON 格式输出结果，不要包含任何额外说明文字。"
            f"输出必须符合以下 schema: {schema_name}"
        )
        structured_prompt = request.prompt + json_instruction

        # 构建新的请求对象，强制非流式
        structured_request = LLMRequest(
            prompt=structured_prompt,
            system_prompt=request.system_prompt,
            max_tokens=request.max_tokens,
            temperature=request.temperature if request.temperature is not None else 0.0,
            top_p=request.top_p,
            top_k=request.top_k,
            stream=False,
            stop_sequences=request.stop_sequences,
            thinking_enabled=False,  # 结构化输出不需要 extended thinking
            thinking_budget_tokens=None,
            extra_params=request.extra_params,
        )

        logger.bind(
            module="claude_provider",
            event="structured_request",
            model=self.model,
            schema=schema_name,
            request_id=request_id,
        ).info(f"发起 Claude 结构化输出请求: model={self.model}, schema={schema_name}")

        # 调用非流式生成
        response = await self._generate_non_streaming(structured_request)

        if not response.success or not response.content:
            raise StructuredOutputError(
                message=f"结构化输出失败: {response.error or '响应内容为空'}",
                raw_output=response.content or "",
                reason="empty_response",
                provider=self.provider_name,
                model=self.model,
            )

        # 使用 json_utils 容错解析
        try:
            result = parse_structured_output(response.content, schema)
            logger.bind(
                module="claude_provider",
                event="structured_success",
                model=self.model,
                schema=schema_name,
                request_id=request_id,
            ).info(f"结构化输出解析成功: schema={schema_name}")
            return result
        except StructuredOutputError:
            # parse_structured_output 已经抛出 StructuredOutputError，直接传播
            raise
        except Exception as exc:
            logger.bind(
                module="claude_provider",
                event="structured_parse_error",
                model=self.model,
                schema=schema_name,
                error_type=type(exc).__name__,
                request_id=request_id,
            ).error(f"结构化输出解析异常: {type(exc).__name__}: {str(exc)[:300]}")
            raise StructuredOutputError(
                message=f"结构化输出解析异常: {str(exc)[:500]}",
                raw_output=response.content,
                reason="parse_exception",
                provider=self.provider_name,
                model=self.model,
            )

    async def health_check(self) -> bool:
        """
        检查 Claude API 连接健康状态。

        通过发送一个最小化的 API 请求来验证 API Key 和网络连通性。

        Returns:
            bool: True 表示健康，False 表示不可用
        """
        try:
            # 发送一个极小的请求来验证连通性
            response = await asyncio.wait_for(
                self._client.messages.create(
                    model=self.model,
                    messages=[{"role": "user", "content": "Hi"}],
                    max_tokens=1,
                ),
                timeout=10.0,
            )
            # 能收到响应即认为健康
            return response is not None
        except asyncio.TimeoutError:
            logger.bind(
                module="claude_provider",
                event="health_check_timeout",
                model=self.model,
            ).warning(f"Claude 健康检查超时: model={self.model}")
            return False
        except AuthenticationError:
            logger.bind(
                module="claude_provider",
                event="health_check_auth_error",
                model=self.model,
            ).warning(f"Claude 健康检查认证失败: model={self.model}")
            return False
        except APIError as exc:
            status_code = getattr(exc, "status_code", None)
            # 401 表示认证失败
            if status_code == 401:
                logger.bind(
                    module="claude_provider",
                    event="health_check_auth_error",
                    model=self.model,
                ).warning(f"Claude 健康检查认证失败: model={self.model}")
                return False
            # 其他 API 错误也视为不健康
            logger.bind(
                module="claude_provider",
                event="health_check_api_error",
                model=self.model,
                status_code=status_code,
            ).warning(f"Claude 健康检查失败: {type(exc).__name__}")
            return False
        except Exception as exc:
            logger.bind(
                module="claude_provider",
                event="health_check_error",
                model=self.model,
                error_type=type(exc).__name__,
            ).warning(f"Claude 健康检查异常: {type(exc).__name__}: {str(exc)[:200]}")
            return False

    def __repr__(self) -> str:
        return (
            f"<ClaudeProvider model={self.model} "
            f"api_base={self.api_base} "
            f"max_retries={self.max_retries}>"
        )
