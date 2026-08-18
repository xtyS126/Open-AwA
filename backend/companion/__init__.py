"""
陪伴系统模块：基于 NSP-roleplay 心智模型的确定性情感深度引擎。

提供：
- belief_network：信念网络（精度/应变/负荷/灾变 + v9 优化）
- appraisal：OCC 事件评估、情绪状态与双通道行为引导
- cognition：8 态认知谱系
- memory：陪伴记忆召回优先级与睡眠整合
- observer：涌现弧线检测
- mental_engine：每轮心智更新与睡眠整合编排（确定性引擎入口）

设计原则：LLM 是「声音」，Python 是「灵魂」。本包全部为确定性计算，
不直接调用 LLM；抽取层与回复生成由上层编排接入。
"""

from companion.appraisal import (
    Appraisal,
    EmotionState,
    dual_channel_guidance,
    emotion_from_appraisal,
    mix_weight,
)
from companion.belief_network import BeliefNetwork, BeliefNode
from companion.cognition import COGNITION_STATES, Cognition
from companion.extraction import extract_mental_state, parse_mental_extraction
from companion.memory import CompanionMemory, consolidate_memories, recall_priority
from companion.mental_engine import MentalEngine, MentalExtraction, MentalUpdate
from companion.observer import (
    ARC_GRADUAL_SHIFT,
    ARC_OSCILLATION,
    ARC_PLATEAU,
    ARC_SUDDEN_JUMP,
    detect_arc,
    detect_arcs,
)


__all__ = [
    "Appraisal",
    "EmotionState",
    "dual_channel_guidance",
    "emotion_from_appraisal",
    "mix_weight",
    "BeliefNetwork",
    "BeliefNode",
    "COGNITION_STATES",
    "Cognition",
    "CompanionMemory",
    "consolidate_memories",
    "recall_priority",
    "extract_mental_state",
    "parse_mental_extraction",
    "MentalEngine",
    "MentalExtraction",
    "MentalUpdate",
    "detect_arc",
    "detect_arcs",
    "ARC_SUDDEN_JUMP",
    "ARC_OSCILLATION",
    "ARC_GRADUAL_SHIFT",
    "ARC_PLATEAU",
]