"""
LiteLLM 统一调用适配层。

所有 LLM 请求通过此模块发起，业务代码不再直接拼接供应商端点。
该模块负责：
1. 依赖检测与启动前校验
2. 统一调用接口（模型、消息、温度、超时、重试、上下文）
3. 错误映射与日志标准化
4. request_id 透传与诊断字段记录
"""

from __future__ import annotations

import time
from typing import Any, AsyncGenerator, Dict, List, Optional

from loguru import logger

from config.logging import generate_request_id, get_request_id
from core.model_service import build_standard_error

# LiteLLM 依赖检测
_LITELLM_AVAILABLE = False
_LITELLM_IMPORT_ERROR: Optional[str] = None

try:
    import litellm
    # 关闭 litellm 内置的冗余日志，避免重复输出干扰主应用日志
    litellm.suppress_debug_info = True
    _LITELLM_AVAILABLE = True
except ImportError as exc:
    _LITELLM_IMPORT_ERROR = str(exc)


# LiteLLM 模型名前缀映射，用于将业务层 provider+model 转换为 LiteLLM 识别的格式
PROVIDER_MODEL_PREFIX_MAP: Dict[str, str] = {
    "openai": "openai/",
    "anthropic": "anthropic/",
    "deepseek": "deepseek/",
    "google": "gemini/",
    "alibaba": "openai/",
    "moonshot": "openai/",
    "zhipu": "openai/",
    "ollama": "ollama/",
}

# 供应商特定的 API base URL 键名映射
PROVIDER_API_BASE_KEY: Dict[str, str] = {
    "openai": "api_base",
    "anthropic": "api_base",
    "deepseek": "api_base",
    "google": "api_base",
    "alibaba": "api_base",
    "moonshot": "api_base",
    "zhipu": "api_base",
    "ollama": "api_base",
}

# LiteLLM HTTP 状态码到统一业务错误码的映射
STATUS_CODE_ERROR_MAP: Dict[int, str] = {
    400: "model_service_bad_request",
    401: "model_service_auth_error",
    403: "model_service_forbidden",
    404: "model_service_model_not_found",
    429: "model_service_rate_limit",
    500: "model_service_internal_error",
    502: "model_service_gateway_error",
    503: "model_service_unavailable",
    504: "model_service_timeout",
}

# 可重试的状态码集合
RETRYABLE_STATUS_CODES = {408, 409, 425, 429, 500, 502, 503, 504}


def check_litellm_available() -> None:
    """
    检查 LiteLLM 是否已安装。
    未安装时抛出明确异常，提示安装步骤。
    """
    if not _LITELLM_AVAILABLE:
        error_msg = (
            "LiteLLM 依赖未安装，无法发起模型请求。"
            "请执行 `pip install litellm` 安装后重启服务。"
        )
        if _LITELLM_IMPORT_ERROR:
            error_msg += f" 原始错误: {_LITELLM_IMPORT_ERROR}"
        raise RuntimeError(error_msg)


def is_litellm_available() -> bool:
    """返回 LiteLLM 是否可用的状态。"""
    return _LITELLM_AVAILABLE


def build_litellm_model_name(provider: str, model: str) -> str:
    """
    根据 provider 和 model 构造 LiteLLM 识别的模型全名。

    LiteLLM 使用 "provider/model" 格式来路由请求到正确的 API。
    如果模型名已包含前缀则不再重复添加。
    """
    normalized_provider = str(provider or "").strip().lower()
    normalized_model = str(model or "").strip()

    if not normalized_model:
        return ""

    prefix = PROVIDER_MODEL_PREFIX_MAP.get(normalized_provider, "openai/")

    # 如果模型名已包含 provider 前缀或 "/" 路径分隔符，则不重复添加
    if "/" in normalized_model:
        return normalized_model

    return f"{prefix}{normalized_model}"


def _build_litellm_optional_params(
    *,
    temperature: Optional[float] = None,
    top_p: Optional[float] = None,
    max_tokens: int = 8192,
    stream: bool = False,
) -> Dict[str, Any]:
    """
    构造 LiteLLM 调用的可选参数。
    仅在参数有值时传入，避免不支持的参数导致供应商报错。
    """
    params: Dict[str, Any] = {
        "max_tokens": max_tokens,
        "stream": stream,
    }
    if temperature is not None:
        params["temperature"] = temperature
    if top_p is not None:
        params["top_p"] = top_p
    return params


