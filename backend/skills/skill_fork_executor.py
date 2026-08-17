"""
Skill Fork 执行器（Task 16.4 & 16.5 + Task 18 真实调度）。

为 fork 模式的技能提供 Fork 子 Agent 启动与上下文准备能力。

核心功能：
- execute_forked_skill: 桥接 task_runtime.spawn_agent(fork_mode=True) 真实调度
  Fork 子 Agent，等待完成后提取结果文本返回（Task 18 修复"假实现"）
- prepare_forked_command_context: 为 Fork 子 Agent 准备命令上下文

设计要点：
- 依赖 Task 13 的 Fork 机制（build_forked_messages、build_child_message）
- Task 15 为 facade.spawn_agent 增加 fork_mode 参数，此处直接使用该参数真实调度
- 子 Agent 完成后通过轮询会话状态 + transcript 提取结果文本
- 通过 is_fork_child=True 标志防止递归 Fork
"""

from __future__ import annotations

import asyncio
import copy
import time
from typing import Any, Dict, List, Optional

from loguru import logger

from core.task_runtime.fork import (
    build_child_message,
    build_forked_messages,
)


# Fork 子 Agent 结果等待上限与轮询间隔（秒）
_FORK_RESULT_TIMEOUT_SECONDS = 300.0
_FORK_RESULT_POLL_INTERVAL_SECONDS = 1.0


def prepare_forked_command_context(
    skill: Dict[str, Any],
    parent_context: Dict[str, Any],
) -> Dict[str, Any]:
    """
    为 Fork 子 Agent 准备命令上下文。

    算法：
    1. 深拷贝 parent_context，确保子 Agent 与父 Agent 上下文独立
    2. 添加技能相关信息（skill_id、skill_name、skill_description）
    3. 设置 is_fork_child=True 标志，防止递归 Fork
    4. 返回准备好的上下文

    Args:
        skill: 技能配置字典，需包含 name 和 description 字段。
        parent_context: 父 Agent 的上下文，包含 messages、user_id 等。

    Returns:
        准备好的 Fork 子 Agent 上下文字典。
    """
    # 深拷贝父上下文，确保子 Agent 修改不影响父 Agent
    prepared = copy.deepcopy(parent_context)

    # 注入技能相关信息
    skill_name = skill.get("name", "")
    prepared["skill_id"] = skill_name
    prepared["skill_name"] = skill_name
    prepared["skill_description"] = skill.get("description", "")

    # 设置 Fork 子 Agent 标志，防止递归 Fork
    prepared["is_fork_child"] = True

    logger.debug(
        f"已准备 Fork 子 Agent 上下文: skill={skill_name!r}, "
        f"context_keys={list(prepared.keys())}"
    )

    return prepared


def _extract_fork_result_text(
    transcript: Any,
    session: Optional[Dict[str, Any]],
) -> str:
    """从子代理 transcript 与会话记录中提取结果文本。

    优先级：transcript 中最后一条 agent_message > subagent_stop 的 summary > 会话 summary。
    """
    result_parts: List[str] = []
    if isinstance(transcript, list):
        for entry in reversed(transcript):
            if not isinstance(entry, dict):
                continue
            event = str(entry.get("event") or "").strip()
            message = str(entry.get("message") or "").strip()
            if event == "agent_message" and message:
                result_parts.append(message)
                break
        else:
            # 无 agent_message 时回退到 subagent_stop 的 summary
            for entry in reversed(transcript):
                if not isinstance(entry, dict):
                    continue
                event = str(entry.get("event") or "").strip()
                summary = str(entry.get("summary") or "").strip()
                if event == "subagent_stop" and summary:
                    result_parts.append(summary)
                    break
    if not result_parts and isinstance(session, dict):
        summary = str(session.get("summary") or "").strip()
        if summary:
            result_parts.append(summary)
    return "\n".join(result_parts)


