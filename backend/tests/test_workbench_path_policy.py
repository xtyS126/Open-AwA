import json
import os
from pathlib import Path

import pytest

from workbench.errors import ProjectRootChanged, ProjectRootForbidden, ProjectRootInvalid
from workbench.path_policy import WorkbenchPathPolicy


def _policy_for(tmp_path: Path, *, user_id: str = "user-1") -> WorkbenchPathPolicy:
    allowed_root = tmp_path / "allowed"
    allowed_root.mkdir()
    return WorkbenchPathPolicy.from_json(
        global_roots_json="[]",
        user_roots_json=json.dumps({user_id: [str(allowed_root)]}, ensure_ascii=False),
        project_root=tmp_path / "project-default",
        workspace_root=tmp_path / "workspace-default",
    )


@pytest.mark.parametrize("raw_root", ["", "relative/project", "~/project", "bad\x00path"])
def test_registration_rejects_non_absolute_or_ambiguous_roots(tmp_path: Path, raw_root: str) -> None:
    policy = _policy_for(tmp_path)

    with pytest.raises(ProjectRootInvalid):
        policy.canonicalize_registration(raw_root, user_id="user-1", user_role="user")


def test_registration_accepts_owned_allowed_directory(tmp_path: Path) -> None:
    policy = _policy_for(tmp_path)
    project = tmp_path / "allowed" / "project-a"
    project.mkdir()

    registered_root, canonical_root = policy.canonicalize_registration(
        str(project),
        user_id="user-1",
        user_role="user",
    )

    assert registered_root == str(project)
    assert canonical_root == os.path.normcase(str(project.resolve()))


def test_registration_rejects_directory_outside_user_roots(tmp_path: Path) -> None:
    policy = _policy_for(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()

    with pytest.raises(ProjectRootForbidden):
        policy.canonicalize_registration(str(outside), user_id="user-1", user_role="user")


def test_empty_user_mapping_does_not_fall_back_to_global_roots(tmp_path: Path) -> None:
    global_root = tmp_path / "global"
    global_root.mkdir()
    project = global_root / "project"
    project.mkdir()
    policy = WorkbenchPathPolicy.from_json(
        global_roots_json=json.dumps([str(global_root)]),
        user_roots_json=json.dumps({"user-1": []}),
        project_root=tmp_path / "project-default",
        workspace_root=tmp_path / "workspace-default",
    )

    with pytest.raises(ProjectRootForbidden):
        policy.canonicalize_registration(str(project), user_id="user-1", user_role="user")


def test_admin_uses_global_roots(tmp_path: Path) -> None:
    global_root = tmp_path / "global"
    project = global_root / "project"
    project.mkdir(parents=True)
    policy = WorkbenchPathPolicy.from_json(
        global_roots_json=json.dumps([str(global_root)]),
        user_roots_json="{}",
        project_root=tmp_path / "project-default",
        workspace_root=tmp_path / "workspace-default",
    )

    _, canonical_root = policy.canonicalize_registration(
        str(project),
        user_id="admin-1",
        user_role="admin",
    )

    assert canonical_root == os.path.normcase(str(project.resolve()))


def test_invalid_allowed_root_configuration_fails_closed(tmp_path: Path) -> None:
    missing = tmp_path / "missing"

    with pytest.raises(ProjectRootInvalid):
        WorkbenchPathPolicy.from_json(
            global_roots_json=json.dumps([str(missing)]),
            user_roots_json="{}",
            project_root=tmp_path / "project-default",
            workspace_root=tmp_path / "workspace-default",
        )


def test_registered_root_is_re_resolved_and_detects_drift(tmp_path: Path) -> None:
    policy = _policy_for(tmp_path)
    project = tmp_path / "allowed" / "project-a"
    project.mkdir()
    registered_root, canonical_root = policy.canonicalize_registration(
        str(project),
        user_id="user-1",
        user_role="user",
    )
    different_root = tmp_path / "allowed" / "project-moved"
    different_root.mkdir()
    drifted_canonical_root = os.path.normcase(str(different_root.resolve()))

    with pytest.raises(ProjectRootChanged):
        policy.resolve_registered_root(
            registered_root,
            drifted_canonical_root,
            user_id="user-1",
            user_role="user",
        )

    assert canonical_root != drifted_canonical_root


def test_registered_root_disappearance_is_invalid(tmp_path: Path) -> None:
    policy = _policy_for(tmp_path)
    project = tmp_path / "allowed" / "project-a"
    project.mkdir()
    registered_root, canonical_root = policy.canonicalize_registration(
        str(project),
        user_id="user-1",
        user_role="user",
    )
    project.rmdir()

    with pytest.raises(ProjectRootInvalid):
        policy.resolve_registered_root(
            registered_root,
            canonical_root,
            user_id="user-1",
            user_role="user",
        )


def test_symlink_escape_is_rejected_when_supported(tmp_path: Path) -> None:
    policy = _policy_for(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    link = tmp_path / "allowed" / "linked-project"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"当前环境不能创建目录符号链接: {exc}")

    with pytest.raises(ProjectRootForbidden):
        policy.canonicalize_registration(str(link), user_id="user-1", user_role="user")
