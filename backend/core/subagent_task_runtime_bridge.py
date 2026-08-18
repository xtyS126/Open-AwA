"""
subagents 图编排与 task_runtime 的桥接层（Task 19 统一子代理系统）。

职责：
  1. 将 subagents 的委派执行（orchestrator/delegate）复用 task_runtime 的
     facade.spawn_agent 派生真实 LLM 子代理，替代纯规则"伪 Agent"内置节点。
  2. 图节点在显式请求（context.use_llm / llm_delegate）时同样委派 task_runtime。
  3. 内置规则"伪 Agent"保留为离线回退：LLM 委派不可用（代理类型未注册 /
     运行时异常）时降级到规则实现，保证无 LLM 环境下图编排仍可演示，
     且不破坏现有 API 与存量测试。

API 面关系：代理会话/任务清单/代理类型等查询见 /api/task-runtime/*，
本桥接层只负责编排层的执行委派，不新增或删除任何 HTTP 端点。
"""

from typing import Any, Dict, Optional

from loguru import logger
from collections.abc import AsyncGenerator

from core.task_runtime import task_runtime, agent_registry
from core.subagent import (
    AgentState,
    IsolationLevel,
    SubagentResult,
    SubagentTask,
    SubagentLifecycleState,
)


# 内置"伪 Agent"名称到 task_runtime 原生代理类型的映射。
# 旧图定义 / 委派请求中引用 analyzer/planner 等名称时，
# 通过该映射路由到 task_runtime 中语义相近的真实 LLM 代理类型。
BUILTIN_TO_TASK_RUNTIME_TYPE: Dict[str, str] = {
    "analyzer": "Plan",
    "planner": "Plan",
    "executor": "general-purpose",
    "reviewer": "verification",
    "code_reviewer": "verification",
    "searcher": "Explore",
    "data_analyst": "general-purpose",
}

# ── subagent.py 与 task_runtime 的语义收敛（单一映射点） ────────────
# 避免 subagent.py 的 IsolationLevel/ResourceLimits 与
# core/task_runtime/definitions.py 的 isolation_mode/max_turns/effort 各自漂移。
#
# 1) 隔离级别：subagent.py 三级 IsolationLevel -> task_runtime isolation_mode
#    - CONTEXT(1)  语义等同 isolation_mode="inherit"（共享进程/文件系统）
#    - PROCESS(2)  对应 isolation_mode="worktree"（git worktree 隔离）
#    - SANDBOX(3)  task_runtime 未实现，禁止静默降级（isolation_level_to_mode 抛 ValueError）
#
# 2) 资源限制：subagent.py 的 ResourceLimits 是"任务级运行时配额"，
#    task_runtime 的 AgentDefinition.max_turns/effort 是"代理类型级静态配置"。
#    - ResourceLimits.max_turns        <-> AgentDefinition.max_turns（轮次上限）
#    - ResourceLimits.max_tokens 等其余字段 在 task_runtime 无对应（由 provider/model 或编排层超时控制）
#    - AgentDefinition.effort          无任务级等价（仅代理类型级努力程度）
#    桥接委派时以 AgentDefinition 为准（其内置 max_turns 更严格，如 verification=10/guide=5），
#    不把 ResourceLimits.max_turns 的默认值强制覆写过去，避免放宽内置限制。

ISOLATION_LEVEL_TO_MODE: Dict[IsolationLevel, str] = {
    IsolationLevel.CONTEXT: "inherit",
    IsolationLevel.PROCESS: "worktree",
}


def isolation_level_to_mode(level: IsolationLevel) -> Optional[str]:
    """
    将 subagent.py 的隔离级别转换为 task_runtime 的 isolation_mode 覆写值。

    - CONTEXT：语义等同 isolation_mode="inherit"，但桥接委派时返回 None，
      表示不覆写 AgentDefinition 自身的 isolation_mode，避免把 fresh 等内置语义误覆盖。
    - PROCESS：返回 "worktree"。
    - SANDBOX：task_runtime 未实现，抛 ValueError，禁止静默降级。

    Args:
        level: subagent.py 的 IsolationLevel 枚举

    Returns:
        用于 spawn_agent(isolation=...) 的覆写值；None 表示不覆写

    Raises:
        ValueError: SANDBOX 等未实现的隔离级别
    """
    if level == IsolationLevel.SANDBOX:
        raise ValueError(
            f"IsolationLevel.SANDBOX 在 task_runtime 未实现，禁止静默降级: {level}"
        )
    if level == IsolationLevel.CONTEXT:
        return None
    return ISOLATION_LEVEL_TO_MODE.get(level)


async def consume_spawn_stream(stream: Any) -> tuple[str, str, str]:
    """
    消费 task_runtime.spawn_agent 前台事件流，提取执行终态与摘要。

    返回:
        (state, summary, agent_id)；
        事件流异常时按 failed 处理，保证编排层总能拿到可解析的结果。
    """
    state = "failed"
    summary = ""
    agent_id = ""
    try:
        async for event in stream:
            if not isinstance(event, dict):
                continue
            event_type = event.get("type")
            if event_type == "subagent_stop":
                state = str(event.get("state") or "failed")
                summary = str(event.get("summary") or "")
                agent_id = str(event.get("agent_id") or agent_id)
            elif event_type == "error":
                state = "failed"
                summary = str(event.get("error") or summary)
            elif event_type in ("subagent_start", "fork_started"):
                agent_id = str(event.get("agent_id") or agent_id)
    except Exception as exc:
        # 消费边界：流异常时按失败处理并记录日志，禁止抛出影响编排器
        logger.bind(module="subagents", event="spawn_stream").warning(
            f"task_runtime 事件流消费异常: {exc}"
        )
        state = "failed"
    return state, summary, agent_id


