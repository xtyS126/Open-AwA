"""
陪伴状态管理器：心智引擎与数据库之间的持久化桥梁。

负责：
- 从 companion_states 表加载/创建 MentalEngine
- 将心智状态快照回写到 companion_states 表
- 持久化陪伴记忆与里程碑

默认信念维度与维度共振矩阵在此定义，供首次创建陪伴者时初始化。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from loguru import logger
from sqlalchemy.orm import Session

from companion.appraisal import EmotionState
from companion.belief_network import BeliefNetwork, clamp
from companion.cognition import Cognition
from companion.memory import CompanionMemory, sanitize_memory_content
from companion.mental_engine import MentalEngine
from db.models import CompanionMemory as CompanionMemoryRow
from db.models import CompanionMilestone, CompanionState


# 陪伴者默认信念维度（初始值介于 [0, 1]）
DEFAULT_BELIEFS: Dict[str, float] = {
    "people_are_trustworthy": 0.6,   # 人是否值得信赖
    "self_worth": 0.5,               # 自我价值感
    "duty_above_desire": 0.5,        # 责任高于欲望
    "vulnerability_is_weakness": 0.3,  # 脆弱是否等于软弱
    "affection_for_user": 0.5,       # 对用户的好感度
}

# 维度共振矩阵（v9）：关联维度应力溢出会侵蚀本维度精度
DEFAULT_LINKS: Dict[str, List[str]] = {
    "people_are_trustworthy": ["self_worth"],
    "self_worth": ["people_are_trustworthy", "vulnerability_is_weakness"],
    "duty_above_desire": ["self_worth"],
    "vulnerability_is_weakness": ["self_worth"],
    "affection_for_user": ["people_are_trustworthy"],
}


class CompanionStateManager:
    """陪伴者心智状态的持久化管理器。"""

    def __init__(self, db: Session) -> None:
        self.db = db

    # ---- 引擎加载与创建 ----

    def get_or_create_engine(
        self,
        user_id: str,
        role_id: str,
        beliefs: Optional[Dict[str, float]] = None,
        links: Optional[Dict[str, List[str]]] = None,
    ) -> MentalEngine:
        """按用户与角色加载既有心智引擎，不存在则创建新引擎。"""
        state = self._load_state(user_id, role_id)
        resolved_links = links or DEFAULT_LINKS
        if state:
            engine = MentalEngine({}, links=resolved_links)
            engine.network = BeliefNetwork.from_dict(state["beliefs"], links=resolved_links)
            engine.emotion = self._restore_emotion(state.get("emotion"))
            engine.cognition = Cognition.from_dict(state.get("cognition") or {})
            engine.turn = int(state.get("turn", 0))
            engine.memories = self._load_memories(user_id, role_id)
        else:
            engine = MentalEngine(beliefs or DEFAULT_BELIEFS, links=resolved_links)
        return engine

    def _load_state(self, user_id: str, role_id: str) -> Optional[Dict[str, Any]]:
        """从数据库读取心智状态快照。"""
        row = (
            self.db.query(CompanionState)
            .filter(
                CompanionState.user_id == user_id,
                CompanionState.role_id == role_id,
            )
            .first()
        )
        if row is None:
            return None
        return {
            "beliefs": row.beliefs_json or DEFAULT_BELIEFS,
            "emotion": row.emotion_json or {},
            "cognition": row.cognition_json or {},
            "turn": row.turn or 0,
        }

    @staticmethod
    def _restore_emotion(data: Dict[str, Any]) -> EmotionState:
        """从字典恢复情绪状态。"""
        return EmotionState(
            primary=str(data.get("primary", "neutral")),
            secondary=str(data.get("secondary", "neutral")),
            intensity=clamp(float(data.get("intensity", 0.0))),
            valence=clamp(float(data.get("valence", 0.0)), -1.0, 1.0),
            ambivalence=bool(data.get("ambivalence", False)),
        )

    def _load_memories(self, user_id: str, role_id: str) -> List[CompanionMemory]:
        """加载该用户与角色的陪伴记忆到引擎。"""
        rows = (
            self.db.query(CompanionMemoryRow)
            .filter(
                CompanionMemoryRow.user_id == user_id,
                CompanionMemoryRow.role_id == role_id,
            )
            .all()
        )
        return [
            CompanionMemory(
                id=row.id,
                content=row.content,
                memory_type=row.memory_type,
                emotional_intensity=row.emotional_intensity,
                personality_impact=row.personality_impact,
                created_turn=row.created_turn,
                keywords=row.keywords or [],
                consolidated=row.consolidated,
            )
            for row in rows
        ]

    # ---- 持久化 ----

    def save(
        self,
        user_id: str,
        role_id: str,
        engine: MentalEngine,
        bond_level: Optional[int] = None,
        count_conversation: bool = True,
    ) -> CompanionState:
        """将心智引擎快照回写到数据库（upsert）。

        Args:
            count_conversation: 是否计入一次对话；睡眠整合等非对话保存传 False。
        """
        now = datetime.now(timezone.utc)
        snapshot = engine.snapshot()

        row = (
            self.db.query(CompanionState)
            .filter(
                CompanionState.user_id == user_id,
                CompanionState.role_id == role_id,
            )
            .first()
        )

        if row is None:
            row = CompanionState(
                id=str(uuid.uuid4()),
                user_id=user_id,
                role_id=role_id,
                beliefs_json=snapshot["beliefs"],
                emotion_json=snapshot["emotion"],
                cognition_json=snapshot["cognition"],
                bond_level=bond_level if bond_level is not None else 1,
                turn=snapshot["turn"],
                total_conversations=1 if count_conversation else 0,
                first_met_at=now,
                last_interaction_at=now,
                updated_at=now,
            )
            self.db.add(row)
        else:
            row.beliefs_json = snapshot["beliefs"]
            row.emotion_json = snapshot["emotion"]
            row.cognition_json = snapshot["cognition"]
            if bond_level is not None:
                row.bond_level = bond_level
            row.turn = snapshot["turn"]
            if count_conversation:
                row.total_conversations += 1
            row.last_interaction_at = now
            row.updated_at = now

        self.db.commit()
        logger.bind(
            event="companion_state_saved",
            module="companion",
            user_id=user_id,
            turn=snapshot["turn"],
        ).debug("陪伴者心智状态已保存")
        return row

    def save_memory(self, user_id: str, role_id: str, memory: CompanionMemory) -> None:
        """持久化一条陪伴记忆（落库前统一做长度上限与 PII 脱敏）。"""
        row = CompanionMemoryRow(
            id=memory.id,
            user_id=user_id,
            role_id=role_id,
            content=sanitize_memory_content(memory.content),
            memory_type=memory.memory_type,
            emotional_intensity=memory.emotional_intensity,
            personality_impact=memory.personality_impact,
            created_turn=memory.created_turn,
            keywords=memory.keywords or [],
            consolidated=memory.consolidated,
        )
        self.db.add(row)
        self.db.commit()

    def record_milestone(
        self,
        user_id: str,
        role_id: str,
        milestone_type: str,
        detail: str,
        turn: int,
        belief_name: str = "",
    ) -> None:
        """记录一条心智里程碑。"""
        row = CompanionMilestone(
            id=str(uuid.uuid4()),
            user_id=user_id,
            role_id=role_id,
            milestone_type=milestone_type,
            belief_name=belief_name,
            detail=detail,
            turn=turn,
        )
        self.db.add(row)
        self.db.commit()