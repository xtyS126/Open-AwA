"""
子Agent管理路由 - 提供子Agent注册、查询、图编排等API入口。
基于 langchain-ai/langgraph 思想实现的子Agent编排系统。
来源参考: https://github.com/langchain-ai/langgraph
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from loguru import logger

from core.subagent import SubAgentManager, AgentState, AgentGraph


router = APIRouter(prefix="/api/subagents", tags=["subagents"])

# 全局子Agent管理器实例
_manager: Optional[SubAgentManager] = None


def _get_manager() -> SubAgentManager:
    """获取或初始化子Agent管理器。"""
    global _manager
    if _manager is None:
        _manager = SubAgentManager()
        _register_builtin_agents(_manager)
    return _manager


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
async def list_agents():
    """获取所有已注册的子Agent。"""
    manager = _get_manager()
    agents = manager.get_registered_agents()
    return {"agents": agents, "count": len(agents)}


@router.get("/graphs")
async def list_graphs():
    """获取所有已创建的执行图。"""
    manager = _get_manager()
    graphs = manager.get_graphs_info()
    return {"graphs": graphs, "count": len(graphs)}


@router.get("/graphs/{graph_name}")
async def get_graph(graph_name: str):
    """获取指定图的详细信息。"""
    manager = _get_manager()
    graph = manager.get_graph(graph_name)
    if not graph:
        raise HTTPException(status_code=404, detail=f"图 '{graph_name}' 不存在")
    return graph.get_graph_info()


@router.post("/run/graph")
async def run_graph(req: RunGraphRequest):
    """运行指定的Agent执行图。"""
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
async def run_sequential(req: RunSequentialRequest):
    """顺序执行多个子Agent。"""
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
async def run_parallel(req: RunParallelRequest):
    """并行执行多个子Agent。"""
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
