"""
Coding 模式 API 路由。
提供文件树、Git 操作、AST 搜索和 Diff 接口。
"""
import html as _html_module
import os
import re
from pathlib import Path
from typing import Optional
from urllib.parse import quote as _url_quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from loguru import logger
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.dependencies import get_current_user
from core.coding.file_tree import FileTreeService
from core.coding.git_integration import GitIntegration
from core.coding.ast_search import ASTSearchService
from core.coding.diff_engine import DiffEngine
from db.models import User, get_db
from security.sandbox import is_path_allowed

router = APIRouter(prefix="/api/coding", tags=["coding"])

# 默认项目目录（可配置）
DEFAULT_PROJECT_DIR = os.getenv("CODING_PROJECT_DIR", os.getcwd())

# ---- 敏感文件 deny 列表（P0-4）----
# 敏感文件扩展名：命中即拒绝读取/预览，避免泄露密钥与凭证
_DENY_FILE_EXTENSIONS: frozenset[str] = frozenset({
    ".env",
    ".key",        # 私钥
    ".pem",        # 证书/私钥
    ".pfx",        # PKCS#12 证书
    ".p12",        # PKCS#12 证书
    ".keystore",   # Java 密钥库
    ".htpasswd",    # Apache 密码文件
    ".netrc",      # 网络凭证
    ".npmrc",      # npm 认证令牌
    ".pypirc",     # PyPI 认证令牌
    ".gitconfig",  # Git 全局配置（可能含 token）
})

# 敏感文件名（basename 精确匹配）：命中即拒绝
_DENY_FILE_NAMES: frozenset[str] = frozenset({
    ".env",
    ".env.local",
    ".env.production",
    ".env.development",
    ".env.staging",
    "credentials.json",       # 云凭证（GCP/AWS）
    "secrets.json",
    "secrets.yaml",
    "secrets.yml",
    "id_rsa",                 # SSH 私钥
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    "authorized_keys",
    "known_hosts",
    ".htpasswd",
    ".netrc",
    ".npmrc",
    ".pypirc",
    "wallet.dat",             # 加密货币钱包
})

# 敏感文件路径正则：匹配即拒绝
_DENY_FILE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(^|[/\\])\.env($|\.[a-zA-Z0-9_-]+$)"),      # .env 及其变体
    re.compile(r"(^|[/\\])\.git[/\\]"),                       # Git 元数据目录
    re.compile(r"(^|[/\\])\.ssh[/\\]"),                        # SSH 目录
    re.compile(r"(^|[/\\])\.aws[/\\]"),                        # AWS 凭证目录
    re.compile(r"(^|[/\\])\.docker[/\\]"),                     # Docker 配置目录
    re.compile(r"(^|[/\\])\.kube[/\\]"),                       # Kubernetes 配置目录
    re.compile(r"_secrets\.(json|ya?ml|ini|toml|env)$", re.IGNORECASE),  # 通用 secrets 文件
]


def _is_sensitive_file(file_path: str) -> bool:
    """判断文件路径是否命中敏感文件 deny 列表。

    检查顺序：扩展名 → 文件名 basename → 路径正则。
    任一命中即返回 True。

    Args:
        file_path: 待检查的文件路径（相对或绝对均可）。

    Returns:
        True 表示该文件为敏感文件，应拒绝访问。
    """
    if not file_path:
        return False

    path_obj = Path(file_path)
    ext = path_obj.suffix.lower()
    if ext in _DENY_FILE_EXTENSIONS:
        return True

    name = path_obj.name.lower()
    if name in _DENY_FILE_NAMES:
        return True

    # 同时检查原始路径与标准化路径，兼容 Windows 反斜杠
    normalized = file_path.replace("\\", "/")
    for pattern in _DENY_FILE_PATTERNS:
        if pattern.search(file_path) or pattern.search(normalized):
            return True

    return False


