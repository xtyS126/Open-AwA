"""
验证规划层生成的 LLM 步骤参数命名，避免执行层因缺少 prompt 被拦截。
"""

import pytest

from core.planner import PlanningLayer


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("intent", "context", "expected_action", "expected_prompt"),
    [
        ("execute", {"message": "请总结这段日志"}, "llm_generate", "请总结这段日志"),
        ("query", {"message": "查询今天的系统状态"}, "llm_query", "查询今天的系统状态"),
        ("explain", {"message": "解释为什么会报错"}, "llm_explain", "解释为什么会报错"),
    ],
)
async def test_create_plan_uses_message_as_prompt_for_llm_steps(
    intent,
    context,
    expected_action,
    expected_prompt,
):
    """当上游没有显式传 prompt/task/query/target 时，规划层应回退到 message。"""

    planner = PlanningLayer()

    plan = await planner.create_plan(intent=intent, entities={}, context=context)

    assert len(plan["steps"]) == 1
    assert plan["steps"][0]["action"] == expected_action
    assert plan["steps"][0]["prompt"] == expected_prompt