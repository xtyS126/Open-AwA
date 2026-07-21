"""
启动编排器测试模块。
验证 BLOCKING 任务的并行执行、依赖串行保持、循环依赖检测以及 profiler 记录行为。
"""

import asyncio
import sys
import time
from pathlib import Path
from typing import Awaitable, Callable

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.startup.bootstrap import run_startup
from core.startup.profiler import StartupProfiler
from core.startup.tasks import StartupTask, StartupTier


def make_task(
    name: str,
    coro: Callable[[], Awaitable[None]],
    depends_on: list[str] | None = None,
    tier: StartupTier = StartupTier.BLOCKING,
) -> StartupTask:
    """构造启动任务辅助函数，统一关闭 requires_db 与 skip_in_dev_fast 以隔离测试。"""
    return StartupTask(
        name=name,
        tier=tier,
        coro=coro,
        depends_on=depends_on or [],
        requires_db=False,
        skip_in_dev_fast=False,
    )


def make_recording_coro(
    name: str, delay: float, timeline: dict[str, list[float]]
) -> Callable[[], Awaitable[None]]:
    """构造记录开始/结束时间戳的协程工厂，用于断言并行或串行执行区间。"""

    async def coro() -> None:
        start = time.monotonic()
        timeline[name] = [start]
        await asyncio.sleep(delay)
        timeline[name].append(time.monotonic())

    return coro


async def test_parallel_execution_of_independent_tasks() -> None:
    """验证两个无依赖的任务在同一 ready 批次内并行执行（执行区间存在重叠）。"""
    timeline: dict[str, list[float]] = {}
    tasks = [
        make_task("task_a", make_recording_coro("task_a", 0.1, timeline)),
        make_task("task_b", make_recording_coro("task_b", 0.1, timeline)),
    ]
    profiler = StartupProfiler()
    await run_startup(tasks, profiler)

    a_start, a_end = timeline["task_a"]
    b_start, b_end = timeline["task_b"]
    # 并行执行：两任务区间应重叠（B 在 A 结束前开始，A 在 B 结束前开始）
    assert b_start < a_end, "无依赖任务应并行执行，区间应重叠"
    assert a_start < b_end


async def test_serial_execution_with_dependencies() -> None:
    """验证有依赖关系的任务串行执行（B 依赖 A，B 在 A 完成后才开始）。"""
    timeline: dict[str, list[float]] = {}
    tasks = [
        make_task("task_a", make_recording_coro("task_a", 0.05, timeline)),
        make_task(
            "task_b",
            make_recording_coro("task_b", 0.05, timeline),
            depends_on=["task_a"],
        ),
    ]
    profiler = StartupProfiler()
    await run_startup(tasks, profiler)

    a_start, a_end = timeline["task_a"]
    b_start, b_end = timeline["task_b"]
    # 串行执行：B 在 A 结束后才开始
    assert b_start >= a_end, "有依赖的任务应在依赖完成后才开始"


async def test_mixed_parallel_and_serial() -> None:
    """验证混合场景：A、B 并行，C 依赖 A 和 B，C 在两者完成后执行。"""
    timeline: dict[str, list[float]] = {}
    tasks = [
        make_task("task_a", make_recording_coro("task_a", 0.1, timeline)),
        make_task("task_b", make_recording_coro("task_b", 0.1, timeline)),
        make_task(
            "task_c",
            make_recording_coro("task_c", 0.05, timeline),
            depends_on=["task_a", "task_b"],
        ),
    ]
    profiler = StartupProfiler()
    await run_startup(tasks, profiler)

    a_start, a_end = timeline["task_a"]
    b_start, b_end = timeline["task_b"]
    c_start, c_end = timeline["task_c"]
    # A 与 B 并行（区间重叠）
    assert b_start < a_end and a_start < b_end
    # C 在 A、B 都完成后才开始
    assert c_start >= a_end and c_start >= b_end


async def test_dependency_cycle_detection() -> None:
    """验证循环依赖会抛出 RuntimeError。"""

    async def noop() -> None:
        pass

    tasks = [
        make_task("task_a", noop, depends_on=["task_b"]),
        make_task("task_b", noop, depends_on=["task_a"]),
    ]
    profiler = StartupProfiler()
    with pytest.raises(RuntimeError, match="无法解析的启动任务依赖"):
        await run_startup(tasks, profiler)


async def test_profiler_records_all_tasks() -> None:
    """验证 profiler 记录所有执行过的任务。"""

    async def noop() -> None:
        pass

    tasks = [
        make_task("task_a", noop),
        make_task("task_b", noop, depends_on=["task_a"]),
        make_task("task_c", noop, depends_on=["task_a"]),
    ]
    profiler = StartupProfiler()
    await run_startup(tasks, profiler)

    recorded_names = {r["name"] for r in profiler._records}
    assert recorded_names == {"task_a", "task_b", "task_c"}
