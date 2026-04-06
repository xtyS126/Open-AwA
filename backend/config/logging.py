"""
配置管理模块，负责系统运行参数、安全策略或日志行为的统一定义。
配置项通常会在多个子模块中生效，因此理解其字段含义非常重要。
"""

import re
import sys
import uuid
from collections import deque
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from loguru import logger


REQUEST_ID_HEADER = "X-Request-Id"
_REQUEST_ID_CTX: ContextVar[str] = ContextVar("request_id", default="")
_LOG_BUFFER = deque(maxlen=5000)

SENSITIVE_KEYS = {
    "password",
    "token",
    "api_key",
    "secret",
    "authorization",
    "cookie",
    "access_token",
    "refresh_token",
}

IDENTIFIER_KEYS = {
    "user_id",
    "user_id_masked",
    "account_id",
    "phone",
    "email",
    "ip",
    "client_ip",
    "client_ip_masked",
    "openid",
}


def generate_request_id() -> str:
    """
    生成唯一的请求标识符。
    
    Returns:
        32位十六进制字符串形式的UUID。
    """
    return uuid.uuid4().hex


def set_request_id(request_id: str) -> None:
    """
    设置当前请求的标识符到上下文变量中。
    
    Args:
        request_id: 要设置的请求ID字符串。
    """
    _REQUEST_ID_CTX.set(str(request_id or "").strip())


def get_request_id() -> str:
    """
    获取当前请求的标识符。
    
    Returns:
        当前上下文中的请求ID，未设置时返回空字符串。
    """
    return _REQUEST_ID_CTX.get()


def clear_request_id() -> None:
    """
    清除当前请求的标识符，重置为空字符串。
    """
    _REQUEST_ID_CTX.set("")


def _mask_identifier(value: Any) -> Any:
    """
    对标识符进行脱敏处理，保留部分字符用于追踪。
    
    Args:
        value: 需要脱敏的值，支持字符串或其他类型。
        
    Returns:
        脱敏后的值。邮箱格式保留前后字符，普通字符串保留首尾字符。
    """
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return text
    if "@" in text and len(text) > 5:
        local, domain = text.split("@", 1)
        if len(local) <= 2:
            return f"{local[0]}***@{domain}" if local else f"***@{domain}"
        return f"{local[:2]}***{local[-1:]}@{domain}"
    if len(text) <= 4:
        return "*" * len(text)
    if len(text) <= 8:
        return f"{text[:1]}***{text[-1:]}"
    return f"{text[:2]}***{text[-2:]}"


def _mask_secret_text(text: str) -> str:
    """
    对文本中的敏感信息进行脱敏处理。
    
    Args:
        text: 需要脱敏的文本字符串。
        
    Returns:
        脱敏后的文本，敏感值被替换为***。
    """
    if not text:
        return text

    key_pattern = r"(password|token|api[_-]?key|secret|authorization|cookie|access_token|refresh_token)"

    text = re.sub(
        rf"({key_pattern}\s*[:=]\s*)([^\s,;\"']+)",
        lambda m: f"{m.group(1)}***",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"(Bearer\s+)[A-Za-z0-9\-._~+/]+=*", r"\1***", text, flags=re.IGNORECASE)

    if len(text) > 20 and re.fullmatch(r"[A-Za-z0-9\-._~+/=]+", text):
        return f"{text[:2]}***{text[-2:]}"
    return text


def sanitize_for_logging(value: Any, key_name: str = "") -> Any:
    """
    递归地对日志数据进行脱敏处理。
    
    Args:
        value: 需要脱敏的数据，支持字典、列表、元组、集合和基本类型。
        key_name: 当前字段的键名，用于判断是否为敏感字段。
        
    Returns:
        脱敏后的数据，敏感值被替换为***或部分遮蔽。
    """
    normalized_key = str(key_name or "").strip().lower()

    if isinstance(value, dict):
        sanitized: Dict[str, Any] = {}
        for k, v in value.items():
            child_key = str(k or "")
            lower_child_key = child_key.lower()
            if lower_child_key in SENSITIVE_KEYS:
                sanitized[child_key] = "***"
            elif lower_child_key in IDENTIFIER_KEYS:
                sanitized[child_key] = _mask_identifier(v)
            else:
                sanitized[child_key] = sanitize_for_logging(v, child_key)
        return sanitized

    if isinstance(value, list):
        return [sanitize_for_logging(item, key_name=normalized_key) for item in value]

    if isinstance(value, tuple):
        return tuple(sanitize_for_logging(item, key_name=normalized_key) for item in value)

    if isinstance(value, set):
        return {sanitize_for_logging(item, key_name=normalized_key) for item in value}

    if normalized_key in SENSITIVE_KEYS:
        return "***"

    if normalized_key in IDENTIFIER_KEYS:
        return _mask_identifier(value)

    if isinstance(value, str):
        return _mask_secret_text(value)

    return value