async def _await_fork_agent_result(
    agent_id: str,
    timeout_seconds: float = _FORK_RESULT_TIMEOUT_SECONDS,
    poll_interval_seconds: float = _FORK_RESULT_POLL_INTERVAL_SECONDS,
) -> str:
    """轮询 Fork 子代理状态直到完成，返回提取的结果文本。

    fork_mode 启动的子 Agent 在后台异步执行，此处通过 task_runtime.get_agent
    轮询会话状态，完成/失败/停止后读取 transcript 提取结果文本。
    """
    if not agent_id:
        return ""

    from core.task_runtime import task_runtime

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        session = await task_runtime.get_agent(agent_id)
        if session is None:
            # 会话不存在（可能已清理），返回空结果
            return ""
        state = str(session.get("state") or "")
        if state in ("completed", "failed", "stopped"):
            transcript = await task_runtime.get_transcript(agent_id)
            result_text = _extract_fork_result_text(transcript, session)
            logger.bind(
                module="skill_fork_executor",
                agent_id=agent_id,
                state=state,
            ).debug(f"Fork 子 Agent 已结束: {agent_id} (state={state})")
            return result_text
        await asyncio.sleep(poll_interval_seconds)

    logger.bind(
        module="skill_fork_executor",
        agent_id=agent_id,
        timeout_seconds=timeout_seconds,
    ).warning(f"等待 Fork 子 Agent 结果超时: {agent_id}")
    return f"[Fork 子 Agent 等待超时: {agent_id}]"


async def execute_forked_skill(
    skill: Dict[str, Any],
    parent_context: Dict[str, Any],
) -> Dict[str, Any]:
    """
    桥接 task_runtime.spawn_agent(fork_mode=True) 真实调度 Fork 子 Agent 执行技能。

    算法（Task 18，修复"仅返回随机 task_id 的假实现"）：
    1. 调用 build_forked_messages 克隆父上下文消息
    2. 调用 build_child_message 构造子任务消息（含防递归指令）
    3. 通过 prepare_forked_command_context 准备子 Agent 上下文
    4. 调用 task_runtime.spawn_agent(fork_mode=True) 真实调度子 Agent，
       消费 fork_started 事件拿到 agent_id
    5. 轮询等待子 Agent 完成，从 transcript 提取结果文本
    6. 返回包含 task_id / result 的结果字典

    Args:
        skill: 技能配置字典，需包含 name 和 description 字段。
        parent_context: 父 Agent 的上下文，需包含 messages 列表。

    Returns:
        结果字典：{success, task_id, agent_type, result}。
        result 为子 Agent 完成后的结果文本摘要。
    """
    from core.task_runtime import task_runtime

    skill_name = skill.get("name", "unknown")
    skill_description = skill.get("description", "")
    agent_type = str(skill.get("agent_type") or "general-purpose")
    prompt = str(skill.get("prompt") or skill.get("description") or "")

    logger.info(
        f"启动 Fork 子 Agent: skill={skill_name!r}, agent_type={agent_type!r}"
    )

    # 克隆父上下文消息（字节精确深拷贝）
    forked_messages = build_forked_messages(parent_context)

    # 构造子任务首条消息（含防递归指令）
    child_message = build_child_message(skill_description)

    # 准备 Fork 子 Agent 上下文（设置 is_fork_child=True）
    child_context = prepare_forked_command_context(skill, parent_context)

    # 将克隆的消息与子任务消息注入子上下文
    forked_messages.append(child_message)
    child_context["messages"] = forked_messages

    # Task 18: 桥接 facade.spawn_agent(fork_mode=True) 真实调度
    stream = await task_runtime.spawn_agent(
        agent_type=agent_type,
        prompt=prompt,
        description=skill_description,
        context=child_context,
        fork_mode=True,
    )

    agent_id = ""
    async for event in stream:
        if isinstance(event, dict) and event.get("type") == "fork_started":
            agent_id = str(event.get("agent_id") or event.get("task_id") or "")

    logger.info(
        f"Fork 子 Agent 已调度: task_id={agent_id}, skill={skill_name!r}, "
        f"message_count={len(forked_messages)}"
    )

    # 等待子 Agent 完成并提取结果文本
    result_text = await _await_fork_agent_result(agent_id)

    return {
        "success": bool(agent_id),
        "task_id": agent_id,
        "agent_type": agent_type,
        "result": result_text,
    }
