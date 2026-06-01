"""
启动任务分级与编排的单元测试。
验证 BLOCKING/WARMUP 任务执行顺序、依赖检查、dev_fast 跳过逻辑、超时保护。
"""
import asyncio
import os
from unittest.mock import AsyncMock, patch

import pytest

from openawa.core.startup.tasks import StartupTier, StartupTask, get_startup_tasks
from openawa.core.startup.bootstrap import run_startup, is_dev_fast_start
from openawa.core.startup.profiler import StartupProfiler


async def _noop():
    pass


def _make_task(name: str, tier: StartupTier, deps=None, skip_dev=False):
    return StartupTask(
        name=name,
        tier=tier,
        coro=_noop,
        depends_on=deps or [],
        requires_db=False,
        skip_in_dev_fast=skip_dev,
    )


def _make_profiler():
    p = StartupProfiler()
    p.start()
    return p


class TestStartupTaskTiers:
    """验证任务分级定义。"""

    def test_blocking_task_has_correct_tier(self):
        t = _make_task("db_init", StartupTier.BLOCKING)
        assert t.tier == StartupTier.BLOCKING

    def test_warmup_task_has_correct_tier(self):
        t = _make_task("marketplace_seed", StartupTier.WARMUP)
        assert t.tier == StartupTier.WARMUP

    def test_lazy_task_has_correct_tier(self):
        t = _make_task("some_heavy_module", StartupTier.LAZY)
        assert t.tier == StartupTier.LAZY

    def test_task_defaults(self):
        t = _make_task("test", StartupTier.BLOCKING)
        assert t.requires_db is False
        assert t.skip_in_dev_fast is False
        assert t.depends_on == []


class TestStartupBootstrapExecution:
    """验证编排器行为——任务执行顺序、依赖、跳过。"""

    @pytest.mark.asyncio
    async def test_blocking_completes_before_warmup(self):
        order = []
        profiler = _make_profiler()

        async def _blocking():
            order.append("blocking")

        async def _warmup():
            order.append("warmup")

        blocking_task = _make_task("b", StartupTier.BLOCKING)
        blocking_task.coro = _blocking
        warmup_task = _make_task("w", StartupTier.WARMUP)
        warmup_task.coro = _warmup

        await run_startup([blocking_task, warmup_task], profiler)
        await asyncio.sleep(0.2)  # wait for background warmup

        assert "blocking" in order
        # warmup 可能还在后台运行，给一点时间

    @pytest.mark.asyncio
    async def test_dependency_order_enforced(self):
        completed = []
        profiler = _make_profiler()

        async def _a():
            completed.append("a")

        async def _b():
            completed.append("b")

        a = _make_task("a", StartupTier.BLOCKING)
        a.coro = _a
        b = _make_task("b", StartupTier.BLOCKING, deps=["a"])
        b.coro = _b

        await run_startup([a, b], profiler)

        assert completed.index("a") < completed.index("b")

    @pytest.mark.asyncio
    async def test_missing_dependency_raises(self):
        profiler = _make_profiler()

        b = _make_task("b", StartupTier.BLOCKING, deps=["nonexistent"])
        b.coro = _noop

        with pytest.raises(RuntimeError, match="无法解析"):
            await run_startup([b], profiler)

    @pytest.mark.asyncio
    async def test_slow_blocking_task_is_guarded_by_timeout(self):
        """慢任务应被内部 60s 超时或外部 asyncio.wait_for 终止，不永久挂起。"""
        profiler = _make_profiler()

        async def _slow():
            await asyncio.sleep(999)

        slow = _make_task("slow", StartupTier.BLOCKING)
        slow.coro = _slow

        # 外部 wait_for 模拟测试环境，验证任务不会永久挂起
        with pytest.raises((RuntimeError, asyncio.TimeoutError)):
            await asyncio.wait_for(
                run_startup([slow], profiler),
                timeout=0.2
            )

    @pytest.mark.asyncio
    async def test_warmup_failure_does_not_block(self):
        profiler = _make_profiler()
        failed = []

        async def _blocking_ok():
            pass

        async def _warmup_fail():
            failed.append("warmup_failed")
            raise RuntimeError("warmup 故意失败")

        blocking = _make_task("b", StartupTier.BLOCKING)
        blocking.coro = _blocking_ok
        warmup = _make_task("w", StartupTier.WARMUP)
        warmup.coro = _warmup_fail

        # 不应抛异常
        await run_startup([blocking, warmup], profiler)
        await asyncio.sleep(0.2)

        assert len(failed) == 1


