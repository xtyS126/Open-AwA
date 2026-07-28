"""
熔断器（Circuit Breaker）。

外部依赖（LLM、数据库、向量库、ACP 子进程）出现持续故障时，
熔断器在 N 次连续失败后进入 open 状态直接拒绝请求，
避免请求方阻塞在超时上拖垮整站；recovery_timeout 后进入 half_open
放行少量探测请求，成功则恢复 closed，失败则回到 open。

设计原则：
1. 简单状态机：closed → open → half_open → closed
2. 异步友好：asyncio.Lock 保护状态转换，无阻塞 IO
3. 异常分类：默认所有异常都计入失败，调用方可传 should_trip 自定义过滤
   （例如 4xx 业务异常不计入熔断）
4. 全局注册表：按 name 共享实例，便于跨模块使用同一熔断器
5. 可观测：每次状态转换记录 loguru 日志，暴露当前状态查询 API

使用示例：
    from core.circuit_breaker import circuit_breaker_guard, CircuitOpenError

    # 方式一：装饰器
    @circuit_breaker_guard("llm_call", failure_threshold=5, recovery_timeout=30)
    async def call_llm(...): ...

    # 方式二：上下文管理器
    breaker = get_circuit_breaker("db_session")
    async with breaker:
        async with db.session() as session:
            ...

    # 方式三：手动调用
    breaker = get_circuit_breaker("llm_call")
    if breaker.is_open:
        raise CircuitOpenError("LLM 服务暂不可用")
    try:
        result = await call_fn()
        breaker.record_success()
    except Exception as exc:
        breaker.record_failure(exc)
        raise
"""

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, Optional, TypeVar

from loguru import logger


T = TypeVar("T")


class CircuitState(str, Enum):
    """熔断器状态。"""

    CLOSED = "closed"  # 正常放行
    OPEN = "open"  # 拒绝所有请求
    HALF_OPEN = "half_open"  # 放行少量探测请求


class CircuitOpenError(Exception):
    """
    熔断器处于 open 状态时抛出。

    调用方应捕获此异常并返回 retryable=True 的错误响应，
    让前端按错误码注册表决策重试。
    """

    def __init__(self, name: str, state: CircuitState, retry_after_seconds: Optional[float] = None):
        self.name = name
        self.state = state
        self.retry_after_seconds = retry_after_seconds
        super().__init__(
            f"熔断器 {name} 处于 {state.value} 状态，"
            f"{'预计 ' + str(int(retry_after_seconds)) + ' 秒后恢复' if retry_after_seconds else '稍后将自动探测恢复'}"
        )


@dataclass
class CircuitBreakerConfig:
    """熔断器配置。"""

    name: str
    # 连续失败多少次后进入 open
    failure_threshold: int = 5
    # open 状态持续多少秒后进入 half_open 探测
    recovery_timeout: float = 30.0
    # half_open 状态允许的最大探测请求数
    half_open_max_calls: int = 1
    # 自定义异常过滤：返回 True 的异常才计入失败（如 4xx 业务异常不计入）
    should_trip: Optional[Callable[[Exception], bool]] = None


