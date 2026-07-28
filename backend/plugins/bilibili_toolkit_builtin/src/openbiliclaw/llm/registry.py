"""构建已配置 LLM registry 的工厂辅助工具。"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .base import LLMProvider, LLMProviderError, LLMRegistry
from .claude_provider import ClaudeProvider
from .gemini_provider import GeminiProvider, gemini_sdk_available
from .ollama_provider import OllamaProvider
from .openai_provider import DeepSeekProvider, OpenAIProvider
from .openrouter_provider import OpenRouterProvider

if TYPE_CHECKING:
    from openbiliclaw.config import Config
    from openbiliclaw.llm.embedding import SupportsEmbeddingService

logger = logging.getLogger(__name__)


class RegistryBuildError(LLMProviderError):
    """当配置无法创建任何可用 provider 时抛出。"""


@dataclass
class RegistrySummary:
    """registry 构建细节的摘要。"""

    configured_default: str
    effective_default: str
    registered_providers: list[str]


def build_llm_registry(
    config: Config,
    *,
    provider_overrides: dict[str, LLMProvider] | None = None,
    fallback_order: list[str] | None = None,
) -> LLMRegistry:
    """根据应用配置构建 LLM registry。"""
    overrides = provider_overrides or {}
    registry = LLMRegistry()
    registry.fallback_enabled = bool(getattr(config.llm, "fallback_enabled", False))
    registry.fallback_provider = str(getattr(config.llm, "fallback_provider", "")).strip().lower()

    provider_specs = [
        ("openai", _maybe_openai_provider(config, overrides)),
        ("claude", _maybe_claude_provider(config, overrides)),
        ("gemini", _maybe_gemini_provider(config, overrides)),
        ("deepseek", _maybe_deepseek_provider(config, overrides)),
        ("ollama", _maybe_ollama_provider(config, overrides)),
        ("openrouter", _maybe_openrouter_provider(config, overrides)),
        ("openai_compatible", _maybe_openai_compatible_provider(config, overrides)),
    ]

    for _name, provider in provider_specs:
        if provider is None:
            continue
        # Ollama 有特殊的 chat 能力检查：即使用户从未配置 chat 模型，
        # registry 在做 embedding 时也需要它；但此时它 MUST 不进入
        # chat fallback 链（见 _ollama_is_chat_capable + base.py:_fallback_order）。
        chat_capable = True
        if _name == "ollama" and not _ollama_is_chat_capable(config):
            chat_capable = False
        registry.register(provider, default=False, chat_capable=chat_capable)

    for name, provider in overrides.items():
        if name not in registry.available_providers:
            registry.register(provider, default=False)

    if fallback_order:
        reordered = [name for name in fallback_order if name in registry.available_providers]
        remainder = [name for name in registry.available_providers if name not in reordered]
        registry._providers = {name: registry._providers[name] for name in [*reordered, *remainder]}

    if not registry.available_providers:
        raise RegistryBuildError("No LLM providers are available from the current configuration.")

    configured_default = config.llm.default_provider
    effective_default = (
        configured_default
        if configured_default in registry.available_providers
        else registry.available_providers[0]
    )
    registry._default = effective_default
    return registry


_EMBEDDING_CAPABLE_PROVIDERS: tuple[str, ...] = (
    "openai",
    "gemini",
    "ollama",
    # 大多数 OpenAI 协议兼容后端（Together、vLLM、Azure OpenAI 等）
    # 暴露 /v1/embeddings。Groq 目前不暴露，但运行 Groq +
    # openai_compatible 配置的用户本来就必须在 [llm.embedding] 中显式
    # 指定 embedding provider —— 这个候选项只有在用户主动请求时才生效。
    "openai_compatible",
    # OpenRouter 按 ``<vendor>/<model>`` slug 路由 embedding
    # （例如 ``google/gemini-embedding-2-preview``、
    # ``openai/text-embedding-3-small``）。各路由覆盖范围参差不齐，
    # 因此它不进入 chat 侧的 ``supports_embedding`` 标志 ——
    # 用户必须通过设置 ``[llm.embedding].provider = "openrouter"``
    # 并显式指定 ``model`` 来主动启用。
    "openrouter",
)
_DEFAULT_EMBEDDING_MODEL_BY_PROVIDER: dict[str, str] = {
    "gemini": "gemini-embedding-001",
    "openai": "text-embedding-3-small",
    "ollama": "bge-m3",
    # openai_compatible 没有安全的默认值 —— 完全取决于上游服务。
    # 用户必须显式指定模型。
    "openai_compatible": "text-embedding-3-small",
}
# 模块级集合，确保 back-compat 警告在每个进程每个 provider 上只触发一次
# （而非每次 build_embedding_service 调用都触发 —— runtime_context 在
# 每次 PUT /api/config 时都会重建 embedding，不能让它刷屏）。
_embedding_compat_warned: set[str] = set()


def build_embedding_service(
    config: Config,
    registry: LLMRegistry,  # noqa: ARG001 — 保留给 back-compat 调用方
) -> SupportsEmbeddingService | None:
    """根据 ``[llm.embedding]`` 构建 EmbeddingService。

    v0.3.32+ 起 embedding 拥有自己专属的 ``api_key`` / ``base_url``
    （见 ``EmbeddingConfig``），因此 embedding provider 作为独立实例
    构造 —— 与 chat 侧的 LLMRegistry 完全解耦。保留 ``registry`` 参数
    只是为了现有调用点不必修改；它已不再被查阅。

    ``[llm.embedding].provider`` 为空时禁用 embedding；它不再跟随
    ``[llm].default_provider``。Provider fallback 通过
    ``[llm.embedding].fallback_provider`` 显式启用，且只会尝试那一个
    显式备份 provider。``fallback_enabled`` 作为遗留兼容标志保留，
    用于借用 chat 侧凭证。
    """
    try:
        from typing import cast

        from openbiliclaw.llm.embedding import EmbeddingCache, EmbeddingService, SupportsEmbed

        emb_cfg = config.llm.embedding
        requested_name = emb_cfg.provider.strip().lower()
        fallback_provider = str(getattr(emb_cfg, "fallback_provider", "")).strip().lower()

        # 构建候选顺序：先请求的 provider，再可选的显式 fallback provider。
        # 空 provider 不再跟随 [llm].default_provider；embedding 是独立的
        # 配置面。
        fallback_order: list[str] = []
        fallback_candidates: tuple[str, ...] = (fallback_provider,) if fallback_provider else ()
        for name in ((requested_name,) if requested_name else ()) + fallback_candidates:
            if name in _EMBEDDING_CAPABLE_PROVIDERS and name not in fallback_order:
                fallback_order.append(name)

        chosen_provider: LLMProvider | None = None
        chosen_name = ""
        chosen_model = ""
        for candidate in fallback_order:
            built = _build_dedicated_embedding_provider(candidate, emb_cfg, config, requested_name)
            if built is None:
                continue
            chosen_provider, chosen_model = built
            chosen_name = candidate
            break

        if chosen_provider is None:
            requested_label = requested_name or "(not configured)"
            logger.warning(
                "No embedding-capable provider available (requested=%r). "
                "Embedding service disabled — recommendation diversity and "
                "deduplication will degrade. Run 'openbiliclaw setup-embedding' "
                "to install local Ollama bge-m3, or configure a Gemini API key.",
                requested_label,
            )
            return None

        if chosen_name != requested_name:
            requested_label = requested_name or "(not configured)"
            logger.warning(
                "Embedding provider %r unavailable; falling back to %r. "
                "Set [llm.embedding] provider=%r explicitly in config.toml "
                "to silence this, or run 'openbiliclaw setup-embedding'.",
                requested_label,
                chosen_name,
                chosen_name,
            )

        # 持久化 L2 缓存：将 embedding 存储在与主 DB 同目录的 SQLite 中
        l2_cache: EmbeddingCache | None = None
        try:
            cache_path = config.data_path / "embedding_cache.db"
            l2_cache = EmbeddingCache(cache_path)
            l2_cache.initialize()
        except Exception:
            logger.debug("Failed to init embedding L2 cache", exc_info=True)

        output_dimensionality = _embedding_output_dimensionality(emb_cfg)
        cache_model = _embedding_cache_model(
            chosen_name,
            chosen_model,
            output_dimensionality,
        )

        return EmbeddingService(
            cast("SupportsEmbed", chosen_provider),
            model=chosen_model,
            cache_model=cache_model,
            similarity_threshold=emb_cfg.similarity_threshold,
            persistent_cache=l2_cache,
        )
    except Exception:
        return None


def _build_dedicated_embedding_provider(
    candidate: str,
    emb_cfg: Any,
    config: Config,
    requested_name: str,
) -> tuple[LLMProvider, str] | None:
    """为 embedding 调用构造独立的 provider 实例。

    返回 ``(provider, effective_model)``，若候选无法构造（缺 api_key、
    缺 SDK 等）则返回 ``None``。
    """
    emb_api_key = emb_cfg.api_key.strip()
    emb_base_url = emb_cfg.base_url.strip()
    fallback_enabled = bool(getattr(emb_cfg, "fallback_enabled", False))
    output_dimensionality = _embedding_output_dimensionality(emb_cfg)

    # 一等路径：候选与用户请求一致 且 用户在 [llm.embedding] 中提供了凭证。
    use_embedding_creds = candidate == requested_name and bool(emb_api_key or emb_base_url)

    if use_embedding_creds:
        api_key = emb_api_key
        base_url = emb_base_url
    elif fallback_enabled:
        # 可选 back-compat 路径：仅在 embedding fallback 显式开启时
        # 才从 [llm.<candidate>] 借用凭证。
        chat_cfg = getattr(config.llm, candidate, None)
        api_key = (getattr(chat_cfg, "api_key", "") if chat_cfg is not None else "").strip()
        base_url = (getattr(chat_cfg, "base_url", "") if chat_cfg is not None else "").strip()
        borrowed_chat_credentials = (
            bool(api_key and base_url) if candidate == "openai_compatible" else bool(api_key)
        )
        if (
            emb_cfg.provider.strip().lower() == candidate
            and candidate == requested_name
            and candidate != "ollama"
            and borrowed_chat_credentials
        ):
            _emit_embedding_compat_warning(candidate)
    else:
        api_key = ""
        base_url = ""

    # 有效模型：只有在构造被请求的 provider 时才尊重显式的
    # emb_cfg.model —— fallback 路径必须使用各 provider 的默认值
    # （例如回退到 Ollama 时 text-embedding-3-small 毫无意义）。
    if candidate == requested_name and emb_cfg.model.strip():
        effective_model = emb_cfg.model.strip()
    else:
        effective_model = _DEFAULT_EMBEDDING_MODEL_BY_PROVIDER.get(
            candidate, "gemini-embedding-001"
        )

    if candidate == "ollama":
        # Ollama 不需要 api_key，若不加门控构造器永远会成功，从而静默
        # 掩盖"用户没有任何 embedding 能力的 provider"这一事实 —— 这
        # 会影响警告路径（提示用户去设置 Ollama 或 Gemini key）。仅在
        # 用户确实主动选择时才构造：
        #   - [llm.embedding] 提供了自己的 ollama 配置，或
        #   - 用户为 embedding 请求了 Ollama，或
        #   - [llm.ollama] 已配置（back-compat —— 用户在本地跑它）。
        chat_ollama = config.llm.ollama
        has_chat_ollama_config = bool(chat_ollama.model.strip() or chat_ollama.base_url.strip())
        if not use_embedding_creds and requested_name != "ollama" and not has_chat_ollama_config:
            return None
        if not base_url:
            base_url = "http://localhost:11434/v1"
        if not base_url.rstrip("/").endswith("/v1"):
            base_url = base_url.rstrip("/") + "/v1"
        return (
            OllamaProvider(
                api_key=api_key or "ollama",
                model=effective_model,
                base_url=base_url,
            ),
            effective_model,
        )

    if candidate == "openai":
        if not api_key:
            return None
        return (
            OpenAIProvider(
                api_key=api_key,
                model=effective_model,
                base_url=base_url,
                embedding_output_dimensionality=output_dimensionality,
            ),
            effective_model,
        )

    if candidate == "gemini":
        if not api_key:
            api_key = _gemini_env_api_key()
        if not api_key or not gemini_sdk_available():
            return None
        return (
            GeminiProvider(
                api_key=api_key,
                model=effective_model,
                base_url=base_url,
                embedding_output_dimensionality=output_dimensionality,
            ),
            effective_model,
        )

    if candidate == "openai_compatible":
        # 严格 —— 没有 api_key 或没有 base_url 就无法构造。
        # 与 "openai" 不同，这里没有 api.openai.com fallback，
        # 因为该 provider 存在的全部理由就是自定义 base_url。
        if not api_key or not base_url:
            return None
        return (
            OpenAIProvider(
                api_key=api_key,
                model=effective_model,
                base_url=base_url,
                provider_name="openai_compatible",
            ),
            effective_model,
        )

    if candidate == "openrouter":
        # OpenRouter 要求显式的 ``<vendor>/<model>`` slug —— 没有安全
        # 默认值，因为路由取决于它。无 slug 时拒绝构造，而不是在第一次
        # embed 调用时才 404。
        if not api_key:
            return None
        if candidate == requested_name and not emb_cfg.model.strip():
            return None
        # 从 [llm.openrouter] 透传可选的 attribution headers，让
        # embedding 流量与 chat 流量在同一个 OpenRouter 账户面板下显示。
        chat_openrouter = config.llm.openrouter
        return (
            OpenRouterProvider(
                api_key=api_key,
                model=effective_model,
                base_url=base_url or "https://openrouter.ai/api/v1",
                http_referer=chat_openrouter.http_referer,
                x_title=chat_openrouter.x_title,
            ),
            effective_model,
        )

    return None


def _embedding_output_dimensionality(emb_cfg: Any) -> int:
    try:
        return max(0, int(getattr(emb_cfg, "output_dimensionality", 1024) or 0))
    except (TypeError, ValueError):
        return 1024


def _embedding_cache_model(
    provider_name: str,
    model: str,
    output_dimensionality: int,
) -> str:
    if output_dimensionality > 0 and _embedding_provider_honors_output_dimensionality(
        provider_name, model
    ):
        return f"{model}#dim={output_dimensionality}"
    return model


def _embedding_provider_honors_output_dimensionality(
    provider_name: str,
    model: str,
) -> bool:
    if provider_name == "gemini":
        return True
    if provider_name == "openai":
        return model.startswith("text-embedding-3-")
    return False


def _emit_embedding_compat_warning(provider_name: str) -> None:
    """每个 provider 每个进程至多触发一次 embedding back-compat 路径的
    WARNING。"""
    if provider_name in _embedding_compat_warned:
        return
    _embedding_compat_warned.add(provider_name)
    logger.warning(
        "[llm.embedding] api_key/base_url is empty — falling back to "
        "[llm.%s] credentials. This back-compat path will be removed in a "
        "future release. Move the embedding credentials into "
        "[llm.embedding] in your config.toml.",
        provider_name,
    )


def summarize_registry(config: Config, registry: LLMRegistry) -> RegistrySummary:
    """返回 registry 摘要详情，用于 CLI 展示。"""
    return RegistrySummary(
        configured_default=config.llm.default_provider,
        effective_default=registry.default_provider,
        registered_providers=registry.available_providers,
    )


def _maybe_openai_provider(config: Config, overrides: dict[str, LLMProvider]) -> LLMProvider | None:
    if "openai" in overrides:
        return overrides["openai"]
    auth_mode = config.llm.openai.auth_mode.strip().lower()
    if auth_mode == "codex_oauth":
        from openbiliclaw.llm.codex_auth import get_valid_codex_token, load_codex_credentials

        credentials = load_codex_credentials()
        if credentials is None:
            logger.warning("codex_oauth configured but no Codex credentials were found")
            return None

        async def _codex_token_provider(force_refresh: bool = False) -> str:
            return await get_valid_codex_token(force_refresh=force_refresh)

        return OpenAIProvider(
            api_key=credentials.access_token,
            model=config.llm.openai.model or "gpt-4o",
            base_url=config.llm.openai.base_url,
            token_provider=_codex_token_provider,
            timeout=float(config.llm.timeout),
        )
    if not config.llm.openai.api_key.strip():
        return None
    return OpenAIProvider(
        api_key=config.llm.openai.api_key,
        model=config.llm.openai.model or "gpt-4o",
        base_url=config.llm.openai.base_url,
        timeout=float(config.llm.timeout),
    )


def _maybe_claude_provider(config: Config, overrides: dict[str, LLMProvider]) -> LLMProvider | None:
    if "claude" in overrides:
        return overrides["claude"]
    if not config.llm.claude.api_key.strip():
        return None
    return ClaudeProvider(
        api_key=config.llm.claude.api_key,
        model=config.llm.claude.model or "claude-sonnet-4-20250514",
        timeout=float(config.llm.timeout),
    )


def _maybe_deepseek_provider(
    config: Config, overrides: dict[str, LLMProvider]
) -> LLMProvider | None:
    if "deepseek" in overrides:
        return overrides["deepseek"]
    if not config.llm.deepseek.api_key.strip():
        return None
    return DeepSeekProvider(
        api_key=config.llm.deepseek.api_key,
        model=config.llm.deepseek.model or "deepseek-v4-flash",
        reasoning_effort=config.llm.deepseek.reasoning_effort,
        timeout=float(config.llm.timeout),
    )


def _gemini_env_api_key() -> str:
    return (
        os.environ.get("GOOGLE_API_KEY", "").strip() or os.environ.get("GEMINI_API_KEY", "").strip()
    )


def _maybe_gemini_provider(config: Config, overrides: dict[str, LLMProvider]) -> LLMProvider | None:
    if "gemini" in overrides:
        return overrides["gemini"]
    api_key = config.llm.gemini.api_key.strip() or _gemini_env_api_key()
    if not api_key:
        return None
    if not gemini_sdk_available():
        return None
    return GeminiProvider(
        api_key=api_key,
        model=config.llm.gemini.model or "gemini-2.5-flash",
        timeout=float(config.llm.timeout),
    )


def _maybe_ollama_provider(config: Config, overrides: dict[str, LLMProvider]) -> LLMProvider | None:
    if "ollama" in overrides:
        return overrides["ollama"]

    raw_base_url = config.llm.ollama.base_url.strip()
    model = config.llm.ollama.model.strip()

    # v0.3.32+ 注：build_embedding_service 现在直接从 [llm.embedding]
    # （或 back-compat 从 [llm.ollama]）构造自己的 Ollama provider ——
    # 不再经过本 registry。因此不再需要旧的 ``embedding_wants_ollama``
    # 自动注册 hack：chat registry 保持干净，Ollama 仅在用户确实想用
    # 它做 chat completion 时才在这里注册。
    if not model and not raw_base_url:
        return None
    base_url = raw_base_url or "http://localhost:11434/v1"
    # 规范化：Ollama 的 OpenAI 兼容 shim 位于 ``/v1/...``。旧版
    # config.example.toml 中是 ``http://localhost:11434``（无 /v1），
    # 这会让 OpenAI SDK 调用 ``/chat/completions`` —— Ollama 会 404。
    # 防御性地补上 /v1，让使用旧配置的用户升级后仍能正常 chat。
    if not base_url.rstrip("/").endswith("/v1"):
        base_url = base_url.rstrip("/") + "/v1"
    return OllamaProvider(
        api_key=config.llm.ollama.api_key or "ollama",
        model=model or "llama3",
        base_url=base_url,
        timeout=float(config.llm.timeout),
        num_ctx=int(config.llm.ollama.num_ctx),
    )


def _ollama_is_chat_capable(config: Config) -> bool:
    """判断已注册的 Ollama 实例是否能提供 chat completion，还是只能
    处理 embedding 请求。

    用户通过以下任意方式启用 chat 能力：
      * 设置 ``[llm.ollama] model``（显式 chat 模型），或
      * 将 ``ollama`` 选为 ``[llm].default_provider``，或
      * 将 ``ollama`` 命名为 ``[llm].fallback_provider`` —— 显式请求
        将本地 Ollama 作为 chat fallback，或
      * 在任何按模块的 override 中使用它。

    若以上都不满足，且我们仅因 embedding 段指向它才注册了 Ollama，
    则视为仅支持 embedding。fallback 链在 chat completion 时会跳过它，
    避免出现"磁盘上唯一的模型是 bge-m3 时，报 All providers failed
    (..., ollama). Last error: ollama request failed: 404"的情况。

    注：当 chat 能力*仅*来自 ``fallback_provider``（无显式
    ``[llm.ollama] model``）时，provider 会以 ``llama3`` 默认值构造 ——
    因此用户必须本地拉取一个 chat 模型，fallback 才能真正服务请求。
    但这是用户声明的意图，fallback 时的 404 比"静默把 Ollama 从链中
    删除"是更响亮、更诚实的失败。
    """
    if config.llm.ollama.model.strip():
        return True
    if config.llm.default_provider.strip().lower() == "ollama":
        return True
    if config.llm.fallback_provider.strip().lower() == "ollama":
        return True
    for module in ("soul", "discovery", "recommendation", "evaluation"):
        module_cfg = getattr(config.llm, module, None)
        if module_cfg is None:
            continue
        if str(getattr(module_cfg, "provider", "")).strip().lower() == "ollama":
            return True
    return False


def _maybe_openrouter_provider(
    config: Config, overrides: dict[str, LLMProvider]
) -> LLMProvider | None:
    if "openrouter" in overrides:
        return overrides["openrouter"]
    if not config.llm.openrouter.api_key.strip():
        return None
    return OpenRouterProvider(
        api_key=config.llm.openrouter.api_key,
        model=config.llm.openrouter.model or "openai/gpt-4o-mini",
        base_url=config.llm.openrouter.base_url or "https://openrouter.ai/api/v1",
        http_referer=config.llm.openrouter.http_referer,
        x_title=config.llm.openrouter.x_title,
        timeout=float(config.llm.timeout),
    )


def _maybe_openai_compatible_provider(
    config: Config, overrides: dict[str, LLMProvider]
) -> LLMProvider | None:
    """通用 OpenAI 协议兼容 provider（Groq / Together / Azure OpenAI /
    vLLM / 自托管等）。

    与 ``[llm.openai]`` 区分，让用户可以并行运行两者并保持成本 / 模型
    核算独立。无 ``base_url`` 时拒绝注册 —— 这是该 provider 存在的全部
    意义；没有它，调用只会打到 api.openai.com，与 ``[llm.openai]`` 无
    法区分（且会用错的 key 401）。"""
    if "openai_compatible" in overrides:
        return overrides["openai_compatible"]
    cfg = config.llm.openai_compatible
    if not cfg.api_key.strip():
        return None
    if not cfg.base_url.strip():
        # 在 _collect_config_issues 中作为 ConfigIssue 暴露；这里只是
        # 拒绝构造一个配置错误的 provider。
        return None
    return OpenAIProvider(
        api_key=cfg.api_key,
        model=cfg.model or "gpt-4o-mini",
        base_url=cfg.base_url,
        provider_name="openai_compatible",
        timeout=float(config.llm.timeout),
    )
