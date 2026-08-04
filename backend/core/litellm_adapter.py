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

import asyncio
import os
import random
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple, Union

from loguru import logger

from config.logging import generate_request_id, get_request_id

# 默认使用 LiteLLM 随包价格表，避免离线环境启动时请求 GitHub 并等待 DNS 超时。
# 显式环境变量仍可覆盖该默认值，以便需要远程更新价格表的部署自行启用。
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

# LiteLLM 依赖检测
_LITELLM_AVAILABLE = False
_LITELLM_IMPORT_ERROR: Optional[str] = None

try:
    import litellm
    # 关闭 litellm 内置的冗余日志，避免重复输出干扰主应用日志
    litellm.suppress_debug_info = True
    # 允许透传 LiteLLM 不认识的参数到供应商 API，避免自定义兼容端点因参数校验而被拒绝
    litellm.drop_params = True
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

# 熔断器默认配置
_CIRCUIT_BREAKER_FAILURE_THRESHOLD = 5  # 连续失败阈值
_CIRCUIT_BREAKER_RECOVERY_TIMEOUT = 60  # 熔断恢复等待时间（秒）
_CIRCUIT_BREAKER_HALF_OPEN_MAX_REQUESTS = 1  # 半开状态最大请求数


# ==================== 通用工具函数（迁移自 core/model_service.py） ====================
# 以下常量与函数原属 model_service.py，现统一收归至 litellm_adapter 作为唯一 LLM 入口的一部分。

# 客户端/服务端版本协商请求头
CLIENT_VERSION_HEADER = "X-Client-Ver"
SERVER_VERSION_HEADER = "X-Server-Ver"
VERSION_STATUS_HEADER = "X-Version-Status"

# Anthropic API 版本协商头
ANTHROPIC_VERSION_HEADER = "anthropic-version"
DEFAULT_ANTHROPIC_VERSION = "2023-06-01"

# Google Gemini API topK 取值上限（整数），用于把归一化的 0.0-1.0 浮点映射回原始区间
GOOGLE_TOPK_MAX = 40

# 全局共享的异步 HTTP 客户端，复用连接池以减少 TLS 握手与连接建立开销
# 主要供非 LLM 路径（如 webhook 回调、健康检查）复用，LLM 调用走 litellm 自有客户端
_shared_client: Optional["httpx.AsyncClient"] = None


def build_standard_error(
    code: str,
    message: str,
    *,
    request_id: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
    retryable: Optional[bool] = None,
    status_code: Optional[int] = None,
) -> Dict[str, Any]:
    """
    统一标准错误对象结构，便于前端和日志系统稳定解析。

    retryable 与 status_code 未显式传入时，根据 code 从 error_codes.REGISTRY
    解析默认值，避免调用方重复指定。显式传值优先级最高。
    """
    # 延迟导入避免循环依赖
    from core.error_codes import resolve_defaults

    defaults = resolve_defaults(code, retryable=retryable, status_code=status_code)
    error: Dict[str, Any] = {
        "code": str(code or "unknown_error"),
        "message": str(message or "Unknown error"),
        "request_id": str(request_id or generate_request_id()),
        "retryable": bool(defaults.get("retryable", False)),
        "details": details or {},
    }
    if "status_code" in defaults:
        error["status_code"] = int(defaults["status_code"])
    return error


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

    return tuple(normalized[:3])  # type: ignore[return-value]


def negotiate_version_status(
    client_version: Optional[str],
    server_version: Optional[str] = None,
) -> str:
    """
    根据客户端与服务端版本返回一个简单的协商结果。
    当前策略优先比较主版本，主版本一致视为兼容。
    """
    # 延迟导入避免循环依赖
    from config.settings import settings

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


def get_shared_client() -> "httpx.AsyncClient":
    """
    获取全局共享的异步 HTTP 客户端实例。
    在应用生命周期内复用同一个连接池。
    """
    global _shared_client
    if _shared_client is None or _shared_client.is_closed:
        import httpx
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


# ==================== 多模态与思考参数工具（迁移自 llm/utils.py） ====================