@dataclass
class CircuitBreaker:
    """
    熔断器实例。

    状态转换：
    - closed → open: 连续 failure_count >= failure_threshold
    - open → half_open: 距离 opened_at 超过 recovery_timeout
    - half_open → closed: 探测请求成功
    - half_open → open: 探测请求失败
    """

    config: CircuitBreakerConfig
    _state: CircuitState = field(init=False, default=CircuitState.CLOSED)
    _failure_count: int = field(init=False, default=0)
    _success_count: int = field(init=False, default=0)
    _opened_at: float = field(init=False, default=0.0)
    _half_open_calls: int = field(init=False, default=0)
    _lock: asyncio.Lock = field(init=False, default_factory=asyncio.Lock)

    @property
    def state(self) -> CircuitState:
        """当前状态（不加锁，读后状态可能过期但调用方会在 _lock 内重新校验）。"""
        return self._state

    @property
    def is_open(self) -> bool:
        """当前是否处于 open 状态。"""
        return self._state == CircuitState.OPEN

    @property
    def metrics(self) -> Dict[str, Any]:
        """暴露指标供健康检查端点查询。"""
        return {
            "name": self.config.name,
            "state": self._state.value,
            "failure_count": self._failure_count,
            "success_count": self._success_count,
            "opened_at": self._opened_at,
            "half_open_calls": self._half_open_calls,
        }

    async def acquire(self) -> None:
        """
        获取调用许可。

        - closed：直接放行
        - open：检查是否到 recovery_timeout，是则转 half_open 放行探测，否则抛 CircuitOpenError
        - half_open：检查探测请求数，未超限放行，否则抛 CircuitOpenError
        """
        async with self._lock:
            now = time.monotonic()
            if self._state == CircuitState.OPEN:
                elapsed = now - self._opened_at
                if elapsed >= self.config.recovery_timeout:
                    # 转入 half_open，放行一个探测请求
                    self._state = CircuitState.HALF_OPEN
                    self._half_open_calls = 1
                    self._success_count = 0
                    logger.bind(
                        module="circuit_breaker",
                        event="state_transition",
                        name=self.config.name,
                        from_state=CircuitState.OPEN.value,
                        to_state=CircuitState.HALF_OPEN.value,
                    ).info(f"熔断器 {self.config.name} 从 open 转入 half_open，开始探测")
                else:
                    # 仍在 open 状态，拒绝请求
                    retry_after = self.config.recovery_timeout - elapsed
                    raise CircuitOpenError(
                        self.config.name, CircuitState.OPEN, retry_after_seconds=retry_after
                    )
            elif self._state == CircuitState.HALF_OPEN:
                if self._half_open_calls >= self.config.half_open_max_calls:
                    # 探测请求数已满，拒绝其他请求
                    raise CircuitOpenError(self.config.name, CircuitState.HALF_OPEN)
                self._half_open_calls += 1
            # closed 状态无需额外处理

    async def record_success(self) -> None:
        """记录一次成功调用，可能触发 half_open → closed 转换。"""
        async with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                # 探测成功，恢复 closed
                self._state = CircuitState.CLOSED
                self._failure_count = 0
                self._half_open_calls = 0
                self._opened_at = 0.0
                logger.bind(
                    module="circuit_breaker",
                    event="state_transition",
                    name=self.config.name,
                    from_state=CircuitState.HALF_OPEN.value,
                    to_state=CircuitState.CLOSED.value,
                ).info(f"熔断器 {self.config.name} 探测成功，从 half_open 恢复 closed")
            elif self._state == CircuitState.CLOSED:
                # closed 状态下成功调用重置失败计数
                self._failure_count = 0

    async def record_failure(self, exc: Exception) -> None:
        """记录一次失败调用，可能触发 closed → open 或 half_open → open 转换。"""
        # 调用方自定义异常过滤
        if self.config.should_trip is not None and not self.config.should_trip(exc):
            # 业务异常不计入熔断
            return
        async with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                # 探测失败，回到 open
                self._state = CircuitState.OPEN
                self._opened_at = time.monotonic()
                self._half_open_calls = 0
                logger.bind(
                    module="circuit_breaker",
                    event="state_transition",
                    name=self.config.name,
                    from_state=CircuitState.HALF_OPEN.value,
                    to_state=CircuitState.OPEN.value,
                    error_type=type(exc).__name__,
                ).warning(f"熔断器 {self.config.name} 探测失败，从 half_open 回到 open: {exc}")
            elif self._state == CircuitState.CLOSED:
                self._failure_count += 1
                if self._failure_count >= self.config.failure_threshold:
                    self._state = CircuitState.OPEN
                    self._opened_at = time.monotonic()
                    logger.bind(
                        module="circuit_breaker",
                        event="state_transition",
                        name=self.config.name,
                        from_state=CircuitState.CLOSED.value,
                        to_state=CircuitState.OPEN.value,
                        failure_count=self._failure_count,
                        error_type=type(exc).__name__,
                    ).warning(
                        f"熔断器 {self.config.name} 连续失败 {self._failure_count} 次，"
                        f"从 closed 转入 open: {exc}"
                    )

    async def __aenter__(self) -> "CircuitBreaker":
        await self.acquire()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if exc_type is None:
            await self.record_success()
        else:
            await self.record_failure(exc if exc else RuntimeError("unknown error"))


