"""
验证 wave2+wave3 拆分出的 7 个流式子方法的异常路径与边界条件。

覆盖方法：
- _run_tool_calls_loop：取消信号传播、预算耗尽正常退出
- _dispatch_tool_call：ask_user_port 缺失抛 RuntimeError、常规 builtin 工具分发
- _finalize_stream：main_completed=False 时仍要 abort + unregister
- _handle_magic_command_or_yield：魔法命令分发与提前退出
- _prepare_role_and_capabilities：角色引擎加载与能力注入
- _build_session_history：对话历史构建、压缩状态事件、长期记忆检索
- _emit_tool_post_events：PostToolUse 钩子与通知事件派发
"""

import json
import time

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from core.agent import AIAgent, _StreamEarlyExit
from core.agent_execution_context import StreamFinalizationContext
from core.task_runtime.hook_dispatcher import HOOK_POST_TOOL_USE
from core.tool_event_emitter import ToolEventEmitter
from core.tool_dispatcher import ToolCallContext, ToolDispatcher
from core.stream_orchestrator import StreamOrchestrator


def make_agent() -> AIAgent:
    """通过正式构造入口创建 AIAgent，并替换当前测试所需依赖。

    所有子引擎和 mock 依赖均显式注入，禁止绕过生产构造契约。
    """
    agent = AIAgent()
    agent.executor = AsyncMock()
    agent.turn_coordinator = AsyncMock()
    agent.feedback = AsyncMock()
    agent.skill_engine = AsyncMock()
    agent.budget_tracker = MagicMock()
    agent.budget_tracker.is_near_completion.return_value = False
    agent.budget_tracker.max_input_tokens = 8000
    agent.budget_tracker.usage_ratio.return_value = 0.5
    agent.budget_tracker.total_used.return_value = 4000
    agent.budget_tracker.remaining.return_value = 4000
    agent.content_replacement_state = {}
    agent._ask_user_port = None
    agent._tool_dispatcher = ToolDispatcher(
        agent.executor, agent._ask_user_port, _StreamEarlyExit,
    )
    agent.memory_manager = None
    agent.root_abort_controller = None
    agent._tool_event_emitter = ToolEventEmitter()
    agent.unregister_task = MagicMock()
    agent._stream_orchestrator = StreamOrchestrator(
        agent.executor,
        agent.feedback,
        agent._tool_dispatcher,
        agent._tool_event_emitter,
        _StreamEarlyExit,
        agent.budget_tracker,
        agent.content_replacement_state,
        MagicMock(),
        agent.unregister_task,
    )
    return agent


# ===== 1. _run_tool_calls_loop =====


@pytest.mark.asyncio
async def test_run_tool_calls_loop_yields_cancelled_and_raises_when_current_task_cancelled():
    """current_task.cancelled() 返回 True 时应 yield cancelled 事件并 raise _StreamEarlyExit。

    覆盖取消信号传播路径：进入 while 循环后立即检测到取消，应跳过 LLM 调用。
    """
    agent = make_agent()
    # budget_tracker 不接近耗尽，确保能进入 while 循环
    agent.budget_tracker.is_near_completion.return_value = False
    # executor._call_llm_api_stream 不应被调用（取消信号在调用前触发）
    agent.executor._call_llm_api_stream = AsyncMock()

    current_task = MagicMock()
    current_task.cancelled.return_value = True

    context = {"max_tool_call_rounds": 5}
    state = {
        "effective_user_input": "测试输入",
        "final_only_mode": False,
        "round_count": 0,
        "full_content": "",
        "full_reasoning": "",
        "accumulated_tool_events": [],
        "user_input": "测试输入",
    }

    events: list = []
    with pytest.raises(_StreamEarlyExit):
        async for event in agent._stream_orchestrator.run_tool_calls_loop(
            context,
            current_task,
            "session-id",
            state,
        ):
            events.append(event)

    # 断言：yield 了 cancelled 事件
    cancelled_events = [e for e in events if e.get("type") == "cancelled"]
    assert len(cancelled_events) == 1, f"期望 1 个 cancelled 事件，实际: {events}"
    assert cancelled_events[0]["content"] == ""
    # 断言：executor._call_llm_api_stream 未被调用（取消信号在 LLM 调用前触发）
    agent.executor._call_llm_api_stream.assert_not_called()
    # 断言：round_count 未增加（取消在自增前触发）
    assert state["round_count"] == 0


