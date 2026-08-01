"""
验证 AIAgent 核心逻辑：初始化、上下文构建、消息处理、异常处理。
覆盖正常流程与边界场景，mock 外部 LLM/DB 依赖。
"""

import asyncio
from types import SimpleNamespace

import pytest
from unittest.mock import MagicMock, patch

from api.routes.chat import cancel_agent_task
from core.agent import AIAgent
from core.agent_task_registry import get_agent_tasks, register_agent_task
from core.agent_capability_builder import build_native_tools
from core.agent_helpers import (
    build_effective_user_input,
    build_status_event,
    get_stream_tool_kind,
    is_final_only_mode,
    map_finish_reason_to_state,
    summarize_stream_tool_result,
)
from core.agent_context_builder import (
    build_multimodal_context,
    build_thinking_context,
    strip_reasoning_content,
)
from core.agent_state import AgentState
from core.agent_capability_builder import (
    summarize_plugin_capabilities,
    summarize_skill_capabilities,
)


# ==================== Agent 初始化测试 ====================


class TestAgentInitialization:
    """验证 AIAgent 的初始化流程。"""

    def test_agent_init_without_db_session_initializes_all_layers(self):
        """无 DB 会话时，Agent 应初始化轮次协调、执行和反馈协作者。"""
        agent = AIAgent()

        assert agent.turn_coordinator is not None
        assert agent.executor is not None
        assert agent.feedback is not None
        assert agent.experience_extractor is not None
        assert agent.skill_results == []
        assert agent.plugin_results == []
        assert agent.memory_manager is None
        assert agent.workflow_engine is None
        assert agent._closed is False

    def test_agent_init_with_db_session_sets_db_related_attributes(self):
        """有 DB 会话时，Agent 应设置 _db_session 并尝试创建记忆/工作流引擎。"""
        mock_db = MagicMock()

        agent = AIAgent(db_session=mock_db)

        assert agent._db_session is mock_db
        # memory_manager 和 workflow_engine 在有 db session 时应不为 None
        # （若 DB 不可用则可能为 None，但不影响基础流程）
        if agent.memory_manager is not None:
            assert agent.workflow_engine is not None


@pytest.mark.asyncio
async def test_cancel_agent_task_is_scoped_by_user_and_cancels_all_session_tasks():
    """取消接口只能取消当前用户同名会话的全部活跃任务。"""
    blocker = asyncio.Event()

    async def wait_forever() -> None:
        await blocker.wait()

    user_a_tasks = [asyncio.create_task(wait_forever()) for _ in range(2)]
    user_b_task = asyncio.create_task(wait_forever())
    for task in user_a_tasks:
        register_agent_task("user-a", "shared-session", task)
    register_agent_task("user-b", "shared-session", user_b_task)

    result = await cancel_agent_task(
        "shared-session",
        current_user=SimpleNamespace(id="user-a"),
    )
    await asyncio.sleep(0)

    assert result["cancelled_count"] == 2
    assert all(task.cancelled() for task in user_a_tasks)
    assert user_b_task.done() is False
    assert get_agent_tasks("user-b", "shared-session") == [user_b_task]

    user_b_task.cancel()
    await asyncio.gather(user_b_task, return_exceptions=True)


# ==================== 输出模式测试 ====================


