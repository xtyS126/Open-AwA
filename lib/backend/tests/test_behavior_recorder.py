import asyncio
from typing import Any

import pytest

from billing.token_counter import TokenBreakdown
from core.behavior_recorder import BehaviorRecorder


class _Recorder:
    def __init__(self) -> None:
        self.entries: list[dict[str, Any]] = []

    async def record(self, *args: Any, **kwargs: Any) -> None:
        self.entries.append(args[0] if args else kwargs)


async def _identity(coro: Any) -> Any:
    return await coro


@pytest.mark.asyncio
async def test_schedule_records_behavior_and_conversation() -> None:
    behavior = _Recorder()
    conversation = _Recorder()
    completed = []
    recorder = BehaviorRecorder(
        behavior,
        conversation,
        _identity,
        lambda task: completed.append(task),
    )

    recorder.schedule(
        node_type="llm_call",
        user_message="测试消息",
        context={"user_id": "user-1", "session_id": "session-1"},
        db_session=None,
        llm_output={"response": "完成"},
    )
    await asyncio.sleep(0)

    assert behavior.entries
    assert conversation.entries == [{
        "node_type": "llm_call",
        "session_id": "session-1",
        "user_message": "测试消息",
        "user_id": "user-1",
        "provider": None,
        "model": None,
        "llm_input": None,
        "llm_output": {"response": "完成"},
        "llm_tokens_used": None,
        "execution_duration_ms": None,
        "status": "success",
        "error_message": None,
        "metadata": None,
    }]
    assert all(task.done() for task in completed)


@pytest.mark.asyncio
async def test_schedule_respects_isolated_execution() -> None:
    behavior = _Recorder()
    conversation = _Recorder()
    recorder = BehaviorRecorder(behavior, conversation, _identity, lambda task: None)

    recorder.schedule(
        node_type="llm_call",
        user_message="测试消息",
        context={"user_id": "user-1", "scheduled_execution_isolated": True},
        db_session=None,
    )
    await asyncio.sleep(0)

    assert behavior.entries == []
    assert conversation.entries == []


@pytest.mark.asyncio
async def test_isolated_execution_skips_usage_record(monkeypatch: pytest.MonkeyPatch) -> None:
    usage_calls = []

    class _UsageTracker:
        def __init__(self, db_session: object) -> None:
            usage_calls.append(("init", db_session))

        async def record_llm_call(self, **kwargs: Any) -> None:
            usage_calls.append(("record", kwargs))

    monkeypatch.setattr("billing.usage_tracker.UsageTracker", _UsageTracker)
    recorder = BehaviorRecorder(_Recorder(), _Recorder(), _identity, lambda task: None)

    recorder.schedule(
        node_type="llm_call",
        user_message="测试消息",
        context={"user_id": "user-1", "scheduled_execution_isolated": True},
        db_session=object(),
        token_breakdown=TokenBreakdown(output_tokens=3, method="api_usage", estimated=False),
    )
    await asyncio.sleep(0)

    assert usage_calls == []
