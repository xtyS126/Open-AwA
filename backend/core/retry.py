"""
指数退避重试策略模块，为 Agent 执行步骤提供可配置的重试机制。
"""

import asyncio
import random
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional, TypeVar
from loguru import logger
from config.settings import settings


# 默认只重试连接层瞬态故障。超时、业务校验和未知异常必须由调用方明确选择，
# 避免无界重试放大外部依赖已经超时的请求。
DEFAULT_RETRYABLE_EXCEPTIONS: tuple[type[Exception], ...] = (ConnectionError,)


@dataclass
class RetryResult:
    """重试执行结果。"""
    success: bool
    attempts: int
    last_error: Optional[Exception] = None
    total_delay_seconds: float = 0.0
    result: Any = None


@dataclass
class RetryPolicy:
    """
    指数退避重试策略。

    参数:
        max_attempts: 最大重试次数（含首次执行）
        base_interval: 基础等待间隔（秒）
        max_interval: 最大等待间隔（秒）
        jitter: 随机抖动系数（0.0-1.0）
        exponential_base: 指数底数
    """
    max_attempts: int = 3
    base_interval: float = field(
        default_factory=lambda: settings.AGENT_RETRY_BASE_INTERVAL
    )
    max_interval: float = field(
        default_factory=lambda: settings.AGENT_RETRY_MAX_INTERVAL
    )
    jitter: float = field(
        default_factory=lambda: settings.AGENT_RETRY_JITTER
    )
    exponential_base: float = 2.0

    def compute_delay(self, attempt: int) -> float:
        """计算第 attempt 次重试的等待时间（秒）。"""
        delay = self.base_interval * (self.exponential_base ** (attempt - 1))
        delay = min(delay, self.max_interval)
        jitter_amount = delay * self.jitter * random.random()
        return min(delay + jitter_amount, self.max_interval)


async def execute_with_retry(
    func: Callable[..., Awaitable[Any]],
    *args: Any,
    policy: Optional[RetryPolicy] = None,
    retryable_exceptions: tuple[type[Exception], ...] = DEFAULT_RETRYABLE_EXCEPTIONS,
    **kwargs: Any,
) -> RetryResult:
    """
    使用指数退避策略执行异步函数。

    参数:
        func: 要执行的异步函数
        policy: 重试策略，为 None 时使用默认策略
        retryable_exceptions: 可重试的异常类型元组
    """
    if policy is None:
        policy = RetryPolicy()

    result = RetryResult(success=False, attempts=0)
    last_error: Optional[Exception] = None

    for attempt in range(1, policy.max_attempts + 1):
        result.attempts = attempt
        try:
            ret = await func(*args, **kwargs)
            result.success = True
            result.result = ret
            return result
        except retryable_exceptions as e:
            last_error = e
            logger.bind(
                event="retry_attempt",
                module="retry",
                attempt=attempt,
                max_attempts=policy.max_attempts,
                error=str(e),
            ).warning(f"第 {attempt} 次执行失败: {e}")

            if attempt < policy.max_attempts:
                delay = policy.compute_delay(attempt)
                result.total_delay_seconds += delay
                logger.bind(
                    event="retry_delay",
                    module="retry",
                    attempt=attempt,
                    delay_seconds=round(delay, 2),
                ).info(f"等待 {delay:.2f}s 后重试")
                await asyncio.sleep(delay)
        except Exception as e:
            # 不可重试的异常，立即返回失败
            last_error = e
            logger.bind(
                event="retry_non_retryable",
                module="retry",
                attempt=attempt,
                error_type=type(e).__name__,
                error=str(e),
            ).warning(f"不可重试异常，立即失败: {e}")
            break

    result.last_error = last_error
    return result
