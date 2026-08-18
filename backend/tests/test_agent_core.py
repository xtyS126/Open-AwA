"""
验证 AIAgent 核心逻辑：初始化、上下文构建、消息处理、异常处理。
覆盖正常流程与边界场景，mock 外部 LLM/DB 依赖。
"""

import asyncio
from types import SimpleNamespace

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

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
    async def test_build_conversation_history_without_memory_manager_raises(self):
        """记忆管理器未注入时必须显式失败，禁止静默返回空历史。"""
        agent = AIAgent()

        with pytest.raises(RuntimeError, match="记忆管理器未注入，无法构建对话历史"):
            await agent._build_conversation_history("session-1")

    @pytest.mark.asyncio
    async def test_retrieve_relevant_memories_without_memory_manager_raises(self):
        """记忆管理器未注入时必须显式失败，禁止静默返回空记忆。"""
        agent = AIAgent()

        with pytest.raises(RuntimeError, match="记忆管理器未注入，无法检索长期记忆"):
            await agent._retrieve_relevant_memories("query", {})

    @pytest.mark.asyncio
    async def test_process_normal_flow_returns_completed_response(self, monkeypatch):
        """正常流程应返回 completed 状态和最终回复。"""
        agent = AIAgent()

        async def fake_inject_runtime_capabilities(ctx):
            return None

        async def fake_build_conversation_history(session_id, max_turns=20):
            return []

        async def fake_retrieve_relevant_memories(user_input, context):
            # 轻量实例未注入记忆管理器，mock 记忆检索返回空列表
            return []

        async def fake_recognize_intent(user_input):
            return {"type": "chat"}

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
        monkeypatch.setattr(agent, "_retrieve_relevant_memories", fake_retrieve_relevant_memories)
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

        async def fake_retrieve_relevant_memories(user_input, context):
            # 轻量实例未注入记忆管理器，mock 记忆检索返回空列表
            return []

        async def fake_recognize_intent(user_input):
            return {"type": "query"}

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
        monkeypatch.setattr(agent, "_retrieve_relevant_memories", fake_retrieve_relevant_memories)
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

        async def fake_retrieve_relevant_memories(user_input, context):
            # 轻量实例未注入记忆管理器，mock 记忆检索返回空列表
            return []

        async def fake_recognize_intent(user_input):
            return {"type": "execute"}

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
        monkeypatch.setattr(agent, "_retrieve_relevant_memories", fake_retrieve_relevant_memories)
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

    def test_map_finish_reason_unknown_raises(self):
        """未知 finish_reason 应走显式错误路径（抛 ValueError）。"""
        with pytest.raises(ValueError, match="未知的 finish_reason"):
            map_finish_reason_to_state(
                finish_reason="unknown_reason", current_round=1, max_rounds=10
            )

    def test_map_finish_reason_empty_string_raises(self):
        """空 finish_reason 应走显式错误路径（抛 ValueError）。"""
        with pytest.raises(ValueError, match="未知的 finish_reason"):
            map_finish_reason_to_state(
                finish_reason="", current_round=1, max_rounds=10
            )


# ==================== 预算 usage 回填测试 ====================


