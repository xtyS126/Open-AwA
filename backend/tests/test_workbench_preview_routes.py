"""工作台预览租约 HTTP 路由测试。"""

from __future__ import annotations

import asyncio
import gzip
import threading
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.dependencies import get_current_user
from api.routes import preview_proxy
from api.routes.preview_proxy import router as preview_router
from workbench.listener_registry import PreviewListenerVerifierRegistry
from workbench.preview_lease import PreviewLeaseRegistry, PreviewSessionKind
from workbench.runtime_registry import WorkbenchRuntimeRegistry


class _DummyUser:
    """仅提供预览路由需要的用户字段。"""

    def __init__(self, user_id: str = "user-a", role: str = "user") -> None:
        self.id = user_id
        self.role = role


def _create_client(*, listener_verifier=None, user: _DummyUser | None = None) -> TestClient:
    app = FastAPI()
    app.include_router(preview_router)
    current_user = user or _DummyUser()
    app.dependency_overrides[get_current_user] = lambda: current_user
    lease_registry = PreviewLeaseRegistry(runtime_registry=WorkbenchRuntimeRegistry())
    verifier_registry = PreviewListenerVerifierRegistry()
    verifier_registry.register(
        PreviewSessionKind.TERMINAL,
        listener_verifier or (lambda *_args: True),
    )
    app.dependency_overrides[preview_proxy.get_preview_path_policy] = lambda: object()
    app.dependency_overrides[preview_proxy.get_preview_lease_registry] = lambda: lease_registry
    app.dependency_overrides[
        preview_proxy.get_preview_listener_registry
    ] = lambda: verifier_registry
    return TestClient(app)


def _create_lease(client: TestClient) -> dict:
    """通过公开端点创建一个终端预览租约。"""
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


def test_create_preview_lease_returns_public_projection() -> None:
    """创建租约只返回浏览器可消费的公开字段。"""
    with patch.object(preview_proxy, "_resolve_project_sync"):
        with _create_client() as client:
            response = client.post(
                "/api/workbench/projects/project-a/previews",
                json={
                    "session_kind": "terminal",
                    "session_id": "terminal-a",
                    "port": 5173,
                },
            )

    assert response.status_code == 201
    assert set(response.json()) == {
        "preview_id",
        "project_id",
        "session_kind",
        "session_id",
        "port",
        "expires_at",
    }
    assert response.json()["project_id"] == "project-a"


def test_renew_preview_lease_returns_same_public_identity() -> None:
    """续租保留租约身份并返回新的公开投影。"""
    with patch.object(preview_proxy, "_resolve_project_sync"):
        with _create_client() as client:
            created = _create_lease(client)
            response = client.post(
                f"/api/workbench/projects/project-a/previews/{created['preview_id']}/renew"
            )

    assert response.status_code == 200
    assert response.json()["preview_id"] == created["preview_id"]
    assert set(response.json()) == set(created)


def test_delete_preview_lease_revokes_it() -> None:
    """删除租约后再次续租必须返回不存在。"""
    with patch.object(preview_proxy, "_resolve_project_sync"):
        with _create_client() as client:
            created = _create_lease(client)
            deleted = client.delete(
                f"/api/workbench/projects/project-a/previews/{created['preview_id']}"
            )
            renewed = client.post(
                f"/api/workbench/projects/project-a/previews/{created['preview_id']}/renew"
            )

    assert deleted.status_code == 204
    assert renewed.status_code == 404
    assert renewed.json()["detail"]["code"] == "workbench_preview_lease_not_found"


class _FakeStreamResponse:
    """提供可观察 raw 迭代行为的 httpx 流响应替身。"""

    def __init__(self, *, content: bytes, headers: dict[str, str]) -> None:
        self.status_code = 200
        self.headers = headers
        self.content = content
        self.raw_iterated = False

    async def aiter_raw(self):
        self.raw_iterated = True
        yield self.content


class _FakeStreamContext:
    """模拟 httpx 的流上下文。"""

    def __init__(self, response: _FakeStreamResponse) -> None:
        self.response = response

    async def __aenter__(self) -> _FakeStreamResponse:
        return self.response

    async def __aexit__(self, exc_type, exc, traceback) -> bool:
        return False


