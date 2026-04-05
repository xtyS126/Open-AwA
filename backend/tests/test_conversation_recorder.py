"""
后端测试模块，负责验证对应功能在正常、边界或异常场景下的行为是否符合预期。
保持测试注释清晰，有助于快速分辨各个用例所覆盖的场景。
"""

import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.conversation_recorder import ConversationRecorder
from db.models import Base, ConversationRecord


class _User:
    """
    封装与User相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    def __init__(self, user_id: str):
        """
        处理init相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        self.id = user_id


@pytest.mark.asyncio
async def test_record_respects_user_preference_and_flushes(monkeypatch, tmp_path):
    """
    验证record、respects、user、preference、and、flushes相关场景的行为是否符合预期。
    通过断言结果可以帮助定位实现与预期行为之间的偏差。
    """
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
    """
    验证recorder、queue、is、bounded、under、high、frequency相关场景的行为是否符合预期。
    通过断言结果可以帮助定位实现与预期行为之间的偏差。
    """
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


@pytest.mark.asyncio
async def test_flush_batch_uses_to_thread(monkeypatch, tmp_path):
    """
    验证批量刷盘时会通过 asyncio.to_thread 下沉同步写库，
    避免在事件循环线程中直接执行数据库提交。
    """
    db_path = tmp_path / "conversation_recorder_threaded_flush.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    test_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    monkeypatch.setattr("core.conversation_recorder.SessionLocal", test_session_local)

    recorder = ConversationRecorder(batch_size=2, flush_interval=0.01, queue_maxsize=10)
    called = {"value": False}
    original_to_thread = asyncio.to_thread

    async def tracking_to_thread(func, /, *args, **kwargs):
        called["value"] = True
        return await original_to_thread(func, *args, **kwargs)

    monkeypatch.setattr("core.conversation_recorder.asyncio.to_thread", tracking_to_thread)

    payload = {
        "session_id": "s-3",
        "user_id": "u-3",
        "node_type": "intent",
        "user_message": "hello",
        "provider": None,
        "model": None,
        "llm_input": None,
        "llm_output": None,
        "llm_tokens_used": None,
        "execution_duration_ms": None,
        "status": "success",
        "error_message": None,
        "record_metadata": None,
    }
    recorder.queue.put_nowait(payload)

    await recorder._flush_batch([payload])

    assert called["value"] is True

    db = test_session_local()
    try:
        rows = db.query(ConversationRecord).all()
        assert len(rows) == 1
        assert rows[0].user_id == "u-3"
    finally:
        db.close()