@pytest.mark.asyncio
async def test_run_tool_calls_loop_returns_normally_when_budget_near_completion():
    """budget_tracker.is_near_completion() 返回 True 时，while 循环不进入，方法正常返回。"""
    agent = make_agent()
    agent.budget_tracker.is_near_completion.return_value = True
    agent.executor._call_llm_api_stream = AsyncMock()

    context = {"max_tool_call_rounds": 5}
    state = {
        "effective_user_input": "测试输入",
        "final_only_mode": False,
        "round_count": 0,
        "full_content": "",
        "full_reasoning": "",
        "accumulated_tool_events": [],
        "user_input": "测试输入",
    }

    events: list = []
    async for event in agent._stream_orchestrator.run_tool_calls_loop(
        context,
        None,
        "session-id",
        state,
    ):
        events.append(event)

    # 断言：未 yield 任何事件
    assert events == [], f"期望无事件，实际: {events}"
    # 断言：executor._call_llm_api_stream 未被调用
    agent.executor._call_llm_api_stream.assert_not_called()
    # 断言：round_count 未增加
    assert state["round_count"] == 0


# ===== 2. _dispatch_tool_call =====


@pytest.mark.asyncio
async def test_dispatch_tool_call_raises_runtime_error_when_ask_user_port_is_none():
    """builtin_ask_user 工具且 ask_user_port 为 None 时应 raise RuntimeError。

    覆盖 ask_user 端口未注入的异常路径，期望异常消息明确指引 main.py lifespan 注入。
    """
    agent = make_agent()
    agent._ask_user_port = None

    tc = {
        "function": {"name": "builtin_ask_user", "arguments": "{}"},
        "id": "test-id",
    }
    context = {"user_id": "user-1", "session_id": "session-1"}
    tc_state = ToolCallContext()

    events: list = []
    with pytest.raises(RuntimeError, match="ask_user_port not configured"):
        async for event in agent._tool_dispatcher.dispatch(
            tc,
            context,
            "session-1",
            tc_state,
        ):
            events.append(event)

    # 断言：raise 前已 yield running 工具事件
    running_events = [
        e for e in events
        if e.get("type") == "tool" and e.get("tool", {}).get("status") == "running"
    ]
    assert len(running_events) == 1, f"期望 1 个 running 工具事件，实际: {events}"
    # 断言：tc_state 已记录 tool_name（在 raise 前完成）
    assert tc_state.tool_name == "builtin_ask_user"
    assert tc_state.tool_id == "test-id"


@pytest.mark.asyncio
async def test_dispatch_tool_call_dispatches_regular_builtin_tool():
    """常规 builtin 工具应通过 executor._execute_tool_call 执行并设置 tc_state.result。"""
    agent = make_agent()
    expected_result = {"ok": True, "result": {"status": "success"}}
    agent.executor._execute_tool_call = AsyncMock(return_value=expected_result)

    tc = {
        "function": {
            "name": "builtin_some_tool",
            "arguments": json.dumps({"key": "value"}, ensure_ascii=False),
        },
        "id": "test-id",
    }
    context = {"user_id": "user-1", "session_id": "session-1"}
    tc_state = ToolCallContext()

    events: list = []
    async for event in agent._tool_dispatcher.dispatch(
        tc,
        context,
        "session-1",
        tc_state,
    ):
        events.append(event)

    # 断言：yield 了 running 工具事件
    running_events = [
        e for e in events
        if e.get("type") == "tool" and e.get("tool", {}).get("status") == "running"
    ]
    assert len(running_events) == 1, f"期望 1 个 running 工具事件，实际: {events}"
    assert running_events[0]["tool"]["name"] == "builtin_some_tool"
    assert running_events[0]["tool"]["input"] == {"key": "value"}
    # 断言：executor._execute_tool_call 被调用
    agent.executor._execute_tool_call.assert_awaited_once_with(tc, context)
    # 断言：tc_state.result 被设置为 executor 返回值
    assert tc_state.result == expected_result
    # 断言：tc_state 已记录 tool_name / tool_id / func_args
    assert tc_state.tool_name == "builtin_some_tool"
    assert tc_state.tool_id == "test-id"
    assert tc_state.func_args == {"key": "value"}


