"""
验证执行层的模型工具调用闭环。
覆盖真实 tool_calls 与伪 JSON 兼容回环，避免模型输出调用代码后直接截断结束。
"""

from types import MethodType

import pytest

import core.executor as executor_module
import core.task_runtime as task_runtime_module
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


def test_build_assistant_tool_call_message_validates_inputs():
    """构造 assistant tool_call 消息时应校验入参与兜底转换类型。"""

    message = ExecutionLayer.build_assistant_tool_call_message(
        content="处理中",
        reasoning_content=123,
        tool_calls=[],
    )

    assert message["reasoning_content"] == "123"
    assert "tool_calls" not in message

    with pytest.raises(ValueError, match="tool_calls must be a list"):
        ExecutionLayer.build_assistant_tool_call_message(
            content="处理中",
            reasoning_content="需要调用工具",
            tool_calls={"id": "call_1"},
        )


@pytest.mark.asyncio
async def test_execute_tool_call_normalizes_task_prefix_case(monkeypatch):
    """工具前缀首字母被模型错误大写时，执行层仍应正确路由到 task runtime。"""

    execution_layer = ExecutionLayer()
    captured: dict[str, object] = {}

    class FakeTaskRuntime:
        async def initialize(self):
            captured["initialized"] = True

        async def create_task_item(self, **kwargs):
            captured["kwargs"] = kwargs
            return {"ok": True, "task_id": "task_123", "subject": kwargs.get("subject")}

    monkeypatch.setattr(task_runtime_module, "task_runtime", FakeTaskRuntime())

    result = await execution_layer._execute_tool_call(
        {
            "id": "call_1",
            "type": "function",
            "function": {
                "name": "Task_create_task",
                "arguments": '{"subject":"修复工具调用卡住问题"}',
            },
        },
        {"session_id": "sess_1", "agent_id": "agt_1"},
    )

    assert captured["initialized"] is True
    assert captured["kwargs"] == {
        "list_id": None,
        "subject": "修复工具调用卡住问题",
        "description": None,
        "dependencies": None,
        "owner_agent_id": None,
    }
    assert result == {
        "ok": True,
        "result": {"ok": True, "task_id": "task_123", "subject": "修复工具调用卡住问题"},
        "tool_name": "task_create_task",
    }


@pytest.mark.asyncio
async def test_execute_tool_call_spawn_agent_supports_qualified_model(monkeypatch):
    """子代理工具调用应支持使用 provider:model 单字段格式指定跨供应商模型。"""

    execution_layer = ExecutionLayer()
    captured: dict[str, object] = {}

    class FakeTaskRuntime:
        async def initialize(self):
            captured["initialized"] = True

        async def spawn_agent(self, **kwargs):
            captured["kwargs"] = kwargs
            return {"ok": True, "agent_id": "agt_123", "state": "queued"}

    monkeypatch.setattr(task_runtime_module, "task_runtime", FakeTaskRuntime())

    result = await execution_layer._execute_tool_call(
        {
            "id": "call_2",
            "type": "function",
            "function": {
                "name": "task_spawn_agent",
                "arguments": '{"agent_type":"Explore","prompt":"分析日志","description":"排查问题","model":"anthropic:claude-3-5-sonnet","background":true}',
            },
        },
        {"session_id": "sess_1", "agent_id": "agt_1", "provider": "openai"},
    )

    assert captured["initialized"] is True
    assert captured["kwargs"] == {
        "agent_type": "Explore",
        "prompt": "分析日志",
        "description": "排查问题",
        "provider": "anthropic",
        "model": "claude-3-5-sonnet",
        "background": True,
        "context": {"session_id": "sess_1", "agent_id": "agt_1", "provider": "openai"},
    }
    assert result == {
        "ok": True,
        "result": {"ok": True, "agent_id": "agt_123", "state": "queued"},
        "tool_name": "task_spawn_agent",
    }


@pytest.mark.asyncio
async def test_execute_tool_call_spawn_agent_consumes_foreground_stream(monkeypatch):
    """前台子代理应被真实消费，并把摘要结果回传给主代理。"""

    execution_layer = ExecutionLayer()
    captured_events: list[dict[str, object]] = []

    async def fake_foreground_stream():
        yield {
            "type": "subagent_start",
            "agent_id": "agt_fg_1",
            "agent_type": "Explore",
            "description": "前台执行",
        }
        yield {
            "type": "agent_message",
            "agent_id": "agt_fg_1",
            "agent_type": "Explore",
            "message": "子代理实时输出",
        }
        yield {
            "type": "subagent_stop",
            "agent_id": "agt_fg_1",
            "agent_type": "Explore",
            "state": "completed",
            "summary": "子代理执行完成",
        }

    class FakeTaskRuntime:
        async def initialize(self):
            return None

        async def spawn_agent(self, **kwargs):
            return fake_foreground_stream()

    async def on_subagent_event(event):
        captured_events.append(event)

    monkeypatch.setattr(task_runtime_module, "task_runtime", FakeTaskRuntime())

    result = await execution_layer._execute_tool_call(
        {
            "id": "call_fg_1",
            "type": "function",
            "function": {
                "name": "task_spawn_agent",
                "arguments": '{"agent_type":"Explore","prompt":"执行前台任务","description":"前台执行","provider":"openai","model":"gpt-4o-mini"}',
            },
        },
        {"session_id": "sess_fg_1", "agent_id": "agt_parent_1", "provider": "openai", "model": "gpt-4o-mini"},
        on_subagent_event=on_subagent_event,
    )

    assert [event["type"] for event in captured_events] == [
        "subagent_start",
        "agent_message",
        "subagent_stop",
    ]
    assert result == {
        "ok": True,
        "result": {
            "agent_id": "agt_fg_1",
            "agent_type": "Explore",
            "run_mode": "foreground",
            "status": "completed",
            "summary": "子代理执行完成",
            "message": "子代理执行完成",
        },
        "tool_name": "task_spawn_agent",
    }


