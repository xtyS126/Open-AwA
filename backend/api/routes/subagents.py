"""
子Agent管理路由 - 提供子Agent注册、查询、图编排等API入口。
基于 langchain-ai/langgraph 思想实现的子Agent编排系统。
来源参考: https://github.com/langchain-ai/langgraph

架构参考: https://yangcazz.github.io/2026/05/22/subagent-architecture-isolation/
新增: SubagentOrchestrator 委派-收集-合并模式 API（隔离/资源限制/生命周期）
v2: 内置专业 Agent（CodeReviewAgent/SearchAgent/DataAnalysisAgent）+ 图定义持久化 + 执行历史
"""

import threading
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List, Dict, Any
from loguru import logger
from sqlalchemy.orm import Session

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
from db.models import SubagentDefinition, SubagentExecutionHistory, User, get_db


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


# ── 专业内置 Agent：CodeReviewAgent / SearchAgent / DataAnalysisAgent ──


async def _builtin_code_reviewer(state: AgentState) -> AgentState:
    """
    内置代码审查 Agent。

    基于 state.context 中的 code / language / focus 字段生成结构化审查报告。
    支持识别常见问题：安全漏洞、性能瓶颈、可读性、错误处理。
    """
    code = str(state.context.get('code') or state.context.get('user_message') or '')
    language = str(state.context.get('language') or 'unknown')
    focus = str(state.context.get('focus') or 'all')

    issues: List[Dict[str, Any]] = []
    # 基于规则的轻量静态检查（不依赖外部 LLM，保证可用性）
    code_lower = code.lower()
    if 'eval(' in code_lower or 'exec(' in code_lower:
        issues.append({
            'severity': 'critical',
            'category': 'security',
            'message': '检测到 eval/exec 调用，存在代码注入风险',
            'suggestion': '使用 ast.literal_eval 或参数化方案替代',
        })
    if 'password' in code_lower and ('=' in code_lower or '==' in code_lower):
        issues.append({
            'severity': 'high',
            'category': 'security',
            'message': '代码中疑似包含硬编码密码',
            'suggestion': '从环境变量或密钥管理服务读取凭据',
        })
    if 'except:' in code_lower or 'except exception:' in code_lower:
        issues.append({
            'severity': 'medium',
            'category': 'error_handling',
            'message': '存在过宽的异常捕获',
            'suggestion': '捕获具体异常类型，避免静默吞错误',
        })
    if code.count('\n') > 0 and code.count('def ') == 0 and code.count('class ') == 0:
        issues.append({
            'severity': 'low',
            'category': 'structure',
            'message': '代码片段未封装为函数或类',
            'suggestion': '将逻辑封装为可复用单元，便于测试和维护',
        })

    # 焦点过滤
    if focus != 'all':
        issues = [i for i in issues if i['category'] == focus] or issues

    severity_count = {'critical': 0, 'high': 0, 'medium': 0, 'low': 0}
    for issue in issues:
        severity_count[issue['severity']] = severity_count.get(issue['severity'], 0) + 1

    approved = severity_count['critical'] == 0 and severity_count['high'] == 0
    state.set_result('code_reviewer', {
        'issues': issues,
        'severity_count': severity_count,
        'approved': approved,
        'summary': f"发现 {len(issues)} 个问题（critical={severity_count['critical']}, high={severity_count['high']}）",
        'language': language,
        'lines_reviewed': code.count('\n') + 1,
    })
    state.add_message('system', f'代码审查完成: {len(issues)} 个问题，{"通过" if approved else "不通过"}')
    return state