# ===== 3. _finalize_stream =====


@pytest.mark.asyncio
async def test_finalize_stream_aborts_and_unregisters_when_main_not_completed():
    """main_completed=False（异常退出）时仍要 abort 根控制器并 unregister 任务。

    覆盖异常退出路径：finally 块必须始终执行清理，feedback.update_memory 不应被调用。
    """
    agent = make_agent()
    # 用独立 mock 引用，因为 _finalize_stream 调用 abort 后会将属性置 None
    mock_abort_controller = MagicMock()
    agent.root_abort_controller = mock_abort_controller
    agent.feedback.update_memory = AsyncMock()

    state = {
        "main_completed": False,
        "full_content": "",
        "full_reasoning": "",
        "accumulated_tool_events": [],
        "round_count": 0,
    }
    context = {"session_id": "session-1"}

    await agent._stream_orchestrator.finalize(
        StreamFinalizationContext(
            user_input="用户输入",
            context=context,
            state=state,
            started_at=time.time(),
            task_user_id="user-1",
            session_id="session-1",
            current_task=None,
            abort_controller=mock_abort_controller,
        )
    )
    agent.unregister_task.assert_called_once_with("user-1", "session-1", None)

    # 断言：feedback.update_memory 未被调用（main_completed=False 跳过 if 块）
    agent.feedback.update_memory.assert_not_awaited()
    # 断言：root_abort_controller.abort 被调用（通过独立 mock 引用断言）
    mock_abort_controller.abort.assert_called_once()


# ===== 4. _handle_magic_command_or_yield =====


@pytest.mark.asyncio
async def test_handle_magic_command_or_yield_dispatches_clear_command():
    """/clear 命令应 yield magic_command + context_cleared 事件并 raise _StreamEarlyExit。

    覆盖魔法命令分发路径：clears_context=True 时应额外 yield context_cleared 事件。
    """
    agent = make_agent()
    agent._check_and_handle_magic_command = AsyncMock(return_value={
        "is_command": True,
        "command_name": "clear",
        "success": True,
        "clears_context": True,
        "message": "上下文已清空",
    })

    context = {"session_id": "session-1"}
    events: list = []
    with pytest.raises(_StreamEarlyExit):
        async for event in agent._handle_magic_command_or_yield("/clear", context):
            events.append(event)

    # 断言：yield 了 magic_command 事件
    magic_events = [e for e in events if e.get("type") == "magic_command"]
    assert len(magic_events) == 1, f"期望 1 个 magic_command 事件，实际: {events}"
    assert magic_events[0]["command_name"] == "clear"
    # content 字段是 cmd_result 的 JSON 序列化
    parsed_content = json.loads(magic_events[0]["content"])
    assert parsed_content["command_name"] == "clear"
    assert parsed_content["clears_context"] is True

    # 断言：yield 了 context_cleared 事件（因 clears_context=True）
    cleared_events = [e for e in events if e.get("type") == "context_cleared"]
    assert len(cleared_events) == 1, f"期望 1 个 context_cleared 事件，实际: {events}"
    assert cleared_events[0]["content"] == ""

    # 断言：_check_and_handle_magic_command 被正确调用
    agent._check_and_handle_magic_command.assert_awaited_once_with("/clear", context)


# ===== 5. _prepare_role_and_capabilities =====