class _FakeHttpClient:
    """记录代理发往上游的方法、URL 和请求头。"""

    def __init__(self, response: _FakeStreamResponse) -> None:
        self.response = response
        self.calls: list[tuple[str, str, dict[str, str]]] = []

    def stream(self, method: str, url: str, *, headers: dict[str, str]):
        self.calls.append((method, url, headers))
        return _FakeStreamContext(self.response)

    async def aclose(self) -> None:
        return None


def test_proxy_consumes_lease_and_filters_credentials_and_response_headers() -> None:
    """每次代理都重验租约，并在双向边界移除凭据与 Cookie。"""
    compressed = gzip.compress(b"preview-body")
    upstream = _FakeStreamResponse(
        content=compressed,
        headers={
            "content-type": "text/plain",
            "content-encoding": "gzip",
            "content-length": str(len(compressed)),
            "set-cookie": "secret=upstream",
            "connection": "x-hop",
            "x-hop": "connection-scoped-secret",
            "x-preview": "ok",
        },
    )
    fake_client = _FakeHttpClient(upstream)
    listener_verifier = MagicMock(return_value=True)
    resolver = MagicMock()

    with patch.object(preview_proxy, "_resolve_project_sync", resolver):
        with patch.object(
            preview_proxy.httpx,
            "AsyncClient",
            return_value=fake_client,
        ):
            with _create_client(listener_verifier=listener_verifier) as client:
                lease = _create_lease(client)
                response = client.get(
                    f"/api/workbench/projects/project-a/previews/{lease['preview_id']}/assets/app.js",
                    params={"v": "1"},
                    headers={
                        "Authorization": "Bearer browser-secret",
                        "Cookie": "session=browser-secret",
                        "X-CSRF-Token": "csrf-secret",
                        "Range": "bytes=0-20",
                        "Accept": "text/javascript",
                    },
                )

    assert response.status_code == 200
    assert response.content == b"preview-body"
    assert response.headers["content-encoding"] == "gzip"
    assert response.headers["content-length"] == str(len(compressed))
    assert response.headers["x-preview"] == "ok"
    assert "set-cookie" not in response.headers
    assert "connection" not in response.headers
    assert "x-hop" not in response.headers
    assert upstream.raw_iterated is True
    assert resolver.call_count == 2
    assert listener_verifier.call_count == 2
    method, target_url, headers = fake_client.calls[0]
    assert method == "GET"
    assert target_url == "http://127.0.0.1:5173/assets/app.js?v=1"
    assert headers["range"] == "bytes=0-20"
    assert headers["accept"] == "text/javascript"
    assert "authorization" not in headers
    assert "cookie" not in headers
    assert "x-csrf-token" not in headers
    assert "host" not in headers


def test_proxy_head_uses_head_upstream() -> None:
    """HEAD 预览必须使用 HEAD 请求上游且不向浏览器发送正文。"""
    upstream = _FakeStreamResponse(content=b"ignored", headers={"content-length": "7"})
    fake_client = _FakeHttpClient(upstream)

    with patch.object(preview_proxy, "_resolve_project_sync"):
        with patch.object(
            preview_proxy.httpx,
            "AsyncClient",
            return_value=fake_client,
        ):
            with _create_client() as client:
                lease = _create_lease(client)
                response = client.head(
                    f"/api/workbench/projects/project-a/previews/{lease['preview_id']}/"
                )

    assert response.status_code == 200
    assert response.content == b""
    assert fake_client.calls[0][0] == "HEAD"


def test_proxy_rewrites_local_redirect_and_drops_refresh_header() -> None:
    """本地重定向必须继续经过租约路径，不能暴露或绕过裸端口。"""
    upstream = _FakeStreamResponse(
        content=b"",
        headers={
            "location": "http://127.0.0.1:5173/login?next=1",
            "refresh": "0; url=http://127.0.0.1:5173/login",
        },
    )
    upstream.status_code = 302
    fake_client = _FakeHttpClient(upstream)

    with patch.object(preview_proxy, "_resolve_project_sync"):
        with patch.object(
            preview_proxy.httpx,
            "AsyncClient",
            return_value=fake_client,
        ):
            with _create_client() as client:
                lease = _create_lease(client)
                response = client.get(
                    f"/api/workbench/projects/project-a/previews/{lease['preview_id']}/app",
                    follow_redirects=False,
                )

    assert response.status_code == 302
    assert response.headers["location"] == (
        f"/api/workbench/projects/project-a/previews/{lease['preview_id']}/login?next=1"
    )
    assert "refresh" not in response.headers
    assert "127.0.0.1" not in response.headers["location"]
    assert "5173" not in response.headers["location"]


