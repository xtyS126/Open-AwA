"""
Task 19 统一子代理系统：图编排与 task_runtime 委派连通性测试。

覆盖范围：
1. 委派执行（orchestrator/delegate）复用 task_runtime.spawn_agent 的调用路径
2. 图节点在 use_llm 标志下委派 task_runtime 真实 LLM 子代理
3. 无 use_llm 标志 / 代理类型未注册时回退内置规则实现（离线降级）
4. facade.spawn_agent 的 force_foreground 参数行为
5. API 端点 /api/subagents/orchestrator/delegate 的端到端连通

验证手段：mock task_runtime.spawn_agent（不依赖真实 LLM），
断言委派路径确实调用了 task_runtime 的 spawn_agent。
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.routes import subagents as subagents_routes
from core.subagent import (
    AgentState,
    IsolationLevel,
    SubagentTask,
    SubagentLifecycleState,
)
from core.subagent_task_runtime_bridge import (
    run_task_via_task_runtime,
    make_llm_aware_handler,
    resolve_task_runtime_agent_type,
    isolation_level_to_mode,
)
import core.subagent_task_runtime_bridge as bridge
import core.task_runtime.facade as facade_module


# ── 测试辅助 ──────────────────────────────────────────────


def _make_fake_spawn_stream(summary: str = "调研完成，找到相关实现位置", state: str = "completed"):
    """构造 spawn_agent 的 mock 实现：返回模拟的前台事件流。"""

    async def fake_spawn_agent(*args, **kwargs):
        async def stream():
            yield {
                "type": "subagent_start",
                "agent_id": "agent-mock-1",
                "agent_type": kwargs.get("agent_type", "Explore"),
            }
            yield {
                "type": "subagent_stop",
                "state": state,
                "summary": summary,
                "agent_id": "agent-mock-1",
            }
        return stream()

    return fake_spawn_agent


# ── 委派执行路径测试 ──────────────────────────────────────


class TestTaskRuntimeDelegation:
    """验证委派执行复用 task_runtime.spawn_agent 的调用路径。"""

    @pytest.mark.asyncio
    async def test_run_task_via_task_runtime_calls_spawn_agent(self):
        """run_task_via_task_runtime 应调用 spawn_agent 并消费事件流生成结果。"""
        fake_spawn = _make_fake_spawn_stream(summary="代码库调研结果摘要")
        with patch.object(bridge.task_runtime, "spawn_agent", new=AsyncMock(side_effect=fake_spawn)) as mock_spawn:
            task = SubagentTask(
                task_id="t-delegate-1",
                instruction="调研代码库中 Agent 的入口实现",
                metadata={"agent_name": "searcher"},
            )
            result = await run_task_via_task_runtime(task)

        assert result is not None
        assert result.success is True
        assert "代码库调研结果摘要" in result.output
        # 通过内置映射表 searcher -> Explore 路由到 task_runtime 原生类型
        assert result.metadata["agent_type"] == "Explore"
        assert result.metadata["runtime"] == "task_runtime"
        # 断言 spawn_agent 被真实调用且参数正确（force_foreground 强制前台同步取结果）
        mock_spawn.assert_awaited_once()
        call_kwargs = mock_spawn.await_args.kwargs
        assert call_kwargs["agent_type"] == "Explore"
        assert call_kwargs["prompt"] == "调研代码库中 Agent 的入口实现"
        assert call_kwargs["force_foreground"] is True
        assert call_kwargs["background"] is False

    @pytest.mark.asyncio
    async def test_run_task_via_task_runtime_explicit_agent_type(self):
        """metadata.agent_type 显式指定时应直接使用 task_runtime 原生类型。"""
        fake_spawn = _make_fake_spawn_stream()
        with patch.object(bridge.task_runtime, "spawn_agent", new=AsyncMock(side_effect=fake_spawn)) as mock_spawn:
            task = SubagentTask(
                task_id="t-delegate-2",
                instruction="审查代码安全性",
                metadata={"agent_type": "verification"},
            )
            result = await run_task_via_task_runtime(task)

        assert result is not None
        assert mock_spawn.await_args.kwargs["agent_type"] == "verification"

    @pytest.mark.asyncio
    async def test_run_task_via_task_runtime_returns_none_when_type_unregistered(self):
        """代理类型未注册时不应调用 spawn_agent，返回 None 交由调用方回退。"""
        with patch.object(bridge.agent_registry, "get", return_value=None) as mock_registry:
            with patch.object(bridge.task_runtime, "spawn_agent", new=AsyncMock()) as mock_spawn:
                task = SubagentTask(
                    task_id="t-delegate-3",
                    instruction="未知类型任务",
                    metadata={"agent_type": "no_such_type"},
                )
                result = await run_task_via_task_runtime(task)

        assert result is None
        mock_spawn.assert_not_awaited()
        mock_registry.assert_called()

    @pytest.mark.asyncio
    async def test_run_task_via_task_runtime_handles_failed_stream(self):
        """spawn_agent 事件流以 failed 终态结束时结果应标记失败。"""
        fake_spawn = _make_fake_spawn_stream(summary="执行出错", state="failed")
        with patch.object(bridge.task_runtime, "spawn_agent", new=AsyncMock(side_effect=fake_spawn)):
            task = SubagentTask(task_id="t-delegate-4", instruction="会失败的任务")
            result = await run_task_via_task_runtime(task)

        assert result is not None
        assert result.success is False
        assert result.lifecycle_state == SubagentLifecycleState.ERROR

    def test_resolve_task_runtime_agent_type_priority(self):
        """代理类型解析优先级：显式 agent_type > 映射表 > 默认 Explore。"""
        # 显式 agent_type 优先
        task = SubagentTask(
            task_id="t1", instruction="x",
            metadata={"agent_type": "verification", "agent_name": "analyzer"},
        )
        assert resolve_task_runtime_agent_type(task) == "verification"
        # agent_name 走映射表
        task = SubagentTask(task_id="t1", instruction="x", metadata={"agent_name": "code_reviewer"})
        assert resolve_task_runtime_agent_type(task) == "verification"
        # 无任何指定时默认 Explore
        task = SubagentTask(task_id="t1", instruction="x")
        assert resolve_task_runtime_agent_type(task) == "Explore"

    def test_resolve_task_runtime_agent_type_native_type_passthrough(self):
        """agent_name 本身就是已注册的 task_runtime 原生类型时直接使用。"""
        task = SubagentTask(
            task_id="t1", instruction="x", metadata={"agent_name": "verification"}
        )
        assert resolve_task_runtime_agent_type(task) == "verification"


class TestIsolationLevelConvergence:
    """验证 subagent.py IsolationLevel 与 task_runtime isolation_mode 的单一映射。"""

    def test_isolation_level_to_mode_returns_none_for_context(self):
        """CONTEXT 返回 None，表示不覆写代理定义的 isolation_mode。"""
        assert isolation_level_to_mode(IsolationLevel.CONTEXT) is None

    def test_isolation_level_to_mode_returns_worktree_for_process(self):
        """PROCESS 映射到 worktree。"""
        assert isolation_level_to_mode(IsolationLevel.PROCESS) == "worktree"

    def test_isolation_level_to_mode_raises_for_sandbox(self):
        """SANDBOX 未实现时显式失败，禁止静默降级。"""
        with pytest.raises(ValueError):
            isolation_level_to_mode(IsolationLevel.SANDBOX)


# ── 图节点 LLM 感知包装测试 ────────────────────────────────


class TestGraphNodeLlmAwareHandler:
    """验证图节点处理器在 use_llm 标志下委派 task_runtime。"""

    @pytest.mark.asyncio
    async def test_handler_delegates_to_task_runtime_with_llm_flag(self):
        """context.use_llm=True 时图节点应委派 task_runtime 并写入结果。"""
        from api.routes.subagents import _builtin_analyzer

        handler = make_llm_aware_handler("analyzer", _builtin_analyzer)
        fake_spawn = _make_fake_spawn_stream(summary="意图分析完成")
        with patch.object(bridge.task_runtime, "spawn_agent", new=AsyncMock(side_effect=fake_spawn)) as mock_spawn:
            state = AgentState(context={"use_llm": True, "user_message": "分析这段需求"})
            result_state = await handler(state)

        mock_spawn.assert_awaited_once()
        node_result = result_state.get_result("analyzer")
        assert node_result["runtime"] == "task_runtime"
        assert node_result["approved"] is True
        assert node_result["summary"] == "意图分析完成"
        # 图节点应通过映射表将 analyzer 路由到 Plan 类型
        assert mock_spawn.await_args.kwargs["agent_type"] == "Plan"

    @pytest.mark.asyncio
    async def test_handler_falls_back_to_rule_without_flag(self):
        """无 use_llm 标志时图节点应回退内置规则实现，不调用 spawn_agent。"""
        from api.routes.subagents import _builtin_analyzer

        handler = make_llm_aware_handler("analyzer", _builtin_analyzer)
        with patch.object(bridge.task_runtime, "spawn_agent", new=AsyncMock()) as mock_spawn:
            state = AgentState(context={"user_message": "分析这段需求"})
            result_state = await handler(state)

        mock_spawn.assert_not_awaited()
        # 规则实现输出 analyzer 结果
        rule_result = result_state.get_result("analyzer")
        assert rule_result["intent"] == "general"
        assert "message_length" in rule_result

    @pytest.mark.asyncio
    async def test_handler_falls_back_when_delegation_fails(self):
        """LLM 委派失败（代理类型未注册）时应回退规则实现，图执行不中断。"""
        from api.routes.subagents import _builtin_analyzer

        handler = make_llm_aware_handler("analyzer", _builtin_analyzer)
        with patch.object(bridge.agent_registry, "get", return_value=None):
            with patch.object(bridge.task_runtime, "spawn_agent", new=AsyncMock()) as mock_spawn:
                state = AgentState(context={"use_llm": True, "user_message": "分析"})
                result_state = await handler(state)

        mock_spawn.assert_not_awaited()
        rule_result = result_state.get_result("analyzer")
        assert rule_result["intent"] == "general"


# ── facade.spawn_agent force_foreground 行为测试 ────────────


class TestFacadeForceForeground:
    """验证 facade.spawn_agent 的 force_foreground 参数行为。"""

    def _make_definition(self, background_default: bool = True):
        from core.task_runtime.definitions import AgentDefinition

        return AgentDefinition(
            name="TestAgent",
            description="测试代理",
            permission_mode="default",
            background_default=background_default,
        )

    @pytest.mark.asyncio
    async def test_force_foreground_ignores_background_default(self):
        """force_foreground=True 时应忽略 background_default 强制前台执行。"""
        # run_foreground 原始实现是 async generator 函数（调用返回事件流、无需 await），
        # 因此用普通 Mock 模拟其"调用即返回 async generator"的语义
        async def fake_foreground_stream(**kwargs):
            yield {"type": "subagent_stop", "state": "completed", "summary": "done"}

        mock_foreground = Mock(side_effect=fake_foreground_stream)
        mock_background = AsyncMock()

        with patch.object(bridge.agent_registry, "get", return_value=self._make_definition(background_default=True)):
            with patch.object(facade_module, "run_foreground", new=mock_foreground) as m_fg:
                with patch.object(facade_module, "run_background", new=mock_background) as m_bg:
                    await facade_module.task_runtime.spawn_agent(
                        agent_type="TestAgent",
                        prompt="测试",
                        background=False,
                        force_foreground=True,
                    )

        m_fg.assert_called_once()
        m_bg.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_background_default_still_applies_without_force(self):
        """不带 force_foreground 时 background_default=True 仍走后台模式（向后兼容）。"""
        async def fake_foreground_stream(**kwargs):
            yield {"type": "subagent_stop", "state": "completed", "summary": "done"}

        mock_foreground = Mock(side_effect=fake_foreground_stream)
        mock_background = AsyncMock()

        with patch.object(bridge.agent_registry, "get", return_value=self._make_definition(background_default=True)):
            with patch.object(facade_module, "run_foreground", new=mock_foreground) as m_fg:
                with patch.object(facade_module, "run_background", new=mock_background) as m_bg:
                    await facade_module.task_runtime.spawn_agent(
                        agent_type="TestAgent",
                        prompt="测试",
                        background=False,
                    )

        m_fg.assert_not_called()
        m_bg.assert_awaited_once()


# ── API 端点端到端连通测试 ─────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_runtime_state():
    """每个测试结束后重置 subagents 路由的单例，避免跨测试污染。"""
    previous_manager = subagents_routes._manager
    previous_orchestrator = subagents_routes._orchestrator
    yield
    subagents_routes._manager = previous_manager
    subagents_routes._orchestrator = previous_orchestrator


def _delegate_payload():
    """构造委派请求 payload。"""
    return {
        "tasks": [
            {
                "task_id": "api-delegate-1",
                "instruction": "调研项目中的子代理实现位置",
                "context_snippet": "",
                "allowed_tools": [],
                "timeout_seconds": 60,
                "isolation_level": 1,
                "resource_limits": {
                    "max_turns": 5,
                    "max_tokens": 2000,
                    "max_time_seconds": 30,
                    "max_tool_calls": 5,
                    "max_output_tokens": 2000,
                    "soft_timeout_seconds": 20,
                },
                "metadata": {"agent_name": "searcher"},
            }
        ],
        "merge_strategy": "concatenate",
    }


def test_delegate_api_endpoint_routes_to_task_runtime():
    """POST /api/subagents/orchestrator/delegate 应委派到 task_runtime spawn_agent。"""
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from api.dependencies import get_current_user, get_db
    from db.models import Base
    from main import app

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    class DummyUser:
        id = "user-api-test"
        username = "apitest"

    def override_get_current_user():
        return DummyUser()

    previous_overrides = dict(app.dependency_overrides)
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    subagents_routes._manager = None
    subagents_routes._orchestrator = None

    fake_spawn = _make_fake_spawn_stream(summary="API 委派调研结果")
    try:
        with patch.object(bridge.task_runtime, "spawn_agent", new=AsyncMock(side_effect=fake_spawn)) as mock_spawn:
            with TestClient(app) as client:
                response = client.post("/api/subagents/orchestrator/delegate", json=_delegate_payload())
    finally:
        app.dependency_overrides = previous_overrides

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert len(data["results"]) == 1
    result = data["results"][0]
    assert result["success"] is True
    assert "API 委派调研结果" in result["output"]
    # 结果元数据应标明经 task_runtime 执行
    assert result["metadata"]["runtime"] == "task_runtime"
    # spawn_agent 应被调用，agent_type 经映射表 searcher -> Explore
    mock_spawn.assert_awaited()
    assert mock_spawn.await_args.kwargs["agent_type"] == "Explore"


def test_delegate_api_endpoint_falls_back_without_runtime_type():
    """委派请求指定未注册代理类型时，编排端点应回退规则执行器而非报错。"""
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from api.dependencies import get_current_user, get_db
    from db.models import Base
    from main import app

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    class DummyUser:
        id = "user-api-test-2"
        username = "apitest2"

    def override_get_current_user():
        return DummyUser()

    previous_overrides = dict(app.dependency_overrides)
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    subagents_routes._manager = None
    subagents_routes._orchestrator = None

    payload = _delegate_payload()
    # 指定 task_runtime 不存在的代理类型，强制走回退路径
    payload["tasks"][0]["metadata"] = {"agent_type": "no_such_type"}

    try:
        with patch.object(bridge.agent_registry, "get", return_value=None):
            with patch.object(bridge.task_runtime, "spawn_agent", new=AsyncMock()) as mock_spawn:
                with TestClient(app) as client:
                    response = client.post("/api/subagents/orchestrator/delegate", json=payload)
    finally:
        app.dependency_overrides = previous_overrides

    assert response.status_code == 200
    data = response.json()
    # 回退到内置规则执行器：默认 agent_name=analyzer 的规则分析结果
    assert data["success"] is True
    assert len(data["results"]) == 1
    # 规则执行器输出含 analyzer 的完成消息
    assert "分析完成" in data["results"][0]["output"]
    mock_spawn.assert_not_awaited()
