"""
配置管理模块，负责系统运行参数、安全策略或日志行为的统一定义。
配置项通常会在多个子模块中生效，因此理解其字段含义非常重要。
"""

import os
import re
import sys
import traceback
import uuid
from collections import deque
from contextvars import ContextVar
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from loguru import logger


REQUEST_ID_HEADER = "X-Request-Id"
_REQUEST_ID_CTX: ContextVar[str] = ContextVar("request_id", default="")
_LOG_BUFFER = deque(maxlen=5000)
# 全局脱敏开关，init_logging 时根据配置设置
_DISABLE_SANITIZE = False

SENSITIVE_KEYS = {
    "password",
    "token",
    "bot_token",
    "api_key",
    "secret",
    "authorization",
    "cookie",
    "access_token",
    "refresh_token",
    "session_key",
    "auth_id",
    "confirm_id",
    "ticket",
    "ticket_id",
    "username",
    "user_input",
    "message_content",
    "chat_content",
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
    处理generate、request、id相关逻辑，并为调用方返回对应结果。
    阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
    """
    return uuid.uuid4().hex


def set_request_id(request_id: str) -> None:
    """
    设置request、id相关配置或运行状态。
    此类方法通常会直接影响后续执行路径或运行上下文中的关键数据。
    """
    _REQUEST_ID_CTX.set(str(request_id or "").strip())


def get_request_id() -> str:
    """
    获取request、id相关数据或当前状态。
    调用方通常依赖该结果继续进行后续判断、渲染或业务编排。
    """
    return _REQUEST_ID_CTX.get()


def clear_request_id() -> None:
    """
    处理clear、request、id相关逻辑，并为调用方返回对应结果。
    阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
    """
    _REQUEST_ID_CTX.set("")


def _mask_identifier(value: Any) -> Any:
    """
    处理mask、identifier相关逻辑，并为调用方返回对应结果。
    阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
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
    处理mask、secret、text相关逻辑，并为调用方返回对应结果。
    阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
    """
    if not text:
        return text

    key_pattern = r"(password|token|bot[_-]?token|api[_-]?key|secret|authorization|cookie|access_token|refresh_token|session[_-]?key|auth[_-]?id|confirm[_-]?id|ticket(?:[_-]?id)?)"

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
    对日志内容进行脱敏处理。当全局脱敏开关 _DISABLE_SANITIZE 为 True 时跳过脱敏，方便开发调试。
    """
    if _DISABLE_SANITIZE:
        return value
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
    处理patch、record相关逻辑，并为调用方返回对应结果。
    阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
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

    # 构建日志事件，包含异常堆栈信息
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

    # 从 record 中提取异常堆栈（loguru 在 logger.exception() 时写入 record["exception"]）
    exception_info = record.get("exception")
    if exception_info is not None:
        exc_type = exception_info.type
        exc_value = exception_info.value
        exc_tb = exception_info.traceback
        if exc_type and exc_value:
            log_event["error_type"] = exc_type.__name__
            log_event["error_message"] = str(exc_value)
        if exc_tb:
            try:
                tb_lines = traceback.format_exception(exc_type, exc_value, exc_tb)
                log_event["traceback"] = "".join(tb_lines)
            except Exception:
                pass

    # 从 extra 中提取结构化错误字段
    for err_field in ("error_type", "error_message", "error_code", "status_code"):
        val = extra.get(err_field)
        if val and err_field not in log_event:
            log_event[err_field] = val

    _LOG_BUFFER.append(log_event)


def _console_log_filter(record: Dict[str, Any]) -> bool:
    """
    控制台仅输出简洁访问日志和错误日志，减少开发终端噪音。
    """
    level_name = str(getattr(record.get("level"), "name", "")).upper()
    if level_name in {"ERROR", "CRITICAL"}:
        return True
    event_name = str((record.get("extra") or {}).get("event") or "")
    return event_name == "http_request_completed"


def init_logging(
    log_level: str = "INFO",
    service_name: str = "openawa-backend",
    log_serialize: bool = True,
    log_dir: str = "./logs",
    log_file_rotation: str = "10 MB",
    log_file_retention: str = "30 days",
    log_file_compression: str = "gz",
    disable_sanitize: bool = False,
) -> None:
    """
    初始化日志系统：控制台输出 + 文件持久化 + 错误日志独立文件。
    日志文件按大小自动轮转，按保留天数自动清理，支持压缩归档。
    """
    global _DISABLE_SANITIZE
    _DISABLE_SANITIZE = disable_sanitize

    logger.remove()
    logger.configure(patcher=lambda record: _patch_record(record, service_name=service_name))

    level_str = str(log_level or "INFO").upper()

    # 控制台输出（stderr）
    logger.add(
        sys.stderr,
        level=level_str,
        serialize=False,
        format=(
            "<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | "
            "{message}"
        ),
        filter=_console_log_filter,
        enqueue=False,
        backtrace=True,
        diagnose=False,
    )

    # 文件持久化
    os.makedirs(log_dir, exist_ok=True)

    # 全量日志文件：所有级别
    logger.add(
        os.path.join(log_dir, "openawa_{time:YYYY-MM-DD}.log"),
        level=level_str,
        serialize=True,
        rotation=log_file_rotation,
        retention=log_file_retention,
        compression=log_file_compression,
        encoding="utf-8",
        enqueue=True,
        backtrace=True,
        diagnose=False,
    )

    # 错误日志独立文件：仅 WARNING 及以上，方便快速定位问题
    logger.add(
        os.path.join(log_dir, "openawa_error_{time:YYYY-MM-DD}.log"),
        level="WARNING",
        serialize=True,
        rotation=log_file_rotation,
        retention=log_file_retention,
        compression=log_file_compression,
        encoding="utf-8",
        enqueue=True,
        backtrace=True,
        diagnose=True,
    )

    logger.bind(
        event="logging_initialized",
        module="config",
        log_level=level_str,
        log_dir=log_dir,
        file_rotation=log_file_rotation,
        file_retention=log_file_retention,
    ).info(
        f"日志系统初始化完成: level={level_str}, dir={log_dir}, "
        f"rotation={log_file_rotation}, retention={log_file_retention}"
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
    处理query、log、buffer相关逻辑，并为调用方返回对应结果。
    阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
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


def query_logs_by_request_id(request_id: str) -> List[Dict[str, Any]]:
    """
    根据 request_id 聚合一次请求的完整日志链路，方便追踪单次请求的全部执行过程。
    返回按时间正序排列的日志列表。
    """
    if not request_id:
        return []
    matched = []
    for entry in _LOG_BUFFER:
        if str(entry.get("request_id", "")) == request_id:
            matched.append(entry)
    return matched


def get_error_summary(
    hours: Optional[int] = None,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    limit: int = 50,
) -> Dict[str, Any]:
    """
    统计错误日志摘要：按 error_type 分组计数，并返回最近的错误列表。
    用于快速了解系统错误分布和高频报错。
    """
    if hours is not None and start_time is None:
        end_time = end_time or datetime.now(timezone.utc)
        start_time = end_time - timedelta(hours=max(1, int(hours)))

    errors: List[Dict[str, Any]] = []
    error_type_counts: Dict[str, int] = {}
    module_error_counts: Dict[str, int] = {}

    for entry in reversed(_LOG_BUFFER):
        level = str(entry.get("level", "")).upper()
        if level not in ("ERROR", "CRITICAL"):
            continue

        entry_time = None
        try:
            entry_time = datetime.fromisoformat(
                str(entry.get("timestamp", "")).replace("Z", "+00:00")
            )
        except ValueError:
            pass

        if start_time and entry_time and entry_time < start_time:
            continue
        if end_time and entry_time and entry_time > end_time:
            continue

        errors.append(entry)

        # 按错误类型统计
        etype = entry.get("error_type") or entry.get("event", "unknown")
        error_type_counts[etype] = error_type_counts.get(etype, 0) + 1

        # 按模块统计
        mod = entry.get("module", "unknown")
        module_error_counts[mod] = module_error_counts.get(mod, 0) + 1

    # 按频率降序排序
    sorted_types = sorted(error_type_counts.items(), key=lambda x: x[1], reverse=True)
    sorted_modules = sorted(module_error_counts.items(), key=lambda x: x[1], reverse=True)

    return {
        "total_errors": len(errors),
        "error_types": [{"type": t, "count": c} for t, c in sorted_types],
        "error_by_module": [{"module": m, "count": c} for m, c in sorted_modules],
        "recent_errors": errors[:limit],
    }


def get_log_file_list(log_dir: str = "./logs") -> List[Dict[str, Any]]:
    """
    列出日志目录中的所有日志文件及其大小，方便前端展示和下载。
    """
    files = []
    if not os.path.isdir(log_dir):
        return files
    for fname in sorted(os.listdir(log_dir), reverse=True):
        fpath = os.path.join(log_dir, fname)
        if os.path.isfile(fpath) and (fname.endswith(".log") or fname.endswith(".gz")):
            stat = os.stat(fpath)
            files.append({
                "filename": fname,
                "size_bytes": stat.st_size,
                "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            })
    return files
