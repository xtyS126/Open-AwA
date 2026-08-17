"""工作台预览租约 WebSocket 代理安全边界测试。"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from api.dependencies import get_current_user
from api.routes import preview_proxy
from api.routes.preview_proxy import router as preview_router
from workbench.errors import ProjectDisabled, ProjectRootChanged
from workbench.listener_registry import PreviewListenerVerifierRegistry
from workbench.preview_lease import PreviewLeaseRegistry, PreviewSessionKind
from workbench.runtime_registry import WorkbenchRuntimeRegistry


class _DummyUser:
    """仅提供预览路由需要的用户字段。"""

    def __init__(self, user_id: str = "user-a", role: str = "user") -> None:
        self.id = user_id
        self.role = role


class _FakeUpstream:
    """提供可观察双向帧转发和关闭行为的上游连接替身。"""

    def __init__(self, *initial_messages: str | bytes, subprotocol: str | None = None) -> None:
        self.subprotocol = subprotocol
        self.sent: list[str | bytes] = []
        self.closed = False
        self._messages: asyncio.Queue[str | bytes] = asyncio.Queue()
        for message in initial_messages:
            self._messages.put_nowait(message)

    def __aiter__(self):
        return self

    async def __anext__(self) -> str | bytes:
        return await self._messages.get()

    async def send(self, message: str | bytes) -> None:
        self.sent.append(message)
        await self._messages.put(message)

    async def close(self) -> None:
        self.closed = True


class _FakeConnectContext:
    """模拟 websockets.connect 的异步上下文管理器。"""

    def __init__(self, upstream: _FakeUpstream, error: Exception | None = None) -> None:
        self.upstream = upstream
        self.error = error

    async def __aenter__(self) -> _FakeUpstream:
        if self.error is not None:
            raise self.error
        return self.upstream

    async def __aexit__(self, exc_type, exc, traceback) -> bool:
        await self.upstream.close()
        return False


def _create_client(
    *,
    current_user: _DummyUser | None = None,
    listener_state: dict[str, bool] | None = None,
    now=None,
) -> tuple[TestClient, PreviewLeaseRegistry, MagicMock]:
    """构造使用独立租约和 listener 注册表的测试客户端。"""
    app = FastAPI()
    app.include_router(preview_router)
    user = current_user or _DummyUser()
    app.dependency_overrides[get_current_user] = lambda: user
    lease_registry = PreviewLeaseRegistry(
        runtime_registry=WorkbenchRuntimeRegistry(),
        now=now,
    )
    state = listener_state or {"valid": True}
    listener_verifier = MagicMock(side_effect=lambda *_args: state["valid"])
    verifier_registry = PreviewListenerVerifierRegistry()
    verifier_registry.register(PreviewSessionKind.TERMINAL, listener_verifier)
    app.dependency_overrides[preview_proxy.get_preview_path_policy] = lambda: object()
    app.dependency_overrides[preview_proxy.get_preview_lease_registry] = lambda: lease_registry
    app.dependency_overrides[
        preview_proxy.get_preview_listener_registry
    ] = lambda: verifier_registry
    return TestClient(app), lease_registry, listener_verifier


def _create_lease(client: TestClient) -> dict:
    """通过公开 HTTP 端点签发测试租约。"""
    response = client.post(
        "/api/workbench/projects/project-a/previews",
        json={
            "session_kind": "terminal",
            "session_id": "terminal-a",
            "port": 5173,
        },
    )
    assert response.status_code == 201
    return response.json()


def _ws_path(preview_id: str, suffix: str = "hmr") -> str:
    return f"/api/workbench/projects/project-a/previews/{preview_id}/{suffix}"


def test_websocket_proxy_consumes_lease_and_relays_text_and_binary_frames() -> None:
    """握手必须重验租约，且文本与二进制帧均保持原类型双向转发。"""
    upstream = _FakeUpstream("server-text", b"server-bytes", subprotocol="vite-hmr")
    connect_factory = MagicMock(return_value=_FakeConnectContext(upstream))
    resolver = MagicMock()

    with patch.object(preview_proxy, "_resolve_project_sync", resolver):
        with patch.object(
            preview_proxy,
            "resolve_ws_user_from_token",
            return_value=_DummyUser(),
        ) as authenticate:
            with patch.object(preview_proxy.websockets, "connect", connect_factory):
                client, lease_registry, listener_verifier = _create_client()
                with client:
                    lease = _create_lease(client)
                    original_expiry = asyncio.run(
                        lease_registry.get_owned(
                            preview_id=lease["preview_id"],
                            user_id="user-a",
                            project_id="project-a",
                        )
                    ).expires_at
                    with client.websocket_connect(
                        f"{_ws_path(lease['preview_id'])}?client=1",
                        subprotocols=["bearer.browser-secret", "vite-hmr"],
                        headers={
                            "Origin": "http://localhost:5173",
                            "Authorization": "Bearer header-secret",
                            "Cookie": "access_token=cookie-secret; private=value",
                            "X-CSRF-Token": "csrf-secret",
                            "Proxy-Authorization": "Basic proxy-secret",
                            "Accept-Language": "zh-CN",
                        },
                    ) as websocket:
                        assert websocket.accepted_subprotocol == "vite-hmr"
                        assert websocket.receive_text() == "server-text"
                        assert websocket.receive_bytes() == b"server-bytes"
                        websocket.send_text("client-text")
                        assert websocket.receive_text() == "client-text"
                        websocket.send_bytes(b"client-bytes")
                        assert websocket.receive_bytes() == b"client-bytes"

                    unchanged_expiry = asyncio.run(
                        lease_registry.get_owned(
                            preview_id=lease["preview_id"],
                            user_id="user-a",
                            project_id="project-a",
                        )
                    ).expires_at

    authenticate.assert_called_once_with("browser-secret")
    assert resolver.call_count == 2
    assert listener_verifier.call_count == 2
    assert upstream.sent == ["client-text", b"client-bytes"]
    assert upstream.closed is True
    assert unchanged_expiry == original_expiry
    connect_factory.assert_called_once()
    target_url = connect_factory.call_args.args[0]
    connect_options = connect_factory.call_args.kwargs
    assert target_url == "ws://127.0.0.1:5173/hmr?client=1"
    assert connect_options["subprotocols"] == ["vite-hmr"]
    assert connect_options["extra_headers"] == {"accept-language": "zh-CN"}
    serialized_options = repr(connect_factory.call_args).lower()
    assert "browser-secret" not in serialized_options
    assert "cookie-secret" not in serialized_options
    assert "header-secret" not in serialized_options
    assert "csrf-secret" not in serialized_options
    assert "proxy-secret" not in serialized_options


def test_websocket_proxy_accepts_valid_cookie_without_query_or_header_token() -> None:
    """纯 Cookie 登录允许连接，但 Cookie 本身绝不透传给上游。"""
    upstream = _FakeUpstream()
    connect_factory = MagicMock(return_value=_FakeConnectContext(upstream))

    with patch.object(preview_proxy, "_resolve_project_sync"):
        with patch.object(
            preview_proxy,
            "resolve_ws_user_from_token",
            return_value=_DummyUser(),
        ) as authenticate:
            with patch.object(preview_proxy.websockets, "connect", connect_factory):
                client, _, _ = _create_client()
                client.cookies.set("access_token", "cookie-secret")
                with client:
                    lease = _create_lease(client)
                    with client.websocket_connect(
                        _ws_path(lease["preview_id"]),
                        headers={"Origin": "http://localhost:5173"},
                    ) as websocket:
                        websocket.close()

    authenticate.assert_called_once_with("cookie-secret")
    assert "cookie" not in connect_factory.call_args.kwargs["extra_headers"]


def test_websocket_proxy_rejects_query_token_before_authentication() -> None:
    """URL query 中出现认证 token 时必须在认证和租约消费前拒绝。"""
    connect_factory = MagicMock()
    authenticate = MagicMock(return_value=_DummyUser())

    with patch.object(preview_proxy, "_resolve_project_sync"):
        with patch.object(preview_proxy, "resolve_ws_user_from_token", authenticate):
            with patch.object(preview_proxy.websockets, "connect", connect_factory):
                client, _, listener_verifier = _create_client()
                with client:
                    lease = _create_lease(client)
                    with pytest.raises(WebSocketDisconnect) as rejected:
                        with client.websocket_connect(
                            f"{_ws_path(lease['preview_id'])}?token=query-secret",
                            subprotocols=["bearer.browser-secret"],
                            headers={"Origin": "http://localhost:5173"},
                        ):
                            pass

    assert rejected.value.code == 4400
    assert "query-secret" not in rejected.value.reason
    authenticate.assert_not_called()
    assert listener_verifier.call_count == 1
    connect_factory.assert_not_called()


def test_websocket_proxy_cross_scope_and_invalid_listener_fail_closed() -> None:
    """跨用户、跨项目或 listener 失效均不能触达上游。"""
    listener_state = {"valid": True}
    connect_factory = MagicMock()

    with patch.object(preview_proxy, "_resolve_project_sync"):
        with patch.object(preview_proxy.websockets, "connect", connect_factory):
            client, _, _ = _create_client(listener_state=listener_state)
            with client:
                lease = _create_lease(client)
                with patch.object(
                    preview_proxy,
                    "resolve_ws_user_from_token",
                    return_value=_DummyUser("user-b"),
                ):
                    with pytest.raises(WebSocketDisconnect) as cross_user:
                        with client.websocket_connect(
                            _ws_path(lease["preview_id"]),
                            subprotocols=["bearer.other-user"],
                            headers={"Origin": "http://localhost:5173"},
                        ):
                            pass

                with patch.object(
                    preview_proxy,
                    "resolve_ws_user_from_token",
                    return_value=_DummyUser(),
                ):
                    with pytest.raises(WebSocketDisconnect) as cross_project:
                        with client.websocket_connect(
                            _ws_path(lease["preview_id"]).replace(
                                "/projects/project-a/",
                                "/projects/project-b/",
                            ),
                            subprotocols=["bearer.owner"],
                            headers={"Origin": "http://localhost:5173"},
                        ):
                            pass

                listener_state["valid"] = False
                with patch.object(
                    preview_proxy,
                    "resolve_ws_user_from_token",
                    return_value=_DummyUser(),
                ):
                    with pytest.raises(WebSocketDisconnect) as invalid_listener:
                        with client.websocket_connect(
                            _ws_path(lease["preview_id"]),
                            subprotocols=["bearer.owner"],
                            headers={"Origin": "http://localhost:5173"},
                        ):
                            pass

    assert cross_user.value.code == 4404
    assert cross_project.value.code == 4404
    assert invalid_listener.value.code == 4404
    assert (
        cross_user.value.reason
        == cross_project.value.reason
        == invalid_listener.value.reason
        == "Preview unavailable"
    )
    connect_factory.assert_not_called()


@pytest.mark.parametrize("project_error", [ProjectDisabled(), ProjectRootChanged()])
def test_websocket_proxy_expired_or_project_drift_fails_before_upstream(
    project_error: Exception,
) -> None:
    """过期租约和项目禁用都必须在上游连接前失败。"""
    clock = [datetime(2026, 8, 15, tzinfo=timezone.utc)]
    connect_factory = MagicMock()

    with patch.object(preview_proxy, "_resolve_project_sync") as resolver:
        with patch.object(
            preview_proxy,
            "resolve_ws_user_from_token",
            return_value=_DummyUser(),
        ):
            with patch.object(preview_proxy.websockets, "connect", connect_factory):
                client, _, _ = _create_client(now=lambda: clock[0])
                with client:
                    expired_lease = _create_lease(client)
                    clock[0] += timedelta(minutes=16)
                    with pytest.raises(WebSocketDisconnect) as expired:
                        with client.websocket_connect(
                            _ws_path(expired_lease["preview_id"]),
                            subprotocols=["bearer.owner"],
                            headers={"Origin": "http://localhost:5173"},
                        ):
                            pass

                    clock[0] -= timedelta(minutes=16)
                    active_lease = _create_lease(client)
                    resolver.side_effect = project_error
                    with pytest.raises(WebSocketDisconnect) as drifted:
                        with client.websocket_connect(
                            _ws_path(active_lease["preview_id"]),
                            subprotocols=["bearer.owner"],
                            headers={"Origin": "http://localhost:5173"},
                        ):
                            pass

    assert expired.value.code == 4404
    assert drifted.value.code == 4404
    assert expired.value.reason == drifted.value.reason == "Preview unavailable"
    connect_factory.assert_not_called()


def test_websocket_proxy_ignores_authorization_header_as_authentication() -> None:
    """Authorization 头不能替代安全 Cookie 或 bearer 子协议完成鉴权。"""
    connect_factory = MagicMock()
    authenticate = MagicMock(return_value=_DummyUser())

    with patch.object(preview_proxy, "_resolve_project_sync"):
        with patch.object(preview_proxy, "resolve_ws_user_from_token", authenticate):
            with patch.object(preview_proxy.websockets, "connect", connect_factory):
                client, _, listener_verifier = _create_client()
                with client:
                    lease = _create_lease(client)
                    with pytest.raises(WebSocketDisconnect) as rejected:
                        with client.websocket_connect(
                            _ws_path(lease["preview_id"]),
                            headers={
                                "Origin": "http://localhost:5173",
                                "Authorization": "Bearer header-secret",
                            },
                        ):
                            pass

    assert rejected.value.code == 4401
    authenticate.assert_not_called()
    assert listener_verifier.call_count == 1
    connect_factory.assert_not_called()


def test_websocket_upstream_failure_is_sanitized_and_closes_connection() -> None:
    """上游握手失败只返回稳定错误，不泄露端口、URL 或绝对路径。"""
    upstream = _FakeUpstream()
    connect_factory = MagicMock(
        return_value=_FakeConnectContext(
            upstream,
            RuntimeError("ws://127.0.0.1:5173/D:/private/project"),
        )
    )

    with patch.object(preview_proxy, "_resolve_project_sync"):
        with patch.object(
            preview_proxy,
            "resolve_ws_user_from_token",
            return_value=_DummyUser(),
        ):
            with patch.object(preview_proxy.websockets, "connect", connect_factory):
                client, _, _ = _create_client()
                with client:
                    lease = _create_lease(client)
                    with pytest.raises(WebSocketDisconnect) as rejected:
                        with client.websocket_connect(
                            _ws_path(lease["preview_id"]),
                            subprotocols=["bearer.owner"],
                            headers={"Origin": "http://localhost:5173"},
                        ):
                            pass

    assert rejected.value.code == 1013
    assert rejected.value.reason == "Preview unavailable"
    serialized_error = f"{rejected.value.code} {rejected.value.reason}".lower()
    assert "127.0.0.1" not in serialized_error
    assert "5173" not in serialized_error
    assert "private" not in serialized_error
