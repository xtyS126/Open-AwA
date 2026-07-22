"""
核心执行编排模块，负责 Agent 主流程中的理解、规划、执行、反馈或记录能力。
这些文件决定了用户请求在内部被如何拆解、编排以及最终落地执行。
"""

import asyncio
import threading
import json
import time
from typing import Any, Dict, List, Optional, Set, Tuple
from loguru import logger
from .comprehension import ComprehensionLayer
from .planner import PlanningLayer
from .executor import ExecutionLayer, resolve_max_tool_call_rounds
from .feedback import FeedbackLayer
from .metrics import record_tool_execution_metric
from .abort_controller import AbortController
from memory.experience_manager import ExperienceManager
from skills.experience_extractor import ExperienceExtractor
from skills.skill_engine import SkillEngine
from plugins import plugin_instance
from workflow.engine import WorkflowEngine
from .behavior_logger import behavior_logger
from .behavior_entry_builder import build_behavior_entries
from .behavior_recorder import BehaviorRecorder
from .conversation_recorder import conversation_recorder
from .magic_commands import get_magic_command_registry
from .compaction_manager import CompactionManager
from .context.token_budget import TokenBudget
from billing.token_counter import TokenBreakdown
from .budget_tracker import BudgetTracker
from .content_replacement import ContentReplacementState, enforce_tool_result_budget
from .soul_state import SoulStateManager
from core.streaming_events import (
    emit_task_event,
    emit_tool_event,
    emit_subagent_start_event,
    emit_task_created_event,
    emit_task_updated_event,
    emit_team_event,
    emit_ask_user_event,
)
from core.task_runtime.tool_definitions import build_task_runtime_tool_definitions
from core.agent_capability_builder import (
    summarize_skill_capabilities,
    summarize_plugin_capabilities,
    collect_mcp_capabilities,
    collect_configured_model_capabilities,
)
from core.capability_aggregator import CapabilityAggregator
from core.agent_context_builder import (
    strip_reasoning_content,
    apply_scheduled_execution_defaults,
    build_multimodal_context,
    build_thinking_context,
)
from core.agent_state import AgentState
from core.agent_helpers import (
    is_final_only_mode,
    build_status_event,
    map_finish_reason_to_state,
    get_stream_tool_kind,
    summarize_stream_tool_result,
    extract_spawned_subagent_result,
    build_effective_user_input,
    build_configured_model_hint,
)


from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

# 活跃 Agent 任务容量上限：防止异常断流或取消链路不完整时字典无限增长
# 工具调用回环上限和任务容量均通过 settings 配置，支持不同部署环境调优。
_MAX_ACTIVE_AGENT_TASKS = 1000  # 从 settings 读取的默认值，实际由注册逻辑使用
# 全局活跃 Agent 任务字典：(user_id, session_id) -> asyncio.Task 集合
# 用户维度用于阻断同名会话的跨用户取消，集合用于覆盖同会话多端并发任务
_active_agent_tasks: Dict[Tuple[str, str], Set[asyncio.Task]] = {}
_active_agent_tasks_lock = threading.RLock()


def register_agent_task(user_id: str, session_id: str, task: asyncio.Task) -> None:
    """注册活跃的 Agent 异步任务，供取消端点查找。
    容量满时自动清理已完成的任务，仍满则拒绝注册并告警。
    """
    from config.settings import settings

    with _active_agent_tasks_lock:
        max_active_tasks = settings.MAX_ACTIVE_AGENT_TASKS
        active_count = sum(len(tasks) for tasks in _active_agent_tasks.values())
        if active_count >= max_active_tasks:
            _cleanup_completed_tasks()
            active_count = sum(len(tasks) for tasks in _active_agent_tasks.values())
        if active_count >= max_active_tasks:
            logger.bind(event="agent_task_capacity_reached", module="agent",
                        active_count=active_count,
                        max_capacity=max_active_tasks
                        ).warning("活跃 Agent 任务字典达到容量上限，拒绝注册新任务")
            return
        key = (str(user_id), str(session_id))
        _active_agent_tasks.setdefault(key, set()).add(task)


def unregister_agent_task(user_id: str, session_id: str, task: Optional[asyncio.Task] = None) -> None:
    """移除已完成的 Agent 任务。"""
    with _active_agent_tasks_lock:
        key = (str(user_id), str(session_id))
        tasks = _active_agent_tasks.get(key)
        if not tasks:
            return
        target = task or asyncio.current_task()
        if target is not None:
            tasks.discard(target)
        if not tasks:
            _active_agent_tasks.pop(key, None)


def get_agent_tasks(user_id: str, session_id: str) -> List[asyncio.Task]:
    """获取指定用户会话的全部活跃 Agent 任务。"""
    with _active_agent_tasks_lock:
        return list(_active_agent_tasks.get((str(user_id), str(session_id)), set()))


def _cleanup_completed_tasks() -> None:
    """清理已完成或已取消的 Agent 任务条目，防止内存泄漏。"""
    with _active_agent_tasks_lock:
        removed_count = 0
        for key, tasks in list(_active_agent_tasks.items()):
            active_tasks = {task for task in tasks if not task.done()}
            removed_count += len(tasks) - len(active_tasks)
            if active_tasks:
                _active_agent_tasks[key] = active_tasks
            else:
                _active_agent_tasks.pop(key, None)
        remaining_count = len(_active_agent_tasks)
    if removed_count:
        logger.bind(event="agent_tasks_cleanup", module="agent",
                    removed=removed_count,
                    remaining=remaining_count
                    ).debug("清理已完成的 Agent 任务条目")


