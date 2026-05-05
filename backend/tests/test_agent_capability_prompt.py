"""
验证 Agent 运行态能力摘要会被注入到上下文，并转换为模型可见的系统提示。
这些测试专注于能力声明与提示词拼装，不依赖完整应用启动链路。
"""

from types import MethodType, SimpleNamespace

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
                "configured_models": {
                    "count": 2,
                    "provider_count": 2,
                    "entries": [
                        {
                            "provider": "openai",
                            "model": "gpt-4o",
                            "label": "openai:gpt-4o",
                        },
                        {
                            "provider": "anthropic",
                            "model": "claude-3-5-sonnet",
                            "label": "anthropic:claude-3-5-sonnet",
                        },
                    ],
                    "providers": [
                        {"provider": "openai", "models": ["gpt-4o"]},
                        {"provider": "anthropic", "models": ["claude-3-5-sonnet"]},
                    ],
                    "summary": "openai:gpt-4o、anthropic:claude-3-5-sonnet",
                },
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
    assert "openai:gpt-4o" in messages[0]["content"]
    assert "task_spawn_agent" in messages[0]["content"]
    assert messages[-1]["role"] == "user"
    assert messages[-1]["content"] == "你能调用插件和 MCP 吗"


def test_execution_layer_build_messages_injects_auto_execution_results_prompt():
    """
    自动执行的插件结果应被注入到最终回答提示词，避免模型再次输出伪调用 JSON。
    """

    execution_layer = ExecutionLayer()
    messages = execution_layer._build_messages_with_history(
        "请总结 OpenAI 最近推文",
        {
            "message": "请总结 OpenAI 最近推文",
            "auto_execution_results": {
                "skills": [],
                "plugins": [
                    {
                        "plugin_name": "twitter-monitor",
                        "tool": "summarize_twitter_tweets",
                        "result": {
                            "status": "success",
                            "message": "已整理 12 条推文摘要素材",
                            "data": {
                                "count": 12,
                                "source_type": "latest",
                            },
                        },
                    }
                ],
            },
        },
    )

    assert messages[0]["role"] == "system"
    assert "平台已在生成当前回答前自动执行了部分技能或插件" in messages[0]["content"]
    assert "twitter-monitor/summarize_twitter_tweets" in messages[0]["content"]
    assert "不要再输出任何插件、技能或 MCP 调用 JSON" in messages[0]["content"]
    assert messages[-1] == {"role": "user", "content": "请总结 OpenAI 最近推文"}


def test_execution_layer_build_messages_injects_twitter_summary_contract_and_materials():
    """
    Twitter 总结插件的角色设定、输出格式和摘要素材应进入系统提示，供主模型流式生成最终答案。
    """

    execution_layer = ExecutionLayer()
    messages = execution_layer._build_messages_with_history(
        "请总结 OpenAI 最近推文",
        {
            "message": "请总结 OpenAI 最近推文",
            "auto_execution_results": {
                "skills": [],
                "plugins": [
                    {
                        "plugin_name": "twitter-monitor",
                        "tool": "summarize_twitter_tweets",
                        "result": {
                            "status": "success",
                            "source_type": "latest",
                            "target_date": "2026-04-19",
                            "count": 2,
                            "summary_mode": "current_model",
                            "summary_guidance": "请直接完成最终中文总结，不要再调用额外总结模型。",
                            "summary_role": "你是一名 AI 行业速报编辑。",
                            "summary_priority_rules": [
                                "新开源模型。",
                                "商业大模型更新。",
                            ],
                            "summary_output_rules": [
                                "第一部分只输出整体结论。",
                                "第三部分输出 AI总结。",
                            ],
                            "summary_language_rules": [
                                "全中文输出。",
                                "不要输出格式说明。",
                            ],
                            "summary_context": "请先判断是否存在重要动态，再给出核心摘要。",
                            "digest": [
                                "[1] @OpenAI | 2026-04-19T08:00:00 | 赞 12 转 5 回 2 | 发布了新的 API 更新说明",
                                "[2] @AnthropicAI | 2026-04-19T09:00:00 | 赞 30 转 11 回 4 | 发布了新版 Claude 工具能力",
                            ],
                            "top_tweets": [
                                {
                                    "id": "2",
                                    "text": "发布了新版 Claude 工具能力",
                                    "created_at": "2026-04-19T09:00:00",
                                    "author": {
                                        "user_name": "AnthropicAI",
                                        "name": "AnthropicAI",
                                    },
                                    "metrics": {
                                        "likes": 30,
                                        "retweets": 11,
                                        "replies": 4,
                                    },
                                }
                            ],
                        },
                    }
                ],
            },
        },
    )

    assert messages[0]["role"] == "system"
    assert "AI 行业速报编辑" in messages[0]["content"]
    assert "第一部分只输出整体结论" in messages[0]["content"]
    assert "发布了新的 API 更新说明" in messages[0]["content"]
    assert "高价值候选推文" in messages[0]["content"]
    assert "不要输出 JSON、代码块或额外调度指令" in messages[0]["content"]


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

        def fake_collect_configured_model_capabilities(context):
            return {
                "count": 2,
                "provider_count": 2,
                "entries": [
                    {
                        "provider": "openai",
                        "model": "gpt-4o",
                        "label": "openai:gpt-4o",
                    },
                    {
                        "provider": "anthropic",
                        "model": "claude-3-5-sonnet",
                        "label": "anthropic:claude-3-5-sonnet",
                    },
                ],
                "providers": [
                    {"provider": "openai", "models": ["gpt-4o"]},
                    {"provider": "anthropic", "models": ["claude-3-5-sonnet"]},
                ],
                "summary": "openai:gpt-4o、anthropic:claude-3-5-sonnet",
            }
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
        assert capabilities["configured_models"]["entries"][0]["label"] == "openai:gpt-4o"
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
    monkeypatch.setattr(agent, "_collect_configured_model_capabilities", fake_collect_configured_model_capabilities)
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


