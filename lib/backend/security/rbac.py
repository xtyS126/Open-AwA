"""
基于角色的访问控制（RBAC）模块，负责角色定义、用户角色分配与权限校验。
所有权限检查逻辑集中在此模块管理，确保权限控制的一致性。
"""

import asyncio
import json
from typing import Optional
from sqlalchemy.orm import Session
from loguru import logger

from db.models import Role, UserRole


class PermissionCheckError(RuntimeError):
    """权限数据损坏或不符合约定时抛出的安全异常。"""


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
        created = False
        for role_name, role_info in self.BUILT_IN_ROLES.items():
            existing = self.db.query(Role).filter(Role.name == role_name).first()
            if not existing:
                new_role = Role(
                    name=role_name,
                    display_name=role_info["name"],
                    permissions=json.dumps(role_info["permissions"])
                )
                self.db.add(new_role)
                created = True
        if created:
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
        # 同步 DB 查询包装为 to_thread，避免阻塞事件循环
        return await asyncio.to_thread(self._get_user_role_sync, user_id)

    def _get_user_role_sync(self, user_id: str) -> str:
        """get_user_role 的同步实现。"""
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
        # 同步 DB 写入包装为 to_thread，避免阻塞事件循环
        return await asyncio.to_thread(self._set_user_role_sync, user_id, role)

    def _set_user_role_sync(self, user_id: str, role: str) -> bool:
        """set_user_role 的同步实现。"""
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
        检查用户是否拥有指定权限。支持层级通配符匹配。

        匹配规则：
        - "*" 匹配所有权限
        - "skill:*" 匹配 "skill:read"、"skill:execute"、"skill:create" 等
        - "skill:read" 精确匹配 "skill:read"
        - 不支持 "skill:re*" 等部分通配符（仅支持完整段通配符 "*"）

        Args:
            user_id: 用户唯一标识。
            permission: 权限标识，如 'chat:send'。

        Returns:
            True 表示拥有权限，False 表示没有。
        """
        # 整个权限检查链路（含 DB 查询）包装为 to_thread，避免多次线程切换
        return await asyncio.to_thread(self._check_permission_sync, user_id, permission)

    def _check_permission_sync(self, user_id: str, permission: str) -> bool:
        """check_permission 的同步实现，内部直接调用同步方法避免线程切换开销。"""
        # 一次 join 获取已分配角色及其权限，避免每次校验产生用户角色、角色权限两次查询。
        permission_record = (
            self.db.query(Role.permissions)
            .join(UserRole, UserRole.role_name == Role.name)
            .filter(UserRole.user_id == user_id)
            .order_by(UserRole.assigned_at.desc())
            .first()
        )
        if permission_record is None:
            permission_record = (
                self.db.query(Role.permissions)
                .filter(Role.name == "viewer")
                .first()
            )

        if permission_record is None:
            logger.error("默认 viewer 角色不存在，拒绝权限请求")
            return False

        permissions = self._parse_permissions(permission_record[0], role="assigned")

        # 通配符权限表示拥有所有权限
        if "*" in permissions:
            return True

        # 精确匹配
        if permission in permissions:
            return True

        # 层级通配符匹配：将权限按 ":" 分段，逐段对比
        # 例如 "skill:*" 匹配 "skill:read"、"skill:execute"
        permission_parts = permission.split(":")
        for role_perm in permissions:
            role_parts = role_perm.split(":")
            if self._wildcard_match(permission_parts, role_parts):
                return True

        return False

    @staticmethod
    def _wildcard_match(requested_parts: list[str], granted_parts: list[str]) -> bool:
        """
        逐段对比权限段，支持 granted 侧的 "*" 通配符。

        Args:
            requested_parts: 请求的权限段列表，如 ["skill", "read"]。
            granted_parts: 授予的权限段列表，如 ["skill", "*"]。

        Returns:
            True 表示匹配成功。
        """
        # 段数不同时无法通配匹配（"*" 通配仅在同段数下生效）
        # 例: "skill" (1段) vs "skill:*" (2段) → 不匹配
        #     "skill:read" (2段) vs "skill:*" (2段) → 匹配
        #     "skill:read:advanced" (3段) vs "skill:*" (2段) → 不匹配
        if len(requested_parts) != len(granted_parts):
            return False

        for req_part, granted_part in zip(requested_parts, granted_parts):
            if granted_part == "*":
                continue
            if req_part != granted_part:
                return False

        return True

    async def get_role_permissions(self, role: str) -> list[str]:
        """
        获取指定角色的权限列表。

        Args:
            role: 角色名称。

        Returns:
            权限标识列表。
        """
        # 同步 DB 查询包装为 to_thread，避免阻塞事件循环
        return await asyncio.to_thread(self._get_role_permissions_sync, role)

    def _get_role_permissions_sync(self, role: str) -> list[str]:
        """get_role_permissions 的同步实现。"""
        role_record = self.db.query(Role).filter(Role.name == role).first()
        if not role_record:
            logger.warning(f"角色不存在: {role}")
            return []

        return self._parse_permissions(role_record.permissions, role)

    @staticmethod
    def _parse_permissions(raw_permissions: object, role: str) -> list[str]:
        """解析权限 JSON，数据损坏时抛错以保证权限路径默认拒绝。"""
        try:
            permissions = json.loads(raw_permissions)
        except (json.JSONDecodeError, TypeError) as exc:
            raise PermissionCheckError(f"角色 {role} 的权限数据格式错误") from exc

        if not isinstance(permissions, list) or not all(isinstance(item, str) for item in permissions):
            raise PermissionCheckError(f"角色 {role} 的权限数据必须是字符串列表")
        return permissions

    async def list_roles(self) -> list[dict]:
        """
        获取所有角色列表。

        Returns:
            角色信息字典列表，每项包含 name、display_name、permissions。
        """
        # 同步 DB 查询包装为 to_thread，避免阻塞事件循环
        return await asyncio.to_thread(self._list_roles_sync)

    def _list_roles_sync(self) -> list[dict]:
        """list_roles 的同步实现。"""
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
