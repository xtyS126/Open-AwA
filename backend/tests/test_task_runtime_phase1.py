"""
任务运行时 Phase 1 测试，覆盖 Agent spawn、SendMessage、TaskStop、
代理会话持久化、transcript 存储与基础 SSE 事件。
"""

from __future__ import annotations

import os
import tempfile

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import core.agent as agent_module
import core.task_runtime.runners as runners_module

from db.models import TaskAgentSession, init_db
from core.task_runtime.sessions import (
    create_session,
    update_session_state,
    validate_transition,
    claim_session,
    release_session,
    recover_orphaned_sessions,
    _generate_agent_id,
)
from core.task_runtime.serializers import (
    save_transcript_entry,
    read_transcript,
    get_transcript_path,
    build_summary,
    emit_subagent_start_event,
    emit_subagent_stop_event,
    emit_agent_message_event,
)
from core.task_runtime.definitions import (
    AgentDefinition,
    get_agent_definition,
    get_builtin_agents,
    list_agent_types,
)
from core.task_runtime.registry import agent_registry


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


@pytest.fixture
def testing_db(testing_session_local):
    """提供独立会话，自动回滚关闭。"""
    db = testing_session_local()
    try:
        yield db
    finally:
        db.rollback()
        db.close()


# -- Agent 会话状态机 --------------------------------------------------

class TestAgentSessionStateMachine:
    """代理会话状态转换测试。"""

    def test_created_to_queued(self):
        assert validate_transition("created", "queued") is True

    def test_queued_to_running(self):
        assert validate_transition("queued", "running") is True

    def test_running_to_completed(self):
        assert validate_transition("running", "completed") is True

    def test_running_to_failed(self):
        assert validate_transition("running", "failed") is True

    def test_running_to_stopped(self):
        assert validate_transition("running", "stopped") is True

    def test_running_to_waiting_user(self):
        assert validate_transition("running", "waiting_user") is True

    def test_waiting_user_to_running(self):
        assert validate_transition("waiting_user", "running") is True

    def test_waiting_user_to_stopped(self):
        assert validate_transition("waiting_user", "stopped") is True

    def test_terminal_rejects_all(self):
        for state in ("completed", "failed", "stopped", "cancelled"):
            assert validate_transition(state, "running") is False
            assert validate_transition(state, "created") is False

    def test_invalid_transition(self):
        assert validate_transition("created", "completed") is False
        assert validate_transition("queued", "completed") is False


# -- 代理会话 CRUD ----------------------------------------------------

class TestAgentSessionCRUD:
    """代理会话创建、查询与状态更新测试。"""

    def test_create_session_foreground(self, testing_db):
        session = create_session(
            testing_db,
            agent_type="Explore",
            run_mode="foreground",
        )
        assert session.agent_id.startswith("agt_")
        assert session.state == "created"
        assert session.run_mode == "foreground"
        assert session.agent_type == "Explore"

    def test_create_session_background(self, testing_db):
        session = create_session(
            testing_db,
            agent_type="general-purpose",
            run_mode="background",
            isolation_mode="fresh",
        )
        assert session.run_mode == "background"
        assert session.isolation_mode == "fresh"

    def test_create_session_with_parent(self, testing_db):
        session = create_session(
            testing_db,
            parent_session_id="parent_001",
            root_chat_session_id="chat_001",
            agent_type="Plan",
        )
        assert session.parent_session_id == "parent_001"
        assert session.root_chat_session_id == "chat_001"

    def test_update_state_valid(self, testing_db):
        session = create_session(testing_db, agent_type="Explore")
        updated = update_session_state(testing_db, session.agent_id, "queued")
        assert updated is not None
        assert updated.state == "queued"

    def test_update_state_invalid(self, testing_db):
        session = create_session(testing_db, agent_type="Explore")
        # created -> completed 不合法
        updated = update_session_state(testing_db, session.agent_id, "completed")
        assert updated is None

    def test_update_state_with_summary(self, testing_db):
        session = create_session(testing_db, agent_type="Explore")
        update_session_state(testing_db, session.agent_id, "queued")
        updated = update_session_state(
            testing_db,
            session.agent_id,
            "running",
            summary="开始执行",
        )
        assert updated is not None
        assert updated.summary == "开始执行"
        assert updated.started_at is not None

    def test_update_state_sets_ended_at(self, testing_db):
        session = create_session(testing_db, agent_type="Explore")
        update_session_state(testing_db, session.agent_id, "queued")
        update_session_state(testing_db, session.agent_id, "running")
        updated = update_session_state(
            testing_db,
            session.agent_id,
            "completed",
            summary="执行完成",
        )
        assert updated.ended_at is not None

    def test_get_session_exists(self, testing_db):
        session = create_session(testing_db, agent_type="Explore")
        # get_session() 使用生产 SessionLocal，此处直接查测试 DB
        found = testing_db.query(TaskAgentSession).filter(
            TaskAgentSession.agent_id == session.agent_id
        ).first()
        assert found is not None
        assert found.agent_id == session.agent_id

    def test_update_nonexistent_session(self, testing_db):
        updated = update_session_state(testing_db, "agt_ghost", "running")
        assert updated is None