class TestOutputMode:
    """验证 output_mode / suppress_reasoning / thinking_enabled 对输出的影响。"""

    def test_is_final_only_with_output_mode_final_only_returns_true(self):
        """output_mode=final_only 时返回 True。"""
        assert is_final_only_mode({"output_mode": "final_only"}) is True

    def test_is_final_only_with_suppress_reasoning_returns_true(self):
        """suppress_reasoning=True 时返回 True。"""
        assert is_final_only_mode({"suppress_reasoning": True}) is True

    def test_is_final_only_with_thinking_disabled_returns_true(self):
        """thinking_enabled=False 时返回 True。"""
        assert is_final_only_mode({"thinking_enabled": False}) is True

    def test_is_final_only_with_default_context_returns_false(self):
        """无特殊标记时返回 False。"""
        assert is_final_only_mode({}) is False

    def test_is_final_only_with_thinking_enabled_returns_false(self):
        """thinking_enabled=True 时返回 False。"""
        assert is_final_only_mode({"thinking_enabled": True}) is False

    def test_strip_reasoning_content_removes_top_level_key(self):
        """顶层 reasoning_content 应被实例方法移除。"""
        payload = {"result": "ok", "reasoning_content": "思考..."}
        result = strip_reasoning_content(payload)
        assert "reasoning_content" not in result
        assert result["result"] == "ok"

    def test_strip_reasoning_content_removes_nested_key(self):
        """嵌套结构中的 reasoning_content 也应被递归移除。"""
        payload = {
            "data": {"nested": {"reasoning_content": "深入思考", "value": 42}},
        }
        result = strip_reasoning_content(payload)
        assert "reasoning_content" not in result["data"]["nested"]
        assert result["data"]["nested"]["value"] == 42

    def test_strip_reasoning_content_handles_list(self):
        """列表中的每个元素都应递归移除 reasoning_content。"""
        payload = [
            {"reasoning_content": "思考1", "text": "a"},
            {"reasoning_content": "思考2", "text": "b"},
        ]
        result = strip_reasoning_content(payload)
        assert "reasoning_content" not in result[0]
        assert "reasoning_content" not in result[1]
        assert result[0]["text"] == "a"

    def test_apply_output_mode_in_final_only_strips_reasoning(self):
        """final_only 模式下 apply_output_mode 应去除推理内容。"""
        agent = AIAgent()
        payload = {"response": "答案", "reasoning_content": "逻辑推导"}
        result = agent._apply_output_mode(payload, {"output_mode": "final_only"})
        assert "reasoning_content" not in result

    def test_apply_output_mode_in_normal_mode_preserves_payload(self):
        """正常模式下 apply_output_mode 应原样返回。"""
        agent = AIAgent()
        payload = {"response": "答案", "reasoning_content": "逻辑推导"}
        result = agent._apply_output_mode(payload, {})
        assert result == payload


# ==================== 上下文构建测试 ====================


class TestContextBuilding:
    """验证上下文前置处理逻辑。"""

    def test_build_effective_user_input_without_continuation_returns_original(self):
        """无 continuation 时原样返回用户输入。"""
        result = build_effective_user_input("你好", {})
        assert result == "你好"

    def test_build_effective_user_input_with_continuation_appends_context(self):
        """存在 continuation 时应附加子代理聚合上下文。"""
        context = {
            "continuation": {
                "aggregated_context": "子代理已完成分析",
                "source": "subagent",
            }
        }
        result = build_effective_user_input("你好", context)
        assert "你好" in result
        assert "子代理已完成分析" in result
        assert "subagent" in result

    def test_build_effective_user_input_with_continuation_no_user_input(self):
        """continuation 存在但无用户输入时，仅拼接指令和结果。"""
        context = {
            "continuation": {
                "aggregated_context": "子代理结果",
                "source": "Explore",
            }
        }
        result = build_effective_user_input("", context)
        assert "子代理结果" in result
        assert "Explore" in result

    def test_build_status_event_returns_correct_format(self):
        """状态事件格式应包含 type/phase/message。"""
        event = build_status_event("planning", "正在生成计划")
        assert event["type"] == "status"
        assert event["phase"] == "planning"
        assert event["message"] == "正在生成计划"

    def test_build_status_event_with_extra_kwargs(self):
        """额外参数应合并到事件中。"""
        event = build_status_event(
            "executing", "执行步骤", step=1, total=3
        )
        assert event["step"] == 1
        assert event["total"] == 3


# ==================== 上下文准备测试 ====================


class TestPrepareContext:
    """验证 _prepare_context 方法。"""

    def test_prepare_context_sets_message_in_context(self):
        """_prepare_context 应将 user_input 写入 context['message']。"""
        agent = AIAgent()
        ctx = {}
        agent._prepare_context("测试消息", ctx)
        assert ctx["message"] == "测试消息"

    def test_prepare_context_does_not_overwrite_existing_message(self):
        """当 context 已有 message 时不覆盖。"""
        agent = AIAgent()
        ctx = {"message": "已有消息"}
        agent._prepare_context("新消息", ctx)
        assert ctx["message"] == "已有消息"

    def test_prepare_context_applies_scheduled_execution_defaults(self):
        """定时任务隔离场景应补齐隔离开关。"""
        agent = AIAgent()
        ctx = {"scheduled_execution_isolated": True}
        agent._prepare_context("任务", ctx)
        assert ctx["disable_behavior_logging"] is True
        assert ctx["disable_conversation_record"] is True
        assert ctx["disable_memory_update"] is True
        assert ctx["retrieve_experiences"] is False
        assert ctx["retrieve_long_term_memory"] is False
        assert ctx["enable_skill_plugin"] is False
        assert ctx["extract_experience"] is False
        assert ctx["output_mode"] == "final_only"

    def test_prepare_context_sets_record_hook(self):
        """_prepare_context 应注入 _record_hook。"""
        agent = AIAgent()
        ctx = {}
        agent._prepare_context("测试", ctx)
        assert callable(ctx.get("_record_hook"))


