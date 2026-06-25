"""
结构化运行时追踪模块。

提供：
- TraceId 生成和传播
- 结构化 JSONL 日志
- 敏感信息自动脱敏
- 性能指标追踪

参考 Agent Diva 的 trace 模块设计。
"""

import json
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Set
import threading

from loguru import logger


class TraceLevel(str, Enum):
    """追踪级别。"""

    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class TraceConfig:
    """追踪配置。"""

    log_dir: str = "./data/traces"  # 日志目录
    min_level: TraceLevel = TraceLevel.INFO  # 最低记录级别
    enable_redaction: bool = True  # 是否启用敏感信息脱敏
    redacted_fields: Set[str] = field(default_factory=lambda: {
        "password", "secret", "token", "api_key", "apikey",
        "authorization", "auth", "credential", "private_key"
    })
    max_message_length: int = 10000  # 单条消息最大长度
    buffer_size: int = 100  # 缓冲区大小
    flush_interval_seconds: float = 5.0  # 刷新间隔

    def __post_init__(self):
        """校验配置合法性。"""
        if self.max_message_length < 100:
            raise ValueError("max_message_length 必须 >= 100")
        if self.buffer_size < 1:
            raise ValueError("buffer_size 必须 >= 1")
        if self.flush_interval_seconds <= 0:
            raise ValueError("flush_interval_seconds 必须 > 0")


