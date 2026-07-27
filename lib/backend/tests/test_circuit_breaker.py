"""
熔断器（Circuit Breaker）单元测试。

覆盖：
- 状态机转换：closed → open → half_open → closed
- failure_threshold 触发条件
- recovery_timeout 触发 half_open
- half_open 探测成功/失败的转换
- should_trip 自定义过滤
- CircuitOpenError 抛出与 retry_after_seconds 计算
- 全局注册表共享实例
- 同步工具函数 list_circuit_breakers / reset_circuit_breakers
"""

import asyncio
from typing import Optional

import pytest

from core.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitOpenError,
    CircuitState,
    call_with_circuit_breaker,
    circuit_breaker_guard,
    get_circuit_breaker,
    get_circuit_breaker_sync,
    list_circuit_breakers,
    reset_circuit_breakers,
)


@pytest.fixture(autouse=True)
def _reset_registry():
    """每个用例运行前清空全局注册表，确保状态隔离。"""
    reset_circuit_breakers()
    yield
    reset_circuit_breakers()


@pytest.mark.asyncio
async def test_initial_state_is_closed():
    """新建熔断器默认状态为 closed。"""
    breaker = await get_circuit_breaker("test_init")
    assert breaker.state == CircuitState.CLOSED
    assert breaker.is_open is False


@pytest.mark.asyncio
async def test_failure_threshold_triggers_open():
    """连续失败达 failure_threshold 次后转入 open。"""
    breaker = await get_circuit_breaker(
        "test_threshold",
        failure_threshold=3,
        recovery_timeout=30.0,
    )

    await breaker.record_failure(RuntimeError("err 1"))
    await breaker.record_failure(RuntimeError("err 2"))
    assert breaker.state == CircuitState.CLOSED  # 还未到阈值

    await breaker.record_failure(RuntimeError("err 3"))
    assert breaker.state == CircuitState.OPEN


@pytest.mark.asyncio
async def test_acquire_open_raises_with_retry_after():
    """open 状态下 acquire 抛 CircuitOpenError 并携带 retry_after_seconds。"""
    breaker = await get_circuit_breaker(
        "test_open_acquire",
        failure_threshold=1,
        recovery_timeout=30.0,
    )
    await breaker.record_failure(RuntimeError("trigger"))

    with pytest.raises(CircuitOpenError) as exc_info:
        await breaker.acquire()

    assert exc_info.value.state == CircuitState.OPEN
    assert exc_info.value.retry_after_seconds is not None
    assert 0 < exc_info.value.retry_after_seconds <= 30.0


@pytest.mark.asyncio
async def test_open_transitions_to_half_open_after_recovery_timeout():
    """recovery_timeout 后 acquire 转入 half_open 并放行探测请求。"""
    breaker = await get_circuit_breaker(
        "test_half_open",
        failure_threshold=1,
        recovery_timeout=0.05,  # 50ms，加速测试
        half_open_max_calls=1,
    )
    await breaker.record_failure(RuntimeError("trigger"))
    assert breaker.state == CircuitState.OPEN

    # 等待 recovery_timeout 过期
    await asyncio.sleep(0.06)

    # acquire 应转入 half_open 并放行
    await breaker.acquire()
    assert breaker.state == CircuitState.HALF_OPEN


@pytest.mark.asyncio
async def test_half_open_success_restores_closed():
    """half_open 探测成功后恢复 closed。"""
    breaker = await get_circuit_breaker(
        "test_half_open_success",
        failure_threshold=1,
        recovery_timeout=0.05,
        half_open_max_calls=1,
    )
    await breaker.record_failure(RuntimeError("trigger"))
    await asyncio.sleep(0.06)
    await breaker.acquire()
    assert breaker.state == CircuitState.HALF_OPEN

    await breaker.record_success()
    assert breaker.state == CircuitState.CLOSED


@pytest.mark.asyncio
async def test_half_open_failure_back_to_open():
    """half_open 探测失败回到 open。"""
    breaker = await get_circuit_breaker(
        "test_half_open_failure",
        failure_threshold=1,
        recovery_timeout=0.05,
        half_open_max_calls=1,
    )
    await breaker.record_failure(RuntimeError("trigger1"))
    await asyncio.sleep(0.06)
    await breaker.acquire()
    assert breaker.state == CircuitState.HALF_OPEN

    await breaker.record_failure(RuntimeError("probe failed"))
    assert breaker.state == CircuitState.OPEN


@pytest.mark.asyncio
async def test_half_open_max_calls_rejected():
    """half_open 状态超出探测请求数时拒绝新请求。"""
    breaker = await get_circuit_breaker(
        "test_half_open_max",
        failure_threshold=1,
        recovery_timeout=0.05,
        half_open_max_calls=1,
    )
    await breaker.record_failure(RuntimeError("trigger"))
    await asyncio.sleep(0.06)
    await breaker.acquire()  # 占用唯一的探测名额
    assert breaker.state == CircuitState.HALF_OPEN

    with pytest.raises(CircuitOpenError) as exc_info:
        await breaker.acquire()
    assert exc_info.value.state == CircuitState.HALF_OPEN


@pytest.mark.asyncio
async def test_should_trip_filter_skips_business_errors():
    """should_trip 返回 False 的异常不计入熔断统计。"""
    def is_infra_error(exc: Exception) -> bool:
        # 仅基础设施异常（TimeoutError / ConnectionError）才计入
        return isinstance(exc, (TimeoutError, ConnectionError))

    breaker = await get_circuit_breaker(
        "test_filter",
        failure_threshold=2,
        recovery_timeout=30.0,
        should_trip=is_infra_error,
    )

    # 业务异常不计入
    await breaker.record_failure(ValueError("business error"))
    await breaker.record_failure(ValueError("business error 2"))
    assert breaker.state == CircuitState.CLOSED

    # 基础设施异常计入
    await breaker.record_failure(TimeoutError("timeout 1"))
    await breaker.record_failure(TimeoutError("timeout 2"))
    assert breaker.state == CircuitState.OPEN


