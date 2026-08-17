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
      3. 默认 Explore（只读调研代理）
    """
    explicit = str(task.metadata.get("agent_type") or "").strip()
    if explicit:
        return explicit
    agent_name = str(task.metadata.get("agent_name") or "").strip()
    if agent_name:
        return BUILTIN_TO_TASK_RUNTIME_TYPE.get(agent_name)
    return "Explore"


async def run_task_via_task_runtime(task: SubagentTask) -> Optional[SubagentResult]:
    """
    通过 task_runtime.spawn_agent 执行子代理任务（真实 LLM 子代理）。

    返回 SubagentResult 表示委派成功；返回 None 表示 task_runtime 侧不可用
    （代理类型未注册 / 非流式返回），调用方应回退到内置规则执行器。
    """
    agent_type = resolve_task_runtime_agent_type(task)
    if not agent_type or not agent_registry.get(agent_type):
        return None

    stream = await task_runtime.spawn_agent(
        agent_type=agent_type,
        prompt=task.instruction,
        description=f"Subagent 编排委派（{task.task_id}）",
        background=False,
        force_foreground=True,
        context=dict(task.metadata or {}),
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
