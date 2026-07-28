"""下载任务调度器，等价 Rust bili-sync 的 ``tokio-cron-scheduler`` 集成。

Rust 参考实现使用 ``tokio_cron_scheduler::JobScheduler`` 注册 cron job，
通过 ``VersionedConfig::watch`` 通道监听配置变更，热重建调度。

Python 等价实现：

- 基于 APScheduler 4.x 的 :class:`apscheduler.AsyncScheduler`（复用 Open-AwA
  既有依赖，与 ``core/scheduled_task_manager.py`` 一致），使用默认
  ``MemoryDataStore``（不污染数据库）。
- 配置变更（:class:`~plugins.bilibili_toolkit_builtin.config.VersionedConfig`）
  时，自动移除旧 Job 并根据新 ``trigger`` 配置注册新 Job。

调度器启动流程：

1. :meth:`DownloadScheduler.start` 启动 APScheduler 与初始 Job。
2. 后台 :meth:`_watch_config_changes` 协程监听 ``VersionedConfig`` 变更。
3. 收到变更通知后调用 :meth:`_rebuild_job` 重建 Job。

阶段 12 仅实现调度框架，``_execute_download`` 留空，实际下载逻辑由阶段 14
的 ``workflow/pipeline.py`` 注入。
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

from apscheduler import AsyncScheduler, ScheduleLookupError
from apscheduler._enums import ConflictPolicy
from loguru import logger

from plugins.bilibili_toolkit_builtin.config import VersionedConfig
from plugins.bilibili_toolkit_builtin.scheduler.trigger import (
    Trigger,
    parse_trigger,
)


# 调度器内 APScheduler schedule 的固定 id（单 Job 模式，热重建时复用同一 id）
_SCHEDULE_ID: str = "bilibili_toolkit_download_schedule"


class DownloadScheduler:
    """下载任务调度器，等价 Rust ``tokio-cron-scheduler``。

    基于 APScheduler ``AsyncScheduler``，配置变更时动态重建 Job。
    单 Job 模式：同一时间只有一个下载任务调度，避免并发扫描叠加。

    Attributes:
        _config_manager: 配置管理器，提供当前配置与变更通知。
        _scheduler: APScheduler 4.x 异步调度器实例（默认 ``MemoryDataStore``）。
        _current_job_id: 当前注册的 schedule id，未注册时为 ``None``。
        _lock: 保护 ``_rebuild_job`` 等操作的异步锁，避免并发重建竞态。
        _watch_task: 后台监听配置变更的 ``asyncio.Task``，停止时取消。
        _started: 调度器是否已启动，避免重复 ``start``。
    """

    def __init__(self, config_manager: VersionedConfig) -> None:
        """初始化下载调度器。

        Args:
            config_manager: 配置管理器实例，用于读取 trigger 配置与监听变更。
        """
        self._config_manager: VersionedConfig = config_manager
        # APScheduler 4.x 默认使用 MemoryDataStore，不污染主数据库
        self._scheduler: AsyncScheduler = AsyncScheduler()
        self._current_job_id: Optional[str] = None
        self._lock: asyncio.Lock = asyncio.Lock()
        self._watch_task: Optional[asyncio.Task[None]] = None
        self._started: bool = False

    async def start(self) -> None:
        """启动调度器。

        步骤：
        1. 进入 ``AsyncScheduler`` 上下文（初始化 data store）。
        2. 后台启动调度器。
        3. 注册初始 Job（根据当前 trigger 配置）。
        4. 启动配置变更监听协程。

        幂等：重复调用 ``start`` 直接返回，不重复初始化。
        """
        if self._started:
            return

        # 初始化 APScheduler data store（MemoryDataStore 自动建表）
        await self._scheduler.__aenter__()
        # 后台启动调度器，避免阻塞调用方事件循环
        await self._scheduler.start_in_background()
        self._started = True

        # 注册初始 Job
        await self._rebuild_job()

        # 启动配置变更监听协程
        self._watch_task = asyncio.create_task(
            self._watch_config_changes(),
            name="bilibili_toolkit_config_watcher",
        )

        logger.bind(
            event="bilibili_toolkit_scheduler_started",
            module="bilibili_toolkit",
        ).info("bilibili toolkit download scheduler started")

    async def stop(self) -> None:
        """停止调度器。

        取消配置变更监听协程，移除已注册 Job，并退出 ``AsyncScheduler`` 上下文
        释放资源。
        """
        if not self._started:
            return

        # 取消配置变更监听协程
        if self._watch_task is not None:
            self._watch_task.cancel()
            try:
                await self._watch_task
            except asyncio.CancelledError:
                # 取消监听协程是预期行为，静默吞掉 CancelledError
                pass
            except Exception as exc:  # noqa: BLE001 - 监听协程异常不阻塞停止
                logger.bind(
                    event="bilibili_toolkit_scheduler_watch_cancel_error",
                    module="bilibili_toolkit",
                    error_type=type(exc).__name__,
                ).warning(f"config watcher cancel failed: {exc}")
            self._watch_task = None

        # 移除当前 Job（若存在），避免调度器停止后残留 schedule
        await self._remove_current_job()

        # 退出 AsyncScheduler 上下文
        try:
            await self._scheduler.__aexit__(None, None, None)
        except Exception as exc:  # noqa: BLE001 - 停止失败不传播
            logger.bind(
                event="bilibili_toolkit_scheduler_stop_error",
                module="bilibili_toolkit",
                error_type=type(exc).__name__,
            ).warning(f"download scheduler stop failed: {exc}")

        self._started = False
        logger.bind(
            event="bilibili_toolkit_scheduler_stopped",
            module="bilibili_toolkit",
        ).info("bilibili toolkit download scheduler stopped")

    async def _rebuild_job(self) -> None:
        """根据当前配置重建 Job。

        步骤：
        1. 移除旧的 schedule（若存在）。
        2. 从 ``VersionedConfig`` 读取当前 trigger 配置。
        3. 解析为 :class:`Trigger` 并转换为 APScheduler trigger。
        4. 注册新 schedule，``conflict_policy=replace`` 保证幂等。

        若配置中无 ``trigger`` 字段或解析失败，记录 WARNING 但不抛异常，
        调度器仍以无 Job 状态运行（等待下次配置变更恢复）。
        """
        # 移除旧 Job
        await self._remove_current_job()

        config = self._config_manager.get_config()
        trigger_config = config.get("trigger")
        if not trigger_config:
            logger.bind(
                event="bilibili_toolkit_scheduler_no_trigger",
                module="bilibili_toolkit",
            ).warning("config has no 'trigger' field, scheduler runs without job")
            return

        try:
            trigger: Trigger = parse_trigger(trigger_config)
            ap_trigger = trigger.to_ap_scheduler_trigger()
        except (ValueError, TypeError) as exc:
            logger.bind(
                event="bilibili_toolkit_scheduler_trigger_parse_error",
                module="bilibili_toolkit",
                error_type=type(exc).__name__,
            ).warning(f"failed to parse trigger config: {exc}")
            return

        try:
            await self._scheduler.add_schedule(
                self._execute_download,
                ap_trigger,
                id=_SCHEDULE_ID,
                conflict_policy=ConflictPolicy.replace,
            )
            self._current_job_id = _SCHEDULE_ID
            logger.bind(
                event="bilibili_toolkit_scheduler_job_registered",
                module="bilibili_toolkit",
                trigger_repr=repr(trigger),
            ).info(f"download schedule registered: {trigger}")
        except Exception as exc:  # noqa: BLE001 - add_schedule 异常不阻塞调度器
            logger.bind(
                event="bilibili_toolkit_scheduler_register_error",
                module="bilibili_toolkit",
                error_type=type(exc).__name__,
            ).warning(f"failed to register download schedule: {exc}")

    async def _remove_current_job(self) -> None:
        """移除当前已注册的 schedule（若存在）。

        schedule 不存在时静默忽略 ``ScheduleLookupError``。
        """
        if self._current_job_id is None:
            return
        try:
            await self._scheduler.remove_schedule(self._current_job_id)
        except ScheduleLookupError:
            # schedule 已不存在（可能被其他路径移除），静默忽略
            pass
        except Exception as exc:  # noqa: BLE001 - 移除异常不阻塞重建
            logger.bind(
                event="bilibili_toolkit_scheduler_remove_error",
                module="bilibili_toolkit",
                error_type=type(exc).__name__,
            ).warning(f"failed to remove schedule: {exc}")
        finally:
            self._current_job_id = None

    async def _watch_config_changes(self) -> None:
        """监听配置变更，触发重建。

        循环等待 ``VersionedConfig.wait_for_change``，收到变更通知后
        加锁重建 Job。60 秒超时作为兜底轮询，避免 Event 信号丢失导致
        调度器无法恢复（虽然概率极低）。
        """
        while True:
            try:
                changed = await self._config_manager.wait_for_change(timeout=60)
            except asyncio.CancelledError:
                # 停止调度器时主动取消，正常退出循环
                raise
            except Exception as exc:  # noqa: BLE001 - 等待异常不退出监听循环
                logger.bind(
                    event="bilibili_toolkit_scheduler_watch_error",
                    module="bilibili_toolkit",
                    error_type=type(exc).__name__,
                ).warning(f"wait_for_change failed: {exc}")
                # 短暂退避后重试，避免异常导致监听协程退出
                await asyncio.sleep(5)
                continue

            if not changed:
                # 超时未收到变更，继续下一轮等待
                continue

            async with self._lock:
                try:
                    await self._rebuild_job()
                except Exception as exc:  # noqa: BLE001 - 重建异常不退出循环
                    logger.bind(
                        event="bilibili_toolkit_scheduler_rebuild_error",
                        module="bilibili_toolkit",
                        error_type=type(exc).__name__,
                    ).warning(f"rebuild_job failed: {exc}")

    async def _execute_download(self, *args: Any, **kwargs: Any) -> None:
        """单轮下载任务执行入口。

        由 APScheduler 在 trigger 触发时调用，负责：
        1. 读取当前 ``VersionedConfig`` 获取订阅列表与下载配置。
        2. 调用 ``sources/`` 各订阅源扫描新视频。
        3. 对每个新视频调用 ``workflow/pipeline.py`` 执行 5 路并发子任务
           （封面 / 视频 / NFO / 弹幕 / 字幕）。
        4. 风控信号触发时立即终止本轮，等待下轮重试。

        阶段 12 仅实现调度框架，实际下载逻辑由阶段 14
        ``workflow/pipeline.py`` 注入。当前留空仅记录 INFO 日志，
        便于调度器独立验证触发是否生效。
        """
        logger.bind(
            event="bilibili_toolkit_download_tick",
            module="bilibili_toolkit",
            config_version=self._config_manager.version,
        ).info("download tick triggered (phase 12 placeholder, phase 14 will inject workflow)")
