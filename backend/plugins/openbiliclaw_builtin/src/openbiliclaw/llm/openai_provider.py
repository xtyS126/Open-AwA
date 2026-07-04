"""OpenAI 兼容 LLM provider。

支持 OpenAI API 以及任意兼容 API（如 DeepSeek、本地 vLLM）。
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from openai import AsyncOpenAI

from .base import (
    LLMProvider,
    LLMProviderError,
    LLMRateLimitError,
    LLMResponse,
    LLMResponseError,
    LLMTimeoutError,
)

logger = logging.getLogger(__name__)
_BILLING_BACKOFF_STATUS_CODES = {402}
_BILLING_BACKOFF_MARKERS = (
    "insufficient balance",
    "payment required",
    "quota exceeded",
    "billing",
    "out of credit",
    "credit exhausted",
    "余额不足",
    "账户余额",
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


def _generic_json_schema_response_format() -> dict[str, Any]:
    """用于任意 JSON 对象任务的 OpenAI 结构化输出形状。"""
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "structured_response",
            "strict": False,
            "schema": {
                "type": "object",
                "properties": {},
                "additionalProperties": True,
            },
        },
    }


class OpenAIProvider(LLMProvider):
    """OpenAI 及兼容 API provider。"""

    # OpenAI 的 API 有可用的 embeddings 端点
    # （text-embedding-3-small / -large）。指向不暴露 embeddings 的
    # 后端（DeepSeek、OpenRouter 等）的子类会将此改回 False —— 见
    # DeepSeekProvider / OpenRouterProvider。
    supports_embedding = True

    _MAX_RETRIES = 3
    _BASE_RETRY_DELAY = 0.25

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o",
        base_url: str = "",
        provider_name: str = "openai",
        token_provider: Callable[[bool], Awaitable[str]] | None = None,
        timeout: float = 300.0,
        embedding_output_dimensionality: int = 0,
    ) -> None:
        self._model = model
        self._provider_name = provider_name
        self.base_url = base_url or ""
        self._token_provider = token_provider
        self._timeout = timeout
        self._embedding_output_dimensionality = max(0, int(embedding_output_dimensionality or 0))
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url or None,
            max_retries=0,
            timeout=timeout,
        )

    @property
    def name(self) -> str:
        return self._provider_name

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
        # ``reasoning_effort`` 由 ``DeepSeekProvider`` 消费；基础 OpenAI
        # provider 为保持签名兼容性接受它，但不对其做处理
        # （原版 GPT-4o 没有思考开关）。
        del reasoning_effort
        effective_model = (model or "").strip() or self._model
        kwargs: dict[str, Any] = {
            "model": effective_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            fmt = self._json_response_format()
            if fmt is not None:
                kwargs["response_format"] = fmt
        extra_headers = self._extra_headers()
        if extra_headers:
            kwargs["extra_headers"] = extra_headers
        extra_body = self._extra_body()
        if extra_body:
            kwargs["extra_body"] = extra_body

        try:
            response = await self._request_with_retry(**kwargs)
        except LLMProviderError as exc:
            # 至多重试一次：替换后 kwargs["response_format"] 不再是
            # json_object，所以 _uses_json_object 返回 False。
            if (
                json_mode
                and self._uses_json_object(kwargs.get("response_format"))
                and self._json_object_response_format_rejected(exc)
            ):
                logger.info(
                    "%s rejected json_object response_format; retrying with json_schema",
                    self._provider_name,
                )
                kwargs["response_format"] = _generic_json_schema_response_format()
                response = await self._request_with_retry(**kwargs)
            else:
                raise
        choice = response.choices[0]
        content = choice.message.content or ""
        if not content.strip():
            # 某些 OpenAI 兼容后端在设置了 ``response_format`` 时返回
            # HTTP 200 并报告 completion_tokens > 0，但
            # ``message.content`` 为空。去掉约束重试一次；prompt 本身
            # 已要求 JSON。
            if json_mode and "response_format" in kwargs:
                logger.warning(
                    "%s returned empty content with response_format=%s; "
                    "retrying without response_format constraint",
                    self._provider_name,
                    kwargs["response_format"].get("type", "?"),
                )
                kwargs.pop("response_format")
                response = await self._request_with_retry(**kwargs)
                choice = response.choices[0]
                content = choice.message.content or ""
            if not content.strip():
                raise LLMResponseError(f"{self._provider_name} returned empty content")

        usage = None
        if response.usage:
            usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }
            # 在 OpenAI 协议家族中归一化缓存字段。
            # OpenAI 自 GPT-4o 起暴露 `prompt_tokens_details.cached_tokens`；
            # DeepSeek 在同一 usage 对象上注入 `prompt_cache_hit_tokens` /
            # `prompt_cache_miss_tokens`；Kimi / 通义 / 中转站各异。
            # 我们探测已知字段，把后端发送的那个挂到通用的
            # ``cached_input_tokens`` 键下。下游计费 / 可观测性代码
            # 只读此归一化字段。
            cached = 0
            details = getattr(response.usage, "prompt_tokens_details", None)
            if details is not None:
                cached = int(getattr(details, "cached_tokens", 0) or 0)
            if not cached:
                # DeepSeek 的显式字段
                cached = int(getattr(response.usage, "prompt_cache_hit_tokens", 0) or 0)
            if cached:
                usage["cached_input_tokens"] = cached

        return LLMResponse(
            content=content,
            model=response.model,
            provider=self._provider_name,
            usage=usage,
            raw=response,
        )

    async def _request_with_retry(self, **kwargs: Any) -> Any:
        """发送请求，对瞬时失败进行有界重试。"""
        last_error: Exception | None = None

        for attempt in range(1, self._MAX_RETRIES + 1):
            try:
                await self._apply_dynamic_token(force_refresh=False)
                return await self._client.chat.completions.create(**kwargs)
            except Exception as exc:
                if self._is_unauthorized(exc) and self._token_provider is not None:
                    try:
                        await self._apply_dynamic_token(force_refresh=True)
                        return await self._client.chat.completions.create(**kwargs)
                    except Exception as refresh_exc:
                        mapped_refresh = self._map_error(refresh_exc)
                        raise mapped_refresh from refresh_exc
                mapped = self._map_error(exc)
                last_error = mapped
                if not self._is_retryable(mapped) or attempt == self._MAX_RETRIES:
                    raise mapped from exc

                await asyncio.sleep(self._BASE_RETRY_DELAY * attempt)

        if last_error is None:
            raise LLMProviderError(f"{self._provider_name} request failed")
        raise last_error

    async def _apply_dynamic_token(self, *, force_refresh: bool) -> None:
        if self._token_provider is None:
            return
        try:
            token = await self._token_provider(force_refresh)
        except Exception as exc:
            raise LLMProviderError(
                f"{self._provider_name} token refresh failed; run `openbiliclaw login codex` again."
            ) from exc
        if token:
            self._client.api_key = token

    @staticmethod
    def _is_unauthorized(exc: Exception) -> bool:
        status_code = getattr(exc, "status_code", None)
        if isinstance(status_code, int):
            return status_code == 401
        if isinstance(status_code, str):
            return status_code.strip() == "401"
        return False

    def _map_error(self, exc: Exception) -> LLMProviderError:
        """将 provider 或网络异常映射为共享的 provider 错误。"""
        if isinstance(exc, LLMProviderError):
            return exc
        if isinstance(exc, TimeoutError):
            return LLMTimeoutError(f"{self._provider_name} request timed out")

        status_code = getattr(exc, "status_code", None)
        status_code_int = self._status_code_int(status_code)
        body_excerpt = self._provider_error_body_excerpt(exc)
        message = f"{exc} {body_excerpt}".lower()
        if status_code_int == 429 or "rate limit" in message or "too many requests" in message:
            return LLMRateLimitError(f"{self._provider_name} rate limit exceeded")
        if status_code_int in _BILLING_BACKOFF_STATUS_CODES or any(
            marker in message for marker in _BILLING_BACKOFF_MARKERS
        ):
            detail = body_excerpt or str(exc)
            return LLMRateLimitError(
                f"{self._provider_name} provider backoff: HTTP {status_code_int or status_code}: "
                f"{detail}"
            )
        if status_code_int and status_code_int >= 500:
            return LLMProviderError(f"{self._provider_name} server error: {status_code}")
        if status_code and body_excerpt:
            logger.warning(
                "%s request failed with HTTP %s: %s",
                self._provider_name,
                status_code,
                body_excerpt,
            )
            return LLMProviderError(
                f"{self._provider_name} request failed: HTTP {status_code}: {body_excerpt}"
            )

        return LLMProviderError(f"{self._provider_name} request failed: {exc}")

    @staticmethod
    def _status_code_int(status_code: object) -> int | None:
        if isinstance(status_code, int):
            return status_code
        if isinstance(status_code, str):
            try:
                return int(status_code.strip())
            except ValueError:
                return None
        return None

    @staticmethod
    def _provider_error_body_excerpt(exc: Exception) -> str:
        """从 SDK 异常中抽取紧凑的 provider 响应体。"""

        candidates: list[object] = []
        body = getattr(exc, "body", None)
        if body:
            candidates.append(body)
        response = getattr(exc, "response", None)
        if response is not None:
            text = getattr(response, "text", None)
            if text:
                candidates.append(text)
            content = getattr(response, "content", None)
            if content:
                candidates.append(content)

        for candidate in candidates:
            if isinstance(candidate, bytes):
                text = candidate.decode("utf-8", errors="replace")
            elif isinstance(candidate, (dict, list)):
                text = json.dumps(candidate, ensure_ascii=False, sort_keys=True)
            else:
                text = str(candidate)
            text = " ".join(text.split())
            if text:
                return text[:1000] + ("..." if len(text) > 1000 else "")
        return ""

    def _is_retryable(self, exc: LLMProviderError) -> bool:
        """判断映射后的异常是否应重试。"""
        if isinstance(exc, LLMRateLimitError):
            return False
        return isinstance(exc, (LLMProviderError, LLMTimeoutError))

    def _json_response_format(self) -> dict[str, Any] | None:
        if self._is_lm_studio():
            # LM Studio 的 OpenAI 兼容层在 ``json_object`` 和
            # ``json_schema`` 两种 response_format 下都会丢失
            # ``message.content``（HTTP 200、completion_tokens > 0，
            # 但 content 为空）。完全跳过 ``response_format``；
            # prompt 已要求 JSON，模型仍会产出。
            return None
        return {"type": "json_object"}

    def _is_lm_studio(self) -> bool:
        """通过 URL 启发式检测 LM Studio（名称或默认端口）。"""
        raw_base_url = self.base_url.strip()
        if not raw_base_url:
            return False
        normalized = raw_base_url.lower()
        if "lmstudio" in normalized or "lm-studio" in normalized:
            return True
        parsed_url = raw_base_url if "://" in raw_base_url else f"http://{raw_base_url}"
        parsed = urlparse(parsed_url)
        host = (parsed.hostname or "").lower()
        try:
            port = parsed.port
        except ValueError:
            return False
        if host in {"localhost", "127.0.0.1", "::1"} and port == 1234:
            logger.debug("treating %s as LM Studio (default port 1234)", raw_base_url)
            return True
        return False

    @staticmethod
    def _uses_json_object(response_format: object) -> bool:
        return isinstance(response_format, dict) and response_format.get("type") == "json_object"

    @staticmethod
    def _json_object_response_format_rejected(exc: LLMProviderError) -> bool:
        # 字段路径 "response_format.type" 在所有已知的 OpenAI 协议实现中
        # 都是小写，因此 .lower() + 字面量匹配是安全的。
        message = str(exc).lower()
        return "response_format.type" in message and "json_schema" in message and "text" in message

    async def embed(self, text: str, *, model: str = "text-embedding-3-small") -> list[float]:
        """通过 OpenAI 的 ``/v1/embeddings`` 端点获取文本嵌入。

        失败时返回空列表，以便调用方优雅降级（嵌入服务将空向量视为
        "无嵌入"）。这与 Gemini/Ollama provider 已遵循的契约一致。
        """
        try:
            kwargs: dict[str, Any] = {"model": model, "input": text}
            if (
                self._supports_embedding_dimensions(model)
                and self._embedding_output_dimensionality > 0
            ):
                kwargs["dimensions"] = self._embedding_output_dimensionality
            response = await self._client.embeddings.create(**kwargs)
            return list(response.data[0].embedding)
        except Exception:
            logger.warning(
                "%s embedding failed (model=%s)",
                self._provider_name,
                model,
                exc_info=True,
            )
            return []

    def _supports_embedding_dimensions(self, model: str) -> bool:
        if not model.startswith("text-embedding-3-"):
            return False
        return self._provider_name == "openai"

    def _extra_headers(self) -> dict[str, str]:
        """返回可选的 provider 专属请求头。"""
        return {}

    def _extra_body(self) -> dict[str, Any]:
        """返回可选的 provider 专属请求体字段。

        用于 DeepSeek 的 ``thinking`` 和 ``reasoning_effort`` 等非标准
        键。此处返回的键会通过 OpenAI SDK 的 ``extra_body`` 原样传递。
        """
        return {}


# DeepSeek 的 ``max_tokens`` 同时限制思考 + 响应。在
# ``reasoning_effort="max"`` 下，仅思考流就可能烧掉数万 token 才输出
# 任何 ``content``，导致响应以 ``content=""`` 结束，我们的 provider
# 抛出 LLMResponseError。这些下限确保传入较小 ``max_tokens`` 的调用方
# （我们代码库默认 4096）仍为推理阶段留出足够余量完成。DeepSeek 文档
# 上限是 64K。
_DEEPSEEK_THINKING_MAX_TOKENS_FLOOR = {
    "max": 32768,
    "high": 16384,
}


class DeepSeekProvider(OpenAIProvider):
    """DeepSeek provider（OpenAI 兼容 API）。

    通过 ``reasoning_effort`` 支持 v4 ``thinking`` 模式。当设置了
    ``reasoning_effort``（``"high"`` 或 ``"max"``）时，请求会带上
    ``thinking={"type": "enabled"}`` 以及所请求的 effort 级别作为顶层
    body 字段（DeepSeek API 接受两种 schema）。
    """

    # DeepSeek 的 API 不暴露 embeddings 端点。继承的 ``embed()`` 会在
    # 调用时 404，这曾经悄然让从未运行 ``setup-embedding`` 的
    # DeepSeek 用户的推荐管线崩溃。标记为 False 使
    # ``build_embedding_service`` 回退到 ollama / gemini。
    supports_embedding = False

    def __init__(
        self,
        api_key: str,
        model: str = "deepseek-v4-flash",
        *,
        reasoning_effort: str = "",
        timeout: float = 300.0,
    ) -> None:
        super().__init__(
            api_key=api_key,
            model=model,
            base_url="https://api.deepseek.com",
            provider_name="deepseek",
            timeout=timeout,
        )
        self._reasoning_effort = reasoning_effort.strip()

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
        # v0.3.51+: 单次调用的 ``reasoning_effort`` 覆盖。``None`` =
        # 使用 provider 默认（在 config.toml 中配置）。空字符串 =
        # 为此次调用显式禁用思考（用于 discovery 的 eval_batch 等
        # 结构化任务 —— 2026-05-05 日志观察到开启推理时 8-16 分钟/批，
        # 预期不开启时约 30 秒）。
        previous_effort = self._reasoning_effort
        applied_effort = reasoning_effort if reasoning_effort is not None else previous_effort
        # 临时修改实例属性，以便 ``_extra_body`` 和空内容重试路径
        # 看到的是单次调用的值。
        self._reasoning_effort = applied_effort
        try:
            effort = applied_effort
            if effort:
                floor = _DEEPSEEK_THINKING_MAX_TOKENS_FLOOR.get(effort, 16384)
                if max_tokens < floor:
                    logger.debug(
                        "deepseek: bumping max_tokens from %s to %s for effort=%s",
                        max_tokens,
                        floor,
                        effort,
                    )
                    max_tokens = floor
            try:
                return await super().complete(
                    messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    json_mode=json_mode,
                    model=model,
                )
            except LLMResponseError:
                if not effort:
                    logger.warning("deepseek: empty content; retrying once")
                    return await super().complete(
                        messages,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        json_mode=json_mode,
                        model=model,
                    )
                # 最大 effort 推理偶尔会在模型输出任何 ``content`` 之前
                # 烧光整个输出预算。禁用思考重试一次，让结构化管线得到
                # 可用响应而不是硬失败。
                logger.warning(
                    "deepseek: empty content with reasoning_effort=%s; "
                    "retrying with thinking disabled",
                    effort,
                )
                self._reasoning_effort = ""
                return await super().complete(
                    messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    json_mode=json_mode,
                    model=model,
                )
        finally:
            self._reasoning_effort = previous_effort

    def _extra_body(self) -> dict[str, Any]:
        if not self._reasoning_effort:
            return {}
        return {
            "thinking": {"type": "enabled"},
            "reasoning_effort": self._reasoning_effort,
        }
