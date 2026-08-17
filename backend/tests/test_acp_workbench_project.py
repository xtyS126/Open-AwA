"""ACP API 使用工作台项目 ID 的隔离与资源生命周期契约测试。"""

from __future__ import annotations

import asyncio
import inspect
import json
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.dependencies import get_current_user
from api.routes import acp
from db.models import get_db
from workbench import listener_ownership
from workbench.errors import ProjectDisabled, ProjectNotFound, ProjectRootChanged
from workbench.listener_registry import listener_verifier_registry
from workbench.preview_lease import PreviewSessionKind


class _User:
    """提供 ACP 路由需要的最小认证用户。"""

    def __init__(self, user_id: str = "user-a") -> None:
        self.id = user_id
        self.username = user_id
        self.role = "user"


class _FakeConversation:
    """提供权限恢复流程需要的 ACP 会话字段。"""

    acp_session_id = "acp-session-1"
    user_id = "user-a"
    project_id = "project-a"
    resolved_root = ""
    process = SimpleNamespace(pid=4312)


class _FakeACPService:
    """隔离真实 ACP SDK 和子进程的服务替身。"""

    def __init__(self) -> None:
        self.run_turn = AsyncMock(return_value={"status": "completed"})
        self.resume_permission = AsyncMock(return_value={"status": "completed"})
        self.cancel_turn = AsyncMock(return_value=True)
        self.close_chat_session = AsyncMock(return_value=None)
        self.get_session = AsyncMock(return_value=_FakeConversation())
        self.get_pending_permission = AsyncMock(return_value={"option": "allow_once"})


class _RecordingRuntimeRegistry:
    """记录资源注册事件，同时执行真实 verify 回调。"""

    def __init__(self) -> None:
        self.events: list[tuple[str, str, str]] = []
        self.active: dict[tuple[str, str, str, str], Optional[Callable[..., Any]]] = {}

    async def acquire(
        self,
        *,
        user_id: str,
        project_id: str,
        resource_type: Any,
        resource_id: str,
        verify_project: Callable[[], Any],
        close_callback: Optional[Callable[..., Any]] = None,
    ) -> None:
        verification = verify_project()
        if inspect.isawaitable(verification):
            await verification
        resource_name = getattr(resource_type, "value", str(resource_type))
        self.events.append(("acquire", resource_name, resource_id))
        self.active[(str(user_id), str(project_id), resource_name, resource_id)] = close_callback

    async def release(
        self,
        *,
        user_id: str,
        project_id: str,
        resource_type: Any,
        resource_id: str,
    ) -> None:
        resource_name = getattr(resource_type, "value", str(resource_type))
        self.events.append(("release", resource_name, resource_id))
        self.active.pop((str(user_id), str(project_id), resource_name, resource_id), None)


@pytest.fixture(autouse=True)
def _reset_session_metadata() -> Any:
    """隔离模块级 ACP 会话和安装锁状态。"""
    acp._acp_user_sessions.clear()
    acp._OPENCODE_INSTALL_LOCKS.clear()
    yield
    acp._acp_user_sessions.clear()
    acp._OPENCODE_INSTALL_LOCKS.clear()


@pytest.fixture()
def project_root(tmp_path: Path) -> Path:
    """创建不会触碰真实项目的临时 Node.js 工作台项目。"""
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    return tmp_path


