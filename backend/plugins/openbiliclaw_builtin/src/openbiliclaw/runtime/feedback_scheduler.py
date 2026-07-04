"""对昂贵的反馈批量学习做防抖调度。"""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class FeedbackBatchScheduler:
    """把推荐反馈的爆发合并成一次批量刷新。"""

    soul_engine: Any
    debounce_seconds: float = 5.0
    _dirty: bool = field(default=False, init=False)
    _closed: bool = field(default=False, init=False)
    _task: asyncio.Task[None] | None = field(default=None, init=False)

    def schedule(self) -> None:
        """在防抖窗口之后请求一次反馈批处理。"""
        if self._closed:
            return
        self._dirty = True
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())

    async def drain(self) -> None:
        """等待当前已调度的一轮（如有）。

        主要用于测试和优雅关闭。它本身不会创建工作；调用方应先
        调用 :meth:`schedule`。
        """
        task = self._task
        if task is None:
            return
        await task

    async def close(self) -> None:
        """取消所有挂起的已调度工作。"""
        self._closed = True
        task = self._task
        if task is None or task.done():
            return
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    async def _run(self) -> None:
        while not self._closed:
            delay = max(0.0, float(self.debounce_seconds))
            if delay > 0:
                await asyncio.sleep(delay)
            self._dirty = False
            process = getattr(self.soul_engine, "process_feedback_batch_if_needed", None)
            if callable(process):
                try:
                    await process()
                except Exception:
                    logger.exception("post-feedback batch processing failed")
            if not self._dirty:
                return