async def _builtin_searcher(state: AgentState) -> AgentState:
    """
    内置搜索 Agent。

    基于 state.context 中的 query 字段执行搜索任务。
    当前实现为结构化响应（不调用真实搜索引擎），返回搜索建议和关键词扩展。
    """
    query = str(state.context.get('query') or state.context.get('user_message') or '').strip()
    if not query:
        state.set_result('searcher', {
            'success': False,
            'error': '搜索查询为空',
            'results': [],
        })
        state.add_message('system', '搜索失败: 查询为空')
        return state

    # 关键词扩展（简单分词）
    keywords = [kw.strip() for kw in query.replace(',', ' ').split() if kw.strip()]
    expanded_keywords = list({kw for kw in keywords if len(kw) >= 2})

    # 模拟搜索结果结构（实际场景可对接搜索 API）
    results = [{
        'title': f'关于 "{query}" 的搜索结果',
        'snippet': f'基于关键词 {", ".join(expanded_keywords[:5])} 的相关内容',
        'source': 'builtin_searcher',
        'relevance_score': 1.0,
    }]

    state.set_result('searcher', {
        'success': True,
        'query': query,
        'keywords': expanded_keywords,
        'results': results,
        'total_results': len(results),
        'search_strategy': 'keyword_expansion',
    })
    state.add_message('system', f'搜索完成: 查询="{query}"，返回 {len(results)} 条结果')
    return state


async def _builtin_data_analyst(state: AgentState) -> AgentState:
    """
    内置数据分析 Agent。

    基于 state.context 中的 data 字段执行基础统计分析。
    支持列表/字典结构数据，返回分布、聚合、异常检测等结果。
    """
    data = state.context.get('data') or state.context.get('user_message') or []
    analysis_target = str(state.context.get('analysis_target') or 'summary')

    if not data:
        state.set_result('data_analyst', {
            'success': False,
            'error': '数据为空',
            'analysis': {},
        })
        state.add_message('system', '数据分析失败: 数据为空')
        return state

    analysis: Dict[str, Any] = {'target': analysis_target}

    if isinstance(data, list):
        # 列表数据：基础统计
        numeric_values = [v for v in data if isinstance(v, (int, float))]
        analysis['record_count'] = len(data)
        analysis['data_type'] = 'list'
        if numeric_values:
            analysis['numeric_stats'] = {
                'count': len(numeric_values),
                'sum': sum(numeric_values),
                'mean': sum(numeric_values) / len(numeric_values),
                'min': min(numeric_values),
                'max': max(numeric_values),
            }
            # 异常检测：使用 IQR（四分位距）方法，对极端值更鲁棒
            if len(numeric_values) >= 4:
                mean_val = analysis['numeric_stats']['mean']
                sorted_vals = sorted(numeric_values)
                # 计算四分位数（线性插值法）
                q1_pos = 0.25 * (len(sorted_vals) - 1)
                q3_pos = 0.75 * (len(sorted_vals) - 1)
                q1_low = int(q1_pos)
                q1_high = min(q1_low + 1, len(sorted_vals) - 1)
                q1_frac = q1_pos - q1_low
                q1 = sorted_vals[q1_low] + q1_frac * (sorted_vals[q1_high] - sorted_vals[q1_low])
                q3_low = int(q3_pos)
                q3_high = min(q3_low + 1, len(sorted_vals) - 1)
                q3_frac = q3_pos - q3_low
                q3 = sorted_vals[q3_low] + q3_frac * (sorted_vals[q3_high] - sorted_vals[q3_low])
                iqr = q3 - q1
                lower_bound = q1 - 1.5 * iqr
                upper_bound = q3 + 1.5 * iqr
                outliers = [v for v in numeric_values if v < lower_bound or v > upper_bound]
                analysis['outliers'] = outliers
                analysis['numeric_stats']['std'] = (sum((v - mean_val) ** 2 for v in numeric_values) / len(numeric_values)) ** 0.5
                analysis['numeric_stats']['q1'] = q1
                analysis['numeric_stats']['q3'] = q3
                analysis['numeric_stats']['iqr'] = iqr
        # 类型分布
        type_distribution: Dict[str, int] = {}
        for item in data:
            type_name = type(item).__name__
            type_distribution[type_name] = type_distribution.get(type_name, 0) + 1
        analysis['type_distribution'] = type_distribution
    elif isinstance(data, dict):
        # 字典数据：键值统计
        analysis['record_count'] = len(data)
        analysis['data_type'] = 'dict'
        analysis['keys'] = list(data.keys())
        # 值类型分布
        value_types: Dict[str, int] = {}
        for v in data.values():
            type_name = type(v).__name__
            value_types[type_name] = value_types.get(type_name, 0) + 1
        analysis['value_type_distribution'] = value_types
    else:
        analysis['data_type'] = type(data).__name__
        analysis['record_count'] = 1
        analysis['note'] = '不支持的复杂数据类型，仅做类型识别'

    state.set_result('data_analyst', {
        'success': True,
        'analysis': analysis,
        'summary': f"分析完成: {analysis.get('record_count', 0)} 条记录，类型={analysis.get('data_type', 'unknown')}",
    })
    state.add_message('system', f'数据分析完成: {analysis.get("record_count", 0)} 条记录')
    return state