class AIAgent:
    """
    封装与AIAgent相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    # 能力缓存 TTL：30 秒内复用 skills/plugins/mcp 查询结果
    # 过期后下一次 process_stream 重新构建，保证插件/MCP 状态变化最终可见
    _CAPABILITIES_CACHE_TTL: float = 30.0

    # Deprecated: 仅为兼容测试套件 AIAgent._method_name(...) 直接调用，
    # 待 fix-test-implementation-coupling spec 重写测试后整体移除。
    _is_final_only_mode = staticmethod(is_final_only_mode)
    _build_status_event = staticmethod(build_status_event)
    _map_finish_reason_to_state = staticmethod(map_finish_reason_to_state)
    _get_stream_tool_kind = staticmethod(get_stream_tool_kind)
    _summarize_stream_tool_result = staticmethod(summarize_stream_tool_result)
    _extract_spawned_subagent_result = staticmethod(extract_spawned_subagent_result)
    _build_effective_user_input = staticmethod(build_effective_user_input)
    _build_configured_model_hint = staticmethod(build_configured_model_hint)

    def __init__(self, db_session: Session = None):
        """
        初始化 AI Agent，包含理解层、规划层、执行层、反馈层以及记忆管理。
        """
        # TTFT 诊断：AIAgent 构造耗时分解（定位 agent_registry 首次 10s 根因）
        _init_t0 = time.time()
        self.comprehension = ComprehensionLayer()
        self.planner = PlanningLayer()
        self.executor = ExecutionLayer()
        self.feedback = FeedbackLayer()
        self.experience_extractor = ExperienceExtractor()
        _init_layers_ms = round((time.time() - _init_t0) * 1000, 2)

        # 绑定态 db：__init__ 时传入的 db，作为兜底
        # 请求级 db：由 bind_db 设置，优先级最高（用于 AIAgent 实例复用场景）
        self._db_session_bound: Optional[Session] = db_session
        self._db_session_request: Optional[Session] = None
        # 能力缓存（Task 7 使用），实例复用场景下按需失效
        # 采用 TTL + 显式 invalidate：避免 _compute_tools_version 依赖 context["agent_capabilities"]
        # 导致的循环依赖问题（fresh context 中 capabilities 未构建，version 为空字符串）
        self._capability_aggregator = CapabilityAggregator(self._CAPABILITIES_CACHE_TTL)

        _skill_t0 = time.time()
        self.skill_engine = SkillEngine(self._db_session)
        _skill_engine_ms = round((time.time() - _skill_t0) * 1000, 2)

        _plugin_t0 = time.time()
        self.plugin_manager = plugin_instance.get()
        _plugin_manager_ms = round((time.time() - _plugin_t0) * 1000, 2)

        self._closed = False

        self.skill_results: List[Dict[str, Any]] = []
        self.plugin_results: List[Dict[str, Any]] = []

        # 限制并发 fire-and-forget 记录任务数，防止高并发下 Task 堆积
        from config.settings import settings as _agent_settings
        self._record_semaphore = asyncio.Semaphore(_agent_settings.RECORD_SEMAPHORE_SIZE)
        self._behavior_recorder = BehaviorRecorder(
            behavior_logger,
            conversation_recorder,
            self._record_with_backpressure,
            self._handle_record_task_result,
        )

        # 初始化记忆管理器，并注入到反馈层
        _mem_t0 = time.time()
        self.memory_manager = None
        self.workflow_engine = None
        if self._db_session:
            from memory.manager import MemoryManager
            from db.models import SessionLocal
            # 传入会话工厂而非请求级 Session，确保线程池中的 DB 操作各自持有独立会话
            self.memory_manager = MemoryManager(SessionLocal)
            self.feedback.set_memory_manager(self.memory_manager)
            self.workflow_engine = WorkflowEngine(db_session=self._db_session, skill_engine=self.skill_engine)
        _memory_engine_ms = round((time.time() - _mem_t0) * 1000, 2)

        # 初始化灵魂状态管理器（默认工作区）
        self.soul_state_manager = SoulStateManager(workspace_id="default")

        # 初始化预算追踪器，用于在 Agent 主循环中追踪 token 使用量
        self.budget_tracker: BudgetTracker = BudgetTracker()

        # 初始化工具结果内容替换状态，用于在 LLM 调用前应用工具结果预算
        self.content_replacement_state: ContentReplacementState = ContentReplacementState()

        # 根中止控制器：每次 process_stream 创建新的根 controller，
        # 流结束时 abort 清理所有子任务（工具执行、子代理等）
        self.root_abort_controller: Optional[AbortController] = None

        # 工具定义实例级缓存：按技能/插件/MCP 工具版本失效
        # 避免每次 process_stream 重复构建 _build_native_tools 的开销
        _init_total_ms = round((time.time() - _init_t0) * 1000, 2)
        logger.bind(
            event="agent_init_breakdown",
            module="agent",
            layers_ms=_init_layers_ms,
            skill_engine_ms=_skill_engine_ms,
            plugin_manager_ms=_plugin_manager_ms,
            memory_engine_ms=_memory_engine_ms,
            total_ms=_init_total_ms,
        ).info(f"AIAgent 构造耗时分解: layers={_init_layers_ms}ms, skill_engine={_skill_engine_ms}ms, plugin_manager={_plugin_manager_ms}ms, memory_engine={_memory_engine_ms}ms, total={_init_total_ms}ms")
        logger.info("AI Agent initialized with SkillEngine and PluginManager integration")

    def bind_db(self, db_session: Session) -> None:
        """
        绑定请求级数据库会话。
        在 AIAgentRegistry.get_or_create 中调用，确保复用实例时使用本次请求的 db。
        同时更新已构造的子引擎（SkillEngine/WorkflowEngine）及其内部 registry 的 db 引用。
        请求结束后由 FastAPI Depends get_db 自动关闭，本方法不负责 close。

        注意：SkillRegistry 内部持有 db 引用与缓存（_cache/_list_cache），
        缓存的 Skill 对象绑定到旧 session，访问属性会触发 DetachedInstanceError。
        因此 bind_db 时必须同步更新 registry.db 并清空其缓存，强制下次查询使用新 session。
        """
        self._db_session_request = db_session
        # 同步更新子引擎的 db 引用（SkillEngine/WorkflowEngine 均使用 db_session 属性名）
        if hasattr(self, 'skill_engine') and self.skill_engine is not None:
            try:
                self.skill_engine.db_session = db_session
            except (AttributeError, TypeError):
                # 子引擎可能用其他属性名或不可变，尝试常见属性名
                for attr_name in ('_db', 'db', '_db_session'):
                    if hasattr(self.skill_engine, attr_name):
                        try:
                            setattr(self.skill_engine, attr_name, db_session)
                            break
                        except (AttributeError, TypeError):
                            continue
            # 同步更新 SkillRegistry 的 db 引用并清空缓存
            # 缓存的 Skill 对象绑定到旧 session，复用会触发 DetachedInstanceError
            registry = getattr(self.skill_engine, 'registry', None)
            if registry is not None:
                try:
                    registry.db = db_session
                except (AttributeError, TypeError):
                    pass
                # 清空单条缓存与 list_all 缓存，强制下次查询使用新 session
                _cache = getattr(registry, '_cache', None)
                if isinstance(_cache, dict):
                    _cache.clear()
                _list_cache = getattr(registry, '_list_cache', None)
                if _list_cache is not None:
                    try:
                        setattr(registry, '_list_cache', None)
                    except (AttributeError, TypeError):
                        pass
        if hasattr(self, 'workflow_engine') and self.workflow_engine is not None:
            try:
                self.workflow_engine.db_session = db_session
            except (AttributeError, TypeError):
                for attr_name in ('_db', 'db', '_db_session'):
                    if hasattr(self.workflow_engine, attr_name):
                        try:
                            setattr(self.workflow_engine, attr_name, db_session)
                            break
                        except (AttributeError, TypeError):
                            continue

    @property
    def _db_session(self) -> Optional[Session]:
        """动态返回当前有效的 db session：优先请求级 bind 的 db，回退到 __init__ 的 db。"""
        if self._db_session_request is not None:
            return self._db_session_request
        return self._db_session_bound

    @property
    def _capabilities_cache(self) -> Optional[Dict[str, Any]]:
        """兼容既有调用，返回能力聚合器持有的缓存。"""
        return self._capability_aggregator.capabilities_cache

    @_capabilities_cache.setter
    def _capabilities_cache(self, value: Optional[Dict[str, Any]]) -> None:
        self._capability_aggregator.capabilities_cache = value

    @property
    def _capabilities_cache_ts(self) -> float:
        """兼容既有调用，返回能力缓存时间戳。"""
        return self._capability_aggregator.capabilities_cache_ts

    @_capabilities_cache_ts.setter
    def _capabilities_cache_ts(self, value: float) -> None:
        self._capability_aggregator.capabilities_cache_ts = value

    @property
    def _tools_cache(self) -> Optional[List[Dict[str, Any]]]:
        """兼容既有调用，返回原生工具缓存。"""
        return self._capability_aggregator.tools_cache

    @_tools_cache.setter
    def _tools_cache(self, value: Optional[List[Dict[str, Any]]]) -> None:
        self._capability_aggregator.tools_cache = value

    @property
    def _tools_cache_version(self) -> str:
        """兼容既有调用，返回工具缓存版本。"""
        return self._capability_aggregator.tools_cache_version

    @_tools_cache_version.setter
    def _tools_cache_version(self, value: str) -> None:
        self._capability_aggregator.tools_cache_version = value

    def invalidate_capabilities_cache(self) -> None:
        """
        主动失效实例级 capabilities 与 tools 缓存。

        在插件 load/unload、MCP server connect/disconnect、技能启用/禁用等
        影响能力集合的事件发生后调用，确保下一次 process_stream 重建 capabilities。
        若不调用，TTL（默认 30 秒）到期后也会自动失效重建。
        """
        self._capability_aggregator.invalidate()
        logger.bind(
            event="capabilities_cache_invalidated",
            module="agent",
        ).debug("capabilities 与 tools 实例级缓存已主动失效")

    async def _record_with_backpressure(self, coro) -> Any:
        """
        通过信号量限制并发 fire-and-forget 记录任务数，防止高并发下 Task 堆积。
        """
        async with self._record_semaphore:
            return await coro

    def _handle_record_task_result(self, task: asyncio.Task) -> None:
        """
        检查后台记录任务（行为日志/对话记录）的执行结果，
        对取消和异常情况记录告警日志，避免 fire-and-forget 任务静默失败。
        """
        try:
            if task.cancelled():
                logger.warning("Conversation recorder task was cancelled")
                return

            exc = task.exception()
            if exc is not None:
                logger.warning(f"Conversation recorder task failed: {exc}")
                return

            task.result()
        except Exception as e:
            logger.warning(f"Conversation recorder task failed: {e}")

    def _strip_reasoning_content(self, payload: Any) -> Any:
        """Deprecated: 请使用 agent_context_builder.strip_reasoning_content"""
        return strip_reasoning_content(payload)

    def _apply_output_mode(self, payload: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """
        根据上下文裁剪对外响应，确保渠道级输出模式真正落到返回值上。
        """
        if not is_final_only_mode(context):
            return payload
        return self._strip_reasoning_content(payload)

    def _apply_scheduled_execution_defaults(self, context: Dict[str, Any]) -> None:
        """Deprecated: 请使用 agent_context_builder.apply_scheduled_execution_defaults"""
        apply_scheduled_execution_defaults(context)

    def _prepare_context(self, user_input: str, context: Dict[str, Any]) -> None:
        """
        统一补齐执行上下文，保证数据库会话与隔离开关能够透传到执行层。
        """
        self._apply_scheduled_execution_defaults(context)

        if "message" not in context:
            context["message"] = user_input

        if self._db_session and context.get("db") is None:
            context["db"] = self._db_session

        context["_record_hook"] = self._schedule_record

    def _build_multimodal_context(self, user_input: str, context: Dict[str, Any]) -> None:
        """Deprecated: 请使用 agent_context_builder.build_multimodal_context"""
        build_multimodal_context(user_input, context)

    def _build_thinking_context(self, context: Dict[str, Any]) -> None:
        """Deprecated: 请使用 agent_context_builder.build_thinking_context"""
        build_thinking_context(context)

    def _record_round_budget_usage(
        self,
        *,
        user_input: str,
        context: Dict[str, Any],
        round_content: str,
        round_reasoning: str,
    ) -> None:
        """
        估算并记录本轮 LLM 调用的 token 使用量到预算追踪器。

        流式响应不直接返回 usage 信息，因此基于本轮输入和输出文本进行启发式估算：
        - 输入 token：用户输入 + 对话历史
        - 输出 token：本轮生成的内容 + 推理内容

        参数:
            user_input: 本轮有效的用户输入
            context: 执行上下文，可能包含 conversation_history
            round_content: 本轮 LLM 生成的回复内容
            round_reasoning: 本轮 LLM 生成的推理内容
        """
        token_budget = TokenBudget()

        # 估算输入 token：用户输入 + 对话历史
        input_text = user_input or ""
        conversation_history = context.get("conversation_history", [])
        if isinstance(conversation_history, list):
            for msg in conversation_history:
                if isinstance(msg, dict):
                    content = msg.get("content", "")
                    if isinstance(content, str):
                        input_text += " " + content
        input_tokens = token_budget.estimate_tokens(input_text)

        # 估算输出 token：本轮生成的内容 + 推理内容
        output_text = (round_content or "") + (round_reasoning or "")
        output_tokens = token_budget.estimate_tokens(output_text)

        self.budget_tracker.record_usage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    # Deprecated: 仅为兼容测试 AIAgent._summarize_skill_capabilities(...) 调用，
    # 待 fix-test-implementation-coupling spec 落地后移除。
    _summarize_skill_capabilities = staticmethod(summarize_skill_capabilities)

    # Deprecated: 仅为兼容测试 AIAgent._summarize_plugin_capabilities(...) 调用，
    # 待 fix-test-implementation-coupling spec 落地后移除。
    _summarize_plugin_capabilities = staticmethod(summarize_plugin_capabilities)

    async def _collect_mcp_capabilities(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Deprecated: 请使用 agent_capability_builder.collect_mcp_capabilities"""
        return await collect_mcp_capabilities(context)

    def _collect_configured_model_capabilities(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Deprecated: 请使用 agent_capability_builder.collect_configured_model_capabilities"""
        return collect_configured_model_capabilities(context, self._db_session)

    async def _inject_runtime_capabilities(self, context: Dict[str, Any]) -> None:
        """
        在进入最终模型回答前，把当前会话可用的技能、插件和 MCP 连接态写入上下文。
        这样模型在回答“我能不能调用某能力”时能基于真实运行态，而不是凭空猜测。
        """
        await self._capability_aggregator.inject(
            context,
            get_available_skills=self.get_available_skills,
            get_available_plugins=self.get_available_plugins,
            summarize_skills=self._summarize_skill_capabilities,
            summarize_plugins=self._summarize_plugin_capabilities,
            collect_configured_models=self._collect_configured_model_capabilities,
            collect_mcp=self._collect_mcp_capabilities,
            build_native_tools=self._build_native_tools,
        )

    @staticmethod
    def _compute_tools_version(context: Dict[str, Any]) -> str:
        """
        基于当前会话可用的技能/插件/MCP 工具集合生成版本字符串。
        任一关键能力变更（启用/禁用、工具增减、MCP 派发开关）时版本变化，
        触发 AIAgent 实例级工具定义缓存失效，避免返回过期 tool 定义。
        """
        import hashlib

        capabilities = context.get("agent_capabilities")
        if not isinstance(capabilities, dict):
            return ""

        skills_raw = capabilities.get("skills")
        skills_signature = [
            {"name": str(s.get("name", ""))}
            for s in (skills_raw if isinstance(skills_raw, list) else [])
            if isinstance(s, dict)
        ]

        plugins_raw = capabilities.get("plugins")
        plugins_signature = [
            {
                "name": str(p.get("name", "")),
                "loaded": bool(p.get("loaded", False)),
                "tool_names": [
                    str(t.get("name", ""))
                    for t in (p.get("tools") if isinstance(p.get("tools"), list) else [])
                    if isinstance(t, dict)
                ],
            }
            for p in (plugins_raw if isinstance(plugins_raw, list) else [])
            if isinstance(p, dict)
        ]

        mcp_raw = capabilities.get("mcp")
        mcp = mcp_raw if isinstance(mcp_raw, dict) else {}
        mcp_tools = mcp.get("tools") if isinstance(mcp.get("tools"), list) else []
        mcp_signature = {
            "chat_dispatch_enabled": bool(mcp.get("chat_dispatch_enabled", False)),
            "tool_count": len(mcp_tools),
        }

        payload = {
            "skills": skills_signature,
            "plugins": plugins_signature,
            "mcp": mcp_signature,
        }
        payload_json = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.md5(payload_json.encode("utf-8")).hexdigest()

    @staticmethod
    def _build_native_tools(capabilities: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        将 agent_capabilities 中的插件/MCP 工具转换为 OpenAI 兼容的 tools 参数格式，
        使 LLM 能通过原生 function calling 协议触发工具调用，而不是在文本中模拟。
        """
        tools: List[Dict[str, Any]] = []
        seen_names: set = set()

        plugins = (
            capabilities.get("plugins")
            if isinstance(capabilities.get("plugins"), list)
            else []
        )
        for plugin in plugins:
            if not isinstance(plugin, dict):
                continue
            plugin_name = str(plugin.get("name", "")).strip()
            if not plugin_name:
                continue
            plugin_tools = plugin.get("tools") if isinstance(plugin.get("tools"), list) else []
            for tool_def in plugin_tools:
                if not isinstance(tool_def, dict):
                    continue
                tool_name = str(tool_def.get("name", "")).strip()
                if not tool_name:
                    continue

                func_name = f"plugin_{plugin_name}__{tool_name}"
                if func_name in seen_names:
                    continue
                seen_names.add(func_name)

                params = tool_def.get("parameters")
                if not isinstance(params, dict) or not params:
                    params = {"type": "object", "properties": {}}

                tool_entry = {
                    "type": "function",
                    "function": {
                        "name": func_name,
                        "description": str(tool_def.get("description", "")),
                        "parameters": params,
                    },
                }
                tools.append(tool_entry)

        # MCP 工具也转换为原生 tool_calls
        mcp = capabilities.get("mcp") if isinstance(capabilities.get("mcp"), dict) else {}
        if mcp.get("chat_dispatch_enabled", False):
            mcp_tools = mcp.get("tools") if isinstance(mcp.get("tools"), list) else []
            for mcp_tool in mcp_tools:
                if not isinstance(mcp_tool, dict):
                    continue
                server_name = str(mcp_tool.get("server_name", mcp_tool.get("server_id", ""))).strip()
                tool_name = str(mcp_tool.get("name", "")).strip()
                if not server_name or not tool_name:
                    continue

                func_name = f"mcp_{server_name}__{tool_name}"
                if func_name in seen_names:
                    continue
                seen_names.add(func_name)

                mcp_params = mcp_tool.get("parameters")
                if not isinstance(mcp_params, dict) or not mcp_params:
                    mcp_params = {"type": "object", "properties": {}}

                tool_entry = {
                    "type": "function",
                    "function": {
                        "name": func_name,
                        "description": str(mcp_tool.get("description", "")),
                        "parameters": mcp_params,
                    },
                }
                tools.append(tool_entry)

        # 内置工具（文件管理、终端执行、网页搜索）
        try:
            from core.builtin_tools.manager import builtin_tool_manager
            builtin_defs = builtin_tool_manager.get_tool_definitions()
            for bt in builtin_defs:
                func_name = bt.get("function", {}).get("name", "")
                if func_name and func_name not in seen_names:
                    seen_names.add(func_name)
                    tools.append(bt)
        except Exception:
            logger.bind(module="agent", event="builtin_tools_load_error").warning(
                "加载内置工具定义失败，跳过内置工具"
            )

        if tools:
            logger.bind(
                event="native_tools_built",
                module="agent",
                tool_count=len(tools),
            ).debug(f"已构建 {len(tools)} 个原生工具定义")

        # 追加任务运行时工具定义
        try:
            from core.task_runtime.definitions import list_agent_types
            # 触发 task_runtime 可用性校验；agent_types 不再用于本方法体（已迁移到
            # build_task_runtime_tool_definitions 内部），保留调用以维持原降级行为。
            agent_types = list_agent_types()  # noqa: F841
            model_hint = AIAgent._build_configured_model_hint(capabilities)
            task_tools = build_task_runtime_tool_definitions(model_hint)
            for bt in task_tools:
                func_name = bt.get("function", {}).get("name", "")
                if func_name and func_name not in seen_names:
                    seen_names.add(func_name)
                    tools.append(bt)
        except Exception:
            logger.bind(module="agent", event="task_tools_load_error").warning(
                "加载任务运行时工具定义失败，跳过任务工具"
            )

        return tools

    def _schedule_record(
        self,
        *,
        node_type: str,
        user_message: str,
        context: Dict[str, Any],
        status: str = "success",
        error_message: Optional[str] = None,
        llm_input: Any = None,
        llm_output: Any = None,
        llm_tokens_used: Optional[int] = None,
        token_breakdown: Optional[TokenBreakdown] = None,
        execution_duration_ms: Optional[int] = None,
        metadata: Any = None,
    ) -> None:
        """
        将对话节点（LLM调用/工具执行/意图识别）通过后台任务异步记录到行为日志和对话记录表。
        受 scheduled_execution_isolated 开关控制，定时任务执行时不写入记录以避免污染。

        token 计数来源优先级：
        1. token_breakdown 非 None 时直接使用（携带 input/output/cache 等明细）
        2. 否则从 llm_tokens_used 构造简单 breakdown（向后兼容旧调用方）
        最终 llm_tokens_used 从 breakdown.total_tokens 派生，保证下游记录器一致。
        """
        self._behavior_recorder.schedule(
            node_type=node_type,
            user_message=user_message,
            context=context,
            db_session=self._db_session,
            status=status,
            error_message=error_message,
            llm_input=llm_input,
            llm_output=llm_output,
            llm_tokens_used=llm_tokens_used,
            token_breakdown=token_breakdown,
            execution_duration_ms=execution_duration_ms,
            metadata=metadata,
        )

    def _build_behavior_entries(
        self,
        *,
        user_id: str,
        node_type: str,
        status: str,
        error_message: Optional[str],
        llm_output: Any,
        llm_tokens_used: Optional[int],
        execution_duration_ms: Optional[int],
        metadata: Any,
    ) -> List[Dict[str, Any]]:
        """
        将运行态信息整理成轻量埋点结构，交给后台队列统一批量落库。
        这里仅做内存对象拼装，不直接触发数据库操作。
        """
        return build_behavior_entries(
            user_id=user_id,
            node_type=node_type,
            status=status,
            error_message=error_message,
            llm_output=llm_output,
            llm_tokens_used=llm_tokens_used,
            execution_duration_ms=execution_duration_ms,
            metadata=metadata,
        )

    async def execute_skill(self, skill_name: str, inputs: Dict, context: Dict) -> Dict[str, Any]:
        """
        通过 SkillEngine 执行指定技能，收集执行结果并记录到 skill_results 列表。
        成功时返回包含 outputs 和 steps 的结构化结果，失败时返回错误信息。
        """
        logger.info(f"Executing skill: {skill_name}")
        try:
            result = await self.skill_engine.execute_skill(skill_name, inputs, context)
            
            self.skill_results.append({
                'skill_name': skill_name,
                'result': result,
                'success': result.get('success', False)
            })
            
            if result.get('success'):
                logger.info(f"Skill '{skill_name}' executed successfully")
                return {
                    'status': 'completed',
                    'skill_name': skill_name,
                    'outputs': result.get('outputs', {}),
                    'steps': result.get('steps', []),
                    'execution_id': result.get('execution_id'),
                    'metrics': result.get('metrics', {})
                }
            else:
                logger.error(f"Skill '{skill_name}' execution failed: {result.get('error')}")
                return {
                    'status': 'error',
                    'skill_name': skill_name,
                    'error': result.get('error', 'Unknown error'),
                    'outputs': result.get('outputs', {}),
                    'execution_id': result.get('execution_id')
                }
        except Exception as e:
            logger.bind(
                event="skill_execution_error",
                module="agent",
                error_type=type(e).__name__,
                skill_name=skill_name,
            ).opt(exception=True).error(f"技能 '{skill_name}' 执行异常: {e}")
            return {
                'status': 'error',
                'skill_name': skill_name,
                'error': str(e)
            }
    
    async def execute_plugin(self, plugin_name: str, method: str, **kwargs) -> Any:
        """
        加载并异步执行指定插件的目标方法。若插件未加载则自动加载。
        将执行结果（成功/失败）记录到 plugin_results 列表，用于后续汇总统计。
        """
        logger.info(f"Executing plugin '{plugin_name}' method '{method}'")
        try:
            if plugin_name not in self.plugin_manager.loaded_plugins:
                load_result = self.plugin_manager.load_plugin(plugin_name)
                if not load_result:
                    logger.error(f"Failed to load plugin '{plugin_name}'")
                    return {
                        'status': 'error',
                        'message': f"Plugin '{plugin_name}' not found or failed to load"
                    }
            
            result = await self.plugin_manager.execute_plugin_async(plugin_name, method, **kwargs)
            
            self.plugin_results.append({
                'plugin_name': plugin_name,
                'method': method,
                'result': result,
                'success': result.get('status') == 'success'
            })
            
            status = result.get('status', 'error')

            if status == 'success':
                logger.info(f"Plugin '{plugin_name}' method '{method}' executed successfully")
                return {
                    'status': 'completed',
                    'data': result.get('data') if result.get('data') is not None else result.get('result'),
                    'message': result.get('message', '')
                }

            logger.error(f"Plugin '{plugin_name}' method '{method}' failed: {result.get('message')}")
            response = {
                'status': 'error' if status == 'error' else status,
                'message': result.get('message', 'Unknown error')
            }
            if result.get('data') is not None:
                response['data'] = result.get('data')
            if result.get('required_permissions') is not None:
                response['required_permissions'] = result.get('required_permissions')
            return response
        except Exception as e:
            logger.bind(
                event="plugin_execution_error",
                module="agent",
                error_type=type(e).__name__,
                plugin_name=plugin_name,
                method=method,
            ).opt(exception=True).error(f"插件 '{plugin_name}' 方法 '{method}' 执行异常: {e}")
            return {
                'status': 'error',
                'message': str(e)
            }
    
    async def get_available_skills(self) -> List[Dict[str, Any]]:
        """
        获取available、skills相关数据或当前状态。
        调用方通常依赖该结果继续进行后续判断、渲染或业务编排。
        """
        logger.info("Getting available skills")
        if self._db_session is None:
            logger.info("No database session available, returning empty skill list")
            return []
        try:
            registry = self.skill_engine.registry
            skills = registry.list_all()
            
            skill_list = []
            for skill in skills:
                stats = self.skill_engine.get_skill_statistics(skill.name)
                # 直接从 list_all 返回的 ORM 对象读取 config，
                # 避免 load_from_db 的额外数据库查询。config 字段是 JSON 类型，SQLAlchemy 已自动反序列化为 dict。
                skill_config = skill.config if isinstance(skill.config, dict) else {}
                skill_list.append({
                    'name': skill.name,
                    'version': skill.version,
                    'description': skill.description,
                    'enabled': skill.enabled,
                    'usage_count': skill.usage_count,
                    'stats': stats,
                    'config': skill_config,
                })
            
            logger.info(f"Found {len(skill_list)} available skills")
            return skill_list
        except Exception as e:
            logger.bind(
                event="get_skills_error",
                module="agent",
                error_type=type(e).__name__,
            ).opt(exception=True).error(f"获取可用技能列表失败: {e}")
            return []
    
    async def get_available_plugins(self) -> List[Dict[str, Any]]:
        """
        获取available、plugins相关数据或当前状态。
        未 loaded 的插件返回 loaded=False, tools=[]，不再触发 lazy load。
        """
        logger.info("Getting available plugins")
        try:
            discovered_plugins = self.plugin_manager.discover_plugins()

            plugin_list = []
            for plugin_info in discovered_plugins:
                plugin_name = plugin_info.get('name')
                if not plugin_name:
                    continue

                if plugin_name not in self.plugin_manager.loaded_plugins:
                    # 未 loaded 的插件不再 lazy load，直接返回空 tools
                    # lifespan startup 已加载所有 enabled 插件，未 loaded 意味着用户禁用或加载失败
                    plugin_list.append({
                        'name': plugin_name,
                        'version': plugin_info.get('version'),
                        'description': plugin_info.get('description'),
                        'loaded': False,
                        'tools': [],
                    })
                    continue

                # 已 loaded 的插件正常读取 tools 与 info
                tools = self.plugin_manager.get_plugin_tools(plugin_name)
                info = self.plugin_manager.get_plugin_info(plugin_name)

                plugin_list.append({
                    'name': plugin_name,
                    'version': plugin_info.get('version'),
                    'description': plugin_info.get('description'),
                    'loaded': info.get('loaded', False) if info else False,
                    'tools': tools,
                })

            logger.info(f"Found {len(plugin_list)} available plugins (loaded: {len(self.plugin_manager.loaded_plugins)})")
            return plugin_list
        except Exception as e:
            logger.bind(
                event="get_plugins_error",
                module="agent",
                error_type=type(e).__name__,
            ).opt(exception=True).error(f"获取可用插件列表失败: {e}")
            return []
    
    async def _build_conversation_history(self, session_id: str, max_turns: int = 20) -> list:
        """
        从记忆管理器中构建对话历史消息列表，用于注入到 LLM 调用中。
        返回 [{"role": "user"|"assistant", "content": "..."}] 格式。
        对单条消息内容做字符截断，防止超大消息撑爆上下文窗口。
        """
        MAX_MSG_CHARS = 5_000
        if not self.memory_manager:
            return []
        try:
            memories = await self.memory_manager.get_short_term_memories(
                session_id=session_id, limit=max_turns
            )
            history = []
            for mem in reversed(memories):
                if mem.role in ("user", "assistant"):
                    content = mem.content or ""
                    original_len = len(content)
                    if original_len > MAX_MSG_CHARS:
                        content = content[:MAX_MSG_CHARS] + (
                            f"\n[消息已截断，原始长度: {original_len} 字符]"
                        )
                    history.append({"role": mem.role, "content": content})
            return history
        except Exception as e:
            logger.warning(f"构建对话历史失败: {e}")
            return []

    async def _check_and_handle_magic_command(
        self, user_input: str, context: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        检测用户输入是否包含魔法命令，如果匹配则执行对应处理程序。
        返回命令执行结果字典，如果不是命令则返回 None。
        """
        registry = get_magic_command_registry()
        cmd_name, cmd_args, remaining = registry.parse_message(user_input)
        if cmd_name is None:
            return None

        command = registry.get_command(cmd_name)
        if command is None:
            return {
                "is_command": True,
                "command_name": cmd_name,
                "success": False,
                "message": f"未知命令: /{cmd_name}，输入 /help 查看可用命令",
            }

        logger.bind(
            event="magic_command_detected",
            command=cmd_name,
            session_id=context.get("session_id", ""),
        ).info(f"检测到魔法命令: /{cmd_name}")

        try:
            ctx = {
                "session_id": context.get("session_id", "default"),
                "workspace_id": context.get("workspace_id", "default"),
                "user_id": context.get("user_id", ""),
                "model_name": context.get("model", "default"),
                "db": context.get("db"),
            }
            result = await command.handler(ctx)
            result["is_command"] = True
            result["command_name"] = cmd_name
            return result
        except Exception as exc:
            logger.bind(
                event="magic_command_error",
                command=cmd_name,
            ).error(f"魔法命令执行失败: {exc}")
            return {
                "is_command": True,
                "command_name": cmd_name,
                "success": False,
                "message": f"命令执行失败: {str(exc)}",
            }

    async def _auto_compress_context(
        self, context: Dict[str, Any], messages: list
    ) -> list:
        """
        自动检测并压缩对话上下文。
        当 token 使用量超过阈值时触发压缩，返回压缩后的消息列表。
        使用 CompactionManager 进行结构化摘要压缩，断路器保护避免反复失败。
        """
        model_name = context.get("model", "default")
        budget = TokenBudget(model_name=model_name)
        current_tokens = budget.count_messages(messages)
        # 更新计数器后检查压缩阈值
        budget.track(current_tokens)

        if not budget.should_compress() and len(messages) <= 40:
            return messages

        # 使用 CompactionManager 进行压缩，窗口大小取自 TokenBudget
        compaction = CompactionManager(model_context_window=budget.max_tokens)

        # 设置 LLM 调用函数：复用 executor 的 LLM 配置解析与调用能力
        # 构建最小化上下文，仅包含配置解析所需字段，避免注入对话历史
        async def _compaction_llm_call(prompt: str, **kwargs) -> str:
            summary_ctx: Dict[str, Any] = {
                "provider": context.get("provider"),
                "model": context.get("model"),
                "db": context.get("db"),
                "request_id": context.get("request_id"),
            }
            try:
                result = await self.executor._call_llm_api(prompt, summary_ctx)
                if isinstance(result, dict) and result.get("ok"):
                    return result.get("response", "") or ""
                return ""
            except Exception as exc:
                logger.warning(f"压缩摘要 LLM 调用失败: {exc}")
                return ""

        compaction.set_llm_call(_compaction_llm_call)

        result = await compaction.compact(messages=messages)
        compressed_messages = result["messages"]

        logger.bind(
            event="auto_context_compressed",
            original_count=len(messages),
            compressed_count=len(compressed_messages),
            tokens_before=current_tokens,
            tokens_after=budget.count_messages(compressed_messages),
            compacted=result.get("compacted", False),
        ).info("对话上下文已自动压缩")
        return compressed_messages

    async def process_stream(self, user_input: str, context: Dict[str, Any]):
        """
        流式处理用户输入，注入对话历史后调用大模型并实时 yield 数据块。
        支持 tool_calls 循环：检测到工具调用时自动执行并将结果回传 LLM。
        支持多模态附件和思考模式参数。
        优先检测魔法命令，匹配时跳过 LLM 处理。
        """
        # TTFT 诊断计时点：记录 process_stream 入口时间，用于定位首个事件延迟根因
        _ttft_t0 = time.time()
        _ttft_session_id = context.get("session_id", "")
        logger.info(f"Processing user input (stream), length={len(user_input)}")

        # 清空上一次请求的残留状态（AIAgent 实例复用场景下必需）
        self.skill_results = []
        self.plugin_results = []

        # 创建本轮流的根中止控制器，所有工具执行和子代理共享其子 controller
        # 流结束（正常或异常）时调用 abort() 清理所有子任务
        self.root_abort_controller = AbortController()

        # 检测魔法命令
        cmd_result = await self._check_and_handle_magic_command(user_input, context)
        if cmd_result is not None:
            import json as _json
            yield {
                "type": "magic_command",
                "command_name": cmd_result.get("command_name", ""),
                "content": _json.dumps(cmd_result, ensure_ascii=False, default=str),
            }
            if cmd_result.get("clears_context"):
                yield {"type": "context_cleared", "content": ""}
            return

        yield build_status_event("starting", "正在准备对话上下文")

        # TTFT 诊断：首个 SSE 事件已发出，记录从入口到此处的耗时
        logger.bind(
            event="ttft_first_event",
            module="agent",
            session_id=_ttft_session_id,
            elapsed_ms=round((time.time() - _ttft_t0) * 1000, 2),
        ).info("首个 SSE 事件已发送（TTFT 基准点）")

        self._prepare_context(user_input, context)

        # 灵魂注入开关检查：若禁用则跳过角色引擎
        role_id = context.get("role_id")
        soul_injection_enabled = True
        if hasattr(self, 'soul_state_manager') and self.soul_state_manager is not None:
            try:
                soul_injection_enabled = self.soul_state_manager.is_injection_enabled()
                if not soul_injection_enabled:
                    logger.bind(event="soul_injection_skipped", module="agent").info(
                        f"灵魂注入已禁用，跳过角色引擎加载 (workspace_id={context.get('workspace_id', 'unknown')})"
                    )
            except Exception as e:
                logger.bind(event="soul_state_check_error", module="agent").warning(
                    f"灵魂状态检查失败，默认启用角色引擎: {e}"
                )

        # 角色引擎集成：如果上下文中有 role_id，加载角色配置并应用
        if role_id and soul_injection_enabled:
            request_db = context.get("db")
            if request_db is None:
                logger.bind(event="role_engine_no_db", module="agent").warning(
                    "context['db'] 不可用，跳过角色引擎加载"
                )
            else:
                try:
                    _role_t0 = time.time()
                    from core.role_engine import RoleEngine
                    role_engine = RoleEngine(db=request_db)
                    role = role_engine.load_role(role_id)
                    if role:
                        context = role_engine.apply_role_to_context(role, context)
                        # 角色引擎加载成功，标记灵魂注入完成
                        if hasattr(self, 'soul_state_manager') and self.soul_state_manager is not None:
                            try:
                                self.soul_state_manager.mark_injection_completed()
                            except Exception as e:
                                logger.bind(event="soul_state_mark_error", module="agent").warning(
                                    f"标记灵魂注入完成失败: {e}"
                                )
                    logger.bind(
                        event="ttft_stage",
                        module="agent",
                        stage="role_engine",
                        session_id=_ttft_session_id,
                        elapsed_ms=round((time.time() - _role_t0) * 1000, 2),
                        total_ms=round((time.time() - _ttft_t0) * 1000, 2),
                    ).info("阶段耗时: role_engine")
                except Exception as e:
                    logger.bind(event="role_engine_error", module="agent").warning(f"角色引擎加载失败: {e}")

        _cap_t0 = time.time()
        await self._inject_runtime_capabilities(context)
        logger.bind(
            event="ttft_stage",
            module="agent",
            stage="inject_capabilities",
            session_id=_ttft_session_id,
            elapsed_ms=round((time.time() - _cap_t0) * 1000, 2),
            total_ms=round((time.time() - _ttft_t0) * 1000, 2),
        ).info("阶段耗时: inject_capabilities")

        # 构建多模态消息内容（若用户上传了附件）
        self._build_multimodal_context(user_input, context)

        # 构建思考模式参数（若用户开启了思考）
        self._build_thinking_context(context)

        # 构建对话历史并注入到上下文中
        session_id = context.get("session_id", "default")
        task_user_id = str(context.get("user_id", ""))

        # 将当前协程注册为活跃任务，供取消端点查找
        current_task = asyncio.current_task()
        if current_task is not None and session_id:
            register_agent_task(task_user_id, session_id, current_task)

        # 提前初始化流式处理变量，避免 try 块早期异常导致 finally 中引用未定义变量
        full_content = ""
        full_reasoning = ""
        accumulated_tool_events: list = []
        _stream_start_time = time.time()

        try:
            _hist_t0 = time.time()
            conversation_history = await self._build_conversation_history(session_id)
            logger.bind(
                event="ttft_stage",
                module="agent",
                stage="build_history",
                session_id=_ttft_session_id,
                elapsed_ms=round((time.time() - _hist_t0) * 1000, 2),
                total_ms=round((time.time() - _ttft_t0) * 1000, 2),
            ).info("阶段耗时: build_history")
            # 触发压缩前向用户发送状态事件，避免长时间无响应被误认为卡死
            # 简单判断：消息数超过 40 时先 yield 进度，与 _auto_compress_context 内部阈值一致
            if len(conversation_history) > 40:
                yield build_status_event("compressing", "正在压缩对话上下文")
            # 自动检测并压缩上下文
            _compress_t0 = time.time()
            context["conversation_history"] = await self._auto_compress_context(
                context, conversation_history
            )
            if _compress_t0 and (time.time() - _compress_t0) > 0.05:
                logger.bind(
                    event="ttft_stage",
                    module="agent",
                    stage="auto_compress",
                    session_id=_ttft_session_id,
                    elapsed_ms=round((time.time() - _compress_t0) * 1000, 2),
                    total_ms=round((time.time() - _ttft_t0) * 1000, 2),
                ).info("阶段耗时: auto_compress")

            effective_user_input = build_effective_user_input(user_input, context)

            # 自动检索相关长期记忆（stream 路径）
            if context.get("retrieve_long_term_memory", True) and self.memory_manager:
                try:
                    _mem_t0 = time.time()
                    relevant_memories = await self._retrieve_relevant_memories(
                        user_input=effective_user_input,
                        context=context,
                    )
                    logger.bind(
                        event="ttft_stage",
                        module="agent",
                        stage="retrieve_memories",
                        session_id=_ttft_session_id,
                        elapsed_ms=round((time.time() - _mem_t0) * 1000, 2),
                        total_ms=round((time.time() - _ttft_t0) * 1000, 2),
                        memory_count=len(relevant_memories) if relevant_memories else 0,
                    ).info("阶段耗时: retrieve_memories")
                    if relevant_memories:
                        context["vector_retrieved_memories"] = relevant_memories
                        logger.info(f"Stream: 检索到 {len(relevant_memories)} 条相关长期记忆")
                except (SQLAlchemyError, asyncio.TimeoutError, ValueError) as mem_err:
                    logger.warning(f"Stream 自动记忆检索失败: {mem_err}")

            _intent_t0 = time.time()
            intent = await self.comprehension.recognize_intent(effective_user_input)
            logger.bind(
                event="ttft_stage",
                module="agent",
                stage="recognize_intent",
                session_id=_ttft_session_id,
                elapsed_ms=round((time.time() - _intent_t0) * 1000, 2),
                total_ms=round((time.time() - _ttft_t0) * 1000, 2),
            ).info("阶段耗时: recognize_intent")

            _entity_t0 = time.time()
            entities = await self.comprehension.extract_entities(effective_user_input)
            logger.bind(
                event="ttft_stage",
                module="agent",
                stage="extract_entities",
                session_id=_ttft_session_id,
                elapsed_ms=round((time.time() - _entity_t0) * 1000, 2),
                total_ms=round((time.time() - _ttft_t0) * 1000, 2),
            ).info("阶段耗时: extract_entities")

            yield build_status_event("planning", "正在生成执行计划")
            _plan_t0 = time.time()
            plan = await self.planner.create_plan(
                intent=intent,
                entities=entities,
                context=context,
            )
            logger.bind(
                event="ttft_stage",
                module="agent",
                stage="create_plan",
                session_id=_ttft_session_id,
                elapsed_ms=round((time.time() - _plan_t0) * 1000, 2),
                total_ms=round((time.time() - _ttft_t0) * 1000, 2),
            ).info("阶段耗时: create_plan")
            context["plan"] = plan
            yield {
                "type": "plan",
                "plan": plan,
            }

            # 流式变量已在 try 块前初始化，此处无需重复赋值

            final_only_mode = is_final_only_mode(context)

            # 初始化 RollbackManager，供工具调用循环和自主纠错使用
            if not context.get("_rollback_manager"):
                from core.rollback import RollbackManager
                context["_rollback_manager"] = RollbackManager()

            round_count = 0
            max_rounds = resolve_max_tool_call_rounds(context)

            # 显式状态机：初始状态为继续工具调用，终态时退出循环
            state = AgentState.CONTINUE_TOOL_CALLS
            while not state.is_terminal and not self.budget_tracker.is_near_completion():
                # 在每轮循环开始检查取消信号
                if current_task and current_task.cancelled():
                    yield {"type": "cancelled", "content": "", "reasoning_content": ""}
                    return
                round_count += 1
                tool_calls_detected = False
                round_content = ""
                round_reasoning = ""
                background_subagents_spawned = False

                # 在每次 LLM 调用前应用工具结果预算：替换旧工具结果以控制 token 用量
                _tool_messages_for_budget = context.get("_tool_messages", [])
                if _tool_messages_for_budget:
                    _tool_result_budget = self.budget_tracker.max_input_tokens // 4
                    context["_tool_messages"] = enforce_tool_result_budget(
                        _tool_messages_for_budget,
                        self.content_replacement_state,
                        _tool_result_budget,
                    )

                async for chunk in self.executor._call_llm_api_stream(effective_user_input, context):
                    if "error" in chunk:
                        yield {
                            "type": "error",
                            "error": chunk["error"]
                        }
                        return

                    # 检测工具调用事件
                    if chunk.get("type") == "tool_calls":
                        tool_calls_detected = True
                        tool_calls = chunk.get("tool_calls", [])

                        logger.info(f"Detected {len(tool_calls)} tool_calls in stream mode, executing...")

                        # 在工具执行前保存快照，供回滚和自主纠错使用
                        rollback_manager = context.get("_rollback_manager")
                        if rollback_manager:
                            rollback_manager.save_snapshot(
                                step_index=round_count,
                                step_action="tool_calls",
                                context=context,
                                description=f"第 {round_count} 轮工具调用前快照",
                            )

                        # 发射 task 事件
                        yield emit_task_event({
                            "step_count": len(tool_calls),
                            "steps": [{"name": tc.get("function", {}).get("name", "unknown")} for tc in tool_calls],
                        })

                        # 执行每个工具
                        tool_results = []
                        for tc in tool_calls:
                            # 在工具执行循环中检查取消信号
                            if current_task and current_task.cancelled():
                                yield {"type": "cancelled", "content": "", "reasoning_content": ""}
                                return
                            tool_name = tc.get("function", {}).get("name", "unknown")
                            tool_id = tc.get("id", "")
                            tool_kind = get_stream_tool_kind(tool_name)
                            spawn_agent_type = "Explore"
                            spawn_description = ""

                            if tool_name == "task_spawn_agent":
                                func_args_str = tc.get("function", {}).get("arguments", "{}")
                                try:
                                    func_args = json.loads(func_args_str) if isinstance(func_args_str, str) else func_args_str
                                except json.JSONDecodeError:
                                    func_args = {}
                                spawn_agent_type = func_args.get("agent_type", "Explore")
                                spawn_description = func_args.get("description", "")

                            yield emit_tool_event({
                                "id": tool_id,
                                "kind": tool_kind,
                                "name": tool_name,
                                "status": "running",
                            })

                            if tool_name == "task_spawn_agent":
                                subagent_event_queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()

                                async def on_subagent_event(event: Dict[str, Any]) -> None:
                                    await subagent_event_queue.put(event)

                                exec_task = asyncio.create_task(
                                    self.executor._execute_tool_call(
                                        tc,
                                        context,
                                        on_subagent_event=on_subagent_event,
                                    )
                                )

                                while True:
                                    if exec_task.done() and subagent_event_queue.empty():
                                        break
                                    try:
                                        subagent_event = await asyncio.wait_for(
                                            subagent_event_queue.get(),
                                            timeout=0.05,
                                        )
                                    except asyncio.TimeoutError:
                                        continue
                                    yield subagent_event

                                result = await exec_task
                            elif tool_name == "builtin_ask_user":
                                # ask_user 特殊处理：直接在 process_stream 中处理
                                # 因为需要在工具阻塞期间下发问题卡片事件给前端
                                func_args_str = tc.get("function", {}).get("arguments", "{}")
                                try:
                                    ask_args = json.loads(func_args_str) if isinstance(func_args_str, str) else func_args_str
                                except json.JSONDecodeError:
                                    ask_args = {}
                                # 注入 user_id 和 session_id（executor 层也会注入，这里冗余确保可用）
                                ask_args.setdefault("user_id", str(context.get("user_id", "") or ""))
                                ask_args.setdefault("session_id", str(context.get("session_id", "") or ""))

                                # 延迟导入避免循环依赖
                                from api.routes.ask_user import enqueue_ask_user_request
                                try:
                                    request_id, ask_future = enqueue_ask_user_request(
                                        user_id=ask_args.get("user_id", ""),
                                        session_id=ask_args.get("session_id", ""),
                                        question=ask_args.get("question", ""),
                                        options=ask_args.get("options"),
                                        allow_multiple=ask_args.get("allow_multiple", False),
                                        allow_free_text=ask_args.get("allow_free_text", True),
                                        placeholder=ask_args.get("placeholder", ""),
                                        timeout=ask_args.get("timeout", 300),
                                    )
                                except ValueError as ve:
                                    # 参数校验失败
                                    result = {
                                        "ok": False,
                                        "error": f"ask_user 参数校验失败: {ve}",
                                        "tool_name": tool_name,
                                    }
                                else:
                                    # 下发问题卡片事件（前端渲染 AskUserCard）
                                    yield emit_ask_user_event({
                                        "request_id": request_id,
                                        "user_id": ask_args.get("user_id", ""),
                                        "session_id": ask_args.get("session_id", ""),
                                        "question": ask_args.get("question", ""),
                                        "options": ask_args.get("options") or [],
                                        "allow_multiple": ask_args.get("allow_multiple", False),
                                        "allow_free_text": ask_args.get("allow_free_text", True),
                                        "placeholder": ask_args.get("placeholder", ""),
                                        "timeout": ask_args.get("timeout", 300),
                                    })
                                    # 阻塞等待用户回答或超时
                                    try:
                                        answer_payload = await ask_future
                                    except asyncio.TimeoutError:
                                        result = {
                                            "ok": False,
                                            "error": "ask_user 等待用户回答超时",
                                            "tool_name": tool_name,
                                            "request_id": request_id,
                                        }
                                    except asyncio.CancelledError:
                                        logger.info(f"ask_user cancelled for session {session_id}")
                                        yield {"type": "cancelled", "content": "任务已被用户取消", "reasoning_content": ""}
                                        return
                                    else:
                                        result = {
                                            "ok": True,
                                            "result": answer_payload,
                                            "tool_name": tool_name,
                                            "request_id": request_id,
                                        }
                            else:
                                try:
                                    result = await self.executor._execute_tool_call(tc, context)
                                except asyncio.CancelledError:
                                    logger.info(f"Agent task cancelled for session {session_id}")
                                    yield {"type": "cancelled", "content": "任务已被用户取消", "reasoning_content": ""}
                                    return  # 在 yield 后使用 return 安全退出 async generator

                            # PostToolUse 钩子：工具调用后审计与后处理
                            try:
                                from core.task_runtime.hook_dispatcher import hook_dispatcher, HOOK_POST_TOOL_USE
                                await hook_dispatcher.dispatch(HOOK_POST_TOOL_USE, {
                                    "tool_name": tool_name,
                                    "tool_args": json.loads(tc.get("function", {}).get("arguments", "{}"))
                                    if isinstance(tc.get("function", {}).get("arguments"), str) else {},
                                    "result": result,
                                    "context": context,
                                })
                            except ImportError:
                                pass

                            tool_event_data = {
                                "id": tool_id,
                                "kind": tool_kind,
                                "name": tool_name,
                                "status": "completed" if result.get("ok") else "error",
                                "detail": summarize_stream_tool_result(result),
                                "output": result.get("result") if result.get("ok") else result.get("error"),
                            }
                            accumulated_tool_events.append(tool_event_data)
                            yield emit_tool_event(tool_event_data)

                            # 通知工具：发射前端通知事件
                            if tool_name == "builtin_notify" and result.get("ok"):
                                notify_result = result.get("result", {})
                                if isinstance(notify_result, dict):
                                    yield {
                                        "type": "notification",
                                        "title": notify_result.get("title", ""),
                                        "body": notify_result.get("body", ""),
                                        "channels": notify_result.get("channels", []),
                                        "message": notify_result.get("message", ""),
                                    }

                            # Todo 工具：发射前端 Todo 面板更新事件
                            if tool_name == "builtin_todo_write" and result.get("ok"):
                                todo_result = result.get("result", {})
                                if isinstance(todo_result, dict):
                                    yield {
                                        "type": "todo_update",
                                        "todos": todo_result.get("todos", []),
                                        "counts": todo_result.get("counts", {}),
                                        "summary": todo_result.get("summary", ""),
                                    }

                            if tool_name == "task_spawn_agent":
                                spawned_subagent = extract_spawned_subagent_result(result)
                                if spawned_subagent and spawned_subagent.get("run_mode") == "background":
                                    background_subagents_spawned = True
                                    yield emit_subagent_start_event(
                                        spawned_subagent["agent_id"],
                                        spawn_agent_type,
                                        spawn_description,
                                        run_mode="background",
                                    )

                            # 对任务清单操作发射生命周期事件
                            if tool_name == "task_create_task" and result.get("ok"):
                                yield emit_task_created_event(result.get("result", result))
                            if tool_name == "task_update_task" and result.get("ok"):
                                yield emit_task_updated_event(result.get("result", result))
                            if tool_name == "task_todo_write" and result.get("ok"):
                                todo_result = result.get("result", result)
                                if isinstance(todo_result, dict):
                                    yield {
                                        "type": "todo_update",
                                        "todos": todo_result.get("todos", []),
                                        "counts": todo_result.get("counts", {}),
                                        "summary": todo_result.get("summary", ""),
                                    }
                            # 对团队操作发射生命周期事件
                            if tool_name in ("task_create_team", "task_delete_team",
                                             "task_add_teammate", "task_remove_teammate") and result.get("ok"):
                                yield emit_team_event(result.get("result", result))

                            tool_results.append({"tool_call": tc, "result": result})

                        # 构建工具调用消息并注入到上下文中
                        tool_messages = []
                        assistant_tool_calls = [
                            {
                                "id": tc.get("id", ""),
                                "type": "function",
                                "function": {
                                    "name": tc.get("function", {}).get("name", ""),
                                    "arguments": tc.get("function", {}).get("arguments", ""),
                                }
                            }
                            for tc in tool_calls
                        ]
                        tool_messages.append(
                            self.executor.build_assistant_tool_call_message(
                                content=round_content,
                                reasoning_content=round_reasoning,
                                tool_calls=assistant_tool_calls,
                            )
                        )
                        for tr in tool_results:
                            tool_messages.append(self.executor._build_tool_message(tr["tool_call"], tr["result"]))

                        if background_subagents_spawned:
                            # 在返回前持久化本轮累积的工具消息到上下文，避免结果丢失
                            context["_tool_messages"] = tool_messages
                            context["_pending_background_subagents"] = True
                            yield build_status_event("waiting_subagents", "子代理已创建，等待运行结果")
                            return

                        context["_tool_messages"] = tool_messages
                        break  # 跳出 async for 循环，重新进入 while 循环进行下一轮 LLM 调用

                    content = chunk.get("content", "")
                    raw_reasoning = chunk.get("reasoning_content", "")
                    reasoning = raw_reasoning

                    if final_only_mode:
                        reasoning = ""

                    if content:
                        full_content += content
                        round_content += content
                    if raw_reasoning:
                        full_reasoning += raw_reasoning
                        round_reasoning += raw_reasoning

                    output_chunk = {
                        "type": "chunk",
                        "content": content,
                    }
                    if reasoning:
                        output_chunk["reasoning_content"] = reasoning
                    yield output_chunk

                # 根据本轮 finish_reason 推进状态机
                # tool_calls_detected=True 对应 finish_reason=tool_calls，否则对应 stop
                finish_reason = "tool_calls" if tool_calls_detected else "stop"
                state = map_finish_reason_to_state(
                    finish_reason=finish_reason,
                    current_round=round_count,
                    max_rounds=max_rounds,
                )

                # 记录本轮 LLM 调用的 token 使用量到预算追踪器
                self._record_round_budget_usage(
                    user_input=effective_user_input,
                    context=context,
                    round_content=round_content,
                    round_reasoning=round_reasoning,
                )

                # 预算即将耗尽时转换为 TERMINAL_BUDGET_EXHAUSTED 状态
                if self.budget_tracker.is_near_completion():
                    state = AgentState.TERMINAL_BUDGET_EXHAUSTED
                    logger.bind(
                        event="budget_near_completion",
                        module="agent",
                        usage_ratio=self.budget_tracker.usage_ratio(),
                        total_used=self.budget_tracker.total_used(),
                        remaining=self.budget_tracker.remaining(),
                    ).info("预算即将耗尽，提前结束本轮对话")
                    yield build_status_event(
                        "budget_exhausted", "预算即将耗尽，提前结束本轮对话"
                    )

            # TaskCompleted 钩子：流完成后触发质量门控
            try:
                from core.task_runtime.hook_dispatcher import hook_dispatcher, HOOK_TASK_COMPLETED
                await hook_dispatcher.dispatch(HOOK_TASK_COMPLETED, {
                    "response": full_content,
                    "context": context,
                    "round_count": round_count,
                })
            except ImportError:
                pass

            # Update memory after stream completes
            if full_content:
                await self.feedback.update_memory(
                    user_input=user_input,
                    response=full_content,
                    context=context,
                    reasoning_content=full_reasoning if full_reasoning else None,
                    tool_events=accumulated_tool_events if accumulated_tool_events else None,
                )
        finally:
            # 收集对话数据
            try:
                from data.collector import data_collector
                await data_collector.collect_conversation({
                    "conversation_id": context.get("session_id", ""),
                    "role_id": context.get("role_id", ""),
                    "user_message": user_input[:2000] if user_input else "",
                    "assistant_message": full_content[:2000] if full_content else "",
                    "tools_used": [evt.get("name", "") for evt in accumulated_tool_events] if accumulated_tool_events else [],
                    "model_used": context.get("model", ""),
                    "token_count": {},
                    "response_time_ms": int((time.time() - _stream_start_time) * 1000),
                })
            except Exception as e:
                # 数据收集不影响主流程，但记录日志便于排查
                logger.warning("流式数据收集失败", exc_info=e)

            # 中止根控制器，级联清理所有子任务（工具执行、子代理等）
            if self.root_abort_controller is not None:
                self.root_abort_controller.abort(reason="process_stream_finished")
                self.root_abort_controller = None

            unregister_agent_task(task_user_id, session_id, current_task)

    async def process(self, user_input: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        处理用户输入的完整流程：意图识别、规划、执行、反馈。
        自动注入对话历史以支持多轮对话上下文。
        支持多模态附件和思考模式参数。
        优先检测魔法命令，匹配时跳过 LLM 处理。
        """
        logger.info(f"Processing user input, length={len(user_input)}")

        # 检测魔法命令
        cmd_result = await self._check_and_handle_magic_command(user_input, context)
        if cmd_result is not None:
            response_text = cmd_result.get("message", "")
            if cmd_result.get("success"):
                return {
                    "status": "success",
                    "response": response_text,
                    "is_magic_command": True,
                    "command_name": cmd_result.get("command_name", ""),
                    "command_result": cmd_result,
                }
            else:
                return {
                    "status": "error",
                    "response": response_text,
                    "error": cmd_result.get("message", "命令执行失败"),
                    "is_magic_command": True,
                    "command_name": cmd_result.get("command_name", ""),
                }

        self._prepare_context(user_input, context)
        await self._inject_runtime_capabilities(context)

        # 构建多模态消息内容（若用户上传了附件）
        self._build_multimodal_context(user_input, context)

        # 构建思考模式参数（若用户开启了思考）
        self._build_thinking_context(context)

        # 构建对话历史并注入到上下文中
        session_id = context.get("session_id", "default")
        task_user_id = str(context.get("user_id", ""))

        # 将当前协程注册为活跃任务，供取消端点查找
        current_task = asyncio.current_task()
        if current_task is not None and session_id:
            register_agent_task(task_user_id, session_id, current_task)

        try:
            conversation_history = await self._build_conversation_history(session_id)
            # 自动检测并压缩上下文
            context["conversation_history"] = await self._auto_compress_context(
                context, conversation_history
            )

            effective_user_input = build_effective_user_input(user_input, context)

            intent_start = time.perf_counter()
            intent = await self.comprehension.recognize_intent(effective_user_input)
            logger.debug(f"Recognized intent: {intent}")

            entities = await self.comprehension.extract_entities(effective_user_input)
            logger.debug(f"Extracted entities: {entities}")
            intent_duration_ms = int((time.perf_counter() - intent_start) * 1000)
            self._schedule_record(
                node_type="intent_recognition",
                user_message=user_input,
                context=context,
                execution_duration_ms=intent_duration_ms,
                metadata={
                    "intent": intent,
                    "entities": entities
                }
            )
        
            experiences = []
            if context.get('retrieve_experiences', True):
                experiences = await self._retrieve_relevant_experiences(
                    user_input=effective_user_input,
                    context=context
                )
                if experiences:
                    context['relevant_experiences'] = experiences
                    logger.info(f"Retrieved {len(experiences)} relevant experiences")

            relevant_memories = []
            if context.get('retrieve_long_term_memory', True):
                relevant_memories = await self._retrieve_relevant_memories(
                    user_input=effective_user_input,
                    context=context,
                )
                if relevant_memories:
                    context['vector_retrieved_memories'] = relevant_memories
                    logger.info(f"Retrieved {len(relevant_memories)} long-term memories")

            workflow_result = None
            if self.workflow_engine and (context.get('workflow_definition') is not None or context.get('workflow_id') is not None):
                workflow_result = await self._execute_workflow_from_context(context)
                if workflow_result:
                    context['workflow_result'] = workflow_result
                    if context.get('workflow_only'):
                        return self._apply_output_mode(
                            {
                                "status": workflow_result.get("status", "completed"),
                                "response": workflow_result.get("last_result", workflow_result),
                                "results": [
                                    {
                                        "type": "workflow",
                                        "step": {"action": "workflow_execution"},
                                        "result": workflow_result,
                                    }
                                ],
                                "workflows_executed": 1,
                                "experiences_used": len(experiences),
                            },
                            context,
                        )
        
            plan = await self.planner.create_plan(
                intent=intent,
                entities=entities,
                context=context
            )
            logger.debug(f"Created plan: {plan}")
        
            auto_results = {"skills": [], "plugins": []}
            if context.get('enable_skill_plugin', True):
                matching_start = time.perf_counter()
                auto_results = await self._auto_execute_skills_and_plugins(
                    intent=intent,
                    entities=entities,
                    context=context
                )
                matching_duration_ms = int((time.perf_counter() - matching_start) * 1000)
                if auto_results.get('skills') or auto_results.get('plugins'):
                    context['auto_execution_results'] = auto_results
                    logger.info(f"Auto-executed {len(auto_results.get('skills', []))} skills and {len(auto_results.get('plugins', []))} plugins")

                self._schedule_record(
                    node_type="skill_plugin_matching",
                    user_message=user_input,
                    context=context,
                    execution_duration_ms=matching_duration_ms,
                    metadata={
                        "skills": [item.get('skill_name') for item in auto_results.get('skills', [])],
                        "plugins": [item.get('plugin_name') for item in auto_results.get('plugins', [])],
                        "skills_count": len(auto_results.get('skills', [])),
                        "plugins_count": len(auto_results.get('plugins', []))
                    }
                )
        
            results = []
            for step in plan.get("steps", []):
                if context.get('enable_skill_plugin', True) and step.get('use_skill'):
                    skill_name = step.get('skill_name')
                    if skill_name:
                        skill_result = await self.execute_skill(
                            skill_name=skill_name,
                            inputs=step.get('inputs', {}),
                            context=context
                        )
                        results.append({
                            'type': 'skill',
                            'step': step,
                            'result': skill_result
                        })
                        self._schedule_record(
                            node_type="tool_execution",
                            user_message=user_input,
                            context=context,
                            status="success" if skill_result.get('status') in ('completed', 'success') else "error",
                            error_message=skill_result.get('error'),
                            llm_input=step,
                            llm_output=skill_result,
                            metadata={
                                "execution_type": "skill",
                                "skill_name": skill_name
                            }
                        )
                        record_tool_execution_metric("skill", skill_result.get("status", "unknown"))
                        continue
            
                if context.get('enable_skill_plugin', True) and step.get('use_plugin'):
                    plugin_name = step.get('plugin_name')
                    plugin_method = step.get('plugin_method')
                    if plugin_name and plugin_method:
                        plugin_result = await self.execute_plugin(
                            plugin_name=plugin_name,
                            method=plugin_method,
                            **step.get('kwargs', {})
                        )
                        results.append({
                            'type': 'plugin',
                            'step': step,
                            'result': plugin_result
                        })
                        self._schedule_record(
                            node_type="tool_execution",
                            user_message=user_input,
                            context=context,
                            status="success" if plugin_result.get('status') in ('completed', 'success') else "error",
                            error_message=plugin_result.get('message'),
                            llm_input=step,
                            llm_output=plugin_result,
                            metadata={
                                "execution_type": "plugin",
                                "plugin_name": plugin_name,
                                "plugin_method": plugin_method
                            }
                        )
                        record_tool_execution_metric("plugin", plugin_result.get("status", "unknown"))
                        continue
                result = await self.executor.execute_step(step, context)
                results.append({
                    'type': 'execution',
                    'step': step,
                    'result': result
                })
                self._schedule_record(
                    node_type="tool_execution",
                    user_message=user_input,
                    context=context,
                    status="success" if isinstance(result, dict) and result.get('status') in ['completed', 'success'] else "error",
                    error_message=result.get('message') if isinstance(result, dict) else None,
                    llm_input=step,
                    llm_output=result,
                    metadata={
                        "execution_type": "execution",
                        "action": step.get('action')
                    }
                )
                
                if isinstance(result, dict):
                    feedback = await self.feedback.evaluate_result(result)
                    if feedback.get("needs_confirmation"):
                        return self._apply_output_mode({
                            "status": "awaiting_confirmation",
                            "message": feedback.get("message"),
                            "step": step,
                            "results": results
                        }, context)
                    
                    if feedback.get("needs_retry"):
                        retry_result = await self.executor.retry_step(step, context)
                        results[-1] = {
                            'type': 'execution',
                            'step': step,
                            'result': retry_result
                        }
        
            final_response = await self.feedback.generate_response(results, context)

            first_error = None
            for item in results:
                result = item.get('result', item)
                if isinstance(result, dict) and result.get('error'):
                    first_error = result.get('error')
                    break

            if first_error:
                return self._apply_output_mode({
                    "status": "error",
                    "response": final_response,
                    "results": results,
                    "error": first_error
                }, context)
            await self.feedback.update_memory(
                user_input=user_input,
                response=final_response,
                context=context
            )
        
            if context.get('extract_experience', False):
                await self._extract_and_store_experience(
                    user_input=user_input,
                    context=context,
                    results=results,
                    status='success' if final_response else 'failed'
                )
        
            skill_count = sum(1 for r in results if r.get('type') == 'skill')
            plugin_count = sum(1 for r in results if r.get('type') == 'plugin')
        
            reasoning_parts = []
            for item in results:
                result = item.get('result', item)
                if isinstance(result, dict) and result.get('reasoning_content'):
                    reasoning_parts.append(result['reasoning_content'])
        
            output = {
                "status": "completed",
                "response": final_response,
                "results": results,
                "experiences_used": len(experiences),
                "memories_used": len(relevant_memories),
                "skills_executed": skill_count,
                "plugins_executed": plugin_count,
                "skill_results": self.skill_results.copy(),
                "plugin_results": self.plugin_results.copy()
            }
            if workflow_result:
                output["workflow_result"] = workflow_result
            if reasoning_parts:
                output["reasoning_content"] = "\n".join(reasoning_parts)
            return self._apply_output_mode(output, context)
        except asyncio.CancelledError:
            logger.info(f"Agent task cancelled for session {session_id}")
            return {
                "status": "cancelled",
                "response": "",
                "results": [],
                "experiences_used": 0,
                "memories_used": 0,
                "skills_executed": 0,
                "plugins_executed": 0,
                "skill_results": [],
                "plugin_results": [],
            }
        finally:
            unregister_agent_task(task_user_id, session_id, current_task)
    
    async def _auto_execute_skills_and_plugins(
        self,
        intent: Dict[str, Any],
        entities: Dict[str, Any],
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        基于意图识别结果和实体信息，自动匹配并执行相关技能和插件。
        匹配策略：将意图关键词和实体类型与技能描述/工具描述进行文本匹配。
        仅处理已启用且 auto_executable 不为 False 的技能。
        """
        logger.info("Auto-executing skills and plugins based on intent and entities")
        auto_results: dict[str, list[Any]] = {
            'skills': [],
            'plugins': []
        }

        try:
            if isinstance(intent, dict):
                intent_type = str(intent.get('type', ''))
                intent_action = str(intent.get('action', ''))
            else:
                intent_type = str(intent or '')
                intent_action = ''

            intent_keywords = f"{intent_type} {intent_action}".lower().strip()

            entities_list: List[Dict[str, Any]] = []
            if isinstance(entities, dict):
                raw_entities = entities.get('entities')
                if isinstance(raw_entities, list):
                    entities_list = [e for e in raw_entities if isinstance(e, dict)]
                else:
                    for entity_type, entity_values in entities.items():
                        if isinstance(entity_values, list):
                            entities_list.extend(
                                {
                                    'type': entity_type,
                                    'value': value
                                }
                                for value in entity_values
                            )

            available_skills = await self.get_available_skills()
            available_plugins = await self.get_available_plugins()

            # 收集所有匹配的技能任务，使用 asyncio.gather 并行执行
            skill_tasks: list = []
            skill_metas: list[dict] = []
            for skill in available_skills:
                if not skill.get('enabled'):
                    continue
                if skill.get('config', {}).get('auto_executable') is False:
                    continue

                skill_name = skill.get('name', '')
                skill_description = skill.get('description', '').lower()

                if self._is_skill_relevant(skill_name, skill_description, intent_keywords, entities_list):
                    logger.info(f"Auto-selecting skill: {skill_name}")

                    skill_inputs = {
                        'intent': intent,
                        'entities': entities,
                        'context': context
                    }

                    skill_tasks.append(self.execute_skill(
                        skill_name=skill_name,
                        inputs=skill_inputs,
                        context=context
                    ))
                    skill_metas.append({'skill_name': skill_name})

            if skill_tasks:
                skill_results = await asyncio.gather(*skill_tasks, return_exceptions=True)
                for meta, result in zip(skill_metas, skill_results):
                    if isinstance(result, Exception):
                        logger.bind(
                            event="auto_skill_error",
                            skill_name=meta['skill_name'],
                            error_type=type(result).__name__,
                        ).warning(f"并行执行技能失败: {result}")
                        continue
                    if isinstance(result, dict) and result.get('status') in ('completed', 'success'):
                        auto_results['skills'].append({
                            'skill_name': meta['skill_name'],
                            'result': result,
                            'reason': 'auto_selected'
                        })

            # 收集所有匹配的插件任务，使用 asyncio.gather 并行执行
            plugin_tasks: list = []
            plugin_metas: list[dict] = []
            for plugin in available_plugins:
                plugin_name = plugin.get('name', '')
                plugin_tools = plugin.get('tools', [])

                for tool in plugin_tools:
                    tool_name = tool.get('name', '').lower()
                    tool_description = tool.get('description', '').lower()

                    if self._is_plugin_relevant(tool_name, tool_description, intent_keywords, entities_list):
                        logger.info(f"Auto-selecting plugin '{plugin_name}' tool '{tool.get('name')}'")

                        plugin_kwargs: Dict[str, Any] = {}
                        default_params = tool.get('default_params')
                        if isinstance(default_params, dict):
                            plugin_kwargs.update(default_params)
                        plugin_kwargs.update({
                            'intent': intent,
                            'entities': entities,
                            'context': context,
                        })

                        plugin_tasks.append(self.execute_plugin(
                            plugin_name=plugin_name,
                            method=tool.get('method'),
                            **plugin_kwargs
                        ))
                        plugin_metas.append({
                            'plugin_name': plugin_name,
                            'tool': tool.get('name'),
                        })

            if plugin_tasks:
                plugin_results = await asyncio.gather(*plugin_tasks, return_exceptions=True)
                for meta, result in zip(plugin_metas, plugin_results):
                    if isinstance(result, Exception):
                        logger.bind(
                            event="auto_plugin_error",
                            plugin_name=meta['plugin_name'],
                            tool=meta['tool'],
                            error_type=type(result).__name__,
                        ).warning(f"并行执行插件失败: {result}")
                        continue
                    if isinstance(result, dict) and result.get('status') in ('completed', 'success'):
                        auto_results['plugins'].append({
                            'plugin_name': meta['plugin_name'],
                            'tool': meta['tool'],
                            'result': result,
                            'reason': 'auto_selected'
                        })

            logger.info(f"Auto-execution completed: {len(auto_results['skills'])} skills, {len(auto_results['plugins'])} plugins")
            return auto_results

        except Exception as e:
            logger.bind(
                event="auto_execution_error",
                module="agent",
                error_type=type(e).__name__,
            ).opt(exception=True).error(f"自动执行技能/插件异常: {e}")
            return auto_results
    
    def _is_skill_relevant(
        self,
        skill_name: str,
        skill_description: str,
        intent_keywords: str,
        entities: List[Dict]
    ) -> bool:
        """
        判断技能是否与当前意图相关：检查技能名称和描述是否包含意图关键词或实体类型。
        仅匹配长度超过 3 字符的关键词，避免短词误匹配。
        """
        skill_name_lower = skill_name.lower()
        
        if any(keyword in skill_name_lower or keyword in skill_description 
               for keyword in intent_keywords.split() if len(keyword) > 3):
            return True
        
        entity_types = [entity.get('type', '').lower() for entity in entities]
        if any(entity_type in skill_name_lower or entity_type in skill_description 
               for entity_type in entity_types if entity_type):
            return True
        
        return False
    
    def _is_plugin_relevant(
        self,
        tool_name: str,
        tool_description: str,
        intent_keywords: str,
        entities: List[Dict]
    ) -> bool:
        """
        判断插件工具是否与当前意图相关：检查工具名称和描述是否包含意图关键词或实体类型。
        匹配逻辑与 _is_skill_relevant 一致，仅匹配长度超过 3 字符的关键词。
        """
        tool_name_lower = tool_name.lower()
        
        if any(keyword in tool_name_lower or keyword in tool_description 
               for keyword in intent_keywords.split() if len(keyword) > 3):
            return True
        
        entity_types = [entity.get('type', '').lower() for entity in entities]
        if any(entity_type in tool_name_lower or entity_type in tool_description 
               for entity_type in entity_types if entity_type):
            return True
        
        return False
    
    async def handle_confirmation(self, confirmed: bool, step: Dict, context: Dict) -> Dict[str, Any]:
        """
        处理用户对操作步骤的确认或取消：确认时执行步骤，取消时返回 cancelled 状态。
        用于需要用户二次确认的危险操作流程（如文件删除、命令执行等）。
        """
        self._prepare_context(context.get("message", ""), context)

        if confirmed:
            result = await self.executor.execute_step(step, context)
            return {"status": "executed", "result": result}
        else:
            return {"status": "cancelled", "message": "User cancelled the operation"}
    
    async def _retrieve_relevant_experiences(
        self,
        user_input: str,
        context: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        从经验记忆中检索与当前用户输入相关的历史经验。
        通过 ExperienceManager 进行语义匹配，最多返回 3 条相关经验，
        每条包含类型、标题、内容、置信度和触发条件。
        """
        try:
            db = context.get('db')
            if not db:
                logger.debug("无可用数据库会话，跳过经验检索")
                return []
            
            manager = ExperienceManager(db)
            
            task_context = {
                'description': user_input,
                'task_type': context.get('task_type', 'general'),
                'intent': context.get('intent', {})
            }
            
            experiences = await manager.retrieve_relevant_experiences(
                task_context=task_context,
                max_experiences=3
            )
            
            formatted_experiences = []
            for exp in experiences:
                formatted_experiences.append({
                    'type': exp.experience_type,
                    'title': exp.title,
                    'content': exp.content,
                    'confidence': exp.confidence,
                    'trigger': exp.trigger_conditions
                })
            
            return formatted_experiences

        except (SQLAlchemyError, asyncio.TimeoutError, ValueError) as e:
            logger.bind(
                event="experience_retrieval_error",
                module="agent",
                error_type=type(e).__name__,
            ).opt(exception=True).error(f"检索相关经验失败: {e}")
            return []

    async def _retrieve_relevant_memories(
        self,
        user_input: str,
        context: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """
        使用长期记忆的混合检索能力获取相关记忆，并整理为可注入上下文的结构。
        """
        if not self.memory_manager:
            return []

        try:
            memories = await self.memory_manager.search_memories(
                query=user_input,
                limit=5,
                user_id=context.get('user_id'),
                include_archived=False,
                use_vector=True,
            )
            return [
                {
                    'id': memory.id,
                    'content': memory.content,
                    'importance': memory.importance,
                    'confidence': memory.confidence,
                    'quality_score': memory.quality_score,
                }
                for memory in memories
            ]
        except (SQLAlchemyError, asyncio.TimeoutError, ValueError) as e:
            logger.bind(
                event="long_term_memory_retrieval_error",
                module="agent",
                error_type=type(e).__name__,
            ).opt(exception=True).error(f"检索长期记忆失败: {e}")
            return []

    async def _execute_workflow_from_context(self, context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        从上下文中提取工作流定义或工作流 ID，并执行对应工作流。
        """
        if not self.workflow_engine:
            return None

        workflow_definition = context.get('workflow_definition')
        workflow_id = context.get('workflow_id')
        workflow_name = context.get('workflow_name')

        if workflow_definition is None and workflow_id is not None and self._db_session is not None:
            from db.models import Workflow

            def _sync_lookup_workflow():
                return self._db_session.query(Workflow).filter(Workflow.id == workflow_id).first()

            workflow_record = await asyncio.to_thread(_sync_lookup_workflow)
            if workflow_record is None:
                return {
                    'status': 'failed',
                    'error': f'Workflow {workflow_id} not found',
                }
            workflow_definition = workflow_record.definition
            workflow_name = workflow_record.name

        if workflow_definition is None:
            return None

        return await self.workflow_engine.execute_definition(
            workflow_definition,
            workflow_id=workflow_id,
            workflow_name=workflow_name,
            user_id=context.get('user_id'),
            input_context=context.get('workflow_input_context', {}),
            format_hint=context.get('workflow_format'),
        )
    
    async def _extract_and_store_experience(
        self,
        user_input: str,
        context: Dict[str, Any],
        results: List[Dict],
        status: str
    ) -> None:
        """
        从会话执行结果中提取可复用的经验并持久化存储。
        通过 ExperienceExtractor 分析用户目标、执行步骤和最终结果，
        提取有价值的经验模式保存到经验文件。
        """
        try:
            db = context.get('db')
            if not db:
                logger.debug("无可用数据库会话，跳过经验提取")
                return
            
            execution_steps = []
            for i, result in enumerate(results, 1):
                step = {
                    'action': result.get('action', f'Step {i}'),
                    'result': result.get('message', result.get('status', 'Unknown')),
                    'success': result.get('status') == 'success'
                }
                execution_steps.append(step)
            
            experience_data = await self.experience_extractor.extract_from_session(
                user_goal=user_input,
                execution_steps=execution_steps,
                final_result=context.get('final_result', ''),
                status=status,
                session_id=context.get('session_id', '')
            )

            if not experience_data:
                logger.info("No experience extracted from session")
                return

            logger.info(
                f"Extracted experience and saved to file: {experience_data.get('save_result', {}).get('file_name', '')}"
            )
            
        except (SQLAlchemyError, asyncio.TimeoutError, ValueError, json.JSONDecodeError) as e:
            logger.bind(
                event="experience_extraction_error",
                module="agent",
                error_type=type(e).__name__,
            ).opt(exception=True).error(f"经验提取与存储失败: {e}")
    
    def _collect_skill_plugin_results(self) -> Dict[str, Any]:
        """
        汇总当前会话中所有技能和插件的执行统计。
        返回包含技能/插件各自的总数、成功数、失败数和详细结果的字典。
        """
        logger.info("Collecting skill and plugin execution results")
        
        skill_results_summary: dict[str, Any] = {
            'total': len(self.skill_results),
            'successful': sum(1 for r in self.skill_results if r.get('success', False)),
            'failed': sum(1 for r in self.skill_results if not r.get('success', False)),
            'details': self.skill_results.copy()
        }

        plugin_results_summary: dict[str, Any] = {
            'total': len(self.plugin_results),
            'successful': sum(1 for r in self.plugin_results if r.get('success', False)),
            'failed': sum(1 for r in self.plugin_results if not r.get('success', False)),
            'details': self.plugin_results.copy()
        }
        
        logger.info(f"Collected {skill_results_summary['total']} skill results, {plugin_results_summary['total']} plugin results")
        
        return {
            'skills': skill_results_summary,
            'plugins': plugin_results_summary,
            'overall_success': skill_results_summary['successful'] > 0 or plugin_results_summary['successful'] > 0
        }
    
    def _generate_skill_plugin_feedback(self, results: Dict[str, Any]) -> Dict[str, Any]:
        """
        根据技能和插件执行统计生成反馈摘要。
        计算各自的成功率，成功率低于 50% 时标记 needs_attention 告警。
        """
        logger.info("Generating feedback for skill and plugin executions")
        
        skills = results.get('skills', {})
        plugins = results.get('plugins', {})
        
        skill_success_rate = 0
        if skills.get('total', 0) > 0:
            skill_success_rate = skills['successful'] / skills['total']
        
        plugin_success_rate = 0
        if plugins.get('total', 0) > 0:
            plugin_success_rate = plugins['successful'] / plugins['total']
        
        feedback_messages = []
        
        if skills['total'] > 0:
            feedback_messages.append(f"Executed {skills['total']} skills with {skills['successful']} successful")
            if skill_success_rate < 0.5:
                feedback_messages.append(f"Warning: Low skill success rate ({skill_success_rate:.1%})")
        
        if plugins['total'] > 0:
            feedback_messages.append(f"Executed {plugins['total']} plugins with {plugins['successful']} successful")
            if plugin_success_rate < 0.5:
                feedback_messages.append(f"Warning: Low plugin success rate ({plugin_success_rate:.1%})")
        
        if not feedback_messages:
            feedback_messages.append("No skills or plugins were executed")
        
        logger.info(f"Generated feedback: {'; '.join(feedback_messages)}")
        
        return {
            'skill_success_rate': skill_success_rate,
            'plugin_success_rate': plugin_success_rate,
            'messages': feedback_messages,
            'needs_attention': skill_success_rate < 0.5 or plugin_success_rate < 0.5
        }
    
    def clear_results(self) -> None:
        """
        清空当前会话中累积的技能和插件执行结果列表。
        通常在新轮对话开始时调用，避免历史执行结果干扰后续判断。
        """
        logger.info("Clearing skill and plugin results")
        self.skill_results.clear()
        self.plugin_results.clear()
        logger.info("Results cleared successfully")

    async def _self_correction_loop(
        self,
        step: Dict[str, Any],
        context: Dict[str, Any],
        error: Exception,
    ) -> Dict[str, Any]:
        """
        自主纠错循环：诊断错误 -> 生成修复计划 -> 回滚 -> 重新执行。
        最多执行 AGENT_SELF_CORRECTION_MAX_ROUNDS 轮纠错，超出则请求人工介入。
        """
        from config.settings import settings

        max_rounds = settings.AGENT_SELF_CORRECTION_MAX_ROUNDS
        rollback_manager = context.get("_rollback_manager")

        for correction_round in range(1, max_rounds + 1):
            logger.bind(
                event="self_correction_round",
                module="agent",
                round=correction_round,
                max_rounds=max_rounds,
            ).info(f"自主纠错第 {correction_round}/{max_rounds} 轮")

            # 1. 诊断错误
            diagnosis = await self.feedback.diagnose_error(error, context)

            # 2. 生成修复计划
            fix_plan = await self.planner.generate_fix_plan(diagnosis, context)

            # 3. 回滚到上一个稳定状态
            if rollback_manager:
                restored_context = rollback_manager.get_context_after_rollback()
                if restored_context:
                    # 只更新非内部键的上下文
                    for key, value in restored_context.items():
                        if not key.startswith("_"):
                            context[key] = value

            # 4. 执行修复计划
            try:
                result = await self.executor.execute_step(fix_plan, context)
                if result.get("status") != "failed":
                    logger.bind(
                        event="self_correction_success",
                        module="agent",
                        round=correction_round,
                    ).info(f"自主纠错第 {correction_round} 轮成功")
                    return result
                error = Exception(result.get("response", "修复计划执行失败"))
            except Exception as e:
                error = e

        # 超出最大纠错轮数，请求人工介入
        logger.bind(
            event="self_correction_exhausted",
            module="agent",
            max_rounds=max_rounds,
        ).warning(f"自主纠错 {max_rounds} 轮后仍失败，需要人工介入")

        return {
            "status": "needs_human_intervention",
            "response": f"自主纠错 {max_rounds} 轮后仍失败，需要人工介入",
            "error": str(error),
        }