def test_legacy_raw_port_route_is_tombstone_and_never_contacts_upstream() -> None:
    """旧裸端口路由只返回迁移提示，不能再发起上游请求。"""
    client_factory = MagicMock()

    with patch.object(preview_proxy.httpx, "AsyncClient", client_factory):
        with _create_client() as client:
            response = client.get("/api/preview/5173/private/path")

    assert response.status_code == 410
    assert response.json() == {
        "detail": {
            "code": "preview_proxy_retired",
            "message": "裸端口预览代理已停用，请使用工作台预览租约",
        }
    }
    assert response.headers["deprecation"] == "true"
    client_factory.assert_not_called()


def test_unregistered_listener_verifier_fails_closed() -> None:
    """未接入会话 provider 时不能签发租约。"""
    app = FastAPI()
    app.include_router(preview_router)
    app.dependency_overrides[get_current_user] = lambda: _DummyUser()
    app.dependency_overrides[preview_proxy.get_preview_path_policy] = lambda: object()
    app.dependency_overrides[preview_proxy.get_preview_lease_registry] = lambda: (
        PreviewLeaseRegistry(runtime_registry=WorkbenchRuntimeRegistry())
    )
    app.dependency_overrides[preview_proxy.get_preview_listener_registry] = lambda: (
        PreviewListenerVerifierRegistry()
    )

    with patch.object(preview_proxy, "_resolve_project_sync"):
        with TestClient(app) as client:
            response = client.post(
                "/api/workbench/projects/project-a/previews",
                json={
                    "session_kind": "terminal",
                    "session_id": "terminal-a",
                    "port": 5173,
                },
            )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "workbench_preview_listener_forbidden"


def test_cross_user_proxy_attempt_is_not_found_and_does_not_contact_upstream() -> None:
    """租约不能被另一个用户枚举或消费。"""
    user = _DummyUser()
    client_factory = MagicMock()

    with patch.object(preview_proxy, "_resolve_project_sync"):
        with patch.object(preview_proxy.httpx, "AsyncClient", client_factory):
            with _create_client(user=user) as client:
                lease = _create_lease(client)
                user.id = "user-b"
                response = client.get(
                    f"/api/workbench/projects/project-a/previews/{lease['preview_id']}/"
                )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "workbench_preview_lease_not_found"
    client_factory.assert_not_called()


def test_create_rejects_extra_path_like_fields() -> None:
    """创建载荷不得夹带服务器路径或旧式项目目录字段。"""
    with _create_client() as client:
        response = client.post(
            "/api/workbench/projects/project-a/previews",
            json={
                "session_kind": "terminal",
                "session_id": "terminal-a",
                "port": 5173,
                "project_dir": "D:\\private\\project",
            },
        )

    assert response.status_code == 422


def test_create_rejects_boolean_port() -> None:
    """布尔值不能被整数强制转换后当作端口。"""
    with _create_client() as client:
        response = client.post(
            "/api/workbench/projects/project-a/previews",
            json={
                "session_kind": "terminal",
                "session_id": "terminal-a",
                "port": True,
            },
        )

    assert response.status_code == 422


def test_production_disabled_mode_fails_before_project_or_listener_checks() -> None:
    """生产禁用开关必须在任何项目和 listener 消费前拒绝。"""
    listener_verifier = MagicMock(return_value=True)
    resolver = MagicMock()

    with patch.object(preview_proxy, "_PREVIEW_ENABLED", False):
        with patch.object(preview_proxy, "_resolve_project_sync", resolver):
            with _create_client(listener_verifier=listener_verifier) as client:
                response = client.post(
                    "/api/workbench/projects/project-a/previews",
                    json={
                        "session_kind": "terminal",
                        "session_id": "terminal-a",
                        "port": 5173,
                    },
                )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "preview_proxy_disabled"
    resolver.assert_not_called()
    listener_verifier.assert_not_called()


