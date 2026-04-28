"""
模型服务协议适配模块，负责统一处理不同 Provider 的端点、请求头、载荷、
标准错误对象、版本协商以及基础重试逻辑。
"""

from __future__ import annotations

from dataclasses import dataclass
import asyncio
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlencode

import httpx

from billing.pricing_manager import PricingManager
from config.logging import REQUEST_ID_HEADER, generate_request_id
from config.settings import settings


CLIENT_VERSION_HEADER = "X-Client-Ver"
SERVER_VERSION_HEADER = "X-Server-Ver"
VERSION_STATUS_HEADER = "X-Version-Status"

ANTHROPIC_VERSION_HEADER = "anthropic-version"
DEFAULT_ANTHROPIC_VERSION = "2023-06-01"

DEFAULT_RETRY_ATTEMPTS = 3
DEFAULT_RETRY_BACKOFF_SECONDS = 0.2
RETRYABLE_STATUS_CODES = {408, 409, 425, 429, 500, 502, 503, 504}

# 全局共享的异步 HTTP 客户端，复用连接池以减少 TLS 握手和连接建立开销
_shared_client: Optional[httpx.AsyncClient] = None


def get_shared_client() -> httpx.AsyncClient:
    """
    获取全局共享的异步 HTTP 客户端实例。
    在应用生命周期内复用同一个连接池。
    """
    global _shared_client
    if _shared_client is None or _shared_client.is_closed:
        _shared_client = httpx.AsyncClient(
            timeout=httpx.Timeout(60.0, connect=10.0),
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
        )
    return _shared_client


async def close_shared_client() -> None:
    """
    关闭全局共享的 HTTP 客户端，通常在应用关闭时调用。
    """
    global _shared_client
    if _shared_client is not None and not _shared_client.is_closed:
        await _shared_client.aclose()
        _shared_client = None

# Google Gemini API topK range is 1-40 (integer). We map from normalized 0.0-1.0 float.
# See: https://ai.google.dev/api/rest/v1beta/GenerationConfig
GOOGLE_TOPK_MAX = 40


@dataclass
class ProviderRequestSpec:
    """
    描述一次发往模型服务的标准化请求。
    """

    endpoint: str
    headers: Dict[str, str]
    payload: Optional[Dict[str, Any]]
    timeout: float = 120.0
    method: str = "POST"
    query_params: Optional[Dict[str, Any]] = None


def _parse_version_tuple(version: Optional[str]) -> Tuple[int, int, int]:
    """
    将版本号解析为三段整数，无法识别时回退为 0.0.0，
    这样可以在不中断请求的情况下做宽松兼容判断。
    """

    raw = str(version or "").strip().lstrip("vV")
    if not raw:
        return (0, 0, 0)

    parts = raw.split(".")
    normalized = []
    for part in parts[:3]:
        digits = "".join(ch for ch in part if ch.isdigit())
        normalized.append(int(digits or "0"))

    while len(normalized) < 3:
        normalized.append(0)

    return tuple(normalized[:3])


def negotiate_version_status(
    client_version: Optional[str],
    server_version: Optional[str] = None,
) -> str:
    """
    根据客户端与服务端版本返回一个简单的协商结果。
    当前策略优先比较主版本，主版本一致视为兼容。
    """

    server = str(server_version or settings.VERSION).strip() or settings.VERSION
    client = str(client_version or "").strip()
    if not client:
        return "server_only"

    client_major, client_minor, _ = _parse_version_tuple(client)
    server_major, server_minor, _ = _parse_version_tuple(server)

    if client_major == 0 or server_major == 0:
        return "compatible"
    if client_major != server_major:
        return "upgrade_required"
    if client_minor < server_minor:
        return "upgrade_recommended"
    return "compatible"


def build_standard_error(
    code: str,
    message: str,
    *,
    request_id: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
    retryable: bool = False,
    status_code: Optional[int] = None,
) -> Dict[str, Any]:
    """
    统一标准错误对象结构，便于前端和日志系统稳定解析。
    """

    error: Dict[str, Any] = {
        "code": str(code or "unknown_error"),
        "message": str(message or "Unknown error"),
        "request_id": str(request_id or generate_request_id()),
        "retryable": bool(retryable),
        "details": details or {},
    }
    if status_code is not None:
        error["status_code"] = int(status_code)
    return error


