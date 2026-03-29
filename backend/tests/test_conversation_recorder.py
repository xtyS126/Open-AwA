import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.conversation_recorder import ConversationRecorder
from db.models import Base, ConversationRecord


class _User:
    def __init__(self, user_id: str):
        self.id = user_id


@pytest.mark.asyncio
async def test_record_respects_user_preference_and_flushes(monkeypatch, tmp_path):
    db_path = tmp_path / "conversation_recorder_test.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    test_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    monkeypatch.setattr("core.conversation_recorder.SessionLocal", test_session_local)

    recorder = ConversationRecorder(batch_size=2, flush_interval=0.01, queue_maxsize=10)
    user = _User("u-1")

    not_recorded = await recorder.record(
        node_type="intent",
        session_id="s-1",
        user_message="hello",
        current_user=user,
    )
    assert not_recorded is False

    recorder.set_collection_enabled(True, current_user=user)
    recorded = await recorder.record(
        node_type="intent",
        session_id="s-1",
        user_message="hello",
        current_user=user,
        metadata={"intent": "chat"},
        status="success",
    )
    assert recorded is True

    await asyncio.sleep(0.05)
    await recorder.stop()

    db = test_session_local()
    try:
        rows = db.query(ConversationRecord).all()
        assert len(rows) == 1
        assert rows[0].user_id == "u-1"
        assert rows[0].node_type == "intent"
    finally:
        db.close()


@pytest.mark.asyncio
async def test_recorder_queue_is_bounded_under_high_frequency(monkeypatch, tmp_path):
    db_path = tmp_path / "conversation_recorder_pressure.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    test_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    monkeypatch.setattr("core.conversation_recorder.SessionLocal", test_session_local)

    recorder = ConversationRecorder(batch_size=5, flush_interval=5.0, queue_maxsize=3)
    user = _User("u-2")
    recorder.set_collection_enabled(True, current_user=user)

    for i in range(20):
        await recorder.record(
            node_type="llm",
            session_id="s-2",
            user_message=f"msg-{i}",
            current_user=user,
        )

    stats = recorder.get_runtime_stats()
    assert stats["queue_size"] <= stats["queue_maxsize"]
    assert stats["dropped_count"] > 0

    await recorder.stop()
