"""验证 HTTP、SSE 与 WebSocket 共用会话助手上下文装配结果。"""

from contextlib import asynccontextmanager
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import Request, Response, WebSocketDisconnect
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.routes import chat as chat_route
from api.schemas import ChatMessage
from api.services import chat_protocol
from db.models import Base, Conversation, LongTermMemory, Workspace


engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base.metadata.create_all(bind=engine)


def _reset_tables() -> None:
    """清理本文件使用的隔离数据。"""
    db = TestingSessionLocal()
    try:
        db.query(LongTermMemory).delete()
        db.query(Conversation).delete()
        db.query(Workspace).delete()
        db.commit()
    finally:
        db.close()


def setup_function() -> None:
    _reset_tables()


def teardown_function() -> None:
    _reset_tables()


def _seed_context() -> int:
    """保存一个可由三种传输读取的会话上下文。"""
    db = TestingSessionLocal()
    try:
        db.add(
            Workspace(
                id="workspace-chat",
                name="聊天工作区",
                is_enabled=True,
                config_json={"owner_id": "1"},
            )
        )
        memory = LongTermMemory(
            user_id="1",
            workspace_id="workspace-chat",
            content="聊天必须使用的显式记忆",
            archive_status="active",
            state="active",
        )
        db.add(memory)
        db.flush()
        db.add(
            Conversation(
                session_id="session-chat-context",
                user_id="1",
                title="聊天上下文",
                summary="",
                last_message_preview="",
                message_count=0,
                conversation_metadata={
                    "assistant_context": {
                        "role_id": None,
                        "workspace_id": "workspace-chat",
                        "selected_memory_ids": [int(memory.id)],
                        "speaker_id": "speaker-only-preference",
                    }
                },
            )
        )
        db.commit()
        return int(memory.id)
    finally:
        db.close()


def _request() -> Request:
    """构造带 request_id 的最小 HTTP Request。"""
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/chat",
            "headers": [],
        }
    )
    request.state.request_id = "request-context-test"
    return request


class _CapturingAgent:
    def __init__(self) -> None:
        self.process_context = None
        self.stream_context = None

    async def process(self, message, context):
        self.process_context = dict(context)
        return {"status": "completed", "response": "ok"}

    async def process_stream(self, message, context):
        self.stream_context = dict(context)
        yield {"type": "content", "content": "ok"}


class _FakeRegistry:
    def __init__(self, agent: _CapturingAgent) -> None:
        self.agent = agent

    @asynccontextmanager
    async def acquire(self, user_id, db):
        yield self.agent


class _FakeTaskManager:
    def start_cleanup_loop(self) -> None:
        return None

    async def register_task(self, **kwargs) -> None:
        return None

    async def get_task_status(self, task_id):
        return {"status": "pending"}

    async def start_task(self, task_id, generator_factory) -> None:
        async for _ in generator_factory():
            pass

    def subscribe(self, task_id, from_seq):
        async def _empty_stream():
            if False:
                yield None

        return _empty_stream()


async def _no_profile_trigger(user_id: str) -> None:
    """测试中禁用与上下文无关的后台画像计数。"""
    return None


@pytest.mark.asyncio
async def test_http_nonstream_injects_saved_assistant_context(monkeypatch) -> None:
    """非流式 HTTP 必须把已保存选择传给 Agent，且不注入 speaker 偏好。"""
    memory_id = _seed_context()
    agent = _CapturingAgent()
    monkeypatch.setattr(chat_route, "get_registry", lambda: _FakeRegistry(agent))
    monkeypatch.setattr(chat_route, "prewarm_agent_memory", AsyncMock())
    monkeypatch.setattr(chat_route, "_trigger_profile_n_turn_fallback", _no_profile_trigger)

    db = TestingSessionLocal()
    try:
        result = await chat_route.chat.__wrapped__(
            request=_request(),
            message=ChatMessage(
                message="测试非流式上下文",
                session_id="session-chat-context",
                mode="chat",
            ),
            db=db,
            current_user=SimpleNamespace(id="1", username="owner"),
        )
    finally:
        db.close()

    assert result.status == "completed"
    assert agent.process_context["workspace_id"] == "workspace-chat"
    assert agent.process_context["selected_memory_ids"] == [memory_id]
    assert "speaker_id" not in agent.process_context


@pytest.mark.asyncio
async def test_http_sse_injects_saved_assistant_context(monkeypatch) -> None:
    """SSE 必须在启动后台流任务前使用与非流式相同的上下文装配。"""
    memory_id = _seed_context()
    agent = _CapturingAgent()
    monkeypatch.setattr(chat_route, "get_registry", lambda: _FakeRegistry(agent))
    monkeypatch.setattr(chat_route, "get_chat_task_manager", lambda: _FakeTaskManager())
    monkeypatch.setattr(chat_route, "prewarm_agent_memory", AsyncMock())
    monkeypatch.setattr(chat_route, "_trigger_profile_n_turn_fallback", _no_profile_trigger)
    monkeypatch.setattr(chat_route, "build_sse_response", AsyncMock(return_value=Response()))

    db = TestingSessionLocal()
    try:
        response = await chat_route.chat.__wrapped__(
            request=_request(),
            message=ChatMessage(
                message="测试 SSE 上下文",
                session_id="session-chat-context",
                mode="stream",
            ),
            db=db,
            current_user=SimpleNamespace(id="1", username="owner"),
        )
    finally:
        db.close()

    assert response.headers["X-Chat-Task-Id"]
    assert agent.stream_context["workspace_id"] == "workspace-chat"
    assert agent.stream_context["selected_memory_ids"] == [memory_id]
    assert "speaker_id" not in agent.stream_context