# -- 会话列表与过滤 ----------------------------------------------------

class TestSessionList:
    """会话列表与过滤测试。"""

    def test_list_all(self, testing_db):
        create_session(testing_db, agent_type="Explore")
        create_session(testing_db, agent_type="Plan")
        sessions = testing_db.query(TaskAgentSession).limit(50).all()
        assert len(sessions) >= 2

    def test_list_by_state(self, testing_db):
        create_session(testing_db, agent_type="Explore")
        sessions = testing_db.query(TaskAgentSession).filter(
            TaskAgentSession.state == "created"
        ).limit(50).all()
        assert all(s.state == "created" for s in sessions)

    def test_list_by_parent(self, testing_db):
        create_session(testing_db, parent_session_id="p1", agent_type="Explore")
        create_session(testing_db, parent_session_id="p2", agent_type="Plan")
        sessions = testing_db.query(TaskAgentSession).filter(
            TaskAgentSession.parent_session_id == "p1"
        ).limit(50).all()
        assert all(s.parent_session_id == "p1" for s in sessions)


# -- 会话租约 ----------------------------------------------------------

class TestSessionLease:
    """会话租约领取与释放测试。"""

    def test_claim_session(self, testing_db):
        session = create_session(testing_db, agent_type="Explore")
        update_session_state(testing_db, session.agent_id, "queued")
        update_session_state(testing_db, session.agent_id, "running")

        claimed = claim_session(testing_db, session.agent_id, "worker_1")
        assert claimed is not None
        assert claimed.lease_owner == "worker_1"
        assert claimed.lease_expires_at is not None

    def test_claim_already_owned(self, testing_db):
        session = create_session(testing_db, agent_type="Explore")
        update_session_state(testing_db, session.agent_id, "queued")
        update_session_state(testing_db, session.agent_id, "running")

        claim_session(testing_db, session.agent_id, "worker_1")
        # 另一个 worker 尝试 claim
        claimed = claim_session(testing_db, session.agent_id, "worker_2")
        assert claimed is None

    def test_release_session(self, testing_db):
        session = create_session(testing_db, agent_type="Explore")
        update_session_state(testing_db, session.agent_id, "queued")
        update_session_state(testing_db, session.agent_id, "running")

        claim_session(testing_db, session.agent_id, "worker_1")
        released = release_session(testing_db, session.agent_id, "worker_1")
        assert released is True

    def test_release_wrong_owner(self, testing_db):
        session = create_session(testing_db, agent_type="Explore")
        update_session_state(testing_db, session.agent_id, "queued")
        update_session_state(testing_db, session.agent_id, "running")

        claim_session(testing_db, session.agent_id, "worker_1")
        released = release_session(testing_db, session.agent_id, "wrong_owner")
        assert released is False

    def test_claim_non_running(self, testing_db):
        session = create_session(testing_db, agent_type="Explore")
        claimed = claim_session(testing_db, session.agent_id, "worker_1")
        assert claimed is None


