"""
验证执行层的模型工具调用闭环。
覆盖真实 tool_calls 与伪 JSON 兼容回环，避免模型输出调用代码后直接截断结束。
"""

from types import MethodType

import pytest

import core.executor as executor_module
from core.executor import ExecutionLayer


class FakePluginManager:
    """最小插件管理器桩对象。"""

    def __init__(self):
        self.loaded_plugins = {}
        self.executions = []

    def discover_plugins(self):
        return [{"name": "twitter-monitor"}]

    def load_plugin(self, plugin_name: str):
        self.loaded_plugins[plugin_name] = object()
        return True

    def get_plugin_tools(self, plugin_name: str):
        return [
            {
                "name": "get_twitter_user_info",
                "method": "get_twitter_user_info",
                "description": "获取指定 Twitter 用户的账号信息",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "user_name": {
                            "type": "string",
                            "description": "目标用户名",
                        }
                    },
                    "required": ["user_name"],
                },
            }
        ]

    async def execute_plugin_async(self, plugin_name: str, method: str, **kwargs):
        self.executions.append((plugin_name, method, kwargs))
        return {
            "status": "success",
            "message": "调用成功",
            "data": {
                "user_name": kwargs.get("user_name"),
                "followers": 123,
            },
        }


@pytest.mark.asyncio
async def test_call_llm_api_executes_real_tool_calls(monkeypatch):
    """支持函数调用的模型应执行 tool_calls 后再生成最终文本。"""

    execution_layer = ExecutionLayer()
    fake_manager = FakePluginManager()
    monkeypatch.setattr(executor_module.plugin_instance, "get", lambda: fake_manager)

    def mock_resolve(self, context):
        return {
            "ok": True,
            "provider": "openai",
            "model": "gpt-4o-mini",
            "api_endpoint": "https://api.openai.com",
            "api_key": "secret",
            "request_id": "req-tool-loop-1",
            "client_version": "1.0.0",
        }

    execution_layer._resolve_llm_configuration = MethodType(mock_resolve, execution_layer)

    call_index = {"value": 0}

    async def fake_litellm_chat_completion(**kwargs):
        call_index["value"] += 1
        if call_index["value"] == 1:
            assert kwargs.get("tools")
            return {
                "ok": True,
                "response": "",
                "reasoning_content": "",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "plugin_twitter_monitor_get_twitter_user_info",
                            "arguments": '{"user_name": "openai"}',
                        },
                    }
                ],
                "usage": None,
            }

        assert any(message.get("role") == "tool" for message in kwargs.get("messages", []))
        return {
            "ok": True,
            "response": "OpenAI 的账号信息已经获取完成。",
            "reasoning_content": "",
            "usage": None,
        }

    monkeypatch.setattr(executor_module, "litellm_chat_completion", fake_litellm_chat_completion)

    result = await execution_layer._call_llm_api(
        "查询 OpenAI 的 Twitter 账号信息",
        {
            "message": "查询 OpenAI 的 Twitter 账号信息",
            "username": "tester",
            "enable_skill_plugin": True,
        },
    )

    assert result["ok"] is True
    assert result["response"] == "OpenAI 的账号信息已经获取完成。"
    assert fake_manager.executions == [
        ("twitter-monitor", "get_twitter_user_info", {"user_name": "openai"})
    ]
    assert result["tool_events"][0]["name"] == "twitter-monitor/get_twitter_user_info"


@pytest.mark.asyncio
async def test_call_llm_api_stream_handles_pseudo_json_tool_call(monkeypatch):
    """不支持函数调用的模型输出伪 JSON 时，应执行工具并继续给出最终回答。"""

    execution_layer = ExecutionLayer()
    fake_manager = FakePluginManager()
    monkeypatch.setattr(executor_module.plugin_instance, "get", lambda: fake_manager)

    def mock_resolve(self, context):
        return {
            "ok": True,
            "provider": "deepseek",
            "model": "deepseek-reasoner",
            "api_endpoint": "https://api.deepseek.com",
            "api_key": "secret",
            "request_id": "req-tool-loop-2",
            "client_version": "1.0.0",
        }

    execution_layer._resolve_llm_configuration = MethodType(mock_resolve, execution_layer)

    call_index = {"value": 0}

    async def fake_litellm_chat_completion(**kwargs):
        call_index["value"] += 1
        if call_index["value"] == 1:
            return {
                "ok": True,
                "response": (
                    "我先调用插件。\n"
                    "```json\n"
                    '{"action": "plugin", "action_input": {"plugin_name": "twitter-monitor", "tool_name": "get_twitter_user_info", "user_name": "openai"}}\n'
                    "```"
                ),
                "reasoning_content": "",
                "usage": None,
            }

        assert any(
            message.get("role") == "system"
            and "平台已识别并执行你上一条消息中的插件调用意图" in str(message.get("content"))
            for message in kwargs.get("messages", [])
        )
        return {
            "ok": True,
            "response": "OpenAI 的账号信息如下：followers=123。",
            "reasoning_content": "",
            "usage": None,
        }

    monkeypatch.setattr(executor_module, "litellm_chat_completion", fake_litellm_chat_completion)

    chunks = []
    async for chunk in execution_layer._call_llm_api_stream(
        "查询 OpenAI 的 Twitter 账号信息",
        {
            "message": "查询 OpenAI 的 Twitter 账号信息",
            "username": "tester",
            "enable_skill_plugin": True,
        },
    ):
        chunks.append(chunk)

    tool_chunks = [chunk for chunk in chunks if chunk.get("type") == "tool"]
    content_chunks = [chunk for chunk in chunks if chunk.get("content")]

    assert len(tool_chunks) == 1
    assert fake_manager.executions == [
        ("twitter-monitor", "get_twitter_user_info", {"user_name": "openai"})
    ]
    assert any("OpenAI 的账号信息如下：followers=123。" in chunk.get("content", "") for chunk in content_chunks)
    assert not any('"action": "plugin"' in chunk.get("content", "") for chunk in content_chunks)