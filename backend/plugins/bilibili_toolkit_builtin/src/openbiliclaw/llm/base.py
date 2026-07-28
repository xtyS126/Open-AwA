"""LLM 基础接口与 provider 注册表。

定义抽象的 LLM provider 接口，以及用于动态选择和切换 provider 的注册表。
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

LLM_CONNECTIVITY_PROBE_MAX_TOKENS = 1024


class LLMProviderError(Exception):
    """provider 请求失败的基类异常。"""


class LLMRateLimitError(LLMProviderError):
    """当 provider 对请求进行限流时抛出。"""


class LLMTimeoutError(LLMProviderError):
    """当 provider 请求超时时抛出。"""


class LLMResponseError(LLMProviderError):
    """当 provider 返回无效或空响应时抛出。"""


class LLMFallbackError(LLMProviderError):
    """当所有候选 provider 都失败时抛出。"""


@dataclass
class LLMResponse:
    """任意 LLM provider 的标准化响应。"""

    content: str = ""
    model: str = ""
    provider: str = ""
    usage: dict[str, int] | None = None  # token 计数
    raw: Any = None  # provider 原始响应
    tool_calls: list[dict[str, Any]] | None = None  # Phase 4: 函数调用


@dataclass
class HealthCheckResult:
    """单个 provider 的可用性结果。"""

    available: bool
    is_default: bool = False
    error: str | None = None


class LLMProvider(ABC):
    """LLM provider 的抽象基类。

    所有 provider 必须实现统一接口，以便 agent 可以透明地在它们之间切换。
    """

    # 子类若实现了基于可用 embeddings 端点的 ``async embed()`` 方法，
    # 则需将其设置为 True。``build_embedding_service`` 会用此标志在用户主
    # provider 没有嵌入 API（如 Anthropic Claude、DeepSeek）时挑选回退
    # provider。``hasattr(provider, "embed")`` 不可靠，因为继承
    # OpenAIProvider 会自动继承 ``embed``，即便厂商后端并未真正暴露该接口。
    supports_embedding: bool = False

    @property
    @abstractmethod
    def name(self) -> str:
        """provider 名称标识符。"""
        ...

    @abstractmethod
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
        """发送聊天补全请求。

        Args:
            messages: OpenAI 格式的聊天消息 [{role, content}]。
            temperature: 采样温度。
            max_tokens: 响应的最大 token 数。
            json_mode: 是否请求结构化 JSON 输出。
            reasoning_effort: 对 provider 的 ``reasoning_effort`` 设置进行
                单次调用覆盖（目前仅 DeepSeek 支持；其他 provider 忽略）。
                ``None`` 表示"使用 provider 的配置默认值"；
                ``""`` 表示"为此次调用显式禁用思考"（用于 discovery 的
                ``_evaluate_batch`` 等不会从推理中受益的结构化任务）。
            model: 可选的单次调用模型覆盖。空值或空白值会回退到 provider
                的配置默认值，且不会修改 provider 状态。

        Returns:
            标准化的 LLMResponse。
        """
        ...

    async def health_check(self) -> bool:
        """检查 provider 是否可访问。

        Returns:
            provider 可用时返回 True。
        """
        try:
            # 优先推理的 OpenAI 兼容后端可能会先把输出预算花在推理上，
            # 然后才输出可见内容。连通性探测要小，但不能小到让这些
            # provider 在返回可见内容之前就被截断。
            resp = await self.complete(
                [{"role": "user", "content": "hi"}],
                max_tokens=LLM_CONNECTIVITY_PROBE_MAX_TOKENS,
            )
            return bool(resp.content)
        except Exception:
            logger.exception("Health check failed for %s", self.name)
            return False


class LLMRegistry:
    """LLM provider 注册表。

    支持 provider 的动态注册与选择。
    """

    _RATE_LIMIT_COOLDOWN_SECONDS = 60.0

    def __init__(self) -> None:
        self._providers: dict[str, LLMProvider] = {}
        self._default: str = ""
        self._rate_limited_until: dict[str, float] = {}
        self.fallback_enabled: bool = False
        self.fallback_provider: str = ""
        # 不应出现在聊天补全回退链中的 provider 名称 —— 通常是仅为嵌入而
        # 注册的 Ollama 实例（见 register(..., chat_capable=False)）。
        self._chat_disabled: set[str] = set()

    def register(
        self,
        provider: LLMProvider,
        *,
        default: bool = False,
        chat_capable: bool = True,
    ) -> None:
        """注册一个 provider。

        Args:
            provider: LLM provider 实例。
            default: 是否设为默认 provider。
            chat_capable: 为 False 时，该 provider 仅供非聊天用途（通常是
                仅用于嵌入的 Ollama），不会出现在聊天补全回退链中。
                默认 True 以保持向后兼容 —— 其他所有调用方都需要聊天能力。

                为何重要：若用户只设置了 ``[llm.embedding] provider = "ollama"``
                而从未配置 ``[llm.ollama] model``，嵌入服务仍需要 Ollama
                留在注册表中 —— 但磁盘上的模型是 ``bge-m3``，无法服务
                ``/api/chat`` 请求。没有此标志时，当主云 provider 出现瞬时
                错误，回退链会欣然选择 Ollama，从 ``/api/chat`` 收到 404，
                用户就会看到 ``All providers failed (openai, ollama)``。
        """
        self._providers[provider.name] = provider
        if not chat_capable:
            self._chat_disabled.add(provider.name)
        else:
            self._chat_disabled.discard(provider.name)
        if default or not self._default:
            self._default = provider.name
        logger.info(
            "Registered LLM provider: %s%s%s",
            provider.name,
            " (default)" if default else "",
            "" if chat_capable else " [embedding-only]",
        )

    def get(self, name: str | None = None) -> LLMProvider:
        """按名称获取 provider，或返回默认 provider。

        Args:
            name: provider 名称。若为 None，则返回默认 provider。

        Returns:
            LLM provider 实例。

        Raises:
            KeyError: 若 provider 未注册。
        """
        target = name or self._default
        if target not in self._providers:
            available = ", ".join(self._providers.keys())
            raise KeyError(f"LLM provider '{target}' not found. Available: {available}")
        return self._providers[target]

    @property
    def available_providers(self) -> list[str]:
        """已注册的 provider 名称列表。"""
        return list(self._providers.keys())

    @property
    def default_provider(self) -> str:
        """默认 provider 的名称。"""
        return self._default

    def is_chat_capable(self, name: str) -> bool:
        """返回 *name* 是否已注册为可进行聊天补全。"""
        target = name.strip().lower()
        return bool(target and target in self._providers and target not in self._chat_disabled)

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        json_mode: bool = False,
        reasoning_effort: str | None = None,
    ) -> LLMResponse:
        """执行补全请求，按顺序回退 provider。"""
        last_error: Exception | None = None
        attempted: list[str] = []

        for provider_name in self._fallback_order():
            attempted.append(provider_name)
            if self._provider_on_cooldown(provider_name):
                last_error = LLMRateLimitError(
                    f"Provider {provider_name} is cooling down after rate limit."
                )
                logger.warning("Provider %s is cooling down after rate limit.", provider_name)
                continue
            provider = self.get(provider_name)
            try:
                response = await provider.complete(
                    messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    json_mode=json_mode,
                    reasoning_effort=reasoning_effort,
                )
                self._rate_limited_until.pop(provider_name, None)
                return response
            except LLMResponseError:
                raise
            except LLMRateLimitError as exc:
                last_error = exc
                self._mark_rate_limited(provider_name)
                logger.warning("Provider %s failed, trying next fallback.", provider_name)
            except (LLMProviderError, LLMTimeoutError) as exc:
                last_error = exc
                logger.warning("Provider %s failed, trying next fallback.", provider_name)

        attempted_list = ", ".join(attempted)
        if last_error is None:
            raise LLMFallbackError("No provider was available to process the request.")
        raise LLMFallbackError(
            f"All providers failed ({attempted_list}). Last error: {last_error}"
        ) from last_error

    async def complete_provider(
        self,
        provider_name: str,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        json_mode: bool = False,
        reasoning_effort: str | None = None,
        model: str | None = None,
    ) -> LLMResponse:
        """针对某个确切的、具备聊天能力的 provider 执行补全。

        与 ``complete()`` 不同，此方法故意不设回退链。它用于显式的按模块
        覆盖场景，回退到其他 provider 会违反用户意图。
        """
        target = provider_name.strip().lower()
        if not self.is_chat_capable(target):
            available = ", ".join(self._fallback_order())
            raise LLMFallbackError(
                f"LLM provider '{target or provider_name}' is not registered "
                f"or not chat-capable. Chat-capable providers: {available}"
            )
        if self._provider_on_cooldown(target):
            logger.warning("Provider %s is cooling down after rate limit.", target)
            raise LLMRateLimitError(f"Provider {target} is cooling down after rate limit.")

        provider = self.get(target)
        try:
            response = await provider.complete(
                messages,
                temperature=temperature,
                max_tokens=max_tokens,
                json_mode=json_mode,
                reasoning_effort=reasoning_effort,
                model=model,
            )
            self._rate_limited_until.pop(target, None)
            return response
        except LLMRateLimitError:
            self._mark_rate_limited(target)
            logger.warning("Provider %s rate-limited exact routed call.", target)
            raise

    async def health_check_all(self) -> dict[str, HealthCheckResult]:
        """对所有已注册 provider 运行健康检查。"""
        results: dict[str, HealthCheckResult] = {}
        for provider_name in self.available_providers:
            provider = self.get(provider_name)
            try:
                available = await provider.health_check()
                results[provider_name] = HealthCheckResult(
                    available=available,
                    is_default=provider_name == self._default,
                    error=None if available else "health check returned false",
                )
            except Exception as exc:
                results[provider_name] = HealthCheckResult(
                    available=False,
                    is_default=provider_name == self._default,
                    error=str(exc),
                )
        return results

    def _fallback_order(self) -> list[str]:
        """返回按顺序的聊天回退 provider 顺序。

        跳过以 ``chat_capable=False`` 注册的 provider（仅用于嵌入的 Ollama
        场景）。只要默认 provider 具备聊天能力就予以保留。只有当
        ``fallback_provider`` 指向一个已注册的聊天 provider 时才纳入回退；
        不进行自动 provider 遍历。
        """
        chat_pool = [name for name in self.available_providers if name not in self._chat_disabled]
        if not chat_pool:
            # 边界情况：所有 provider 都仅用于嵌入。暴露问题而不是
            # 静默地什么也不做 —— complete() 会抛出
            # LLMFallbackError("No provider was available to process the request.")。
            return []
        if self._default and self._default in chat_pool:
            ordered = [
                self._default,
                *[name for name in chat_pool if name != self._default],
            ]
        else:
            ordered = chat_pool
        fallback_provider = self.fallback_provider.strip().lower()
        if not fallback_provider:
            return ordered[:1]
        if fallback_provider == ordered[0] or fallback_provider not in chat_pool:
            return ordered[:1]
        return [ordered[0], fallback_provider]

    def _provider_on_cooldown(self, provider_name: str) -> bool:
        until = self._rate_limited_until.get(provider_name)
        if until is None:
            return False
        if until > time.monotonic():
            return True
        self._rate_limited_until.pop(provider_name, None)
        return False

    def _mark_rate_limited(self, provider_name: str) -> None:
        self._rate_limited_until[provider_name] = (
            time.monotonic() + self._RATE_LIMIT_COOLDOWN_SECONDS
        )
