"""
陪伴通知检查 API 路由。
提供检查陪伴事件（羁绊升级、纪念日、日记生成、不活跃提醒）的端点，
供前端定时轮询以触发桌面通知。
"""
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api.dependencies import get_current_user
from db.models import get_db, User

router = APIRouter(prefix="/companion", tags=["companion"])


# ──────────────────────────────────────────────
# 请求/响应模型
# ──────────────────────────────────────────────

class CompanionEventItem(BaseModel):
    """陪伴事件条目"""
    type: str = Field(..., description="事件类型: bond_upgrade | milestone | diary_ready | inactivity_reminder")
    title: str = Field(..., description="通知标题")
    body: str = Field(..., description="通知正文")
    navigate_to: Optional[str] = Field(default=None, description="点击后导航的前端路由路径")


class CompanionCheckEventsResponse(BaseModel):
    """陪伴事件检查响应"""
    success: bool = True
    events: List[CompanionEventItem] = Field(default_factory=list)
    checked_at: str = Field(default="", description="检查时间 ISO 8601")


# ──────────────────────────────────────────────
# API 端点
# ──────────────────────────────────────────────

@router.get(
    "/check-events",
    response_model=CompanionCheckEventsResponse,
    summary="检查陪伴事件",
    description="检查当前用户是否有需要通知的陪伴事件（羁绊升级、纪念日、日记生成、不活跃提醒）。",
)
async def check_companion_events(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    检查当前用户是否有需要通知的陪伴事件。

    当前为占位实现，陪伴系统（companion_states 表）尚未创建，
    接口结构已完整对接，后续集成陪伴系统后替换占位逻辑即可。
    """
    events: List[CompanionEventItem] = []
    checked_at = datetime.now(timezone.utc).isoformat()

    # ── 占位：羁绊升级检查 ──
    # 后续实现：查询 companion_states 表，检查 bond_level 是否变化
    # bond_upgrade_events = await _check_bond_upgrade(db, current_user.id)
    # events.extend(bond_upgrade_events)

    # ── 占位：纪念日检查 ──
    # 后续实现：查询 companion_states 表的 first_met_at，计算天数
    # milestone_events = await _check_milestones(db, current_user.id)
    # events.extend(milestone_events)

    # ── 占位：日记生成检查 ──
    # 后续实现：检查 diary 目录最新文件时间，判断是否有新日记
    # diary_events = await _check_diary_ready(current_user.id)
    # events.extend(diary_events)

    # ── 占位：不活跃提醒检查 ──
    # 后续实现：检查用户最后活跃时间，超过阈值时触发提醒
    # inactivity_events = await _check_inactivity(db, current_user.id)
    # events.extend(inactivity_events)

    logger.bind(
        event="companion_check_events",
        module="companion",
        user_id=current_user.id,
        event_count=len(events),
    ).debug("陪伴事件检查完成（占位实现）")

    return CompanionCheckEventsResponse(
        success=True,
        events=events,
        checked_at=checked_at,
    )


# ──────────────────────────────────────────────
# 辅助函数（占位，后续实现）
# ──────────────────────────────────────────────

async def _check_bond_upgrade(
    db: Session,
    user_id: str,
) -> List[CompanionEventItem]:
    """
    检查羁绊升级事件。
    后续实现：查询 companion_states 表，对比 bond_level 变化。
    """
    return []


async def _check_milestones(
    db: Session,
    user_id: str,
) -> List[CompanionEventItem]:
    """
    检查纪念日事件。
    后续实现：读取 first_met_at，计算特殊天数（如 30/100/365 天）。
    """
    return []


async def _check_diary_ready(user_id: str) -> List[CompanionEventItem]:
    """
    检查日记生成事件。
    后续实现：检查 diary 目录最新文件修改时间。
    """
    return []


async def _check_inactivity(
    db: Session,
    user_id: str,
) -> List[CompanionEventItem]:
    """
    检查不活跃提醒事件。
    后续实现：查询用户最后活跃时间，超过阈值时触发提醒。
    """
    return []