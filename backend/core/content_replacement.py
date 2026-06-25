"""
工具结果内容替换状态与预算管理 — 控制上下文中工具结果的 token 总量。

核心思想（三分区算法）：
1. replaced（已替换）：已在 state.replacements 中的 tool_call_id，保持替换状态
2. frozen（冻结）：最近 N 条消息中的工具结果，不替换（保留最新结果）
3. fresh（新鲜）：新出现的 tool_call_id，若总 token 超过 budget，则替换为占位文本

旧的工具结果可以被安全替换（因为 LLM 已经看过），新的工具结果必须保留。
子 Agent 通过 clone_content_replacement_state 继承父 Agent 的替换状态，
但后续修改互不影响。
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List

from core.context.token_budget import TokenBudget


# 工具结果被替换时的占位文本
_TOOL_RESULT_CLEARED_PLACEHOLDER = "[Old tool result content cleared]"


@dataclass
class ContentReplacementState:
    """
    工具结果内容替换状态。

    seen_ids: 已见过的 tool_call_id 集合，用于区分新旧工具结果
    replacements: tool_call_id -> 替换文本 的映射，记录已被替换的工具结果
    """
    seen_ids: set = field(default_factory=set)
    replacements: Dict[str, str] = field(default_factory=dict)


def enforce_tool_result_budget(
    messages: List[Dict[str, Any]],
    state: ContentReplacementState,
    budget: int,
) -> List[Dict[str, Any]]:
    """
    对消息列表中的工具结果应用 token 预算，超预算时替换旧工具结果。

    三分区算法：
    1. replaced：已在 state.replacements 中的 tool_call_id，保持替换状态
    2. frozen：从后往前扫描，最近的消息标记为冻结（直到累积 token 达到 budget）
    3. fresh：不在冻结区且未被替换的工具结果，若总 token 超过 budget，则替换

    本函数不修改原消息列表，返回新的列表。

    Args:
        messages: 消息列表，可能包含 role=tool 的工具结果消息
        state: 内容替换状态，会被本函数更新（seen_ids 和 replacements）
        budget: 工具结果的 token 预算上限

    Returns:
        应用预算后的新消息列表
    """
    token_budget = TokenBudget()

    # 浅拷贝每条消息，避免修改原列表
    result: List[Dict[str, Any]] = [dict(msg) for msg in messages]

    # 收集所有工具消息的索引（role=tool 且有 tool_call_id）
    tool_indices: List[int] = []
    for i, msg in enumerate(result):
        if msg.get("role") == "tool" and msg.get("tool_call_id"):
            tool_indices.append(i)

    # 无工具消息时直接返回
    if not tool_indices:
        return result

    # 步骤 1：对已在 replacements 中的工具消息，应用替换文本
    for i in tool_indices:
        tool_call_id = result[i].get("tool_call_id")
        if tool_call_id in state.replacements:
            result[i]["content"] = state.replacements[tool_call_id]

    # 步骤 2：计算所有工具消息的总 token 数
    total_tokens = 0
    for i in tool_indices:
        content = result[i].get("content", "")
        if isinstance(content, str):
            total_tokens += token_budget.estimate_tokens(content)

    # 步骤 3：总 token 在预算内时，仅更新 seen_ids 并返回
    if total_tokens <= budget:
        for i in tool_indices:
            tool_call_id = result[i].get("tool_call_id")
            if tool_call_id:
                state.seen_ids.add(tool_call_id)
        return result

    # 步骤 4：总 token 超过预算，从后往前标记冻结区
    # 冻结区为最近的工具结果，累积 token 达到 budget 为止
    frozen: set = set()
    accumulated = 0
    for i in reversed(tool_indices):
        content = result[i].get("content", "")
        if isinstance(content, str):
            tokens = token_budget.estimate_tokens(content)
        else:
            tokens = 0
        frozen.add(i)
        accumulated += tokens
        if accumulated >= budget:
            break

    # 步骤 5：处理每条工具消息
    for i in tool_indices:
        tool_call_id = result[i].get("tool_call_id")
        if not tool_call_id:
            continue

        if tool_call_id in state.replacements:
            # replaced 区：已在步骤 1 应用替换文本，此处保持不变
            pass
        elif i in frozen:
            # frozen 区：保留最新结果，不替换
            pass
        else:
            # fresh 区：新出现的工具结果，超预算时替换为占位文本
            result[i]["content"] = _TOOL_RESULT_CLEARED_PLACEHOLDER
            state.replacements[tool_call_id] = _TOOL_RESULT_CLEARED_PLACEHOLDER

        # 更新 seen_ids
        state.seen_ids.add(tool_call_id)

    return result


def clone_content_replacement_state(
    state: ContentReplacementState,
) -> ContentReplacementState:
    """
    克隆内容替换状态，用于子 Agent 继承父 Agent 的替换状态。

    子 Agent 继承父 Agent 的 seen_ids 和 replacements，
    但后续对克隆状态的修改互不影响原状态。

    Args:
        state: 待克隆的内容替换状态

    Returns:
        新的 ContentReplacementState 实例，包含原状态的副本
    """
    return ContentReplacementState(
        seen_ids=set(state.seen_ids),
        replacements=dict(state.replacements),
    )