def resolve_task_runtime_agent_type(task: SubagentTask) -> Optional[str]:
    """
    解析任务对应的 task_runtime 代理类型。

    优先级:
      1. task.metadata.agent_type 显式指定（直接使用 task_runtime 原生类型名）
      2. task.metadata.agent_name 按内置映射表转换
      3. task.metadata.agent_name 本身就是已注册的 task_runtime 原生类型
      4. 默认 Explore（只读调研代理）
    """
    explicit = str(task.metadata.get("agent_type") or "").strip()
    if explicit:
        return explicit
    agent_name = str(task.metadata.get("agent_name") or "").strip()
    if agent_name:
        mapped = BUILTIN_TO_TASK_RUNTIME_TYPE.get(agent_name)
        if mapped:
            return mapped
        # agent_name 本身就是 task_runtime 原生类型（如 verification/Explore）时直接使用
        if agent_registry.get(agent_name):
            return agent_name
        return None
    return "Explore"


async def run_task_via_task_runtime(task: SubagentTask) -> Optional[SubagentResult]:
    """
    通过 task_runtime.spawn_agent 执行子代理任务（真实 LLM 子代理）。

    返回 SubagentResult 表示委派成功；返回 None 表示 task_runtime 侧不可用
    （代理类型未注册 / 非流式返回），调用方应回退到内置规则执行器。

    Raises:
        ValueError: 任务请求了 task_runtime 未实现的隔离级别（如 SANDBOX）
    """
    agent_type = resolve_task_runtime_agent_type(task)
    if not agent_type or not agent_registry.get(agent_type):
        return None

    # 隔离级别经单一映射转换为 isolation_mode 覆写；CONTEXT 返回 None 表示不覆写
    isolation = isolation_level_to_mode(task.isolation_level)

    # 委派上下文：显式元数据 + 上下文片段，透传给真实 LLM 子代理
    spawn_context = dict(task.metadata or {})
    if task.context_snippet:
        spawn_context.setdefault("context_snippet", task.context_snippet)
    if task.allowed_tools:
        spawn_context.setdefault("allowed_tools", list(task.allowed_tools))

    stream = await task_runtime.spawn_agent(
        agent_type=agent_type,
        prompt=task.instruction,
        description=f"Subagent 编排委派（{task.task_id}）",
        background=False,
        force_foreground=True,
        isolation=isolation,
        context=spawn_context,
    )
    if not isinstance(stream, AsyncGenerator):
        # 后台模式/未知类型错误：无法同步取回结果，交由调用方回退
        return None

    run_state, summary, agent_id = await consume_spawn_stream(stream)
    success = run_state == "completed"
    return SubagentResult(
        task_id=task.task_id,
        success=success,
        output=summary or ("任务完成" if success else ""),
        metadata={
            "agent_type": agent_type,
            "agent_id": agent_id,
            "runtime": "task_runtime",
        },
        lifecycle_state=(
            SubagentLifecycleState.COMPLETED if success else SubagentLifecycleState.ERROR
        ),
    )


async def run_graph_node_via_task_runtime(
    agent_name: str, state: AgentState
) -> AgentState:
    """
    图节点经 task_runtime 执行：以节点指令为 prompt 派生真实 LLM 子代理。

    执行结果写入 state.results[agent_name]，供后续节点与响应体消费。
    代理类型未注册或 spawn_agent 非流式返回时抛出异常，由包装器回退规则实现。
    """
    agent_type = BUILTIN_TO_TASK_RUNTIME_TYPE.get(agent_name, agent_name)
    if not agent_registry.get(agent_type):
        raise RuntimeError(f"task_runtime 未注册代理类型: {agent_type}")

    user_message = str(
        state.context.get("user_message")
        or state.context.get("query")
        or state.context.get("code")
        or state.context.get("prompt")
        or ""
    )
    stream = await task_runtime.spawn_agent(
        agent_type=agent_type,
        prompt=user_message or f"请以 {agent_name} 的身份完成节点任务",
        description=f"图节点执行: {agent_name}",
        background=False,
        force_foreground=True,
        context=dict(state.context),
    )
    if not isinstance(stream, AsyncGenerator):
        raise RuntimeError(f"spawn_agent 返回非流式结果: {stream}")

    run_state, summary, agent_id = await consume_spawn_stream(stream)
    node_result = {
        "summary": summary,
        "agent_id": agent_id,
        "agent_type": agent_type,
        "runtime": "task_runtime",
        "approved": run_state == "completed",
        "task_runtime_state": run_state,
    }
    state.set_result(agent_name, node_result)
    state.add_message(
        "system", f"{agent_name} 经 task_runtime 执行完成: {summary[:200]}"
    )
    return state


def make_llm_aware_handler(agent_name: str, fallback: Any) -> Any:
    """
    构造图节点处理器：state.context.use_llm（或 llm_delegate）为 True 时
    优先委派 task_runtime 派生真实 LLM 子代理；否则或委派失败时
    回退内置规则实现，保证离线可用与存量行为不变。
    """
    async def handler(state: AgentState) -> AgentState:
        use_llm = bool(
            state.context.get("use_llm") or state.context.get("llm_delegate")
        )
        if not use_llm:
            return await fallback(state)
        try:
            return await run_graph_node_via_task_runtime(agent_name, state)
        except Exception as exc:
            # 委派边界：LLM 委派失败回退规则实现，保证图执行不中断
            logger.bind(module="subagents", node=agent_name).warning(
                f"图节点 {agent_name} task_runtime 委派失败，回退规则实现: {exc}"
            )
            return await fallback(state)

    handler.__name__ = f"llm_aware_{agent_name}"
    return handler