# -- 悬挂会话恢复 ------------------------------------------------------

class TestOrphanedSessionRecovery:
    """悬挂会话恢复测试。"""

    def test_recover_empty(self):
        count = recover_orphaned_sessions()
        assert count == 0


# -- Transcript 存储与读取 ---------------------------------------------

class TestTranscript:
    """Transcript 存储、读取与摘要测试。"""

    def test_save_and_read(self):
        agent_id = _generate_agent_id()
        try:
            save_transcript_entry(agent_id, {"event": "test", "data": "hello"})
            save_transcript_entry(agent_id, {"event": "subagent_stop", "state": "completed"})

            entries = read_transcript(agent_id)
            assert len(entries) == 2
            assert entries[0]["event"] == "test"
            assert entries[1]["event"] == "subagent_stop"
        finally:
            path = get_transcript_path(agent_id)
            if os.path.exists(path):
                os.remove(path)

    def test_read_empty(self):
        entries = read_transcript("agt_no_transcript")
        assert entries == []

    def test_transcript_path(self):
        path = get_transcript_path("agt_test")
        assert "agt_test.jsonl" in path
        assert "transcripts" in path

    def test_build_summary_from_response(self):
        result = {"response": "分析完成：共找到 3 处问题"}
        summary = build_summary(result, max_length=50)
        assert "分析完成" in summary

    def test_build_summary_from_content(self):
        result = {"content": "代码审查通过"}
        summary = build_summary(result)
        assert summary == "代码审查通过"

    def test_build_summary_from_error(self):
        result = {"error": "执行超时"}
        summary = build_summary(result)
        assert "[ERROR]" in summary

    def test_build_summary_truncation(self):
        result = {"response": "A" * 3000}
        summary = build_summary(result, max_length=100)
        assert len(summary) <= 100 + 3  # +3 for "..."
        assert summary.endswith("...")


# -- SSE 事件构建 ------------------------------------------------------

class TestSSEEvents:
    """SSE 事件构建测试。"""

    def test_subagent_start_event(self):
        event = emit_subagent_start_event("agt_001", "Explore", "调研代码结构")
        assert event["type"] == "subagent_start"
        assert event["agent_id"] == "agt_001"
        assert event["agent_type"] == "Explore"

    def test_subagent_stop_event(self):
        event = emit_subagent_stop_event("agt_001", "completed", "任务完成", agent_type="Explore")
        assert event["type"] == "subagent_stop"
        assert event["state"] == "completed"
        assert event["summary"] == "任务完成"
        assert event["agent_type"] == "Explore"

    def test_agent_message_event(self):
        event = emit_agent_message_event("agt_001", "摘要消息内容", agent_type="Explore")
        assert event["type"] == "agent_message"
        assert event["agent_id"] == "agt_001"
        assert event["message"] == "摘要消息内容"
        assert event["agent_type"] == "Explore"

    def test_subagent_stop_failed(self):
        event = emit_subagent_stop_event("agt_002", "failed", "执行错误", agent_type="Executor")
        assert event["type"] == "subagent_stop"
        assert event["state"] == "failed"
        assert event["agent_type"] == "Executor"


