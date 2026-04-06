"""
错误重试机制模块
实现指数退避算法、熔断器模式和重试装饰器
"""

from __future__ import annotations

import asyncio
import functools
import random
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, TypeVar, Union

from loguru import logger

T = TypeVar("T")


class CircuitState(Enum):
    """熔断器状态枚举"""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class RetryConfig:
    """
    重试配置类
    封装重试策略的配置参数

    属性:
        max_retries: 最大重试次数，默认为3
        base_delay_ms: 基础延迟时间（毫秒），默认为1000
        max_delay_ms: 最大延迟时间（毫秒），默认为30000
        exponential_base: 指数退避基数，默认为2
        jitter_ms: 抖动时间（毫秒），默认为100
        retryable_exceptions: 可重试的异常类型列表
    """

    max_retries: int = 3
    base_delay_ms: int = 1000
    max_delay_ms: int = 30000
    exponential_base: float = 2.0
    jitter_ms: int = 100
    retryable_exceptions: List[type] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.retryable_exceptions:
            self.retryable_exceptions = [Exception]


@dataclass
class CircuitBreakerConfig:
    """
    熔断器配置类
    封装熔断器策略的配置参数

    属性:
        failure_threshold: 触发熔断的连续失败次数阈值，默认为3
        recovery_timeout_ms: 熔断恢复超时时间（毫秒），默认为30000
        half_open_max_calls: 半开状态最大尝试次数，默认为1
    """

    failure_threshold: int = 3
    recovery_timeout_ms: int = 30000
    half_open_max_calls: int = 1


class CircuitBreaker:
    """
    熔断器类
    实现熔断器模式，防止系统过载

    当连续失败次数达到阈值时，熔断器打开，暂停请求一段时间。
    经过恢复超时后，熔断器进入半开状态，允许有限次数的尝试。
    如果尝试成功，熔断器关闭；如果失败，熔断器重新打开。

    属性:
        name: 熔断器名称
        config: 熔断器配置
        state: 当前状态
        failure_count: 连续失败计数
        last_failure_time: 最后一次失败时间戳
        half_open_calls: 半开状态下的调用次数
    """

    def __init__(self, name: str, config: Optional[CircuitBreakerConfig] = None) -> None:
        """
        初始化熔断器实例

        参数:
            name: 熔断器名称，用于标识和日志
            config: 熔断器配置，如果为None则使用默认配置
        """
        self.name = name
        self.config = config or CircuitBreakerConfig()
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.last_failure_time: float = 0
        self.half_open_calls = 0
        self._lock = asyncio.Lock()

    async def can_execute(self) -> bool:
        """
        检查是否可以执行请求

        返回:
            True表示可以执行，False表示熔断器打开，应暂停执行
        """
        async with self._lock:
            if self.state == CircuitState.CLOSED:
                return True

            if self.state == CircuitState.OPEN:
                elapsed_ms = (time.time() - self.last_failure_time) * 1000
                if elapsed_ms >= self.config.recovery_timeout_ms:
                    self.state = CircuitState.HALF_OPEN
                    self.half_open_calls = 0
                    logger.info(f"[CircuitBreaker:{self.name}] 熔断器进入半开状态")
                    return True
                return False

            if self.state == CircuitState.HALF_OPEN:
                if self.half_open_calls < self.config.half_open_max_calls:
                    self.half_open_calls += 1
                    return True
                return False

        return False

    async def record_success(self) -> None:
        """
        记录成功调用
        如果当前处于半开状态，成功后会关闭熔断器
        """
        async with self._lock:
            if self.state == CircuitState.HALF_OPEN:
                self.state = CircuitState.CLOSED
                self.failure_count = 0
                self.half_open_calls = 0
                logger.info(f"[CircuitBreaker:{self.name}] 熔断器已关闭，恢复正常")

    async def record_failure(self) -> None:
        """
        记录失败调用
        如果连续失败次数达到阈值，熔断器打开
        """
        async with self._lock:
            self.failure_count += 1
            self.last_failure_time = time.time()

            if self.state == CircuitState.HALF_OPEN:
                self.state = CircuitState.OPEN
                self.half_open_calls = 0
                logger.warning(
                    f"[CircuitBreaker:{self.name}] 半开状态下失败，熔断器重新打开"
                )
            elif self.failure_count >= self.config.failure_threshold:
                self.state = CircuitState.OPEN
                logger.warning(
                    f"[CircuitBreaker:{self.name}] 连续失败{self.failure_count}次，熔断器已打开，"
                    f"将在{self.config.recovery_timeout_ms / 1000:.1f}秒后尝试恢复"
                )

    def get_state(self) -> Dict[str, Any]:
        """
        获取熔断器当前状态信息

        返回:
            包含状态信息的字典
        """
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_count": self.failure_count,
            "last_failure_time": self.last_failure_time,
            "recovery_timeout_ms": self.config.recovery_timeout_ms,
        }


