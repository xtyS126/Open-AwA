"""
安全相关 API 路由模块，提供 RBAC 角色管理、审计日志查询与权限请求实时推送接口。
"""

import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from loguru import logger
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.dependencies import get_current_user, get_current_admin_user
from api.schemas import (
    AuditLogListResponse,
    AuditLogResponse,
    PermissionCheckRequest,
    PermissionCheckResponse,
    PermissionReplyRequest,
    RoleResponse,
    SavedPermissionResponse,
    SavedPermissionsListResponse,
    UserRoleResponse,
    UserRoleUpdate,
)
from config.settings import settings
from db.models import AuditLog, User, get_db
from db.permission_models import PermissionSaved, PROJECT_GLOBAL
from security.rbac import RBACManager


router = APIRouter(prefix="/api/security", tags=["Security"])


# -------- 权限请求实时推送 --------

class PendingPermissionRequest:
    """待处理的权限请求条目。"""

    def __init__(
        self,
        request_id: str,
        user_id: str,
        session_id: str,
        action: str,
        resources: list[str],
        save: list[str] | None = None,
        metadata: Optional[dict] = None,
        agent: Optional[str] = None,
    ) -> None:
        self.request_id = request_id
        self.user_id = user_id
        self.session_id = session_id
        self.action = action
        self.resources = resources
        self.save = save or []
        self.metadata = metadata or {}
        self.agent = agent
        self.created_at = datetime.now(timezone.utc).isoformat()
        # 用于等待回复的 Future，reply 端设置结果后，请求端即可拿到回复
        self._reply_future: asyncio.Future[str] = asyncio.get_event_loop().create_future()

    def to_dict(self) -> dict:
        """序列化为前端可消费的字典格式。"""
        return {
            "id": self.request_id,
            "session_id": self.session_id,
            "action": self.action,
            "resources": self.resources,
            "save": self.save,
            "metadata": self.metadata,
            "agent": self.agent,
            "created_at": self.created_at,
        }


# 内存队列：user_id -> 待处理权限请求列表
_pending_permission_queue: dict[str, list[PendingPermissionRequest]] = {}

# SSE 推送队列：user_id -> 该用户所有 SSE 连接的 asyncio.Queue 列表
# 当新权限请求入队时，同时向所有已连接的 SSE 客户端推送事件
_sse_subscribers: dict[str, list[asyncio.Queue[str]]] = {}


def _get_user_queue(user_id: str) -> list[PendingPermissionRequest]:
    """获取指定用户的待处理权限请求队列。"""
    if user_id not in _pending_permission_queue:
        _pending_permission_queue[user_id] = []
    return _pending_permission_queue[user_id]


def _subscribe_sse(user_id: str) -> asyncio.Queue[str]:
    """注册一个 SSE 客户端订阅，返回用于接收事件的 asyncio.Queue。"""
    queue: asyncio.Queue[str] = asyncio.Queue()
    if user_id not in _sse_subscribers:
        _sse_subscribers[user_id] = []
    _sse_subscribers[user_id].append(queue)
    logger.bind(
        event="sse_subscriber_added",
        user_id=user_id,
        subscriber_count=len(_sse_subscribers[user_id]),
    ).debug(f"SSE 订阅者已注册: {user_id}")
    return queue


def _unsubscribe_sse(user_id: str, queue: asyncio.Queue[str]) -> None:
    """移除一个 SSE 客户端订阅。"""
    if user_id in _sse_subscribers:
        try:
            _sse_subscribers[user_id].remove(queue)
        except ValueError:
            pass
        if not _sse_subscribers[user_id]:
            del _sse_subscribers[user_id]
    logger.bind(
        event="sse_subscriber_removed",
        user_id=user_id,
    ).debug(f"SSE 订阅者已移除: {user_id}")


def _broadcast_to_sse(user_id: str, event_data: dict) -> None:
    """向指定用户的所有 SSE 客户端广播权限请求事件。"""
    subscribers = _sse_subscribers.get(user_id, [])
    if not subscribers:
        return
    payload = json.dumps(event_data, ensure_ascii=False)
    for queue in subscribers:
        try:
            queue.put_nowait(payload)
        except asyncio.QueueFull:
            logger.bind(
                event="sse_queue_full",
                user_id=user_id,
            ).warning("SSE 推送队列已满，丢弃事件")


