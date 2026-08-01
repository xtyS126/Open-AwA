"""Agent 单一轮次协调器与旧规则层退役门禁。"""

from pathlib import Path

import pytest

from core.agent_turn_coordinator import AgentTurnCoordinator


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"


@pytest.mark.asyncio
async def test_coordinator_delegates_full_request_to_native_model_path() -> None:
    """轮次协调器不得用本地关键词规则改写用户任务。"""
    coordinator = AgentTurnCoordinator()

    intent, entities, plan = await coordinator.prepare_turn(
        "请分析 report.md 并选择合适工具",
        {"message": "请分析 report.md 并选择合适工具"},
    )

    assert intent == {"type": "chat", "action": "respond"}
    assert entities == {
        "entities": [
            {
                "type": "user_message",
                "value": "请分析 report.md 并选择合适工具",
            }
        ]
    }
    assert plan == {
        "intent": "chat",
        "steps": [
            {
                "step": 1,
                "action": "llm_chat",
                "message": "请分析 report.md 并选择合适工具",
                "purpose": "模型原生工具调用与回答",
            }
        ],
        "requires_confirmation": False,
    }


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
