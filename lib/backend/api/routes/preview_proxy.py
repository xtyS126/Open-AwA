# -*- coding: utf-8 -*-
"""
本地开发服务器反向代理路由。

将前端本地开发服务器（如 Vite 5173、Next 3000）的响应透传给客户端，
便于在统一域名下访问预览页面。仅允许代理到 127.0.0.1，避免 SSRF 风险。

安全控制：
1. 强制认证（Depends(get_current_user)），防止未认证 SSRF
2. 端口白名单：仅允许已知本地开发服务器端口，禁止代理到后端自身（8000）和数据库等内部服务
3. 仅在非生产环境启用，生产环境直接 404
"""

from __future__ import annotations

import os
from typing import Optional
from urllib.parse import urlsplit, urlunsplit

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse

from api.dependencies import get_current_user
from config.settings import is_production_environment, settings

router = APIRouter(
    prefix="/api/preview",
    tags=["preview"],
    dependencies=[Depends(get_current_user)],
)

# 允许代理的本地开发服务器端口白名单（防止 SSRF 探测内部服务）
# 5173: Vite 默认端口；3000: Next.js 默认端口；4173: Vite preview 端口
_ALLOWED_PREVIEW_PORTS = frozenset({5173, 4173, 3000, 8080})

# 固定目标主机，禁止用户传入
_TARGET_HOST = "127.0.0.1"

# 透传时丢弃的 hop-by-hop 头（HTTP/1.1 规范）
_HOP_BY_HOP_HEADERS = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "transfer-encoding",
        "upgrade",
    }
)

# 生产环境禁用预览代理（防止公网部署被滥用为 SSRF 跳板）
if is_production_environment(settings.ENVIRONMENT):
    _PREVIEW_ENABLED = False
else:
    _PREVIEW_ENABLED = os.getenv("ENABLE_PREVIEW_PROXY", "true").lower() == "true"


def _validate_port(port: int) -> None:
    """校验端口必须在白名单内，防止代理到非预期内部服务（SSRF 防护）。"""
    if port not in _ALLOWED_PREVIEW_PORTS:
        raise HTTPException(
            status_code=400,
            detail=f"preview proxy only allows ports {sorted(_ALLOWED_PREVIEW_PORTS)}, got {port}",
        )


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


@router.get("/{port}/{path:path}")
async def proxy_to_local(
    port: int,
    request: Request,
    path: str,
) -> Response:
    """
    反向代理到本地开发服务器 http://127.0.0.1:{port}/{path}。

    - 需要认证（router 级 Depends 已强制）
    - port 必须在白名单内（5173/4173/3000/8080）
    - 生产环境直接 404
    - 目标主机固定为 127.0.0.1，不接受用户传入
    - 透传响应状态码、headers、body
    """
    # 生产环境完全禁用预览代理
    if not _PREVIEW_ENABLED:
        raise HTTPException(status_code=404, detail="preview proxy disabled in production")

    _validate_port(port)

    target_url = _build_target_url(port, path, request.url.query)

    # 收集需要转发的请求头（去除 hop-by-hop）
    forward_headers = {
        k: v for k, v in request.headers.items() if k.lower() not in _HOP_BY_HOP_HEADERS
    }
    # 强制覆盖 Host，避免暴露内部 host
    forward_headers["host"] = f"{_TARGET_HOST}:{port}"

    client = httpx.AsyncClient(follow_redirects=False, timeout=30.0)

    # 直接 await client.stream 进入上下文，捕获响应头与状态码
    try:
        upstream_cm = client.stream("GET", target_url, headers=forward_headers)
        upstream = await upstream_cm.__aenter__()

        passthrough_headers = {
            k: v for k, v in upstream.headers.items() if k.lower() not in _HOP_BY_HOP_HEADERS
        }

        async def body_iterator():
            try:
                async for chunk in upstream.aiter_bytes():
                    yield chunk
            finally:
                await upstream_cm.__aexit__(None, None, None)
                await client.aclose()

        return StreamingResponse(
            body_iterator(),
            status_code=upstream.status_code,
            headers=passthrough_headers,
        )
    except httpx.RequestError as exc:
        await client.aclose()
        return Response(
            content=f'{{"detail":"upstream error: {exc}"}}',
            status_code=502,
            media_type="application/json",
        )
    except Exception:
        # __aenter__ 等非 RequestError 异常同样必须关闭客户端，防止连接池泄漏。
        await client.aclose()
        logger.bind(event="preview_proxy_error", module="preview_proxy").opt(exception=True).error(
            "预览代理请求失败"
        )
        return Response(
            content='{"detail":"upstream unavailable"}',
            status_code=502,
            media_type="application/json",
        )
