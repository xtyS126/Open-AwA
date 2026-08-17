"""
Fork 机制上下文克隆模块。

提供子 Agent 继承父 Agent 完整消息上下文的能力，同时通过防递归检测
阻止 Fork 子 Agent 再次发起 Fork，避免无限递归。

核心概念：
- Fork 子 Agent 通过 `build_forked_messages` 字节精确克隆父上下文消息，
  并在末尾追加 `FORK_PLACEHOLDER_RESULT` 占位 tool_result 块，标记父上下文注入完成
- `is_in_fork_child` 基于对话内容（fork 标记文本）检测 Fork 子 Agent，
  同时兼容外部 `is_fork_child` 状态标志，防止递归 Fork
- `build_child_message` 在子任务消息中注入防递归指令
- Fork 启动后主 Agent 不阻塞，结果通过 task-notification 异步推送
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List

# Fork 占位符结果，主 Agent 在 Fork 启动后立即返回此占位符，
# 真实结果由子 Agent 完成后通过 task-notification 异步推送
FORK_PLACEHOLDER_RESULT: str = "[Fork placeholder - parent context will be injected]"

# 防递归指令文本，注入到 Fork 子 Agent 的首条 user 消息中
_ANTI_RECURSION_DIRECTIVE: str = "你当前是 Fork 子 Agent，不允许再次启动 Fork 子 Agent"

# 占位 tool_result 块的 tool_call_id 标识，用于在克隆上下文中标记占位块
_FORK_PLACEHOLDER_TOOL_CALL_ID: str = "fork_placeholder"


def build_forked_messages(parent_context: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    字节精确克隆父 Agent 的消息上下文，并追加 Fork 占位 tool_result 块。

    设计（字节一致前缀）：
    - 对父代每条消息做 `copy.deepcopy` 深拷贝，确保子 Agent 与父 Agent 之间
      无共享引用，互不影响；
    - 在克隆消息列表末尾追加一条 tool 角色占位块，其 content 为
      `FORK_PLACEHOLDER_RESULT`，作为"父上下文已注入"的标记；子 Agent 完成后
      该占位块可被真实结果替换。

    Args:
        parent_context: 父 Agent 的上下文，需包含 `messages` 列表。
                        若缺失则返回空列表。

    Returns:
        克隆后的消息列表：深拷贝的父代消息（字节一致前缀） + 末尾占位 tool_result 块。
    """
    if not isinstance(parent_context, dict):
        return []

    messages = parent_context.get("messages")
    if not isinstance(messages, list):
        return []

    # 逐条深拷贝，避免子 Agent 修改消息时影响父 Agent 上下文
    forked_messages = [copy.deepcopy(message) for message in messages]

    # 追加 Fork 占位 tool_result 块，标记父上下文注入完成
    forked_messages.append(
        {
            "role": "tool",
            "tool_call_id": _FORK_PLACEHOLDER_TOOL_CALL_ID,
            "name": "fork_context",
            "content": FORK_PLACEHOLDER_RESULT,
        }
    )
    return forked_messages


def is_in_fork_child(context: Dict[str, Any]) -> bool:
    """
    检测当前上下文是否处于 Fork 子 Agent 中。

    防递归检测基于对话内容而非仅外部状态标志：
    - 检查消息列表中任意消息的 content 是否包含 fork 标记文本
      （防递归指令或占位符结果文本）；
    - 兼容保留外部 `is_fork_child` 状态标志作为快速路径。

    Args:
        context: 当前 Agent 的上下文。

    Returns:
        True 表示当前为 Fork 子 Agent；False 表示非 Fork 子 Agent。
    """
    if not isinstance(context, dict):
        return False

    # 外部状态标志快速路径（兼容旧调用方）
    if context.get("is_fork_child"):
        return True

    # 对话内容检测：Fork 子 Agent 的消息中必然携带 fork 标记文本
    messages = context.get("messages")
    if not isinstance(messages, list):
        return False
    for message in messages:
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if not isinstance(content, str):
            continue
        if _ANTI_RECURSION_DIRECTIVE in content or FORK_PLACEHOLDER_RESULT in content:
            return True
    return False


def build_child_message(task_description: str) -> Dict[str, Any]:
    """
    构造 Fork 子 Agent 的首条 user 消息，包含任务描述与防递归指令。

    Args:
        task_description: 子 Agent 需要执行的任务描述。

    Returns:
        符合 OpenAI 消息格式的字典：`{"role": "user", "content": "..."}`
    """
    # 拼接任务描述与防递归指令，确保子 Agent 明确自身边界
    content = f"{task_description}\n\n{_ANTI_RECURSION_DIRECTIVE}"
    return {"role": "user", "content": content}
