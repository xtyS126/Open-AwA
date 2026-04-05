"""
聚焦验证模型服务协议适配、版本协商、重试、幂等与 WebSocket 分段行为。
这些测试直接覆盖本次修复最容易回归的关键链路。
"""

from types import MethodType, SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from api.routes import chat as chat_route
from billing.pricing_manager import PricingManager
from core.executor import ExecutionLayer
from core.model_service import build_provider_request
from main import app


def test_pricing_manager_normalizes_provider_specific_base_suffix():
    """
    保存配置时应保留 Provider 自己的基础路径，而不是一律补 `/v1`。
    """

    normalized_alibaba = PricingManager._normalize_provider_api_endpoint(
        "alibaba",
        "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
    )
    normalized_zhipu = PricingManager._normalize_provider_api_endpoint(
        "zhipu",
        "https://open.bigmodel.cn/api/paas/v4/chat/completions",
    )

    assert normalized_alibaba == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert normalized_zhipu == "https://open.bigmodel.cn/api/paas/v4"


def test_build_provider_request_generates_provider_specific_headers_and_payload():
    """
    不同 Provider 应生成符合自身协议的端点、请求头和载荷。
    """

    anthropic_request = build_provider_request(
        provider="anthropic",
        api_endpoint="https://api.anthropic.com",
        api_key="anthropic-secret",
        purpose="chat",
        model="claude-3-5-sonnet",
        prompt="你好",
        request_id="req-a",
        client_version="2.0.0",
        context={"scene": "test"},
    )
    google_request = build_provider_request(
        provider="google",
        api_endpoint="https://generativelanguage.googleapis.com",
        api_key="google-secret",
        purpose="chat",
        model="gemini-2.0-flash",
        prompt="你好",
        request_id="req-g",
        client_version="2.0.0",
    )

    assert anthropic_request.endpoint == "https://api.anthropic.com/v1/messages"
    assert anthropic_request.headers["x-api-key"] == "anthropic-secret"
    assert anthropic_request.payload["messages"][0]["content"] == "你好"
    assert anthropic_request.payload["metadata"]["request_id"] == "req-a"

    assert google_request.endpoint.endswith("/v1beta/models/gemini-2.0-flash:generateContent?key=google-secret")
    assert google_request.payload["contents"][0]["parts"][0]["text"] == "你好"
    assert "request_id=req-g" in google_request.payload["systemInstruction"]["parts"][0]["text"]


@pytest.mark.asyncio
async def test_execution_layer_retries_and_forwards_request_headers(monkeypatch):
    """
    模型服务短暂失败时应自动重试，并透传 request_id 与 X-Client-Ver。
    """

    execution_layer = ExecutionLayer()
    calls = []

    class MockResponse:
        def __init__(self, status_code: int, payload: dict, url: str):
            self.status_code = status_code
            self._payload = payload
            self.text = str(payload)
            self.request = httpx.Request("POST", url)

        def raise_for_status(self):
            if self.status_code >= 400:
                raise httpx.HTTPStatusError("upstream failure", request=self.request, response=self)

        def json(self):
            return self._payload

    class MockAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, json=None, headers=None):
            calls.append({"url": url, "json": json, "headers": headers or {}})
            if len(calls) < 3:
                return MockResponse(503, {"error": "busy"}, url)
            return MockResponse(
                200,
                {
                    "choices": [
                        {
                            "message": {
                                "content": "重试成功",
                            }
                        }
                    ]
                },
                url,
            )

    monkeypatch.setattr(httpx, "AsyncClient", MockAsyncClient)

    def mock_resolve(self, context):
        return {
            "ok": True,
            "provider": "openai",
            "model": "gpt-4o-mini",
            "api_endpoint": "https://api.openai.com",
            "api_key": "secret",
            "request_id": "req-llm-1",
            "client_version": "2.3.4",
        }

    execution_layer._resolve_llm_configuration = MethodType(mock_resolve, execution_layer)

    result = await execution_layer._call_llm_api("你好", {"message": "你好"})

    assert result["ok"] is True
    assert result["response"] == "重试成功"
    assert len(calls) == 3
    assert calls[0]["headers"]["X-Request-Id"] == "req-llm-1"
    assert calls[0]["headers"]["X-Client-Ver"] == "2.3.4"
    assert calls[0]["url"] == "https://api.openai.com/v1/chat/completions"


