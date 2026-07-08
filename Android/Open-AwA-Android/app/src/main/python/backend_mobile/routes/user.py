"""
用户路由 - 用户信息管理

阶段 2 实现说明：
- 仅提供当前用户信息查询和基本字段更新
- 管理员功能（用户列表/禁用/删除）阶段 3 实现
- /me 路由对齐桌面版 /api/user/profile（前端 userAPI.getProfile 实际走 /user/profile）
- /preferences 路由提供 key-value 偏好存储（前端 modelStore 依赖）
"""

import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import User, UserPreference, get_db
from ..security import hash_password, verify_password
from .auth import get_current_user, UserResponse

router = APIRouter(prefix="/api/user", tags=["User"])


class UpdateProfileRequest(BaseModel):
    """更新个人资料请求"""

    email: Optional[str] = Field(None, max_length=128, description="邮箱")


class ChangePasswordRequest(BaseModel):
    """修改密码请求"""

    old_password: str = Field(..., min_length=1, max_length=256)
    new_password: str = Field(..., min_length=6, max_length=256)


class PreferencesUpdateRequest(BaseModel):
    """更新用户偏好请求（前端 UserPreferencesResponse 格式）"""

    preferences: Dict[str, Any] = Field(default_factory=dict, description="偏好键值对")


@router.get("/me", response_model=UserResponse)
async def get_profile(
    current_user: User = Depends(get_current_user),
) -> User:
    """获取当前用户资料"""
    return current_user


@router.put("/me", response_model=UserResponse)
async def update_profile(
    payload: UpdateProfileRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> User:
    """更新当前用户资料"""
    if payload.email is not None:
        current_user.email = payload.email
    db.commit()
    db.refresh(current_user)
    return current_user


@router.post("/me/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    payload: ChangePasswordRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """修改当前用户密码"""
    if not verify_password(payload.old_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="原密码错误",
        )
    current_user.password_hash = hash_password(payload.new_password)
    db.commit()


# ============================================================================
# /api/user/preferences 路由
#
# 前端 frontend/src/shared/api/api.ts 的 userAPI.getPreferences/updatePreferences
# 用 /user/preferences 端点读写 modelStore.selectedModel 等偏好。
# 移动端用 UserPreference 表 key-value 存储，GET 返回合并后的 dict，
# PUT 全量替换（前端传整个 preferences dict）。
# ============================================================================


def _load_preferences(db: Session, user_id: int) -> Dict[str, Any]:
    """从数据库加载用户偏好，JSON 反序列化 value"""
    rows = (
        db.query(UserPreference)
        .filter(UserPreference.user_id == user_id)
        .all()
    )
    result: Dict[str, Any] = {}
    for row in rows:
        if row.value is None:
            result[row.key] = None
            continue
        try:
            result[row.key] = json.loads(row.value)
        except (json.JSONDecodeError, ValueError):
            # 非 JSON 字符串原样返回
            result[row.key] = row.value
    return result


def _save_preferences(db: Session, user_id: int, preferences: Dict[str, Any]) -> None:
    """全量替换用户偏好（删除旧记录，写入新记录）"""
    db.query(UserPreference).filter(UserPreference.user_id == user_id).delete()
    now = datetime.now(timezone.utc)
    for key, value in preferences.items():
        # None 值直接存 NULL，其他值 JSON 序列化
        if value is None:
            stored_value: Optional[str] = None
        else:
            try:
                stored_value = json.dumps(value, ensure_ascii=False)
            except (TypeError, ValueError):
                # 不可序列化的值转字符串
                stored_value = json.dumps(str(value), ensure_ascii=False)
        db.add(
            UserPreference(
                user_id=user_id,
                key=str(key)[:128],
                value=stored_value,
                updated_at=now,
            )
        )
    db.commit()


@router.get("/preferences")
async def get_preferences(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """获取当前用户偏好（前端 UserPreferencesResponse 格式）"""
    prefs = _load_preferences(db, current_user.id)
    return {"preferences": prefs}


@router.put("/preferences")
async def update_preferences(
    payload: PreferencesUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """全量更新当前用户偏好（前端 UserPreferencesResponse 格式）"""
    _save_preferences(db, current_user.id, payload.preferences)
    return {"preferences": payload.preferences}
