"""
后端接口依赖注入模块，负责认证、数据库会话与通用依赖能力的装配。
当路由需要复用身份验证或上下文能力时，通常会先经过这一层。

单用户模式下，认证优先级为：API Key > JWT > 密码验证 > Cookie。
"""

import asyncio
import os
import re
import secrets as _secrets
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from loguru import logger
from sqlalchemy.orm import Session

from config.security import (
    ACCESS_TOKEN_COOKIE_NAME,
    decode_access_token,
    is_token_blacklisted,
    verify_password,
)
from config.settings import settings
from core.password_cache import password_verification_cache
from db.models import User, get_db, SessionLocal


oauth2_scheme = HTTPBearer(auto_error=False)
_MAX_REQUEST_TOKEN_LENGTH = 2048
# token 合法字符集：字母、数字、点、横杠、下划线、等号
_TOKEN_CHARSET_RE = re.compile(r'^[A-Za-z0-9._\-=]+$')


def _load_user_by_username(username: str) -> Optional["User"]:
    """
    在独立会话中按用户名加载用户，确保不把请求级 Session 传入线程池。
    """
    with SessionLocal() as db:
        return db.query(User).filter(User.username == username).first()


def _load_user_by_id(user_id: str) -> Optional["User"]:
    """
    在独立会话中按用户 ID 加载用户。
    """
    with SessionLocal() as db:
        return db.query(User).filter(User.id == user_id).first()


def _normalize_request_token(token: Optional[str]) -> Optional[str]:
    """
    规范化请求中的访问令牌，拒绝超长值和包含空白字符的异常输入。
    """
    if not isinstance(token, str):
        return None

    normalized_token = token.strip()
    if not normalized_token:
        return None
    if len(normalized_token) > _MAX_REQUEST_TOKEN_LENGTH:
        return None
    if any(char.isspace() for char in normalized_token):
        return None
    # 验证 token 字符集，防止注入特殊字符
    if not _TOKEN_CHARSET_RE.match(normalized_token):
        return None

    return normalized_token


def _get_owner_from_settings() -> Optional[User]:
    """
    尝试从缓存或数据库加载 owner 用户（同步路径，用于 API Key 认证）。
    """
    try:
        from core.owner import get_owner_id_sync
        with SessionLocal() as db:
            owner_id = get_owner_id_sync(db)
            return db.query(User).filter(User.id == owner_id).first()
    except ImportError:
        logger.warning("core.owner 模块不可用，API Key 认证降级")
        return None
    except Exception as exc:
        # API Key 认证关键路径：异常被吞掉会导致认证降级且无日志可追溯
        logger.bind(event="owner_resolution_failed", module="auth").warning(
            "加载 owner 用户失败，API Key 认证降级", exc_info=exc
        )
        return None


async def _resolve_jwt_user(token: str, db: Session) -> Optional[User]:
    """
    解析 JWT token 并返回对应用户。
    """
    payload = decode_access_token(token)
    if payload is None:
        return None

    jti = payload.get("jti")
    if jti and is_token_blacklisted(str(jti), db):
        return None

    username = payload.get("sub")
    if not isinstance(username, str):
        return None

    # 在独立会话中查询用户，避免把请求级 Session 传入线程池
    user = await asyncio.to_thread(_load_user_by_username, username)
    if user is None:
        return None
    # 禁用状态的用户视为无效凭证
    if user.role == "disabled":
        return None

    return user


