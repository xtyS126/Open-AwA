"""
多 Agent 讨论任务核心模块。

提供讨论任务的创建、多角色评审、投票统计、动作执行与 SSE 流式推送能力。

主要导出：
- 枚举：DiscussionStatus / DiscussionRole / VoteDecision
- 数据类：DiscussionTaskData / DiscussionVoteData / ProposedAction
- 编排器：DiscussionOrchestrator
- 状态机：validate_transition / is_terminal
- 异常：DiscussionError 及其子类
"""

from core.discussion.definitions import (
    BUILTIN_ROLES,
    DiscussionError,
    DiscussionExecutionError,
    DiscussionParseError,
    DiscussionRole,
    DiscussionRoundLimitError,
    DiscussionStateError,
    DiscussionStatus,
    DiscussionTaskData,
    DiscussionVoteData,
    ProposedAction,
    VoteDecision,
)
from core.discussion.orchestrator import DiscussionOrchestrator
from core.discussion.state_machine import (
    VALID_TRANSITIONS,
    is_terminal,
    validate_transition,
)

__all__ = [
    # 枚举
    "DiscussionStatus",
    "DiscussionRole",
    "VoteDecision",
    # 数据类
    "ProposedAction",
    "DiscussionTaskData",
    "DiscussionVoteData",
    # 常量
    "BUILTIN_ROLES",
    "VALID_TRANSITIONS",
    # 编排器
    "DiscussionOrchestrator",
    # 状态机
    "validate_transition",
    "is_terminal",
    # 异常
    "DiscussionError",
    "DiscussionStateError",
    "DiscussionRoundLimitError",
    "DiscussionExecutionError",
    "DiscussionParseError",
]