async def _check_coding_permission(
    current_user: User,
    permission: str,
    db: Session,
) -> None:
    """检查 coding 模块权限。

    管理员自动放行。其他用户通过 RBAC 校验：
    - 用户无显式角色分配时降级放行（保持兼容性，BUILT_IN_ROLES 未含 coding 权限）
    - 用户有显式角色分配但无对应权限时拒绝
    - DB 异常时降级放行，避免 DB 故障导致服务不可用

    Args:
        current_user: 当前认证用户。
        permission: 权限标识，如 "coding:read" / "coding:write"。
        db: 数据库会话。

    Raises:
        HTTPException: 权限不足时抛 403。
    """
    # 管理员直接放行
    if getattr(current_user, "role", None) == "admin":
        return

    try:
        from security.rbac import RBACManager
        from db.models import UserRole

        rbac = RBACManager(db)
        user_id = str(current_user.id)

        # 检查是否有显式角色分配
        user_role_record = (
            db.query(UserRole)
            .filter(UserRole.user_id == user_id)
            .first()
        )
        if user_role_record is None:
            # 无显式角色分配，BUILT_IN_ROLES 未含 coding 权限，降级放行
            logger.info(f"用户 {user_id} 无显式角色分配，coding 权限降级放行")
            return

        # 有显式角色分配，按 RBAC 判定
        allowed = await rbac.check_permission(user_id, permission)
        if not allowed:
            raise HTTPException(
                status_code=403,
                detail=f"权限不足，需要 {permission} 权限或管理员角色"
            )
    except HTTPException:
        raise
    except Exception as exc:
        # RBAC 检查异常时降级放行，避免 DB 故障导致服务不可用
        logger.warning(
            f"RBAC 检查异常，降级放行: user_id={current_user.id}, "
            f"permission={permission}, error={exc}"
        )
        return

# ---- 可选依赖：Markdown 渲染与净化 ----
# 故意放在模块顶层 try/except 中，避免在 requirements.txt 中强制依赖
try:
    import markdown as _markdown_lib  # type: ignore
except ImportError:
    _markdown_lib = None  # type: ignore

try:
    import bleach as _bleach_lib  # type: ignore
except ImportError:
    _bleach_lib = None  # type: ignore


def _get_project_dir(project_dir: Optional[str] = None) -> str:
    """获取项目根目录。"""
    raw = project_dir or DEFAULT_PROJECT_DIR
    # 防止通过 project_dir 参数遍历到系统根目录
    resolved = Path(os.path.realpath(os.path.abspath(raw))).resolve()
    default_resolved = Path(os.path.realpath(os.path.abspath(DEFAULT_PROJECT_DIR))).resolve()
    # 使用 relative_to 替代 startswith，防止前缀绕过（符号链接/短文件名/大小写等场景）
    try:
        resolved.relative_to(default_resolved)
    except ValueError:
        raise HTTPException(status_code=403, detail="禁止访问指定项目目录")
    return str(resolved)


