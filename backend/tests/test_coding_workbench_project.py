"""Coding API 通过工作台项目 ID 解析项目根的契约测试。"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.dependencies import get_current_user
from api.routes import coding
from db.models import get_db
from workbench.errors import ProjectDisabled, ProjectNotFound, ProjectRootChanged
from workbench.errors import ProjectRootForbidden, ProjectRootInvalid


class _AdminUser:
    """提供 Coding 路由需要的最小管理员身份。"""

    id = "user-a"
    role = "admin"
    username = "admin"


@dataclass(frozen=True)
class _EndpointCase:
    """描述一个会消费项目根的 Coding 入口。"""

    name: str
    method: Literal["GET", "POST"]
    path: str
    location: Literal["query", "body"]
    data: dict[str, Any]
    permission: Literal["coding:read", "coding:write"] = "coding:read"


_ROOT_ENDPOINTS = (
    _EndpointCase("tree", "GET", "/api/coding/tree", "query", {"path": ""}),
    _EndpointCase("list", "GET", "/api/coding/list", "query", {"path": ""}),
    _EndpointCase("read", "POST", "/api/coding/read", "body", {"path": "sample.py"}),
    _EndpointCase(
        "write",
        "POST",
        "/api/coding/write",
        "body",
        {"path": "generated.txt", "content": "已写入"},
        "coding:write",
    ),
    _EndpointCase(
        "search-files",
        "POST",
        "/api/coding/search-files",
        "body",
        {"pattern": "sample", "directory": ""},
    ),
    _EndpointCase("git-status", "GET", "/api/coding/git/status", "query", {}),
    _EndpointCase("git-diff", "GET", "/api/coding/git/diff", "query", {}),
    _EndpointCase("git-log", "GET", "/api/coding/git/log", "query", {"max_count": 1}),
    _EndpointCase(
        "git-commit",
        "POST",
        "/api/coding/git/commit",
        "body",
        {"message": "测试提交"},
        "coding:write",
    ),
    _EndpointCase("git-branches", "GET", "/api/coding/git/branches", "query", {}),
    _EndpointCase(
        "git-branch",
        "POST",
        "/api/coding/git/branch",
        "query",
        {"name": "test-branch"},
        "coding:write",
    ),
    _EndpointCase(
        "ast-definitions",
        "GET",
        "/api/coding/ast/definitions",
        "query",
        {"name": "sample_function"},
    ),
    _EndpointCase(
        "ast-references",
        "GET",
        "/api/coding/ast/references",
        "query",
        {"name": "sample_function"},
    ),
    _EndpointCase(
        "ast-search",
        "POST",
        "/api/coding/ast/search",
        "body",
        {"pattern": "sample_function"},
    ),
    _EndpointCase(
        "ast-structure",
        "GET",
        "/api/coding/ast/structure",
        "query",
        {"file_path": "sample.py"},
    ),
    _EndpointCase(
        "lsp-diagnostics",
        "GET",
        "/api/coding/lsp/diagnostics",
        "query",
        {"file_path": "sample.py"},
    ),
    _EndpointCase(
        "lsp-completions",
        "POST",
        "/api/coding/lsp/completions",
        "body",
        {"file_path": "sample.py", "line": 1, "column": 1},
    ),
    _EndpointCase(
        "lsp-hover",
        "POST",
        "/api/coding/lsp/hover",
        "body",
        {"file_path": "sample.py", "line": 1, "column": 1},
    ),
    _EndpointCase(
        "lsp-symbols",
        "GET",
        "/api/coding/lsp/symbols",
        "query",
        {"file_path": "sample.py"},
    ),
    _EndpointCase(
        "preview",
        "GET",
        "/api/coding/preview/file",
        "query",
        {"path": "sample.txt"},
    ),
    _EndpointCase(
        "download",
        "GET",
        "/api/coding/download",
        "query",
        {"path": "sample.txt"},
    ),
)


def _send_request(
    client: TestClient,
    case: _EndpointCase,
    *,
    project_id: str | None = None,
    project_dir: str | None = None,
):
    data = dict(case.data)
    if project_id is not None:
        data["project_id"] = project_id
    if project_dir is not None:
        data["project_dir"] = project_dir
    if case.method == "GET":
        return client.get(case.path, params=data)
    if case.location == "query":
        return client.post(case.path, params=data)
    return client.post(case.path, json=data)


@pytest.fixture()
def project_root(tmp_path: Path) -> Path:
    """建立与真实项目数据隔离的临时项目。"""
    (tmp_path / "sample.py").write_text(
        "def sample_function():\n    return '临时项目'\n",
        encoding="utf-8",
    )
    (tmp_path / "sample.txt").write_text("仅来自临时项目", encoding="utf-8")
    (tmp_path / "sample.bin").write_bytes(b"temporary-project")
    (tmp_path / "office.docx").write_bytes(b"PK\x03\x04")
    return tmp_path


@pytest.fixture()
def coding_client(monkeypatch: pytest.MonkeyPatch, project_root: Path):
    """用可观测的领域服务边界把 project_id 解析到临时目录。"""
    calls: list[dict[str, str]] = []
    error_holder: dict[str, Exception | None] = {"error": None}

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
            calls.append(
                {
                    "user_id": user_id,
                    "user_role": user_role,
                    "project_id": project_id,
                }
            )
            if error_holder["error"] is not None:
                raise error_holder["error"]
            return project_root

    monkeypatch.setattr(coding, "WorkbenchProjectService", _ProjectService, raising=False)

    app = FastAPI()
    app.include_router(coding.router)
    app.dependency_overrides[get_current_user] = lambda: _AdminUser()
    app.dependency_overrides[get_db] = lambda: object()
    path_policy_dependency = getattr(coding, "get_coding_workbench_path_policy", None)
    if path_policy_dependency is not None:
        app.dependency_overrides[path_policy_dependency] = lambda: object()

    with TestClient(app) as client:
        yield client, calls, error_holder


@pytest.mark.parametrize("case", _ROOT_ENDPOINTS, ids=lambda case: case.name)
def test_all_root_consuming_endpoints_resolve_project_id(
    coding_client,
    case: _EndpointCase,
) -> None:
    """所有入口必须用当前用户和 project_id 调用统一解析器。"""
    client, calls, _ = coding_client

    response = _send_request(client, case, project_id="project-a")

    assert response.status_code == 200, response.text
    assert calls == [
        {"user_id": "user-a", "user_role": "admin", "project_id": "project-a"}
    ]


@pytest.mark.parametrize("case", _ROOT_ENDPOINTS, ids=lambda case: case.name)
def test_all_root_consuming_endpoints_enforce_coding_permission(
    coding_client,
    case: _EndpointCase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """所有根消费入口必须按读写性质经过统一 RBAC 门禁。"""
    client, _, _ = coding_client
    permissions: list[str] = []

    async def _record_permission(current_user: Any, permission: str, db: Any) -> None:
        permissions.append(permission)

    monkeypatch.setattr(coding, "_check_coding_permission", _record_permission)

    response = _send_request(client, case, project_id="project-a")

    assert response.status_code == 200, response.text
    assert permissions == [case.permission]


@pytest.mark.parametrize("case", _ROOT_ENDPOINTS, ids=lambda case: case.name)
def test_all_root_consuming_endpoints_require_project_id(
    coding_client,
    case: _EndpointCase,
) -> None:
    """缺失 project_id 时必须结构化拒绝，且不能尝试解析根。"""
    client, calls, _ = coding_client

    response = _send_request(client, case)

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "workbench_project_required"
    assert calls == []


@pytest.mark.parametrize("case", _ROOT_ENDPOINTS, ids=lambda case: case.name)
def test_all_root_consuming_endpoints_reject_legacy_project_dir(
    coding_client,
    case: _EndpointCase,
) -> None:
    """兼容期只识别并拒绝旧路径，不得执行客户端提供的目录。"""
    client, calls, _ = coding_client

    response = _send_request(
        client,
        case,
        project_id="project-a",
        project_dir="C:\\不应执行\\legacy",
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "legacy_project_path_not_supported"
    assert response.headers["sunset"] == "2026-09-01"
    assert calls == []


def test_body_rejects_explicit_null_legacy_project_dir(coding_client) -> None:
    """请求体显式出现旧字段时，即使为 null 也不能继续执行。"""
    client, calls, _ = coding_client

    response = client.post(
        "/api/coding/read",
        json={
            "project_id": "project-a",
            "project_dir": None,
            "path": "sample.txt",
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "legacy_project_path_not_supported"
    assert response.headers["sunset"] == "2026-09-01"
    assert calls == []


@pytest.mark.parametrize(
    ("error", "status_code", "code"),
    (
        (ProjectNotFound(), 404, "workbench_project_not_found"),
        (ProjectDisabled(), 409, "workbench_project_disabled"),
        (ProjectRootChanged(), 409, "workbench_project_root_changed"),
        (ProjectRootForbidden(), 403, "workbench_project_root_forbidden"),
        (ProjectRootInvalid(), 422, "workbench_project_root_invalid"),
    ),
)
def test_project_resolution_errors_fail_closed(
    coding_client,
    error: Exception,
    status_code: int,
    code: str,
) -> None:
    """越权、禁用和根漂移都必须在文件服务执行前失败。"""
    client, calls, error_holder = coding_client
    error_holder["error"] = error

    response = client.get(
        "/api/coding/tree",
        params={"project_id": "project-a"},
    )

    assert response.status_code == status_code
    assert response.json()["detail"]["code"] == code
    assert len(calls) == 1


def test_resolved_root_is_used_for_file_access(coding_client, project_root: Path) -> None:
    """解析结果必须成为文件树、读取、预览和下载的真实根。"""
    client, _, _ = coding_client

    tree = client.get("/api/coding/tree", params={"project_id": "project-a"})
    read = client.post(
        "/api/coding/read",
        json={"project_id": "project-a", "path": "sample.txt"},
    )
    preview = client.get(
        "/api/coding/preview/file",
        params={"project_id": "project-a", "path": "sample.txt"},
    )
    download = client.get(
        "/api/coding/download",
        params={"project_id": "project-a", "path": "sample.bin"},
    )

    assert tree.json()["root"] == "."
    assert str(project_root.resolve()) not in tree.text
    assert read.json()["content"] == "仅来自临时项目"
    assert preview.json()["content"] == "仅来自临时项目"
    assert download.content == b"temporary-project"
    assert "attachment" in download.headers["content-disposition"]


def test_preview_download_link_preserves_project_id(coding_client) -> None:
    """预览降级生成的下载链接必须携带同一个不透明项目 ID。"""
    client, _, _ = coding_client

    response = client.get(
        "/api/coding/preview/file",
        params={"project_id": "project-a", "path": "office.docx"},
    )

    assert response.status_code == 200
    parsed = urlparse(response.json()["url"])
    assert parsed.path == "/api/coding/download"
    assert parse_qs(parsed.query) == {
        "path": ["office.docx"],
        "project_id": ["project-a"],
    }


@pytest.mark.parametrize("path", (".env", "../outside.txt"))
def test_file_read_keeps_secondary_path_validation(coding_client, path: str) -> None:
    """统一根解析后仍必须保留敏感文件与项目边界二次校验。"""
    client, calls, _ = coding_client

    response = client.post(
        "/api/coding/read",
        json={"project_id": "project-a", "path": path},
    )

    assert response.status_code == 403
    assert len(calls) == 1


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    (
        ("GET", "/api/coding/tree", {"path": "../"}),
        ("GET", "/api/coding/list", {"path": "../"}),
        (
            "POST",
            "/api/coding/search-files",
            {"pattern": "outside", "directory": "../"},
        ),
    ),
)
def test_directory_endpoints_reject_paths_outside_resolved_project(
    coding_client,
    method: str,
    path: str,
    payload: dict[str, str],
) -> None:
    """目录浏览与搜索也必须执行项目边界二次校验。"""
    client, calls, _ = coding_client
    request_data = {"project_id": "project-a", **payload}

    if method == "GET":
        response = client.get(path, params=request_data)
    else:
        response = client.post(path, json=request_data)

    assert response.status_code == 403
    assert len(calls) == 1


def test_ast_structure_rejects_path_outside_resolved_project(coding_client) -> None:
    """AST 单文件结构查询不得绕过项目边界二次校验。"""
    client, calls, _ = coding_client

    response = client.get(
        "/api/coding/ast/structure",
        params={"project_id": "project-a", "file_path": "../outside.py"},
    )

    assert response.status_code == 403
    assert len(calls) == 1


def test_tree_does_not_follow_symlink_outside_project(
    coding_client,
    project_root: Path,
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    """目录树不得沿项目内符号链接读取允许根外的目录。"""
    outside = tmp_path_factory.mktemp("coding-outside")
    (outside / "outside-secret.txt").write_text("不应出现在树中", encoding="utf-8")
    link = project_root / "linked-outside"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"当前环境无法创建目录符号链接: {exc}")

    client, _, _ = coding_client
    response = client.get(
        "/api/coding/tree",
        params={"project_id": "project-a"},
    )

    assert response.status_code == 200
    assert "outside-secret.txt" not in response.text


def test_ast_search_does_not_read_symlinked_file_outside_project(
    coding_client,
    project_root: Path,
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    """AST 全仓搜索不得读取项目根外的符号链接文件。"""
    outside = tmp_path_factory.mktemp("coding-ast-outside")
    outside_file = outside / "outside.py"
    outside_file.write_text(
        "def outside_secret_function():\n    return 'secret'\n",
        encoding="utf-8",
    )
    link = project_root / "linked-outside.py"
    try:
        link.symlink_to(outside_file)
    except OSError as exc:
        pytest.skip(f"当前环境无法创建文件符号链接: {exc}")

    client, _, _ = coding_client
    response = client.get(
        "/api/coding/ast/definitions",
        params={"project_id": "project-a", "name": "outside_secret_function"},
    )

    assert response.status_code == 200
    assert response.json()["results"] == []


def test_file_search_skips_symlinked_file_outside_project(
    coding_client,
    project_root: Path,
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    """文件名搜索不得泄露项目根外符号链接目标的元数据。"""
    outside = tmp_path_factory.mktemp("coding-search-outside")
    outside_file = outside / "outside-secret.txt"
    outside_file.write_text("secret", encoding="utf-8")
    link = project_root / "linked-outside-secret.txt"
    try:
        link.symlink_to(outside_file)
    except OSError as exc:
        pytest.skip(f"当前环境无法创建文件符号链接: {exc}")

    client, _, _ = coding_client
    response = client.post(
        "/api/coding/search-files",
        json={
            "project_id": "project-a",
            "pattern": "linked-outside-secret",
            "directory": "",
        },
    )

    assert response.status_code == 200
    assert response.json()["results"] == []


@pytest.mark.parametrize("case", _ROOT_ENDPOINTS, ids=lambda case: case.name)
def test_query_endpoints_reject_explicit_blank_legacy_project_dir(
    coding_client,
    case: _EndpointCase,
) -> None:
    """查询参数入口显式提交空旧字段时也必须 fail-closed。"""
    if case.location != "query":
        pytest.skip("该入口的项目身份位于请求体")
    client, calls, _ = coding_client
    data = {"project_id": "project-a", "project_dir": "", **case.data}

    if case.method == "GET":
        response = client.get(case.path, params=data)
    else:
        response = client.post(case.path, params=data)

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "legacy_project_path_not_supported"
    assert response.headers["sunset"] == "2026-09-01"
    assert calls == []


@pytest.mark.parametrize(
    ("path", "params"),
    (
        (
            "/api/coding/git/diff",
            {"project_id": "project-a", "file_path": ":(glob)**"},
        ),
        (
            "/api/coding/git/commit",
            {
                "project_id": "project-a",
                "message": "不应执行",
                "files": ["../outside.txt"],
            },
        ),
    ),
)
def test_git_file_arguments_reject_pathspec_magic_and_escape(
    coding_client,
    path: str,
    params: dict[str, Any],
) -> None:
    """Git 文件参数只能是项目内普通相对路径。"""
    client, calls, _ = coding_client

    if path.endswith("/diff"):
        response = client.get(path, params=params)
    else:
        response = client.post(path, json=params)

    assert response.status_code == 403
    assert len(calls) == 1


def test_download_rejects_file_swapped_after_path_validation(
    coding_client,
    project_root: Path,
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """下载必须复核实际打开句柄，不能跟随校验后的 symlink 调包。"""
    outside = tmp_path_factory.mktemp("coding-download-outside")
    outside_file = outside / "outside-secret.bin"
    outside_file.write_bytes(b"outside-secret")
    target = project_root / "sample.bin"
    original_validate = coding._validate_file_path
    swapped = False

    def _validate_then_swap(file_path: str, project_dir: str, *, is_write: bool = False):
        nonlocal swapped
        validated = original_validate(file_path, project_dir, is_write=is_write)
        if not swapped:
            target.unlink()
            try:
                target.symlink_to(outside_file)
            except OSError as exc:
                pytest.skip(f"当前环境无法创建文件符号链接: {exc}")
            swapped = True
        return validated

    monkeypatch.setattr(coding, "_validate_file_path", _validate_then_swap)
    client, _, _ = coding_client

    response = client.get(
        "/api/coding/download",
        params={"project_id": "project-a", "path": "sample.bin"},
    )

    assert response.status_code == 403
    assert response.content != b"outside-secret"
