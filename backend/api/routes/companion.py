"""
陪伴系统 API 路由。

提供心智状态查询、每一轮心智更新（turn）以及陪伴事件检查。

心智更新接收「抽取层」产出的结构化结果（OCC 评估、受影响信念的加权误差、
认知更新、新记忆），交由确定性心智引擎计算，返回引导文本、情绪、触发里程碑
与涌现弧线，供注入聊天回复与前端展示。
"""
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api.dependencies import get_current_user
from companion.appraisal import Appraisal
from companion.extraction import extract_mental_state
from companion.memory import CompanionMemory
from companion.mental_engine import MentalExtraction
from companion.observer import detect_arcs
from companion.state_manager import CompanionStateManager
from db.models import CompanionMilestone, CompanionState, User, get_db

router = APIRouter(prefix="/companion", tags=["companion"])


# ──────────────────────────────────────────────
# 请求/响应模型
# ──────────────────────────────────────────────

class AppraisalIn(BaseModel):
    """OCC 事件评估输入。"""
    relevance: float = Field(default=0.5, ge=0.0, le=1.0, description="相关性")
    desirability: float = Field(default=0.0, ge=-1.0, le=1.0, description="合意性")
    controllability: float = Field(default=0.5, ge=0.0, le=1.0, description="可控性")
    novelty: float = Field(default=0.5, ge=0.0, le=1.0, description="新奇性")


class NewMemoryIn(BaseModel):
    """新陪伴记忆输入。"""
    content: str = Field(..., description="记忆内容")
    memory_type: str = Field(default="shared_experience", description="记忆类型")
    emotional_intensity: float = Field(default=0.5, ge=0.0, le=1.0, description="情感显著性")
    personality_impact: float = Field(default=0.5, ge=0.0, le=1.0, description="人格影响")
    keywords: List[str] = Field(default_factory=list, description="关键词")


class CognitionUpdateIn(BaseModel):
    """认知谱系转换输入。"""
    fact_id: str = Field(..., description="知识条目标识")
    event_type: str = Field(..., description="触发事件类型")


class TurnRequest(BaseModel):
    """一轮心智更新请求（由抽取层产出）。"""
    role_id: str = Field(default="", description="角色 ID；为空则使用默认陪伴状态")
    # 提供 user_message 时走自动抽取层（用 Haiku 档模型解析），忽略下方手动评估字段
    user_message: Optional[str] = Field(default=None, description="用户消息；非空时自动调用抽取层")
    appraisal: AppraisalIn = Field(default_factory=AppraisalIn, description="OCC 评估")
    weighted_errors: Dict[str, float] = Field(default_factory=dict, description="信念维度 -> 加权误差")
    cognition_updates: List[CognitionUpdateIn] = Field(default_factory=list, description="认知转换")
    new_memory: Optional[NewMemoryIn] = Field(default=None, description="新记忆")
    current_keywords: List[str] = Field(default_factory=list, description="当前上下文关键词")
    rational_cue: str = Field(default="", description="冷通道（理性）引导")
    emotional_cue: str = Field(default="", description="热通道（情感）引导")


class CompanionEventItem(BaseModel):
    """陪伴事件条目。"""
    type: str = Field(..., description="事件类型: bond_upgrade | milestone | diary_ready | inactivity_reminder")
    title: str = Field(..., description="通知标题")
    body: str = Field(..., description="通知正文")
    navigate_to: Optional[str] = Field(default=None, description="点击后导航的前端路由路径")


class CompanionCheckEventsResponse(BaseModel):
    """陪伴事件检查响应。"""
    success: bool = True
    events: List[CompanionEventItem] = Field(default_factory=list)
    checked_at: str = Field(default="", description="检查时间 ISO 8601")


# 纪念日（按天）的特殊节点
_MILESTONE_DAYS = {1, 7, 30, 100, 365}


def _state_of(db: Session, user_id: str, role_id: str) -> Optional[CompanionState]:
    """查询陪伴状态行。"""
    return (
        db.query(CompanionState)
        .filter(
            CompanionState.user_id == user_id,
            CompanionState.role_id == role_id,
        )
        .first()
    )


# ──────────────────────────────────────────────
# 状态查询
# ──────────────────────────────────────────────

