"""
讨论任务状态机定义。

合法状态转换路径：
    created -> discussing -> pending_approval -> approved/rejected
                                             -> executing -> completed/failed
    rejected -> discussing （修订后由 orchestrator 转换）
    completed/failed 为终态，不可再转换。
"""

from __future__ import annotations

from typing import Set

from core.discussion.definitions import DiscussionStatus


# 合法状态转换映射：当前状态 -> 允许的目标状态集合
VALID_TRANSITIONS: dict[str, Set[str]] = {
    DiscussionStatus.CREATED.value: {
        DiscussionStatus.DISCUSSING.value,
        "cancelled",  # 允许创建后立即取消（取消视为终态，复用 rejected 语义之外的旁路）
    },
    DiscussionStatus.DISCUSSING.value: {
        DiscussionStatus.PENDING_APPROVAL.value,
        DiscussionStatus.FAILED.value,
    },
    DiscussionStatus.PENDING_APPROVAL.value: {
        DiscussionStatus.APPROVED.value,
        DiscussionStatus.REJECTED.value,
        # rejected 后允许 revise 回到 discussing；pending_approval 也允许直接重新讨论
        DiscussionStatus.DISCUSSING.value,
    },
    DiscussionStatus.APPROVED.value: {
        DiscussionStatus.EXECUTING.value,
        # approved 可直接 completed（proposed_action 已执行或为空操作时）
        DiscussionStatus.COMPLETED.value,
    },
    DiscussionStatus.REJECTED.value: {
        # 修订后回到 discussing，由 orchestrator 在 revise 时转换
        DiscussionStatus.DISCUSSING.value,
    },
    DiscussionStatus.EXECUTING.value: {
        DiscussionStatus.COMPLETED.value,
        DiscussionStatus.FAILED.value,
    },
    # 终态：不可再转换
    DiscussionStatus.COMPLETED.value: set(),
    DiscussionStatus.FAILED.value: set(),
}


def validate_transition(current: str, target: str) -> bool:
    """
    校验从 current 状态到 target 状态的转换是否合法。

    Args:
        current: 当前状态字符串
        target: 目标状态字符串

    Returns:
        bool: 合法返回 True，否则 False
    """
    allowed = VALID_TRANSITIONS.get(current, set())
    return target in allowed


def is_terminal(status: str) -> bool:
    """
    判断给定状态是否为终态（completed/failed）。

    Args:
        status: 状态字符串

    Returns:
        bool: 终态返回 True，否则 False
    """
    return status in (
        DiscussionStatus.COMPLETED.value,
        DiscussionStatus.FAILED.value,
    )