async def _resolve_password_bearer_user(
    raw_password: str,
    db: Session,
) -> Optional[User]:
    """
    尝试将 Bearer 原始 token 作为 owner 密码进行验证。

    验证流程（spec: support-password-as-bearer）：
    1. 获取 owner 用户；owner 不存在（未初始化）时返回 None，跳过密码验证
    2. 先查密码验证缓存，命中直接返回 owner（避免 bcrypt 计算）
    3. 缓存未命中：通过 asyncio.to_thread 调用 verify_password 避免阻塞事件循环
    4. 验证通过：写入缓存（TTL 5 分钟）并返回 owner
    5. 验证失败：不写入缓存，返回 None（继续走 Cookie 路径）

    Args:
        raw_password: 原始 Bearer token（仅做 strip 处理，不走字符集校验，
            因为密码可能包含 !@#$% 等 _TOKEN_CHARSET_RE 之外的字符）
        db: 请求级数据库会话

    Returns:
        验证通过返回 owner User；否则返回 None
    """
    if not raw_password:
        return None

    # 长度安全检查：与 _normalize_request_token 保持一致的上限，避免超长密码攻击
    if len(raw_password) > _MAX_REQUEST_TOKEN_LENGTH:
        return None

    # 获取 owner 用户；未初始化时 get_owner_user 抛 RuntimeError，需捕获并跳过
    try:
        from core.owner import get_owner_user
        owner = await get_owner_user(db)
    except RuntimeError:
        # owner 未初始化，跳过密码验证路径
        return None
    except Exception as exc:
        # 加载 owner 出现未预期异常：记录日志并降级，不阻断认证流程
        logger.bind(
            event="owner_resolution_failed",
            module="auth",
        ).warning(
            "密码验证路径加载 owner 失败，跳过密码验证",
            exc_info=exc,
        )
        return None

    if owner is None:
        return None

    # 禁用状态的 owner 不允许通过密码登录
    if owner.role == "disabled":
        return None

    # 先查缓存，命中直接返回 owner
    cached_user_id = password_verification_cache.get(raw_password)
    if cached_user_id is not None and cached_user_id == owner.id:
        return owner

    # 缓存未命中：在线程池中执行 bcrypt 验证，避免阻塞事件循环
    try:
        is_valid = await asyncio.to_thread(
            verify_password, raw_password, owner.password_hash
        )
    except Exception as exc:
        logger.bind(
            event="password_verify_failed",
            module="auth",
        ).warning(
            "密码验证执行异常，按不匹配处理",
            exc_info=exc,
        )
        return None

    if not is_valid:
        # 验证失败不写入缓存，避免错误结果被复用
        return None

    # 验证通过：写入缓存（TTL 5 分钟）并返回 owner
    password_verification_cache.set(raw_password, owner.id)
    return owner


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
) -> User:
    """
    统一认证依赖注入：API Key → JWT Bearer → 密码验证 → HttpOnly Cookie。

    API Key 认证通过后直接返回 owner 用户，跳过 JWT 解析和黑名单检查。
    JWT 路径保持原有行为以兼容历史前端。
    密码验证路径（新增）允许用户用 /setup 时设置的密码作为 Bearer 登录，
    验证结果会缓存 5 分钟以规避 bcrypt 计算开销。
    Cookie 路径作为最后的降级方式。

    返回: 认证通过的用户 ORM 对象。
    认证失败: 抛出 401 HTTPException。
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    api_key = settings.OPENAWA_API_KEY.get_secret_value()
    has_api_key_auth = False

    if credentials:
        token = _normalize_request_token(credentials.credentials)
        # 密码验证路径使用原始 token（仅 strip），因为密码可能包含 !@#$% 等
        # _TOKEN_CHARSET_RE 之外的字符；当 _normalize_request_token 因字符集
        # 拒绝时，raw_bearer_token 仍可作为密码尝试
        raw_bearer_token = (
            credentials.credentials.strip()
            if isinstance(credentials.credentials, str)
            else ""
        )

        # 路径 1: API Key 认证
        if api_key and token and _secrets.compare_digest(token, api_key):
            has_api_key_auth = True
            # 优先使用 core.owner.get_owner_user 的缓存（带双重检查锁），
            # 避免 _get_owner_from_settings 每次新建 SessionLocal + 查 DB 的固有开销
            try:
                from core.owner import get_owner_user
                owner = await get_owner_user(db)
                if owner is not None:
                    return owner
            except Exception as exc:
                logger.bind(event="owner_resolution_failed", module="auth").warning(
                    "加载 owner 用户失败（缓存路径），回退到 _get_owner_from_settings",
                    exc_info=exc,
                )
            owner = _get_owner_from_settings()
            if owner is not None:
                return owner

        # 路径 2: JWT Bearer 认证（API Key 不匹配时降级）
        if not has_api_key_auth and token:
            user = await _resolve_jwt_user(token, db)
            if user is not None:
                return user

        # 路径 3: 密码验证（API Key 与 JWT 均未命中时尝试）
        # 使用 raw_bearer_token 而非 normalized token，因为密码可能包含特殊字符
        if not has_api_key_auth and raw_bearer_token:
            user = await _resolve_password_bearer_user(raw_bearer_token, db)
            if user is not None:
                return user

    # 路径 4: Cookie 认证（兼容旧前端）
    cookie_token = request.cookies.get(ACCESS_TOKEN_COOKIE_NAME, "")
    cookie_token_normalized = _normalize_request_token(cookie_token)
    if cookie_token_normalized:
        user = await _resolve_jwt_user(cookie_token_normalized, db)
        if user is not None:
            return user

    raise credentials_exception


async def get_optional_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
) -> Optional[User]:
    """
    尝试获取当前登录用户，未认证时返回 None 而非抛出异常。
    适用于允许匿名访问但可选附加用户信息的接口。

    认证顺序与 get_current_user 一致：API Key → JWT → 密码验证 → Cookie。
    """
    api_key = settings.OPENAWA_API_KEY.get_secret_value()

    if credentials:
        token = _normalize_request_token(credentials.credentials)
        # 密码验证路径使用原始 token（仅 strip），允许包含 _TOKEN_CHARSET_RE 之外的字符
        raw_bearer_token = (
            credentials.credentials.strip()
            if isinstance(credentials.credentials, str)
            else ""
        )

        # API Key 路径
        if api_key and token and _secrets.compare_digest(token, api_key):
            owner = _get_owner_from_settings()
            if owner is not None:
                return owner

        # JWT 路径
        if token:
            user = await _resolve_jwt_user(token, db)
            if user is not None:
                return user

        # 密码验证路径（与 get_current_user 保持一致）
        if raw_bearer_token:
            user = await _resolve_password_bearer_user(raw_bearer_token, db)
            if user is not None:
                return user

    # Cookie 路径
    cookie_token = request.cookies.get(ACCESS_TOKEN_COOKIE_NAME, "")
    cookie_token_normalized = _normalize_request_token(cookie_token)
    if cookie_token_normalized:
        user = await _resolve_jwt_user(cookie_token_normalized, db)
        if user is not None:
            return user

    return None


async def get_current_admin_user(
    current_user: User = Depends(get_current_user)
) -> User:
    """
    获取当前管理员用户。
    单用户模式下，owner 用户即管理员，此依赖检查仅做安全兜底。
    """
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required"
        )
    return current_user