class TestRecordRoundBudgetUsage:
    """验证 _record_round_budget_usage 的真实 usage 回填与估算回退。"""

    def test_record_round_budget_usage_backfills_real_usage(self):
        """提供真实 usage 时应回填 input/output/cache_read/cache_write 四维。"""
        agent = AIAgent()
        agent.budget_tracker = MagicMock()

        agent._record_round_budget_usage(
            user_input="你好",
            context={},
            round_content="回复内容",
            round_reasoning="",
            usage={
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "prompt_tokens_details": {"cached_tokens": 20},
            },
        )

        agent.budget_tracker.record_usage.assert_called_once_with(
            input_tokens=100,
            output_tokens=50,
            cache_read=20,
            cache_write=0,
        )

    def test_record_round_budget_usage_skips_empty_usage(self):
        """空 usage 字典不应进入回填分支，应回退到估算。"""
        agent = AIAgent()
        agent.budget_tracker = MagicMock()

        agent._record_round_budget_usage(
            user_input="你好",
            context={},
            round_content="这是一段较长的回复内容",
            round_reasoning="",
            usage={},
        )

        assert agent.budget_tracker.record_usage.called
        kwargs = agent.budget_tracker.record_usage.call_args.kwargs
        # 估算分支只回填 input/output 两维，cache 维度为 0
        assert kwargs.get("cache_read", 0) == 0
        assert kwargs.get("cache_write", 0) == 0
        assert kwargs["output_tokens"] >= 1

    def test_record_round_budget_usage_estimates_without_usage(self):
        """usage 完全缺失时应基于文本启发式估算。"""
        agent = AIAgent()
        agent.budget_tracker = MagicMock()

        agent._record_round_budget_usage(
            user_input="你好",
            context={},
            round_content="回复内容",
            round_reasoning="",
        )

        agent.budget_tracker.record_usage.assert_called_once()
        kwargs = agent.budget_tracker.record_usage.call_args.kwargs
        assert kwargs["input_tokens"] >= 1
        assert kwargs["output_tokens"] >= 1


# ==================== process_stream 取消处理测试 ====================


class TestProcessStreamCancellation:
    """验证 process_stream 对 CancelledError 的显式终态事件转换。"""

    @pytest.mark.asyncio
    async def test_process_stream_cancelled_yields_cancelled_event(self):
        """process_stream 捕获 CancelledError 时应产出 cancelled 终态事件并保持取消语义。"""
        agent = AIAgent()

        async def noop(*args, **kwargs):
            return None

        async def noop_gen(*args, **kwargs):
            if False:
                yield

        async def fake_build_session_history(user_input, context, session_id, _ttft_session_id, _ttft_t0, state):
            state["effective_user_input"] = user_input
            if False:
                yield

        async def raise_cancelled(*args, **kwargs):
            if False:
                yield
            raise asyncio.CancelledError()

        agent._handle_magic_command_or_yield = noop_gen
        agent._prepare_role_and_capabilities = noop
        agent._build_session_history = fake_build_session_history
        agent.turn_coordinator.prepare_turn = AsyncMock(return_value=(None, None, None))
        fake_orchestrator = MagicMock()
        fake_orchestrator.run_tool_calls_loop = raise_cancelled
        fake_orchestrator.finalize = AsyncMock()
        agent._stream_orchestrator = fake_orchestrator

        events = []
        with pytest.raises(asyncio.CancelledError):
            async for event in agent.process_stream("你好", {"session_id": "session-cancel-test"}):
                events.append(event)

        assert any(event.get("type") == "cancelled" for event in events)
        # 取消后仍应完成清理流程
        fake_orchestrator.finalize.assert_awaited_once()


# ==================== 流式 max_output_tokens 恢复链测试 ====================


