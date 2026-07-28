"""
细粒度权限模块，提供 resource:action 格式的权限定义、自定义角色管理与权限校验。

权限格式约定：
- "resource:action" 二段式，如 "plugin:install"、"skill:execute"、"model:use"、"billing:view"
- 支持层级通配符："skill:*" 匹配 "skill:read"、"skill:execute" 等
- "*" 匹配所有权限（仅管理员）

与 RBACManager（security/rbac.py）互补：
- RBACManager: 面向内置角色（admin/developer/viewer）的权限校验
- FineGrainedPermissionManager: 面向自定义角色的细粒度权限管理
两者通过 check_permission 统一入口协同工作。
"""

import json
import re
from datetime import datetime, timezone
from typing import Optional

from loguru import logger
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from db.models import CustomRole, UserRole, Role


# 权限标识正则：resource:action，resource 和 action 均为小写字母+下划线+数字
# action 部分允许单独的 "*" 通配符（如 "skill:*"）
PERMISSION_PATTERN = re.compile(r"^[a-z][a-z0-9_]*:([a-z][a-z0-9_]*|\*)$")

# 系统预定义权限目录（resource:action）
KNOWN_PERMISSIONS: dict[str, str] = {
    "plugin:install": "安装插件",
    "plugin:uninstall": "卸载插件",
    "plugin:read": "查看插件",
    "plugin:execute": "执行插件",
    "plugin:publish": "发布插件到市场",
    "skill:read": "查看技能",
    "skill:execute": "执行技能",
    "skill:install": "安装技能",
    "skill:create": "创建技能",
    "skill:delete": "删除技能",
    "model:use": "使用模型",
    "model:read": "查看模型配置",
    "model:write": "修改模型配置",
    "billing:read": "查看计费",
    "billing:write": "修改计费配置",
    "billing:export": "导出计费报表",
    "memory:read": "查看记忆",
    "memory:write": "写入记忆",
    "memory:delete": "删除记忆",
    "chat:send": "发送消息",
    "chat:history": "查看历史",
    "mcp:read": "查看 MCP 配置",
    "mcp:connect": "连接 MCP 服务器",
    "mcp:write": "修改 MCP 配置",
    "subagent:read": "查看子智能体",
    "subagent:execute": "执行子智能体",
    "subagent:write": "修改子智能体",
    "workflow:read": "查看工作流",
    "workflow:execute": "执行工作流",
    "workflow:write": "修改工作流",
    "security:read": "查看安全配置",
    "security:write": "修改安全配置",
    "system:config": "系统配置",
    "user:manage": "用户管理",
}


def validate_permission_format(permission: str) -> bool:
    """
    校验权限标识格式是否符合 resource:action 规范。

    Args:
        permission: 权限标识字符串。

    Returns:
        True 表示格式合法。
    """
    if permission == "*":
        return True
    return bool(PERMISSION_PATTERN.match(permission))


def normalize_permissions(permissions: list[str]) -> list[str]:
    """
    规范化权限列表：去重、过滤空值、校验格式。

    Args:
        permissions: 原始权限列表。

    Returns:
        规范化后的权限列表。

    Raises:
        ValueError: 当存在格式非法的权限时。
    """
    seen: set[str] = set()
    normalized: list[str] = []
    for perm in permissions:
        perm = perm.strip().lower()
        if not perm:
            continue
        if not validate_permission_format(perm):
            raise ValueError(f"权限标识格式非法: {perm}，应为 resource:action 格式")
        if perm not in seen:
            seen.add(perm)
            normalized.append(perm)
    return normalized


