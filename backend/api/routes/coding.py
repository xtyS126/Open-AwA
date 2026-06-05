"""
Coding 模式 API 路由。
提供文件树、Git 操作、AST 搜索和 Diff 接口。
"""
import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.dependencies import get_current_user
from core.coding.file_tree import FileTreeService
from core.coding.git_integration import GitIntegration
from core.coding.ast_search import ASTSearchService
from core.coding.diff_engine import DiffEngine

router = APIRouter(prefix="/api/coding", tags=["coding"])

# 默认项目目录（可配置）
DEFAULT_PROJECT_DIR = os.getenv("CODING_PROJECT_DIR", os.getcwd())


def _get_project_dir(project_dir: Optional[str] = None) -> str:
    """获取项目根目录。"""
    raw = project_dir or DEFAULT_PROJECT_DIR
    # 防止通过 project_dir 参数遍历到系统根目录
    resolved = os.path.realpath(os.path.abspath(raw))
    default_resolved = os.path.realpath(os.path.abspath(DEFAULT_PROJECT_DIR))
    # 仅当请求目录在默认项目目录子树内或等于默认目录时放行
    if not (resolved == default_resolved or resolved.startswith(default_resolved + os.sep)):
        raise HTTPException(status_code=403, detail="禁止访问指定项目目录")
    return resolved


def _validate_file_path(file_path: str, project_dir: str) -> str:
    """
    校验文件路径在项目目录内，防止路径遍历攻击。
    返回解析后的绝对路径。
    """
    root_real = os.path.realpath(project_dir)
    resolved = os.path.realpath(os.path.join(root_real, file_path.lstrip("/\\")))
    if not resolved.startswith(root_real + os.sep) and resolved != root_real:
        raise HTTPException(status_code=403, detail="禁止访问项目目录外的文件")
    return resolved


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
def get_file_tree(path: str = "", project_dir: Optional[str] = None, current_user=Depends(get_current_user)):
    """
    获取目录树结构。
    """
    root = _get_project_dir(project_dir)
    service = FileTreeService(root)
    return service.get_tree(path)


@router.get("/list")
def list_directory(path: str = "", project_dir: Optional[str] = None, current_user=Depends(get_current_user)):
    """
    列出目录内容。
    """
    root = _get_project_dir(project_dir)
    service = FileTreeService(root)
    return service.list_directory(path)


@router.post("/read")
def read_file(body: FileReadRequest, current_user=Depends(get_current_user)):
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
def write_file(body: FileWriteRequest, current_user=Depends(get_current_user)):
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
def search_files(body: FileSearchRequest, current_user=Depends(get_current_user)):
    """
    按文件名搜索。
    """
    root = _get_project_dir(body.project_dir)
    service = FileTreeService(root)
    results = service.search_files(body.pattern, body.directory)
    return {"results": results, "count": len(results)}


# ---- Git 接口 ----

@router.get("/git/status")
def git_status(project_dir: Optional[str] = None, current_user=Depends(get_current_user)):
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
def git_diff(file_path: Optional[str] = None, staged: bool = False, project_dir: Optional[str] = None, current_user=Depends(get_current_user)):
    """
    获取 Git 差异。
    """
    root = _get_project_dir(project_dir)
    git = GitIntegration(root)
    return git.get_diff(file_path, staged)


@router.get("/git/log")
def git_log(max_count: int = 20, project_dir: Optional[str] = None, current_user=Depends(get_current_user)):
    """
    获取 Git 提交日志。
    """
    root = _get_project_dir(project_dir)
    git = GitIntegration(root)
    return git.get_log(max_count)


@router.post("/git/commit")
def git_commit(body: GitCommitRequest, current_user=Depends(get_current_user)):
    """
    提交 Git 更改。
    """
    root = _get_project_dir(body.project_dir)
    git = GitIntegration(root)
    return git.commit(body.message, body.files)


@router.get("/git/branches")
def git_branches(project_dir: Optional[str] = None, current_user=Depends(get_current_user)):
    """
    获取分支列表。
    """
    root = _get_project_dir(project_dir)
    git = GitIntegration(root)
    return git.get_branches()


@router.post("/git/branch")
def git_create_branch(name: str, project_dir: Optional[str] = None, current_user=Depends(get_current_user)):
    """
    创建新分支。
    """
    root = _get_project_dir(project_dir)
    git = GitIntegration(root)
    return git.create_branch(name)


# ---- AST 搜索接口 ----

@router.get("/ast/definitions")
def ast_search_definitions(name: str, project_dir: Optional[str] = None, current_user=Depends(get_current_user)):
    """
    搜索函数/类定义。
    """
    root = _get_project_dir(project_dir)
    service = ASTSearchService(root)
    results = service.search_definitions(name)
    return {"results": results, "count": len(results)}


@router.get("/ast/references")
def ast_search_references(name: str, project_dir: Optional[str] = None, current_user=Depends(get_current_user)):
    """
    搜索变量/函数引用。
    """
    root = _get_project_dir(project_dir)
    service = ASTSearchService(root)
    results = service.search_references(name)
    return {"results": results, "count": len(results)}


