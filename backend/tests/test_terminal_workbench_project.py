"""Terminal 与工作台项目绑定的回归测试。"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import api.routes.terminal as terminal_route
from api.dependencies import get_current_user, get_db
from workbench.errors import ProjectDisabled, ProjectNotFound, ProjectRootChanged, ProjectRootInvalid
from workbench.listener_registry import listener_verifier_registry
from workbench.preview_lease import PreviewSessionKind
from workbench.runtime_registry import RuntimeResourceType


app = FastAPI()
app.include_router(terminal_route.router, prefix="/api")


class FakeRegistry:
    """记录资源注册与释放，不启动任何真实运行时。"""

    def __init__(self) -> None:
        self.acquired: list[tuple[str, str, RuntimeResourceType, str]] = []
        self.released: list[tuple[str, str, RuntimeResourceType, str]] = []
        self.event_loop_thread_ids: list[int] = []

    async def acquire(
        self,
        *,
        user_id: str,
        project_id: str,
        resource_type: RuntimeResourceType,
        resource_id: str,
        verify_project,
        close_callback=None,
    ) -> None:
        self.event_loop_thread_ids.append(threading.get_ident())
        result = verify_project()
        if asyncio.iscoroutine(result):
            await result
        self.acquired.append((user_id, project_id, resource_type, resource_id))

    async def release(
        self,
        *,
        user_id: str,
        project_id: str,
        resource_type: RuntimeResourceType,
        resource_id: str,
    ) -> None:
        self.event_loop_thread_ids.append(threading.get_ident())
        self.released.append((user_id, project_id, resource_type, resource_id))


class FakePreviewLeaseRegistry:
    """记录按 Terminal 会话撤销预览租约的调用。"""

    def __init__(self) -> None:
        self.revoked: list[tuple[str, str, PreviewSessionKind, str]] = []

    async def revoke_session(
        self,
        *,
        user_id: str,
        project_id: str,
        session_kind: PreviewSessionKind,
        session_id: str,
    ) -> None:
        self.revoked.append((user_id, project_id, session_kind, session_id))


class FakeDbSession:
    """记录 SessionLocal 的创建与关闭线程。"""

    instances: list["FakeDbSession"] = []

    def __init__(self) -> None:
        self.created_thread_id = threading.get_ident()
        self.closed_thread_id: int | None = None
        self.instances.append(self)

    def __enter__(self) -> "FakeDbSession":
        return self

    def __exit__(self, *args: object) -> bool:
        self.closed_thread_id = threading.get_ident()
        return False


class FakeProjectService:
    """用临时目录模拟服务端权威项目解析。"""

    root = Path(".").resolve()
    calls: list[tuple[str, str, str]] = []
    failure: Exception | None = None
    thread_records: list[tuple[int, object]] = []

    def __init__(self, db: object, path_policy: object) -> None:
        self.db = db
        self.path_policy = path_policy

    def resolve_project_root(
        self,
        *,
        user_id: str,
        user_role: str,
        project_id: str,
    ) -> Path:
        self.thread_records.append((threading.get_ident(), self.db))
        self.calls.append((user_id, user_role, project_id))
        if self.failure is not None:
            raise self.failure
        return self.root


class FakeTerminalSession:
    """避免普通终端测试启动真实子进程。"""

    def __init__(
        self,
        session_id: str,
        cwd: str,
        owner_user_id: str | None = None,
        project_id: str | None = None,
        runtime_registry: Any = None,
    ) -> None:
        self.session_id = session_id
        self.cwd = cwd
        self.owner_user_id = owner_user_id
        self.project_id = project_id
        self.runtime_registry = runtime_registry
        self.active = True
        self.process: Any = None
        self.close_calls = 0
        self.execute_calls: list[tuple[str, int]] = []

    async def execute(self, command: str, timeout: int) -> dict[str, Any]:
        self.execute_calls.append((command, timeout))
        return {"ok": True, "stdout": command, "stderr": "", "exit_code": 0}

    async def close(self) -> None:
        self.close_calls += 1
        self.active = False


class FakePTYTerminalSession(FakeTerminalSession):
    """模拟 PTY 启动成功或失败，并复用资源释放记录。"""

    fail_start = False
    start_error = "start failed"

    def __init__(self, *, command=None, cols=80, rows=24, **kwargs) -> None:
        super().__init__(**kwargs)
        self.command = command or ["fake-shell"]
        self.cols = cols
        self.rows = rows
        self._subscribers: list[object] = []
        self.pty = SimpleNamespace(is_alive=lambda: self.active)

    async def start(self) -> None:
        if self.fail_start:
            raise RuntimeError(self.start_error)

    async def close(self) -> None:
        self.close_calls += 1
        self.active = False

    def get_scrollback(self, limit: int = 100) -> list[str]:
        return []

    def get_snapshot(self) -> dict[str, Any]:
        return {"grid": [[]], "cols": self.cols, "rows": self.rows}

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        if queue in self._subscribers:
            self._subscribers.remove(queue)

    async def write_input(self, data: str) -> dict[str, Any]:
        return {"ok": True}



@pytest.fixture
def terminal_client(monkeypatch):
    """覆盖认证、数据库、项目解析与运行时注册表。"""
    user = SimpleNamespace(id="user-1", role="user", username="tester")
    registry = FakeRegistry()
    FakeProjectService.calls = []
    FakeProjectService.failure = None
    FakeProjectService.thread_records = []
    FakeDbSession.instances = []
    terminal_route._terminal_sessions.clear()
    terminal_route._pty_sessions.clear()
    monkeypatch.setattr(terminal_route, "WorkbenchProjectService", FakeProjectService, raising=False)
    monkeypatch.setattr(terminal_route, "TerminalSession", FakeTerminalSession)
    monkeypatch.setattr(terminal_route, "validate_ws_origin", lambda origin: True)
    monkeypatch.setattr(terminal_route, "resolve_ws_user_from_token", lambda token: user)
    monkeypatch.setattr(terminal_route, "SessionLocal", FakeDbSession)

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: object()
    path_dependency = getattr(terminal_route, "get_terminal_workbench_path_policy", None)
    registry_dependency = getattr(terminal_route, "get_terminal_runtime_registry", None)
    if path_dependency is not None:
        app.dependency_overrides[path_dependency] = lambda: object()
    if registry_dependency is not None:
        app.dependency_overrides[registry_dependency] = lambda: registry
    try:
        with TestClient(app) as client:
            yield client, registry
    finally:
        app.dependency_overrides.clear()
        terminal_route._terminal_sessions.clear()
        terminal_route._pty_sessions.clear()


def test_normal_session_uses_project_id_and_releases_registry(terminal_client) -> None:
    """普通会话只消费项目 ID，并在关闭时释放运行时占用。"""
    client, registry = terminal_client

    created = client.post("/api/terminal/sessions", params={"project_id": "project-1"})

    assert created.status_code == 200
    payload = created.json()
    assert payload["ok"] is True
    assert payload["project_id"] == "project-1"
    assert "cwd" not in payload
    session_id = payload["session_id"]
    session = terminal_route._terminal_sessions[session_id]
    assert session.owner_user_id == "user-1"
    assert session.project_id == "project-1"
    assert registry.acquired == [
        ("user-1", "project-1", RuntimeResourceType.TERMINAL_SESSION, session_id)
    ]

    executed = client.post(
        f"/api/terminal/sessions/{session_id}/execute",
        json={"command": "echo hello", "timeout": 5},
    )
    assert executed.status_code == 200
    assert len(FakeProjectService.calls) >= 2

    closed = client.delete(f"/api/terminal/sessions/{session_id}")
    assert closed.status_code == 200
    assert registry.released[-1] == (
        "user-1",
        "project-1",
        RuntimeResourceType.TERMINAL_SESSION,
        session_id,
    )


def test_terminal_create_rejects_client_cwd(terminal_client) -> None:
    """旧 cwd 查询参数不得继续成为权威工作目录。"""
    client, _registry = terminal_client

    response = client.post(
        "/api/terminal/sessions",
        params={"project_id": "project-1", "cwd": "C:/untrusted"},
    )

    assert response.status_code == 422
    assert "legacy_project_path_not_supported" in str(response.json())


@pytest.mark.parametrize("field_name", ["cwd", "project_dir", "projectCwd", "projectDir"])
@pytest.mark.parametrize("endpoint_kind", ["normal", "pty"])
@pytest.mark.parametrize("location", ["query", "json"])
def test_terminal_create_rejects_all_legacy_project_path_fields_consistently(
    terminal_client,
    field_name: str,
    endpoint_kind: str,
    location: str,
) -> None:
    """两类会话在查询串或 JSON 中出现任一旧路径字段时都返回同一退役错误。"""
    client, _registry = terminal_client
    if endpoint_kind == "normal":
        path = "/api/terminal/sessions"
        params = {"project_id": "project-1"}
        payload: dict[str, Any] = {}
    else:
        path = "/api/terminal/sessions/pty"
        params = {}
        payload = {"project_id": "project-1", "command": ["fake-shell"]}

    if location == "query":
        params[field_name] = "C:/untrusted"
    else:
        payload[field_name] = None

    response = client.post(path, params=params, json=payload)

    assert response.status_code == 422
    assert response.headers["Sunset"] == "2026-09-01"
    assert response.json() == {
        "detail": {
            "code": "legacy_project_path_not_supported",
            "message": "不再支持客户端提供项目路径，请改用 project_id",
        }
    }


@pytest.mark.parametrize(
    "path",
    [
        "/api/terminal/ws/query-only?token=fake-token",
        "/api/terminal/ws/pty/query-only?token=fake-token",
    ],
)
def test_terminal_websocket_query_token_never_authenticates(terminal_client, path: str) -> None:
    """Terminal WebSocket 只允许 bearer 子协议鉴权，URL query token 必须被忽略。"""
    client, _registry = terminal_client

    with client.websocket_connect(path) as websocket:
        assert websocket.receive_json() == {"type": "error", "message": "缺少认证 token"}
        with pytest.raises(WebSocketDisconnect) as exc_info:
            websocket.receive_json()

        assert exc_info.value.code == 4001


def test_pty_create_requires_project_id_and_rejects_cwd(terminal_client) -> None:
    """PTY 创建载荷只允许项目 ID，不接受 cwd 字段。"""
    client, _registry = terminal_client

    missing = client.post(
        "/api/terminal/sessions/pty",
        json={"cols": 80, "rows": 24, "command": ["fake-shell"]},
    )
    legacy = client.post(
        "/api/terminal/sessions/pty",
        json={
            "project_id": "project-1",
            "cwd": "C:/untrusted",
            "cols": 80,
            "rows": 24,
            "command": ["fake-shell"],
        },
    )

    assert missing.status_code == 409
    assert "workbench_project_required" in str(missing.json())
    assert legacy.status_code == 422


def test_bound_project_is_revalidated_before_session_access(terminal_client) -> None:
    """项目禁用后不得继续执行已绑定会话。"""
    client, _registry = terminal_client
    created = client.post("/api/terminal/sessions", params={"project_id": "project-1"})
    session_id = created.json()["session_id"]
    FakeProjectService.failure = ProjectDisabled()

    response = client.post(
        f"/api/terminal/sessions/{session_id}/execute",
        json={"command": "echo hello"},
    )

    assert response.status_code == 409
    assert "workbench_project_disabled" in str(response.json())


def test_http_project_resolution_uses_worker_local_database_sessions(terminal_client) -> None:
    """HTTP 项目解析必须在工作线程内创建、使用并关闭独立数据库 Session。"""
    client, registry = terminal_client

    response = client.post("/api/terminal/sessions", params={"project_id": "project-1"})

    assert response.status_code == 200
    assert FakeDbSession.instances
    assert FakeProjectService.thread_records
    assert registry.event_loop_thread_ids
    for resolver_thread_id, db in FakeProjectService.thread_records:
        assert isinstance(db, FakeDbSession)
        assert db.created_thread_id == resolver_thread_id
        assert db.closed_thread_id == resolver_thread_id
        assert resolver_thread_id not in registry.event_loop_thread_ids


def test_websocket_project_resolution_uses_worker_local_database_sessions(terminal_client) -> None:
    """WS 项目重验同样必须在线程池内创建并关闭短生命周期数据库 Session。"""
    client, registry = terminal_client
    session = FakeTerminalSession(
        session_id="thread-ws",
        cwd=str(FakeProjectService.root),
        owner_user_id="user-1",
        project_id="project-1",
        runtime_registry=registry,
    )
    terminal_route._terminal_sessions[session.session_id] = session

    with client.websocket_connect(
        "/api/terminal/ws/thread-ws",
        subprotocols=["bearer.fake-token"],
    ) as websocket:
        websocket.send_json({"command": "echo hello"})
        assert websocket.receive_json()["type"] == "command"
        assert websocket.receive_json()["type"] == "output"

    assert FakeDbSession.instances
    assert FakeProjectService.thread_records
    resolver_thread_ids = {record[0] for record in FakeProjectService.thread_records}
    for resolver_thread_id, db in FakeProjectService.thread_records:
        assert isinstance(db, FakeDbSession)
        assert db.created_thread_id == resolver_thread_id
        assert db.closed_thread_id == resolver_thread_id
    assert resolver_thread_ids.isdisjoint(registry.event_loop_thread_ids)


@pytest.mark.parametrize(
    ("failure", "status_code", "error_code"),
    [
        (ProjectDisabled(), 409, "workbench_project_disabled"),
        (ProjectRootChanged(), 409, "workbench_project_root_changed"),
        (ProjectRootInvalid(), 422, "workbench_project_root_invalid"),
    ],
)
@pytest.mark.parametrize("session_kind", ["normal", "pty"])
def test_close_discards_bound_runtime_while_preserving_project_error(
    terminal_client,
    failure: Exception,
    status_code: int,
    error_code: str,
    session_kind: str,
) -> None:
    """所有权通过后，关闭时项目失效仍必须销毁运行时并原样返回项目错误。"""
    client, registry = terminal_client
    session_id = f"close-{session_kind}"
    session_type = FakeTerminalSession if session_kind == "normal" else FakePTYTerminalSession
    session = session_type(
        session_id=session_id,
        cwd=str(FakeProjectService.root),
        owner_user_id="user-1",
        project_id="project-1",
        runtime_registry=registry,
    )
    sessions = (
        terminal_route._terminal_sessions
        if session_kind == "normal"
        else terminal_route._pty_sessions
    )
    sessions[session_id] = session
    FakeProjectService.failure = failure
    path = (
        f"/api/terminal/sessions/{session_id}"
        if session_kind == "normal"
        else f"/api/terminal/sessions/pty/{session_id}"
    )

    response = client.delete(path)

    assert response.status_code == status_code
    assert response.json()["detail"]["code"] == error_code
    assert session.close_calls == 1
    assert session.active is False
    assert session_id not in sessions
    assert registry.released == [
        (
            "user-1",
            "project-1",
            RuntimeResourceType.TERMINAL_SESSION
            if session_kind == "normal"
            else RuntimeResourceType.PTY_SESSION,
            session_id,
        )
    ]


@pytest.mark.parametrize(
    ("failure", "error_code"),
    [
        (ProjectDisabled(), "workbench_project_disabled"),
        (ProjectRootChanged(), "workbench_project_root_changed"),
        (ProjectRootInvalid(), "workbench_project_root_invalid"),
    ],
)
@pytest.mark.parametrize("session_kind", ["normal", "pty"])
def test_websocket_project_failure_discards_bound_runtime_and_returns_original_error(
    terminal_client,
    failure: Exception,
    error_code: str,
    session_kind: str,
) -> None:
    """WS 初次重验失败时必须返回领域错误并销毁已通过所有权校验的会话。"""
    client, registry = terminal_client
    session_id = f"ws-{session_kind}"
    session_type = FakeTerminalSession if session_kind == "normal" else FakePTYTerminalSession
    session = session_type(
        session_id=session_id,
        cwd=str(FakeProjectService.root),
        owner_user_id="user-1",
        project_id="project-1",
        runtime_registry=registry,
    )
    sessions = (
        terminal_route._terminal_sessions
        if session_kind == "normal"
        else terminal_route._pty_sessions
    )
    sessions[session_id] = session
    FakeProjectService.failure = failure
    path = (
        f"/api/terminal/ws/{session_id}"
        if session_kind == "normal"
        else f"/api/terminal/ws/pty/{session_id}"
    )

    with client.websocket_connect(path, subprotocols=["bearer.fake-token"]) as websocket:
        error = websocket.receive_json()
        assert error["type"] == "error"
        assert error["code"] == error_code
        with pytest.raises(WebSocketDisconnect):
            websocket.receive_json()

    assert session.close_calls == 1
    assert session.active is False
    assert session_id not in sessions
    assert registry.released == [
        (
            "user-1",
            "project-1",
            RuntimeResourceType.TERMINAL_SESSION
            if session_kind == "normal"
            else RuntimeResourceType.PTY_SESSION,
            session_id,
        )
    ]


@pytest.mark.parametrize(
    ("failure", "error_code"),
    [
        (ProjectDisabled(), "workbench_project_disabled"),
        (ProjectRootChanged(), "workbench_project_root_changed"),
        (ProjectRootInvalid(), "workbench_project_root_invalid"),
    ],
)
@pytest.mark.parametrize("session_kind", ["normal", "pty"])
def test_websocket_runtime_revalidation_failure_discards_bound_session(
    terminal_client,
    failure: Exception,
    error_code: str,
    session_kind: str,
) -> None:
    """WS 已连接后的每次消费重验失败也必须关闭、移除并释放会话。"""
    client, registry = terminal_client
    session_id = f"ws-runtime-{session_kind}"
    session_type = FakeTerminalSession if session_kind == "normal" else FakePTYTerminalSession
    session = session_type(
        session_id=session_id,
        cwd=str(FakeProjectService.root),
        owner_user_id="user-1",
        project_id="project-1",
        runtime_registry=registry,
    )
    sessions = (
        terminal_route._terminal_sessions
        if session_kind == "normal"
        else terminal_route._pty_sessions
    )
    sessions[session_id] = session
    path = (
        f"/api/terminal/ws/{session_id}"
        if session_kind == "normal"
        else f"/api/terminal/ws/pty/{session_id}"
    )

    with client.websocket_connect(path, subprotocols=["bearer.fake-token"]) as websocket:
        if session_kind == "pty":
            for expected_type in ("shell_info", "scrollback", "snapshot"):
                assert websocket.receive_json()["type"] == expected_type
        FakeProjectService.failure = failure
        websocket.send_json(
            {"command": "echo hello"}
            if session_kind == "normal"
            else {"type": "input", "data": "echo hello\n"}
        )
        error = websocket.receive_json()
        assert error["type"] == "error"
        assert error["code"] == error_code
        with pytest.raises(WebSocketDisconnect):
            websocket.receive_json()

    assert session.close_calls == 1
    assert session.active is False
    assert session_id not in sessions
    assert registry.released == [
        (
            "user-1",
            "project-1",
            RuntimeResourceType.TERMINAL_SESSION
            if session_kind == "normal"
            else RuntimeResourceType.PTY_SESSION,
            session_id,
        )
    ]


@pytest.mark.parametrize(
    ("session_kind", "method", "path_template", "json_body"),
    [
        ("normal", "post", "/api/terminal/sessions/{session_id}/execute", {"command": "echo"}),
        ("normal", "delete", "/api/terminal/sessions/{session_id}", None),
        ("pty", "delete", "/api/terminal/sessions/pty/{session_id}", None),
        ("pty", "get", "/api/terminal/sessions/pty/{session_id}/snapshot", None),
    ],
)
def test_cross_user_http_access_cannot_resolve_or_destroy_session(
    terminal_client,
    monkeypatch,
    session_kind: str,
    method: str,
    path_template: str,
    json_body: dict[str, Any] | None,
) -> None:
    """跨用户 HTTP 访问在项目解析前即拒绝，且不能借关闭接口销毁他人进程。"""
    client, registry = terminal_client
    lease_registry = FakePreviewLeaseRegistry()
    monkeypatch.setattr(terminal_route, "preview_lease_registry", lease_registry, raising=False)
    session_id = f"other-{session_kind}"
    session_type = FakeTerminalSession if session_kind == "normal" else FakePTYTerminalSession
    session = session_type(
        session_id=session_id,
        cwd=str(FakeProjectService.root),
        owner_user_id="user-2",
        project_id="project-2",
        runtime_registry=registry,
    )
    sessions = (
        terminal_route._terminal_sessions
        if session_kind == "normal"
        else terminal_route._pty_sessions
    )
    sessions[session_id] = session

    response = client.request(
        method,
        path_template.format(session_id=session_id),
        json=json_body,
    )

    assert response.status_code == 403
    assert FakeProjectService.calls == []
    assert session.active is True
    assert session.close_calls == 0
    assert session_id in sessions
    assert registry.released == []
    assert lease_registry.revoked == []


@pytest.mark.parametrize("session_kind", ["normal", "pty"])
def test_cross_user_websocket_cannot_resolve_or_destroy_session(
    terminal_client,
    session_kind: str,
) -> None:
    """跨用户 WS 访问只关闭攻击者连接，不能关闭或释放被猜中的会话。"""
    client, registry = terminal_client
    session_id = f"other-ws-{session_kind}"
    session_type = FakeTerminalSession if session_kind == "normal" else FakePTYTerminalSession
    session = session_type(
        session_id=session_id,
        cwd=str(FakeProjectService.root),
        owner_user_id="user-2",
        project_id="project-2",
        runtime_registry=registry,
    )
    sessions = (
        terminal_route._terminal_sessions
        if session_kind == "normal"
        else terminal_route._pty_sessions
    )
    sessions[session_id] = session
    path = (
        f"/api/terminal/ws/{session_id}"
        if session_kind == "normal"
        else f"/api/terminal/ws/pty/{session_id}"
    )

    with client.websocket_connect(path, subprotocols=["bearer.fake-token"]) as websocket:
        assert websocket.receive_json() == {"type": "error", "message": "无权访问该会话"}
        with pytest.raises(WebSocketDisconnect) as exc_info:
            websocket.receive_json()

    assert exc_info.value.code == 4003
    assert FakeProjectService.calls == []
    assert session.active is True
    assert session.close_calls == 0
    assert session_id in sessions
    assert registry.released == []


def test_cross_project_session_is_hidden_before_command_execution(terminal_client) -> None:
    """绑定到当前用户无权项目的会话必须按 not found 隐藏，且不得执行命令。"""
    client, registry = terminal_client
    session = FakeTerminalSession(
        session_id="other-project",
        cwd=str(FakeProjectService.root),
        owner_user_id="user-1",
        project_id="project-2",
        runtime_registry=registry,
    )
    terminal_route._terminal_sessions[session.session_id] = session
    FakeProjectService.failure = ProjectNotFound()

    response = client.post(
        "/api/terminal/sessions/other-project/execute",
        json={"command": "echo forbidden"},
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "workbench_project_not_found"
    assert FakeProjectService.calls == [("user-1", "user", "project-2")]
    assert session.execute_calls == []


def test_normal_http_output_projection_redacts_bound_root_and_passive_absolute_paths(
    terminal_client,
) -> None:
    """普通 HTTP 命令结果不得通过 stdout/stderr/error 回显绑定根或被动外部路径。"""
    client, registry = terminal_client
    root_text = str(FakeProjectService.root)
    outside_path = "C:\\outside\\private\\secret.txt"
    session = FakeTerminalSession(
        session_id="unsafe-http-output",
        cwd=root_text,
        owner_user_id="user-1",
        project_id="project-1",
        runtime_registry=registry,
    )

    async def _unsafe_execute(command: str, timeout: int) -> dict[str, Any]:
        return {
            "ok": False,
            "stdout": f"cwd={root_text}",
            "stderr": f"failed under {root_text}\\src",
            "error": f"cannot open {outside_path} from {root_text}",
            "exit_code": 1,
        }

    session.execute = _unsafe_execute
    terminal_route._terminal_sessions[session.session_id] = session

    response = client.post(
        "/api/terminal/sessions/unsafe-http-output/execute",
        json={"command": f"echo {root_text}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert root_text not in payload["stdout"]
    assert root_text not in payload["stderr"]
    assert root_text not in payload["error"]
    assert outside_path not in payload["error"]


def test_normal_websocket_projection_redacts_command_stdout_and_stderr(terminal_client) -> None:
    """普通 WS 的 command/output 事件不得回显会话绑定根。"""
    client, registry = terminal_client
    root_text = str(FakeProjectService.root)
    session = FakeTerminalSession(
        session_id="unsafe-ws-output",
        cwd=root_text,
        owner_user_id="user-1",
        project_id="project-1",
        runtime_registry=registry,
    )

    async def _unsafe_execute(command: str, timeout: int) -> dict[str, Any]:
        return {
            "ok": True,
            "stdout": f"stdout {root_text}",
            "stderr": f"stderr {root_text}\\src",
            "exit_code": 0,
        }

    session.execute = _unsafe_execute
    terminal_route._terminal_sessions[session.session_id] = session

    with client.websocket_connect(
        "/api/terminal/ws/unsafe-ws-output",
        subprotocols=["bearer.fake-token"],
    ) as websocket:
        websocket.send_json({"command": f"type {root_text}\\README.md"})
        command_event = websocket.receive_json()
        output_event = websocket.receive_json()

    assert root_text not in command_event["command"]
    assert root_text not in output_event["stdout"]
    assert root_text not in output_event["stderr"]


def test_terminal_responses_never_expose_server_root_or_cwd(terminal_client, monkeypatch) -> None:
    """创建与列表响应只投影项目 ID 和安全运行时状态，不返回服务端根。"""
    client, _registry = terminal_client
    monkeypatch.setattr(terminal_route, "PTYTerminalSession", FakePTYTerminalSession)
    root_text = str(FakeProjectService.root)

    normal = client.post("/api/terminal/sessions", params={"project_id": "project-1"})
    pty = client.post(
        "/api/terminal/sessions/pty",
        json={
            "project_id": "project-1",
            "command": [str(FakeProjectService.root / "bin" / "fake-shell")],
        },
    )
    normal_list = client.get("/api/terminal/sessions")
    pty_list = client.get("/api/terminal/sessions/pty")

    def _all_strings(value: object) -> list[str]:
        if isinstance(value, str):
            return [value]
        if isinstance(value, dict):
            return [item for child in value.values() for item in _all_strings(child)]
        if isinstance(value, list):
            return [item for child in value for item in _all_strings(child)]
        return []

    for response in (normal, pty, normal_list, pty_list):
        assert response.status_code == 200
        response_text = response.text
        assert all(root_text not in value for value in _all_strings(response.json()))
        assert '"cwd"' not in response_text
        assert '"registered_root"' not in response_text
        assert '"canonical_root"' not in response_text
        assert '"resolved_root"' not in response_text


def test_pty_start_failure_releases_registry(terminal_client, monkeypatch) -> None:
    """PTY 启动失败时必须释放已登记的运行时资源。"""
    client, registry = terminal_client
    FakePTYTerminalSession.fail_start = True
    monkeypatch.setattr(terminal_route, "PTYTerminalSession", FakePTYTerminalSession)

    response = client.post(
        "/api/terminal/sessions/pty",
        json={"project_id": "project-1", "command": ["fake-shell"]},
    )

    assert response.status_code == 200
    assert response.json()["ok"] is False
    assert registry.acquired
    acquired = registry.acquired[-1]
    assert registry.released[-1] == acquired
    FakePTYTerminalSession.fail_start = False


def test_pty_start_failure_response_does_not_leak_project_root(terminal_client, monkeypatch) -> None:
    """PTY 启动异常可记录在服务端，但普通错误响应不得回显项目根。"""
    client, _registry = terminal_client
    FakePTYTerminalSession.fail_start = True
    FakePTYTerminalSession.start_error = f"spawn failed under {FakeProjectService.root}"
    monkeypatch.setattr(terminal_route, "PTYTerminalSession", FakePTYTerminalSession)

    try:
        response = client.post(
            "/api/terminal/sessions/pty",
            json={"project_id": "project-1", "command": ["fake-shell"]},
        )
    finally:
        FakePTYTerminalSession.fail_start = False
        FakePTYTerminalSession.start_error = "start failed"

    assert response.status_code == 200
    assert response.json() == {"ok": False, "error": "PTY 会话启动失败"}
    assert str(FakeProjectService.root) not in response.text


@pytest.mark.parametrize("session_kind", ["normal", "pty"])
def test_successful_close_revokes_terminal_preview_leases(
    terminal_client,
    monkeypatch,
    session_kind: str,
) -> None:
    """普通和 PTY 会话成功关闭时都必须撤销对应的预览租约。"""
    client, registry = terminal_client
    lease_registry = FakePreviewLeaseRegistry()
    monkeypatch.setattr(terminal_route, "preview_lease_registry", lease_registry, raising=False)
    session_type = FakeTerminalSession if session_kind == "normal" else FakePTYTerminalSession
    session = session_type(
        session_id=f"close-{session_kind}",
        cwd=str(FakeProjectService.root),
        owner_user_id="user-1",
        project_id="project-1",
        runtime_registry=registry,
    )
    sessions = (
        terminal_route._terminal_sessions
        if session_kind == "normal"
        else terminal_route._pty_sessions
    )
    sessions[session.session_id] = session
    path = (
        f"/api/terminal/sessions/{session.session_id}"
        if session_kind == "normal"
        else f"/api/terminal/sessions/pty/{session.session_id}"
    )

    response = client.delete(path)

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert lease_registry.revoked == [
        (
            "user-1",
            "project-1",
            PreviewSessionKind.TERMINAL,
            session.session_id,
        )
    ]


@pytest.mark.parametrize("session_kind", ["normal", "pty"])
def test_invalid_project_cleanup_revokes_terminal_preview_leases(
    terminal_client,
    monkeypatch,
    session_kind: str,
) -> None:
    """项目失效触发的会话销毁也必须撤销对应预览租约。"""
    client, registry = terminal_client
    lease_registry = FakePreviewLeaseRegistry()
    monkeypatch.setattr(terminal_route, "preview_lease_registry", lease_registry, raising=False)
    session_type = FakeTerminalSession if session_kind == "normal" else FakePTYTerminalSession
    session = session_type(
        session_id=f"invalid-{session_kind}",
        cwd=str(FakeProjectService.root),
        owner_user_id="user-1",
        project_id="project-1",
        runtime_registry=registry,
    )
    sessions = (
        terminal_route._terminal_sessions
        if session_kind == "normal"
        else terminal_route._pty_sessions
    )
    sessions[session.session_id] = session
    FakeProjectService.failure = ProjectDisabled()
    path = (
        f"/api/terminal/sessions/{session.session_id}"
        if session_kind == "normal"
        else f"/api/terminal/sessions/pty/{session.session_id}"
    )

    response = client.delete(path)

    assert response.status_code == 409
    assert session.session_id not in sessions
    assert lease_registry.revoked == [
        (
            "user-1",
            "project-1",
            PreviewSessionKind.TERMINAL,
            session.session_id,
        )
    ]


@pytest.mark.asyncio
async def test_lru_eviction_closes_and_releases_registry(monkeypatch) -> None:
    """全局 LRU 淘汰应关闭会话并释放 runtime 与预览租约。"""
    registry = FakeRegistry()
    lease_registry = FakePreviewLeaseRegistry()
    evicted = FakeTerminalSession(
        "evicted",
        str(Path(".").resolve()),
        owner_user_id="user-1",
        project_id="project-1",
        runtime_registry=registry,
    )
    replacement = FakeTerminalSession(
        "replacement",
        str(Path(".").resolve()),
        owner_user_id="user-1",
        project_id="project-1",
        runtime_registry=registry,
    )
    sessions = terminal_route.OrderedDict({"evicted": evicted})
    monkeypatch.setattr(terminal_route, "_MAX_TOTAL_SESSIONS", 1)
    monkeypatch.setattr(terminal_route, "preview_lease_registry", lease_registry, raising=False)

    terminal_route._add_session(sessions, "replacement", replacement, "user-1", 10)
    await asyncio.sleep(0)

    assert evicted.active is False
    assert registry.released[-1] == (
        "user-1",
        "project-1",
        RuntimeResourceType.TERMINAL_SESSION,
        "evicted",
    )
    assert lease_registry.revoked == [
        ("user-1", "project-1", PreviewSessionKind.TERMINAL, "evicted")
    ]


@pytest.mark.asyncio
async def test_idle_pty_eviction_revokes_terminal_preview_leases(monkeypatch) -> None:
    """PTY 单用户配额淘汰路径也必须撤销会话预览租约。"""
    registry = FakeRegistry()
    lease_registry = FakePreviewLeaseRegistry()
    session = FakePTYTerminalSession(
        session_id="idle-pty",
        cwd=str(Path(".").resolve()),
        owner_user_id="user-1",
        project_id="project-1",
        runtime_registry=registry,
    )
    terminal_route._pty_sessions[session.session_id] = session
    monkeypatch.setattr(terminal_route, "preview_lease_registry", lease_registry, raising=False)

    evicted = terminal_route._evict_idle_user_pty("user-1")
    await asyncio.sleep(0)

    assert evicted is True
    assert session.active is False
    assert lease_registry.revoked == [
        ("user-1", "project-1", PreviewSessionKind.TERMINAL, session.session_id)
    ]


@pytest.mark.asyncio
async def test_registered_terminal_listener_provider_accepts_root_and_descendant(
    monkeypatch,
) -> None:
    """注册的 Terminal provider 应接受根进程及其子进程的真实监听端口。"""
    root_process = SimpleNamespace(
        pid=4100,
        children=lambda recursive: [SimpleNamespace(pid=4101)],
    )
    connections = [
        SimpleNamespace(laddr=SimpleNamespace(port=5173), pid=4100, status="LISTEN"),
        SimpleNamespace(laddr=SimpleNamespace(port=5174), pid=4101, status="LISTEN"),
    ]
    fake_psutil = SimpleNamespace(
        CONN_LISTEN="LISTEN",
        Process=lambda pid: root_process,
        net_connections=lambda **kwargs: connections,
    )
    import workbench.listener_ownership as listener_ownership

    monkeypatch.setattr(listener_ownership, "psutil", fake_psutil)
    session = FakeTerminalSession(
        "listener-1",
        str(Path(".").resolve()),
        owner_user_id="user-1",
        project_id="project-1",
    )
    session.process = SimpleNamespace(pid=4100, returncode=None)
    terminal_route._terminal_sessions[session.session_id] = session
    try:
        root_owned = await listener_verifier_registry.verify(
            "user-1",
            "project-1",
            PreviewSessionKind.TERMINAL,
            session.session_id,
            5173,
        )
        child_owned = await listener_verifier_registry.verify(
            "user-1",
            "project-1",
            PreviewSessionKind.TERMINAL,
            session.session_id,
            5174,
        )
    finally:
        terminal_route._terminal_sessions.clear()

    assert root_owned is True
    assert child_owned is True


@pytest.mark.asyncio
async def test_terminal_listener_provider_accepts_pty_root_pid(monkeypatch) -> None:
    """Terminal provider 必须从 PTY 会话提取底层真实根进程 PID。"""
    ownership_calls: list[tuple[int, int]] = []
    monkeypatch.setattr(
        terminal_route,
        "process_tree_owns_listener",
        lambda *, root_pid, port: ownership_calls.append((root_pid, port)) or True,
        raising=False,
    )
    session = FakePTYTerminalSession(
        session_id="pty-listener",
        cwd=str(Path(".").resolve()),
        owner_user_id="user-1",
        project_id="project-1",
    )
    session.pty.get_root_pid = lambda: 4300
    terminal_route._pty_sessions[session.session_id] = session
    try:
        result = await terminal_route.verify_terminal_listener(
            "user-1",
            "project-1",
            PreviewSessionKind.TERMINAL,
            session.session_id,
            5173,
        )
    finally:
        terminal_route._pty_sessions.clear()

    assert result is True
    assert ownership_calls == [(4300, 5173)]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("user_id", "project_id", "session_kind"),
    [
        ("user-2", "project-1", PreviewSessionKind.TERMINAL),
        ("user-1", "project-2", PreviewSessionKind.TERMINAL),
        ("user-1", "project-1", PreviewSessionKind.ACP),
    ],
)
async def test_terminal_listener_provider_rejects_identity_or_kind_mismatch(
    monkeypatch,
    user_id: str,
    project_id: str,
    session_kind: PreviewSessionKind,
) -> None:
    """provider 必须同时匹配 owner、project 与 terminal 会话类型。"""
    ownership_calls: list[tuple[int, int]] = []
    monkeypatch.setattr(
        terminal_route,
        "process_tree_owns_listener",
        lambda *, root_pid, port: ownership_calls.append((root_pid, port)) or True,
        raising=False,
    )
    session = FakeTerminalSession(
        "listener-mismatch",
        str(Path(".").resolve()),
        owner_user_id="user-1",
        project_id="project-1",
    )
    session.process = SimpleNamespace(pid=4100)
    terminal_route._terminal_sessions[session.session_id] = session
    try:
        result = await terminal_route.verify_terminal_listener(
            user_id,
            project_id,
            session_kind,
            session.session_id,
            5173,
        )
    finally:
        terminal_route._terminal_sessions.clear()

    assert result is False
    assert ownership_calls == []


@pytest.mark.asyncio
async def test_terminal_listener_provider_ignores_declared_ports_and_fails_closed(
    monkeypatch,
) -> None:
    """客户端声明的 listener_ports 不能替代进程树监听证据。"""
    session = FakeTerminalSession(
        "listener-declared-only",
        str(Path(".").resolve()),
        owner_user_id="user-1",
        project_id="project-1",
    )
    session.listener_ports = {5173}
    session.process = SimpleNamespace(pid=4100)
    terminal_route._terminal_sessions[session.session_id] = session
    monkeypatch.setattr(
        terminal_route,
        "process_tree_owns_listener",
        lambda **kwargs: False,
        raising=False,
    )
    try:
        result = await terminal_route.verify_terminal_listener(
            "user-1",
            "project-1",
            PreviewSessionKind.TERMINAL,
            session.session_id,
            5173,
        )
    finally:
        terminal_route._terminal_sessions.clear()

    assert result is False


@pytest.mark.asyncio
@pytest.mark.parametrize("session_kind", ["normal", "pty"])
async def test_terminal_listener_provider_rejects_ended_root_process(
    monkeypatch,
    session_kind: str,
) -> None:
    """已退出或失活的根进程 PID 不能因 PID 复用而获得 listener 所有权。"""
    ownership_calls: list[tuple[int, int]] = []
    monkeypatch.setattr(
        terminal_route,
        "process_tree_owns_listener",
        lambda *, root_pid, port: ownership_calls.append((root_pid, port)) or True,
    )
    if session_kind == "normal":
        session = FakeTerminalSession(
            "ended-normal",
            str(Path(".").resolve()),
            owner_user_id="user-1",
            project_id="project-1",
        )
        session.process = SimpleNamespace(pid=4100, returncode=0)
        sessions = terminal_route._terminal_sessions
    else:
        session = FakePTYTerminalSession(
            session_id="ended-pty",
            cwd=str(Path(".").resolve()),
            owner_user_id="user-1",
            project_id="project-1",
        )
        session.pty.get_root_pid = lambda: 4200
        session.pty.is_alive = lambda: False
        sessions = terminal_route._pty_sessions
    sessions[session.session_id] = session
    try:
        result = await terminal_route.verify_terminal_listener(
            "user-1",
            "project-1",
            PreviewSessionKind.TERMINAL,
            session.session_id,
            5173,
        )
    finally:
        sessions.clear()

    assert result is False
    assert ownership_calls == []
