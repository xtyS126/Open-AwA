"""
Owner 用户管理辅助模块，为单用户模式提供统一的所有者查询和创建逻辑。
所有需要 user_id 的业务层统一通过此模块获取 owner 用户信息。
"""

import asyncio
import os
import secrets
import uuid
from typing import Optional

from loguru import logger
from sqlalchemy.orm import Session

from config.security import get_password_hash
from config.settings import settings
from db.models import User


_owner_cache: Optional[User] = None
_owner_lock = asyncio.Lock()


def _get_owner_username() -> str:
    """从环境变量获取 owner 用户名，未设置时使用默认值。"""
    return os.getenv("OPENAWA_OWNER_USERNAME", "admin").strip() or "admin"


def ensure_owner_user(db: Session) -> User:
    """
    确保唯一的 owner 用户在数据库中存在，不存在则创建。
    此函数在应用启动时调用，同步执行。

    返回: owner User 对象
    """
    global _owner_cache

    username = _get_owner_username()
    password = (
        os.getenv("OPENAWA_OWNER_PASSWORD", "").strip()
        or secrets.token_urlsafe(16)
    )
    nickname = os.getenv("OPENAWA_OWNER_NICKNAME", "").strip()
    email = os.getenv("OPENAWA_OWNER_EMAIL", "").strip()

    user = db.query(User).filter(User.username == username).first()

    if user is None:
        user = User(
            id=str(uuid.uuid4()),
            username=username,
            password_hash=get_password_hash(password),
            role="admin",
            nickname=nickname or None,
            email=email or None,
        )
        db.add(user)
        db.commit()
        logger.bind(
            event="owner_created",
            module="core.owner",
            username=username,
        ).info(f"已创建 owner 用户: {username}")
    else:
        # 更新画像信息（如果环境变量有值且与现有不同）
        updated = False
        if nickname and user.nickname != nickname:
            user.nickname = nickname
            updated = True
        if email and user.email != email:
            user.email = email
            updated = True
        if updated:
            db.commit()
            logger.bind(
                event="owner_updated",
                module="core.owner",
                username=username,
            ).info(f"已更新 owner 用户画像: {username}")

    _owner_cache = user
    return user


async def get_owner_user(db: Session) -> User:
    """
    异步获取唯一 owner 用户（带缓存和双重检查锁）。

    所有需要当前用户信息的业务层应通过此函数获取 owner，
    而非直接查询 users 表。

    返回: owner User 对象
    """
    global _owner_cache

    if _owner_cache is not None:
        return _owner_cache

    async with _owner_lock:
        if _owner_cache is not None:
            return _owner_cache

        from api.dependencies import _load_user_by_username

        username = _get_owner_username()
        # 在独立线程中查询用户，避免阻塞事件循环
        user = await asyncio.to_thread(_load_user_by_username, username)
        if user is None:
            raise RuntimeError(
                f"Owner 用户 '{username}' 未初始化，"
                f"请检查应用启动日志中的 _ensure_owner_user 步骤"
            )
        _owner_cache = user
        return user


def get_owner_id_sync(db: Session) -> str:
    """
    同步获取 owner 用户的 ID（用于非 async 上下文）。
    优先使用缓存，缓存未命中时查询数据库。

    返回: owner 用户 ID 字符串
    """
    global _owner_cache

    if _owner_cache is not None:
        return _owner_cache.id

    username = _get_owner_username()
    user = db.query(User).filter(User.username == username).first()
    if user is None:
        raise RuntimeError(f"Owner 用户 '{username}' 未初始化")
    _owner_cache = user
    return user.id


def invalidate_owner_cache() -> None:
    """清除 owner 用户缓存（用于测试或用户信息更新后）。"""
    global _owner_cache
    _owner_cache = None
    logger.debug("owner 用户缓存已清除")
