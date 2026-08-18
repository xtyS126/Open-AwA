"""
陪伴系统域 ORM 模型：情感深度系统的持久化模型。

- CompanionState：每用户的陪伴者心智状态（信念网络 / 情绪 / 认知 / 羁绊）
- CompanionMemory：陪伴记忆（情感显著性、人格影响、关键词）
- CompanionMilestone：心智里程碑（灾变、羁绊升级、纪念日等）

三者共享 db.models.base.Base，由 init_db 的 create_all 统一建表。
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import Boolean, DateTime, Float, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from db.models.base import Base


class CompanionState(Base):
    """陪伴者心智状态：以 user_id + role_id 定位一行。"""

    __tablename__ = "companion_states"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    user_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    role_id: Mapped[str] = mapped_column(String, index=True, default="")

    # 信念网络快照：{belief_name: {value, strain, load}}
    beliefs_json: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    # 情绪状态快照：{primary, secondary, intensity, valence, ambivalence}
    emotion_json: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    # 认知谱系快照：{fact_id: {state, transitions}}
    cognition_json: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)

    # 羁绊等级（1-10），随互动增长
    bond_level: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    # 总对话轮次
    turn: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # 总对话次数
    total_conversations: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    first_met_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_interaction_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )


class CompanionMemory(Base):
    """陪伴记忆：带情感显著性与人格影响的共享经历记录。"""

    __tablename__ = "companion_memories"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    user_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    role_id: Mapped[str] = mapped_column(String, index=True, default="")

    content: Mapped[str] = mapped_column(Text, default="")
    # first_meeting / emotional_moment / shared_experience / milestone / user_preference / inside_joke
    memory_type: Mapped[str] = mapped_column(String, default="shared_experience")

    # 情感显著性 [0, 1]
    emotional_intensity: Mapped[float] = mapped_column(Float, default=0.5)
    # 人格影响 [0, 1]
    personality_impact: Mapped[float] = mapped_column(Float, default=0.5)
    # 产生轮次
    created_turn: Mapped[int] = mapped_column(Integer, default=0)
    # 参与睡眠整合的关键词
    keywords: Mapped[List[str]] = mapped_column(JSON, default=list)
    consolidated: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )


class CompanionMilestone(Base):
    """心智里程碑：灾变、羁绊升级、纪念日等可庆祝事件。"""

    __tablename__ = "companion_milestones"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    user_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    role_id: Mapped[str] = mapped_column(String, index=True, default="")

    # catastrophe / bond_upgrade / first_meeting / anniversary
    milestone_type: Mapped[str] = mapped_column(String, default="catastrophe")
    # 关联信念维度（灾变时记录）
    belief_name: Mapped[str] = mapped_column(String, default="")
    detail: Mapped[str] = mapped_column(Text, default="")
    turn: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )