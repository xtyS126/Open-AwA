import json
import os
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
    def __init__(
        self,
        level: str,
        message: str,
        plugin_id: str,
        extra: Optional[Dict[str, Any]] = None,
    ):
        self.timestamp = datetime.now(timezone.utc).isoformat()
        self.level = level.upper()
        self.message = message
        self.plugin_id = plugin_id
        self.extra = extra or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "level": self.level,
            "message": self.message,
            "plugin_id": self.plugin_id,
            "extra": self.extra,
        }


class PluginLogger:
    def __init__(self, plugin_id: str, max_entries: int = 500):
        self.plugin_id = plugin_id
        self._level = "DEBUG"
        self._entries: deque = deque(maxlen=max_entries)
        self._lock = Lock()

    @property
    def level(self) -> str:
        return self._level

    @level.setter
    def level(self, value: str) -> None:
        value = value.upper()
        if value not in LOG_LEVELS:
            raise ValueError(f"Invalid log level: {value}")
        self._level = value

    def _should_log(self, level: str) -> bool:
        return LOG_LEVELS.get(level.upper(), 0) >= LOG_LEVELS.get(self._level, 0)

    def _log(self, level: str, message: str, **extra: Any) -> None:
        if not self._should_log(level):
            return
        entry = LogEntry(level=level, message=message, plugin_id=self.plugin_id, extra=extra)
        with self._lock:
            self._entries.append(entry)

    def debug(self, message: str, **extra: Any) -> None:
        self._log("DEBUG", message, **extra)

    def info(self, message: str, **extra: Any) -> None:
        self._log("INFO", message, **extra)

    def warning(self, message: str, **extra: Any) -> None:
        self._log("WARNING", message, **extra)

    def error(self, message: str, **extra: Any) -> None:
        self._log("ERROR", message, **extra)

    def critical(self, message: str, **extra: Any) -> None:
        self._log("CRITICAL", message, **extra)

    def get_entries(
        self,
        level: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        with self._lock:
            entries = list(self._entries)
        if level:
            level = level.upper()
            entries = [e for e in entries if LOG_LEVELS.get(e.level, 0) >= LOG_LEVELS.get(level, 0)]
        entries = entries[offset: offset + limit]
        return [e.to_dict() for e in entries]

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


class LogManager:
    _instance: Optional["LogManager"] = None
    _lock: Lock = Lock()

    def __new__(cls) -> "LogManager":
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._loggers: Dict[str, PluginLogger] = {}
        return cls._instance

    def get_logger(self, plugin_id: str) -> PluginLogger:
        if plugin_id not in self._loggers:
            self._loggers[plugin_id] = PluginLogger(plugin_id)
        return self._loggers[plugin_id]

    def remove_logger(self, plugin_id: str) -> None:
        self._loggers.pop(plugin_id, None)

    def list_plugin_ids(self) -> List[str]:
        return list(self._loggers.keys())
