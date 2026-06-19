"""
记忆衰减机制实现。
提供指数衰减、线性衰减等函数，用于计算记忆权重随时间的衰减。
"""

from datetime import datetime, timezone
from typing import Optional


def exponential_decay(
    last_access: datetime,
    half_life_days: float = 30.0,
    current_time: Optional[datetime] = None
) -> float:
    """
    指数衰减函数。
    
    公式: weight = 0.5 ^ (days_elapsed / half_life_days)
    
    Args:
        last_access: 最后访问时间
        half_life_days: 半衰期（天），默认30天
        current_time: 当前时间，默认使用UTC时间
    
    Returns:
        float: 衰减后的权重（0.0-1.0）
    """
    if current_time is None:
        current_time = datetime.now(timezone.utc)
    
    # 确保时间有时区信息
    if last_access.tzinfo is None:
        last_access = last_access.replace(tzinfo=timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    
    days_elapsed = (current_time - last_access).total_seconds() / 86400.0
    
    if days_elapsed <= 0:
        return 1.0
    
    decay_factor = 0.5 ** (days_elapsed / half_life_days)
    return max(0.0, min(1.0, decay_factor))


def linear_decay(
    last_access: datetime,
    max_days: float = 90.0,
    current_time: Optional[datetime] = None
) -> float:
    """
    线性衰减函数。
    
    公式: weight = 1.0 - (days_elapsed / max_days)
    
    Args:
        last_access: 最后访问时间
        max_days: 最大衰减天数，超过此天数权重为0，默认90天
        current_time: 当前时间，默认使用UTC时间
    
    Returns:
        float: 衰减后的权重（0.0-1.0）
    """
    if current_time is None:
        current_time = datetime.now(timezone.utc)
    
    # 确保时间有时区信息
    if last_access.tzinfo is None:
        last_access = last_access.replace(tzinfo=timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    
    days_elapsed = (current_time - last_access).total_seconds() / 86400.0
    
    if days_elapsed <= 0:
        return 1.0
    
    if days_elapsed >= max_days:
        return 0.0
    
    decay_factor = 1.0 - (days_elapsed / max_days)
    return max(0.0, min(1.0, decay_factor))


def step_decay(
    last_access: datetime,
    step_days: float = 7.0,
    decay_per_step: float = 0.1,
    current_time: Optional[datetime] = None
) -> float:
    """
    阶梯衰减函数。
    
    每经过 step_days 天，权重减少 decay_per_step。
    
    Args:
        last_access: 最后访问时间
        step_days: 衰减间隔天数，默认7天
        decay_per_step: 每次衰减的权重减少量，默认0.1
        current_time: 当前时间，默认使用UTC时间
    
    Returns:
        float: 衰减后的权重（0.0-1.0）
    """
    if current_time is None:
        current_time = datetime.now(timezone.utc)
    
    # 确保时间有时区信息
    if last_access.tzinfo is None:
        last_access = last_access.replace(tzinfo=timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    
    days_elapsed = (current_time - last_access).total_seconds() / 86400.0
    
    if days_elapsed <= 0:
        return 1.0
    
    steps = int(days_elapsed / step_days)
    decay_factor = 1.0 - (steps * decay_per_step)
    
    return max(0.0, min(1.0, decay_factor))


def no_decay(
    last_access: datetime,
    current_time: Optional[datetime] = None
) -> float:
    """
    无衰减函数，始终返回1.0。
    用于核心记忆（Core Memory）等不需要衰减的记忆层。
    
    Args:
        last_access: 最后访问时间（忽略）
        current_time: 当前时间（忽略）
    
    Returns:
        float: 始终返回1.0
    """
    return 1.0