def _build_common_headers(
    *,
    request_id: Optional[str],
    client_version: Optional[str],
) -> Dict[str, str]:
    """
    为所有上游模型请求补齐链路追踪和版本协商相关头信息。
    """

    resolved_request_id = str(request_id or generate_request_id()).strip() or generate_request_id()
    resolved_client_version = str(client_version or settings.VERSION).strip() or settings.VERSION
    return {
        "Content-Type": "application/json",
        REQUEST_ID_HEADER: resolved_request_id,
        CLIENT_VERSION_HEADER: resolved_client_version,
    }


def _append_query(endpoint: str, params: Optional[Dict[str, Any]]) -> str:
    """
    仅在存在查询参数时拼接 URL，避免出现多余的问号。
    """

    if not params:
        return endpoint
    return f"{endpoint}?{urlencode(params, doseq=True)}"


def _build_google_chat_endpoint(base_endpoint: str, model: str) -> str:
    """
    Google Generative Language API 的聊天接口要求模型名出现在路径中。
    """

    normalized_model = str(model or "").strip()
    if not normalized_model:
        raise ValueError("Google provider requires model for chat request")
    return f"{base_endpoint.rstrip('/')}/{normalized_model}:generateContent"


def build_provider_request(
    *,
    provider: str,
    api_endpoint: str,
    api_key: str,
    purpose: str,
    model: Optional[str] = None,
    prompt: str = "",
    max_tokens: int = 1000,
    temperature: Optional[float] = None,
    top_k: Optional[float] = None,
    top_p: Optional[float] = None,
    request_id: Optional[str] = None,
    client_version: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
    stream: bool = False,
) -> ProviderRequestSpec:
    """
    按 Provider 组装端点、请求头和载荷，避免不同模型服务共用错误协议。
    """

    provider_id = PricingManager.normalize_provider(provider)
    base_endpoint = PricingManager.build_provider_api_endpoint(provider_id, api_endpoint, purpose)
    if not base_endpoint:
        raise ValueError(f"Provider endpoint is missing for provider '{provider_id}'")

    headers = _build_common_headers(request_id=request_id, client_version=client_version)

    if provider_id == "anthropic":
        headers["x-api-key"] = api_key
        headers[ANTHROPIC_VERSION_HEADER] = DEFAULT_ANTHROPIC_VERSION
        if purpose == "models":
            return ProviderRequestSpec(endpoint=base_endpoint, headers=headers, payload=None, method="GET", timeout=20.0)
        anthropic_payload: Dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
            "stream": stream,
            "metadata": {
                "request_id": headers[REQUEST_ID_HEADER],
            },
        }
        if temperature is not None:
            anthropic_payload["temperature"] = temperature
        if top_k is not None:
            anthropic_payload["top_k"] = top_k
        return ProviderRequestSpec(
            endpoint=base_endpoint,
            headers=headers,
            payload=anthropic_payload,
        )

    if provider_id == "google":
        if purpose == "models":
            return ProviderRequestSpec(
                endpoint=_append_query(base_endpoint, {"key": api_key}),
                headers=headers,
                payload=None,
                method="GET",
                timeout=20.0,
            )
        google_gen_config: Dict[str, Any] = {
            "maxOutputTokens": max_tokens,
        }
        if temperature is not None:
            google_gen_config["temperature"] = temperature
        if top_k is not None:
            google_gen_config["topK"] = round(top_k * GOOGLE_TOPK_MAX)
        if top_p is not None:
            google_gen_config["topP"] = top_p
        return ProviderRequestSpec(
            endpoint=_append_query(_build_google_chat_endpoint(base_endpoint, str(model or "")), {"key": api_key}),
            headers=headers,
            payload={
                "contents": [
                    {
                        "role": "user",
                        "parts": [{"text": prompt}],
                    }
                ],
                "generationConfig": google_gen_config,
                "systemInstruction": {
                    "parts": [
                        {
                            "text": (
                                f"request_id={headers[REQUEST_ID_HEADER]};"
                                f"client_version={headers[CLIENT_VERSION_HEADER]}"
                            )
                        }
                    ]
                },
            },
        )

    headers["Authorization"] = f"Bearer {api_key}"

    # Ollama 本地模型无需鉴权，跳过 Authorization 头
    if provider_id == "ollama":
        headers.pop("Authorization", None)

    if purpose == "models":
        return ProviderRequestSpec(endpoint=base_endpoint, headers=headers, payload=None, method="GET", timeout=20.0)

    openai_payload: Dict[str, Any] = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": prompt,
            }
        ],
        "max_tokens": max_tokens,
        "stream": stream,
    }
    if temperature is not None:
        openai_payload["temperature"] = temperature
    # top_p takes precedence over top_k when both are provided,
    # since top_k is mapped to top_p for OpenAI-compatible providers.
    if top_k is not None and top_p is None:
        openai_payload["top_p"] = top_k
    if top_p is not None:
        openai_payload["top_p"] = top_p

    return ProviderRequestSpec(
        endpoint=base_endpoint,
        headers=headers,
        payload=openai_payload,
    )


