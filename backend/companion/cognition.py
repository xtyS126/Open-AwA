"""
认知谱系模块：角色对特定事实的 8 态认知建模。

对应 NSP-roleplay 心智模型的「角色知道什么（以及不知道什么）」层。
知识不再被建模为二元（知道/不知道），而是 8 态谱系，各状态携带
心理学上连贯的行为倾向，并通过对话事件发生阶段性转换。

典型转换链：unaware -> suspects -> denies -> aware。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


# 8 态认知谱系（按行为影响分组）
COGNITION_STATES: List[str] = [
    "aware",           # 正确知晓
    "misbelieves",     # 自以为知道，但错误
    "suspects",        # 有猜测，不确定
    "partially_aware", # 只知道部分真相
    "unaware",         # 不知道
    "forgot",          # 曾经知道，已遗忘
    "overwhelmed",     # 知道但无法处理
    "denies",          # 知道但拒绝接受
]

# 合法状态集合
VALID_STATES = frozenset(COGNITION_STATES)


@dataclass
class CognitionEntry:
    """单个知识条目的认知状态与演化轨迹。"""

    state: str = "unaware"
    # 记录每次状态转换的轮次，便于追溯演化时序
    transitions: List[Dict[str, object]] = field(default_factory=list)


# 状态转换矩阵：{当前状态: {触发事件类型: 目标状态}}
# 事件类型由抽取层在对话中识别，这里仅承载确定性转换规则
TRANSITION_MATRIX: Dict[str, Dict[str, str]] = {
    "unaware": {
        "hint": "suspects",        # 接收到线索 -> 产生猜测
        "reveal": "partially_aware",  # 直接被部分告知 -> 部分知晓
        "full_reveal": "aware",    # 完整告知 -> 正确知晓
    },
    "suspects": {
        "confirm": "aware",        # 猜测被证实 -> 正确知晓
        "misleading": "misbelieves",  # 错误线索 -> 误信
        "threat": "denies",        # 真相带来威胁 -> 拒绝接受
    },
    "denies": {
        "breakdown": "overwhelmed",  # 否认崩溃 -> 无法处理
        "accept": "aware",          # 最终接受 -> 正确知晓
    },
    "overwhelmed": {
        "cooldown": "partially_aware",  # 情绪平复 -> 部分接受
        "accept": "aware",
    },
    "partially_aware": {
        "full_reveal": "aware",
        "threat": "denies",
    },
    "aware": {
        "forget": "forgot",        # 遗忘 -> 曾知已忘
    },
    "forgot": {
        "remind": "aware",         # 被提醒 -> 恢复知晓
    },
    "misbelieves": {
        "correct": "aware",        # 被纠正 -> 正确知晓
        "challenge": "suspects",   # 被质疑 -> 回到怀疑
    },
}


class Cognition:
    """角色的认知谱系容器：维护多条知识条目的认知状态。"""

    def __init__(self) -> None:
        self.entries: Dict[str, CognitionEntry] = {}

    def ensure(self, fact_id: str) -> CognitionEntry:
        """确保某知识条目存在，不存在则创建为 unaware。"""
        if fact_id not in self.entries:
            self.entries[fact_id] = CognitionEntry()
        return self.entries[fact_id]

    def transition(self, fact_id: str, event_type: str, turn: int) -> Optional[str]:
        """
        对某知识条目执行一次状态转换。

        Args:
            fact_id: 知识条目标识
            event_type: 触发事件类型（见 TRANSITION_MATRIX）
            turn: 当前对话轮次（用于记录转换时间）

        Returns:
            新状态；若无可转换规则则返回 None
        """
        entry = self.ensure(fact_id)
        targets = TRANSITION_MATRIX.get(entry.state, {})
        new_state = targets.get(event_type)
        if new_state is None:
            return None
        entry.transitions.append(
            {"from": entry.state, "to": new_state, "event": event_type, "turn": turn}
        )
        entry.state = new_state
        return new_state

    def state_of(self, fact_id: str) -> str:
        """查询某知识条目的当前认知状态。"""
        return self.ensure(fact_id).state

    def to_dict(self) -> Dict[str, Dict[str, object]]:
        """导出为字典。"""
        return {
            fact_id: {"state": entry.state, "transitions": entry.transitions}
            for fact_id, entry in self.entries.items()
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Dict[str, object]]) -> "Cognition":
        """从字典恢复认知谱系。"""
        cognition = cls()
        for fact_id, payload in data.items():
            entry = CognitionEntry(state=str(payload.get("state", "unaware")))
            entry.transitions = [
                dict(t) for t in payload.get("transitions", [])  # type: ignore[arg-type]
            ]
            cognition.entries[fact_id] = entry
        return cognition