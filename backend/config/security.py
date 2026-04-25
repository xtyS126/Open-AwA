"""
配置管理模块，负责系统运行参数、安全策略或日志行为的统一定义。
配置项通常会在多个子模块中生效，因此理解其字段含义非常重要。
"""

import base64
import hashlib
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken
from fastapi import Response
from jose import JWTError, jwt
from loguru import logger
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from db.models import TokenBlacklist
from .settings import settings


ACCESS_TOKEN_COOKIE_NAME = "access_token"


def add_to_blacklist(jti: str, db: Session) -> None:
    """将指定 jti 加入数据库黑名单，同时清理已过期的黑名单记录。"""
    if not jti:
        return
    now = datetime.now(timezone.utc)
    db.query(TokenBlacklist).filter(TokenBlacklist.expires_at < now).delete()
    expires_at = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    db.add(TokenBlacklist(jti=jti, expires_at=expires_at))
    db.commit()
    logger.bind(
        event="token_blacklist_add",
        module="security",
    ).debug(f"token {jti[:8]}... added to blacklist")


def is_token_blacklisted(jti: str, db: Session) -> bool:
    """检查指定 jti 是否在数据库黑名单中（自动忽略已过期记录）。"""
    return db.query(TokenBlacklist).filter(
        TokenBlacklist.jti == jti,
        TokenBlacklist.expires_at > datetime.now(timezone.utc),
    ).first() is not None

pwd_context = CryptContext(
    schemes=["pbkdf2_sha256", "bcrypt"],
    deprecated="auto",
    bcrypt__rounds=12,
    pbkdf2_sha256__default_rounds=600_000,
)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    处理verify、password相关逻辑，并为调用方返回对应结果。
    阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
    """
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """
    获取password、hash相关数据或当前状态。
    调用方通常依赖该结果继续进行后续判断、渲染或业务编排。
    """
    return pwd_context.hash(password)


def _build_secret_cipher() -> Fernet:
    """
    基于 SECRET_KEY 派生稳定的对称加密密钥，用于敏感令牌的加密存储。
    """
    key_material = hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(key_material))


def encrypt_secret_value(value: str) -> str:
    """
    对敏感字符串进行加密，空值直接返回空字符串。
    已加密值会原样返回，避免重复加密。
    """
    normalized = str(value or "").strip()
    if not normalized:
        return ""
    if normalized.startswith("enc:"):
        return normalized
    cipher = _build_secret_cipher()
    return f"enc:{cipher.encrypt(normalized.encode('utf-8')).decode('utf-8')}"


def decrypt_secret_value(value: str) -> str:
    """
    解密敏感字符串，兼容历史明文数据。
    解密失败时返回空字符串并记录告警，避免继续传播损坏的令牌。
    """
    normalized = str(value or "").strip()
    if not normalized:
        return ""
    if not normalized.startswith("enc:"):
        return normalized

    encrypted_payload = normalized[4:]
    if not encrypted_payload:
        return ""

    try:
        cipher = _build_secret_cipher()
        return cipher.decrypt(encrypted_payload.encode("utf-8")).decode("utf-8")
    except (InvalidToken, ValueError) as exc:
        logger.warning(f"敏感字段解密失败，已按空值处理: {type(exc).__name__}")
        return ""


def set_access_token_cookie(response: Response, access_token: str) -> None:
    """
    将访问令牌写入 HttpOnly Cookie，避免前端脚本直接读取。
    """
    secure_cookie = os.getenv("ENVIRONMENT", "development") == "production"
    max_age = int(settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60)
    response.set_cookie(
        key=ACCESS_TOKEN_COOKIE_NAME,
        value=access_token,
        httponly=True,
        secure=secure_cookie,
        samesite="lax",
        max_age=max_age,
        expires=max_age,
        path="/",
    )


def clear_access_token_cookie(response: Response) -> None:
    """
    清理访问令牌 Cookie。
    """
    response.delete_cookie(
        key=ACCESS_TOKEN_COOKIE_NAME,
        path="/",
        samesite="lax",
    )


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    创建access、token相关对象、记录或执行结果。
    实现过程中往往会涉及初始化、组装、持久化或返回统一结构。
    """
    import uuid
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire, "jti": str(uuid.uuid4())})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt


def decode_access_token(token: str) -> Optional[dict]:
    """
    处理decode、access、token相关逻辑，并为调用方返回对应结果。
    阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
    """
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        expires_at = payload.get("exp")
        if expires_at is None:
            return None
        expire_time = datetime.fromtimestamp(float(expires_at), tz=timezone.utc)
        if expire_time <= datetime.now(timezone.utc):
            return None
        return payload
    except (JWTError, TypeError, ValueError, OverflowError):
        return None
