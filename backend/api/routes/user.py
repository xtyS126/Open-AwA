"""
用户中心路由，提供用户画像、个人信息、头像、设备管理和远程登出等接口。
"""

from datetime import datetime, timezone
from pathlib import Path
import os
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from loguru import logger

from api.dependencies import get_current_user
from api.schemas import UserPreferencesUpdate
from config.security import add_to_blacklist
from db.models import LoginDevice, User as UserModel, BehaviorLog, get_db


router = APIRouter(prefix="/user", tags=["User"])

# 头像上传配置
ALLOWED_AVATAR_TYPES = {"image/jpeg", "image/png"}
MAX_AVATAR_SIZE = 1 * 1024 * 1024  # 1MB
AVATAR_UPLOAD_DIR = Path("uploads/avatars")


def _ensure_upload_dir() -> None:
    """确保头像上传目录存在。"""
    AVATAR_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


# --- 请求模型 ---

class UserProfileUpdate(BaseModel):
    """用户个人信息更新请求。"""
    nickname: Optional[str] = Field(None, max_length=100)
    email: Optional[str] = Field(None, max_length=200)
    phone: Optional[str] = Field(None, max_length=50)


class LoginDeviceResponse(BaseModel):
    """登录设备响应模型。"""
    id: int
    device_type: str
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    logged_in_at: datetime
    last_active_at: datetime
    is_online: bool
    is_current: bool = False

    class Config:
        from_attributes = True


# --- API 端点 ---

