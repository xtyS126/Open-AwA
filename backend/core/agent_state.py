"""Agent 主循环状态机枚举，从 core/agent.py 迁移以便 agent_helpers 等模块复用。

本模块独立定义 AgentState 枚举，避免 agent_helpers.py 与 agent.py 之间的循环 import。
agent.py 通过 `from core.agent_state import AgentState` 导入，agent_helpers.py 同样如此。
"""

from __future__ import annotations

# 标准库
from enum import Enum


class AgentState(Enum):
    """
    Agent 主循环的显式状态机枚举。

    状态分为两类：
    - 继续态（CONTINUE_*）：循环需继续执行下一轮
    - 终态（TERMINAL_*）：循环应停止，对应不同的结束原因
    """

    # 继续态：检测到 tool_calls，需要执行工具后继续下一轮 LLM 调用
    CONTINUE_TOOL_CALLS = "continue_tool_calls"
    # 继续态：上下文超限（finish_reason=length），需要压缩后继续
    CONTINUE_COMPACT = "continue_compact"
    # 终态：模型正常结束（finish_reason=stop）
    TERMINAL_END_TURN = "terminal_end_turn"
    # 终态：达到最大轮次上限
    TERMINAL_MAX_ROUNDS = "terminal_max_rounds"
    # 终态：模型拒绝（finish_reason=content_filter）
    TERMINAL_REFUSAL = "terminal_refusal"
    # 终态：预算耗尽
    TERMINAL_BUDGET_EXHAUSTED = "terminal_budget_exhausted"

    @property
    def is_terminal(self) -> bool:
        """判断当前状态是否为终态，终态时主循环应退出。"""
        return self in (
            AgentState.TERMINAL_END_TURN,
            AgentState.TERMINAL_MAX_ROUNDS,
            AgentState.TERMINAL_REFUSAL,
            AgentState.TERMINAL_BUDGET_EXHAUSTED,
        )

    @property
    def is_continuation(self) -> bool:
        """判断当前状态是否为继续态，继续态时主循环应执行下一轮。"""
        return self in (
            AgentState.CONTINUE_TOOL_CALLS,
            AgentState.CONTINUE_COMPACT,
        )
