"""
微信消息监控主循环模块
实现长轮询监控、错误恢复和会话保护机制
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from loguru import logger

from skills.weixin.config import (
    WeixinRuntimeConfig,
    SESSION_EXPIRED_ERRCODE,
    SESSION_PAUSE_DURATION_SECONDS,
)
from skills.weixin.errors import WeixinAdapterError
from skills.weixin.storage.state import StateManager
from skills.weixin.messaging.process import poll_updates, check_session_active
from skills.weixin.messaging.inbound import InboundMessage, parse_messages_from_response
from skills.weixin.utils.retry import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerOpenError,
    ExponentialBackoff,
    RetryConfig,
)


class MonitorState(Enum):
    """监控器状态枚举"""

    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPING = "stopping"
    ERROR = "error"


@dataclass
class MonitorStatus:
    """
    监控器状态数据类
    封装监控器的运行状态信息

    属性:
        account_id: 账号ID
        state: 当前状态
        running: 是否正在运行
        paused: 是否暂停
        consecutive_failures: 连续失败次数
        total_messages: 总消息数
        last_message_at: 最后一条消息时间戳
        last_error: 最后错误信息
        last_error_at: 最后错误时间戳
        started_at: 启动时间戳
        circuit_breaker_state: 熔断器状态
        session_paused: 会话是否暂停
        session_remaining_seconds: 会话剩余暂停时间
    """

    account_id: str
    state: MonitorState
    running: bool
    paused: bool
    consecutive_failures: int
    total_messages: int
    last_message_at: Optional[float]
    last_error: Optional[str]
    last_error_at: Optional[float]
    started_at: Optional[float]
    circuit_breaker_state: str
    session_paused: bool
    session_remaining_seconds: int

    def to_dict(self) -> Dict[str, Any]:
        """
        将状态转换为字典格式

        返回:
            包含状态信息的字典
        """
        return {
            "account_id": self.account_id,
            "state": self.state.value,
            "running": self.running,
            "paused": self.paused,
            "consecutive_failures": self.consecutive_failures,
            "total_messages": self.total_messages,
            "last_message_at": self.last_message_at,
            "last_error": self.last_error,
            "last_error_at": self.last_error_at,
            "started_at": self.started_at,
            "circuit_breaker_state": self.circuit_breaker_state,
            "session_paused": self.session_paused,
            "session_remaining_seconds": self.session_remaining_seconds,
        }


@dataclass
class MonitorConfig:
    """
    监控器配置类
    封装监控器的配置参数

    属性:
        longpoll_timeout_seconds: 长轮询超时时间（秒），默认38秒
        max_consecutive_failures: 最大连续失败次数，默认3次
        backoff_delay_seconds: 退避延迟时间（秒），默认30秒
        retry_delay_seconds: 重试延迟时间（秒），默认2秒
        message_handler: 消息处理回调函数
        error_handler: 错误处理回调函数
    """

    longpoll_timeout_seconds: int = 38
    max_consecutive_failures: int = 3
    backoff_delay_seconds: float = 30.0
    retry_delay_seconds: float = 2.0
    message_handler: Optional[Callable[[InboundMessage], None]] = None
    error_handler: Optional[Callable[[Exception], None]] = None


class WeixinMonitor:
    """
    微信消息监控器类
    实现长轮询监控循环，包含错误恢复和会话保护机制

    该类负责:
    1. 持续轮询微信服务器获取新消息
    2. 持久化get_updates游标
    3. 实现指数退避和熔断器错误恢复策略
    4. 检测会话过期并暂停保护
    5. 提供监控启动/停止接口

    属性:
        config: 运行时配置
        state_manager: 状态管理器
        monitor_config: 监控器配置
        state: 当前监控状态
        circuit_breaker: 熔断器实例
    """

    _instances: Dict[str, WeixinMonitor] = {}

    def __init__(
        self,
        config: WeixinRuntimeConfig,
        state_manager: StateManager,
        monitor_config: Optional[MonitorConfig] = None,
    ) -> None:
        """
        初始化监控器实例

        参数:
            config: 微信运行时配置
            state_manager: 状态管理器，用于持久化游标和上下文令牌
            monitor_config: 监控器配置，可选
        """
        self.config = config
        self.state_manager = state_manager
        self.monitor_config = monitor_config or MonitorConfig()

        self._state = MonitorState.STOPPED
        self._running = False
        self._paused = False
        self._stop_event = asyncio.Event()
        self._pause_event = asyncio.Event()
        self._task: Optional[asyncio.Task] = None

        self._consecutive_failures = 0
        self._total_messages = 0
        self._last_message_at: Optional[float] = None
        self._last_error: Optional[str] = None
        self._last_error_at: Optional[float] = None
        self._started_at: Optional[float] = None

        self._cursor = ""

        self.circuit_breaker = CircuitBreaker(
            name=f"weixin_monitor_{config.account_id}",
            config=CircuitBreakerConfig(
                failure_threshold=self.monitor_config.max_consecutive_failures,
                recovery_timeout_ms=int(self.monitor_config.backoff_delay_seconds * 1000),
                half_open_max_calls=1,
            ),
        )

        self._backoff = ExponentialBackoff(
            RetryConfig(
                base_delay_ms=int(self.monitor_config.retry_delay_seconds * 1000),
                max_delay_ms=int(self.monitor_config.backoff_delay_seconds * 1000),
            )
        )

    @property
    def state(self) -> MonitorState:
        """获取当前监控状态"""
        return self._state

    @property
    def account_id(self) -> str:
        """获取账号ID"""
        return self.config.account_id

    def get_status(self) -> MonitorStatus:
        """
        获取监控器状态信息

        返回:
            MonitorStatus实例，包含完整的状态信息
        """
        return MonitorStatus(
            account_id=self.config.account_id,
            state=self._state,
            running=self._running,
            paused=self._paused,
            consecutive_failures=self._consecutive_failures,
            total_messages=self._total_messages,
            last_message_at=self._last_message_at,
            last_error=self._last_error,
            last_error_at=self._last_error_at,
            started_at=self._started_at,
            circuit_breaker_state=self.circuit_breaker.get_state()["state"],
            session_paused=self.state_manager.is_session_paused(self.config.account_id),
            session_remaining_seconds=self.state_manager.remaining_pause_seconds(
                self.config.account_id
            ),
        )

    async def start(self) -> None:
        """
        启动监控循环

        如果监控器已经在运行，则不做任何操作。
        启动后会持续轮询微信服务器获取新消息，直到调用stop()方法。
        """
        if self._running:
            logger.warning(f"[WeixinMonitor:{self.account_id}] 监控器已在运行中")
            return

        self._state = MonitorState.STARTING
        self._running = True
        self._stop_event.clear()
        self._pause_event.clear()
        self._started_at = time.time()

        self._cursor = self.state_manager.load_get_updates_buf(self.config.account_id)
        logger.info(
            f"[WeixinMonitor:{self.account_id}] 启动监控，"
            f"初始游标长度={len(self._cursor)}"
        )

        self._task = asyncio.create_task(self._monitor_loop())
        self._state = MonitorState.RUNNING

        logger.info(f"[WeixinMonitor:{self.account_id}] 监控器已启动")

    async def stop(self) -> None:
        """
        停止监控循环

        设置停止标志并等待监控循环结束。
        """
        if not self._running:
            logger.warning(f"[WeixinMonitor:{self.account_id}] 监控器未在运行")
            return

        self._state = MonitorState.STOPPING
        self._stop_event.set()
        self._pause_event.set()

        if self._task and not self._task.done():
            try:
                await asyncio.wait_for(self._task, timeout=10.0)
            except asyncio.TimeoutError:
                logger.warning(f"[WeixinMonitor:{self.account_id}] 监控任务停止超时，强制取消")
                self._task.cancel()
                try:
                    await self._task
                except asyncio.CancelledError:
                    pass

        self._running = False
        self._state = MonitorState.STOPPED
        logger.info(f"[WeixinMonitor:{self.account_id}] 监控器已停止")

    async def pause(self) -> None:
        """
        暂停监控循环

        暂停后监控循环会等待恢复信号。
        """
        if not self._running:
            return

        self._paused = True
        self._pause_event.set()
        self._state = MonitorState.PAUSED
        logger.info(f"[WeixinMonitor:{self.account_id}] 监控器已暂停")

    async def resume(self) -> None:
        """
        恢复监控循环

        清除暂停标志，监控循环继续执行。
        """
        if not self._running:
            return

        self._paused = False
        self._pause_event.clear()
        if self._state == MonitorState.PAUSED:
            self._state = MonitorState.RUNNING
        logger.info(f"[WeixinMonitor:{self.account_id}] 监控器已恢复")

    async def _monitor_loop(self) -> None:
        """
        监控主循环

        持续轮询微信服务器获取新消息，处理错误并实现退避策略。
        """
        logger.info(f"[WeixinMonitor:{self.account_id}] 进入监控主循环")

        while not self._stop_event.is_set():
            try:
                if self._paused:
                    await self._wait_for_resume()
                    continue

                if self.state_manager.is_session_paused(self.config.account_id):
                    await self._handle_session_paused()
                    continue

                if not await self.circuit_breaker.can_execute():
                    await self._handle_circuit_breaker_open()
                    continue

                await self._poll_and_process()

                self._consecutive_failures = 0
                await self.circuit_breaker.record_success()

            except CircuitBreakerOpenError as exc:
                logger.warning(f"[WeixinMonitor:{self.account_id}] 熔断器打开: {exc}")
                await self._handle_circuit_breaker_open()

            except WeixinAdapterError as exc:
                await self._handle_weixin_error(exc)

            except asyncio.CancelledError:
                logger.info(f"[WeixinMonitor:{self.account_id}] 监控任务被取消")
                break

            except Exception as exc:
                await self._handle_unexpected_error(exc)

        logger.info(f"[WeixinMonitor:{self.account_id}] 退出监控主循环")

    async def _poll_and_process(self) -> None:
        """
        执行轮询并处理消息
        """
        result = await poll_updates(
            config=self.config,
            state_manager=self.state_manager,
            cursor=self._cursor,
        )

        response = result.get("response", {})
        self._cursor = result.get("cursor", "")

        errcode = response.get("errcode")
        ret = response.get("ret")

        if errcode == SESSION_EXPIRED_ERRCODE or ret == SESSION_EXPIRED_ERRCODE:
            logger.warning(f"[WeixinMonitor:{self.account_id}] 检测到会话过期")
            self.state_manager.pause_session(self.config.account_id)
            return

        messages = parse_messages_from_response(response)
        if messages:
            self._total_messages += len(messages)
            self._last_message_at = time.time()
            logger.debug(
                f"[WeixinMonitor:{self.account_id}] 收到{len(messages)}条消息"
            )

            for msg in messages:
                await self._process_message(msg)

    async def _process_message(self, message: InboundMessage) -> None:
        """
        处理单条消息

        参数:
            message: 入站消息实例
        """
        try:
            if self.monitor_config.message_handler:
                handler = self.monitor_config.message_handler
                if asyncio.iscoroutinefunction(handler):
                    await handler(message)
                else:
                    handler(message)
        except Exception as exc:
            logger.warning(
                f"[WeixinMonitor:{self.account_id}] 消息处理失败: {exc}, "
                f"seq={message.seq}, from={message.from_user_id}"
            )

    async def _wait_for_resume(self) -> None:
        """
        等待恢复信号
        """
        logger.debug(f"[WeixinMonitor:{self.account_id}] 等待恢复...")
        try:
            await asyncio.wait_for(self._pause_event.wait(), timeout=1.0)
        except asyncio.TimeoutError:
            pass

    async def _handle_session_paused(self) -> None:
        """
        处理会话暂停状态
        """
        remaining = self.state_manager.remaining_pause_seconds(self.config.account_id)
        logger.warning(
            f"[WeixinMonitor:{self.account_id}] 会话已暂停，"
            f"剩余{remaining}秒"
        )

        wait_time = min(remaining, 60)
        try:
            await asyncio.sleep(wait_time)
        except asyncio.CancelledError:
            pass

    async def _handle_circuit_breaker_open(self) -> None:
        """
        处理熔断器打开状态
        """
        self._state = MonitorState.ERROR
        recovery_ms = self.circuit_breaker.config.recovery_timeout_ms
        recovery_seconds = recovery_ms / 1000

        logger.warning(
            f"[WeixinMonitor:{self.account_id}] 熔断器打开，"
            f"等待{recovery_seconds}秒后重试"
        )

        try:
            await asyncio.sleep(recovery_seconds)
        except asyncio.CancelledError:
            pass

        if not self._stop_event.is_set():
            self._state = MonitorState.RUNNING

    async def _handle_weixin_error(self, exc: WeixinAdapterError) -> None:
        """
        处理微信适配器错误

        参数:
            exc: 微信适配器错误实例
        """
        self._consecutive_failures += 1
        self._last_error = str(exc)
        self._last_error_at = time.time()

        await self.circuit_breaker.record_failure()

        logger.error(
            f"[WeixinMonitor:{self.account_id}] 微信错误: {exc}, "
            f"连续失败次数={self._consecutive_failures}"
        )

        if self.monitor_config.error_handler:
            try:
                handler = self.monitor_config.error_handler
                if asyncio.iscoroutinefunction(handler):
                    await handler(exc)
                else:
                    handler(exc)
            except Exception as handler_exc:
                logger.warning(f"[WeixinMonitor:{self.account_id}] 错误处理器失败: {handler_exc}")

        delay_ms = self._backoff.get_delay_ms(self._consecutive_failures - 1)
        delay_seconds = delay_ms / 1000

        logger.info(f"[WeixinMonitor:{self.account_id}] 等待{delay_seconds}秒后重试")

        try:
            await asyncio.sleep(delay_seconds)
        except asyncio.CancelledError:
            pass

    async def _handle_unexpected_error(self, exc: Exception) -> None:
        """
        处理未预期的错误

        参数:
            exc: 异常实例
        """
        self._consecutive_failures += 1
        self._last_error = f"{type(exc).__name__}: {exc}"
        self._last_error_at = time.time()

        await self.circuit_breaker.record_failure()

        logger.exception(
            f"[WeixinMonitor:{self.account_id}] 未预期错误: {exc}, "
            f"连续失败次数={self._consecutive_failures}"
        )

        if self.monitor_config.error_handler:
            try:
                handler = self.monitor_config.error_handler
                if asyncio.iscoroutinefunction(handler):
                    await handler(exc)
                else:
                    handler(exc)
            except Exception as handler_exc:
                logger.warning(f"[WeixinMonitor:{self.account_id}] 错误处理器失败: {handler_exc}")

        delay_ms = self._backoff.get_delay_ms(self._consecutive_failures - 1)
        delay_seconds = delay_ms / 1000

        logger.info(f"[WeixinMonitor:{self.account_id}] 等待{delay_seconds}秒后重试")

        try:
            await asyncio.sleep(delay_seconds)
        except asyncio.CancelledError:
            pass

    @classmethod
    def get_instance(cls, account_id: str) -> Optional[WeixinMonitor]:
        """
        获取指定账号的监控器实例

        参数:
            account_id: 账号ID

        返回:
            WeixinMonitor实例，如果不存在则返回None
        """
        return cls._instances.get(account_id)

    @classmethod
    def register_instance(cls, monitor: WeixinMonitor) -> None:
        """
        注册监控器实例

        参数:
            monitor: WeixinMonitor实例
        """
        cls._instances[monitor.account_id] = monitor

    @classmethod
    def unregister_instance(cls, account_id: str) -> None:
        """
        注销监控器实例

        参数:
            account_id: 账号ID
        """
        cls._instances.pop(account_id, None)

    @classmethod
    def get_all_instances(cls) -> Dict[str, WeixinMonitor]:
        """
        获取所有监控器实例

        返回:
            账号ID到监控器实例的映射字典
        """
        return dict(cls._instances)


async def start_monitor(
    account_id: str,
    config: WeixinRuntimeConfig,
    state_manager: StateManager,
    monitor_config: Optional[MonitorConfig] = None,
) -> WeixinMonitor:
    """
    启动指定账号的监控器

    参数:
        account_id: 账号ID
        config: 微信运行时配置
        state_manager: 状态管理器
        monitor_config: 监控器配置，可选

    返回:
        WeixinMonitor实例

    抛出:
        ValueError: 当账号ID不匹配时
    """
    if config.account_id != account_id:
        raise ValueError(
            f"配置中的account_id({config.account_id})与参数account_id({account_id})不匹配"
        )

    existing = WeixinMonitor.get_instance(account_id)
    if existing and existing._running:
        logger.warning(f"[start_monitor] 账号{account_id}的监控器已在运行")
        return existing

    monitor = WeixinMonitor(
        config=config,
        state_manager=state_manager,
        monitor_config=monitor_config,
    )

    WeixinMonitor.register_instance(monitor)
    await monitor.start()

    return monitor


async def stop_monitor(account_id: str) -> None:
    """
    停止指定账号的监控器

    参数:
        account_id: 账号ID
    """
    monitor = WeixinMonitor.get_instance(account_id)
    if not monitor:
        logger.warning(f"[stop_monitor] 未找到账号{account_id}的监控器")
        return

    await monitor.stop()
    WeixinMonitor.unregister_instance(account_id)


def get_monitor_status(account_id: str) -> Optional[Dict[str, Any]]:
    """
    获取指定账号的监控器状态

    参数:
        account_id: 账号ID

    返回:
        状态字典，如果监控器不存在则返回None
    """
    monitor = WeixinMonitor.get_instance(account_id)
    if not monitor:
        return None

    return monitor.get_status().to_dict()


def get_all_monitors() -> Dict[str, Dict[str, Any]]:
    """
    获取所有监控器的状态

    返回:
        账号ID到状态字典的映射
    """
    result: Dict[str, Dict[str, Any]] = {}
    for account_id, monitor in WeixinMonitor.get_all_instances().items():
        result[account_id] = monitor.get_status().to_dict()
    return result