class ExponentialBackoff:
    """
    指数退避算法类
    实现指数退避延迟计算

    每次重试的延迟时间按指数增长，同时添加随机抖动避免惊群效应。
    延迟时间公式: min(max_delay, base_delay * exponential_base^attempt) + random_jitter

    属性:
        config: 重试配置
    """

    def __init__(self, config: Optional[RetryConfig] = None) -> None:
        """
        初始化指数退避实例

        参数:
            config: 重试配置，如果为None则使用默认配置
        """
        self.config = config or RetryConfig()

    def get_delay_ms(self, attempt: int) -> int:
        """
        计算指定尝试次数的延迟时间

        参数:
            attempt: 当前尝试次数（从0开始）

        返回:
            延迟时间（毫秒）
        """
        exponential_delay = self.config.base_delay_ms * (
            self.config.exponential_base ** attempt
        )
        capped_delay = min(exponential_delay, self.config.max_delay_ms)
        jitter = random.randint(0, self.config.jitter_ms)
        return int(capped_delay + jitter)

    async def wait(self, attempt: int) -> None:
        """
        异步等待指定的延迟时间

        参数:
            attempt: 当前尝试次数（从0开始）
        """
        delay_ms = self.get_delay_ms(attempt)
        delay_seconds = delay_ms / 1000
        logger.debug(f"[ExponentialBackoff] 等待 {delay_seconds:.3f} 秒后重试")
        await asyncio.sleep(delay_seconds)


def calculate_backoff_delay(
    attempt: int,
    base_delay_ms: int = 1000,
    max_delay_ms: int = 30000,
    exponential_base: float = 2.0,
    jitter_ms: int = 100,
) -> int:
    """
    计算指数退避延迟时间的便捷函数

    参数:
        attempt: 当前尝试次数（从0开始）
        base_delay_ms: 基础延迟时间（毫秒）
        max_delay_ms: 最大延迟时间（毫秒）
        exponential_base: 指数退避基数
        jitter_ms: 抖动时间（毫秒）

    返回:
        延迟时间（毫秒）
    """
    exponential_delay = base_delay_ms * (exponential_base ** attempt)
    capped_delay = min(exponential_delay, max_delay_ms)
    jitter = random.randint(0, jitter_ms)
    return int(capped_delay + jitter)


def retry_with_backoff(
    max_retries: int = 3,
    base_delay_ms: int = 1000,
    max_delay_ms: int = 30000,
    exponential_base: float = 2.0,
    jitter_ms: int = 100,
    retryable_exceptions: Optional[List[type]] = None,
    circuit_breaker: Optional[CircuitBreaker] = None,
    on_retry: Optional[Callable[[int, Exception], None]] = None,
):
    """
    重试装饰器
    为异步函数添加指数退避重试逻辑

    参数:
        max_retries: 最大重试次数
        base_delay_ms: 基础延迟时间（毫秒）
        max_delay_ms: 最大延迟时间（毫秒）
        exponential_base: 指数退避基数
        jitter_ms: 抖动时间（毫秒）
        retryable_exceptions: 可重试的异常类型列表
        circuit_breaker: 可选的熔断器实例
        on_retry: 重试时的回调函数，接收尝试次数和异常

    返回:
        装饰器函数

    使用示例:
        @retry_with_backoff(max_retries=3)
        async def fetch_data():
            return await some_api_call()
    """
    exceptions = retryable_exceptions or [Exception]

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            backoff = ExponentialBackoff(
                RetryConfig(
                    max_retries=max_retries,
                    base_delay_ms=base_delay_ms,
                    max_delay_ms=max_delay_ms,
                    exponential_base=exponential_base,
                    jitter_ms=jitter_ms,
                    retryable_exceptions=exceptions,
                )
            )

            last_exception: Optional[Exception] = None

            for attempt in range(max_retries + 1):
                if circuit_breaker and not await circuit_breaker.can_execute():
                    raise CircuitBreakerOpenError(
                        f"熔断器 {circuit_breaker.name} 处于打开状态，请求被拒绝"
                    )

                try:
                    result = await func(*args, **kwargs)
                    if circuit_breaker:
                        await circuit_breaker.record_success()
                    return result
                except tuple(exceptions) as exc:
                    last_exception = exc

                    if circuit_breaker:
                        await circuit_breaker.record_failure()

                    if attempt < max_retries:
                        if on_retry:
                            on_retry(attempt, exc)

                        logger.warning(
                            f"[Retry] {func.__name__} 第{attempt + 1}次执行失败: {exc}，"
                            f"将在 {backoff.get_delay_ms(attempt)}ms 后重试"
                        )
                        await backoff.wait(attempt)
                    else:
                        logger.error(
                            f"[Retry] {func.__name__} 已达到最大重试次数 {max_retries}，"
                            f"最后错误: {exc}"
                        )

            raise last_exception

        return wrapper

    return decorator