# ==================== 工具定义构建测试 ====================


class TestBuildNativeTools:
    """验证 _build_native_tools 方法。"""

    def test_build_native_tools_with_empty_capabilities_returns_builtin_and_task_tools(self):
        """空能力摘要时应返回内置工具和任务运行时工具。"""
        tools = build_native_tools({})
        # 至少应包含 task_ 前缀的运行工具
        task_tools = [t for t in tools if t.get("function", {}).get("name", "").startswith("task_")]
        assert len(task_tools) > 0
        # 应有 task_spawn_agent 等核心工具
        task_names = {t["function"]["name"] for t in task_tools}
        assert "task_spawn_agent" in task_names

    def test_build_native_tools_with_plugin_converts_to_function_format(self):
        """插件工具应被转换为 OpenAI function calling 格式。"""
        capabilities = {
            "plugins": [
                {
                    "name": "twitter-monitor",
                    "tools": [
                        {
                            "name": "get_twitter_user_info",
                            "description": "获取用户信息",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "user_name": {"type": "string"}
                                },
                                "required": ["user_name"],
                            },
                        }
                    ],
                }
            ]
        }
        tools = build_native_tools(capabilities)
        plugin_tools = [
            t for t in tools
            if t.get("function", {}).get("name", "").startswith("plugin_")
        ]
        assert len(plugin_tools) == 1
        assert plugin_tools[0]["function"]["name"] == "plugin_twitter-monitor__get_twitter_user_info"
        assert plugin_tools[0]["function"]["description"] == "获取用户信息"

    def test_build_native_tools_deduplicates_by_name(self):
        """同名的工具定义只应出现一次。"""
        capabilities = {
            "plugins": [
                {
                    "name": "demo",
                    "tools": [
                        {"name": "tool_a", "description": "工具 A"},
                        {"name": "tool_a", "description": "工具 A 重复"},
                    ],
                }
            ]
        }
        tools = build_native_tools(capabilities)
        plugin_tools = [
            t for t in tools
            if t.get("function", {}).get("name", "").startswith("plugin_")
        ]
        assert len(plugin_tools) == 1


# ==================== Process 方法流程测试 ====================


