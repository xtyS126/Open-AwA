"""调度触发器抽象，等价 Rust bili-sync 的 ``Trigger`` 枚举。

Rust 参考实现定义：

```rust
pub enum Trigger {
    Interval(u64),
    Cron(String),
}
```

Python 等价实现使用抽象基类 + 两个具体子类：

- :class:`IntervalTrigger` - 固定间隔触发（秒）
- :class:`CronTrigger` - cron 表达式触发（5 字段：分 时 日 月 周）

每个子类实现 :meth:`Trigger.to_ap_scheduler_trigger`，将自身转换为
APScheduler 4.x 的 ``BaseTrigger`` 子类，供 :class:`DownloadScheduler`
注册到 ``AsyncScheduler`` 使用。

复用 Open-AwA 既有依赖：``apscheduler>=4.0.0a1,<5.0.dev0``
（见 ``backend/requirements.txt``），与 ``core/scheduled_task_manager.py``
使用的版本一致。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class Trigger(ABC):
    """调度触发器抽象基类。

    所有触发器必须实现 :meth:`to_ap_scheduler_trigger`，将自身转换为
    APScheduler 4.x 的 ``BaseTrigger`` 子类实例。

    设计动机：屏蔽 APScheduler trigger 类型细节，让 :class:`DownloadScheduler`
    只依赖 :class:`Trigger` 抽象，便于后续扩展新触发器类型（如 DateTrigger）。
    """

    @abstractmethod
    def to_ap_scheduler_trigger(self) -> Any:
        """转换为 APScheduler Trigger 对象。

        Returns:
            APScheduler 4.x ``BaseTrigger`` 子类实例。
        """


class IntervalTrigger(Trigger):
    """间隔触发器。

    按固定秒数间隔触发调度。等价 Rust ``Trigger::Interval(u64)``。

    Attributes:
        seconds: 触发间隔（秒）。
    """

    def __init__(self, seconds: int) -> None:
        """初始化间隔触发器。

        Args:
            seconds: 触发间隔秒数，必须为正整数。
        """
        if not isinstance(seconds, int) or seconds <= 0:
            raise ValueError(
                f"IntervalTrigger.seconds 必须为正整数，实际收到: {seconds!r}"
            )
        self.seconds: int = seconds

    def to_ap_scheduler_trigger(self) -> Any:
        """转换为 APScheduler ``IntervalTrigger`` 对象。"""
        # 局部导入避免模块加载时强依赖 apscheduler（便于在无该依赖的环境做类型检查）
        from apscheduler.triggers.interval import (
            IntervalTrigger as APIntervalTrigger,
        )

        return APIntervalTrigger(seconds=self.seconds)

    def __repr__(self) -> str:
        return f"IntervalTrigger(seconds={self.seconds})"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, IntervalTrigger) and other.seconds == self.seconds


class CronTrigger(Trigger):
    """Cron 表达式触发器。

    支持标准 5 字段 cron 表达式（分 时 日 月 周），等价 Rust
    ``Trigger::Cron(String)``。例如 ``"0 0 * * *"`` 表示每天 0 点触发。

    Attributes:
        expr: 5 字段 cron 表达式字符串。
    """

    def __init__(self, expr: str) -> None:
        """初始化 cron 触发器。

        Args:
            expr: 5 字段 cron 表达式，例如 ``"0 0 * * *"``。
        """
        if not isinstance(expr, str) or not expr.strip():
            raise ValueError(
                f"CronTrigger.expr 必须为非空字符串，实际收到: {expr!r}"
            )
        # 校验 cron 表达式格式：5 个空白分隔字段
        parts = expr.split()
        if len(parts) != 5:
            raise ValueError(
                f"cron 表达式必须为 5 字段（分 时 日 月 周），实际收到 {len(parts)} 字段: {expr!r}"
            )
        self.expr: str = expr

    def to_ap_scheduler_trigger(self) -> Any:
        """转换为 APScheduler ``CronTrigger`` 对象。

        通过 ``CronTrigger.from_crontab`` 解析 5 字段 cron 表达式，
        与 ``core/scheduled_task_manager.py`` 使用相同的解析方式。
        时区固定为 UTC，与项目其他模块时间基准一致。
        """
        from apscheduler.triggers.cron import CronTrigger as APCronTrigger

        return APCronTrigger.from_crontab(self.expr, timezone="UTC")

    def __repr__(self) -> str:
        return f"CronTrigger(expr={self.expr!r})"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, CronTrigger) and other.expr == self.expr


def parse_trigger(config: dict) -> Trigger:
    """从配置 dict 解析触发器。

    配置格式：

    - 间隔触发器: ``{"type": "interval", "seconds": 1200}``
    - cron 触发器: ``{"type": "cron", "expr": "0 0 * * *"}``

    Args:
        config: 触发器配置字典。

    Returns:
        :class:`IntervalTrigger` 或 :class:`CronTrigger` 实例。

    Raises:
        ValueError: 配置格式不合法或 ``type`` 字段未知。
    """
    if not isinstance(config, dict):
        raise ValueError(
            f"trigger 配置必须为 dict，实际收到: {type(config).__name__}"
        )

    trigger_type = config.get("type")
    if trigger_type == "interval":
        seconds = config.get("seconds")
        if seconds is None:
            raise ValueError(
                "interval 触发器缺少 'seconds' 字段"
            )
        return IntervalTrigger(int(seconds))
    if trigger_type == "cron":
        expr = config.get("expr")
        if not expr:
            raise ValueError(
                "cron 触发器缺少 'expr' 字段"
            )
        return CronTrigger(str(expr))

    raise ValueError(
        f"未知触发器类型: {trigger_type!r}，支持 'interval' / 'cron'"
    )
