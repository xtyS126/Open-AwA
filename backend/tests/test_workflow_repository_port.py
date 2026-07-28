"""工作流仓储端口与 Agent 委托测试。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from api.adapters.workflow_repository_adapter import WorkflowRepositoryAdapter
from core.agent import AIAgent
from core.ports.workflow_repository_port import WorkflowDefinition


@pytest.mark.asyncio
async def test_workflow_repository_adapter_returns_core_projection():
    """适配器应把 ORM 记录转换为不含 ORM 依赖的核心投影。"""
    db_session = MagicMock()
    record = SimpleNamespace(
        id="workflow-1",
        name="测试工作流",
        definition={"steps": [{"action": "run"}]},
    )
    db_session.query.return_value.filter.return_value.first.return_value = record
    repository = WorkflowRepositoryAdapter(db_session)

    result = await repository.find_by_id("workflow-1")

    assert result == WorkflowDefinition(
        workflow_id="workflow-1",
        name="测试工作流",
        definition={"steps": [{"action": "run"}]},
    )


@pytest.mark.asyncio
async def test_agent_executes_workflow_through_repository_port():
    """仅提供 workflow_id 时，Agent 应通过仓储端口读取定义。"""
    repository = MagicMock()
    repository.find_by_id = AsyncMock(return_value=WorkflowDefinition(
        workflow_id="workflow-1",
        name="测试工作流",
        definition={"steps": []},
    ))
    agent = AIAgent(workflow_repository=repository)
    agent.workflow_engine = MagicMock()
    agent.workflow_engine.execute_definition = AsyncMock(return_value={"status": "completed"})

    result = await agent._execute_workflow_from_context({
        "workflow_id": "workflow-1",
        "user_id": "user-1",
    })

    assert result == {"status": "completed"}
    repository.find_by_id.assert_awaited_once_with("workflow-1")
    agent.workflow_engine.execute_definition.assert_awaited_once()
