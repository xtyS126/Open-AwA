"""
关键操作事件日志系统，用于审计和调试。

参考 OpenCode EventV2 设计：
- 类型化的事件定义
- 事件持久化到数据库
- 支持按会话/代理/时间范围查询
- 为后续事件溯源架构打基础
"""

import json
import time
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from loguru import logger
from sqlalchemy import String, DateTime, Integer, Text, Index, desc
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.orm import Session

from db.models import Base


class EventType(str, Enum):
    """关键操作事件类型"""
    # Agent 事件
    AGENT_STARTED = "agent.started"
    AGENT_FINISHED = "agent.finished"
    AGENT_CANCELLED = "agent.cancelled"
    AGENT_ERROR = "agent.error"

    # LLM 事件
    LLM_REQUEST_START = "llm.request_start"
    LLM_REQUEST_END = "llm.request_end"
    LLM_REQUEST_ERROR = "llm.request_error"
    LLM_TOKEN_USAGE = "llm.token_usage"

    # 工具事件
    TOOL_CALL_START = "tool.call_start"
    TOOL_CALL_END = "tool.call_end"
    TOOL_CALL_ERROR = "tool.call_error"

    # 会话事件
    SESSION_CREATED = "session.created"
    SESSION_CLOSED = "session.closed"
    SESSION_COMPACTED = "session.compacted"

    # 权限事件
    PERMISSION_ASKED = "permission.asked"
    PERMISSION_REPLIED = "permission.replied"

    # 系统事件
    SYSTEM_STARTUP = "system.startup"
    SYSTEM_SHUTDOWN = "system.shutdown"
    SYSTEM_ERROR = "system.error"


class EventLog(Base):
    """
    关键操作事件日志表。

    每条事件记录包含：
    - event_id: 事件唯一标识
    - event_type: 事件类型枚举
    - session_id: 关联的会话 ID
    - agent_id: 关联的代理 ID
    - user_id: 关联的用户 ID
    - data: 事件携带的 JSON 数据
    - timestamp: 事件发生时间（毫秒精度）
    - sequence: 会话内序号（用于事件排序）
    """
    __tablename__ = "event_logs"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: f"evt_{uuid.uuid4().hex[:16]}"
    )
    event_type: Mapped[str] = mapped_column(
        String(64), index=True, comment="事件类型"
    )
    session_id: Mapped[Optional[str]] = mapped_column(
        String, index=True, nullable=True, comment="关联会话 ID"
    )
    agent_id: Mapped[Optional[str]] = mapped_column(
        String, index=True, nullable=True, comment="关联代理 ID"
    )
    user_id: Mapped[Optional[str]] = mapped_column(
        String, index=True, nullable=True, comment="关联用户 ID"
    )
    data_json: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="事件数据（JSON）"
    )
    timestamp_ms: Mapped[int] = mapped_column(
        Integer, comment="事件时间戳（毫秒）"
    )
    sequence: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, comment="会话内事件序号"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (
        Index("idx_event_logs_session_seq", "session_id", "sequence"),
        Index("idx_event_logs_type_time", "event_type", "timestamp_ms"),
    )

    def __repr__(self) -> str:
        return f"<EventLog type={self.event_type} session={self.session_id}>"


