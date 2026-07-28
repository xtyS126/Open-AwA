"""
P2 安全增强 API 路由模块，提供细粒度权限管理、IP 白名单/黑名单与异常事件查询。

路由前缀: /api/security/enhanced
所有接口均需认证，管理员接口需 admin 角色。

注：CSRF token 管理与用户级速率限制统计已迁移至成熟包：
- CSRF 防护由 fastapi-csrf-protect 通过双提交 Cookie 模式在 main.py 中间件层处理
  前端通过 GET /api/auth/csrf-token 获取 token
- 速率限制由 slowapi 在中间件层全局处理，无需用户级统计端点
"""

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from api.dependencies import get_current_user, get_current_admin_user
from api.schemas import (
    AnomalyEventResponse,
    CustomRoleCreate,
    CustomRoleResponse,
    CustomRoleUpdate,
    FineGrainedPermissionCheckRequest,
    FineGrainedPermissionCheckResponse,
    IpAccessCheckRequest,
    IpAccessCheckResponse,
    IpAccessEntryCreate,
    IpAccessEntryResponse,
)
from db.models import User, get_db
from security.anomaly_detector import get_anomaly_detector
from security.fine_grained_permissions import (
    FineGrainedPermissionManager,
    get_permission_manager,
)
from security.ip_access import IpAccessController


router = APIRouter(prefix="/api/security/enhanced", tags=["SecurityEnhanced"])


# -------- 细粒度权限管理 --------


@router.get("/permissions/known")
async def list_known_permissions(
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """列出系统预定义的所有权限目录。"""
    manager = FineGrainedPermissionManager.__new__(FineGrainedPermissionManager)
    return {"permissions": manager.list_known_permissions()}


@router.post("/permissions/check", response_model=FineGrainedPermissionCheckResponse)
async def check_fine_grained_permission(
    body: FineGrainedPermissionCheckRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """检查指定用户是否拥有某项细粒度权限。"""
    manager = get_permission_manager(db)
    allowed = await manager.check_permission(body.user_id, body.permission)
    return FineGrainedPermissionCheckResponse(
        allowed=allowed,
        permission=body.permission,
    )


@router.get("/roles", response_model=list[CustomRoleResponse])
async def list_custom_roles(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """列出所有自定义角色。"""
    manager = get_permission_manager(db)
    return manager.list_roles()


@router.post("/roles", response_model=CustomRoleResponse, status_code=status.HTTP_201_CREATED)
async def create_custom_role(
    body: CustomRoleCreate,
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user),
) -> Dict[str, Any]:
    """创建自定义角色（仅管理员）。"""
    manager = get_permission_manager(db)
    try:
        role = manager.create_role(
            name=body.name,
            permissions=body.permissions,
            display_name=body.display_name,
            description=body.description,
            created_by=str(admin_user.id),
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    # 重新查询以获取完整字段（并发场景下角色可能已被删除）
    role_info = manager.get_role(role.name)
    if not role_info:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="角色创建后查询失败，请重试",
        )
    return CustomRoleResponse(**role_info)


@router.get("/roles/{role_name}", response_model=CustomRoleResponse)
async def get_custom_role(
    role_name: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """获取指定自定义角色详情。"""
    manager = get_permission_manager(db)
    role_info = manager.get_role(role_name)
    if not role_info:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"角色 '{role_name}' 不存在")
    return CustomRoleResponse(**role_info)


@router.put("/roles/{role_name}", response_model=CustomRoleResponse)
async def update_custom_role(
    role_name: str,
    body: CustomRoleUpdate,
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user),
) -> Dict[str, Any]:
    """更新自定义角色（仅管理员）。"""
    manager = get_permission_manager(db)
    try:
        manager.update_role(
            name=role_name,
            permissions=body.permissions,
            display_name=body.display_name,
            description=body.description,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    # 并发场景下角色可能已被删除
    role_info = manager.get_role(role_name)
    if not role_info:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"角色 '{role_name}' 更新后查询失败，可能已被删除",
        )
    return CustomRoleResponse(**role_info)


@router.delete("/roles/{role_name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_custom_role(
    role_name: str,
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user),
) -> None:
    """删除自定义角色（仅管理员）。"""
    manager = get_permission_manager(db)
    try:
        manager.delete_role(role_name)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


