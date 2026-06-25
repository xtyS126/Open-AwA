"""
Skill Fork 执行器（Task 16.4 & 16.5）。

为 fork 模式的技能提供 Fork 子 Agent 启动与上下文准备能力。

核心功能：
- execute_forked_skill: 启动 Fork 子 Agent 执行技能，返回 task_id（异步执行）
- prepare_forked_command_context: 为 Fork 子 Agent 准备命令上下文

设计要点：
- 依赖 Task 13 的 Fork 机制（build_forked_messages、build_child_message）
- Fork 启动后立即返回 task_id，不阻塞等待子 Agent 完成
- 子 Agent 结果通过 task-notification 异步推送
- 通过 is_fork_child=True 标志防止递归 Fork
"""

from __future__ import annotations

import copy
import uuid
from typing import Any, Dict

from loguru import logger

from core.task_runtime.fork import (
    build_child_message,
    build_forked_messages,
)


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


def execute_forked_skill(
    skill: Dict[str, Any],
    parent_context: Dict[str, Any],
) -> str:
    """
    启动 Fork 子 Agent 执行技能。

    算法：
    1. 生成唯一 task_id 标识本次 Fork 任务
    2. 调用 build_forked_messages 克隆父上下文消息
    3. 调用 build_child_message 构造子任务消息（含防递归指令）
    4. 通过 prepare_forked_command_context 准备子 Agent 上下文
    5. 返回 task_id（异步执行，不等待完成）

    注意：当前实现仅完成上下文准备与消息构造，返回 task_id。
    实际的子 Agent 调度与执行由上层 task_runtime 负责调度，
    结果通过 task-notification 异步推送。

    Args:
        skill: 技能配置字典，需包含 name 和 description 字段。
        parent_context: 父 Agent 的上下文，需包含 messages 列表。

    Returns:
        task_id 字符串，用于标识本次 Fork 任务。
    """
    # 生成唯一 task_id
    task_id = str(uuid.uuid4())

    skill_name = skill.get("name", "unknown")
    skill_description = skill.get("description", "")

    logger.info(
        f"启动 Fork 子 Agent: task_id={task_id}, skill={skill_name!r}"
    )

    # 克隆父上下文消息（字节精确深拷贝）
    forked_messages = build_forked_messages(parent_context)

    # 构造子任务首条消息（含防递归指令）
    child_message = build_child_message(skill_description)

    # 准备 Fork 子 Agent 上下文（设置 is_fork_child=True）
    child_context = prepare_forked_command_context(skill, parent_context)

    # 将克隆的消息与子任务消息注入子上下文
    # 子任务消息追加到克隆消息末尾，作为子 Agent 的首条 user 指令
    forked_messages.append(child_message)
    child_context["messages"] = forked_messages

    logger.info(
        f"Fork 子 Agent 上下文准备完成: task_id={task_id}, "
        f"skill={skill_name!r}, message_count={len(forked_messages)}"
    )

    # 注意：实际的子 Agent 调度由上层 task_runtime 负责
    # 此处仅返回 task_id，调用方通过 task_id 关联异步结果
    return task_id
