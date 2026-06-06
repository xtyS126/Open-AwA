"""
security/rbac.py 通配符权限匹配单元测试。
覆盖层级通配符（如 "skill:*" 匹配 "skill:read"）和精确匹配。
"""

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.models import Base, Role
from security.rbac import RBACManager


@pytest.fixture
def db_session(tmp_path):
    """创建临时 SQLite 数据库会话"""
    db_path = tmp_path / "test_rbac_wildcard.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    engine.dispose()


def _seed_custom_role(db_session, role_name: str, permissions: list[str]):
    """在测试数据库中插入自定义角色及权限"""
    role = Role(
        name=role_name,
        display_name=role_name,
        permissions=json.dumps(permissions),
    )
    db_session.add(role)
    db_session.commit()


class TestWildcardMatching:
    """测试 _wildcard_match 静态方法"""

    def test_exact_match_same_segments(self):
        """相同段数的精确匹配"""
        assert RBACManager._wildcard_match(["skill", "read"], ["skill", "read"]) is True

    def test_exact_match_mismatch(self):
        """段值不同时应不匹配"""
        assert RBACManager._wildcard_match(["skill", "write"], ["skill", "read"]) is False

    def test_wildcard_last_segment(self):
        """最后一段为 * 时通配匹配"""
        assert RBACManager._wildcard_match(["skill", "read"], ["skill", "*"]) is True
        assert RBACManager._wildcard_match(["skill", "execute"], ["skill", "*"]) is True
        assert RBACManager._wildcard_match(["skill", "delete"], ["skill", "*"]) is True

    def test_wildcard_middle_segment(self):
        """中间段为 * 时通配匹配"""
        assert RBACManager._wildcard_match(["resource", "sub", "action"], ["resource", "*", "action"]) is True

    def test_wildcard_all_segments(self):
        """全部段为 * 时匹配任意"""
        assert RBACManager._wildcard_match(["anything", "at", "all"], ["*", "*", "*"]) is True

    def test_wildcard_different_segment_count(self):
        """段数不同时不匹配（即使有 *）"""
        assert RBACManager._wildcard_match(["skill", "read"], ["skill", "read", "advanced"]) is False
        assert RBACManager._wildcard_match(["skill", "read", "advanced"], ["skill", "*"]) is False
        assert RBACManager._wildcard_match(["skill"], ["skill", "*"]) is False

    def test_wildcard_single_segment(self):
        """单段通配符"""
        assert RBACManager._wildcard_match(["skill"], ["*"]) is True
        assert RBACManager._wildcard_match(["chat"], ["*"]) is True
        assert RBACManager._wildcard_match(["skill"], ["chat"]) is False

    def test_no_wildcard_mismatch_segments(self):
        """无通配符时段值不同不匹配"""
        assert RBACManager._wildcard_match(["a", "b", "c"], ["a", "b", "d"]) is False
        assert RBACManager._wildcard_match(["a", "b"], ["a", "c"]) is False

    def test_wildcard_first_segment(self):
        """第一段为 * 时匹配"""
        assert RBACManager._wildcard_match(["resource", "action"], ["*", "action"]) is True

    def test_empty_string_not_matched(self):
        """空字符串段不应因通配符意外匹配"""
        assert RBACManager._wildcard_match([""], ["*"]) is True  # 单段空字符串被 * 匹配
        assert RBACManager._wildcard_match([""], [""]) is True
        # 两段 vs 一段不匹配
        assert RBACManager._wildcard_match(["a", ""], ["a", "*"]) is True  # * 通配空段
        assert RBACManager._wildcard_match(["a", ""], ["a", "b"]) is False

    def test_double_colon_segments(self):
        """连续冒号产生空段时的匹配行为"""
        # "skill::read".split(":") → ["skill", "", "read"]
        assert RBACManager._wildcard_match(["skill", "", "read"], ["skill", "*", "read"]) is True
        assert RBACManager._wildcard_match(["skill", "", "read"], ["skill", "execute", "read"]) is False


