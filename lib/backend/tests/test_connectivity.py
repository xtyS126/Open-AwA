"""
连通性测试模块 - 验证 API Key 真实连通性检测端点的行为。
覆盖场景：有效 Key 返回成功、无效 Key 返回 401 错误、超时返回超时提示。
"""

from types import SimpleNamespace

import pytest
import httpx
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from db.models import Base
from api.dependencies import get_current_admin_user, get_current_user
from main import app


@pytest.fixture
def db_session():
    """创建独立的内存数据库会话，避免测试之间互相影响。"""
    engine = create_engine(
        "sqlite://",
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def client(db_session, monkeypatch):
    """为系统路由提供覆盖依赖后的测试客户端。"""
    async def override_get_current_admin_user():
        return SimpleNamespace(id=1, username="admin", role="admin")

    app.dependency_overrides[get_current_admin_user] = override_get_current_admin_user
    app.dependency_overrides[get_current_user] = override_get_current_admin_user
    # 连接分类测试只模拟 HTTP 层，单独的 SSRF 测试负责验证地址拦截策略。
    from api.routes import system as system_routes
    monkeypatch.setattr(system_routes, "_validate_connectivity_url", lambda url: None)
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(get_current_admin_user, None)
        app.dependency_overrides.pop(get_current_user, None)


class TestConnectivityTestEndpoint:
    """验证 POST /api/system/connectivity-test 端点的行为。"""

    def test_valid_key_returns_success_with_model_count(self, client, monkeypatch):
        """
        有效 API Key 应返回成功结果，包含模型数量和延迟。
        """
        class MockResponse:
            status_code = 200

            def json(self):
                return {
                    "data": [
                        {"id": "gpt-4o"},
                        {"id": "gpt-4o-mini"},
                        {"id": "gpt-3.5-turbo"},
                    ]
                }

        class MockAsyncClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def get(self, url, headers=None, **kwargs):
                return MockResponse()

        monkeypatch.setattr(httpx, "AsyncClient", MockAsyncClient)

        response = client.post(
            "/api/system/connectivity-test",
            json={
                "provider": "openai",
                "api_key": "sk-valid-test-key-1234567890",
            },
        )
        assert response.status_code == 200
        data = response.json()

        assert data["success"] is True
        assert data["model_count"] == 3
        assert data["error_message"] is None
        assert data["latency_ms"] >= 0
        assert data["provider"] == "openai"

    def test_invalid_key_returns_401_error_message(self, client, monkeypatch):
        """
        无效 API Key 应返回 401 错误及中文提示。
        """
        class MockAsyncClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def get(self, url, headers=None, **kwargs):
                return httpx.Response(401, request=httpx.Request("GET", url))

        monkeypatch.setattr(httpx, "AsyncClient", MockAsyncClient)

        response = client.post(
            "/api/system/connectivity-test",
            json={
                "provider": "openai",
                "api_key": "sk-invalid-key",
            },
        )
        assert response.status_code == 200
        data = response.json()

        assert data["success"] is False
        assert data["model_count"] is None
        assert data["error_message"] == "API Key 无效或已过期"
        assert data["provider"] == "openai"

    def test_timeout_returns_timeout_error_message(self, client, monkeypatch):
        """
        连接超时应返回超时错误提示。
        """
        class MockAsyncClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def get(self, url, headers=None, **kwargs):
                raise httpx.TimeoutException("Connection timed out")

        monkeypatch.setattr(httpx, "AsyncClient", MockAsyncClient)

        response = client.post(
            "/api/system/connectivity-test",
            json={
                "provider": "deepseek",
                "api_key": "sk-test-key-1234567890",
            },
        )
        assert response.status_code == 200
        data = response.json()

        assert data["success"] is False
        assert data["model_count"] is None
        assert data["error_message"] == "连接超时（5秒），请检查网络或 Base URL"
        assert data["provider"] == "deepseek"

    def test_connect_error_returns_unreachable_message(self, client, monkeypatch):
        """
        连接失败（如 DNS 解析失败）应返回无法连接提示。
        """
        class MockAsyncClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def get(self, url, headers=None, **kwargs):
                raise httpx.ConnectError("Connection refused")

        monkeypatch.setattr(httpx, "AsyncClient", MockAsyncClient)

        response = client.post(
            "/api/system/connectivity-test",
            json={
                "provider": "openai",
                "api_key": "sk-test-key-1234567890",
                "base_url": "https://invalid-host.example.com",
            },
        )
        assert response.status_code == 200
        data = response.json()

        assert data["success"] is False
        assert data["error_message"] == "无法连接到服务器，请检查 Base URL"

    def test_403_returns_permission_error(self, client, monkeypatch):
        """
        403 状态码应返回权限不足提示。
        """
        class MockAsyncClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def get(self, url, headers=None, **kwargs):
                return httpx.Response(403, request=httpx.Request("GET", url))

        monkeypatch.setattr(httpx, "AsyncClient", MockAsyncClient)

        response = client.post(
            "/api/system/connectivity-test",
            json={
                "provider": "openai",
                "api_key": "sk-restricted-key",
            },
        )
        assert response.status_code == 200
        data = response.json()

        assert data["success"] is False
        assert data["error_message"] == "API Key 权限不足"

    def test_missing_api_key_returns_error(self, client):
        """
        未提供 API Key 应返回错误提示。
        """
        response = client.post(
            "/api/system/connectivity-test",
            json={
                "provider": "openai",
                "api_key": "",
            },
        )
        assert response.status_code == 200
        data = response.json()

        assert data["success"] is False
        assert data["error_message"] == "未提供 API Key"

    def test_missing_provider_and_env_var_returns_422(self, client):
        """
        未提供 provider 和 env_var_name 应返回 422 错误。
        """
        response = client.post(
            "/api/system/connectivity-test",
            json={
                "api_key": "sk-test-key",
            },
        )
        assert response.status_code == 422

    def test_custom_base_url_is_used(self, client, monkeypatch):
        """
        自定义 Base URL 应被正确使用。
        """
        captured_url = {}

        class MockResponse:
            status_code = 200

            def json(self):
                return {"data": [{"id": "custom-model"}]}

        class MockAsyncClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def get(self, url, headers=None, **kwargs):
                captured_url["value"] = url
                return MockResponse()

        monkeypatch.setattr(httpx, "AsyncClient", MockAsyncClient)

        response = client.post(
            "/api/system/connectivity-test",
            json={
                "provider": "openai",
                "api_key": "sk-test-key-1234567890",
                "base_url": "https://custom-proxy.example.com/v1",
            },
        )
        assert response.status_code == 200
        data = response.json()

        assert data["success"] is True
        assert data["model_count"] == 1
        # 验证自定义 Base URL 被正确拼接
        assert captured_url["value"] == "https://custom-proxy.example.com/v1/models"

    def test_anthropic_uses_x_api_key_header(self, client, monkeypatch):
        """
        Anthropic 供应商应使用 x-api-key 请求头而非 Authorization Bearer。
        """
        captured_headers = {}

        class MockResponse:
            status_code = 200

            def json(self):
                return {"data": [{"id": "claude-3-opus"}]}

        class MockAsyncClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def get(self, url, headers=None, **kwargs):
                captured_headers["value"] = headers or {}
                return MockResponse()

        monkeypatch.setattr(httpx, "AsyncClient", MockAsyncClient)

        response = client.post(
            "/api/system/connectivity-test",
            json={
                "provider": "anthropic",
                "api_key": "sk-ant-test-key-1234567890",
            },
        )
        assert response.status_code == 200
        data = response.json()

        assert data["success"] is True
        assert data["provider"] == "anthropic"
        # 验证 Anthropic 使用 x-api-key 头
        assert "x-api-key" in captured_headers["value"]
        assert captured_headers["value"]["x-api-key"] == "sk-ant-test-key-1234567890"
        # 不应使用 Authorization Bearer
        assert "Authorization" not in captured_headers["value"]


class TestBuildModelsUrl:
    """验证 _build_models_url 辅助函数的 URL 拼接逻辑。"""

    def test_openai_default_url(self):
        """OpenAI 默认 Base URL 应拼接为 /v1/models。"""
        from api.routes.system import _build_models_url
        url = _build_models_url("openai", "https://api.openai.com/v1")
        assert url == "https://api.openai.com/v1/models"

    def test_base_url_without_v1_suffix(self):
        """不含 /v1 后缀的 Base URL 应自动追加 /v1/models。"""
        from api.routes.system import _build_models_url
        url = _build_models_url("openai", "https://api.openai.com")
        assert url == "https://api.openai.com/v1/models"

    def test_anthropic_url(self):
        """Anthropic 应使用 /v1/models 端点。"""
        from api.routes.system import _build_models_url
        url = _build_models_url("anthropic", "https://api.anthropic.com")
        assert url == "https://api.anthropic.com/v1/models"

    def test_deepseek_url(self):
        """DeepSeek Base URL 已含 /v1 应直接追加 /models。"""
        from api.routes.system import _build_models_url
        url = _build_models_url("deepseek", "https://api.deepseek.com/v1")
        assert url == "https://api.deepseek.com/v1/models"


class TestClassifyHttpError:
    """验证 _classify_http_error 辅助函数的错误分类逻辑。"""

    def test_401_returns_invalid_key(self):
        from api.routes.system import _classify_http_error
        assert _classify_http_error(401) == "API Key 无效或已过期"

    def test_403_returns_permission_denied(self):
        from api.routes.system import _classify_http_error
        assert _classify_http_error(403) == "API Key 权限不足"

    def test_404_returns_endpoint_not_found(self):
        from api.routes.system import _classify_http_error
        assert _classify_http_error(404) == "API 端点不存在，请检查 Base URL"

    def test_500_returns_unknown_error(self):
        from api.routes.system import _classify_http_error
        assert _classify_http_error(500) == "未知错误: HTTP 500"

    def test_429_returns_unknown_error(self):
        from api.routes.system import _classify_http_error
        assert _classify_http_error(429) == "未知错误: HTTP 429"
