"""StreamOrchestrator 的工具轮次编排测试。"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.agent_execution_context import RoundState
from core.stream_orchestrator import StreamOrchestrator
from core.tool_dispatcher import ToolDispatcher
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