@pytest.mark.asyncio
async def test_prepare_role_and_capabilities_injects_role_and_capabilities():
    """正常调用时应加载角色引擎、注入角色信息到 context 并触发能力注入。"""
    agent = make_agent()
    agent._prepare_context = MagicMock()
    agent._inject_runtime_capabilities = AsyncMock()
    context = {
        "role_id": "test-role",
        "db": MagicMock(),
        "session_id": "session-1",
    }

    with (
        patch("core.agent.RoleEngine") as MockRoleEngine,
        patch("core.agent.build_multimodal_context") as mock_multimodal,
        patch("core.agent.build_thinking_context") as mock_thinking,
    ):
        mock_engine = MockRoleEngine.return_value
        mock_engine.load_role.return_value = {"id": "test-role", "name": "测试角色"}
        # apply_role_to_context 返回带角色信息的新 context
        mock_engine.apply_role_to_context.return_value = {
            **context, "role_name": "测试角色",
        }

        await agent._prepare_role_and_capabilities(
            "用户输入", context, "ttft-session", time.time()
        )

        # 断言：RoleEngine 用 context['db'] 实例化
        MockRoleEngine.assert_called_once_with(db=context["db"])
        # 断言：load_role 用 role_id 调用
        mock_engine.load_role.assert_called_once_with("test-role")
        # 断言：apply_role_to_context 被调用
        mock_engine.apply_role_to_context.assert_called_once()

    # 断言：_prepare_context 被调用
    agent._prepare_context.assert_called_once_with("用户输入", context)
    # 断言：_inject_runtime_capabilities 被调用，且参数 context 包含角色信息
    agent._inject_runtime_capabilities.assert_awaited_once()
    injected_ctx = agent._inject_runtime_capabilities.call_args[0][0]
    assert injected_ctx.get("role_name") == "测试角色"
    # 断言：多模态与思考上下文构建被调用
    mock_multimodal.assert_called_once()
    mock_thinking.assert_called_once()


# ===== 6. _build_session_history =====


@pytest.mark.asyncio
async def test_build_session_history_builds_history_with_memories():
    """正常调用时应构建对话历史、触发压缩状态事件、检索长期记忆。

    覆盖消息数 > 40 时 yield compressing 状态事件 + 长期记忆检索成功路径。
    """
    agent = make_agent()
    agent.memory_manager = MagicMock()  # truthy，触发记忆检索分支

    # 构造 41 条消息，触发 > 40 条的 compressing 状态事件
    fake_history = [{"role": "user", "content": f"msg-{i}"} for i in range(41)]
    compressed_history = fake_history[:20]  # 压缩后剩 20 条

    agent._build_conversation_history = AsyncMock(return_value=fake_history)
    agent._auto_compress_context = AsyncMock(return_value=compressed_history)
    agent._retrieve_relevant_memories = AsyncMock(return_value=[
        {
            "id": "mem-1",
            "content": "记忆1",
            "importance": 0.8,
            "confidence": 0.9,
            "quality_score": 0.85,
        },
        {
            "id": "mem-2",
            "content": "记忆2",
            "importance": 0.7,
            "confidence": 0.85,
            "quality_score": 0.8,
        },
    ])

    context = {
        "session_id": "session-1",
        "user_id": "user-1",
        "model": "test-model",
        "retrieve_long_term_memory": True,
    }
    state: dict = {}

    events: list = []
    async for event in agent._build_session_history(
        "用户输入", context, "session-1", "ttft-session", time.time(), state
    ):
        events.append(event)

    # 断言：yield 了 compressing 状态事件（因为消息数 41 > 40）
    compressing_events = [
        e for e in events
        if e.get("type") == "status" and e.get("phase") == "compressing"
    ]
    assert len(compressing_events) == 1, f"期望 1 个 compressing 事件，实际: {events}"
    # 断言：_build_conversation_history 用 session_id 调用
    agent._build_conversation_history.assert_awaited_once_with("session-1")
    # 断言：_auto_compress_context 被调用
    agent._auto_compress_context.assert_awaited_once()
    # 断言：context["conversation_history"] 被设置为压缩后的列表
    assert context["conversation_history"] == compressed_history
    # 断言：长期记忆被检索并注入 context
    agent._retrieve_relevant_memories.assert_awaited_once()
    assert "vector_retrieved_memories" in context
    assert len(context["vector_retrieved_memories"]) == 2
    # 断言：state["effective_user_input"] 被设置为原用户输入（无 continuation 场景）
    assert state["effective_user_input"] == "用户输入"


# ===== 7. _emit_tool_post_events =====


