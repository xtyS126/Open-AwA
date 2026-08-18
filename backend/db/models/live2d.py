"""
Live2D 模型域 ORM 模型：存储用户上传的 Cubism 模型元数据与文件路径。

- Live2DModel：登记所有 Live2D 模型（内置行 user_id 为空，用户上传行 user_id 为用户 id）。
  与主业务模型共享 db.models.base.Base，统一在 init_db 的 create_all 中建表。
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import DateTime, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from db.models.base import Base


class Live2DModel(Base):
    """Live2D 模型注册表：内置行 user_id 为空，用户上传行 user_id 为用户 id。"""

    __tablename__ = "live2d_models"

    # 主键 uuid
    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)

    # 模型名称
    model_name: Mapped[str] = mapped_column(String, nullable=False)

    # 存储目录路径（相对于 LIVED2D_DATA_DIR 或绝对路径）
    model_path: Mapped[str] = mapped_column(String, nullable=False)

    # .model3.json 入口文件路径
    model3_json_path: Mapped[str] = mapped_column(String, nullable=False)

    # .moc3 文件路径
    moc3_path: Mapped[str] = mapped_column(String, nullable=False)

    # 纹理文件列表，如 ["texture_00.png", ...]
    texture_paths: Mapped[List[str]] = mapped_column(JSON, nullable=False, default=list)

    # 表情定义（从 .model3.json 的 Expressions 解析）
    expressions_json: Mapped[List[Any]] = mapped_column(JSON, nullable=False, default=list)

    # 动作定义（从 .model3.json 的 Groups 解析）
    motions_json: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    # 物理定义文件路径（可选）
    physics_json: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # 姿势定义文件路径（可选）
    pose_json: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # 模型版本号
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # 上传用户 id（None 为内置模型，非 None 为用户上传）
    user_id: Mapped[Optional[str]] = mapped_column(String, index=True, nullable=True)

    # 创建时间
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )