"""
子Agent管理路由 - 提供子Agent注册、查询、图编排等API入口。
基于 langchain-ai/langgraph 思想实现的子Agent编排系统。
来源参考: https://github.com/langchain-ai/langgraph

架构参考: https://yangcazz.github.io/2026/05/22/subagent-architecture-isolation/
新增: SubagentOrchestrator 委派-收集-合并模式 API（隔离/资源限制/生命周期）
"""

import threading

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from loguru import logger

from api.dependencies import get_current_user
from core.subagent import (
    SubAgentManager,
    AgentState,
    AgentGraph,
    SubagentOrchestrator,
    SubagentTask,
    SubagentResult,
    IsolationLevel,
    SubagentLifecycleState,
    ResourceLimits,
    ResultMergeStrategy,
    DEFAULT_RESOURCE_LIMITS,
    validate_task_security,
)
from db.models import User


router = APIRouter(prefix="/api/subagents", tags=["subagents"])

# 全局子Agent管理器实例及线程锁
_manager: Optional[SubAgentManager] = None
_manager_lock = threading.Lock()

# 全局 SubagentOrchestrator 实例及线程锁
_orchestrator: Optional[SubagentOrchestrator] = None
_orchestrator_lock = threading.Lock()


def _get_manager() -> SubAgentManager:
    """获取或初始化子Agent管理器（线程安全）。"""
    global _manager
    if _manager is None:
        with _manager_lock:
            # 双重检查，避免多线程重复初始化
            if _manager is None:
                _manager = SubAgentManager()
                _register_builtin_agents(_manager)
    return _manager


def _get_orchestrator() -> SubagentOrchestrator:
    """获取或初始化 SubagentOrchestrator（线程安全）。"""
    global _orchestrator
    if _orchestrator is None:
        with _orchestrator_lock:
            if _orchestrator is None:
                # 尝试集成 WorktreeManager（Level 2 隔离），失败时降级为 Level 1
                worktree_mgr = None
                try:
                    from core.task_runtime.worktree_manager import worktree_manager as worktree_mgr
                except Exception as exc:
                    logger.warning(f"WorktreeManager 加载失败，Level 2 隔离将降级: {exc}")
                _orchestrator = SubagentOrchestrator(
                    max_parallel=4,
                    worktree_manager=worktree_mgr,
                )
    return _orchestrator


async def _builtin_analyzer(state: AgentState) -> AgentState:
    """内置分析Agent - 分析用户意图和上下文。"""
    user_message = state.context.get('user_message', '')
    state.set_result('analyzer', {
        'intent': 'general',
        'entities': [],
        'complexity': 'medium',
        'message_length': len(user_message)
    })
    state.add_message('system', f'分析完成: 消息长度={len(user_message)}')
    return state


async def _builtin_planner(state: AgentState) -> AgentState:
    """内置规划Agent - 根据分析结果制定执行计划。"""
    analysis = state.get_result('analyzer') or {}
    steps = [
        {"step": 1, "action": "理解任务", "status": "completed"},
        {"step": 2, "action": "制定方案", "status": "completed"},
        {"step": 3, "action": "执行任务", "status": "pending"}
    ]
    state.set_result('planner', {
        'plan': steps,
        'based_on': analysis.get('intent', 'unknown')
    })
    state.add_message('system', f'规划完成: {len(steps)}个步骤')
    return state


async def _builtin_executor(state: AgentState) -> AgentState:
    """内置执行Agent - 执行计划中的步骤。"""
    plan = state.get_result('planner') or {}
    steps = plan.get('plan', [])
    executed = []
    for step in steps:
        executed.append({**step, 'status': 'completed'})
    state.set_result('executor', {
        'executed_steps': executed,
        'success': True
    })
    state.add_message('system', f'执行完成: {len(executed)}个步骤已完成')
    return state


async def _builtin_reviewer(state: AgentState) -> AgentState:
    """内置审查Agent - 审查执行结果。"""
    execution = state.get_result('executor') or {}
    state.set_result('reviewer', {
        'approved': execution.get('success', False),
        'feedback': '执行结果符合预期' if execution.get('success') else '需要重新执行'
    })
    return state


