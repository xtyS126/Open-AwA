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
    serialized_context = context or {}

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
                "client_version": headers[CLIENT_VERSION_HEADER],
                "context": serialized_context,
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
            google_gen_config["topK"] = round(top_k * 40)
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
        "metadata": {
            "request_id": headers[REQUEST_ID_HEADER],
            "client_version": headers[CLIENT_VERSION_HEADER],
            "context": serialized_context,
        },
    }
    if temperature is not None:
        openai_payload["temperature"] = temperature
    if top_k is not None:
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
            async with httpx.AsyncClient(timeout=spec.timeout) as client:
                if spec.method.upper() == "GET":
                    response = await client.get(spec.endpoint, headers=spec.headers)
                else:
                    response = await client.post(spec.endpoint, json=spec.payload, headers=spec.headers)
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


from typing import AsyncGenerator

async def send_stream_with_retries(
    spec: ProviderRequestSpec,
    *,
    attempts: int = DEFAULT_RETRY_ATTEMPTS,
    backoff_seconds: float = DEFAULT_RETRY_BACKOFF_SECONDS,
) -> AsyncGenerator[str, None]:
    """
    统一封装流式请求重试逻辑，生成 SSE 数据流。
    """
    last_error: Optional[Exception] = None
    total_attempts = max(1, int(attempts))

    for attempt in range(1, total_attempts + 1):
        try:
            # Note: We need a persistent client across the stream iteration. 
            # So we yield from the client stream context directly.
            # Retries only apply if connection fails before yielding data.
            client = httpx.AsyncClient(timeout=spec.timeout)
            req = client.build_request(spec.method, spec.endpoint, json=spec.payload, headers=spec.headers)
            response = await client.send(req, stream=True)
            response.raise_for_status()

            async def stream_generator():
                try:
                    async for line in response.aiter_lines():
                        if line:
                            yield line
                finally:
                    await response.aclose()
                    await client.aclose()
            
            return stream_generator()

        except Exception as exc:
            last_error = exc
            if attempt >= total_attempts or not is_retryable_exception(exc):
                raise
            await asyncio.sleep(backoff_seconds * (2 ** (attempt - 1)))

    if last_error is not None:
        raise last_error
    raise RuntimeError("Model service stream request failed without explicit error")
