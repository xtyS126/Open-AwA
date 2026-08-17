"""AIAgent 运行时协作者的组合与初始化。"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional, Type

from loguru import logger
from sqlalchemy.orm import Session

from config.settings import settings
from config.thresholds import CAPABILITIES_CACHE_TTL
from core.agent_capability_builder import (
    build_native_tools,
    collect_configured_model_capabilities,
    collect_mcp_capabilities,
)
from core.behavior_logger import behavior_logger
from core.behavior_recorder import BehaviorRecorder
from core.budget_tracker import BudgetTracker
from core.capability_aggregator import CapabilityAggregator
from core.content_replacement import ContentReplacementState
from core.conversation_recorder import conversation_recorder
from core.executor import ExecutionLayer
from core.feedback import FeedbackLayer
from core.plan_executor import PlanExecutor
from core.agent_turn_coordinator import AgentTurnCoordinator
from core.soul_state import SoulStateManager
from core.stream_orchestrator import StreamOrchestrator
from core.tool_dispatcher import ToolDispatcher
from core.tool_event_emitter import ToolEventEmitter
from memory.consolidation_runner import ConsolidationRunner
from memory.experience_manager import ExperienceManager
from memory.extractor import make_default_extract_callback
from memory.manager import MemoryManager
from plugins import plugin_instance
from skills.experience_extractor import ExperienceExtractor
from skills.skill_engine import SkillEngine
from workflow.engine import WorkflowEngine

from core.ports.ask_user_port import AskUserPort
from core.ports.workflow_repository_port import WorkflowRepositoryPort


@dataclass(frozen=True)
class AgentRuntimeTimings:
    """Agent 初始化阶段耗时。"""

    layers_ms: float
    skill_engine_ms: float
    plugin_manager_ms: float
    memory_engine_ms: float


def initialize_agent_runtime(
    agent: Any,
    *,
    db_session: Optional[Session],
    ask_user_port: Optional[AskUserPort],
    workflow_repository: Optional[WorkflowRepositoryPort],
    memory_session_factory: Optional[Callable[[], Session]],
    early_exit_type: Type[Exception],
    unregister_task: Callable[..., None],
) -> AgentRuntimeTimings:
    """构造 Agent 的全部协作者，并把它们安装到入口对象。"""
    _initialize_request_state(agent)
    layers_ms = _initialize_core_layers(agent)
    skill_engine_ms, plugin_manager_ms = _initialize_runtime_dependencies(
        agent,
        db_session=db_session,
        ask_user_port=ask_user_port,
        workflow_repository=workflow_repository,
        memory_session_factory=memory_session_factory,
        early_exit_type=early_exit_type,
        unregister_task=unregister_task,
    )
    memory_engine_ms = _initialize_memory_dependencies(agent)
    return AgentRuntimeTimings(
        layers_ms=layers_ms,
        skill_engine_ms=skill_engine_ms,
        plugin_manager_ms=plugin_manager_ms,
        memory_engine_ms=memory_engine_ms,
    )


def _initialize_request_state(agent: Any) -> None:
    """初始化实例独立的请求状态。"""
    agent.soul_state_manager = SoulStateManager(workspace_id="default")
    agent.budget_tracker = BudgetTracker()
    agent.content_replacement_state = ContentReplacementState()
    agent.root_abort_controller = None


def _initialize_core_layers(agent: Any) -> float:
    """初始化轮次协调、执行、反馈与经验提取协作者。"""
    started_at = time.time()
    agent.turn_coordinator = AgentTurnCoordinator()
    agent.executor = ExecutionLayer()
    agent.feedback = FeedbackLayer()
    agent.experience_extractor = ExperienceExtractor()
    return round((time.time() - started_at) * 1000, 2)


def _initialize_runtime_dependencies(
    agent: Any,
    *,
    db_session: Optional[Session],
    ask_user_port: Optional[AskUserPort],
    workflow_repository: Optional[WorkflowRepositoryPort],
    memory_session_factory: Optional[Callable[[], Session]],
    early_exit_type: Type[Exception],
    unregister_task: Callable[..., None],
) -> tuple[float, float]:
    """初始化能力、工具、计划、技能、插件和行为记录协作者。"""
    agent._db_session_bound = db_session
    agent._db_session_request = None
    agent._ask_user_port = ask_user_port
    agent._workflow_repository = workflow_repository
    agent._memory_session_factory = memory_session_factory
    agent._experience_manager_factory = ExperienceManager
    agent._max_self_correction_rounds = settings.AGENT_SELF_CORRECTION_MAX_ROUNDS
    agent._capability_aggregator = CapabilityAggregator(
        CAPABILITIES_CACHE_TTL,
        collect_configured_models=lambda context: (
            collect_configured_model_capabilities(context, agent._db_session)
        ),
        collect_mcp=collect_mcp_capabilities,
    )
    agent.native_tool_builder = build_native_tools
    agent._tool_event_emitter = ToolEventEmitter()
    agent._tool_dispatcher = ToolDispatcher(
        agent.executor,
        ask_user_port,
        early_exit_type,
    )
    agent._stream_orchestrator = StreamOrchestrator(
        agent.executor,
        agent.feedback,
        agent._tool_dispatcher,
        agent._tool_event_emitter,
        early_exit_type,
        agent.budget_tracker,
        agent.content_replacement_state,
        agent._record_round_budget_usage,
        unregister_task,
        finalize_agent_response=agent._finalize_agent_response,
    )
    agent._plan_executor = PlanExecutor(
        agent.executor,
        agent.feedback,
        agent.execute_skill,
        agent.execute_plugin,
        agent.get_available_skills,
        agent.get_available_plugins,
        agent._schedule_record,
        agent._apply_output_mode,
    )
    skill_started_at = time.time()
    agent.skill_engine = SkillEngine(agent._db_session)
    skill_engine_ms = round((time.time() - skill_started_at) * 1000, 2)
    plugin_started_at = time.time()
    agent.plugin_manager = plugin_instance.get()
    plugin_manager_ms = round((time.time() - plugin_started_at) * 1000, 2)
    agent._closed = False
    agent.skill_results = []
    agent.plugin_results = []
    agent._record_semaphore = asyncio.Semaphore(
        settings.RECORD_SEMAPHORE_SIZE
    )
    agent._behavior_recorder = BehaviorRecorder(
        behavior_logger,
        conversation_recorder,
        agent._record_with_backpressure,
        agent._handle_record_task_result,
    )
    return skill_engine_ms, plugin_manager_ms


def _initialize_memory_dependencies(agent: Any) -> float:
    """初始化工作流、记忆与自动巩固依赖。"""
    started_at = time.time()
    agent.memory_manager = None
    agent.consolidation_runner = None
    agent.workflow_engine = None
    if not agent._db_session:
        return round((time.time() - started_at) * 1000, 2)
    agent.workflow_engine = WorkflowEngine(
        db_session=agent._db_session,
        skill_engine=agent.skill_engine,
    )
    session_factory = agent._memory_session_factory
    if session_factory is None:
        logger.bind(
            event="memory_session_factory_missing",
            module="agent_runtime",
        ).warning("未注入记忆会话工厂，跳过记忆与巩固组件初始化")
        return round((time.time() - started_at) * 1000, 2)
    agent.memory_manager = MemoryManager(session_factory)
    agent.feedback.set_memory_manager(agent.memory_manager)
    agent.executor.memory_manager = agent.memory_manager
    agent.consolidation_runner = ConsolidationRunner(
        agent.memory_manager,
        session_factory,
        conversation_threshold=settings.CONSOLIDATION_CONVERSATION_THRESHOLD,
        batch_size=settings.CONSOLIDATION_BATCH_SIZE,
    )
    agent.consolidation_runner.set_extract_callback(
        make_default_extract_callback(
            session_factory,
            provider=settings.CONSOLIDATION_EXTRACT_PROVIDER or None,
            model=settings.CONSOLIDATION_EXTRACT_MODEL or None,
        )
    )
    agent.feedback.set_consolidation_runner(agent.consolidation_runner)
    return round((time.time() - started_at) * 1000, 2)
