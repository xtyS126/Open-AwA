"""
backend_mobile 安全模块

提供密码哈希、JWT 令牌、CSRF 令牌功能。
与桌面版 backend/config/security.py 的差异：
- passlib 不带 [bcrypt]，使用 pbkdf2_sha256 纯 Python 后端
- JWT 使用 PyJWT（与桌面版一致）
- CSRF 令牌使用 secrets.token_urlsafe 生成
"""

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import jwt
from passlib.context import CryptContext

from .config import get_settings

# 密码哈希上下文：使用 pbkdf2_sha256（纯 Python，无 C 扩展依赖）
_pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")


def hash_password(password: str) -> str:
    """哈希密码"""
    return _pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码"""
    try:
        return _pwd_context.verify(plain_password, hashed_password)
    except (ValueError, TypeError):
        return False


def create_access_token(
    data: dict[str, Any],
    expires_delta: Optional[timedelta] = None,
) -> str:
    """
    创建 JWT 访问令牌

    参数：
        data: 令牌载荷（必须包含 sub 字段标识用户）
        expires_delta: 过期时间增量，默认使用配置中的 access_token_expire_minutes
    """
    settings = get_settings()
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta
        if expires_delta is not None
        else timedelta(minutes=settings.access_token_expire_minutes)
    )
    to_encode["exp"] = expire
    return jwt.encode(to_encode, settings.jwt_secret_key, algorithm="HS256")


def decode_access_token(token: str) -> dict[str, Any]:
    """
    解码 JWT 令牌

    返回令牌载荷，失败抛出 jwt.PyJWTError
    """
    settings = get_settings()
    return jwt.decode(token, settings.jwt_secret_key, algorithms=["HS256"])


def generate_csrf_token() -> str:
    """生成 CSRF 令牌（32 字节随机字符串）"""
    return secrets.token_urlsafe(32)


def set_access_token_cookie(response, token: str) -> None:
    """在响应中设置访问令牌 Cookie"""
    settings = get_settings()
    response.set_cookie(
        key=settings.access_token_cookie_name,
        value=token,
        httponly=True,
        secure=False,  # 移动端 WebView 走 http://127.0.0.1
        samesite="lax",
        max_age=settings.access_token_expire_minutes * 60,
        path="/",
    )


def clear_access_token_cookie(response) -> None:
    """清除访问令牌 Cookie"""
    settings = get_settings()
    response.delete_cookie(
        key=settings.access_token_cookie_name,
        path="/",
    )


def set_csrf_cookie(response, token: str) -> None:
    """在响应中设置 CSRF 令牌 Cookie"""
    settings = get_settings()
    response.set_cookie(
        key=settings.csrf_cookie_name,
        value=token,
        httponly=False,  # 前端需要读取
        secure=False,
        samesite="lax",
        max_age=settings.access_token_expire_minutes * 60,
        path="/",
    )
