"""
登录限流存储抽象层，提供进程内存和数据库两种后端实现。
支持通过 RATE_LIMIT_BACKEND 配置切换，实现多 worker 部署时限流状态共享。

接口约定：
- get_retry_after_seconds(key) → int: 返回需等待秒数，0 表示允许尝试
- record_failed_attempt(key) → None: 记录一次失败尝试
- clear_attempts(key) → None: 登录成功后清理限流状态
"""

import math
import threading
import time
from abc import ABC, abstractmethod
from collections import deque
from typing import Optional

from loguru import logger
from sqlalchemy.orm import Session

from db.models import LoginRateLimit

# ==================== 限流参数（与 auth.py 原有常量保持一致） ====================

LOGIN_ATTEMPT_WINDOW_SECONDS = 5 * 60       # 失败计数窗口（5 分钟）
LOGIN_MAX_ATTEMPTS = 5                       # 窗口内最大失败次数
LOGIN_BLOCK_SECONDS = 15 * 60                # 触发限流后封禁时长（15 分钟）
LOGIN_CLEANUP_INTERVAL_SECONDS = 60          # 过期条目清理间隔
LOGIN_STATE_MAX_CAPACITY = 10000             # 内存存储容量上限


# ==================== 抽象基类 ====================

class RateLimitStore(ABC):
    """登录限流存储的抽象接口，定义三种核心操作。"""

    @abstractmethod
    def get_retry_after_seconds(self, rate_limit_key: str) -> int:
        """
        检查指定键是否处于限流封禁状态。

        Args:
            rate_limit_key: 限流键（格式: "客户端IP|用户名"）。

        Returns:
            需等待的秒数，0 表示允许尝试。
        """
        ...

    @abstractmethod
    def record_failed_attempt(self, rate_limit_key: str) -> None:
        """
        记录一次失败登录尝试。

        Args:
            rate_limit_key: 限流键。
        """
        ...

    @abstractmethod
    def clear_attempts(self, rate_limit_key: str) -> None:
        """
        登录成功后清理该键的所有限流状态。

        Args:
            rate_limit_key: 限流键。
        """
        ...


# ==================== 进程内存实现 ====================

class MemoryRateLimitStore(RateLimitStore):
    """
    基于进程内存字典的限流存储实现。
    保留原有 auth.py 的完整逻辑，适用于单 worker 部署或开发环境。
    多进程/多实例部署时限流状态不共享。
    """

    def __init__(self):
        self._attempts: dict[str, deque[float]] = {}
        self._blocked_until: dict[str, float] = {}
        self._lock = threading.Lock()
        self._last_cleanup_at = 0.0
        logger.info("MemoryRateLimitStore 已初始化（单进程限流模式）")

    # ── 公共接口 ──────────────────────────────────────────────

    def get_retry_after_seconds(self, rate_limit_key: str) -> int:
        """检查键是否处于限流封禁状态，返回等待秒数。"""
        now = time.monotonic()
        with self._lock:
            self._cleanup_expired_state(now)
            blocked_until = self._blocked_until.get(rate_limit_key, 0.0)
            if blocked_until > now:
                return self._calc_retry_after(blocked_until, now)

            attempts = self._attempts.setdefault(rate_limit_key, deque())
            self._prune_attempts(attempts, now)

            if len(attempts) < LOGIN_MAX_ATTEMPTS:
                if not attempts:
                    self._attempts.pop(rate_limit_key, None)
                return 0

            # 达到限流阈值：清空尝试记录并设置封禁
            attempts.clear()
            self._attempts.pop(rate_limit_key, None)
            blocked_until = now + LOGIN_BLOCK_SECONDS
            self._blocked_until[rate_limit_key] = blocked_until
            return self._calc_retry_after(blocked_until, now)

    def record_failed_attempt(self, rate_limit_key: str) -> None:
        """记录一次失败登录尝试，含容量保护。"""
        now = time.monotonic()
        with self._lock:
            self._cleanup_expired_state(now)
            total = len(self._attempts) + len(self._blocked_until)
            if total >= LOGIN_STATE_MAX_CAPACITY:
                self._force_full_cleanup(now)
                if len(self._attempts) + len(self._blocked_until) >= LOGIN_STATE_MAX_CAPACITY:
                    logger.bind(
                        event="login_rate_limit_capacity_reached",
                        module="rate_limit_store",
                        total=total,
                        max_capacity=LOGIN_STATE_MAX_CAPACITY,
                    ).warning("MemoryRateLimitStore 达到容量上限，拒绝记录新的失败尝试")
                    return
            attempts = self._attempts.setdefault(rate_limit_key, deque())
            self._prune_attempts(attempts, now)
            attempts.append(now)

    def clear_attempts(self, rate_limit_key: str) -> None:
        """登录成功后清理该键的限流状态。"""
        with self._lock:
            self._attempts.pop(rate_limit_key, None)
            self._blocked_until.pop(rate_limit_key, None)

    def _test_inject_state(self, stale_key: Optional[str] = None, blocked_until: float = 0.0) -> None:
        """
        测试辅助方法：注入指定的限流状态，避免测试直接操作私有属性。

        Args:
            stale_key: 要注入过期状态的目标键。
            blocked_until: 封禁截止时间（monotonic 时间戳）。
        """
        if stale_key:
            with self._lock:
                self._attempts[stale_key] = deque([0.0])
                self._blocked_until[stale_key] = blocked_until

    # ── 内部方法 ──────────────────────────────────────────────

    @staticmethod
    def _calc_retry_after(blocked_until: float, now: float) -> int:
        """将单调时钟差值转换为 Retry-After 秒数。"""
        return max(1, math.ceil(blocked_until - now))

    @staticmethod
    def _prune_attempts(attempts: deque[float], now: float) -> None:
        """删除窗口外的失败记录。"""
        while attempts and now - attempts[0] > LOGIN_ATTEMPT_WINDOW_SECONDS:
            attempts.popleft()

    def _cleanup_expired_state(self, now: float) -> None:
        """定期清理过期的封禁和尝试记录。"""
        if now - self._last_cleanup_at < LOGIN_CLEANUP_INTERVAL_SECONDS:
            return

        expired = [k for k, bt in self._blocked_until.items() if bt <= now]
        for key in expired:
            self._blocked_until.pop(key, None)

        stale: list[str] = []
        for key, attempts in list(self._attempts.items()):
            self._prune_attempts(attempts, now)
            if not attempts and key not in self._blocked_until:
                stale.append(key)

        for key in stale:
            self._attempts.pop(key, None)

        self._last_cleanup_at = now

    def _force_full_cleanup(self, now: float) -> None:
        """强制执行全量过期清理，用于容量保护。"""
        expired = [k for k, bt in self._blocked_until.items() if bt <= now]
        for key in expired:
            self._blocked_until.pop(key, None)

        stale: list[str] = []
        for key, attempts in list(self._attempts.items()):
            self._prune_attempts(attempts, now)
            if not attempts and key not in self._blocked_until:
                stale.append(key)

        for key in stale:
            self._attempts.pop(key, None)


