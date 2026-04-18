"""
定时任务调度器测试，覆盖上下文收敛与领取事务回滚两类关键回归场景。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import core.scheduled_task_manager as scheduled_task_manager_module
from core.scheduled_task_manager import ScheduledTaskManager
from db.models import ScheduledTask, ScheduledTaskExecution, User, init_db


@pytest.fixture
def testing_session_local():
    """
    创建独立的内存数据库会话工厂，避免测试之间互相影响。
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    init_db(bind_engine=engine)
    try:
        yield session_local
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_run_agent_relies_on_unified_isolation_defaults(monkeypatch):
    """
    _run_agent 只应传入最小必要上下文，隔离细节交由 Agent 统一默认值补齐。
    """
    manager = ScheduledTaskManager()
    captured: dict[str, object] = {}

    class DummySession:
        def close(self):
            return None

    class FakeAgent:
        def __init__(self, db_session=None):
            captured["db_session"] = db_session

        async def process(self, user_input, context):
            captured["user_input"] = user_input
            captured["context"] = dict(context)
            return {
                "status": "completed",
                "response": "ok",
                "results": [],
            }

    monkeypatch.setattr(scheduled_task_manager_module, "SessionLocal", lambda: DummySession())
    monkeypatch.setattr(scheduled_task_manager_module, "AIAgent", FakeAgent)

    result = await manager._run_agent(
        {
            "id": 7,
            "user_id": "user-1",
            "title": "测试任务",
            "prompt": "请整理今天的待办",
            "scheduled_at": datetime.now(timezone.utc),
            "provider": None,
            "model": None,
        }
    )

    assert result["status"] == "completed"
    assert captured["user_input"] == "请整理今天的待办"

    context = captured["context"]
    assert context["scheduled_execution_isolated"] is True
    assert context["session_id"] == "scheduled-task-7"
    assert context["scheduled_task_id"] == 7
    assert "db" not in context
    assert "message" not in context
    assert "disable_behavior_logging" not in context
    assert "disable_conversation_record" not in context
    assert "disable_memory_update" not in context
    assert "retrieve_experiences" not in context
    assert "retrieve_long_term_memory" not in context
    assert "enable_skill_plugin" not in context
    assert "extract_experience" not in context
    assert "output_mode" not in context


@pytest.mark.asyncio
async def test_run_agent_closes_session_when_agent_raises(monkeypatch):
    """
    当 Agent 执行异常时，_run_agent 也应确保数据库会话被关闭。
    """
    manager = ScheduledTaskManager()
    session_state = {"closed": False}

    class DummySession:
        def close(self):
            session_state["closed"] = True

    class FakeAgent:
        def __init__(self, db_session=None):
            self.db_session = db_session

        async def process(self, user_input, context):
            raise RuntimeError("agent failed")

    monkeypatch.setattr(scheduled_task_manager_module, "SessionLocal", lambda: DummySession())
    monkeypatch.setattr(scheduled_task_manager_module, "AIAgent", FakeAgent)

    with pytest.raises(RuntimeError, match="agent failed"):
        await manager._run_agent(
            {
                "id": 8,
                "user_id": "user-1",
                "title": "异常任务",
                "prompt": "请故意失败",
                "scheduled_at": datetime.now(timezone.utc),
                "provider": None,
                "model": None,
            }
        )

    assert session_state["closed"] is True


@pytest.mark.asyncio
async def test_execute_task_rolls_back_claim_transaction_on_flush_failure(monkeypatch, testing_session_local):
    """
    当创建执行记录阶段失败时，任务状态应回滚为 pending，且不能留下半条执行记录。
    """
    seed_session = testing_session_local()
    try:
        seed_session.add(
            User(
                id="user-1",
                username="tester",
                password_hash="hashed",
                role="user",
            )
        )
        task = ScheduledTask(
            user_id="user-1",
            title="回滚测试任务",
            prompt="请在失败时保持事务一致性",
            scheduled_at=datetime.now(timezone.utc) + timedelta(minutes=5),
            status="pending",
            task_metadata={"kind": "prompt_once"},
        )
        seed_session.add(task)
        seed_session.commit()
        task_id = task.id
    finally:
        seed_session.close()

    failing_session = testing_session_local()
    monkeypatch.setattr(
        scheduled_task_manager_module,
        "SessionLocal",
        lambda: failing_session,
    )
    monkeypatch.setattr(
        failing_session,
        "flush",
        lambda: (_ for _ in ()).throw(RuntimeError("flush failed")),
    )

    manager = ScheduledTaskManager()
    await manager._execute_task(task_id)

    verify_session = testing_session_local()
    try:
        task = verify_session.query(ScheduledTask).filter(ScheduledTask.id == task_id).first()
        executions = (
            verify_session.query(ScheduledTaskExecution)
            .filter(ScheduledTaskExecution.task_id == task_id)
            .all()
        )
    finally:
        verify_session.close()

    assert task is not None
    assert task.status == "pending"
    assert task.completed_at is None
    assert executions == []


def test_claim_task_for_execution_rejects_second_claim(monkeypatch, testing_session_local):
    """
    同一任务在第一次被领取后，再次领取应直接失败，避免同进程重复执行。
    """
    seed_session = testing_session_local()
    try:
        seed_session.add(
            User(
                id="user-2",
                username="tester-2",
                password_hash="hashed",
                role="user",
            )
        )
        task = ScheduledTask(
            user_id="user-2",
            title="重复领取测试",
            prompt="只允许领取一次",
            scheduled_at=datetime.now(timezone.utc) + timedelta(minutes=5),
            status="pending",
            task_metadata={"kind": "prompt_once"},
        )
        seed_session.add(task)
        seed_session.commit()
        task_id = task.id
    finally:
        seed_session.close()

    monkeypatch.setattr(
        scheduled_task_manager_module,
        "SessionLocal",
        testing_session_local,
    )

    manager = ScheduledTaskManager()
    first_claim, execution_id = manager._claim_task_for_execution(task_id)
    second_claim, second_execution_id = manager._claim_task_for_execution(task_id)

    assert first_claim is not None
    assert execution_id is not None
    assert second_claim is None
    assert second_execution_id is None

    verify_session = testing_session_local()
    try:
        task = verify_session.query(ScheduledTask).filter(ScheduledTask.id == task_id).first()
        executions = verify_session.query(ScheduledTaskExecution).filter(ScheduledTaskExecution.task_id == task_id).all()
    finally:
        verify_session.close()

    assert task is not None
    assert task.status == "running"
    assert len(executions) == 1