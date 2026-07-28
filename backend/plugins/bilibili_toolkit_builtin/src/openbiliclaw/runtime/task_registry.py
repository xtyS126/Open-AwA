"""用于热重载时取消的后台任务注册表。

运行时会发起许多 ``asyncio.create_task(...)`` 调用来执行分离的
fire-and-forget 工作——各策略的预计算、预热助手、各事件触发器、手动
刷新句柄。当配置在运行时发生变化（``RuntimeContext.rebuild_from_config``）
时，过去只有顶层循环任务会被取消；分离任务仍持有对 *旧* runtime 对象的
引用继续运行，与刚构建好的 runtime 争夺 SQLite 写入和 LLM token，持续
数秒之久。

``BackgroundTaskRegistry`` 是每个分离任务都应流经的单一收口点。
``cancel_all`` 在 ``rebuild_from_config`` 的最顶部被 await，使新 runtime
从干净状态启动。

向后兼容说明：每个之前直接使用 ``asyncio.create_task`` 的调用方都继续
原样工作——注册表是可选接入的，没有注册表的代码路径会回退到裸
``create_task``，行为与之前完全一致。这样既保证现有测试套件不挂，也不
强制每个测试夹具都注入注册表。
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Coroutine

logger = logging.getLogger(__name__)


class BackgroundTaskRegistry:
    """跟踪 asyncio.create_task 派生任务，便于热重载时取消。

    runtime 派生的每个分离任务（预计算、预热、各事件触发器、刷新循环
    tick）都应通过 ``track`` 而非裸 ``asyncio.create_task``。在
    ``cancel_all`` 时，注册表会取消每个仍在运行的任务并等待其收尾。
    """

    def __init__(self) -> None:
        self._tasks: dict[asyncio.Task[Any], str] = {}

    def track(self, name: str, coro: Coroutine[Any, Any, Any]) -> asyncio.Task[Any]:
        """包装 ``asyncio.create_task`` 并记住返回的任务。

        任务通过 ``add_done_callback`` 在完成时自我注销，使注册表不会
        在长时间运行的守护进程中无限增长。
        """
        task = asyncio.create_task(coro, name=name)
        self._tasks[task] = name
        task.add_done_callback(lambda t: self._tasks.pop(t, None))
        return task

    async def cancel_all(
        self, *, grace_seconds: float = 1.5, exclude: frozenset[str] = frozenset()
    ) -> int:
        """取消已跟踪的任务，最多等待 ``grace_seconds`` 完成清理。

        ``exclude`` 是要保留运行（且仍跟踪）的任务名集合——用于配置驱动
        的 rebuild 不要杀掉 guided-init 任务（gui-init 规范 §5c）。返回
        实际被取消的任务数。
        """
        tasks = [t for t, name in self._tasks.items() if name not in exclude]
        for task in tasks:
            task.cancel()
        if tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*tasks, return_exceptions=True),
                    timeout=grace_seconds,
                )
            except TimeoutError:
                logger.warning(
                    "%d background task(s) did not exit within %.1fs of cancel",
                    sum(1 for t in tasks if not t.done()),
                    grace_seconds,
                )
        # 被取消任务的自注销回调可能尚未触发（特别是宽限超时命中时）。
        # 显式丢弃已取消的；排除的任务仍保持跟踪，便于后续可取消。
        for task in tasks:
            self._tasks.pop(task, None)
        return len(tasks)

    async def cancel(self, name: str, *, grace_seconds: float = 1.5) -> int:
        """取消所有以给定 ``name`` 跟踪的任务。返回取消数。

        用于停止单个具名后台任务（如 ``guided_init``）而不动其他任务
        （gui-init 规范 §5f）。
        """
        tasks = [t for t, n in self._tasks.items() if n == name]
        for task in tasks:
            task.cancel()
        if tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*tasks, return_exceptions=True),
                    timeout=grace_seconds,
                )
            except TimeoutError:
                logger.warning("task %r did not exit within %.1fs of cancel", name, grace_seconds)
        for task in tasks:
            self._tasks.pop(task, None)
        return len(tasks)

    def stats(self) -> dict[str, int]:
        """诊断：按名称前缀分组的实时任务计数。

        前缀是任务名中第一个 ``.`` 之前的部分（如
        ``"precompute_pool_copy"`` → ``"precompute_pool_copy"``，
        ``"refresh.manual"`` → ``"refresh"``）。未命名创建的任务归入
        ``"unknown"``。
        """
        counts: dict[str, int] = {}
        for name in self._tasks.values():
            key = name.split(".", 1)[0] if name else "unknown"
            counts[key] = counts.get(key, 0) + 1
        return counts
