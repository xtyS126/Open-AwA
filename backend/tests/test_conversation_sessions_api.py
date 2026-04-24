"""
会话聚合与会话接口回归测试，覆盖会话归属修复与前端依赖的 CRUD 契约。
"""

import sys
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.dependencies import get_current_user, get_db
from config.settings import settings
from core.conversation_sessions import ensure_conversation
from core.feedback import FeedbackLayer
from db.models import Base, Conversation, ConversationRecord
from main import app


engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base.metadata.create_all(bind=engine)


def override_get_db():
    """提供独立测试数据库会话。"""
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


def override_get_current_user():
    """提供固定测试用户。"""

    class DummyUser:
        id = "user-1"
        username = "tester"
        role = "user"

    return DummyUser()


def override_get_other_user():
    """提供另一个测试用户。"""

    class DummyUser:
        id = "user-2"
        username = "other"
        role = "user"

    return DummyUser()


def _reset_tables():
    """清理本测试文件涉及的表。"""
    db = TestingSessionLocal()
    try:
        db.query(ConversationRecord).delete()
        db.query(Conversation).delete()
        db.commit()
    finally:
        db.close()


def setup_function():
    """每个用例前清理测试数据。"""
    _reset_tables()


def teardown_function():
    """每个用例后清理测试数据。"""
    _reset_tables()


@contextmanager
def _test_client():
    """局部注入依赖覆盖，避免污染其他测试。"""
    previous_overrides = dict(app.dependency_overrides)
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides = previous_overrides


@pytest.mark.asyncio
async def test_feedback_layer_forwards_user_id_to_memory_manager():
    """反馈层写入记忆时应保留当前用户标识。"""

    class StubMemoryManager:
        def __init__(self):
            self.short_calls = []
            self.long_calls = []

        async def add_short_term_memory(self, **kwargs):
            self.short_calls.append(kwargs)

        async def add_long_term_memory(self, **kwargs):
            self.long_calls.append(kwargs)

    memory_manager = StubMemoryManager()
    feedback_layer = FeedbackLayer()
    feedback_layer.set_memory_manager(memory_manager)

    await feedback_layer.update_memory(
        user_input="请记住我的偏好",
        response="好的，我会记住这个重要偏好。",
        context={"session_id": "session-feedback", "user_id": "user-1"},
    )

    assert len(memory_manager.short_calls) == 2
    assert memory_manager.short_calls[0]["user_id"] == "user-1"
    assert memory_manager.short_calls[1]["user_id"] == "user-1"
    assert len(memory_manager.long_calls) == 1
    assert memory_manager.long_calls[0]["user_id"] == "user-1"


def test_ensure_conversation_reuses_existing_session_when_user_id_missing():
    """缺失 user_id 的补写不应再次插入同 session_id 的会话聚合行。"""
    db = TestingSessionLocal()
    try:
        existing = Conversation(
            session_id="debug-stream",
            user_id="user-1",
            title="原始标题",
            summary="",
            last_message_preview="",
            message_count=0,
            conversation_metadata={},
        )
        db.add(existing)
        db.commit()

        conversation = ensure_conversation(
            db,
            session_id="debug-stream",
            user_id=None,
            content="新的助手回复",
            role="assistant",
            increment_message_count=True,
        )
        db.commit()

        all_rows = db.query(Conversation).filter(Conversation.session_id == "debug-stream").all()
        assert conversation is not None
        assert len(all_rows) == 1
        assert all_rows[0].user_id == "user-1"
        assert all_rows[0].message_count == 1
        assert all_rows[0].last_message_preview == "新的助手回复"
    finally:
        db.close()


def test_conversation_session_routes_match_frontend_contract():
    """会话 CRUD 路由应覆盖前端历史侧栏当前依赖的接口契约。"""
    with _test_client() as client:
        create_response = client.post(f"{settings.API_V1_STR}/conversations", json={})
        assert create_response.status_code == 200
        created = create_response.json()
        session_id = created["session_id"]
        assert created["user_id"] == "user-1"
        assert created["title"]

        list_response = client.get(f"{settings.API_V1_STR}/conversations")
        assert list_response.status_code == 200
        listed = list_response.json()
        assert listed["total"] == 1
        assert listed["page"] == 1
        assert listed["page_size"] == 20
        assert listed["has_more"] is False
        assert listed["items"][0]["session_id"] == session_id

        rename_response = client.patch(
            f"{settings.API_V1_STR}/conversations/{session_id}",
            json={"title": "已重命名会话"},
        )
        assert rename_response.status_code == 200
        assert rename_response.json()["title"] == "已重命名会话"

        delete_response = client.delete(
            f"{settings.API_V1_STR}/conversations/{session_id}",
            params={"retention_days": 7},
        )
        assert delete_response.status_code == 200
        assert delete_response.json()["deleted_at"] is not None

        active_list_response = client.get(f"{settings.API_V1_STR}/conversations")
        assert active_list_response.status_code == 200
        assert active_list_response.json()["items"] == []

        deleted_list_response = client.get(
            f"{settings.API_V1_STR}/conversations",
            params={"include_deleted": True},
        )
        assert deleted_list_response.status_code == 200
        assert deleted_list_response.json()["items"][0]["session_id"] == session_id
        assert deleted_list_response.json()["items"][0]["deleted_at"] is not None

        restore_response = client.post(f"{settings.API_V1_STR}/conversations/{session_id}/restore")
        assert restore_response.status_code == 200
        assert restore_response.json()["deleted_at"] is None

        batch_delete_response = client.post(
            f"{settings.API_V1_STR}/conversations/batch-delete",
            json={"session_ids": [session_id], "retention_days": 3},
        )
        assert batch_delete_response.status_code == 200
        batch_payload = batch_delete_response.json()
        assert batch_payload["total"] == 1
        assert batch_payload["items"][0]["session_id"] == session_id
        assert batch_payload["items"][0]["deleted_at"] is not None


def test_create_session_rejects_other_users_existing_record():
    """当 session_id 已被其他用户占用时，创建接口应返回 403。"""
    db = TestingSessionLocal()
    try:
        db.add(
            ConversationRecord(
                session_id="shared-session",
                user_id="user-2",
                node_type="chat",
                user_message="hello",
                status="success",
            )
        )
        db.commit()
    finally:
        db.close()

    with _test_client() as client:
        response = client.post(
            f"{settings.API_V1_STR}/conversations",
            json={"session_id": "shared-session"},
        )
        assert response.status_code == 403


def test_rename_session_rejects_other_users_conversation():
    """会话已归属其他用户时，重命名接口应拒绝越权访问。"""
    db = TestingSessionLocal()
    try:
        db.add(
            Conversation(
                session_id="owned-by-other",
                user_id="user-2",
                title="其他用户会话",
                summary="",
                last_message_preview="",
                message_count=0,
                conversation_metadata={},
            )
        )
        db.commit()
    finally:
        db.close()

    with _test_client() as client:
        response = client.patch(
            f"{settings.API_V1_STR}/conversations/owned-by-other",
            json={"title": "不应成功"},
        )
        assert response.status_code == 403