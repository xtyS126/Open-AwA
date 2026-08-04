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
from core.conversation_recorder import JsonlTranscriptWriter
from core.conversation_sessions import (
    deserialize_messages_with_interrupt_detection,
    ensure_conversation,
    load_conversation_for_resume,
)
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
    """
    反馈层写入记忆时应保留当前用户标识。

    Spec memory-experience-redesign：关键词命中后长期记忆写入改为后台
    提炼触发（原文不再直存），user_id 经 extract_turn_async 透传。
    """

    class StubMemoryManager:
        def __init__(self):
            self.short_calls = []
            self.long_calls = []

        async def add_short_term_memory(self, **kwargs):
            self.short_calls.append(kwargs)

        async def add_long_term_memory(self, **kwargs):
            self.long_calls.append(kwargs)

    class StubRunner:
        """记录即时提炼调用（含 user_id 透传）。"""

        _conversation_threshold = 10

        def __init__(self):
            self.extract_calls = []

        def increment_conversation_count(self, user_id, workspace_id="default"):
            return 5

        async def extract_turn_async(self, user_input, response, user_id, workspace_id="default"):
            self.extract_calls.append(
                {"user_input": user_input, "response": response, "user_id": user_id}
            )
            return 1

    memory_manager = StubMemoryManager()
    runner = StubRunner()
    feedback_layer = FeedbackLayer()
    feedback_layer.set_memory_manager(memory_manager)
    feedback_layer.set_consolidation_runner(runner)

    await feedback_layer.update_memory(
        user_input="请记住我的偏好",
        response="好的，我会记住这个重要偏好。",
        context={"session_id": "session-feedback", "user_id": "user-1"},
    )
    # 让后台 create_task 有执行机会
    import asyncio

    await asyncio.sleep(0)

    assert len(memory_manager.short_calls) == 2
    assert memory_manager.short_calls[0]["user_id"] == "user-1"
    assert memory_manager.short_calls[1]["user_id"] == "user-1"
    # 原文不再直存长期记忆；提炼触发携带 user_id
    assert len(memory_manager.long_calls) == 0
    assert len(runner.extract_calls) == 1
    assert runner.extract_calls[0]["user_id"] == "user-1"
    assert runner.extract_calls[0]["user_input"] == "请记住我的偏好"


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


def test_list_sessions_hides_subagent_internal_sessions():
    """会话列表应隐藏子代理内部会话，但数据库记录仍保留。"""
    db = TestingSessionLocal()
    try:
        db.add_all(
            [
                Conversation(
                    session_id="conv-visible",
                    user_id="user-1",
                    title="用户会话",
                    summary="",
                    last_message_preview="",
                    message_count=1,
                    conversation_metadata={},
                ),
                Conversation(
                    session_id="subagent_agt_hidden",
                    user_id="user-1",
                    title="内部子代理会话",
                    summary="",
                    last_message_preview="",
                    message_count=1,
                    conversation_metadata={},
                ),
            ]
        )
        db.commit()

        stored_session_ids = {
            item.session_id
            for item in db.query(Conversation).filter(Conversation.user_id == "user-1").all()
        }
        assert stored_session_ids == {"conv-visible", "subagent_agt_hidden"}
    finally:
        db.close()

    with _test_client() as client:
        response = client.get(f"{settings.API_V1_STR}/conversations")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert [item["session_id"] for item in payload["items"]] == ["conv-visible"]


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


# ---------------------------------------------------------------------------
# 会话恢复（--resume）相关测试
# ---------------------------------------------------------------------------


def _write_transcript(
    base_dir: str,
    session_id: str,
    records: list[dict],
) -> None:
    """辅助函数：将消息记录列表写入 JSONL 文件。"""
    writer = JsonlTranscriptWriter(session_id=session_id, base_dir=base_dir)
    for record in records:
        writer.append(
            uuid=record["uuid"],
            parent_uuid=record.get("parent_uuid"),
            type=record["type"],
            content=record["content"],
            timestamp=record.get("timestamp", "2026-01-01T00:00:00+00:00"),
        )
    writer.close()


