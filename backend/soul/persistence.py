"""
OnionProfile 持久化层。

提供 OnionProfile 序列化/反序列化与数据库读写能力，
将 SoulEngine 的内存画像缓存与 user_profiles 表解耦。

设计要点：
- save_profile 使用 upsert 语义：存在则更新（version 递增），不存在则插入
- load_profile 未命中返回 None，由上层决定是否创建空画像
- delete_profile 静默删除（不存在时不报错）
- 所有写入操作均调用 db.commit()，确保事务提交
"""
import json
from datetime import datetime, timezone
from typing import Optional

from loguru import logger
from sqlalchemy.orm import Session

from db.models import UserProfile
from soul.profile import OnionProfile


def save_profile(db: Session, user_id: str, profile: OnionProfile) -> None:
    """
    保存或更新用户画像（upsert 语义）。

    Args:
        db: SQLAlchemy 会话
        user_id: 用户 ID
        profile: OnionProfile 画像对象

    Notes:
        - 存在记录时：更新 profile_json 与 updated_at，version 递增
        - 不存在记录时：插入新记录，version 初始为 1
        - 调用方负责传入有效的 db 会话，本函数会执行 commit
    """
    profile_dict = profile.to_dict()
    profile_json = json.dumps(profile_dict, ensure_ascii=False, default=str)

    existing = db.query(UserProfile).filter(UserProfile.user_id == user_id).first()
    if existing is not None:
        existing.profile_json = profile_json
        existing.version = (existing.version or 1) + 1
        existing.updated_at = datetime.now(timezone.utc)
    else:
        new_record = UserProfile(
            user_id=user_id,
            profile_json=profile_json,
            version=1,
        )
        db.add(new_record)

    db.commit()


def load_profile(db: Session, user_id: str) -> Optional[OnionProfile]:
    """
    加载用户画像。

    Args:
        db: SQLAlchemy 会话
        user_id: 用户 ID

    Returns:
        Optional[OnionProfile]: 反序列化后的画像对象；未命中或反序列化失败时返回 None
    """
    record = db.query(UserProfile).filter(UserProfile.user_id == user_id).first()
    if record is None:
        return None

    if not record.profile_json:
        return None

    try:
        profile_dict = json.loads(record.profile_json)
        return OnionProfile.from_dict(profile_dict)
    except (json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
        logger.bind(user_id=user_id).opt(exception=True).warning(
            f"画像反序列化失败: {exc}"
        )
        return None


def delete_profile(db: Session, user_id: str) -> None:
    """
    删除用户画像。

    Args:
        db: SQLAlchemy 会话
        user_id: 用户 ID

    Notes:
        - 不存在记录时静默返回，不报错
        - 调用方负责传入有效的 db 会话，本函数会执行 commit
    """
    record = db.query(UserProfile).filter(UserProfile.user_id == user_id).first()
    if record is None:
        return

    db.delete(record)
    db.commit()
