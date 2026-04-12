"""
后端接口路由模块，负责接收请求、校验输入并协调业务层返回统一响应。
这些路由函数通常是前端或外部调用与后端内部能力之间的第一层行为边界。
"""

from collections import deque
from datetime import timedelta
import math
import threading
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from loguru import logger
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.dependencies import get_current_user
from api.schemas import Token, UserCreate, UserResponse
from config.security import (
    clear_access_token_cookie,
    create_access_token,
    get_password_hash,
    set_access_token_cookie,
    verify_password,
)
from config.settings import settings
from db.models import User as UserModel, get_db


router = APIRouter(prefix="/auth", tags=["Authentication"])

_LOGIN_ATTEMPT_WINDOW_SECONDS = 5 * 60
_LOGIN_MAX_ATTEMPTS = 5
_LOGIN_BLOCK_SECONDS = 15 * 60
_LOGIN_CLEANUP_INTERVAL_SECONDS = 60
_LOGIN_ATTEMPTS: dict[str, deque[float]] = {}
_LOGIN_BLOCKED_UNTIL: dict[str, float] = {}
_LOGIN_RATE_LIMIT_LOCK = threading.Lock()
_LOGIN_LAST_CLEANUP_AT = 0.0


def _build_login_rate_limit_key(username: str, client_ip: str) -> str:
    """
    为登录限流生成稳定键，避免单用户或单来源地址被暴力尝试。
    """
    return f"{client_ip}|{str(username or '').strip().lower()}"


def _get_retry_after_seconds(rate_limit_key: str) -> int:
    """
    检查当前登录键是否仍处于限流窗口。
    """
    now = time.monotonic()
    with _LOGIN_RATE_LIMIT_LOCK:
        _cleanup_expired_login_rate_limit_state(now)
        blocked_until = _LOGIN_BLOCKED_UNTIL.get(rate_limit_key, 0.0)
        if blocked_until > now:
            return _calculate_retry_after_seconds(blocked_until, now)

        attempts = _LOGIN_ATTEMPTS.setdefault(rate_limit_key, deque())
        _prune_login_attempts(attempts, now)

        if len(attempts) < _LOGIN_MAX_ATTEMPTS:
            if not attempts:
                _LOGIN_ATTEMPTS.pop(rate_limit_key, None)
            return 0

        attempts.clear()
        _LOGIN_ATTEMPTS.pop(rate_limit_key, None)
        blocked_until = now + _LOGIN_BLOCK_SECONDS
        _LOGIN_BLOCKED_UNTIL[rate_limit_key] = blocked_until
        return _calculate_retry_after_seconds(blocked_until, now)


def _record_failed_login(rate_limit_key: str) -> None:
    """
    记录一次失败登录尝试。
    """
    now = time.monotonic()
    with _LOGIN_RATE_LIMIT_LOCK:
        _cleanup_expired_login_rate_limit_state(now)
        attempts = _LOGIN_ATTEMPTS.setdefault(rate_limit_key, deque())
        _prune_login_attempts(attempts, now)
        attempts.append(now)


def _clear_failed_login(rate_limit_key: str) -> None:
    """
    登录成功后清理该来源的失败计数。
    """
    with _LOGIN_RATE_LIMIT_LOCK:
        _LOGIN_ATTEMPTS.pop(rate_limit_key, None)
        _LOGIN_BLOCKED_UNTIL.pop(rate_limit_key, None)


def _calculate_retry_after_seconds(blocked_until: float, now: float) -> int:
    """
    将单调时钟差值转换为 Retry-After 秒数，避免向下取整导致少报 1 秒。
    """
    return max(1, math.ceil(blocked_until - now))


def _prune_login_attempts(attempts: deque[float], now: float) -> None:
    """
    删除窗口外的失败记录，保证 deque 只保留有效时间范围内的数据。
    """
    while attempts and now - attempts[0] > _LOGIN_ATTEMPT_WINDOW_SECONDS:
        attempts.popleft()


