"""
事件评估模块：OCC 评估模型、情绪状态与双通道行为引导。

对应 NSP-roleplay 心智模型的「先感受，再思考」层：

- OCC 评估：每个事件沿相关性/合意性/可控性/新奇性四个维度被评估
- 情绪状态：由评估结果推导出主副情绪、强度、效价，并标记情绪矛盾（v9）
- 双通道引导：冷通道（理性）与热通道（情感）通过 sigmoid 按情绪强度混合

本模块为纯确定性代码。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict


# 情绪效价阈值：|desirability| 低于此值视为中性
NEUTRAL_DESIRABILITY: float = 0.1


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    """将数值钳制到 [low, high] 区间。"""
    return max(low, min(high, value))


def sigmoid(x: float) -> float:
    """标准 logistic 函数。"""
    return 1.0 / (1.0 + math.exp(-x))


@dataclass
class Appraisal:
    """OCC 评估结果：事件在四个心理学维度上的评分。"""

    relevance: float = 0.5        # 相关性 [0, 1]：这件事对我重要吗
    desirability: float = 0.0     # 合意性 [-1, 1]：对我的目标是好是坏
    controllability: float = 0.5  # 可控性 [0, 1]：我能影响这件事吗
    novelty: float = 0.5          # 新奇性 [0, 1]：这有多出乎意料


@dataclass
class EmotionState:
    """陪伴者某一时刻的情绪状态。"""

    primary: str = "neutral"      # 主情绪
    secondary: str = "neutral"    # 副情绪
    intensity: float = 0.0        # 强度 [0, 1]
    valence: float = 0.0          # 效价 [-1, 1]
    ambivalence: bool = False     # 情绪矛盾标记（v9）

    def to_dict(self) -> Dict[str, object]:
        """导出为字典。"""
        return {
            "primary": self.primary,
            "secondary": self.secondary,
            "intensity": self.intensity,
            "valence": self.valence,
            "ambivalence": self.ambivalence,
        }


def emotion_from_appraisal(appraisal: Appraisal) -> EmotionState:
    """
    由 OCC 评估推导情绪状态。

    负面事件（desirability < 0）：
    - 可控性主导（能做点什么）-> anger
    - 合意性主导（证实自我怀疑）-> sadness
    正面事件（desirability > 0）：
    - 新奇性高 -> surprise，否则 -> joy
    中性事件 -> neutral

    Args:
        appraisal: OCC 评估结果
    """
    d = appraisal.desirability
    valence = clamp(d, -1.0, 1.0)

    if abs(d) < NEUTRAL_DESIRABILITY:
        primary = "neutral"
    elif d < 0:
        # 可控性高 -> 愤怒（我能对此做点什么），可控性低 -> 悲伤/羞耻
        primary = "anger" if appraisal.controllability >= 0.5 else "sadness"
    else:
        primary = "surprise" if appraisal.novelty >= 0.7 else "joy"

    intensity = clamp(
        max(abs(d), appraisal.relevance * abs(d), appraisal.novelty * 0.5)
    )

    return EmotionState(
        primary=primary,
        secondary="neutral",
        intensity=intensity,
        valence=valence,
        ambivalence=False,
    )


def mix_weight(emotion_intensity: float) -> float:
    """
    双通道行为引导的混合权重：情绪越多，情感通道占比越高。

    mix = 0.2 + 0.6 * sigmoid(12 * (intensity - 0.5))
    端点匹配：情绪 0 -> 0.2，情绪 0.5 -> 0.5，情绪 1.0 -> 0.8
    """
    intensity = clamp(emotion_intensity)
    return 0.2 + 0.6 * sigmoid(12.0 * (intensity - 0.5))


def dual_channel_guidance(
    rational_cue: str,
    emotional_cue: str,
    emotion_intensity: float,
) -> Dict[str, object]:
    """
    将冷/热通道文本与混合权重渲染为自然语言引导。

    Args:
        rational_cue: 冷通道（理性）引导文本
        emotional_cue: 热通道（情感）引导文本
        emotion_intensity: 当前情绪强度 [0, 1]

    Returns:
        含混合权重、冷热占比与最终引导文本的字典
    """
    mix = mix_weight(emotion_intensity)
    rational_share = 1.0 - mix
    emotional_share = mix
    guidance = (
        f"当前状态倾向 {rational_share * 100:.0f}% 理性、{emotional_share * 100:.0f}% 情感。"
        f"理性导向：{rational_cue}；情感导向：{emotional_cue}。"
    )
    return {
        "mix_weight": mix,
        "rational_share": rational_share,
        "emotional_share": emotional_share,
        "guidance": guidance,
    }