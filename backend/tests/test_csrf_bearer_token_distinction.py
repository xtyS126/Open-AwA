"""
CSRF 中间件 Bearer token 类型区分测试。

验证 CSRF 豁免策略（基于双提交 Cookie 模式）：
- 纯 Bearer token 认证（无 Cookie）豁免 CSRF 验证：CSRF 攻击依赖浏览器自动携带 Cookie，
  若请求无 Cookie，则 CSRF 无攻击面，无论 Bearer token 是 API Key 还是 JWT 格式
- 携带 Cookie 的请求（含 Bearer token）必须通过 X-CSRF-Token 校验
- 无 Bearer token 的 Cookie 认证请求必须通过 X-CSRF-Token 校验
"""

import os
import pytest
from unittest.mock import MagicMock, patch
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.datastructures import Headers


# 导入 CSRF 中间件函数
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from main import csrf_protection_middleware


@pytest.fixture(autouse=True)
def disable_skip_csrf_env():
    """临时取消 SKIP_CSRF_FOR_TEST 环境变量，使 CSRF 中间件正常执行校验逻辑。"""
    original = os.environ.pop("SKIP_CSRF_FOR_TEST", None)
    try:
        yield
    finally:
        if original is not None:
            os.environ["SKIP_CSRF_FOR_TEST"] = original
        else:
            os.environ.pop("SKIP_CSRF_FOR_TEST", None)


class MockResponse:
    """模拟响应对象"""
    def __init__(self, status_code=200):
        self.status_code = status_code


@pytest.fixture
def mock_call_next():
    """模拟 call_next 函数"""
    async def _call_next(request):
        return MockResponse(status_code=200)
    return _call_next


@pytest.fixture
def mock_csrf_exempt_paths():
    """模拟 CSRF 豁免路径"""
    with patch('main._CSRF_EXEMPT_PATHS', set()):
        yield


@pytest.fixture
def mock_csrf_checked_methods():
    """模拟 CSRF 检查的 HTTP 方法"""
    with patch('main._CSRF_CHECKED_METHODS', {'POST', 'PUT', 'DELETE', 'PATCH'}):
        yield


