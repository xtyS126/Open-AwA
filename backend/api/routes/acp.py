# -*- coding: utf-8 -*-
"""
ACP (Agent Client Protocol) HTTP API 路由。

为前端提供 ACP Agent 会话管理与流式 prompt 接口，所有端点强制鉴权。

安全策略：
1. 所有 HTTP 端点强制 Depends(get_current_user)
2. 浏览器只提交 project_id，服务端统一解析并复验项目根
3. agent 标识必须在 discover_agents() 列表中且 enabled=True
4. SSE 流式端点用 asyncio.to_thread 包裹同步探测，避免阻塞事件循环
5. 客户端断开时调用 ACPService.cancel_turn 取消未完成的 prompt

会话与 ACPService 桥接：
- 用 chat_id = f"{user_id}:{session_id}" 作为 ACPService 的 chat_id
- 通过 get_acp_service(agent) 获取对应 Agent 的 service 实例
- acp SDK 未安装时 run_turn 抛 ACPConfigurationError，SSE 流中捕获并推送 error 事件
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import uuid
from pathlib import Path
from typing import Any, Dict, List, NoReturn, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from loguru import logger
from pydantic import BaseModel, Field

from acp_host import get_acp_service
from acp_host.core import ACPConfigurationError, ACPSessionError
from acp_host.agents import (
    discover_agents,
    is_agent_available,
    resolve_agent_command,
)
from api.dependencies import get_current_user
from config.settings import settings
from db.models import SessionLocal, User, get_db
from sqlalchemy.orm import Session
from workbench.errors import (
    ProjectDisabled,
    ProjectNotFound,
    ProjectRootChanged,
    ProjectRootForbidden,
    ProjectRootInvalid,
    WorkbenchError,
)
from workbench import listener_ownership
from workbench.listener_registry import listener_verifier_registry
from workbench.path_policy import WorkbenchPathPolicy
from workbench.preview_lease import PreviewSessionKind, preview_lease_registry
from workbench.project_service import WorkbenchProjectService
from workbench.runtime_registry import (
    RuntimeResourceType,
    WorkbenchRuntimeRegistry,
    runtime_registry,
)


router = APIRouter(prefix="/acp", tags=["acp"])

_LEGACY_PROJECT_PATH_SUNSET = "2026-09-01"
_LEGACY_PROJECT_PATH_FIELDS = frozenset({"cwd", "project_dir", "projectCwd", "projectDir"})
_PRIVATE_ROOT_FIELD_NAMES = frozenset(
    {"userid", "registeredroot", "canonicalroot", "resolvedroot"},
)
_REDACTED_PATH = "[redacted-path]"
_QUOTED_ABSOLUTE_PATH_RE = re.compile(
    r"(?P<quote>['\"])(?P<path>(?:[A-Za-z]:[\\/]|/)[^'\"]+)(?P=quote)",
)
_WINDOWS_ABSOLUTE_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?P<path>[A-Za-z]:[\\/][^\s'\"<>|;,]+)",
)
_POSIX_ABSOLUTE_PATH_RE = re.compile(
    r"(?<![:.A-Za-z0-9_])(?P<path>/[^\s'\"<>|;,]+)",
)


def get_acp_workbench_path_policy() -> WorkbenchPathPolicy:
    """按当前设置构建 ACP 使用的工作台路径策略。"""
    return WorkbenchPathPolicy.from_settings(settings)


def get_acp_runtime_registry() -> WorkbenchRuntimeRegistry:
    return runtime_registry


def _detail(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def _raise_workbench_http_error(exc: WorkbenchError) -> NoReturn:
    """把工作台领域异常映射为 ACP API 结构化响应。"""
    status_code = status.HTTP_409_CONFLICT
    if isinstance(exc, ProjectNotFound):
        status_code = status.HTTP_404_NOT_FOUND
    elif isinstance(exc, ProjectRootForbidden):
        status_code = status.HTTP_403_FORBIDDEN
    elif isinstance(exc, ProjectRootInvalid):
        status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    elif isinstance(exc, (ProjectDisabled, ProjectRootChanged)):
        status_code = status.HTTP_409_CONFLICT
    raise HTTPException(
        status_code=status_code,
        detail=_detail(exc.code, exc.message),
    ) from exc


def _raise_legacy_project_path_error() -> NoReturn:
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=_detail(
            "legacy_project_path_not_supported",
            "不再支持客户端提供项目路径，请改用 project_id",
        ),
        headers={"Sunset": _LEGACY_PROJECT_PATH_SUNSET},
    )


def _reject_legacy_query_fields(request: Request) -> None:
    if _LEGACY_PROJECT_PATH_FIELDS.intersection(request.query_params.keys()):
        _raise_legacy_project_path_error()


def _reject_legacy_body_fields(body: BaseModel) -> None:
    if _LEGACY_PROJECT_PATH_FIELDS.intersection(body.model_fields_set):
        _raise_legacy_project_path_error()


def _require_project_id(project_id: Optional[str]) -> str:
    normalized = project_id.strip() if project_id is not None else ""
    if not normalized:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_detail("workbench_project_required", "请先选择工作台项目"),
        )
    return normalized


def _resolve_project_root(
    *,
    project_id: str,
    current_user: User,
    db: Session,
    path_policy: WorkbenchPathPolicy,
) -> Path:
    service = WorkbenchProjectService(db, path_policy)
    try:
        return service.resolve_project_root(
            user_id=str(current_user.id),
            user_role=str(current_user.role),
            project_id=project_id,
        )
    except WorkbenchError as exc:
        _raise_workbench_http_error(exc)


def _resolve_request_project(
    *,
    request: Request,
    project_id: Optional[str],
    current_user: User,
    db: Session,
    path_policy: WorkbenchPathPolicy,
) -> tuple[str, Path]:
    _reject_legacy_query_fields(request)
    normalized = _require_project_id(project_id)
    return normalized, _resolve_project_root(
        project_id=normalized,
        current_user=current_user,
        db=db,
        path_policy=path_policy,
    )


def _resolve_project_root_with_new_session(
    *,
    project_id: str,
    current_user: User,
    path_policy: WorkbenchPathPolicy,
) -> Path:
    """在独立短数据库会话中重新解析项目根。"""
    with SessionLocal() as fresh_db:
        return _resolve_project_root(
            project_id=project_id,
            current_user=current_user,
            db=fresh_db,
            path_policy=path_policy,
        )


async def _fresh_resolve_project_root(
    *,
    project_id: str,
    current_user: User,
    path_policy: WorkbenchPathPolicy,
    expected_root: Path | str,
) -> Path:
    """紧邻运行时消费点重验项目，并拒绝根快照变化。"""
    resolved_root = await asyncio.to_thread(
        _resolve_project_root_with_new_session,
        project_id=project_id,
        current_user=current_user,
        path_policy=path_policy,
    )
    if str(resolved_root) != str(expected_root):
        _raise_workbench_http_error(ProjectRootChanged())
    return resolved_root


def _normalize_private_field_name(value: object) -> str:
    """将字段名规范化为仅含小写字母数字的比较形式。"""
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def _path_display_value(value: str, project_root: Path) -> str:
    """把绝对路径投影为项目相对路径或稳定脱敏值。"""
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        return value
    try:
        relative = candidate.resolve(strict=False).relative_to(
            project_root.resolve(strict=False),
        )
    except (OSError, RuntimeError, ValueError):
        return _REDACTED_PATH
    return "." if not relative.parts else str(relative)


def _sanitize_public_text(value: str, project_root: Path) -> str:
    """清理任意文本中的项目内与根外绝对路径。"""
    stripped = value.strip()
    if stripped:
        direct = _path_display_value(stripped, project_root)
        if direct != stripped:
            return direct

    root_text = str(project_root.resolve(strict=False))
    root_variants = {root_text, root_text.replace("\\", "/"), root_text.replace("/", "\\")}
    sanitized = value
    for root_variant in sorted(root_variants, key=len, reverse=True):
        if not root_variant:
            continue
        sanitized = re.sub(
            rf"{re.escape(root_variant)}(?=$|[\\/\s'\";,}}])",
            ".",
            sanitized,
            flags=re.IGNORECASE if os.name == "nt" else 0,
        )

    def _replace_quoted(match: re.Match[str]) -> str:
        quote = match.group("quote")
        projected = _path_display_value(match.group("path"), project_root)
        return f"{quote}{projected}{quote}"

    def _replace_unquoted(match: re.Match[str]) -> str:
        return _path_display_value(match.group("path"), project_root)

    sanitized = _QUOTED_ABSOLUTE_PATH_RE.sub(_replace_quoted, sanitized)
    sanitized = _WINDOWS_ABSOLUTE_PATH_RE.sub(_replace_unquoted, sanitized)
    sanitized = _POSIX_ABSOLUTE_PATH_RE.sub(_replace_unquoted, sanitized)
    return sanitized


def _project_public_payload(value: Any, project_root: Path | str) -> Any:
    """递归构造不含服务端身份与绝对路径的公共响应投影。"""
    root = Path(project_root)
    if isinstance(value, dict):
        projected: dict[str, Any] = {}
        for key, item in value.items():
            if _normalize_private_field_name(key) in _PRIVATE_ROOT_FIELD_NAMES:
                continue
            projected[str(key)] = _project_public_payload(item, root)
        return projected
    if isinstance(value, (list, tuple)):
        return [_project_public_payload(item, root) for item in value]
    if isinstance(value, str):
        return _sanitize_public_text(value, root)
    return value


def _public_executable_name(command: str) -> str:
    """只暴露逻辑可执行文件名，不返回服务端绝对路径。"""
    normalized = str(command or "").strip()
    if not normalized:
        return ""
    return Path(normalized).name if Path(normalized).is_absolute() else normalized


def _get_bound_session(
    *,
    user_id: str,
    session_id: str,
    project_id: str,
) -> Dict[str, Any]:
    meta = _acp_user_sessions.get((user_id, session_id))
    if meta is None or meta.get("project_id") != project_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_detail("acp_session_not_found", "ACP 会话不存在"),
        )
    return meta


def _assert_session_root(meta: Dict[str, Any], resolved_root: Path) -> str:
    current_root = str(resolved_root)
    if meta.get("resolved_root") != current_root:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_detail(
                "workbench_project_root_changed",
                "工作台项目根路径已发生变化",
            ),
        )
    return current_root


def _resolve_allowed_workdirs() -> List[str]:
    """从 settings.ACP_ALLOWED_WORKDIRS 解析允许的工作目录白名单。

    安全策略：
    1. 不再使用动态的 os.getcwd() 作为白名单，避免任意用户指定任意路径作为子进程 cwd
    2. 默认允许 var/workspace 与 Open-AwA 项目根目录，满足受控项目内的 Node.js Agent 安装
    3. 自动创建不存在的白名单根目录，避免首次启动时校验失败
    4. 配置项支持逗号分隔的多个绝对路径

    Returns:
        归一化为绝对路径的白名单列表。
    """
    # 项目根目录绝对路径（__file__ = backend/api/routes/acp.py，parents[4] = 项目根）
    project_root = Path(__file__).resolve().parents[3]

    raw_value = (settings.ACP_ALLOWED_WORKDIRS or "").strip()
    if not raw_value:
        # 默认白名单：隔离工作区 var/workspace 与当前 Open-AwA 项目根目录
        default_dirs = [str(project_root / "var" / "workspace"), str(project_root)]
    else:
        # 配置项按逗号分隔，过滤空字符串
        default_dirs = [p.strip() for p in raw_value.split(",") if p.strip()]

    # 归一化为绝对路径并去重，保留插入顺序
    resolved: List[str] = []
    seen: set[str] = set()
    for candidate in default_dirs:
        try:
            abs_path = str(Path(candidate).resolve())
        except (OSError, ValueError) as exc:
            logger.warning(f"ACP_ALLOWED_WORKDIRS 配置项解析失败: {candidate}, 错误: {exc}")
            continue
        if abs_path in seen:
            continue
        seen.add(abs_path)
        resolved.append(abs_path)

    if not resolved:
        # 兜底：所有配置项均无效时使用隔离工作区与项目根目录
        resolved.extend([str(project_root / "var" / "workspace"), str(project_root)])

    # 自动创建不存在的白名单根目录，避免首次启动校验失败
    for workdir in resolved:
        try:
            Path(workdir).mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.warning(f"ACP 工作目录创建失败: {workdir}, 错误: {exc}")

    return resolved


# 旧兼容测试仍引用该白名单；运行时项目根不再从这里解析。
_ALLOWED_WORKSPACE_ROOTS: List[str] = _resolve_allowed_workdirs()


# 会话元数据：以 (user_id, session_id) 为键
# 元数据结构包含 user_id、project_id、resolved_root、agent 与 created_at。
_acp_user_sessions: Dict[Tuple[str, str], Dict[str, Any]] = {}

# P0-14: 模块级字典容量上限，防止单用户创建海量会话触发 OOM
# 单用户最大并发会话数
_MAX_ACP_SESSIONS_PER_USER = 10
# 全局最大会话总数
_MAX_TOTAL_ACP_SESSIONS = 1000
_OPENCODE_PACKAGE = "opencode-ai@latest"
_OPENCODE_INSTALL_TIMEOUT_SECONDS = 600
_OPENCODE_INSTALL_LOCKS: Dict[str, asyncio.Lock] = {}


async def verify_acp_preview_listener(
    user_id: str,
    project_id: str,
    session_kind: PreviewSessionKind,
    session_id: str,
    port: int,
) -> bool:
    """校验预览端口确实由完整身份绑定的 ACP 进程树监听。"""
    if session_kind is not PreviewSessionKind.ACP:
        return False
    try:
        meta = _acp_user_sessions.get((user_id, session_id))
        if (
            meta is None
            or meta.get("user_id") != user_id
            or meta.get("project_id") != project_id
        ):
            return False
        agent = str(meta.get("agent", ""))
        resolved_root = str(meta.get("resolved_root", ""))
        if not agent or not resolved_root:
            return False
        service = get_acp_service(agent)
        if service is None:
            return False
        conversation = await service.get_session(
            chat_id=f"{user_id}:{session_id}",
            agent=agent,
            user_id=user_id,
            project_id=project_id,
            resolved_root=resolved_root,
        )
        if (
            conversation is None
            or getattr(conversation, "user_id", None) != user_id
            or getattr(conversation, "project_id", None) != project_id
            or getattr(conversation, "resolved_root", None) != resolved_root
        ):
            return False
        process = getattr(conversation, "process", None)
        pid = getattr(process, "pid", None)
        if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
            return False
        return (
            await asyncio.to_thread(
                listener_ownership.process_tree_owns_listener,
                root_pid=pid,
                port=port,
            )
            is True
        )
    except Exception as exc:
        logger.bind(
            event="acp_preview_listener_verification_failed",
            session_id=session_id,
        ).warning(f"ACP 预览 listener 校验失败，已拒绝请求: {exc}")
        return False


listener_verifier_registry.register(
    PreviewSessionKind.ACP,
    verify_acp_preview_listener,
)


async def _revoke_acp_preview_leases(
    *,
    user_id: str,
    project_id: str,
    session_id: str,
) -> None:
    """撤销精确绑定到 ACP 用户、项目与会话的全部预览 lease。"""
    await preview_lease_registry.revoke_session(
        user_id=user_id,
        project_id=project_id,
        session_kind=PreviewSessionKind.ACP,
        session_id=session_id,
    )


async def _evict_acp_session(
    key: Tuple[str, str],
    *,
    registry: WorkbenchRuntimeRegistry,
) -> None:
    """关闭最旧 ACP 子进程并释放其工作台运行时资源。"""
    meta = _acp_user_sessions.get(key)
    if meta is None:
        return
    user_id, session_id = key
    project_id = str(meta.get("project_id", ""))
    agent = str(meta.get("agent", ""))
    resolved_root = str(meta.get("resolved_root", ""))
    service = get_acp_service(agent)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_detail("acp_service_unavailable", "ACP 服务暂不可用，请稍后重试"),
        )
    try:
        await service.close_chat_session(
            chat_id=f"{user_id}:{session_id}",
            agent=agent,
            user_id=user_id,
            project_id=project_id,
            resolved_root=resolved_root,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=_detail("acp_session_eviction_failed", "ACP 会话淘汰失败，请稍后重试"),
        ) from exc
    if project_id:
        await _revoke_acp_preview_leases(
            user_id=user_id,
            project_id=project_id,
            session_id=session_id,
        )
        await registry.release(
            user_id=user_id,
            project_id=project_id,
            resource_type=RuntimeResourceType.ACP_TURN,
            resource_id=session_id,
        )
        await registry.release(
            user_id=user_id,
            project_id=project_id,
            resource_type=RuntimeResourceType.ACP_SESSION,
            resource_id=session_id,
        )
    _acp_user_sessions.pop(key, None)


async def _ensure_acp_session_capacity(
    user_id: str,
    *,
    registry: WorkbenchRuntimeRegistry,
) -> None:
    """在创建前关闭超限会话，禁止只移除元数据而遗留进程。"""
    if len(_acp_user_sessions) >= _MAX_TOTAL_ACP_SESSIONS:
        oldest_key = min(
            _acp_user_sessions,
            key=lambda key: _acp_user_sessions[key].get("created_at", ""),
        )
        await _evict_acp_session(oldest_key, registry=registry)

    user_keys = [key for key in _acp_user_sessions if key[0] == user_id]
    if len(user_keys) >= _MAX_ACP_SESSIONS_PER_USER:
        oldest_key = min(
            user_keys,
            key=lambda key: _acp_user_sessions[key].get("created_at", ""),
        )
        await _evict_acp_session(oldest_key, registry=registry)


def _add_acp_session(user_id: str, session_id: str, meta: Dict[str, Any]) -> None:
    """添加 ACP 会话到全局字典，强制 per-user 与全局容量上限。

    超出上限时按 created_at 时间戳淘汰最旧的会话，防止单用户创建海量会话触发 OOM。

    Args:
        user_id: 用户 ID。
        session_id: 会话 ID。
        meta: 会话元数据（必须含 created_at 字段用于淘汰排序）。
    """
    _acp_user_sessions[(user_id, session_id)] = meta


# ==================== 请求/响应 Schema ====================


class AgentInfo(BaseModel):
    """单个 ACP Agent 的展示信息。"""

    id: str = Field(..., description="Agent 唯一标识")
    name: str = Field(..., description="Agent 展示名称")
    command: str = Field(..., description="启动 Agent 子进程的命令")
    enabled: bool = Field(..., description="配置中是否启用")
    available: bool = Field(..., description="本地是否安装了对应 CLI 命令")


class AgentListResponse(BaseModel):
    """GET /agents 响应：返回所有已注册 agent 列表。"""

    agents: List[AgentInfo] = Field(default_factory=list)
    count: int = Field(..., description="Agent 总数")


class SessionCreateRequest(BaseModel):
    """POST /sessions 请求体：创建 ACP 会话。"""

    agent: str = Field(..., description="Agent 标识")
    project_id: Optional[str] = Field(default=None, description="工作台项目 ID")
    cwd: Optional[str] = Field(default=None, description="工作目录")
    project_dir: Optional[str] = None
    projectCwd: Optional[str] = None
    projectDir: Optional[str] = None


class SessionCreateResponse(BaseModel):
    """POST /sessions 响应。"""

    session_id: str = Field(..., description="会话 ID")
    project_id: str = Field(..., description="工作台项目 ID")
    config_options: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="可选的会话配置项，暂返回空列表",
    )


class SessionInfo(BaseModel):
    """单个会话的展示信息。"""

    session_id: str = Field(..., description="会话 ID")
    agent: str = Field(..., description="Agent 标识")
    project_id: str = Field(..., description="工作台项目 ID")
    created_at: str = Field(..., description="创建时间（ISO 格式）")


class SessionListResponse(BaseModel):
    """GET /sessions 响应。"""

    sessions: List[SessionInfo] = Field(default_factory=list)
    count: int = Field(..., description="当前用户的活动会话数")


class PromptRequest(BaseModel):
    """POST /sessions/{session_id}/prompt 请求体。"""

    prompt: str = Field(..., min_length=1, max_length=32000, description="用户 prompt 内容")
    restart: bool = Field(default=False, description="是否重启会话")
    project_id: Optional[str] = Field(default=None, description="工作台项目 ID")
    cwd: Optional[str] = None
    project_dir: Optional[str] = None
    projectCwd: Optional[str] = None
    projectDir: Optional[str] = None


class PermissionResponseRequest(BaseModel):
    """POST /sessions/{session_id}/permission 请求体。"""

    option_id: str = Field(..., description="用户选择的审批选项 ID")
    project_id: Optional[str] = Field(default=None, description="工作台项目 ID")
    cwd: Optional[str] = None
    project_dir: Optional[str] = None
    projectCwd: Optional[str] = None
    projectDir: Optional[str] = None


class PermissionResponseResponse(BaseModel):
    """POST /sessions/{session_id}/permission 响应。"""

    status: str = Field(..., description="权限恢复结果状态")


class CancelResponse(BaseModel):
    """POST /sessions/{session_id}/cancel 响应。"""

    cancelled: bool = Field(..., description="是否已取消当前 prompt")


class SessionCloseResponse(BaseModel):
    """DELETE /sessions/{session_id} 响应。"""

    closed: bool = Field(..., description="是否已关闭并移除会话")


class OpenCodeStatusResponse(BaseModel):
    """OpenCode 在指定项目中的安装与可用状态。"""

    project_id: str
    package_json_exists: bool
    project_installed: bool
    available: bool
    command: str


class OpenCodeInstallRequest(BaseModel):
    """项目内 OpenCode 安装请求。"""

    project_id: Optional[str] = Field(default=None, description="工作台项目 ID")
    cwd: Optional[str] = Field(default=None, description="工作目录")
    project_dir: Optional[str] = None
    projectCwd: Optional[str] = None
    projectDir: Optional[str] = None
    confirm_install: bool = Field(..., description="是否已由用户明确确认安装")


class OpenCodeInstallResponse(OpenCodeStatusResponse):
    """项目内 OpenCode 安装结果。"""

    installed: bool
    audit_passed: Optional[bool] = None
    output: str = ""


def _get_opencode_install_lock(cwd: str) -> asyncio.Lock:
    """按项目目录串行化 OpenCode 安装，避免并发修改同一锁文件。"""
    lock = _OPENCODE_INSTALL_LOCKS.get(cwd)
    if lock is None:
        lock = asyncio.Lock()
        _OPENCODE_INSTALL_LOCKS[cwd] = lock
    return lock


def _build_npm_safe_env() -> Dict[str, str]:
    """构建 npm 安装子进程环境，避免向依赖安装脚本传递密钥。"""
    allowed_keys = (
        "APPDATA", "COMSPEC", "HOME", "HOMEDRIVE", "HOMEPATH",
        "LOCALAPPDATA", "PATH", "PATHEXT", "SYSTEMROOT", "TEMP", "TMP",
        "USERPROFILE", "WINDIR",
    )
    return {key: os.environ[key] for key in allowed_keys if key in os.environ}


def _npm_command() -> str:
    """解析 npm 可执行文件，兼容 Windows 的 npm.cmd。"""
    return shutil.which("npm.cmd") or shutil.which("npm") or "npm"


async def _run_npm_command(cwd: str, args: List[str]) -> tuple[int, str]:
    """以固定参数执行 npm 并限制输出与超时。"""
    try:
        process = await asyncio.create_subprocess_exec(
            _npm_command(),
            *args,
            cwd=cwd,
            env=_build_npm_safe_env(),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="未检测到可用的 npm，请先安装 Node.js",
        ) from exc

    try:
        stdout, _ = await asyncio.wait_for(
            process.communicate(),
            timeout=_OPENCODE_INSTALL_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError as exc:
        process.kill()
        await process.communicate()
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="OpenCode 安装超时，请检查网络或 npm 配置",
        ) from exc

    output = stdout.decode("utf-8", errors="replace")[-12000:]
    return process.returncode or 0, output


async def _get_opencode_status(project_id: str, cwd: str) -> OpenCodeStatusResponse:
    """读取指定项目中 OpenCode 的安装状态与最终启动命令。"""
    agents = discover_agents()
    config = agents["opencode"]
    command = resolve_agent_command(config, cwd)
    project_installed = command != config.command
    available = await asyncio.to_thread(is_agent_available, "opencode", agents, cwd)
    return OpenCodeStatusResponse(
        project_id=project_id,
        package_json_exists=(Path(cwd) / "package.json").is_file(),
        project_installed=project_installed,
        available=available,
        command=_public_executable_name(config.command),
    )


# ==================== 端点实现 ====================


@router.get("/agents", response_model=AgentListResponse)
async def list_agents(
    current_user: User = Depends(get_current_user),
) -> AgentListResponse:
    """返回所有已注册 ACP Agent 列表。

    available 字段通过 is_agent_available(agent_id) 探测本地 CLI 是否安装。
    探测是同步阻塞操作，通过 asyncio.to_thread 包裹避免阻塞事件循环。
    """
    del current_user  # 仅用于鉴权，不参与业务逻辑
    agents = discover_agents()
    agent_infos: List[AgentInfo] = []
    for agent_id, config in agents.items():
        # 同步探测放到线程池中执行
        available = await asyncio.to_thread(is_agent_available, agent_id, agents)
        agent_infos.append(
            AgentInfo(
                id=config.agent_id,
                name=config.name,
                command=_public_executable_name(config.command),
                enabled=config.enabled,
                available=available,
            )
        )
    return AgentListResponse(agents=agent_infos, count=len(agent_infos))


@router.get("/opencode/status", response_model=OpenCodeStatusResponse)
async def get_opencode_status(
    request: Request,
    project_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    path_policy: WorkbenchPathPolicy = Depends(get_acp_workbench_path_policy),
) -> OpenCodeStatusResponse:
    """返回当前工作台项目中 OpenCode 的安装状态。"""
    normalized_project_id, root = _resolve_request_project(
        request=request,
        project_id=project_id,
        current_user=current_user,
        db=db,
        path_policy=path_policy,
    )
    return await _get_opencode_status(normalized_project_id, str(root))


@router.post("/opencode/install", response_model=OpenCodeInstallResponse)
async def install_opencode(
    request: OpenCodeInstallRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    path_policy: WorkbenchPathPolicy = Depends(get_acp_workbench_path_policy),
    registry: WorkbenchRuntimeRegistry = Depends(get_acp_runtime_registry),
) -> OpenCodeInstallResponse:
    """在白名单 Node.js 项目中安装固定的 OpenCode 包。"""
    _reject_legacy_body_fields(request)
    project_id = _require_project_id(request.project_id)
    safe_cwd = str(
        _resolve_project_root(
            project_id=project_id,
            current_user=current_user,
            db=db,
            path_policy=path_policy,
        )
    )
    if not request.confirm_install:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="必须由用户明确确认后才能安装 OpenCode",
        )

    if not (Path(safe_cwd) / "package.json").is_file():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="工作目录不是 Node.js 项目，缺少 package.json",
        )

    resource_id = str(uuid.uuid4())

    def _verify_project() -> None:
        _resolve_project_root(
            project_id=project_id,
            current_user=current_user,
            db=db,
            path_policy=path_policy,
        )

    await registry.acquire(
        user_id=str(current_user.id),
        project_id=project_id,
        resource_type=RuntimeResourceType.OPENCODE_INSTALL,
        resource_id=resource_id,
        verify_project=_verify_project,
    )
    try:
        async with _get_opencode_install_lock(safe_cwd):
            fresh_root = await _fresh_resolve_project_root(
                project_id=project_id,
                current_user=current_user,
                path_policy=path_policy,
                expected_root=safe_cwd,
            )
            fresh_cwd = str(fresh_root)
            if not (fresh_root / "package.json").is_file():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="工作目录不是 Node.js 项目，缺少 package.json",
                )
            return_code, output = await _run_npm_command(
                fresh_cwd,
                ["install", "--save-dev", _OPENCODE_PACKAGE, "--no-audit", "--no-fund"],
            )
            if return_code != 0:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail={
                        "message": "OpenCode 安装失败",
                        "output": _project_public_payload(output, fresh_root),
                    },
                )

            fresh_root = await _fresh_resolve_project_root(
                project_id=project_id,
                current_user=current_user,
                path_policy=path_policy,
                expected_root=safe_cwd,
            )
            fresh_cwd = str(fresh_root)
            audit_code, audit_output = await _run_npm_command(
                fresh_cwd,
                ["audit", "--audit-level=high", "--json"],
            )
            status_result = await _get_opencode_status(project_id, fresh_cwd)
    finally:
        await registry.release(
            user_id=str(current_user.id),
            project_id=project_id,
            resource_type=RuntimeResourceType.OPENCODE_INSTALL,
            resource_id=resource_id,
        )

    logger.bind(
        event="acp_opencode_installed",
        module="acp",
        user_id=current_user.id,
        project_id=project_id,
        audit_passed=(audit_code == 0),
    ).info("OpenCode 已在 ACP 工作目录安装")
    return OpenCodeInstallResponse(
        **status_result.model_dump(),
        installed=status_result.project_installed and status_result.available,
        audit_passed=(audit_code == 0),
        output=_project_public_payload(
            (output + "\n" + audit_output)[-12000:],
            fresh_root,
        ),
    )


@router.post("/sessions", response_model=SessionCreateResponse)
async def create_session(
    request: SessionCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    path_policy: WorkbenchPathPolicy = Depends(get_acp_workbench_path_policy),
    registry: WorkbenchRuntimeRegistry = Depends(get_acp_runtime_registry),
) -> SessionCreateResponse:
    """创建 ACP 会话。

    流程：
    1. 校验并解析工作台 project_id
    2. 校验 agent 在 discover_agents() 中且 enabled=True
    3. 登记 acp_session 运行时资源与会话元数据
    4. 返回 session_id、project_id 与空 config_options

    注意：实际 ACP 子进程会话由 ACPService.run_turn 在首次 prompt 时创建。
    """
    _reject_legacy_body_fields(request)
    project_id = _require_project_id(request.project_id)
    resolved_root = _resolve_project_root(
        project_id=project_id,
        current_user=current_user,
        db=db,
        path_policy=path_policy,
    )
    agents = discover_agents()
    agent_config = agents.get(request.agent)
    if agent_config is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"未知的 ACP agent: {request.agent}",
        )
    if not agent_config.enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"ACP agent '{request.agent}' 已禁用",
        )

    session_id = str(uuid.uuid4())
    user_id = str(current_user.id)
    safe_cwd = str(resolved_root)
    await _ensure_acp_session_capacity(user_id, registry=registry)

    def _verify_project() -> None:
        _resolve_project_root(
            project_id=project_id,
            current_user=current_user,
            db=db,
            path_policy=path_policy,
        )

    async def _close_runtime_session() -> None:
        service = get_acp_service(request.agent)
        if service is None:
            raise ACPSessionError("ACP service is unavailable during runtime close")
        await service.close_chat_session(
            chat_id=f"{user_id}:{session_id}",
            agent=request.agent,
            user_id=user_id,
            project_id=project_id,
            resolved_root=safe_cwd,
        )
        await _revoke_acp_preview_leases(
            user_id=user_id,
            project_id=project_id,
            session_id=session_id,
        )
        _acp_user_sessions.pop((user_id, session_id), None)

    await registry.acquire(
        user_id=user_id,
        project_id=project_id,
        resource_type=RuntimeResourceType.ACP_SESSION,
        resource_id=session_id,
        verify_project=_verify_project,
        close_callback=_close_runtime_session,
    )
    # 用 chat_id = f"{user_id}:{session_id}" 作为 ACPService 的 chat_id
    # P0-14: 通过 _add_acp_session 强制容量上限，防止单用户创建海量会话触发 OOM
    _add_acp_session(
        user_id=user_id,
        session_id=session_id,
        meta={
            "user_id": user_id,
            "project_id": project_id,
            "agent": request.agent,
            "resolved_root": safe_cwd,
            "cwd": safe_cwd,
            "created_at": _now_iso(),
        },
    )

    logger.bind(
        event="acp_session_created",
        module="acp",
        session_id=session_id,
        user_id=current_user.id,
        agent=request.agent,
    ).info(f"ACP 会话已创建: agent={request.agent}, session_id={session_id}")

    return SessionCreateResponse(
        session_id=session_id,
        project_id=project_id,
        config_options=[],
    )


@router.get("/sessions", response_model=SessionListResponse)
async def list_sessions(
    request: Request,
    project_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    path_policy: WorkbenchPathPolicy = Depends(get_acp_workbench_path_policy),
) -> SessionListResponse:
    """列出当前用户的活动 ACP 会话。"""
    user_id = str(current_user.id)
    normalized_project_id, _ = _resolve_request_project(
        request=request,
        project_id=project_id,
        current_user=current_user,
        db=db,
        path_policy=path_policy,
    )
    sessions: List[SessionInfo] = []
    for (uid, sid), meta in _acp_user_sessions.items():
        if uid != user_id or meta.get("project_id") != normalized_project_id:
            continue
        sessions.append(
            SessionInfo(
                session_id=sid,
                agent=meta["agent"],
                project_id=normalized_project_id,
                created_at=meta["created_at"],
            )
        )
    return SessionListResponse(sessions=sessions, count=len(sessions))


@router.post("/sessions/{session_id}/prompt")
async def prompt_session(
    session_id: str,
    request: PromptRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    path_policy: WorkbenchPathPolicy = Depends(get_acp_workbench_path_policy),
    registry: WorkbenchRuntimeRegistry = Depends(get_acp_runtime_registry),
) -> StreamingResponse:
    """对指定 ACP 会话发起一轮 prompt（SSE 流式响应）。

    Content-Type: text/event-stream

    SSE 事件类型：
    - text: 文本块输出
    - tool: 工具调用相关事件
    - status: 状态变更
    - permission: 权限审批请求挂起
    - usage: 用量统计
    - result: 一轮 prompt 结束
    - error: 错误信息（SDK 缺失等）

    客户端断开时调用 ACPService.cancel_turn 取消未完成的 prompt。
    """
    _reject_legacy_body_fields(request)
    user_id = str(current_user.id)
    project_id = _require_project_id(request.project_id)
    resolved_root = _resolve_project_root(
        project_id=project_id,
        current_user=current_user,
        db=db,
        path_policy=path_policy,
    )
    meta = _get_bound_session(
        user_id=user_id,
        session_id=session_id,
        project_id=project_id,
    )

    agent = meta["agent"]
    cwd = _assert_session_root(meta, resolved_root)
    chat_id = f"{user_id}:{session_id}"
    service = get_acp_service(agent)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="ACP 服务暂不可用，请稍后重试",
        )

    prompt_blocks = [{"type": "text", "text": request.prompt}]

    def _verify_project() -> None:
        current_root = _resolve_project_root(
            project_id=project_id,
            current_user=current_user,
            db=db,
            path_policy=path_policy,
        )
        _assert_session_root(meta, current_root)

    await registry.acquire(
        user_id=user_id,
        project_id=project_id,
        resource_type=RuntimeResourceType.ACP_TURN,
        resource_id=session_id,
        verify_project=_verify_project,
    )

    async def event_generator():
        """SSE 事件生成器：把 ACPService 事件转为 SSE 帧推送。"""
        # 队列承载所有要推送的事件，避免 await service.run_turn 阻塞流
        # 有界队列避免断开客户端或异常 Agent 持续产出时无限占用内存。
        queue: asyncio.Queue[Optional[str]] = asyncio.Queue(maxsize=256)
        # 标记 run_turn 是否已完成
        run_turn_task: Optional[asyncio.Task[Any]] = None
        cancel_event = asyncio.Event()
        release_turn = True

        async def on_message(payload: Dict[str, Any], is_last: bool) -> None:
            """ACPService 事件回调：把事件转为 SSE 帧后放入队列。"""
            event_type = _resolve_event_type(payload)
            sse_frame = _format_sse(
                event_type,
                payload,
                project_root=cwd,
            )
            await queue.put(sse_frame)

        async def _run_turn_wrapper() -> None:
            """包裹 service.run_turn，捕获异常并推送 error 事件。"""
            try:
                fresh_root = await _fresh_resolve_project_root(
                    project_id=project_id,
                    current_user=current_user,
                    path_policy=path_policy,
                    expected_root=cwd,
                )
                fresh_cwd = _assert_session_root(meta, fresh_root)
                result = await service.run_turn(
                    chat_id=chat_id,
                    agent=agent,
                    prompt_blocks=prompt_blocks,
                    cwd=fresh_cwd,
                    user_id=user_id,
                    project_id=project_id,
                    resolved_root=fresh_cwd,
                    on_message=on_message,
                    restart=request.restart,
                )
                # 推送最终结果事件
                status_value = result.get("status", "completed")
                if status_value == "permission_required":
                    suspended = result.get("suspended_permission")
                    perm_payload: Dict[str, Any] = {}
                    if suspended is not None:
                        perm_payload = _suspended_permission_to_dict(
                            suspended,
                            project_root=fresh_cwd,
                        )
                    await queue.put(
                        _format_sse(
                            "permission",
                            perm_payload,
                            project_root=fresh_cwd,
                        )
                    )
                await queue.put(
                    _format_sse(
                        "result",
                        {"status": status_value},
                        project_root=fresh_cwd,
                    )
                )
            except ACPConfigurationError as exc:
                logger.bind(
                    event="acp_prompt_config_error",
                    module="acp",
                    session_id=session_id,
                    agent=agent,
                    error_message=str(exc),
                ).warning(f"ACP 配置错误: {exc}")
                await queue.put(
                    _format_sse(
                        "error",
                        {"message": str(exc)},
                        project_root=cwd,
                    )
                )
            except ACPSessionError as exc:
                logger.bind(
                    event="acp_prompt_session_error",
                    module="acp",
                    session_id=session_id,
                    agent=agent,
                    error_message=str(exc),
                ).warning(f"ACP 会话错误: {exc}")
                await queue.put(
                    _format_sse(
                        "error",
                        {"message": str(exc)},
                        project_root=cwd,
                    )
                )
            except Exception as exc:
                logger.bind(
                    event="acp_prompt_error",
                    module="acp",
                    session_id=session_id,
                    agent=agent,
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                ).error(f"ACP prompt 异常: {exc}")
                await queue.put(
                    _format_sse(
                        "error",
                        {"message": "ACP 请求执行失败"},
                        project_root=cwd,
                    )
                )
            finally:
                # 哨兵：通知生成器退出
                await queue.put(None)

        run_turn_task = asyncio.create_task(_run_turn_wrapper())

        try:
            while True:
                # 客户端断开时 asyncio.CancelledError 由 try/except 捕获
                if cancel_event.is_set():
                    break
                try:
                    frame = await asyncio.wait_for(queue.get(), timeout=30.0)
                except asyncio.TimeoutError:
                    # 心跳保持连接活跃
                    yield ": heartbeat\n\n"
                    continue
                if frame is None:
                    break
                yield frame
        except asyncio.CancelledError:
            # 客户端断开连接，取消未完成的 prompt
            logger.bind(
                event="acp_prompt_cancelled",
                module="acp",
                session_id=session_id,
                agent=agent,
            ).info(f"客户端断开，取消 ACP prompt: {session_id}")
            cancel_event.set()
            try:
                cancel_confirmed = await asyncio.wait_for(
                    service.cancel_turn(
                        chat_id=chat_id,
                        agent=agent,
                        user_id=user_id,
                        project_id=project_id,
                        resolved_root=cwd,
                    ),
                    timeout=5.0,
                )
                if not cancel_confirmed:
                    release_turn = False
            except asyncio.TimeoutError:
                release_turn = False
                logger.bind(
                    event="acp_prompt_cancel_timeout",
                    module="acp",
                    session_id=session_id,
                    agent=agent,
                ).warning("ACP prompt 取消超时")
            except Exception as exc:
                release_turn = False
                logger.warning(f"取消 ACP prompt 失败: {exc}")
            raise
        finally:
            if run_turn_task is not None and not run_turn_task.done():
                run_turn_task.cancel()
                try:
                    await asyncio.wait_for(run_turn_task, timeout=5.0)
                except asyncio.TimeoutError:
                    logger.bind(
                        event="acp_prompt_task_cancel_timeout",
                        module="acp",
                        session_id=session_id,
                        agent=agent,
                    ).warning("ACP prompt 后台任务取消超时，已停止等待")
                except (asyncio.CancelledError, Exception):
                    pass
            if release_turn:
                await registry.release(
                    user_id=user_id,
                    project_id=project_id,
                    resource_type=RuntimeResourceType.ACP_TURN,
                    resource_id=session_id,
                )

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.post("/sessions/{session_id}/permission", response_model=PermissionResponseResponse)
async def respond_permission(
    session_id: str,
    request: PermissionResponseRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    path_policy: WorkbenchPathPolicy = Depends(get_acp_workbench_path_policy),
    registry: WorkbenchRuntimeRegistry = Depends(get_acp_runtime_registry),
) -> PermissionResponseResponse:
    """响应当前挂起的权限审批请求。

    通过 session_id 找到会话，再通过 ACPService.resume_permission 恢复执行。
    """
    _reject_legacy_body_fields(request)
    user_id = str(current_user.id)
    project_id = _require_project_id(request.project_id)
    resolved_root = _resolve_project_root(
        project_id=project_id,
        current_user=current_user,
        db=db,
        path_policy=path_policy,
    )
    meta = _get_bound_session(
        user_id=user_id,
        session_id=session_id,
        project_id=project_id,
    )
    _assert_session_root(meta, resolved_root)

    agent = meta["agent"]
    chat_id = f"{user_id}:{session_id}"
    service = get_acp_service(agent)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="ACP 服务暂不可用，请稍后重试",
        )

    def _verify_project() -> None:
        current_root = _resolve_project_root(
            project_id=project_id,
            current_user=current_user,
            db=db,
            path_policy=path_policy,
        )
        _assert_session_root(meta, current_root)

    await registry.acquire(
        user_id=user_id,
        project_id=project_id,
        resource_type=RuntimeResourceType.ACP_TURN,
        resource_id=session_id,
        verify_project=_verify_project,
    )
    try:
        # 通过 get_session 拿到 _Conversation 实例，从中取 acp_session_id
        conversation = await service.get_session(
            chat_id=chat_id,
            agent=agent,
            user_id=user_id,
            project_id=project_id,
            resolved_root=str(resolved_root),
        )
        if conversation is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="ACP 会话未建立，请先发起一次 prompt",
            )
        # 校验存在挂起的权限请求
        pending = await service.get_pending_permission(
            chat_id=chat_id,
            agent=agent,
            user_id=user_id,
            project_id=project_id,
            resolved_root=str(resolved_root),
        )
        if pending is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="当前没有挂起的权限请求",
            )
        # _Conversation 含 acp_session_id 字段
        acp_session_id = getattr(conversation, "acp_session_id", None)
        if not isinstance(acp_session_id, str) or not acp_session_id:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="无法获取 ACP 会话 ID",
            )

        async def _noop_on_message(payload: Dict[str, Any], is_last: bool) -> None:
            """resume_permission 需要事件回调，此端点为非流式，丢弃事件即可。"""
            del payload, is_last

        try:
            result = await service.resume_permission(
                acp_session_id=acp_session_id,
                option_id=request.option_id,
                on_message=_noop_on_message,
                user_id=user_id,
                project_id=project_id,
                resolved_root=str(resolved_root),
            )
        except ACPConfigurationError as exc:
            logger.bind(
                event="acp_permission_configuration_error",
                module="acp",
                session_id=session_id,
                error_type=type(exc).__name__,
            ).opt(exception=True).warning("ACP 权限响应配置异常")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="ACP 服务暂不可用，请稍后重试",
            ) from exc
        except ACPSessionError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            )
    finally:
        await registry.release(
            user_id=user_id,
            project_id=project_id,
            resource_type=RuntimeResourceType.ACP_TURN,
            resource_id=session_id,
        )

    status_value = str(result.get("status", "completed"))
    return PermissionResponseResponse(status=status_value)


@router.post("/sessions/{session_id}/cancel", response_model=CancelResponse)
async def cancel_session_turn(
    session_id: str,
    request: Request,
    project_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    path_policy: WorkbenchPathPolicy = Depends(get_acp_workbench_path_policy),
    registry: WorkbenchRuntimeRegistry = Depends(get_acp_runtime_registry),
) -> CancelResponse:
    """取消指定会话当前正在进行的 prompt 任务。"""
    user_id = str(current_user.id)
    normalized_project_id, resolved_root = _resolve_request_project(
        request=request,
        project_id=project_id,
        current_user=current_user,
        db=db,
        path_policy=path_policy,
    )
    meta = _get_bound_session(
        user_id=user_id,
        session_id=session_id,
        project_id=normalized_project_id,
    )
    _assert_session_root(meta, resolved_root)

    agent = meta["agent"]
    chat_id = f"{user_id}:{session_id}"
    service = get_acp_service(agent)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="ACP 服务暂不可用，请稍后重试",
        )

    try:
        cancelled = await service.cancel_turn(
            chat_id=chat_id,
            agent=agent,
            user_id=user_id,
            project_id=normalized_project_id,
            resolved_root=str(resolved_root),
        )
    except ACPSessionError as exc:
        logger.warning(f"取消 ACP prompt 会话校验失败: {exc}")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_detail("acp_turn_cancel_failed", "ACP prompt 未能确认取消，请稍后重试"),
        ) from exc
    except Exception as exc:
        logger.warning(f"取消 ACP prompt 异常: {exc}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=_detail("acp_turn_cancel_failed", "ACP prompt 取消失败，请稍后重试"),
        ) from exc
    if not cancelled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_detail("acp_turn_cancel_failed", "ACP prompt 未能确认取消，请稍后重试"),
        )
    await registry.release(
        user_id=user_id,
        project_id=normalized_project_id,
        resource_type=RuntimeResourceType.ACP_TURN,
        resource_id=session_id,
    )
    return CancelResponse(cancelled=cancelled)


@router.delete("/sessions/{session_id}", response_model=SessionCloseResponse)
async def close_session(
    session_id: str,
    request: Request,
    project_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    path_policy: WorkbenchPathPolicy = Depends(get_acp_workbench_path_policy),
    registry: WorkbenchRuntimeRegistry = Depends(get_acp_runtime_registry),
) -> SessionCloseResponse:
    """关闭并移除指定 ACP 会话。

    调用 ACPService.close_chat_session 清理子进程资源，并从 _acp_user_sessions 移除元数据。
    """
    user_id = str(current_user.id)
    normalized_project_id, resolved_root = _resolve_request_project(
        request=request,
        project_id=project_id,
        current_user=current_user,
        db=db,
        path_policy=path_policy,
    )
    meta = _get_bound_session(
        user_id=user_id,
        session_id=session_id,
        project_id=normalized_project_id,
    )
    _assert_session_root(meta, resolved_root)

    agent = meta["agent"]
    chat_id = f"{user_id}:{session_id}"
    service = get_acp_service(agent)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_detail("acp_service_unavailable", "ACP 服务暂不可用，请稍后重试"),
        )
    try:
        await service.close_chat_session(
            chat_id=chat_id,
            agent=agent,
            user_id=user_id,
            project_id=normalized_project_id,
            resolved_root=str(resolved_root),
        )
    except ACPSessionError as exc:
        logger.warning(f"关闭 ACP 会话校验失败: {exc}")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_detail("acp_session_close_failed", "ACP 会话未能确认关闭，请稍后重试"),
        ) from exc
    except Exception as exc:
        logger.warning(f"关闭 ACP 会话失败: {exc}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=_detail("acp_session_close_failed", "ACP 会话关闭失败，请稍后重试"),
        ) from exc

    await _revoke_acp_preview_leases(
        user_id=user_id,
        project_id=normalized_project_id,
        session_id=session_id,
    )
    await registry.release(
        user_id=user_id,
        project_id=normalized_project_id,
        resource_type=RuntimeResourceType.ACP_TURN,
        resource_id=session_id,
    )
    await registry.release(
        user_id=user_id,
        project_id=normalized_project_id,
        resource_type=RuntimeResourceType.ACP_SESSION,
        resource_id=session_id,
    )
    _acp_user_sessions.pop((user_id, session_id), None)

    logger.bind(
        event="acp_session_closed",
        module="acp",
        session_id=session_id,
        user_id=current_user.id,
        agent=agent,
    ).info(f"ACP 会话已关闭: {session_id}")

    return SessionCloseResponse(closed=True)


# ==================== 工具函数 ====================


def _now_iso() -> str:
    """返回当前时间的 ISO 格式字符串（含时区）。"""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _format_sse(
    event_type: str,
    payload: Dict[str, Any],
    *,
    project_root: Path | str | None = None,
) -> str:
    """构造 SSE 帧：event: <type>\\ndata: <json>\\n\\n。

    Args:
        event_type: 事件类型（text/tool/status/permission/usage/result/error）。
        payload: 事件数据。

    Returns:
        合法的 SSE 帧字符串。
    """
    public_payload = (
        _project_public_payload(payload, project_root)
        if project_root is not None
        else payload
    )
    return f"event: {event_type}\ndata: {json.dumps(public_payload, ensure_ascii=False)}\n\n"


def _resolve_event_type(payload: Dict[str, Any]) -> str:
    """根据 ACPService 事件 payload 推断 SSE 事件类型。

    Args:
        payload: ACPService 事件回调收到的字典。

    Returns:
        SSE 事件类型字符串。
    """
    # payload 中可能包含 type 字段（如 text/tool_call/tool_result/usage/status）
    payload_type = payload.get("type") or payload.get("event")
    if isinstance(payload_type, str):
        normalized = payload_type.lower()
        if normalized in (
            "text",
            "tool",
            "tool_call",
            "tool_result",
            "tool_start",
            "tool_update",
            "tool_end",
            "status",
            "permission",
            "usage",
            "result",
            "error",
        ):
            if normalized in (
                "tool_call",
                "tool_result",
                "tool_start",
                "tool_update",
                "tool_end",
            ):
                return "tool"
            return normalized
    # 默认归为 status 事件
    return "status"


def _suspended_permission_to_dict(
    suspended: Any,
    *,
    project_root: Path | str | None = None,
) -> Dict[str, Any]:
    """把 SuspendedPermission 实例转为可序列化的字典。

    Args:
        suspended: acp_host.core.SuspendedPermission 实例。

    Returns:
        包含 agent/tool_name/tool_kind/target/action/summary/command/paths/options 的字典。
    """
    if suspended is None:
        return {}
    if isinstance(suspended, dict):
        result = dict(suspended)
        return (
            _project_public_payload(result, project_root)
            if project_root is not None
            else result
        )
    # dataclass 实例
    fields = (
        "agent",
        "tool_name",
        "tool_kind",
        "target",
        "action",
        "summary",
        "command",
        "paths",
        "options",
        "requires_user_confirmation",
    )
    result: Dict[str, Any] = {}
    for field_name in fields:
        value = getattr(suspended, field_name, None)
        if value is None:
            continue
        # options 是 list[dict]，paths 是 list[str]，直接保留
        result[field_name] = value
    return (
        _project_public_payload(result, project_root)
        if project_root is not None
        else result
    )
