"""
观察者模块：分析人格状态历史，检测涌现弧线。

对应 NSP-roleplay 心智模型的「涌现弧线」层。观察者在弧线涌现之后才识别
模式，永不反馈到生成中——它只描述数学已经产生的结果，避免叙事标签
反向塑造行为的反馈循环。

弧线分类：
- SUDDEN_JUMP   突变：单步变化 >= 0.2
- OSCILLATION   摆荡：方向改变 >= 3 次
- GRADUAL_SHIFT 渐变：累计变化 > 0.1
- PLATEAU       稳态：以上均不满足
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List


# 突变阈值：单步变化超过此值判定为 SUDDEN_JUMP
SUDDEN_JUMP_THRESHOLD: float = 0.2

# 摆荡阈：方向改变次数达到此值判定为 OSCILLATION
OSCILLATION_DIRECTION_CHANGES: int = 3

# 渐变阈值：累计净变化超过此值判定为 GRADUAL_SHIFT
GRADUAL_SHIFT_THRESHOLD: float = 0.1

# 弧线类型常量
ARC_SUDDEN_JUMP = "SUDDEN_JUMP"
ARC_OSCILLATION = "OSCILLATION"
ARC_GRADUAL_SHIFT = "GRADUAL_SHIFT"
ARC_PLATEAU = "PLATEAU"


@dataclass
class ArcResult:
    """弧线检测结果。"""

    arc: str
    belief: str
    max_step: float
    direction_changes: int
    total_delta: float


def detect_arc(history: List[float], belief: str = "") -> ArcResult:
    """
    对单个人格维度的状态历史执行弧线分类。

    Args:
        history: 状态值序列（按时间顺序）
        belief: 维度名（可选，用于结果标注）

    Returns:
        ArcResult 弧线检测结果
    """
    if len(history) < 2:
        return ArcResult(
            arc=ARC_PLATEAU,
            belief=belief,
            max_step=0.0,
            direction_changes=0,
            total_delta=0.0,
        )

    steps = [history[i + 1] - history[i] for i in range(len(history) - 1)]
    max_step = max(abs(s) for s in steps)
    total_delta = history[-1] - history[0]

    # 方向改变计数：相邻步进符号变化
    direction_changes = 0
    for i in range(1, len(steps)):
        if steps[i - 1] != 0 and steps[i] != 0 and (steps[i - 1] * steps[i] < 0):
            direction_changes += 1

    if max_step >= SUDDEN_JUMP_THRESHOLD:
        arc = ARC_SUDDEN_JUMP
    elif direction_changes >= OSCILLATION_DIRECTION_CHANGES:
        arc = ARC_OSCILLATION
    elif abs(total_delta) > GRADUAL_SHIFT_THRESHOLD:
        arc = ARC_GRADUAL_SHIFT
    else:
        arc = ARC_PLATEAU

    return ArcResult(
        arc=arc,
        belief=belief,
        max_step=max_step,
        direction_changes=direction_changes,
        total_delta=total_delta,
    )


def detect_arcs(histories: dict[str, List[float]]) -> List[ArcResult]:
    """批量检测多个维度的弧线。"""
    return [detect_arc(history, belief=name) for name, history in histories.items()]