def test_load_conversation_for_resume_from_jsonl(tmp_path: Path) -> None:
    """验证从 JSONL 文件加载会话消息，type 字段正确映射为 role。"""
    base_dir = str(tmp_path / "transcripts")
    _write_transcript(
        base_dir,
        "resume-jsonl-test",
        [
            {"uuid": "msg-1", "parent_uuid": None, "type": "user", "content": "你好"},
            {"uuid": "msg-2", "parent_uuid": "msg-1", "type": "assistant", "content": "你好，我是助手"},
        ],
    )

    messages = load_conversation_for_resume("resume-jsonl-test", base_dir=base_dir)

    assert len(messages) == 2
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "你好"
    assert messages[1]["role"] == "assistant"
    assert messages[1]["content"] == "你好，我是助手"
    # 验证 JSONL 元数据字段保留
    assert messages[0]["uuid"] == "msg-1"
    assert messages[0]["parent_uuid"] is None
    assert messages[1]["parent_uuid"] == "msg-1"


def test_load_conversation_for_resume_fallback_to_db(monkeypatch) -> None:
    """JSONL 文件不存在时，应回退到数据库 ConversationRecord 加载。"""
    # 替换 SessionLocal 为测试数据库会话工厂
    from core import conversation_sessions

    monkeypatch.setattr(conversation_sessions, "SessionLocal", TestingSessionLocal)

    db = TestingSessionLocal()
    try:
        db.add(
            ConversationRecord(
                session_id="resume-db-test",
                user_id="user-1",
                node_type="chat",
                user_message="数据库回退问题",
                llm_output={"content": "数据库回退回复"},
                status="success",
            )
        )
        db.commit()
    finally:
        db.close()

    # 使用不存在的 base_dir 确保 JSONL 文件不存在
    messages = load_conversation_for_resume(
        "resume-db-test",
        base_dir="data/nonexistent_transcripts_for_test",
    )

    assert len(messages) == 2
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "数据库回退问题"
    assert messages[1]["role"] == "assistant"
    assert messages[1]["content"] == "数据库回退回复"


def test_load_conversation_for_resume_empty(tmp_path: Path) -> None:
    """空会话（无 JSONL 且无数据库记录）应返回空列表。"""
    from core import conversation_sessions

    # 临时替换 SessionLocal 以使用测试数据库
    original_session_local = conversation_sessions.SessionLocal
    conversation_sessions.SessionLocal = TestingSessionLocal
    try:
        messages = load_conversation_for_resume(
            "resume-empty-test",
            base_dir=str(tmp_path / "empty_transcripts"),
        )
        assert messages == []
    finally:
        conversation_sessions.SessionLocal = original_session_local


def test_deserialize_filters_unresolved_tool_uses() -> None:
    """验证过滤未完成 tool_use：无对应 tool 结果的 tool_use 块应被移除。"""
    messages = [
        {"role": "user", "content": "请搜索资料"},
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "我来搜索"},
                {"type": "tool_use", "id": "tool-1", "name": "search", "input": {"q": "test"}},
            ],
        },
        # 缺少 tool_call_id="tool-1" 的 tool 结果消息
    ]

    filtered, was_interrupted = deserialize_messages_with_interrupt_detection(messages)

    # 未完成 tool_use 被检测为中断
    assert was_interrupted is True
    # 过滤后: user + assistant(仅保留 text 块) + 续接 prompt = 3 条
    assert len(filtered) == 3
    assistant_msg = next(m for m in filtered if m["role"] == "assistant")
    assert all(item.get("type") != "tool_use" for item in assistant_msg["content"])
    # 末尾应注入续接 prompt
    assert filtered[-1]["role"] == "user"
    assert filtered[-1]["content"] == "Continue from where you left off."


