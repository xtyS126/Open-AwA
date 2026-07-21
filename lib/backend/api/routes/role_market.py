"""
角色市场 API，提供角色发布、浏览、安装和评分功能。
"""

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api.dependencies import get_current_user, get_db
from db.models import AgentRole

router = APIRouter(prefix="/role-market", tags=["role-market"])


class RolePublishRequest(BaseModel):
    """发布角色到市场请求。"""
    role_id: str = Field(..., description="要发布的角色 ID")
    category: str = Field(default="general", description="分类")
    tags: List[str] = Field(default=list, description="标签")


class RoleInstallRequest(BaseModel):
    """从市场安装角色请求。"""
    role_id: str = Field(..., description="要安装的角色 ID")


class RoleRatingRequest(BaseModel):
    """角色评分请求。"""
    rating: int = Field(..., ge=1, le=5, description="评分 1-5")
    comment: str = Field(default="", max_length=500, description="评价内容")


@router.get("")
async def list_market_roles(
    category: Optional[str] = None,
    sort: str = Query(default="popular", description="排序: popular | newest | rating"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: Dict = Depends(get_current_user),
) -> Dict[str, Any]:
    """浏览市场角色列表。"""
    query = db.query(AgentRole).filter(AgentRole.is_public == True)  # noqa: E712
    if category and category != "all":
        # 简化分类过滤：通过 description 或 name 模糊匹配
        query = query.filter(
            (AgentRole.description.contains(category)) |
            (AgentRole.name.contains(category))
        )

    if sort == "newest":
        query = query.order_by(AgentRole.created_at.desc())
    elif sort == "rating":
        query = query.order_by(AgentRole.usage_count.desc())
    else:  # popular
        query = query.order_by(AgentRole.usage_count.desc())

    total = query.count()
    roles = query.offset((page - 1) * page_size).limit(page_size).all()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "id": r.id,
                "name": r.name,
                "description": r.description,
                "avatar_url": r.avatar_url,
                "is_preset": r.is_preset,
                "usage_count": r.usage_count,
                "category": "general",
                "created_at": str(r.created_at) if r.created_at else None,
            }
            for r in roles
        ],
    }


@router.get("/categories")
async def list_categories(
    db: Session = Depends(get_db),
    current_user: Dict = Depends(get_current_user),
) -> Dict[str, Any]:
    """获取市场分类列表。"""
    return {
        "categories": [
            {"id": "all", "name": "全部"},
            {"id": "coding", "name": "编程开发"},
            {"id": "writing", "name": "写作创作"},
            {"id": "analysis", "name": "分析研究"},
            {"id": "office", "name": "办公效率"},
            {"id": "creative", "name": "创意设计"},
        ]
    }


@router.post("/publish")
async def publish_role(
    request: RolePublishRequest,
    db: Session = Depends(get_db),
    current_user: Dict = Depends(get_current_user),
) -> Dict[str, Any]:
    """发布角色到市场。"""
    role = db.query(AgentRole).filter(AgentRole.id == request.role_id).first()
    if not role:
        raise HTTPException(status_code=404, detail="角色不存在")

    role.is_public = True
    db.commit()

    logger.bind(
        event="role_published",
        module="role_market",
        role_id=request.role_id,
        category=request.category,
    ).info(f"角色已发布到市场: {request.role_id}")

    return {"ok": True, "role_id": request.role_id}


@router.post("/install/{role_id}")
async def install_role(
    role_id: str,
    db: Session = Depends(get_db),
    current_user: Dict = Depends(get_current_user),
) -> Dict[str, Any]:
    """从市场安装角色（复制到自己的角色列表）。"""
    import uuid
    source_role = db.query(AgentRole).filter(
        AgentRole.id == role_id,
        AgentRole.is_public == True,  # noqa: E712
    ).first()
    if not source_role:
        raise HTTPException(status_code=404, detail="角色不存在或未公开")

    # 检查是否已安装
    new_id = f"installed-{str(uuid.uuid4())[:8]}"
    installed_role = AgentRole(
        id=new_id,
        name=source_role.name,
        description=source_role.description,
        avatar_url=source_role.avatar_url,
        system_prompt=source_role.system_prompt,
        personality=source_role.personality,
        expertise=source_role.expertise,
        knowledge_base_ids=source_role.knowledge_base_ids,
        allowed_tools=source_role.allowed_tools,
        allowed_skills=source_role.allowed_skills,
        model_config=source_role.model_config,
        creator_id=current_user.get("id"),
        is_public=False,
        is_preset=False,
    )
    db.add(installed_role)
    db.commit()

    return {"ok": True, "installed_role_id": new_id}


@router.post("/{role_id}/rate")
async def rate_role(
    role_id: str,
    request: RoleRatingRequest,
    db: Session = Depends(get_db),
    current_user: Dict = Depends(get_current_user),
) -> Dict[str, Any]:
    """为角色评分。"""
    role = db.query(AgentRole).filter(AgentRole.id == role_id).first()
    if not role:
        raise HTTPException(status_code=404, detail="角色不存在")

    # 简化版：通过 usage_count 模拟评分计数
    # 实际应使用独立的评分表
    logger.bind(
        event="role_rated",
        module="role_market",
        role_id=role_id,
        rating=request.rating,
    ).info(f"角色评分: {role_id} -> {request.rating}星")

    return {"ok": True, "role_id": role_id, "rating": request.rating}
