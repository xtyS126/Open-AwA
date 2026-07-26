"""PlanExecutor 的分支执行与反馈决策测试。"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from core.plan_executor import PlanExecutor


def make_plan_executor() -> tuple[PlanExecutor, MagicMock, AsyncMock, AsyncMock]:
    """构造不依赖完整 AIAgent 的计划执行器。"""
    executor = MagicMock()
    executor.execute_step = AsyncMock()
    executor.retry_step = AsyncMock()
    planner = MagicMock()
    planner.create_plan = AsyncMock(return_value={"steps": []})
    feedback = MagicMock()
    feedback.evaluate_result = AsyncMock(return_value={})
    execute_skill = AsyncMock()
    execute_plugin = AsyncMock()
    schedule_record = MagicMock()
    apply_output_mode = MagicMock(side_effect=lambda output, _: output)
    plan_executor = PlanExecutor(
        executor,
        planner,
        feedback,
        execute_skill,
        execute_plugin,
        AsyncMock(return_value=[]),
        AsyncMock(return_value=[]),
        schedule_record,
        apply_output_mode,
    )
    return plan_executor, executor, execute_skill, execute_plugin


@pytest.mark.asyncio
async def test_plan_executor_executes_skill_and_records_result():
    """技能步骤应调用技能执行器、追加结果且不进入常规执行器。"""
    plan_executor, executor, execute_skill, _ = make_plan_executor()
    execute_skill.return_value = {"status": "success", "response": "技能结果"}
    results: list[dict] = []

    early_return = await plan_executor.execute_single_step(
        {"use_skill": True, "skill_name": "summarize", "inputs": {"text": "x"}},
        "用户输入",
        {"enable_skill_plugin": True},
        results,
    )

    assert early_return is None
    execute_skill.assert_awaited_once()
    executor.execute_step.assert_not_awaited()
    assert results[0]["type"] == "skill"


@pytest.mark.asyncio
async def test_plan_executor_returns_confirmation_for_regular_step():
    """常规步骤要求确认时，应返回统一的 awaiting_confirmation 响应。"""
    plan_executor, executor, _, _ = make_plan_executor()
    executor.execute_step.return_value = {"status": "success", "response": "待确认"}
    plan_executor._feedback.evaluate_result.return_value = {
        "needs_confirmation": True,
        "message": "请确认",
    }
    results: list[dict] = []

    early_return = await plan_executor.execute_single_step(
        {"action": "delete_resource"}, "用户输入", {}, results,
    )

    assert early_return is not None
    assert early_return["status"] == "awaiting_confirmation"
    assert early_return["message"] == "请确认"
    assert results[0]["type"] == "execution"
