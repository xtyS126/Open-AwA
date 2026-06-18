"""
P2 安全增强测试：细粒度权限、IP 白名单/黑名单、用户级速率限制、异常检测、CSRF token。
"""
import asyncio
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.models import (
    AnomalyEvent,
    Base,
    CsrfToken,
    CustomRole,
    IpAccessList,
    Role,
    UserRole,
)
from security.fine_grained_permissions import (
    FineGrainedPermissionManager,
    KNOWN_PERMISSIONS,
    get_permission_manager,
    normalize_permissions,
    validate_permission_format,
)
from security.proactive_defense import (
    AnomalyDetector,
    CsrfTokenManager,
    IpAccessController,
    UserRateLimiter,
    get_anomaly_detector,
    get_user_rate_limiter,
)


# ── 测试夹具 ──────────────────────────────────────────


@pytest.fixture
def db_session(tmp_path):
    """创建临时 SQLite 数据库会话。"""
    db_path = tmp_path / "test_security_enhanced.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def permission_manager(db_session):
    """创建细粒度权限管理器实例。"""
    return FineGrainedPermissionManager(db_session)


@pytest.fixture
def ip_controller(db_session):
    """创建 IP 访问控制器实例。"""
    return IpAccessController(db_session)


@pytest.fixture
def csrf_manager(db_session):
    """创建 CSRF token 管理器实例。"""
    return CsrfTokenManager(db_session)


@pytest.fixture
def rate_limiter():
    """创建用户级速率限制器实例（独立于全局单例）。"""
    return UserRateLimiter(max_requests=5, window_seconds=2)


@pytest.fixture
def anomaly_detector():
    """创建异常检测器实例（独立于全局单例）。"""
    return AnomalyDetector(burst_threshold=5, burst_window=2, failure_threshold=3, failure_window=2)


# ── 权限格式校验测试 ──────────────────────────────────────────


class TestPermissionFormat:
    """权限标识格式校验测试。"""

    def test_valid_permission(self):
        assert validate_permission_format("plugin:install") is True
        assert validate_permission_format("skill:execute") is True
        assert validate_permission_format("model:use") is True
        assert validate_permission_format("billing:view") is True

    def test_wildcard_permission(self):
        assert validate_permission_format("*") is True

    def test_invalid_permission_uppercase(self):
        assert validate_permission_format("Plugin:Install") is False

    def test_invalid_permission_missing_colon(self):
        assert validate_permission_format("plugininstall") is False

    def test_invalid_permission_empty(self):
        assert validate_permission_format("") is False

    def test_invalid_permission_starts_with_digit(self):
        assert validate_permission_format("1plugin:install") is False


class TestNormalizePermissions:
    """权限列表规范化测试。"""

    def test_dedup_permissions(self):
        result = normalize_permissions(["plugin:read", "plugin:read", "skill:execute"])
        assert result == ["plugin:read", "skill:execute"]

    def test_lowercase_normalization(self):
        result = normalize_permissions(["PLUGIN:READ"])
        assert result == ["plugin:read"]

    def test_filter_empty(self):
        result = normalize_permissions(["plugin:read", "", "  ", "skill:execute"])
        assert result == ["plugin:read", "skill:execute"]

    def test_invalid_format_raises(self):
        with pytest.raises(ValueError, match="格式非法"):
            normalize_permissions(["plugin:read", "INVALID"])

    def test_wildcard_allowed(self):
        result = normalize_permissions(["*"])
        assert result == ["*"]


# ── 细粒度权限管理器测试 ──────────────────────────────────────────


