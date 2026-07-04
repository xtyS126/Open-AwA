"""通过 OpenAI 兼容 API 的 Ollama LLM provider。"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from .base import LLMProviderError, LLMResponse, LLMResponseError, LLMTimeoutError
from .openai_provider import OpenAIProvider

logger = logging.getLogger(__name__)


class OllamaProvider(OpenAIProvider):
    """使用本地 OpenAI 兼容端点的 Ollama provider。

    通过 Ollama 的 ``/v1/chat/completions`` 垫片继承聊天补全支持。
    本类新增一个 ``embed()`` 方法，命中 Ollama *原生* 的
    ``/api/embeddings`` 端点 —— 该路由比 OpenAI 兼容嵌入垫片更直接，
    也是 Ollama 文档推荐的规范集成点。
    """

    # v0.3.54+: Ollama 专有的扩展重试。生产日志（2026-05-05）显示
    # 守护进程前 90 秒内出现 9 次 502 Bad Gateway，原因是 Ollama 正在
    # 从磁盘加载 bge-m3。基础 OpenAIProvider 重试（3 × 0.25s 线性
    # = 共 1.25s）远太短 —— 等模型加载完时请求早已失败。这些常量
    # 通过指数退避给出约 30s 总等待时间，吸收冷加载而不拖延稳态路径
    # （稳态下不会触发重试）。
    _OLLAMA_MAX_RETRIES = 5
    _OLLAMA_BASE_RETRY_DELAY = 1.0

    def __init__(
        self,
        api_key: str = "ollama",
        model: str = "llama3",
        base_url: str = "http://localhost:11434/v1",
        timeout: float = 300.0,
        num_ctx: int = 0,
    ) -> None:
        super().__init__(
            api_key=api_key,
            model=model,
            base_url=base_url,
            provider_name="ollama",
            timeout=timeout,
        )
        self._embed_timeout = timeout
        # v0.3.x+: 当 >0 时，聊天补全走 Ollama *原生* ``/api/chat``
        # 端点，以便传入 ``options.num_ctx``。OpenAI 兼容 ``/v1`` 垫片
        # 会静默丢弃 ``num_ctx``（已验证：模型停留在服务端默认值，
        # 通常是 4096），这会在 schema 中途截断大批量 prompt，让弱
        # 模型输出无法解析 / 重复的 JSON。0 保持 OpenAI 兼容路径
        # （行为不变）—— 见 _complete_native。
        self._num_ctx = max(0, int(num_ctx))

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
        """聊天补全，对 Ollama 启动抖动进行扩展重试。

        v0.3.54+: 当 Ollama 仍在加载模型时（最常发生在守护进程前
        60-90 秒），``/v1/chat/completions`` 会返回 502 / 503 或
        超时。基础的 3 次 × 0.25s 重试策略会在运行时就绪前耗尽重试。
        此处的覆盖在之上添加指数退避循环：1s、2s、4s、8s、16s ≈
        31s 墙钟时间，覆盖冷加载而不拖慢正常运行（模型热时不会触发重试）。
        """
        last_error: Exception | None = None
        for attempt in range(1, self._OLLAMA_MAX_RETRIES + 1):
            try:
                if self._num_ctx > 0:
                    return await self._complete_native(
                        messages,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        json_mode=json_mode,
                        model=model,
                    )
                return await super().complete(
                    messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    json_mode=json_mode,
                    reasoning_effort=reasoning_effort,
                    model=model,
                )
            except (LLMProviderError, LLMTimeoutError, httpx.TransportError) as exc:
                last_error = exc
                if attempt >= self._OLLAMA_MAX_RETRIES:
                    break
                delay = self._OLLAMA_BASE_RETRY_DELAY * (2 ** (attempt - 1))
                logger.info(
                    "Ollama complete attempt %d/%d failed (%s); "
                    "retrying in %.1fs (likely model still loading)",
                    attempt,
                    self._OLLAMA_MAX_RETRIES,
                    exc,
                    delay,
                )
                await asyncio.sleep(delay)
        # 所有尝试耗尽 —— 重新抛出最后一个错误，让注册表的回退链
        # 可以路由到下一个 provider。
        if last_error is None:  # pragma: no cover —— 防御性
            raise LLMProviderError("ollama: complete failed without exception")
        raise last_error

    async def _complete_native(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float,
        max_tokens: int,
        json_mode: bool,
        model: str | None,
    ) -> LLMResponse:
        """通过 Ollama 原生 ``/api/chat`` 端点进行聊天补全。

        仅当 ``num_ctx > 0`` 时使用。与 OpenAI 兼容 ``/v1`` 垫片不同，
        原生端点会遵循 ``options.num_ctx``，因此完整 prompt 会保留在
        上下文窗口内，而不会在服务端默认值处被静默截断。``max_tokens``
        映射到 ``num_predict``；``json_mode`` 映射到 ``format="json"``
        （Ollama 的有效 JSON 约束，与垫片的 ``response_format=json_object``
        对应的原生等价物）。
        """
        effective_model = (model or "").strip() or self._model
        payload: dict[str, Any] = {
            "model": effective_model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_ctx": self._num_ctx,
                "num_predict": max_tokens,
            },
        }
        if json_mode:
            payload["format"] = "json"

        data = await self._post_chat(payload)
        content = str((data.get("message") or {}).get("content") or "")
        if not content.strip() and json_mode:
            # 与 OpenAI 垫片路径保持一致：某些模型在 JSON 约束下
            # 输出空内容。去掉约束重试一次 —— prompt 本身已要求 JSON。
            logger.warning(
                "ollama: empty content with format=json on /api/chat; "
                "retrying without the format constraint"
            )
            payload.pop("format", None)
            data = await self._post_chat(payload)
            content = str((data.get("message") or {}).get("content") or "")
        if not content.strip():
            raise LLMResponseError("ollama returned empty content")

        usage = None
        prompt_tokens = int(data.get("prompt_eval_count", 0) or 0)
        completion_tokens = int(data.get("eval_count", 0) or 0)
        if prompt_tokens or completion_tokens:
            usage = {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            }
        return LLMResponse(
            content=content,
            model=str(data.get("model") or effective_model),
            provider=self._provider_name,
            usage=usage,
            raw=data,
        )

    async def _post_chat(self, payload: dict[str, Any]) -> dict[str, Any]:
        """POST 到 ``/api/chat`` 并返回解码后的 JSON 体。

        传输 / 超时错误会向上传播，以便 ``complete`` 的重试循环吸收
        冷加载抖动；HTTP 状态错误被映射为 ``LLMProviderError``（同样
        会被重试），以与垫片路径保持一致。``trust_env=False`` 绕过
        用户本地代理 —— 与 ``embed`` 路径已依赖的修复相同。
        """
        url = f"{self._native_root()}/api/chat"
        async with httpx.AsyncClient(timeout=self._timeout, trust_env=False) as client:
            response = await client.post(url, json=payload)
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise LLMProviderError(
                    f"ollama: /api/chat returned HTTP {exc.response.status_code}"
                ) from exc
            decoded = response.json()
        if not isinstance(decoded, dict):
            raise LLMResponseError("ollama: /api/chat returned a non-object body")
        return decoded

    def _native_root(self) -> str:
        """剥离 OpenAI 兼容的 ``/v1`` 后缀以获取 Ollama 原生 API 根。"""
        return self.base_url.rstrip("/").rsplit("/v1", 1)[0]

    async def embed(self, text: str, *, model: str = "bge-m3") -> list[float]:
        """通过 Ollama 原生 ``/api/embeddings`` 端点获取文本嵌入。

        推荐的本地回退模型是 ``bge-m3``（多语言，1024 维）。其他
        Ollama 嵌入模型也可使用 —— 只需传入 ``model=...``。

        在瞬时错误（超时 / 连接断开 / Ollama runner 重启）时重试一次。
        仅在两次尝试都失败后返回空列表。调用方（EmbeddingService）
        将空向量视为"无嵌入"并跳过缓存。
        """
        url = f"{self._native_root()}/api/embeddings"
        last_exc: Exception | None = None
        # 1 次初始 + 1 次重试。重试覆盖短暂的 Ollama 抖动（模型切换、
        # runner 重启、瞬时 OOM），不会让瞬时失败把用户体验污染好几
        # 分钟。两次尝试足够 —— 若第二次也失败，说明出现了结构性
        # 问题，再加更多重试只是推迟必然的 WARN。
        for attempt in (1, 2):
            try:
                # trust_env=False 绕过用户的 HTTP_PROXY / HTTPS_PROXY
                # 环境变量，否则本地嵌入调用会被路由到例如 127.0.0.1:7897
                # 的 VPN 代理并超时。
                #
                # 120s 超时吸收 (a) bge-m3 首次冷加载（Ollama 唤醒后
                # 首次调用从磁盘加载约 10-30s）和 (b) EmbeddingService
                # 限流到并发=2 但守护进程在数秒内排了 >2 个缓存未命中
                # 文本时的短暂请求队列积压。代理修复后的缓存重建突发
                # 下 60s 太紧。
                async with httpx.AsyncClient(
                    timeout=self._embed_timeout,
                    trust_env=False,
                ) as client:
                    response = await client.post(
                        url,
                        json={"model": model, "prompt": text},
                    )
                    response.raise_for_status()
                    data = response.json()
                vec = data.get("embedding")
                if not isinstance(vec, list):
                    return []
                return [float(v) for v in vec if isinstance(v, int | float)]
            except Exception as exc:
                last_exc = exc
                if attempt == 1:
                    logger.debug(
                        "Ollama embedding attempt 1 failed (model=%s), retrying",
                        model,
                        exc_info=True,
                    )

        logger.warning(
            "Ollama embedding failed after 2 attempts (model=%s, url=%s)",
            model,
            url,
            exc_info=last_exc,
        )
        return []
