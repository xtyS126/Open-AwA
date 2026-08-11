from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from api.dependencies import get_current_user
from api.routes import workbench as workbench_route
from db.models import Base, User
from db.models.base import get_db
from workbench.path_policy import WorkbenchPathPolicy
from workbench.runtime_registry import RuntimeResourceType, WorkbenchRuntimeRegistry


@pytest.fixture()
def workbench_api(tmp_path: Path) -> Iterator[tuple[TestClient, Session, dict[str, User], WorkbenchRuntimeRegistry]]:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = session_factory()
    users = {
        "owner": User(id="owner", username="owner", password_hash="hash", role="admin"),
        "other": User(id="other", username="other", password_hash="hash", role="admin"),
    }
    session.add_all(users.values())
    session.commit()

    allowed_root = tmp_path / "allowed"
    allowed_root.mkdir()
    policy = WorkbenchPathPolicy.from_json(
        global_roots_json=f'["{allowed_root.as_posix()}"]',
        user_roots_json="{}",
        project_root=tmp_path / "unused-project",
        workspace_root=tmp_path / "unused-workspace",
    )
    registry = WorkbenchRuntimeRegistry()
    current = {"user": users["owner"]}

    def override_db():
        yield session

    def override_user() -> User:
        return current["user"]

    app = FastAPI()
    app.include_router(workbench_route.router)
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user
    app.dependency_overrides[workbench_route.get_workbench_path_policy] = lambda: policy
    app.dependency_overrides[workbench_route.get_workbench_runtime_registry] = lambda: registry

    with TestClient(app) as client:
        client.headers.update({"X-Test-Current-User": "owner"})
        users["set_current"] = current  # type: ignore[assignment]
        yield client, session, users, registry

    session.close()
    engine.dispose()


def _set_current_user(users: dict[str, User], user_key: str) -> None:
    current = users["set_current"]  # type: ignore[assignment]
    current["user"] = users[user_key]  # type: ignore[index]


def _create_project(client: TestClient, root: Path, *, name: str = "Project A") -> dict:
    response = client.post(
        "/api/workbench/projects",
        json={"display_name": name, "root": str(root)},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_project_crud_response_never_exposes_server_paths(workbench_api, tmp_path: Path) -> None:
    client, _session, _users, _registry = workbench_api
    root = tmp_path / "allowed" / "project-a"
    root.mkdir()

    created = _create_project(client, root)

    assert set(created) == {
        "id",
        "display_name",
        "is_enabled",
        "created_at",
        "updated_at",
        "last_opened_at",
    }
    response = client.get("/api/workbench/projects")
    assert response.status_code == 200
    assert response.json()["items"] == [created]
    serialized = response.text.lower()
    assert "registered_root" not in serialized
    assert "canonical_root" not in serialized
    assert "resolved_root" not in serialized
    assert str(root).lower() not in serialized


def test_duplicate_root_is_conflict_and_cross_user_lookup_is_404(workbench_api, tmp_path: Path) -> None:
    client, _session, users, _registry = workbench_api
    root = tmp_path / "allowed" / "project-a"
    root.mkdir()
    project = _create_project(client, root)

    duplicate = client.post(
        "/api/workbench/projects",
        json={"display_name": "Duplicate", "root": str(root)},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["code"] == "workbench_project_root_conflict"

    _set_current_user(users, "other")
    hidden = client.get(f"/api/workbench/projects/{project['id']}")
    assert hidden.status_code == 404
    assert hidden.json()["detail"]["code"] == "workbench_project_not_found"


def test_update_cannot_change_root_and_disable_clears_context(workbench_api, tmp_path: Path) -> None:
    client, _session, _users, _registry = workbench_api
    root = tmp_path / "allowed" / "project-a"
    root.mkdir()
    project = _create_project(client, root)
    selected = client.patch("/api/workbench/context", json={"project_id": project["id"]})
    assert selected.status_code == 200

    illegal = client.patch(
        f"/api/workbench/projects/{project['id']}",
        json={"root": str(root)},
    )
    assert illegal.status_code == 422

    disabled = client.patch(
        f"/api/workbench/projects/{project['id']}",
        json={"is_enabled": False},
    )
    assert disabled.status_code == 200
    context = client.get("/api/workbench/context")
    assert context.status_code == 200
    assert context.json()["project"] is None


def test_context_contract_etag_and_extra_fields(workbench_api, tmp_path: Path) -> None:
    client, _session, _users, _registry = workbench_api
    root = tmp_path / "allowed" / "project-a"
    root.mkdir()
    project = _create_project(client, root)

    initial = client.get("/api/workbench/context")
    assert initial.status_code == 200
    assert initial.json() == {"project": None, "updated_at": None}

    extra = client.patch(
        "/api/workbench/context",
        json={"project_id": project["id"], "cwd": str(root)},
    )
    assert extra.status_code == 422

    selected = client.patch("/api/workbench/context", json={"project_id": project["id"]})
    assert selected.status_code == 200
    assert selected.json()["project"]["id"] == project["id"]
    assert selected.headers["etag"]

    conflict = client.patch(
        "/api/workbench/context",
        json={"project_id": None},
        headers={"If-Match": '"stale"'},
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "workbench_context_conflict"


def test_delete_registration_keeps_disk_and_rejects_active_runtime(workbench_api, tmp_path: Path) -> None:
    client, _session, _users, registry = workbench_api
    root = tmp_path / "allowed" / "project-a"
    root.mkdir()
    marker = root / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    project = _create_project(client, root)

    asyncio.run(
        registry.acquire(
            user_id="owner",
            project_id=project["id"],
            resource_type=RuntimeResourceType.PTY_SESSION,
            resource_id="pty-1",
            verify_project=lambda: None,
        )
    )
    blocked = client.delete(f"/api/workbench/projects/{project['id']}")
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "workbench_project_in_use"

    asyncio.run(
        registry.release(
            user_id="owner",
            project_id=project["id"],
            resource_type=RuntimeResourceType.PTY_SESSION,
            resource_id="pty-1",
        )
    )
    deleted = client.delete(f"/api/workbench/projects/{project['id']}")
    assert deleted.status_code == 204
    assert marker.read_text(encoding="utf-8") == "keep"


def test_invalid_display_name_and_forbidden_root_are_rejected(workbench_api, tmp_path: Path) -> None:
    client, _session, _users, _registry = workbench_api
    outside = tmp_path / "outside"
    outside.mkdir()

    empty_name = client.post(
        "/api/workbench/projects",
        json={"display_name": "   ", "root": str(outside)},
    )
    assert empty_name.status_code == 422

    forbidden = client.post(
        "/api/workbench/projects",
        json={"display_name": "Outside", "root": str(outside)},
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["detail"]["code"] == "workbench_project_root_forbidden"