class TestFineGrainedPermissionManager:
    """细粒度权限管理器测试。"""

    def test_create_role_success(self, permission_manager, db_session):
        role = permission_manager.create_role(
            name="test_role",
            permissions=["plugin:read", "skill:execute"],
            display_name="测试角色",
            description="测试用途",
            created_by="user1",
        )
        assert role.name == "test_role"
        assert role.display_name == "测试角色"
        assert role.created_by == "user1"
        assert role.is_system is False

    def test_create_role_duplicate_raises(self, permission_manager):
        permission_manager.create_role(name="dup_role", permissions=["plugin:read"])
        with pytest.raises(ValueError, match="已存在"):
            permission_manager.create_role(name="dup_role", permissions=["skill:read"])

    def test_create_role_conflict_with_builtin_raises(self, permission_manager):
        with pytest.raises(ValueError, match="内置角色冲突"):
            permission_manager.create_role(name="admin", permissions=["*"])

    def test_create_role_empty_name_raises(self, permission_manager):
        with pytest.raises(ValueError, match="不能为空"):
            permission_manager.create_role(name="  ", permissions=["plugin:read"])

    def test_update_role_success(self, permission_manager):
        permission_manager.create_role(name="update_role", permissions=["plugin:read"])
        updated = permission_manager.update_role(
            name="update_role",
            permissions=["plugin:read", "skill:execute"],
            display_name="更新后",
        )
        assert updated.display_name == "更新后"

    def test_update_nonexistent_role_raises(self, permission_manager):
        with pytest.raises(ValueError, match="不存在"):
            permission_manager.update_role(name="nonexistent", permissions=["plugin:read"])

    def test_delete_role_success(self, permission_manager):
        permission_manager.create_role(name="del_role", permissions=["plugin:read"])
        assert permission_manager.delete_role("del_role") is True

    def test_delete_nonexistent_role_raises(self, permission_manager):
        with pytest.raises(ValueError, match="不存在"):
            permission_manager.delete_role("nonexistent")

    def test_delete_role_with_users_raises(self, permission_manager, db_session):
        permission_manager.create_role(name="used_role", permissions=["plugin:read"])
        # 添加用户角色关联
        db_session.add(UserRole(user_id="user1", role_name="used_role"))
        db_session.commit()
        with pytest.raises(ValueError, match="仍有"):
            permission_manager.delete_role("used_role")

    def test_list_roles(self, permission_manager):
        permission_manager.create_role(name="role_a", permissions=["plugin:read"])
        permission_manager.create_role(name="role_b", permissions=["skill:execute"])
        roles = permission_manager.list_roles()
        assert len(roles) == 2
        names = {r["name"] for r in roles}
        assert names == {"role_a", "role_b"}

    def test_get_role(self, permission_manager):
        permission_manager.create_role(
            name="get_role",
            permissions=["plugin:read"],
            display_name="获取测试",
        )
        info = permission_manager.get_role("get_role")
        assert info is not None
        assert info["name"] == "get_role"
        assert info["display_name"] == "获取测试"
        assert info["permissions"] == ["plugin:read"]

    def test_get_nonexistent_role_returns_none(self, permission_manager):
        assert permission_manager.get_role("nonexistent") is None

    def test_check_permission_admin_role(self, permission_manager, db_session):
        """admin 角色拥有所有权限。"""
        db_session.add(Role(name="admin", display_name="管理员", permissions='["*"]'))
        db_session.add(UserRole(user_id="admin_user", role_name="admin"))
        db_session.commit()
        allowed = asyncio.get_event_loop().run_until_complete(
            permission_manager.check_permission("admin_user", "plugin:install")
        )
        assert allowed is True

    def test_check_permission_custom_role_allowed(self, permission_manager, db_session):
        """自定义角色权限校验通过。"""
        permission_manager.create_role(name="custom_a", permissions=["plugin:install", "skill:read"])
        db_session.add(UserRole(user_id="user_a", role_name="custom_a"))
        db_session.commit()
        allowed = asyncio.get_event_loop().run_until_complete(
            permission_manager.check_permission("user_a", "plugin:install")
        )
        assert allowed is True

    def test_check_permission_custom_role_denied(self, permission_manager, db_session):
        """自定义角色权限校验拒绝。"""
        permission_manager.create_role(name="custom_b", permissions=["plugin:read"])
        db_session.add(UserRole(user_id="user_b", role_name="custom_b"))
        db_session.commit()
        allowed = asyncio.get_event_loop().run_until_complete(
            permission_manager.check_permission("user_b", "plugin:install")
        )
        assert allowed is False

    def test_check_permission_wildcard_match(self, permission_manager, db_session):
        """层级通配符匹配。"""
        permission_manager.create_role(name="wildcard_role", permissions=["skill:*"])
        db_session.add(UserRole(user_id="user_w", role_name="wildcard_role"))
        db_session.commit()
        allowed = asyncio.get_event_loop().run_until_complete(
            permission_manager.check_permission("user_w", "skill:execute")
        )
        assert allowed is True

    def test_check_permission_empty_permission_returns_false(self, permission_manager, db_session):
        db_session.add(UserRole(user_id="user_e", role_name="viewer"))
        db_session.commit()
        allowed = asyncio.get_event_loop().run_until_complete(
            permission_manager.check_permission("user_e", "")
        )
        assert allowed is False

    def test_list_known_permissions(self, permission_manager):
        perms = permission_manager.list_known_permissions()
        assert "plugin:install" in perms
        assert "skill:execute" in perms
        assert "model:use" in perms
        assert "billing:read" in perms


