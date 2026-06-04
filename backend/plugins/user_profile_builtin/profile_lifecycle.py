"""
画像生命周期管理器，负责画像事实的衰减、巩固、归档和清理。

参考: ACM CHI '24 的指数衰减 + 动态巩固模型
"""

from datetime import datetime, timezone
from typing import Any, Dict, List

from loguru import logger
from sqlalchemy.orm import Session

from db.models import ProfileFact
from .profile_confidence import ConfidenceModel


class ProfileLifecycle:
    """
    画像生命周期管理器。

    负责:
    - 定期刷新有效置信度（重新计算衰减后的值）
    - 归档低置信度事实（标记 is_active=False）
    - 清理过期事实（永久删除已归档的超期事实）
    - 统计报告
    """

    # 归档后保留天数（超过后永久删除）
    ARCHIVED_RETENTION_DAYS = 90

    def __init__(self, db: Session, user_id: str):
        self.db = db
        self.user_id = user_id

    def refresh_all_facts(self) -> Dict[str, int]:
        """
        刷新所有画像事实的有效置信度。

        遍历所有活跃事实，重新计算衰减后的置信度。
        将低于归档阈值的事实标记为 inactive。
        """
        facts = self.db.query(ProfileFact).filter(
            ProfileFact.user_id == self.user_id,
            ProfileFact.is_active == True,
        ).all()

        now = datetime.now(timezone.utc)
        stats = {"refreshed": 0, "archived": 0, "unchanged": 0}

        for fact in facts:
            effective = ConfidenceModel.calculate_effective_confidence(
                base_confidence=fact.confidence,
                category=fact.category,
                source_type=fact.source_type,
                last_updated_at=fact.last_updated_at,
                access_count=fact.access_count,
                verification_count=fact.verification_count,
            )

            if ConfidenceModel.is_archived(effective):
                fact.is_active = False
                fact.fact_metadata = fact.fact_metadata or {}
                fact.fact_metadata["archived_at"] = now.isoformat()
                fact.fact_metadata["archived_confidence"] = effective
                stats["archived"] += 1
                logger.bind(
                    user_id=self.user_id,
                    fact_key=f"{fact.category}:{fact.fact_key}",
                    effective_confidence=effective,
                ).info("画像事实已归档")
            else:
                fact.confidence = round(min(1.0, effective), 2)
                fact.access_count += 1
                fact.last_accessed_at = now
                stats["refreshed"] += 1

        self.db.commit()
        return stats

    def archive_low_quality(self) -> int:
        """
        归档低质量画像事实。
        低质量定义：有效置信度 < CONFIDENCE_ARCHIVE (0.15)
        """
        facts = self.db.query(ProfileFact).filter(
            ProfileFact.user_id == self.user_id,
            ProfileFact.is_active == True,
        ).all()

        archived = 0
        now = datetime.now(timezone.utc)

        for fact in facts:
            effective = ConfidenceModel.calculate_effective_confidence(
                base_confidence=fact.confidence,
                category=fact.category,
                source_type=fact.source_type,
                last_updated_at=fact.last_updated_at,
                access_count=fact.access_count,
                verification_count=fact.verification_count,
            )

            if ConfidenceModel.is_archived(effective):
                fact.is_active = False
                fact.fact_metadata = fact.fact_metadata or {}
                fact.fact_metadata["archived_at"] = now.isoformat()
                fact.fact_metadata["archived_confidence"] = effective
                archived += 1

        self.db.commit()
        logger.bind(user_id=self.user_id, archived=archived).info("低质量画像事实已归档")
        return archived

    def purge_expired_archived(self) -> int:
        """
        永久删除已归档且超过保留期的画像事实。
        默认保留期为 90 天。
        """
        cutoff = datetime.now(timezone.utc)
        # 使用 Python 计算截止日期
        from datetime import timedelta
        cutoff = cutoff - timedelta(days=self.ARCHIVED_RETENTION_DAYS)

        # 查找过期的非活跃事实
        expired = self.db.query(ProfileFact).filter(
            ProfileFact.user_id == self.user_id,
            ProfileFact.is_active == False,
            ProfileFact.last_updated_at < cutoff,
        ).all()

        purged = 0
        for fact in expired:
            self.db.delete(fact)
            purged += 1

        self.db.commit()
        logger.bind(user_id=self.user_id, purged=purged).info("过期归档画像事实已清理")
        return purged

    def enhance_fact(
        self, fact_id: str, boost_amount: float = 0.10
    ) -> Dict[str, Any]:
        """
        巩固特定画像事实（用户验证时调用）。

        Args:
            fact_id: 事实 ID
            boost_amount: 提升的置信度值

        Returns:
            更新后的事实信息
        """
        fact = self.db.query(ProfileFact).filter(
            ProfileFact.id == fact_id,
            ProfileFact.user_id == self.user_id,
        ).first()

        if not fact:
            raise ValueError(f"画像事实不存在: {fact_id}")

        fact.verification_count += 1
        fact.confidence = min(1.0, fact.confidence + boost_amount)
        fact.last_updated_at = datetime.now(timezone.utc)
        fact.source_type = "feedback" if fact.source_type != "manual" else "manual"

        self.db.commit()
        return {
            "id": fact.id,
            "category": fact.category,
            "fact_key": fact.fact_key,
            "fact_value": fact.fact_value,
            "confidence": fact.confidence,
            "verification_count": fact.verification_count,
        }

    def weaken_fact(self, fact_id: str, penalty: float = 0.20) -> Dict[str, Any]:
        """
        削弱特定画像事实的置信度（用户否定时调用）。

        Args:
            fact_id: 事实 ID
            penalty: 降低的置信度值

        Returns:
            更新后的事实信息
        """
        fact = self.db.query(ProfileFact).filter(
            ProfileFact.id == fact_id,
            ProfileFact.user_id == self.user_id,
        ).first()

        if not fact:
            raise ValueError(f"画像事实不存在: {fact_id}")

        fact.confidence = max(0.05, fact.confidence - penalty)
        fact.last_updated_at = datetime.now(timezone.utc)

        # 如果置信度过低，直接归档
        if ConfidenceModel.is_archived(fact.confidence):
            fact.is_active = False
            fact.fact_metadata = fact.fact_metadata or {}
            fact.fact_metadata["archived_at"] = datetime.now(timezone.utc).isoformat()
            fact.fact_metadata["archived_reason"] = "用户否定"

        self.db.commit()
        return {
            "id": fact.id,
            "category": fact.category,
            "fact_key": fact.fact_key,
            "fact_value": fact.fact_value,
            "confidence": fact.confidence,
            "is_active": fact.is_active,
        }

    def get_stats(self) -> Dict[str, Any]:
        """获取用户画像的统计信息"""
        active_facts = self.db.query(ProfileFact).filter(
            ProfileFact.user_id == self.user_id,
            ProfileFact.is_active == True,
        ).all()

        archived_facts = self.db.query(ProfileFact).filter(
            ProfileFact.user_id == self.user_id,
            ProfileFact.is_active == False,
        ).all()

        # 类别分布
        category_counts: Dict[str, int] = {}
        for f in active_facts:
            category_counts[f.category] = category_counts.get(f.category, 0) + 1

        # 置信度分布
        confidence_levels = {"高": 0, "中": 0, "低": 0}
        for f in active_facts:
            label = ConfidenceModel.get_confidence_label(f.confidence)
            confidence_levels[label] += 1

        # 来源分布
        source_counts: Dict[str, int] = {}
        for f in active_facts:
            source_counts[f.source_type] = source_counts.get(f.source_type, 0) + 1

        # 总维度数（有 ≥1 个事实的类别数）
        dimensions_filled = len([c for c, n in category_counts.items() if n > 0])
        total_dimensions = 8  # 不含 custom

        return {
            "total_active_facts": len(active_facts),
            "total_archived_facts": len(archived_facts),
            "category_distribution": category_counts,
            "confidence_distribution": confidence_levels,
            "source_distribution": source_counts,
            "dimensions_filled": dimensions_filled,
            "total_dimensions": total_dimensions,
            "completeness_pct": round(dimensions_filled / total_dimensions * 100, 1),
            "avg_confidence": round(
                sum(f.confidence for f in active_facts) / max(len(active_facts), 1), 2
            ),
        }