def build_thinking_params(
    provider: str,
    model: str,
    thinking_depth: int,
    thinking_enabled: Optional[bool] = None,
) -> Dict[str, Any]:
    """
    根据厂商和模型映射思考深度到具体的 API 参数字典。
    深度 0-5 映射策略：
    - OpenAI (o1/o3/o4/gpt-5): reasoning_effort（0-1->low, 2-3->medium, 4-5->high）
    - Anthropic (Claude 4.6/4.7): thinking.type=adaptive + output_config.effort（low/medium/high/xhigh/max）
    - Anthropic (Claude旧版): thinking.type=enabled + budget_tokens（深度*4000，最低1024）
    - DeepSeek (V4/R1): extra_body.thinking.type=enabled/disabled + reasoning_effort（high/max）
    - Gemini (2.5/3.0): reasoning_effort（none/low/medium/high）
    - Zhipu GLM: thinking.type=enabled/disabled
    - Aliyun Qwen/QwQ: extra_body={"enable_thinking": True/False}
    - 其他模型返回空字典
    """
    from billing.pricing_manager import PricingManager

    # 兼容 thinking_depth 未传入或为 None 的情况，避免 None < int 比较失败
    if thinking_depth is None:
        thinking_depth = 0

    normalized = PricingManager.normalize_provider(provider)
    if not model:
        return {}

    model_lower = model.lower()

    # 处理明确关闭思考的情况
    if thinking_enabled is False:
        if normalized == "deepseek" or "deepseek" in model_lower:
            # V4 系列不支持 thinking 参数，关闭思考时需用 reasoning_effort
            if any(v4_prefix in model_lower for v4_prefix in ("deepseek-v4", "deepseek_v4")):
                return {"extra_body": {"reasoning_effort": "none"}}
            return {"extra_body": {"thinking": {"type": "disabled"}}}
        if normalized == "google" or "gemini" in model_lower:
            return {"reasoning_effort": "none"}
        if normalized == "zhipu" and "glm" in model_lower:
            return {"thinking": {"type": "disabled"}}
        if normalized == "aliyun" or "qwen" in model_lower or "qwq" in model_lower:
            return {"extra_body": {"enable_thinking": False}}
        return {}

    # 如果没有开启思考，且 depth < 1，返回空
    if thinking_depth < 1 and thinking_enabled is not True:
        return {}

    # OpenAI (o系列/gpt-5)
    if normalized in ("openai",) and any(
        model_lower.startswith(prefix) for prefix in ("o1", "o3", "o4", "gpt-5")
    ):
        if thinking_depth <= 1:
            effort = "low"
        elif thinking_depth <= 3:
            effort = "medium"
        else:
            effort = "high"
        return {"reasoning_effort": effort}

    # Anthropic (Claude)
    if normalized == "anthropic":
        # 新版 Claude 4.6/4.7 系列使用 Adaptive thinking
        if any(v in model_lower for v in ("claude-opus-4-6", "claude-sonnet-4-6", "claude-opus-4-7")):
            if thinking_depth <= 1:
                effort = "low"
            elif thinking_depth == 2:
                effort = "medium"
            elif thinking_depth == 3:
                effort = "high"
            elif thinking_depth == 4:
                effort = "xhigh"
            else:
                effort = "max"
            return {"thinking": {"type": "adaptive"}, "output_config": {"effort": effort}}
        else:
            # 旧版使用 budget_tokens
            budget_tokens = max(1024, thinking_depth * 4000 if thinking_depth > 0 else 4000)
            return {"thinking": {"type": "enabled", "budget_tokens": budget_tokens}}

    # DeepSeek 推理模型
    if normalized == "deepseek" or "deepseek" in model_lower:
        if thinking_depth <= 3:
            effort = "high"
        else:
            effort = "max"
        # V4 系列模型：仅支持 reasoning_effort，不支持 thinking 参数（thinking 为 R1 独有）
        if any(v4_prefix in model_lower for v4_prefix in ("deepseek-v4", "deepseek_v4")):
            return {"extra_body": {"reasoning_effort": effort}}
        # R1/旧版推理模型：同时需要 thinking 和 reasoning_effort
        return {
            "extra_body": {
                "thinking": {"type": "enabled"},
                "reasoning_effort": effort,
            }
        }

    # Gemini (2.5/3.0)
    if normalized == "google" or "gemini" in model_lower:
        if thinking_depth <= 1:
            effort = "low"
        elif thinking_depth <= 3:
            effort = "medium"
        else:
            effort = "high"
        return {"reasoning_effort": effort}

    # Zhipu GLM 推理模型
    if normalized == "zhipu" and "glm" in model_lower:
        return {"thinking": {"type": "enabled"}}

    # 阿里云 Qwen/QwQ 推理模型
    if normalized == "aliyun" or "qwen" in model_lower or "qwq" in model_lower:
        return {"extra_body": {"enable_thinking": True}}

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


