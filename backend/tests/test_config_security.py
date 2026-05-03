"""
config/security.py 单元测试。
覆盖密码哈希、令牌加解密、Cookie操作和JWT创建/解码的边界路径。
"""

import time
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.models import Base, TokenBlacklist


@pytest.fixture
def memory_db():
    """创建内存数据库用于黑名单测试"""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    engine.dispose()


class TestPasswordHash:
    """密码哈希与验证测试"""

    def test_hash_and_verify(self):
        from config.security import get_password_hash, verify_password

        hashed = get_password_hash("my_secret_password")
        assert hashed != "my_secret_password"
        assert verify_password("my_secret_password", hashed) is True
        assert verify_password("wrong_password", hashed) is False

    def test_hash_produces_unique_results(self):
        from config.security import get_password_hash

        h1 = get_password_hash("password123")
        h2 = get_password_hash("password123")
        # 两次哈希结果应不同（salt 不同）
        assert h1 != h2

    def test_verify_empty_password(self):
        from config.security import verify_password

        from config.security import get_password_hash

        hashed = get_password_hash("test")
        assert verify_password("", hashed) is False

    def test_verify_bcrypt_hash(self):
        """验证 bcrypt 格式的哈希（legacy 格式）"""
        from config.security import verify_password

        # 使用已知的 bcrypt 格式哈希
        result = verify_password(
            "test_password",
            "$2b$12$LJ3m4ys3Lk0TSwHCeZQzKOTBqzGfYhDPy6R8DmY5KyJmFRCKhv7jK",
        )
        # 返回 bool（无论匹配与否，不应崩溃）
        assert isinstance(result, bool)


class TestSecretEncryption:
    """敏感值加解密测试"""

    def test_encrypt_decrypt_roundtrip(self):
        from config.security import encrypt_secret_value, decrypt_secret_value

        original = "sk-abc123def456"
        encrypted = encrypt_secret_value(original)
        assert encrypted.startswith("enc:")
        assert original not in encrypted

        decrypted = decrypt_secret_value(encrypted)
        assert decrypted == original

    def test_encrypt_empty_string(self):
        from config.security import encrypt_secret_value

        assert encrypt_secret_value("") == ""
        assert encrypt_secret_value(None) == ""

    def test_encrypt_already_encrypted(self):
        from config.security import encrypt_secret_value

        already = "enc:some_encrypted_value"
        result = encrypt_secret_value(already)
        assert result == already  # 不重复加密

    def test_decrypt_plain_text(self):
        from config.security import decrypt_secret_value

        assert decrypt_secret_value("plain_key_12345") == "plain_key_12345"

    def test_decrypt_empty_string(self):
        from config.security import decrypt_secret_value

        assert decrypt_secret_value("") == ""
        assert decrypt_secret_value(None) == ""

    def test_decrypt_empty_payload(self):
        from config.security import decrypt_secret_value

        # "enc:" 后无实际内容
        assert decrypt_secret_value("enc:") == ""

    def test_decrypt_corrupted_payload(self):
        from config.security import decrypt_secret_value

        result = decrypt_secret_value("enc:not_a_valid_encrypted_payload_!")
        # 解密失败返回空字符串，不抛异常
        assert result == ""