@router.get("/profile")
async def get_user_profile(
    request: Request,
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    获取当前用户的 AI 画像信息。
    从数据库中的 profile_data 或行为日志动态生成。
    """
    # 如果已有缓存的画像数据，直接返回
    if current_user.profile_data and current_user.profile_data.get("generated_at"):
        return {
            "user_id": current_user.id,
            "username": current_user.username,
            "nickname": current_user.nickname,
            "avatar_url": current_user.avatar_url,
            "email": current_user.email,
            "phone": current_user.phone,
            "profile": current_user.profile_data,
        }

    # 从行为日志中生成画像数据
    profile = _generate_user_profile(db, current_user.id)

    # 缓存画像数据
    current_user.profile_data = profile
    db.commit()

    return {
        "user_id": current_user.id,
        "username": current_user.username,
        "nickname": current_user.nickname,
        "avatar_url": current_user.avatar_url,
        "email": current_user.email,
        "phone": current_user.phone,
        "profile": profile,
    }


@router.put("/profile")
async def update_user_profile(
    request: UserProfileUpdate,
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    更新当前用户的个人信息（昵称、邮箱、电话）。
    """
    if request.nickname is not None:
        current_user.nickname = request.nickname.strip() or None
    if request.email is not None:
        current_user.email = request.email.strip() or None
    if request.phone is not None:
        current_user.phone = request.phone.strip() or None

    db.commit()

    logger.bind(
        event="user_profile_updated",
        module="user",
        action="update_profile",
        status="success",
        user_id=current_user.id,
    ).info("user profile updated")

    return {"message": "个人信息更新成功"}


@router.post("/avatar")
async def upload_avatar(
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
    file: UploadFile = File(...),
):
    """
    上传用户头像图片。
    仅支持 jpg/png 格式，大小不超过 1MB。
    """
    # 校验文件类型
    content_type = file.content_type or ""
    if content_type not in ALLOWED_AVATAR_TYPES:
        raise HTTPException(status_code=400, detail="仅支持 JPG 和 PNG 格式的头像图片")

    # 读取文件内容并校验大小
    file_data = await file.read()
    if len(file_data) > MAX_AVATAR_SIZE:
        raise HTTPException(status_code=400, detail="头像图片大小不能超过 1MB")

    # 保存文件
    _ensure_upload_dir()
    ext = ".png" if "png" in content_type else ".jpg"
    file_name = f"{current_user.id}_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}{ext}"
    file_path = AVATAR_UPLOAD_DIR / file_name
    file_path.write_bytes(file_data)

    # 更新用户头像 URL
    avatar_url = f"/api/user/avatar/{file_name}"
    current_user.avatar_url = avatar_url
    db.commit()

    logger.bind(
        event="user_avatar_uploaded",
        module="user",
        action="upload_avatar",
        status="success",
        user_id=current_user.id,
        file_name=file_name,
    ).info("avatar uploaded")

    return {"avatar_url": avatar_url, "message": "头像上传成功"}


@router.get("/devices", response_model=List[LoginDeviceResponse])
async def get_user_devices(
    request: Request,
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    获取当前用户的所有登录设备列表。
    返回设备类型、IP、登录时间等信息，标记当前设备。
    """
    # 获取当前请求的 jti
    from config.security import ACCESS_TOKEN_COOKIE_NAME
    raw_token = request.headers.get("authorization", "")
    if raw_token.lower().startswith("bearer "):
        raw_token = raw_token[7:].strip()
    elif request.cookies.get(ACCESS_TOKEN_COOKIE_NAME):
        raw_token = request.cookies.get(ACCESS_TOKEN_COOKIE_NAME, "")
    current_jti = None
    if raw_token:
        from config.security import decode_access_token
        payload = decode_access_token(raw_token)
        if payload:
            current_jti = payload.get("jti")

    devices = (
        db.query(LoginDevice)
        .filter(LoginDevice.user_id == current_user.id)
        .order_by(LoginDevice.logged_in_at.desc())
        .limit(20)
        .all()
    )

    result = []
    for device in devices:
        result.append({
            "id": device.id,
            "device_type": device.device_type,
            "ip_address": device.ip_address,
            "user_agent": (device.user_agent or "")[:100],
            "logged_in_at": device.logged_in_at,
            "last_active_at": device.last_active_at,
            "is_online": bool(device.is_online),
            "is_current": bool(current_jti and str(device.jti) == str(current_jti)),
        })

    return result


@router.post("/devices/{device_id}/revoke")
async def revoke_device(
    device_id: int,
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    远程登出指定设备，将其 JWT token 加入黑名单。
    """
    device = (
        db.query(LoginDevice)
        .filter(LoginDevice.id == device_id, LoginDevice.user_id == current_user.id)
        .first()
    )
    if not device:
        raise HTTPException(status_code=404, detail="设备记录未找到")

    # 将该设备的 token 加入黑名单
    if device.jti:
        add_to_blacklist(device.jti, db)

    # 标记设备离线
    device.is_online = False
    device.last_active_at = datetime.now(timezone.utc)
    db.commit()

    logger.bind(
        event="user_device_revoked",
        module="user",
        action="revoke_device",
        status="success",
        user_id=current_user.id,
        device_id=device_id,
    ).info("device revoked")

    return {"message": "远程登出成功"}


@router.get("/preferences")
async def get_user_preferences(
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    获取当前用户的偏好设置。
    返回 profile_data["preferences"]，不存在则返回空字典。
    """
    profile = current_user.profile_data or {}
    preferences = profile.get("preferences", {})
    logger.bind(
        event="user_preferences_get",
        module="user",
        action="get_preferences",
        status="success",
        user_id=current_user.id,
    ).debug("user preferences fetched")
    return {"preferences": preferences}


@router.put("/preferences")
async def update_user_preferences(
    body: "UserPreferencesUpdate",
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    增量更新用户偏好设置。
    将传入的键值对合并到 profile_data["preferences"] 中，不影响其他键。
    """
    profile = current_user.profile_data or {}
    existing_prefs = profile.get("preferences", {})
    existing_prefs.update(body.preferences)
    profile["preferences"] = existing_prefs
    current_user.profile_data = profile
    db.commit()
    logger.bind(
        event="user_preferences_put",
        module="user",
        action="update_preferences",
        status="success",
        user_id=current_user.id,
        keys=list(body.preferences.keys()),
    ).info("user preferences updated")
    return {"preferences": existing_prefs}


def _generate_user_profile(db: Session, user_id: str) -> dict:
    """
    从行为日志中生成用户的 AI 画像。
    包含兴趣标签、使用时长统计、活跃时段等。
    """
    from datetime import datetime as dt, timedelta

    now = dt.now(timezone.utc)
    thirty_days_ago = now - timedelta(days=30)

    # 查询最近 30 天的行为日志
    behaviors = (
        db.query(BehaviorLog)
        .filter(
            BehaviorLog.user_id == user_id,
            BehaviorLog.timestamp >= thirty_days_ago,
        )
        .all()
    )

    # 统计活跃时段
    hour_counts = {}
    for b in behaviors:
        hour = b.timestamp.hour
        hour_counts[hour] = hour_counts.get(hour, 0) + 1

    active_hours = sorted(hour_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    active_hour_labels = [f"{h}:00-{h+1}:00" for h, _ in active_hours]

    # 统计行为类型作为兴趣标签
    action_counts = {}
    for b in behaviors:
        action = b.action_type or "other"
        action_counts[action] = action_counts.get(action, 0) + 1

    interest_tags = sorted(action_counts.items(), key=lambda x: x[1], reverse=True)[:8]
    interest_labels = [tag for tag, _ in interest_tags]

    # 计算总使用会话数
    total_actions = len(behaviors)

    return {
        "generated_at": now.isoformat(),
        "interests": interest_labels if interest_labels else ["AI 助手"],
        "total_actions": total_actions,
        "active_hours": active_hour_labels if active_hour_labels else ["暂无数据"],
        "action_period_days": 30,
        "summary": f"在过去 30 天内共执行了 {total_actions} 次操作，主要活跃时段为 {', '.join(active_hour_labels[:3]) if active_hour_labels else '全天'}。",
    }
