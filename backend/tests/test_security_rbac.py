"""
security/rbac.py 单元测试。
覆盖 RBACManager 的角色管理、权限查询和用户角色分配。
"""

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.models import Base, Role, UserRole
from security.rbac import RBACManager


@pytest.fixture
def db_session(tmp_path):
    """创建临时 SQLite 数据库会话，含 Role 和 UserRole 表"""
    db_path = tmp_path / "test_rbac.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def rbac(db_session):
    """创建已初始化的 RBACManager 实例"""
    return RBACManager(db_session)


class TestEnsureBuiltInRoles:
    """测试内置角色初始化"""

    def test_creates_roles_when_empty(self, db_session):
        """空数据库时创建所有内置角色"""
        rbac = RBACManager(db_session)
        rbac.ensure_built_in_roles()

        roles = db_session.query(Role).all()
        role_names = {r.name for r in roles}
        assert role_names == {"admin", "developer", "viewer"}

    def test_idempotent_creation(self, db_session):
        """重复调用不会创建重复角色"""
        rbac = RBACManager(db_session)
        rbac.ensure_built_in_roles()
        count_before = db_session.query(Role).count()
        rbac.ensure_built_in_roles()
        count_after = db_session.query(Role).count()
        assert count_before == count_after

    def test_admin_role_has_wildcard_permission(self, db_session):
        """admin 角色拥有通配符权限"""
        rbac = RBACManager(db_session)
        rbac.ensure_built_in_roles()
        admin_role = db_session.query(Role).filter(Role.name == "admin").first()
        assert admin_role is not None
        perms = json.loads(admin_role.permissions)
        assert "*" in perms

    def test_developer_role_has_limited_permissions(self, db_session):
        """developer 角色拥有受限权限集"""
        rbac = RBACManager(db_session)
        rbac.ensure_built_in_roles()
        dev_role = db_session.query(Role).filter(Role.name == "developer").first()
        perms = json.loads(dev_role.permissions)
        assert "chat:send" in perms
        assert "plugin:execute" in perms
        assert "*" not in perms

    def test_viewer_role_has_read_only_permissions(self, db_session):
        """viewer 角色仅有只读权限"""
        rbac = RBACManager(db_session)
        rbac.ensure_built_in_roles()
        viewer = db_session.query(Role).filter(Role.name == "viewer").first()
        perms = json.loads(viewer.permissions)
        write_perms = [p for p in perms if ":write" in p or ":execute" in p]
        assert len(write_perms) == 0


class TestGetUserRole:
    """测试用户角色查询"""

    @pytest.fixture
    def rbac_with_roles(self, db_session):
        """初始化角色和用户数据"""
        rbac = RBACManager(db_session)
        rbac.ensure_built_in_roles()
        return rbac

    @pytest.mark.asyncio
    async def test_returns_viewer_for_unknown_user(self, rbac_with_roles):
        """未分配角色的用户返回默认 viewer"""
        role = await rbac_with_roles.get_user_role("nonexistent_user")
        assert role == "viewer"

    @pytest.mark.asyncio
    async def test_returns_assigned_role(self, db_session):
        """已分配角色的用户返回对应角色"""
        rbac = RBACManager(db_session)
        rbac.ensure_built_in_roles()
        await rbac.set_user_role("user_123", "developer")

        role = await rbac.get_user_role("user_123")
        assert role == "developer"

    @pytest.mark.asyncio
    async def test_returns_latest_role_after_reassignment(self, db_session):
        """角色变更后返回最新角色"""
        rbac = RBACManager(db_session)
        rbac.ensure_built_in_roles()
        await rbac.set_user_role("user_456", "viewer")
        await rbac.set_user_role("user_456", "admin")

        role = await rbac.get_user_role("user_456")
        assert role == "admin"


