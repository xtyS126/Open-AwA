from datetime import datetime, timezone
import uuid
from typing import Optional

from sqlalchemy import DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from db.models.base import Base


class EventLog(Base):
    __tablename__ = "event_logs"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: f"evt_{uuid.uuid4().hex[:16]}"
    )
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    session_id: Mapped[Optional[str]] = mapped_column(String, index=True, nullable=True)
    agent_id: Mapped[Optional[str]] = mapped_column(String, index=True, nullable=True)
    user_id: Mapped[Optional[str]] = mapped_column(String, index=True, nullable=True)
    data_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    timestamp_ms: Mapped[int] = mapped_column(Integer)
    sequence: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (
        Index("idx_event_logs_session_seq", "session_id", "sequence"),
        Index("idx_event_logs_type_time", "event_type", "timestamp_ms"),
    )

    def __repr__(self) -> str:
        return f"<EventLog type={self.event_type} session={self.session_id}>"
