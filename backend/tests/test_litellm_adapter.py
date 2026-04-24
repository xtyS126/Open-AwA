"""
LiteLLM 统一适配层的单元测试。
覆盖模型名构建、错误映射、非流式调用、流式调用和模型列表接口。
"""

import pytest

from core.litellm_adapter import (
    build_litellm_model_name,
    check_litellm_available,
    is_litellm_available,
    _build_litellm_optional_params,
    _map_litellm_error,
    litellm_chat_completion,
    litellm_chat_completion_stream,
    litellm_list_models,
    litellm_check_provider_connection,
    PROVIDER_MODEL_PREFIX_MAP,
    STATUS_CODE_ERROR_MAP,
    RETRYABLE_STATUS_CODES,
)


class TestBuildLitellmModelName:
    """模型名构建测试。"""

    def test_openai_model_gets_prefix(self):
        assert build_litellm_model_name("openai", "gpt-4o-mini") == "openai/gpt-4o-mini"

    def test_anthropic_model_gets_prefix(self):
        assert build_litellm_model_name("anthropic", "claude-3-5-sonnet") == "anthropic/claude-3-5-sonnet"

    def test_deepseek_model_gets_prefix(self):
        assert build_litellm_model_name("deepseek", "deepseek-chat") == "deepseek/deepseek-chat"

    def test_google_model_gets_gemini_prefix(self):
        assert build_litellm_model_name("google", "gemini-pro") == "gemini/gemini-pro"

    def test_ollama_model_gets_prefix(self):
        assert build_litellm_model_name("ollama", "llama3") == "ollama/llama3"

    def test_alibaba_model_gets_openai_prefix(self):
        assert build_litellm_model_name("alibaba", "qwen-turbo") == "openai/qwen-turbo"

    def test_model_with_existing_slash_not_duplicated(self):
        """已包含路径分隔符的模型名不应重复添加前缀。"""
        assert build_litellm_model_name("openai", "openai/gpt-4o") == "openai/gpt-4o"

    def test_empty_model_returns_empty(self):
        assert build_litellm_model_name("openai", "") == ""

    def test_unknown_provider_defaults_to_openai_prefix(self):
        assert build_litellm_model_name("unknown-provider", "some-model") == "openai/some-model"

    def test_case_insensitive_provider(self):
        assert build_litellm_model_name("OpenAI", "gpt-4o") == "openai/gpt-4o"


class TestBuildOptionalParams:
    """可选参数构建测试。"""

    def test_defaults(self):
        params = _build_litellm_optional_params(max_tokens=4096)
        assert params["max_tokens"] == 4096
        assert params["stream"] is False
        assert "temperature" not in params
        assert "top_p" not in params

    def test_with_temperature(self):
        params = _build_litellm_optional_params(temperature=0.7, max_tokens=1024)
        assert params["temperature"] == 0.7

    def test_with_top_p(self):
        params = _build_litellm_optional_params(top_p=0.9, max_tokens=1024)
        assert params["top_p"] == 0.9

    def test_stream_mode(self):
        params = _build_litellm_optional_params(max_tokens=1024, stream=True)
        assert params["stream"] is True


class TestMapLitellmError:
    """错误映射测试。"""

    def test_auth_error_maps_to_401(self):
        exc = Exception("auth failed")
        exc.status_code = 401
        error = _map_litellm_error(exc, provider="openai", model="gpt-4o")
        assert error["code"] == "model_service_auth_error"
        assert error["retryable"] is False

    def test_rate_limit_maps_to_retryable(self):
        exc = Exception("rate limit exceeded")
        exc.status_code = 429
        error = _map_litellm_error(exc, provider="openai", model="gpt-4o")
        assert error["code"] == "model_service_rate_limit"
        assert error["retryable"] is True

    def test_timeout_maps_to_retryable(self):
        exc = Exception("gateway timeout")
        exc.status_code = 504
        error = _map_litellm_error(exc, provider="openai", model="gpt-4o")
        assert error["code"] == "model_service_timeout"
        assert error["retryable"] is True

    def test_unknown_error_without_status_code(self):
        exc = Exception("unknown error")
        error = _map_litellm_error(exc, provider="openai", model="gpt-4o")
        assert error["code"] == "model_service_unexpected_error"
        assert error["retryable"] is False

    def test_not_found_error(self):
        exc = Exception("model not found")
        exc.status_code = 404
        error = _map_litellm_error(exc, provider="openai", model="gpt-4o")
        assert error["code"] == "model_service_model_not_found"

    def test_request_id_propagated(self):
        exc = Exception("error")
        exc.status_code = 500
        error = _map_litellm_error(exc, provider="openai", model="gpt-4o", request_id="req-123")
        assert error["request_id"] == "req-123"