class EventLogger:
    """
    事件日志记录器。

    提供便捷的事件记录方法，支持：
    - 同步记录（批量写入）
    - 会话序号自动递增
    - 结构化数据自动序列化
    """

    def __init__(self, db_session: Session):
        self._db = db_session
        self._sequence_counters: Dict[str, int] = {}

    def _next_sequence(self, session_id: str) -> int:
        """获取指定会话的下一个事件序号"""
        current = self._sequence_counters.get(session_id, 0)
        next_seq = current + 1
        self._sequence_counters[session_id] = next_seq
        return next_seq

    def record(
        self,
        event_type: str,
        data: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> EventLog:
        """
        记录一条事件。

        Args:
            event_type: 事件类型
            data: 事件数据
            session_id: 会话 ID
            agent_id: 代理 ID
            user_id: 用户 ID

        Returns:
            创建的 EventLog 实例
        """
        event = EventLog(
            event_type=event_type,
            session_id=session_id,
            agent_id=agent_id,
            user_id=user_id,
            data_json=(
                json.dumps(data, ensure_ascii=False, default=str)
                if data else None
            ),
            timestamp_ms=int(time.time() * 1000),
            sequence=(
                self._next_sequence(session_id) if session_id else None
            ),
        )

        try:
            self._db.add(event)
            self._db.flush()
            return event
        except Exception as e:
            logger.warning(f"记录事件失败: {e}")
            return None

    def record_agent_event(
        self,
        event_type: str,
        session_id: str,
        agent_id: Optional[str] = None,
        user_id: Optional[str] = None,
        **kwargs: Any,
    ) -> EventLog:
        """记录 Agent 相关事件"""
        return self.record(
            event_type=event_type,
            data=kwargs if kwargs else None,
            session_id=session_id,
            agent_id=agent_id,
            user_id=user_id,
        )

    def record_tool_event(
        self,
        event_type: str,
        session_id: str,
        tool_name: str,
        tool_input: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> EventLog:
        """记录工具相关事件"""
        return self.record(
            event_type=event_type,
            data={"tool_name": tool_name, "input": tool_input, **kwargs},
            session_id=session_id,
        )

    def record_llm_event(
        self,
        event_type: str,
        session_id: str,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        tokens: Optional[Dict[str, int]] = None,
        **kwargs: Any,
    ) -> EventLog:
        """记录 LLM 相关事件"""
        return self.record(
            event_type=event_type,
            data={
                "provider": provider,
                "model": model,
                "tokens": tokens,
                **kwargs,
            },
            session_id=session_id,
        )


class EventQuery:
    """事件查询器"""

    def __init__(self, db_session: Session):
        self._db = db_session

    def by_session(
        self,
        session_id: str,
        event_type: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[EventLog]:
        """按会话查询事件"""
        query = (
            self._db.query(EventLog)
            .filter(EventLog.session_id == session_id)
        )
        if event_type:
            query = query.filter(EventLog.event_type == event_type)
        return (
            query
            .order_by(desc(EventLog.sequence))
            .offset(offset)
            .limit(limit)
            .all()
        )

    def by_type(
        self,
        event_type: str,
        limit: int = 100,
        offset: int = 0,
    ) -> List[EventLog]:
        """按事件类型查询"""
        return (
            self._db.query(EventLog)
            .filter(EventLog.event_type == event_type)
            .order_by(desc(EventLog.timestamp_ms))
            .offset(offset)
            .limit(limit)
            .all()
        )

    def by_time_range(
        self,
        start_ms: int,
        end_ms: int,
        event_type: Optional[str] = None,
        limit: int = 100,
    ) -> List[EventLog]:
        """按时间范围查询"""
        query = (
            self._db.query(EventLog)
            .filter(EventLog.timestamp_ms >= start_ms)
            .filter(EventLog.timestamp_ms <= end_ms)
        )
        if event_type:
            query = query.filter(EventLog.event_type == event_type)
        return (
            query
            .order_by(desc(EventLog.timestamp_ms))
            .limit(limit)
            .all()
        )

    def count_by_type(self, session_id: str) -> Dict[str, int]:
        """统计会话中各类型事件数量（使用 SQL GROUP BY 下推计算）"""
        from sqlalchemy import func
        rows = (
            self._db.query(
                EventLog.event_type,
                func.count(EventLog.event_type).label("cnt"),
            )
            .filter(EventLog.session_id == session_id)
            .group_by(EventLog.event_type)
            .all()
        )
        return {row.event_type: row.cnt for row in rows}
