"""
任务运行时 Phase 2 测试，覆盖状态机校验、依赖验证、事务领取与审计事件写入。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from db.models import TaskItem, TaskEvent, TaskAgentSession, init_db
from core.task_runtime.task_store import (
    create_task,
    get_task,
    update_task,
    claim_task,
    validate_task_transition,
    validate_dependencies,
)
from core.task_runtime.sessions import (
    create_session,
    update_session_state,
    claim_session,
    release_session,
)


@pytest.fixture
def testing_session_local():
    """独立内存数据库会话工厂。"""
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


# ── 状态机校验 ──────────────────────────────────────────────

class TestValidateTaskTransition:
    """任务状态机转换校验。"""

    def test_valid_transitions(self):
        """验证所有合法状态转换通过。"""
        assert validate_task_transition("pending", "running") is True
        assert validate_task_transition("pending", "cancelled") is True
        assert validate_task_transition("blocked", "pending") is True
        assert validate_task_transition("blocked", "cancelled") is True
        assert validate_task_transition("running", "completed") is True
        assert validate_task_transition("running", "failed") is True
        assert validate_task_transition("running", "cancelled") is True

    def test_invalid_transitions(self):
        """验证非法状态转换被拒绝。"""
        assert validate_task_transition("pending", "completed") is False
        assert validate_task_transition("pending", "failed") is False
        assert validate_task_transition("running", "pending") is False
        assert validate_task_transition("completed", "running") is False
        assert validate_task_transition("failed", "running") is False
        assert validate_task_transition("cancelled", "running") is False
        assert validate_task_transition("completed", "completed") is False

    def test_terminal_states_reject_all(self):
        """验证终态拒绝所有转换。"""
        for state in ("completed", "failed", "cancelled"):
            for target in ("pending", "blocked", "running", "completed", "failed", "cancelled"):
                assert validate_task_transition(state, target) is False, \
                    f"{state} -> {target} should be invalid"


# ── 任务 CRUD 与状态机集成 ─────────────────────────────────

class TestTaskCRUD:
    """任务创建、更新与状态机集成。"""

    def test_create_task(self, testing_session_local):
        """创建任务并验证审计事件写入。"""
        db = testing_session_local()
        try:
            task = create_task(db, subject="测试任务", description="测试描述")
            assert task.task_id.startswith("tsk_")
            assert task.status == "pending"
            assert task.subject == "测试任务"

            # 验证 TaskEvent 已写入
            events = db.query(TaskEvent).filter(
                TaskEvent.entity_id == task.task_id
            ).all()
            assert len(events) == 1
            assert events[0].event_type == "task.created"
        finally:
            db.close()

    def test_update_task_valid_transition(self, testing_session_local):
        """验证合法状态转换成功。"""
        db = testing_session_local()
        try:
            task = create_task(db, subject="待运行任务")
            updated = update_task(db, task.task_id, status="running")
            assert updated is not None
            assert updated.status == "running"

            # 验证 TaskEvent
            events = db.query(TaskEvent).filter(
                TaskEvent.entity_id == task.task_id
            ).all()
            assert len(events) >= 2  # created + updated
        finally:
            db.close()

    def test_update_task_invalid_transition(self, testing_session_local):
        """验证非法状态转换被拒绝。"""
        db = testing_session_local()
        try:
            task = create_task(db, subject="测试任务")
            result = update_task(db, task.task_id, status="completed")
            assert result is None  # pending -> completed 是非法的
        finally:
            db.close()


# ── 依赖验证 ────────────────────────────────────────────────

class TestDependencyValidation:
    """任务依赖校验。"""

    def test_no_dependencies(self, testing_session_local):
        """无依赖任务应直接通过。"""
        db = testing_session_local()
        try:
            task = create_task(db, subject="无依赖任务")
            unmet = validate_dependencies(db, task.task_id)
            assert unmet == []
        finally:
            db.close()

    def test_dependencies_satisfied(self, testing_session_local):
        """依赖已完成时应返回空列表。"""
        db = testing_session_local()
        try:
            dep = create_task(db, subject="依赖任务")
            update_task(db, dep.task_id, status="running")
            update_task(db, dep.task_id, status="completed")

            task = create_task(db, subject="主任务", dependencies=[dep.task_id])
            unmet = validate_dependencies(db, task.task_id)
            assert unmet == []
        finally:
            db.close()

    def test_dependencies_unmet(self, testing_session_local):
        """依赖未完成时应返回未满足的依赖列表。"""
        db = testing_session_local()
        try:
            dep = create_task(db, subject="依赖任务")
            task = create_task(db, subject="主任务", dependencies=[dep.task_id])

            unmet = validate_dependencies(db, task.task_id)
            assert dep.task_id in unmet
        finally:
            db.close()

    def test_update_to_running_blocked_by_deps(self, testing_session_local):
        """依赖未满足时拒绝转移到 running。"""
        db = testing_session_local()
        try:
            dep = create_task(db, subject="依赖任务")
            task = create_task(db, subject="主任务", dependencies=[dep.task_id])

            result = update_task(db, task.task_id, status="running")
            assert result is None  # 依赖不满足
        finally:
            db.close()


# ── 任务领取 ────────────────────────────────────────────────

class TestClaimTask:
    """事务性任务领取。"""

    def test_claim_pending_task(self, testing_session_local):
        """领取一个 pending 任务应成功。"""
        db = testing_session_local()
        try:
            task = create_task(db, subject="待领取任务")
            claimed = claim_task(db, task.task_id, "agt_test123")
            assert claimed is not None
            assert claimed.status == "running"
            assert claimed.owner_agent_id == "agt_test123"
        finally:
            db.close()

    def test_claim_rejects_second_claim(self, testing_session_local):
        """二次领取同一任务应失败。"""
        db = testing_session_local()
        try:
            task = create_task(db, subject="待领取任务")
            first = claim_task(db, task.task_id, "agt_agent1")
            assert first is not None

            second = claim_task(db, task.task_id, "agt_agent2")
            assert second is None  # 已被领取，状态不再是 pending
        finally:
            db.close()

    def test_claim_blocked_by_dependencies(self, testing_session_local):
        """依赖未满足时领取应失败。"""
        db = testing_session_local()
        try:
            dep = create_task(db, subject="依赖任务")
            task = create_task(db, subject="主任务", dependencies=[dep.task_id])

            claimed = claim_task(db, task.task_id, "agt_test")
            assert claimed is None  # 依赖不满足

            # 验证任务被置为 blocked（依赖未满足），直接通过 db 查询
            refreshed = db.query(TaskItem).filter(TaskItem.task_id == task.task_id).first()
            assert refreshed is not None
            assert refreshed.status == "blocked"
        finally:
            db.close()

    def test_claim_writes_audit_event(self, testing_session_local):
        """领取任务后应写入审计事件。"""
        db = testing_session_local()
        try:
            task = create_task(db, subject="审计测试")
            claim_task(db, task.task_id, "agt_audit")

            events = db.query(TaskEvent).filter(
                TaskEvent.entity_id == task.task_id,
                TaskEvent.event_type == "task.claimed",
            ).all()
            assert len(events) == 1
        finally:
            db.close()


# ── 会话租约领取 ────────────────────────────────────────────

class TestSessionClaim:
    """代理会话租约领取与释放。"""

    def test_claim_session_success(self, testing_session_local):
        """领取运行中会话的租约应成功。"""
        db = testing_session_local()
        try:
            session = create_session(db, agent_type="Explore")
            update_session_state(db, session.agent_id, "queued")
            update_session_state(db, session.agent_id, "running")

            claimed = claim_session(db, session.agent_id, "worker_1")
            assert claimed is not None
            assert claimed.lease_owner == "worker_1"
            assert claimed.lease_expires_at is not None
        finally:
            db.close()

    def test_claim_session_rejects_active_lease(self, testing_session_local):
        """已有未过期租约时拒绝二次领取。"""
        db = testing_session_local()
        try:
            session = create_session(db, agent_type="Explore")
            update_session_state(db, session.agent_id, "queued")
            update_session_state(db, session.agent_id, "running")

            # 第一次领取
            first = claim_session(db, session.agent_id, "worker_1", lease_duration_seconds=300)
            assert first is not None

            # 第二次领取应失败
            second = claim_session(db, session.agent_id, "worker_2", lease_duration_seconds=300)
            assert second is None
        finally:
            db.close()

    def test_release_session(self, testing_session_local):
        """释放租约后应清除租约信息。"""
        db = testing_session_local()
        try:
            session = create_session(db, agent_type="Explore")
            update_session_state(db, session.agent_id, "queued")
            update_session_state(db, session.agent_id, "running")
            claim_session(db, session.agent_id, "worker_1")

            success = release_session(db, session.agent_id, "worker_1")
            assert success is True

            # 验证租约已清除，直接通过 db 查询
            refreshed = db.query(TaskAgentSession).filter(
                TaskAgentSession.agent_id == session.agent_id
            ).first()
            assert refreshed is not None
            assert refreshed.lease_owner is None
            assert refreshed.lease_expires_at is None
        finally:
            db.close()

    def test_claim_session_expired_lease(self, testing_session_local):
        """过期租约应允许重新领取。"""
        db = testing_session_local()
        try:
            session = create_session(db, agent_type="Explore")
            update_session_state(db, session.agent_id, "queued")
            update_session_state(db, session.agent_id, "running")

            # 第一次领取（立即过期）
            claimed = claim_session(db, session.agent_id, "worker_1", lease_duration_seconds=-1)
            assert claimed is not None

            # 第二次应成功（因为租约已过期）
            second = claim_session(db, session.agent_id, "worker_2", lease_duration_seconds=300)
            assert second is not None
            assert second.lease_owner == "worker_2"
        finally:
            db.close()