def _validate_file_path(file_path: str, project_dir: str, *, is_write: bool = False) -> str:
    """
    校验文件路径在项目目录内，防止路径遍历攻击，并复用沙箱 deny 列表。

    三层防护：
    1. 敏感文件 deny 列表：命中即拒绝（.env、*.key、*.pem 等）
    2. 自有路径遍历防护：确保解析后路径在项目目录内
    3. 沙箱 is_path_allowed：复用全局 deny 规则与 TOCTOU 防护

    Args:
        file_path: 待校验的文件路径（相对项目目录）。
        project_dir: 项目根目录（已通过 _get_project_dir 校验）。
        is_write: 是否为写操作，写操作更严格（禁止 glob、禁止 .. 穿越）。

    Returns:
        解析后的绝对路径。

    Raises:
        HTTPException: 路径越权、命中敏感文件或被沙箱拒绝时抛 403。
    """
    # 第 1 层：敏感文件 deny 列表
    if _is_sensitive_file(file_path):
        logger.warning(f"敏感文件访问被拒绝: {file_path}")
        raise HTTPException(status_code=403, detail="禁止访问敏感文件")

    # 第 2 层：自有路径遍历防护（使用 relative_to 替代 startswith，防前缀绕过）
    root_real = Path(os.path.realpath(project_dir)).resolve()
    resolved = Path(os.path.realpath(os.path.join(str(root_real), file_path.lstrip("/\\")))).resolve()
    try:
        resolved.relative_to(root_real)
    except ValueError:
        if resolved != root_real:
            raise HTTPException(status_code=403, detail="禁止访问项目目录外的文件")

    # 第 3 层：复用沙箱 is_path_allowed（含 .env deny 规则、TOCTOU 防护）
    if not is_path_allowed(str(resolved), is_write=is_write, working_dir=str(root_real)):
        logger.warning(f"路径被沙箱拒绝: {file_path} (resolved={resolved})")
        raise HTTPException(status_code=403, detail="路径被沙箱安全策略拒绝")

    return str(resolved)


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
async def read_file(
    body: FileReadRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    读取文件内容。
    """
    # P0-4: RBAC 权限校验
    await _check_coding_permission(current_user, "coding:read", db)
    root = _get_project_dir(body.project_dir)
    # P0-4: 路径校验（含敏感文件 deny 列表与沙箱策略）
    _validate_file_path(body.path, root, is_write=False)
    service = FileTreeService(root)
    result = service.read_file(body.path)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.post("/write")
async def write_file(
    body: FileWriteRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    写入文件内容。
    """
    # P0-4: RBAC 权限校验
    await _check_coding_permission(current_user, "coding:write", db)
    root = _get_project_dir(body.project_dir)
    # P0-4: 路径校验（写操作更严格，禁止 glob 与 .. 穿越）
    _validate_file_path(body.path, root, is_write=True)
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
def toggle_cc_mode(body: CCModeRequest, current_user: User = Depends(get_current_user)):
    """
    启用或禁用 Claude Code 兼容模式。
    CC 模式下会注入 Coding 专用系统提示和工具定义。
    """
    user_id = str(current_user.id)
    _cc_mode_sessions[user_id] = body.enabled
    return {"success": True, "cc_mode_enabled": body.enabled}


@router.get("/cc-mode")
def get_cc_mode(current_user: User = Depends(get_current_user)):
    """
    获取当前用户的 CC 模式状态。
    """
    user_id = str(current_user.id)
    return {"cc_mode_enabled": _cc_mode_sessions.get(user_id, False)}


# ---- 文件预览接口 ----

# 图片 MIME 映射
_IMAGE_MIME_MAP: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
}

# 音频 MIME 映射
_AUDIO_MIME_MAP: dict[str, str] = {
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".ogg": "audio/ogg",
}

# 视频 MIME 映射
_VIDEO_MIME_MAP: dict[str, str] = {
    ".mp4": "video/mp4",
    ".webm": "video/webm",
}

# 文本类 MIME 映射
_TEXT_MIME_MAP: dict[str, str] = {
    ".txt": "text/plain; charset=utf-8",
    ".log": "text/plain; charset=utf-8",
    ".py": "text/x-python; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".ts": "application/typescript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".htm": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".xml": "application/xml; charset=utf-8",
    ".yaml": "application/x-yaml; charset=utf-8",
    ".yml": "application/x-yaml; charset=utf-8",
    ".ini": "text/plain; charset=utf-8",
    ".toml": "text/plain; charset=utf-8",
    ".sh": "application/x-sh; charset=utf-8",
    ".bat": "text/plain; charset=utf-8",
    ".ps1": "text/plain; charset=utf-8",
}

# Office 扩展名集合
_OFFICE_EXTS: set[str] = {".docx", ".xlsx", ".pptx"}

# 流式读取的块大小
_STREAM_CHUNK_SIZE = 64 * 1024  # 64KB


def _download_link_response(original_path: str, error: Optional[str] = None) -> dict:
    """生成 Office 文件降级用的下载链接响应体。"""
    payload: dict = {
        "type": "download",
        "url": f"/api/coding/download?path={_url_quote(original_path)}",
    }
    if error:
        payload["error"] = error
    return payload


