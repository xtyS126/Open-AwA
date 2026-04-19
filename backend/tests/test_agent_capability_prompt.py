"""
验证 Agent 运行态能力摘要会被注入到上下文，并转换为模型可见的系统提示。
这些测试专注于能力声明与提示词拼装，不依赖完整应用启动链路。
"""

from types import MethodType

import pytest

import core.agent as agent_module
import core.executor as executor_module
from core.agent import AIAgent
from core.executor import ExecutionLayer


@pytest.mark.asyncio
async def test_execution_layer_injects_capability_system_prompt(monkeypatch):
    """
    执行层应把 Agent 注入的运行态能力摘要转为 system 消息，避免模型误判自己是纯文本聊天模型。
    """

    execution_layer = ExecutionLayer()
    captured_messages = {}

    def mock_resolve(self, context):
        return {
            "ok": True,
            "provider": "openai",
            "model": "gpt-4o-mini",
            "api_endpoint": "https://api.openai.com",
            "api_key": "secret",
            "request_id": "req-capability-1",
            "client_version": "2.3.4",
        }

    async def fake_litellm_chat_completion(**kwargs):
        captured_messages["messages"] = kwargs.get("messages", [])
        return {
            "ok": True,
            "response": "我会基于当前平台能力回答",
            "reasoning_content": "",
            "provider": kwargs.get("provider", "openai"),
            "model": kwargs.get("model", "gpt-4o-mini"),
            "request_id": kwargs.get("request_id", "req-capability-1"),
            "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        }

    execution_layer._resolve_llm_configuration = MethodType(mock_resolve, execution_layer)
    monkeypatch.setattr(executor_module, "litellm_chat_completion", fake_litellm_chat_completion)

    result = await execution_layer._call_llm_api(
        "你能调用插件和 MCP 吗",
        {
            "message": "你能调用插件和 MCP 吗",
            "agent_capabilities": {
                "skills_enabled": True,
                "plugins_enabled": True,
                "tool_dispatch_mode": "platform_managed",
                "skills": [
                    {
                        "name": "weixin_dispatch",
                        "description": "处理微信消息转发与调度",
                    }
                ],
                "plugins": [
                    {
                        "name": "twitter-monitor",
                        "description": "抓取并整理推文",
                        "loaded": True,
                        "tools": [
                            {
                                "name": "help",
                                "description": "查看插件帮助",
                                "method": "get_help",
                            }
                        ],
                    }
                ],
                "mcp": {
                    "platform_supported": True,
                    "chat_dispatch_enabled": False,
                    "connected_servers": [
                        {
                            "server_id": "server-1",
                            "name": "filesystem",
                            "transport_type": "stdio",
                            "connected": True,
                            "tools_count": 1,
                        }
                    ],
                    "tools": [
                        {
                            "server_id": "server-1",
                            "server_name": "filesystem",
                            "name": "read_file",
                            "description": "读取文件内容",
                        }
                    ],
                },
            },
        },
    )

    assert result["ok"] is True
    messages = captured_messages["messages"]
    assert messages[0]["role"] == "system"
    assert "不要笼统声称自己不能调用 MCP、技能或插件" in messages[0]["content"]
    assert "twitter-monitor" in messages[0]["content"]
    assert "weixin_dispatch" in messages[0]["content"]
    assert "filesystem/read_file" in messages[0]["content"]
    assert messages[-1]["role"] == "user"
    assert messages[-1]["content"] == "你能调用插件和 MCP 吗"


@pytest.mark.asyncio
async def test_ai_agent_process_injects_runtime_capabilities(monkeypatch):
    """
    Agent 在进入最终回答前应把技能、插件和 MCP 摘要注入上下文，供执行层构造能力提示。
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
                }
            ],
            "requires_confirmation": False,
        }

    async def fake_get_available_skills():
        return [
            {
                "name": "weixin_dispatch",
                "description": "处理微信消息",
                "enabled": True,
                "config": {},
            }
        ]

    async def fake_get_available_plugins():
        return [
            {
                "name": "twitter-monitor",
                "description": "抓取推文",
                "loaded": True,
                "tools": [
                    {
                        "name": "help",
                        "description": "查看帮助",
                        "method": "get_help",
                    }
                ],
            }
        ]

    class FakeMCPManager:
        def get_all_servers(self):
            return [
                {
                    "server_id": "server-1",
                    "name": "filesystem",
                    "transport_type": "stdio",
                    "connected": True,
                    "tools_count": 1,
                }
            ]

        async def get_all_tools(self):
            return [
                {
                    "server_id": "server-1",
                    "server_name": "filesystem",
                    "tool": {
                        "name": "read_file",
                        "description": "读取文件内容",
                    },
                }
            ]

    async def fake_execute_step(step, context):
        capabilities = context.get("agent_capabilities")
        assert capabilities is not None
        assert capabilities["skills"][0]["name"] == "weixin_dispatch"
        assert capabilities["plugins"][0]["name"] == "twitter-monitor"
        assert capabilities["plugins"][0]["tools"][0]["name"] == "help"
        assert capabilities["mcp"]["connected_servers"][0]["server_id"] == "server-1"
        assert capabilities["mcp"]["tools"][0]["name"] == "read_file"
        return {
            "status": "completed",
            "response": "能力注入成功",
            "provider": "openai",
            "model": "gpt-4o-mini",
        }

    async def fake_evaluate_result(result):
        return {"needs_retry": False, "needs_confirmation": False}

    async def fake_generate_response(results, context):
        return "能力注入成功"

    async def fake_update_memory(user_input, response, context):
        return None

    monkeypatch.setattr(agent.comprehension, "recognize_intent", fake_recognize_intent)
    monkeypatch.setattr(agent.comprehension, "extract_entities", fake_extract_entities)
    monkeypatch.setattr(agent.planner, "create_plan", fake_create_plan)
    monkeypatch.setattr(agent, "get_available_skills", fake_get_available_skills)
    monkeypatch.setattr(agent, "get_available_plugins", fake_get_available_plugins)
    monkeypatch.setattr(agent_module, "MCPManager", lambda: FakeMCPManager())
    monkeypatch.setattr(agent.executor, "execute_step", fake_execute_step)
    monkeypatch.setattr(agent.feedback, "evaluate_result", fake_evaluate_result)
    monkeypatch.setattr(agent.feedback, "generate_response", fake_generate_response)
    monkeypatch.setattr(agent.feedback, "update_memory", fake_update_memory)

    result = await agent.process(
        "你现在能用什么能力",
        {
            "message": "你现在能用什么能力",
            "user_id": "user-1",
            "session_id": "session-capability-context",
            "retrieve_experiences": False,
            "retrieve_long_term_memory": False,
        },
    )

    assert result["status"] == "completed"
    assert result["response"] == "能力注入成功"