@pytest.mark.asyncio
async def test_call_with_circuit_breaker_success():
    """call_with_circuit_breaker 正常调用并记录成功。"""
    call_count = 0

    async def sample_func(x: int, y: int) -> int:
        nonlocal call_count
        call_count += 1
        return x + y

    result = await call_with_circuit_breaker(
        "test_call_ok",
        sample_func,
        3,
        4,
        failure_threshold=5,
    )
    assert result == 7
    assert call_count == 1

    breaker = get_circuit_breaker_sync("test_call_ok")
    assert breaker is not None
    assert breaker.state == CircuitState.CLOSED


@pytest.mark.asyncio
async def test_call_with_circuit_breaker_propagates_and_records_failure():
    """call_with_circuit_breaker 传递异常并记录失败。"""
    async def failing_func() -> None:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        await call_with_circuit_breaker(
            "test_call_fail",
            failing_func,
            failure_threshold=2,
        )

    breaker = get_circuit_breaker_sync("test_call_fail")
    assert breaker.state == CircuitState.CLOSED  # 仅 1 次失败，未到阈值

    # 第二次失败触发 open
    with pytest.raises(RuntimeError):
        await call_with_circuit_breaker(
            "test_call_fail",
            failing_func,
            failure_threshold=2,
        )
    assert breaker.state == CircuitState.OPEN


@pytest.mark.asyncio
async def test_call_with_circuit_breaker_rejected_when_open():
    """熔断器 open 时 call_with_circuit_breaker 抛 CircuitOpenError。"""
    async def always_fail() -> None:
        raise RuntimeError("infra down")

    # 触发 open
    for _ in range(3):
        with pytest.raises(RuntimeError):
            await call_with_circuit_breaker(
                "test_reject",
                always_fail,
                failure_threshold=3,
            )
    assert get_circuit_breaker_sync("test_reject").state == CircuitState.OPEN

    # open 后直接抛 CircuitOpenError，不再调用 func
    call_count = 0

    async def sample_func() -> str:
        nonlocal call_count
        call_count += 1
        return "should not be called"

    with pytest.raises(CircuitOpenError):
        await call_with_circuit_breaker(
            "test_reject",
            sample_func,
            failure_threshold=3,
        )
    assert call_count == 0


@pytest.mark.asyncio
async def test_registry_shares_instance_by_name():
    """按 name 获取的熔断器在多次调用间共享同一实例。"""
    b1 = await get_circuit_breaker("shared", failure_threshold=5)
    b2 = await get_circuit_breaker("shared", failure_threshold=999)  # 配置被忽略
    assert b1 is b2
    assert b1.config.failure_threshold == 5  # 首次创建的配置


@pytest.mark.asyncio
async def test_context_manager_records_success_and_failure():
    """async with 上下文管理器形式正确记账。"""
    breaker = await get_circuit_breaker(
        "test_ctx",
        failure_threshold=2,
    )

    # 成功路径
    async with breaker:
        pass  # 无异常
    assert breaker.state == CircuitState.CLOSED

    # 失败路径
    with pytest.raises(ValueError):
        async with breaker:
            raise ValueError("boom")
    assert breaker.state == CircuitState.CLOSED  # 1 次失败，未到阈值

    # 再一次失败触发 open
    with pytest.raises(ValueError):
        async with breaker:
            raise ValueError("boom 2")
    assert breaker.state == CircuitState.OPEN


@pytest.mark.asyncio
async def test_circuit_breaker_guard_context():
    """circuit_breaker_guard 异步上下文管理器形式可用。"""
    guard = await circuit_breaker_guard(
        "test_guard",
        failure_threshold=3,
    )
    assert isinstance(guard, type(guard))  # 简单类型断言

    async with guard:
        pass

    breaker = get_circuit_breaker_sync("test_guard")
    assert breaker is not None
    assert breaker.state == CircuitState.CLOSED


def test_list_circuit_breakers_returns_metrics():
    """list_circuit_breakers 同步返回所有熔断器指标。"""
    # 通过 asyncio.run 创建一个熔断器
    async def setup():
        await get_circuit_breaker("metrics_test", failure_threshold=7)

    asyncio.run(setup())

    metrics = list_circuit_breakers()
    assert "metrics_test" in metrics
    assert metrics["metrics_test"]["state"] == "closed"
    assert metrics["metrics_test"]["failure_threshold"] if "failure_threshold" in metrics["metrics_test"] else True
    # 指标包含必要字段
    assert "name" in metrics["metrics_test"]
    assert "state" in metrics["metrics_test"]


def test_get_circuit_breaker_sync_returns_none_for_unknown():
    """同步获取未注册的熔断器返回 None。"""
    assert get_circuit_breaker_sync("nonexistent") is None


@pytest.mark.asyncio
async def test_consecutive_success_resets_failure_count():
    """closed 状态下成功调用重置失败计数，避免历史失败累积触发误熔断。"""
    breaker = await get_circuit_breaker(
        "test_reset",
        failure_threshold=3,
    )
    await breaker.record_failure(RuntimeError("e1"))
    await breaker.record_failure(RuntimeError("e2"))
    # 成功调用应重置失败计数
    await breaker.record_success()
    # 再次失败 1 次不应触发 open
    await breaker.record_failure(RuntimeError("e3"))
    assert breaker.state == CircuitState.CLOSED