def enqueue_permission_request(
    user_id: str,
    session_id: str,
    action: str,
    resources: list[str],
    save: list[str] | None = None,
    metadata: Optional[dict] = None,
    agent: Optional[str] = None,
    timeout: float = 120.0,
) -> asyncio.Future[str]:
    """
    将权限请求加入用户队列，并返回一个 Future。
    调用方 await 此 Future 即可阻塞等待用户回复（once/always/reject）。
    超时后 Future 自动以 "reject" 结束。

    参数:
        user_id: 目标用户 ID
        session_id: 会话 ID
        action: 请求的操作类型（如 read/write/execute）
        resources: 操作涉及的资源列表
        save: 可持久化的权限规则名称列表
        metadata: 附加元数据
        agent: 发起请求的 Agent 标识
        timeout: 等待回复的超时时间（秒），默认 120 秒

    返回:
        asyncio.Future[str] - 回复值为 "once"/"always"/"reject"
    """
    request_id = uuid.uuid4().hex[:16]
    entry = PendingPermissionRequest(
        request_id=request_id,
        user_id=user_id,
        session_id=session_id,
        action=action,
        resources=resources,
        save=save,
        metadata=metadata,
        agent=agent,
    )
    queue = _get_user_queue(user_id)
    queue.append(entry)

    # 向所有已连接的 SSE 客户端广播权限请求事件
    _broadcast_to_sse(user_id, entry.to_dict())

    logger.bind(
        event="permission_request_enqueued",
        user_id=user_id,
        request_id=request_id,
        action=action,
    ).info(f"权限请求已入队: {request_id} ({action})")

    # 设置超时自动拒绝
    async def _timeout_reject() -> None:
        await asyncio.sleep(timeout)
        if not entry._reply_future.done():
            entry._reply_future.set_result("reject")
            # 从队列中移除已超时的请求
            try:
                queue.remove(entry)
            except ValueError:
                pass
            logger.bind(
                event="permission_request_timeout",
                user_id=user_id,
                request_id=request_id,
            ).warning(f"权限请求超时自动拒绝: {request_id}")

    asyncio.create_task(_timeout_reject())

    return entry._reply_future


def _resolve_pending_request(user_id: str, request_id: str, reply: str) -> bool:
    """
    解析指定用户的待处理权限请求。
    找到请求后设置 Future 结果并从队列中移除。
    返回是否成功找到并解析了请求。
    """
    queue = _get_user_queue(user_id)
    for entry in queue:
        if entry.request_id == request_id:
            if not entry._reply_future.done():
                entry._reply_future.set_result(reply)
            queue.remove(entry)
            return True
    return False


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


# -------- 持久化权限规则路由 --------

@router.get("/permissions/pending")
async def get_pending_permissions(
    current_user: User = Depends(get_current_user),
):
    """
    获取当前用户待处理的权限请求列表。
    前端通过轮询此接口实现权限请求的实时推送。
    """
    user_id = str(current_user.id)
    queue = _pending_permission_queue.get(user_id, [])
    return {
        "requests": [entry.to_dict() for entry in queue],
        "count": len(queue),
    }


