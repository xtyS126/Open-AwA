"""
插件系统模块，负责插件定义、加载、校验、沙箱隔离、生命周期或扩展协议处理。
这一层通常同时涉及可扩展性、安全性与运行时状态管理。
"""

from collections import deque
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Dict, List, Optional


LOG_LEVELS = {
    "DEBUG": 10,
    "INFO": 20,
    "WARNING": 30,
    "ERROR": 40,
    "CRITICAL":50,
}


class LogEntry:
    """
    封装与LogEntry相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    def __init__(
        self,
        level: str,
        message: str,
        plugin_id: str,
        extra: Optional[Dict[str, Any]] = None,
    ):
        """
        处理init相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        self.timestamp = datetime.now(timezone.utc).isoformat()
        self.level = level.upper()
        self.message = message
        self.plugin_id = plugin_id
        self.extra = extra or {}

    def to_dict(self) -> Dict[str, Any]:
        """
        处理to、dict相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        return {
            "timestamp": self.timestamp,
            "level": self.level,
            "message": self.message,
            "plugin_id": self.plugin_id,
            "extra": self.extra,
        }


class PluginLogger:
    """
    封装与PluginLogger相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    def __init__(self, plugin_id: str, max_entries: int = 500):
        """
        处理init相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        self.plugin_id = plugin_id
        self._level = "DEBUG"
        self._entries: deque = deque(maxlen=max_entries)
        self._lock = Lock()

    @property
    def level(self) -> str:
        """
        处理level相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        return self._level

    @level.setter
    def level(self, value: str) -> None:
        """
        处理level相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        value = value.upper()
        if value not in LOG_LEVELS:
            raise ValueError(f"Invalid log level: {value}")
        self._level = value

    def _should_log(self, level: str) -> bool:
        """
        处理should、log相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        return LOG_LEVELS.get(level.upper(), 0) >= LOG_LEVELS.get(self._level, 0)

    def _log(self, level: str, message: str, **extra: Any) -> None:
        """
        处理log相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        if not self._should_log(level):
            return
        entry = LogEntry(level=level, message=message, plugin_id=self.plugin_id, extra=extra)
        with self._lock:
            self._entries.append(entry)

    def debug(self, message: str, **extra: Any) -> None:
        """
        处理debug相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        self._log("DEBUG", message, **extra)

    def info(self, message: str, **extra: Any) -> None:
        """
        处理info相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        self._log("INFO", message, **extra)

    def warning(self, message: str, **extra: Any) -> None:
        """
        处理warning相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        self._log("WARNING", message, **extra)

    def error(self, message: str, **extra: Any) -> None:
        """
        处理error相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        self._log("ERROR", message, **extra)

    def critical(self, message: str, **extra: Any) -> None:
        """
        处理critical相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        self._log("CRITICAL", message, **extra)

    def get_entries(
        self,
        level: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """
        获取entries相关数据或当前状态。
        调用方通常依赖该结果继续进行后续判断、渲染或业务编排。
        """
        with self._lock:
            entries = list(self._entries)
        if level:
            level = level.upper()
            entries = [e for e in entries if LOG_LEVELS.get(e.level, 0) >= LOG_LEVELS.get(level, 0)]
        entries = entries[offset: offset + limit]
        return [e.to_dict() for e in entries]

    def clear(self) -> None:
        """
        处理clear相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        with self._lock:
            self._entries.clear()


class LogManager:
    """
    封装与LogManager相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    _instance: Optional["LogManager"] = None
    _lock: Lock = Lock()
    _loggers: Dict[str, PluginLogger] = {}

    def __new__(cls) -> "LogManager":
        """
        处理new相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
        return cls._instance

    def get_logger(self, plugin_id: str) -> PluginLogger:
        """
        获取logger相关数据或当前状态。
        调用方通常依赖该结果继续进行后续判断、渲染或业务编排。
        """
        if plugin_id not in self._loggers:
            self._loggers[plugin_id] = PluginLogger(plugin_id)
        return self._loggers[plugin_id]

    def remove_logger(self, plugin_id: str) -> None:
        """
        移除logger相关数据、缓存或配置项。
        这类逻辑常用于运行时清理、兼容性整理或状态维护。
        """
        self._loggers.pop(plugin_id, None)

    def list_plugin_ids(self) -> List[str]:
        """
        列出plugin、ids相关内容，便于调用方查看、筛选或批量处理。
        返回结果通常会被页面展示、审计流程或后续操作复用。
        """
        return list(self._loggers.keys())