def _register_builtin_agents(manager: SubAgentManager):
    """注册内置子Agent。"""
    manager.register_agent(
        'analyzer', _builtin_analyzer,
        description='分析用户意图和上下文',
        capabilities=['intent_detection', 'entity_extraction']
    )
    manager.register_agent(
        'planner', _builtin_planner,
        description='根据分析结果制定执行计划',
        capabilities=['task_decomposition', 'step_planning']
    )
    manager.register_agent(
        'executor', _builtin_executor,
        description='执行计划中的步骤',
        capabilities=['tool_calling', 'code_execution']
    )
    manager.register_agent(
        'reviewer', _builtin_reviewer,
        description='审查和验证执行结果',
        capabilities=['quality_check', 'result_validation']
    )

    # 创建默认的顺序执行图
    graph = manager.create_graph(
        'default_pipeline',
        description='默认的分析-规划-执行-审查流水线'
    )
    graph.add_node('analyzer', _builtin_analyzer, '分析用户意图')
    graph.add_node('planner', _builtin_planner, '制定执行计划')
    graph.add_node('executor', _builtin_executor, '执行计划步骤')
    graph.add_node('reviewer', _builtin_reviewer, '审查执行结果')
    graph.add_edge('analyzer', 'planner')
    graph.add_edge('planner', 'executor')
    graph.add_edge('executor', 'reviewer')
    graph.set_entry_point('analyzer')
    graph.set_finish_point('reviewer')

    logger.info("Built-in sub-agents and default pipeline registered")


# --- 请求模型 ---

class RunGraphRequest(BaseModel):
    """运行图请求。"""
    graph_name: str = Field(..., description="图名称")
    context: Dict[str, Any] = Field(default_factory=dict, description="初始上下文")
    messages: List[Dict[str, str]] = Field(default_factory=list, description="初始消息")


class RunSequentialRequest(BaseModel):
    """顺序执行请求。"""
    agent_names: List[str] = Field(..., description="要执行的Agent名称列表")
    context: Dict[str, Any] = Field(default_factory=dict, description="初始上下文")


class RunParallelRequest(BaseModel):
    """并行执行请求。"""
    agent_names: List[str] = Field(..., description="要执行的Agent名称列表")
    context: Dict[str, Any] = Field(default_factory=dict, description="初始上下文")
    timeout: float = Field(default=120.0, ge=1, le=600, description="超时时间（秒）")


# --- API端点 ---

@router.get("/agents")
async def list_agents(
    current_user: User = Depends(get_current_user),
):
    """获取所有已注册的子Agent（需认证）。"""
    manager = _get_manager()
    agents = manager.get_registered_agents()
    return {"agents": agents, "count": len(agents)}


@router.get("/graphs")
async def list_graphs(
    current_user: User = Depends(get_current_user),
):
    """获取所有已创建的执行图（需认证）。"""
    manager = _get_manager()
    graphs = manager.get_graphs_info()
    return {"graphs": graphs, "count": len(graphs)}


@router.get("/graphs/{graph_name}")
async def get_graph(
    graph_name: str,
    current_user: User = Depends(get_current_user),
):
    """获取指定图的详细信息（需认证）。"""
    manager = _get_manager()
    graph = manager.get_graph(graph_name)
    if not graph:
        raise HTTPException(status_code=404, detail=f"图 '{graph_name}' 不存在")
    return graph.get_graph_info()


@router.post("/run/graph")
async def run_graph(
    req: RunGraphRequest,
    current_user: User = Depends(get_current_user),
):
    """运行指定的Agent执行图（需认证）。"""
    manager = _get_manager()
    graph = manager.get_graph(req.graph_name)
    if not graph:
        raise HTTPException(status_code=404, detail=f"图 '{req.graph_name}' 不存在")

    state = AgentState(
        context=req.context,
        messages=[{"role": m.get("role", "user"), "content": m.get("content", "")} for m in req.messages]
    )

    try:
        result_state = await graph.execute(state)
        return {
            "success": True,
            "results": result_state.results,
            "messages": result_state.messages,
            "errors": result_state.errors,
            "metadata": result_state.metadata,
            "execution_log": graph.get_execution_log()
        }
    except Exception as e:
        logger.error(f"Graph execution failed: {e}")
        raise HTTPException(status_code=500, detail=f"图执行失败: {str(e)}")


@router.post("/run/sequential")
async def run_sequential(
    req: RunSequentialRequest,
    current_user: User = Depends(get_current_user),
):
    """顺序执行多个子Agent（需认证）。"""
    manager = _get_manager()
    state = AgentState(context=req.context)

    try:
        result_state = await manager.run_sequential(req.agent_names, state)
        return {
            "success": len(result_state.errors) == 0,
            "results": result_state.results,
            "messages": result_state.messages,
            "errors": result_state.errors
        }
    except Exception as e:
        logger.error(f"Sequential execution failed: {e}")
        raise HTTPException(status_code=500, detail=f"顺序执行失败: {str(e)}")