def _patch_record(record: Dict[str, Any], service_name: str) -> None:
    """
    对日志记录进行补丁处理，添加请求ID和服务信息，并写入缓冲区。
    
    Args:
        record: loguru的日志记录字典。
        service_name: 服务名称，用于标识日志来源。
    """
    extra = dict(record.get("extra") or {})

    request_id = get_request_id()
    if request_id and not extra.get("request_id"):
        extra["request_id"] = request_id

    extra["service"] = extra.get("service") or service_name
    extra["module"] = extra.get("module") or str(record.get("name") or "").split(".")[-1]
    extra["event"] = extra.get("event") or "app_log"

    record["message"] = sanitize_for_logging(record.get("message"))
    record["extra"] = sanitize_for_logging(extra)

    level_obj = record.get("level")
    level_name = getattr(level_obj, "name", "")

    log_event = {
        "timestamp": str(record.get("time", datetime.now(timezone.utc))),
        "level": str(level_name).upper(),
        "service": str(extra.get("service", service_name)),
        "module": str(extra.get("module", "")),
        "event": str(extra.get("event", "")),
        "message": str(record.get("message", "")),
        "request_id": str(extra.get("request_id", "")),
        "extra": extra,
    }
    _LOG_BUFFER.append(log_event)


def init_logging(log_level: str = "INFO", service_name: str = "openawa-backend", log_serialize: bool = True) -> None:
    """
    初始化日志系统，配置loguru的输出格式和级别。
    
    Args:
        log_level: 日志级别，默认为INFO。
        service_name: 服务名称，用于标识日志来源。
        log_serialize: 是否序列化日志输出。
    """
    logger.remove()
    logger.configure(patcher=lambda record: _patch_record(record, service_name=service_name))
    logger.add(
        sys.stderr,
        level=str(log_level or "INFO").upper(),
        serialize=bool(log_serialize),
        enqueue=False,
        backtrace=False,
        diagnose=False,
    )


def query_log_buffer(
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    level: str = "",
    keyword: str = "",
    limit: int = 100,
    offset: int = 0,
) -> Dict[str, Any]:
    """
    查询日志缓冲区中的日志记录。
    
    Args:
        start_time: 查询起始时间，可选。
        end_time: 查询结束时间，可选。
        level: 日志级别过滤，可选。
        keyword: 关键词搜索，可选。
        limit: 返回记录数量限制，默认100。
        offset: 分页偏移量，默认0。
        
    Returns:
        包含total、offset、limit和records字段的字典。
    """
    level_filter = str(level or "").upper().strip()
    keyword_filter = str(keyword or "").strip().lower()

    matched = []
    for entry in reversed(_LOG_BUFFER):
        entry_time = None
        try:
            entry_time = datetime.fromisoformat(str(entry.get("timestamp", "")).replace("Z", "+00:00"))
        except ValueError:
            entry_time = None

        if start_time and entry_time and entry_time < start_time:
            continue
        if end_time and entry_time and entry_time > end_time:
            continue
        if level_filter and str(entry.get("level", "")).upper() != level_filter:
            continue
        if keyword_filter:
            haystack = f"{entry.get('message', '')} {entry.get('event', '')} {entry.get('module', '')} {entry.get('request_id', '')}".lower()
            if keyword_filter not in haystack:
                continue
        matched.append(entry)

    total = len(matched)
    page = matched[offset : offset + limit]
    return {"total": total, "offset": offset, "limit": limit, "records": page}
