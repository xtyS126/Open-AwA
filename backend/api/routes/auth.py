"""
后端接口路由模块，负责接收请求、校验输入并协调业务层返回统一响应。
这些路由函数通常是前端或外部调用与后端内部能力之间的第一层行为边界。
"""

from datetime import timedelta
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from loguru import logger
from sqlalchemy.orm import Session

from api.dependencies import get_current_user
from api.schemas import Token, UserResponse
from config.security import (
    ACCESS_TOKEN_COOKIE_NAME,
    add_to_blacklist,
    clear_access_token_cookie,
    create_access_token,
    decode_access_token,
    get_password_hash,
    set_access_token_cookie,
    verify_password,
)
from config.settings import settings
from db.models import LoginDevice, User as UserModel, get_db
from pydantic import BaseModel, Field, SecretStr
from security.rate_limit_store import get_rate_limit_store
from security.csrf_manager import generate_csrf_token_pair


router = APIRouter(prefix="/auth", tags=["Authentication"])


def _build_login_rate_limit_key(username: str, client_ip: str) -> str:
    """
    为登录限流生成稳定键，避免单用户或单来源地址被暴力尝试。
    """
    return f"{client_ip}|{str(username or '').strip().lower()}"


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
) -> Dict[str, Any]:
    client_ip = request.client.host if request.client else "unknown"
    rate_limit_key = _build_login_rate_limit_key(form_data.username, client_ip)
    rate_limit_store = get_rate_limit_store()
    retry_after = rate_limit_store.get_retry_after_seconds(rate_limit_key)
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
        rate_limit_store.record_failed_attempt(rate_limit_key)
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

    # 禁用状态的用户不允许登录
    if user.role == "disabled":
        rate_limit_store.record_failed_attempt(rate_limit_key)
        logger.bind(
            event="auth_login_disabled",
            module="auth",
            action="login",
            status="failure",
            client_ip=client_ip,
        ).warning("disabled user attempted login")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is disabled. Please contact administrator.",
        )

    rate_limit_store.clear_attempts(rate_limit_key)

    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username, "uid": user.id}, expires_delta=access_token_expires
    )
    set_access_token_cookie(response, access_token)

    # 解析 token 的 jti 并记录登录设备
    payload = decode_access_token(access_token)
    jti = payload.get("jti") if payload else None
    device_type = _parse_device_type(request.headers.get("user-agent", ""))
    login_device = LoginDevice(
        user_id=user.id,
        device_type=device_type,
        ip_address=client_ip,
        user_agent=request.headers.get("user-agent", "")[:500],
        is_online=True,
        jti=str(jti) if jti else None,
    )
    db.add(login_device)
    db.commit()

    logger.bind(
        event="auth_login_success",
        module="auth",
        action="login",
        status="success",
        user_id=user.id,
    ).info("login succeeded")

    # 登录响应同时返回原始 token，并写入配对的签名 Cookie。
    csrf_token, _ = generate_csrf_token_pair(response)

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "csrf_token": csrf_token,
    }