def _render_markdown_file(abs_path: str) -> dict:
    """将 Markdown 文件渲染为净化后的 HTML。

    若 markdown/bleach 未安装，则降级为 <pre> 包裹的纯文本。
    """
    try:
        with open(abs_path, "r", encoding="utf-8") as fh:
            md_text = fh.read()
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"读取文件失败: {exc}")

    if _markdown_lib is None or _bleach_lib is None:
        # 优雅降级：返回 <pre> 包裹的 HTML 转义文本
        escaped = _html_module.escape(md_text)
        return {
            "type": "markdown",
            "html": f"<pre>{escaped}</pre>",
            "error": "markdown or bleach library not installed",
        }

    try:
        raw_html = _markdown_lib.markdown(
            md_text,
            extensions=["extra", "fenced_code", "tables", "sane_lists"],
        )
        cleaned_html = _bleach_lib.clean(
            raw_html,
            tags={
                "h1", "h2", "h3", "h4", "h5", "h6",
                "p", "br", "hr",
                "strong", "em", "b", "i", "u", "s", "del", "ins", "sub", "sup",
                "ul", "ol", "li",
                "blockquote", "code", "pre",
                "a", "img",
                "table", "thead", "tbody", "tfoot", "tr", "th", "td",
                "div", "span", "abbr", "cite", "q",
            },
            attributes={
                "a": ["href", "title", "target", "rel"],
                "img": ["src", "alt", "title", "width", "height"],
                "span": ["class"],
                "div": ["class"],
                "code": ["class"],
                "pre": ["class"],
                "td": ["colspan", "rowspan"],
                "th": ["colspan", "rowspan"],
            },
            protocols=["http", "https", "mailto", "tel"],
            strip=True,
        )
        return {"type": "markdown", "html": cleaned_html}
    except Exception as exc:
        escaped = _html_module.escape(md_text)
        return {
            "type": "markdown",
            "html": f"<pre>{escaped}</pre>",
            "error": f"markdown rendering failed: {exc}",
        }


def _stream_binary_file(
    abs_path: str,
    content_type: str,
    request: Request,
    support_range: bool,
) -> StreamingResponse:
    """流式返回二进制文件，可选支持 Range 请求。"""
    file_size = os.path.getsize(abs_path)

    range_header = request.headers.get("range") if support_range else None
    if range_header:
        try:
            range_spec = range_header.strip()
            if range_spec.startswith("bytes="):
                range_spec = range_spec[len("bytes="):]
            start_str, _, end_str = range_spec.partition("-")
            start = int(start_str) if start_str else 0
            end = int(end_str) if end_str else file_size - 1
            if start < 0 or start >= file_size or end >= file_size or start > end:
                raise ValueError("invalid range")
        except (ValueError, IndexError):
            raise HTTPException(
                status_code=416,
                detail="Range Not Satisfiable",
                headers={"Content-Range": f"bytes */{file_size}"},
            )

        content_length = end - start + 1

        def _iter_range() -> bytes:
            with open(abs_path, "rb") as fh:
                fh.seek(start)
                remaining = content_length
                while remaining > 0:
                    chunk = fh.read(min(_STREAM_CHUNK_SIZE, remaining))
                    if not chunk:
                        break
                    yield chunk
                    remaining -= len(chunk)

        return StreamingResponse(
            _iter_range(),
            status_code=206,
            media_type=content_type,
            headers={
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Content-Length": str(content_length),
                "Accept-Ranges": "bytes",
            },
        )

    def _iter_full() -> bytes:
        with open(abs_path, "rb") as fh:
            while True:
                chunk = fh.read(_STREAM_CHUNK_SIZE)
                if not chunk:
                    break
                yield chunk

    return StreamingResponse(
        _iter_full(),
        media_type=content_type,
        headers={
            "Content-Length": str(file_size),
            "Accept-Ranges": "bytes",
        },
    )


