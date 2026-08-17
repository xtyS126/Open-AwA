# -*- coding: utf-8 -*-
"""工作台本地开发服务器预览租约与安全反向代理路由。"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime
from typing import NoReturn, Optional
from urllib.parse import quote, urljoin, urlsplit, urlunsplit

import httpx
import websockets
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    Response,
    WebSocket,
    status,
)
from fastapi.responses import JSONResponse, StreamingResponse
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field

from api.dependencies import get_current_user
from api.security.ws_auth import (
    extract_token_from_subprotocol,
    resolve_ws_user_from_token,
    validate_ws_origin,
)
from config.security import ACCESS_TOKEN_COOKIE_NAME
from config.settings import is_production_environment, settings
from db.models import SessionLocal, User
from workbench.errors import (
    ProjectDisabled,
    ProjectNotFound,
    ProjectRootForbidden,
    ProjectRootInvalid,
    WorkbenchError,
)
from workbench.listener_registry import (
    PreviewListenerVerifierRegistry,
    listener_verifier_registry,
)
from workbench.path_policy import WorkbenchPathPolicy
from workbench.preview_lease import (
    PreviewLease,
    PreviewLeaseForbidden,
    PreviewLeaseLimitExceeded,
    PreviewLeaseNotFound,
    PreviewLeaseRegistry,
    PreviewSessionKind,
    preview_lease_registry,
)
from workbench.project_service import WorkbenchProjectService

router = APIRouter(
    tags=["preview"],
)


class PreviewLeaseCreate(BaseModel):
    """创建预览租约所需的最小会话绑定。"""

    model_config = ConfigDict(extra="forbid")

    session_kind: PreviewSessionKind
    session_id: str = Field(min_length=1, max_length=200)
    port: int = Field(strict=True, ge=1, le=65535)


class PreviewLeaseResponse(BaseModel):
    """浏览器可见的预览租约投影，不包含用户和服务端路径。"""

    preview_id: str
    project_id: str
    session_kind: PreviewSessionKind
    session_id: str
    port: int
    expires_at: datetime


def get_preview_path_policy() -> WorkbenchPathPolicy:
    """按稳定配置构造工作台路径策略。"""
    return WorkbenchPathPolicy.from_settings(settings)


def get_preview_lease_registry() -> PreviewLeaseRegistry:
    return preview_lease_registry


def get_preview_listener_registry() -> PreviewListenerVerifierRegistry:
    return listener_verifier_registry


def _detail(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def _raise_preview_error(exc: WorkbenchError) -> NoReturn:
    status_code = status.HTTP_409_CONFLICT
    if isinstance(exc, (ProjectNotFound, PreviewLeaseNotFound)):
        status_code = status.HTTP_404_NOT_FOUND
    elif isinstance(exc, (ProjectRootForbidden, PreviewLeaseForbidden)):
        status_code = status.HTTP_403_FORBIDDEN
    elif isinstance(exc, ProjectRootInvalid):
        status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    elif isinstance(exc, (ProjectDisabled, PreviewLeaseLimitExceeded)):
        status_code = status.HTTP_409_CONFLICT
    raise HTTPException(
        status_code=status_code,
        detail=_detail(exc.code, exc.message),
    ) from exc


def _resolve_project_sync(
    *,
    user_id: str,
    user_role: str,
    project_id: str,
    path_policy: WorkbenchPathPolicy,
) -> None:
    """使用 worker 内独立数据库会话重新验证项目根。"""
    with SessionLocal() as fresh_db:
        WorkbenchProjectService(fresh_db, path_policy).resolve_project_root(
            user_id=user_id,
            user_role=user_role,
            project_id=project_id,
        )


def _project_verifier(
    *,
    user_id: str,
    user_role: str,
    project_id: str,
    path_policy: WorkbenchPathPolicy,
):
    async def verify() -> None:
        await asyncio.to_thread(
            _resolve_project_sync,
            user_id=user_id,
            user_role=user_role,
            project_id=project_id,
            path_policy=path_policy,
        )

    return verify


def _lease_response(lease: PreviewLease) -> PreviewLeaseResponse:
    return PreviewLeaseResponse(
        preview_id=lease.preview_id,
        project_id=lease.project_id,
        session_kind=lease.session_kind,
        session_id=lease.session_id,
        port=lease.port,
        expires_at=lease.expires_at,
    )


def _rewrite_preview_location(
    location: str,
    *,
    target_url: str,
    project_id: str,
    preview_id: str,
) -> str | None:
    """把本地上游重定向改写回租约路径，拒绝其他本地端口跳转。"""
    try:
        target = urlsplit(target_url)
        resolved = urlsplit(urljoin(target_url, location))
        target_port = target.port
        resolved_port = resolved.port
    except ValueError:
        return None
    local_hosts = {_TARGET_HOST, "localhost"}
    if resolved.hostname in local_hosts:
        if resolved.scheme not in {"http", "https"} or resolved_port != target_port:
            return None
        proxy_prefix = (
            f"/api/workbench/projects/{quote(project_id, safe='')}"
            f"/previews/{quote(preview_id, safe='')}"
        )
        upstream_path = resolved.path if resolved.path.startswith("/") else f"/{resolved.path}"
        return urlunsplit(("", "", f"{proxy_prefix}{upstream_path}", resolved.query, resolved.fragment))
    if resolved.scheme not in {"http", "https"}:
        return None
    return location


async def _close_proxy_resources(
    *,
    upstream_cm,
    client: httpx.AsyncClient | None,
    upstream_entered: bool,
) -> None:
    """关闭代理流与客户端；清理失败只记录脱敏事件。"""
    if upstream_cm is not None and upstream_entered:
        try:
            await upstream_cm.__aexit__(None, None, None)
        except Exception:
            logger.bind(event="preview_upstream_close_failed").opt(exception=True).warning(
                "关闭预览上游流失败"
            )
    if client is not None:
        try:
            await client.aclose()
        except Exception:
            logger.bind(event="preview_client_close_failed").opt(exception=True).warning(
                "关闭预览 HTTP 客户端失败"
            )


def _ensure_preview_enabled() -> None:
    if not _PREVIEW_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_detail("preview_proxy_disabled", "预览代理在当前环境不可用"),
        )


async def _close_preview_websocket(
    websocket: WebSocket,
    *,
    code: int,
    reason: str,
) -> None:
    """关闭浏览器连接，拒绝消息只使用稳定且脱敏的公开文本。"""
    try:
        await websocket.close(code=code, reason=reason)
    except RuntimeError:
        return


def _has_query_auth_token(websocket: WebSocket) -> bool:
    """拒绝 URL 中的认证凭据，避免 access log 与浏览器历史泄露。"""
    blocked_names = {"token", "access_token", "auth_token", "authorization"}
    return any(name.lower() in blocked_names for name in websocket.query_params.keys())


def _upstream_subprotocols(websocket: WebSocket) -> list[str]:
    """仅把非认证子协议传给上游，bearer 凭据止于代理边界。"""
    protocols: list[str] = []
    for value in websocket.headers.get("sec-websocket-protocol", "").split(","):
        protocol = value.strip()
        if protocol and not protocol.startswith("bearer."):
            protocols.append(protocol)
    return protocols


def _build_websocket_target_url(port: int, path: str, query: str) -> str:
    """构造只指向租约端口回环地址的 WebSocket 上游 URL。"""
    if not path.startswith("/"):
        path = "/" + path
    split = urlsplit(f"ws://{_TARGET_HOST}:{port}{path}")
    return urlunsplit(
        ("ws", f"{_TARGET_HOST}:{port}", split.path, query or split.query, "")
    )


async def _relay_browser_frames(websocket: WebSocket, upstream) -> None:
    """把浏览器文本和二进制帧原样发送给上游。"""
    while True:
        event = await websocket.receive()
        if event["type"] == "websocket.disconnect":
            return
        text = event.get("text")
        if text is not None:
            await upstream.send(text)
            continue
        data = event.get("bytes")
        if data is not None:
            await upstream.send(data)


async def _relay_upstream_frames(websocket: WebSocket, upstream) -> None:
    """把上游文本和二进制帧原样发送给浏览器。"""
    async for message in upstream:
        if isinstance(message, str):
            await websocket.send_text(message)
        else:
            await websocket.send_bytes(message)


async def _relay_websocket_bidirectionally(websocket: WebSocket, upstream) -> None:
    """任一方向结束时取消另一方向，确保连接和任务及时释放。"""
    browser_task = asyncio.create_task(_relay_browser_frames(websocket, upstream))
    upstream_task = asyncio.create_task(_relay_upstream_frames(websocket, upstream))
    tasks = {browser_task, upstream_task}
    try:
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


@router.post(
    "/api/workbench/projects/{project_id}/previews",
    response_model=PreviewLeaseResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_preview_lease(
    project_id: str,
    body: PreviewLeaseCreate,
    current_user: User = Depends(get_current_user),
    path_policy: WorkbenchPathPolicy = Depends(get_preview_path_policy),
    lease_registry: PreviewLeaseRegistry = Depends(get_preview_lease_registry),
    verifier_registry: PreviewListenerVerifierRegistry = Depends(get_preview_listener_registry),
) -> PreviewLeaseResponse:
    """在项目与 listener 均通过实时验证后签发短期租约。"""
    _ensure_preview_enabled()
    try:
        lease = await lease_registry.issue(
            user_id=str(current_user.id),
            project_id=project_id,
            session_kind=body.session_kind,
            session_id=body.session_id,
            port=body.port,
            verify_project=_project_verifier(
                user_id=str(current_user.id),
                user_role=str(current_user.role),
                project_id=project_id,
                path_policy=path_policy,
            ),
            verify_listener=verifier_registry.verify,
        )
    except WorkbenchError as exc:
        _raise_preview_error(exc)
    return _lease_response(lease)


@router.post(
    "/api/workbench/projects/{project_id}/previews/{preview_id}/renew",
    response_model=PreviewLeaseResponse,
)
async def renew_preview_lease(
    project_id: str,
    preview_id: str,
    current_user: User = Depends(get_current_user),
    path_policy: WorkbenchPathPolicy = Depends(get_preview_path_policy),
    lease_registry: PreviewLeaseRegistry = Depends(get_preview_lease_registry),
    verifier_registry: PreviewListenerVerifierRegistry = Depends(get_preview_listener_registry),
) -> PreviewLeaseResponse:
    """重验项目与 listener 后续租。"""
    _ensure_preview_enabled()
    try:
        lease = await lease_registry.renew(
            preview_id=preview_id,
            user_id=str(current_user.id),
            project_id=project_id,
            verify_project=_project_verifier(
                user_id=str(current_user.id),
                user_role=str(current_user.role),
                project_id=project_id,
                path_policy=path_policy,
            ),
            verify_listener=verifier_registry.verify,
        )
    except WorkbenchError as exc:
        _raise_preview_error(exc)
    return _lease_response(lease)


@router.delete(
    "/api/workbench/projects/{project_id}/previews/{preview_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_preview_lease(
    project_id: str,
    preview_id: str,
    current_user: User = Depends(get_current_user),
    lease_registry: PreviewLeaseRegistry = Depends(get_preview_lease_registry),
) -> Response:
    """撤销当前用户在指定项目中的预览租约。"""
    _ensure_preview_enabled()
    try:
        await lease_registry.revoke(
            preview_id=preview_id,
            user_id=str(current_user.id),
            project_id=project_id,
        )
    except WorkbenchError as exc:
        _raise_preview_error(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.websocket(
    "/api/workbench/projects/{project_id}/previews/{preview_id}/{path:path}"
)
async def proxy_workbench_preview_websocket(
    websocket: WebSocket,
    project_id: str,
    preview_id: str,
    path: str,
    path_policy: WorkbenchPathPolicy = Depends(get_preview_path_policy),
    lease_registry: PreviewLeaseRegistry = Depends(get_preview_lease_registry),
    verifier_registry: PreviewListenerVerifierRegistry = Depends(
        get_preview_listener_registry
    ),
) -> None:
    """认证并双向代理指定工作台预览租约的 WebSocket 帧。"""
    if not _PREVIEW_ENABLED:
        await _close_preview_websocket(
            websocket,
            code=4404,
            reason="Preview unavailable",
        )
        return
    if _has_query_auth_token(websocket):
        await _close_preview_websocket(
            websocket,
            code=4400,
            reason="Query authentication is not allowed",
        )
        return
    if not validate_ws_origin(websocket.headers.get("origin", "")):
        await _close_preview_websocket(
            websocket,
            code=4403,
            reason="Origin not allowed",
        )
        return

    token, _ = extract_token_from_subprotocol(websocket)
    if not token:
        token = websocket.cookies.get(ACCESS_TOKEN_COOKIE_NAME, "")
    if not token:
        await _close_preview_websocket(
            websocket,
            code=4401,
            reason="Authentication required",
        )
        return
    try:
        current_user = await asyncio.to_thread(resolve_ws_user_from_token, token)
    except Exception as exc:
        logger.bind(
            event="preview_websocket_auth_failed",
            error_type=type(exc).__name__,
        ).warning("工作台预览 WebSocket 鉴权失败")
        current_user = None
    if current_user is None:
        await _close_preview_websocket(
            websocket,
            code=4401,
            reason="Authentication required",
        )
        return

    try:
        lease = await lease_registry.consume(
            preview_id=preview_id,
            user_id=str(current_user.id),
            project_id=project_id,
            verify_project=_project_verifier(
                user_id=str(current_user.id),
                user_role=str(current_user.role),
                project_id=project_id,
                path_policy=path_policy,
            ),
            verify_listener=verifier_registry.verify,
        )
    except Exception as exc:
        logger.bind(
            event="preview_websocket_lease_rejected",
            error_type=type(exc).__name__,
        ).warning("工作台预览 WebSocket 租约校验失败")
        await _close_preview_websocket(
            websocket,
            code=4404,
            reason="Preview unavailable",
        )
        return

    target_url = _build_websocket_target_url(
        lease.port,
        path,
        websocket.url.query,
    )
    forward_headers = {
        name.lower(): value
        for name, value in websocket.headers.items()
        if name.lower() in _SAFE_WEBSOCKET_REQUEST_HEADERS
    }
    requested_subprotocols = _upstream_subprotocols(websocket)
    accepted = False
    try:
        async with websockets.connect(
            target_url,
            subprotocols=requested_subprotocols or None,
            extra_headers=forward_headers,
            open_timeout=10,
            close_timeout=5,
        ) as upstream:
            selected_subprotocol = getattr(upstream, "subprotocol", None)
            if selected_subprotocol not in requested_subprotocols:
                selected_subprotocol = None
            await websocket.accept(subprotocol=selected_subprotocol)
            accepted = True
            await _relay_websocket_bidirectionally(websocket, upstream)
    except Exception as exc:
        logger.bind(
            event="preview_websocket_upstream_failed",
            error_type=type(exc).__name__,
        ).warning("工作台预览 WebSocket 上游连接失败")
        await _close_preview_websocket(
            websocket,
            code=1013,
            reason="Preview unavailable",
        )
        return
    if accepted:
        await _close_preview_websocket(websocket, code=1000, reason="")


@router.api_route(
    "/api/workbench/projects/{project_id}/previews/{preview_id}/{path:path}",
    methods=["GET", "HEAD"],
)
async def proxy_workbench_preview(
    project_id: str,
    preview_id: str,
    path: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    path_policy: WorkbenchPathPolicy = Depends(get_preview_path_policy),
    lease_registry: PreviewLeaseRegistry = Depends(get_preview_lease_registry),
    verifier_registry: PreviewListenerVerifierRegistry = Depends(get_preview_listener_registry),
) -> Response:
    """使用短期租约代理已归属的本地开发服务器。"""
    _ensure_preview_enabled()
    try:
        lease = await lease_registry.consume(
            preview_id=preview_id,
            user_id=str(current_user.id),
            project_id=project_id,
            verify_project=_project_verifier(
                user_id=str(current_user.id),
                user_role=str(current_user.role),
                project_id=project_id,
                path_policy=path_policy,
            ),
            verify_listener=verifier_registry.verify,
        )
    except WorkbenchError as exc:
        _raise_preview_error(exc)

    target_url = _build_target_url(lease.port, path, request.url.query)
    forward_headers = {
        name.lower(): value
        for name, value in request.headers.items()
        if name.lower() in _SAFE_REQUEST_HEADERS
    }
    client = None
    upstream_cm = None
    upstream_entered = False
    try:
        client = httpx.AsyncClient(follow_redirects=False, timeout=30.0)
        upstream_cm = client.stream(
            request.method,
            target_url,
            headers=forward_headers,
        )
        upstream = await upstream_cm.__aenter__()
        upstream_entered = True
        connection_scoped_headers = {
            token.strip().lower()
            for token in upstream.headers.get("connection", "").split(",")
            if token.strip()
        }
        blocked_response_headers = _BLOCKED_RESPONSE_HEADERS | connection_scoped_headers
        response_headers = {
            name: value
            for name, value in upstream.headers.items()
            if name.lower() not in blocked_response_headers
        }
        location_key = next(
            (name for name in response_headers if name.lower() == "location"),
            None,
        )
        if location_key is not None:
            rewritten_location = _rewrite_preview_location(
                response_headers[location_key],
                target_url=target_url,
                project_id=project_id,
                preview_id=preview_id,
            )
            if rewritten_location is None:
                response_headers.pop(location_key, None)
            else:
                response_headers[location_key] = rewritten_location

        if request.method == "HEAD":
            await _close_proxy_resources(
                upstream_cm=upstream_cm,
                client=client,
                upstream_entered=upstream_entered,
            )
            return Response(
                status_code=upstream.status_code,
                headers=response_headers,
            )

        async def body_iterator():
            try:
                async for chunk in upstream.aiter_raw():
                    yield chunk
            finally:
                await _close_proxy_resources(
                    upstream_cm=upstream_cm,
                    client=client,
                    upstream_entered=upstream_entered,
                )

        return StreamingResponse(
            body_iterator(),
            status_code=upstream.status_code,
            headers=response_headers,
        )
    except Exception:
        await _close_proxy_resources(
            upstream_cm=upstream_cm,
            client=client,
            upstream_entered=upstream_entered,
        )
        logger.bind(event="preview_proxy_error", module="preview_proxy").opt(
            exception=True
        ).warning("工作台预览上游请求失败")
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content={
                "detail": _detail(
                    "preview_upstream_unavailable",
                    "预览服务暂时不可用",
                )
            },
        )

# 固定目标主机，禁止用户传入
_TARGET_HOST = "127.0.0.1"

# 透传时丢弃的 hop-by-hop 头（HTTP/1.1 规范）
_HOP_BY_HOP_HEADERS = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "proxy-connection",
        "te",
        "trailers",
        "transfer-encoding",
        "upgrade",
    }
)

_SAFE_REQUEST_HEADERS = frozenset(
    {
        "accept",
        "accept-encoding",
        "accept-language",
        "cache-control",
        "if-match",
        "if-modified-since",
        "if-none-match",
        "if-range",
        "range",
        "user-agent",
    }
)

_SAFE_WEBSOCKET_REQUEST_HEADERS = frozenset(
    {
        "accept-language",
        "cache-control",
        "pragma",
    }
)

_BLOCKED_RESPONSE_HEADERS = _HOP_BY_HOP_HEADERS | frozenset(
    {
        "refresh",
        "set-cookie",
        "set-cookie2",
    }
)

# 生产环境禁用预览代理（防止公网部署被滥用为 SSRF 跳板）
if is_production_environment(settings.ENVIRONMENT):
    _PREVIEW_ENABLED = False
else:
    _PREVIEW_ENABLED = os.getenv("ENABLE_PREVIEW_PROXY", "true").lower() == "true"


def _build_target_url(port: int, path: str, query: Optional[str]) -> str:
    """构造反向代理目标 URL，强制使用 127.0.0.1 作为主机。

    防止通过 path 注入其它主机：path 中的 authority 段不会被解析为主机。
    """
    # 确保 path 以 / 开头
    if not path.startswith("/"):
        path = "/" + path
    # 重新组装 URL，强制 host
    split = urlsplit(f"http://{_TARGET_HOST}:{port}{path}")
    # 显式忽略 split 中的 netloc，用我们自己的
    target = urlunsplit(("http", f"{_TARGET_HOST}:{port}", split.path, query or split.query, ""))
    return target


@router.get("/api/preview/{port}/{path:path}")
async def legacy_preview_proxy_tombstone(
    port: int,
    request: Request,
    path: str,
    current_user: User = Depends(get_current_user),
) -> Response:
    """返回旧裸端口代理的结构化退役响应，绝不访问上游。"""
    del port, request, path, current_user
    return JSONResponse(
        status_code=status.HTTP_410_GONE,
        headers={"Deprecation": "true"},
        content={
            "detail": _detail(
                "preview_proxy_retired",
                "裸端口预览代理已停用，请使用工作台预览租约",
            )
        },
    )
