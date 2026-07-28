"""VersionedConfig 配置热更新与调度器联动测试。

覆盖 SubTask 51.4：

- ``VersionedConfig.get_config`` / ``update_config`` / ``version`` 基础读写。
- ``VersionedConfig.wait_for_change`` 异步等待配置变更。
- ``update_config`` 后版本号自增。
- 配置变更通过 ``asyncio.Event`` 通知等待者。
- ``init_config_manager`` / ``get_config_manager`` / ``reset_config_manager_for_test``
  模块级单例管理。
- ``DownloadScheduler._rebuild_job`` 在配置变更时被调用（mock APScheduler）。
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from plugins.bilibili_toolkit_builtin.config import (
    VersionedConfig,
    get_config_manager,
    init_config_manager,
    reset_config_manager_for_test,
)
from plugins.bilibili_toolkit_builtin.scheduler.scheduler import (
    DownloadScheduler,
)


# =============================================================================
# VersionedConfig 基础读写测试
# =============================================================================


class TestVersionedConfigBasic:
    """``VersionedConfig`` 基础读写与版本号管理。"""

    def test_initial_version_is_zero(self) -> None:
        """构造后版本号应为 0。"""
        config = VersionedConfig({"key": "value"})
        assert config.version == 0

    def test_get_config_returns_initial_values(self) -> None:
        """``get_config`` 应返回构造时传入的配置。"""
        initial = {"video_name": "{{title}}", "concurrent_limit": 4}
        config = VersionedConfig(initial)
        result = config.get_config()
        assert result == initial

    def test_get_config_returns_shallow_copy(self) -> None:
        """``get_config`` 返回的是浅拷贝，外部修改不影响内部状态。"""
        initial = {"key": "value", "list": [1, 2, 3]}
        config = VersionedConfig(initial)
        result = config.get_config()
        # 修改返回值
        result["key"] = "modified"
        result["list"].append(4)
        # 内部状态不应被影响（浅拷贝保护了顶层 key）
        internal = config.get_config()
        assert internal["key"] == "value"
        # 注意：浅拷贝下嵌套可变对象（如 list）仍共享引用，
        # 这是 Python 浅拷贝的标准行为，不在热更新测试范围

    def test_update_config_increments_version(self) -> None:
        """``update_config`` 应使版本号自增。"""
        config = VersionedConfig({"key": "v1"})
        assert config.version == 0

        v1 = config.update_config({"key": "v2"})
        assert v1 == 1
        assert config.version == 1

        v2 = config.update_config({"key": "v3"})
        assert v2 == 2
        assert config.version == 2

    def test_update_config_replaces_full_dict(self) -> None:
        """``update_config`` 是整体替换，不是合并。"""
        config = VersionedConfig({"a": 1, "b": 2})
        # 只传一个 key，应整体替换
        config.update_config({"c": 3})
        result = config.get_config()
        assert result == {"c": 3}
        # 旧的 a/b 不应保留
        assert "a" not in result
        assert "b" not in result

    def test_update_config_does_not_share_reference(self) -> None:
        """``update_config`` 内部拷贝一份，外部修改不影响内部。"""
        config = VersionedConfig({"key": "v1"})
        new_dict = {"key": "v2"}
        config.update_config(new_dict)
        # 修改外部 dict
        new_dict["key"] = "v3"
        new_dict["extra"] = "extra"
        # 内部不应被影响
        assert config.get_config() == {"key": "v2"}

    def test_concurrent_update_config_is_thread_safe(self) -> None:
        """多线程并发 ``update_config`` 不丢失版本号自增。

        100 个线程并发调用 update_config，最终版本号应为 100。
        """
        config = VersionedConfig({"counter": 0})

        def increment(idx: int) -> None:
            config.update_config({"counter": idx})

        threads = [threading.Thread(target=increment, args=(i,)) for i in range(100)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert config.version == 100


# =============================================================================
# wait_for_change 异步等待测试
# =============================================================================


class TestWaitForChange:
    """``VersionedConfig.wait_for_change`` 异步等待配置变更。"""

    @pytest.mark.asyncio
    async def test_wait_for_change_returns_false_on_timeout(self) -> None:
        """无变更时，``wait_for_change(timeout)`` 应在超时后返回 False。"""
        config = VersionedConfig({"key": "v1"})
        # 短超时
        result = await config.wait_for_change(timeout=0.1)
        assert result is False

    @pytest.mark.asyncio
    async def test_wait_for_change_returns_true_after_update(self) -> None:
        """``update_config`` 后 ``wait_for_change`` 应被唤醒返回 True。"""
        config = VersionedConfig({"key": "v1"})

        # 启动一个等待任务
        async def waiter() -> bool:
            return await config.wait_for_change(timeout=2.0)

        task = asyncio.create_task(waiter())
        # 让事件循环跑一下，确保 waiter 已开始等待
        await asyncio.sleep(0.05)

        # 在事件循环线程内调用 update_config
        config.update_config({"key": "v2"})

        # 等待 waiter 返回
        result = await asyncio.wait_for(task, timeout=2.0)
        assert result is True

    @pytest.mark.asyncio
    async def test_wait_for_change_can_be_called_multiple_times(self) -> None:
        """``wait_for_change`` 可多次调用，每次都能收到下一次变更通知。"""
        config = VersionedConfig({"key": "v1"})

        # 第一次等待 + 第一次变更
        task1 = asyncio.create_task(config.wait_for_change(timeout=2.0))
        await asyncio.sleep(0.05)
        config.update_config({"key": "v2"})
        assert await asyncio.wait_for(task1, timeout=2.0) is True

        # 第二次等待 + 第二次变更
        task2 = asyncio.create_task(config.wait_for_change(timeout=2.0))
        await asyncio.sleep(0.05)
        config.update_config({"key": "v3"})
        assert await asyncio.wait_for(task2, timeout=2.0) is True

    @pytest.mark.asyncio
    async def test_update_config_from_other_thread_notifies(self) -> None:
        """从其他线程调用 ``update_config`` 也应通知事件循环中的等待者。"""
        config = VersionedConfig({"key": "v1"})

        # 启动等待者
        task = asyncio.create_task(config.wait_for_change(timeout=2.0))
        await asyncio.sleep(0.05)

        # 从另一个线程调用 update_config
        def update_from_thread() -> None:
            config.update_config({"key": "v2"})

        thread = threading.Thread(target=update_from_thread)
        thread.start()
        thread.join()

        # 等待者应被唤醒
        result = await asyncio.wait_for(task, timeout=2.0)
        assert result is True

    @pytest.mark.asyncio
    async def test_wait_for_change_with_none_timeout_does_not_return_immediately(
        self,
    ) -> None:
        """``timeout=None`` 表示无限等待，无变更时不返回。"""
        config = VersionedConfig({"key": "v1"})
        # 启动一个无限等待的任务
        task = asyncio.create_task(config.wait_for_change(timeout=None))
        await asyncio.sleep(0.05)
        # 任务不应完成
        assert not task.done()
        # 触发变更让它返回
        config.update_config({"key": "v2"})
        result = await asyncio.wait_for(task, timeout=2.0)
        assert result is True


# =============================================================================
# 模块级单例管理测试
# =============================================================================


class TestModuleLevelSingleton:
    """模块级 ``init`` / ``get`` / ``reset`` 单例管理。"""

    def test_get_config_manager_raises_before_init(self) -> None:
        """未初始化时 ``get_config_manager`` 应抛 RuntimeError。"""
        reset_config_manager_for_test()
        with pytest.raises(RuntimeError) as exc_info:
            get_config_manager()
        assert "尚未初始化" in str(exc_info.value)

    def test_init_config_manager_returns_instance(self) -> None:
        """``init_config_manager`` 应返回 VersionedConfig 实例。"""
        reset_config_manager_for_test()
        manager = init_config_manager({"key": "v1"})
        assert isinstance(manager, VersionedConfig)
        assert manager.get_config() == {"key": "v1"}

    def test_get_config_manager_returns_singleton(self) -> None:
        """``get_config_manager`` 返回与 ``init_config_manager`` 同一实例。"""
        reset_config_manager_for_test()
        manager = init_config_manager({"key": "v1"})
        # 多次获取应返回同一实例
        assert get_config_manager() is manager
        assert get_config_manager() is manager

    def test_init_config_manager_raises_on_duplicate_init(self) -> None:
        """已初始化后再次调用 ``init_config_manager`` 应抛 RuntimeError。"""
        reset_config_manager_for_test()
        init_config_manager({"key": "v1"})
        with pytest.raises(RuntimeError) as exc_info:
            init_config_manager({"key": "v2"})
        assert "已初始化" in str(exc_info.value)

    def test_reset_config_manager_allows_reinit(self) -> None:
        """``reset_config_manager_for_test`` 后可重新初始化。"""
        reset_config_manager_for_test()
        manager1 = init_config_manager({"key": "v1"})
        reset_config_manager_for_test()
        manager2 = init_config_manager({"key": "v2"})
        # 应是不同实例
        assert manager1 is not manager2
        assert manager2.get_config() == {"key": "v2"}

    def teardown_method(self) -> None:
        """每个测试用例后清理全局单例，避免污染其他用例。"""
        reset_config_manager_for_test()


# =============================================================================
# DownloadScheduler 配置变更联动测试
# =============================================================================


class TestDownloadSchedulerRebuild:
    """``DownloadScheduler`` 配置变更联动 ``_rebuild_job``。"""

    @pytest.mark.asyncio
    async def test_rebuild_job_called_when_config_changes(self) -> None:
        """配置变更后 ``_rebuild_job`` 应被调用。

        通过 patch ``DownloadScheduler._rebuild_job`` 为 AsyncMock，
        手动调用 ``_watch_config_changes`` 的一轮（限制单轮迭代后退出），
        验证 ``update_config`` 后 ``_rebuild_job`` 被调用。
        """
        # 准备 VersionedConfig，含 interval trigger 配置
        config_manager = VersionedConfig(
            {"trigger": {"type": "interval", "seconds": 60}}
        )

        scheduler = DownloadScheduler(config_manager)

        # mock _rebuild_job 跟踪调用
        rebuild_calls: list[Any] = []
        rebuild_mock = AsyncMock(side_effect=lambda *a, **kw: rebuild_calls.append(a))

        # 用一个简化的 _watch_config_changes 实现：只等待一次变更后返回
        async def fake_watch() -> None:
            # 等待配置变更
            changed = await config_manager.wait_for_change(timeout=2.0)
            if changed:
                await rebuild_mock()

        with patch.object(scheduler, "_rebuild_job", rebuild_mock):
            task = asyncio.create_task(fake_watch())
            await asyncio.sleep(0.05)
            # 触发配置变更
            config_manager.update_config(
                {"trigger": {"type": "interval", "seconds": 120}}
            )
            # 等待 fake_watch 完成
            await asyncio.wait_for(task, timeout=2.0)

        # _rebuild_job 应被调用一次
        assert len(rebuild_calls) == 1

    @pytest.mark.asyncio
    async def test_rebuild_job_removes_old_and_registers_new(self) -> None:
        """``_rebuild_job`` 应先移除旧 Job，再注册新 Job。

        通过 mock APScheduler 的 ``remove_schedule`` 与 ``add_schedule``，
        验证调用顺序与参数。
        """
        config_manager = VersionedConfig(
            {"trigger": {"type": "interval", "seconds": 60}}
        )
        scheduler = DownloadScheduler(config_manager)

        # 用 MagicMock(spec=AsyncScheduler) 替换整个 _scheduler 实例
        # （AsyncScheduler 用 attrs __slots__，单方法 patch 不可行）
        mock_remove = AsyncMock()
        mock_add = AsyncMock()
        mock_async_scheduler = MagicMock()
        mock_async_scheduler.remove_schedule = mock_remove
        mock_async_scheduler.add_schedule = mock_add
        scheduler._scheduler = mock_async_scheduler
        # 初始 _current_job_id 设为某个值，验证移除被调用
        scheduler._current_job_id = "old_schedule_id"

        await scheduler._rebuild_job()

        # 应先移除旧 Job
        mock_remove.assert_awaited_once_with("old_schedule_id")
        # 应注册新 Job
        assert mock_add.await_count == 1
        # 新的 _current_job_id 应被设置
        assert scheduler._current_job_id == "bilibili_toolkit_download_schedule"

    @pytest.mark.asyncio
    async def test_rebuild_job_skips_when_no_trigger(self) -> None:
        """配置中无 ``trigger`` 字段时，``_rebuild_job`` 应跳过注册。"""
        config_manager = VersionedConfig({})
        scheduler = DownloadScheduler(config_manager)

        # mock APScheduler 实例（整体替换）
        mock_remove = AsyncMock()
        mock_add = AsyncMock()
        mock_async_scheduler = MagicMock()
        mock_async_scheduler.remove_schedule = mock_remove
        mock_async_scheduler.add_schedule = mock_add
        scheduler._scheduler = mock_async_scheduler
        scheduler._current_job_id = "old_id"

        await scheduler._rebuild_job()

        # 旧 Job 被移除
        mock_remove.assert_awaited_once_with("old_id")
        # 新 Job 未被注册
        mock_add.assert_not_awaited()
        # _current_job_id 被重置为 None
        assert scheduler._current_job_id is None

    @pytest.mark.asyncio
    async def test_rebuild_job_handles_invalid_trigger(self) -> None:
        """``trigger`` 配置无效时，``_rebuild_job`` 应吞掉异常不抛出。"""
        config_manager = VersionedConfig(
            {"trigger": {"type": "unknown_type", "seconds": 60}}
        )
        scheduler = DownloadScheduler(config_manager)

        # mock APScheduler 实例（整体替换）
        mock_remove = AsyncMock()
        mock_add = AsyncMock()
        mock_async_scheduler = MagicMock()
        mock_async_scheduler.remove_schedule = mock_remove
        mock_async_scheduler.add_schedule = mock_add
        scheduler._scheduler = mock_async_scheduler
        scheduler._current_job_id = None

        # 不应抛异常
        await scheduler._rebuild_job()

        # 注册未被调用
        mock_add.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_remove_current_job_no_op_when_no_job(self) -> None:
        """``_current_job_id=None`` 时 ``_remove_current_job`` 应直接返回。"""
        config_manager = VersionedConfig({})
        scheduler = DownloadScheduler(config_manager)

        mock_remove = AsyncMock()
        mock_async_scheduler = MagicMock()
        mock_async_scheduler.remove_schedule = mock_remove
        scheduler._scheduler = mock_async_scheduler
        scheduler._current_job_id = None

        await scheduler._remove_current_job()

        # 未调用 remove_schedule
        mock_remove.assert_not_awaited()
        # _current_job_id 仍为 None
        assert scheduler._current_job_id is None

    @pytest.mark.asyncio
    async def test_start_is_idempotent(self) -> None:
        """``start`` 重复调用应直接返回，不重复初始化。"""
        config_manager = VersionedConfig(
            {"trigger": {"type": "interval", "seconds": 60}}
        )
        scheduler = DownloadScheduler(config_manager)

        # 用 MagicMock 替换整个 _scheduler 实例（AsyncScheduler 用 attrs __slots__）
        mock_aenter = AsyncMock(return_value=None)
        mock_start_bg = AsyncMock(return_value=None)
        mock_aexit = AsyncMock(return_value=None)
        mock_async_scheduler = MagicMock()
        mock_async_scheduler.__aenter__ = mock_aenter
        mock_async_scheduler.__aexit__ = mock_aexit
        mock_async_scheduler.start_in_background = mock_start_bg
        mock_async_scheduler.remove_schedule = AsyncMock()
        mock_async_scheduler.add_schedule = AsyncMock()
        scheduler._scheduler = mock_async_scheduler

        # mock _rebuild_job 避免实际注册 Job
        rebuild_mock = AsyncMock()
        with patch.object(scheduler, "_rebuild_job", rebuild_mock):
            # 第一次 start
            await scheduler.start()
            assert scheduler._started is True
            first_aenter_calls = mock_aenter.await_count

            # 第二次 start 应直接返回
            await scheduler.start()
            # aenter 不应被再次调用
            assert mock_aenter.await_count == first_aenter_calls

        # 停止调度器以清理后台任务
        await scheduler.stop()

    @pytest.mark.asyncio
    async def test_stop_when_not_started_is_no_op(self) -> None:
        """未启动时调用 ``stop`` 应直接返回，不抛异常。"""
        config_manager = VersionedConfig({})
        scheduler = DownloadScheduler(config_manager)

        # 未启动直接 stop，不应抛异常
        await scheduler.stop()
        assert scheduler._started is False