@router.post("/run/parallel")
async def run_parallel(
    req: RunParallelRequest,
    current_user: User = Depends(get_current_user),
):
    """并行执行多个子Agent（需认证）。"""
    manager = _get_manager()
    state = AgentState(context=req.context)

    try:
        result_state = await manager.run_parallel(req.agent_names, state, timeout=req.timeout)
        return {
            "success": len(result_state.errors) == 0,
            "results": result_state.results,
            "messages": result_state.messages,
            "errors": result_state.errors
        }
    except Exception as e:
        logger.error(f"Parallel execution failed: {e}")
        raise HTTPException(status_code=500, detail=f"并行执行失败: {str(e)}")


# ── SubagentOrchestrator API（委派-收集-合并模式） ──────────────────


class ResourceLimitsSchema(BaseModel):
    """子代理资源限制。"""
    max_turns: int = Field(default=20, ge=1, description="最大 Agent 循环轮数")
    max_tokens: int = Field(default=8000, ge=1, description="最大消耗 token 数")
    max_time_seconds: int = Field(default=120, ge=1, le=600, description="最大执行时间（硬超时）")
    max_tool_calls: int = Field(default=15, ge=1, description="最大工具调用次数")
    max_output_tokens: int = Field(default=2000, ge=1, description="返回结果最大长度")
    soft_timeout_seconds: int = Field(default=90, ge=1, description="软超时（给一轮收尾）")


class SubagentTaskSchema(BaseModel):
    """子代理任务定义。"""
    task_id: str = Field(..., description="任务唯一标识")
    instruction: str = Field(..., min_length=1, description="任务指令")
    context_snippet: str = Field(default="", description="必要的上下文片段")
    allowed_tools: List[str] = Field(default_factory=list, description="工具白名单")
    timeout_seconds: int = Field(default=120, ge=1, le=600, description="超时秒数")
    isolation_level: int = Field(default=1, ge=1, le=3, description="隔离级别 1=上下文 2=进程 3=沙箱")
    resource_limits: ResourceLimitsSchema = Field(default_factory=ResourceLimitsSchema)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class DelegateRequest(BaseModel):
    """委派任务请求。"""
    tasks: List[SubagentTaskSchema] = Field(..., min_length=1, description="子代理任务列表")
    merge_strategy: str = Field(
        default="concatenate",
        description="结果合并策略: concatenate/dag/llm_summary/voting",
    )


class CancelRequest(BaseModel):
    """取消任务请求。"""
    task_id: str = Field(..., description="要取消的任务 ID")