# ==================== 数据库持久化实现 ====================

class DatabaseRateLimitStore(RateLimitStore):
    """
    基于数据库的登录限流存储实现。
    限流状态持久化到 login_rate_limits 表，支持多 worker 部署时状态共享。

    使用 SQLAlchemy Session 进行事务性操作，row-level locking 保证并发安全。

    注意：使用 time.time()（Unix 时间戳）以确保跨进程/跨机器的时钟一致性。
    MemoryRateLimitStore 使用 time.monotonic()（单进程内不受系统时钟跳变影响）。
    """

    def __init__(self, db_session_factory):
        """
        初始化数据库限流存储。

        Args:
            db_session_factory: 返回 SQLAlchemy Session 的可调用对象（如 SessionLocal）。
        """
        self._session_factory = db_session_factory
        self._last_cleanup_at = 0.0
        logger.info("DatabaseRateLimitStore 已初始化（分布式限流模式）")

    def get_retry_after_seconds(self, rate_limit_key: str) -> int:
        """检查键是否处于限流封禁状态，返回等待秒数。"""
        now = time.time()
        db: Session = self._session_factory()

        try:
            # 低频执行过期记录清理
            self._cleanup_expired_records(db, now)

            record = (
                db.query(LoginRateLimit)
                .filter(LoginRateLimit.rate_limit_key == rate_limit_key)
                .with_for_update()
                .first()
            )

            if record is None:
                return 0

            # 检查封禁状态
            if record.blocked_until > now:
                return max(1, math.ceil(record.blocked_until - now))

            # 清理窗口外的旧记录
            if record.first_attempt_at > 0 and now - record.first_attempt_at > LOGIN_ATTEMPT_WINDOW_SECONDS:
                record.attempt_count = 0
                record.first_attempt_at = 0.0
                record.blocked_until = 0.0
                db.commit()
                return 0

            # 检查是否超过最大尝试次数
            if record.attempt_count < LOGIN_MAX_ATTEMPTS:
                if record.attempt_count == 0:
                    # 无有效尝试，清理记录
                    db.delete(record)
                    db.commit()
                return 0

            # 触发封禁
            blocked_until = now + LOGIN_BLOCK_SECONDS
            record.blocked_until = blocked_until
            record.attempt_count = 0
            record.first_attempt_at = 0.0
            db.commit()
            return max(1, math.ceil(blocked_until - now))

        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def record_failed_attempt(self, rate_limit_key: str) -> None:
        """记录一次失败登录尝试。"""
        now = time.time()
        db: Session = self._session_factory()

        try:
            # 低频执行过期记录清理
            self._cleanup_expired_records(db, now)

            record = (
                db.query(LoginRateLimit)
                .filter(LoginRateLimit.rate_limit_key == rate_limit_key)
                .with_for_update()
                .first()
            )

            if record is None:
                record = LoginRateLimit(
                    rate_limit_key=rate_limit_key,
                    attempt_count=1,
                    first_attempt_at=now,
                    blocked_until=0.0,
                )
                db.add(record)
            else:
                # 清理窗口外的旧记录，同时重置 blocked_until
                if record.first_attempt_at > 0 and now - record.first_attempt_at > LOGIN_ATTEMPT_WINDOW_SECONDS:
                    record.attempt_count = 0
                    record.first_attempt_at = now
                    record.blocked_until = 0.0

                record.attempt_count += 1
                if record.first_attempt_at == 0.0:
                    record.first_attempt_at = now

            db.commit()

        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def clear_attempts(self, rate_limit_key: str) -> None:
        """登录成功后删除该键的限流记录，同时触发一次低频过期清理。"""
        db: Session = self._session_factory()

        try:
            # 低频执行过期记录清理
            self._cleanup_expired_records(db, time.time())

            record = (
                db.query(LoginRateLimit)
                .filter(LoginRateLimit.rate_limit_key == rate_limit_key)
                .first()
            )
            if record:
                db.delete(record)
                db.commit()

        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _cleanup_expired_records(self, db: Session, now: float) -> None:
        """
        低频清理过期的限流记录，避免 login_rate_limits 表无限增长。

        清理条件：
        - 已过期的封禁记录（blocked_until <= now 且 attempt_count = 0）
        - 窗口外且无封禁的旧尝试记录（first_attempt_at + window < now 且 blocked_until = 0）
        """
        if now - self._last_cleanup_at < LOGIN_CLEANUP_INTERVAL_SECONDS:
            return

        expired_blocked = (
            db.query(LoginRateLimit)
            .filter(
                LoginRateLimit.blocked_until > 0,
                LoginRateLimit.blocked_until <= now,
                LoginRateLimit.attempt_count == 0,
            )
            .delete(synchronize_session="fetch")
        )
        stale_window = (
            db.query(LoginRateLimit)
            .filter(
                LoginRateLimit.first_attempt_at > 0,
                LoginRateLimit.first_attempt_at + LOGIN_ATTEMPT_WINDOW_SECONDS <= now,
                LoginRateLimit.blocked_until == 0.0,
            )
            .delete(synchronize_session="fetch")
        )

        if expired_blocked > 0 or stale_window > 0:
            db.commit()
            logger.debug(
                f"DatabaseRateLimitStore 清理了 {expired_blocked} 条过期封禁 + "
                f"{stale_window} 条过期尝试记录"
            )

        self._last_cleanup_at = now


