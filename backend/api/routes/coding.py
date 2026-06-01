"""
Coding 模式 API 路由。
提供文件树、Git 操作、AST 搜索和 Diff 接口。
"""
import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.core.coding.file_tree import FileTreeService
from backend.core.coding.git_integration import GitIntegration
from backend.core.coding.ast_search import ASTSearchService
from backend.core.coding.diff_engine import DiffEngine

router = APIRouter(prefix="/api/coding", tags=["coding"])

# 默认项目目录（可配置）
DEFAULT_PROJECT_DIR = os.getenv("CODING_PROJECT_DIR", os.getcwd())


def _get_project_dir(project_dir: Optional[str] = None) -> str:
    """获取项目根目录。"""
    return project_dir or DEFAULT_PROJECT_DIR


# ---- Request Schemas ----

class FileReadRequest(BaseModel):
    path: str = ""
    project_dir: Optional[str] = None


class FileWriteRequest(BaseModel):
    path: str
    content: str
    project_dir: Optional[str] = None


class SearchRequest(BaseModel):
    pattern: str
    project_dir: Optional[str] = None


class GitCommitRequest(BaseModel):
    message: str
    files: Optional[list[str]] = None
    project_dir: Optional[str] = None


class DiffRequest(BaseModel):
    original: str
    modified: str


class FileSearchRequest(BaseModel):
    pattern: str
    directory: str = ""
    project_dir: Optional[str] = None


# ---- 文件树接口 ----

@router.get("/tree")
def get_file_tree(path: str = "", project_dir: Optional[str] = None):
    """
    获取目录树结构。
    """
    root = _get_project_dir(project_dir)
    service = FileTreeService(root)
    return service.get_tree(path)


@router.get("/list")
def list_directory(path: str = "", project_dir: Optional[str] = None):
    """
    列出目录内容。
    """
    root = _get_project_dir(project_dir)
    service = FileTreeService(root)
    return service.list_directory(path)


@router.post("/read")
def read_file(body: FileReadRequest):
    """
    读取文件内容。
    """
    root = _get_project_dir(body.project_dir)
    service = FileTreeService(root)
    result = service.read_file(body.path)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.post("/write")
def write_file(body: FileWriteRequest):
    """
    写入文件内容。
    """
    root = _get_project_dir(body.project_dir)
    service = FileTreeService(root)
    result = service.write_file(body.path, body.content)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/search-files")
def search_files(body: FileSearchRequest):
    """
    按文件名搜索。
    """
    root = _get_project_dir(body.project_dir)
    service = FileTreeService(root)
    results = service.search_files(body.pattern, body.directory)
    return {"results": results, "count": len(results)}


# ---- Git 接口 ----

@router.get("/git/status")
def git_status(project_dir: Optional[str] = None):
    """
    获取 Git 仓库状态。
    """
    root = _get_project_dir(project_dir)
    git = GitIntegration(root)
    if not git.is_repo():
        return {"error": "不是 Git 仓库", "is_repo": False}
    result = git.get_status()
    result["is_repo"] = True
    return result


@router.get("/git/diff")
def git_diff(file_path: Optional[str] = None, staged: bool = False, project_dir: Optional[str] = None):
    """
    获取 Git 差异。
    """
    root = _get_project_dir(project_dir)
    git = GitIntegration(root)
    return git.get_diff(file_path, staged)


@router.get("/git/log")
def git_log(max_count: int = 20, project_dir: Optional[str] = None):
    """
    获取 Git 提交日志。
    """
    root = _get_project_dir(project_dir)
    git = GitIntegration(root)
    return git.get_log(max_count)


@router.post("/git/commit")
def git_commit(body: GitCommitRequest):
    """
    提交 Git 更改。
    """
    root = _get_project_dir(body.project_dir)
    git = GitIntegration(root)
    return git.commit(body.message, body.files)


@router.get("/git/branches")
def git_branches(project_dir: Optional[str] = None):
    """
    获取分支列表。
    """
    root = _get_project_dir(project_dir)
    git = GitIntegration(root)
    return git.get_branches()


@router.post("/git/branch")
def git_create_branch(name: str, project_dir: Optional[str] = None):
    """
    创建新分支。
    """
    root = _get_project_dir(project_dir)
    git = GitIntegration(root)
    return git.create_branch(name)


# ---- AST 搜索接口 ----

@router.get("/ast/definitions")
def ast_search_definitions(name: str, project_dir: Optional[str] = None):
    """
    搜索函数/类定义。
    """
    root = _get_project_dir(project_dir)
    service = ASTSearchService(root)
    results = service.search_definitions(name)
    return {"results": results, "count": len(results)}


@router.get("/ast/references")
def ast_search_references(name: str, project_dir: Optional[str] = None):
    """
    搜索变量/函数引用。
    """
    root = _get_project_dir(project_dir)
    service = ASTSearchService(root)
    results = service.search_references(name)
    return {"results": results, "count": len(results)}


@router.post("/ast/search")
def ast_search_pattern(body: SearchRequest):
    """
    正则模式搜索代码。
    """
    root = _get_project_dir(body.project_dir)
    service = ASTSearchService(root)
    results = service.search_pattern(body.pattern)
    return {"results": results, "count": len(results)}


@router.get("/ast/structure")
def ast_get_structure(file_path: str, project_dir: Optional[str] = None):
    """
    获取文件结构概览。
    """
    root = _get_project_dir(body=None)  # Use default
    service = ASTSearchService(_get_project_dir(project_dir))
    return service.get_structure(file_path)


# ---- Diff 接口 ----

@router.post("/diff")
def compute_diff(body: DiffRequest):
    """
    计算文本差异。
    """
    engine = DiffEngine()
    return engine.compute_inline_diff(body.original, body.modified)