def _render_office_file(abs_path: str, original_path: str) -> dict:
    """渲染 Office 文件。

    优先尝试 mammoth / openpyxl / python-pptx，缺失或失败时降级为下载链接。
    """
    ext = Path(abs_path).suffix.lower()

    if ext == ".docx":
        try:
            import mammoth  # type: ignore
        except ImportError:
            return _download_link_response(
                original_path, error="mammoth library not installed"
            )
        try:
            with open(abs_path, "rb") as fh:
                result = mammoth.convert_to_html(fh)
            return {"type": "markdown", "html": result.value}
        except Exception as exc:
            return _download_link_response(original_path, error=str(exc))

    if ext == ".xlsx":
        try:
            import openpyxl  # type: ignore
        except ImportError:
            return _download_link_response(
                original_path, error="openpyxl library not installed"
            )
        try:
            wb = openpyxl.load_workbook(abs_path, read_only=True)
            sheet_names = wb.sheetnames
            list_html = (
                "<ul>" + "".join(f"<li>{_html_module.escape(s)}</li>" for s in sheet_names) + "</ul>"
            )
            return {"type": "markdown", "html": list_html}
        except Exception as exc:
            return _download_link_response(original_path, error=str(exc))

    if ext == ".pptx":
        try:
            from pptx import Presentation  # type: ignore
        except ImportError:
            return _download_link_response(
                original_path, error="python-pptx library not installed"
            )
        try:
            prs = Presentation(abs_path)
            slide_count = len(prs.slides)
            return {
                "type": "markdown",
                "html": f"<p>共 {slide_count} 张幻灯片</p>",
            }
        except Exception as exc:
            return _download_link_response(original_path, error=str(exc))

    return _download_link_response(original_path)


@router.get("/preview/file")
async def preview_file(
    path: str,
    request: Request,
    project_dir: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    预览文件内容：按扩展名返回适当格式。

    - Markdown (.md/.markdown)：渲染为 HTML 并经 bleach 净化
    - 图片 (.png/.jpg/.jpeg/.gif/.webp/.svg)：StreamingResponse + 正确 Content-Type
    - 音视频 (.mp3/.wav/.mp4/.webm/.ogg)：StreamingResponse + Range 支持
    - Office (.docx/.xlsx/.pptx)：尝试 mammoth/openpyxl/python-pptx，缺失降级为下载链接
    - 文本类：返回 {type:text, content:...}
    - 其他：返回下载链接

    所有路径校验通过 _validate_file_path 防止路径遍历，并应用敏感文件 deny 列表。
    """
    # P0-4: RBAC 权限校验
    await _check_coding_permission(current_user, "coding:read", db)
    root = _get_project_dir(project_dir)
    # P0-4: 路径校验（含敏感文件 deny 列表与沙箱策略）
    abs_path = _validate_file_path(path, root, is_write=False)

    if not os.path.isfile(abs_path):
        raise HTTPException(status_code=404, detail="文件不存在或不是常规文件")

    ext = Path(abs_path).suffix.lower()

    # Markdown 渲染
    if ext in (".md", ".markdown"):
        return _render_markdown_file(abs_path)

    # 图片
    if ext in _IMAGE_MIME_MAP:
        return _stream_binary_file(
            abs_path, _IMAGE_MIME_MAP[ext], request, support_range=False
        )

    # 音频
    if ext in _AUDIO_MIME_MAP:
        return _stream_binary_file(
            abs_path, _AUDIO_MIME_MAP[ext], request, support_range=True
        )

    # 视频
    if ext in _VIDEO_MIME_MAP:
        return _stream_binary_file(
            abs_path, _VIDEO_MIME_MAP[ext], request, support_range=True
        )

    # Office 文件
    if ext in _OFFICE_EXTS:
        return _render_office_file(abs_path, path)

    # 文本类
    if ext in _TEXT_MIME_MAP:
        try:
            with open(abs_path, "r", encoding="utf-8") as fh:
                content = fh.read()
            return {
                "type": "text",
                "content": content,
                "mime": _TEXT_MIME_MAP[ext],
            }
        except UnicodeDecodeError:
            # 编码失败，回退到下载
            return _download_link_response(path)

    # 未知类型：返回下载链接
    return _download_link_response(path)
