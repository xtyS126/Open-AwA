"""
持久化权限规则模型，存储用户 "always allow" 的权限决策。
参考 OpenCode PermissionSaved 设计。
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import String, DateTime, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from db.models import Base

# 全局项目标识（跨项目生效的权限规则）
PROJECT_GLOBAL = "*"


class PermissionSaved(Base):
    """
    用户持久化的权限规则表。

    当用户在权限请求弹窗中选择 "Always Allow" 时，
    对应的 action/resource 组合会被保存到此表。
    后续相同 action/resource 的请求会自动放行。
    """
    __tablename__ = "permission_saved"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: f"permsave_{uuid.uuid4().hex[:12]}"
    )
    project_id: Mapped[str] = mapped_column(
        String, index=True,
        comment="项目标识，* 表示全局生效。调用方必须显式传入，不应依赖默认值"
    )
    action: Mapped[str] = mapped_column(
        String, index=True,
        comment="操作名称，支持通配符"
    )
    resource: Mapped[str] = mapped_column(
        String, index=True,
        comment="资源标识，支持通配符"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc),
        comment="创建时间"
    )
    created_by: Mapped[Optional[str]] = mapped_column(
        String, nullable=True,
        comment="创建者用户 ID"
    )

    __table_args__ = (
        UniqueConstraint("project_id", "action", "resource", name="uq_permission_saved"),
        Index("idx_permission_saved_lookup", "project_id", "action"),
    )

    def __repr__(self) -> str:
        return f"<PermissionSaved action={self.action} resource={self.resource}>"
