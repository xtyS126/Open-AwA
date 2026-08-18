"""
AI 角色管理 API 路由，提供角色 CRUD、切换、预设模板接口和 Live2D 模型绑定。
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
from db.models import AgentRole, Live2DModel

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
    live2d_model_id: Optional[str] = None
    live2d_model: Optional[Dict[str, Any]] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class Live2DModelInfoResponse(BaseModel):
    """Live2D 模型简要信息（用于角色详情嵌入）。"""
    model_config = ConfigDict(from_attributes=True)

    id: str
    model_name: str
    texture_paths: List[str] = Field(default_factory=list)
    version: int = 1


class RoleLive2DBindRequest(BaseModel):
    """绑定/解绑 Live2D 模型请求。"""
    live2d_model_id: Optional[str] = Field(default=None, description="Live2D 模型 ID，为 None 表示解绑")


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


def _build_role_response(role: AgentRole, db: Session) -> Dict[str, Any]:
    """构建角色响应，附带 Live2D 模型信息（如果已绑定）。"""
    result = {
        "id": role.id,
        "name": role.name,
        "description": role.description,
        "avatar_url": role.avatar_url,
        "system_prompt": role.system_prompt,
        "personality": role.personality,
        "expertise": role.expertise,
        "knowledge_base_ids": role.knowledge_base_ids,
        "allowed_tools": role.allowed_tools,
        "allowed_skills": role.allowed_skills,
        "model_config": role.model_config,
        "creator_id": role.creator_id,
        "is_public": role.is_public,
        "usage_count": role.usage_count,
        "is_preset": role.is_preset,
        "live2d_model_id": role.live2d_model_id,
        "live2d_model": None,
        "created_at": role.created_at,
        "updated_at": role.updated_at,
    }
    if role.live2d_model_id:
        live2d_model = db.get(Live2DModel, role.live2d_model_id)
        if live2d_model:
            result["live2d_model"] = {
                "id": live2d_model.id,
                "model_name": live2d_model.model_name,
                "texture_paths": live2d_model.texture_paths or [],
                "version": live2d_model.version,
            }
    return result


@router.get("/{role_id}", response_model=RoleResponse)
async def get_role(
    role_id: str,
    db: Session = Depends(get_db),
    current_user: Dict = Depends(get_current_user),
) -> Dict[str, Any]:
    """获取角色详情（包含 Live2D 模型绑定信息）。"""
    role = db.query(AgentRole).filter(AgentRole.id == role_id).first()
    if not role:
        raise HTTPException(status_code=404, detail="角色不存在")
    return _build_role_response(role, db)


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


@router.put("/{role_id}/live2d", response_model=RoleResponse)
async def bind_live2d_to_role(
    role_id: str,
    body: RoleLive2DBindRequest,
    db: Session = Depends(get_db),
    current_user: Dict = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    绑定或解绑角色的 Live2D 模型。

    - live2d_model_id 不为空时：校验模型存在，绑定到角色
    - live2d_model_id 为 None 时：解绑角色的 Live2D 模型
    """
    role = db.query(AgentRole).filter(AgentRole.id == role_id).first()
    if not role:
        raise HTTPException(status_code=404, detail="角色不存在")

    # 校验用户权限：只能修改自己创建的角色
    user_id = current_user.get("id")
    role_creator_id = role.creator_id
    if role_creator_id is not None and str(role_creator_id) != str(user_id):
        raise HTTPException(status_code=403, detail="无权修改该角色的 Live2D 绑定")

    if body.live2d_model_id is not None:
        # 校验 Live2D 模型存在
        live2d_model = db.get(Live2DModel, body.live2d_model_id)
        if live2d_model is None:
            raise HTTPException(status_code=404, detail="Live2D 模型不存在")
        role.live2d_model_id = body.live2d_model_id
    else:
        # 解绑
        role.live2d_model_id = None

    db.commit()
    db.refresh(role)

    logger.bind(
        event="role_live2d_bind",
        module="roles",
        role_id=role_id,
        live2d_model_id=body.live2d_model_id,
    ).info(f"角色 {role_id} {'绑定' if body.live2d_model_id else '解绑'} Live2D 模型")

    return _build_role_response(role, db)


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
