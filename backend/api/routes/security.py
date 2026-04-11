"""
安全相关 API 路由模块，提供 RBAC 角色管理与审计日志查询接口。
"""

import json
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from loguru import logger
from sqlalchemy import func
from sqlalchemy.orm import Session

from api.dependencies import get_current_user, get_current_admin_user
from api.schemas import (
    AuditLogListResponse,
    AuditLogResponse,
    PermissionCheckRequest,
    PermissionCheckResponse,
    RoleResponse,
    UserRoleResponse,
    UserRoleUpdate,
)
from db.models import AuditLog, User, get_db
from security.rbac import RBACManager


router = APIRouter(prefix="/api/security", tags=["Security"])


# -------- RBAC 角色管理路由 --------

@router.get("/roles", response_model=list[RoleResponse])
async def list_roles(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取所有角色列表。"""
    rbac = RBACManager(db)
    rbac.ensure_built_in_roles()
    roles = await rbac.list_roles()
    return roles


@router.get("/users/{user_id}/role", response_model=UserRoleResponse)
async def get_user_role(
    user_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取指定用户的角色信息。"""
    rbac = RBACManager(db)
    role_name = await rbac.get_user_role(user_id)
    return UserRoleResponse(user_id=user_id, role_name=role_name, assigned_at=None)


@router.put("/users/{user_id}/role", response_model=UserRoleResponse)
async def set_user_role(
    user_id: str,
    body: UserRoleUpdate,
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user),
):
    """设置用户角色（仅管理员可操作）。"""
    rbac = RBACManager(db)
    rbac.ensure_built_in_roles()
    success = await rbac.set_user_role(user_id, body.role_name)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"角色 '{body.role_name}' 不存在"
        )
    return UserRoleResponse(
        user_id=user_id,
        role_name=body.role_name,
        assigned_at=datetime.now(timezone.utc),
    )


@router.post("/check-permission", response_model=PermissionCheckResponse)
async def check_permission(
    body: PermissionCheckRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """检查指定用户是否拥有某项权限。"""
    rbac = RBACManager(db)
    role_name = await rbac.get_user_role(body.user_id)
    allowed = await rbac.check_permission(body.user_id, body.permission)
    return PermissionCheckResponse(
        allowed=allowed,
        role=role_name,
        permission=body.permission,
    )


# -------- 审计日志路由 --------

@router.get("/audit-logs", response_model=AuditLogListResponse)
async def get_audit_logs(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    user_id: Optional[str] = Query(None, description="按用户 ID 筛选"),
    action: Optional[str] = Query(None, description="按操作类型筛选"),
    result: Optional[str] = Query(None, description="按结果筛选"),
    start_time: Optional[str] = Query(None, description="开始时间，ISO 格式"),
    end_time: Optional[str] = Query(None, description="结束时间，ISO 格式"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取审计日志列表，支持分页和多维度筛选。"""
    query = db.query(AuditLog)

    # 条件筛选
    if user_id:
        query = query.filter(AuditLog.user_id == user_id)
    if action:
        query = query.filter(AuditLog.action.contains(action))
    if result:
        query = query.filter(AuditLog.result == result)
    if start_time:
        try:
            start_dt = datetime.fromisoformat(start_time)
            query = query.filter(AuditLog.created_at >= start_dt)
        except ValueError:
            raise HTTPException(status_code=400, detail="start_time 格式无效")
    if end_time:
        try:
            end_dt = datetime.fromisoformat(end_time)
            query = query.filter(AuditLog.created_at <= end_dt)
        except ValueError:
            raise HTTPException(status_code=400, detail="end_time 格式无效")

    total = query.count()
    logs = (
        query.order_by(AuditLog.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return AuditLogListResponse(
        logs=[AuditLogResponse.model_validate(log) for log in logs],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/audit-logs/export")
async def export_audit_logs(
    user_id: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    start_time: Optional[str] = Query(None),
    end_time: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user),
):
    """导出审计日志为 JSONL 格式（仅管理员可操作）。"""
    query = db.query(AuditLog)

    if user_id:
        query = query.filter(AuditLog.user_id == user_id)
    if action:
        query = query.filter(AuditLog.action.contains(action))
    if start_time:
        try:
            start_dt = datetime.fromisoformat(start_time)
            query = query.filter(AuditLog.created_at >= start_dt)
        except ValueError:
            pass
    if end_time:
        try:
            end_dt = datetime.fromisoformat(end_time)
            query = query.filter(AuditLog.created_at <= end_dt)
        except ValueError:
            pass

    logs = query.order_by(AuditLog.created_at.desc()).all()

    def generate_jsonl():
        for log in logs:
            entry = {
                "id": log.id,
                "user_id": log.user_id,
                "action": log.action,
                "resource": log.resource,
                "result": log.result,
                "details": log.details,
                "ip_address": log.ip_address,
                "created_at": log.created_at.isoformat() if log.created_at else None,
            }
            yield json.dumps(entry, ensure_ascii=False) + "\n"

    return StreamingResponse(
        generate_jsonl(),
        media_type="application/x-jsonlines",
        headers={"Content-Disposition": "attachment; filename=audit_logs.jsonl"},
    )


@router.get("/audit-logs/stats")
async def get_audit_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取审计日志统计信息，包括按操作类型分组计数与成功率。"""
    total = db.query(func.count(AuditLog.id)).scalar() or 0
    success_count = (
        db.query(func.count(AuditLog.id))
        .filter(AuditLog.result == "success")
        .scalar() or 0
    )

    # 按操作类型分组计数
    action_stats = (
        db.query(AuditLog.action, func.count(AuditLog.id))
        .group_by(AuditLog.action)
        .order_by(func.count(AuditLog.id).desc())
        .limit(20)
        .all()
    )

    # 最活跃用户
    user_stats = (
        db.query(AuditLog.user_id, func.count(AuditLog.id))
        .filter(AuditLog.user_id.isnot(None))
        .group_by(AuditLog.user_id)
        .order_by(func.count(AuditLog.id).desc())
        .limit(5)
        .all()
    )

    return {
        "total": total,
        "success_count": success_count,
        "success_rate": round(success_count / total * 100, 1) if total > 0 else 0,
        "action_stats": [{"action": a, "count": c} for a, c in action_stats],
        "top_users": [{"user_id": u, "count": c} for u, c in user_stats],
    }