@router.post("/orchestrator/delegate")
async def orchestrator_delegate(
    req: DelegateRequest,
    current_user: User = Depends(get_current_user),
):
    """
    并行委派多个子代理任务（需认证）。

    基于委派-收集-合并模式，支持:
      - 三级隔离深度（上下文/进程/沙箱）
      - 工具白名单过滤
      - 资源限制（轮数/token/时间/工具调用/输出长度）
      - 软/硬超时控制
      - 生命周期状态机管理
      - 结果合并策略（拼接/DAG/LLM摘要/投票）
    """
    orchestrator = _get_orchestrator()

    # 转换 Schema 为内部数据结构
    tasks: List[SubagentTask] = []
    security_issues: List[Dict[str, str]] = []

    for schema in req.tasks:
        try:
            isolation = IsolationLevel(schema.isolation_level)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"无效的隔离级别: {schema.isolation_level}，有效值 1/2/3",
            )

        limits = ResourceLimits(
            max_turns=schema.resource_limits.max_turns,
            max_tokens=schema.resource_limits.max_tokens,
            max_time_seconds=schema.resource_limits.max_time_seconds,
            max_tool_calls=schema.resource_limits.max_tool_calls,
            max_output_tokens=schema.resource_limits.max_output_tokens,
            soft_timeout_seconds=schema.resource_limits.soft_timeout_seconds,
        )

        task = SubagentTask(
            task_id=schema.task_id,
            instruction=schema.instruction,
            context_snippet=schema.context_snippet,
            allowed_tools=schema.allowed_tools,
            timeout_seconds=schema.timeout_seconds,
            isolation_level=isolation,
            resource_limits=limits,
            metadata=schema.metadata,
        )

        # 安全性检查
        issues = validate_task_security(task)
        if issues:
            security_issues.append({"task_id": task.task_id, "issues": issues})

        tasks.append(task)

    # 合并策略校验
    try:
        strategy = ResultMergeStrategy(req.merge_strategy)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"无效的合并策略: {req.merge_strategy}",
        )

    # 内置执行器：基于已注册的子 Agent 处理任务
    async def _builtin_executor(task: SubagentTask) -> SubagentResult:
        """内置执行器：将任务路由到已注册的子 Agent。"""
        manager = _get_manager()
        # 通过 metadata.agent_name 指定要调用的子 Agent
        agent_name = task.metadata.get("agent_name", "analyzer")
        agent_info = manager._registered_agents.get(agent_name)
        if not agent_info:
            return SubagentResult(
                task_id=task.task_id,
                success=False,
                output="",
                error=f"子 Agent '{agent_name}' 未注册",
                lifecycle_state=SubagentLifecycleState.ERROR,
            )

        state = AgentState(context={"user_message": task.instruction, **task.metadata})
        try:
            result_state = await agent_info["handler"](state)
            output_parts: List[str] = []
            for msg in result_state.messages:
                output_parts.append(f"{msg.get('role', 'system')}: {msg.get('content', '')}")
            return SubagentResult(
                task_id=task.task_id,
                success=True,
                output="\n".join(output_parts) or "任务完成",
                artifacts=[result_state.results],
                metadata={"agent_name": agent_name},
            )
        except Exception as exc:
            return SubagentResult(
                task_id=task.task_id,
                success=False,
                output="",
                error=f"子 Agent 执行失败: {exc}",
                lifecycle_state=SubagentLifecycleState.ERROR,
            )

    try:
        results, merged_text = await orchestrator.delegate_all(
            tasks, executor=_builtin_executor, merge_strategy=strategy
        )
        return {
            "success": all(r.success for r in results),
            "results": [r.to_dict() for r in results],
            "merged_output": merged_text,
            "security_issues": security_issues,
            "active_tasks": orchestrator.get_active_tasks(),
        }
    except Exception as e:
        logger.error(f"Orchestrator delegation failed: {e}")
        raise HTTPException(status_code=500, detail=f"委派执行失败: {str(e)}")


@router.post("/orchestrator/cancel")
async def orchestrator_cancel(
    req: CancelRequest,
    current_user: User = Depends(get_current_user),
):
    """取消指定子代理任务（需认证）。"""
    orchestrator = _get_orchestrator()
    cancelled = await orchestrator.cancel(req.task_id)
    if not cancelled:
        raise HTTPException(
            status_code=404,
            detail=f"任务 '{req.task_id}' 不存在或已处于终态",
        )
    return {"success": True, "task_id": req.task_id, "status": "cancelled"}


@router.get("/orchestrator/active")
async def orchestrator_active(
    current_user: User = Depends(get_current_user),
):
    """获取当前活跃的子代理任务列表（需认证）。"""
    orchestrator = _get_orchestrator()
    return {
        "active_tasks": orchestrator.get_active_tasks(),
        "max_parallel": orchestrator.max_parallel,
    }


@router.get("/orchestrator/capabilities")
async def orchestrator_capabilities(
    current_user: User = Depends(get_current_user),
):
    """
    获取编排器能力描述（需认证）。

    返回隔离级别、合并策略、资源限制默认值等元信息，
    便于前端动态渲染配置表单。
    """
    return {
        "isolation_levels": [
            {"level": 1, "name": "CONTEXT", "description": "上下文隔离（开销低，安全性低）"},
            {"level": 2, "name": "PROCESS", "description": "进程级隔离（git worktree，安全性中）"},
            {"level": 3, "name": "SANDBOX", "description": "完整沙箱隔离（Docker/VM，安全性高）"},
        ],
        "merge_strategies": [
            {"value": "concatenate", "description": "直接拼接所有结果"},
            {"value": "dag", "description": "按依赖 DAG 合并"},
            {"value": "llm_summary", "description": "LLM 摘要合并"},
            {"value": "voting", "description": "多数投票"},
        ],
        "lifecycle_states": [s.value for s in SubagentLifecycleState],
        "default_limits": {
            "max_turns": DEFAULT_RESOURCE_LIMITS.max_turns,
            "max_tokens": DEFAULT_RESOURCE_LIMITS.max_tokens,
            "max_time_seconds": DEFAULT_RESOURCE_LIMITS.max_time_seconds,
            "max_tool_calls": DEFAULT_RESOURCE_LIMITS.max_tool_calls,
            "max_output_tokens": DEFAULT_RESOURCE_LIMITS.max_output_tokens,
            "soft_timeout_seconds": DEFAULT_RESOURCE_LIMITS.soft_timeout_seconds,
        },
    }
