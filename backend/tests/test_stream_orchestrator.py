"""StreamOrchestrator 的工具轮次编排测试。"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.agent_execution_context import RoundState
from core.stream_orchestrator import StreamOrchestrator
from core.tool_dispatcher import ToolCallContext, ToolDispatcher
from core.tool_event_emitter import ToolEventEmitter


class EarlyExit(Exception):
    """测试用流式提前退出信号。"""


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

    with patch("core.task_runtime.hook_dispatcher.hook_dispatcher") as hook_dispatcher:
        hook_dispatcher.dispatch = AsyncMock()
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
