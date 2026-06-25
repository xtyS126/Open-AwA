"""
Fork 机制上下文克隆模块。

提供子 Agent 继承父 Agent 完整消息上下文的能力，同时通过防递归标志
阻止 Fork 子 Agent 再次发起 Fork，避免无限递归。

核心概念：
- Fork 子 Agent 通过 `build_forked_messages` 字节精确克隆父上下文消息
- 通过 `is_fork_child` 标志位识别 Fork 子 Agent，防止递归 Fork
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


def build_forked_messages(parent_context: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    字节精确克隆父 Agent 的消息上下文。

    使用 `copy.deepcopy` 对每条消息进行深拷贝，确保子 Agent 与父 Agent
    之间无共享引用，互不影响。

    Args:
        parent_context: 父 Agent 的上下文，需包含 `messages` 列表。
                        若缺失则返回空列表。

    Returns:
        克隆后的消息列表，与原列表内容等价但完全独立。
    """
    if not isinstance(parent_context, dict):
        return []

    messages = parent_context.get("messages")
    if not isinstance(messages, list):
        return []

    # 逐条深拷贝，避免子 Agent 修改消息时影响父 Agent 上下文
    return [copy.deepcopy(message) for message in messages]


def is_in_fork_child(context: Dict[str, Any]) -> bool:
    """
    检测当前上下文是否处于 Fork 子 Agent 中。

    用于防止 Fork 子 Agent 再次发起 Fork（递归保护）。

    Args:
        context: 当前 Agent 的上下文。

    Returns:
        True 表示当前为 Fork 子 Agent；False 表示非 Fork 子 Agent 或未设置标志。
    """
    if not isinstance(context, dict):
        return False
    return bool(context.get("is_fork_child", False))


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
