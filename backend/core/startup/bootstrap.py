"""
启动流程编排器。
按 BLOCKING → (ready) → WARMUP 的顺序执行启动任务，
支持开发快速启动 profile。
"""
import asyncio
import os
from typing import Optional

from loguru import logger

from core.startup.profiler import StartupProfiler
from core.startup.tasks import StartupTier, StartupTask

# 开发快启模式环境变量
ENV_DEV_FAST_START = "DEV_FAST_START"


def is_dev_fast_start() -> bool:
    """是否开启了开发快速启动模式。"""
    return os.getenv(ENV_DEV_FAST_START, "").lower() in ("1", "true", "yes")


async def run_startup(tasks: list[StartupTask], profiler: StartupProfiler) -> None:
    """
    编排启动流程：
    1. 过滤：dev_fast 模式下跳过标记为 skip_in_dev_fast 的任务
    2. 按 tier 分层执行
    3. BLOCKING 任务按依赖顺序执行完毕后，服务 ready
    4. WARMUP 任务在后台异步执行
    """
    dev_fast = is_dev_fast_start()
    if dev_fast:
        logger.bind(event="startup_mode", module="startup").info("开发快速启动模式已启用")

    # 过滤任务
    active_tasks: list[StartupTask] = []
    for task in tasks:
        if task.requires_db and os.getenv("SKIP_INIT_DB"):
            continue
        if dev_fast and task.skip_in_dev_fast:
            logger.bind(event="startup_skip", module="startup", task=task.name).info(
                f"开发快启模式，跳过任务: {task.name}"
            )
            continue
        active_tasks.append(task)

    blocking = [t for t in active_tasks if t.tier == StartupTier.BLOCKING]
    warmup = [t for t in active_tasks if t.tier == StartupTier.WARMUP]

    # 执行 BLOCKING 任务（拓扑排序按依赖）
    completed: set[str] = set()

    async def execute_blocking(task: StartupTask) -> None:
        for dep in task.depends_on:
            if dep not in completed:
                raise RuntimeError(
                    f"任务 {task.name} 依赖 {dep} 但 {dep} 未完成或未定义为 BLOCKING"
                )
        with profiler.step(task.name):
            await task.coro()
        completed.add(task.name)

    # 简单的拓扑执行：多轮扫描直到全部完成
    remaining = list(blocking)
    while remaining:
        ready = [t for t in remaining if all(d in completed for d in t.depends_on)]
        if not ready:
            # 存在未满足依赖或循环依赖
            unresolved = [t.name for t in remaining]
            raise RuntimeError(f"无法解析的启动任务依赖: {unresolved}")
        # BLOCKING 任务串行执行以保证确定性
        for task in ready:
            await execute_blocking(task)
        remaining = [t for t in remaining if t.name not in completed]

    logger.bind(event="startup_ready", module="startup").info("核心启动完成，服务已就绪")

    # WARMUP 任务后台执行（不阻塞）
    if warmup:
        async def run_warmup() -> None:
            for task in warmup:
                try:
                    with profiler.step(f"warmup:{task.name}"):
                        await task.coro()
                except Exception as exc:
                    logger.bind(event="startup_warmup_error", module="startup", task=task.name).warning(
                        f"后台预热任务 {task.name} 失败: {exc}"
                    )

        asyncio.create_task(run_warmup())
