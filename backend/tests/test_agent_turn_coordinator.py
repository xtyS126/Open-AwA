"""Agent 单一轮次协调器测试：验证意图分类与差异化计划生成。"""

from pathlib import Path

import pytest

from core.agent_turn_coordinator import AgentTurnCoordinator


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"


@pytest.mark.asyncio
async def test_coordinator_classifies_chat_as_fast_path() -> None:
    """闲聊消息应被分类为 chat 意图并使用快速路径。"""
    coordinator = AgentTurnCoordinator()

    intent, entities, plan = await coordinator.prepare_turn(
        "今天天气怎么样？",
        {"message": "今天天气怎么样？"},
    )

    assert intent == {"type": "chat", "action": "respond"}
    assert plan["intent"] == "chat"
    assert plan["mode"] == "fast"
    assert plan["use_subagent"] is False
    assert plan["requires_confirmation"] is False
    assert len(plan["steps"]) == 1
    assert plan["steps"][0].get("enable_tools") is not True  # chat 路径不包含 enable_tools 字段


@pytest.mark.asyncio
async def test_coordinator_classifies_code_as_tool_calls_path() -> None:
    """编程关键词应被分类为 code 意图并使用工具调用路径。"""
    coordinator = AgentTurnCoordinator()

    intent, entities, plan = await coordinator.prepare_turn(
        "帮我写代码实现一个排序算法",
        {"message": "帮我写代码实现一个排序算法"},
    )

    assert intent == {"type": "code", "action": "code"}
    assert plan["intent"] == "code"
    assert plan["mode"] == "tool_calls"
    assert plan["use_subagent"] is False
    assert plan["steps"][0]["enable_tools"] is True


@pytest.mark.asyncio
async def test_coordinator_classifies_search_as_tool_calls_path() -> None:
    """搜索关键词应被分类为 search 意图。"""
    coordinator = AgentTurnCoordinator()

    intent, entities, plan = await coordinator.prepare_turn(
        "搜索一下 Python 异步的资料",
        {"message": "搜索一下 Python 异步的资料"},
    )

    assert intent == {"type": "search", "action": "search"}
    assert plan["intent"] == "search"
    assert plan["mode"] == "tool_calls"


@pytest.mark.asyncio
async def test_coordinator_classifies_task_as_multi_step_path() -> None:
    """任务关键词应被分类为 task 意图并使用多步骤路径。"""
    coordinator = AgentTurnCoordinator()

    intent, entities, plan = await coordinator.prepare_turn(
        "帮我执行一个批量处理任务",
        {"message": "帮我执行一个批量处理任务"},
    )

    assert intent == {"type": "task", "action": "task"}
    assert plan["intent"] == "task"
    assert plan["mode"] == "multi_step"
    assert plan["use_subagent"] is True


@pytest.mark.asyncio
async def test_coordinator_classifies_manage_as_tool_calls_path() -> None:
    """管理关键词应被分类为 manage 意图。"""
    coordinator = AgentTurnCoordinator()

    intent, entities, plan = await coordinator.prepare_turn(
        "帮我修改设置添加插件",
        {"message": "帮我修改设置添加插件"},
    )

    assert intent == {"type": "manage", "action": "manage"}
    assert plan["intent"] == "manage"
    assert plan["mode"] == "tool_calls"


@pytest.mark.asyncio
async def test_coordinator_extracts_entities_with_keywords() -> None:
    """实体提取应包含用户消息和关键词。"""
    coordinator = AgentTurnCoordinator()

    _, entities, _ = await coordinator.prepare_turn(
        "请搜索 Python 异步编程资料",
        {"message": "请搜索 Python 异步编程资料"},
    )

    assert len(entities["entities"]) >= 1
    # 应包含 user_message 实体
    message_entities = [e for e in entities["entities"] if e["type"] == "user_message"]
    assert len(message_entities) == 1
    assert message_entities[0]["value"] == "请搜索 Python 异步编程资料"

    # 应包含 keywords 实体
    keyword_entities = [e for e in entities["entities"] if e["type"] == "keywords"]
    assert len(keyword_entities) >= 1
    assert "Python" in keyword_entities[0]["value"] or "搜索" in keyword_entities[0]["value"]


@pytest.mark.asyncio
async def test_coordinator_classify_and_plan_returns_typed_result() -> None:
    """classify_and_plan 应返回 IntentType、置信度和 ExecutionPlan。"""
    coordinator = AgentTurnCoordinator()

    from core.intent_classifier import IntentType
    from core.plan_builder import ExecutionPlan

    intent_type, confidence, execution_plan = await coordinator.classify_and_plan(
        "帮我写代码",
    )

    assert intent_type == IntentType.CODE
    assert confidence == 0.8
    assert isinstance(execution_plan, ExecutionPlan)
    assert execution_plan.mode == "tool_calls"


@pytest.mark.asyncio
async def test_coordinator_classify_and_plan_chat_has_lower_confidence() -> None:
    """闲聊意图的置信度应较低。"""
    coordinator = AgentTurnCoordinator()

    intent_type, confidence, execution_plan = await coordinator.classify_and_plan(
        "你好啊",
    )

    assert intent_type.value == "chat"
    assert confidence == 0.5
    assert execution_plan.mode == "fast"


@pytest.mark.asyncio
async def test_coordinator_prepare_turn_includes_relevant_experiences() -> None:
    """prepare_turn 应在 plan 中包含 relevant_experiences。"""
    coordinator = AgentTurnCoordinator()

    _, _, plan = await coordinator.prepare_turn(
        "你好",
        {"message": "你好", "relevant_experiences": [{"id": "exp1"}]},
    )

    assert "relevant_experiences" in plan
    assert plan["relevant_experiences"] == [{"id": "exp1"}]


def test_retired_rule_layers_cannot_return_to_production() -> None:
    """旧理解层和规划层不得继续保留生产文件或构造引用。"""
    assert not (BACKEND_ROOT / "core" / "comprehension.py").exists()
    assert not (BACKEND_ROOT / "core" / "planner.py").exists()

    forbidden_markers = (
        "ComprehensionLayer",
        "PlanningLayer",
        "core.comprehension",
        "core.planner",
    )
    offenders: list[str] = []
    for source_path in (BACKEND_ROOT / "core").rglob("*.py"):
        source = source_path.read_text(encoding="utf-8-sig")
        if any(marker in source for marker in forbidden_markers):
            offenders.append(source_path.relative_to(PROJECT_ROOT).as_posix())

    assert offenders == []