@pytest.mark.asyncio
async def test_websocket_endpoint_loads_saved_assistant_context(monkeypatch) -> None:
    """WebSocket 入口必须通过同一服务装配会话上下文后再进入协议循环。"""
    memory_id = _seed_context()
    captured = {}

    class _FakeWebSocket:
        headers = {"origin": "http://localhost", "x-request-id": "ws-context"}
        cookies = {}

        async def close(self, code, reason):
            raise AssertionError(f"WebSocket 不应关闭: {code} {reason}")

    async def fake_handle_websocket_session(**kwargs):
        captured.update(kwargs)

    db = TestingSessionLocal()
    monkeypatch.setattr(chat_route, "validate_ws_origin", lambda origin: True)
    monkeypatch.setattr(
        chat_route,
        "_ws_resolve_user_from_token",
        lambda token: SimpleNamespace(id="1", username="owner"),
    )
    monkeypatch.setattr(chat_route, "_ws_load_session_owner_id", lambda session_id: "1")
    monkeypatch.setattr(chat_route, "SessionLocal", lambda: db)
    monkeypatch.setattr(chat_route, "prewarm_agent_memory", AsyncMock())
    monkeypatch.setattr(chat_route.ws_manager, "connect", AsyncMock())
    monkeypatch.setattr(chat_route.ws_manager, "disconnect", lambda *args, **kwargs: None)
    monkeypatch.setattr(chat_route, "AIAgent", lambda **kwargs: SimpleNamespace())
    monkeypatch.setattr(chat_route, "handle_websocket_session", fake_handle_websocket_session)

    await chat_route.websocket_endpoint(
        websocket=_FakeWebSocket(),
        session_id="session-chat-context",
        token="valid-token",
    )

    assert captured["agent_context"] == {
        "role_id": None,
        "workspace_id": "workspace-chat",
        "selected_memory_ids": [memory_id],
    }


def test_legacy_session_agent_context_keeps_default_behavior() -> None:
    """旧会话没有助手上下文时仍使用默认工作区和自动记忆选择标记。"""
    from api.services.assistant_context_service import build_conversation_agent_context

    conversation = Conversation(
        session_id="legacy-session",
        user_id="1",
        title="旧会话",
        summary="",
        last_message_preview="",
        message_count=0,
        conversation_metadata={},
    )
    db = TestingSessionLocal()
    try:
        context = build_conversation_agent_context(
            db,
            conversation,
            "1",
            {"request_id": "legacy"},
        )
    finally:
        db.close()

    assert context["workspace_id"] == "default"
    assert context["selected_memory_ids"] == []
    assert context["role_id"] is None


@pytest.mark.asyncio
async def test_websocket_protocol_uses_server_context_without_client_override(monkeypatch) -> None:
    """协议循环必须使用服务端上下文，忽略客户端伪造的助手字段。"""
    captured = {}

    class _ProtocolWebSocket:
        def __init__(self) -> None:
            self.received = False
            self.sent = []

        async def receive_text(self) -> str:
            if self.received:
                raise WebSocketDisconnect()
            self.received = True
            return json.dumps(
                {
                    "type": "message",
                    "content": "测试协议上下文",
                    "workspace_id": "client-forged",
                    "selected_memory_ids": [999],
                }
            )

        async def send_json(self, payload) -> None:
            self.sent.append(payload)

    class _ProtocolManager:
        def mark_activity(self, websocket) -> None:
            return None

        async def broadcast_to_session(self, *args, **kwargs) -> None:
            return None

        def disconnect(self, *args, **kwargs) -> None:
            return None

    class _ProtocolAgent:
        async def process(self, message, context):
            captured.update(context)
            return {"status": "completed", "response": "ok"}

    monkeypatch.setattr(chat_protocol, "ws_manager", _ProtocolManager())
    await chat_protocol.handle_websocket_session(
        websocket=_ProtocolWebSocket(),
        session_id="session-chat-context",
        user_id="1",
        username="owner",
        client_version="test",
        connection_request_id="ws-context",
        agent=_ProtocolAgent(),
        agent_context={
            "role_id": "role-server",
            "workspace_id": "workspace-server",
            "selected_memory_ids": [42],
        },
    )

    assert captured["role_id"] == "role-server"
    assert captured["workspace_id"] == "workspace-server"
    assert captured["selected_memory_ids"] == [42]