@pytest.fixture()
def acp_context(monkeypatch: pytest.MonkeyPatch, project_root: Path):
    """构造可观测的项目解析器、运行时注册表和 ACP 服务。"""
    resolve_calls: list[dict[str, str]] = []
    resolve_db_ids: list[int] = []
    lifecycle_events: list[str] = []
    error_holder: dict[str, Exception | None] = {"error": None}
    roots: dict[str, Path] = {
        "project-a": project_root,
        "project-b": project_root / "project-b",
    }
    roots["project-b"].mkdir()

    class _ProjectService:
        def __init__(self, db: Any, path_policy: Any) -> None:
            self.db = db
            self.path_policy = path_policy

        def resolve_project_root(
            self,
            *,
            user_id: str,
            user_role: str,
            project_id: str,
        ) -> Path:
            lifecycle_events.append("resolve")
            resolve_db_ids.append(id(self.db))
            resolve_calls.append(
                {
                    "user_id": user_id,
                    "user_role": user_role,
                    "project_id": project_id,
                }
            )
            if error_holder["error"] is not None:
                raise error_holder["error"]
            if project_id not in roots:
                raise ProjectNotFound()
            return roots[project_id]

    registry = _RecordingRuntimeRegistry()
    preview_registry = SimpleNamespace(revoke_session=AsyncMock(return_value=None))
    fake_service = _FakeACPService()
    request_db = object()
    fresh_db = object()

    @contextmanager
    def _fresh_session():
        """模拟只用于消费前重验的独立短数据库会话。"""
        yield fresh_db

    monkeypatch.setattr(acp, "WorkbenchProjectService", _ProjectService, raising=False)
    monkeypatch.setattr(acp, "SessionLocal", _fresh_session, raising=False)
    monkeypatch.setattr(acp, "get_acp_service", lambda agent: fake_service)
    monkeypatch.setattr(acp, "preview_lease_registry", preview_registry, raising=False)
    monkeypatch.setattr(
        acp,
        "_run_npm_command",
        AsyncMock(side_effect=[(0, "installed"), (0, "audit ok")]),
    )
    monkeypatch.setattr(
        acp,
        "_get_opencode_status",
        AsyncMock(
            return_value=acp.OpenCodeStatusResponse(
                project_id="project-a",
                package_json_exists=True,
                project_installed=True,
                available=True,
                command="opencode",
            )
        ),
    )

    @contextmanager
    def _client(user: _User = _User()):
        app = FastAPI()
        app.include_router(acp.router)
        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_db] = lambda: request_db
        path_policy_dependency = getattr(acp, "get_acp_workbench_path_policy", None)
        if path_policy_dependency is not None:
            app.dependency_overrides[path_policy_dependency] = lambda: object()
        registry_dependency = getattr(acp, "get_acp_runtime_registry", None)
        if registry_dependency is not None:
            app.dependency_overrides[registry_dependency] = lambda: registry
        with TestClient(app) as client:
            yield client

    return {
        "client": _client,
        "service": fake_service,
        "registry": registry,
        "preview_registry": preview_registry,
        "resolve_calls": resolve_calls,
        "resolve_db_ids": resolve_db_ids,
        "lifecycle_events": lifecycle_events,
        "request_db": request_db,
        "fresh_db": fresh_db,
        "error_holder": error_holder,
        "roots": roots,
    }


def _seed_session(acp_context, *, project_id: str = "project-a") -> None:
    root = acp_context["roots"][project_id]
    acp._acp_user_sessions[("user-a", "session-1")] = {
        "user_id": "user-a",
        "project_id": project_id,
        "agent": "claude_code",
        "resolved_root": str(root.resolve()),
        "cwd": str(root.resolve()),
        "created_at": "2026-08-12T00:00:00+00:00",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("session_kind", "metadata", "expected_service_calls"),
    (
        (PreviewSessionKind.TERMINAL, None, 0),
        (
            PreviewSessionKind.ACP,
            {
                "user_id": "user-b",
                "project_id": "project-a",
                "agent": "claude_code",
                "resolved_root": "unused",
            },
            0,
        ),
        (
            PreviewSessionKind.ACP,
            {
                "user_id": "user-a",
                "project_id": "project-b",
                "agent": "claude_code",
                "resolved_root": "unused",
            },
            0,
        ),
    ),
)
async def test_listener_verifier_rejects_wrong_kind_or_route_identity(
    acp_context,
    monkeypatch: pytest.MonkeyPatch,
    session_kind: PreviewSessionKind,
    metadata: Optional[dict[str, str]],
    expected_service_calls: int,
) -> None:
    """listener 校验必须先拒绝错误类型以及路由层用户或项目身份不匹配。"""
    if metadata is not None:
        acp._acp_user_sessions[("user-a", "session-1")] = metadata
    ownership_check = MagicMock(return_value=True)
    monkeypatch.setattr(
        listener_ownership,
        "process_tree_owns_listener",
        ownership_check,
    )
    verified = await listener_verifier_registry.verify(
        "user-a",
        "project-a",
        session_kind,
        "session-1",
        5173,
    )

    assert verified is False
    assert acp_context["service"].get_session.await_count == expected_service_calls
    ownership_check.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("listener_owner", ("root", "child"))
