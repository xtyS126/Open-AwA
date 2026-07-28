"""
指数退避重试策略模块测试。
"""

import asyncio
import pytest
from core.retry import RetryPolicy, RetryResult, execute_with_retry


class TestRetryPolicy:
    """RetryPolicy 计算逻辑测试。"""

    def test_compute_delay_increases_exponentially(self):
        """验证延迟随重试次数指数增长。"""
        policy = RetryPolicy(
            max_attempts=5,
            base_interval=1.0,
            max_interval=100.0,
            jitter=0.0,
            exponential_base=2.0,
        )
        delays = [policy.compute_delay(i) for i in range(1, 5)]
        # 无抖动时：1.0, 2.0, 4.0, 8.0
        assert delays[0] == pytest.approx(1.0, abs=0.01)
        assert delays[1] == pytest.approx(2.0, abs=0.01)
        assert delays[2] == pytest.approx(4.0, abs=0.01)
        assert delays[3] == pytest.approx(8.0, abs=0.01)

    def test_compute_delay_capped_at_max_interval(self):
        """验证延迟不超过最大值。"""
        policy = RetryPolicy(
            base_interval=10.0,
            max_interval=30.0,
            jitter=0.0,
        )
        # attempt=1: 10.0, attempt=2: 20.0, attempt=3: 40.0 -> capped at 30.0
        assert policy.compute_delay(3) == pytest.approx(30.0, abs=0.01)

    def test_compute_delay_with_jitter(self):
        """验证抖动在合理范围内。"""
        policy = RetryPolicy(
            base_interval=10.0,
            max_interval=100.0,
            jitter=0.5,
            exponential_base=1.0,  # 固定基础延迟
        )
        # 基础延迟=10.0, 抖动范围=[0, 10.0*0.5*1.0] = [0, 5.0]
        # 总延迟范围=[10.0, 15.0]
        for _ in range(100):
            delay = policy.compute_delay(1)
            assert 10.0 <= delay <= 15.0


class TestExecuteWithRetry:
    """execute_with_retry 执行逻辑测试。"""

    @pytest.mark.asyncio
    async def test_succeeds_first_attempt(self):
        """首次成功不重试。"""
        call_count = 0

        async def succeed():
            nonlocal call_count
            call_count += 1
            return "ok"

        result = await execute_with_retry(succeed, policy=RetryPolicy(max_attempts=3))
        assert result.success is True
        assert result.attempts == 1
        assert result.result == "ok"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_retries_on_failure_then_succeeds(self):
        """失败后重试，最终成功。"""
        call_count = 0

        async def fail_then_succeed():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("temporary error")
            return "ok"

        policy = RetryPolicy(max_attempts=3, base_interval=0.01, max_interval=0.1, jitter=0.0)
        result = await execute_with_retry(
            fail_then_succeed,
            policy=policy,
            retryable_exceptions=(ValueError,),
        )
        assert result.success is True
        assert result.attempts == 3
        assert result.result == "ok"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_stops_after_max_attempts(self):
        """超过最大次数停止。"""
        async def always_fail():
            raise ValueError("permanent error")

        policy = RetryPolicy(max_attempts=2, base_interval=0.01, max_interval=0.1, jitter=0.0)
        result = await execute_with_retry(
            always_fail,
            policy=policy,
            retryable_exceptions=(ValueError,),
        )
        assert result.success is False
        assert result.attempts == 2
        assert isinstance(result.last_error, ValueError)

    @pytest.mark.asyncio
    async def test_non_retryable_exception_fails_immediately(self):
        """不可重试异常立即失败。"""
        async def raise_type_error():
            raise TypeError("not retryable")

        policy = RetryPolicy(max_attempts=3, base_interval=0.01, max_interval=0.1, jitter=0.0)
        result = await execute_with_retry(
            raise_type_error,
            policy=policy,
            retryable_exceptions=(ValueError,),  # 只重试 ValueError
        )
        assert result.success is False
        assert result.attempts == 1
        assert isinstance(result.last_error, TypeError)

    @pytest.mark.asyncio
    async def test_default_policy_does_not_retry_timeout(self):
        """默认策略不得放大已超时的外部调用。"""
        call_count = 0

        async def raise_timeout():
            nonlocal call_count
            call_count += 1
            raise TimeoutError("upstream timeout")

        result = await execute_with_retry(
            raise_timeout,
            policy=RetryPolicy(max_attempts=3, base_interval=0.01, max_interval=0.1, jitter=0.0),
        )

        assert result.success is False
        assert result.attempts == 1
        assert call_count == 1
        assert isinstance(result.last_error, TimeoutError)