class TestProcessFlow:
    """验证 process() 方法的完整执行链路。"""

    @pytest.mark.asyncio
    async def test_process_normal_flow_returns_completed_response(self, monkeypatch):
        """正常流程应返回 completed 状态和最终回复。"""
        agent = AIAgent()

        async def fake_inject_runtime_capabilities(ctx):
            return None

        async def fake_build_conversation_history(session_id, max_turns=20):
            return []

        async def fake_recognize_intent(user_input):
            return "chat"

        async def fake_extract_entities(user_input):
            return {}

        async def fake_create_plan(intent, entities, context):
            return {"intent": "chat", "steps": [
                {"step": 1, "action": "llm_chat", "message": context.get("message", ""),
                 "purpose": "对话交流"}
            ], "requires_confirmation": False}

        async def fake_execute_step(step, context):
            return {"status": "completed", "response": "一切就绪", "step": 1, "action": "llm_chat"}

        async def fake_evaluate_result(result):
            return {"needs_confirmation": False, "needs_retry": False}

        async def fake_generate_response(results, context):
            return "最终回复: 一切就绪"

        async def fake_update_memory(user_input, response, context, **kwargs):
            return None

        async def fake_auto_execute_skills_and_plugins(execution_context):
            return {"skills": [], "plugins": []}

        monkeypatch.setattr(agent, "_inject_runtime_capabilities", fake_inject_runtime_capabilities)
        monkeypatch.setattr(agent, "_build_conversation_history", fake_build_conversation_history)
        monkeypatch.setattr(agent.turn_coordinator, "recognize_intent", fake_recognize_intent)
        monkeypatch.setattr(agent.turn_coordinator, "extract_entities", fake_extract_entities)
        monkeypatch.setattr(agent.turn_coordinator, "create_plan", fake_create_plan)
        monkeypatch.setattr(agent.executor, "execute_step", fake_execute_step)
        monkeypatch.setattr(agent.feedback, "evaluate_result", fake_evaluate_result)
        monkeypatch.setattr(agent.feedback, "generate_response", fake_generate_response)
        monkeypatch.setattr(agent.feedback, "update_memory", fake_update_memory)
        monkeypatch.setattr(
            agent._plan_executor,
            "auto_execute",
            fake_auto_execute_skills_and_plugins,
        )
        monkeypatch.setattr(agent, "_schedule_record", lambda **kwargs: None)

        result = await agent.process("你好", {"session_id": "test-session"})

        assert result["status"] == "completed"
        assert "最终回复" in result["response"]
        assert len(result["results"]) == 1

    @pytest.mark.asyncio
    async def test_process_handles_llm_error_gracefully(self, monkeypatch):
        """LLM 执行失败时应返回 error 状态和错误详情。"""
        agent = AIAgent()

        async def fake_inject_runtime_capabilities(ctx):
            return None

        async def fake_build_conversation_history(session_id, max_turns=20):
            return []

        async def fake_recognize_intent(user_input):
            return "query"

        async def fake_extract_entities(user_input):
            return {}

        async def fake_create_plan(intent, entities, context):
            return {"intent": "query", "steps": [
                {"step": 1, "action": "llm_query", "prompt": context.get("message", ""),
                 "purpose": "查询"}
            ], "requires_confirmation": False}

        async def fake_execute_step_error(step, context):
            return {"status": "error", "message": "LLM 服务不可用", "error": {"code": "model_service_error", "message": "LLM 服务不可用"}, "step": 1, "action": "llm_query"}

        async def fake_evaluate_result(result):
            return {"needs_confirmation": False, "needs_retry": False}

        async def fake_generate_response(results, context):
            return "抱歉，查询失败"

        async def fake_auto_execute_skills_and_plugins(execution_context):
            return {"skills": [], "plugins": []}

        monkeypatch.setattr(agent, "_inject_runtime_capabilities", fake_inject_runtime_capabilities)
        monkeypatch.setattr(agent, "_build_conversation_history", fake_build_conversation_history)
        monkeypatch.setattr(agent.turn_coordinator, "recognize_intent", fake_recognize_intent)
        monkeypatch.setattr(agent.turn_coordinator, "extract_entities", fake_extract_entities)
        monkeypatch.setattr(agent.turn_coordinator, "create_plan", fake_create_plan)
        monkeypatch.setattr(agent.executor, "execute_step", fake_execute_step_error)
        monkeypatch.setattr(agent.feedback, "evaluate_result", fake_evaluate_result)
        monkeypatch.setattr(agent.feedback, "generate_response", fake_generate_response)
        monkeypatch.setattr(
            agent._plan_executor,
            "auto_execute",
            fake_auto_execute_skills_and_plugins,
        )
        monkeypatch.setattr(agent, "_schedule_record", lambda **kwargs: None)

        result = await agent.process("查询天气", {"session_id": "test-session"})

        assert result["status"] == "error"
        assert isinstance(result["error"], dict)
        assert result["error"]["code"] == "model_service_error"

    @pytest.mark.asyncio
    async def test_process_executes_auto_skills_and_plugins_when_enabled(self, monkeypatch):
        """启用技能/插件时应自动执行匹配的技能。"""
        agent = AIAgent()

        captured_auto_context = {"called": False}

        async def fake_inject_runtime_capabilities(ctx):
            return None

        async def fake_build_conversation_history(session_id, max_turns=20):
            return []

        async def fake_recognize_intent(user_input):
            return "execute"

        async def fake_extract_entities(user_input):
            return {}

        async def fake_create_plan(intent, entities, context):
            return {"intent": "execute", "steps": [
                {"step": 1, "action": "execute_command", "command": "echo done",
                 "purpose": "执行命令"}
            ], "requires_confirmation": False}

        async def fake_execute_step(step, context):
            return {"status": "completed", "stdout": "done", "step": 1, "action": "execute_command"}

        async def fake_evaluate_result(result):
            return {"needs_confirmation": False, "needs_retry": False}

        async def fake_generate_response(results, context):
            return "命令已执行"

        async def fake_update_memory(user_input, response, context, **kwargs):
            return None

        async def fake_auto_execute(execution_context):
            captured_auto_context["called"] = True
            return {"skills": [{"skill_name": "demo", "result": "done"}], "plugins": []}

        monkeypatch.setattr(agent, "_inject_runtime_capabilities", fake_inject_runtime_capabilities)
        monkeypatch.setattr(agent, "_build_conversation_history", fake_build_conversation_history)
        monkeypatch.setattr(agent.turn_coordinator, "recognize_intent", fake_recognize_intent)
        monkeypatch.setattr(agent.turn_coordinator, "extract_entities", fake_extract_entities)
        monkeypatch.setattr(agent.turn_coordinator, "create_plan", fake_create_plan)
        monkeypatch.setattr(agent.executor, "execute_step", fake_execute_step)
        monkeypatch.setattr(agent.feedback, "evaluate_result", fake_evaluate_result)
        monkeypatch.setattr(agent.feedback, "generate_response", fake_generate_response)
        monkeypatch.setattr(agent.feedback, "update_memory", fake_update_memory)
        monkeypatch.setattr(agent._plan_executor, "auto_execute", fake_auto_execute)
        monkeypatch.setattr(agent, "_schedule_record", lambda **kwargs: None)

        result = await agent.process("执行任务", {
            "session_id": "test-session",
            "enable_skill_plugin": True,
        })

        assert captured_auto_context["called"] is True
        assert result["status"] == "completed"


