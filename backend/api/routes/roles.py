"""
AI 角色管理 API 路由，提供角色 CRUD、切换和预设模板接口。
"""

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from api.dependencies import get_current_user, get_db
from core.role_engine import RoleEngine
from db.models import AgentRole

router = APIRouter(prefix="/roles", tags=["roles"])


# --- Pydantic Schema ---

class RoleCreate(BaseModel):
    """创建角色请求。"""
    name: str = Field(..., max_length=100, description="角色名称")
    description: str = Field(default="", max_length=2000, description="角色描述")
    avatar_url: str = Field(default="", max_length=500, description="头像URL")
    system_prompt: str = Field(..., max_length=10000, description="系统提示词")
    personality: Dict[str, Any] = Field(default=dict, description="性格参数")
    expertise: Dict[str, Any] = Field(default=dict, description="专长领域")
    knowledge_base_ids: List[str] = Field(default=list, description="知识库ID列表")
    allowed_tools: List[str] = Field(default=list, description="允许的工具列表")
    allowed_skills: List[str] = Field(default=list, description="允许的技能列表")
    model_config_override: Dict[str, Any] = Field(default=dict, description="模型配置")
    is_public: bool = Field(default=False, description="是否公开")


class RoleUpdate(BaseModel):
    """更新角色请求。"""
    name: Optional[str] = Field(default=None, max_length=100)
    description: Optional[str] = Field(default=None, max_length=2000)
    avatar_url: Optional[str] = Field(default=None, max_length=500)
    system_prompt: Optional[str] = Field(default=None, max_length=10000)
    personality: Optional[Dict[str, Any]] = None
    expertise: Optional[Dict[str, Any]] = None
    knowledge_base_ids: Optional[List[str]] = None
    allowed_tools: Optional[List[str]] = None
    allowed_skills: Optional[List[str]] = None
    model_config_override: Optional[Dict[str, Any]] = None
    is_public: Optional[bool] = None


class RoleResponse(BaseModel):
    """角色响应。"""
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str
    name: str
    description: str
    avatar_url: str
    system_prompt: str
    personality: Dict[str, Any]
    expertise: Dict[str, Any]
    knowledge_base_ids: List[str]
    allowed_tools: List[str]
    allowed_skills: List[str]
    model_config_data: Dict[str, Any] = Field(alias="model_config")
    creator_id: Optional[int] = None
    is_public: bool
    usage_count: int
    is_preset: bool
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class RoleActivateRequest(BaseModel):
    """激活角色请求。"""
    session_id: str = Field(..., description="要绑定角色的会话ID")


# --- API 端点 ---

@router.get("", response_model=List[RoleResponse])
async def list_roles(
    db: Session = Depends(get_db),
    current_user: Dict = Depends(get_current_user),
) -> Dict[str, Any]:
    """获取所有角色列表。"""
    roles = db.query(AgentRole).order_by(AgentRole.created_at.desc()).all()
    return roles


@router.get("/presets", response_model=List[Dict[str, Any]])
async def get_presets(
    current_user: Dict = Depends(get_current_user),
) -> Dict[str, Any]:
    """获取预设角色模板列表。"""
    return RoleEngine.get_preset_roles()


@router.get("/{role_id}", response_model=RoleResponse)
async def get_role(
    role_id: str,
    db: Session = Depends(get_db),
    current_user: Dict = Depends(get_current_user),
) -> Dict[str, Any]:
    """获取角色详情。"""
    role = db.query(AgentRole).filter(AgentRole.id == role_id).first()
    if not role:
        raise HTTPException(status_code=404, detail="角色不存在")
    return role


@router.post("", response_model=RoleResponse, status_code=201)
async def create_role(
    role_data: RoleCreate,
    db: Session = Depends(get_db),
    current_user: Dict = Depends(get_current_user),
) -> Dict[str, Any]:
    """创建新角色。"""
    role_id = str(uuid.uuid4())[:8]
    role = AgentRole(
        id=role_id,
        name=role_data.name,
        description=role_data.description,
        avatar_url=role_data.avatar_url,
        system_prompt=role_data.system_prompt,
        personality=role_data.personality,
        expertise=role_data.expertise,
        knowledge_base_ids=role_data.knowledge_base_ids,
        allowed_tools=role_data.allowed_tools,
        allowed_skills=role_data.allowed_skills,
        model_config=role_data.model_config_override,
        creator_id=current_user.get("id"),
        is_public=role_data.is_public,
    )
    db.add(role)
    db.commit()
    db.refresh(role)
    return role


@router.put("/{role_id}", response_model=RoleResponse)
async def update_role(
    role_id: str,
    role_data: RoleUpdate,
    db: Session = Depends(get_db),
    current_user: Dict = Depends(get_current_user),
) -> Dict[str, Any]:
    """更新角色配置。"""
    role = db.query(AgentRole).filter(AgentRole.id == role_id).first()
    if not role:
        raise HTTPException(status_code=404, detail="角色不存在")

    update_data = role_data.model_dump(exclude_unset=True)
    # 映射 model_config_override -> model_config（避免 Pydantic 保留字冲突）
    if "model_config_override" in update_data:
        update_data["model_config"] = update_data.pop("model_config_override")

    for key, value in update_data.items():
        if hasattr(role, key):
            setattr(role, key, value)

    db.commit()
    db.refresh(role)
    return role


@router.delete("/{role_id}", status_code=204)
async def delete_role(
    role_id: str,
    db: Session = Depends(get_db),
    current_user: Dict = Depends(get_current_user),
) -> None:
    """删除角色。"""
    role = db.query(AgentRole).filter(AgentRole.id == role_id).first()
    if not role:
        raise HTTPException(status_code=404, detail="角色不存在")

    if role.is_preset:
        raise HTTPException(status_code=400, detail="预设角色不可删除")

    db.delete(role)
    db.commit()


@router.post("/{role_id}/activate")
async def activate_role(
    role_id: str,
    request: RoleActivateRequest,
    db: Session = Depends(get_db),
    current_user: Dict = Depends(get_current_user),
) -> Dict[str, Any]:
    """激活角色（绑定到当前会话）。"""
    role = db.query(AgentRole).filter(AgentRole.id == role_id).first()
    if not role:
        raise HTTPException(status_code=404, detail="角色不存在")

    # 更新使用计数
    role.usage_count = (role.usage_count or 0) + 1
    db.commit()

    return {
        "status": "activated",
        "role_id": role.id,
        "role_name": role.name,
        "session_id": request.session_id,
        "system_prompt": role.system_prompt,
        "personality": role.personality,
        "allowed_tools": role.allowed_tools,
        "allowed_skills": role.allowed_skills,
        "model_config": role.model_config,
    }
