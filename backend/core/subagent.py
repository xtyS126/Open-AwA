"""
子Agent编排系统 - 受 langchain-ai/langgraph 启发的子Agent管理和协调模块。
来源参考: https://github.com/langchain-ai/langgraph
作者: langchain-ai
许可: MIT License

本模块实现了类似 LangGraph 的状态图（StateGraph）概念，
支持将复杂任务分解为多个子Agent节点，通过状态传递实现协作。

架构参考: https://yangcazz.github.io/2026/05/22/subagent-architecture-isolation/
核心概念:
  - SubAgent: 独立的执行单元，具有特定职责
  - AgentState: 在节点间传递的共享状态
  - AgentGraph: 定义节点和边的有向图，编排执行流程
  - SubagentTask/SubagentResult: 委派-收集-合并模式的核心数据结构
  - IsolationLevel: 三级隔离深度（上下文/进程/沙箱）
  - SubagentOrchestrator: 带资源限制和超时控制的编排器
  - ResourceLimits: 子代理资源配额（轮数/token/时间/工具调用次数）
"""

import asyncio
import copy
import time
import uuid
from enum import Enum
from typing import Dict, List, Any, Optional, Callable, Awaitable, Union, Sequence
from dataclasses import dataclass, field
from loguru import logger


# ── 隔离深度与生命周期 ──────────────────────────────────────────────


class IsolationLevel(int, Enum):
    """
    子代理隔离深度（参考文章 3.1 三级隔离深度）。

    Level 1: 上下文隔离 - 独立上下文窗口，共享进程和文件系统，开销几乎为零
    Level 2: 进程级隔离 - 独立上下文 + 沙箱进程（git worktree），受限文件系统
    Level 3: 完整沙箱隔离 - Docker/VM 级隔离，完整文件系统快照，网络完全隔离
    """

    CONTEXT = 1  # 上下文隔离
    PROCESS = 2  # 进程级隔离（worktree）
    SANDBOX = 3  # 完整沙箱隔离


class SubagentLifecycleState(str, Enum):
    """
    子代理生命周期状态机（参考文章 5.1 状态机）。

    状态转换路径:
        Created -> Running -> Waiting -> Completed/Timeout/Error/Cancelled -> Terminated
    """

    CREATED = "created"
    RUNNING = "running"
    WAITING = "waiting"
    COMPLETED = "completed"
    TIMEOUT = "timeout"
    ERROR = "error"
    CANCELLED = "cancelled"
    TERMINATED = "terminated"


# 合法的状态转换（参考文章 5.1 状态机）
VALID_LIFECYCLE_TRANSITIONS: Dict[str, set] = {
    SubagentLifecycleState.CREATED.value: {
        SubagentLifecycleState.RUNNING.value,
        SubagentLifecycleState.CANCELLED.value,
    },
    SubagentLifecycleState.RUNNING.value: {
        SubagentLifecycleState.WAITING.value,
        SubagentLifecycleState.COMPLETED.value,
        SubagentLifecycleState.TIMEOUT.value,
        SubagentLifecycleState.ERROR.value,
        SubagentLifecycleState.CANCELLED.value,
    },
    SubagentLifecycleState.WAITING.value: {
        SubagentLifecycleState.RUNNING.value,
        SubagentLifecycleState.COMPLETED.value,
        SubagentLifecycleState.TIMEOUT.value,
        SubagentLifecycleState.ERROR.value,
        SubagentLifecycleState.CANCELLED.value,
    },
    # 终态均可转入 TERMINATED（资源释放）
    SubagentLifecycleState.COMPLETED.value: {SubagentLifecycleState.TERMINATED.value},
    SubagentLifecycleState.TIMEOUT.value: {SubagentLifecycleState.TERMINATED.value},
    SubagentLifecycleState.ERROR.value: {SubagentLifecycleState.TERMINATED.value},
    SubagentLifecycleState.CANCELLED.value: {SubagentLifecycleState.TERMINATED.value},
    SubagentLifecycleState.TERMINATED.value: set(),
}


def validate_lifecycle_transition(current: str, target: str) -> bool:
    """校验生命周期状态转换是否合法。"""
    allowed = VALID_LIFECYCLE_TRANSITIONS.get(current, set())
    return target in allowed


# ── 资源限制与任务/结果数据结构 ──────────────────────────────────────


@dataclass
class ResourceLimits:
    """
    子代理资源限制配置（参考文章 5.2 资源限制与超时）。

    所有字段均为可选，未设置时使用编排器默认值。
    """

    max_turns: int = 20  # 最大 Agent 循环轮数
    max_tokens: int = 8000  # 最大消耗 token 数
    max_time_seconds: int = 120  # 最大执行时间（硬超时）
    max_tool_calls: int = 15  # 最大工具调用次数
    max_output_tokens: int = 2000  # 返回结果的最大长度（字符数近似）
    soft_timeout_seconds: int = 90  # 软超时：触发后给一轮时间收尾


# 默认资源限制（参考文章 5.2）
DEFAULT_RESOURCE_LIMITS = ResourceLimits()


@dataclass
class SubagentTask:
    """
    委派给 Subagent 的任务（参考文章 4.1 基本模式）。

    封装任务指令、上下文片段、工具白名单、超时与隔离级别，
    供 SubagentOrchestrator 统一调度。
    """

    task_id: str
    instruction: str
    context_snippet: str = ""  # 仅传递必要的上下文片段，避免污染
    allowed_tools: List[str] = field(default_factory=list)  # 工具白名单
    timeout_seconds: int = 120
    isolation_level: IsolationLevel = IsolationLevel.CONTEXT
    resource_limits: ResourceLimits = field(default_factory=ResourceLimits)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """校验必填字段。"""
        if not self.task_id:
            raise ValueError("task_id 不能为空")
        if not self.instruction:
            raise ValueError("instruction 不能为空")


