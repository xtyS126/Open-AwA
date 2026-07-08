"""
认证路由 - 登录、注册、CSRF 令牌

与桌面版 backend/api/routes/auth.py 的差异：
- 移除登录限流（移动端单用户场景）
- 移除设备管理（移动端通过设备标识自动管理）
- 移除 OAuth2PasswordRequestForm，改用 JSON 请求体（更适合移动端）
"""

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPBearer
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import User, get_db
from ..security import (
    clear_access_token_cookie,
    create_access_token,
    decode_access_token,
    generate_csrf_token,
    hash_password,
    set_access_token_cookie,
    set_csrf_cookie,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["Authentication"])

# Bearer 令牌提取器（用于依赖注入）
_bearer_scheme = HTTPBearer(auto_error=False)


class LoginRequest(BaseModel):
    """登录请求"""

    username: str = Field(..., min_length=1, max_length=64, description="用户名")
    password: str = Field(..., min_length=1, max_length=256, description="密码")


class RegisterRequest(BaseModel):
    """注册请求"""

    username: str = Field(..., min_length=3, max_length=64, description="用户名")
    password: str = Field(..., min_length=6, max_length=256, description="密码")
    email: Optional[str] = Field(None, max_length=128, description="邮箱")


class UserResponse(BaseModel):
    """用户信息响应"""

    id: int
    username: str
    email: Optional[str]
    role: str
    is_active: bool
    created_at: datetime
    last_login_at: Optional[datetime]

    class Config:
        orm_mode = True


class TokenResponse(BaseModel):
    """令牌响应"""

    access_token: str
    token_type: str = "bearer"
    user: UserResponse


def get_current_user(
    db: Session = Depends(get_db),
    token_data=Depends(_bearer_scheme),
) -> User:
    """
    FastAPI 依赖：从 Bearer 令牌解析当前用户

    移动端支持两种 Bearer 令牌：
    1. JWT 令牌（通过 /api/auth/login 获取）
    2. API Key（前端登录页输入，等值于 settings.api_key）

    无有效令牌时抛出 401。
    """
    if token_data is None or not token_data.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未提供认证令牌",
            headers={"WWW-Authenticate": "Bearer"},
        )

    settings = get_settings()

    # 路径 1：API Key 直通（移动端单用户场景）
    # 前端 LoginPage 输入的 API Key 通过 Authorization: Bearer <apiKey> 传递
    if token_data.credentials == settings.api_key:
        user = db.query(User).filter(User.role == "admin").first()
        if user is None or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="管理员账号不可用",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return user

    # 路径 2：JWT 令牌解析
    try:
        payload = decode_access_token(token_data.credentials)
        user_id = payload.get("sub")
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="令牌无效",
                headers={"WWW-Authenticate": "Bearer"},
            )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"令牌解析失败: {e}",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = db.query(User).filter(User.id == int(user_id)).first()
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在或已禁用",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


@router.get("/csrf-token")
async def get_csrf_token(response: Response) -> Dict[str, Any]:
    """
    获取 CSRF 令牌

    令牌同时通过 Cookie（httpOnly=False，前端可读）和响应体返回。
    """
    token = generate_csrf_token()
    set_csrf_cookie(response, token)
    return {"csrf_token": token}


@router.post("/login", response_model=TokenResponse)
async def login(
    request: Request,
    response: Response,
    payload: LoginRequest,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    用户登录

    成功后返回访问令牌并设置 httpOnly Cookie。
    """
    user = db.query(User).filter(User.username == payload.username).first()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="账号已被禁用",
        )

    # 更新最后登录时间
    user.last_login_at = datetime.now(timezone.utc)
    db.commit()

    # 生成 JWT
    access_token = create_access_token(
        data={"sub": str(user.id), "username": user.username, "role": user.role}
    )
    set_access_token_cookie(response, access_token)

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": user,
    }


@router.post("/register", response_model=TokenResponse)
async def register(
    response: Response,
    payload: RegisterRequest,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    用户注册

    移动端默认允许注册，首个用户自动成为管理员。
    """
    # 检查用户名是否已存在
    existing = db.query(User).filter(User.username == payload.username).first()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="用户名已存在",
        )

    # 首个用户自动成为管理员
    user_count = db.query(User).count()
    role = "admin" if user_count == 0 else "user"

    user = User(
        username=payload.username,
        password_hash=hash_password(payload.password),
        email=payload.email,
        role=role,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    access_token = create_access_token(
        data={"sub": str(user.id), "username": user.username, "role": user.role}
    )
    set_access_token_cookie(response, access_token)

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": user,
    }


@router.post("/logout")
async def logout(response: Response) -> Dict[str, Any]:
    """用户登出（清除 Cookie）"""
    clear_access_token_cookie(response)
    return {"status": "ok", "message": "已登出"}


@router.get("/me", response_model=UserResponse)
async def get_me(
    current_user: User = Depends(get_current_user),
) -> User:
    """获取当前登录用户信息"""
    return current_user
