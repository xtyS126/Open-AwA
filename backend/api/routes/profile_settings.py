"""
用户画像设置 API。
提供 N 值与探针触发条件的读写接口。
"""

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from loguru import logger

from api.dependencies import get_current_user, get_db
from db.models import User
from plugins.user_profile_builtin.coordinator import get_coordinator


router = APIRouter(prefix="/api/profile", tags=["profile-settings"])


class ProfileSettingsResponse(BaseModel):
    """画像设置响应"""
    n_threshold: int = 5
    probe_flags: Dict[str, bool] = Field(default_factory=dict)
    turns_since_last_extract: int = 0
    last_extracted_at: Optional[str] = None


class ProfileSettingsUpdateRequest(BaseModel):
    """画像设置更新请求"""
    n_threshold: Optional[int] = Field(None, ge=3, le=20, description="N 轮阈值（3-20）")
    probe_flags: Optional[Dict[str, bool]] = Field(None, description="探针触发条件 flags")


@router.get("/settings", response_model=ProfileSettingsResponse)
async def get_profile_settings(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """获取当前用户的画像设置"""
    user_id = str(current_user.id)
    coordinator = get_coordinator()
    settings = coordinator.get_settings(user_id, db)
    return settings


@router.put("/settings", response_model=ProfileSettingsResponse)
async def update_profile_settings(
    req: ProfileSettingsUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """更新当前用户的画像设置"""
    user_id = str(current_user.id)
    coordinator = get_coordinator()
    settings = coordinator.update_settings(
        user_id, db,
        n_threshold=req.n_threshold,
        probe_flags=req.probe_flags,
    )

    logger.bind(
        user_id=user_id,
        n_threshold=settings.get("n_threshold"),
        probe_flags=settings.get("probe_flags"),
    ).info("用户画像设置已更新")

    return settings
