"""
自主模式资源限制模块。

对 CPU/内存/时间施加硬限制，防止失控进程耗尽系统资源。
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, Optional

from loguru import logger

from core.autonomous.config import AutonomousConfig


class TaskTimeoutError(Exception):
    """任务超时异常。"""
    def __init__(self, elapsed_s: float, limit_s: int):
        self.elapsed_s = elapsed_s
        self.limit_s = limit_s
        super().__init__(f"任务超时: {elapsed_s:.1f}s > {limit_s}s")


class CommandTimeoutError(Exception):
    """命令执行超时异常。"""
    def __init__(self, elapsed_s: float, limit_s: int):
        self.elapsed_s = elapsed_s
        self.limit_s = limit_s
        super().__init__(f"命令超时: {elapsed_s:.1f}s > {limit_s}s")


class MemoryLimitError(Exception):
    """内存超限异常。"""
    def __init__(self, used_mb: float, limit_mb: int):
        self.used_mb = used_mb
        self.limit_mb = limit_mb
        super().__init__(f"内存超限: {used_mb:.1f}MB > {limit_mb}MB")


class ResourceLimiter:
    """资源限制器。

    在自主模式下确保：
    - 单命令执行不超过 cmd_timeout 秒
    - 总任务不超过 task_timeout 秒
    - 内存使用不超过 memory_limit MB
    """

    def __init__(self, config: AutonomousConfig):
        self._cmd_timeout = config.cmd_timeout
        self._task_timeout = config.task_timeout
        self._memory_limit_mb = config.memory_limit
        # 任务级别计时
        self._task_started_at: Optional[float] = None

    def start_task_timer(self) -> None:
        """标记任务开始计时。"""
        self._task_started_at = time.monotonic()

    def check_task_timeout(self) -> Optional[Dict[str, Any]]:
        """检查是否超过总任务超时限制。

        Returns:
            None 表示尚未超时，dict 表示超时拒绝信息
        """
        if self._task_started_at is None:
            self._task_started_at = time.monotonic()
            return None

        elapsed = time.monotonic() - self._task_started_at
        if elapsed > self._task_timeout:
            logger.warning(f"[资源限制] 总任务超时: {elapsed:.1f}s > {self._task_timeout}s")
            return {
                "ok": False,
                "error": (
                    f"资源限制: 总任务执行时间 ({elapsed:.1f}s) 超过上限 "
                    f"({self._task_timeout}s)。任务已被终止。"
                ),
                "denied_by": "resource",
                "recoverable": True,
                "suggestion": "请将任务拆分为更小的子任务，减少单次调用的处理量。",
            }

        return None

    def get_cmd_timeout(self) -> int:
        """获取单命令超时秒数。"""
        return self._cmd_timeout

    def check_memory(self, limit_mb: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """检查当前进程内存是否超限。

        注意：Python 层面难以精确控制内存限制，
        此方法使用 psutil（如果可用）进行进程级内存监控。
        """
        limit = limit_mb or self._memory_limit_mb
        try:
            import psutil
            proc = psutil.Process()
            mem_info = proc.memory_info()
            used_mb = mem_info.rss / (1024 * 1024)

            if used_mb > limit:
                logger.warning(f"[资源限制] 内存超限: {used_mb:.1f}MB > {limit}MB")
                return {
                    "ok": False,
                    "error": (
                        f"资源限制: 当前内存使用 ({used_mb:.1f}MB) 超过上限 "
                        f"({limit}MB)。请减少数据处理量。"
                    ),
                    "denied_by": "resource",
                    "recoverable": True,
                    "suggestion": f"当前内存使用 {used_mb:.1f}MB，上限 {limit}MB。请优化内存使用。",
                }
        except ImportError:
            # psutil 不可用，跳过内存检查
            pass
        except Exception as e:
            logger.debug(f"内存检查失败: {e}")

        return None

    async def execute_with_limits(
        self,
        coro,
        timeout: Optional[int] = None,
    ) -> Any:
        """在资源限制下执行异步协程。

        Args:
            coro: 要执行的协程
            timeout: 覆盖默认超时（秒）

        Returns:
            协程返回值

        Raises:
            asyncio.TimeoutError: 超时
        """
        cmd_timeout = timeout or self._cmd_timeout
        return await asyncio.wait_for(coro, timeout=cmd_timeout)

    def build_timeout_error(self, elapsed_s: float) -> Dict[str, Any]:
        """构建超时错误响应。"""
        return {
            "ok": False,
            "error": (
                f"资源限制: 命令执行超时 ({elapsed_s:.1f}s > {self._cmd_timeout}s)。"
            ),
            "denied_by": "resource",
            "recoverable": True,
            "suggestion": (
                f"单命令超时限制为 {self._cmd_timeout}s。"
                f"请减少单次处理的数据量或使用更高效的命令。"
            ),
        }


# 全局默认实例
_default_limiter: Optional[ResourceLimiter] = None


def get_resource_limiter() -> Optional[ResourceLimiter]:
    """获取当前 ResourceLimiter 实例。"""
    return _default_limiter


def set_resource_limiter(limiter: ResourceLimiter) -> None:
    """设置全局 ResourceLimiter 实例。"""
    global _default_limiter
    _default_limiter = limiter
