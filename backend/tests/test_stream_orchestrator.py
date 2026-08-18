"""StreamOrchestrator 的工具轮次编排测试。"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.agent_execution_context import RoundState
from core.agent_state import AgentState
from core.stream_orchestrator import StreamOrchestrator
from core.tool_dispatcher import ToolCallContext, ToolDispatcher
from core.tool_event_emitter import ToolEventEmitter
from core.tool_registry import ToolDefinition, tool_registry as global_tool_registry


class EarlyExit(Exception):
    """测试用流式提前退出信号。"""


def _build_orchestrator(executor, budget_tracker, record_budget_usage=None):
    """构造最小化 StreamOrchestrator，便于单测。"""
    return StreamOrchestrator(
        executor,
        MagicMock(),
        MagicMock(),
        MagicMock(),
        EarlyExit,
        budget_tracker,
        MagicMock(),
        record_budget_usage or MagicMock(),
        MagicMock(),
    )


def _build_state():
    """构造 run_tool_calls_loop 所需的共享状态。"""
    return {
        "effective_user_input": "测试",
        "round_count": 0,
        "full_content": "",
        "full_reasoning": "",
        "accumulated_tool_events": [],
        "user_input": "测试",
        "final_only_mode": False,
    }


def _build_budget_tracker():
    """构造不触发预算退出的 mock 预算追踪器。"""
    budget_tracker = MagicMock()
    budget_tracker.is_near_completion.return_value = False
    budget_tracker.is_diminishing.return_value = False
    return budget_tracker


# ==================== finish_reason 状态映射测试 ====================


def test_advance_state_machine_length_returns_continue_compact():
    """透传 finish_reason=length 时应返回 CONTINUE_COMPACT 并触发工具结果预算截断事件。"""
    orchestrator = _build_orchestrator(MagicMock(), _build_budget_tracker())
    state = _build_state()
    round_state = RoundState(1, "", "", state, "测试")

    state_machine, status_event = orchestrator._advance_state_machine(
        round_state, False, 10, {}, finish_reason="length",
    )

    assert state_machine is AgentState.CONTINUE_COMPACT
    assert status_event is not None
    assert status_event["type"] == "status"
    assert status_event["phase"] == "compacting"


def test_advance_state_machine_content_filter_returns_terminal_refusal():
    """透传 finish_reason=content_filter 时应返回 TERMINAL_REFUSAL（模型拒绝）。"""
    orchestrator = _build_orchestrator(MagicMock(), _build_budget_tracker())
    state = _build_state()
    round_state = RoundState(1, "", "", state, "测试")

    state_machine, _ = orchestrator._advance_state_machine(
        round_state, False, 10, {}, finish_reason="content_filter",
    )

    assert state_machine is AgentState.TERMINAL_REFUSAL


def test_advance_state_machine_content_filter_emits_refused_event():
    """模型拒绝（content_filter）终态应产出可观测的 refused 原因事件。"""
    orchestrator = _build_orchestrator(MagicMock(), _build_budget_tracker())
    state = _build_state()
    round_state = RoundState(1, "", "", state, "测试")

    _, status_event = orchestrator._advance_state_machine(
        round_state, False, 10, {}, finish_reason="content_filter",
    )

    assert status_event is not None
    assert status_event["type"] == "status"
    assert status_event["phase"] == "refused"


def test_advance_state_machine_max_rounds_emits_max_rounds_event():
    """达到最大轮次上限终态应产出可观测的 max_rounds 原因事件。"""
    orchestrator = _build_orchestrator(MagicMock(), _build_budget_tracker())
    state = _build_state()
    round_state = RoundState(1, "", "", state, "测试")

    # current_round 达到 max_rounds 时无论 finish_reason 都返回 TERMINAL_MAX_ROUNDS
    state_machine, status_event = orchestrator._advance_state_machine(
        round_state, True, 1, {}, finish_reason="stop",
    )

    assert state_machine is AgentState.TERMINAL_MAX_ROUNDS
    assert status_event is not None
    assert status_event["phase"] == "max_rounds"


def test_terminal_status_event_end_turn_returns_none():
    """正常结束（TERMINAL_END_TURN）不产出额外原因事件。"""
    orchestrator = _build_orchestrator(MagicMock(), _build_budget_tracker())
    assert orchestrator._terminal_status_event(AgentState.TERMINAL_END_TURN) is None
    assert orchestrator._terminal_status_event(AgentState.CONTINUE_TOOL_CALLS) is None


def test_advance_state_machine_defaults_to_stop_without_finish_reason():
    """未透传 finish_reason 且无工具调用时应回退到 stop（TERMINAL_END_TURN）。"""
    orchestrator = _build_orchestrator(MagicMock(), _build_budget_tracker())
    state = _build_state()
    round_state = RoundState(1, "", "", state, "测试")

    state_machine, _ = orchestrator._advance_state_machine(
        round_state, False, 10, {},
    )

    assert state_machine is AgentState.TERMINAL_END_TURN


def test_advance_state_machine_tool_calls_takes_priority():
    """检测到工具调用时即使透传了其他 finish_reason 也应推进为 CONTINUE_TOOL_CALLS。"""
    orchestrator = _build_orchestrator(MagicMock(), _build_budget_tracker())
    state = _build_state()
    round_state = RoundState(1, "", "", state, "测试")

    state_machine, _ = orchestrator._advance_state_machine(
        round_state, True, 10, {}, finish_reason="stop",
    )

    assert state_machine is AgentState.CONTINUE_TOOL_CALLS


# ==================== 流式错误恢复测试 ====================


@pytest.mark.asyncio
async def test_run_tool_calls_loop_recovers_from_model_error_and_succeeds():
    """模型服务错误应触发 fallback model 恢复，恢复后正常输出内容。"""
    executor = MagicMock()
    call_count = 0

    async def fake_stream(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            yield {"error": {"code": "model_service_unavailable", "status_code": 503, "message": "上游不可用"}}
            return
        yield {"content": "恢复后的回复", "reasoning_content": ""}
        yield {"content": "", "reasoning_content": "", "finish_reason": "stop"}

    executor._call_llm_api_stream = fake_stream
    budget_tracker = _build_budget_tracker()
    record_budget_usage = MagicMock()
    orchestrator = _build_orchestrator(executor, budget_tracker, record_budget_usage)
    context = {"model_config_override": {"fallback_model": "gpt-4o-mini"}}
    state = _build_state()

    events = [event async for event in orchestrator.run_tool_calls_loop(context, None, "session-1", state)]

    assert context["model"] == "gpt-4o-mini"
    contents = [e.get("content", "") for e in events if e.get("type") == "chunk"]
    assert "".join(contents) == "恢复后的回复"
    assert state["full_content"] == "恢复后的回复"
    assert call_count == 2


@pytest.mark.asyncio
async def test_run_tool_calls_loop_surfaces_error_after_recovery_exhausted():
    """恢复策略用尽后错误必须表面化（yield error + 提前退出），不得静默吞掉。"""
    executor = MagicMock()

    async def fake_stream(*args, **kwargs):
        yield {"error": {"code": "model_service_unavailable", "status_code": 503, "message": "持续不可用"}}

    executor._call_llm_api_stream = fake_stream
    orchestrator = _build_orchestrator(executor, _build_budget_tracker())
    state = _build_state()

    collected = []
    with pytest.raises(EarlyExit):
        async for event in orchestrator.run_tool_calls_loop({}, None, "session-1", state):
            collected.append(event)

    assert collected[-1]["type"] == "error"
    assert collected[-1]["error"]["status_code"] == 503


@pytest.mark.asyncio
async def test_run_tool_calls_loop_surfaces_error_when_content_already_emitted():
    """已产生内容后再遇错误不得重试恢复（避免重复内容），直接表面化。"""
    executor = MagicMock()

    async def fake_stream(*args, **kwargs):
        yield {"content": "已经说了半句", "reasoning_content": ""}
        yield {"error": {"code": "model_service_rate_limit", "status_code": 429, "message": "限流"}}

    executor._call_llm_api_stream = fake_stream
    orchestrator = _build_orchestrator(executor, _build_budget_tracker())
    state = _build_state()

    collected = []
    with pytest.raises(EarlyExit):
        async for event in orchestrator.run_tool_calls_loop({}, None, "session-1", state):
            collected.append(event)

    assert any(e.get("type") == "chunk" for e in collected)
    assert collected[-1]["type"] == "error"


# ==================== finish_reason 与 usage 透传测试 ====================


@pytest.mark.asyncio
async def test_run_tool_calls_loop_propagates_finish_reason_and_usage():
    """流式透传的 finish_reason 与 usage 应到达状态机与预算记录。"""
    executor = MagicMock()

    async def fake_stream(*args, **kwargs):
        yield {"content": "输出内容", "reasoning_content": ""}
        yield {"content": "", "reasoning_content": "", "finish_reason": "length", "usage": {"prompt_tokens": 10, "completion_tokens": 5}}

    executor._call_llm_api_stream = fake_stream
    budget_tracker = _build_budget_tracker()
    record_budget_usage = MagicMock()
    orchestrator = _build_orchestrator(executor, budget_tracker, record_budget_usage)
    # max_tool_call_rounds 限制为 3，避免 length 状态下无限循环
    context = {"max_tool_call_rounds": 3}
    state = _build_state()

    events = [event async for event in orchestrator.run_tool_calls_loop(context, None, "session-1", state)]

    assert any(e.get("content") == "输出内容" for e in events)
    # 预算记录应收到透传的真实 usage
    usage_kwargs = record_budget_usage.call_args.kwargs
    assert usage_kwargs["usage"] == {"prompt_tokens": 10, "completion_tokens": 5}


# ==================== 原有工具轮次测试 ====================


@pytest.mark.asyncio
async def test_stream_orchestrator_executes_tool_and_persists_messages():
    """常规工具轮次应输出事件并持久化 assistant 与 tool 消息。"""
    executor = MagicMock()
    executor._execute_tool_call = AsyncMock(return_value={
        "ok": True,
        "result": {"status": "success", "message": "完成"},
    })
    executor.build_assistant_tool_call_message.return_value = {"role": "assistant"}
    executor._build_tool_message.return_value = {"role": "tool"}
    feedback = MagicMock()
    feedback.update_memory = AsyncMock()
    dispatcher = ToolDispatcher(executor, None, EarlyExit)
    emitter = ToolEventEmitter()
    budget_tracker = MagicMock()
    budget_tracker.is_near_completion.return_value = False
    orchestrator = StreamOrchestrator(
        executor,
        feedback,
        dispatcher,
        emitter,
        EarlyExit,
        budget_tracker,
        MagicMock(),
        MagicMock(),
        MagicMock(),
    )
    context: dict = {}
    state = {
        "accumulated_tool_events": [],
        "user_input": "测试",
        "full_reasoning": "",
    }
    tool_calls = [{
        "id": "call-1",
        "function": {"name": "builtin_demo", "arguments": "{}"},
    }]

    with patch("core.hook_manager.hook_manager") as hook_mgr:
        hook_mgr.trigger = AsyncMock()
        events = [event async for event in orchestrator.handle_tool_calls_in_round(
            tool_calls,
            context,
            None,
            "session-1",
            RoundState(1, "", "", state, "测试"),
        )]

    assert [event["tool"]["status"] for event in events] == ["running", "completed"]
    assert context["_tool_messages"] == [{"role": "assistant"}, {"role": "tool"}]
    assert state["accumulated_tool_events"][0]["name"] == "builtin_demo"
    feedback.update_memory.assert_not_awaited()


@pytest.mark.asyncio
async def test_regular_tool_timeout_does_not_block_agent_loop():
    """常规工具超时后必须返回结构化失败结果，不能阻塞整轮 Agent 执行。"""
    executor = MagicMock()
    blocker = asyncio.Event()

    async def never_finishes(*_args, **_kwargs):
        await blocker.wait()
        return {"ok": True}

    executor._execute_tool_call = never_finishes
    dispatcher = ToolDispatcher(executor, None, EarlyExit)
    call_context = ToolCallContext()
    tool_call = {
        "id": "call-timeout",
        "function": {"name": "builtin_demo", "arguments": '{"timeout": 0.01}'},
    }

    async for _ in dispatcher.dispatch(tool_call, {}, "session-timeout", call_context):
        pass

    assert call_context.result == {
        "ok": False,
        "error": "工具调用超时",
        "error_code": "tool_call_timeout",
        "tool_name": "builtin_demo",
    }


# ==================== 流式并发调度测试 ====================

_CONCURRENT_TOOL_NAMES = [
    "test_stream_read_a",
    "test_stream_read_b",
    "test_stream_write_a",
    "test_stream_write_b",
]


def _build_concurrent_orchestrator(executor):
    """构造含真实 dispatcher/emitter 的编排器，用于并发调度测试。"""
    feedback = MagicMock()
    feedback.update_memory = AsyncMock()
    dispatcher = ToolDispatcher(executor, None, EarlyExit)
    emitter = ToolEventEmitter()
    budget_tracker = MagicMock()
    budget_tracker.is_near_completion.return_value = False
    orchestrator = StreamOrchestrator(
        executor,
        feedback,
        dispatcher,
        emitter,
        EarlyExit,
        budget_tracker,
        MagicMock(),
        MagicMock(),
        MagicMock(),
    )
    return orchestrator, feedback


@pytest.fixture(autouse=True)
def _cleanup_concurrent_tools():
    """每个测试后清理并发调度测试注册的工具。"""
    yield
    for name in _CONCURRENT_TOOL_NAMES:
        global_tool_registry.unregister(name)


def _make_counting_executor():
    """构造记录最大并行调用数的工具执行器。"""
    executor = MagicMock()
    active = 0
    max_active = 0

    async def fake_execute(tool_call, context, on_subagent_event=None):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        try:
            await asyncio.sleep(0.05)
        finally:
            active -= 1
        name = tool_call.get("function", {}).get("name")
        return {"ok": True, "result": {"name": name}, "tool_name": name}

    executor._execute_tool_call = fake_execute
    executor.build_assistant_tool_call_message.return_value = {"role": "assistant"}
    executor._build_tool_message.return_value = {"role": "tool"}
    return executor, lambda: max_active


@pytest.mark.asyncio
async def test_stream_orchestrator_concurrent_executes_read_only_tools_concurrently():
    """多个只读并发安全工具应在单轮内并发执行（最大并行调用数 > 1）。"""
    global_tool_registry.register(ToolDefinition(
        name="test_stream_read_a",
        description="只读并发安全工具 A",
        is_read_only=True,
        is_concurrency_safe=True,
    ))
    global_tool_registry.register(ToolDefinition(
        name="test_stream_read_b",
        description="只读并发安全工具 B",
        is_read_only=True,
        is_concurrency_safe=True,
    ))
    executor, get_max_active = _make_counting_executor()
    orchestrator, feedback = _build_concurrent_orchestrator(executor)
    context: dict = {}
    state = {
        "accumulated_tool_events": [],
        "user_input": "测试",
        "full_reasoning": "",
    }
    tool_calls = [
        {"id": "read-a", "function": {"name": "test_stream_read_a", "arguments": "{}"}},
        {"id": "read-b", "function": {"name": "test_stream_read_b", "arguments": "{}"}},
    ]

    with patch("core.hook_manager.hook_manager") as hook_mgr:
        hook_mgr.trigger = AsyncMock()
        events = [event async for event in orchestrator.handle_tool_calls_in_round(
            tool_calls, context, None, "session-1",
            RoundState(1, "", "", state, "测试"),
        )]

    # 两个只读并发安全工具应并发执行
    assert get_max_active() == 2, f"期望两个只读工具并发执行，实际最大并行数: {get_max_active()}"
    # 事件语义：先按声明顺序发射 running，再按完成顺序发射 completed
    statuses = [e["tool"]["status"] for e in events if e.get("type") == "tool"]
    assert statuses[:2] == ["running", "running"]
    assert statuses.count("running") == 2
    assert statuses.count("completed") == 2
    # 工具消息按声明顺序稳定产出（1 assistant + 2 tool）
    assert len(context["_tool_messages"]) == 3
    feedback.update_memory.assert_not_awaited()


@pytest.mark.asyncio
async def test_stream_orchestrator_serializes_non_concurrency_safe_tools():
    """非并发安全工具（写入类）应在单轮内串行执行（最大并行调用数为 1）。"""
    global_tool_registry.register(ToolDefinition(
        name="test_stream_write_a",
        description="写工具 A",
        is_read_only=False,
        is_concurrency_safe=False,
    ))
    global_tool_registry.register(ToolDefinition(
        name="test_stream_write_b",
        description="写工具 B",
        is_read_only=False,
        is_concurrency_safe=False,
    ))
    executor, get_max_active = _make_counting_executor()
    orchestrator, feedback = _build_concurrent_orchestrator(executor)
    context: dict = {}
    state = {
        "accumulated_tool_events": [],
        "user_input": "测试",
        "full_reasoning": "",
    }
    tool_calls = [
        {"id": "write-a", "function": {"name": "test_stream_write_a", "arguments": "{}"}},
        {"id": "write-b", "function": {"name": "test_stream_write_b", "arguments": "{}"}},
    ]

    with patch("core.hook_manager.hook_manager") as hook_mgr:
        hook_mgr.trigger = AsyncMock()
        events = [event async for event in orchestrator.handle_tool_calls_in_round(
            tool_calls, context, None, "session-1",
            RoundState(1, "", "", state, "测试"),
        )]

    # 非并发安全工具应串行执行
    assert get_max_active() == 1, f"期望写工具串行执行，实际最大并行数: {get_max_active()}"
    statuses = [e["tool"]["status"] for e in events if e.get("type") == "tool"]
    assert statuses.count("running") == 2
    assert statuses.count("completed") == 2
    assert len(context["_tool_messages"]) == 3
    feedback.update_memory.assert_not_awaited()
