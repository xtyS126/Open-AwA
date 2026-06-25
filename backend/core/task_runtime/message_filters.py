"""
Resume 消息清洗过滤器模块。

在代理恢复（resume）场景下，从数据库加载的历史消息可能包含未完成的工具调用、
孤立的思考块或空白助手消息。这些脏数据会导致下游 LLM 调用失败或产生异常行为，
因此在恢复前需要依次应用三道过滤器进行清洗：

1. filter_unresolved_tool_uses: 移除未完成的 tool_use 块
2. filter_orphaned_thinking_only_messages: 移除只含 thinking 的孤立消息
3. filter_whitespace_only_assistant_messages: 移除空白助手消息

所有过滤器均为纯函数，返回新列表，不修改原列表。
"""

from __future__ import annotations

from typing import Any, Dict, List


def filter_unresolved_tool_uses(
    messages: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    移除未完成的 tool_use 块。

    当 assistant 消息含 tool_use 块但没有对应的 tool 结果消息时，
    移除该 tool_use 块；若移除后 assistant 消息的 content 为空，则移除整个消息。

    Args:
        messages: 原始消息列表

    Returns:
        清洗后的新消息列表，原列表不会被修改
    """
    # 收集所有已存在的 tool_call_id（来自 role="tool" 的消息）
    resolved_tool_call_ids: set[str] = {
        msg.get("tool_call_id")
        for msg in messages
        if msg.get("role") == "tool" and msg.get("tool_call_id") is not None
    }

    cleaned: List[Dict[str, Any]] = []
    for message in messages:
        # 仅处理 assistant 消息
        if message.get("role") != "assistant":
            cleaned.append(message)
            continue

        content = message.get("content")
        # content 非 list 时直接保留（字符串或 None 不涉及 tool_use 块）
        if not isinstance(content, list):
            cleaned.append(message)
            continue

        # 过滤掉未匹配到 tool 结果的 tool_use 项
        new_content: List[Dict[str, Any]] = []
        for item in content:
            if not isinstance(item, dict):
                new_content.append(item)
                continue
            if item.get("type") == "tool_use":
                tool_use_id = item.get("id")
                if tool_use_id in resolved_tool_call_ids:
                    new_content.append(item)
                # 否则跳过（移除未完成的 tool_use 块）
            else:
                new_content.append(item)

        # 若移除后 content 为空，则跳过整个 assistant 消息
        if not new_content:
            continue

        # 构造新的 assistant 消息（浅拷贝，避免污染原消息）
        new_message = dict(message)
        new_message["content"] = new_content
        cleaned.append(new_message)

    return cleaned


def filter_orphaned_thinking_only_messages(
    messages: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    移除只含 thinking 内容的孤立 assistant 消息。

    若 assistant 消息的 content 是列表且所有项的 type 都是 "thinking"，
    或者 content 是空字符串，则移除该消息。

    Args:
        messages: 原始消息列表

    Returns:
        清洗后的新消息列表，原列表不会被修改
    """
    cleaned: List[Dict[str, Any]] = []
    for message in messages:
        if message.get("role") != "assistant":
            cleaned.append(message)
            continue

        content = message.get("content")

        # content 为字符串时：空字符串视为孤立消息
        if isinstance(content, str):
            if content == "":
                continue
            cleaned.append(message)
            continue

        # content 为列表时：所有项 type 均为 thinking 才移除
        if isinstance(content, list):
            if not content:
                # 空列表视为孤立消息
                continue
            all_thinking = all(
                isinstance(item, dict) and item.get("type") == "thinking"
                for item in content
            )
            if all_thinking:
                continue
            cleaned.append(message)
            continue

        # 其他类型（None 或异常结构）保留
        cleaned.append(message)

    return cleaned


def filter_whitespace_only_assistant_messages(
    messages: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    移除空白 assistant 消息。

    若 assistant 消息的 content 为空字符串或只含空白字符，
    或者 content 是列表且所有项的 text 字段都是空白，则移除该消息。

    Args:
        messages: 原始消息列表

    Returns:
        清洗后的新消息列表，原列表不会被修改
    """
    cleaned: List[Dict[str, Any]] = []
    for message in messages:
        if message.get("role") != "assistant":
            cleaned.append(message)
            continue

        content = message.get("content")

        # content 为字符串时：strip 后为空则移除
        if isinstance(content, str):
            if content.strip() == "":
                continue
            cleaned.append(message)
            continue

        # content 为列表时：所有项的 text 字段都是空白才移除
        if isinstance(content, list):
            if not content:
                continue
            # 仅考察含 text 字段的项；若所有项的 text 都是空白则移除
            all_whitespace = True
            for item in content:
                if not isinstance(item, dict):
                    all_whitespace = False
                    break
                if item.get("type") == "text":
                    text_value = item.get("text", "")
                    if not isinstance(text_value, str) or text_value.strip() != "":
                        all_whitespace = False
                        break
                else:
                    # 非 text 类型项（如 tool_use、thinking）说明消息有实质内容
                    all_whitespace = False
                    break
            if all_whitespace:
                continue
            cleaned.append(message)
            continue

        # 其他类型（None 或异常结构）保留
        cleaned.append(message)

    return cleaned


def apply_resume_filters(
    messages: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    便捷函数：依次应用三道 Resume 清洗过滤器。

    应用顺序：
    1. filter_unresolved_tool_uses: 先清理未完成的 tool_use，避免后续误判
    2. filter_orphaned_thinking_only_messages: 清理只含 thinking 的孤立消息
    3. filter_whitespace_only_assistant_messages: 清理空白助手消息

    Args:
        messages: 原始消息列表

    Returns:
        清洗后的新消息列表，原列表不会被修改
    """
    cleaned = filter_unresolved_tool_uses(messages)
    cleaned = filter_orphaned_thinking_only_messages(cleaned)
    cleaned = filter_whitespace_only_assistant_messages(cleaned)
    return cleaned
