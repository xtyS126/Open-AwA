"""
子Agent编排系统 - 受 langchain-ai/langgraph 启发的子Agent管理和协调模块。
来源参考: https://github.com/langchain-ai/langgraph
作者: langchain-ai
许可: MIT License

本模块实现了类似 LangGraph 的状态图（StateGraph）概念，
支持将复杂任务分解为多个子Agent节点，通过状态传递实现协作。
核心概念:
  - SubAgent: 独立的执行单元，具有特定职责
  - AgentState: 在节点间传递的共享状态
  - AgentGraph: 定义节点和边的有向图，编排执行流程
"""

import asyncio
import time
import uuid
from enum import Enum
from typing import Dict, List, Any, Optional, Callable, Awaitable, Union
from dataclasses import dataclass, field
from loguru import logger


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
                AgentEdge(source=source, target=target, condition=condition)
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

        # 检查条件边
        if current_node in self.conditional_edges:
            for edge in self.conditional_edges[current_node]:
                if edge.condition:
                    result = edge.condition(state)
                    if result == edge.target or result == True:
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
        """
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

            for node_name in current_nodes:
                if node_name not in self.nodes:
                    logger.warning(f"Node '{node_name}' not found, skipping")
                    continue

                node = self.nodes[node_name]
                try:
                    state = await self._execute_node(node, state)
                except Exception as e:
                    logger.error(f"Node '{node_name}' failed: {e}")
                    # 失败时不继续后续节点
                    continue

                # 确定下一步
                if node_name not in self.finish_points:
                    successors = self._get_next_nodes(node_name, state)
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
        每个Agent接收状态的副本，最后合并结果。
        """
        state = initial_state or AgentState()
        tasks = []

        for agent_name in agent_names:
            agent_info = self._registered_agents.get(agent_name)
            if not agent_info:
                state.errors[agent_name] = "Agent未注册"
                continue
            # 每个Agent获取独立的状态副本
            agent_state = AgentState(
                messages=list(state.messages),
                context=dict(state.context),
                results=dict(state.results),
                metadata=dict(state.metadata)
            )
            tasks.append((agent_name, agent_info['handler'](agent_state)))

        if tasks:
            try:
                results = await asyncio.wait_for(
                    asyncio.gather(*[t[1] for t in tasks], return_exceptions=True),
                    timeout=timeout
                )

                for (agent_name, _), result in zip(tasks, results):
                    if isinstance(result, Exception):
                        state.errors[agent_name] = str(result)
                        logger.error(f"Parallel sub-agent '{agent_name}' failed: {result}")
                    elif isinstance(result, AgentState):
                        # 合并结果
                        state.results[agent_name] = result.results
                        state.messages.extend(result.messages[len(state.messages):])
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
