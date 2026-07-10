# -*- coding: utf-8 -*-
"""
搜索配置路由单元测试。

覆盖 /api/search 路由的全部端点：
1. GET /config：默认配置返回、api_key 脱敏、未认证 401
2. PUT /config：保存 searxng provider、provider 校验、URL 校验、SSRF 防护、
   内网授权放行、localhost 拒绝、云元数据地址拒绝
3. POST /test：searxng 成功调用、超时失败、500 失败、使用请求体配置而非数据库配置

测试隔离：每个测试独立 fixture，使用 in-memory SQLite，不依赖全局状态。
HTTP mock：使用 monkeypatch.setattr(httpx, "AsyncClient", ...) 替换 AsyncClient，禁止真实网络调用。
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Optional

import pytest
from fastapi import FastAPI, HTTPException, status
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# 兼容性兜底：当 pytest-cov 的 import hooks 激活时，bcrypt 的 PyO3 扩展可能
# 抛 "PyO3 modules compiled for CPython 3.8 or older may only be initialized
# once per interpreter process" 错误。本测试文件仅测试搜索配置路由，不涉及
# 密码哈希，因此安全地注入 mock bcrypt 规避环境依赖问题。
if "bcrypt" not in sys.modules:
    try:
        import bcrypt  # noqa: F401
    except ImportError:
        _mock_bcrypt = types.ModuleType("bcrypt")
        _mock_bcrypt.hashpw = lambda *args, **kwargs: b"mock_hash"
        _mock_bcrypt.checkpw = lambda *args, **kwargs: True
        _mock_bcrypt.gensalt = lambda *args, **kwargs: b"mock_salt"
        _mock_bcrypt.__version__ = "mock"
        sys.modules["bcrypt"] = _mock_bcrypt

from api.dependencies import get_current_user, get_db
from api.routes.search_config import router as search_router
from db.models import Base, SearchProviderConfig


# ==================== 测试用户与依赖覆盖 ====================


class _DummyUser:
    """测试用 DummyUser，仅暴露 id/username/role 三个字段。"""

    def __init__(self, user_id: str, username: str) -> None:
        self.id = user_id
        self.username = username
        self.role = "user"


_USER_A = _DummyUser("user-a", "alice")
_USER_A.role = "admin"


def _override_user(user: _DummyUser):
    """生成 get_current_user 的依赖覆盖函数。"""

    def _override() -> _DummyUser:
        return user

    return _override


def _deny_user():
    """模拟未认证：依赖函数抛 401。"""

    def _raise() -> None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    return _raise


# ==================== 公共 fixture ====================


@pytest.fixture()
def db_session():
    """
    创建独立的内存数据库会话。
    每个测试用例使用全新的数据库实例，避免测试之间互相污染。
    """
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def client_fixture(db_session):
    """
    构造仅注册 search_config 路由的 FastAPI 测试客户端。
    覆盖 get_db 依赖返回内存会话，覆盖 get_current_user 返回普通用户。
    """
    app = FastAPI()
    app.include_router(search_router)

    def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = _override_user(_USER_A)

    with TestClient(app) as client:
        yield client


@pytest.fixture()
def unauth_client_fixture(db_session):
    """构造未认证的测试客户端，用于 401 测试。"""
    app = FastAPI()
    app.include_router(search_router)

    def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = _deny_user()

    with TestClient(app) as client:
        yield client


@pytest.fixture()
def seed_default_config_fixture(db_session):
    """在数据库插入默认 duckduckgo 配置（enabled=True）。"""
    config = SearchProviderConfig(
        provider="duckduckgo",
        base_url=None,
        api_key=None,
        enabled=True,
        extra_config={},
    )
    db_session.add(config)
    db_session.commit()
    db_session.refresh(config)
    return config


# ==================== GET /config 测试 ====================


class TestGetConfig:
    """GET /api/search/config 端点测试。"""

    def test_get_config_returns_default_duckduckgo(self, client_fixture) -> None:
        """无激活配置时应返回 duckduckgo 默认值。"""
        response = client_fixture.get("/api/search/config")

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["provider"] == "duckduckgo"
        # 默认 base_url 为 None（JSON 中为 null）
        assert body["base_url"] is None
        assert body["api_key_set"] is False
        assert body["enabled"] is True

    def test_get_config_masks_api_key_when_set(
        self, client_fixture, db_session
    ) -> None:
        """当 api_key 已设置时，响应只暴露 api_key_set=True，不返回原值。"""
        # 插入一条带 api_key 的激活配置
        config = SearchProviderConfig(
            provider="searxng",
            base_url="https://example.com",
            api_key="sk-secret",
            enabled=True,
            extra_config={},
        )
        db_session.add(config)
        db_session.commit()

        response = client_fixture.get("/api/search/config")

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["api_key_set"] is True
        # 响应中不应包含原 api_key 字符串
        assert "sk-secret" not in response.text
        # 响应字段不应有 api_key 原文键
        assert "api_key" not in body

    def test_get_config_returns_401_when_unauthenticated(
        self, unauth_client_fixture
    ) -> None:
        """未认证请求应返回 401。"""
        response = unauth_client_fixture.get("/api/search/config")

        assert response.status_code == 401, response.text


# ==================== PUT /config 测试 ====================


class TestPutConfig:
    """PUT /api/search/config 端点测试。"""

    def test_put_config_saves_searxng_provider(self, client_fixture, monkeypatch) -> None:
        """PUT searxng 配置应返回 200，再 GET 验证已持久化。"""
        monkeypatch.setattr(
            "api.routes.search_config.validate_search_url",
            lambda url, allow_private=False: (True, None),
        )
        put_response = client_fixture.put(
            "/api/search/config",
            json={
                "provider": "searxng",
                "base_url": "https://example.com/search",
                "enabled": True,
            },
        )

        assert put_response.status_code == 200, put_response.text
        put_body = put_response.json()
        assert put_body["provider"] == "searxng"
        assert put_body["base_url"] == "https://example.com/search"

        # 再 GET 验证持久化
        get_response = client_fixture.get("/api/search/config")
        assert get_response.status_code == 200
        get_body = get_response.json()
        assert get_body["provider"] == "searxng"
        assert get_body["base_url"] == "https://example.com/search"

    def test_put_config_rejects_invalid_provider(self, client_fixture) -> None:
        """非法 provider 应返回 422（Pydantic pattern 校验失败）。"""
        response = client_fixture.put(
            "/api/search/config",
            json={"provider": "invalid", "base_url": "https://example.com"},
        )

        assert response.status_code == 422, response.text

    def test_put_config_rejects_malformed_url(self, client_fixture) -> None:
        """searxng provider 提供非 http(s) 开头的 base_url 应被拒绝。

        实现层在 handler 中校验 base_url 必须以 http:// 或 https:// 开头，
        不通过时返回 400（非 422 Pydantic 校验）。
        """
        response = client_fixture.put(
            "/api/search/config",
            json={"provider": "searxng", "base_url": "not-a-url"},
        )

        # 实现返回 400（handler 层 HTTPException），非 422（schema 层）
        assert response.status_code == 400, response.text
        # 错误信息应包含 http 提示
        assert "http" in response.text.lower() or "base_url" in response.text.lower()

    def test_put_config_rejects_private_ip_by_default(
        self, client_fixture
    ) -> None:
        """默认拒绝私有 IP 地址的 base_url。

        实现层 SSRF 校验失败时返回 400（handler 层 HTTPException），
        非 403。响应应包含"不允许配置内网地址"提示。
        """
        response = client_fixture.put(
            "/api/search/config",
            json={
                "provider": "searxng",
                "base_url": "http://192.168.2.10:7653/",
            },
        )

        # 实现返回 400（SSRF 校验失败）
        assert response.status_code == 400, response.text
        assert "不允许配置内网地址" in response.text

    def test_put_config_allows_private_ip_when_explicitly_authorized(
        self, client_fixture
    ) -> None:
        """extra_config.allow_private_network=true 时允许私有 IP，但记录 WARNING 审计日志。"""
        response = client_fixture.put(
            "/api/search/config",
            json={
                "provider": "searxng",
                "base_url": "http://192.168.2.10:7653/",
                "extra_config": {"allow_private_network": True},
            },
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["provider"] == "searxng"
        assert body["base_url"] == "http://192.168.2.10:7653/"
        # extra_config 应保留 allow_private_network 标记
        assert body["extra_config"].get("allow_private_network") is True

    def test_put_config_rejects_localhost(self, client_fixture) -> None:
        """localhost 地址应被 SSRF 策略拒绝。"""
        response = client_fixture.put(
            "/api/search/config",
            json={
                "provider": "searxng",
                "base_url": "http://localhost:8080/",
            },
        )

        # 实现返回 400（SSRF 校验失败）
        assert response.status_code == 400, response.text
        assert "localhost" in response.text or "不允许配置" in response.text

    def test_put_config_rejects_cloud_metadata_address(
        self, client_fixture
    ) -> None:
        """云元数据地址（169.254.169.254）应被 SSRF 策略拒绝。"""
        response = client_fixture.put(
            "/api/search/config",
            json={
                "provider": "searxng",
                "base_url": "http://169.254.169.254/",
            },
        )

        # 实现返回 400（SSRF 校验失败）
        assert response.status_code == 400, response.text
        assert "云元数据" in response.text or "不允许配置" in response.text


# ==================== POST /test 测试 ====================


class TestPostTestSearch:
    """POST /api/search/test 端点测试。"""

    def test_search_test_calls_searxng_successfully(
        self, client_fixture, monkeypatch
    ) -> None:
        """mock httpx 成功响应，POST /test 应返回 success=True 与样本结果。"""

        class MockResponse:
            status_code = 200

            def json(self):
                return {
                    "results": [
                        {
                            "title": "OpenAwA Project",
                            "url": "https://example.com/1",
                            "content": "Open-AwA is an AI agent platform",
                        },
                        {
                            "title": "SearXNG",
                            "url": "https://example.com/2",
                            "content": "SearXNG is a metasearch engine",
                        },
                    ]
                }

        class MockAsyncClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def get(self, url, params=None, headers=None, **kwargs):
                return MockResponse()

        monkeypatch.setattr(
            "api.routes.search_config.httpx.AsyncClient", MockAsyncClient
        )
        monkeypatch.setattr(
            "api.routes.search_config.validate_search_url",
            lambda url, allow_private=False: (True, None),
        )

        response = client_fixture.post(
            "/api/search/test",
            json={
                "provider": "searxng",
                "base_url": "https://example.com",
            },
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["success"] is True
        assert body["latency_ms"] >= 0
        assert isinstance(body["sample_results"], list)
        assert len(body["sample_results"]) == 2
        # 样本结果应包含 title/url/snippet 字段
        first = body["sample_results"][0]
        assert "title" in first
        assert "url" in first
        assert "snippet" in first

    def test_search_test_returns_failure_on_timeout(
        self, client_fixture, monkeypatch
    ) -> None:
        """mock httpx 超时异常，POST /test 应返回 success=False 与超时错误。"""

        class MockAsyncClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def get(self, url, params=None, headers=None, **kwargs):
                raise __import__("httpx").TimeoutException("Connection timed out")

        monkeypatch.setattr(
            "api.routes.search_config.httpx.AsyncClient", MockAsyncClient
        )
        monkeypatch.setattr(
            "api.routes.search_config.validate_search_url",
            lambda url, allow_private=False: (True, None),
        )

        response = client_fixture.post(
            "/api/search/test",
            json={
                "provider": "searxng",
                "base_url": "https://example.com",
            },
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["success"] is False
        assert body["error"] is not None
        assert "超时" in body["error"] or "timeout" in body["error"].lower()

    def test_search_test_returns_failure_on_500(
        self, client_fixture, monkeypatch
    ) -> None:
        """mock SearXNG 返回 500，POST /test 应返回 success=False 与 HTTP 错误。"""
        import httpx

        class MockAsyncClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def get(self, url, params=None, headers=None, **kwargs):
                return httpx.Response(500, request=httpx.Request("GET", url))

        monkeypatch.setattr(
            "api.routes.search_config.httpx.AsyncClient", MockAsyncClient
        )
        monkeypatch.setattr(
            "api.routes.search_config.validate_search_url",
            lambda url, allow_private=False: (True, None),
        )

        response = client_fixture.post(
            "/api/search/test",
            json={
                "provider": "searxng",
                "base_url": "https://example.com",
            },
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["success"] is False
        assert body["error"] is not None
        assert "500" in body["error"]

    def test_search_test_uses_request_body_config_not_db_config(
        self, client_fixture, db_session, monkeypatch
    ) -> None:
        """请求体中提供的临时配置应被用于测试，不应读取数据库。

        验证方式：数据库中插入 searxng 配置指向 https://8.8.4.4，
        但请求体中提供 https://8.8.8.8。
        使用公网 IP 字面量避免 DNS 解析依赖，SSRF 校验在 IP 字面量阶段直接通过。
        通过捕获实际请求 URL 验证使用的是请求体中的配置。
        """
        captured_urls = []

        class MockResponse:
            status_code = 200

            def json(self):
                return {"results": []}

        class MockAsyncClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def get(self, url, params=None, headers=None, **kwargs):
                captured_urls.append(url)
                return MockResponse()

        monkeypatch.setattr(
            "api.routes.search_config.httpx.AsyncClient", MockAsyncClient
        )

        # 数据库中插入不同配置（使用公网 IP 避免依赖 DNS）
        db_config = SearchProviderConfig(
            provider="searxng",
            base_url="https://8.8.4.4",
            api_key=None,
            enabled=True,
            extra_config={},
        )
        db_session.add(db_config)
        db_session.commit()

        # 请求体中使用不同的 base_url（公网 IP）
        response = client_fixture.post(
            "/api/search/test",
            json={
                "provider": "searxng",
                "base_url": "https://8.8.8.8",
            },
        )

        assert response.status_code == 200, response.text
        assert response.json()["success"] is True
        # 验证实际请求的 URL 来自请求体，而非数据库
        assert len(captured_urls) == 1
        assert "8.8.8.8" in captured_urls[0]
        assert "8.8.4.4" not in captured_urls[0]
