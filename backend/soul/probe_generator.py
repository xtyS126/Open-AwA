"""
兴趣探针生成器。
根据用户配置的 probe_flags 生成 InterestProbe 让用户确认/拒绝。

三种触发条件：
1. low_confidence: 查询 confidence < 0.5 的 ProfileFact，生成确认探针
2. new_interest: 检测到新关键词无法归类到现有分类时生成探针（基于 inferred 事实）
3. periodic_review: 每 20 轮对话触发一次画像复核（turns_since_last_extract % 20 == 0）

注意：InterestProbe 模型无 fact_id 字段，通过 reasoning.fact_id 存储 ProfileFact.id 引用，
通过查询已有探针的 reasoning JSON 在内存中去重，避免重复生成。
"""

from typing import Any, Dict, List, Optional

from loguru import logger
from sqlalchemy.orm import Session

from db.models import InterestProbe, ProfileExtractionState, ProfileFact


class ProbeGenerator:
    """探针生成器：根据用户配置的 flags 生成兴趣探针。"""

    # 每 20 轮触发一次定期复核
    PERIODIC_REVIEW_INTERVAL = 20
    # 低置信度阈值：低于此值生成确认探针
    LOW_CONFIDENCE_THRESHOLD = 0.5
    # 定期复核查询的置信度下限：只复核高置信度事实
    PERIODIC_REVIEW_MIN_CONFIDENCE = 0.7
    # 每次生成探针的最大数量（各类触发器独立限制）
    MAX_LOW_CONFIDENCE_PROBES = 5
    MAX_NEW_INTEREST_PROBES = 3
    MAX_PERIODIC_REVIEW_PROBES = 3

    async def generate_probes(
        self,
        user_id: str,
        db: Session,
        flags: Optional[Dict[str, bool]] = None,
    ) -> List[InterestProbe]:
        """
        根据用户配置生成探针。

        Args:
            user_id: 用户 ID
            db: 数据库 session
            flags: 探针触发条件 flags，None 时从 ProfileExtractionState 读取

        Returns:
            生成的探针列表（已持久化到数据库）
        """
        if flags is None:
            state = db.query(ProfileExtractionState).filter(
                ProfileExtractionState.user_id == user_id
            ).first()
            flags = state.probe_flags if state else {}

        # 所有触发条件都禁用时直接返回空列表
        if not any(flags.values()):
            return []

        # 探针生成失败显式传播（不静默吞）：由调用方决定补偿采样策略，
        # 未生成的探针不会在下次采样中被重复忽略
        generated: List[InterestProbe] = []

        if flags.get("low_confidence"):
            generated.extend(await self._generate_low_confidence_probes(user_id, db))

        if flags.get("new_interest"):
            generated.extend(await self._generate_new_interest_probes(user_id, db))

        if flags.get("periodic_review"):
            generated.extend(await self._generate_periodic_review_probes(user_id, db))

        return generated

    def _fetch_existing_fact_ids(self, user_id: str, db: Session) -> set:
        """
        查询该用户已有探针（任意状态）关联的 fact_id 集合，用于去重。

        InterestProbe 无 fact_id 字段，fact_id 存储在 reasoning JSON 中，
        此处在内存中提取以避免依赖数据库 JSON 查询函数（兼容 SQLite/PostgreSQL）。

        Args:
            user_id: 用户 ID
            db: 数据库 session

        Returns:
            已生成过探针的 ProfileFact.id 集合
        """
        existing_probes = db.query(InterestProbe).filter(
            InterestProbe.user_id == user_id,
        ).all()

        fact_ids: set = set()
        for probe in existing_probes:
            reasoning = probe.reasoning or {}
            fact_id = reasoning.get("fact_id")
            if fact_id:
                fact_ids.add(fact_id)
        return fact_ids

    def _fetch_existing_hypothesis_values(self, user_id: str, db: Session, trigger: str) -> set:
        """
        查询该用户指定触发器类型已有探针的 fact_value 集合，用于无 fact_id 场景的二级去重。

        Args:
            user_id: 用户 ID
            db: 数据库 session
            trigger: 触发器类型（low_confidence/new_interest/periodic_review）

        Returns:
            已存在探针的 fact_value 集合
        """
        existing_probes = db.query(InterestProbe).filter(
            InterestProbe.user_id == user_id,
        ).all()

        values: set = set()
        for probe in existing_probes:
            reasoning = probe.reasoning or {}
            if reasoning.get("trigger") == trigger:
                fact_value = reasoning.get("fact_value")
                if fact_value:
                    values.add(fact_value)
        return values

    async def _generate_low_confidence_probes(
        self, user_id: str, db: Session
    ) -> List[InterestProbe]:
        """
        低置信度探针：confidence < 0.5 的 ProfileFact 生成确认探针。

        查询条件：
        - user_id 匹配
        - is_active == True
        - confidence < 0.5
        - 未已生成过探针（通过 reasoning.fact_id 去重）

        Args:
            user_id: 用户 ID
            db: 数据库 session

        Returns:
            生成的探针列表
        """
        low_conf_facts = db.query(ProfileFact).filter(
            ProfileFact.user_id == user_id,
            ProfileFact.is_active == True,  # noqa: E712 SQLAlchemy 需要布尔值比较
            ProfileFact.confidence < self.LOW_CONFIDENCE_THRESHOLD,
        ).order_by(
            ProfileFact.confidence.asc()
        ).limit(self.MAX_LOW_CONFIDENCE_PROBES * 2).all()

        if not low_conf_facts:
            return []

        existing_fact_ids = self._fetch_existing_fact_ids(user_id, db)

        probes: List[InterestProbe] = []
        for fact in low_conf_facts:
            if len(probes) >= self.MAX_LOW_CONFIDENCE_PROBES:
                break

            # 通过 reasoning.fact_id 去重
            if fact.id in existing_fact_ids:
                continue

            probe = InterestProbe(
                user_id=user_id,
                hypothesis=f"我观察到你可能偏好: {fact.fact_value}",
                reasoning={
                    "fact_id": fact.id,
                    "fact_key": fact.fact_key,
                    "fact_value": fact.fact_value,
                    "category": fact.category,
                    "confidence": fact.confidence,
                    "source_type": fact.source_type,
                    "trigger": "low_confidence",
                },
                status="pending",
                probe_question=f"是否确认: {fact.fact_value}?",
            )
            db.add(probe)
            probes.append(probe)
            existing_fact_ids.add(fact.id)

        if probes:
            db.commit()
            for p in probes:
                db.refresh(p)
            logger.bind(
                user_id=user_id,
                trigger="low_confidence",
                probe_count=len(probes),
            ).info("低置信度探针生成完成")

        return probes

    async def _generate_new_interest_probes(
        self, user_id: str, db: Session
    ) -> List[InterestProbe]:
        """
        新兴趣不确定探针：基于最近提取的 inferred 事实生成确认探针。

        简化实现：查询最近新增的 source_type='inferred' 事实，
        让用户确认推测是否准确（LLM 判断归类为可选增强，此处不调用 LLM）。

        查询条件：
        - user_id 匹配
        - is_active == True
        - source_type == 'inferred'
        - 按 first_observed_at 倒序取最近若干条
        - 未已生成过探针（通过 reasoning.fact_id 去重）

        Args:
            user_id: 用户 ID
            db: 数据库 session

        Returns:
            生成的探针列表
        """
        recent_inferred = db.query(ProfileFact).filter(
            ProfileFact.user_id == user_id,
            ProfileFact.is_active == True,  # noqa: E712
            ProfileFact.source_type == "inferred",
        ).order_by(
            ProfileFact.first_observed_at.desc()
        ).limit(self.MAX_NEW_INTEREST_PROBES * 2).all()

        if not recent_inferred:
            return []

        existing_fact_ids = self._fetch_existing_fact_ids(user_id, db)

        probes: List[InterestProbe] = []
        for fact in recent_inferred:
            if len(probes) >= self.MAX_NEW_INTEREST_PROBES:
                break

            # 通过 reasoning.fact_id 去重
            if fact.id in existing_fact_ids:
                continue

            probe = InterestProbe(
                user_id=user_id,
                hypothesis=f"我推测你对以下内容感兴趣: {fact.fact_value}",
                reasoning={
                    "fact_id": fact.id,
                    "fact_key": fact.fact_key,
                    "fact_value": fact.fact_value,
                    "category": fact.category,
                    "trigger": "new_interest",
                },
                status="pending",
                probe_question=f"你对以下内容感兴趣吗: {fact.fact_value}?",
            )
            db.add(probe)
            probes.append(probe)
            existing_fact_ids.add(fact.id)

        if probes:
            db.commit()
            for p in probes:
                db.refresh(p)
            logger.bind(
                user_id=user_id,
                trigger="new_interest",
                probe_count=len(probes),
            ).info("新兴趣探针生成完成")

        return probes

    async def _generate_periodic_review_probes(
        self, user_id: str, db: Session
    ) -> List[InterestProbe]:
        """
        定期复核探针：turns_since_last_extract % 20 == 0 时触发。

        查询高置信度事实（>= 0.7）让用户复核是否仍然准确。
        不通过 fact_id 去重（允许同一事实在不同周期被复核），
        但通过 fact_value + review_turns 避免同一轮次重复生成。

        Args:
            user_id: 用户 ID
            db: 数据库 session

        Returns:
            生成的探针列表
        """
        state = db.query(ProfileExtractionState).filter(
            ProfileExtractionState.user_id == user_id
        ).first()

        if state is None:
            return []

        turns = state.turns_since_last_extract or 0
        # 0 轮不触发（刚提取完），必须达到 PERIODIC_REVIEW_INTERVAL 的整数倍
        if turns == 0 or turns % self.PERIODIC_REVIEW_INTERVAL != 0:
            return []

        high_conf_facts = db.query(ProfileFact).filter(
            ProfileFact.user_id == user_id,
            ProfileFact.is_active == True,  # noqa: E712
            ProfileFact.confidence >= self.PERIODIC_REVIEW_MIN_CONFIDENCE,
        ).order_by(
            ProfileFact.confidence.desc()
        ).limit(self.MAX_PERIODIC_REVIEW_PROBES * 2).all()

        if not high_conf_facts:
            return []

        # 同一轮次内避免重复生成（通过 fact_value + review_turns 二级去重）
        existing_review_values = self._fetch_existing_hypothesis_values(user_id, db, "periodic_review")

        probes: List[InterestProbe] = []
        for fact in high_conf_facts:
            if len(probes) >= self.MAX_PERIODIC_REVIEW_PROBES:
                break

            # 同一轮次已生成过该 fact 的复核探针则跳过
            # 通过 fact_value + review_turns 组合键判断
            review_key = f"{fact.fact_value}|turns={turns}"
            if review_key in existing_review_values:
                continue

            probe = InterestProbe(
                user_id=user_id,
                hypothesis=f"复核: 以下画像是否仍然准确: {fact.fact_value}",
                reasoning={
                    "fact_id": fact.id,
                    "fact_key": fact.fact_key,
                    "fact_value": fact.fact_value,
                    "category": fact.category,
                    "confidence": fact.confidence,
                    "trigger": "periodic_review",
                    "review_turns": turns,
                },
                status="pending",
                probe_question=f"以下画像是否仍然准确: {fact.fact_value}?",
            )
            db.add(probe)
            probes.append(probe)
            existing_review_values.add(review_key)

        if probes:
            db.commit()
            for p in probes:
                db.refresh(p)
            logger.bind(
                user_id=user_id,
                trigger="periodic_review",
                probe_count=len(probes),
                review_turns=turns,
            ).info("定期复核探针生成完成")

        return probes


# 模块级单例
_probe_generator: Optional[ProbeGenerator] = None


def get_probe_generator() -> ProbeGenerator:
    """获取探针生成器单例。"""
    global _probe_generator
    if _probe_generator is None:
        _probe_generator = ProbeGenerator()
    return _probe_generator
