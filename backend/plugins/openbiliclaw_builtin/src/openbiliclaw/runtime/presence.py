"""扩展存在性跟踪，用于后台 LLM 工作的门控。"""

from __future__ import annotations

import logging
import threading
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

_DEFAULT_EXTENSION_DISCONNECT_GRACE_SECONDS = 90


class PresenceTracker:
    """跟踪跨 runtime-stream 客户端的共享扩展存在性。"""

    def __init__(self, *, now: Callable[[], float] = time.monotonic) -> None:
        self._now = now
        self._lock = threading.Lock()
        self._active_count = 0
        self._last_disconnect_at: float | None = now()

    def on_connect(self) -> None:
        """记录一次 runtime-stream 客户端连接。"""
        with self._lock:
            self._active_count += 1
            if self._active_count == 1:
                self._last_disconnect_at = None

    def on_disconnect(self) -> None:
        """记录一次 runtime-stream 客户端断开。"""
        with self._lock:
            if self._active_count <= 0:
                logger.warning("Presence disconnect received without active clients")
                self._active_count = 0
                return
            self._active_count -= 1
            if self._active_count == 0:
                self._last_disconnect_at = self._now()

    def is_present(self, grace_seconds: int) -> bool:
        """返回是否有客户端处于活跃状态，或处于断开宽限期内。"""
        with self._lock:
            active_count = self._active_count
            last_disconnect_at = self._last_disconnect_at
        if active_count > 0:
            return True
        if last_disconnect_at is None or grace_seconds <= 0:
            return False
        return self._now() - last_disconnect_at <= grace_seconds

    def snapshot(self) -> dict[str, int | float | None]:
        """返回当前存在性状态用于诊断。"""
        with self._lock:
            active_count = self._active_count
            last_disconnect_at = self._last_disconnect_at
        seconds_since_disconnect = (
            None if last_disconnect_at is None else max(0.0, self._now() - last_disconnect_at)
        )
        return {
            "active_count": active_count,
            "last_disconnect_at": last_disconnect_at,
            "seconds_since_disconnect": seconds_since_disconnect,
        }


def background_llm_work_allowed(scheduler: object, presence: PresenceTracker) -> bool:
    """返回守护进程持有的后台 LLM / embedding 工作是否可以运行。"""
    if not bool(getattr(scheduler, "enabled", True)):
        return False
    if not bool(getattr(scheduler, "pause_on_extension_disconnect", False)):
        return True
    try:
        grace = int(
            getattr(
                scheduler,
                "extension_disconnect_grace_seconds",
                _DEFAULT_EXTENSION_DISCONNECT_GRACE_SECONDS,
            )
            or _DEFAULT_EXTENSION_DISCONNECT_GRACE_SECONDS
        )
    except (TypeError, ValueError):
        grace = _DEFAULT_EXTENSION_DISCONNECT_GRACE_SECONDS
    if grace <= 0:
        grace = _DEFAULT_EXTENSION_DISCONNECT_GRACE_SECONDS
    return presence.is_present(grace_seconds=grace)


__all__ = ["PresenceTracker", "background_llm_work_allowed"]
