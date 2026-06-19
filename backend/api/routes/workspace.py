"""
工作区管理 API 路由。
提供多智能体工作区的 CRUD 和配置管理接口。
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from core.workspace.manager import WorkspaceManager
from core.soul_state import SoulStateManager
from db.models import get_db

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])


# ---- Request/Response Schemas ----

class WorkspaceCreate(BaseModel):
    """创建工作区请求体。"""
    name: str
    description: str = ""
    agent_type: str = "default"
    workspace_id: Optional[str] = None


class WorkspaceUpdate(BaseModel):
    """更新工作区请求体。"""
    name: Optional[str] = None
    description: Optional[str] = None
    agent_type: Optional[str] = None
    is_enabled: Optional[bool] = None
    config_json: Optional[dict] = None
    enabled_channels_json: Optional[dict] = None


class PersonaFileUpdate(BaseModel):
    """人设文件更新请求体。"""
    filename: str
    content: str


class HeartbeatConfigUpdate(BaseModel):
    """心跳配置更新请求体。"""
    enabled: bool = False
    every: str = "6h"
    target: str = "main"
    active_hours: Optional[dict] = None


# ---- Helper ----

def _get_mgr(db: Session = Depends(get_db)) -> WorkspaceManager:
    return WorkspaceManager(db)


# ---- API Endpoints ----

@router.get("")
def list_workspaces(enabled_only: bool = False, mgr: WorkspaceManager = Depends(_get_mgr)):
    """
    获取所有工作区列表。
    """
    workspaces = mgr.list_workspaces(enabled_only=enabled_only)
    return {
        "workspaces": [
            {
                "id": ws.id,
                "name": ws.name,
                "description": ws.description,
                "agent_type": ws.agent_type,
                "is_default": ws.is_default,
                "is_enabled": ws.is_enabled,
                "skills_count": len(ws.skills_json),
                "channels_count": len(ws.enabled_channels_json),
                "created_at": ws.created_at.isoformat() if ws.created_at else None,
                "updated_at": ws.updated_at.isoformat() if ws.updated_at else None,
            }
            for ws in workspaces
        ],
        "total": len(workspaces),
    }


@router.post("")
def create_workspace(body: WorkspaceCreate, mgr: WorkspaceManager = Depends(_get_mgr)):
    """
    创建新工作区。
    """
    try:
        ws = mgr.create_workspace(
            name=body.name,
            description=body.description,
            agent_type=body.agent_type,
            workspace_id=body.workspace_id,
        )
        return {
            "id": ws.id,
            "name": ws.name,
            "description": ws.description,
            "agent_type": ws.agent_type,
            "is_default": ws.is_default,
            "is_enabled": ws.is_enabled,
            "config": ws.config_json,
            "created_at": ws.created_at.isoformat() if ws.created_at else None,
        }
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.get("/{workspace_id}")
def get_workspace(workspace_id: str, mgr: WorkspaceManager = Depends(_get_mgr)):
    """
    获取指定工作区详情。
    """
    ws = mgr.get_workspace(workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail=f"工作区 '{workspace_id}' 不存在")
    return {
        "id": ws.id,
        "name": ws.name,
        "description": ws.description,
        "agent_type": ws.agent_type,
        "is_default": ws.is_default,
        "is_enabled": ws.is_enabled,
        "config": ws.config_json,
        "enabled_channels": ws.enabled_channels_json,
        "skills": ws.skills_json,
        "persona_files": ws.persona_files_json,
        "heartbeat_config": ws.heartbeat_config_json,
        "created_at": ws.created_at.isoformat() if ws.created_at else None,
        "updated_at": ws.updated_at.isoformat() if ws.updated_at else None,
    }


@router.put("/{workspace_id}")
def update_workspace(workspace_id: str, body: WorkspaceUpdate, mgr: WorkspaceManager = Depends(_get_mgr)):
    """
    更新工作区配置。
    """
    ws = mgr.update_workspace(
        workspace_id,
        name=body.name,
        description=body.description,
        agent_type=body.agent_type,
        is_enabled=body.is_enabled,
        config_json=body.config_json,
        enabled_channels_json=body.enabled_channels_json,
    )
    if not ws:
        raise HTTPException(status_code=404, detail=f"工作区 '{workspace_id}' 不存在")
    return {"message": "工作区已更新", "workspace_id": workspace_id}


@router.delete("/{workspace_id}")
def delete_workspace(workspace_id: str, mgr: WorkspaceManager = Depends(_get_mgr)):
    """
    删除工作区。
    """
    try:
        ok = mgr.delete_workspace(workspace_id)
        if not ok:
            raise HTTPException(status_code=404, detail=f"工作区 '{workspace_id}' 不存在")
        return {"message": "工作区已删除", "workspace_id": workspace_id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/{workspace_id}/skills/{skill_name}/enable")
def enable_workspace_skill(workspace_id: str, skill_name: str, mgr: WorkspaceManager = Depends(_get_mgr)):
    """
    在工作区中启用指定技能。
    """
    ws = mgr.enable_skill(workspace_id, skill_name)
    if not ws:
        raise HTTPException(status_code=404, detail=f"工作区 '{workspace_id}' 不存在")
    return {"message": f"技能 '{skill_name}' 已启用", "workspace_id": workspace_id}


@router.put("/{workspace_id}/skills/{skill_name}/disable")
def disable_workspace_skill(workspace_id: str, skill_name: str, mgr: WorkspaceManager = Depends(_get_mgr)):
    """
    在工作区中禁用指定技能。
    """
    ws = mgr.disable_skill(workspace_id, skill_name)
    if not ws:
        raise HTTPException(status_code=404, detail=f"工作区 '{workspace_id}' 不存在")
    return {"message": f"技能 '{skill_name}' 已禁用", "workspace_id": workspace_id}


@router.put("/{workspace_id}/persona")
def update_persona_file(workspace_id: str, body: PersonaFileUpdate, mgr: WorkspaceManager = Depends(_get_mgr)):
    """
    更新工作区人设文件。
    """
    ws = mgr.update_persona_file(workspace_id, body.filename, body.content)
    if not ws:
        raise HTTPException(status_code=404, detail=f"工作区 '{workspace_id}' 不存在")
    return {"message": f"人设文件 '{body.filename}' 已更新"}


@router.put("/{workspace_id}/heartbeat")
def update_heartbeat_config(workspace_id: str, body: HeartbeatConfigUpdate, mgr: WorkspaceManager = Depends(_get_mgr)):
    """
    更新工作区心跳配置。
    """
    ws = mgr.update_workspace(
        workspace_id,
        heartbeat_config_json={
            "enabled": body.enabled,
            "every": body.every,
            "target": body.target,
            "active_hours": body.active_hours or {"start": "08:00", "end": "22:00"},
        },
    )
    if not ws:
        raise HTTPException(status_code=404, detail=f"工作区 '{workspace_id}' 不存在")
    return {"message": "心跳配置已更新"}


# ---- 灵魂状态管理 API ----

class SoulInjectionToggle(BaseModel):
    """灵魂注入开关切换请求体。"""
    enabled: bool


@router.get("/{workspace_id}/soul/injection-status")
def get_soul_injection_status(workspace_id: str):
    """
    获取工作区灵魂注入状态。
    """
    soul_mgr = SoulStateManager(workspace_id)
    return soul_mgr.get_state_summary()


@router.put("/{workspace_id}/soul/injection-toggle")
def toggle_soul_injection(workspace_id: str, body: SoulInjectionToggle):
    """
    切换工作区灵魂注入开关。
    """
    soul_mgr = SoulStateManager(workspace_id)
    soul_mgr.set_injection_enabled(body.enabled)
    return {
        "message": f"灵魂注入已{'启用' if body.enabled else '禁用'}",
        "workspace_id": workspace_id,
        "enabled": body.enabled
    }


@router.post("/{workspace_id}/soul/reset")
def reset_soul_state(workspace_id: str):
    """
    重置工作区灵魂状态。
    """
    soul_mgr = SoulStateManager(workspace_id)
    soul_mgr.reset_state()
    return {
        "message": "灵魂状态已重置",
        "workspace_id": workspace_id
    }