def normalize_provider_name(provider: str) -> str:
    """
    标准化 Provider 名称。
    将各种别名统一为规范名称。

    Args:
        provider: 原始 Provider 名称

    Returns:
        str: 标准化后的名称
    """
    provider = provider.lower().strip()

    # 别名映射
    aliases = {
        "anthropic": "claude",
        "google": "gemini",
        "deepseek": "openai",  # DeepSeek 兼容 OpenAI 格式
        "azure": "openai",
    }

    return aliases.get(provider, provider)


class CircuitBreakerState:
    """熔断器状态枚举。"""
    CLOSED = "closed"       # 正常状态
    OPEN = "open"           # 熔断状态
    HALF_OPEN = "half_open" # 半开状态（试探性恢复）


class CircuitBreaker:
    """
    简单的每供应商熔断器。
    
    当连续失败达到阈值时打开电路，阻止后续请求；
    经过恢复时间后进入半开状态，允许少量试探请求；
    试探成功则关闭电路，失败则继续保持熔断。
    """

    def __init__(
        self,
        failure_threshold: int = _CIRCUIT_BREAKER_FAILURE_THRESHOLD,
        recovery_timeout: float = _CIRCUIT_BREAKER_RECOVERY_TIMEOUT,
        half_open_max_requests: int = _CIRCUIT_BREAKER_HALF_OPEN_MAX_REQUESTS,
    ):
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._half_open_max_requests = half_open_max_requests
        self._state = CircuitBreakerState.CLOSED
        self._failure_count = 0
        self._last_failure_time = 0.0
        self._half_open_requests = 0
        self._lock = asyncio.Lock()

    @property
    def state(self) -> str:
        return self._state

    async def can_request(self) -> bool:
        """检查是否允许发起请求。"""
        async with self._lock:
            if self._state == CircuitBreakerState.CLOSED:
                return True

            if self._state == CircuitBreakerState.OPEN:
                if time.monotonic() - self._last_failure_time >= self._recovery_timeout:
                    self._state = CircuitBreakerState.HALF_OPEN
                    self._half_open_requests = 0
                    return True
                return False

            if self._state == CircuitBreakerState.HALF_OPEN:
                if self._half_open_requests < self._half_open_max_requests:
                    self._half_open_requests += 1
                    return True
                return False

            return False

    async def on_success(self) -> None:
        """请求成功时重置熔断器状态。"""
        async with self._lock:
            if self._state == CircuitBreakerState.HALF_OPEN:
                self._state = CircuitBreakerState.CLOSED
                self._failure_count = 0
                self._half_open_requests = 0
            elif self._state == CircuitBreakerState.CLOSED:
                self._failure_count = 0

    async def on_failure(self) -> None:
        """请求失败时累加失败计数。"""
        async with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.monotonic()
            if self._failure_count >= self._failure_threshold:
                self._state = CircuitBreakerState.OPEN
                self._half_open_requests = 0


# 每供应商熔断器实例缓存
import threading
_circuit_breakers: Dict[str, CircuitBreaker] = {}
_circuit_breakers_lock = threading.Lock()


def _get_circuit_breaker(provider: str) -> CircuitBreaker:
    """获取指定供应商的熔断器实例（单例）。"""
    if provider not in _circuit_breakers:
        with _circuit_breakers_lock:
            if provider not in _circuit_breakers:  # 双重检查锁定
                _circuit_breakers[provider] = CircuitBreaker()
    return _circuit_breakers[provider]


def _extract_retry_after(exc: Exception) -> Optional[float]:
    """
    从异常的响应头中提取 Retry-After 值（秒）。
    支持 Retry-After: <seconds> 和 Retry-After: <http-date> 两种格式。
    """
    response = getattr(exc, "response", None)
    if response is None:
        return None
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    raw = headers.get("Retry-After") or headers.get("retry-after")
    if raw is None:
        return None
    try:
        return float(raw)
    except (ValueError, TypeError):
        try:
            dt = parsedate_to_datetime(str(raw))
            return max(0.0, (dt - datetime.now(dt.tzinfo or timezone.utc)).total_seconds())
        except Exception as exc:
            # Retry-After 头部格式不规范，记录 debug 级别日志便于排查
            logger.bind(module="litellm_adapter", event="retry_after_parse_failed").debug(
                f"无法解析 Retry-After 头部: {raw!r}, error={exc}"
            )
            return None