class TestLitellmAvailability:
    """LiteLLM 依赖检测测试。"""

    def test_is_available(self):
        assert is_litellm_available() is True

    def test_check_available_does_not_raise(self):
        check_litellm_available()


@pytest.mark.asyncio
async def test_litellm_chat_completion_success(monkeypatch):
    """非流式调用成功路径。"""

    class MockChoice:
        class MockMessage:
            content = "模型回复内容"
            reasoning_content = "推理过程"
        message = MockMessage()

    class MockUsage:
        prompt_tokens = 10
        completion_tokens = 20
        total_tokens = 30

    class MockResponse:
        choices = [MockChoice()]
        usage = MockUsage()

    async def mock_acompletion(**kwargs):
        return MockResponse()

    import litellm
    monkeypatch.setattr(litellm, "acompletion", mock_acompletion)

    result = await litellm_chat_completion(
        provider="openai",
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "你好"}],
        api_key="test-key",
    )

    assert result["ok"] is True
    assert result["response"] == "模型回复内容"
    assert result["reasoning_content"] == "推理过程"
    assert result["usage"]["total_tokens"] == 30
    assert result["provider"] == "openai"
    assert result["model"] == "gpt-4o-mini"


@pytest.mark.asyncio
async def test_litellm_chat_completion_returns_tool_calls(monkeypatch):
    """非流式响应中包含 tool_calls 时应正确透传。"""

    class MockFunction:
        name = "get_weather"
        arguments = '{"location":"Paris"}'

    class MockToolCall:
        id = "call_1"
        function = MockFunction()

    class MockChoice:
        class MockMessage:
            content = ""
            reasoning_content = ""
            tool_calls = [MockToolCall()]

        message = MockMessage()

    class MockResponse:
        choices = [MockChoice()]
        usage = None

    async def mock_acompletion(**kwargs):
        return MockResponse()

    import litellm
    monkeypatch.setattr(litellm, "acompletion", mock_acompletion)

    result = await litellm_chat_completion(
        provider="openai",
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "帮我查天气"}],
        api_key="test-key",
        tools=[{"type": "function", "function": {"name": "get_weather", "parameters": {"type": "object"}}}],
    )

    assert result["ok"] is True
    assert result["tool_calls"] == [
        {
            "id": "call_1",
            "type": "function",
            "function": {
                "name": "get_weather",
                "arguments": '{"location":"Paris"}',
            },
        }
    ]


@pytest.mark.asyncio
async def test_litellm_chat_completion_empty_response(monkeypatch):
    """模型返回空内容时应标记为失败。"""

    class MockChoice:
        class MockMessage:
            content = ""
            reasoning_content = ""
        message = MockMessage()

    class MockResponse:
        choices = [MockChoice()]
        usage = None

    async def mock_acompletion(**kwargs):
        return MockResponse()

    import litellm
    monkeypatch.setattr(litellm, "acompletion", mock_acompletion)

    result = await litellm_chat_completion(
        provider="openai",
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "你好"}],
        api_key="test-key",
    )

    assert result["ok"] is False
    assert result["error"]["code"] == "model_service_empty_response"


@pytest.mark.asyncio
async def test_litellm_chat_completion_error(monkeypatch):
    """模型服务报错时应返回统一错误结构。"""

    async def mock_acompletion(**kwargs):
        exc = Exception("rate limit exceeded")
        exc.status_code = 429
        raise exc

    import litellm
    monkeypatch.setattr(litellm, "acompletion", mock_acompletion)

    result = await litellm_chat_completion(
        provider="openai",
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "你好"}],
        api_key="test-key",
    )

    assert result["ok"] is False
    assert result["error"]["code"] == "model_service_rate_limit"
    assert result["error"]["retryable"] is True


@pytest.mark.asyncio
async def test_litellm_chat_completion_missing_model():
    """缺少模型名时应返回明确错误。"""
    result = await litellm_chat_completion(
        provider="openai",
        model="",
        messages=[{"role": "user", "content": "你好"}],
        api_key="test-key",
    )
    assert result["ok"] is False
    assert result["error"]["code"] == "llm_model_missing"


