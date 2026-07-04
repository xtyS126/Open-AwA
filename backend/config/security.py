"""
配置管理模块，负责系统运行参数、安全策略或日志行为的统一定义。
配置项通常会在多个子模块中生效，因此理解其字段含义非常重要。
"""

import base64
import hashlib
import hmac
import json
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
from cryptography.fernet import Fernet, InvalidToken
from fastapi import Response
import jwt
from jwt import PyJWTError
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


def _is_legacy_bcrypt_hash(hashed_password: str) -> bool:
    """识别历史 bcrypt 哈希，避免 passlib 在部分 bcrypt 版本组合下初始化失败。"""
    return hashed_password.startswith(("$2a$", "$2b$", "$2y$"))


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    处理verify、password相关逻辑，并为调用方返回对应结果。
    阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
    """
    normalized_hash = str(hashed_password or "")
    if not normalized_hash:
        return False

    # 兼容历史 bcrypt 哈希，规避 passlib + bcrypt 新版本组合下的 72 字节探测异常。
    if _is_legacy_bcrypt_hash(normalized_hash):
        try:
            return bcrypt.checkpw(
                str(plain_password or "").encode("utf-8"),
                normalized_hash.encode("utf-8"),
            )
        except ValueError as exc:
            logger.warning(f"bcrypt 密码校验失败，已按不匹配处理: {exc}")
            return False

    try:
        return pwd_context.verify(plain_password, normalized_hash)
    except ValueError as exc:
        logger.warning(f"密码校验失败，已按不匹配处理: {exc}")
        return False


def get_password_hash(password: str) -> str:
    """
    获取password、hash相关数据或当前状态。
    调用方通常依赖该结果继续进行后续判断、渲染或业务编排。
    """
    return pwd_context.hash(password)


def _build_secret_cipher() -> Fernet:
    """直接使用 ENCRYPTION_KEY 构造 Fernet，不再 SHA256 派生。"""
    return Fernet(settings.ENCRYPTION_KEY.encode("utf-8"))


def encrypt_secret_value(value: str) -> str:
    """
    对敏感字符串进行加密，空值直接返回空字符串。
    已加密值（enc: 或 enc2: 前缀）原样返回，避免重复加密。
    新密文统一使用 enc2: 前缀标识新算法 + 新密钥。
    """
    normalized = str(value or "").strip()
    if not normalized:
        return ""
    # 已加密值原样返回，避免重复加密（兼容旧 enc: 与新 enc2:）
    if normalized.startswith("enc:") or normalized.startswith("enc2:"):
        return normalized
    cipher = _build_secret_cipher()
    return f"enc2:{cipher.encrypt(normalized.encode('utf-8')).decode('utf-8')}"


def decrypt_secret_value(value: str) -> str:
    """
    解密敏感字符串，兼容历史明文数据。
    - 空/无前缀明文：原样返回
    - enc: 旧算法密文：直接返回空字符串并记录 warning（旧密钥已废弃，需重新录入）
    - enc2: 新算法密文：用新 Fernet 解密，失败返回空 + warning
    """
    normalized = str(value or "").strip()
    if not normalized:
        return ""

    # 旧算法密文：密钥已废弃，不尝试解密，直接返回空
    if normalized.startswith("enc:"):
        logger.warning("检测到旧算法密文(enc:)，已标记失效，需重新录入")
        return ""

    # 新算法密文：用 ENCRYPTION_KEY 构造的 Fernet 解密
    if normalized.startswith("enc2:"):
        encrypted_payload = normalized[5:]
        if not encrypted_payload:
            return ""
        try:
            cipher = _build_secret_cipher()
            return cipher.decrypt(encrypted_payload.encode("utf-8")).decode("utf-8")
        except (InvalidToken, ValueError) as exc:
            logger.warning(f"敏感字段解密失败，已按空值处理: {type(exc).__name__}")
            return ""

    # 无前缀明文：原样返回（兼容历史明文存储）
    return normalized


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
    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt


def decode_access_token(token: str) -> Optional[dict]:
    """
    处理decode、access、token相关逻辑，并为调用方返回对应结果。
    阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
    """
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.ALGORITHM])
        expires_at = payload.get("exp")
        if expires_at is None:
            return None
        expire_time = datetime.fromtimestamp(float(expires_at), tz=timezone.utc)
        if expire_time <= datetime.now(timezone.utc):
            return None
        return payload
    except (PyJWTError, TypeError, ValueError, OverflowError):
        return None


# ---------------------------------------------------------------------------
# Per-session CSRF token — user-bound signed token（参考 Django CSRF 的签名 token 模式）
# 格式: base64url(payload).base64url(HMAC-SHA256(payload, server_secret))
# payload JSON: {"sub": <user_id>, "jti": <token_jti>, "iat": <issued_at>}
# 来源参考: https://github.com/django/django/blob/main/django/middleware/csrf.py
# ---------------------------------------------------------------------------

# CSRF token 有效期（秒），默认与 access token 相同
_CSRF_TOKEN_MAX_AGE_SECONDS = int(settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60)


def _derive_csrf_signing_key() -> bytes:
    """
    从 CSRF_SECRET_KEY 使用 HKDF (HMAC-SHA256) 派生 CSRF 签名密钥。
    使用 HKDF 而非裸 SHA-256 提供更强的密钥派生保证（RFC 5869）。
    context_seed 作为 info 参数确保与 JWT 等其他密钥独立。
    """
    context_seed = b"open-awa-csrf-v1"
    # 使用 hashlib 内置的 HKDF（Python 3.12+ 可用，回退到手动实现）
    try:
        key_material = hashlib.hkdf(
            ikm=settings.CSRF_SECRET_KEY.encode("utf-8"),
            length=32,
            salt=context_seed,
            info=b"csrf-signing",
            hashfunc=hashlib.sha256,
        )
    except AttributeError:
        # Python < 3.12 回退：使用 SHA-256 作为保守的密钥派生
        key_material = hashlib.sha256(
            settings.CSRF_SECRET_KEY.encode("utf-8") + context_seed
        ).digest()
    return key_material


def generate_csrf_token(user_id, jti: Optional[str] = None) -> str:
    """
    为用户生成 per-session 的 CSRF token。

    参数:
        user_id: 用户数据库 ID（支持 str 或 int，与 User.id 类型一致）
        jti: 当前会话的 JWT jti（可选，用于绑定到特定登录会话）

    返回:
        base64url 编码的签名 CSRF token 字符串
    """
    import uuid

    payload_data = {
        "sub": user_id,
        "jti": jti or str(uuid.uuid4()),
        "iat": int(time.time()),
    }
    payload_bytes = json.dumps(payload_data, separators=(",", ":")).encode("utf-8")
    payload_b64 = base64.urlsafe_b64encode(payload_bytes).rstrip(b"=").decode("ascii")

    signing_key = _derive_csrf_signing_key()
    signature = hmac.new(signing_key, payload_b64.encode("ascii"), hashlib.sha256).digest()
    signature_b64 = base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii")

    return f"{payload_b64}.{signature_b64}"


def verify_csrf_token(token: str) -> Optional[dict]:
    """
    验证 CSRF token 的签名和有效期，返回解码后的 payload 或 None。

    参数:
        token: 客户端发送的 CSRF token 字符串

    返回:
        验证成功返回 payload dict（含 sub/jti/iat），失败返回 None
    """
    if not token or not isinstance(token, str):
        return None

    token = token.strip()
    if not token:
        return None

    parts = token.split(".")
    if len(parts) != 2:
        return None

    payload_b64, signature_b64 = parts

    # 验证签名
    signing_key = _derive_csrf_signing_key()
    expected_signature = hmac.new(
        signing_key, payload_b64.encode("ascii"), hashlib.sha256
    ).digest()
    expected_b64 = base64.urlsafe_b64encode(expected_signature).rstrip(b"=").decode("ascii")

    if not hmac.compare_digest(signature_b64, expected_b64):
        return None

    # 解码 payload
    try:
        # 恢复 base64 padding
        padding = 4 - len(payload_b64) % 4
        if padding != 4:
            payload_b64 += "=" * padding
        payload_bytes = base64.urlsafe_b64decode(payload_b64)
        payload = json.loads(payload_bytes.decode("utf-8"))
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return None

    # 验证必要字段（sub 可以是 int 或 str，与 User.id 类型兼容）
    sub = payload.get("sub")
    if not isinstance(sub, (int, str)) or (isinstance(sub, str) and not sub.strip()):
        return None
    if not isinstance(payload.get("iat"), (int, float)):
        return None

    # 验证有效期
    token_age = time.time() - payload["iat"]
    if token_age < 0 or token_age > _CSRF_TOKEN_MAX_AGE_SECONDS:
        logger.bind(
            event="csrf_token_expired", module="security"
        ).debug(f"CSRF token expired: age={token_age:.0f}s")
        return None

    return payload