def is_retryable_exception(exc: Exception) -> bool:
    """
    判断异常是否适合重试。
    """

    if isinstance(exc, httpx.TimeoutException):
        return True
    if isinstance(exc, httpx.NetworkError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in RETRYABLE_STATUS_CODES
    return False


async def send_with_retries(
    spec: ProviderRequestSpec,
    *,
    attempts: int = DEFAULT_RETRY_ATTEMPTS,
    backoff_seconds: float = DEFAULT_RETRY_BACKOFF_SECONDS,
) -> httpx.Response:
    """
    统一封装请求重试逻辑，仅对显式可重试的状态或网络故障执行指数退避。
    """

    last_error: Optional[Exception] = None
    total_attempts = max(1, int(attempts))

    for attempt in range(1, total_attempts + 1):
        try:
            client = get_shared_client()
            if spec.method.upper() == "GET":
                response = await client.get(spec.endpoint, headers=spec.headers, timeout=spec.timeout)
            else:
                response = await client.post(spec.endpoint, json=spec.payload, headers=spec.headers, timeout=spec.timeout)
            response.raise_for_status()
            return response
        except Exception as exc:  # noqa: BLE001 - 这里需要统一兜底判断是否可重试
            last_error = exc
            if attempt >= total_attempts or not is_retryable_exception(exc):
                raise
            await asyncio.sleep(backoff_seconds * (2 ** (attempt - 1)))

    if last_error is not None:
        raise last_error
    raise RuntimeError("Model service request failed without explicit error")


def build_thinking_params(provider: str, model: str, thinking_depth: int) -> Dict[str, Any]:
    """
    根据厂商和模型映射思考深度到具体的 API 参数字典。
    深度 0-5 映射策略：
    - OpenAI o 系列: reasoning_effort（0-1→low, 2-3→medium, 4-5→high）
    - Anthropic: thinking.type=enabled + budget_tokens（深度×4000）
    - DeepSeek R1/Reasoner: thinking.type=enabled（无分档深度）
    - Zhipu GLM: thinking.type=enabled
    - 其他模型返回空字典
    """
    from billing.pricing_manager import PricingManager

    normalized = PricingManager.normalize_provider(provider)
    if not model or thinking_depth < 1:
        return {}

    model_lower = model.lower()

    # OpenAI o 系列推理模型
    if normalized in ("openai",) and any(
        model_lower.startswith(prefix) for prefix in ("o1", "o3", "o4")
    ):
        if thinking_depth <= 1:
            effort = "low"
        elif thinking_depth <= 3:
            effort = "medium"
        else:
            effort = "high"
        return {"reasoning_effort": effort}

    # Anthropic 扩展思考
    if normalized == "anthropic":
        budget_tokens = thinking_depth * 4000
        return {"thinking": {"type": "enabled", "budget_tokens": budget_tokens}}

    # DeepSeek 推理模型
    if normalized == "deepseek" and model_lower in ("deepseek-reasoner", "deepseek-r1"):
        return {"thinking": {"type": "enabled"}}

    # Zhipu GLM 推理模型
    if normalized == "zhipu" and "glm" in model_lower:
        return {"thinking": {"type": "enabled"}}

    return {}


def build_multimodal_message(
    text: str,
    attachments: Optional[List[Dict[str, Any]]] = None,
    provider: str = "",
) -> Union[str, List[Dict[str, Any]]]:
    """
    根据 provider 将文本和附件构建为多模态消息格式。
    无附件时返回纯文本字符串以保证向后兼容。
    """
    from billing.pricing_manager import PricingManager

    if not attachments:
        return text

    normalized = PricingManager.normalize_provider(provider)

    if normalized == "anthropic":
        # Anthropic content blocks 格式
        content_blocks: List[Dict[str, Any]] = []
        if text:
            content_blocks.append({"type": "text", "text": text})
        for att in attachments:
            att_type = att.get("type", "")
            mime = att.get("mime_type", "")
            data = att.get("data", "")
            if att_type == "image":
                content_blocks.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": mime,
                        "data": data,
                    },
                })
            elif att_type == "audio":
                content_blocks.append({
                    "type": "audio",
                    "source": {
                        "type": "base64",
                        "media_type": mime,
                        "data": data,
                    },
                })
            elif att_type == "video":
                content_blocks.append({
                    "type": "video",
                    "source": {
                        "type": "base64",
                        "media_type": mime,
                        "data": data,
                    },
                })
        return content_blocks

    if normalized == "google":
        # Google Gemini parts 格式
        parts: List[Dict[str, Any]] = []
        if text:
            parts.append({"text": text})
        for att in attachments:
            att_type = att.get("type", "")
            mime = att.get("mime_type", "")
            data = att.get("data", "")
            if att_type == "image":
                parts.append({"inline_data": {"mime_type": mime, "data": data}})
            elif att_type == "audio":
                parts.append({"inline_data": {"mime_type": mime, "data": data}})
            elif att_type == "video":
                parts.append({"inline_data": {"mime_type": mime, "data": data}})
        return parts

    # OpenAI 兼容格式（OpenAI / DeepSeek / Alibaba / Moonshot / Zhipu）
    content_parts: List[Dict[str, Any]] = []
    if text:
        content_parts.append({"type": "text", "text": text})
    for att in attachments:
        att_type = att.get("type", "")
        mime = att.get("mime_type", "")
        data = att.get("data", "")
        if att_type == "image":
            content_parts.append({
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{data}"},
            })
        elif att_type == "audio":
            content_parts.append({
                "type": "audio_url",
                "audio_url": {"url": f"data:{mime};base64,{data}"},
            })
        elif att_type == "video":
            content_parts.append({
                "type": "video_url",
                "video_url": {"url": f"data:{mime};base64,{data}"},
            })
    return content_parts


