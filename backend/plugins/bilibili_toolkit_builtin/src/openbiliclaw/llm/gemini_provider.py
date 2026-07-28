"""基于官方 google-genai SDK 构建的 Gemini Developer API provider。"""

from __future__ import annotations

import asyncio
from typing import Any, NoReturn

from .base import (
    LLMProvider,
    LLMProviderError,
    LLMRateLimitError,
    LLMResponse,
    LLMResponseError,
    LLMTimeoutError,
)

genai: Any | None
errors: Any | None
types: Any | None

try:
    from google import genai as _genai
    from google.genai import errors as _errors
    from google.genai import types as _types
except ModuleNotFoundError:  # pragma: no cover - 通过集成行为覆盖
    genai = None
    errors = None
    types = None
else:
    genai = _genai
    errors = _errors
    types = _types


def gemini_sdk_available() -> bool:
    """返回可选依赖 google-genai 是否已安装。"""
    return genai is not None and types is not None


def _raise_missing_sdk() -> NoReturn:
    raise LLMProviderError(
        "Gemini provider requires the optional dependency 'google-genai' to be installed."
    )


class GeminiProvider(LLMProvider):
    """使用官方 Gemini Developer API 客户端的 Gemini provider。"""

    supports_embedding = True

    _MAX_RETRIES = 3
    _BASE_RETRY_DELAY = 0.25

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-2.5-flash",
        timeout: float = 300.0,
        base_url: str = "",
        embedding_output_dimensionality: int | None = None,
    ) -> None:
        if not gemini_sdk_available():
            _raise_missing_sdk()
        assert genai is not None
        self._model = model
        self._embedding_output_dimensionality = (
            embedding_output_dimensionality
            if embedding_output_dimensionality is not None and embedding_output_dimensionality > 0
            else None
        )
        http_options: dict[str, int | str] = {"timeout": int(timeout * 1000)}
        normalized_base_url = (base_url or "").strip()
        if normalized_base_url:
            http_options["base_url"] = normalized_base_url.rstrip("/") + "/"
        self._client = genai.Client(
            api_key=api_key,
            http_options=http_options,
        )

    @staticmethod
    def _is_reasoning_first_model(model: str) -> bool:
        """判断模型是否属于会拒绝 ``thinking_budget=0`` 的推理优先家族。

        背景：``thinking_budget=0`` 这个 hack 是 2.5-flash 的成本优化 ——
        它告诉 Gemini "不要花 token 思考"。Gemini 3.x Pro / 3.x Flash
        和 2.5-pro 是推理优先模型；Google 会对它们拒绝
        ``thinking_budget=0``，返回 ``400 INVALID_ARGUMENT``
        （"Thinking budget X is invalid for model Y"）。症状：第一次
        调用可能侥幸通过，但 json_mode 调用点（discovery / soul 结构化
        任务）会立即全部 400。

        此检查刻意基于名称（不调用 SDK）：preview / GA / 带日期修订版
        共享相同家族前缀。
        """
        m = model.lower()
        # Gemini 3.x: 3-pro / 3-flash / 3.1-pro / 3.1-flash-lite-preview / ...
        if m.startswith("gemini-3"):
            return True
        # 2.5-pro 也是推理优先；2.5-flash 是唯一合法接受
        # thinking_budget=0 的 2.5 变体。
        return m.startswith("gemini-2.5-pro")

    @property
    def name(self) -> str:
        return "gemini"

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
        # ``reasoning_effort`` 是 DeepSeek 专有。Gemini 有自己的
        # ``thinking_config``，且在 JSON 模式下已自动禁用。为保持
        # 签名兼容性接受此参数，但此处不做任何处理。
        del reasoning_effort
        if types is None:
            _raise_missing_sdk()
        effective_model = (model or "").strip() or self._model
        # ``thinking_budget=0`` 是 2.5-flash 的成本节省。推理优先模型
        # （3.x 家族、2.5-pro）会以 400 INVALID_ARGUMENT 拒绝它 ——
        # 见 _is_reasoning_first_model。在这些模型上跳过此 hack。
        thinking_config = None
        if json_mode and not self._is_reasoning_first_model(effective_model):
            thinking_config = types.ThinkingConfig(thinking_budget=0)
        config = types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
            response_mime_type="application/json" if json_mode else None,
            thinking_config=thinking_config,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        response = await self._request_with_retry(
            model=effective_model,
            contents=self._render_messages(messages),
            config=config,
        )

        content = response.text or ""
        if not content.strip():
            raise LLMResponseError("gemini returned empty content")

        usage = None
        if response.usage_metadata is not None:
            usage = {
                "prompt_tokens": response.usage_metadata.prompt_token_count or 0,
                "completion_tokens": response.usage_metadata.candidates_token_count or 0,
                "total_tokens": response.usage_metadata.total_token_count or 0,
            }
            # 当使用先前上传的显式缓存（Context Caching API）时，
            # Gemini 会暴露 cached_content_token_count。在通用的
            # ``cached_input_tokens`` 键下做归一化。
            cached = int(getattr(response.usage_metadata, "cached_content_token_count", 0) or 0)
            if cached:
                usage["cached_input_tokens"] = cached

        return LLMResponse(
            content=content,
            model=response.model_version or effective_model,
            provider="gemini",
            usage=usage,
            raw=response,
        )

    async def _request_with_retry(self, **kwargs: Any) -> Any:
        last_error: Exception | None = None

        for attempt in range(1, self._MAX_RETRIES + 1):
            try:
                return await self._client.aio.models.generate_content(**kwargs)
            except Exception as exc:
                mapped = self._map_error(exc)
                last_error = mapped
                if not self._is_retryable(mapped) or attempt == self._MAX_RETRIES:
                    raise mapped from exc
                await asyncio.sleep(self._BASE_RETRY_DELAY * attempt)

        if last_error is None:
            raise LLMProviderError("gemini request failed")
        raise last_error

    def _map_error(self, exc: Exception) -> LLMProviderError:
        if isinstance(exc, LLMProviderError):
            return exc
        if isinstance(exc, TimeoutError):
            return LLMTimeoutError("gemini request timed out")

        status_code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
        message = (getattr(exc, "message", None) or str(exc)).lower()
        if status_code == 429 or "rate limit" in message or "resource_exhausted" in message:
            return LLMRateLimitError("gemini rate limit exceeded")
        if (errors is not None and isinstance(exc, errors.ServerError)) or (
            status_code and int(status_code) >= 500
        ):
            return LLMProviderError(f"gemini server error: {status_code}")
        return LLMProviderError(f"gemini request failed: {exc}")

    def _is_retryable(self, exc: LLMProviderError) -> bool:
        if isinstance(exc, LLMRateLimitError):
            return False
        return isinstance(exc, (LLMProviderError, LLMTimeoutError))

    async def embed(self, text: str, *, model: str = "gemini-embedding-001") -> list[float]:
        """使用 Gemini 的嵌入模型获取文本嵌入。

        Args:
            text: 待嵌入的文本。
            model: 嵌入模型名称（默认：text-embedding-004）。

        Returns:
            嵌入向量（text-embedding-004 为 768 维）。
        """
        if types is None:
            _raise_missing_sdk()
        config_kwargs: dict[str, Any] = {"task_type": "SEMANTIC_SIMILARITY"}
        if self._embedding_output_dimensionality is not None:
            config_kwargs["output_dimensionality"] = self._embedding_output_dimensionality
        response = await self._client.aio.models.embed_content(
            model=model,
            contents=text,
            config=types.EmbedContentConfig(**config_kwargs),
        )
        return list(response.embeddings[0].values)

    def _render_messages(self, messages: list[dict[str, str]]) -> str:
        chunks: list[str] = []
        for message in messages:
            content = message["content"].strip()
            if not content:
                continue
            role = message["role"].upper()
            chunks.append(f"[{role}]\n{content}")
        return "\n\n".join(chunks)