def _cleanup_expired_login_rate_limit_state(now: float) -> None:
    """
    定期清理过期限流数据，避免全局字典在长期运行时无限增长。
    """
    global _LOGIN_LAST_CLEANUP_AT

    if now - _LOGIN_LAST_CLEANUP_AT < _LOGIN_CLEANUP_INTERVAL_SECONDS:
        return

    expired_blocked_keys = [
        key for key, blocked_until in _LOGIN_BLOCKED_UNTIL.items()
        if blocked_until <= now
    ]
    for key in expired_blocked_keys:
        _LOGIN_BLOCKED_UNTIL.pop(key, None)

    stale_attempt_keys: list[str] = []
    for key, attempts in list(_LOGIN_ATTEMPTS.items()):
        _prune_login_attempts(attempts, now)
        if not attempts and key not in _LOGIN_BLOCKED_UNTIL:
            stale_attempt_keys.append(key)

    for key in stale_attempt_keys:
        _LOGIN_ATTEMPTS.pop(key, None)

    _LOGIN_LAST_CLEANUP_AT = now


@router.post("/register", response_model=UserResponse)
async def register(user: UserCreate, db: Session = Depends(get_db)):
    """
    创建新的本地用户账户。
    接口会先校验用户名是否已存在，再对密码执行哈希处理并写入数据库，成功后返回新建用户的基础资料。
    """
    db_user = db.query(UserModel).filter(UserModel.username == user.username).first()
    if db_user:
        logger.bind(
            event="auth_register_conflict",
            module="auth",
            action="register",
            status="failure",
        ).warning("username already registered")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already registered"
        )

    new_user = UserModel(
        id=str(uuid.uuid4()),
        username=user.username,
        password_hash=get_password_hash(user.password),
        role="user"
    )
    db.add(new_user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        logger.bind(
            event="auth_register_conflict_race",
            module="auth",
            action="register",
            status="failure",
        ).warning("concurrent registration conflict for username")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username already registered"
        )
    db.refresh(new_user)

    logger.bind(
        event="auth_register_success",
        module="auth",
        action="register",
        status="success",
        user_id=new_user.id,
    ).info("user registered")

    return new_user


@router.post(
    "/login",
    response_model=Token,
    summary="用户登录",
    description="使用 OAuth2PasswordRequestForm 提交用户名和密码，成功后返回访问令牌。"
)
async def login(
    request: Request,
    response: Response,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    """
    处理login相关逻辑，并为调用方返回对应结果。
    阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
    """
    client_ip = request.client.host if request.client else "unknown"
    rate_limit_key = _build_login_rate_limit_key(form_data.username, client_ip)
    retry_after = _get_retry_after_seconds(rate_limit_key)
    if retry_after > 0:
        logger.bind(
            event="auth_login_rate_limited",
            module="auth",
            action="login",
            status="blocked",
            client_ip=client_ip,
        ).warning("login rate limited")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts, please try again later",
            headers={"Retry-After": str(retry_after)},
        )

    user = db.query(UserModel).filter(UserModel.username == form_data.username).first()
    if not user or not verify_password(form_data.password, user.password_hash):
        _record_failed_login(rate_limit_key)
        logger.bind(
            event="auth_login_failed",
            module="auth",
            action="login",
            status="failure",
            client_ip=client_ip,
        ).warning("login failed")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    _clear_failed_login(rate_limit_key)

    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )
    set_access_token_cookie(response, access_token)

    logger.bind(
        event="auth_login_success",
        module="auth",
        action="login",
        status="success",
        user_id=user.id,
    ).info("login succeeded")

    return {"access_token": access_token, "token_type": "bearer"}


@router.post(
    "/logout",
    summary="用户登出",
    description="清理当前会话的访问令牌 Cookie。"
)
async def logout(
    response: Response,
    current_user: UserModel = Depends(get_current_user),
):
    """
    清理当前访问令牌 Cookie，并返回统一登出结果。
    """
    clear_access_token_cookie(response)
    logger.bind(
        event="auth_logout_success",
        module="auth",
        action="logout",
        status="success",
        user_id=current_user.id,
    ).info("user logged out")
    return {"message": "logout success"}


@router.get(
    "/me",
    response_model=UserResponse,
    summary="获取当前用户信息",
    description="返回当前访问令牌对应的用户资料。"
)
async def get_me(current_user: UserModel = Depends(get_current_user)):
    """
    获取me相关数据或当前状态。
    调用方通常依赖该结果继续进行后续判断、渲染或业务编排。
    """
    logger.bind(
        event="auth_me",
        module="auth",
        action="me",
        status="success",
        user_id=current_user.id,
    ).info("fetched current user")
    return current_user
