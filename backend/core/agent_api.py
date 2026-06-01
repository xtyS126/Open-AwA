"""
Agent 协作 API — 为 Agent 间通信提供命名接口。
封装 chat_with_agent 和 spawn_subagent 等高级功能，
基于已有的 TaskRuntimeFacade 和 SubAgentManager 基础设施。
"""
from typing import Any, AsyncIterator, Optional
from dataclasses import dataclass, field

from loguru import logger


@dataclass
class AgentResponse:
    """Agent 对话响应。"""
    agent_id: str
    message: str
    tool_calls: list[dict] = field(default_factory=list)
    execution_meta: dict = field(default_factory=dict)
    success: bool = True
    error: Optional[str] = None


@dataclass
class SubagentResult:
    """子 Agent 执行结果。"""
    subagent_id: str
    status: str  # running/completed/failed
    result: Any = None
    error: Optional[str] = None


async def chat_with_agent(
    agent_id: str,
    message: str,
    workspace_id: str = "default",
    session_id: Optional[str] = None,
    context: Optional[dict] = None,
    **kwargs,
) -> AgentResponse:
    """
    向指定 Agent 发送消息并获取响应。
    封装了 agent 的完整处理流水线 (comprehension → planner → executor → feedback)。

    Args:
        agent_id: 目标 Agent ID
        message: 发送的消息内容
        workspace_id: 工作区 ID
        session_id: 会话 ID（可选，自动创建）
        context: 额外上下文参数

    Returns:
        AgentResponse 包含响应消息和执行元数据
    """
    try:
        from core.agent import AIAgent

        agent_ctx = context.copy() if context else {}
        agent_ctx["workspace_id"] = workspace_id
        if session_id:
            agent_ctx["session_id"] = session_id
        else:
            import uuid
            agent_ctx["session_id"] = f"agent_chat_{uuid.uuid4().hex[:12]}"

        agent = AIAgent()
        result = await agent.process(
            user_message=message,
            context=agent_ctx,
        )

        return AgentResponse(
            agent_id=agent_id,
            message=result.get("response", ""),
            tool_calls=result.get("tool_calls", []),
            execution_meta=result.get("execution_meta", {}),
            success=result.get("success", True),
        )
    except Exception as e:
        logger.bind(event="chat_with_agent_error", agent_id=agent_id).error(f"Agent 通信失败: {str(e)}")
        return AgentResponse(
            agent_id=agent_id,
            message="",
            success=False,
            error=str(e),
        )


async def chat_with_agent_stream(
    agent_id: str,
    message: str,
    workspace_id: str = "default",
    context: Optional[dict] = None,
    **kwargs,
) -> AsyncIterator[dict]:
    """
    向 Agent 发送消息并以流式获取响应。
    适用于需要渐进式输出的场景。

    Yields:
        流式事件字典 (chunk/status/plan/result/task/tool/usage)
    """
    try:
        from core.agent import AIAgent
        import uuid

        agent_ctx = context.copy() if context else {}
        agent_ctx["workspace_id"] = workspace_id
        agent_ctx["session_id"] = f"agent_chat_{uuid.uuid4().hex[:12]}"

        agent = AIAgent()
        async for event in agent.process_stream(
            user_message=message,
            context=agent_ctx,
        ):
            yield event

    except Exception as e:
        logger.bind(event="chat_with_agent_stream_error").error(str(e))
        yield {"type": "error", "message": str(e)}


async def spawn_subagent(
    agent_type: str,
    task: str,
    parent_session_id: str,
    workspace_id: str = "default",
    isolation_level: str = "process",
    **kwargs,
) -> SubagentResult:
    """
    派生子 Agent 执行独立任务。
    基于 TaskRuntimeFacade 的子 Agent 管理能力。

    Args:
        agent_type: 子 Agent 类型 (e.g. "code_reviewer", "tester", "researcher")
        task: 子 Agent 要执行的任务描述
        parent_session_id: 父会话 ID
        workspace_id: 工作区 ID
        isolation_level: 隔离级别 (process/worktree/none)

    Returns:
        SubagentResult 包含执行状态和结果
    """
    try:
        from core.task_runtime.facade import TaskRuntimeFacade
        import uuid

        subagent_id = kwargs.get("subagent_id") or f"subagent_{uuid.uuid4().hex[:8]}"
        facade = TaskRuntimeFacade()

        result = await facade.spawn_agent(
            agent_type=agent_type,
            prompt=task,
            background=isolation_level == "background",
            parent_session_id=parent_session_id,
        )

        return SubagentResult(
            subagent_id=subagent_id,
            status="running" if result else "failed",
            result=result,
        )
    except Exception as e:
        logger.bind(event="spawn_subagent_error", agent_type=agent_type).error(str(e))
        return SubagentResult(
            subagent_id=kwargs.get("subagent_id", ""),
            status="failed",
            error=str(e),
        )


async def get_subagent_result(subagent_id: str) -> SubagentResult:
    """
    获取子 Agent 的执行结果。

    Args:
        subagent_id: 子 Agent ID

    Returns:
        SubagentResult 包含最终状态和结果
    """
    try:
        from core.task_runtime.facade import TaskRuntimeFacade
        facade = TaskRuntimeFacade()
        status = await facade.get_agent_status(subagent_id)

        if not status:
            return SubagentResult(subagent_id=subagent_id, status="unknown", error="子 Agent 不存在")

        return SubagentResult(
            subagent_id=subagent_id,
            status=status.get("state", "unknown"),
            result=status.get("result"),
            error=status.get("error"),
        )
    except Exception as e:
        return SubagentResult(subagent_id=subagent_id, status="error", error=str(e))


async def stop_subagent(subagent_id: str) -> bool:
    """
    停止正在运行的子 Agent。

    Args:
        subagent_id: 子 Agent ID

    Returns:
        是否成功停止
    """
    try:
        from core.task_runtime.facade import TaskRuntimeFacade
        facade = TaskRuntimeFacade()
        await facade.stop_run(subagent_id)
        return True
    except Exception as e:
        logger.warning(f"停止子 Agent 失败: {str(e)}")
        return False