def test_deserialize_filters_orphaned_thinking() -> None:
    """验证过滤孤立 thinking：只含 thinking 的 assistant 消息应被移除。"""
    messages = [
        {"role": "user", "content": "你好"},
        {
            "role": "assistant",
            "content": [
                {"type": "thinking", "thinking": "让我想想"},
            ],
        },
        {"role": "assistant", "content": "你好，很高兴见到你"},
    ]

    filtered, was_interrupted = deserialize_messages_with_interrupt_detection(messages)

    # 正常会话不中断
    assert was_interrupted is False
    # 只含 thinking 的孤立消息被移除
    assert len(filtered) == 2
    assert filtered[0]["role"] == "user"
    assert filtered[1]["role"] == "assistant"
    assert filtered[1]["content"] == "你好，很高兴见到你"


def test_deserialize_filters_whitespace_assistant() -> None:
    """验证过滤空白 assistant：content 为纯空白的 assistant 消息应被移除。"""
    messages = [
        {"role": "user", "content": "请回复"},
        {"role": "assistant", "content": "   "},
        {"role": "assistant", "content": "这是有效回复"},
    ]

    filtered, was_interrupted = deserialize_messages_with_interrupt_detection(messages)

    # 正常会话不中断
    assert was_interrupted is False
    # 空白 assistant 消息被移除
    assert len(filtered) == 2
    assert filtered[0]["role"] == "user"
    assert filtered[1]["role"] == "assistant"
    assert filtered[1]["content"] == "这是有效回复"


def test_deserialize_detects_interrupt_user_last() -> None:
    """验证检测中断：最后一条为 user 消息时应判定为中断。"""
    messages = [
        {"role": "user", "content": "第一个问题"},
        {"role": "assistant", "content": "第一个回复"},
        {"role": "user", "content": "第二个问题"},  # 用户发送后未收到响应
    ]

    filtered, was_interrupted = deserialize_messages_with_interrupt_detection(
        messages, session_id="interrupt-user-last"
    )

    assert was_interrupted is True
    # 末尾注入续接 prompt
    assert filtered[-1]["role"] == "user"
    assert filtered[-1]["content"] == "Continue from where you left off."
    # 原始消息保留
    assert len(filtered) == 4


def test_deserialize_detects_interrupt_unfinished_tool() -> None:
    """验证检测中断：最后一条 assistant 含未完成 tool_use 时应判定为中断。"""
    messages = [
        {"role": "user", "content": "请执行搜索"},
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "正在搜索"},
                {"type": "tool_use", "id": "tool-99", "name": "search", "input": {"q": "test"}},
            ],
        },
        # 缺少 tool_call_id="tool-99" 的 tool 结果消息，表示 AI 调用工具时被中断
    ]

    filtered, was_interrupted = deserialize_messages_with_interrupt_detection(
        messages, session_id="interrupt-tool"
    )

    assert was_interrupted is True
    # 末尾注入续接 prompt
    assert filtered[-1]["role"] == "user"
    assert filtered[-1]["content"] == "Continue from where you left off."


def test_deserialize_injects_continue_prompt() -> None:
    """验证中断时注入续接 prompt，且 prompt 内容与位置正确。"""
    messages = [
        {"role": "user", "content": "问题"},
        {"role": "assistant", "content": "回复"},
        {"role": "user", "content": "追问"},  # 中断点
    ]

    filtered, was_interrupted = deserialize_messages_with_interrupt_detection(messages)

    assert was_interrupted is True
    # 续接 prompt 应为最后一条消息
    continue_prompt = filtered[-1]
    assert continue_prompt["role"] == "user"
    assert continue_prompt["content"] == "Continue from where you left off."
    # 续接 prompt 前一条应为原始最后一条 user 消息
    assert filtered[-2]["content"] == "追问"


def test_deserialize_no_interrupt() -> None:
    """验证正常会话（最后一条为 assistant 文本回复）不注入续接 prompt。"""
    messages = [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "你好，有什么可以帮你的？"},
    ]

    filtered, was_interrupted = deserialize_messages_with_interrupt_detection(messages)

    assert was_interrupted is False
    # 不注入续接 prompt，消息数量不变
    assert len(filtered) == 2
    assert filtered[-1]["role"] == "assistant"
    assert filtered[-1]["content"] == "你好，有什么可以帮你的？"