class TestSubagentRunnerContext:
    """子代理运行上下文测试。"""

    def test_create_subagent_execution_bundle_uses_dedicated_db_session(self, monkeypatch):
        class FakeSession:
            def __init__(self):
                self.closed = False

            def close(self):
                self.closed = True

        fake_session = FakeSession()
        captured: dict[str, object] = {}

        class FakeAgent:
            def __init__(self, db_session=None):
                captured["db_session"] = db_session

        monkeypatch.setattr(runners_module, "SessionLocal", lambda: fake_session)
        monkeypatch.setattr(agent_module, "AIAgent", FakeAgent)

        sub_agent, subagent_db, sub_context = runners_module._create_subagent_execution_bundle(
            agent_id="agt_runner_1",
            agent_type="Explore",
            provider=None,
            model=None,
            context={
                "user_id": "user-1",
                "username": "tester",
                "provider": "deepseek",
                "model": "deepseek-chat",
                "configured_model_catalog": {
                    "providers": [
                        {"provider": "deepseek", "models": ["deepseek-chat"]},
                    ],
                    "entries": [
                        {"provider": "deepseek", "model": "deepseek-chat", "label": "deepseek:deepseek-chat"},
                    ],
                },
            },
        )

        assert isinstance(sub_agent, FakeAgent)
        assert subagent_db is fake_session
        assert captured["db_session"] is fake_session
        assert sub_context["db"] is fake_session
        assert sub_context["provider"] == "deepseek"
        assert sub_context["model"] == "deepseek-chat"


# -- 代理定义 ----------------------------------------------------------

class TestAgentDefinitions:
    """代理定义与注册表测试。"""

    def test_get_explore_definition(self):
        agent_def = get_agent_definition("Explore")
        assert agent_def is not None
        assert agent_def.name == "Explore"
        assert agent_def.permission_mode == "plan"
        assert agent_def.memory_mode == "none"
        assert agent_def.color == "#6B8E23"

    def test_get_plan_definition(self):
        agent_def = get_agent_definition("Plan")
        assert agent_def is not None
        assert agent_def.permission_mode == "plan"
        assert agent_def.isolation_mode == "inherit"

    def test_get_general_purpose(self):
        agent_def = get_agent_definition("general-purpose")
        assert agent_def is not None
        assert agent_def.permission_mode == "default"
        assert agent_def.memory_mode == "user"
        assert agent_def.isolation_mode == "fresh"

    def test_get_unknown(self):
        assert get_agent_definition("UnknownAgent") is None

    def test_list_types(self):
        types = list_agent_types()
        assert "Explore" in types
        assert "Plan" in types
        assert "general-purpose" in types

    def test_builtin_agents(self):
        agents = get_builtin_agents()
        assert len(agents) >= 3

    def test_registry_get_builtin(self):
        agent_def = agent_registry.get("Explore")
        assert agent_def is not None
        assert agent_def.name == "Explore"

    def test_registry_list_types_has_builtins(self):
        types = agent_registry.list_types()
        assert "Explore" in types
        assert "Plan" in types

    def test_registry_register_plugin(self):
        custom = AgentDefinition(
            name="CustomAgent",
            scope="plugin",
            description="自定义代理",
            permission_mode="accept_edits",
        )
        agent_registry.register("CustomAgent", custom, source="plugin")

        found = agent_registry.get("CustomAgent")
        assert found is not None
        assert found.description == "自定义代理"

        agent_registry.unregister("CustomAgent")
        assert agent_registry.get("CustomAgent") is None

    def test_registry_db_takes_priority(self):
        db_def = AgentDefinition(
            name="Explore",
            scope="user",
            description="DB 覆盖版本",
            permission_mode="default",
        )
        agent_registry.register("Explore", db_def, source="db")

        found = agent_registry.get("Explore")
        assert found is not None
        assert found.scope == "user"
        assert found.description == "DB 覆盖版本"

        agent_registry.unregister("Explore")

    def test_to_dict(self):
        agent_def = AgentDefinition(
            name="Test",
            scope="user",
            description="测试用",
            memory_mode="project",
            color="#FF0000",
        )
        d = agent_def.to_dict()
        assert d["name"] == "Test"
        assert d["memory_mode"] == "project"
        assert d["color"] == "#FF0000"
        assert d["background_default"] is False