@router.get("/permissions/stream")
async def stream_permission_requests(
    request: Request,
    api_key: Optional[str] = Query(None, description="API Key（用于 SSE 连接认证，因 EventSource 不支持自定义 Header）"),
    db: Session = Depends(get_db),
):
    """
    SSE 端点：实时推送当前用户的权限请求事件。
    前端连接此端点后，当后端有新的权限请求时，会以
    event: permission_request 格式推送给客户端。
    连接建立时先推送当前已有的待处理请求，之后持续监听新请求。

    认证方式：优先使用 Authorization Header（标准 Bearer 认证），
    若 Header 认证失败则尝试 query parameter 中的 api_key。
    """
    # 尝试标准认证（Authorization Header / Cookie）
    user: Optional[User] = None
    from api.dependencies import (
        _normalize_request_token,
        _get_owner_from_settings,
        _resolve_jwt_user,
        oauth2_scheme,
    )
    import secrets as _secrets

    # 路径 1: Authorization Header 认证
    credentials = await oauth2_scheme(request)
    configured_key = settings.OPENAWA_API_KEY.get_secret_value()
    if credentials:
        token = _normalize_request_token(credentials.credentials)
        # API Key 认证
        if configured_key and token and _secrets.compare_digest(token, configured_key):
            user = _get_owner_from_settings()
        # JWT 认证
        if user is None and token:
            user = await _resolve_jwt_user(token, db)

    # 路径 2: Cookie 认证
    if user is None:
        from config.security import ACCESS_TOKEN_COOKIE_NAME
        cookie_token = request.cookies.get(ACCESS_TOKEN_COOKIE_NAME, "")
        cookie_token_normalized = _normalize_request_token(cookie_token)
        if cookie_token_normalized:
            user = await _resolve_jwt_user(cookie_token_normalized, db)

    # 路径 3: query parameter API Key 认证（EventSource 不支持自定义 Header）
    if user is None and api_key:
        normalized_key = _normalize_request_token(api_key)
        if configured_key and normalized_key and _secrets.compare_digest(normalized_key, configured_key):
            user = _get_owner_from_settings()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="认证失败，请提供有效的 API Key",
        )

    user_id = str(user.id)
    sse_queue = _subscribe_sse(user_id)

    async def event_generator():
        try:
            # 连接建立时先推送当前已有的待处理请求
            existing = _pending_permission_queue.get(user_id, [])
            for entry in existing:
                yield f"event: permission_request\ndata: {json.dumps(entry.to_dict(), ensure_ascii=False)}\n\n"

            # 持续监听新事件
            while True:
                try:
                    # 使用 wait_for 避免无限阻塞，同时定期发送心跳
                    payload = await asyncio.wait_for(sse_queue.get(), timeout=30.0)
                    yield f"event: permission_request\ndata: {payload}\n\n"
                except asyncio.TimeoutError:
                    # 发送心跳保持连接活跃
                    yield ": heartbeat\n\n"
        except asyncio.CancelledError:
            # 客户端断开连接
            pass
        finally:
            _unsubscribe_sse(user_id, sse_queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.post("/permissions/reply")
async def reply_to_permission(
    body: PermissionReplyRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    回复权限请求。

    当 reply 为 "always" 且 body.message 中包含权限规则名（action:resource 格式）时，
    将对应权限规则持久化到 PermissionSaved 表。
    reply 值由 Pydantic Literal 类型在请求解析阶段自动校验。
    同时解析内存队列中对应的待处理请求，使请求方获得回复结果。
    """
    request_id = body.request_id
    reply = body.reply.lower()
    user_id = str(current_user.id)

    # 解析内存队列中的待处理请求
    resolved = _resolve_pending_request(user_id, request_id, reply)
    if not resolved:
        logger.bind(
            event="permission_reply_no_pending",
            request_id=request_id,
            user_id=user_id,
        ).warning(f"回复的权限请求不在待处理队列中: {request_id}")

    # 持久化 "always allow" 规则
    if reply == "always":
        saved_count = 0
        # 尝试从消息中提取权限规则名进行保存
        for rule_name in body.message.split(",") if body.message else []:
            rule_name = rule_name.strip()
            if not rule_name:
                continue
            # rule_name 格式: action:resource（如 file:read 或 skill:*）
            parts = rule_name.split(":", 1)
            action = parts[0] if len(parts) >= 1 else rule_name
            resource = parts[1] if len(parts) >= 2 else "*"
            # 幂等插入（重复规则忽略）
            existing = (
                db.query(PermissionSaved)
                .filter(
                    PermissionSaved.project_id == PROJECT_GLOBAL,
                    PermissionSaved.action == action,
                    PermissionSaved.resource == resource,
                )
                .first()
            )
            if not existing:
                db.add(PermissionSaved(
                    project_id=PROJECT_GLOBAL,
                    action=action,
                    resource=resource,
                    created_by=user_id,
                ))
                saved_count += 1
        if saved_count > 0:
            try:
                # 先 flush 捕获 IntegrityError，再用 SAVEPOINT 隔离回滚
                db.flush()
            except IntegrityError:
                # 并发重复插入视为幂等成功，仅回滚当前 SAVEPOINT
                db.rollback()
                saved_count = 0
                logger.bind(
                    event="permission_rule_saved_duplicate",
                    user_id=user_id,
                ).info("权限规则已存在（并发重复插入），忽略")
            else:
                db.commit()
            if saved_count > 0:
                logger.bind(
                    event="permission_rule_saved",
                    user_id=user_id,
                    count=saved_count,
                ).info(f"已保存 {saved_count} 条权限规则")
        else:
            logger.bind(
                event="permission_reply_always_no_rules",
                request_id=request_id,
            ).info("always 回复但未附带需要保存的权限规则")

    logger.bind(
        event="permission_reply",
        request_id=request_id,
        reply=reply,
        user_id=str(current_user.id),
    ).info(f"权限请求 {request_id} 已回复: {reply}")

    # 向 SSE 客户端广播权限请求已回复事件，前端可据此移除已回复的请求
    _broadcast_to_sse(user_id, {
        "type": "permission_reply",
        "request_id": request_id,
        "reply": reply,
    })

    return {"ok": True}


@router.get("/permissions/saved", response_model=SavedPermissionsListResponse)
async def get_saved_permissions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    获取当前用户已保存的持久化权限规则列表。
    """
    user_id = str(current_user.id)
    permissions = (
        db.query(PermissionSaved)
        .filter(PermissionSaved.created_by == user_id)
        .order_by(PermissionSaved.created_at.desc())
        .all()
    )
    return SavedPermissionsListResponse(
        permissions=[SavedPermissionResponse.model_validate(p) for p in permissions],
        total=len(permissions),
    )


@router.delete("/permissions/saved/{permission_id}")
async def delete_saved_permission(
    permission_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    删除指定的持久化权限规则。
    """
    user_id = str(current_user.id)
    perm = (
        db.query(PermissionSaved)
        .filter(
            PermissionSaved.id == permission_id,
            PermissionSaved.created_by == user_id,
        )
        .first()
    )
    if not perm:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"权限规则 {permission_id} 不存在或无权删除",
        )
    db.delete(perm)
    db.commit()
    logger.bind(
        event="permission_rule_deleted",
        user_id=user_id,
        permission_id=permission_id,
    ).info(f"已删除权限规则 {permission_id}")
    return {"ok": True}


@router.delete("/permissions/saved")
async def delete_all_saved_permissions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    删除当前用户所有已保存的持久化权限规则。
    """
    user_id = str(current_user.id)
    deleted_count = (
        db.query(PermissionSaved)
        .filter(PermissionSaved.created_by == user_id)
        .delete()
    )
    db.commit()
    logger.bind(
        event="permission_rules_deleted_all",
        user_id=user_id,
        count=deleted_count,
    ).info(f"已删除 {deleted_count} 条权限规则")
    return {"ok": True, "deleted_count": deleted_count}
