"""
任务运行时 Phase 4 测试，覆盖团队管理、成员操作与邮箱消息。
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from db.models import init_db, TaskTeam, TaskTeamMember, TaskMailboxMessage
from core.task_runtime.team_manager import (
    create_team,
    delete_team,
    add_teammate,
    remove_teammate,
    list_teams,
    get_team,
    send_teammate_message,
    get_mailbox,
    mark_message_read,
    update_teammate_state,
    validate_team_transition,
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


# ── 团队状态机 ────────────────────────────────────────────────

class TestTeamStateMachine:
    """团队状态转换测试。"""

    def test_starting_to_active(self):
        assert validate_team_transition("starting", "active") is True

    def test_starting_to_failed(self):
        assert validate_team_transition("starting", "failed") is True

    def test_active_to_cleaning(self):
        assert validate_team_transition("active", "cleaning") is True

    def test_active_to_failed(self):
        assert validate_team_transition("active", "failed") is True

    def test_cleaning_to_stopped(self):
        assert validate_team_transition("cleaning", "stopped") is True

    def test_stopped_no_transition(self):
        assert validate_team_transition("stopped", "active") is False
        assert validate_team_transition("stopped", "failed") is False

    def test_invalid_transition(self):
        assert validate_team_transition("active", "starting") is False


# ── 团队创建与删除 ────────────────────────────────────────────

class TestTeamCreateDelete:
    """团队 CRUD 测试。"""

    def test_create_team_minimal(self, testing_session_local):
        db = testing_session_local()
        try:
            result = create_team(lead_agent_id="lead_001", db=db)
            assert result.get("ok") is True
            assert result.get("team_id", "").startswith("team_")
            assert result.get("lead_agent_id") == "lead_001"
            assert result.get("state") == "active"
            assert len(result.get("members", [])) == 1
            assert result["members"][0]["role"] == "lead"

            db.close()
            # 使用同一 db 删除
            db2 = testing_session_local()
            delete_team(result["team_id"], db=db2)
            db2.close()
        finally:
            pass

    def test_create_team_with_name(self, testing_session_local):
        db = testing_session_local()
        try:
            result = create_team(lead_agent_id="lead_002", name="测试团队", db=db)
            assert result.get("ok") is True
            assert result.get("name") == "测试团队"
            delete_team(result["team_id"], db=db)
        finally:
            db.close()

    def test_create_team_with_teammates(self, testing_session_local):
        db = testing_session_local()
        try:
            result = create_team(
                lead_agent_id="lead_003",
                name="协作团队",
                teammate_agent_ids=[
                    {"agent_id": "agt_a", "name": "Alice"},
                    {"agent_id": "agt_b", "name": "Bob"},
                ],
                db=db,
            )
            assert result.get("ok") is True
            assert len(result.get("members", [])) == 3
            delete_team(result["team_id"], db=db)
        finally:
            db.close()

    def test_delete_team(self, testing_session_local):
        db = testing_session_local()
        try:
            result = create_team(lead_agent_id="lead_del", db=db)
            team_id = result["team_id"]
            del_result = delete_team(team_id, db=db)
            assert del_result.get("ok") is True
            assert del_result.get("status") == "stopped"
        finally:
            db.close()

    def test_delete_nonexistent_team(self, testing_session_local):
        db = testing_session_local()
        try:
            result = delete_team("team_nonexistent", db=db)
            assert result.get("ok") is False
        finally:
            db.close()

    def test_delete_already_cleaning(self, testing_session_local):
        db = testing_session_local()
        try:
            r = create_team(lead_agent_id="lead_clean", db=db)
            team_id = r["team_id"]

            # 手动设为 cleaning
            team = db.query(TaskTeam).filter(TaskTeam.team_id == team_id).first()
            team.state = "cleaning"
            db.commit()

            result = delete_team(team_id, db=db)
            assert result.get("ok") is False

            # 清理：手动改回再删除
            team.state = "active"
            db.commit()
            delete_team(team_id, db=db)
        finally:
            db.close()


# ── 成员管理 ──────────────────────────────────────────────────

class TestTeamMembers:
    """团队成员管理测试。"""

    def test_add_teammate(self, testing_session_local):
        db = testing_session_local()
        try:
            r = create_team(lead_agent_id="lead_member", name="成员测试团队", db=db)
            team_id = r["team_id"]

            result = add_teammate(team_id, "agt_new", "NewGuy", db=db)
            assert result.get("ok") is True

            team = get_team(team_id, db=db)
            member_ids = [m["agent_id"] for m in team["members"]]
            assert "agt_new" in member_ids

            delete_team(team_id, db=db)
        finally:
            db.close()

    def test_add_duplicate_teammate_fails(self, testing_session_local):
        db = testing_session_local()
        try:
            r = create_team(lead_agent_id="lead_dup", db=db)
            team_id = r["team_id"]

            add_teammate(team_id, "agt_dup", "Dup", db=db)
            result = add_teammate(team_id, "agt_dup", "DupAgain", db=db)
            assert result.get("ok") is False

            delete_team(team_id, db=db)
        finally:
            db.close()

    def test_remove_teammate(self, testing_session_local):
        db = testing_session_local()
        try:
            r = create_team(lead_agent_id="lead_rm", db=db)
            team_id = r["team_id"]

            add_teammate(team_id, "agt_rm", "RemoveMe", db=db)
            result = remove_teammate(team_id, "agt_rm", db=db)
            assert result.get("ok") is True

            delete_team(team_id, db=db)
        finally:
            db.close()

    def test_remove_lead_fails(self, testing_session_local):
        db = testing_session_local()
        try:
            r = create_team(lead_agent_id="lead_cannot_rm", db=db)
            team_id = r["team_id"]

            result = remove_teammate(team_id, "lead_cannot_rm", db=db)
            assert result.get("ok") is False

            delete_team(team_id, db=db)
        finally:
            db.close()

    def test_remove_nonexistent_member(self, testing_session_local):
        db = testing_session_local()
        try:
            r = create_team(lead_agent_id="lead_ghost", db=db)
            team_id = r["team_id"]

            result = remove_teammate(team_id, "agt_ghost", db=db)
            assert result.get("ok") is False

            delete_team(team_id, db=db)
        finally:
            db.close()

    def test_add_to_inactive_team(self, testing_session_local):
        db = testing_session_local()
        try:
            r = create_team(lead_agent_id="lead_inactive", db=db)
            team_id = r["team_id"]

            team = db.query(TaskTeam).filter(TaskTeam.team_id == team_id).first()
            team.state = "cleaning"
            db.commit()

            result = add_teammate(team_id, "agt_fail", "Fail", db=db)
            assert result.get("ok") is False

            team.state = "active"
            db.commit()
            delete_team(team_id, db=db)
        finally:
            db.close()

    def test_update_member_state(self, testing_session_local):
        db = testing_session_local()
        try:
            r = create_team(lead_agent_id="lead_state", db=db)
            team_id = r["team_id"]

            add_teammate(team_id, "agt_state", "StateMan", db=db)
            result = update_teammate_state(team_id, "agt_state", "idle", db=db)
            assert result.get("ok") is True
            assert result.get("state") == "idle"

            delete_team(team_id, db=db)
        finally:
            db.close()

    def test_update_member_invalid_state(self, testing_session_local):
        db = testing_session_local()
        try:
            r = create_team(lead_agent_id="lead_bad", db=db)
            team_id = r["team_id"]

            add_teammate(team_id, "agt_badstate", "Bad", db=db)
            result = update_teammate_state(team_id, "agt_badstate", "dead", db=db)
            assert result.get("ok") is False

            delete_team(team_id, db=db)
        finally:
            db.close()


# ── 邮箱消息 ──────────────────────────────────────────────────

class TestMailbox:
    """邮箱消息测试。"""

    def test_send_message(self, testing_session_local):
        db = testing_session_local()
        try:
            r = create_team(
                lead_agent_id="lead_mail",
                name="消息测试团队",
                teammate_agent_ids=[{"agent_id": "agt_alice", "name": "Alice"}],
                db=db,
            )
            team_id = r["team_id"]

            result = send_teammate_message(
                from_agent_id="lead_mail",
                to_agent_id="agt_alice",
                message="你好 Alice！",
                team_id=team_id,
                db=db,
            )
            assert result.get("ok") is True
            assert result.get("from_agent_id") == "lead_mail"
            assert result.get("to_agent_id") == "agt_alice"
            assert result.get("delivered") is False

            delete_team(team_id, db=db)
        finally:
            db.close()

    def test_get_mailbox(self, testing_session_local):
        db = testing_session_local()
        try:
            r = create_team(
                lead_agent_id="lead_mail2",
                teammate_agent_ids=[{"agent_id": "agt_bob", "name": "Bob"}],
                db=db,
            )
            team_id = r["team_id"]

            send_teammate_message("lead_mail2", "agt_bob", "消息1", team_id=team_id, db=db)
            send_teammate_message("lead_mail2", "agt_bob", "消息2", team_id=team_id, db=db)

            messages = get_mailbox("agt_bob", db=db)
            assert len(messages) == 2
            assert messages[0]["from_agent_id"] == "lead_mail2"

            delete_team(team_id, db=db)
        finally:
            db.close()

    def test_get_mailbox_unread_only(self, testing_session_local):
        db = testing_session_local()
        try:
            r = create_team(
                lead_agent_id="lead_unread",
                teammate_agent_ids=[{"agent_id": "agt_unread", "name": "Unread"}],
                db=db,
            )
            team_id = r["team_id"]

            send_teammate_message("lead_unread", "agt_unread", "msg1", team_id=team_id, db=db)
            send_teammate_message("lead_unread", "agt_unread", "msg2", team_id=team_id, db=db)

            all_msgs = get_mailbox("agt_unread", db=db)
            mark_message_read(all_msgs[0]["message_id"], db=db)

            unread = get_mailbox("agt_unread", unread_only=True, db=db)
            assert len(unread) == 1

            delete_team(team_id, db=db)
        finally:
            db.close()

    def test_mark_message_read(self, testing_session_local):
        db = testing_session_local()
        try:
            r = create_team(
                lead_agent_id="lead_mark",
                teammate_agent_ids=[{"agent_id": "agt_mark", "name": "Mark"}],
                db=db,
            )
            team_id = r["team_id"]

            send_teammate_message("lead_mark", "agt_mark", "read me", team_id=team_id, db=db)
            messages = get_mailbox("agt_mark", db=db)
            msg_id = messages[0]["message_id"]

            result = mark_message_read(msg_id, db=db)
            assert result.get("ok") is True
            assert result.get("delivered") is True

            delete_team(team_id, db=db)
        finally:
            db.close()

    def test_mark_nonexistent_message(self, testing_session_local):
        db = testing_session_local()
        try:
            result = mark_message_read("msg_ghost", db=db)
            assert result.get("ok") is False
        finally:
            db.close()

    def test_get_empty_mailbox(self, testing_session_local):
        db = testing_session_local()
        try:
            messages = get_mailbox("agent_no_messages", db=db)
            assert messages == []
        finally:
            db.close()

    def test_send_message_without_team(self, testing_session_local):
        db = testing_session_local()
        try:
            result = send_teammate_message(
                from_agent_id="agt_a",
                to_agent_id="agt_b",
                message="独立消息",
                db=db,
            )
            assert result.get("ok") is True
        finally:
            db.close()


# ── 团队列表与查询 ────────────────────────────────────────────

class TestTeamList:
    """团队列表与查询测试。"""

    def test_list_teams(self, testing_session_local):
        db = testing_session_local()
        try:
            r = create_team(lead_agent_id="lead_list", name="列表测试", db=db)
            team_id = r["team_id"]

            teams = list_teams(db=db)
            assert isinstance(teams, list)
            assert any(t["team_id"] == team_id for t in teams)

            delete_team(team_id, db=db)
        finally:
            db.close()

    def test_list_teams_by_state(self, testing_session_local):
        db = testing_session_local()
        try:
            r = create_team(lead_agent_id="lead_state2", name="状态测试", db=db)
            team_id = r["team_id"]

            active_teams = list_teams(state="active", db=db)
            assert any(t["team_id"] == team_id for t in active_teams)

            stopped_teams = list_teams(state="stopped", db=db)
            assert not any(t["team_id"] == team_id for t in stopped_teams)

            delete_team(team_id, db=db)
        finally:
            db.close()

    def test_get_team(self, testing_session_local):
        db = testing_session_local()
        try:
            r = create_team(
                lead_agent_id="lead_detail",
                name="详情测试",
                teammate_agent_ids=[{"agent_id": "agt_detail", "name": "Detail"}],
                db=db,
            )
            team_id = r["team_id"]

            team = get_team(team_id, db=db)
            assert team is not None
            assert team["name"] == "详情测试"
            assert len(team["members"]) == 2
            assert team["lead_agent_id"] == "lead_detail"

            delete_team(team_id, db=db)
        finally:
            db.close()

    def test_get_nonexistent_team(self, testing_session_local):
        db = testing_session_local()
        try:
            assert get_team("team_fake", db=db) is None
        finally:
            db.close()
