from types import SimpleNamespace

from api.dependencies import _resolve_request_token
from config.security import ACCESS_TOKEN_COOKIE_NAME


def test_resolve_request_token_rejects_overlong_bearer_token():
    """超长 Bearer Token 应直接被拒绝。"""
    request = SimpleNamespace(cookies={})

    assert _resolve_request_token(request, "a" * 2049) is None


def test_resolve_request_token_rejects_cookie_token_with_whitespace():
    """包含空白分隔的 Cookie Token 应视为无效。"""
    request = SimpleNamespace(cookies={ACCESS_TOKEN_COOKIE_NAME: "abc def"})

    assert _resolve_request_token(request, None) is None


def test_resolve_request_token_falls_back_to_valid_cookie_token():
    """当 Bearer Token 无效时，应继续尝试使用合法 Cookie Token。"""
    request = SimpleNamespace(cookies={ACCESS_TOKEN_COOKIE_NAME: "valid-cookie-token"})

    assert _resolve_request_token(request, "a" * 2049) == "valid-cookie-token"
