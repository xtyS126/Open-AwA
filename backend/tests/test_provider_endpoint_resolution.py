"""
后端测试模块，负责验证对应功能在正常、边界或异常场景下的行为是否符合预期。
保持测试注释清晰，有助于快速分辨各个用例所覆盖的场景。
"""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from billing.models import Base, ModelConfiguration, ModelPricing
from billing.pricing_manager import PricingManager
from core.executor import ExecutionLayer
from core.model_service import build_provider_request
from api.dependencies import get_current_user
from db.models import get_db
from main import app


@pytest.fixture
def db_session():
    """
    创建独立的内存数据库会话，避免测试之间互相影响。
    """
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
def client(db_session):
    """
    为计费路由提供覆盖数据库依赖后的测试客户端。
    """
    def override_get_db():
        yield db_session

    async def override_get_current_user():
        return SimpleNamespace(id=1, username="tester", role="admin")

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user, None)


class TestPricingManagerEndpointResolution:
    """
    验证基础 URL 归一化与接口地址拼接逻辑。
    """

    def test_normalize_provider_api_endpoint_keeps_base_url(self):
        """
        保存配置时应当保留基础 URL，如果无 /v1 则补 /v1。
        """
        normalized = PricingManager._normalize_provider_api_endpoint("openai", "https://api.openai.com")
        assert normalized == "https://api.openai.com/v1"

        # 如果已有 v1 则保留
        normalized_v1 = PricingManager._normalize_provider_api_endpoint("openai", "https://api.openai.com/v1")
        assert normalized_v1 == "https://api.openai.com/v1"

    def test_normalize_provider_api_endpoint_strips_known_suffix(self):
        """
        当用户输入完整聊天接口地址时，应自动还原为基础 URL，并确保补上 /v1。
        """
        normalized = PricingManager._normalize_provider_api_endpoint(
            "openai",
            "https://api.openai.com/v1/chat/completions",
        )
        assert normalized == "https://api.openai.com/v1"

    def test_build_provider_api_endpoint_appends_models_suffix(self):
        """
        远端模型拉取时应基于基础 URL 拼接 /models 接口路径（根据最新规范）。
        """
        endpoint = PricingManager.build_provider_api_endpoint("openai", "https://api.openai.com/v1", "models")
        assert endpoint == "https://api.openai.com/v1/models"

    def test_build_provider_api_endpoint_appends_chat_suffix(self):
        """
        聊天调用时应基于基础 URL 自动补全聊天接口后缀。
        """
        endpoint = PricingManager.build_provider_api_endpoint("openai", "https://api.openai.com", "chat")
        assert endpoint == "https://api.openai.com/v1/chat/completions"