# ==================== 工厂函数 ====================

# 全局单例，由 lifespan startup 初始化
_rate_limit_store: Optional[RateLimitStore] = None
_store_lock = threading.Lock()


def get_rate_limit_store() -> RateLimitStore:
    """
    获取当前配置的限流存储实例。
    必须在应用启动时调用 init_rate_limit_store() 初始化。

    Returns:
        RateLimitStore 实例。

    Raises:
        RuntimeError: 存储未初始化。
    """
    if _rate_limit_store is None:
        raise RuntimeError("RateLimitStore 尚未初始化，请在 lifespan startup 中调用 init_rate_limit_store()")
    return _rate_limit_store


def init_rate_limit_store(backend: str = "memory", db_session_factory=None) -> RateLimitStore:
    """
    根据配置初始化全局限流存储实例。

    Args:
        backend: 后端类型，可选 "memory" 或 "database"。
        db_session_factory: 数据库会话工厂（database 后端必需）。

    Returns:
        初始化后的 RateLimitStore 实例。

    Raises:
        ValueError: 后端类型不支持或缺少必要参数。
    """
    global _rate_limit_store

    with _store_lock:
        backend_normalized = backend.strip().lower()

        if backend_normalized == "memory":
            _rate_limit_store = MemoryRateLimitStore()
        elif backend_normalized == "database":
            if db_session_factory is None:
                raise ValueError("database 后端需要提供 db_session_factory 参数")
            _rate_limit_store = DatabaseRateLimitStore(db_session_factory)
        else:
            raise ValueError(f"不支持的 RATE_LIMIT_BACKEND: {backend}，可选值: memory, database")

        logger.info(f"RateLimitStore 已初始化为 {backend_normalized} 后端")
        return _rate_limit_store