def extract_reasoning_content(response_data: Dict[str, Any], provider: str = "") -> str:
    """
    从模型非流式响应中提取推理内容（思维链）。
    不同 Provider 的响应格式不同，需分别处理：
    - OpenAI/DeepSeek: choices[0].message.reasoning_content
    - Anthropic: content blocks 中 type 为 "thinking" 的 block
    """
    # OpenAI / DeepSeek 兼容格式
    choices = response_data.get("choices")
    if isinstance(choices, list) and choices:
        first_choice = choices[0]
        if isinstance(first_choice, dict):
            message = first_choice.get("message")
            if isinstance(message, dict):
                reasoning = message.get("reasoning_content")
                if isinstance(reasoning, str) and reasoning:
                    return reasoning

    # Anthropic 格式：content 列表中 type 为 "thinking" 的 block
    content = response_data.get("content")
    if isinstance(content, list):
        thinking_parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "thinking":
                text = block.get("thinking", "")
                if isinstance(text, str) and text:
                    thinking_parts.append(text)
        if thinking_parts:
            return "\n".join(thinking_parts)

    return ""


from typing import AsyncGenerator

async def send_stream_with_retries(
    spec: ProviderRequestSpec,
    *,
    attempts: int = DEFAULT_RETRY_ATTEMPTS,
    backoff_seconds: float = DEFAULT_RETRY_BACKOFF_SECONDS,
) -> AsyncGenerator[str, None]:
    """
    统一封装流式请求重试逻辑，生成 SSE 数据流。
    使用共享 client 避免重复创建连接；通过 async with 上下文管理器确保资源正确释放。
    """
    last_error: Optional[Exception] = None
    total_attempts = max(1, int(attempts))

    for attempt in range(1, total_attempts + 1):
        try:
            # 复用共享 client 而非每次创建新实例，与 send_with_retries 保持一致
            client = get_shared_client()
            req = client.build_request(spec.method, spec.endpoint, json=spec.payload, headers=spec.headers)
            response = await client.send(req, stream=True)
            response.raise_for_status()

            async def stream_generator(resp=response):
                """在 generator 自然结束或被提前放弃时确保响应正确关闭。"""
                try:
                    async for line in resp.aiter_lines():
                        if line:
                            yield line
                finally:
                    # 确保无论 generator 是否被完全消费，底层 HTTP 响应都能被正确释放
                    await resp.aclose()
            
            return stream_generator()

        except Exception as exc:
            last_error = exc
            if attempt >= total_attempts or not is_retryable_exception(exc):
                raise
            await asyncio.sleep(backoff_seconds * (2 ** (attempt - 1)))

    if last_error is not None:
        raise last_error
    raise RuntimeError("Model service stream request failed without explicit error")


