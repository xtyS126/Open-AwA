"""
后端接口依赖注入模块，负责认证、数据库会话与通用依赖能力的装配。
当路由需要复用身份验证或上下文能力时，通常会先经过这一层。
"""

import asyncio
import re
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from config.security import ACCESS_TOKEN_COOKIE_NAME, decode_access_token
from db.models import User, get_db


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)
_MAX_REQUEST_TOKEN_LENGTH = 2048
# token 合法字符集：字母、数字、点、横杠、下划线、等号
_TOKEN_CHARSET_RE = re.compile(r'^[A-Za-z0-9._\-=]+$')


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


def _resolve_request_token(request: Request, bearer_token: Optional[str]) -> Optional[str]:
    """
    优先读取 Bearer Token，缺失时回退到 HttpOnly Cookie。
    """
    normalized_bearer_token = _normalize_request_token(bearer_token)
    if normalized_bearer_token:
        return normalized_bearer_token

    cookie_token = request.cookies.get(ACCESS_TOKEN_COOKIE_NAME, "")
    return _normalize_request_token(cookie_token)


async def get_current_user(
    request: Request,
    token: Optional[str] = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
) -> User:
    """
    获取current、user相关数据或当前状态。
    调用方通常依赖该结果继续进行后续判断、渲染或业务编排。
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    resolved_token = _resolve_request_token(request, token)
    if not resolved_token:
        raise credentials_exception

    payload = decode_access_token(resolved_token)
    if payload is None:
        raise credentials_exception
    
    username = payload.get("sub")
    if not isinstance(username, str):
        raise credentials_exception
    
    # 使用 asyncio.to_thread 避免同步 ORM 查询阻塞事件循环
    user = await asyncio.to_thread(
        lambda: db.query(User).filter(User.username == username).first()
    )
    if user is None:
        raise credentials_exception
    # 禁用状态的用户视为无效凭证
    if user.role == "disabled":
        raise credentials_exception
    
    return user


async def get_optional_current_user(
    request: Request,
    token: Optional[str] = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
) -> Optional[User]:
    """
    尝试获取当前登录用户，未认证时返回 None 而非抛出异常。
    适用于允许匿名访问但可选附加用户信息的接口。
    """
    resolved_token = _resolve_request_token(request, token)
    if not resolved_token:
        return None

    payload = decode_access_token(resolved_token)
    if payload is None:
        return None

    username = payload.get("sub")
    if not isinstance(username, str):
        return None

    # 使用 asyncio.to_thread 避免同步 ORM 查询阻塞事件循环
    return await asyncio.to_thread(
        lambda: db.query(User).filter(User.username == username).first()
    )


async def get_current_admin_user(
    current_user: User = Depends(get_current_user)
) -> User:
    """
    获取current、admin、user相关数据或当前状态。
    调用方通常依赖该结果继续进行后续判断、渲染或业务编排。
    """
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required"
        )
    return current_user
