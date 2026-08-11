from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from db.models import Base, User, WorkbenchContext, WorkbenchProject
from workbench.errors import ProjectDisabled, ProjectNotFound, ProjectRootConflict
from workbench.path_policy import WorkbenchPathPolicy
from workbench.project_service import WorkbenchProjectService


@pytest.fixture()
def service_fixture(tmp_path: Path):
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
    session = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
    session.add_all(
        [
            User(id="owner", username="owner", password_hash="hash", role="user"),
            User(id="other", username="other", password_hash="hash", role="user"),
        ]
    )
    session.commit()
    allowed_root = tmp_path / "allowed"
    allowed_root.mkdir()
    policy = WorkbenchPathPolicy.from_json(
        global_roots_json="[]",
        user_roots_json=json.dumps(
            {
                "owner": [str(allowed_root)],
                "other": [str(allowed_root)],
            },
            ensure_ascii=False,
        ),
        project_root=tmp_path / "unused-project",
        workspace_root=tmp_path / "unused-workspace",
    )
    service = WorkbenchProjectService(session, policy)
    try:
        yield service, session, allowed_root
    finally:
        session.close()
        engine.dispose()


def test_register_and_resolve_owned_project(service_fixture) -> None:
    service, _session, allowed_root = service_fixture
    project_root = allowed_root / "project-a"
    project_root.mkdir()

    project = service.register_project(
        user_id="owner",
        user_role="user",
        display_name="  Project A  ",
        root=str(project_root),
    )
    resolved = service.resolve_project_root(
        user_id="owner",
        user_role="user",
        project_id=project.id,
    )

    assert project.display_name == "Project A"
    assert resolved == project_root.resolve()


def test_get_owned_project_does_not_reveal_other_users_project(service_fixture) -> None:
    service, _session, allowed_root = service_fixture
    project_root = allowed_root / "project-a"
    project_root.mkdir()
    project = service.register_project(
        user_id="owner",
        user_role="user",
        display_name="Project A",
        root=str(project_root),
    )

    with pytest.raises(ProjectNotFound):
        service.get_owned_project(user_id="other", project_id=project.id)


def test_register_duplicate_canonical_root_is_conflict(service_fixture) -> None:
    service, _session, allowed_root = service_fixture
    project_root = allowed_root / "project-a"
    project_root.mkdir()
    service.register_project(
        user_id="owner",
        user_role="user",
        display_name="Project A",
        root=str(project_root),
    )

    with pytest.raises(ProjectRootConflict):
        service.register_project(
            user_id="owner",
            user_role="user",
            display_name="Duplicate",
            root=str(project_root),
        )


def test_disabled_project_fails_closed_and_clears_context(service_fixture) -> None:
    service, session, allowed_root = service_fixture
    project_root = allowed_root / "project-a"
    project_root.mkdir()
    project = service.register_project(
        user_id="owner",
        user_role="user",
        display_name="Project A",
        root=str(project_root),
    )
    service.set_current_project(
        user_id="owner",
        user_role="user",
        project_id=project.id,
    )

    service.update_project(
        user_id="owner",
        project_id=project.id,
        display_name=None,
        is_enabled=False,
    )

    context = session.get(WorkbenchContext, "owner")
    assert context is not None
    assert context.current_project_id is None
    with pytest.raises(ProjectDisabled):
        service.resolve_project_root(
            user_id="owner",
            user_role="user",
            project_id=project.id,
        )


def test_set_context_rejects_cross_user_project(service_fixture) -> None:
    service, _session, allowed_root = service_fixture
    project_root = allowed_root / "project-a"
    project_root.mkdir()
    project = service.register_project(
        user_id="owner",
        user_role="user",
        display_name="Project A",
        root=str(project_root),
    )

    with pytest.raises(ProjectNotFound):
        service.set_current_project(
            user_id="other",
            user_role="user",
            project_id=project.id,
        )


def test_delete_project_only_deletes_registration(service_fixture) -> None:
    service, session, allowed_root = service_fixture
    project_root = allowed_root / "project-a"
    project_root.mkdir()
    marker = project_root / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    project = service.register_project(
        user_id="owner",
        user_role="user",
        display_name="Project A",
        root=str(project_root),
    )
    service.set_current_project(
        user_id="owner",
        user_role="user",
        project_id=project.id,
    )

    service.delete_project(user_id="owner", project_id=project.id)

    assert session.get(WorkbenchProject, project.id) is None
    context = session.get(WorkbenchContext, "owner")
    assert context is not None
    assert context.current_project_id is None
    assert marker.read_text(encoding="utf-8") == "keep"