async def test_listener_verifier_uses_bound_agent_process_tree(
    acp_context,
    monkeypatch: pytest.MonkeyPatch,
    listener_owner: str,
) -> None:
    """根进程或其后代监听端口时都必须用真实 ACP 根 PID 完成归属验证。"""
    _seed_session(acp_context)
    project_root = str(acp_context["roots"]["project-a"].resolve())
    conversation = SimpleNamespace(
        user_id="user-a",
        project_id="project-a",
        resolved_root=project_root,
        process=SimpleNamespace(pid=4312),
    )
    acp_context["service"].get_session = AsyncMock(return_value=conversation)
    ownership_check = MagicMock(return_value=listener_owner in {"root", "child"})
    monkeypatch.setattr(
        listener_ownership,
        "process_tree_owns_listener",
        ownership_check,
    )

    verified = await listener_verifier_registry.verify(
        "user-a",
        "project-a",
        PreviewSessionKind.ACP,
        "session-1",
        5173,
    )

    assert verified is True
    acp_context["service"].get_session.assert_awaited_once_with(
        chat_id="user-a:session-1",
        agent="claude_code",
        user_id="user-a",
        project_id="project-a",
        resolved_root=project_root,
    )
    ownership_check.assert_called_once_with(root_pid=4312, port=5173)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "conversation",
    (
        None,
        SimpleNamespace(
            user_id="user-b",
            project_id="project-a",
            resolved_root="unused",
            process=SimpleNamespace(pid=4312),
        ),
        SimpleNamespace(
            user_id="user-a",
            project_id="project-b",
            resolved_root="unused",
            process=SimpleNamespace(pid=4312),
        ),
        SimpleNamespace(
            user_id="user-a",
            project_id="project-a",
            resolved_root="wrong-root",
            process=SimpleNamespace(pid=4312),
        ),
        SimpleNamespace(
            user_id="user-a",
            project_id="project-a",
            resolved_root="unused",
            process=SimpleNamespace(pid=0),
        ),
    ),
)
async def test_listener_verifier_fails_closed_for_missing_or_mismatched_runtime(
    acp_context,
    monkeypatch: pytest.MonkeyPatch,
    conversation: object,
) -> None:
    """会话缺失、三元身份不完整或 PID 非法时不得探测监听端口。"""
    _seed_session(acp_context)
    if conversation is not None and getattr(conversation, "resolved_root", None) == "unused":
        conversation.resolved_root = str(acp_context["roots"]["project-a"].resolve())
    acp_context["service"].get_session = AsyncMock(return_value=conversation)
    ownership_check = MagicMock(return_value=True)
    monkeypatch.setattr(
        listener_ownership,
        "process_tree_owns_listener",
        ownership_check,
    )

    verified = await listener_verifier_registry.verify(
        "user-a",
        "project-a",
        PreviewSessionKind.ACP,
        "session-1",
        5173,
    )

    assert verified is False
    ownership_check.assert_not_called()


