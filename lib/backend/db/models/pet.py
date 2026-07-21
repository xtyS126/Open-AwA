"""
宠物域 ORM 模型：宠物注册表与每用户的当前激活宠物。

- Pet：登记所有可用宠物（内置系统行 + 用户自定义行），缓存元数据以便快速列表，避免每次扫描目录。
- UserActivePet：每用户当前选中的宠物 id，单行映射。
两者共享 db.models.base.Base，与主业务模型统一在 init_db 的 create_all 中建表。
"""

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import Boolean, DateTime, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from db.models.base import Base


class Pet(Base):
    """宠物注册表：内置行 user_id 为空，自定义行 user_id 为用户 id。"""

    __tablename__ = "pets"
    __table_args__ = (
        UniqueConstraint("user_id", "pet_id", name="uq_pets_user_pet"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    user_id: Mapped[Optional[str]] = mapped_column(String, index=True, nullable=True)
    pet_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(String, default="")
    sprite_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    frame_width: Mapped[int] = mapped_column(Integer, default=192, nullable=False)
    frame_height: Mapped[int] = mapped_column(Integer, default=208, nullable=False)
    columns: Mapped[int] = mapped_column(Integer, default=8, nullable=False)
    rows: Mapped[int] = mapped_column(Integer, default=9, nullable=False)
    frame_count: Mapped[int] = mapped_column(Integer, default=72, nullable=False)
    animations: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    spritesheet_path: Mapped[str] = mapped_column(String, nullable=False, default="")
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    spritesheet_ready: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )


class UserActivePet(Base):
    """每用户当前激活的宠物，user_id 为主键，单行。"""

    __tablename__ = "user_active_pets"

    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    pet_id: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
