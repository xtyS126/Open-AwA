"""基于 OpenAI 兼容客户端构建的 OpenRouter provider。"""

from __future__ import annotations

from .openai_provider import OpenAIProvider


class OpenRouterProvider(OpenAIProvider):
    """带可选 attribution 头的 OpenRouter provider。"""

    # OpenRouter 路由大多数聊天模型，但其 embeddings 覆盖因路由而异
    # —— 默认回退到 ollama / gemini 比让用户在管线中途遭遇 404 更好。
    # 想用 OpenRouter 嵌入的用户可设置
    # ``[llm.embedding] provider="openrouter"`` 并指定显式
    # ``<vendor>/<model>``（例如 ``google/gemini-embedding-2-preview``）；
    # 该专用路径位于
    # ``registry._build_dedicated_embedding_provider``，不查阅此标志。
    supports_embedding = False

    def __init__(
        self,
        api_key: str,
        model: str = "openai/gpt-4o-mini",
        base_url: str = "https://openrouter.ai/api/v1",
        http_referer: str = "",
        x_title: str = "",
        timeout: float = 300.0,
    ) -> None:
        super().__init__(
            api_key=api_key,
            model=model,
            base_url=base_url,
            provider_name="openrouter",
            timeout=timeout,
        )
        self._http_referer = http_referer
        self._x_title = x_title

    def _extra_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self._http_referer.strip():
            headers["HTTP-Referer"] = self._http_referer
        if self._x_title.strip():
            headers["X-Title"] = self._x_title
        return headers
