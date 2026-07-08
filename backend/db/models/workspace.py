"""
工作区与系统配置域 ORM 模型：智能体工作区、搜索 Provider 配置。
所有模型继承 db.models.base.Base，与主业务模型共享同一 Metadata。
"""

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import Boolean, DateTime, Index, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from db.models.base import Base


class Workspace(Base):
    """
    智能体工作区模型，存储独立智能体的配置、人设、频道和技能绑定。
    每个工作区拥有独立的记忆、对话历史和定时任务，互不干扰。
    """
    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(String(50), primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(String(500), default="")
    agent_type: Mapped[str] = mapped_column(String(50), default="default")  # default / coding / qa / writer / custom
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # JSON 配置：包含模型选择、工具开关、运行参数等
    config_json: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    # 已启用的频道列表
    enabled_channels_json: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    # 技能启用状态 {skill_name: enabled}
    skills_json: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    # 人设文件（AGENTS.md / SOUL.md / PROFILE.md / HEARTBEAT.md 等）
    persona_files_json: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    # 心跳配置
    heartbeat_config_json: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )


class SearchProviderConfig(Base):
    """
    搜索 Provider 配置模型，支持 duckduckgo / searxng / disabled 三种 provider。
    extra_config 用于存放 allow_private_network 等扩展开关。
    """
    __tablename__ = "search_provider_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # provider 名称：duckduckgo/searxng/disabled
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    # 服务基址（duckduckgo 可为空）
    base_url: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    # API Key（可选，用于需要鉴权的 provider）
    api_key: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # 扩展配置，默认空 dict（存放 allow_private_network 等开关）
    extra_config: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (
        Index("idx_search_provider_enabled", "provider", "enabled"),
    )
