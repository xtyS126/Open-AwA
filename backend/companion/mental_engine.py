"""
心智引擎编排模块：把信念网络、事件评估、认知谱系、记忆与观察者
组织成每轮对话与睡眠的确定性更新流程。

对应 NSP-roleplay 架构中的「人格更新器 + 记忆系统 + 引导生成器 + 观察者」：
LLM 只负责抽取与回复生成，其余一切都在本模块用确定性代码计算。

流程（每轮）：
1. 接收抽取层产出（OCC 评估、受影响信念的加权误差、认知更新、新记忆）
2. 推导情绪状态，更新信念网络（应变/负荷/灾变）
3. 计算双通道引导文本
4. 召回相关记忆
5. 睡眠时执行睡眠整合管线
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from loguru import logger

from companion.appraisal import (
    Appraisal,
    EmotionState,
    dual_channel_guidance,
    emotion_from_appraisal,
)
from companion.belief_network import BeliefNetwork
from companion.cognition import Cognition
from companion.memory import (
    CompanionMemory,
    consolidate_memories,
    recall_priority,
)
from companion.observer import ArcResult, detect_arcs


# 睡眠应变恢复：strain *= 0.95^8（约降低 33%）
SLEEP_STRAIN_RECOVERY: float = 0.95 ** 8

# 睡眠情绪衰减：强度减半，低于此值重置为中性
SLEEP_EMOTION_DECAY: float = 0.5
SLEEP_NEUTRAL_INTENSITY: float = 0.1


@dataclass
class MentalExtraction:
    """抽取层（廉价 LLM）对一轮对话的结构化产出，作为心智引擎的输入。"""

    appraisal: Appraisal = field(default_factory=Appraisal)
    weighted_errors: Dict[str, float] = field(default_factory=dict)
    cognition_updates: List[tuple] = field(default_factory=list)
    new_memory: Optional[CompanionMemory] = None
    current_keywords: List[str] = field(default_factory=list)
    rational_cue: str = ""
    emotional_cue: str = ""


@dataclass
class MentalUpdate:
    """心智引擎一轮更新后的输出，供注入生成与持久化使用。"""

    emotion: EmotionState = field(default_factory=EmotionState)
    guidance: Dict[str, Any] = field(default_factory=dict)
    milestones: List[str] = field(default_factory=list)
    recalled_memories: List[CompanionMemory] = field(default_factory=list)
    cognition_changes: List[Dict[str, Any]] = field(default_factory=list)
    arcs: List[ArcResult] = field(default_factory=list)


class MentalEngine:
    """陪伴者心智引擎：承载并演化单个用户的完整心理状态。"""

    def __init__(self, beliefs: Dict[str, float], links: Optional[Dict[str, List[str]]] = None) -> None:
        self.network = BeliefNetwork(beliefs, links=links)
        self.cognition = Cognition()
        self.emotion = EmotionState()
        self.memories: List[CompanionMemory] = []
        self.turn: int = 0
        self.snapshots: List[Dict[str, Any]] = []

    # ---- 每轮更新 ----

    def process_turn(self, extraction: MentalExtraction) -> MentalUpdate:
        """执行一轮确定性心智更新。"""
        self.turn += 1

        # 1. 情绪更新
        self.emotion = emotion_from_appraisal(extraction.appraisal)

        # 2. 信念网络更新（应变/负荷/灾变）
        milestones = self.network.update(
            weighted_errors=extraction.weighted_errors,
            emotion_intensity=self.emotion.intensity,
            desirability=extraction.appraisal.desirability,
        )

        # 3. 双通道引导
        guidance = dual_channel_guidance(
            rational_cue=extraction.rational_cue or "基于信念、承诺与义务应如何行动",
            emotional_cue=extraction.emotional_cue or "受当前情绪与直觉推动如何行动",
            emotion_intensity=self.emotion.intensity,
        )

        # 4. 新记忆入库
        if extraction.new_memory is not None:
            extraction.new_memory.created_turn = self.turn
            self.memories.append(extraction.new_memory)

        # 5. 记忆召回（按优先级降序，返回前若干条）
        recalled = sorted(
            self.memories,
            key=lambda m: recall_priority(m, self.turn, extraction.current_keywords),
            reverse=True,
        )

        # 6. 认知谱系转换
        cognition_changes: List[Dict[str, Any]] = []
        for fact_id, event_type in extraction.cognition_updates:
            new_state = self.cognition.transition(fact_id, event_type, self.turn)
            if new_state is not None:
                cognition_changes.append(
                    {"fact_id": fact_id, "state": new_state, "turn": self.turn}
                )

        # 7. 观察者分析（周期执行，此处每次运行以保持状态可观测）
        arcs = detect_arcs(
            {name: node.history for name, node in self.network.nodes.items()}
        )

        logger.bind(
            event="mental_turn",
            module="companion",
            turn=self.turn,
            emotion=self.emotion.primary,
            intensity=self.emotion.intensity,
            milestone_count=len(milestones),
        ).debug("心智引擎完成一轮更新")

        return MentalUpdate(
            emotion=self.emotion,
            guidance=guidance,
            milestones=milestones,
            recalled_memories=recalled[:5],
            cognition_changes=cognition_changes,
            arcs=arcs,
        )

    # ---- 睡眠整合 ----

    def sleep(self) -> Dict[str, Any]:
        """
        执行睡眠整合管线：应变恢复、情绪衰减、记忆整合、人格存档、观察者分析。

        负荷不恢复（心理伤疤不消失），应变随睡眠显著降低。
        """
        self.turn += 1

        # 1. 应变恢复（负荷不恢复）
        for node in self.network.nodes.values():
            node.strain *= SLEEP_STRAIN_RECOVERY

        # 2. 情绪衰减（强度减半，低于阈值重置中性）
        self.emotion.intensity *= SLEEP_EMOTION_DECAY
        if self.emotion.intensity < SLEEP_NEUTRAL_INTENSITY:
            self.emotion = EmotionState()

        # 3. 记忆整合（关键词重叠聚类）
        self.memories = consolidate_memories(self.memories, self.turn)

        # 4. 人格存档（为分叉/平行剧本提供快照）
        snapshot = self.snapshot()
        self.snapshots.append(snapshot)

        # 5. 观察者分析
        arcs = detect_arcs(
            {name: node.history for name, node in self.network.nodes.items()}
        )

        logger.bind(
            event="mental_sleep",
            module="companion",
            turn=self.turn,
        ).info("心智引擎执行睡眠整合")

        return {
            "snapshot": snapshot,
            "arcs": [a.arc for a in arcs],
        }

    # ---- 状态快照 ----

    def snapshot(self) -> Dict[str, Any]:
        """导出完整心智状态快照（用于持久化或分叉）。"""
        return {
            "turn": self.turn,
            "beliefs": self.network.to_dict(),
            "emotion": self.emotion.to_dict(),
            "cognition": self.cognition.to_dict(),
        }

    def guidance_text(self) -> str:
        """渲染当前情绪状态与双通道占比的自然语言引导，供注入 system prompt。"""
        mix = self.emotion
        from companion.appraisal import mix_weight

        rational_share = 1.0 - mix_weight(mix.intensity)
        emotional_share = mix_weight(mix.intensity)
        return (
            f"情绪：{mix.primary}（强度 {mix.intensity:.2f}）。"
            f"当前状态倾向 {rational_share * 100:.0f}% 理性、{emotional_share * 100:.0f}% 情感。"
        )