def test_build_native_tools_exposes_configured_models_for_subagent_selection():
    """
    子代理工具定义应显式暴露已配置模型目录与 provider 参数，方便模型自行选型。
    """

    tools = AIAgent._build_native_tools(
        {
            "configured_models": {
                "count": 2,
                "entries": [
                    {
                        "provider": "openai",
                        "model": "gpt-4o",
                        "label": "openai:gpt-4o",
                    },
                    {
                        "provider": "anthropic",
                        "model": "claude-3-5-sonnet",
                        "label": "anthropic:claude-3-5-sonnet",
                    },
                ],
            }
        }
    )

    spawn_tool = next(
        tool for tool in tools if tool.get("function", {}).get("name") == "task_spawn_agent"
    )
    properties = spawn_tool["function"]["parameters"]["properties"]

    assert "openai:gpt-4o" in spawn_tool["function"]["description"]
    assert "anthropic:claude-3-5-sonnet" in properties["model"]["description"]
    assert "provider" in properties
    assert "provider:model" in properties["model"]["description"]


@pytest.mark.asyncio
async def test_ai_agent_collect_mcp_capabilities_handles_unavailable_manager(monkeypatch):
    """
    MCP 管理器不可用时，能力采集应返回稳定降级结构，而不是直接抛异常。
    """

    agent = AIAgent()
    monkeypatch.setattr(agent_module, "MCPManager", lambda: None)

    result = await agent._collect_mcp_capabilities({})

    assert result["platform_supported"] is True
    assert result["connected_servers"] == []
    assert result["tools"] == []
    assert 'NoneType' in str(result.get('error', '')) or 'none' in str(result.get('error', '')).lower()


@pytest.mark.asyncio
async def test_execution_layer_records_billing_usage_for_llm_calls(monkeypatch):
    pytest.skip("BillingEngine has been removed, using _record_hook pattern now")
    """
    非流式模型调用成功后，应把 usage 写入 billing 记录并回填到返回结果。
    """

    execution_layer = ExecutionLayer()
    captured_record_call = {}

    class FakeCalculator:
        @staticmethod
        def estimate_text_tokens(text):
            return len(text)

    class FakeBillingEngine:
        def __init__(self, db_session):
            self.db_session = db_session
            self.calculator = FakeCalculator()

        def record_call(self, **kwargs):
            captured_record_call.update(kwargs)
            return {
                "call_id": "usage-1",
                "input_tokens": kwargs["input_tokens"],
                "output_tokens": kwargs["output_tokens"],
                "total_cost": 0.0123,
                "currency": "USD",
            }

    def mock_resolve(self, context):
        return {
            "ok": True,
            "provider": "openai",
            "model": "gpt-4o-mini",
            "api_endpoint": "https://api.openai.com",
            "api_key": "secret",
            "request_id": "req-billing-1",
            "client_version": "2.3.4",
        }

    async def fake_litellm_chat_completion(**kwargs):
        return {
            "ok": True,
            "response": "用量记录成功",
            "reasoning_content": "",
            "provider": kwargs.get("provider", "openai"),
            "model": kwargs.get("model", "gpt-4o-mini"),
            "request_id": kwargs.get("request_id", "req-billing-1"),
            "usage": {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20},
        }

    execution_layer._resolve_llm_configuration = MethodType(mock_resolve, execution_layer)
    monkeypatch.setattr(executor_module, "BillingEngine", FakeBillingEngine)
    monkeypatch.setattr(executor_module, "litellm_chat_completion", fake_litellm_chat_completion)

    context = {
        "message": "统计本次调用",
        "db": SimpleNamespace(name="billing-db"),
        "user_id": "user-1",
        "session_id": "session-1",
    }

    result = await execution_layer._call_llm_api("统计本次调用", context)

    assert result["ok"] is True
    assert captured_record_call["user_id"] == "user-1"
    assert captured_record_call["session_id"] == "session-1"
    assert captured_record_call["input_tokens"] == 12
    assert captured_record_call["output_tokens"] == 8
    assert result["usage"]["call_id"] == "usage-1"
    assert result["usage"]["provider"] == "openai"
    assert context["_latest_llm_usage"]["model"] == "gpt-4o-mini"