# ==================== 能力摘要测试 ====================


class TestSkillPluginSummary:
    """验证技能/插件能力摘要的构建逻辑。"""

    def test_summarize_skill_capabilities_filters_disabled(self):
        """disabled 的技能不应出现在摘要中。"""
        skills = [
            {"name": "s1", "description": "技能1", "enabled": True},
            {"name": "s2", "description": "技能2", "enabled": False},
            {"name": "s3", "description": "技能3", "enabled": True},
        ]
        result = summarize_skill_capabilities(skills)
        assert len(result) == 2
        assert result[0]["name"] == "s1"
        assert result[1]["name"] == "s3"

    def test_summarize_skill_capabilities_non_dict_ignored(self):
        """非字典类型的技能项应被忽略。"""
        skills = [
            {"name": "s1", "enabled": True},
            "invalid_string",
            None,
        ]
        result = summarize_skill_capabilities(skills)
        assert len(result) == 1

    def test_summarize_plugin_capabilities_includes_tool_definitions(self):
        """插件摘要应包含工具名称和描述。"""
        plugins = [
            {
                "name": "demo",
                "description": "演示插件",
                "loaded": True,
                "tools": [
                    {"name": "tool_a", "description": "工具A", "method": "run_a"},
                ],
            }
        ]
        result = summarize_plugin_capabilities(plugins)
        assert len(result) == 1
        assert result[0]["name"] == "demo"
        assert len(result[0]["tools"]) == 1
        assert result[0]["tools"][0]["name"] == "tool_a"


# ==================== 流处理类名推断测试 ====================


class TestStreamToolHelpers:
    """验证流式工具处理辅助方法。"""

    def test_get_stream_tool_kind_plugin_prefix(self):
        """plugin_ 前缀应返回 'plugin' 类别。"""
        assert get_stream_tool_kind("plugin_demo__run") == "plugin"

    def test_get_stream_tool_kind_mcp_prefix(self):
        """mcp_ 前缀应返回 'mcp' 类别。"""
        assert get_stream_tool_kind("mcp_server__tool") == "mcp"

    def test_get_stream_tool_kind_task_prefix(self):
        """task_ 前缀应返回 'task' 类别。"""
        assert get_stream_tool_kind("task_spawn_agent") == "task"

    def test_get_stream_tool_kind_unknown_returns_tool(self):
        """未知前缀默认返回 'tool'。"""
        assert get_stream_tool_kind("unknown_function") == "tool"

    def test_summarize_stream_tool_result_ok_with_message(self):
        """成功结果有 message 字段时取 message 值。"""
        exec_result = {"ok": True, "result": {"message": "执行成功"}}
        result = summarize_stream_tool_result(exec_result)
        assert result == "执行成功"

    def test_summarize_stream_tool_result_ok_with_response(self):
        """成功结果有 response 字段时取 response 值。"""
        exec_result = {"ok": True, "result": {"response": "查询结果"}}
        result = summarize_stream_tool_result(exec_result)
        assert result == "查询结果"

    def test_summarize_stream_tool_result_error(self):
        """失败结果返回错误信息。"""
        exec_result = {"ok": False, "error": "工具调用异常"}
        result = summarize_stream_tool_result(exec_result)
        assert result == "工具调用异常"

    def test_summarize_stream_tool_result_empty(self):
        """空结果返回默认文本。"""
        exec_result = {"ok": True, "result": {}}
        result = summarize_stream_tool_result(exec_result)
        assert result == "工具调用完成"


