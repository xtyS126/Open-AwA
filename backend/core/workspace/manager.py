"""
工作区管理器，负责多智能体工作区的生命周期管理。
每个工作区拥有独立的配置、技能、频道和人设文件。
"""
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from loguru import logger
from sqlalchemy.orm import Session

from backend.db.models import Workspace


# 默认工作区配置模板
DEFAULT_WORKSPACE_CONFIG = {
    "model": None,
    "thinking_depth": 3,
    "max_tool_call_rounds": 12,
    "max_turns": 20,
    "enabled_tools": [],
    "disabled_tools": [],
    "language": "zh",
}

DEFAULT_PERSONA_FILES = {
    "AGENTS.md": "# Agent Instructions\n\n你是一个智能助理，帮助用户完成各种任务。",
    "SOUL.md": "# Soul\n\n你是一个温暖、专业的AI助手。",
    "PROFILE.md": "# Profile\n\n通用智能助理，可以处理多种类型的任务。",
}

DEFAULT_HEARTBEAT_CONFIG = {
    "enabled": False,
    "every": "6h",
    "target": "main",
    "active_hours": {"start": "08:00", "end": "22:00"},
}


class WorkspaceManager:
    """
    工作区管理器。
    负责工作区的 CRUD、默认工作区创建和配置管理。
    """

    def __init__(self, db: Session):
        self.db = db

    def ensure_default_workspace(self) -> Workspace:
        """
        确保存在默认工作区，不存在时自动创建。
        """
        default = self.db.query(Workspace).filter(Workspace.is_default == True).first()
        if not default:
            default = self.create_workspace(
                name="默认工作区",
                description="系统默认智能体工作区",
                agent_type="default",
                is_default=True,
                workspace_id="default",
            )
        return default

    def create_workspace(
        self,
        name: str,
        description: str = "",
        agent_type: str = "default",
        is_default: bool = False,
        workspace_id: Optional[str] = None,
        config: Optional[dict[str, Any]] = None,
    ) -> Workspace:
        """
        创建新工作区。
        """
        wid = workspace_id or str(uuid.uuid4())[:8]

        existing = self.db.query(Workspace).filter(Workspace.id == wid).first()
        if existing:
            raise ValueError(f"工作区 '{wid}' 已存在")

        ws = Workspace(
            id=wid,
            name=name,
            description=description,
            agent_type=agent_type,
            is_default=is_default,
            config_json=config or DEFAULT_WORKSPACE_CONFIG,
            enabled_channels_json={},
            skills_json={},
            persona_files_json=DEFAULT_PERSONA_FILES.copy(),
            heartbeat_config_json=DEFAULT_HEARTBEAT_CONFIG.copy(),
        )
        self.db.add(ws)
        self.db.commit()
        self.db.refresh(ws)
        logger.bind(event="workspace_created", workspace_id=wid, name=name).info("工作区已创建")
        return ws

    def get_workspace(self, workspace_id: str) -> Optional[Workspace]:
        """
        获取指定工作区。
        """
        return self.db.query(Workspace).filter(Workspace.id == workspace_id).first()

    def list_workspaces(self, enabled_only: bool = False) -> list[Workspace]:
        """
        列出所有工作区。
        """
        query = self.db.query(Workspace)
        if enabled_only:
            query = query.filter(Workspace.is_enabled == True)
        return query.order_by(Workspace.is_default.desc(), Workspace.created_at.asc()).all()

    def update_workspace(self, workspace_id: str, **kwargs) -> Optional[Workspace]:
        """
        更新工作区配置。
        """
        ws = self.get_workspace(workspace_id)
        if not ws:
            return None

        allowed_fields = [
            "name", "description", "agent_type", "is_enabled",
            "config_json", "enabled_channels_json", "skills_json",
            "persona_files_json", "heartbeat_config_json",
        ]

        for key, value in kwargs.items():
            if key in allowed_fields and value is not None:
                setattr(ws, key, value)

        ws.updated_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(ws)
        logger.bind(event="workspace_updated", workspace_id=workspace_id).info("工作区已更新")
        return ws

    def delete_workspace(self, workspace_id: str) -> bool:
        """
        删除工作区。默认工作区不可删除。
        """
        ws = self.get_workspace(workspace_id)
        if not ws:
            return False
        if ws.is_default:
            raise ValueError("默认工作区不可删除")

        self.db.delete(ws)
        self.db.commit()
        logger.bind(event="workspace_deleted", workspace_id=workspace_id).info("工作区已删除")
        return True

    def enable_skill(self, workspace_id: str, skill_name: str) -> Optional[Workspace]:
        """
        在工作区中启用指定技能。
        """
        ws = self.get_workspace(workspace_id)
        if not ws:
            return None
        skills = dict(ws.skills_json)
        skills[skill_name] = True
        ws.skills_json = skills
        ws.updated_at = datetime.now(timezone.utc)
        self.db.commit()
        return ws

    def disable_skill(self, workspace_id: str, skill_name: str) -> Optional[Workspace]:
        """
        在工作区中禁用指定技能。
        """
        ws = self.get_workspace(workspace_id)
        if not ws:
            return None
        skills = dict(ws.skills_json)
        skills[skill_name] = False
        ws.skills_json = skills
        ws.updated_at = datetime.now(timezone.utc)
        self.db.commit()
        return ws

    def update_persona_file(self, workspace_id: str, filename: str, content: str) -> Optional[Workspace]:
        """
        更新工作区的人设文件。
        """
        ws = self.get_workspace(workspace_id)
        if not ws:
            return None
        files = dict(ws.persona_files_json)
        files[filename] = content
        ws.persona_files_json = files
        ws.updated_at = datetime.now(timezone.utc)
        self.db.commit()
        return ws

    def get_heartbeat_config(self, workspace_id: str) -> dict:
        """
        获取工作区心跳配置。
        """
        ws = self.get_workspace(workspace_id)
        if not ws:
            return DEFAULT_HEARTBEAT_CONFIG
        return dict(ws.heartbeat_config_json)
