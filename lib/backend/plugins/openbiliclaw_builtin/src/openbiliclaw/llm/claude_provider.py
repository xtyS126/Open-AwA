"""Anthropic Claude LLM provider。"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, cast

from anthropic import AsyncAnthropic

from .base import (
    LLMProvider,
    LLMProviderError,
    LLMRateLimitError,
    LLMResponse,
    LLMResponseError,
    LLMTimeoutError,
)

if TYPE_CHECKING:
    from anthropic.types import Message, MessageParam

logger = logging.getLogger(__name__)


class ClaudeProvider(LLMProvider):
    """Anthropic Claude provider。"""

    _MAX_RETRIES = 3
    _BASE_RETRY_DELAY = 0.25

    def __init__(
        self, api_key: str, model: str = "claude-sonnet-4-20250514", timeout: float = 300.0
    ) -> None:
        self._model = model
        self._client = AsyncAnthropic(api_key=api_key, timeout=timeout)

    @property
    def name(self) -> str:
        return "claude"

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        json_mode: bool = False,
        reasoning_effort: str | None = None,
        model: str | None = None,
    ) -> LLMResponse:
        # ``reasoning_effort`` 是 DeepSeek 专有；Claude 有自己的、单独控制的
        # ``thinking`` 模式。为保持签名兼容性接受此参数，但此处不对其做处理。
        del reasoning_effort
        effective_model = (model or "").strip() or self._model
        # 若存在 system 消息则提取出来
        system = ""
        chat_messages = []
        for msg in messages:
            if msg["role"] == "system":
                system = msg["content"]
            else:
                chat_messages.append(msg)

        # v0.3.29+: Anthropic prompt-cache 集成。Claude 要求对我们希望缓存的
        # 消息块显式添加 ``cache_control: {"type": "ephemeral"}`` 标记 ——
        # 纯字符串 ``system="..."`` 永远不会被缓存。我们始终把 system 块
        # 标记为可缓存；当 system 文本低于各模型的最小阈值（Sonnet 1024
        # token，Haiku/Opus 2048 token）时 Anthropic 会静默忽略标记，因此
        # 对短 prompt 也安全。缓存命中按输入费率的 10% 计费；首次调用会以
        # +25% 附加费写入缓存，随后读取有 5 分钟 TTL。system_param 会经过
        # ``_render_system_param``，测试可对其进行覆盖。
        system_text = system or "You are a helpful assistant."
        system_param: Any = self._render_system_param(system_text)

        response = cast(
            "Message",
            await self._request_with_retry(
                model=effective_model,
                max_tokens=max_tokens,
                system=system_param,
                messages=chat_messages,
                temperature=temperature,
            ),
        )

        content = ""
        for block in response.content:
            if hasattr(block, "text"):
                content += block.text

        if not content.strip():
            raise LLMResponseError("claude returned empty content")

        # Claude 在使用 prompt-cache 时会暴露缓存字段：
        # cache_read_input_tokens（9 折）+ cache_creation_input_tokens
        # （+25% 附加费）。我们将它们挂到通用的
        # ``cached_input_tokens`` / ``cache_creation_input_tokens`` 键下，
        # 以便下游的计费/可观测性与 provider 无关。
        cache_read = int(getattr(response.usage, "cache_read_input_tokens", 0) or 0)
        cache_create = int(getattr(response.usage, "cache_creation_input_tokens", 0) or 0)
        usage_dict = {
            "prompt_tokens": response.usage.input_tokens,
            "completion_tokens": response.usage.output_tokens,
            "total_tokens": response.usage.input_tokens + response.usage.output_tokens,
        }
        if cache_read:
            usage_dict["cached_input_tokens"] = cache_read
        if cache_create:
            usage_dict["cache_creation_input_tokens"] = cache_create
        return LLMResponse(
            content=content,
            model=response.model,
            provider="claude",
            usage=usage_dict,
            raw=response,
        )

    def _render_system_param(self, system_text: str) -> Any:
        """将 system prompt 包装为 Anthropic 的 prompt-cache 形状。

        Claude API 接受 ``system`` 为纯字符串或带类型的块列表；只有后者
        支持 ``cache_control``。我们始终输出列表形式，并在 system 块上加
        ``ephemeral`` 缓存标记。若 system 文本低于各模型的最小阈值
        （Sonnet 1024 token / Haiku/Opus 2048 token），Anthropic 会静默
        忽略标记而非报错，因此无论大小都安全。
        """
        return [
            {
                "type": "text",
                "text": system_text,
                "cache_control": {"type": "ephemeral"},
            }
        ]

    async def _request_with_retry(self, **kwargs: Any) -> Any:
        """发送请求，对瞬时失败进行有界重试。"""
        last_error: Exception | None = None

        for attempt in range(1, self._MAX_RETRIES + 1):
            try:
                return await self._client.messages.create(
                    model=cast("str", kwargs["model"]),
                    max_tokens=cast("int", kwargs["max_tokens"]),
                    system=kwargs["system"],
                    messages=cast("list[MessageParam]", kwargs["messages"]),
                    temperature=cast("float", kwargs["temperature"]),
                )
            except Exception as exc:
                mapped = self._map_error(exc)
                last_error = mapped
                if not self._is_retryable(mapped) or attempt == self._MAX_RETRIES:
                    raise mapped from exc

                await asyncio.sleep(self._BASE_RETRY_DELAY * attempt)

        if last_error is None:
            raise LLMProviderError("claude request failed")
        raise last_error

    def _map_error(self, exc: Exception) -> LLMProviderError:
        """将 Anthropic 或网络错误映射为共享的 provider 错误。"""
        if isinstance(exc, LLMProviderError):
            return exc
        if isinstance(exc, TimeoutError):
            return LLMTimeoutError("claude request timed out")

        message = str(exc).lower()
        if "rate limit" in message or "too many requests" in message:
            return LLMRateLimitError("claude rate limit exceeded")

        return LLMProviderError(f"claude request failed: {exc}")

    def _is_retryable(self, exc: LLMProviderError) -> bool:
        """判断映射后的异常是否应重试。"""
        if isinstance(exc, LLMRateLimitError):
            return False
        return isinstance(exc, (LLMProviderError, LLMTimeoutError))
