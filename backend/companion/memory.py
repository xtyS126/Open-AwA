"""
陪伴记忆模块：像人一样记忆，而非像数据库一样检索。

对应 NSP-roleplay 心智模型的「像人一样记忆」层。记忆按情感显著性、
人格影响与当前相关性被召回，而非按时间戳。

召回优先级：
priority = time_decay * 0.2 + personality_impact * 0.3
         + emotional_intensity * 0.2 + keyword_relevance * 0.3

闪光灯记忆：高情感事件抵抗正常遗忘曲线。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional


# 召回优先级各因子权重
TIME_DECAY_WEIGHT: float = 0.2
PERSONALITY_IMPACT_WEIGHT: float = 0.3
EMOTIONAL_INTENSITY_WEIGHT: float = 0.2
KEYWORD_RELEVANCE_WEIGHT: float = 0.3

# 遗忘曲线半衰期（轮次）：情感强度会拉长该值
BASE_HALF_LIFE: float = 30.0

# 陪伴记忆内容长度上限（与通用长期记忆上限保持一致）
MAX_COMPANION_MEMORY_CONTENT_CHARS: int = 500


def sanitize_memory_content(content: str) -> str:
    """
    对陪伴记忆内容做长度截断与 PII 脱敏。

    陪伴记忆 content 由抽取层 LLM 直出，复用通用记忆系统的 PII 脱敏
    工具（memory.pii_guard.scrub），并截断超长内容，避免 API key /
    私钥 / 证件号等敏感信息被写入库并被召回注入上下文。

    Args:
        content: 原始记忆内容。

    Returns:
        脱敏并截断后的内容；空值或非字符串原样返回。
    """
    if not isinstance(content, str) or not content:
        return content
    # 延迟导入避免循环依赖：memory.pii_guard 无 companion 依赖
    from memory.pii_guard import scrub as _pii_scrub

    scrubbed = _pii_scrub(content)
    if len(scrubbed) > MAX_COMPANION_MEMORY_CONTENT_CHARS:
        scrubbed = scrubbed[:MAX_COMPANION_MEMORY_CONTENT_CHARS]
    return scrubbed


@dataclass
class CompanionMemory:
    """单条陪伴记忆。"""

    id: str
    content: str
    memory_type: str = "shared_experience"  # 见路线图：first_meeting/emotional_moment 等
    emotional_intensity: float = 0.5        # 情感显著性 [0, 1]
    personality_impact: float = 0.5         # 人格影响 [0, 1]
    created_turn: int = 0                   # 产生轮次
    keywords: List[str] = field(default_factory=list)
    consolidated: bool = False              # 是否已参与睡眠整合


def time_decay(age: int, emotional_intensity: float) -> float:
    """
    时效性衰减：记忆越久越模糊，但高情感强度减缓衰减（闪光灯记忆）。

    Args:
        age: 记忆年龄（轮次差）
        emotional_intensity: 情感强度 [0, 1]
    """
    if age <= 0:
        return 1.0
    # 情感强度拉长半衰期：情感越强，半衰期越长，衰减越慢
    half_life = BASE_HALF_LIFE * (1.0 + emotional_intensity * 3.0)
    return math.pow(0.5, age / half_life)


def keyword_relevance(memory_keywords: List[str], current_keywords: List[str]) -> float:
    """关键词重叠度：记忆关键词与当前上下文关键词的重叠比例。"""
    if not memory_keywords or not current_keywords:
        return 0.0
    memory_set = set(memory_keywords)
    current_set = set(current_keywords)
    overlap = len(memory_set & current_set)
    if overlap == 0:
        return 0.0
    return overlap / len(memory_set)


def recall_priority(
    memory: CompanionMemory,
    current_turn: int,
    current_keywords: List[str],
) -> float:
    """计算记忆在给定上下文下的召回优先级。"""
    age = max(0, current_turn - memory.created_turn)
    td = time_decay(age, memory.emotional_intensity)
    kr = keyword_relevance(memory.keywords, current_keywords)
    return (
        td * TIME_DECAY_WEIGHT
        + memory.personality_impact * PERSONALITY_IMPACT_WEIGHT
        + memory.emotional_intensity * EMOTIONAL_INTENSITY_WEIGHT
        + kr * KEYWORD_RELEVANCE_WEIGHT
    )


def consolidate_memories(
    memories: List[CompanionMemory],
    current_turn: int,
) -> List[CompanionMemory]:
    """
    睡眠记忆整合：按关键词重叠度聚类相关记忆，合并为整合条目。

    简化实现：将关键词重叠度 >= 阈值且未整合的记忆聚为一组，
    每组生成一条整合记忆（保留最高情感强度与人格影响）。
    """
    threshold = 0.5
    clustered: List[CompanionMemory] = []
    remaining = [m for m in memories if not m.consolidated]

    while remaining:
        seed = remaining.pop(0)
        group = [seed]
        group_keywords = set(seed.keywords)
        idx = 0
        while idx < len(remaining):
            other = remaining[idx]
            if keyword_relevance(other.keywords, list(group_keywords)) >= threshold:
                group.append(other)
                group_keywords.update(other.keywords)
                remaining.pop(idx)
            else:
                idx += 1

        if len(group) == 1:
            seed.consolidated = True
            clustered.append(seed)
            continue

        # 合并组内记忆
        combined_content = "；".join(m.content for m in group)
        combined_memory = CompanionMemory(
            id=f"consolidated-{current_turn}-{len(clustered)}",
            content=combined_content,
            memory_type=seed.memory_type,
            emotional_intensity=max(m.emotional_intensity for m in group),
            personality_impact=max(m.personality_impact for m in group),
            created_turn=current_turn,
            keywords=sorted(group_keywords),
            consolidated=True,
        )
        clustered.append(combined_memory)

    return clustered