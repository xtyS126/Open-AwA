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

    from plugins.plugin_manager import PluginManager
    original_execute = PluginManager.execute_plugin_async
    async def fake_execute(self, plugin_name, method, **kwargs):
        fake_manager.executions.append((plugin_name, method, kwargs))
        return {
            "status": "success",
            "message": "调用成功",
            "data": {
                "user_name": kwargs.get("user_name"),
                "followers": 123,
            },
        }
    monkeypatch.setattr(PluginManager, "execute_plugin_async", fake_execute)

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
    captured_messages = {"value": []}

    async def fake_litellm_chat_completion(**kwargs):
        call_index["value"] += 1
        if call_index["value"] == 1:
            assert kwargs.get("tools")
            return {
                "ok": True,
                "response": "我先调用工具查询一下。",
                "reasoning_content": "需要先拿到实时账号信息再总结。",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "plugin_twitter-monitor__get_twitter_user_info",
                            "arguments": '{"user_name": "openai"}',
                        },
                    }
                ],
                "usage": None,
            }

        captured_messages["value"] = kwargs.get("messages", [])
        assert any(message.get("role") == "tool" for message in captured_messages["value"])
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
            "_tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "plugin_twitter-monitor__get_twitter_user_info",
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
                    },
                }
            ],
        },
    )

    assert result["ok"] is True
    assert result["response"] == "OpenAI 的账号信息已经获取完成。"
    assert fake_manager.executions == [
        ("twitter-monitor", "get_twitter_user_info", {"user_name": "openai"})
    ]
    assert result["tool_events"][0]["name"] == "plugin_twitter-monitor__get_twitter_user_info"
    assistant_index = next(
        index for index, message in enumerate(captured_messages["value"])
        if message.get("role") == "assistant" and message.get("tool_calls")
    )
    tool_index = next(
        index for index, message in enumerate(captured_messages["value"])
        if message.get("role") == "tool"
    )
    assert assistant_index < tool_index
    assert captured_messages["value"][assistant_index]["reasoning_content"] == "需要先拿到实时账号信息再总结。"
    monkeypatch.setattr(PluginManager, "execute_plugin_async", original_execute)


@pytest.mark.asyncio
async def test_call_llm_api_stream_handles_pseudo_json_tool_call(monkeypatch):
    """流式 _call_llm_api_stream 应透传 tool_calls 事件并正常返回内容。"""

    execution_layer = ExecutionLayer()

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

    async def fake_litellm_chat_completion_stream(**kwargs):
        call_index["value"] += 1
        if call_index["value"] == 1:
            assert kwargs.get("tools")
            yield {
                    "type": "tool_calls",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "plugin_twitter-monitor__get_twitter_user_info",
                                "arguments": '{"user_name": "openai"}',
                            },
                        }
                    ],
                }
            return

        async for c in _generate_content_chunks("OpenAI 的账号信息如下：followers=123。"):
            yield c

    async def _generate_content_chunks(text: str):
        yield {"content": text, "reasoning_content": ""}

    monkeypatch.setattr(executor_module, "litellm_chat_completion_stream", fake_litellm_chat_completion_stream)

    chunks = []
    async for chunk in execution_layer._call_llm_api_stream(
        "查询 OpenAI 的 Twitter 账号信息",
        {
            "message": "查询 OpenAI 的 Twitter 账号信息",
            "username": "tester",
            "enable_skill_plugin": True,
            "_tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "plugin_twitter-monitor__get_twitter_user_info",
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
                    },
                }
            ],
        },
    ):
        chunks.append(chunk)

    tool_chunks = [chunk for chunk in chunks if chunk.get("type") == "tool_calls"]
    content_chunks = [chunk for chunk in chunks if chunk.get("content")]

    assert len(tool_chunks) == 1
    assert len(content_chunks) == 0
