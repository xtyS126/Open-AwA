"""
用户画像置信度计算与衰减模型。

参考: ACM CHI '24 — "My agent understands me better"
实现简化的指数衰减 + 动态巩固机制。
"""

import math
import uuid
from datetime import datetime, timezone
from typing import Optional

from .profile_dimensions import (
    PROFILE_CATEGORIES,
    SOURCE_BASE_CONFIDENCE,
    CONFIDENCE_HIGH,
    CONFIDENCE_MEDIUM,
    CONFIDENCE_ARCHIVE,
)


class ConfidenceModel:
    """
    画像事实的置信度计算器。

    每条画像事实的有效置信度 = 基础置信度 * 衰减因子 + 验证加成。
    衰减速率由画像类别和来源类型决定，频繁访问的事实衰减更慢。
    """

    @staticmethod
    def calculate_effective_confidence(
        base_confidence: float,
        category: str,
        source_type: str,
        last_updated_at: datetime,
        access_count: int,
        verification_count: int,
    ) -> float:
        """
        计算画像事实的有效置信度。

        Args:
            base_confidence: 存储的基础置信度 (0.0-1.0)
            category: 画像维度分类
            source_type: 来源类型
            last_updated_at: 最后更新时间
            access_count: 访问次数
            verification_count: 用户验证次数

        Returns:
            0.0-1.0 的有效置信度
        """
        now = datetime.now(timezone.utc)
        days_since_update = max(0, (now - last_updated_at).days)

        # 类别特定的基础衰减率
        category_config = PROFILE_CATEGORIES.get(category, {})
        decay_rate = category_config.get("decay_rate", 0.01)

        # 来源类型调整
        if source_type in ("explicit", "manual"):
            decay_rate *= 0.5  # 用户明确提供的信息衰减更慢
        elif source_type == "behavioral":
            decay_rate *= 1.2  # 行为推断衰减稍快

        # 巩固因子：每次访问/验证降低有效衰减率
        total_interactions = access_count + verification_count * 2
        consolidation = 1.0 + 0.15 * math.log(1 + total_interactions)
        effective_decay = decay_rate / consolidation

        # 时间衰减
        decay_factor = math.exp(-effective_decay * days_since_update)

        # 验证加成（每验证一次 +0.03，上限 0.15）
        verification_bonus = min(0.15, verification_count * 0.03)

        effective = base_confidence * decay_factor + verification_bonus
        return min(1.0, max(0.0, effective))

    @staticmethod
    def get_base_confidence(source_type: str) -> float:
        """获取来源类型对应的基础置信度"""
        return SOURCE_BASE_CONFIDENCE.get(source_type, 0.50)

    @staticmethod
    def should_extract(
        last_extraction_at: Optional[datetime],
        conversation_turns_since_last: int,
        min_interval_minutes: int = 30,
        min_turns: int = 10,
    ) -> tuple[bool, str]:
        """
        判断是否应触发新一轮画像提取。

        Args:
            last_extraction_at: 上次提取时间
            conversation_turns_since_last: 自上次提取以来的对话轮次
            min_interval_minutes: 最小提取间隔（分钟）
            min_turns: 最小对话轮次

        Returns:
            (should_extract, reason) 元组
        """
        if last_extraction_at is None:
            return True, "首次提取：无历史提取记录"

        now = datetime.now(timezone.utc)
        minutes_since = (now - last_extraction_at).total_seconds() / 60

        if minutes_since < min_interval_minutes:
            return False, f"距上次提取仅 {minutes_since:.0f} 分钟，未达最小间隔 {min_interval_minutes} 分钟"

        if conversation_turns_since_last < min_turns:
            return False, f"自上次提取以来仅 {conversation_turns_since_last} 轮对话，未达最小轮次 {min_turns}"

        return True, f"满足提取条件：距上次 {minutes_since:.0f} 分钟，{conversation_turns_since_last} 轮对话"

    @staticmethod
    def get_confidence_label(confidence: float) -> str:
        """获取置信度标签"""
        if confidence >= CONFIDENCE_HIGH:
            return "高"
        elif confidence >= CONFIDENCE_MEDIUM:
            return "中"
        else:
            return "低"

    @staticmethod
    def is_archived(confidence: float) -> bool:
        """判断是否应归档"""
        return confidence < CONFIDENCE_ARCHIVE


def generate_fact_id() -> str:
    """生成画像事实的唯一 ID"""
    return f"pf_{uuid.uuid4().hex[:12]}"


def generate_extraction_log_id() -> str:
    """生成提取日志的唯一 ID"""
    return f"pel_{uuid.uuid4().hex[:12]}"