class TestCSRFBearerTokenDistinction:
    """测试 CSRF 中间件对 Bearer token 类型的区分"""

    @pytest.mark.asyncio
    async def test_api_key_bearer_exempt_from_csrf(
        self, mock_call_next, mock_csrf_exempt_paths, mock_csrf_checked_methods
    ):
        """API Key Bearer token (非 JWT 格式) 应豁免 CSRF 验证"""
        # 构造 API Key Bearer token (非 JWT 格式)
        api_key = "sk-" + "a" * 40  # 总共 43 字符，非 JWT 格式

        headers = Headers({
            "authorization": f"Bearer {api_key}",
        })
        request = MagicMock(spec=Request)
        request.url.path = "/api/chat/send"
        request.method = "POST"
        request.headers = headers

        # 调用中间件
        response = await csrf_protection_middleware(request, mock_call_next)

        # API Key Bearer 应直接放行，返回 200
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_api_key_bearer_arbitrary_format_exempt_from_csrf(
        self, mock_call_next, mock_csrf_exempt_paths, mock_csrf_checked_methods
    ):
        """任意非 JWT 格式的 API Key Bearer token 均应豁免 CSRF 验证"""
        # 构造各种非 JWT 格式的 API Key
        api_keys = [
            "deepseek-api-key-12345",  # deepseek 格式
            "openawa_secret_key_abc",  # 自定义格式
            "pk-" + "b" * 50,  # 其他前缀格式
            "short",  # 短 token
        ]

        for api_key in api_keys:
            headers = Headers({
                "authorization": f"Bearer {api_key}",
            })
            request = MagicMock(spec=Request)
            request.url.path = "/api/chat/send"
            request.method = "POST"
            request.headers = headers

            # 调用中间件
            response = await csrf_protection_middleware(request, mock_call_next)

            # 非 JWT 格式的 Bearer token 均应直接放行
            assert response.status_code == 200, f"API Key {api_key} 应豁免 CSRF"

    @pytest.mark.asyncio
    async def test_jwt_bearer_without_cookie_exempt_from_csrf(
        self, mock_call_next, mock_csrf_exempt_paths, mock_csrf_checked_methods
    ):
        """纯 JWT Bearer token（无 Cookie）豁免 CSRF 验证。

        新策略：CSRF 攻击依赖浏览器自动携带 Cookie，若请求无 Cookie，
        则 CSRF 无攻击面，无论 Bearer token 是 JWT 还是 API Key 格式。
        """
        # 构造 JWT 格式 token (三段 base64 用 . 连接)
        jwt_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ1c2VyLTEyMyIsImV4cCI6OTk5OTk5OTk5OX0.signature"

        headers = Headers({
            "authorization": f"Bearer {jwt_token}",
        })
        request = MagicMock(spec=Request)
        request.url.path = "/api/chat/send"
        request.method = "POST"
        request.headers = headers

        # 调用中间件
        response = await csrf_protection_middleware(request, mock_call_next)

        # 纯 Bearer（无 Cookie）应直接放行，返回 200
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_jwt_bearer_with_cookie_requires_csrf_token(
        self, mock_call_next, mock_csrf_exempt_paths, mock_csrf_checked_methods
    ):
        """JWT Bearer token 携带 Cookie 时必须通过 CSRF 校验（缺失 CSRF token 返回 403）。

        策略：若请求同时携带 Cookie（可能存在基于 Cookie 的会话），
        即使有 Bearer header 也继续校验 CSRF。
        """
        # 构造 JWT 格式 token (三段 base64 用 . 连接)
        jwt_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ1c2VyLTEyMyIsImV4cCI6OTk5OTk5OTk5OX0.signature"

        headers = Headers({
            "authorization": f"Bearer {jwt_token}",
            "cookie": "access_token=abc123",
        })
        request = MagicMock(spec=Request)
        request.url.path = "/api/chat/send"
        request.method = "POST"
        request.headers = headers

        # 调用中间件
        response = await csrf_protection_middleware(request, mock_call_next)

        # Bearer + Cookie 但无 CSRF token 应返回 403
        assert response.status_code == 403
        # 解析响应体校验错误码
        import json
        body = json.loads(response.body.decode("utf-8"))
        assert body["error"] == "missing_csrf_token"

    @pytest.mark.asyncio
    async def test_jwt_bearer_with_cookie_and_valid_csrf_token_passes(
        self, mock_call_next, mock_csrf_exempt_paths, mock_csrf_checked_methods
    ):
        """JWT Bearer token 携带 Cookie 且 CSRF 校验通过时应正常放行。

        新策略：Bearer + Cookie 组合需要 CSRF 校验，校验通过则放行。
        """
        # 构造 JWT 格式 token
        jwt_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ1c2VyLTEyMyIsImV4cCI6OTk5OTk5OTk5OX0.signature"

        headers = Headers({
            "authorization": f"Bearer {jwt_token}",
            "cookie": "access_token=abc123",
            "x-csrf-token": "some-csrf-token",
        })
        request = MagicMock(spec=Request)
        request.url.path = "/api/chat/send"
        request.method = "POST"
        request.headers = headers

        # Mock validate_csrf_request 返回 True（校验通过）
        with patch('main.validate_csrf_request', return_value=True):
            response = await csrf_protection_middleware(request, mock_call_next)

        # CSRF 校验通过应放行，返回 200
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_jwt_bearer_with_cookie_and_invalid_csrf_token_rejected(
        self, mock_call_next, mock_csrf_exempt_paths, mock_csrf_checked_methods
    ):
        """JWT Bearer token 携带 Cookie 但 CSRF 校验失败时应返回 403。

        新策略：Bearer + Cookie 组合需要 CSRF 校验，校验失败则拒绝。
        """
        # 构造 JWT 格式 token
        jwt_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ1c2VyLTEyMyIsImV4cCI6OTk5OTk5OTk5OX0.signature"

        headers = Headers({
            "authorization": f"Bearer {jwt_token}",
            "cookie": "access_token=abc123",
            "x-csrf-token": "invalid_csrf_token",
        })
        request = MagicMock(spec=Request)
        request.url.path = "/api/chat/send"
        request.method = "POST"
        request.headers = headers

        # Mock validate_csrf_request 返回 False（校验失败）
        with patch('main.validate_csrf_request', return_value=False):
            response = await csrf_protection_middleware(request, mock_call_next)

        # CSRF 校验失败应返回 403
        assert response.status_code == 403
        # 解析响应体校验错误码
        import json
        body = json.loads(response.body.decode("utf-8"))
        assert body["error"] == "invalid_csrf_token"

    @pytest.mark.asyncio
    async def test_api_key_bearer_short_token_exempt_from_csrf(
        self, mock_call_next, mock_csrf_exempt_paths, mock_csrf_checked_methods
    ):
        """短 token (非 JWT 格式) 应视为 API Key，豁免 CSRF"""
        # 构造短 token (非 JWT 格式)
        short_token = "sk-" + "a" * 10  # 总共 13 字符，非 JWT 格式

        headers = Headers({
            "authorization": f"Bearer {short_token}",
        })
        request = MagicMock(spec=Request)
        request.url.path = "/api/chat/send"
        request.method = "POST"
        request.headers = headers

        # 调用中间件
        response = await csrf_protection_middleware(request, mock_call_next)

        # 非 JWT 格式的短 token 应视为 API Key，直接放行
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_no_bearer_token_requires_csrf(
        self, mock_call_next, mock_csrf_exempt_paths, mock_csrf_checked_methods
    ):
        """无 Bearer token 的请求需要 CSRF token"""
        headers = Headers({})
        request = MagicMock(spec=Request)
        request.url.path = "/api/chat/send"
        request.method = "POST"
        request.headers = headers
        
        # 调用中间件
        response = await csrf_protection_middleware(request, mock_call_next)
        
        # 无 Bearer token 且无 CSRF token，应返回 403
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_get_request_exempt_from_csrf(
        self, mock_call_next, mock_csrf_exempt_paths, mock_csrf_checked_methods
    ):
        """GET 请求不受 CSRF 校验影响"""
        headers = Headers({})
        request = MagicMock(spec=Request)
        request.url.path = "/api/chat/history"
        request.method = "GET"
        request.headers = headers
        
        # 调用中间件
        response = await csrf_protection_middleware(request, mock_call_next)
        
        # GET 请求不在 CSRF 检查方法列表中，应直接放行
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_websocket_request_exempt_from_csrf(
        self, mock_call_next, mock_csrf_exempt_paths, mock_csrf_checked_methods
    ):
        """WebSocket 请求豁免 CSRF 校验"""
        headers = Headers({
            "upgrade": "websocket",
        })
        request = MagicMock(spec=Request)
        request.url.path = "/api/ws"
        request.method = "GET"
        request.headers = headers
        
        # 调用中间件
        response = await csrf_protection_middleware(request, mock_call_next)
        
        # WebSocket 请求应直接放行
        assert response.status_code == 200