class TraceLogger:
    """
    结构化追踪日志器。

    提供：
    - 结构化 JSONL 格式日志
    - TraceId 生成和传播
    - 敏感信息自动脱敏
    - 性能指标追踪
    - 上下文关联
    """

    def __init__(self, config: Optional[TraceConfig] = None):
        """
        初始化追踪日志器。

        Args:
            config: 追踪配置，None 表示使用默认配置
        """
        self.config = config or TraceConfig()
        self._current_trace_id: Optional[str] = None
        self._current_span_id: Optional[str] = None
        self._buffer: List[Dict[str, Any]] = []
        self._buffer_lock = threading.Lock()
        self._log_file: Optional[Path] = None
        self._setup_log_file()

        # 启动定时刷新线程
        self._flush_thread = threading.Thread(target=self._periodic_flush, daemon=True)
        self._flush_thread.start()

    def _setup_log_file(self) -> None:
        """设置日志文件。"""
        log_dir = Path(self.config.log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)

        # 按日期创建日志文件
        date_str = datetime.now().strftime("%Y%m%d")
        self._log_file = log_dir / f"trace_{date_str}.jsonl"

    def generate_trace_id(self) -> str:
        """
        生成新的 TraceId。

        Returns:
            唯一的追踪 ID
        """
        return str(uuid.uuid4())

    def generate_span_id(self) -> str:
        """
        生成新的 SpanId。

        Returns:
            唯一的跨度 ID
        """
        return str(uuid.uuid4())[:8]

    def set_trace_context(self, trace_id: str, span_id: Optional[str] = None) -> None:
        """
        设置当前追踪上下文。

        Args:
            trace_id: 追踪 ID
            span_id: 跨度 ID（可选）
        """
        self._current_trace_id = trace_id
        self._current_span_id = span_id or self.generate_span_id()

    def clear_trace_context(self) -> None:
        """清除当前追踪上下文。"""
        self._current_trace_id = None
        self._current_span_id = None

    @contextmanager
    def trace_context(self, trace_id: Optional[str] = None) -> Iterator[Dict[str, str]]:
        """
        追踪上下文管理器。

        Args:
            trace_id: 追踪 ID，None 表示自动生成

        Yields:
            包含 trace_id 和 span_id 的字典
        """
        # 保存原有上下文
        old_trace_id = self._current_trace_id
        old_span_id = self._current_span_id

        # 设置新上下文
        new_trace_id = trace_id or self.generate_trace_id()
        new_span_id = self.generate_span_id()
        self.set_trace_context(new_trace_id, new_span_id)

        try:
            yield {"trace_id": new_trace_id, "span_id": new_span_id}
        finally:
            # 恢复原有上下文
            if old_trace_id:
                self.set_trace_context(old_trace_id, old_span_id)
            else:
                self.clear_trace_context()

    def log(
        self,
        level: TraceLevel,
        message: str,
        data: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> None:
        """
        记录追踪日志。

        Args:
            level: 日志级别
            message: 日志消息
            data: 附加数据
            **kwargs: 其他字段
        """
        # 检查级别
        if not self._should_log(level):
            return

        # 构建日志条目
        entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": level.value,
            "message": message[:self.config.max_message_length],
            "trace_id": self._current_trace_id,
            "span_id": self._current_span_id,
        }

        # 添加附加数据
        if data:
            entry["data"] = self._redact_sensitive_data(data)

        # 添加其他字段
        for key, value in kwargs.items():
            if key not in entry:
                entry[key] = self._redact_value(value) if isinstance(value, str) else value

        # 添加到缓冲区
        with self._buffer_lock:
            self._buffer.append(entry)

            # 缓冲区满时立即刷新
            if len(self._buffer) >= self.config.buffer_size:
                self._flush_buffer()

    def debug(self, message: str, data: Optional[Dict[str, Any]] = None, **kwargs) -> None:
        """记录 DEBUG 级别日志。"""
        self.log(TraceLevel.DEBUG, message, data, **kwargs)

    def info(self, message: str, data: Optional[Dict[str, Any]] = None, **kwargs) -> None:
        """记录 INFO 级别日志。"""
        self.log(TraceLevel.INFO, message, data, **kwargs)

    def warning(self, message: str, data: Optional[Dict[str, Any]] = None, **kwargs) -> None:
        """记录 WARNING 级别日志。"""
        self.log(TraceLevel.WARNING, message, data, **kwargs)

    def error(self, message: str, data: Optional[Dict[str, Any]] = None, **kwargs) -> None:
        """记录 ERROR 级别日志。"""
        self.log(TraceLevel.ERROR, message, data, **kwargs)

    def critical(self, message: str, data: Optional[Dict[str, Any]] = None, **kwargs) -> None:
        """记录 CRITICAL 级别日志。"""
        self.log(TraceLevel.CRITICAL, message, data, **kwargs)

    def trace_operation(
        self,
        operation: str,
        data: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> "TraceSpan":
        """
        追踪一个操作。

        Args:
            operation: 操作名称
            data: 附加数据
            **kwargs: 其他字段

        Returns:
            TraceSpan 上下文管理器
        """
        return TraceSpan(self, operation, data, **kwargs)

    def flush(self) -> None:
        """立即刷新缓冲区。"""
        with self._buffer_lock:
            self._flush_buffer()

    def _flush_buffer(self) -> None:
        """刷新缓冲区到文件（内部方法，需在锁内调用）。"""
        if not self._buffer or not self._log_file:
            return

        try:
            with open(self._log_file, "a", encoding="utf-8") as f:
                for entry in self._buffer:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            self._buffer.clear()
        except Exception as e:
            # 日志写入失败不应影响主流程
            logger.warning(f"[TraceLogger] 写入日志失败: {e}")

    def _periodic_flush(self) -> None:
        """定时刷新缓冲区。"""
        while True:
            time.sleep(self.config.flush_interval_seconds)
            self.flush()

    def _should_log(self, level: TraceLevel) -> bool:
        """检查是否应该记录该级别的日志。"""
        level_order = {
            TraceLevel.DEBUG: 0,
            TraceLevel.INFO: 1,
            TraceLevel.WARNING: 2,
            TraceLevel.ERROR: 3,
            TraceLevel.CRITICAL: 4,
        }
        return level_order[level] >= level_order[self.config.min_level]

    def _redact_sensitive_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        脱敏敏感数据。

        Args:
            data: 原始数据

        Returns:
            脱敏后的数据
        """
        if not self.config.enable_redaction:
            return data

        redacted = {}
        for key, value in data.items():
            if key.lower() in self.config.redacted_fields:
                redacted[key] = "***REDACTED***"
            elif isinstance(value, dict):
                redacted[key] = self._redact_sensitive_data(value)
            else:
                redacted[key] = value

        return redacted

    def _redact_value(self, value: str) -> str:
        """
        脱敏单个值。

        Args:
            value: 原始值

        Returns:
            脱敏后的值
        """
        if not self.config.enable_redaction:
            return value

        # 检查是否包含敏感关键词
        lower_value = value.lower()
        for field in self.config.redacted_fields:
            if field in lower_value:
                return "***REDACTED***"

        return value


class TraceSpan:
    """
    追踪跨度。

    用于追踪一个操作的执行时间和结果。
    """

    def __init__(
        self,
        logger: TraceLogger,
        operation: str,
        data: Optional[Dict[str, Any]] = None,
        **kwargs
    ):
        """
        初始化追踪跨度。

        Args:
            logger: 追踪日志器
            operation: 操作名称
            data: 附加数据
            **kwargs: 其他字段
        """
        self.logger = logger
        self.operation = operation
        self.data = data or {}
        self.kwargs = kwargs
        self.start_time: Optional[float] = None
        self.span_id: Optional[str] = None

    def __enter__(self) -> "TraceSpan":
        """进入跨度。"""
        self.start_time = time.time()
        self.span_id = self.logger.generate_span_id()

        # 记录开始
        self.logger.info(
            f"开始操作: {self.operation}",
            data={**self.data, "span_id": self.span_id},
            **self.kwargs
        )

        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """退出跨度。"""
        if self.start_time is None:
            return

        duration = time.time() - self.start_time

        # 记录结束
        if exc_type is not None:
            self.logger.error(
                f"操作失败: {self.operation}",
                data={
                    **self.data,
                    "span_id": self.span_id,
                    "duration_seconds": duration,
                    "error": str(exc_val),
                },
                **self.kwargs
            )
        else:
            self.logger.info(
                f"操作完成: {self.operation}",
                data={
                    **self.data,
                    "span_id": self.span_id,
                    "duration_seconds": duration,
                },
                **self.kwargs
            )


# 全局追踪日志器实例
_global_logger: Optional[TraceLogger] = None
_logger_lock = threading.Lock()


def get_trace_logger(config: Optional[TraceConfig] = None) -> TraceLogger:
    """
    获取全局追踪日志器。

    Args:
        config: 追踪配置，None 表示使用默认配置

    Returns:
        全局 TraceLogger 实例
    """
    global _global_logger

    if _global_logger is None:
        with _logger_lock:
            if _global_logger is None:
                _global_logger = TraceLogger(config)

    return _global_logger


def set_trace_logger(logger: TraceLogger) -> None:
    """
    设置全局追踪日志器。

    Args:
        logger: 新的 TraceLogger 实例
    """
    global _global_logger

    with _logger_lock:
        _global_logger = logger
