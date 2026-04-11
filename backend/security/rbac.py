"""
基于角色的访问控制（RBAC）模块，负责角色定义、用户角色分配与权限校验。
所有权限检查逻辑集中在此模块管理，确保权限控制的一致性。
"""

import json
from typing import Optional
from sqlalchemy.orm import Session
from loguru import logger

from db.models import Role, UserRole


class RBACManager:
    """基于角色的访问控制管理器，提供角色查询、分配与权限校验能力。"""

    # 内置角色定义
    BUILT_IN_ROLES = {
        "admin": {
            "name": "管理员",
            "permissions": ["*"]
        },
        "developer": {
            "name": "开发者",
            "permissions": [
                "chat:send", "chat:history",
                "skill:read", "skill:execute",
                "plugin:read", "plugin:execute",
                "memory:read", "memory:write",
                "billing:read",
                "mcp:read", "mcp:connect"
            ]
        },
        "viewer": {
            "name": "访客",
            "permissions": [
                "chat:send", "chat:history",
                "skill:read",
                "plugin:read",
                "memory:read",
                "billing:read"
            ]
        }
    }

    def __init__(self, db: Session):
        """
        初始化 RBAC 管理器。

        Args:
            db: 数据库会话实例。
        """
        self.db = db
        logger.debug("RBACManager initialized")

    def ensure_built_in_roles(self) -> None:
        """确保内置角色已写入数据库，若不存在则创建。"""
        for role_name, role_info in self.BUILT_IN_ROLES.items():
            existing = self.db.query(Role).filter(Role.name == role_name).first()
            if not existing:
                new_role = Role(
                    name=role_name,
                    display_name=role_info["name"],
                    permissions=json.dumps(role_info["permissions"])
                )
                self.db.add(new_role)
        self.db.commit()
        logger.info("内置角色初始化完成")

    async def get_user_role(self, user_id: str) -> str:
        """
        获取用户当前角色名称，若未分配角色则返回默认角色 viewer。

        Args:
            user_id: 用户唯一标识。

        Returns:
            角色名称字符串。
        """
        user_role = (
            self.db.query(UserRole)
            .filter(UserRole.user_id == user_id)
            .order_by(UserRole.assigned_at.desc())
            .first()
        )
        if user_role:
            return user_role.role_name
        return "viewer"

    async def set_user_role(self, user_id: str, role: str) -> bool:
        """
        为用户设置角色，若角色不存在则返回 False。

        Args:
            user_id: 用户唯一标识。
            role: 目标角色名称。

        Returns:
            设置成功返回 True，角色不存在返回 False。
        """
        # 校验角色是否存在
        role_exists = self.db.query(Role).filter(Role.name == role).first()
        if not role_exists:
            logger.warning(f"尝试设置不存在的角色: {role}")
            return False

        # 查找已有的用户角色记录
        existing = (
            self.db.query(UserRole)
            .filter(UserRole.user_id == user_id)
            .first()
        )
        if existing:
            existing.role_name = role
        else:
            new_user_role = UserRole(user_id=user_id, role_name=role)
            self.db.add(new_user_role)

        self.db.commit()
        logger.info(f"用户 {user_id} 角色已设置为 {role}")
        return True

    async def check_permission(self, user_id: str, permission: str) -> bool:
        """
        检查用户是否拥有指定权限。

        Args:
            user_id: 用户唯一标识。
            permission: 权限标识，如 'chat:send'。

        Returns:
            True 表示拥有权限，False 表示没有。
        """
        role_name = await self.get_user_role(user_id)
        permissions = await self.get_role_permissions(role_name)

        # 通配符权限表示拥有所有权限
        if "*" in permissions:
            return True

        return permission in permissions

    async def get_role_permissions(self, role: str) -> list[str]:
        """
        获取指定角色的权限列表。

        Args:
            role: 角色名称。

        Returns:
            权限标识列表。
        """
        role_record = self.db.query(Role).filter(Role.name == role).first()
        if not role_record:
            logger.warning(f"角色不存在: {role}")
            return []

        try:
            return json.loads(role_record.permissions)
        except (json.JSONDecodeError, TypeError):
            logger.error(f"角色 {role} 的权限数据格式错误")
            return []

    async def list_roles(self) -> list[dict]:
        """
        获取所有角色列表。

        Returns:
            角色信息字典列表，每项包含 name、display_name、permissions。
        """
        roles = self.db.query(Role).all()
        result = []
        for role in roles:
            try:
                permissions = json.loads(role.permissions)
            except (json.JSONDecodeError, TypeError):
                permissions = []
            result.append({
                "name": role.name,
                "display_name": role.display_name,
                "permissions": permissions
            })
        return result