class TestTokenBlacklist:
    """JWT 黑名单操作测试"""

    def test_add_to_blacklist(self, memory_db):
        from config.security import add_to_blacklist

        jti = "test-jti-12345678"
        add_to_blacklist(jti, memory_db)

        record = (
            memory_db.query(TokenBlacklist)
            .filter(TokenBlacklist.jti == jti)
            .first()
        )
        assert record is not None
        assert record.jti == jti
        assert record.expires_at is not None
        # SQLite 可能存储为 naive datetime，统一转换为 UTC 比较
        expires = record.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        assert expires > datetime.now(timezone.utc)

    def test_add_empty_jti_skipped(self, memory_db):
        from config.security import add_to_blacklist

        add_to_blacklist("", memory_db)
        add_to_blacklist(None, memory_db)

        count = memory_db.query(TokenBlacklist).count()
        assert count == 0

    def test_add_cleans_expired_entries(self, memory_db):
        from config.security import add_to_blacklist

        # 插入一条已过期的记录
        expired = TokenBlacklist(
            jti="expired-jti",
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
        memory_db.add(expired)
        memory_db.commit()
        memory_db.expunge_all()  # 清理 identity map 避免后续 flush 冲突

        add_to_blacklist("new-jti", memory_db)

        # 过期记录应被清理
        expired_record = (
            memory_db.query(TokenBlacklist)
            .filter(TokenBlacklist.jti == "expired-jti")
            .first()
        )
        assert expired_record is None

        # 新记录保留
        new_record = (
            memory_db.query(TokenBlacklist)
            .filter(TokenBlacklist.jti == "new-jti")
            .first()
        )
        assert new_record is not None

    def test_is_token_blacklisted(self, memory_db):
        from config.security import add_to_blacklist, is_token_blacklisted

        assert is_token_blacklisted("nonexistent", memory_db) is False

        add_to_blacklist("blacklisted-jti", memory_db)
        assert is_token_blacklisted("blacklisted-jti", memory_db) is True

    def test_expired_token_not_considered_blacklisted(self, memory_db):
        from config.security import is_token_blacklisted

        # 插入已过期的黑名单记录
        expired = TokenBlacklist(
            jti="expired-jti-2",
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
        memory_db.add(expired)
        memory_db.commit()

        assert is_token_blacklisted("expired-jti-2", memory_db) is False


class TestCookieOperations:
    """Cookie 操作测试"""

    def test_set_access_token_cookie(self):
        from config.security import set_access_token_cookie
        from fastapi import Response

        response = Response()
        set_access_token_cookie(response, "test-token-value")

        cookie_header = response.headers.get("set-cookie", "")
        assert "access_token=test-token-value" in cookie_header
        assert "HttpOnly" in cookie_header
        assert "SameSite=lax" in cookie_header

    def test_set_cookie_with_production_env(self):
        from config.security import set_access_token_cookie
        from fastapi import Response

        with patch.dict("os.environ", {"ENVIRONMENT": "production"}):
            response = Response()
            set_access_token_cookie(response, "prod-token")
            cookie_header = response.headers.get("set-cookie", "")
            assert "Secure" in cookie_header

    def test_clear_access_token_cookie(self):
        from config.security import clear_access_token_cookie
        from fastapi import Response

        response = Response()
        clear_access_token_cookie(response)

        cookie_header = response.headers.get("set-cookie", "")
        assert 'access_token=""' in cookie_header or "access_token=" in cookie_header


class TestJWTToken:
    """JWT 创建与解码测试"""

    def test_create_and_decode_roundtrip(self):
        from config.security import create_access_token, decode_access_token

        token = create_access_token({"sub": "user-123"})
        assert token is not None

        payload = decode_access_token(token)
        assert payload is not None
        assert payload["sub"] == "user-123"
        assert "jti" in payload
        assert "exp" in payload

    def test_create_token_with_custom_expiry(self):
        from config.security import create_access_token, decode_access_token

        token = create_access_token(
            {"sub": "user-456"}, expires_delta=timedelta(minutes=30)
        )
        payload = decode_access_token(token)
        assert payload is not None
        assert payload["sub"] == "user-456"

    def test_decode_invalid_token(self):
        from config.security import decode_access_token

        assert decode_access_token("invalid.token.here") is None
        assert decode_access_token("") is None

    def test_decode_expired_token(self):
        from config.security import create_access_token, decode_access_token

        # 创建已过期的 token
        token = create_access_token(
            {"sub": "user-expired"},
            expires_delta=timedelta(seconds=-1),
        )
        payload = decode_access_token(token)
        assert payload is None

    def test_decode_token_without_exp(self):
        """缺少 exp 字段的 token 返回 None"""
        from config.security import decode_access_token
        from config.settings import settings
        from jose import jwt

        token = jwt.encode(
            {"sub": "user-no-exp", "jti": "test-jti"},
            settings.SECRET_KEY,
            algorithm=settings.ALGORITHM,
        )
        payload = decode_access_token(token)
        assert payload is None

    def test_each_token_has_unique_jti(self):
        from config.security import create_access_token, decode_access_token

        t1 = create_access_token({"sub": "user"})
        t2 = create_access_token({"sub": "user"})

        p1 = decode_access_token(t1)
        p2 = decode_access_token(t2)

        assert p1["jti"] != p2["jti"]