async def _rate_limit_backoff(exc: Exception, attempt: int) -> None:
    """
    针对速率限制错误的智能退避。
    优先使用服务端 Retry-After，回退到指数退避（最小 5 秒）。
    """
    retry_after = _extract_retry_after(exc)
    await _exponential_backoff(
        attempt,
        base_delay=3.0,
        max_delay=120.0,
        min_delay=5.0,
        retry_after=retry_after,
    )


async def _exponential_backoff(
    attempt: int,
    base_delay: float = 2.0,
    max_delay: float = 60.0,
    min_delay: float = 0.0,
    retry_after: Optional[float] = None,
) -> None:
    """
    指数退避等待。
    计算公式: delay = clamp(base_delay * 2^attempt + random_jitter, min_delay, max_delay)
    如果提供了 retry_after，优先使用服务端建议的等待时间。
    """
    if retry_after is not None and retry_after > 0:
        delay = min(retry_after + random.uniform(0, 0.5), max_delay)
    else:
        delay = base_delay * (2 ** attempt) + random.uniform(0, 0.5)
        delay = max(delay, min_delay)
        delay = min(delay, max_delay)
    await asyncio.sleep(delay)


async def _call_with_timeout(coro, timeout: float, label: str = "litellm_request") -> Any:
    """
    使用 asyncio.wait_for 包装的异步调用，确保不会无限等待。
    超时后抛出 asyncio.TimeoutError。
    """
    return await asyncio.wait_for(coro, timeout=timeout)


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

    DeepSeek 模型名规范化：DeepSeek API 自 2026-07 起仅接受 `deepseek-v4-pro` 与
    `deepseek-v4-flash`，旧名（deepseek-v3 / deepseek-chat / deepseek-reasoner /
    deepseek-r1 / deepseek-v3.x / *-official）会触发 BadRequestError。
    此映射在前端 localStorage 仍存旧名或 DB model_configurations 表残留旧记录时兜底，
    将旧名自动映射为当前 API 接受的等价名：
    - 推理类（reasoner/r1）→ deepseek-v4-pro（推理增强模型）
    - 通用类（chat/v3/v3.x/official）→ deepseek-v4-flash（默认通用模型）
    """
    normalized_provider = str(provider or "").strip().lower()
    normalized_model = str(model or "").strip()

    if not normalized_model:
        return ""

    # DeepSeek 旧模型名规范化映射（spec memory-quality-and-short-term-recovery 阶段后）
    if normalized_provider == "deepseek":
        normalized_model = _normalize_deepseek_model(normalized_model)

    prefix = PROVIDER_MODEL_PREFIX_MAP.get(normalized_provider, "openai/")

    # 如果模型名已包含 "/" 路径分隔符，则不重复添加
    if "/" in normalized_model:
        return normalized_model

    # 去除 "provider:model" 格式中的 provider 前缀（如 "deepseek:deepseek-v4-flash" → "deepseek-v4-flash"）
    if ":" in normalized_model:
        colon_idx = normalized_model.index(":")
        prefix_part = normalized_model[:colon_idx].lower()
        # 仅当 ":" 前的部分与当前 provider 名匹配时才去掉前缀，避免误处理含冒号的模型名
        if prefix_part == normalized_provider:
            normalized_model = normalized_model[colon_idx + 1:]

    return f"{prefix}{normalized_model}"


# DeepSeek 旧模型名 → 当前 API 接受的模型名映射
# 背景：DeepSeek API 2026-07 改造后仅接受 deepseek-v4-pro / deepseek-v4-flash
_DEEPSEEK_MODEL_ALIASES: Dict[str, str] = {
    # 通用类（chat / v3 系列）→ flash
    "deepseek-chat": "deepseek-v4-flash",
    "deepseek-v3": "deepseek-v4-flash",
    "deepseek-v3-official": "deepseek-v4-flash",
    "deepseek-v3.1": "deepseek-v4-flash",
    "deepseek-v3.2": "deepseek-v4-flash",
    # 推理类（reasoner / r1）→ pro
    "deepseek-reasoner": "deepseek-v4-pro",
    "deepseek-r1": "deepseek-v4-pro",
    "deepseek-r1-official": "deepseek-v4-pro",
}


def _normalize_deepseek_model(model: str) -> str:
    """
    将 DeepSeek 旧模型名规范化为当前 API 接受的模型名。

    已是 v4 系列或不在映射表中的模型名原样返回。
    """
    if not model:
        return model
    normalized = model.strip().lower()
    # 已是当前 API 接受的模型名，直接返回
    if normalized in ("deepseek-v4-pro", "deepseek-v4-flash"):
        return normalized
    # 命中映射表的旧名，返回规范化后的名
    if normalized in _DEEPSEEK_MODEL_ALIASES:
        return _DEEPSEEK_MODEL_ALIASES[normalized]
    # 未知模型名原样返回（让上游 API 报错暴露真实问题，而非静默替换）
    return model


def _build_litellm_optional_params(
    *,
    temperature: Optional[float] = None,
    top_p: Optional[float] = None,
    max_tokens: int = 8192,
    stream: bool = False,
    thinking_params: Optional[Dict[str, Any]] = None,
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
    if thinking_params:
        params.update(thinking_params)
    return params


# 以 openai/ 前缀路由、但实际上是自定义兼容 API 的供应商集合
# 这些供应商通过自定义 api_base 提供扩展参数（如 reasoning_effort），
# 但 LiteLLM 的 openai 参数白名单不包含这些参数，需要移入 extra_body 透传
_OPENAI_COMPAT_CUSTOM_PROVIDERS = {"alibaba", "moonshot", "zhipu"}


def _fix_call_kwargs_for_custom_openai_compat(
    call_kwargs: Dict[str, Any],
    provider: str,
) -> Dict[str, Any]:
    """
    对使用 openai/ 路由但实际是自定义兼容 API 的供应商，将 top-level 的扩展参数
    （如 reasoning_effort）迁移到 extra_body，绕过 LiteLLM 的 openai 参数白名单校验。
    """
    if provider.lower() not in _OPENAI_COMPAT_CUSTOM_PROVIDERS:
        return call_kwargs

    # 如果存在 top-level reasoning_effort，迁入 extra_body
    if "reasoning_effort" in call_kwargs:
        effort_val = call_kwargs.pop("reasoning_effort")
        extra_body = call_kwargs.get("extra_body") or {}
        if "reasoning_effort" not in extra_body:
            extra_body["reasoning_effort"] = effort_val
        call_kwargs["extra_body"] = extra_body

    return call_kwargs


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
    if status_code is None:
        response = getattr(exc, "response", None)
        status_code = getattr(response, "status_code", None)

    # 提取 LiteLLM 错误消息
    error_message = str(exc)
    if hasattr(exc, "message"):
        error_message = str(exc.message)

    # 消息级兜底检测：部分异常未携带 status_code，通过消息关键词识别
    if status_code is None:
        _msg_lower = error_message.lower()
        if any(kw in _msg_lower for kw in ("rate limit", "rate_limit", "ratelimit", "too many requests")):
            status_code = 429
        elif "connection refused" in _msg_lower:
            status_code = 503

    error_code = STATUS_CODE_ERROR_MAP.get(
        status_code, "model_service_unexpected_error"
    ) if status_code else "model_service_unexpected_error"

    # 判断是否可重试
    retryable = status_code in RETRYABLE_STATUS_CODES if status_code else False

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
    tools: Optional[List[Dict[str, Any]]] = None,
    thinking_params: Optional[Dict[str, Any]] = None,
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
        thinking_params=thinking_params,
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

    if tools:
        call_kwargs["tools"] = tools

    # 将自定义 openai 兼容供应商的扩展参数迁入 extra_body，避免 LiteLLM 参数校验拒绝
    call_kwargs = _fix_call_kwargs_for_custom_openai_compat(call_kwargs, provider)

    started_at = time.perf_counter()

    circuit_breaker = _get_circuit_breaker(provider)

    if not await circuit_breaker.can_request():
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        logger.bind(
            event="circuit_breaker_open",
            module="litellm_adapter",
            provider=provider,
            model=model,
            request_id=resolved_request_id,
            duration_ms=duration_ms,
        ).warning(f"熔断器开启，拒绝 {provider}/{model} 请求")

        return {
            "ok": False,
            "error": build_standard_error(
                "model_service_circuit_breaker_open",
                f"模型服务 {provider} 当前处于熔断状态，请稍后重试",
                request_id=resolved_request_id,
                details={"provider": provider, "model": model},
                retryable=True,
                status_code=503,
            ),
        }

    last_error: Optional[Dict[str, Any]] = None

    for attempt in range(max(1, num_retries + 1)):
        response = None
        is_rate_limit = False
        _last_exc: Optional[Exception] = None
        try:
            logger.bind(
                event="litellm_request",
                module="litellm_adapter",
                provider=provider,
                model=model,
                request_id=resolved_request_id,
                attempt=attempt + 1,
            ).info(f"发起 LiteLLM 请求: provider={provider}, model={model}, attempt={attempt + 1}")

            # 诊断日志：输出实际发送给 API 的关键参数，便于排查 404 等问题
            _extra_body = call_kwargs.get("extra_body")
            _extra_keys = list(_extra_body.keys()) if isinstance(_extra_body, dict) else []
            logger.bind(
                event="litellm_diag",
                module="litellm_adapter",
                provider=provider,
                request_id=resolved_request_id,
                litellm_model=litellm_model,
                api_base=call_kwargs.get("api_base", "未设置"),
                has_api_key=bool(call_kwargs.get("api_key")),
                extra_body_keys=_extra_keys,
                has_tools=bool(call_kwargs.get("tools")),
            ).info(f"LiteLLM 调用参数: model={litellm_model}, api_base={call_kwargs.get('api_base', '未设置')}, has_api_key={bool(call_kwargs.get('api_key'))}, extra_body_keys={_extra_keys}")

            response = await _call_with_timeout(
                litellm.acompletion(**call_kwargs),
                timeout=timeout,
            )
            duration_ms = int((time.perf_counter() - started_at) * 1000)

            # 请求成功，通知熔断器
            await circuit_breaker.on_success()

            # 提取响应文本
            response_text = ""
            reasoning_content = ""
            usage = None

            if hasattr(response, "choices") and response.choices:
                first_choice = response.choices[0]
                if hasattr(first_choice, "message") and first_choice.message:
                    response_text = first_choice.message.content or ""
                    if hasattr(first_choice.message, "reasoning_content"):
                        reasoning_content = first_choice.message.reasoning_content or ""

                    # 提取工具调用
                    tool_calls = None
                    if hasattr(first_choice.message, "tool_calls") and first_choice.message.tool_calls:
                        tool_calls = []
                        for tc in first_choice.message.tool_calls:
                            tc_entry = {
                                "id": tc.id,
                                "type": "function",
                                "function": {
                                    "name": tc.function.name,
                                    "arguments": tc.function.arguments,
                                }
                            }
                            tool_calls.append(tc_entry)

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

            if not response_text.strip() and not tool_calls:
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
                "tool_calls": tool_calls,
            }

        except asyncio.TimeoutError:
            duration_ms = int((time.perf_counter() - started_at) * 1000)
            logger.bind(
                event="litellm_timeout",
                module="litellm_adapter",
                provider=provider,
                model=model,
                request_id=resolved_request_id,
                attempt=attempt + 1,
                duration_ms=duration_ms,
            ).error(f"LiteLLM 请求超时: provider={provider}, model={model}")

            last_error = build_standard_error(
                "model_service_timeout",
                f"模型服务请求超时（{timeout}s），请稍后重试",
                request_id=resolved_request_id,
                details={"provider": provider, "model": model, "timeout": timeout},
                retryable=True,
                status_code=504,
            )

        except Exception as exc:
            _last_exc = exc
            duration_ms = int((time.perf_counter() - started_at) * 1000)
            logger.bind(
                event="litellm_error",
                module="litellm_adapter",
                provider=provider,
                model=model,
                request_id=resolved_request_id,
                error_type=type(exc).__name__,
                attempt=attempt + 1,
                duration_ms=duration_ms,
            ).error(f"LiteLLM 请求失败: {type(exc).__name__}: {str(exc)[:300]}")

            mapped = _map_litellm_error(
                exc,
                provider=provider,
                model=model,
                request_id=resolved_request_id,
            )
            last_error = mapped.get("error", mapped) if isinstance(mapped, dict) else mapped

            # 检测是否为速率限制错误（429），使用更长的退避时间
            is_rate_limit = (
                isinstance(last_error, dict)
                and last_error.get("details", {}).get("status_code") == 429
            )

            if isinstance(last_error, dict) and not last_error.get("retryable", False):
                await circuit_breaker.on_failure()
                break

        finally:
            if response is not None:
                try:
                    response.close()
                except Exception:
                    # 响应清理失败不影响已获取的结果，降级为 debug 避免每次调用产生噪音
                    logger.bind(module="litellm_adapter", event="response_close_error").debug(
                        "关闭 HTTP 响应失败（结果已获取，忽略）"
                    )

        if attempt < num_retries:
            if is_rate_limit and _last_exc is not None:
                await _rate_limit_backoff(_last_exc, attempt)
            else:
                await _exponential_backoff(attempt)

    await circuit_breaker.on_failure()
    return {
        "ok": False,
        "error": last_error,
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
    tools: Optional[List[Dict[str, Any]]] = None,
    thinking_params: Optional[Dict[str, Any]] = None,
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
        thinking_params=thinking_params,
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

    if tools:
        call_kwargs["tools"] = tools

    # 将自定义 openai 兼容供应商的扩展参数迁入 extra_body，避免 LiteLLM 参数校验拒绝
    call_kwargs = _fix_call_kwargs_for_custom_openai_compat(call_kwargs, provider)

    started_at = time.perf_counter()

    circuit_breaker = _get_circuit_breaker(provider)

    if not await circuit_breaker.can_request():
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        logger.bind(
            event="circuit_breaker_open",
            module="litellm_adapter",
            provider=provider,
            model=model,
            request_id=resolved_request_id,
            duration_ms=duration_ms,
        ).warning(f"熔断器开启，拒绝 {provider}/{model} 流式请求")
        yield {
            "error": build_standard_error(
                "model_service_circuit_breaker_open",
                f"模型服务 {provider} 当前处于熔断状态，请稍后重试",
                request_id=resolved_request_id,
                details={"provider": provider, "model": model},
                retryable=True,
                status_code=503,
            ),
        }
        return

    stream_success = False

    response = None
    for attempt in range(max(1, num_retries + 1)):
        is_rate_limit = False
        _last_exc: Optional[Exception] = None
        try:
            logger.bind(
                event="litellm_stream_request",
                module="litellm_adapter",
                provider=provider,
                model=model,
                request_id=resolved_request_id,
                attempt=attempt + 1,
            ).info(f"发起 LiteLLM 流式请求: provider={provider}, model={model}, attempt={attempt + 1}")

            # 诊断日志：输出实际发送给 API 的关键参数，便于排查 404 等问题
            _extra_body = call_kwargs.get("extra_body")
            _extra_keys = list(_extra_body.keys()) if isinstance(_extra_body, dict) else []
            logger.bind(
                event="litellm_stream_diag",
                module="litellm_adapter",
                provider=provider,
                request_id=resolved_request_id,
                litellm_model=litellm_model,
                api_base=call_kwargs.get("api_base", "未设置"),
                has_api_key=bool(call_kwargs.get("api_key")),
                extra_body_keys=_extra_keys,
                has_tools=bool(call_kwargs.get("tools")),
            ).info(f"LiteLLM 流式调用参数: model={litellm_model}, api_base={call_kwargs.get('api_base', '未设置')}, has_api_key={bool(call_kwargs.get('api_key'))}, extra_body_keys={_extra_keys}")

            response = await _call_with_timeout(
                litellm.acompletion(**call_kwargs),
                timeout=timeout,
            )

            delta_tool_calls: Dict[int, Dict[str, Any]] = {}

            async for chunk in response:
                content = ""
                reasoning = ""

                if hasattr(chunk, "choices") and chunk.choices:
                    delta = chunk.choices[0].delta
                    if delta:
                        content = delta.content or ""
                        if hasattr(delta, "reasoning_content"):
                            reasoning = delta.reasoning_content or ""

                        # 累积 tool_calls delta
                        if hasattr(delta, "tool_calls") and delta.tool_calls:
                            for tc_delta in delta.tool_calls:
                                idx = tc_delta.index
                                if idx not in delta_tool_calls:
                                    delta_tool_calls[idx] = {"id": None, "function": {"name": "", "arguments": ""}}
                                if tc_delta.id:
                                    delta_tool_calls[idx]["id"] = tc_delta.id
                                if hasattr(tc_delta, "function"):
                                    if tc_delta.function.name:
                                        delta_tool_calls[idx]["function"]["name"] = tc_delta.function.name
                                    if tc_delta.function.arguments:
                                        delta_tool_calls[idx]["function"]["arguments"] += tc_delta.function.arguments

                if content or reasoning:
                    yield {"content": content, "reasoning_content": reasoning}

            # 如果有累积的 tool_calls，发出 tool_calls 事件
            if delta_tool_calls:
                tool_calls_list = []
                for idx in sorted(delta_tool_calls.keys()):
                    tc = delta_tool_calls[idx]
                    tool_calls_list.append({
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["function"]["name"],
                            "arguments": tc["function"]["arguments"],
                        }
                    })
                yield {"type": "tool_calls", "tool_calls": tool_calls_list}

            duration_ms = int((time.perf_counter() - started_at) * 1000)
            await circuit_breaker.on_success()
            stream_success = True
            logger.bind(
                event="litellm_stream_complete",
                module="litellm_adapter",
                provider=provider,
                model=model,
                request_id=resolved_request_id,
                duration_ms=duration_ms,
            ).info(f"LiteLLM 流式请求完成: duration={duration_ms}ms")
            return

        except asyncio.TimeoutError:

            duration_ms = int((time.perf_counter() - started_at) * 1000)
            logger.bind(
                event="litellm_stream_timeout",
                module="litellm_adapter",
                provider=provider,
                model=model,
                request_id=resolved_request_id,
                attempt=attempt + 1,
                duration_ms=duration_ms,
            ).error(f"LiteLLM 流式请求超时: provider={provider}, model={model}")

            if attempt == num_retries:
                yield {
                    "error": build_standard_error(
                        "model_service_timeout",
                        f"模型服务请求超时（{timeout}s），请稍后重试",
                        request_id=resolved_request_id,
                        details={"provider": provider, "model": model, "timeout": timeout},
                        retryable=True,
                        status_code=504,
                    ),
                }

        except Exception as exc:

            _last_exc = exc
            duration_ms = int((time.perf_counter() - started_at) * 1000)
            logger.bind(
                event="litellm_stream_error",
                module="litellm_adapter",
                provider=provider,
                model=model,
                request_id=resolved_request_id,
                error_type=type(exc).__name__,
                attempt=attempt + 1,
                duration_ms=duration_ms,
            ).error(f"LiteLLM 流式请求失败: {type(exc).__name__}: {str(exc)[:300]}")

            mapped = _map_litellm_error(
                exc,
                provider=provider,
                model=model,
                request_id=resolved_request_id,
            )
            mapped_error = mapped.get("error", mapped) if isinstance(mapped, dict) else mapped

            # 检测是否为速率限制错误（429），使用更长的退避时间
            is_rate_limit = (
                isinstance(mapped_error, dict)
                and mapped_error.get("details", {}).get("status_code") == 429
            )

            if isinstance(mapped_error, dict) and not mapped_error.get("retryable", False):
                await circuit_breaker.on_failure()
                yield {"error": mapped_error}
                return

            if attempt == num_retries:
                await circuit_breaker.on_failure()
                yield {"error": mapped_error}
                return

        if attempt < num_retries:
            if is_rate_limit and _last_exc is not None:
                await _rate_limit_backoff(_last_exc, attempt)
            else:
                await _exponential_backoff(attempt)

    if not stream_success:
        await circuit_breaker.on_failure()


# 模块级共享 httpx 客户端（懒初始化），避免每次调用 litellm_list_models 都新建连接
_models_httpx_client: Optional["httpx.AsyncClient"] = None
_models_httpx_client_lock = asyncio.Lock()


async def _get_models_httpx_client() -> "httpx.AsyncClient":
    """获取或懒初始化共享的 httpx 客户端，复用连接池以减少 TCP 握手开销。"""
    global _models_httpx_client
    if _models_httpx_client is not None and not _models_httpx_client.is_closed:
        return _models_httpx_client
    async with _models_httpx_client_lock:
        if _models_httpx_client is None or _models_httpx_client.is_closed:
            import httpx
            _models_httpx_client = httpx.AsyncClient(
                limits=httpx.Limits(max_keepalive_connections=5, max_connections=20),
            )
        return _models_httpx_client


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

        client = await _get_models_httpx_client()
        resp = await client.get(endpoint, headers=headers, timeout=timeout)
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
    except Exception as exc:
        # Ollama 连接异常时降级返回空模型列表，但必须记录日志便于排查
        # 此处保持 ok=True 是为了让上层 UI 不把网络异常显示为"配置错误"
        logger.bind(
            module="litellm_adapter",
            event="ollama_list_models_failed",
            provider="ollama",
            request_id=request_id,
        ).warning(f"Ollama 列出模型失败，降级返回空列表：{exc}", exc_info=exc)
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
