"""
启动阶段耗时采集器。
记录每个启动步骤的名称、耗时、是否成功，启动完成后输出汇总日志。
"""
import time
from typing import Optional

from loguru import logger


class StartupProfiler:
    """启动耗时采集器，非生产环境输出明细耗时。"""

    def __init__(self) -> None:
        self._records: list[dict] = []
        self._started_at: Optional[float] = None

    def start(self) -> None:
        """开始记录。"""
        self._started_at = time.monotonic()
        logger.bind(event="startup_begin", module="startup").info("启动流程开始")

    def step(self, name: str) -> "StepTimer":
        """返回一个上下文管理器，自动记录该步骤耗时。"""
        return StepTimer(name, self._records)

    def finish(self) -> None:
        """输出汇总。"""
        total = time.monotonic() - (self._started_at or time.monotonic())
        logger.bind(
            event="startup_complete",
            module="startup",
            total_s=round(total, 3),
            steps=[{"name": r["name"], "elapsed_ms": round(r["elapsed_ms"], 1), "ok": r["ok"]} for r in self._records],
        ).info(f"启动流程完成，耗时 {total:.2f}s，共 {len(self._records)} 步")


class StepTimer:
    """单个步骤计时器，作为上下文管理器使用。"""

    def __init__(self, name: str, records: list[dict]) -> None:
        self._name = name
        self._records = records
        self._start: float = 0.0
        self._ok = True

    def __enter__(self) -> "StepTimer":
        self._start = time.monotonic()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        elapsed_ms = (time.monotonic() - self._start) * 1000
        self._ok = exc_type is None
        self._records.append({
            "name": self._name,
            "elapsed_ms": elapsed_ms,
            "ok": self._ok,
        })
        status = "ok" if self._ok else f"failed ({exc_type.__name__ if exc_type else '?'})"
        logger.bind(
            event="startup_step", module="startup", step=self._name,
            elapsed_ms=round(elapsed_ms, 1), status=status
        ).debug(f"启动步骤 [{self._name}]: {elapsed_ms:.1f}ms {status}")
        return False  # 不吞异常