# ── IP 访问控制器测试 ──────────────────────────────────────────


class TestIpAccessController:
    """IP 白名单/黑名单控制器测试。"""

    def test_add_whitelist_entry(self, ip_controller, db_session):
        entry = ip_controller.add_entry(
            ip_cidr="192.168.1.1",
            list_type="whitelist",
            reason="测试白名单",
        )
        assert entry.ip_cidr == "192.168.1.1"
        assert entry.list_type == "whitelist"
        assert entry.is_active is True

    def test_add_blacklist_entry(self, ip_controller):
        entry = ip_controller.add_entry(
            ip_cidr="10.0.0.1",
            list_type="blacklist",
            reason="恶意 IP",
        )
        assert entry.list_type == "blacklist"

    def test_add_cidr_entry(self, ip_controller):
        entry = ip_controller.add_entry(
            ip_cidr="10.0.0.0/8",
            list_type="blacklist",
        )
        assert entry.ip_cidr == "10.0.0.0/8"

    def test_add_invalid_ip_raises(self, ip_controller):
        with pytest.raises(ValueError, match="格式非法"):
            ip_controller.add_entry(ip_cidr="999.999.999.999", list_type="whitelist")

    def test_add_invalid_list_type_raises(self, ip_controller):
        with pytest.raises(ValueError, match="list_type"):
            ip_controller.add_entry(ip_cidr="192.168.1.1", list_type="invalid")

    def test_add_duplicate_raises(self, ip_controller):
        ip_controller.add_entry(ip_cidr="192.168.1.1", list_type="whitelist")
        with pytest.raises(ValueError, match="已存在"):
            ip_controller.add_entry(ip_cidr="192.168.1.1", list_type="whitelist")

    def test_remove_entry_success(self, ip_controller):
        entry = ip_controller.add_entry(ip_cidr="192.168.1.1", list_type="whitelist")
        assert ip_controller.remove_entry(entry.id) is True

    def test_remove_nonexistent_raises(self, ip_controller):
        with pytest.raises(ValueError, match="不存在"):
            ip_controller.remove_entry(9999)

    def test_list_entries_filter_by_type(self, ip_controller):
        ip_controller.add_entry(ip_cidr="192.168.1.1", list_type="whitelist")
        ip_controller.add_entry(ip_cidr="10.0.0.1", list_type="blacklist")
        whitelist = ip_controller.list_entries(list_type="whitelist")
        blacklist = ip_controller.list_entries(list_type="blacklist")
        assert len(whitelist) == 1
        assert len(blacklist) == 1

    def test_check_ip_whitelist_match(self, ip_controller):
        ip_controller.add_entry(ip_cidr="192.168.1.1", list_type="whitelist")
        result = ip_controller.check_ip("192.168.1.1")
        assert result["allowed"] is True
        assert result["matched_list"] == "whitelist"

    def test_check_ip_blacklist_match(self, ip_controller):
        ip_controller.add_entry(ip_cidr="10.0.0.1", list_type="blacklist")
        result = ip_controller.check_ip("10.0.0.1")
        assert result["allowed"] is False
        assert result["matched_list"] == "blacklist"

    def test_check_ip_cidr_match(self, ip_controller):
        ip_controller.add_entry(ip_cidr="10.0.0.0/8", list_type="blacklist")
        result = ip_controller.check_ip("10.1.2.3")
        assert result["allowed"] is False
        assert result["matched_list"] == "blacklist"

    def test_check_ip_no_match_default_allow(self, ip_controller):
        result = ip_controller.check_ip("8.8.8.8")
        assert result["allowed"] is True
        assert result["matched_list"] == "none"

    def test_check_ip_whitelist_priority_over_blacklist(self, ip_controller):
        """白名单优先级高于黑名单。"""
        ip_controller.add_entry(ip_cidr="192.168.1.1", list_type="whitelist")
        ip_controller.add_entry(ip_cidr="192.168.1.1", list_type="blacklist")
        result = ip_controller.check_ip("192.168.1.1")
        assert result["allowed"] is True
        assert result["matched_list"] == "whitelist"

    def test_check_invalid_ip_returns_false(self, ip_controller):
        result = ip_controller.check_ip("not-an-ip")
        assert result["allowed"] is False

    def test_check_ip_expired_entry_skipped(self, ip_controller, db_session):
        """过期条目应被跳过。"""
        expired = datetime.now(timezone.utc) - timedelta(hours=1)
        entry = IpAccessList(
            ip_cidr="192.168.1.1",
            list_type="blacklist",
            is_active=True,
            expires_at=expired,
        )
        db_session.add(entry)
        db_session.commit()
        result = ip_controller.check_ip("192.168.1.1")
        assert result["allowed"] is True
        assert result["matched_list"] == "none"


