"""
验证行为埋点批量队列在高频场景下的写入与限流行为。
"""

import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.behavior_logger import BehaviorLogger
from db.models import Base, BehaviorLog


@pytest.mark.asyncio
async def test_behavior_logger_flushes_records(monkeypatch, tmp_path):
    """
    验证行为埋点进入队列后，能够被后台 worker 批量刷新到数据库。
    """
    db_path = tmp_path / "behavior_logger_test.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    test_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    monkeypatch.setattr("core.behavior_logger.SessionLocal", test_session_local)

    logger_instance = BehaviorLogger(batch_size=2, flush_interval=0.01, queue_maxsize=10)
    recorded = await logger_instance.record({
        "user_id": "u-1",
        "action_type": "llm_call",
        "details": "{\"duration_ms\": 12}",
    })

    assert recorded is True

    await asyncio.sleep(0.05)
    await logger_instance.stop()

    db = test_session_local()
    try:
        rows = db.query(BehaviorLog).all()
        assert len(rows) == 1
        assert rows[0].user_id == "u-1"
        assert rows[0].action_type == "llm_call"
    finally:
        db.close()


@pytest.mark.asyncio
async def test_behavior_logger_queue_is_bounded(monkeypatch, tmp_path):
    """
    验证高频写入时队列不会无限增长，并会记录丢弃计数。
    """
    db_path = tmp_path / "behavior_logger_pressure.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    test_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    monkeypatch.setattr("core.behavior_logger.SessionLocal", test_session_local)

    logger_instance = BehaviorLogger(batch_size=5, flush_interval=5.0, queue_maxsize=3)

    for index in range(20):
        await logger_instance.record({
            "user_id": "u-2",
            "action_type": "llm_call",
            "details": f"payload-{index}",
        })

    stats = logger_instance.get_runtime_stats()
    assert stats["queue_size"] <= stats["queue_maxsize"]
    assert stats["dropped_count"] > 0
    assert stats["enqueue_failed_count"] >= 0

    await logger_instance.stop()


@pytest.mark.asyncio
async def test_behavior_logger_records_enqueue_failure_stats(monkeypatch, tmp_path):
    """
    验证当队列满且限时入队仍失败时，会返回 False 并记录失败统计。
    """
    db_path = tmp_path / "behavior_logger_timeout.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    test_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    monkeypatch.setattr("core.behavior_logger.SessionLocal", test_session_local)

    logger_instance = BehaviorLogger(
        batch_size=5,
        flush_interval=5.0,
        queue_maxsize=1,
        enqueue_timeout=0.001,
    )

    async def noop_start():
        return None

    async def slow_put(_payload):
        await asyncio.sleep(0.01)

    monkeypatch.setattr(logger_instance, "start", noop_start)
    monkeypatch.setattr(logger_instance.queue, "put", slow_put)

    first_ok = await logger_instance.record({
        "user_id": "u-3",
        "action_type": "llm_call",
        "details": "payload-initial",
    })
    assert first_ok is True

    second_ok = await logger_instance.record({
        "user_id": "u-3",
        "action_type": "llm_call",
        "details": "payload-timeout",
    })
    assert second_ok is False

    stats = logger_instance.get_runtime_stats()
    assert stats["dropped_count"] == 1
    assert stats["enqueue_failed_count"] == 1