class TestSetUserRole:
    """测试用户角色设置"""

    @pytest.fixture
    def rbac_with_roles(self, db_session):
        rbac = RBACManager(db_session)
        rbac.ensure_built_in_roles()
        return rbac

    @pytest.mark.asyncio
    async def test_set_role_success(self, rbac_with_roles):
        """成功为用户设置角色"""
        result = await rbac_with_roles.set_user_role("user_789", "developer")
        assert result is True

        # 验证数据库记录
        db = rbac_with_roles.db
        user_role = db.query(UserRole).filter(UserRole.user_id == "user_789").first()
        assert user_role is not None
        assert user_role.role_name == "developer"

    @pytest.mark.asyncio
    async def test_set_nonexistent_role_fails(self, rbac_with_roles):
        """设置不存在的角色返回 False"""
        result = await rbac_with_roles.set_user_role("user_abc", "superadmin")
        assert result is False

    @pytest.mark.asyncio
    async def test_update_existing_user_role(self, rbac_with_roles):
        """更新已有用户的角色"""
        await rbac_with_roles.set_user_role("user_xyz", "viewer")
        result = await rbac_with_roles.set_user_role("user_xyz", "admin")
        assert result is True

        role = await rbac_with_roles.get_user_role("user_xyz")
        assert role == "admin"


class TestCheckPermission:
    """测试权限检查"""

    @pytest.mark.asyncio
    async def test_admin_has_wildcard_access(self, db_session):
        """admin 角色的通配符权限允许所有操作"""
        rbac = RBACManager(db_session)
        rbac.ensure_built_in_roles()
        await rbac.set_user_role("admin_user", "admin")

        assert await rbac.check_permission("admin_user", "any:operation") is True
        assert await rbac.check_permission("admin_user", "chat:send") is True
        assert await rbac.check_permission("admin_user", "system:config") is True

    @pytest.mark.asyncio
    async def test_developer_can_access_allowed_permissions(self, db_session):
        """developer 可以访问其权限列表内的操作"""
        rbac = RBACManager(db_session)
        rbac.ensure_built_in_roles()
        await rbac.set_user_role("dev_user", "developer")

        assert await rbac.check_permission("dev_user", "chat:send") is True
        assert await rbac.check_permission("dev_user", "plugin:execute") is True

    @pytest.mark.asyncio
    async def test_developer_cannot_access_restricted(self, db_session):
        """developer 不能访问权限列表外的操作"""
        rbac = RBACManager(db_session)
        rbac.ensure_built_in_roles()
        await rbac.set_user_role("dev_user", "developer")

        assert await rbac.check_permission("dev_user", "system:config") is False

    @pytest.mark.asyncio
    async def test_viewer_cannot_write(self, db_session):
        """viewer 不能执行写操作"""
        rbac = RBACManager(db_session)
        rbac.ensure_built_in_roles()
        await rbac.set_user_role("viewer_user", "viewer")

        assert await rbac.check_permission("viewer_user", "memory:write") is False

    @pytest.mark.asyncio
    async def test_unknown_user_has_viewer_permissions(self, db_session):
        """未分配角色的用户具有 viewer 权限"""
        rbac = RBACManager(db_session)
        rbac.ensure_built_in_roles()

        assert await rbac.check_permission("stranger", "chat:send") is True
        assert await rbac.check_permission("stranger", "memory:write") is False


class TestGetRolePermissions:
    """测试角色权限查询"""

    @pytest.mark.asyncio
    async def test_returns_permissions_for_valid_role(self, db_session):
        rbac = RBACManager(db_session)
        rbac.ensure_built_in_roles()
        perms = await rbac.get_role_permissions("developer")
        assert isinstance(perms, list)
        assert "chat:send" in perms

    @pytest.mark.asyncio
    async def test_returns_empty_for_nonexistent_role(self, db_session):
        rbac = RBACManager(db_session)
        rbac.ensure_built_in_roles()
        perms = await rbac.get_role_permissions("ghost_role")
        assert perms == []


class TestListRoles:
    """测试角色列表查询"""

    @pytest.mark.asyncio
    async def test_lists_all_roles(self, db_session):
        rbac = RBACManager(db_session)
        rbac.ensure_built_in_roles()
        roles = await rbac.list_roles()
        assert len(roles) == 3
        names = {r["name"] for r in roles}
        assert names == {"admin", "developer", "viewer"}

    @pytest.mark.asyncio
    async def test_each_role_has_required_fields(self, db_session):
        rbac = RBACManager(db_session)
        rbac.ensure_built_in_roles()
        roles = await rbac.list_roles()
        for role in roles:
            assert "name" in role
            assert "display_name" in role
            assert "permissions" in role
            assert isinstance(role["permissions"], list)

    @pytest.mark.asyncio
    async def test_empty_roles_list(self, db_session):
        """空数据库返回空列表"""
        rbac = RBACManager(db_session)
        roles = await rbac.list_roles()
        assert roles == []
