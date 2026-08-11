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
    ),
    _EndpointCase("git-branches", "GET", "/api/coding/git/branches", "query", {}),
    _EndpointCase(
        "git-branch",
        "POST",
        "/api/coding/git/branch",
        "query",
        {"name": "test-branch"},
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


@pytest.mark.parametrize(
    ("error", "status_code", "code"),
    (
        (ProjectNotFound(), 404, "workbench_project_not_found"),
        (ProjectDisabled(), 409, "workbench_project_disabled"),
        (ProjectRootChanged(), 409, "workbench_project_root_changed"),
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

    assert tree.json()["root"] == str(project_root.resolve())
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