@router.get("/state", summary="查询陪伴者心智状态")
async def get_companion_state(
    role_id: str = "",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """返回当前用户与指定角色的心智状态（信念/情绪/认知/羁绊）。"""
    manager = CompanionStateManager(db)
    engine = manager.get_or_create_engine(current_user.id, role_id)
    row = _state_of(db, current_user.id, role_id)

    return {
        "user_id": current_user.id,
        "role_id": role_id,
        "bond_level": row.bond_level if row else 1,
        "turn": engine.turn,
        "total_conversations": row.total_conversations if row else 0,
        "beliefs": engine.network.to_dict(),
        "emotion": engine.emotion.to_dict(),
        "guidance": engine.guidance_text(),
        "arcs": [
            {"belief": a.belief, "arc": a.arc}
            for a in detect_arcs({name: node.history for name, node in engine.network.nodes.items()})
        ],
        "first_met_at": row.first_met_at.isoformat() if row and row.first_met_at else None,
        "last_interaction_at": row.last_interaction_at.isoformat() if row and row.last_interaction_at else None,
    }


# ──────────────────────────────────────────────
# 每轮心智更新
# ──────────────────────────────────────────────

@router.post("/turn", summary="执行一轮心智更新")
async def process_companion_turn(
    request: TurnRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """提交抽取结果，执行确定性心智更新并返回引导与里程碑。"""
    manager = CompanionStateManager(db)
    engine = manager.get_or_create_engine(current_user.id, request.role_id)

    if request.user_message:
        # 自动抽取层：用 Haiku 档模型解析用户消息（可设置）
        try:
            extraction = await extract_mental_state(db, request.user_message, engine)
        except RuntimeError as exc:
            raise HTTPException(
                status_code=400,
                detail=f"抽取层失败（请检查 Haiku 档模型配置）: {exc}",
            )
        new_memory = extraction.new_memory
    else:
        new_memory = None
        if request.new_memory is not None:
            new_memory = CompanionMemory(
                id=f"mem-{datetime.now(timezone.utc).timestamp():.0f}",
                content=request.new_memory.content,
                memory_type=request.new_memory.memory_type,
                emotional_intensity=request.new_memory.emotional_intensity,
                personality_impact=request.new_memory.personality_impact,
                keywords=request.new_memory.keywords,
            )

        extraction = MentalExtraction(
            appraisal=Appraisal(
                relevance=request.appraisal.relevance,
                desirability=request.appraisal.desirability,
                controllability=request.appraisal.controllability,
                novelty=request.appraisal.novelty,
            ),
            weighted_errors=request.weighted_errors,
            cognition_updates=[(c.fact_id, c.event_type) for c in request.cognition_updates],
            new_memory=new_memory,
            current_keywords=request.current_keywords,
            rational_cue=request.rational_cue,
            emotional_cue=request.emotional_cue,
        )

    update = engine.process_turn(extraction)

    # 持久化状态与记忆
    manager.save(current_user.id, request.role_id, engine)
    if new_memory is not None:
        manager.save_memory(current_user.id, request.role_id, new_memory)
    for belief_name in update.milestones:
        manager.record_milestone(
            user_id=current_user.id,
            role_id=request.role_id,
            milestone_type="catastrophe",
            detail=f"信念维度 {belief_name} 触发灾变",
            turn=engine.turn,
            belief_name=belief_name,
        )

    logger.bind(
        event="companion_turn",
        module="companion",
        user_id=current_user.id,
        turn=engine.turn,
    ).info("陪伴者执行一轮心智更新")

    return {
        "turn": engine.turn,
        "emotion": update.emotion.to_dict(),
        "guidance": update.guidance,
        "milestones": update.milestones,
        "arcs": [{"belief": a.belief, "arc": a.arc} for a in update.arcs],
        "recalled_memories": [m.content for m in update.recalled_memories],
        "cognition_changes": update.cognition_changes,
    }


# ──────────────────────────────────────────────
# 睡眠整合
# ──────────────────────────────────────────────

@router.post("/sleep", summary="触发睡眠整合")
async def companion_sleep(
    role_id: str = "",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """执行睡眠整合管线：应变恢复、情绪衰减、记忆整合、人格存档、观察者分析。"""
    manager = CompanionStateManager(db)
    engine = manager.get_or_create_engine(current_user.id, role_id)
    result = engine.sleep()
    manager.save(current_user.id, role_id, engine, count_conversation=False)
    return {
        "success": True,
        "turn": engine.turn,
        "emotion": engine.emotion.to_dict(),
        "arcs": result["arcs"],
    }


# ──────────────────────────────────────────────
# 陪伴事件检查
# ──────────────────────────────────────────────

@router.get(
    "/check-events",
    response_model=CompanionCheckEventsResponse,
    summary="检查陪伴事件",
    description="检查当前用户是否有需要通知的陪伴事件（纪念日、心智灾变、不活跃提醒）。",
)
async def check_companion_events(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CompanionCheckEventsResponse:
    """基于真实陪伴状态检查待通知的陪伴事件。"""
    events: List[CompanionEventItem] = []
    checked_at = datetime.now(timezone.utc).isoformat()

    row = (
        db.query(CompanionState)
        .filter(CompanionState.user_id == current_user.id)
        .first()
    )

    # 纪念日：初次见面天数命中特殊节点
    if row is not None and row.first_met_at is not None:
        days = (datetime.now(timezone.utc) - row.first_met_at).days
        if days in _MILESTONE_DAYS:
            events.append(
                CompanionEventItem(
                    type="milestone",
                    title="纪念日",
                    body=f"今天是你们相识的第 {days} 天",
                    navigate_to="/companion",
                )
            )

    # 心智灾变：最近一次灾变里程碑
    last_catastrophe = (
        db.query(CompanionMilestone)
        .filter(
            CompanionMilestone.user_id == current_user.id,
            CompanionMilestone.milestone_type == "catastrophe",
        )
        .order_by(CompanionMilestone.created_at.desc())
        .first()
    )
    if last_catastrophe is not None:
        events.append(
            CompanionEventItem(
                type="milestone",
                title="心智成长",
                body=last_catastrophe.detail,
                navigate_to="/companion",
            )
        )

    logger.bind(
        event="companion_check_events",
        module="companion",
        user_id=current_user.id,
        event_count=len(events),
    ).debug("陪伴事件检查完成")

    return CompanionCheckEventsResponse(
        success=True,
        events=events,
        checked_at=checked_at,
    )