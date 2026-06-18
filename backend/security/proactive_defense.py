"""
主动防御模块，提供 IP 白名单/黑名单、用户级速率限制、异常行为检测与 CSRF token 轮换。

主要组件：
- IpAccessController: IP 白名单/黑名单管理，支持单 IP 和 CIDR 网段
- UserRateLimiter: 用户级 API 速率限制，基于内存滑动窗口
- AnomalyDetector: 异常行为检测，识别速率突发和重复失败模式
- CsrfTokenManager: CSRF token 生成、校验、轮换

设计原则：
- IP 白名单优先级最高，命中白名单的请求跳过所有限制
- IP 黑名单次之，命中黑名单的请求直接拒绝
- 用户级速率限制独立于全局 IP 限流，按 user_id 维度计数
- 异常检测为被动观察，不主动拦截，仅记录事件供管理员审查
- CSRF token 支持一次性使用和自动轮换，过期 token 自动失效
"""

import ipaddress
import secrets
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Optional

from loguru import logger
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from db.models import AnomalyEvent, CsrfToken, IpAccessList


# ==================== IP 白名单/黑名单 ====================


class IpAccessController:
    """
    IP 访问控制器，管理白名单和黑名单。

    白名单优先级高于黑名单：若 IP 同时命中两者，按白名单放行。
    支持单 IP（如 "192.168.1.1"）和 CIDR 网段（如 "10.0.0.0/8"）。
    """

    def __init__(self, db: Session):
        """
        初始化 IP 访问控制器。

        Args:
            db: 数据库会话实例。
        """
        self.db = db

    def add_entry(
        self,
        ip_cidr: str,
        list_type: str,
        reason: str = "",
        created_by: Optional[str] = None,
        expires_at: Optional[datetime] = None,
    ) -> IpAccessList:
        """
        添加 IP 到白名单或黑名单。

        Args:
            ip_cidr: IP 地址或 CIDR 网段。
            list_type: "whitelist" 或 "blacklist"。
            reason: 添加原因。
            created_by: 创建者用户 ID。
            expires_at: 过期时间，None 表示永不过期。

        Returns:
            创建的 IpAccessList 实例。

        Raises:
            ValueError: 参数非法或条目已存在。
        """
        ip_cidr = ip_cidr.strip()
        list_type = list_type.strip().lower()

        if list_type not in {"whitelist", "blacklist"}:
            raise ValueError(f"list_type 必须为 whitelist 或 blacklist，实际: {list_type}")

        # 校验 IP/CIDR 格式
        try:
            if "/" in ip_cidr:
                ipaddress.ip_network(ip_cidr, strict=False)
            else:
                ipaddress.ip_address(ip_cidr)
        except ValueError as e:
            raise ValueError(f"IP/CIDR 格式非法: {ip_cidr}") from e

        # 检查是否已存在
        existing = (
            self.db.query(IpAccessList)
            .filter(
                IpAccessList.ip_cidr == ip_cidr,
                IpAccessList.list_type == list_type,
            )
            .first()
        )
        if existing:
            raise ValueError(f"{list_type} 条目已存在: {ip_cidr}")

        entry = IpAccessList(
            ip_cidr=ip_cidr,
            list_type=list_type,
            reason=reason,
            created_by=created_by,
            is_active=True,
            expires_at=expires_at,
        )
        self.db.add(entry)
        try:
            self.db.commit()
        except IntegrityError as e:
            self.db.rollback()
            raise ValueError(f"{list_type} 条目已存在: {ip_cidr}（并发创建冲突）") from e
        self.db.refresh(entry)
        logger.bind(
            event="ip_access_added",
            ip_cidr=ip_cidr,
            list_type=list_type,
        ).info(f"IP 访问条目已添加: {list_type} {ip_cidr}")
        return entry

    def remove_entry(self, entry_id: int) -> bool:
        """
        移除 IP 访问条目。

        Args:
            entry_id: 条目 ID。

        Returns:
            True 表示删除成功。

        Raises:
            ValueError: 条目不存在。
        """
        entry = self.db.query(IpAccessList).filter(IpAccessList.id == entry_id).first()
        if not entry:
            raise ValueError(f"IP 访问条目 {entry_id} 不存在")

        info = f"{entry.list_type} {entry.ip_cidr}"
        self.db.delete(entry)
        self.db.commit()
        logger.bind(event="ip_access_removed", entry_id=entry_id).info(f"IP 访问条目已移除: {info}")
        return True

    def list_entries(
        self,
        list_type: Optional[str] = None,
        active_only: bool = True,
    ) -> list[dict]:
        """
        列出 IP 访问条目。

        Args:
            list_type: 筛选类型（whitelist/blacklist），None 表示全部。
            active_only: 是否仅返回活跃条目。

        Returns:
            条目信息字典列表。
        """
        query = self.db.query(IpAccessList)
        if list_type:
            list_type = list_type.strip().lower()
            query = query.filter(IpAccessList.list_type == list_type)
        if active_only:
            query = query.filter(IpAccessList.is_active.is_(True))

        entries = query.order_by(IpAccessList.created_at.desc()).all()
        return [
            {
                "id": e.id,
                "ip_cidr": e.ip_cidr,
                "list_type": e.list_type,
                "reason": e.reason,
                "created_by": e.created_by,
                "is_active": e.is_active,
                "expires_at": e.expires_at.isoformat() if e.expires_at else None,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in entries
        ]

    def check_ip(self, ip_address_str: str) -> dict:
        """
        检查 IP 是否被允许访问。

        白名单优先：命中白名单直接放行，即使同时在黑名单中。
        黑名单次之：命中黑名单拒绝。
        默认策略：无任何匹配时放行。

        Args:
            ip_address_str: 客户端 IP 地址字符串。

        Returns:
            决策字典：
            - allowed: bool 是否允许
            - reason: str 决策原因
            - matched_list: str 命中的列表类型（whitelist/blacklist/none）
        """
        try:
            client_ip = ipaddress.ip_address(ip_address_str)
        except ValueError:
            return {
                "allowed": False,
                "reason": f"IP 地址格式非法: {ip_address_str}",
                "matched_list": "none",
            }

        now = datetime.now(timezone.utc)
        # 获取所有活跃条目
        entries = (
            self.db.query(IpAccessList)
            .filter(IpAccessList.is_active.is_(True))
            .all()
        )

        for entry in entries:
            # 跳过已过期条目
            if entry.expires_at:
                expires_at = entry.expires_at
                # SQLite 存储的 datetime 可能缺少时区信息，统一补齐
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=timezone.utc)
                if expires_at <= now:
                    continue

            try:
                if "/" in entry.ip_cidr:
                    network = ipaddress.ip_network(entry.ip_cidr, strict=False)
                    if client_ip in network:
                        if entry.list_type == "whitelist":
                            return {
                                "allowed": True,
                                "reason": f"IP 命中白名单: {entry.ip_cidr}",
                                "matched_list": "whitelist",
                            }
                        if entry.list_type == "blacklist":
                            return {
                                "allowed": False,
                                "reason": f"IP 命中黑名单: {entry.ip_cidr}",
                                "matched_list": "blacklist",
                            }
                else:
                    entry_ip = ipaddress.ip_address(entry.ip_cidr)
                    if client_ip == entry_ip:
                        if entry.list_type == "whitelist":
                            return {
                                "allowed": True,
                                "reason": f"IP 命中白名单: {entry.ip_cidr}",
                                "matched_list": "whitelist",
                            }
                        if entry.list_type == "blacklist":
                            return {
                                "allowed": False,
                                "reason": f"IP 命中黑名单: {entry.ip_cidr}",
                                "matched_list": "blacklist",
                            }
            except ValueError:
                # 跳过格式损坏的条目
                continue

        return {
            "allowed": True,
            "reason": "IP 未命中任何列表，默认放行",
            "matched_list": "none",
        }


