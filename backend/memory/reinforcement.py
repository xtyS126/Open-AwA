"""
记忆强化机制实现。
提供基于访问频率、重要度和关联性的记忆权重强化函数。
"""

from typing import Optional


def access_reinforcement(
    access_count: int,
    max_count: int = 100,
    reinforcement_factor: float = 0.1
) -> float:
    """
    基于访问次数的强化函数。
    
    访问次数越多，记忆权重越高（但存在上限）。
    
    公式: boost = min(access_count / max_count, 1.0) * reinforcement_factor
    
    Args:
        access_count: 访问次数
        max_count: 最大访问次数（达到此次数后不再增加），默认100次
        reinforcement_factor: 最大强化因子，默认0.1（即最多增加10%权重）
    
    Returns:
        float: 强化后的权重增量（0.0-reinforcement_factor）
    """
    if access_count <= 0:
        return 0.0
    
    normalized_count = min(access_count / max_count, 1.0)
    boost = normalized_count * reinforcement_factor
    
    return max(0.0, min(reinforcement_factor, boost))


def importance_reinforcement(
    importance: float,
    reinforcement_factor: float = 0.2
) -> float:
    """
    基于重要度的强化函数。
    
    重要度越高的记忆，获得越多的权重强化。
    
    公式: boost = importance * reinforcement_factor
    
    Args:
        importance: 记忆重要度（0.0-1.0）
        reinforcement_factor: 强化因子，默认0.2
    
    Returns:
        float: 强化后的权重增量（0.0-reinforcement_factor）
    """
    if importance <= 0.0:
        return 0.0
    
    boost = importance * reinforcement_factor
    return max(0.0, min(reinforcement_factor, boost))


def recency_reinforcement(
    days_since_access: float,
    max_days: float = 7.0,
    reinforcement_factor: float = 0.15
) -> float:
    """
    基于时间新鲜度的强化函数。
    
    最近访问的记忆获得更高的权重强化。
    
    公式: boost = max(0, 1.0 - days_since_access / max_days) * reinforcement_factor
    
    Args:
        days_since_access: 距离上次访问的天数
        max_days: 最大天数，超过此天数不再强化，默认7天
        reinforcement_factor: 最大强化因子，默认0.15
    
    Returns:
        float: 强化后的权重增量（0.0-reinforcement_factor）
    """
    if days_since_access <= 0.0:
        return reinforcement_factor
    
    if days_since_access >= max_days:
        return 0.0
    
    freshness = 1.0 - (days_since_access / max_days)
    boost = freshness * reinforcement_factor
    
    return max(0.0, min(reinforcement_factor, boost))


def combined_reinforcement(
    access_count: int,
    importance: float,
    days_since_access: float,
    access_weight: float = 0.3,
    importance_weight: float = 0.4,
    recency_weight: float = 0.3
) -> float:
    """
    综合强化函数，结合访问次数、重要度和时间新鲜度。
    
    Args:
        access_count: 访问次数
        importance: 记忆重要度（0.0-1.0）
        days_since_access: 距离上次访问的天数
        access_weight: 访问次数权重，默认0.3
        importance_weight: 重要度权重，默认0.4
        recency_weight: 时间新鲜度权重，默认0.3
    
    Returns:
        float: 综合强化后的权重增量
    """
    access_boost = access_reinforcement(access_count)
    importance_boost = importance_reinforcement(importance)
    recency_boost = recency_reinforcement(days_since_access)
    
    total_boost = (
        access_boost * access_weight +
        importance_boost * importance_weight +
        recency_boost * recency_weight
    )
    
    return max(0.0, min(1.0, total_boost))