@pytest.mark.asyncio
async def test_execute_tool_call_spawn_agent_returns_explicit_error_when_model_unresolved(monkeypatch):
    """无法解析子代理模型时，应返回明确错误且不启动子代理。"""

    execution_layer = ExecutionLayer()
    captured = {"spawn_called": False}

    class FakeTaskRuntime:
        async def initialize(self):
            return None

        async def spawn_agent(self, **kwargs):
            captured["spawn_called"] = True
            return {"ok": True}

    def fake_resolve(self, context):
        return {
            "ok": False,
            "error": {
                "code": "llm_provider_missing",
                "message": "未配置可用的模型提供商",
            },
        }

    monkeypatch.setattr(task_runtime_module, "task_runtime", FakeTaskRuntime())
    execution_layer._resolve_llm_configuration = MethodType(fake_resolve, execution_layer)

    result = await execution_layer._execute_tool_call(
        {
            "id": "call_fg_2",
            "type": "function",
            "function": {
                "name": "task_spawn_agent",
                "arguments": '{"agent_type":"Explore","prompt":"执行任务","description":"缺模型"}',
            },
        },
        {"session_id": "sess_fg_2", "agent_id": "agt_parent_2"},
    )

    assert captured["spawn_called"] is False
    assert result == {
        "ok": False,
        "error": "未能解析子代理模型，请指定 provider/model 参数或确保主会话已配置模型",
        "tool_name": "task_spawn_agent",
    }


@pytest.mark.asyncio
async def test_execute_tool_call_spawn_agent_inherits_current_model_when_missing(monkeypatch):
    """LLM 未传模型时，子代理应继承主会话当前 provider/model。"""

    execution_layer = ExecutionLayer()
    captured: dict[str, object] = {}

    class FakeTaskRuntime:
        async def initialize(self):
            return None

        async def spawn_agent(self, **kwargs):
            captured["kwargs"] = kwargs
            return {"ok": True, "agent_id": "agt_456", "status": "queued", "run_mode": "background"}

    monkeypatch.setattr(task_runtime_module, "task_runtime", FakeTaskRuntime())

    result = await execution_layer._execute_tool_call(
        {
            "id": "call_bg_3",
            "type": "function",
            "function": {
                "name": "task_spawn_agent",
                "arguments": '{"agent_type":"Explore","prompt":"执行任务","description":"继承模型","background":true}',
            },
        },
        {
            "session_id": "sess_inherit_1",
            "agent_id": "agt_parent_3",
            "provider": "openai",
            "model": "gpt-4o-mini",
        },
    )

    assert captured["kwargs"] == {
        "agent_type": "Explore",
        "prompt": "执行任务",
        "description": "继承模型",
        "provider": "openai",
        "model": "gpt-4o-mini",
        "background": True,
        "context": {
            "session_id": "sess_inherit_1",
            "agent_id": "agt_parent_3",
            "provider": "openai",
            "model": "gpt-4o-mini",
        },
    }
    assert result == {
        "ok": True,
        "result": {"ok": True, "agent_id": "agt_456", "status": "queued", "run_mode": "background"},
        "tool_name": "task_spawn_agent",
    }


@pytest.mark.asyncio
async def test_execute_step_llm_generate_accepts_legacy_task_alias(monkeypatch):
    """执行层应兼容历史 llm_generate.task 字段，避免旧计划直接校验失败。"""

    execution_layer = ExecutionLayer()
    captured: dict[str, object] = {}

    async def fake_call_llm_api(prompt, context):
        captured["prompt"] = prompt
        captured["context"] = context
        return {
            "ok": True,
            "response": "已完成",
            "provider": "deepseek",
            "model": "deepseek-chat",
        }

    monkeypatch.setattr(execution_layer, "_call_llm_api", fake_call_llm_api)

    result = await execution_layer.execute_step(
        {
            "step": 1,
            "action": "llm_generate",
            "task": "请整理这段日志的根因",
        },
        {
            "session_id": "sess_legacy_task",
            "message": "请整理这段日志的根因",
        },
    )

    assert captured["prompt"] == "请整理这段日志的根因"
    assert result["status"] == "completed"
    assert result["response"] == "已完成"


@pytest.mark.asyncio
async def test_execute_step_llm_explain_accepts_legacy_target_alias(monkeypatch):
    """执行层应兼容历史 llm_explain.target 字段。"""

    execution_layer = ExecutionLayer()
    captured: dict[str, object] = {}

    async def fake_call_llm_api(prompt, context):
        captured["prompt"] = prompt
        return {
            "ok": True,
            "response": "解释完成",
            "provider": "deepseek",
            "model": "deepseek-chat",
        }

    monkeypatch.setattr(execution_layer, "_call_llm_api", fake_call_llm_api)

    result = await execution_layer.execute_step(
        {
            "step": 1,
            "action": "llm_explain",
            "target": "为什么子代理会失败",
        },
        {
            "session_id": "sess_legacy_target",
            "message": "解释一下为什么子代理会失败",
        },
    )

    assert captured["prompt"] == "Explain: 为什么子代理会失败"
    assert result["status"] == "completed"
    assert result["response"] == "解释完成"


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
