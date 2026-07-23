"""bilibili-toolkit-builtin 调度模块。

提供下载任务的调度触发器抽象与 ``DownloadScheduler`` 调度器实现。

模块组成：

- :mod:`trigger` - :class:`Trigger` 抽象与 :class:`IntervalTrigger` /
  :class:`CronTrigger` 子类，等价 Rust ``Trigger`` 枚举。
- :mod:`scheduler` - :class:`DownloadScheduler` 基于 APScheduler 4.x，
  配置变更时动态重建 Job。

复用 Open-AwA 既有依赖：``apscheduler>=4.0.0a1,<5.0.dev0``
（与 ``core/scheduled_task_manager.py`` 一致）。
"""

from __future__ import annotations

from plugins.bilibili_toolkit_builtin.scheduler.scheduler import DownloadScheduler
from plugins.bilibili_toolkit_builtin.scheduler.trigger import (
    CronTrigger,
    IntervalTrigger,
    Trigger,
    parse_trigger,
)

__all__ = [
    "DownloadScheduler",
    "Trigger",
    "IntervalTrigger",
    "CronTrigger",
    "parse_trigger",
]