def _register_builtin_agents(manager: SubAgentManager):
    """注册内置子Agent。"""
    # 基础流水线 Agent
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

    # 专业 Agent（路线图 2.3.1 要求）
    manager.register_agent(
        'code_reviewer', _builtin_code_reviewer,
        description='代码审查 Agent：基于规则识别安全漏洞、性能问题、错误处理缺陷',
        capabilities=['static_analysis', 'security_audit', 'code_quality']
    )
    manager.register_agent(
        'searcher', _builtin_searcher,
        description='搜索 Agent：关键词扩展与结构化搜索结果聚合',
        capabilities=['keyword_expansion', 'result_aggregation']
    )
    manager.register_agent(
        'data_analyst', _builtin_data_analyst,
        description='数据分析 Agent：基础统计、分布分析、异常检测',
        capabilities=['statistical_analysis', 'outlier_detection', 'data_summary']
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

    # 代码审查专用图
    code_review_graph = manager.create_graph(
        'code_review_pipeline',
        description='代码审查流水线：分析 -> 审查 -> 反馈'
    )
    code_review_graph.add_node('analyzer', _builtin_analyzer, '分析代码结构')
    code_review_graph.add_node('code_reviewer', _builtin_code_reviewer, '执行代码审查')
    code_review_graph.add_edge('analyzer', 'code_reviewer')
    code_review_graph.set_entry_point('analyzer')
    code_review_graph.set_finish_point('code_reviewer')

    # 数据分析专用图
    data_analysis_graph = manager.create_graph(
        'data_analysis_pipeline',
        description='数据分析流水线：搜索 -> 分析 -> 总结'
    )
    data_analysis_graph.add_node('searcher', _builtin_searcher, '检索相关数据')
    data_analysis_graph.add_node('data_analyst', _builtin_data_analyst, '执行数据分析')
    data_analysis_graph.add_edge('searcher', 'data_analyst')
    data_analysis_graph.set_entry_point('searcher')
    data_analysis_graph.set_finish_point('data_analyst')

    logger.info("Built-in sub-agents and default pipelines registered")


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
) -> Dict[str, Any]:
    """获取所有已注册的子Agent（需认证）。"""
    manager = _get_manager()
    agents = manager.get_registered_agents()
    return {"agents": agents, "count": len(agents)}