# ── 用户级速率限制器测试 ──────────────────────────────────────────


class TestUserRateLimiter:
    """用户级速率限制器测试。"""

    def test_allow_under_limit(self, rate_limiter):
        result = rate_limiter.check("user1")
        assert result["allowed"] is True
        assert result["remaining"] == 4

    def test_block_over_limit(self, rate_limiter):
        for _ in range(5):
            rate_limiter.check("user1")
        result = rate_limiter.check("user1")
        assert result["allowed"] is False
        assert result["remaining"] == 0

    def test_independent_users(self, rate_limiter):
        for _ in range(5):
            rate_limiter.check("user1")
        # user2 仍然可以请求
        result = rate_limiter.check("user2")
        assert result["allowed"] is True

    def test_reset_user(self, rate_limiter):
        for _ in range(5):
            rate_limiter.check("user1")
        assert rate_limiter.check("user1")["allowed"] is False
        rate_limiter.reset("user1")
        assert rate_limiter.check("user1")["allowed"] is True

    def test_empty_user_id_allowed(self, rate_limiter):
        result = rate_limiter.check("")
        assert result["allowed"] is True

    def test_get_stats(self, rate_limiter):
        rate_limiter.check("user1")
        rate_limiter.check("user1")
        stats = rate_limiter.get_stats("user1")
        assert stats["current_count"] == 2
        assert stats["max_requests"] == 5

    def test_window_sliding(self, rate_limiter):
        """窗口滑动后计数重置。"""
        for _ in range(5):
            rate_limiter.check("user1")
        assert rate_limiter.check("user1")["allowed"] is False
        # 等待窗口过期（window_seconds=2）
        time.sleep(2.1)
        result = rate_limiter.check("user1")
        assert result["allowed"] is True


# ── 异常检测器测试 ──────────────────────────────────────────