@router.post(
    "/logout",
    summary="用户登出",
    description="清理当前会话的访问令牌 Cookie。"
)
async def logout(
    request: Request,
    response: Response,
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    清理当前访问令牌 Cookie，将当前 token 加入数据库黑名单防止重放，
    并返回统一登出结果。
    """
    raw_token = _resolve_token_for_blacklist(request)
    jti_value: Optional[str] = None
    if raw_token:
        payload = decode_access_token(raw_token)
        if payload:
            jti_value = payload.get("jti")
            if jti_value:
                add_to_blacklist(str(jti_value), db)
                # 将对应设备标记为离线
                device = db.query(LoginDevice).filter(LoginDevice.jti == str(jti_value)).first()
                if device:
                    from datetime import datetime as dt_module, timezone as tz
                    device.is_online = False
                    device.last_active_at = dt_module.now(tz.utc)
                    db.commit()
    clear_access_token_cookie(response)
    logger.bind(
        event="auth_logout_success",
        module="auth",
        action="logout",
        status="success",
        user_id=current_user.id,
    ).info("user logged out")
    return {"message": "logout success"}


def _resolve_token_for_blacklist(request: Request) -> Optional[str]:
    """从请求中提取原始 token 字符串用于黑名单记录。"""
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()
    return request.cookies.get(ACCESS_TOKEN_COOKIE_NAME)


def _parse_device_type(user_agent: str) -> str:
    """根据 User-Agent 字符串判断设备类型。"""
    ua = user_agent.lower()
    if "mobile" in ua or "android" in ua or "iphone" in ua:
        return "mobile"
    if "tablet" in ua or "ipad" in ua:
        return "tablet"
    if "bot" in ua or "crawler" in ua or "spider" in ua:
        return "bot"
    return "desktop"


class PasswordChangeRequest(BaseModel):
    """修改密码请求体，包含旧密码和新密码的强度校验。"""
    old_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8, max_length=128)
    confirm_password: str = Field(..., min_length=8, max_length=128)


@router.get(
    "/me",
    response_model=UserResponse,
    summary="获取当前用户信息",
    description="返回当前访问令牌对应的用户资料。"
)
async def get_me(current_user: UserModel = Depends(get_current_user)) -> Dict[str, Any]:
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


@router.put(
    "/me/password",
    summary="修改密码",
    description="验证旧密码后设置新密码，新密码需满足强度要求（至少8位，含大小写字母和数字）。"
)
async def change_password(
    request: Request,
    request_body: PasswordChangeRequest,
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    修改当前用户的登录密码。
    要求提供旧密码进行验证，新密码需满足强度规则。

    安全防护：复用 RateLimitStore 限制每个用户密码修改频率，
    防止已登录会话被滥用进行旧密码暴力尝试。
    """
    # 密码修改限流：基于 user_id 隔离，避免已登录会话暴力尝试旧密码
    rate_limit_store = get_rate_limit_store()
    pwd_rate_key = f"pwd_change|{current_user.id}"
    retry_after = rate_limit_store.get_retry_after_seconds(pwd_rate_key)
    if retry_after > 0:
        raise HTTPException(
            status_code=429,
            detail=f"密码修改尝试过于频繁，请 {retry_after} 秒后重试"
        )

    # 验证旧密码
    if not verify_password(request_body.old_password, current_user.password_hash):
        # 记录失败尝试，触发限流
        rate_limit_store.record_failed_attempt(pwd_rate_key)
        raise HTTPException(status_code=400, detail="旧密码不正确")

    # 旧密码验证通过后清理限流计数
    rate_limit_store.clear_attempts(pwd_rate_key)

    # 确认密码一致性
    if request_body.new_password != request_body.confirm_password:
        raise HTTPException(status_code=400, detail="两次输入的新密码不一致")

    # 密码强度校验：至少8位，含大写、小写、数字
    new_pwd = request_body.new_password
    if len(new_pwd) < 8:
        raise HTTPException(status_code=400, detail="新密码长度至少为 8 位")
    if not any(c.isupper() for c in new_pwd):
        raise HTTPException(status_code=400, detail="新密码需要包含至少一个大写字母")
    if not any(c.islower() for c in new_pwd):
        raise HTTPException(status_code=400, detail="新密码需要包含至少一个小写字母")
    if not any(c.isdigit() for c in new_pwd):
        raise HTTPException(status_code=400, detail="新密码需要包含至少一个数字")

    # 更新密码
    current_user.password_hash = get_password_hash(new_pwd)
    db.commit()

    # 清空密码验证缓存：旧密码作为 Bearer 凭证的缓存结果必须立即失效，
    # 防止修改密码后旧密码在缓存 TTL 内仍可登录
    from core.password_cache import password_verification_cache
    password_verification_cache.clear()

    logger.bind(
        event="auth_password_changed",
        module="auth",
        action="change_password",
        status="success",
        user_id=current_user.id,
    ).info("password changed successfully")

    return {"message": "密码修改成功"}


class ApiKeyRotateRequest(BaseModel):
    """API Key 轮转请求体。"""
    confirm: bool = Field(default=False, description="确认轮转，设为 true 才执行")


class ApiKeyRotateResponse(BaseModel):
    """API Key 轮转响应。"""
    message: str
    new_api_key: str = Field(default="", description="新生成的 API Key（仅当 confirm=true 时返回）")


@router.post(
    "/rotate-api-key",
    response_model=ApiKeyRotateResponse,
    summary="轮转 API Key",
    description="生成新的 API Key 使旧 Key 立即失效。需要当前有效的 API Key 验证。"
)
async def rotate_api_key(
    request: Request,
    request_body: ApiKeyRotateRequest,
    current_user: UserModel = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    轮转全局 API Key：生成新 Key → 写入 .env.local → 更新 settings → 返回新 Key。
    旧 Key 立即失效，调用方需保存新 Key 并更新所有客户端配置。
    此操作需当前有效的 API Key 认证。
    """
    import secrets as _secmod
    from pathlib import Path as _FsPath

    if not request_body.confirm:
        return {"message": "请设置 confirm=true 以确认轮转 API Key", "new_api_key": ""}

    # 生成新 Key
    new_key = "sk-" + _secmod.token_urlsafe(32)
    # 先持久化新密钥；持久化失败时不得改变运行时密钥，避免重启后密钥回退。
    env_local_path = _FsPath(__file__).resolve().parents[2] / ".env.local"
    try:
        if env_local_path.exists():
            content = env_local_path.read_text(encoding="utf-8")
            # 替换现有的 OPENAWA_API_KEY 行
            import re as _re
            if _re.search(r'^OPENAWA_API_KEY=', content, _re.MULTILINE):
                content = _re.sub(
                    r'^OPENAWA_API_KEY=.*$',
                    f'OPENAWA_API_KEY={new_key}',
                    content,
                    flags=_re.MULTILINE,
                )
                env_local_path.write_text(content, encoding="utf-8")
            else:
                # 追加
                with open(env_local_path, "a", encoding="utf-8") as f:
                    f.write(f"\nOPENAWA_API_KEY={new_key}\n")
        else:
            env_local_path.write_text(f"OPENAWA_API_KEY={new_key}\n", encoding="utf-8")
    except OSError as exc:
        logger.bind(
            event="api_key_rotate_persist_failed",
            module="auth",
        ).error(f"无法持久化新 API Key 到 .env.local: {exc}")
        raise HTTPException(status_code=500, detail="无法持久化新 API Key，轮转已取消") from exc

    # 仅在文件已成功写入后更新运行时设置，保证运行时与重启后的配置一致。
    object.__setattr__(settings, "OPENAWA_API_KEY", SecretStr(new_key))

    logger.bind(
        event="api_key_rotated",
        module="auth",
        action="rotate_api_key",
        status="success",
        user_id=current_user.id,
    ).warning("访问密钥已轮转")

    # 清除 owner 缓存，下次查询时会重新加载
    # 失败时返回 500：旧 Key 在 TTL 内继续有效属于安全敏感状态，不得伪装成功
    try:
        from core.owner import invalidate_owner_cache
        invalidate_owner_cache()
    except Exception as exc:
        logger.bind(
            event="owner_cache_invalidation_failed",
            module="auth",
            action="rotate_api_key",
            error=str(exc),
        ).error(f"清除 owner 缓存失败，旧 Key 可能在 TTL 内继续有效: {exc}")
        raise HTTPException(
            status_code=500,
            detail="清除 owner 缓存失败，旧 Key 未立即失效，轮转失败请重试",
        ) from exc

    return {
        "message": "API Key 已轮转。请将新 Key 分发到所有客户端。旧 Key 立即失效。",
        "new_api_key": new_key,
    }
