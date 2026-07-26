"""
FeedbackLayer 触发记忆巩固单元测试。

Spec memory-quality-and-short-term-recovery Task 6：
- 每轮对话完成后递增 consolidation_state.conversation_count_since_run
- 计数 >= 阈值时异步触发 consolidation_runner.run_if_due
- 异常捕获并记录 WARNING 日志，不阻塞 chat 响应
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.feedback import FeedbackLayer


def _build_feedback_with_mock_runner():
    """
    构造 FeedbackLayer + mock memory_manager + mock consolidation_runner。

    runner 是 MagicMock，increment_conversation_count 与 run_if_due 都可控。
    """
    feedback = FeedbackLayer()
    feedback.memory_manager = MagicMock()
    feedback.memory_manager._MAX_LONG_TERM_CONTENT_CHARS = 500
    # 异步 add_short_term_memory / add_long_term_memory 不实际写入
    feedback.memory_manager.add_short_term_memory = AsyncMock()
    feedback.memory_manager.add_long_term_memory = AsyncMock()

    runner = MagicMock()
    runner._conversation_threshold = 10
    runner.increment_conversation_count = MagicMock(return_value=0)
    runner.run_if_due = AsyncMock(return_value={"triggered": True, "success": True})
    feedback.set_consolidation_runner(runner)
    return feedback, runner


@pytest.mark.asyncio
async def test_update_memory_increments_conversation_count():
    """
    场景：update_memory 完成后递增 conversation_count_since_run。

    Given 注入 consolidation_runner
    When 调用 update_memory（user_input + response）
    Then runner.increment_conversation_count 被调用 1 次
    """
    feedback, runner = _build_feedback_with_mock_runner()
    # 第一次返回 1，未达阈值
    runner.increment_conversation_count.return_value = 1

    await feedback.update_memory(
        user_input="你好",
        response="你好，有什么可以帮你？",
        context={"session_id": "s1", "user_id": "user-1"},
    )

    # 等待后台 asyncio.create_task 完成
    await asyncio.sleep(0.05)
    runner.increment_conversation_count.assert_called_once_with(
        "user-1", workspace_id="default"
    )


@pytest.mark.asyncio
async def test_consolidation_triggered_when_threshold_reached():
    """
    场景：计数达到阈值时触发 run_if_due。

    Given runner.increment_conversation_count 返回 10（>= 阈值 10）
    When 调用 update_memory
    Then runner.run_if_due 被调用一次
    """
    feedback, runner = _build_feedback_with_mock_runner()
    runner.increment_conversation_count.return_value = 10

    await feedback.update_memory(
        user_input="帮我记住 Python 是我最喜欢的语言",
        response="好的，已记住。",
        context={"session_id": "s1", "user_id": "user-1"},
    )

    await asyncio.sleep(0.05)
    runner.run_if_due.assert_awaited_once_with("user-1", workspace_id="default")


@pytest.mark.asyncio
async def test_consolidation_not_triggered_below_threshold():
    """
    场景：计数未达阈值时不触发 run_if_due。

    Given runner.increment_conversation_count 返回 3（< 阈值 10）
    When 调用 update_memory
    Then runner.run_if_due 不被调用
    """
    feedback, runner = _build_feedback_with_mock_runner()
    runner.increment_conversation_count.return_value = 3

    await feedback.update_memory(
        user_input="你好",
        response="你好",
        context={"session_id": "s1", "user_id": "user-1"},
    )

    await asyncio.sleep(0.05)
    runner.run_if_due.assert_not_called()


@pytest.mark.asyncio
async def test_consolidation_runner_exception_does_not_block_chat():
    """
    场景：consolidation_runner 异常时不阻塞 chat 响应。

    Given runner.increment_conversation_count 抛 RuntimeError
    When 调用 update_memory
    Then update_memory 不抛异常（chat 响应正常返回）
    And runner.run_if_due 不被调用
    """
    feedback, runner = _build_feedback_with_mock_runner()
    runner.increment_conversation_count.side_effect = RuntimeError("DB 超时")

    # 不应抛异常
    await feedback.update_memory(
        user_input="你好",
        response="你好",
        context={"session_id": "s1", "user_id": "user-1"},
    )

    await asyncio.sleep(0.05)
    runner.run_if_due.assert_not_called()


@pytest.mark.asyncio
async def test_no_consolidation_runner_injected_skips_trigger():
    """
    场景：未注入 consolidation_runner 时不触发巩固（向后兼容）。

    Given feedback.consolidation_runner = None
    When 调用 update_memory
    Then 不抛异常
    And memory_manager.add_short_term_memory 仍被调用（短期记忆写入正常）
    """
    feedback = FeedbackLayer()
    feedback.memory_manager = MagicMock()
    feedback.memory_manager.add_short_term_memory = AsyncMock()
    feedback.memory_manager.add_long_term_memory = AsyncMock()

    await feedback.update_memory(
        user_input="你好",
        response="你好",
        context={"session_id": "s1", "user_id": "user-1"},
    )

    # 短期记忆写入仍正常
    assert feedback.memory_manager.add_short_term_memory.await_count == 2


@pytest.mark.asyncio
async def test_no_user_id_skips_consolidation():
    """
    场景：user_id 为空时跳过巩固触发。

    Given context.user_id = None
    When 调用 update_memory
    Then runner.increment_conversation_count 不被调用
    """
    feedback, runner = _build_feedback_with_mock_runner()

    await feedback.update_memory(
        user_input="你好",
        response="你好",
        context={"session_id": "s1", "user_id": None},
    )

    await asyncio.sleep(0.05)
    runner.increment_conversation_count.assert_not_called()


@pytest.mark.asyncio
async def test_workspace_id_passed_to_runner():
    """
    场景：workspace_id 从 context 透传到 runner。

    Given context.workspace_id = "custom-ws"
    When 调用 update_memory
    Then runner.increment_conversation_count 使用 workspace_id="custom-ws"
    """
    feedback, runner = _build_feedback_with_mock_runner()
    runner.increment_conversation_count.return_value = 1

    await feedback.update_memory(
        user_input="你好",
        response="你好",
        context={
            "session_id": "s1",
            "user_id": "user-1",
            "workspace_id": "custom-ws",
        },
    )

    await asyncio.sleep(0.05)
    runner.increment_conversation_count.assert_called_once_with(
        "user-1", workspace_id="custom-ws"
    )