@router.post("/ast/search")
def ast_search_pattern(body: SearchRequest, current_user=Depends(get_current_user)):
    """
    正则模式搜索代码。
    """
    root = _get_project_dir(body.project_dir)
    service = ASTSearchService(root)
    results = service.search_pattern(body.pattern)
    return {"results": results, "count": len(results)}


@router.get("/ast/structure")
def ast_get_structure(file_path: str, project_dir: Optional[str] = None, current_user=Depends(get_current_user)):
    """
    获取文件结构概览。
    """
    root = _get_project_dir(project_dir)
    service = ASTSearchService(root)
    return service.get_structure(file_path)


# ---- Diff 接口 ----

@router.post("/diff")
def compute_diff(body: DiffRequest, current_user=Depends(get_current_user)):
    """
    计算文本差异。
    """
    engine = DiffEngine()
    return engine.compute_inline_diff(body.original, body.modified)


# ---- LSP 接口 ----

class LSPCompletionRequest(BaseModel):
    file_path: str
    line: int
    column: int
    project_dir: Optional[str] = None


class LSPHoverRequest(BaseModel):
    file_path: str
    line: int
    column: int
    project_dir: Optional[str] = None


@router.get("/lsp/diagnostics")
def get_lsp_diagnostics(file_path: str, project_dir: Optional[str] = None, current_user=Depends(get_current_user)):
    """
    获取文件的 LSP 诊断信息（错误/警告）。
    返回语言服务器的可用性和状态信息。
    """
    root = _get_project_dir(project_dir)
    _validate_file_path(file_path, root)
    try:
        ext = Path(file_path).suffix.lstrip(".").lower()
        lang_map = {"py": "python", "ts": "typescript", "tsx": "typescript", "js": "javascript", "jsx": "javascript"}
        language = lang_map.get(ext, ext)
        from core.coding.lsp_proxy import LSPProxy
        lsp = LSPProxy(root)
        available = lsp.is_available(language)
        return {
            "success": True,
            "language": language,
            "lsp_available": available,
            "diagnostics": [],
            "message": f"LSP 服务器{'可用' if available else '不可用'}: {language}",
        }
    except Exception as exc:
        return {"success": False, "diagnostics": [], "error": str(exc)}


@router.post("/lsp/completions")
def get_lsp_completions(body: LSPCompletionRequest, current_user=Depends(get_current_user)):
    """
    获取代码补全建议（基于 AST 静态分析）。
    注：完整 LSP 补全需通过前端 Monaco Editor 内置能力实现。
    """
    root = _get_project_dir(body.project_dir)
    _validate_file_path(body.file_path, root)
    try:
        from core.coding.ast_search import ASTSearchService
        service = ASTSearchService(root)
        # 基于当前文件提供符号补全
        structure = service.get_structure(body.file_path)
        return {
            "success": True,
            "completions": structure.get("symbols", [])[:20],
            "file_path": body.file_path,
        }
    except Exception as exc:
        return {"success": False, "completions": [], "error": str(exc)}


@router.post("/lsp/hover")
def get_lsp_hover(body: LSPHoverRequest, current_user=Depends(get_current_user)):
    """
    获取悬停信息（基于 AST 静态分析）。
    注：完整 LSP 悬停需通过前端 Monaco Editor 内置能力实现。
    """
    root = _get_project_dir(body.project_dir)
    _validate_file_path(body.file_path, root)
    try:
        from core.coding.ast_search import ASTSearchService
        service = ASTSearchService(root)
        structure = service.get_structure(body.file_path)
        return {
            "success": True,
            "hover": f"文件: {body.file_path}\n行: {body.line}, 列: {body.column}\n符号数: {len(structure.get('symbols', []))}",
            "file_path": body.file_path,
        }
    except Exception as exc:
        return {"success": False, "hover": "", "error": str(exc)}


@router.get("/lsp/symbols")
def get_lsp_symbols(file_path: str, project_dir: Optional[str] = None, current_user=Depends(get_current_user)):
    """
    获取文件的符号列表（基于 AST 静态分析）。
    """
    root = _get_project_dir(project_dir)
    _validate_file_path(file_path, root)
    try:
        from core.coding.ast_search import ASTSearchService
        service = ASTSearchService(root)
        structure = service.get_structure(file_path)
        return {"success": True, "symbols": structure.get("symbols", [])}
    except Exception as exc:
        return {"success": False, "symbols": [], "error": str(exc)}


# ---- Claude Code 模式 ----

class CCModeRequest(BaseModel):
    enabled: bool


# 按用户隔离的 CC 模式状态（user_id -> enabled），防止跨用户状态泄露
_cc_mode_sessions: dict[str, bool] = {}


@router.post("/cc-mode")
def toggle_cc_mode(body: CCModeRequest, current_user=Depends(get_current_user)):
    """
    启用或禁用 Claude Code 兼容模式。
    CC 模式下会注入 Coding 专用系统提示和工具定义。
    """
    user_id = str(getattr(current_user, "id", "default"))
    _cc_mode_sessions[user_id] = body.enabled
    return {"success": True, "cc_mode_enabled": body.enabled}


@router.get("/cc-mode")
def get_cc_mode(current_user=Depends(get_current_user)):
    """
    获取当前用户的 CC 模式状态。
    """
    user_id = str(getattr(current_user, "id", "default"))
    return {"cc_mode_enabled": _cc_mode_sessions.get(user_id, False)}