def _map_litellm_error(
    exc: Exception,
    *,
    provider: str = "",
    model: str = "",
    request_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    将 LiteLLM 异常映射为统一业务错误结构。
    """
    status_code = getattr(exc, "status_code", None)
    error_code = STATUS_CODE_ERROR_MAP.get(
        status_code, "model_service_unexpected_error"
    ) if status_code else "model_service_unexpected_error"

    # 判断是否可重试
    retryable = status_code in RETRYABLE_STATUS_CODES if status_code else False

    # 提取 LiteLLM 错误消息
    error_message = str(exc)
    if hasattr(exc, "message"):
        error_message = str(exc.message)

    # 对常见错误提供中文提示
    if status_code == 401:
        user_message = "模型服务认证失败，请检查 API Key 配置"
    elif status_code == 429:
        user_message = "模型服务请求频率超限，请稍后重试"
    elif status_code == 404:
        user_message = "指定的模型不存在或未启用"
    elif status_code in (502, 503, 504):
        user_message = "模型服务暂时不可用，请稍后重试"
    else:
        user_message = "模型服务请求失败"

    return build_standard_error(
        error_code,
        user_message,
        request_id=request_id,
        details={
            "provider": provider,
            "model": model,
            "status_code": status_code,
            "reason": error_message[:500],
        },
        retryable=retryable,
        status_code=status_code,
    )


async def litellm_chat_completion(
    *,
    provider: str,
    model: str,
    messages: List[Dict[str, Any]],
    api_key: str,
    api_base: Optional[str] = None,
    temperature: Optional[float] = None,
    top_p: Optional[float] = None,
    max_tokens: int = 8192,
    request_id: Optional[str] = None,
    timeout: float = 120.0,
    num_retries: int = 2,
) -> Dict[str, Any]:
    """
    通过 LiteLLM 发起非流式聊天补全请求。

    返回统一结构:
    {
        "ok": True/False,
        "response": "...",           # 模型回复文本
        "reasoning_content": "...",   # 推理内容（如有）
        "provider": "...",
        "model": "...",
        "request_id": "...",
        "usage": {...},               # token 用量
        "error": {...},               # 仅 ok=False 时
    }
    """
    check_litellm_available()

    resolved_request_id = str(request_id or get_request_id() or generate_request_id()).strip()
    litellm_model = build_litellm_model_name(provider, model)

    if not litellm_model:
        return {
            "ok": False,
            "error": build_standard_error(
                "llm_model_missing",
                "未配置可用的模型名称",
                request_id=resolved_request_id,
                details={"provider": provider, "model": model},
            ),
        }

    optional_params = _build_litellm_optional_params(
        temperature=temperature,
        top_p=top_p,
        max_tokens=max_tokens,
        stream=False,
    )

    # 构造 LiteLLM 调用参数
    call_kwargs: Dict[str, Any] = {
        "model": litellm_model,
        "messages": messages,
        "api_key": api_key,
        "timeout": timeout,
        "num_retries": num_retries,
        **optional_params,
    }

    if api_base:
        call_kwargs["api_base"] = api_base

    started_at = time.perf_counter()

    try:
        logger.bind(
            event="litellm_request",
            module="litellm_adapter",
            provider=provider,
            model=model,
            request_id=resolved_request_id,
        ).info(f"发起 LiteLLM 请求: provider={provider}, model={model}")

        response = await litellm.acompletion(**call_kwargs)
        duration_ms = int((time.perf_counter() - started_at) * 1000)

        # 提取响应文本
        response_text = ""
        reasoning_content = ""
        usage = None

        if hasattr(response, "choices") and response.choices:
            first_choice = response.choices[0]
            if hasattr(first_choice, "message") and first_choice.message:
                response_text = first_choice.message.content or ""
                # 提取推理内容（DeepSeek / OpenAI 兼容格式）
                if hasattr(first_choice.message, "reasoning_content"):
                    reasoning_content = first_choice.message.reasoning_content or ""

        if hasattr(response, "usage") and response.usage:
            usage = {
                "prompt_tokens": getattr(response.usage, "prompt_tokens", 0),
                "completion_tokens": getattr(response.usage, "completion_tokens", 0),
                "total_tokens": getattr(response.usage, "total_tokens", 0),
            }

        logger.bind(
            event="litellm_response",
            module="litellm_adapter",
            provider=provider,
            model=model,
            request_id=resolved_request_id,
            duration_ms=duration_ms,
            has_content=bool(response_text),
        ).info(f"LiteLLM 请求完成: duration={duration_ms}ms")

        if not response_text.strip():
            return {
                "ok": False,
                "error": build_standard_error(
                    "model_service_empty_response",
                    "模型服务返回空响应",
                    request_id=resolved_request_id,
                    details={"provider": provider, "model": model},
                    retryable=False,
                ),
            }

        return {
            "ok": True,
            "response": response_text,
            "reasoning_content": reasoning_content,
            "provider": provider,
            "model": model,
            "request_id": resolved_request_id,
            "usage": usage,
        }

    except Exception as exc:
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        logger.bind(
            event="litellm_error",
            module="litellm_adapter",
            provider=provider,
            model=model,
            request_id=resolved_request_id,
            error_type=type(exc).__name__,
            duration_ms=duration_ms,
        ).error(f"LiteLLM 请求失败: {type(exc).__name__}: {str(exc)[:300]}")

        return {
            "ok": False,
            "error": _map_litellm_error(
                exc,
                provider=provider,
                model=model,
                request_id=resolved_request_id,
            ),
        }


async def litellm_chat_completion_stream(
    *,
    provider: str,
    model: str,
    messages: List[Dict[str, Any]],
    api_key: str,
    api_base: Optional[str] = None,
    temperature: Optional[float] = None,
    top_p: Optional[float] = None,
    max_tokens: int = 8192,
    request_id: Optional[str] = None,
    timeout: float = 120.0,
    num_retries: int = 2,
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    通过 LiteLLM 发起流式聊天补全请求。

    Yield 统一结构:
    {"content": "...", "reasoning_content": "..."}
    或出错时:
    {"error": {...}}
    """
    check_litellm_available()

    resolved_request_id = str(request_id or get_request_id() or generate_request_id()).strip()
    litellm_model = build_litellm_model_name(provider, model)

    if not litellm_model:
        yield {
            "error": build_standard_error(
                "llm_model_missing",
                "未配置可用的模型名称",
                request_id=resolved_request_id,
                details={"provider": provider, "model": model},
            ),
        }
        return

    optional_params = _build_litellm_optional_params(
        temperature=temperature,
        top_p=top_p,
        max_tokens=max_tokens,
        stream=True,
    )

    call_kwargs: Dict[str, Any] = {
        "model": litellm_model,
        "messages": messages,
        "api_key": api_key,
        "timeout": timeout,
        "num_retries": num_retries,
        **optional_params,
    }

    if api_base:
        call_kwargs["api_base"] = api_base

    started_at = time.perf_counter()

    try:
        logger.bind(
            event="litellm_stream_request",
            module="litellm_adapter",
            provider=provider,
            model=model,
            request_id=resolved_request_id,
        ).info(f"发起 LiteLLM 流式请求: provider={provider}, model={model}")

        response = await litellm.acompletion(**call_kwargs)

        async for chunk in response:
            content = ""
            reasoning = ""

            if hasattr(chunk, "choices") and chunk.choices:
                delta = chunk.choices[0].delta
                if delta:
                    content = delta.content or ""
                    if hasattr(delta, "reasoning_content"):
                        reasoning = delta.reasoning_content or ""

            if content or reasoning:
                yield {"content": content, "reasoning_content": reasoning}

        duration_ms = int((time.perf_counter() - started_at) * 1000)
        logger.bind(
            event="litellm_stream_complete",
            module="litellm_adapter",
            provider=provider,
            model=model,
            request_id=resolved_request_id,
            duration_ms=duration_ms,
        ).info(f"LiteLLM 流式请求完成: duration={duration_ms}ms")

    except Exception as exc:
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        logger.bind(
            event="litellm_stream_error",
            module="litellm_adapter",
            provider=provider,
            model=model,
            request_id=resolved_request_id,
            error_type=type(exc).__name__,
            duration_ms=duration_ms,
        ).error(f"LiteLLM 流式请求失败: {type(exc).__name__}: {str(exc)[:300]}")

        yield {
            "error": _map_litellm_error(
                exc,
                provider=provider,
                model=model,
                request_id=resolved_request_id,
            ),
        }


async def litellm_list_models(
    *,
    provider: str,
    api_key: str,
    api_base: Optional[str] = None,
    request_id: Optional[str] = None,
    timeout: float = 20.0,
) -> Dict[str, Any]:
    """
    通过 LiteLLM 获取供应商的可用模型列表。

    对于 Ollama 等本地服务，直接调用其 API 接口。
    对于远程供应商，尝试使用 LiteLLM 的模型列表能力。
    """
    check_litellm_available()

    resolved_request_id = str(request_id or generate_request_id()).strip()
    normalized_provider = str(provider or "").strip().lower()

    # Ollama 模型发现走专用路径
    if normalized_provider == "ollama":
        return await _discover_ollama_models_via_litellm(api_base, resolved_request_id)

    try:
        import httpx
        from billing.pricing_manager import PricingManager

        # 构建请求头和端点
        headers: Dict[str, str] = {"Content-Type": "application/json"}
        endpoint = str(api_base or "").rstrip("/")

        if normalized_provider == "anthropic":
            headers["x-api-key"] = api_key
            headers["anthropic-version"] = "2023-06-01"
            if not endpoint:
                endpoint = "https://api.anthropic.com"
            # 使用 PricingManager 统一构建模型列表端点
            endpoint = PricingManager.build_provider_api_endpoint(normalized_provider, endpoint, "models")
        elif normalized_provider == "google":
            if not endpoint:
                endpoint = "https://generativelanguage.googleapis.com/v1beta"
            endpoint = PricingManager.build_provider_api_endpoint(normalized_provider, endpoint, "models")
            # Google API 需要通过查询参数传递 API Key
            separator = "&" if "?" in endpoint else "?"
            endpoint = f"{endpoint}{separator}key={api_key}"
        else:
            headers["Authorization"] = f"Bearer {api_key}"
            if not endpoint:
                endpoint = "https://api.openai.com/v1"
            # 使用 PricingManager 统一构建模型列表端点
            endpoint = PricingManager.build_provider_api_endpoint(normalized_provider, endpoint, "models")

        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(endpoint, headers=headers)
            resp.raise_for_status()
            payload = resp.json()

        # 从响应中提取模型列表
        models: list = []
        if isinstance(payload, dict):
            data = payload.get("data") or payload.get("models") or []
            if isinstance(data, list):
                models = data

        return {
            "ok": True,
            "models": models,
            "provider": normalized_provider,
            "request_id": resolved_request_id,
        }

    except Exception as exc:
        logger.bind(
            event="litellm_list_models_error",
            module="litellm_adapter",
            provider=normalized_provider,
            request_id=resolved_request_id,
            error_type=type(exc).__name__,
        ).error(f"模型列表拉取失败: {exc}")
        return {
            "ok": False,
            "error": _map_litellm_error(
                exc,
                provider=normalized_provider,
                request_id=resolved_request_id,
            ),
        }


async def _discover_ollama_models_via_litellm(
    api_base: Optional[str],
    request_id: str,
) -> Dict[str, Any]:
    """
    通过 Ollama API 发现本地可用模型。
    当 Ollama 服务不可用时返回空列表，不抛异常。
    """
    from config.settings import settings

    base_url = str(api_base or settings.OLLAMA_BASE_URL or "http://localhost:11434").rstrip("/")
    endpoint = f"{base_url}/api/tags"

    try:
        import httpx

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(endpoint)
            response.raise_for_status()
            data = response.json()

        raw_models = data.get("models", [])
        result = []
        for m in raw_models:
            if not isinstance(m, dict):
                continue
            result.append({
                "name": m.get("name", ""),
                "size": m.get("size", 0),
                "modified_at": m.get("modified_at", ""),
                "digest": m.get("digest", ""),
            })
        return {
            "ok": True,
            "models": result,
            "provider": "ollama",
            "request_id": request_id,
        }
    except Exception:
        return {
            "ok": True,
            "models": [],
            "provider": "ollama",
            "request_id": request_id,
        }


async def litellm_check_provider_connection(
    *,
    provider: str,
    api_base: str,
    api_key: str = "",
) -> Dict[str, Any]:
    """
    检测指定模型提供商的连接状态。
    通过向其模型端点发送请求来判断是否可达。
    """
    normalized = str(provider or "").strip().lower()

    try:
        result = await litellm_list_models(
            provider=normalized,
            api_key=api_key,
            api_base=api_base,
            timeout=10.0,
        )
        if result.get("ok"):
            return {"provider": provider, "status": "connected", "message": "连接正常"}
        else:
            error = result.get("error", {})
            status_code = error.get("status_code")
            if status_code == 401:
                return {"provider": provider, "status": "auth_error", "message": "认证失败，请检查 API Key"}
            return {"provider": provider, "status": "error", "message": error.get("message", "连接失败")}
    except Exception as exc:
        error_msg = str(exc)
        if "timeout" in error_msg.lower():
            return {"provider": provider, "status": "timeout", "message": "连接超时"}
        return {"provider": provider, "status": "unreachable", "message": error_msg}