# ==================== 用户级速率限制 ====================


class UserRateLimiter:
    """
    用户级 API 速率限制器，基于内存滑动窗口。

    每个 user_id 维护独立的请求计数窗口，超过阈值时返回 False。
    线程安全，使用 threading.Lock 保护内部状态。
    """

    def __init__(
        self,
        max_requests: int = 100,
        window_seconds: int = 60,
        max_tracked_users: int = 10000,
    ):
        """
        初始化用户级速率限制器。

        Args:
            max_requests: 窗口内最大请求数，默认 100。
            window_seconds: 窗口大小（秒），默认 60。
            max_tracked_users: 追踪用户数上限，防止内存无限增长。
        """
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.max_tracked_users = max_tracked_users
        self._requests: dict[str, deque[float]] = {}
        self._lock = threading.Lock()
        self._last_cleanup = time.monotonic()
        logger.info(
            f"UserRateLimiter 已初始化（max={max_requests}, window={window_seconds}s）"
        )

    def _cleanup_stale_users(self, now: float) -> None:
        """
        清理窗口内无请求的用户条目，防止内存无限增长。
        必须在持有 _lock 时调用。
        """
        # 每 5 分钟执行一次清理
        if now - self._last_cleanup < 300:
            return

        stale_users = [
            uid for uid, times in self._requests.items()
            if not times or now - times[-1] > self.window_seconds
        ]
        for uid in stale_users:
            self._requests.pop(uid, None)

        self._last_cleanup = now

    def check(self, user_id: str) -> dict:
        """
        检查用户是否超过速率限制。

        此方法会记录当前请求时间戳，并清理窗口外的旧记录。

        Args:
            user_id: 用户唯一标识。

        Returns:
            决策字典：
            - allowed: bool 是否允许
            - remaining: int 剩余请求数
            - reset_at: float 窗口重置时间（monotonic 时间戳）
        """
        if not user_id:
            return {"allowed": True, "remaining": -1, "reset_at": 0.0}

        now = time.monotonic()
        with self._lock:
            # 定期清理过期用户条目
            self._cleanup_stale_users(now)

            requests = self._requests.setdefault(user_id, deque())
            # 清理窗口外的旧记录
            while requests and now - requests[0] > self.window_seconds:
                requests.popleft()

            if len(requests) >= self.max_requests:
                reset_at = requests[0] + self.window_seconds
                return {
                    "allowed": False,
                    "remaining": 0,
                    "reset_at": reset_at,
                }

            requests.append(now)
            remaining = self.max_requests - len(requests)
            return {
                "allowed": True,
                "remaining": remaining,
                "reset_at": 0.0,
            }

    def reset(self, user_id: str) -> None:
        """
        重置指定用户的速率限制状态。

        Args:
            user_id: 用户唯一标识。
        """
        with self._lock:
            self._requests.pop(user_id, None)

    def get_stats(self, user_id: str) -> dict:
        """
        获取指定用户的速率限制统计。

        Args:
            user_id: 用户唯一标识。

        Returns:
            统计字典：current_count, max_requests, window_seconds。
        """
        now = time.monotonic()
        with self._lock:
            requests = self._requests.get(user_id, deque())
            # 清理窗口外的旧记录
            while requests and now - requests[0] > self.window_seconds:
                requests.popleft()
            return {
                "current_count": len(requests),
                "max_requests": self.max_requests,
                "window_seconds": self.window_seconds,
            }