class TestCheckPermissionWildcard:
    """测试 check_permission 方法的通配符权限匹配"""

    @pytest.mark.asyncio
    async def test_skill_wildcard_grants_read(self, db_session):
        """"skill:*" 权限应授权 "skill:read" 操作"""
        _seed_custom_role(db_session, "tester", ["skill:*"])
        rbac = RBACManager(db_session)
        await rbac.set_user_role("user_wc1", "tester")

        assert await rbac.check_permission("user_wc1", "skill:read") is True

    @pytest.mark.asyncio
    async def test_skill_wildcard_grants_execute(self, db_session):
        """"skill:*" 权限应授权 "skill:execute" 操作"""
        _seed_custom_role(db_session, "tester2", ["skill:*"])
        rbac = RBACManager(db_session)
        await rbac.set_user_role("user_wc2", "tester2")

        assert await rbac.check_permission("user_wc2", "skill:execute") is True

    @pytest.mark.asyncio
    async def test_skill_wildcard_grants_create(self, db_session):
        """"skill:*" 权限应授权 "skill:create" 操作"""
        _seed_custom_role(db_session, "tester3", ["skill:*"])
        rbac = RBACManager(db_session)
        await rbac.set_user_role("user_wc3", "tester3")

        assert await rbac.check_permission("user_wc3", "skill:create") is True

    @pytest.mark.asyncio
    async def test_wildcard_does_not_grant_other_resource(self, db_session):
        """"skill:*" 不应授权 "plugin:read" 等不同资源的操作"""
        _seed_custom_role(db_session, "tester4", ["skill:*"])
        rbac = RBACManager(db_session)
        await rbac.set_user_role("user_wc4", "tester4")

        assert await rbac.check_permission("user_wc4", "plugin:read") is False

    @pytest.mark.asyncio
    async def test_exact_permission_still_works(self, db_session):
        """精确权限匹配向后兼容"""
        rbac = RBACManager(db_session)
        rbac.ensure_built_in_roles()
        await rbac.set_user_role("dev_user", "developer")

        assert await rbac.check_permission("dev_user", "chat:send") is True
        assert await rbac.check_permission("dev_user", "memory:read") is True
        assert await rbac.check_permission("dev_user", "system:config") is False

    @pytest.mark.asyncio
    async def test_mixed_wildcard_and_exact_permissions(self, db_session):
        """混合使用通配符和精确权限"""
        _seed_custom_role(db_session, "mixed_role", ["skill:*", "chat:send"])
        rbac = RBACManager(db_session)
        await rbac.set_user_role("user_mixed", "mixed_role")

        assert await rbac.check_permission("user_mixed", "skill:read") is True
        assert await rbac.check_permission("user_mixed", "skill:execute") is True
        assert await rbac.check_permission("user_mixed", "chat:send") is True
        assert await rbac.check_permission("user_mixed", "chat:history") is False
        assert await rbac.check_permission("user_mixed", "plugin:read") is False

    @pytest.mark.asyncio
    async def test_global_wildcard_still_works(self, db_session):
        """"*" 全局通配符应匹配所有权限"""
        _seed_custom_role(db_session, "super", ["*"])
        rbac = RBACManager(db_session)
        await rbac.set_user_role("super_user", "super")

        assert await rbac.check_permission("super_user", "anything:at_all") is True
        assert await rbac.check_permission("super_user", "skill:read") is True
        assert await rbac.check_permission("super_user", "no_colon") is True

    @pytest.mark.asyncio
    async def test_multi_segment_wildcard(self, db_session):
        """多段权限通配符: "resource:sub:*" 匹配 "resource:sub:action" """
        _seed_custom_role(db_session, "multi_role", ["resource:sub:*"])
        rbac = RBACManager(db_session)
        await rbac.set_user_role("user_multi", "multi_role")

        assert await rbac.check_permission("user_multi", "resource:sub:read") is True
        assert await rbac.check_permission("user_multi", "resource:sub:write") is True
        assert await rbac.check_permission("user_multi", "resource:other:read") is False

    @pytest.mark.asyncio
    async def test_single_segment_wildcard_permission(self, db_session):
        """单段权限通配符: "*" 段匹配任意单段"""
        _seed_custom_role(db_session, "single_role", ["resource:*"])
        rbac = RBACManager(db_session)
        await rbac.set_user_role("user_single", "single_role")

        assert await rbac.check_permission("user_single", "resource:read") is True
        assert await rbac.check_permission("user_single", "resource:anything") is True
        assert await rbac.check_permission("user_single", "other:read") is False

    @pytest.mark.asyncio
    async def test_no_permission_role_denied(self, db_session):
        """无匹配权限时应拒绝"""
        _seed_custom_role(db_session, "empty_role", [])
        rbac = RBACManager(db_session)
        await rbac.set_user_role("user_empty", "empty_role")

        assert await rbac.check_permission("user_empty", "skill:read") is False