@pytest.mark.asyncio
async def test_litellm_stream_completion_success(monkeypatch):
    """流式调用成功路径。"""

    class MockDelta:
        content = "流式"
        reasoning_content = ""

    class MockChoice:
        delta = MockDelta()

    class MockChunk:
        choices = [MockChoice()]

    async def mock_acompletion(**kwargs):
        async def gen():
            yield MockChunk()
        return gen()

    import litellm
    monkeypatch.setattr(litellm, "acompletion", mock_acompletion)

    chunks = []
    async for chunk in litellm_chat_completion_stream(
        provider="openai",
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "你好"}],
        api_key="test-key",
    ):
        chunks.append(chunk)

    assert len(chunks) == 1
    assert chunks[0]["content"] == "流式"


@pytest.mark.asyncio
async def test_litellm_stream_completion_emits_tool_calls(monkeypatch):
    """流式响应中的 tool_calls delta 应聚合为最终事件。"""

    class MockFunction:
        name = "get_weather"
        arguments = '{"location":"Paris"}'

    class MockToolCall:
        index = 0
        id = "call_1"
        function = MockFunction()

    class MockDelta:
        content = ""
        reasoning_content = ""
        tool_calls = [MockToolCall()]

    class MockChoice:
        delta = MockDelta()

    class MockChunk:
        choices = [MockChoice()]

    async def mock_acompletion(**kwargs):
        async def gen():
            yield MockChunk()
        return gen()

    import litellm
    monkeypatch.setattr(litellm, "acompletion", mock_acompletion)

    chunks = []
    async for chunk in litellm_chat_completion_stream(
        provider="openai",
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "帮我查天气"}],
        api_key="test-key",
        tools=[{"type": "function", "function": {"name": "get_weather", "parameters": {"type": "object"}}}],
    ):
        chunks.append(chunk)

    assert chunks == [
        {
            "type": "tool_calls",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "get_weather",
                        "arguments": '{"location":"Paris"}',
                    },
                }
            ],
        }
    ]


@pytest.mark.asyncio
async def test_litellm_stream_completion_error(monkeypatch):
    """流式调用异常时应 yield 错误事件。"""

    async def mock_acompletion(**kwargs):
        exc = Exception("connection refused")
        exc.status_code = 503
        raise exc

    import litellm
    monkeypatch.setattr(litellm, "acompletion", mock_acompletion)

    chunks = []
    async for chunk in litellm_chat_completion_stream(
        provider="openai",
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "你好"}],
        api_key="test-key",
    ):
        chunks.append(chunk)

    assert len(chunks) == 1
    assert "error" in chunks[0]
    assert chunks[0]["error"]["code"] == "model_service_unavailable"


@pytest.mark.asyncio
async def test_litellm_list_models_ollama(monkeypatch):
    """Ollama 模型列表正确走专用发现路径。"""
    import httpx

    class MockResponse:
        status_code = 200
        def raise_for_status(self):
            pass
        def json(self):
            return {"models": [{"name": "llama3", "size": 4000000000}]}

    class MockAsyncClient:
        def __init__(self, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def get(self, url, **kwargs):
            return MockResponse()

    monkeypatch.setattr(httpx, "AsyncClient", MockAsyncClient)

    result = await litellm_list_models(provider="ollama", api_key="")
    assert result["ok"] is True
    assert len(result["models"]) == 1
    assert result["models"][0]["name"] == "llama3"


@pytest.mark.asyncio
async def test_litellm_check_provider_connection_success(monkeypatch):
    """提供商连接检测正常路径。"""
    import core.litellm_adapter as adapter_module

    async def mock_list_models(**kwargs):
        return {"ok": True, "models": [{"id": "gpt-4o"}], "provider": "openai"}

    monkeypatch.setattr(adapter_module, "litellm_list_models", mock_list_models)

    result = await litellm_check_provider_connection(
        provider="openai",
        api_base="https://api.openai.com",
        api_key="test-key",
    )
    assert result["status"] == "connected"


@pytest.mark.asyncio
async def test_litellm_check_provider_connection_auth_error(monkeypatch):
    """提供商认证失败时返回明确状态。"""
    import core.litellm_adapter as adapter_module

    async def mock_list_models(**kwargs):
        return {
            "ok": False,
            "error": {"code": "model_service_auth_error", "message": "认证失败", "status_code": 401},
        }

    monkeypatch.setattr(adapter_module, "litellm_list_models", mock_list_models)

    result = await litellm_check_provider_connection(
        provider="openai",
        api_base="https://api.openai.com",
        api_key="bad-key",
    )
    assert result["status"] == "auth_error"