# 全局单例
_user_rate_limiter: Optional[UserRateLimiter] = None
_limiter_lock = threading.Lock()


def get_user_rate_limiter() -> UserRateLimiter:
    """
    获取全局用户级速率限制器单例。

    Returns:
        UserRateLimiter 实例。
    """
    global _user_rate_limiter
    if _user_rate_limiter is None:
        with _limiter_lock:
            if _user_rate_limiter is None:
                _user_rate_limiter = UserRateLimiter()
    return _user_rate_limiter


# ==================== 异常行为检测 ====================


class AnomalyDetector:
    """
    异常行为检测器，识别速率突发和重复失败模式。

    检测策略：
    - rate_burst: 短时间内请求量超过阈值（如 60 秒内 200 次）
    - repeated_failure: 短时间内失败请求超过阈值（如 60 秒内 50 次失败）

    检测为被动观察，仅记录事件到数据库，不主动拦截。
    """

    def __init__(
        self,
        burst_threshold: int = 200,
        burst_window: int = 60,
        failure_threshold: int = 50,
        failure_window: int = 60,
        max_tracked_users: int = 10000,
    ):
        """
        初始化异常行为检测器。

        Args:
            burst_threshold: 速率突发阈值。
            burst_window: 速率突发窗口（秒）。
            failure_threshold: 重复失败阈值。
            failure_window: 重复失败窗口（秒）。
            max_tracked_users: 追踪用户数上限，防止内存无限增长。
        """
        self.burst_threshold = burst_threshold
        self.burst_window = burst_window
        self.failure_threshold = failure_threshold
        self.failure_window = failure_window
        self.max_tracked_users = max_tracked_users
        self._request_times: dict[str, deque[float]] = {}
        self._failure_times: dict[str, deque[float]] = {}
        self._lock = threading.Lock()
        self._last_cleanup = time.monotonic()
        logger.info(
            f"AnomalyDetector 已初始化（burst={burst_threshold}/{burst_window}s, "
            f"failure={failure_threshold}/{failure_window}s）"
        )

    def _cleanup_stale_entries(self, now: float) -> None:
        """
        清理过期的追踪条目，防止内存无限增长。
        必须在持有 _lock 时调用。
        """
        # 每 5 分钟执行一次清理
        if now - self._last_cleanup < 300:
            return

        stale_request_users = [
            uid for uid, times in self._request_times.items()
            if not times or now - times[-1] > self.burst_window
        ]
        for uid in stale_request_users:
            self._request_times.pop(uid, None)

        stale_failure_users = [
            uid for uid, times in self._failure_times.items()
            if not times or now - times[-1] > self.failure_window
        ]
        for uid in stale_failure_users:
            self._failure_times.pop(uid, None)

        self._last_cleanup = now

    def record_request(self, user_id: str, is_failure: bool = False) -> Optional[dict]:
        """
        记录一次请求，并检测是否触发异常阈值。

        Args:
            user_id: 用户唯一标识。
            is_failure: 是否为失败请求。

        Returns:
            触发异常时返回事件字典，否则返回 None。
        """
        if not user_id:
            return None

        now = time.monotonic()
        triggered: Optional[dict] = None

        with self._lock:
            # 定期清理过期条目，防止内存无限增长
            self._cleanup_stale_entries(now)

            # 速率突发检测
            request_times = self._request_times.setdefault(user_id, deque())
            while request_times and now - request_times[0] > self.burst_window:
                request_times.popleft()
            request_times.append(now)

            if len(request_times) >= self.burst_threshold:
                triggered = {
                    "event_type": "rate_burst",
                    "user_id": user_id,
                    "trigger_detail": f"{self.burst_threshold} requests in {self.burst_window}s",
                    "observed_value": f"{len(request_times)} requests",
                    "action_taken": "warn",
                }
                # 触发后清空窗口，避免重复告警
                request_times.clear()

            # 重复失败检测
            if is_failure:
                failure_times = self._failure_times.setdefault(user_id, deque())
                while failure_times and now - failure_times[0] > self.failure_window:
                    failure_times.popleft()
                failure_times.append(now)

                if len(failure_times) >= self.failure_threshold and triggered is None:
                    triggered = {
                        "event_type": "repeated_failure",
                        "user_id": user_id,
                        "trigger_detail": f"{self.failure_threshold} failures in {self.failure_window}s",
                        "observed_value": f"{len(failure_times)} failures",
                        "action_taken": "warn",
                    }
                    failure_times.clear()

        return triggered

    def persist_event(
        self,
        db: Session,
        event: dict,
        ip_address: Optional[str] = None,
    ) -> AnomalyEvent:
        """
        将异常事件持久化到数据库。

        Args:
            db: 数据库会话实例。
            event: 异常事件字典。
            ip_address: 客户端 IP 地址。

        Returns:
            创建的 AnomalyEvent 实例。
        """
        anomaly = AnomalyEvent(
            event_type=event["event_type"],
            user_id=event.get("user_id"),
            ip_address=ip_address,
            trigger_detail=event.get("trigger_detail", ""),
            observed_value=event.get("observed_value", ""),
            action_taken=event.get("action_taken", "warn"),
            is_resolved=False,
        )
        db.add(anomaly)
        db.commit()
        db.refresh(anomaly)
        logger.bind(
            event="anomaly_detected",
            anomaly_type=anomaly.event_type,
            user_id=anomaly.user_id,
        ).warning(
            f"异常行为检测触发: {anomaly.event_type} (user={anomaly.user_id}, ip={ip_address})"
        )
        return anomaly

    def list_events(
        self,
        db: Session,
        event_type: Optional[str] = None,
        user_id: Optional[str] = None,
        resolved: Optional[bool] = None,
        limit: int = 50,
    ) -> list[dict]:
        """
        列出异常事件。

        Args:
            db: 数据库会话实例。
            event_type: 筛选事件类型。
            user_id: 筛选用户 ID。
            resolved: 筛选是否已解决。
            limit: 返回最大数量。

        Returns:
            事件信息字典列表。
        """
        query = db.query(AnomalyEvent)
        if event_type:
            query = query.filter(AnomalyEvent.event_type == event_type)
        if user_id:
            query = query.filter(AnomalyEvent.user_id == user_id)
        if resolved is not None:
            query = query.filter(AnomalyEvent.is_resolved == resolved)

        events = query.order_by(AnomalyEvent.created_at.desc()).limit(limit).all()
        return [
            {
                "id": e.id,
                "event_type": e.event_type,
                "user_id": e.user_id,
                "ip_address": e.ip_address,
                "trigger_detail": e.trigger_detail,
                "observed_value": e.observed_value,
                "action_taken": e.action_taken,
                "is_resolved": e.is_resolved,
                "created_at": e.created_at.isoformat() if e.created_at else None,
                "resolved_at": e.resolved_at.isoformat() if e.resolved_at else None,
            }
            for e in events
        ]

    def resolve_event(self, db: Session, event_id: int) -> bool:
        """
        标记异常事件为已解决。

        Args:
            db: 数据库会话实例。
            event_id: 事件 ID。

        Returns:
            True 表示标记成功。

        Raises:
            ValueError: 事件不存在。
        """
        event = db.query(AnomalyEvent).filter(AnomalyEvent.id == event_id).first()
        if not event:
            raise ValueError(f"异常事件 {event_id} 不存在")

        event.is_resolved = True
        event.resolved_at = datetime.now(timezone.utc)
        db.commit()
        return True