class TestStreamOutputLimitRecovery:
    """验证 _call_llm_api_stream 的 length 截断恢复链（升级 max_tokens + 注入恢复消息）。"""

    @pytest.mark.asyncio
    async def test_call_llm_api_stream_recovers_from_length_finish_reason(self, monkeypatch):
        """finish_reason=length 时应升级 max_tokens 到 64k 并注入恢复消息重试。"""
        import core.execution_model_runtime as runtime_module
        from core.execution_model_runtime import ExecutionModelRuntimeMixin

        runtime = ExecutionModelRuntimeMixin()

        def fake_resolve(context):
            # 经 asyncio.to_thread 调用，必须是同步函数
            return {
                "ok": True,
                "provider": "openai",
                "model": "gpt-4o-mini",
                "api_endpoint": "https://api.openai.com",
                "api_key": "test-key",
                "max_tokens": 8192,
                "request_id": "req-1",
            }

        runtime._resolve_llm_configuration = fake_resolve
        runtime._build_messages_with_history = lambda prompt, context: [{"role": "user", "content": prompt}]
        runtime._resolve_max_tokens = lambda resolved: resolved.get("max_tokens") or 8192

        calls = []

        async def fake_stream_callable(**kwargs):
            calls.append({"max_tokens": kwargs.get("max_tokens"), "messages": list(kwargs.get("messages", []))})
            if len(calls) == 1:
                yield {"content": "前半段", "reasoning_content": ""}
                yield {"content": "", "reasoning_content": "", "finish_reason": "length"}
                return
            yield {"content": "后半段", "reasoning_content": ""}
            yield {"content": "", "reasoning_content": "", "finish_reason": "stop"}

        runtime._get_llm_stream_callable = lambda: fake_stream_callable

        class FakeBreaker:
            async def acquire(self):
                return None

            async def record_success(self):
                return None

            async def record_failure(self, exc):
                return None

        monkeypatch.setattr(
            runtime_module,
            "get_circuit_breaker",
            AsyncMock(return_value=FakeBreaker()),
        )
        monkeypatch.setattr(
            runtime_module,
            "record_model_service_metric",
            lambda *args, **kwargs: None,
        )

        chunks = []
        async for chunk in runtime._call_llm_api_stream("你好", {}):
            chunks.append(chunk)

        # 第一次调用使用默认 8k，length 截断后升级到 64k 重试
        assert calls[0]["max_tokens"] == 8192
        assert calls[1]["max_tokens"] == 64_000
        # 恢复消息已注入第二次请求
        assert any(
            "Output token limit hit" in str(m.get("content", ""))
            for m in calls[1]["messages"]
        )
        # 两次调用的内容被完整拼接透传
        full_content = "".join(c.get("content", "") for c in chunks)
        assert "前半段" in full_content
        assert "后半段" in full_content

    @pytest.mark.asyncio
    async def test_call_llm_api_stream_gives_up_after_three_length_retries(self, monkeypatch):
        """length 截断连续发生 3 次后应放弃恢复，透传最终 finish_reason=length。"""
        import core.execution_model_runtime as runtime_module
        from core.execution_model_runtime import ExecutionModelRuntimeMixin

        runtime = ExecutionModelRuntimeMixin()

        def fake_resolve(context):
            # 经 asyncio.to_thread 调用，必须是同步函数
            return {
                "ok": True,
                "provider": "openai",
                "model": "gpt-4o-mini",
                "api_endpoint": "https://api.openai.com",
                "api_key": "test-key",
                "max_tokens": 8192,
                "request_id": "req-2",
            }

        runtime._resolve_llm_configuration = fake_resolve
        runtime._build_messages_with_history = lambda prompt, context: [{"role": "user", "content": prompt}]
        runtime._resolve_max_tokens = lambda resolved: resolved.get("max_tokens") or 8192
        call_count = 0

        async def fake_stream_callable(**kwargs):
            nonlocal call_count
            call_count += 1

            yield {"content": f"第{call_count}段", "reasoning_content": ""}
            yield {"content": "", "reasoning_content": "", "finish_reason": "length"}

        runtime._get_llm_stream_callable = lambda: fake_stream_callable

        class FakeBreaker:
            async def acquire(self):
                return None

            async def record_success(self):
                return None

            async def record_failure(self, exc):
                return None

        monkeypatch.setattr(
            runtime_module,
            "get_circuit_breaker",
            AsyncMock(return_value=FakeBreaker()),
        )
        monkeypatch.setattr(
            runtime_module,
            "record_model_service_metric",
            lambda *args, **kwargs: None,
        )

        chunks = []
        async for chunk in runtime._call_llm_api_stream("你好", {}):
            chunks.append(chunk)

        # 1 次原始请求 + 3 次升级重试 = 4 次调用
        assert call_count == 4
        # 最后一次仍为 length，透传真实 finish_reason 供上层状态机决策
        assert any(c.get("finish_reason") == "length" for c in chunks)