@dataclass
class SubagentResult:
    """
    Subagent 执行结果（参考文章 4.1 基本模式）。

    包含成功标志、输出文本、产物列表、token 消耗与耗时，
    供结果合并策略统一处理。
    """

    task_id: str
    success: bool
    output: str
    artifacts: List[Any] = field(default_factory=list)  # 文件路径、代码片段等
    tokens_used: int = 0
    elapsed_seconds: float = 0.0
    error: Optional[str] = None
    lifecycle_state: SubagentLifecycleState = SubagentLifecycleState.COMPLETED
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典。"""
        return {
            "task_id": self.task_id,
            "success": self.success,
            "output": self.output,
            "artifacts": self.artifacts,
            "tokens_used": self.tokens_used,
            "elapsed_seconds": self.elapsed_seconds,
            "error": self.error,
            "lifecycle_state": self.lifecycle_state.value,
            "metadata": self.metadata,
        }


# ── 结果合并策略 ──────────────────────────────────────────────────


class ResultMergeStrategy(str, Enum):
    """
    结果合并策略（参考文章 4.2 结果合并策略）。

    - CONCATENATE: 直接拼接所有结果
    - DAG: 按依赖 DAG 合并，先完成的作为后续输入
    - LLM_SUMMARY: 将所有结果输入 LLM 生成整合摘要
    - VOTING: 多数投票，取一致/最优结果
    """

    CONCATENATE = "concatenate"
    DAG = "dag"
    LLM_SUMMARY = "llm_summary"
    VOTING = "voting"


def merge_results_concatenate(results: List[SubagentResult]) -> str:
    """直接拼接所有成功结果的输出。"""
    parts: List[str] = []
    for r in results:
        if r.success and r.output:
            parts.append(f"[{r.task_id}]\n{r.output}")
        elif not r.success:
            parts.append(f"[{r.task_id}] [FAILED] {r.error or '执行失败'}")
    return "\n\n".join(parts)


def merge_results_voting(results: List[SubagentResult]) -> str:
    """
    多数投票合并：对成功结果按输出内容分组，取出现次数最多的输出。
    适用于多代理冗余执行同一任务的场景。
    """
    success_results = [r for r in results if r.success and r.output]
    if not success_results:
        return merge_results_concatenate(results)

    # 按输出内容归一化后分组计数
    vote_map: Dict[str, List[SubagentResult]] = {}
    for r in success_results:
        normalized = r.output.strip()
        vote_map.setdefault(normalized, []).append(r)

    # 取票数最高的结果
    best_group = max(vote_map.values(), key=len)
    winner = best_group[0]
    vote_count = len(best_group)
    return f"[VOTING] {vote_count}/{len(success_results)} 票一致\n{winner.output}"


def merge_results(
    results: List[SubagentResult],
    strategy: ResultMergeStrategy = ResultMergeStrategy.CONCATENATE,
) -> str:
    """根据策略合并子代理结果。"""
    if strategy == ResultMergeStrategy.VOTING:
        return merge_results_voting(results)
    if strategy == ResultMergeStrategy.LLM_SUMMARY:
        # LLM 摘要需要外部 LLM 调用，此处降级为拼接并标注
        concatenated = merge_results_concatenate(results)
        return f"[LLM_SUMMARY 需外部 LLM 调用，降级为拼接]\n{concatenated}"
    if strategy == ResultMergeStrategy.DAG:
        # DAG 合并需要依赖信息，此处按完成顺序拼接
        return merge_results_concatenate(results)
    return merge_results_concatenate(results)


# ── Agent 节点状态与图结构（保留原有 LangGraph 风格） ──────────────


class AgentNodeStatus(str, Enum):
    """Agent节点执行状态。"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class AgentState:
    """
    Agent状态对象 - 在子Agent节点之间传递的共享状态。
    参考 LangGraph 的 State 概念，所有节点通过读写状态进行通信。
    """
    messages: List[Dict[str, Any]] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)
    results: Dict[str, Any] = field(default_factory=dict)
    errors: Dict[str, str] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def add_message(self, role: str, content: str, **kwargs):
        """添加消息到状态。"""
        msg = {"role": role, "content": content, **kwargs}
        self.messages.append(msg)

    def set_result(self, node_name: str, result: Any):
        """设置节点执行结果。"""
        self.results[node_name] = result

    def get_result(self, node_name: str) -> Any:
        """获取节点执行结果。"""
        return self.results.get(node_name)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典。"""
        return {
            "messages": self.messages,
            "context": self.context,
            "results": self.results,
            "errors": self.errors,
            "metadata": self.metadata
        }


# Agent节点函数类型
AgentNodeFunc = Callable[[AgentState], Awaitable[AgentState]]
# 条件路由函数类型
ConditionalEdgeFunc = Callable[[AgentState], str]


@dataclass
class AgentNode:
    """
    Agent节点定义。
    每个节点封装一个异步执行函数，代表图中的一个处理步骤。
    """
    name: str
    func: AgentNodeFunc
    description: str = ""
    retry_count: int = 0
    timeout: float = 60.0


@dataclass
class AgentEdge:
    """
    Agent边定义。
    连接两个节点，支持条件路由。
    """
    source: str
    target: str
    condition: Optional[ConditionalEdgeFunc] = None
    condition_value: Optional[str] = None


@dataclass
class NodeExecution:
    """节点执行记录。"""
    node_name: str
    status: AgentNodeStatus
    start_time: float
    end_time: Optional[float] = None
    duration_ms: Optional[int] = None
    error: Optional[str] = None


class AgentGraph:
    """
    Agent有向图 - 受 LangGraph StateGraph 启发的执行编排图。
    定义节点和边，支持条件分支、顺序执行和并行执行。

    使用方式:
        graph = AgentGraph("task_decomposition")
        graph.add_node("analyzer", analyze_func, "分析用户意图")
        graph.add_node("planner", plan_func, "生成执行计划")
        graph.add_node("executor", execute_func, "执行计划")
        graph.add_edge("analyzer", "planner")
        graph.add_edge("planner", "executor")
        graph.set_entry_point("analyzer")
        graph.set_finish_point("executor")
        result = await graph.execute(initial_state)
    """

    def __init__(self, name: str, description: str = ""):
        """初始化Agent图。"""
        self.name = name
        self.description = description
        self.nodes: Dict[str, AgentNode] = {}
        self.edges: List[AgentEdge] = []
        self.conditional_edges: Dict[str, List[AgentEdge]] = {}
        self.entry_point: Optional[str] = None
        self.finish_points: List[str] = []
        self._execution_log: List[NodeExecution] = []

    def add_node(self, name: str, func: AgentNodeFunc, description: str = "",
                 retry_count: int = 0, timeout: float = 60.0) -> 'AgentGraph':
        """添加节点到图中。"""
        if name in self.nodes:
            raise ValueError(f"节点 '{name}' 已存在")
        self.nodes[name] = AgentNode(
            name=name, func=func, description=description,
            retry_count=retry_count, timeout=timeout
        )
        logger.debug(f"Added node '{name}' to graph '{self.name}'")
        return self

    def add_edge(self, source: str, target: str) -> 'AgentGraph':
        """添加普通边（无条件连接两个节点）。"""
        self.edges.append(AgentEdge(source=source, target=target))
        return self

    def add_conditional_edges(self, source: str,
                               condition: ConditionalEdgeFunc,
                               target_map: Dict[str, str]) -> 'AgentGraph':
        """
        添加条件边 - 根据条件函数返回值路由到不同目标节点。
        参考 LangGraph 的 add_conditional_edges。

        target_map: 条件返回值 -> 目标节点名的映射
        """
        if source not in self.conditional_edges:
            self.conditional_edges[source] = []
        for condition_value, target in target_map.items():
            self.conditional_edges[source].append(
                AgentEdge(source=source, target=target, condition=condition, condition_value=condition_value)
            )
        logger.debug(f"Added conditional edges from '{source}' with {len(target_map)} branches")
        return self

    def set_entry_point(self, node_name: str) -> 'AgentGraph':
        """设置图的入口节点。"""
        if node_name not in self.nodes:
            raise ValueError(f"入口节点 '{node_name}' 不存在")
        self.entry_point = node_name
        return self

    def set_finish_point(self, node_name: str) -> 'AgentGraph':
        """设置图的终止节点。"""
        if node_name not in self.nodes:
            raise ValueError(f"终止节点 '{node_name}' 不存在")
        self.finish_points.append(node_name)
        return self

    def _get_next_nodes(self, current_node: str, state: AgentState) -> List[str]:
        """根据当前节点和状态确定下一步要执行的节点。"""
        next_nodes = []

        # 检查条件边 - 条件函数返回值与 condition_value 匹配则路由
        if current_node in self.conditional_edges:
            for edge in self.conditional_edges[current_node]:
                if edge.condition:
                    try:
                        result = edge.condition(state)
                    except Exception as exc:
                        logger.bind(module="subagent", event="condition_error").warning(
                            f"条件边回调异常: {exc}"
                        )
                        continue
                    if result == edge.condition_value:
                        next_nodes.append(edge.target)
                        break

        # 检查普通边
        if not next_nodes:
            for edge in self.edges:
                if edge.source == current_node:
                    next_nodes.append(edge.target)

        return next_nodes

    async def _execute_node(self, node: AgentNode, state: AgentState) -> AgentState:
        """执行单个节点，支持重试和超时。"""
        execution = NodeExecution(
            node_name=node.name,
            status=AgentNodeStatus.RUNNING,
            start_time=time.time()
        )
        self._execution_log.append(execution)

        attempts = 0
        max_attempts = node.retry_count + 1

        while attempts < max_attempts:
            attempts += 1
            try:
                logger.info(f"Executing node '{node.name}' (attempt {attempts}/{max_attempts})")
                state = await asyncio.wait_for(
                    node.func(state),
                    timeout=node.timeout
                )
                execution.status = AgentNodeStatus.COMPLETED
                execution.end_time = time.time()
                execution.duration_ms = int((execution.end_time - execution.start_time) * 1000)
                logger.info(f"Node '{node.name}' completed in {execution.duration_ms}ms")
                return state
            except asyncio.TimeoutError:
                error_msg = f"节点 '{node.name}' 执行超时 ({node.timeout}秒)"
                logger.warning(error_msg)
                if attempts >= max_attempts:
                    execution.status = AgentNodeStatus.FAILED
                    execution.error = error_msg
                    execution.end_time = time.time()
                    execution.duration_ms = int((execution.end_time - execution.start_time) * 1000)
                    state.errors[node.name] = error_msg
                    raise
            except Exception as e:
                error_msg = f"节点 '{node.name}' 执行失败: {str(e)}"
                logger.error(error_msg)
                if attempts >= max_attempts:
                    execution.status = AgentNodeStatus.FAILED
                    execution.error = error_msg
                    execution.end_time = time.time()
                    execution.duration_ms = int((execution.end_time - execution.start_time) * 1000)
                    state.errors[node.name] = error_msg
                    raise

        return state

    async def execute(self, initial_state: Optional[AgentState] = None,
                      max_steps: int = 50) -> AgentState:
        """
        执行整个Agent图。
        从入口节点开始，按照边的定义逐步执行，直到到达终止节点或无后续节点。
        当同一层级存在多个可执行节点时，并行执行并合并状态。
        """
        import copy

        if not self.entry_point:
            raise ValueError("未设置入口节点，请调用 set_entry_point()")
        if self.entry_point not in self.nodes:
            raise ValueError(f"入口节点 '{self.entry_point}' 不存在")

        state = initial_state or AgentState()
        state.metadata['graph_name'] = self.name
        state.metadata['execution_id'] = str(uuid.uuid4())
        state.metadata['start_time'] = time.time()

        self._execution_log = []
        current_nodes = [self.entry_point]
        steps = 0

        logger.info(f"Starting graph execution: {self.name}")

        while current_nodes and steps < max_steps:
            steps += 1
            next_nodes = []

            if len(current_nodes) == 1:
                # 单节点：直接执行，无需拷贝
                node_name = current_nodes[0]
                if node_name not in self.nodes:
                    logger.warning(f"Node '{node_name}' not found, skipping")
                else:
                    node = self.nodes[node_name]
                    try:
                        state = await self._execute_node(node, state)
                    except Exception as e:
                        logger.error(f"Node '{node_name}' failed: {e}")
                        state.errors[node_name] = str(e)
                        state.metadata['has_failures'] = True
                        # 失败时不继续该节点的后继节点
                        continue

                    if node_name not in self.finish_points:
                        successors = self._get_next_nodes(node_name, state)
                        next_nodes.extend(successors)
            else:
                # 多节点并行：每个节点获取状态的深拷贝，执行后合并
                async def _run_parallel_node(n_name: str, n_state: AgentState) -> tuple[str, AgentState, Optional[str]]:
                    """并行执行单个节点，返回 (节点名, 结果状态, 错误信息)。"""
                    if n_name not in self.nodes:
                        return n_name, n_state, None
                    node = self.nodes[n_name]
                    try:
                        result = await self._execute_node(node, n_state)
                        return n_name, result, None
                    except Exception as exc:
                        return n_name, n_state, str(exc)

                # 为每个并行节点创建独立的状态副本
                parallel_tasks = []
                for node_name in current_nodes:
                    node_state = AgentState(
                        messages=copy.deepcopy(state.messages),
                        context=copy.deepcopy(state.context),
                        results=copy.deepcopy(state.results),
                        errors=copy.deepcopy(state.errors),
                        metadata=copy.deepcopy(state.metadata),
                    )
                    parallel_tasks.append(_run_parallel_node(node_name, node_state))

                # 并行执行所有节点
                parallel_results = await asyncio.gather(*parallel_tasks)

                # 合并所有并行节点的结果
                for node_name, result_state, error_msg in parallel_results:
                    if error_msg:
                        logger.error(f"Node '{node_name}' failed: {error_msg}")
                        state.errors[node_name] = error_msg
                        state.metadata['has_failures'] = True
                        continue

                    # 合并结果和消息
                    state.results.update(result_state.results)
                    for msg in result_state.messages[len(state.messages):]:
                        state.messages.append(msg)
                    # 合并上下文（并行节点新增的键）
                    for key, value in result_state.context.items():
                        if key not in state.context:
                            state.context[key] = value

                    if node_name not in self.finish_points:
                        successors = self._get_next_nodes(node_name, result_state)
                        next_nodes.extend(successors)

            current_nodes = list(set(next_nodes))

        state.metadata['end_time'] = time.time()
        state.metadata['total_steps'] = steps
        state.metadata['total_duration_ms'] = int(
            (state.metadata['end_time'] - state.metadata['start_time']) * 1000
        )

        logger.info(
            f"Graph '{self.name}' completed: steps={steps}, "
            f"duration={state.metadata['total_duration_ms']}ms"
        )

        return state

    def get_execution_log(self) -> List[Dict[str, Any]]:
        """获取执行日志。"""
        return [
            {
                "node": ex.node_name,
                "status": ex.status.value,
                "start_time": ex.start_time,
                "end_time": ex.end_time,
                "duration_ms": ex.duration_ms,
                "error": ex.error
            }
            for ex in self._execution_log
        ]

    def get_graph_info(self) -> Dict[str, Any]:
        """获取图的结构信息。"""
        return {
            "name": self.name,
            "description": self.description,
            "nodes": [
                {
                    "name": n.name,
                    "description": n.description,
                    "timeout": n.timeout,
                    "retry_count": n.retry_count
                }
                for n in self.nodes.values()
            ],
            "edges": [
                {"source": e.source, "target": e.target, "conditional": e.condition is not None}
                for e in self.edges
            ],
            "entry_point": self.entry_point,
            "finish_points": self.finish_points
        }


class SubAgentManager:
    """
    子Agent管理器 - 管理和编排多个子Agent。
    受 LangGraph 的 multi-agent 模式启发，支持:
    - Supervisor 模式: 一个主Agent协调多个子Agent
    - 顺序链模式: 子Agent按顺序执行
    - 并行模式: 多个子Agent同时执行
    """

    def __init__(self):
        """初始化管理器。"""
        self.graphs: Dict[str, AgentGraph] = {}
        self._registered_agents: Dict[str, Dict[str, Any]] = {}
        logger.info("SubAgentManager initialized")

    def register_agent(self, name: str, handler: AgentNodeFunc,
                       description: str = "", capabilities: Optional[List[str]] = None):
        """注册一个子Agent。"""
        self._registered_agents[name] = {
            "name": name,
            "handler": handler,
            "description": description,
            "capabilities": capabilities or [],
            "registered_at": time.time()
        }
        logger.info(f"Registered sub-agent: {name}")

    def create_graph(self, name: str, description: str = "") -> AgentGraph:
        """创建新的Agent执行图。"""
        graph = AgentGraph(name=name, description=description)
        self.graphs[name] = graph
        return graph

    def get_graph(self, name: str) -> Optional[AgentGraph]:
        """获取已创建的图。"""
        return self.graphs.get(name)

    async def run_sequential(self, agent_names: List[str],
                              initial_state: Optional[AgentState] = None) -> AgentState:
        """顺序执行多个子Agent。"""
        state = initial_state or AgentState()

        for agent_name in agent_names:
            agent_info = self._registered_agents.get(agent_name)
            if not agent_info:
                logger.warning(f"Sub-agent '{agent_name}' not found, skipping")
                state.errors[agent_name] = "Agent未注册"
                continue

            try:
                logger.info(f"Running sequential sub-agent: {agent_name}")
                state = await agent_info['handler'](state)
            except Exception as e:
                logger.error(f"Sub-agent '{agent_name}' failed: {e}")
                state.errors[agent_name] = str(e)

        return state

    async def run_parallel(self, agent_names: List[str],
                            initial_state: Optional[AgentState] = None,
                            timeout: float = 120.0) -> AgentState:
        """
        并行执行多个子Agent。
        每个Agent接收状态的深拷贝，最后合并结果。
        """
        import copy

        state = initial_state or AgentState()
        tasks = []

        for agent_name in agent_names:
            agent_info = self._registered_agents.get(agent_name)
            if not agent_info:
                state.errors[agent_name] = "Agent未注册"
                continue
            # 每个Agent获取独立的状态深拷贝，避免并行执行时的数据竞争
            agent_state = AgentState(
                messages=copy.deepcopy(state.messages),
                context=copy.deepcopy(state.context),
                results=copy.deepcopy(state.results),
                metadata=copy.deepcopy(state.metadata)
            )
            # 记录每个子代理的初始消息数，用于后续增量合并
            initial_message_count = len(agent_state.messages)
            tasks.append((agent_name, agent_info['handler'](agent_state), initial_message_count))

        if tasks:
            try:
                results = await asyncio.wait_for(
                    asyncio.gather(*[t[1] for t in tasks], return_exceptions=True),
                    timeout=timeout
                )

                for (agent_name, _, initial_msg_count), result in zip(tasks, results):
                    if isinstance(result, Exception):
                        state.errors[agent_name] = str(result)
                        logger.error(f"Parallel sub-agent '{agent_name}' failed: {result}")
                    elif isinstance(result, AgentState):
                        # 合并结果：仅追加子代理新增的消息
                        state.results[agent_name] = result.results
                        new_messages = result.messages[initial_msg_count:]
                        state.messages.extend(new_messages)
                        # 合并子代理产生的错误
                        for key, value in result.errors.items():
                            state.errors[f"{agent_name}.{key}"] = value
                    else:
                        state.results[agent_name] = result
            except asyncio.TimeoutError:
                logger.warning(f"Parallel execution timed out after {timeout}s")
                state.errors['_parallel'] = f"并行执行超时 ({timeout}秒)"

        return state

    def get_registered_agents(self) -> List[Dict[str, Any]]:
        """获取所有已注册的子Agent信息。"""
        return [
            {
                "name": info["name"],
                "description": info["description"],
                "capabilities": info["capabilities"],
                "registered_at": info["registered_at"]
            }
            for info in self._registered_agents.values()
        ]

    def get_graphs_info(self) -> List[Dict[str, Any]]:
        """获取所有图的信息。"""
        return [graph.get_graph_info() for graph in self.graphs.values()]

    async def run_conversation(
        self,
        agent_names: list[str],
        initial_message: str,
        max_turns: int = 10,
        timeout: float = 300.0,
    ) -> AgentState:
        """
        多 Agent 多轮对话模式。
        各 Agent 轮流发言，每个 Agent 可见完整对话历史。
        由第一个 Agent 开始，后面轮流响应。

        Args:
            agent_names: 参与对话的 Agent 名称列表
            initial_message: 初始消息
            max_turns: 最大对话轮数（防止无限循环）
            timeout: 超时秒数

        Returns:
            包含完整对话历史的 AgentState
        """
        state = AgentState()
        state.add_message("user", initial_message)
        state.context["max_turns"] = max_turns
        state.context["conversation_mode"] = "multi_turn"

        turn_count = 0
        for turn in range(max_turns):
            agent_name = agent_names[turn % len(agent_names)]
            agent_info = self._registered_agents.get(agent_name)
            if not agent_info:
                state.add_message("system", f"[{agent_name} 未注册，跳过]")
                continue

            # 构建此 Agent 的提示词（包含对话历史摘要）
            history_text = "\n".join([
                f"{m['role']}: {str(m['content'])[:500]}"
                for m in state.messages[-20:]  # 最近 20 条消息
            ])
            state.context["conversation_history"] = history_text
            state.context["current_agent"] = agent_name

            try:
                async with asyncio.timeout(timeout):
                    result_state = await agent_info["handler"](state)
                if isinstance(result_state, AgentState):
                    state = result_state
                turn_count += 1
            except asyncio.TimeoutError:
                state.add_message("system", f"[{agent_name} 超时，对话终止]")
                break
            except Exception as e:
                state.errors[agent_name] = str(e)
                logger.bind(event="conversation_error", agent=agent_name).warning(str(e))
                break

        state.metadata["total_turns"] = turn_count
        state.metadata["conversation_complete"] = turn_count < max_turns
        return state

    async def debate(
        self,
        agent_names: list[str],
        topic: str,
        rounds: int = 3,
        timeout: float = 600.0,
    ) -> AgentState:
        """
        多 Agent 辩论模式。
        各 Agent 各自提出论点，最后协商合成共识意见。

        Args:
            agent_names: 参与辩论的 Agent 名称列表
            topic: 辩论主题
            rounds: 辩论轮数
            timeout: 总超时秒数

        Returns:
            包含所有论点和共识意见的 AgentState
        """
        state = AgentState()
        state.context["debate_topic"] = topic
        state.context["rounds"] = rounds
        state.context["debate_mode"] = True

        # 初始化辩论
        state.add_message("system", f"辩论主题: {topic}\n参与者: {', '.join(agent_names)}\n共 {rounds} 轮")

        try:
            async with asyncio.timeout(timeout):
                for round_num in range(1, rounds + 1):
                    state.add_message("system", f"--- 第 {round_num}/{rounds} 轮 ---")
                    round_results = {}

                    for agent_name in agent_names:
                        agent_info = self._registered_agents.get(agent_name)
                        if not agent_info:
                            continue
                        # 每个 Agent 在辩论轮次中独立发言
                        debate_prompt = (
                            f"辩论主题: {topic}\n"
                            f"当前轮次: 第 {round_num}/{rounds} 轮\n"
                            f"请提出您的论点或回应之前的观点。"
                        )
                        state.add_message("user", debate_prompt)
                        # 记录当前消息数，用于增量合并
                        msg_count_before = len(state.messages)
                        try:
                            result_state = await agent_info["handler"](state)
                            if isinstance(result_state, AgentState):
                                round_results[agent_name] = result_state.results
                                # 仅追加子代理新增的消息，避免重复
                                new_messages = result_state.messages[msg_count_before:]
                                state.messages.extend(new_messages)
                        except Exception as e:
                            logger.warning(f"辩论中 Agent {agent_name} 错误: {str(e)}")

                    state.results[f"round_{round_num}"] = round_results

                # 最后一轮：合成共识
                state.add_message("system", "请基于以上辩论内容，总结各方观点并提出共识建议。")
                if agent_names:
                    first_agent = self._registered_agents.get(agent_names[0])
                    if first_agent:
                        try:
                            consensus_state = await first_agent["handler"](state)
                            if isinstance(consensus_state, AgentState):
                                state.results["consensus"] = consensus_state.results
                        except Exception as e:
                            state.results["consensus"] = {"error": str(e)}

        except asyncio.TimeoutError:
            state.add_message("system", "[辩论超时]")
            state.errors["_debate"] = "辩论超时"

        state.metadata["debate_complete"] = True
        return state


# ── SubagentOrchestrator: 委派-收集-合并编排器 ──────────────────────


# 子代理执行函数类型：接收任务和工具白名单，返回结果
SubagentExecutorFunc = Callable[[SubagentTask], Awaitable[SubagentResult]]


class SubagentOrchestrator:
    """
    Subagent 编排器（参考文章 4.1 基本模式 + 5.2 资源限制与超时）。

    核心职责:
      1. 并行委派多个 SubagentTask（带信号量限流）
      2. 强制工具白名单过滤
      3. 软/硬超时控制（软超时给一轮收尾，硬超时强制终止）
      4. 资源限制校验（轮数/token/工具调用次数/输出长度）
      5. 生命周期状态机管理
      6. Level 2 隔离时集成 WorktreeManager

    使用方式:
        orchestrator = SubagentOrchestrator(max_parallel=4)
        tasks = [
            SubagentTask(task_id="t1", instruction="搜索文档", context_snippet="...",
                         allowed_tools=["search"], isolation_level=IsolationLevel.CONTEXT),
            SubagentTask(task_id="t2", instruction="审查代码", context_snippet="...",
                         allowed_tools=["read_file"], isolation_level=IsolationLevel.PROCESS),
        ]
        results = await orchestrator.delegate_all(tasks, executor=my_executor_func)
        merged = merge_results(results, ResultMergeStrategy.CONCATENATE)
    """

    def __init__(
        self,
        max_parallel: int = 4,
        default_limits: Optional[ResourceLimits] = None,
        worktree_manager: Optional[Any] = None,
    ):
        """
        初始化编排器。

        Args:
            max_parallel: 最大并行子代理数
            default_limits: 默认资源限制，未指定时使用 DEFAULT_RESOURCE_LIMITS
            worktree_manager: WorktreeManager 实例，用于 Level 2 隔离；
                              为 None 时 Level 2 降级为 Level 1
        """
        if max_parallel < 1:
            raise ValueError("max_parallel 必须 >= 1")
        self.max_parallel = max_parallel
        self.semaphore = asyncio.Semaphore(max_parallel)
        self.default_limits = default_limits or DEFAULT_RESOURCE_LIMITS
        self._worktree_manager = worktree_manager
        # 活跃子代理状态：task_id -> (lifecycle_state, asyncio.Task)
        self._active: Dict[str, tuple] = {}
        self._lock = asyncio.Lock()
        logger.info(
            f"SubagentOrchestrator initialized: max_parallel={max_parallel}"
        )

    async def delegate_all(
        self,
        tasks: Sequence[SubagentTask],
        executor: SubagentExecutorFunc,
        merge_strategy: ResultMergeStrategy = ResultMergeStrategy.CONCATENATE,
    ) -> tuple[List[SubagentResult], str]:
        """
        并行委派所有任务，收集结果并按策略合并。

        Args:
            tasks: 子代理任务列表
            executor: 执行函数，接收 SubagentTask 返回 SubagentResult
            merge_strategy: 结果合并策略

        Returns:
            (结果列表, 合并后的文本)
        """
        if not tasks:
            return [], ""

        async def run_one(task: SubagentTask) -> SubagentResult:
            async with self.semaphore:
                return await self._execute_subagent(task, executor)

        results = await asyncio.gather(
            *[run_one(t) for t in tasks], return_exceptions=True
        )

        # 将异常转换为失败结果
        normalized: List[SubagentResult] = []
        for task, result in zip(tasks, results):
            if isinstance(result, SubagentResult):
                normalized.append(result)
            elif isinstance(result, Exception):
                normalized.append(
                    SubagentResult(
                        task_id=task.task_id,
                        success=False,
                        output="",
                        error=f"编排异常: {result}",
                        lifecycle_state=SubagentLifecycleState.ERROR,
                    )
                )
            else:
                normalized.append(
                    SubagentResult(
                        task_id=task.task_id,
                        success=False,
                        output="",
                        error=f"未知返回类型: {type(result)}",
                        lifecycle_state=SubagentLifecycleState.ERROR,
                    )
                )

        merged_text = merge_results(normalized, merge_strategy)
        return normalized, merged_text

    async def delegate_one(
        self,
        task: SubagentTask,
        executor: SubagentExecutorFunc,
    ) -> SubagentResult:
        """委派单个子代理任务。"""
        async with self.semaphore:
            return await self._execute_subagent(task, executor)

    async def cancel(self, task_id: str) -> bool:
        """
        取消指定子代理任务（参考文章 5.1 状态机 - Cancelled）。

        Returns:
            True 表示已发送取消信号，False 表示任务不存在或已终态
        """
        async with self._lock:
            entry = self._active.get(task_id)
            if entry is None:
                return False
            lifecycle_state, bg_task = entry
            if lifecycle_state in (
                SubagentLifecycleState.COMPLETED,
                SubagentLifecycleState.TIMEOUT,
                SubagentLifecycleState.ERROR,
                SubagentLifecycleState.CANCELLED,
                SubagentLifecycleState.TERMINATED,
            ):
                return False
            bg_task.cancel()
            await self._transition(task_id, SubagentLifecycleState.CANCELLED)
        logger.bind(
            module="subagent_orchestrator", task_id=task_id
        ).info(f"子代理已取消: {task_id}")
        return True

    def get_active_tasks(self) -> Dict[str, str]:
        """获取当前活跃子代理的 task_id -> lifecycle_state 映射。"""
        return {
            tid: entry[0].value for tid, entry in self._active.items()
            if entry[0] not in (
                SubagentLifecycleState.TERMINATED,
            )
        }

    # ── 内部方法 ──────────────────────────────────────────────

    async def _execute_subagent(
        self,
        task: SubagentTask,
        executor: SubagentExecutorFunc,
    ) -> SubagentResult:
        """
        执行单个子代理（参考文章 4.1 + 5.2）。

        流程:
          1. 创建隔离上下文（Level 1/2/3）
          2. 过滤工具白名单
          3. 软/硬超时控制
          4. 资源限制校验
          5. 生命周期状态机管理
          6. 结果长度截断
        """
        bg_task = asyncio.current_task()
        async with self._lock:
            self._active[task.task_id] = (
                SubagentLifecycleState.CREATED,
                bg_task,
            )

        start_time = time.time()
        worktree_info = None

        try:
            # 1. 创建隔离上下文
            await self._transition(task.task_id, SubagentLifecycleState.RUNNING)
            isolation_context = await self._create_isolated_context(task)
            if isinstance(isolation_context, dict) and isolation_context.get("worktree"):
                worktree_info = isolation_context["worktree"]

            # 2. 过滤工具白名单（执行器内部应基于此过滤）
            filtered_tools = self._filter_tools(task.allowed_tools)

            # 3. 执行（带硬超时）
            await self._transition(task.task_id, SubagentLifecycleState.WAITING)
            limits = task.resource_limits

            try:
                raw_output = await asyncio.wait_for(
                    executor(task),
                    timeout=limits.max_time_seconds,
                )
            except asyncio.TimeoutError:
                # 硬超时：强制终止
                await self._transition(task.task_id, SubagentLifecycleState.TIMEOUT)
                elapsed = time.time() - start_time
                return SubagentResult(
                    task_id=task.task_id,
                    success=False,
                    output="",
                    error=f"硬超时 ({limits.max_time_seconds}s)",
                    elapsed_seconds=elapsed,
                    lifecycle_state=SubagentLifecycleState.TIMEOUT,
                )

            # 4. 校验返回类型并应用资源限制
            if not isinstance(raw_output, SubagentResult):
                # 执行器返回原始字符串时包装为结果
                output_str = str(raw_output) if raw_output is not None else ""
                raw_output = SubagentResult(
                    task_id=task.task_id,
                    success=True,
                    output=output_str,
                    elapsed_seconds=time.time() - start_time,
                )

            # 5. 结果长度截断（参考文章 6.3 安全性检查清单）
            if len(raw_output.output) > limits.max_output_tokens:
                original_length = len(raw_output.output)
                raw_output.output = (
                    raw_output.output[: limits.max_output_tokens]
                    + f"\n[结果已截断，原始长度 {original_length} 字符]"
                )
                raw_output.metadata["truncated"] = True

            # 6. 补充耗时与状态
            raw_output.elapsed_seconds = time.time() - start_time
            if raw_output.success:
                await self._transition(
                    task.task_id, SubagentLifecycleState.COMPLETED
                )
            else:
                await self._transition(
                    task.task_id, SubagentLifecycleState.ERROR
                )

            return raw_output

        except asyncio.CancelledError:
            await self._transition(task.task_id, SubagentLifecycleState.CANCELLED)
            elapsed = time.time() - start_time
            return SubagentResult(
                task_id=task.task_id,
                success=False,
                output="",
                error="子代理被取消",
                elapsed_seconds=elapsed,
                lifecycle_state=SubagentLifecycleState.CANCELLED,
            )
        except Exception as exc:
            await self._transition(task.task_id, SubagentLifecycleState.ERROR)
            elapsed = time.time() - start_time
            logger.bind(
                module="subagent_orchestrator",
                task_id=task.task_id,
                error=str(exc),
            ).error(f"子代理执行异常: {task.task_id}")
            return SubagentResult(
                task_id=task.task_id,
                success=False,
                output="",
                error=f"执行异常: {exc}",
                elapsed_seconds=elapsed,
                lifecycle_state=SubagentLifecycleState.ERROR,
            )
        finally:
            # 清理 Level 2 隔离资源
            if worktree_info and self._worktree_manager:
                try:
                    await self._worktree_manager.cleanup_worktree(task.task_id)
                except Exception as cleanup_exc:
                    logger.bind(
                        module="subagent_orchestrator",
                        task_id=task.task_id,
                    ).warning(f"worktree 清理失败: {cleanup_exc}")

            # 转入 TERMINATED 并移除活跃记录
            async with self._lock:
                current_state = self._active.get(task.task_id, (None, None))[0]
                if current_state and validate_lifecycle_transition(
                    current_state.value, SubagentLifecycleState.TERMINATED.value
                ):
                    self._active[task.task_id] = (
                        SubagentLifecycleState.TERMINATED,
                        bg_task,
                    )
                # 延迟移除，允许 get_active_tasks 观察终态
                # 实际清理在下次查询时惰性执行

    async def _create_isolated_context(
        self, task: SubagentTask
    ) -> Dict[str, Any]:
        """
        根据隔离级别创建隔离上下文（参考文章 3.1 三级隔离深度）。

        - Level 1 (CONTEXT): 仅返回上下文片段，无额外资源
        - Level 2 (PROCESS): 调用 WorktreeManager 创建 git worktree
        - Level 3 (SANDBOX): 预留 Docker/VM 隔离接口，当前降级为 Level 2
        """
        context: Dict[str, Any] = {
            "isolation_level": task.isolation_level,
            "context_snippet": task.context_snippet,
        }

        if task.isolation_level == IsolationLevel.CONTEXT:
            return context

        if task.isolation_level in (IsolationLevel.PROCESS, IsolationLevel.SANDBOX):
            if task.isolation_level == IsolationLevel.SANDBOX:
                logger.bind(
                    module="subagent_orchestrator",
                    task_id=task.task_id,
                ).warning("Level 3 沙箱隔离暂未实现，降级为 Level 2 进程隔离")

            if self._worktree_manager is None:
                logger.bind(
                    module="subagent_orchestrator",
                    task_id=task.task_id,
                ).warning(
                    "未提供 WorktreeManager，Level 2 隔离降级为 Level 1 上下文隔离"
                )
                return context

            worktree_info = await self._worktree_manager.create_worktree(
                task.task_id
            )
            if worktree_info:
                context["worktree"] = worktree_info
                context["work_dir"] = worktree_info.path
            return context

        return context

    def _filter_tools(self, allowed_tools: List[str]) -> List[str]:
        """
        工具白名单过滤（参考文章 6.3 安全性检查清单）。

        确保子代理只能访问被授予的工具子集。
        """
        if not allowed_tools:
            return []
        # 去重并保持顺序
        seen: set = set()
        filtered: List[str] = []
        for tool in allowed_tools:
            normalized = str(tool).strip()
            if normalized and normalized not in seen:
                seen.add(normalized)
                filtered.append(normalized)
        return filtered

    async def _transition(
        self, task_id: str, new_state: SubagentLifecycleState
    ) -> None:
        """生命周期状态转换（带合法性校验）。"""
        async with self._lock:
            entry = self._active.get(task_id)
            current_state = entry[0] if entry else SubagentLifecycleState.CREATED

            if not validate_lifecycle_transition(
                current_state.value, new_state.value
            ):
                logger.bind(
                    module="subagent_orchestrator",
                    task_id=task_id,
                    current_state=current_state.value,
                    target_state=new_state.value,
                ).warning("非法生命周期状态转换，已忽略")
                return

            bg_task = entry[1] if entry else None
            self._active[task_id] = (new_state, bg_task)

        logger.bind(
            module="subagent_orchestrator",
            task_id=task_id,
            state=new_state.value,
        ).debug(f"子代理状态转换: {current_state.value} -> {new_state.value}")


# ── 安全性检查工具函数（参考文章 6.3 安全性检查清单） ──────────────


def validate_task_security(task: SubagentTask) -> List[str]:
    """
    对子代理任务执行安全性检查，返回问题列表（空列表表示通过）。

    检查项:
      1. 工具白名单是否最小化（不超过 10 个）
      2. 超时是否合理（不超过 600 秒）
      3. 结果长度限制是否设置（> 0）
      4. 隔离级别是否匹配任务风险
    """
    issues: List[str] = []

    if len(task.allowed_tools) > 10:
        issues.append(
            f"工具白名单过大 ({len(task.allowed_tools)} 个)，建议最小化"
        )

    if task.timeout_seconds > 600:
        issues.append(
            f"超时设置过长 ({task.timeout_seconds}s)，不应超过主 Agent 超时"
        )

    if task.resource_limits.max_output_tokens <= 0:
        issues.append("结果长度限制未设置，可能导致主上下文污染")

    # 高风险任务应使用更高隔离级别
    high_risk_keywords = ["rm ", "delete", "drop", "format", "sudo", "chmod 777"]
    instruction_lower = task.instruction.lower()
    if any(kw in instruction_lower for kw in high_risk_keywords):
        if task.isolation_level == IsolationLevel.CONTEXT:
            issues.append(
                "高风险指令建议使用 Level 2+ 隔离（当前为 Level 1 上下文隔离）"
            )

    return issues
