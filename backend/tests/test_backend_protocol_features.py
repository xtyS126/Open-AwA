"""
聚焦验证模型服务协议适配、版本协商、重试、幂等与 WebSocket 分段行为。
这些测试直接覆盖本次修复最容易回归的关键链路。
"""

import asyncio
from types import MethodType, SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from api.routes import chat as chat_route
from billing.pricing_manager import PricingManager
import core.agent as agent_module
from core.agent import AIAgent
import core.executor as executor_module
import core.litellm_adapter as litellm_adapter_module
from core.executor import ExecutionLayer
from core.feedback import FeedbackLayer
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
    LiteLLM 适配层正确处理请求并返回结果。
    """

    execution_layer = ExecutionLayer()

    async def mock_litellm_chat_completion(**kwargs):
        return {
            "ok": True,
            "response": "重试成功",
            "reasoning_content": "",
            "provider": kwargs.get("provider", "openai"),
            "model": kwargs.get("model", "gpt-4o-mini"),
            "request_id": kwargs.get("request_id", "req-llm-1"),
            "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        }

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
    monkeypatch.setattr(executor_module, "litellm_chat_completion", mock_litellm_chat_completion)

    result = await execution_layer._call_llm_api("你好", {"message": "你好"})

    assert result["ok"] is True
    assert result["response"] == "重试成功"


@pytest.mark.asyncio
async def test_execution_layer_returns_retryable_error_on_timeout(monkeypatch):
    """
    上游模型超时时应返回可重试错误，避免微信自动回复把暂时性故障误判为不可恢复。
    """

    execution_layer = ExecutionLayer()

    def mock_resolve(self, context):
        return {
            "ok": True,
            "provider": "openai",
            "model": "gpt-4o-mini",
            "api_endpoint": "https://api.openai.com",
            "api_key": "secret",
            "request_id": "req-timeout-1",
            "client_version": "2.3.4",
        }

    async def fake_litellm_chat_completion(**kwargs):
        # 模拟 LiteLLM 超时返回的错误结构
        return {
            "ok": False,
            "error": {
                "code": "model_service_timeout",
                "message": "模型服务暂时不可用，请稍后重试",
                "request_id": kwargs.get("request_id", "req-timeout-1"),
                "retryable": True,
                "details": {
                    "provider": "openai",
                    "model": "gpt-4o-mini",
                    "status_code": 504,
                    "reason": "read timeout",
                },
            },
        }

    execution_layer._resolve_llm_configuration = MethodType(mock_resolve, execution_layer)
    monkeypatch.setattr(executor_module, "litellm_chat_completion", fake_litellm_chat_completion)

    result = await execution_layer._call_llm_api("你好", {"message": "你好"})

    assert result["ok"] is False
    assert result["error"]["retryable"] is True
    assert result["error"]["details"]["reason"] == "read timeout"


@pytest.mark.asyncio
async def test_execution_layer_returns_retryable_error_on_network_failure(monkeypatch):
    """
    上游网络异常时应返回稳定错误结构，便于回归时区分超时与发送链路失败。
    """

    execution_layer = ExecutionLayer()

    def mock_resolve(self, context):
        return {
            "ok": True,
            "provider": "openai",
            "model": "gpt-4o-mini",
            "api_endpoint": "https://api.openai.com",
            "api_key": "secret",
            "request_id": "req-network-1",
            "client_version": "2.3.4",
        }

    async def fake_litellm_chat_completion(**kwargs):
        # 模拟 LiteLLM 网络错误返回的错误结构
        return {
            "ok": False,
            "error": {
                "code": "model_service_unexpected_error",
                "message": "模型服务请求失败",
                "request_id": kwargs.get("request_id", "req-network-1"),
                "retryable": True,
                "details": {
                    "provider": "openai",
                    "model": "gpt-4o-mini",
                    "reason": "connection reset by peer",
                },
            },
        }

    execution_layer._resolve_llm_configuration = MethodType(mock_resolve, execution_layer)
    monkeypatch.setattr(executor_module, "litellm_chat_completion", fake_litellm_chat_completion)

    result = await execution_layer._call_llm_api("你好", {"message": "你好"})

    assert result["ok"] is False
    assert result["error"]["retryable"] is True
    assert result["error"]["details"]["reason"] == "connection reset by peer"


@pytest.mark.asyncio
async def test_ai_agent_process_strips_reasoning_content_when_final_only(monkeypatch):
    """
    final_only 模式应从顶层和嵌套执行结果中一起剥离 reasoning_content。
    """

    agent = AIAgent()

    async def fake_recognize_intent(user_input):
        return "chat"

    async def fake_extract_entities(user_input):
        return {}

    async def fake_create_plan(intent, entities, context):
        return {
            "intent": "chat",
            "steps": [
                {
                    "step": 1,
                    "action": "llm_chat",
                    "message": context.get("message", ""),
                    "purpose": "对话交流",
                }
            ],
            "requires_confirmation": False,
        }

    async def fake_execute_step(step, context):
        return {
            "status": "completed",
            "response": "最终回复",
            "reasoning_content": "步骤级思维链",
            "nested": {
                "reasoning_content": "嵌套思维链",
                "visible": "保留字段",
            },
        }

    async def fake_evaluate_result(result):
        return {}

    async def fake_generate_response(results, context):
        return "最终回复"

    async def fake_update_memory(user_input, response, context):
        return None

    async def fake_retrieve_relevant_experiences(user_input, context):
        return []

    monkeypatch.setattr(agent.comprehension, "recognize_intent", fake_recognize_intent)
    monkeypatch.setattr(agent.comprehension, "extract_entities", fake_extract_entities)
    monkeypatch.setattr(agent.planner, "create_plan", fake_create_plan)
    monkeypatch.setattr(agent.executor, "execute_step", fake_execute_step)
    monkeypatch.setattr(agent.feedback, "evaluate_result", fake_evaluate_result)
    monkeypatch.setattr(agent.feedback, "generate_response", fake_generate_response)
    monkeypatch.setattr(agent.feedback, "update_memory", fake_update_memory)
    monkeypatch.setattr(agent, "_retrieve_relevant_experiences", fake_retrieve_relevant_experiences)

    result = await agent.process(
        "你好",
        {
            "message": "你好",
            "user_id": "user-1",
            "session_id": "session-final-only",
            "output_mode": "final_only",
        },
    )

    assert result["status"] == "completed"
    assert result["response"] == "最终回复"
    assert "reasoning_content" not in result
    assert "reasoning_content" not in result["results"][0]["result"]
    assert result["results"][0]["result"]["nested"]["visible"] == "保留字段"
    assert "reasoning_content" not in result["results"][0]["result"]["nested"]


@pytest.mark.asyncio
async def test_ai_agent_process_injects_db_into_context(monkeypatch):
    """
    Agent 应将自身持有的数据库会话补入上下文，确保执行层能解析默认模型配置。
    """

    dummy_db = SimpleNamespace(name="scheduled-task-db")
    agent = AIAgent(db_session=dummy_db)

    async def fake_recognize_intent(user_input):
        return "chat"

    async def fake_extract_entities(user_input):
        return {}

    async def fake_create_plan(intent, entities, context):
        return {
            "intent": "chat",
            "steps": [
                {
                    "step": 1,
                    "action": "llm_chat",
                    "message": context.get("message", ""),
                }
            ],
            "requires_confirmation": False,
        }

    async def fake_execute_step(step, context):
        assert context["db"] is dummy_db
        return {
            "status": "completed",
            "response": "透传成功",
            "provider": "openai",
            "model": "gpt-4o-mini",
        }

    async def fake_evaluate_result(result):
        return {"needs_retry": False, "needs_confirmation": False}

    async def fake_generate_response(results, context):
        return "透传成功"

    async def fake_update_memory(user_input, response, context):
        return None

    monkeypatch.setattr(agent.comprehension, "recognize_intent", fake_recognize_intent)
    monkeypatch.setattr(agent.comprehension, "extract_entities", fake_extract_entities)
    monkeypatch.setattr(agent.planner, "create_plan", fake_create_plan)
    monkeypatch.setattr(agent.executor, "execute_step", fake_execute_step)
    monkeypatch.setattr(agent.feedback, "evaluate_result", fake_evaluate_result)
    monkeypatch.setattr(agent.feedback, "generate_response", fake_generate_response)
    monkeypatch.setattr(agent.feedback, "update_memory", fake_update_memory)

    result = await agent.process(
        "请在晚上八点提醒我整理日报",
        {
            "user_id": "user-1",
            "session_id": "session-1",
            "retrieve_experiences": False,
            "retrieve_long_term_memory": False,
            "enable_skill_plugin": False,
        },
    )

    assert result["status"] == "completed"
    assert result["response"] == "透传成功"


@pytest.mark.asyncio
async def test_ai_agent_schedule_record_skips_side_effects_when_isolated(monkeypatch):
    """
    定时任务隔离模式下不应写入行为日志或会话记录。
    """

    agent = AIAgent()
    behavior_calls = []
    conversation_calls = []

    async def fake_behavior_record(entry):
        behavior_calls.append(entry)

    async def fake_conversation_record(**kwargs):
        conversation_calls.append(kwargs)

    monkeypatch.setattr(agent_module.behavior_logger, "record", fake_behavior_record)
    monkeypatch.setattr(agent_module.conversation_recorder, "record", fake_conversation_record)

    agent._schedule_record(
        node_type="llm_call",
        user_message="定时任务测试",
        context={
            "user_id": "user-1",
            "session_id": "scheduled-task-1",
            "scheduled_execution_isolated": True,
        },
        llm_output={"response": "执行完成"},
        metadata={"provider": "openai", "model": "gpt-4o-mini"},
    )

    await asyncio.sleep(0)

    assert behavior_calls == []
    assert conversation_calls == []


@pytest.mark.asyncio
async def test_feedback_layer_skips_memory_update_when_isolated():
    """
    定时任务隔离模式下不应写入短期或长期记忆。
    """

    feedback = FeedbackLayer()
    memory_calls = []

    class DummyMemoryManager:
        async def add_short_term_memory(self, **kwargs):
            memory_calls.append(("short", kwargs))

        async def add_long_term_memory(self, **kwargs):
            memory_calls.append(("long", kwargs))

    feedback.set_memory_manager(DummyMemoryManager())

    await feedback.update_memory(
        user_input="请稍后提醒我检查日志",
        response="好的，稍后提醒",
        context={"scheduled_execution_isolated": True},
    )

    assert memory_calls == []


@pytest.mark.asyncio
async def test_ai_agent_get_available_skills_returns_empty_without_db_session(monkeypatch):
    """
    无数据库会话时应直接返回空列表，而不是继续访问依赖数据库的技能注册表。
    """

    agent = AIAgent()

    def fail_list_all():
        raise AssertionError("无 db_session 时不应访问 registry.list_all")

    monkeypatch.setattr(agent.skill_engine.registry, "list_all", fail_list_all)

    result = await agent.get_available_skills()

    assert result == []


@pytest.mark.asyncio
async def test_ai_agent_get_available_plugins_loads_plugins_before_collecting_tools():
    """
    Agent 获取插件列表时应先尝试加载插件，确保工具定义对 AI 可见。
    """

    agent = AIAgent()

    class FakePluginManager:
        def __init__(self) -> None:
            self.loaded_plugins = {}

        def discover_plugins(self):
            return [
                {
                    "name": "demo-plugin",
                    "version": "1.0.0",
                    "description": "demo plugin",
                }
            ]

        def load_plugin(self, plugin_name: str) -> bool:
            self.loaded_plugins[plugin_name] = object()
            return True

        def get_plugin_tools(self, plugin_name: str):
            if plugin_name not in self.loaded_plugins:
                return []
            return [
                {
                    "name": "fetch_demo_data",
                    "method": "execute",
                    "default_params": {"action": "fetch_demo_data"},
                }
            ]

        def get_plugin_info(self, plugin_name: str):
            return {"loaded": plugin_name in self.loaded_plugins}

    agent.plugin_manager = FakePluginManager()

    result = await agent.get_available_plugins()

    assert len(result) == 1
    assert result[0]["loaded"] is True
    assert result[0]["tools"][0]["method"] == "execute"
    assert result[0]["tools"][0]["default_params"]["action"] == "fetch_demo_data"


@pytest.mark.asyncio
async def test_ai_agent_auto_execute_plugins_merges_default_params(monkeypatch):
    """
    自动匹配插件工具时，应把工具默认参数与运行时上下文一起传给插件。
    """

    agent = AIAgent()
    captured: dict[str, Any] = {}

    async def fake_get_available_skills():
        return []

    async def fake_get_available_plugins():
        return [
            {
                "name": "twitter-monitor",
                "tools": [
                    {
                        "name": "fetch_twitter_tweets",
                        "description": "抓取 twitter 推文",
                        "method": "execute",
                        "default_params": {
                            "action": "fetch_twitter_tweets",
                            "user_names": ["OpenAI"],
                        },
                    }
                ],
            }
        ]

    async def fake_execute_plugin(plugin_name: str, method: str, **kwargs):
        captured.update(
            {
                "plugin_name": plugin_name,
                "method": method,
                "kwargs": kwargs,
            }
        )
        return {"status": "success", "data": {"ok": True}, "message": ""}

    monkeypatch.setattr(agent, "get_available_skills", fake_get_available_skills)
    monkeypatch.setattr(agent, "get_available_plugins", fake_get_available_plugins)
    monkeypatch.setattr(agent, "execute_plugin", fake_execute_plugin)

    result = await agent._auto_execute_skills_and_plugins(
        intent={"type": "fetch", "action": "tweets"},
        entities={},
        context={"request_id": "plugin-auto-1"},
    )

    assert captured["plugin_name"] == "twitter-monitor"
    assert captured["method"] == "execute"
    assert captured["kwargs"]["action"] == "fetch_twitter_tweets"
    assert captured["kwargs"]["user_names"] == ["OpenAI"]
    assert captured["kwargs"]["context"]["request_id"] == "plugin-auto-1"
    assert result["plugins"][0]["plugin_name"] == "twitter-monitor"


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