@pytest.mark.asyncio
async def test_emit_tool_post_events_triggers_hooks_and_dispatches_events():
    """工具执行完成后应触发 PostToolUse 钩子并派发 completed 工具事件 + 通知事件。"""
    agent = make_agent()

    tc = {
        "function": {
            "name": "builtin_notify",
            "arguments": json.dumps({"title": "T"}, ensure_ascii=False),
        },
        "id": "test-id",
    }
    context = {"session_id": "session-1", "user_id": "user-1"}
    tc_state = ToolCallContext()
    tc_state.tool_name = "builtin_notify"
    tc_state.tool_id = "test-id"
    tc_state.tool_kind = "tool"
    tc_state.result = {
        "ok": True,
        "result": {
            "title": "通知标题",
            "body": "通知正文",
            "channels": ["email"],
            "message": "通知消息",
        },
    }
    accumulated: list = []

    with patch("core.task_runtime.hook_dispatcher.hook_dispatcher") as mock_dispatcher:
        mock_dispatcher.dispatch = AsyncMock()

        events: list = []
        async for event in agent._tool_event_emitter.emit(
            tc, context, tc_state, accumulated
        ):
            events.append(event)

        # 断言：PostToolUse 钩子被派发
        mock_dispatcher.dispatch.assert_awaited_once()
        dispatch_args = mock_dispatcher.dispatch.call_args
        # 第一个位置参数是事件类型常量
        assert dispatch_args.args[0] == HOOK_POST_TOOL_USE
        # 第二个位置参数是 payload
        payload = dispatch_args.args[1]
        assert payload["tool_name"] == "builtin_notify"
        assert payload["result"] == tc_state.result
        # tool_args 应从 JSON 字符串解析得到
        assert payload["tool_args"] == {"title": "T"}

    # 断言：yield 了 completed 工具事件
    completed_events = [
        e for e in events
        if e.get("type") == "tool" and e.get("tool", {}).get("status") == "completed"
    ]
    assert len(completed_events) == 1, f"期望 1 个 completed 工具事件，实际: {events}"
    assert completed_events[0]["tool"]["name"] == "builtin_notify"
    assert completed_events[0]["tool"]["output"] == tc_state.result["result"]

    # 断言：yield 了 notification 事件（builtin_notify + ok=True）
    notification_events = [e for e in events if e.get("type") == "notification"]
    assert len(notification_events) == 1, f"期望 1 个 notification 事件，实际: {events}"
    assert notification_events[0]["title"] == "通知标题"
    assert notification_events[0]["body"] == "通知正文"
    assert notification_events[0]["channels"] == ["email"]
    assert notification_events[0]["message"] == "通知消息"

    # 断言：accumulated_tool_events 累积了 1 个事件
    assert len(accumulated) == 1
    assert accumulated[0]["name"] == "builtin_notify"
    assert accumulated[0]["status"] == "completed"


@pytest.mark.asyncio
async def test_tool_event_emitter_dispatches_todo_and_background_subagent_events():
    """事件派发器应通过注册表生成 Todo 与后台子代理事件。"""
    emitter = ToolEventEmitter()

    todo_state = ToolCallContext(
        tool_name="task_todo_write",
        tool_id="todo-id",
        tool_kind="task",
        result={
            "ok": True,
            "result": {"todos": [{"id": "todo-1"}], "counts": {"total": 1}},
        },
    )
    todo_events = [event async for event in emitter._iter_followup_events(todo_state)]
    assert todo_events == [{
        "type": "todo_update",
        "todos": [{"id": "todo-1"}],
        "counts": {"total": 1},
        "summary": "",
    }]

    subagent_state = ToolCallContext(
        tool_name="task_spawn_agent",
        spawn_agent_type="Explore",
        spawn_description="检查代码",
        result={
            "ok": True,
            "result": {"agent_id": "agent-1", "run_mode": "background"},
        },
    )
    subagent_events = [
        event async for event in emitter._iter_followup_events(subagent_state)
    ]
    assert subagent_state.background_subagents_spawned is True
    assert subagent_events[0]["type"] == "subagent_start"
    assert subagent_events[0]["agent_id"] == "agent-1"
