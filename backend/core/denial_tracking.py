"""
权限拒绝追踪与升级模块。

在 auto 模式下持续记录权限拒绝次数，当连续拒绝或累计拒绝超过阈值时，
自动回退到人工确认模式（manual），避免 Agent 在被反复拒绝后陷入死循环。

核心设计：
- DenialTrackingState：不可变状态，记录连续拒绝数与累计拒绝数
- record_denial / record_success：纯函数，返回新状态而非原地修改
- should_fallback_to_prompting：判断是否应回退到人工模式
- 子 Agent 可传入 local_denial_tracking 实例，优先于全局状态
"""

from dataclasses import dataclass
from typing import Dict


# 拒绝次数上限配置
# - max_consecutive: 连续拒绝达到该值时回退人工
# - max_total: 累计拒绝达到该值时回退人工
DENIAL_LIMITS: Dict[str, int] = {
    "max_consecutive": 3,
    "max_total": 20,
}


@dataclass
class DenialTrackingState:
    """
    权限拒绝追踪状态。

    属性：
    - consecutive_denials: 连续拒绝次数，每次成功后重置为 0
    - total_denials: 累计拒绝次数，单调递增
    """
    consecutive_denials: int = 0
    total_denials: int = 0


def record_denial(state: DenialTrackingState) -> DenialTrackingState:
    """
    记录一次权限拒绝，返回新状态（纯函数，不修改原状态）。

    - consecutive_denials += 1
    - total_denials += 1
    """
    return DenialTrackingState(
        consecutive_denials=state.consecutive_denials + 1,
        total_denials=state.total_denials + 1,
    )


def record_success(state: DenialTrackingState) -> DenialTrackingState:
    """
    记录一次权限成功，返回新状态（纯函数，不修改原状态）。

    - consecutive_denials 重置为 0
    - total_denials 保持不变
    """
    return DenialTrackingState(
        consecutive_denials=0,
        total_denials=state.total_denials,
    )


def should_fallback_to_prompting(state: DenialTrackingState) -> bool:
    """
    判断是否应回退到人工确认模式。

    触发条件（任一满足即回退）：
    - consecutive_denials >= max_consecutive
    - total_denials >= max_total
    """
    return (
        state.consecutive_denials >= DENIAL_LIMITS["max_consecutive"]
        or state.total_denials >= DENIAL_LIMITS["max_total"]
    )