class TestAnomalyDetector:
    """异常行为检测器测试。"""

    def test_no_anomaly_under_threshold(self, anomaly_detector):
        for _ in range(4):
            result = anomaly_detector.record_request("user1")
            assert result is None

    def test_rate_burst_triggered(self, anomaly_detector):
        for _ in range(4):
            anomaly_detector.record_request("user1")
        result = anomaly_detector.record_request("user1")
        assert result is not None
        assert result["event_type"] == "rate_burst"
        assert result["action_taken"] == "warn"

    def test_repeated_failure_triggered(self, anomaly_detector):
        for _ in range(2):
            anomaly_detector.record_request("user1", is_failure=True)
        result = anomaly_detector.record_request("user1", is_failure=True)
        assert result is not None
        assert result["event_type"] == "repeated_failure"

    def test_empty_user_id_returns_none(self, anomaly_detector):
        assert anomaly_detector.record_request("") is None

    def test_persist_event(self, anomaly_detector, db_session):
        event = {
            "event_type": "rate_burst",
            "user_id": "user1",
            "trigger_detail": "5 requests in 2s",
            "observed_value": "5 requests",
            "action_taken": "warn",
        }
        record = anomaly_detector.persist_event(db_session, event, ip_address="192.168.1.1")
        assert record.id is not None
        assert record.event_type == "rate_burst"
        assert record.ip_address == "192.168.1.1"
        assert record.is_resolved is False

    def test_list_events(self, anomaly_detector, db_session):
        anomaly_detector.persist_event(
            db_session,
            {"event_type": "rate_burst", "user_id": "u1", "action_taken": "warn"},
        )
        anomaly_detector.persist_event(
            db_session,
            {"event_type": "repeated_failure", "user_id": "u2", "action_taken": "warn"},
        )
        events = anomaly_detector.list_events(db_session)
        assert len(events) == 2

    def test_list_events_filter_by_type(self, anomaly_detector, db_session):
        anomaly_detector.persist_event(
            db_session,
            {"event_type": "rate_burst", "user_id": "u1", "action_taken": "warn"},
        )
        anomaly_detector.persist_event(
            db_session,
            {"event_type": "repeated_failure", "user_id": "u2", "action_taken": "warn"},
        )
        events = anomaly_detector.list_events(db_session, event_type="rate_burst")
        assert len(events) == 1
        assert events[0]["event_type"] == "rate_burst"

    def test_resolve_event(self, anomaly_detector, db_session):
        record = anomaly_detector.persist_event(
            db_session,
            {"event_type": "rate_burst", "user_id": "u1", "action_taken": "warn"},
        )
        assert anomaly_detector.resolve_event(db_session, record.id) is True
        db_session.refresh(record)
        assert record.is_resolved is True
        assert record.resolved_at is not None

    def test_resolve_nonexistent_raises(self, anomaly_detector, db_session):
        with pytest.raises(ValueError, match="不存在"):
            anomaly_detector.resolve_event(db_session, 9999)


# ── CSRF Token 管理器测试 ──────────────────────────────────────────


class TestCsrfTokenManager:
    """CSRF token 管理器测试。"""

    def test_generate_token(self, csrf_manager, db_session):
        result = csrf_manager.generate_token(user_id="user1")
        assert "token" in result
        assert "expires_at" in result
        assert len(result["token"]) == 64  # 32 字节 hex 编码

    def test_validate_valid_token(self, csrf_manager):
        gen = csrf_manager.generate_token(user_id="user1")
        result = csrf_manager.validate_token(gen["token"], user_id="user1")
        assert result["valid"] is True

    def test_validate_consumes_token(self, csrf_manager):
        gen = csrf_manager.generate_token(user_id="user1")
        # 第一次校验消费
        result1 = csrf_manager.validate_token(gen["token"], consume=True)
        assert result1["valid"] is True
        # 第二次校验失败（已使用）
        result2 = csrf_manager.validate_token(gen["token"])
        assert result2["valid"] is False
        assert "使用" in result2["reason"]

    def test_validate_without_consume(self, csrf_manager):
        gen = csrf_manager.generate_token(user_id="user1")
        # 不消费，可多次校验
        result1 = csrf_manager.validate_token(gen["token"], consume=False)
        result2 = csrf_manager.validate_token(gen["token"], consume=False)
        assert result1["valid"] is True
        assert result2["valid"] is True

    def test_validate_empty_token(self, csrf_manager):
        result = csrf_manager.validate_token("")
        assert result["valid"] is False
        assert "为空" in result["reason"]

    def test_validate_nonexistent_token(self, csrf_manager):
        result = csrf_manager.validate_token("nonexistent_token")
        assert result["valid"] is False
        assert "不存在" in result["reason"]

    def test_validate_user_mismatch(self, csrf_manager):
        gen = csrf_manager.generate_token(user_id="user1")
        result = csrf_manager.validate_token(gen["token"], user_id="user2")
        assert result["valid"] is False
        assert "不匹配" in result["reason"]

    def test_validate_expired_token(self, csrf_manager, db_session):
        """过期 token 校验失败。"""
        # 直接插入一个已过期的 token
        expired = datetime.now(timezone.utc) - timedelta(hours=1)
        token = CsrfToken(
            token="expired_token_value",
            user_id="user1",
            is_used=False,
            is_revoked=False,
            created_at=datetime.now(timezone.utc) - timedelta(hours=2),
            expires_at=expired,
        )
        db_session.add(token)
        db_session.commit()
        result = csrf_manager.validate_token("expired_token_value")
        assert result["valid"] is False
        assert "过期" in result["reason"]

    def test_revoke_token(self, csrf_manager):
        gen = csrf_manager.generate_token(user_id="user1")
        assert csrf_manager.revoke_token(gen["token"]) is True
        result = csrf_manager.validate_token(gen["token"])
        assert result["valid"] is False
        assert "撤销" in result["reason"]

    def test_revoke_nonexistent_raises(self, csrf_manager):
        with pytest.raises(ValueError, match="不存在"):
            csrf_manager.revoke_token("nonexistent")

    def test_rotate_token(self, csrf_manager):
        gen = csrf_manager.generate_token(user_id="user1")
        new = csrf_manager.rotate_token(gen["token"], user_id="user1")
        assert new["token"] != gen["token"]
        # 旧 token 已撤销
        old_result = csrf_manager.validate_token(gen["token"])
        assert old_result["valid"] is False
        # 新 token 有效
        new_result = csrf_manager.validate_token(new["token"])
        assert new_result["valid"] is True

    def test_rotate_nonexistent_raises(self, csrf_manager):
        with pytest.raises(ValueError, match="不存在"):
            csrf_manager.rotate_token("nonexistent")

    def test_cleanup_expired(self, csrf_manager, db_session):
        """清理过期且已使用的 token。"""
        expired = datetime.now(timezone.utc) - timedelta(hours=1)
        token = CsrfToken(
            token="cleanup_token",
            user_id="user1",
            is_used=True,
            is_revoked=False,
            created_at=datetime.now(timezone.utc) - timedelta(hours=2),
            expires_at=expired,
        )
        db_session.add(token)
        db_session.commit()
        count = csrf_manager.cleanup_expired()
        assert count == 1


