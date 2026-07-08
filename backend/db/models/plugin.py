"""
插件域 ORM 模型：插件定义、插件执行日志、插件版本历史、评分、评论、下载日志。
所有模型继承 db.models.base.Base，与主业务模型共享同一 Metadata。
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import Boolean, DateTime, Float, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from db.models.base import Base


class Plugin(Base):
    """
    插件模型，存储插件的基本信息、启用状态和依赖关系。
    """
    __tablename__ = "plugins"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String)
    version: Mapped[str] = mapped_column(String)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    config: Mapped[Dict[str, Any]] = mapped_column(JSON)
    category: Mapped[str] = mapped_column(String, default="general")
    author: Mapped[str] = mapped_column(String)
    source: Mapped[str] = mapped_column(String)
    dependencies: Mapped[List[str]] = mapped_column(JSON)
    granted_permissions: Mapped[List[str]] = mapped_column(JSON, default=list)
    installed_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    # 是否不可卸载（内置插件为 True，用户不可卸载/禁用）
    is_uninstallable: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, comment="是否不可卸载（内置插件为 True）")


class PluginExecutionLog(Base):
    """
    插件执行日志，记录插件方法调用的详细信息。
    """
    __tablename__ = "plugin_execution_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    plugin_id: Mapped[str] = mapped_column(String, index=True)
    plugin_name: Mapped[str] = mapped_column(String, index=True)
    method: Mapped[str] = mapped_column(String)
    inputs: Mapped[Dict[str, Any]] = mapped_column(JSON)
    outputs: Mapped[Dict[str, Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String)
    execution_time: Mapped[float] = mapped_column(Float)
    error_message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class PluginVersion(Base):
    """
    插件版本历史模型，记录每个插件的版本发布信息。
    支持版本对比、升级检测、回滚操作。
    """
    __tablename__ = "plugin_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    plugin_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    changelog: Mapped[str] = mapped_column(Text, default="")
    download_url: Mapped[str] = mapped_column(String(500), default="")
    sha256_checksum: Mapped[str] = mapped_column(String(64), default="")
    min_platform_version: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    max_platform_version: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    is_published: Mapped[bool] = mapped_column(Boolean, default=True)
    published_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    # 兼容性标记：stable/beta/dev
    release_channel: Mapped[str] = mapped_column(String(20), default="stable")

    __table_args__ = (
        Index("ix_plugin_version_plugin_id_version", "plugin_id", "version", unique=True),
    )


class PluginRating(Base):
    """
    插件评分模型，每个用户对每个插件仅保留一条评分记录（覆盖更新）。
    """
    __tablename__ = "plugin_ratings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    plugin_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    user_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)  # 1-5 星
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        Index("ix_plugin_rating_plugin_user", "plugin_id", "user_id", unique=True),
    )


class PluginReview(Base):
    """
    插件评论模型，用户可对插件发表评论并附带评分。
    """
    __tablename__ = "plugin_reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    plugin_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    user_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    username: Mapped[str] = mapped_column(String(100), default="")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    rating: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # 1-5 星，可选
    is_hidden: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class PluginDownloadLog(Base):
    """
    插件下载日志模型，记录每次下载操作的状态与来源。
    """
    __tablename__ = "plugin_download_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    plugin_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    version: Mapped[str] = mapped_column(String(50), default="")
    user_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="started")
    # started/success/failed/cancelled
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source_type: Mapped[str] = mapped_column(String(20), default="remote")
    # remote/local/cache
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
