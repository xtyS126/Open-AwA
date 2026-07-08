"""
异常行为检测模块，识别速率突发和重复失败模式。

检测策略：
- rate_burst: 短时间内请求量超过阈值（如 60 秒内 200 次）
- repeated_failure: 短时间内失败请求超过阈值（如 60 秒内 50 次失败）

检测为被动观察，仅记录事件到数据库，不主动拦截。
"""

import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Optional

from loguru import logger
from sqlalchemy.orm import Session

from db.models import AnomalyEvent


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
