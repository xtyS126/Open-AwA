# -*- coding: utf-8 -*-
"""
本地开发服务器反向代理路由。

将前端本地开发服务器（如 Vite 5173、Next 3000）的响应透传给客户端，
便于在统一域名下访问预览页面。仅允许代理到 127.0.0.1，避免 SSRF 风险。
"""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

import httpx
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import StreamingResponse

router = APIRouter(prefix="/api/preview", tags=["preview"])

# 允许的端口范围（避免代理到特权端口或非法端口）
_MIN_PORT = 1024
_MAX_PORT = 65535

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


def _validate_port(port: int) -> None:
    """校验端口范围，防止代理到特权端口或非法端口。"""
    if port < _MIN_PORT or port > _MAX_PORT:
        raise HTTPException(
            status_code=400,
            detail=f"port must be between {_MIN_PORT} and {_MAX_PORT}, got {port}",
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

    - port 必须在 1024-65535 范围内
    - 目标主机固定为 127.0.0.1，不接受用户传入
    - 透传响应状态码、headers、body
    """
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