# ── 全局单例工厂测试 ──────────────────────────────────────────


class TestSingletons:
    """全局单例工厂测试。"""

    def test_get_user_rate_limiter_singleton(self):
        limiter1 = get_user_rate_limiter()
        limiter2 = get_user_rate_limiter()
        assert limiter1 is limiter2

    def test_get_anomaly_detector_singleton(self):
        d1 = get_anomaly_detector()
        d2 = get_anomaly_detector()
        assert d1 is d2

    def test_get_permission_manager_factory(self, db_session):
        m1 = get_permission_manager(db_session)
        m2 = get_permission_manager(db_session)
        # 工厂函数每次创建新实例（绑定到 db_session）
        assert m1 is not m2
        assert m1.db is m2.db


# ── 路由加载测试 ──────────────────────────────────────────


class TestRouterLoading:
    """路由模块加载测试。"""

    def test_security_enhanced_router_importable(self):
        from api.routes.security_enhanced import router
        assert router is not None
        assert router.prefix == "/api/security/enhanced"

    def test_security_enhanced_router_has_routes(self):
        from api.routes.security_enhanced import router
        # 应包含多个路由
        assert len(router.routes) >= 15

    def test_security_enhanced_router_registered_in_main(self):
        """验证路由已在 main.py 中注册。"""
        import main
        # 检查 main 模块导入了 security_enhanced_router
        assert hasattr(main, "security_enhanced_router")


# ── 数据模型注册测试 ──────────────────────────────────────────


class TestModelRegistration:
    """数据模型注册测试。"""

    def test_custom_role_model_registered(self):
        from db.models import CustomRole
        assert CustomRole.__tablename__ == "custom_roles"

    def test_ip_access_list_model_registered(self):
        from db.models import IpAccessList
        assert IpAccessList.__tablename__ == "ip_access_list"

    def test_anomaly_event_model_registered(self):
        from db.models import AnomalyEvent
        assert AnomalyEvent.__tablename__ == "anomaly_events"

    def test_csrf_token_model_registered(self):
        from db.models import CsrfToken
        assert CsrfToken.__tablename__ == "csrf_tokens"

    def test_models_create_tables(self, db_session):
        """模型能正确创建表。"""
        # 通过 fixture 已创建所有表，验证可查询
        db_session.query(CustomRole).all()
        db_session.query(IpAccessList).all()
        db_session.query(AnomalyEvent).all()
        db_session.query(CsrfToken).all()