# ==================== 多模态与思考上下文测试 ====================


class TestMultimodalAndThinking:
    """验证多模态与思考模式上下文的构建。"""

    def test_build_multimodal_context_without_attachments_does_nothing(self):
        """无附件时不应设置 _multimodal_content。"""
        ctx = {}
        build_multimodal_context("你好", ctx)
        assert "_multimodal_content" not in ctx

    def test_build_multimodal_context_with_attachments_builds_content(self):
        """有附件时应调用 build_multimodal_message 构建多模态内容。"""
        attachments = [{"type": "image", "url": "https://example.com/img.png"}]
        ctx = {"attachments": attachments, "provider": "openai", "model": "gpt-4o"}

        with patch("core.litellm_adapter.build_multimodal_message") as mock_build:
            mock_build.return_value = [{"type": "text", "text": "你好"}, {"type": "image_url", "image_url": {"url": "..."}}]
            build_multimodal_context("你好", ctx)
            mock_build.assert_called_once_with("你好", attachments, "openai")
            assert "_multimodal_content" in ctx

    def test_build_thinking_context_without_thinking_does_nothing(self):
        """未启用思考时不应设置任何参数。"""
        ctx = {}
        build_thinking_context(ctx)
        assert "_thinking_params" not in ctx

    def test_build_thinking_context_with_thinking_enabled(self):
        """启用思考时应调用 build_thinking_params。"""
        ctx = {
            "thinking_enabled": True,
            "thinking_depth": 2,
            "provider": "openai",
            "model": "gpt-4o",
        }

        with patch("core.litellm_adapter.build_thinking_params") as mock_build:
            mock_build.return_value = {"type": "enabled", "budget_tokens": 4000}
            build_thinking_context(ctx)
            mock_build.assert_called_once_with("openai", "gpt-4o", 2, True)
            assert ctx["_thinking_params"] == {"type": "enabled", "budget_tokens": 4000}

    def test_build_thinking_context_with_thinking_enabled_but_none_params_does_nothing(self):
        """build_thinking_params 返回 None 时不设置 _thinking_params。"""
        ctx = {
            "thinking_enabled": True,
            "provider": "openai",
            "model": "gpt-4o",
        }

        with patch("core.litellm_adapter.build_thinking_params") as mock_build:
            mock_build.return_value = None
            build_thinking_context(ctx)
            assert "_thinking_params" not in ctx


# ==================== AgentState 枚举测试 ====================


