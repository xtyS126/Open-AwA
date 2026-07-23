# -*- coding: utf-8 -*-
"""
密码即 Bearer 凭证认证测试。

覆盖 spec support-password-as-bearer 的全部场景：
1. PasswordVerificationCache 单元测试（set/get/clear/expire/不存明文）
2. 密码登录成功（Bearer <正确密码> → 200，返回 owner 信息）
3. 密码错误（Bearer <错误密码> → 401）
4. API Key 仍可程序化调用（Bearer <api_key> → 200）
5. 密码缓存命中（mock verify_password 验证调用次数=1）
6. 密码修改后旧密码失效（修改密码 → 旧密码 Bearer → 401）
7. owner 不存在时密码验证路径跳过（不抛异常，返回 401）
8. get_optional_current_user 密码验证路径（返回用户而非 None）

测试隔离：
- 使用 in-memory SQLite + StaticPool 保证 DB 会话与线程池查询共享同一连接
- 每个用例前清理 owner 缓存与密码验证缓存
- 直接设置 core.owner._owner_cache 为测试用户，避免 get_owner_user 走全局 SessionLocal
"""

from __future__ import annotations

import sys
import time
import types
import uuid
from pathlib import Path
from typing import Optional
from unittest.mock import patch

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from pydantic import SecretStr

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# 兼容性兜底：当 pytest-cov 的 import hooks 激活时，bcrypt 的 PyO3 扩展可能
# 抛 "PyO3 modules compiled for CPython 3.8 or older may only be initialized
# once per interpreter process" 错误。本测试需要真实 bcrypt 做密码哈希验证，
# 因此仅在 bcrypt 真实不可用时注入 mock，否则保留真实实现。
if "bcrypt" not in sys.modules:
    try:
        import bcrypt  # noqa: F401
    except ImportError:
        _mock_bcrypt = types.ModuleType("bcrypt")
        _mock_bcrypt.hashpw = lambda *a, **kw: b"mock_hash"
        _mock_bcrypt.checkpw = lambda *a, **kw: True
        _mock_bcrypt.gensalt = lambda *a, **kw: b"mock_salt"
        _mock_bcrypt.__version__ = "mock"
        sys.modules["bcrypt"] = _mock_bcrypt

from api.dependencies import (
    get_current_user,
    get_db,
    get_optional_current_user,
)
from api.routes.auth import router as auth_router
from config.security import get_password_hash
from config.settings import settings
from core.owner import invalidate_owner_cache
from core.password_cache import PasswordVerificationCache, password_verification_cache
from db.models import Base, User


# ============================================================================
# 测试常量
# ============================================================================

_TEST_API_KEY = "sk-test-api-key-0123456789abcdef0123456789abcdef"
_TEST_OWNER_USERNAME = "admin"
_TEST_OWNER_PASSWORD = "TestPass123!"  # 含特殊字符，验证 _TOKEN_CHARSET_RE 之外字符可用
_TEST_OWNER_NEW_PASSWORD = "NewPass456!"


# ============================================================================
# 缓存单元测试（同步，无需 FastAPI）
# ============================================================================