# -------- IP 白名单/黑名单管理 --------


@router.get("/ip-access", response_model=list[IpAccessEntryResponse])
async def list_ip_access_entries(
    list_type: Optional[str] = Query(None, description="筛选类型: whitelist/blacklist"),
    active_only: bool = Query(True, description="仅返回活跃条目"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """列出 IP 访问条目。"""
    controller = IpAccessController(db)
    return controller.list_entries(list_type=list_type, active_only=active_only)


@router.post("/ip-access", response_model=IpAccessEntryResponse, status_code=status.HTTP_201_CREATED)
async def add_ip_access_entry(
    body: IpAccessEntryCreate,
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user),
) -> Dict[str, Any]:
    """添加 IP 到白名单或黑名单（仅管理员）。"""
    controller = IpAccessController(db)
    try:
        entry = controller.add_entry(
            ip_cidr=body.ip_cidr,
            list_type=body.list_type,
            reason=body.reason,
            created_by=str(admin_user.id),
            expires_at=body.expires_at,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    return IpAccessEntryResponse(
        id=entry.id,
        ip_cidr=entry.ip_cidr,
        list_type=entry.list_type,
        reason=entry.reason,
        created_by=entry.created_by,
        is_active=entry.is_active,
        expires_at=entry.expires_at.isoformat() if entry.expires_at else None,
        created_at=entry.created_at.isoformat() if entry.created_at else None,
    )


@router.delete("/ip-access/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_ip_access_entry(
    entry_id: int,
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user),
) -> None:
    """移除 IP 访问条目（仅管理员）。"""
    controller = IpAccessController(db)
    try:
        controller.remove_entry(entry_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post("/ip-access/check", response_model=IpAccessCheckResponse)
async def check_ip_access(
    body: IpAccessCheckRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """检查指定 IP 是否被允许访问。"""
    controller = IpAccessController(db)
    result = controller.check_ip(body.ip_address)
    return IpAccessCheckResponse(**result)


# -------- 异常事件查询 --------


@router.get("/anomalies", response_model=list[AnomalyEventResponse])
async def list_anomaly_events(
    event_type: Optional[str] = Query(None, description="筛选事件类型"),
    user_id: Optional[str] = Query(None, description="筛选用户 ID"),
    resolved: Optional[bool] = Query(None, description="筛选是否已解决"),
    limit: int = Query(50, ge=1, le=500, description="返回最大数量"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """列出异常行为事件。"""
    detector = get_anomaly_detector()
    return detector.list_events(
        db=db,
        event_type=event_type,
        user_id=user_id,
        resolved=resolved,
        limit=limit,
    )


@router.post("/anomalies/{event_id}/resolve", status_code=status.HTTP_200_OK)
async def resolve_anomaly_event(
    event_id: int,
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user),
) -> Dict[str, Any]:
    """标记异常事件为已解决（仅管理员）。"""
    detector = get_anomaly_detector()
    try:
        detector.resolve_event(db=db, event_id=event_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    return {"ok": True}


# -------- CSRF Token 管理 --------
# 注：CSRF 防护已迁移至 fastapi-csrf-protect 双提交 Cookie 模式，
# 由 main.py 的 csrf_protection_middleware 中间件统一处理。
# 前端通过 GET /api/auth/csrf-token 获取 token，无需显式管理端点。


# -------- 用户级速率限制统计 --------
# 注：UserRateLimiter 已删除，速率限制由 slowapi 在中间件层全局处理，
# 不再提供用户级统计端点。如需限流配置，请参考 main.py 中的 limiter 配置。
