"""会话级助手上下文 API 的持久化、可见性与归属校验测试。"""

from contextlib import contextmanager
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.dependencies import get_current_user, get_db
from api.routes.conversation import router as conversation_router
from db.models import AgentRole, Base, Conversation, LongTermMemory, Workspace


engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base.metadata.create_all(bind=engine)

app = FastAPI()
app.include_router(conversation_router, prefix="/api")


def _override_get_db():
    """为 API 测试提供隔离的数据库会话。"""
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


def _override_current_user():
    """使用可与 AgentRole.creator_id 兼容比较的测试用户。"""
    return SimpleNamespace(id="1", username="owner", role="user")


@contextmanager
def _client():
    """在单个用例内安装依赖覆盖，避免污染其他测试模块。"""
    previous_overrides = dict(app.dependency_overrides)
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_user] = _override_current_user
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides = previous_overrides


def _reset_tables() -> None:
    """只清理本测试文件写入的隔离表。"""
    db = TestingSessionLocal()
    try:
        db.query(LongTermMemory).delete()
        db.query(Conversation).delete()
        db.query(AgentRole).delete()
        db.query(Workspace).delete()
        db.commit()
    finally:
        db.close()


def setup_function() -> None:
    _reset_tables()


def teardown_function() -> None:
    _reset_tables()


def _add_conversation(
    session_id: str = "session-context",
    user_id: str = "1",
    metadata: dict | None = None,
) -> None:
    db = TestingSessionLocal()
    try:
        db.add(
            Conversation(
                session_id=session_id,
                user_id=user_id,
                title="上下文测试会话",
                summary="",
                last_message_preview="",
                message_count=0,
                conversation_metadata=metadata or {},
            )
        )
        db.commit()
    finally:
        db.close()


def _add_visible_resources() -> int:
    """创建当前用户可见的角色、工作区与长期记忆。"""
    db = TestingSessionLocal()
    try:
        db.add(
            AgentRole(
                id="role-visible",
                name="可见角色",
                system_prompt="你是测试角色。",
                creator_id=1,
                is_public=False,
                is_preset=False,
            )
        )
        db.add(
            Workspace(
                id="workspace-owned",
                name="当前用户工作区",
                is_enabled=True,
                config_json={"owner_id": "1"},
            )
        )
        memory = LongTermMemory(
            user_id="1",
            workspace_id="workspace-owned",
            content="仅注入这条已选择记忆",
            archive_status="active",
            state="active",
        )
        db.add(memory)
        db.commit()
        db.refresh(memory)
        return int(memory.id)
    finally:
        db.close()


def test_get_assistant_context_returns_legacy_defaults() -> None:
    """旧会话没有 assistant_context 时必须保持默认行为。"""
    _add_conversation(metadata={"unrelated": {"keep": True}})

    with _client() as client:
        response = client.get("/api/conversations/session-context/assistant-context")

    assert response.status_code == 200
    assert response.json() == {
        "session_id": "session-context",
        "role_id": None,
        "workspace_id": "default",
        "selected_memory_ids": [],
        "speaker_id": None,
    }


def test_patch_assistant_context_persists_fixed_metadata_key() -> None:
    """PATCH 应只写 assistant_context 子键并保留其他会话元数据。"""
    _add_conversation(metadata={"unrelated": {"keep": True}})
    memory_id = _add_visible_resources()

    with _client() as client:
        response = client.patch(
            "/api/conversations/session-context/assistant-context",
            json={
                "role_id": "role-visible",
                "workspace_id": "workspace-owned",
                "selected_memory_ids": [memory_id],
                "speaker_id": "speaker-preference",
            },
        )

    assert response.status_code == 200
    assert response.json() == {
        "session_id": "session-context",
        "role_id": "role-visible",
        "workspace_id": "workspace-owned",
        "selected_memory_ids": [memory_id],
        "speaker_id": "speaker-preference",
    }

    db = TestingSessionLocal()
    try:
        stored = db.query(Conversation).filter(Conversation.session_id == "session-context").one()
        assert stored.conversation_metadata == {
            "unrelated": {"keep": True},
            "assistant_context": {
                "role_id": "role-visible",
                "workspace_id": "workspace-owned",
                "selected_memory_ids": [memory_id],
                "speaker_id": "speaker-preference",
            },
        }
    finally:
        db.close()