class TestPasswordVerificationCache:
    """PasswordVerificationCache 单元测试，覆盖 set/get/clear/expire/线程安全。"""

    def test_set_and_get_returns_user_id(self) -> None:
        """set 写入后 get 应返回对应 user_id。"""
        cache = PasswordVerificationCache()
        cache.set("mypassword", "user-123")

        assert cache.get("mypassword") == "user-123"

    def test_get_returns_none_for_unknown_password(self) -> None:
        """未写入的密码 get 返回 None。"""
        cache = PasswordVerificationCache()

        assert cache.get("unknown") is None

    def test_get_returns_none_for_empty_password(self) -> None:
        """空密码 get 返回 None，不写入缓存。"""
        cache = PasswordVerificationCache()

        assert cache.get("") is None

    def test_clear_empties_all_entries(self) -> None:
        """clear 后所有缓存条目被清空。"""
        cache = PasswordVerificationCache()
        cache.set("pwd1", "user-1")
        cache.set("pwd2", "user-2")
        assert len(cache) == 2

        cache.clear()

        assert len(cache) == 0
        assert cache.get("pwd1") is None
        assert cache.get("pwd2") is None

    def test_expired_entry_returns_none_and_is_cleaned(self) -> None:
        """过期条目 get 时返回 None 并被惰性清理。"""
        cache = PasswordVerificationCache()
        # 写入 TTL=0 的条目，立即过期
        cache.set("shortlived", "user-1", ttl=0)
        # monotonic 可能在同一刻，强制推进时间感知：用极小 TTL
        time.sleep(0.001)

        assert cache.get("shortlived") is None
        # 过期条目应被清理
        assert len(cache) == 0

    def test_does_not_store_plaintext_password(self) -> None:
        """缓存内部字典不应包含明文密码，仅存储 sha256 摘要。"""
        cache = PasswordVerificationCache()
        cache.set("plaintext-secret", "user-1")

        # 内部字典的 key 不应是明文密码
        internal_keys = list(cache._cache.keys())
        assert "plaintext-secret" not in internal_keys
        # key 应是 64 字符的 sha256 hex
        assert all(len(k) == 64 for k in internal_keys)

    def test_same_password_overwrites_previous_entry(self) -> None:
        """同一密码多次 set 应覆盖旧条目，不产生重复 key。"""
        cache = PasswordVerificationCache()
        cache.set("pwd", "user-1")
        cache.set("pwd", "user-2")

        assert len(cache) == 1
        assert cache.get("pwd") == "user-2"

    def test_thread_safe_concurrent_access(self) -> None:
        """多线程并发读写不应抛异常（基础线程安全验证）。"""
        import threading

        cache = PasswordVerificationCache()
        errors: list[Exception] = []

        def _writer():
            try:
                for i in range(100):
                    cache.set(f"pwd-{i}", f"user-{i}")
            except Exception as exc:
                errors.append(exc)

        def _reader():
            try:
                for i in range(100):
                    cache.get(f"pwd-{i % 10}")
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=_writer) for _ in range(4)] + \
                  [threading.Thread(target=_reader) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"并发访问出现异常: {errors}"


# ============================================================================
# 集成测试 fixture
# ============================================================================


@pytest.fixture
def db_session():
    """
    创建内存 SQLite 会话，使用 StaticPool 保证 get_owner_user 内部
    通过 SessionLocal 查询时也能命中同一内存数据库（线程池共享连接）。
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionFactory = sessionmaker(bind=engine)
    session = SessionFactory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def owner_user(db_session) -> User:
    """在测试 DB 中创建 owner 用户，密码为 _TEST_OWNER_PASSWORD。"""
    user = User(
        id=str(uuid.uuid4()),
        username=_TEST_OWNER_USERNAME,
        password_hash=get_password_hash(_TEST_OWNER_PASSWORD),
        role="admin",
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture(autouse=True)
def reset_caches_and_state():
    """每个用例前后清理 owner 缓存、密码验证缓存等全局状态。"""
    invalidate_owner_cache()
    password_verification_cache.clear()

    # 初始化限流存储（change_password 端点依赖），未初始化时使用 memory 后端
    from security.rate_limit_store import get_rate_limit_store, init_rate_limit_store
    try:
        store = get_rate_limit_store()
    except RuntimeError:
        store = init_rate_limit_store("memory")
    # 清理限流状态，避免跨用例污染
    if hasattr(store, "_state"):
        store._state.clear()
    if hasattr(store, "_failed_attempts"):
        store._failed_attempts.clear()

    yield

    invalidate_owner_cache()
    password_verification_cache.clear()
    if hasattr(store, "_state"):
        store._state.clear()
    if hasattr(store, "_failed_attempts"):
        store._failed_attempts.clear()


@pytest.fixture
def api_key_setting(monkeypatch):
    """设置 settings.OPENAWA_API_KEY 为已知测试值，用例后恢复。"""
    original = settings.OPENAWA_API_KEY
    monkeypatch.setattr(
        settings,
        "OPENAWA_API_KEY",
        SecretStr(_TEST_API_KEY),
    )
    yield _TEST_API_KEY


@pytest.fixture
def owner_cache_set(owner_user):
    """直接设置 core.owner._owner_cache 为测试用户，避免 get_owner_user 查全局 DB。"""
    import core.owner as owner_module
    owner_module._owner_cache = owner_user
    yield owner_user
    owner_module._owner_cache = None


@pytest.fixture
def client(db_session, owner_user):
    """
    构造仅注册 auth 路由 + 测试专用端点的 FastAPI 客户端。
    覆盖 get_db 依赖返回内存会话；保留 get_current_user / get_optional_current_user 真实逻辑。
    """
    app = FastAPI()
    app.include_router(auth_router, prefix="/api")

    # 测试专用端点：验证 get_optional_current_user 密码验证路径
    @app.get("/api/test/optional-user")
    async def _test_optional_user(
        user: Optional[User] = Depends(get_optional_current_user),
    ):
        if user is None:
            return {"authenticated": False}
        return {"authenticated": True, "user_id": user.id, "username": user.username}

    def _override_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = _override_db

    with TestClient(app) as test_client:
        yield test_client


# ============================================================================
# 集成测试：密码即 Bearer 凭证认证
# ============================================================================


class TestPasswordBearerAuth:
    """密码作为 Bearer 凭证的认证集成测试。"""

    def test_password_login_succeeds_with_correct_password(
        self, client, owner_user, owner_cache_set
    ) -> None:
        """Bearer <正确密码> 应返回 200 和 owner 用户信息。"""
        response = client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {_TEST_OWNER_PASSWORD}"},
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["username"] == _TEST_OWNER_USERNAME
        assert body["id"] == owner_user.id
        assert body["role"] == "admin"

    @pytest.mark.asyncio
    async def test_password_bearer_can_request_csrf_token(
        self, client, owner_user, owner_cache_set
    ) -> None:
        """密码 Bearer 必须能够获取后续写操作所需的 CSRF token。"""
        from fastapi import Response
        from main import get_csrf_token

        response = Response()
        payload = await get_csrf_token(response, owner_user)

        assert payload["csrf_token"]
        assert "csrf_access_token=" in response.headers["set-cookie"]

    def test_password_login_succeeds_with_special_chars(
        self, client, owner_user, owner_cache_set, db_session
    ) -> None:
        """密码含 !@#$% 等 _TOKEN_CHARSET_RE 之外字符时仍可登录。"""
        # 更新 owner 密码为含更多特殊字符的密码
        special_password = "P@$$w0rd!#%^&*"
        owner_user.password_hash = get_password_hash(special_password)
        db_session.commit()
        # 清缓存确保用新密码验证
        password_verification_cache.clear()

        response = client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {special_password}"},
        )

        assert response.status_code == 200, response.text
        assert response.json()["username"] == _TEST_OWNER_USERNAME

    def test_wrong_password_returns_401(
        self, client, owner_user, owner_cache_set
    ) -> None:
        """Bearer <错误密码> 应返回 401。"""
        response = client.get(
            "/api/auth/me",
            headers={"Authorization": "Bearer WrongPassword999"},
        )

        assert response.status_code == 401, response.text

    def test_api_key_programmatic_call_still_works(
        self, client, owner_user, owner_cache_set, api_key_setting
    ) -> None:
        """Bearer <api_key> 应返回 200，API Key 程序化调用路径不受影响。"""
        response = client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {_TEST_API_KEY}"},
        )

        assert response.status_code == 200, response.text
        assert response.json()["username"] == _TEST_OWNER_USERNAME

    def test_password_cache_hit_calls_verify_once(
        self, client, owner_user, owner_cache_set
    ) -> None:
        """
        同一密码第二次请求应命中缓存，verify_password 仅被调用 1 次。
        用 mock 计数验证而非时间断言，避免 CI 环境时间波动。
        """
        call_count = 0
        real_verify = None

        # 导入真实 verify_password 作为底层实现
        from config.security import verify_password as _real_verify

        def _counting_verify(plain: str, hashed: str) -> bool:
            nonlocal call_count
            call_count += 1
            return _real_verify(plain, hashed)

        # patch api.dependencies.verify_password（asyncio.to_thread 调用的对象）
        with patch("api.dependencies.verify_password", side_effect=_counting_verify):
            # 第一次请求：缓存未命中，触发 bcrypt 验证
            r1 = client.get(
                "/api/auth/me",
                headers={"Authorization": f"Bearer {_TEST_OWNER_PASSWORD}"},
            )
            assert r1.status_code == 200, r1.text
            assert call_count == 1, f"第一次请求应调用 verify_password 1 次，实际 {call_count}"

            # 第二次请求：缓存命中，不再调用 verify_password
            r2 = client.get(
                "/api/auth/me",
                headers={"Authorization": f"Bearer {_TEST_OWNER_PASSWORD}"},
            )
            assert r2.status_code == 200, r2.text
            assert call_count == 1, (
                f"第二次请求应命中缓存不调用 verify_password，实际调用 {call_count} 次"
            )

    def test_password_change_invalidates_old_password(
        self, client, owner_user, owner_cache_set, api_key_setting
    ) -> None:
        """
        修改密码后旧密码 Bearer 立即失效。
        流程：
        1. 用旧密码 Bearer 调 PUT /me/password 修改密码（验证旧密码可登录）
        2. 用旧密码 Bearer 调 GET /me → 应 401（缓存已清 + 旧密码不匹配新哈希）
        3. 用新密码 Bearer 调 GET /me → 应 200
        """
        # 步骤 1：用旧密码作为 Bearer 修改密码
        change_resp = client.put(
            "/api/auth/me/password",
            json={
                "old_password": _TEST_OWNER_PASSWORD,
                "new_password": _TEST_OWNER_NEW_PASSWORD,
                "confirm_password": _TEST_OWNER_NEW_PASSWORD,
            },
            headers={"Authorization": f"Bearer {_TEST_OWNER_PASSWORD}"},
        )
        assert change_resp.status_code == 200, change_resp.text

        # 步骤 2：旧密码应失效（缓存已清，bcrypt 验证不通过）
        old_resp = client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {_TEST_OWNER_PASSWORD}"},
        )
        assert old_resp.status_code == 401, (
            f"修改密码后旧密码应失效，实际返回 {old_resp.status_code}: {old_resp.text}"
        )

        # 步骤 3：新密码可登录
        new_resp = client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {_TEST_OWNER_NEW_PASSWORD}"},
        )
        assert new_resp.status_code == 200, new_resp.text
        assert new_resp.json()["username"] == _TEST_OWNER_USERNAME

    def test_owner_not_exists_skips_password_path(
        self, client, api_key_setting
    ) -> None:
        """
        owner 不存在（未初始化）时密码验证路径应跳过，返回 401 而非抛 500。
        通过不设置 owner_cache_set + patch _load_user_by_username 返回 None 模拟。
        """
        # 确保 owner 缓存为空
        invalidate_owner_cache()

        # patch _load_user_by_username 返回 None，模拟 DB 无 owner 用户
        with patch("api.dependencies._load_user_by_username", return_value=None):
            response = client.get(
                "/api/auth/me",
                headers={"Authorization": "Bearer AnyRandomPassword123"},
            )

        # 应返回 401，不应返回 500（说明 RuntimeError 被正确捕获）
        assert response.status_code == 401, (
            f"owner 不存在时应返回 401，实际 {response.status_code}: {response.text}"
        )

    def test_empty_bearer_returns_401(
        self, client, owner_user, owner_cache_set
    ) -> None:
        """Bearer 空字符串应返回 401，不触发密码验证。"""
        response = client.get(
            "/api/auth/me",
            headers={"Authorization": "Bearer "},
        )

        assert response.status_code == 401, response.text

    def test_no_authorization_header_returns_401(
        self, client, owner_user, owner_cache_set
    ) -> None:
        """无 Authorization 头应返回 401。"""
        response = client.get("/api/auth/me")

        assert response.status_code == 401, response.text