# 全局单例
_anomaly_detector: Optional[AnomalyDetector] = None
_detector_lock = threading.Lock()


def get_anomaly_detector() -> AnomalyDetector:
    """
    获取全局异常行为检测器单例。

    Returns:
        AnomalyDetector 实例。
    """
    global _anomaly_detector
    if _anomaly_detector is None:
        with _detector_lock:
            if _anomaly_detector is None:
                _anomaly_detector = AnomalyDetector()
    return _anomaly_detector


# ==================== CSRF Token 管理 ====================


class CsrfTokenManager:
    """
    CSRF token 管理器，支持 token 生成、校验、轮换和一次性使用。

    使用场景：
    - 表单提交：生成 token 嵌入表单，提交时校验
    - API 调用：token 通过自定义 header（如 X-CSRF-Token）传递
    - 一次性使用：校验后立即标记为已使用，防止重放攻击
    """

    TOKEN_LENGTH = 32  # token 字节数，hex 编码后 64 字符
    DEFAULT_TTL_HOURS = 24  # 默认有效期 24 小时

    def __init__(self, db: Session):
        """
        初始化 CSRF token 管理器。

        Args:
            db: 数据库会话实例。
        """
        self.db = db

    def generate_token(
        self,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        ttl_hours: int = DEFAULT_TTL_HOURS,
    ) -> dict:
        """
        生成新的 CSRF token。

        Args:
            user_id: 关联的用户 ID。
            session_id: 关联的会话 ID。
            ttl_hours: 有效期（小时）。

        Returns:
            token 信息字典：token, expires_at。
        """
        token = secrets.token_hex(self.TOKEN_LENGTH)
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(hours=ttl_hours)

        csrf = CsrfToken(
            token=token,
            user_id=user_id,
            session_id=session_id,
            is_used=False,
            is_revoked=False,
            created_at=now,
            expires_at=expires_at,
        )
        self.db.add(csrf)
        self.db.commit()
        self.db.refresh(csrf)
        logger.bind(
            event="csrf_token_generated",
            user_id=user_id,
            expires_at=expires_at.isoformat(),
        ).debug("CSRF token 已生成")
        return {
            "token": token,
            "expires_at": expires_at.isoformat(),
        }

    def validate_token(
        self,
        token: str,
        user_id: Optional[str] = None,
        consume: bool = True,
    ) -> dict:
        """
        校验 CSRF token 有效性。

        Args:
            token: 待校验的 token 字符串。
            user_id: 期望关联的用户 ID（可选，用于额外校验）。
            consume: 是否消费 token（一次性使用）。

        Returns:
            校验结果字典：valid, reason。
        """
        if not token:
            return {"valid": False, "reason": "token 为空"}

        record = self.db.query(CsrfToken).filter(CsrfToken.token == token).first()
        if not record:
            return {"valid": False, "reason": "token 不存在"}

        if record.is_revoked:
            return {"valid": False, "reason": "token 已被撤销"}

        if record.is_used:
            return {"valid": False, "reason": "token 已被使用（一次性）"}

        now = datetime.now(timezone.utc)
        expires_at = record.expires_at
        # SQLite 存储的 datetime 可能缺少时区信息，统一补齐
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= now:
            return {"valid": False, "reason": "token 已过期"}

        if user_id and record.user_id and record.user_id != user_id:
            return {"valid": False, "reason": "token 用户不匹配"}

        if consume:
            record.is_used = True
            record.used_at = now
            self.db.commit()

        return {"valid": True, "reason": "token 校验通过"}

    def revoke_token(self, token: str) -> bool:
        """
        撤销指定 token，使其立即失效。

        Args:
            token: 待撤销的 token 字符串。

        Returns:
            True 表示撤销成功。

        Raises:
            ValueError: token 不存在。
        """
        record = self.db.query(CsrfToken).filter(CsrfToken.token == token).first()
        if not record:
            raise ValueError(f"CSRF token 不存在")

        record.is_revoked = True
        self.db.commit()
        logger.bind(event="csrf_token_revoked").debug("CSRF token 已撤销")
        return True

    def rotate_token(
        self,
        old_token: str,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        ttl_hours: int = DEFAULT_TTL_HOURS,
    ) -> dict:
        """
        轮换 CSRF token：撤销旧 token 并生成新 token。

        Args:
            old_token: 待轮换的旧 token。
            user_id: 关联的用户 ID。
            session_id: 关联的会话 ID。
            ttl_hours: 新 token 有效期（小时）。

        Returns:
            新 token 信息字典。

        Raises:
            ValueError: 旧 token 不存在。
        """
        # 撤销旧 token（不存在时抛出 ValueError，已撤销的 token 允许重复轮换）
        record = self.db.query(CsrfToken).filter(CsrfToken.token == old_token).first()
        if record:
            record.is_revoked = True
            self.db.commit()
        else:
            raise ValueError(f"旧 CSRF token 不存在")

        # 生成新 token
        return self.generate_token(user_id=user_id, session_id=session_id, ttl_hours=ttl_hours)

    def cleanup_expired(self, batch_size: int = 1000) -> int:
        """
        清理已过期或已使用的 token 记录。

        Args:
            batch_size: 单批删除数量上限。

        Returns:
            删除的记录数。
        """
        now = datetime.now(timezone.utc)
        # SQLite 存储的 datetime 可能缺少时区信息，使用 naive datetime 比较
        now_naive = now.replace(tzinfo=None)
        # 删除已过期且已使用的 token
        expired = (
            self.db.query(CsrfToken)
            .filter(
                CsrfToken.expires_at <= now_naive,
                CsrfToken.is_used.is_(True),
            )
            .limit(batch_size)
            .all()
        )
        count = len(expired)
        for record in expired:
            self.db.delete(record)
        if count > 0:
            self.db.commit()
            logger.bind(event="csrf_tokens_cleaned", count=count).debug(
                f"已清理 {count} 条过期 CSRF token"
            )
        return count
