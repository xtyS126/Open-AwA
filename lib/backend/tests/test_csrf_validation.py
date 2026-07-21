"""CSRF 双提交 token 的真实异步校验测试。"""

from urllib.parse import quote

import pytest
from starlette.requests import Request
from starlette.responses import Response

from security.csrf_manager import generate_csrf_token_pair, validate_csrf_request


def _build_request(raw_token: str, signed_token: str) -> Request:
    """构造同时携带原始 token header 与签名 token Cookie 的请求。"""
    cookie_value = quote(signed_token, safe="")
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/test",
        "headers": [
            (b"x-csrf-token", raw_token.encode("ascii")),
            (b"cookie", f"csrf_access_token={cookie_value}".encode("ascii")),
        ],
    }
    return Request(scope)


@pytest.mark.asyncio
async def test_valid_csrf_token_pair_is_accepted():
    """同一对原始 token 与签名 Cookie 必须通过校验。"""
    raw_token, signed_token = generate_csrf_token_pair()

    assert await validate_csrf_request(_build_request(raw_token, signed_token)) is True


@pytest.mark.asyncio
async def test_forged_csrf_header_is_rejected():
    """伪造 header 即使携带合法签名 Cookie 也必须被拒绝。"""
    _, signed_token = generate_csrf_token_pair()

    assert await validate_csrf_request(_build_request("forged-token", signed_token)) is False


@pytest.mark.asyncio
async def test_missing_csrf_cookie_is_rejected():
    """缺少签名 Cookie 时不得只凭 header 放行。"""
    raw_token, _ = generate_csrf_token_pair()
    request = Request({
        "type": "http",
        "method": "POST",
        "path": "/api/test",
        "headers": [(b"x-csrf-token", raw_token.encode("ascii"))],
    })

    assert await validate_csrf_request(request) is False


def test_generate_csrf_token_pair_sets_signed_cookie_on_response():
    """向响应签发 token 对时必须同时写入签名 Cookie。"""
    response = Response()

    raw_token, signed_token = generate_csrf_token_pair(response)

    assert raw_token
    assert signed_token
    assert "csrf_access_token=" in response.headers["set-cookie"]