class FineGrainedPermissionManager:
    """细粒度权限管理器，提供自定义角色 CRUD 与权限校验。"""

    def __init__(self, db: Session):
        """
        初始化细粒度权限管理器。

        Args:
            db: 数据库会话实例。
        """
        self.db = db
        logger.debug("FineGrainedPermissionManager initialized")

    # -------- 自定义角色 CRUD --------

    def create_role(
        self,
        name: str,
        permissions: list[str],
        display_name: str = "",
        description: str = "",
        created_by: Optional[str] = None,
    ) -> CustomRole:
        """
        创建自定义角色。

        Args:
            name: 角色名称（唯一）。
            permissions: 权限列表，格式为 resource:action。
            display_name: 显示名称。
            description: 角色描述。
            created_by: 创建者用户 ID。

        Returns:
            创建的 CustomRole 实例。

        Raises:
            ValueError: 角色名已存在或权限格式非法。
        """
        name = name.strip().lower()
        if not name:
            raise ValueError("角色名称不能为空")

        # 检查角色名是否与内置角色冲突
        if name in {"admin", "developer", "viewer"}:
            raise ValueError(f"角色名 '{name}' 与内置角色冲突")

        # 检查是否已存在
        existing = self.db.query(CustomRole).filter(CustomRole.name == name).first()
        if existing:
            raise ValueError(f"角色 '{name}' 已存在")

        normalized = normalize_permissions(permissions)

        role = CustomRole(
            name=name,
            display_name=display_name or name,
            description=description,
            permissions=json.dumps(normalized),
            created_by=created_by,
            is_system=False,
        )
        self.db.add(role)
        try:
            self.db.commit()
        except IntegrityError as e:
            self.db.rollback()
            raise ValueError(f"角色 '{name}' 已存在（并发创建冲突）") from e
        self.db.refresh(role)
        logger.bind(
            event="custom_role_created",
            role_name=name,
            permission_count=len(normalized),
        ).info(f"自定义角色已创建: {name}（{len(normalized)} 项权限）")
        return role

    def update_role(
        self,
        name: str,
        permissions: Optional[list[str]] = None,
        display_name: Optional[str] = None,
        description: Optional[str] = None,
    ) -> CustomRole:
        """
        更新自定义角色信息。

        Args:
            name: 角色名称。
            permissions: 新权限列表（None 表示不更新）。
            display_name: 新显示名称（None 表示不更新）。
            description: 新描述（None 表示不更新）。

        Returns:
            更新后的 CustomRole 实例。

        Raises:
            ValueError: 角色不存在或权限格式非法。
        """
        role = self.db.query(CustomRole).filter(CustomRole.name == name).first()
        if not role:
            raise ValueError(f"角色 '{name}' 不存在")

        if role.is_system:
            raise ValueError(f"系统角色 '{name}' 不可修改")

        if permissions is not None:
            normalized = normalize_permissions(permissions)
            role.permissions = json.dumps(normalized)

        if display_name is not None:
            role.display_name = display_name

        if description is not None:
            role.description = description

        self.db.commit()
        self.db.refresh(role)
        logger.bind(event="custom_role_updated", role_name=name).info(f"自定义角色已更新: {name}")
        return role

    def delete_role(self, name: str) -> bool:
        """
        删除自定义角色。

        Args:
            name: 角色名称。

        Returns:
            True 表示删除成功。

        Raises:
            ValueError: 角色不存在或为系统角色。
        """
        role = self.db.query(CustomRole).filter(CustomRole.name == name).first()
        if not role:
            raise ValueError(f"角色 '{name}' 不存在")

        if role.is_system:
            raise ValueError(f"系统角色 '{name}' 不可删除")

        # 检查是否有用户正在使用此角色
        users_with_role = (
            self.db.query(UserRole)
            .filter(UserRole.role_name == name)
            .count()
        )
        if users_with_role > 0:
            raise ValueError(f"角色 '{name}' 仍有 {users_with_role} 个用户关联，无法删除")

        self.db.delete(role)
        self.db.commit()
        logger.bind(event="custom_role_deleted", role_name=name).info(f"自定义角色已删除: {name}")
        return True

    def list_roles(self) -> list[dict]:
        """
        列出所有自定义角色。

        Returns:
            角色信息字典列表。
        """
        roles = self.db.query(CustomRole).order_by(CustomRole.created_at.asc()).all()
        result = []
        for role in roles:
            try:
                permissions = json.loads(role.permissions)
            except (json.JSONDecodeError, TypeError):
                permissions = []
            result.append({
                "id": role.id,
                "name": role.name,
                "display_name": role.display_name,
                "description": role.description,
                "permissions": permissions,
                "created_by": role.created_by,
                "is_system": role.is_system,
                "created_at": role.created_at.isoformat() if role.created_at else None,
                "updated_at": role.updated_at.isoformat() if role.updated_at else None,
            })
        return result

    def get_role(self, name: str) -> Optional[dict]:
        """
        获取指定自定义角色详情。

        Args:
            name: 角色名称。

        Returns:
            角色信息字典，不存在返回 None。
        """
        role = self.db.query(CustomRole).filter(CustomRole.name == name).first()
        if not role:
            return None
        try:
            permissions = json.loads(role.permissions)
        except (json.JSONDecodeError, TypeError):
            permissions = []
        return {
            "id": role.id,
            "name": role.name,
            "display_name": role.display_name,
            "description": role.description,
            "permissions": permissions,
            "created_by": role.created_by,
            "is_system": role.is_system,
            "created_at": role.created_at.isoformat() if role.created_at else None,
            "updated_at": role.updated_at.isoformat() if role.updated_at else None,
        }

    # -------- 权限校验 --------

    async def check_permission(self, user_id: str, permission: str) -> bool:
        """
        检查用户是否拥有指定权限。

        优先检查自定义角色，再回退到内置 RBAC。
        支持层级通配符匹配：
        - "*" 匹配所有权限
        - "skill:*" 匹配 "skill:read"、"skill:execute" 等

        Args:
            user_id: 用户唯一标识。
            permission: 权限标识，如 "plugin:install"。

        Returns:
            True 表示拥有权限。
        """
        permission = permission.strip().lower()
        if not permission:
            return False

        # 获取用户角色名
        user_role = (
            self.db.query(UserRole)
            .filter(UserRole.user_id == user_id)
            .order_by(UserRole.assigned_at.desc())
            .first()
        )
        role_name = user_role.role_name if user_role else "viewer"

        # 内置 admin 角色拥有所有权限
        if role_name == "admin":
            return True

        # 优先检查自定义角色
        custom_role = self.db.query(CustomRole).filter(CustomRole.name == role_name).first()
        if custom_role:
            try:
                permissions = json.loads(custom_role.permissions)
            except (json.JSONDecodeError, TypeError):
                permissions = []
            return self._match_permission(permission, permissions)

        # 回退到内置 RBAC
        builtin_role = self.db.query(Role).filter(Role.name == role_name).first()
        if not builtin_role:
            return False
        try:
            permissions = json.loads(builtin_role.permissions)
        except (json.JSONDecodeError, TypeError):
            return False
        return self._match_permission(permission, permissions)

    @staticmethod
    def _match_permission(requested: str, granted: list[str]) -> bool:
        """
        匹配权限，支持层级通配符。

        Args:
            requested: 请求的权限标识。
            granted: 已授予的权限列表。

        Returns:
            True 表示匹配成功。
        """
        if "*" in granted:
            return True

        if requested in granted:
            return True

        # 层级通配符匹配
        requested_parts = requested.split(":")
        for role_perm in granted:
            role_parts = role_perm.split(":")
            if len(requested_parts) != len(role_parts):
                continue
            matched = True
            for req_part, granted_part in zip(requested_parts, role_parts):
                if granted_part == "*":
                    continue
                if req_part != granted_part:
                    matched = False
                    break
            if matched:
                return True

        return False

    def list_known_permissions(self) -> dict[str, str]:
        """
        列出系统预定义的所有权限目录。

        Returns:
            权限标识到描述的映射字典。
        """
        return dict(KNOWN_PERMISSIONS)


def get_permission_manager(db: Session) -> FineGrainedPermissionManager:
    """
    工厂函数，创建细粒度权限管理器实例。

    Args:
        db: 数据库会话实例。

    Returns:
        FineGrainedPermissionManager 实例。
    """
    return FineGrainedPermissionManager(db)