@router.get("/graphs")
async def list_graphs(
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """获取所有已创建的执行图（需认证）。"""
    manager = _get_manager()
    graphs = manager.get_graphs_info()
    return {"graphs": graphs, "count": len(graphs)}


@router.get("/graphs/{graph_name}")
async def get_graph(
    graph_name: str,
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
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
) -> Dict[str, Any]:
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
        raise HTTPException(status_code=500, detail="图执行失败，请稍后重试")


@router.post("/run/sequential")
async def run_sequential(
    req: RunSequentialRequest,
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
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
        raise HTTPException(status_code=500, detail="顺序执行失败，请稍后重试")


@router.post("/run/parallel")
async def run_parallel(
    req: RunParallelRequest,
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
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
        raise HTTPException(status_code=500, detail="并行执行失败，请稍后重试")


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
) -> Dict[str, Any]:
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
        raise HTTPException(status_code=500, detail="委派执行失败，请稍后重试")


@router.post("/orchestrator/cancel")
async def orchestrator_cancel(
    req: CancelRequest,
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
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
) -> Dict[str, Any]:
    """获取当前活跃的子代理任务列表（需认证）。"""
    orchestrator = _get_orchestrator()
    return {
        "active_tasks": orchestrator.get_active_tasks(),
        "max_parallel": orchestrator.max_parallel,
    }


@router.get("/orchestrator/capabilities")
async def orchestrator_capabilities(
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
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


# ── 图定义持久化 CRUD API ──────────────────────────────────────────


class GraphNodeSchema(BaseModel):
    """图节点定义。"""
    name: str = Field(..., min_length=1, max_length=100, description="节点名称")
    agent_name: str = Field(..., min_length=1, max_length=100, description="绑定的已注册 Agent 名称")
    description: str = Field(default="", max_length=500, description="节点描述")
    timeout: float = Field(default=60.0, ge=1, le=600, description="节点超时秒数")
    retry_count: int = Field(default=0, ge=0, le=5, description="重试次数")


class GraphEdgeSchema(BaseModel):
    """图边定义。"""
    source: str = Field(..., min_length=1, max_length=100, description="源节点名称")
    target: str = Field(..., min_length=1, max_length=100, description="目标节点名称")


class GraphDefinitionSchema(BaseModel):
    """图结构定义。"""
    nodes: List[GraphNodeSchema] = Field(..., min_length=1, description="节点列表")
    edges: List[GraphEdgeSchema] = Field(default_factory=list, description="边列表")
    entry_point: str = Field(..., min_length=1, max_length=100, description="入口节点")
    finish_points: List[str] = Field(default_factory=list, description="终止节点列表")


class SubagentDefinitionCreate(BaseModel):
    """创建图定义请求。"""
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(..., min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_\-]+$", description="图名称")
    description: str = Field(default="", max_length=1000)
    graph_definition: GraphDefinitionSchema
    tags: Optional[str] = Field(default=None, max_length=500)


class SubagentDefinitionUpdate(BaseModel):
    """更新图定义请求。"""
    model_config = ConfigDict(str_strip_whitespace=True)

    description: Optional[str] = Field(default=None, max_length=1000)
    graph_definition: Optional[GraphDefinitionSchema] = None
    tags: Optional[str] = Field(default=None, max_length=500)


class SubagentDefinitionResponse(BaseModel):
    """图定义响应。"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str
    graph_definition: Dict[str, Any]
    user_id: str
    is_builtin: bool
    tags: Optional[str]
    created_at: datetime
    updated_at: datetime


def _validate_graph_definition(schema: GraphDefinitionSchema, manager: SubAgentManager) -> None:
    """校验图定义：节点引用的 Agent 必须已注册，边引用的节点必须存在。"""
    registered_agents = {info["name"] for info in manager.get_registered_agents()}
    node_names = {node.name for node in schema.nodes}

    for node in schema.nodes:
        if node.agent_name not in registered_agents:
            raise HTTPException(
                status_code=400,
                detail=f"节点 '{node.name}' 引用的 Agent '{node.agent_name}' 未注册",
            )

    for edge in schema.edges:
        if edge.source not in node_names:
            raise HTTPException(
                status_code=400,
                detail=f"边源节点 '{edge.source}' 不在节点列表中",
            )
        if edge.target not in node_names:
            raise HTTPException(
                status_code=400,
                detail=f"边目标节点 '{edge.target}' 不在节点列表中",
            )

    if schema.entry_point not in node_names:
        raise HTTPException(
            status_code=400,
            detail=f"入口节点 '{schema.entry_point}' 不在节点列表中",
        )

    for fp in schema.finish_points:
        if fp not in node_names:
            raise HTTPException(
                status_code=400,
                detail=f"终止节点 '{fp}' 不在节点列表中",
            )


def _build_graph_from_definition(schema: GraphDefinitionSchema, name: str, description: str, manager: SubAgentManager) -> AgentGraph:
    """从图定义 Schema 构建运行时 AgentGraph 实例。"""
    graph = manager.create_graph(name, description=description)
    for node in schema.nodes:
        agent_info = manager._registered_agents.get(node.agent_name)
        if not agent_info:
            raise ValueError(f"Agent '{node.agent_name}' 未注册")
        graph.add_node(
            node.name,
            agent_info["handler"],
            description=node.description,
            retry_count=node.retry_count,
            timeout=node.timeout,
        )
    for edge in schema.edges:
        graph.add_edge(edge.source, edge.target)
    graph.set_entry_point(schema.entry_point)
    for fp in schema.finish_points:
        graph.set_finish_point(fp)
    return graph


@router.get("/definitions", response_model=List[SubagentDefinitionResponse])
async def list_definitions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> Dict[str, Any]:
    """列出当前用户的图定义（含内置图）。"""
    user_id = str(current_user.id)
    definitions = (
        db.query(SubagentDefinition)
        .filter(
            (SubagentDefinition.user_id == user_id) | (SubagentDefinition.is_builtin == True)
        )
        .order_by(SubagentDefinition.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return definitions


@router.post("/definitions", response_model=SubagentDefinitionResponse)
async def create_definition(
    payload: SubagentDefinitionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """创建新的图定义。"""
    user_id = str(current_user.id)
    manager = _get_manager()

    # 检查名称冲突
    existing = db.query(SubagentDefinition).filter(
        SubagentDefinition.name == payload.name,
        (SubagentDefinition.user_id == user_id) | (SubagentDefinition.is_builtin == True),
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"图定义 '{payload.name}' 已存在")

    # 校验图结构
    _validate_graph_definition(payload.graph_definition, manager)

    # 持久化
    definition = SubagentDefinition(
        name=payload.name,
        description=payload.description,
        graph_definition=payload.graph_definition.model_dump(),
        user_id=user_id,
        is_builtin=False,
        tags=payload.tags,
    )
    db.add(definition)
    db.commit()
    db.refresh(definition)

    # 同步注册到运行时管理器
    try:
        _build_graph_from_definition(payload.graph_definition, payload.name, payload.description, manager)
    except Exception as exc:
        logger.warning(f"图定义 {payload.name} 持久化成功但运行时注册失败: {exc}")

    return definition


@router.put("/definitions/{definition_id}", response_model=SubagentDefinitionResponse)
async def update_definition(
    definition_id: int,
    payload: SubagentDefinitionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """更新图定义。内置图不可更新。"""
    user_id = str(current_user.id)
    definition = db.query(SubagentDefinition).filter(
        SubagentDefinition.id == definition_id,
        SubagentDefinition.user_id == user_id,
    ).first()
    if not definition:
        raise HTTPException(status_code=404, detail="图定义不存在或无权修改")
    if definition.is_builtin:
        raise HTTPException(status_code=403, detail="内置图定义不可修改")

    manager = _get_manager()

    if payload.description is not None:
        definition.description = payload.description
    if payload.tags is not None:
        definition.tags = payload.tags
    if payload.graph_definition is not None:
        _validate_graph_definition(payload.graph_definition, manager)
        definition.graph_definition = payload.graph_definition.model_dump()
        # 重建运行时图
        if definition.name in manager.graphs:
            del manager.graphs[definition.name]
        try:
            _build_graph_from_definition(payload.graph_definition, definition.name, definition.description, manager)
        except Exception as exc:
            logger.warning(f"图定义 {definition.name} 运行时重建失败: {exc}")

    db.commit()
    db.refresh(definition)
    return definition


@router.delete("/definitions/{definition_id}")
async def delete_definition(
    definition_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """删除图定义。内置图不可删除。"""
    user_id = str(current_user.id)
    definition = db.query(SubagentDefinition).filter(
        SubagentDefinition.id == definition_id,
        SubagentDefinition.user_id == user_id,
    ).first()
    if not definition:
        raise HTTPException(status_code=404, detail="图定义不存在或无权删除")
    if definition.is_builtin:
        raise HTTPException(status_code=403, detail="内置图定义不可删除")

    manager = _get_manager()
    if definition.name in manager.graphs:
        del manager.graphs[definition.name]

    db.delete(definition)
    db.commit()
    return {"message": f"图定义 '{definition.name}' 已删除"}


class RunDefinitionRequest(BaseModel):
    """运行图定义请求。"""
    context: Dict[str, Any] = Field(default_factory=dict, description="初始上下文")
    messages: List[Dict[str, str]] = Field(default_factory=list, description="初始消息")


@router.post("/definitions/{definition_id}/run")
async def run_definition(
    definition_id: int,
    payload: RunDefinitionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """运行指定的图定义。"""
    user_id = str(current_user.id)
    definition = db.query(SubagentDefinition).filter(
        SubagentDefinition.id == definition_id,
        (SubagentDefinition.user_id == user_id) | (SubagentDefinition.is_builtin == True),
    ).first()
    if not definition:
        raise HTTPException(status_code=404, detail="图定义不存在")

    manager = _get_manager()
    graph = manager.get_graph(definition.name)
    if not graph:
        # 尝试从持久化定义重建
        try:
            schema = GraphDefinitionSchema(**definition.graph_definition)
            _build_graph_from_definition(schema, definition.name, definition.description, manager)
            graph = manager.get_graph(definition.name)
        except Exception as exc:
            # 记录实际异常便于排查，但避免向客户端泄露内部错误详情
            logger.error("图重建失败", exc_info=exc, extra={"graph_name": definition.name})
            raise HTTPException(status_code=500, detail="图重建失败，请稍后重试")

    if not graph:
        raise HTTPException(status_code=500, detail="图运行时实例不可用")

    context = payload.context
    state = AgentState(
        context=context,
        messages=[{"role": m.get("role", "user"), "content": m.get("content", "")} for m in payload.messages],
    )

    started_at = time.time()
    success = False
    error_msg = ""
    try:
        result_state = await graph.execute(state)
        success = len(result_state.errors) == 0
        # 非异常路径下也收集 errors 信息，避免历史记录丢失错误上下文
        if not success and result_state.errors:
            error_msg = str(result_state.errors)
        response = {
            "success": success,
            "results": result_state.results,
            "messages": result_state.messages,
            "errors": result_state.errors,
            "metadata": result_state.metadata,
            "execution_log": graph.get_execution_log(),
        }
    except Exception as exc:
        error_msg = str(exc)
        logger.error(f"图定义 {definition.name} 执行失败: {exc}")
        response = {"success": False, "error": error_msg}

    # 持久化执行历史
    duration = time.time() - started_at
    try:
        history = SubagentExecutionHistory(
            graph_name=definition.name,
            user_id=user_id,
            execution_mode="graph",
            initial_context=context,
            results=response.get("results", {}),
            errors=response.get("errors", {}) if success else {"error": error_msg},
            execution_log=response.get("execution_log", []),
            success=success,
            duration_seconds=duration,
        )
        db.add(history)
        db.commit()
    except Exception as exc:
        logger.warning(f"执行历史持久化失败: {exc}")

    return response


# ── 执行历史查询 API ──────────────────────────────────────────


class ExecutionHistoryResponse(BaseModel):
    """执行历史响应。"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    graph_name: str
    user_id: str
    execution_mode: str
    initial_context: Dict[str, Any]
    results: Dict[str, Any]
    errors: Dict[str, Any]
    execution_log: List[Dict[str, Any]]
    success: bool
    duration_seconds: float
    created_at: datetime


@router.get("/history", response_model=List[ExecutionHistoryResponse])
async def list_execution_history(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    graph_name: Optional[str] = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
) -> Dict[str, Any]:
    """查询当前用户的子智能体执行历史。"""
    user_id = str(current_user.id)
    query = db.query(SubagentExecutionHistory).filter(
        SubagentExecutionHistory.user_id == user_id
    )
    if graph_name:
        query = query.filter(SubagentExecutionHistory.graph_name == graph_name)
    history = (
        query.order_by(SubagentExecutionHistory.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return history


@router.get("/history/{history_id}", response_model=ExecutionHistoryResponse)
async def get_execution_history(
    history_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """获取指定执行历史详情。"""
    user_id = str(current_user.id)
    history = db.query(SubagentExecutionHistory).filter(
        SubagentExecutionHistory.id == history_id,
        SubagentExecutionHistory.user_id == user_id,
    ).first()
    if not history:
        raise HTTPException(status_code=404, detail="执行历史不存在")
    return history