class TestBillingProviderModelsRoute:
    """
    验证供应商模型列表优先从远端拉取，并在失败时回退本地。
    """

    def test_get_models_by_provider_prefers_remote_models(self, client, db_session, monkeypatch):
        """
        当配置了基础 URL 且远端可用时，应返回远端模型列表。
        """
        db_session.add(
            ModelConfiguration(
                provider="openai",
                model="gpt-4o-mini",
                display_name="OpenAI",
                api_endpoint="https://api.openai.com",
                api_key="secret",
                selected_models='["gpt-4o-mini"]',
                is_active=True,
                is_default=True,
            )
        )
        db_session.commit()

        calls = {}

        class MockResponse:
            status_code = 200

            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "data": [
                        {"id": "gpt-4o-mini"},
                        {"id": "gpt-4.1"},
                    ]
                }

        class MockAsyncClient:
            is_closed = False

            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def aclose(self):
                pass

            async def get(self, url, headers=None, **kwargs):
                calls["url"] = url
                calls["headers"] = headers or {}
                return MockResponse()

        import httpx
        import core.model_service as _ms

        monkeypatch.setattr(httpx, "AsyncClient", MockAsyncClient)
        # 重置全局共享客户端，避免测试间状态污染
        monkeypatch.setattr(_ms, "_shared_client", None)

        response = client.post("/api/billing/models-by-provider/openai", json={})
        assert response.status_code == 200
        data = response.json()

        assert data["success"] is True
        assert data["source"] == "remote"
        assert calls["url"] == "https://api.openai.com/v1/models"
        assert calls["headers"]["Authorization"] == "Bearer secret"
        assert [item["model"] for item in data["models"]] == ["gpt-4o-mini", "gpt-4.1"]
        assert data["models"][0]["selected"] is True

    def test_get_models_by_provider_returns_auth_error_details(self, client, db_session, monkeypatch):
        """
        当远端模型接口认证失败时，应返回上游错误语义，便于前端明确提示。
        """
        db_session.add(
            ModelConfiguration(
                provider="openai",
                model="gpt-4o-mini",
                display_name="OpenAI",
                api_endpoint="https://api.openai.com",
                api_key="secret",
                selected_models='["gpt-4o-mini"]',
                is_active=True,
                is_default=True,
            )
        )
        db_session.add(
            ModelPricing(
                provider="openai",
                model="gpt-4o-mini",
                input_price=0.3,
                output_price=1.2,
                currency="USD",
                is_active=True,
            )
        )
        db_session.commit()

        class MockAsyncClient:
            is_closed = False

            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def aclose(self):
                pass

            async def get(self, url, headers=None, **kwargs):
                import httpx

                request = httpx.Request("GET", url, headers=headers)
                response = httpx.Response(401, request=request)
                raise httpx.HTTPStatusError(
                    "Client error '401 Authorization Required'",
                    request=request,
                    response=response,
                )

        import httpx
        import core.model_service as _ms

        monkeypatch.setattr(httpx, "AsyncClient", MockAsyncClient)
        # 重置全局共享客户端，避免测试间状态污染
        monkeypatch.setattr(_ms, "_shared_client", None)

        response = client.post(
            "/api/billing/models-by-provider/openai",
            json={"api_endpoint": "https://api.openai.com", "api_key": "bad-key"},
        )
        assert response.status_code == 200
        data = response.json()

        assert not data["success"]
        assert data["error"]["code"] == "model_service_auth_error"
        assert data["error"]["message"] == "模型服务认证失败，请检查 API Key 配置"
        assert data["error"]["status_code"] == 401
        assert len(data["models"]) == 0

    def test_get_models_by_provider_empty_api_key_fallback(self, client, db_session, monkeypatch):
        """
        当传入的 api_key 为空字符串时，系统应当回退使用数据库中已保存的密钥。
        """
        db_session.add(
            ModelConfiguration(
                provider="openai",
                model="gpt-4o-mini",
                display_name="OpenAI",
                api_endpoint="https://api.openai.com",
                api_key="saved-valid-secret",
                selected_models='["gpt-4o-mini"]',
                is_active=True,
                is_default=True,
            )
        )
        db_session.commit()

        calls = {}

        class MockResponse:
            status_code = 200

            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "data": [
                        {"id": "gpt-4o-mini"},
                    ]
                }

        class MockAsyncClient:
            is_closed = False

            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def aclose(self):
                pass

            async def get(self, url, headers=None, **kwargs):
                calls["url"] = url
                calls["headers"] = headers or {}
                return MockResponse()

        import httpx
        import core.model_service as _ms

        monkeypatch.setattr(httpx, "AsyncClient", MockAsyncClient)
        monkeypatch.setattr(_ms, "_shared_client", None)

        response = client.post(
            "/api/billing/models-by-provider/openai",
            json={"api_endpoint": "https://api.openai.com", "api_key": ""},
        )
        assert response.status_code == 200
        data = response.json()

        assert data["success"] is True
        assert calls["headers"]["Authorization"] == "Bearer saved-valid-secret"


@pytest.mark.asyncio
async def test_execution_layer_resolves_chat_endpoint_from_base_url():
    """
    执行层应将保存的基础 URL 转换为聊天调用地址。
    """
    execution_layer = ExecutionLayer()
    execution_layer.provider_api_key_fields["openai"] = "OPENAI_API_KEY"

    db = SimpleNamespace()
    config = SimpleNamespace(
        provider="openai",
        model="gpt-4o-mini",
        api_key="secret",
        api_endpoint="https://api.openai.com",
    )

    import billing.pricing_manager as pricing_manager_module

    original_pricing_manager = pricing_manager_module.PricingManager

    class MockPricingManager:
        def __init__(self, session):
            self.session = session

        @staticmethod
        def normalize_provider(provider):
            return original_pricing_manager.normalize_provider(provider)

        @staticmethod
        def _normalize_provider_api_endpoint(provider, api_endpoint):
            return original_pricing_manager._normalize_provider_api_endpoint(provider, api_endpoint)

        @staticmethod
        def get_provider_endpoint_suffixes(provider):
            return original_pricing_manager.get_provider_endpoint_suffixes(provider)

        @staticmethod
        def build_provider_api_endpoint(provider, base_url, purpose):
            return original_pricing_manager.build_provider_api_endpoint(provider, base_url, purpose)

        @staticmethod
        def get_provider_base_suffix(provider):
            return original_pricing_manager.get_provider_base_suffix(provider)

        def get_configuration_by_provider_model(self, provider, model):
            return config

        def get_default_configuration(self):
            return config

    pricing_manager_module.PricingManager = MockPricingManager
    try:
        resolved = execution_layer._resolve_llm_configuration({
            "provider": "openai",
            "model": "gpt-4o-mini",
            "db": db,
        })
    finally:
        pricing_manager_module.PricingManager = original_pricing_manager

    assert resolved["ok"] is True
    assert resolved["api_endpoint"] == "https://api.openai.com/v1/chat/completions"
    assert resolved["api_key"] == "secret"