@pytest.mark.asyncio
async def test_execute_step_uses_idempotency_key_cache():
    """
    同一个幂等键重复执行时，应直接复用第一次结果。
    """

    execution_layer = ExecutionLayer()
    call_count = {"value": 0}

    async def mock_execute_command(step):
        call_count["value"] += 1
        return {"status": "completed", "stdout": "ok", "stderr": "", "returncode": 0}

    execution_layer._execute_command = mock_execute_command
    step = {
        "action": "execute_command",
        "command": "echo ok",
        "idempotency_key": "tool-key-1",
    }
    context = {"session_id": "s1", "user_id": "u1"}

    first_result = await execution_layer.execute_step(step, context)
    second_result = await execution_layer.execute_step(step, context)

    assert first_result["status"] == "completed"
    assert second_result["status"] == "completed"
    assert second_result["idempotent_replay"] is True
    assert call_count["value"] == 1


def test_http_version_headers_and_metrics_route():
    """
    HTTP 响应应返回版本协商头，指标端点应导出 Prometheus 文本。
    """

    with TestClient(app) as client:
        health_response = client.get("/health", headers={"X-Client-Ver": "1.0.0"})
        metrics_response = client.get("/metrics")

    assert health_response.status_code == 200
    assert health_response.headers["X-Server-Ver"] == "1.0.0"
    assert health_response.headers["X-Version-Status"] == "compatible"
    assert health_response.headers["X-Client-Ver"] == "1.0.0"

    assert metrics_response.status_code == 200
    assert "openawa_model_service_requests_total" in metrics_response.text
    assert "openawa_websocket_messages_total" in metrics_response.text
    assert "openawa_tool_execution_total" in metrics_response.text


def test_websocket_sends_chunked_messages_with_seq_and_checksum(monkeypatch):
    """
    WebSocket 响应应先发送分段消息，再发送兼容旧协议的完整消息。
    """

    fake_user = SimpleNamespace(id="user-1", username="tester")

    class FakeQuery:
        def filter(self, *args, **kwargs):
            return self

        def first(self):
            return fake_user

    class FakeSession:
        def query(self, *args, **kwargs):
            return FakeQuery()

        def close(self):
            return None

    async def mock_process(self, user_input, context):
        return {
            "status": "completed",
            "response": "A" * 2500,
            "results": [{"ok": True}],
        }

    monkeypatch.setattr(chat_route, "decode_access_token", lambda token: {"sub": "tester"})
    monkeypatch.setattr(chat_route, "SessionLocal", lambda: FakeSession())
    monkeypatch.setattr(chat_route.AIAgent, "process", mock_process)

    with TestClient(app) as client:
        with client.websocket_connect(
            "/api/chat/ws/session-1?token=fake-token",
            headers={"X-Request-Id": "req-ws-1", "X-Client-Ver": "1.0.0"},
        ) as websocket:
            websocket.send_json(
                {
                    "type": "message",
                    "content": "你好",
                    "request_id": "req-ws-1",
                }
            )
            first_message = websocket.receive_json()
            second_message = None
            while second_message is None or second_message.get("type") != "response":
                second_message = websocket.receive_json()

    assert first_message["type"] == "response_chunk"
    assert first_message["seq"] == 1
    assert first_message["total"] >= 2
    assert len(first_message["checksum"]) == 64

    assert second_message["type"] == "response"
    assert second_message["request_id"] == "req-ws-1"
    assert second_message["chunks_total"] >= 2
    assert second_message["checksum"] == first_message["checksum"]