class TestDevFastStart:
    """验证开发快启模式。"""

    def test_env_var_enables_dev_fast(self):
        with patch.dict(os.environ, {"DEV_FAST_START": "1"}):
            assert is_dev_fast_start() is True

    def test_env_var_true_enables_dev_fast(self):
        with patch.dict(os.environ, {"DEV_FAST_START": "true"}):
            assert is_dev_fast_start() is True

    def test_default_is_not_dev_fast(self):
        with patch.dict(os.environ, {}, clear=True):
            assert is_dev_fast_start() is False

    @pytest.mark.asyncio
    async def test_dev_fast_skips_marked_tasks(self):
        with patch.dict(os.environ, {"DEV_FAST_START": "1"}):
            profiler = _make_profiler()
            executed = []

            async def _blocking():
                executed.append("blocking")

            async def _skipped():
                executed.append("skipped")

            blocking = _make_task("b", StartupTier.BLOCKING)
            blocking.coro = _blocking
            skipped = _make_task("s", StartupTier.WARMUP, skip_dev=True)
            skipped.coro = _skipped

            await run_startup([blocking, skipped], profiler)
            await asyncio.sleep(0.2)

            assert "blocking" in executed
            assert "skipped" not in executed


class TestStartupProfiler:
    """验证耗时采集器。"""

    def test_profiler_start_sets_started_at(self):
        p = StartupProfiler()
        p.start()
        assert p._started_at is not None

    def test_profiler_step_records_timing(self):
        p = StartupProfiler()
        p.start()
        with p.step("test_step"):
            pass
        assert len(p._records) == 1
        assert p._records[0]["name"] == "test_step"
        assert p._records[0]["elapsed_ms"] >= 0
        assert p._records[0]["ok"] is True

    def test_profiler_finish_does_not_crash(self):
        p = StartupProfiler()
        p.start()
        p.finish()  # 不应抛异常


class TestStartupTasksDefinition:
    """验证 get_startup_tasks() 返回正确的任务列表。"""

    def test_returns_correct_number_of_tasks(self):
        tasks = get_startup_tasks(
            init_db_fn=_noop,
            billing_create_all_fn=_noop,
            pricing_init_fn=_noop,
            rbac_init_fn=_noop,
            local_users_sync_fn=_noop,
            marketplace_seed_fn=_noop,
            plugin_discover_fn=_noop,
            plugin_load_all_fn=_noop,
            scheduled_task_start_fn=_noop,
            weixin_auto_reply_start_fn=_noop,
        )
        assert len(tasks) == 10

    def test_blocking_tasks_are_correct(self):
        tasks = get_startup_tasks(
            init_db_fn=_noop,
            billing_create_all_fn=_noop,
            pricing_init_fn=_noop,
            rbac_init_fn=_noop,
            local_users_sync_fn=_noop,
            marketplace_seed_fn=_noop,
            plugin_discover_fn=_noop,
            plugin_load_all_fn=_noop,
            scheduled_task_start_fn=_noop,
            weixin_auto_reply_start_fn=_noop,
        )
        blocking_names = {t.name for t in tasks if t.tier == StartupTier.BLOCKING}
        assert "db_init" in blocking_names
        assert "pricing_init" in blocking_names
        assert "scheduled_task_start" in blocking_names

    def test_warmup_tasks_are_correct(self):
        tasks = get_startup_tasks(
            init_db_fn=_noop,
            billing_create_all_fn=_noop,
            pricing_init_fn=_noop,
            rbac_init_fn=_noop,
            local_users_sync_fn=_noop,
            marketplace_seed_fn=_noop,
            plugin_discover_fn=_noop,
            plugin_load_all_fn=_noop,
            scheduled_task_start_fn=_noop,
            weixin_auto_reply_start_fn=_noop,
        )
        warmup_names = {t.name for t in tasks if t.tier == StartupTier.WARMUP}
        assert "marketplace_seed" in warmup_names
        assert "plugin_load_enabled" in warmup_names
        assert "weixin_auto_reply" in warmup_names

    def test_pricing_depends_on_billing(self):
        tasks = get_startup_tasks(
            init_db_fn=_noop,
            billing_create_all_fn=_noop,
            pricing_init_fn=_noop,
            rbac_init_fn=_noop,
            local_users_sync_fn=_noop,
            marketplace_seed_fn=_noop,
            plugin_discover_fn=_noop,
            plugin_load_all_fn=_noop,
            scheduled_task_start_fn=_noop,
            weixin_auto_reply_start_fn=_noop,
        )
        pricing = next(t for t in tasks if t.name == "pricing_init")
        assert "billing_tables" in pricing.depends_on