# ---- 全局注册表 ----

_REGISTRY: Dict[str, CircuitBreaker] = {}
_REGISTRY_LOCK = asyncio.Lock()


async def get_circuit_breaker(
    name: str,
    *,
    failure_threshold: int = 5,
    recovery_timeout: float = 30.0,
    half_open_max_calls: int = 1,
    should_trip: Optional[Callable[[Exception], bool]] = None,
) -> CircuitBreaker:
    """
    获取或创建具名熔断器。

    首次调用按传入配置创建实例并注册；后续调用忽略配置参数，
    返回已存在的实例（保证全局共享同一状态）。
    """
    async with _REGISTRY_LOCK:
        breaker = _REGISTRY.get(name)
        if breaker is None:
            config = CircuitBreakerConfig(
                name=name,
                failure_threshold=failure_threshold,
                recovery_timeout=recovery_timeout,
                half_open_max_calls=half_open_max_calls,
                should_trip=should_trip,
            )
            breaker = CircuitBreaker(config=config)
            _REGISTRY[name] = breaker
        return breaker


def get_circuit_breaker_sync(name: str) -> Optional[CircuitBreaker]:
    """
    同步获取已注册的熔断器（不创建）。

    供健康检查端点同步查询所有熔断器状态使用。
    """
    return _REGISTRY.get(name)


def list_circuit_breakers() -> Dict[str, Dict[str, Any]]:
    """
    同步列出所有熔断器指标。

    供健康检查端点暴露给前端 Dashboard 使用。
    """
    return {name: breaker.metrics for name, breaker in _REGISTRY.items()}


def reset_circuit_breakers() -> None:
    """
    重置所有熔断器（仅用于测试）。

    清空注册表，让每个测试用例从干净状态开始。
    """
    _REGISTRY.clear()


async def circuit_breaker_guard(
    name: str,
    *,
    failure_threshold: int = 5,
    recovery_timeout: float = 30.0,
    half_open_max_calls: int = 1,
    should_trip: Optional[Callable[[Exception], bool]] = None,
) -> "CircuitBreakerGuardContext":
    """
    异步上下文管理器形式的熔断保护。

    用法：
        async with await circuit_breaker_guard("llm_call") as guard:
            result = await call_llm(...)

    注意：因 asyncio 上下文管理器协议要求 __aenter__ 返回 awaitable，
    本函数返回一个已构造好的 guard 对象，调用方需 await 之。
    """
    breaker = await get_circuit_breaker(
        name,
        failure_threshold=failure_threshold,
        recovery_timeout=recovery_timeout,
        half_open_max_calls=half_open_max_calls,
        should_trip=should_trip,
    )
    return CircuitBreakerGuardContext(breaker)


class CircuitBreakerGuardContext:
    """熔断保护上下文管理器，封装 acquire/record_success/record_failure。"""

    def __init__(self, breaker: CircuitBreaker):
        self._breaker = breaker

    async def __aenter__(self) -> "CircuitBreakerGuardContext":
        await self._breaker.acquire()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if exc_type is None:
            await self._breaker.record_success()
        else:
            await self._breaker.record_failure(exc if exc else RuntimeError("unknown error"))


async def call_with_circuit_breaker(
    name: str,
    func: Callable[..., Awaitable[T]],
    *args: Any,
    failure_threshold: int = 5,
    recovery_timeout: float = 30.0,
    half_open_max_calls: int = 1,
    should_trip: Optional[Callable[[Exception], bool]] = None,
    **kwargs: Any,
) -> T:
    """
    在熔断保护下调用异步函数。

    用法：
        result = await call_with_circuit_breaker("llm_call", call_llm, prompt, model="gpt-4")

    熔断器 open 时直接抛 CircuitOpenError，调用方应捕获并返回 retryable 错误响应。
    """
    breaker = await get_circuit_breaker(
        name,
        failure_threshold=failure_threshold,
        recovery_timeout=recovery_timeout,
        half_open_max_calls=half_open_max_calls,
        should_trip=should_trip,
    )
    await breaker.acquire()
    try:
        result = await func(*args, **kwargs)
        await breaker.record_success()
        return result
    except Exception as exc:
        await breaker.record_failure(exc)
        raise