# ============================================================================
# get_optional_current_user 密码验证路径测试
# ============================================================================


class TestOptionalUserPasswordBearer:
    """get_optional_current_user 密码验证路径测试。"""

    def test_optional_user_returns_user_with_correct_password(
        self, client, owner_user, owner_cache_set
    ) -> None:
        """Bearer <正确密码> 经 get_optional_current_user 应返回用户信息。"""
        response = client.get(
            "/api/test/optional-user",
            headers={"Authorization": f"Bearer {_TEST_OWNER_PASSWORD}"},
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["authenticated"] is True
        assert body["user_id"] == owner_user.id

    def test_optional_user_returns_none_with_wrong_password(
        self, client, owner_user, owner_cache_set
    ) -> None:
        """Bearer <错误密码> 经 get_optional_current_user 应返回 authenticated=False（未抛 401）。"""
        response = client.get(
            "/api/test/optional-user",
            headers={"Authorization": "Bearer WrongPassword999"},
        )

        assert response.status_code == 200, response.text
        assert response.json()["authenticated"] is False

    def test_optional_user_returns_none_without_owner(
        self, client, api_key_setting
    ) -> None:
        """owner 不存在时 get_optional_current_user 不抛异常，返回 authenticated=False。"""
        invalidate_owner_cache()

        with patch("api.dependencies._load_user_by_username", return_value=None):
            response = client.get(
                "/api/test/optional-user",
                headers={"Authorization": "Bearer AnyRandomPassword123"},
            )

        assert response.status_code == 200, response.text
        assert response.json()["authenticated"] is False