class _FailingStreamContext:
    """模拟包含敏感绝对路径的上游连接失败。"""

    async def __aenter__(self):
        raise RuntimeError("D:\\private\\registered-project\\secret.txt")

    async def __aexit__(self, exc_type, exc, traceback) -> bool:
        return False


class _FailingHttpClient:
    """返回失败流并记录关闭。"""

    def __init__(self) -> None:
        self.closed = False

    def stream(self, method: str, url: str, *, headers: dict[str, str]):
        return _FailingStreamContext()

    async def aclose(self) -> None:
        self.closed = True


def test_proxy_error_response_does_not_expose_upstream_url_or_absolute_path() -> None:
    """上游错误只返回稳定错误码，不回显 URL、端口或服务端路径。"""
    fake_client = _FailingHttpClient()

    with patch.object(preview_proxy, "_resolve_project_sync"):
        with patch.object(
            preview_proxy.httpx,
            "AsyncClient",
            return_value=fake_client,
        ):
            with _create_client() as client:
                lease = _create_lease(client)
                response = client.get(
                    f"/api/workbench/projects/project-a/previews/{lease['preview_id']}/secret.txt"
                )

    serialized = response.text.lower()
    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "preview_upstream_unavailable"
    assert "private" not in serialized
    assert "registered-project" not in serialized
    assert "127.0.0.1" not in serialized
    assert "5173" not in serialized
    assert fake_client.closed is True


def test_proxy_client_construction_error_is_sanitized() -> None:
    """HTTP 客户端构造失败也必须返回稳定且脱敏的网关错误。"""
    with patch.object(preview_proxy, "_resolve_project_sync"):
        with patch.object(
            preview_proxy.httpx,
            "AsyncClient",
            side_effect=RuntimeError("D:\\private\\registered-project"),
        ):
            with _create_client() as client:
                lease = _create_lease(client)
                response = client.get(
                    f"/api/workbench/projects/project-a/previews/{lease['preview_id']}/"
                )

    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "preview_upstream_unavailable"
    assert "private" not in response.text.lower()


def test_listener_registry_unregister_and_verifier_exception_fail_closed() -> None:
    """注销、实例不匹配和 provider 异常都保持 fail-closed。"""
    registry = PreviewListenerVerifierRegistry()
    verifier = MagicMock(side_effect=RuntimeError("provider failed"))
    other_verifier = MagicMock(return_value=True)
    registry.register(PreviewSessionKind.TERMINAL, verifier)

    assert asyncio.run(
        registry.verify("user-a", "project-a", PreviewSessionKind.TERMINAL, "session-a", 5173)
    ) is False
    registry.unregister(PreviewSessionKind.TERMINAL, other_verifier)
    assert asyncio.run(
        registry.verify("user-a", "project-a", PreviewSessionKind.TERMINAL, "session-a", 5173)
    ) is False
    registry.unregister(PreviewSessionKind.TERMINAL, verifier)
    assert asyncio.run(
        registry.verify("user-a", "project-a", PreviewSessionKind.TERMINAL, "session-a", 5173)
    ) is False


def test_project_verifier_uses_worker_thread_and_worker_local_session() -> None:
    """项目重验必须在线程 worker 内创建并关闭独立数据库会话。"""
    caller_thread = threading.get_ident()
    worker_threads: list[int] = []
    path_policy = object()
    fake_db = object()
    fake_context = MagicMock()
    fake_context.__enter__.return_value = fake_db
    fake_service = MagicMock()

    def create_session():
        worker_threads.append(threading.get_ident())
        return fake_context

    with patch.object(preview_proxy, "SessionLocal", side_effect=create_session) as session_factory:
        with patch.object(
            preview_proxy,
            "WorkbenchProjectService",
            return_value=fake_service,
        ) as service_factory:
            asyncio.run(
                preview_proxy._project_verifier(
                    user_id="user-a",
                    user_role="user",
                    project_id="project-a",
                    path_policy=path_policy,
                )()
            )

    session_factory.assert_called_once_with()
    service_factory.assert_called_once_with(fake_db, path_policy)
    fake_service.resolve_project_root.assert_called_once_with(
        user_id="user-a",
        user_role="user",
        project_id="project-a",
    )
    fake_context.__exit__.assert_called_once()
    assert worker_threads and worker_threads[0] != caller_thread