async def discover_ollama_models() -> list[dict]:
    """
    从本地 Ollama 服务发现可用模型。
    调用 Ollama 的 /api/tags 接口获取已拉取的模型列表。
    当 Ollama 服务不可用时返回空列表，不抛异常。
    """
    from config.settings import settings as app_settings

    base_url = (app_settings.OLLAMA_BASE_URL or "http://localhost:11434").rstrip("/")
    endpoint = f"{base_url}/api/tags"

    try:
        client = get_shared_client()
        response = await client.get(endpoint, timeout=10.0)
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
        return result
    except Exception:
        # Ollama 服务不可达时静默返回空列表
        return []


async def get_provider_connection_status(provider_id: str, base_url: str, api_key: str = "") -> dict:
    """
    检测指定模型提供商的连接状态。
    通过向其 models 端点发送请求来判断是否可达。
    """
    from billing.pricing_manager import PricingManager

    normalized = PricingManager.normalize_provider(provider_id)
    endpoint = PricingManager.build_provider_api_endpoint(normalized, base_url, "models")
    if not endpoint:
        return {"provider": provider_id, "status": "unconfigured", "message": "未配置端点"}

    headers = {"Content-Type": "application/json"}

    # 根据 provider 类型设置鉴权头
    if normalized == "anthropic":
        if api_key:
            headers["x-api-key"] = api_key
            headers[ANTHROPIC_VERSION_HEADER] = DEFAULT_ANTHROPIC_VERSION
    elif normalized == "google":
        if api_key:
            endpoint = _append_query(endpoint, {"key": api_key})
    elif normalized == "ollama":
        pass  # Ollama 不需要鉴权
    else:
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

    try:
        client = get_shared_client()
        response = await client.get(endpoint, headers=headers, timeout=10.0)
        if response.status_code == 200:
            return {"provider": provider_id, "status": "connected", "message": "连接正常"}
        elif response.status_code == 401:
            return {"provider": provider_id, "status": "auth_error", "message": "认证失败，请检查 API Key"}
        else:
            return {"provider": provider_id, "status": "error", "message": f"HTTP {response.status_code}"}
    except httpx.TimeoutException:
        return {"provider": provider_id, "status": "timeout", "message": "连接超时"}
    except Exception as exc:
        return {"provider": provider_id, "status": "unreachable", "message": str(exc)}
