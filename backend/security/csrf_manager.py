"""
CSRF 防护模块，基于 fastapi-csrf-protect 实现双提交 Cookie 模式。

设计原则：
- 使用 fastapi-csrf-protect 库替代自实现的 CsrfTokenManager
- 双提交 Cookie 模式：签名 token 存 Cookie，原始 token 由前端通过 X-CSRF-Token header 回传
- 中间件校验 header 中的原始 token 与 Cookie 中的签名 token 是否匹配
- Bearer 认证（无 Cookie）的请求豁免 CSRF 校验（CSRF 仅对 Cookie 认证有意义）
"""

from typing import Optional, Tuple

from fastapi import Request, Response
from fastapi_csrf_protect import CsrfProtect
from fastapi_csrf_protect.exceptions import (
    CsrfProtectError,
    MissingTokenError,
    TokenValidationError,
    InvalidHeaderError,
)
from loguru import logger

from config.settings import settings


def _build_csrf_config() -> CsrfProtect:
    """
    构造已加载配置的 CsrfProtect 实例。

    配置项：
    - secret_key: 从 settings.CSRF_SECRET_KEY 复用，确保多 Worker 一致
    - cookie_key: csrf_access_token（避免与 access_token Cookie 冲突）
    - cookie_samesite: lax（与 access_token Cookie 一致，兼容顶层导航）
    - cookie_secure: 生产环境启用 Secure
    - httponly: False（前端无需读 Cookie，但保留默认非 HttpOnly 以便调试；
      双提交模式下攻击者即便读到 Cookie 也无法在跨站请求中携带 header）
    - header_name: X-CSRF-Token（与前端约定一致）
    - token_location: header（前端通过 header 提交，不用 form）
    - max_age: 与 access token 过期时间一致
    - methods: 需要校验的 HTTP 方法
    """
    # 生产环境启用 Secure 标记
    from config.settings import is_production_environment
    import os
    secure_cookie = is_production_environment(os.getenv("ENVIRONMENT", "development"))

    csrf = CsrfProtect()
    csrf.load_config(lambda: (
        ("secret_key", settings.CSRF_SECRET_KEY),
        ("cookie_key", "csrf_access_token"),
        ("cookie_samesite", "lax"),
        ("cookie_secure", secure_cookie),
        ("httponly", False),
        ("header_name", "X-CSRF-Token"),
        ("header_type", ""),
        ("token_location", "header"),
        ("max_age", int(settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60)),
        ("methods", ["POST", "PUT", "DELETE", "PATCH"]),
    ))
    return csrf


# 模块级单例：避免每次请求重复加载配置
_csrf_protect: Optional[CsrfProtect] = None


def get_csrf_protect() -> CsrfProtect:
    """
    获取全局 CsrfProtect 实例（单例）。

    Returns:
        已加载配置的 CsrfProtect 实例。
    """
    global _csrf_protect
    if _csrf_protect is None:
        _csrf_protect = _build_csrf_config()
    return _csrf_protect


def generate_csrf_token_pair(response: Optional[Response] = None) -> Tuple[str, str]:
    """
    生成 CSRF token 对（原始 token + 签名 token），并可选地写入 Cookie。

    Args:
        response: 若提供，则将签名 token 写入 CSRF Cookie。

    Returns:
        (raw_token, signed_token) 元组：
        - raw_token: 由前端通过 X-CSRF-Token header 回传
        - signed_token: 由后端写入 Cookie，用于校验
    """
    csrf = get_csrf_protect()
    raw_token, signed_token = csrf.generate_csrf_tokens()
    if response is not None:
        csrf.set_csrf_cookie(signed_token, response)
    return raw_token, signed_token


def validate_csrf_request(request: Request) -> bool:
    """
    校验请求中的 CSRF token 是否与 Cookie 中的签名 token 匹配。

    Args:
        request: FastAPI 请求对象。

    Returns:
        True 表示校验通过，False 表示校验失败。
    """
    csrf = get_csrf_protect()
    try:
        csrf.validate_csrf(request)
        return True
    except (MissingTokenError, TokenValidationError, InvalidHeaderError) as exc:
        logger.bind(
            event="csrf_validation_failed",
            module="csrf_manager",
            reason=str(exc),
        ).debug(f"CSRF 校验失败: {exc}")
        return False
    except CsrfProtectError as exc:
        logger.bind(
            event="csrf_validation_error",
            module="csrf_manager",
            reason=str(exc),
        ).warning(f"CSRF 校验异常: {exc}")
        return False