class CircuitBreakerOpenError(Exception):
    """熔断器打开错误"""

    pass


@dataclass
class ErrorNotification:
    """
    错误通知数据类
    封装错误通知的内容

    属性:
        error_code: 错误码
        error_message: 错误消息
        error_details: 错误详情
        timestamp: 时间戳
        account_id: 账号ID（可选）
        endpoint: API端点（可选）
        retry_count: 重试次数（可选）
    """

    error_code: str
    error_message: str
    error_details: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    account_id: Optional[str] = None
    endpoint: Optional[str] = None
    retry_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """
        将通知转换为字典格式

        返回:
            包含通知信息的字典
        """
        return {
            "error_code": self.error_code,
            "error_message": self.error_message,
            "error_details": self.error_details,
            "timestamp": self.timestamp,
            "account_id": self.account_id,
            "endpoint": self.endpoint,
            "retry_count": self.retry_count,
        }

    def to_user_message(self) -> str:
        """
        生成面向用户的友好错误消息

        返回:
            用户友好的错误消息字符串
        """
        error_msg = self.error_message.lower()

        if "remote media download failed" in error_msg:
            return "媒体文件下载失败，请检查链接是否可访问。"
        if "cdn upload" in error_msg or "upload" in error_msg:
            return "媒体文件上传失败，请稍后重试。"
        if "timeout" in error_msg:
            return "请求超时，请检查网络连接后重试。"
        if "session" in error_msg or "paused" in error_msg:
            return "会话已过期，请重新扫码登录。"
        if "unauthorized" in error_msg or "token" in error_msg:
            return "认证失败，请检查配置或重新登录。"

        return f"操作失败: {self.error_message}"


class ErrorNotifier:
    """
    错误通知发送类
    负责发送错误通知给用户或监控系统

    属性:
        notification_handlers: 通知处理器列表
    """

    def __init__(self) -> None:
        """初始化错误通知器"""
        self.notification_handlers: List[Callable[[ErrorNotification], None]] = []

    def add_handler(
        self, handler: Callable[[ErrorNotification], None]
    ) -> None:
        """
        添加通知处理器

        参数:
            handler: 处理通知的回调函数
        """
        self.notification_handlers.append(handler)

    def notify(self, notification: ErrorNotification) -> None:
        """
        发送错误通知

        参数:
            notification: 错误通知实例
        """
        logger.error(
            f"[ErrorNotifier] 错误通知: code={notification.error_code}, "
            f"message={notification.error_message}, "
            f"account_id={notification.account_id}"
        )

        for handler in self.notification_handlers:
            try:
                handler(notification)
            except Exception as exc:
                logger.warning(f"[ErrorNotifier] 通知处理器执行失败: {exc}")

    def notify_error(
        self,
        error_code: str,
        error_message: str,
        error_details: Optional[Dict[str, Any]] = None,
        account_id: Optional[str] = None,
        endpoint: Optional[str] = None,
        retry_count: int = 0,
    ) -> None:
        """
        发送错误通知的便捷方法

        参数:
            error_code: 错误码
            error_message: 错误消息
            error_details: 错误详情
            account_id: 账号ID
            endpoint: API端点
            retry_count: 重试次数
        """
        notification = ErrorNotification(
            error_code=error_code,
            error_message=error_message,
            error_details=error_details or {},
            account_id=account_id,
            endpoint=endpoint,
            retry_count=retry_count,
        )
        self.notify(notification)


def send_error_notice(
    error_code: str,
    error_message: str,
    error_details: Optional[Dict[str, Any]] = None,
    account_id: Optional[str] = None,
    endpoint: Optional[str] = None,
) -> str:
    """
    发送错误通知的便捷函数

    参数:
        error_code: 错误码
        error_message: 错误消息
        error_details: 错误详情
        account_id: 账号ID
        endpoint: API端点

    返回:
        用户友好的错误消息
    """
    notification = ErrorNotification(
        error_code=error_code,
        error_message=error_message,
        error_details=error_details or {},
        account_id=account_id,
        endpoint=endpoint,
    )

    logger.error(
        f"[send_error_notice] {notification.to_dict()}"
    )

    return notification.to_user_message()


default_error_notifier = ErrorNotifier()


def get_default_error_notifier() -> ErrorNotifier:
    """
    获取默认的错误通知器实例

    返回:
        ErrorNotifier实例
    """
    return default_error_notifier