@pytest.mark.asyncio
async def test_listener_verifier_fails_closed_when_service_lookup_raises(
    acp_context,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ACP 服务或会话查询异常时 listener 校验必须稳定拒绝。"""
    _seed_session(acp_context)
    monkeypatch.setattr(
        acp,
        "get_acp_service",
        MagicMock(side_effect=RuntimeError("service lookup failed")),
    )
    ownership_check = MagicMock(return_value=True)
    monkeypatch.setattr(
        listener_ownership,
        "process_tree_owns_listener",
        ownership_check,
    )

    verified = await listener_verifier_registry.verify(
        "user-a",
        "project-a",
        PreviewSessionKind.ACP,
        "session-1",
        5173,
    )

    assert verified is False
    ownership_check.assert_not_called()


@pytest.mark.parametrize(
    ("method", "url", "body"),
    (
        ("post", "/acp/sessions", {"agent": "claude_code"}),
        ("get", "/acp/opencode/status", None),
        ("post", "/acp/opencode/install", {"confirm_install": True}),
        ("get", "/acp/sessions", None),
        ("post", "/acp/sessions/session-1/prompt", {"prompt": "hello"}),
        (
            "post",
            "/acp/sessions/session-1/permission",
            {"option_id": "allow_once"},
        ),
        ("post", "/acp/sessions/session-1/cancel", None),
        ("delete", "/acp/sessions/session-1", None),
    ),
)
def test_all_project_consumers_require_project_id(
    acp_context,
    method: str,
    url: str,
    body: Optional[dict[str, Any]],
) -> None:
    """所有项目消费入口缺失 project_id 时必须结构化拒绝。"""
    _seed_session(acp_context)
    with acp_context["client"]() as client:
        response = getattr(client, method)(url, json=body) if body is not None else getattr(client, method)(url)

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "workbench_project_required"
    assert acp_context["resolve_calls"] == []


@pytest.mark.parametrize(
    ("method", "url", "body"),
    (
        (
            "post",
            "/acp/sessions",
            {"agent": "claude_code", "project_id": "project-a", "cwd": "C:\\legacy"},
        ),
        (
            "get",
            "/acp/opencode/status?project_id=project-a&projectDir=C%3A%5Clegacy",
            None,
        ),
        (
            "post",
            "/acp/opencode/install",
            {"project_id": "project-a", "confirm_install": True, "project_dir": None},
        ),
        (
            "post",
            "/acp/sessions/session-1/prompt",
            {"project_id": "project-a", "prompt": "hello", "projectCwd": "C:\\legacy"},
        ),
    ),
)
def test_legacy_project_paths_are_rejected_without_resolution(
    acp_context,
    method: str,
    url: str,
    body: Optional[dict[str, Any]],
) -> None:
    """旧路径字段只能返回兼容期错误，不能进入解析或执行。"""
    _seed_session(acp_context)
    with acp_context["client"]() as client:
        response = getattr(client, method)(url, json=body) if body is not None else getattr(client, method)(url)

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "legacy_project_path_not_supported"
    assert response.headers["sunset"] == "2026-09-01"
    assert acp_context["resolve_calls"] == []


def test_create_binds_project_and_registers_session_resource(acp_context) -> None:
    """创建会话必须绑定用户和项目，并登记可关闭的 session 资源。"""
    with acp_context["client"]() as client:
        response = client.post(
            "/acp/sessions",
            json={"agent": "claude_code", "project_id": "project-a"},
        )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["project_id"] == "project-a"
    assert "cwd" not in data
    session_id = data["session_id"]
    metadata = acp._acp_user_sessions[("user-a", session_id)]
    assert metadata["user_id"] == "user-a"
    assert metadata["project_id"] == "project-a"
    assert metadata["resolved_root"] == str(acp_context["roots"]["project-a"].resolve())
    assert acp_context["registry"].events == [("acquire", "acp_session", session_id)]
    active_entry = next(iter(acp_context["registry"].active.values()))
    assert active_entry is not None


def test_session_acquire_failure_does_not_publish_metadata(acp_context) -> None:
    """资源 acquire 失败时不能留下半创建的 ACP 会话元数据。"""
    acp_context["error_holder"]["error"] = ProjectDisabled()

    with acp_context["client"]() as client:
        response = client.post(
            "/acp/sessions",
            json={"agent": "claude_code", "project_id": "project-a"},
        )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "workbench_project_disabled"
    assert acp._acp_user_sessions == {}
    assert acp_context["registry"].active == {}


def test_session_list_filters_by_user_and_project(acp_context) -> None:
    """同一用户在其他项目的会话不能出现在当前项目列表。"""
    _seed_session(acp_context, project_id="project-a")
    other_root = acp_context["roots"]["project-b"]
    acp._acp_user_sessions[("user-a", "session-2")] = {
        "user_id": "user-a",
        "project_id": "project-b",
        "agent": "codex",
        "resolved_root": str(other_root.resolve()),
        "cwd": str(other_root.resolve()),
        "created_at": "2026-08-12T00:00:01+00:00",
    }

    with acp_context["client"]() as client:
        response = client.get("/acp/sessions", params={"project_id": "project-a"})

    assert response.status_code == 200
    assert response.json()["count"] == 1
    assert response.json()["sessions"][0]["session_id"] == "session-1"
    assert response.json()["sessions"][0]["project_id"] == "project-a"
    assert "cwd" not in response.json()["sessions"][0]


@pytest.mark.parametrize(
    ("url", "body"),
    (
        ("/acp/sessions/session-1/prompt", {"prompt": "hello", "project_id": "project-a"}),
        (
            "/acp/sessions/session-1/permission",
            {"option_id": "allow_once", "project_id": "project-a"},
        ),
    ),
)
def test_turn_operations_revalidate_and_release_turn_resource(
    acp_context,
    url: str,
    body: dict[str, Any],
) -> None:
    """prompt 和 permission 每次重验项目，并在完成后释放 turn 资源。"""
    _seed_session(acp_context)

    with acp_context["client"]() as client:
        response = client.post(url, json=body)

    assert response.status_code == 200, response.text
    assert len(acp_context["resolve_calls"]) >= 1
    assert acp_context["registry"].events[-2:] == [
        ("acquire", "acp_turn", "session-1"),
        ("release", "acp_turn", "session-1"),
    ]
    assert acp_context["registry"].active == {}
    if url.endswith("/permission"):
        acp_context["service"].get_pending_permission.assert_awaited_once_with(
            chat_id="user-a:session-1",
            agent="claude_code",
            user_id="user-a",
            project_id="project-a",
            resolved_root=str(acp_context["roots"]["project-a"]),
        )


def test_prompt_fresh_resolves_inside_stream_immediately_before_run_turn(acp_context) -> None:
    """SSE 真正消费前必须用独立短会话紧邻 run_turn 重新解析项目根。"""
    _seed_session(acp_context)
    lifecycle_events = acp_context["lifecycle_events"]

    async def _run_turn(**kwargs: Any) -> dict[str, str]:
        del kwargs
        lifecycle_events.append("run_turn")
        return {"status": "completed"}

    acp_context["service"].run_turn = AsyncMock(side_effect=_run_turn)

    with acp_context["client"]() as client:
        response = client.post(
            "/acp/sessions/session-1/prompt",
            json={"prompt": "hello", "project_id": "project-a"},
        )

    assert response.status_code == 200, response.text
    assert lifecycle_events[-2:] == ["resolve", "run_turn"]
    assert acp_context["resolve_db_ids"][-1] == id(acp_context["fresh_db"])
    assert acp_context["resolve_db_ids"][-1] != id(acp_context["request_db"])


def test_prompt_sse_applies_public_projection_to_permission_and_error_fields(
    acp_context,
    tmp_path: Path,
) -> None:
    """SSE permission 投影必须覆盖嵌套字段，禁止旁路返回原始绝对路径。"""
    _seed_session(acp_context)
    project_root = acp_context["roots"]["project-a"]
    inside = project_root / "src" / "main.py"
    outside = project_root.parent / f"{project_root.name}-private" / "secret.txt"
    suspended = {
        "target": str(inside),
        "detail": {"output": f"outside={outside}"},
        "paths": [str(inside), str(outside)],
        "command": f'type "{inside}"',
        "resolved_root": str(project_root),
    }
    acp_context["service"].run_turn = AsyncMock(
        return_value={
            "status": "permission_required",
            "suspended_permission": suspended,
        },
    )

    with acp_context["client"]() as client:
        response = client.post(
            "/acp/sessions/session-1/prompt",
            json={"prompt": "hello", "project_id": "project-a"},
        )

    assert response.status_code == 200, response.text
    assert str(project_root) not in response.text
    assert str(outside.parent) not in response.text
    assert "resolved_root" not in response.text
    assert "src" in response.text and "main.py" in response.text
    assert "[redacted-path]" in response.text


@pytest.mark.asyncio
async def test_prompt_disconnect_cancel_failure_preserves_turn_registration(acp_context) -> None:
    """断线取消未确认成功时不得释放 turn 注册项，必须保留后续重试入口。"""
    _seed_session(acp_context)
    registry = acp_context["registry"]
    run_started = asyncio.Event()
    keep_running = asyncio.Event()

    async def _run_turn(**kwargs: Any) -> dict[str, str]:
        del kwargs
        run_started.set()
        await keep_running.wait()
        return {"status": "completed"}

    service = acp_context["service"]
    service.run_turn = AsyncMock(side_effect=_run_turn)
    service.cancel_turn = AsyncMock(return_value=False)
    response = await acp.prompt_session(
        session_id="session-1",
        request=acp.PromptRequest(prompt="hello", project_id="project-a"),
        current_user=_User(),
        db=acp_context["request_db"],
        path_policy=object(),
        registry=registry,
    )
    next_frame = asyncio.create_task(anext(response.body_iterator))
    await asyncio.wait_for(run_started.wait(), timeout=1.0)

    next_frame.cancel()
    with pytest.raises(asyncio.CancelledError):
        await next_frame

    turn_key = ("user-a", "project-a", "acp_turn", "session-1")
    assert turn_key in registry.active
    assert ("release", "acp_turn", "session-1") not in registry.events
    service.cancel_turn.assert_awaited_once_with(
        chat_id="user-a:session-1",
        agent="claude_code",
        user_id="user-a",
        project_id="project-a",
        resolved_root=str(acp_context["roots"]["project-a"]),
    )


def test_cancel_revalidates_project_and_releases_turn_resource(acp_context) -> None:
    """取消入口必须重验项目，并清理可能残留的 turn 注册项。"""
    _seed_session(acp_context)
    acp_context["registry"].active[("user-a", "project-a", "acp_turn", "session-1")] = None

    with acp_context["client"]() as client:
        response = client.post(
            "/acp/sessions/session-1/cancel",
            params={"project_id": "project-a"},
        )

    assert response.status_code == 200
    assert response.json()["cancelled"] is True
    assert acp_context["registry"].events[-1] == ("release", "acp_turn", "session-1")
    assert acp_context["registry"].active == {}


@pytest.mark.parametrize(
    "cancel_result",
    (False, RuntimeError("cancel failed")),
)
def test_cancel_failure_preserves_turn_registration_and_returns_non_2xx(
    acp_context,
    cancel_result: object,
) -> None:
    """取消未确认成功时必须保留可重试的 turn 状态并显式失败。"""
    _seed_session(acp_context)
    registry = acp_context["registry"]
    turn_key = ("user-a", "project-a", "acp_turn", "session-1")
    registry.active[turn_key] = None
    if isinstance(cancel_result, Exception):
        acp_context["service"].cancel_turn = AsyncMock(side_effect=cancel_result)
    else:
        acp_context["service"].cancel_turn = AsyncMock(return_value=cancel_result)

    with acp_context["client"]() as client:
        response = client.post(
            "/acp/sessions/session-1/cancel",
            params={"project_id": "project-a"},
        )

    assert response.status_code >= 400
    assert ("user-a", "session-1") in acp._acp_user_sessions
    assert turn_key in registry.active
    assert ("release", "acp_turn", "session-1") not in registry.events


def test_close_revalidates_project_and_releases_all_session_resources(acp_context) -> None:
    """关闭会话必须释放 session 与 turn 注册项，并移除元数据。"""
    _seed_session(acp_context)
    registry = acp_context["registry"]
    registry.active[("user-a", "project-a", "acp_session", "session-1")] = None
    registry.active[("user-a", "project-a", "acp_turn", "session-1")] = None

    with acp_context["client"]() as client:
        response = client.delete(
            "/acp/sessions/session-1",
            params={"project_id": "project-a"},
        )

    assert response.status_code == 200
    assert ("user-a", "session-1") not in acp._acp_user_sessions
    assert registry.active == {}
    assert ("release", "acp_turn", "session-1") in registry.events
    assert ("release", "acp_session", "session-1") in registry.events
    acp_context["preview_registry"].revoke_session.assert_awaited_once_with(
        user_id="user-a",
        project_id="project-a",
        session_kind=PreviewSessionKind.ACP,
        session_id="session-1",
    )


def test_close_failure_preserves_metadata_and_runtime_registration(acp_context) -> None:
    """关闭子进程失败时不能删除元数据或释放运行时注册项。"""
    _seed_session(acp_context)
    registry = acp_context["registry"]
    session_key = ("user-a", "project-a", "acp_session", "session-1")
    turn_key = ("user-a", "project-a", "acp_turn", "session-1")
    registry.active[session_key] = None
    registry.active[turn_key] = None
    acp_context["service"].close_chat_session = AsyncMock(
        side_effect=RuntimeError("close failed"),
    )

    with acp_context["client"]() as client:
        response = client.delete(
            "/acp/sessions/session-1",
            params={"project_id": "project-a"},
        )

    assert response.status_code >= 400
    assert ("user-a", "session-1") in acp._acp_user_sessions
    assert session_key in registry.active
    assert turn_key in registry.active
    assert not any(event[0] == "release" for event in registry.events)
    acp_context["preview_registry"].revoke_session.assert_not_awaited()


def test_cross_project_close_does_not_revoke_preview_lease(acp_context) -> None:
    """跨项目关闭被隐藏时不得误撤销原项目的预览 lease。"""
    _seed_session(acp_context, project_id="project-a")

    with acp_context["client"]() as client:
        response = client.delete(
            "/acp/sessions/session-1",
            params={"project_id": "project-b"},
        )

    assert response.status_code == 404
    acp_context["preview_registry"].revoke_session.assert_not_awaited()


def test_cross_user_close_does_not_revoke_preview_lease(acp_context) -> None:
    """其他用户无法借同一会话 ID 撤销所有者的预览 lease。"""
    _seed_session(acp_context, project_id="project-a")

    with acp_context["client"](_User("user-b")) as client:
        response = client.delete(
            "/acp/sessions/session-1",
            params={"project_id": "project-a"},
        )

    assert response.status_code == 404
    acp_context["preview_registry"].revoke_session.assert_not_awaited()


@pytest.mark.asyncio
async def test_runtime_close_callback_revokes_preview_after_process_close(acp_context) -> None:
    """运行时关闭回调必须在旧 ACP 进程确认关闭后撤销该会话的全部 lease。"""
    lifecycle_events: list[str] = []

    async def _close(**kwargs: Any) -> None:
        del kwargs
        lifecycle_events.append("close")

    async def _revoke(**kwargs: Any) -> None:
        del kwargs
        lifecycle_events.append("revoke")

    acp_context["service"].close_chat_session = AsyncMock(side_effect=_close)
    acp_context["preview_registry"].revoke_session = AsyncMock(side_effect=_revoke)
    with acp_context["client"]() as client:
        response = client.post(
            "/acp/sessions",
            json={"agent": "claude_code", "project_id": "project-a"},
        )
    assert response.status_code == 200, response.text
    session_id = response.json()["session_id"]
    callback = acp_context["registry"].active[
        ("user-a", "project-a", "acp_session", session_id)
    ]

    await callback()

    assert lifecycle_events == ["close", "revoke"]
    assert ("user-a", session_id) not in acp._acp_user_sessions
    acp_context["preview_registry"].revoke_session.assert_awaited_once_with(
        user_id="user-a",
        project_id="project-a",
        session_kind=PreviewSessionKind.ACP,
        session_id=session_id,
    )


@pytest.mark.asyncio
async def test_runtime_close_failure_preserves_preview_lease_and_metadata(acp_context) -> None:
    """运行时回调关闭旧进程失败时必须保留 lease 与会话元数据供重试。"""
    acp_context["service"].close_chat_session = AsyncMock(
        side_effect=RuntimeError("runtime close failed"),
    )
    with acp_context["client"]() as client:
        response = client.post(
            "/acp/sessions",
            json={"agent": "claude_code", "project_id": "project-a"},
        )
    assert response.status_code == 200, response.text
    session_id = response.json()["session_id"]
    callback = acp_context["registry"].active[
        ("user-a", "project-a", "acp_session", session_id)
    ]

    with pytest.raises(RuntimeError, match="runtime close failed"):
        await callback()

    acp_context["preview_registry"].revoke_session.assert_not_awaited()
    assert ("user-a", session_id) in acp._acp_user_sessions


@pytest.mark.asyncio
async def test_eviction_failure_preserves_metadata_and_runtime_registration(acp_context) -> None:
    """容量淘汰关闭失败时必须保留旧会话和全部运行时注册项。"""
    _seed_session(acp_context)
    registry = acp_context["registry"]
    session_key = ("user-a", "project-a", "acp_session", "session-1")
    turn_key = ("user-a", "project-a", "acp_turn", "session-1")
    registry.active[session_key] = None
    registry.active[turn_key] = None
    acp_context["service"].close_chat_session = AsyncMock(
        side_effect=RuntimeError("eviction close failed"),
    )

    with pytest.raises(HTTPException) as exc_info:
        await acp._evict_acp_session(
            ("user-a", "session-1"),
            registry=registry,
        )

    assert exc_info.value.status_code >= 400
    assert ("user-a", "session-1") in acp._acp_user_sessions
    assert session_key in registry.active
    assert turn_key in registry.active
    assert not any(event[0] == "release" for event in registry.events)
    acp_context["preview_registry"].revoke_session.assert_not_awaited()


@pytest.mark.asyncio
async def test_successful_eviction_revokes_preview_after_process_close(acp_context) -> None:
    """成功淘汰必须先关闭 ACP 进程，再撤销精确身份绑定的预览 lease。"""
    _seed_session(acp_context)
    lifecycle_events: list[str] = []

    async def _close(**kwargs: Any) -> None:
        del kwargs
        lifecycle_events.append("close")

    async def _revoke(**kwargs: Any) -> None:
        del kwargs
        lifecycle_events.append("revoke")

    acp_context["service"].close_chat_session = AsyncMock(side_effect=_close)
    acp_context["preview_registry"].revoke_session = AsyncMock(side_effect=_revoke)

    await acp._evict_acp_session(
        ("user-a", "session-1"),
        registry=acp_context["registry"],
    )

    assert lifecycle_events == ["close", "revoke"]
    acp_context["preview_registry"].revoke_session.assert_awaited_once_with(
        user_id="user-a",
        project_id="project-a",
        session_kind=PreviewSessionKind.ACP,
        session_id="session-1",
    )
    assert ("user-a", "session-1") not in acp._acp_user_sessions


def test_opencode_install_registers_and_releases_install_resource(acp_context) -> None:
    """OpenCode 安装成功后必须释放临时安装资源。"""
    with acp_context["client"]() as client:
        response = client.post(
            "/acp/opencode/install",
            json={"project_id": "project-a", "confirm_install": True},
        )

    assert response.status_code == 200, response.text
    assert acp_context["registry"].events[-2][0:2] == ("acquire", "opencode_install")
    assert acp_context["registry"].events[-1][0:2] == ("release", "opencode_install")
    assert acp_context["registry"].active == {}


def test_opencode_install_fresh_resolves_after_lock_before_each_npm_process(
    acp_context,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """安装锁内每个 npm 子进程前都必须用独立短会话重新解析项目根。"""
    lifecycle_events = acp_context["lifecycle_events"]

    async def _run_npm(cwd: str, args: list[str]) -> tuple[int, str]:
        del cwd, args
        lifecycle_events.append("npm")
        return 0, "ok"

    monkeypatch.setattr(acp, "_run_npm_command", _run_npm)

    with acp_context["client"]() as client:
        response = client.post(
            "/acp/opencode/install",
            json={"project_id": "project-a", "confirm_install": True},
        )

    assert response.status_code == 200, response.text
    assert lifecycle_events[-4:] == ["resolve", "npm", "resolve", "npm"]
    assert acp_context["resolve_db_ids"][-2:] == [
        id(acp_context["fresh_db"]),
        id(acp_context["fresh_db"]),
    ]


def test_opencode_install_output_recursively_redacts_absolute_paths(
    acp_context,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """安装 JSON 不得泄露项目根、用户目录或 npm 的其他绝对路径。"""
    project_root = acp_context["roots"]["project-a"]
    inside = project_root / "node_modules" / "opencode.log"
    outside = project_root.parent / f"{project_root.name}-private" / "npm-cache.log"
    outside.parent.mkdir()
    monkeypatch.setattr(
        acp,
        "_run_npm_command",
        AsyncMock(
            side_effect=[
                (0, f"installed from {inside}"),
                (0, f'{{"cache":"{outside}"}}'),
            ],
        ),
    )

    with acp_context["client"]() as client:
        response = client.post(
            "/acp/opencode/install",
            json={"project_id": "project-a", "confirm_install": True},
        )

    assert response.status_code == 200, response.text
    serialized = response.text
    assert str(project_root) not in serialized
    assert str(outside.parent) not in serialized
    assert "node_modules" in serialized
    assert "[redacted-path]" in serialized


def test_opencode_status_exposes_logical_command_not_absolute_executable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """状态响应只能返回逻辑命令名，不能返回项目内绝对 executable。"""
    executable = tmp_path / "node_modules" / ".bin" / "opencode.cmd"
    executable.parent.mkdir(parents=True)
    executable.write_text("", encoding="utf-8")
    config = type("Config", (), {"command": "opencode"})()
    monkeypatch.setattr(acp, "discover_agents", lambda: {"opencode": config})
    monkeypatch.setattr(acp, "resolve_agent_command", lambda *_: str(executable))
    monkeypatch.setattr(acp, "is_agent_available", lambda *_: True)

    result = asyncio.run(acp._get_opencode_status("project-a", str(tmp_path)))

    assert result.project_installed is True
    assert result.command == "opencode"
    assert str(tmp_path) not in result.model_dump_json()


def test_public_projection_recursively_removes_private_roots_and_keys(tmp_path: Path) -> None:
    """SSE 与 permission 共用的递归投影必须相对化项目内路径并脱敏根外路径。"""
    project_root = tmp_path / "project"
    inside = project_root / "src" / "main.py"
    outside = tmp_path / "private" / "secret.txt"
    inside.parent.mkdir(parents=True)
    outside.parent.mkdir(parents=True)
    payload = {
        "target": str(inside),
        "detail": f"read {inside}",
        "paths": [str(inside), str(outside)],
        "command": f'type "{inside}" && type "{outside}"',
        "output": {"line": f"failed at {outside}"},
        "registered_root": str(project_root),
        "nested": {"canonical_root": str(project_root), "resolved_root": str(project_root)},
    }

    projected = acp._project_public_payload(payload, project_root)
    serialized = json.dumps(projected, ensure_ascii=False)

    assert str(project_root) not in serialized
    assert str(outside.parent) not in serialized
    assert "registered_root" not in serialized
    assert "canonical_root" not in serialized
    assert "resolved_root" not in serialized
    assert "src" in serialized and "main.py" in serialized
    assert serialized.count("[redacted-path]") >= 2


def test_tool_lifecycle_events_map_to_tool_sse() -> None:
    """ACP 工具生命周期三类事件都必须投影为 SSE tool。"""
    for event_type in ("tool_start", "tool_update", "tool_end"):
        assert acp._resolve_event_type({"type": event_type}) == "tool"


@pytest.mark.parametrize(
    ("error", "status_code", "code"),
    (
        (ProjectNotFound(), 404, "workbench_project_not_found"),
        (ProjectDisabled(), 409, "workbench_project_disabled"),
        (ProjectRootChanged(), 409, "workbench_project_root_changed"),
    ),
)
def test_project_resolution_failures_block_session_use(
    acp_context,
    error: Exception,
    status_code: int,
    code: str,
) -> None:
    """不存在、禁用或漂移的项目都不能继续使用缓存 ACP 会话。"""
    _seed_session(acp_context)
    acp_context["error_holder"]["error"] = error

    with acp_context["client"]() as client:
        response = client.post(
            "/acp/sessions/session-1/cancel",
            params={"project_id": "project-a"},
        )

    assert response.status_code == status_code
    assert response.json()["detail"]["code"] == code
    acp_context["service"].cancel_turn.assert_not_awaited()


def test_cross_project_session_access_is_hidden(acp_context) -> None:
    """用户不能用另一个合法项目 ID 操作当前会话。"""
    _seed_session(acp_context, project_id="project-a")

    with acp_context["client"]() as client:
        response = client.post(
            "/acp/sessions/session-1/cancel",
            params={"project_id": "project-b"},
        )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "acp_session_not_found"
    acp_context["service"].cancel_turn.assert_not_awaited()