class TestAgentStateEnum:
    """验证 AgentState 枚举的终态/继续态判断逻辑。"""

    def test_agent_state_is_terminal_end_turn(self):
        """TERMINAL_END_TURN 应被识别为终态。"""
        assert AgentState.TERMINAL_END_TURN.is_terminal is True

    def test_agent_state_is_terminal_max_rounds(self):
        """TERMINAL_MAX_ROUNDS 应被识别为终态。"""
        assert AgentState.TERMINAL_MAX_ROUNDS.is_terminal is True

    def test_agent_state_is_terminal_refusal(self):
        """TERMINAL_REFUSAL 应被识别为终态。"""
        assert AgentState.TERMINAL_REFUSAL.is_terminal is True

    def test_agent_state_is_terminal_budget_exhausted(self):
        """TERMINAL_BUDGET_EXHAUSTED 应被识别为终态。"""
        assert AgentState.TERMINAL_BUDGET_EXHAUSTED.is_terminal is True

    def test_agent_state_is_terminal_continue_tool_calls_false(self):
        """CONTINUE_TOOL_CALLS 不应是终态。"""
        assert AgentState.CONTINUE_TOOL_CALLS.is_terminal is False

    def test_agent_state_is_terminal_continue_compact_false(self):
        """CONTINUE_COMPACT 不应是终态。"""
        assert AgentState.CONTINUE_COMPACT.is_terminal is False

    def test_agent_state_is_continuation_tool_calls(self):
        """CONTINUE_TOOL_CALLS 应被识别为继续态。"""
        assert AgentState.CONTINUE_TOOL_CALLS.is_continuation is True

    def test_agent_state_is_continuation_compact(self):
        """CONTINUE_COMPACT 应被识别为继续态。"""
        assert AgentState.CONTINUE_COMPACT.is_continuation is True

    def test_agent_state_is_continuation_end_turn_false(self):
        """TERMINAL_END_TURN 不应是继续态。"""
        assert AgentState.TERMINAL_END_TURN.is_continuation is False

    def test_agent_state_is_continuation_max_rounds_false(self):
        """TERMINAL_MAX_ROUNDS 不应是继续态。"""
        assert AgentState.TERMINAL_MAX_ROUNDS.is_continuation is False

    def test_agent_state_is_continuation_refusal_false(self):
        """TERMINAL_REFUSAL 不应是继续态。"""
        assert AgentState.TERMINAL_REFUSAL.is_continuation is False

    def test_agent_state_is_continuation_budget_exhausted_false(self):
        """TERMINAL_BUDGET_EXHAUSTED 不应是继续态。"""
        assert AgentState.TERMINAL_BUDGET_EXHAUSTED.is_continuation is False


# ==================== finish_reason 到 AgentState 映射测试 ====================


class TestMapFinishReasonToState:
    """验证 _map_finish_reason_to_state 的映射规则。"""

    def test_map_finish_reason_tool_calls_returns_continue_tool_calls(self):
        """finish_reason=tool_calls 且未达最大轮次时应返回 CONTINUE_TOOL_CALLS。"""
        state = map_finish_reason_to_state(
            finish_reason="tool_calls", current_round=1, max_rounds=10
        )
        assert state is AgentState.CONTINUE_TOOL_CALLS

    def test_map_finish_reason_stop_returns_terminal_end_turn(self):
        """finish_reason=stop 时应返回 TERMINAL_END_TURN。"""
        state = map_finish_reason_to_state(
            finish_reason="stop", current_round=1, max_rounds=10
        )
        assert state is AgentState.TERMINAL_END_TURN

    def test_map_finish_reason_length_returns_continue_compact(self):
        """finish_reason=length 时应返回 CONTINUE_COMPACT（上下文超限需压缩）。"""
        state = map_finish_reason_to_state(
            finish_reason="length", current_round=1, max_rounds=10
        )
        assert state is AgentState.CONTINUE_COMPACT

    def test_map_finish_reason_content_filter_returns_terminal_refusal(self):
        """finish_reason=content_filter 时应返回 TERMINAL_REFUSAL。"""
        state = map_finish_reason_to_state(
            finish_reason="content_filter", current_round=1, max_rounds=10
        )
        assert state is AgentState.TERMINAL_REFUSAL

    def test_map_finish_reason_max_rounds_returns_terminal_max_rounds(self):
        """current_round >= max_rounds 时无论 finish_reason 都应返回 TERMINAL_MAX_ROUNDS。"""
        state = map_finish_reason_to_state(
            finish_reason="tool_calls", current_round=10, max_rounds=10
        )
        assert state is AgentState.TERMINAL_MAX_ROUNDS

    def test_map_finish_reason_max_rounds_exceeds_boundary(self):
        """current_round 超过 max_rounds 时也应返回 TERMINAL_MAX_ROUNDS。"""
        state = map_finish_reason_to_state(
            finish_reason="stop", current_round=11, max_rounds=10
        )
        assert state is AgentState.TERMINAL_MAX_ROUNDS

    def test_map_finish_reason_unknown_returns_terminal_end_turn(self):
        """未知 finish_reason 应安全回退到 TERMINAL_END_TURN。"""
        state = map_finish_reason_to_state(
            finish_reason="unknown_reason", current_round=1, max_rounds=10
        )
        assert state is AgentState.TERMINAL_END_TURN

    def test_map_finish_reason_empty_string_returns_terminal_end_turn(self):
        """空 finish_reason 应安全回退到 TERMINAL_END_TURN。"""
        state = map_finish_reason_to_state(
            finish_reason="", current_round=1, max_rounds=10
        )
        assert state is AgentState.TERMINAL_END_TURN
