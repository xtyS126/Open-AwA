"""WebSocket 连接管理器的用户会话隔离回归测试。"""

import json

import pytest
from fastapi import WebSocketDisconnect

from api.services import chat_protocol
from api.services import ws_manager as ws_manager_module
from api.services.chat_protocol import handle_websocket_session
from api.services.ws_manager import WebSocketManager


class FakeWebSocket:
    """记录握手和发送内容的轻量 WebSocket 替身。"""

    def __init__(self) -> None:
        self.accepted = False
        self.messages = []

    async def accept(self, subprotocol=None) -> None:
        self.accepted = True

    async def send_text(self, payload: str) -> None:
        self.messages.append(json.loads(payload))


@pytest.mark.asyncio
async def test_same_session_id_is_isolated_by_user(monkeypatch) -> None:
    """两个用户使用同名 session_id 时不得互相收到广播。"""
    manager = WebSocketManager()
    monkeypatch.setattr(manager, "start_heartbeat", lambda: None)
    user_a_socket = FakeWebSocket()
    user_b_socket = FakeWebSocket()

    await manager.connect("shared", user_a_socket, user_id="user-a")
    await manager.connect("shared", user_b_socket, user_id="user-b")
    await manager.broadcast_to_session(
        "shared",
        {"type": "sync", "content": "仅用户 A 可见"},
        user_id="user-a",
    )

    assert user_a_socket.messages == [{"type": "sync", "content": "仅用户 A 可见"}]
    assert user_b_socket.messages == []
    assert manager.get_session_count("shared", user_id="user-a") == 1
    assert manager.get_session_count("shared", user_id="user-b") == 1


@pytest.mark.asyncio
async def test_unscoped_lookup_rejects_ambiguous_session_id(monkeypatch) -> None:
    """兼容调用缺少 user_id 且会话归属不唯一时应拒绝选择连接。"""
    manager = WebSocketManager()
    monkeypatch.setattr(manager, "start_heartbeat", lambda: None)
    await manager.connect("shared", FakeWebSocket(), user_id="user-a")
    await manager.connect("shared", FakeWebSocket(), user_id="user-b")

    assert manager.get_connection("shared") is None
    assert manager.get_connections("shared") == []


@pytest.mark.asyncio
async def test_disconnect_cleans_user_reverse_index(monkeypatch) -> None:
    """最后一个连接断开后应同步清理用户到会话的反向索引。"""
    manager = WebSocketManager()
    monkeypatch.setattr(manager, "start_heartbeat", lambda: None)
    websocket = FakeWebSocket()
    await manager.connect("session-1", websocket, user_id="user-a")

    manager.disconnect("session-1", websocket, user_id="user-a")

    assert manager.get_connection("session-1", user_id="user-a") is None
    assert "user-a" not in manager._user_sessions


@pytest.mark.asyncio
async def test_sending_heartbeat_does_not_refresh_client_activity(monkeypatch) -> None:
    """服务端发送 ping 不能冒充客户端活动，否则僵尸连接永不超时。"""
    manager = WebSocketManager()
    monkeypatch.setattr(manager, "start_heartbeat", lambda: None)
    websocket = FakeWebSocket()
    await manager.connect("session-1", websocket, user_id="user-a")
    manager._last_activity[id(websocket)] = 10.0

    await manager._send_heartbeats()

    assert manager._last_activity[id(websocket)] == 10.0
    assert websocket.messages[-1] == {"type": "ping"}


@pytest.mark.asyncio
async def test_pong_activity_prevents_zombie_cleanup(monkeypatch) -> None:
    """客户端 pong 等入站活动应刷新时间并避免健康连接被清理。"""
    manager = WebSocketManager()
    monkeypatch.setattr(manager, "start_heartbeat", lambda: None)
    websocket = FakeWebSocket()
    await manager.connect("session-1", websocket, user_id="user-a")

    monkeypatch.setattr(ws_manager_module.time, "monotonic", lambda: 100.0)
    manager.mark_activity(websocket)
    monkeypatch.setattr(ws_manager_module.time, "monotonic", lambda: 150.0)
    manager._cleanup_zombies()

    assert manager.get_connection("session-1", user_id="user-a") is websocket


@pytest.mark.asyncio
async def test_missing_pong_is_cleaned_as_zombie(monkeypatch) -> None:
    """超过心跳超时仍无客户端入站活动时必须移除连接和反向索引。"""
    manager = WebSocketManager()
    monkeypatch.setattr(manager, "start_heartbeat", lambda: None)
    websocket = FakeWebSocket()
    await manager.connect("session-1", websocket, user_id="user-a")
    manager._last_activity[id(websocket)] = 10.0

    monkeypatch.setattr(ws_manager_module.time, "monotonic", lambda: 101.0)
    manager._cleanup_zombies()

    assert manager.get_connection("session-1", user_id="user-a") is None
    assert "user-a" not in manager._user_sessions


@pytest.mark.asyncio
async def test_protocol_pong_marks_client_activity(monkeypatch) -> None:
    """协议处理器收到 pong 后应刷新该连接活动时间并停止业务分发。"""

    class PongWebSocket:
        """先返回 pong，再模拟客户端断开。"""

        def __init__(self) -> None:
            self.received = False

        async def receive_text(self) -> str:
            if not self.received:
                self.received = True
                return '{"type":"pong"}'
            raise WebSocketDisconnect()

    class RecordingManager:
        """记录协议层活动刷新和断开调用。"""

        def __init__(self) -> None:
            self.marked = []
            self.disconnected = []

        def mark_activity(self, websocket) -> None:
            self.marked.append(websocket)

        def disconnect(self, session_id, websocket=None, user_id=None) -> None:
            self.disconnected.append((session_id, websocket, user_id))

    websocket = PongWebSocket()
    manager = RecordingManager()
    monkeypatch.setattr(chat_protocol, "ws_manager", manager)

    await handle_websocket_session(
        websocket=websocket,
        session_id="session-1",
        user_id="user-a",
        username="tester",
        client_version="1.0.0",
        connection_request_id="request-1",
        agent=object(),
    )

    assert manager.marked == [websocket]
    assert manager.disconnected
    assert all(call == ("session-1", websocket, "user-a") for call in manager.disconnected)