def test_patch_assistant_context_rejects_invisible_role() -> None:
    """私有且不属于当前用户的角色不得写入会话上下文。"""
    _add_conversation()
    db = TestingSessionLocal()
    try:
        db.add(
            AgentRole(
                id="role-private-other",
                name="其他用户私有角色",
                system_prompt="不可见。",
                creator_id=2,
                is_public=False,
                is_preset=False,
            )
        )
        db.commit()
    finally:
        db.close()

    with _client() as client:
        response = client.patch(
            "/api/conversations/session-context/assistant-context",
            json={"role_id": "role-private-other"},
        )

    assert response.status_code == 404
    assert response.json()["detail"] == "Assistant role is not available"


def test_patch_assistant_context_rejects_foreign_memory() -> None:
    """其他用户的长期记忆不得被选择，也不得产生部分写入。"""
    _add_conversation(metadata={"unrelated": True})
    db = TestingSessionLocal()
    try:
        db.add(
            Workspace(
                id="workspace-shared",
                name="共享工作区",
                is_enabled=True,
                config_json={},
            )
        )
        memory = LongTermMemory(
            user_id="2",
            workspace_id="workspace-shared",
            content="其他用户的记忆",
            archive_status="active",
            state="active",
        )
        db.add(memory)
        db.commit()
        db.refresh(memory)
        memory_id = int(memory.id)
    finally:
        db.close()

    with _client() as client:
        response = client.patch(
            "/api/conversations/session-context/assistant-context",
            json={
                "workspace_id": "workspace-shared",
                "selected_memory_ids": [memory_id],
            },
        )

    assert response.status_code == 404
    assert response.json()["detail"] == "Selected memory is not available"
    db = TestingSessionLocal()
    try:
        stored = db.query(Conversation).filter(Conversation.session_id == "session-context").one()
        assert stored.conversation_metadata == {"unrelated": True}
    finally:
        db.close()


def test_assistant_context_rejects_other_users_conversation() -> None:
    """GET 与 PATCH 都必须沿用会话所有权保护。"""
    _add_conversation(session_id="foreign-session", user_id="2")

    with _client() as client:
        get_response = client.get("/api/conversations/foreign-session/assistant-context")
        patch_response = client.patch(
            "/api/conversations/foreign-session/assistant-context",
            json={"speaker_id": "not-allowed"},
        )

    assert get_response.status_code == 403
    assert patch_response.status_code == 403


def test_patch_assistant_context_rejects_more_than_twenty_memories() -> None:
    """单个会话最多允许选择二十条长期记忆。"""
    _add_conversation()

    with _client() as client:
        response = client.patch(
            "/api/conversations/session-context/assistant-context",
            json={"selected_memory_ids": list(range(1, 22))},
        )

    assert response.status_code == 422


def test_patch_assistant_context_rejects_oversized_speaker_id() -> None:
    """声音偏好标识不得超过一百二十八个字符。"""
    _add_conversation()

    with _client() as client:
        response = client.patch(
            "/api/conversations/session-context/assistant-context",
            json={"speaker_id": "s" * 129},
        )

    assert response.status_code == 422


def test_materialized_default_context_does_not_require_workspace_row() -> None:
    """兼容默认工作区未物化为 Workspace 行的现有会话。"""
    from api.services.assistant_context_service import build_session_agent_context

    _add_conversation(
        metadata={
            "assistant_context": {
                "role_id": None,
                "workspace_id": "default",
                "selected_memory_ids": [],
                "speaker_id": "speaker-preference",
            }
        }
    )
    db = TestingSessionLocal()
    try:
        context = build_session_agent_context(
            db,
            "session-context",
            "1",
            {"request_id": "default-workspace"},
        )
    finally:
        db.close()

    assert context == {
        "request_id": "default-workspace",
        "role_id": None,
        "workspace_id": "default",
        "selected_memory_ids": [],
    }