@pytest.mark.asyncio
async def test_execution_layer_resolves_custom_model_to_selected_deepseek_model():
    """
    provider 级配置使用 custom-model 时，应从 selected_models 选择有效模型（DeepSeek 优先 deepseek-chat）。
    """
    execution_layer = ExecutionLayer()
    execution_layer.provider_api_key_fields["deepseek"] = "DEEPSEEK_API_KEY"

    db = SimpleNamespace()
    config = SimpleNamespace(
        provider="deepseek",
        model="custom-model",
        selected_models='["deepseek-reasoner","deepseek-chat"]',
        api_key="secret",
        api_endpoint="https://api.deepseek.com/v1",
        # no max_tokens
    )

    import billing.pricing_manager as pricing_manager_module

    original_pricing_manager = pricing_manager_module.PricingManager

    class MockPricingManager:
        def __init__(self, session):
            self.session = session

        @staticmethod
        def normalize_provider(provider):
            return original_pricing_manager.normalize_provider(provider)

        @staticmethod
        def _normalize_provider_api_endpoint(provider, api_endpoint):
            return original_pricing_manager._normalize_provider_api_endpoint(provider, api_endpoint)

        @staticmethod
        def get_provider_endpoint_suffixes(provider):
            return original_pricing_manager.get_provider_endpoint_suffixes(provider)

        @staticmethod
        def build_provider_api_endpoint(provider, base_url, purpose):
            return original_pricing_manager.build_provider_api_endpoint(provider, base_url, purpose)

        @staticmethod
        def get_provider_base_suffix(provider):
            return original_pricing_manager.get_provider_base_suffix(provider)

        @staticmethod
        def parse_selected_models(selected_models):
            return original_pricing_manager.parse_selected_models(selected_models)

        def get_configuration_by_provider_model(self, provider, model):
            return config

        def get_default_configuration(self):
            return config

    pricing_manager_module.PricingManager = MockPricingManager
    try:
        resolved = execution_layer._resolve_llm_configuration({
            "provider": "deepseek",
            "model": "custom-model",
            "db": db,
        })
    finally:
        pricing_manager_module.PricingManager = original_pricing_manager

    assert resolved["ok"] is True
    assert resolved["model"] == "deepseek-chat"
    assert resolved["api_endpoint"] == "https://api.deepseek.com/v1/chat/completions"


@pytest.mark.asyncio
async def test_execution_layer_uses_provider_level_credentials_for_selected_model():
    """
    聊天页传入 selected_models 中的真实模型名时，应回退到 provider 级配置读取凭证。
    """
    execution_layer = ExecutionLayer()
    execution_layer.provider_api_key_fields["deepseek"] = "DEEPSEEK_API_KEY"

    db = SimpleNamespace()
    config = SimpleNamespace(
        provider="deepseek",
        model="custom-model",
        selected_models='["deepseek-v4-flash","deepseek-v4-pro"]',
        api_key="secret",
        api_endpoint="https://api.deepseek.com/v1",
    )

    import billing.pricing_manager as pricing_manager_module

    original_pricing_manager = pricing_manager_module.PricingManager

    class MockPricingManager:
        def __init__(self, session):
            self.session = session

        @staticmethod
        def normalize_provider(provider):
            return original_pricing_manager.normalize_provider(provider)

        @staticmethod
        def _normalize_provider_api_endpoint(provider, api_endpoint):
            return original_pricing_manager._normalize_provider_api_endpoint(provider, api_endpoint)

        @staticmethod
        def get_provider_endpoint_suffixes(provider):
            return original_pricing_manager.get_provider_endpoint_suffixes(provider)

        @staticmethod
        def build_provider_api_endpoint(provider, base_url, purpose):
            return original_pricing_manager.build_provider_api_endpoint(provider, base_url, purpose)

        @staticmethod
        def get_provider_base_suffix(provider):
            return original_pricing_manager.get_provider_base_suffix(provider)

        @staticmethod
        def parse_selected_models(selected_models):
            return original_pricing_manager.parse_selected_models(selected_models)

        def get_configuration_by_provider_model(self, provider, model):
            return None

        def get_default_provider_configuration(self, provider):
            return config

        def get_default_configuration(self):
            return None

    pricing_manager_module.PricingManager = MockPricingManager
    try:
        resolved = execution_layer._resolve_llm_configuration({
            "provider": "deepseek",
            "model": "deepseek-v4-flash",
            "db": db,
        })
    finally:
        pricing_manager_module.PricingManager = original_pricing_manager

    assert resolved["ok"] is True
    assert resolved["model"] == "deepseek-v4-flash"
    assert resolved["api_key"] == "secret"
    assert resolved["api_endpoint"] == "https://api.deepseek.com/v1/chat/completions"


def test_build_provider_request_for_openai_compatible_excludes_metadata_payload():
    """
    OpenAI 兼容接口（含 DeepSeek）不应注入 metadata，避免上游 400。
    """
    spec = build_provider_request(
        provider="deepseek",
        api_endpoint="https://api.deepseek.com/v1",
        api_key="test-key",
        purpose="chat",
        model="deepseek-chat",
        prompt="hello",
        # no max_tokens
        request_id="rid-1",
        client_version="test-client",
        context={"channel": "weixin"},
    )
    assert spec.endpoint.endswith("/chat/completions")
    assert "metadata" not in spec.payload
    assert spec.payload["model"] == "deepseek-chat"
    assert spec.payload["messages"][0]["content"] == "hello"
