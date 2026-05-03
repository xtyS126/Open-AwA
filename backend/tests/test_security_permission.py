"""
security/permission.py 单元测试。
覆盖 PermissionChecker 的权限检查、参数验证和角色权限查询。
"""

import pytest
from security.permission import PermissionChecker


class TestCheckPermission:
    """测试 check_permission 方法"""

    @pytest.fixture
    def checker(self):
        return PermissionChecker()

    def test_admin_has_full_access(self, checker):
        """admin 角色拥有完全访问权限"""
        result = checker.check_permission("system:config", user_role="admin")
        assert result["allowed"] is True
        assert result["mode"] == "admin"
        assert "Admin has full access" in result["reason"]

    def test_admin_only_operation_denied_for_user(self, checker):
        """admin_only 操作对普通用户拒绝"""
        for op in ["system:config", "user:manage", "plugin:install", "skill:install"]:
            result = checker.check_permission(op, user_role="user")
            assert result["allowed"] is False, f"操作 {op} 应被拒绝"
            assert result["mode"] == "denied"

    def test_auto_approve_operations_allowed_for_user(self, checker):
        """auto_approve 列表中的操作对用户自动批准"""
        for op in ["file:read", "file:list", "network:ping", "network:dns",
                    "process:list", "system:info"]:
            result = checker.check_permission(op, user_role="user")
            assert result["allowed"] is True, f"操作 {op} 应自动批准"
            assert result["mode"] == "auto"

    def test_user_confirm_operations_require_confirmation(self, checker):
        """user_confirm 列表中的操作需要用户确认"""
        for op in ["file:write", "file:delete", "command:execute",
                    "network:http", "process:kill"]:
            result = checker.check_permission(op, user_role="user")
            assert result["allowed"] is True, f"操作 {op} 应允许但需确认"
            assert result["mode"] == "confirm"

    def test_dangerous_pattern_in_target_blocks_operation(self, checker):
        """目标中包含危险模式时拒绝操作"""
        patterns = ["rm -rf /", "del /s /q C:", "format C:", "shutdown -s", "reboot"]
        for pattern in patterns:
            result = checker.check_permission(
                "command:execute", target=pattern, user_role="user"
            )
            assert result["allowed"] is False, f"危险模式 '{pattern}' 应被拦截"
            assert result["mode"] == "denied"

    def test_dangerous_pattern_case_insensitive(self, checker):
        """危险模式检测不区分大小写"""
        result = checker.check_permission(
            "command:execute", target="RM -rf /tmp", user_role="user"
        )
        assert result["allowed"] is False

    def test_unknown_operation_denied(self, checker):
        """不在白名单中的操作被拒绝"""
        result = checker.check_permission("unknown:operation", user_role="user")
        assert result["allowed"] is False
        assert result["mode"] == "denied"

    def test_operation_without_target_passes_pattern_check(self, checker):
        """不提供 target 时跳过危险模式检测，正常走确认流程"""
        result = checker.check_permission("file:write", user_role="user")
        assert result["allowed"] is True
        assert result["mode"] == "confirm"

    def test_default_user_role_is_user(self, checker):
        """默认角色为 user 时走普通用户权限逻辑"""
        result = checker.check_permission("file:read", user_role="user")
        assert result["allowed"] is True
        assert result["mode"] == "auto"


class TestValidateParameters:
    """测试 validate_parameters 方法"""

    @pytest.fixture
    def checker(self):
        return PermissionChecker()

    def test_file_read_requires_path(self, checker):
        """文件读取操作需要 path 参数"""
        result = checker.validate_parameters("file:read", {})
        assert result["valid"] is False
        assert any("path" in e for e in result["errors"])

    def test_file_read_with_valid_path(self, checker):
        """文件读取操作提供有效 path 时通过"""
        result = checker.validate_parameters("file:read", {"path": "/tmp/test.txt"})
        assert result["valid"] is True

    def test_file_read_path_must_be_string(self, checker):
        """文件读取操作的 path 必须是字符串"""
        result = checker.validate_parameters("file:read", {"path": 123})
        assert result["valid"] is False

    def test_file_write_requires_path(self, checker):
        """文件写入操作同样需要 path 参数"""
        result = checker.validate_parameters("file:write", {})
        assert result["valid"] is False

    def test_file_write_with_valid_path(self, checker):
        result = checker.validate_parameters("file:write", {"path": "/tmp/output.txt"})
        assert result["valid"] is True

    def test_command_execute_requires_command(self, checker):
        """命令执行需要 command 参数"""
        result = checker.validate_parameters("command:execute", {})
        assert result["valid"] is False
        assert any("command" in e for e in result["errors"])

    def test_command_execute_with_valid_command(self, checker):
        result = checker.validate_parameters("command:execute", {"command": "ls -la"})
        assert result["valid"] is True

    def test_command_execute_command_must_be_string(self, checker):
        result = checker.validate_parameters("command:execute", {"command": 456})
        assert result["valid"] is False

    def test_network_http_requires_url(self, checker):
        """网络请求需要 url 参数"""
        result = checker.validate_parameters("network:http", {})
        assert result["valid"] is False

    def test_network_http_url_must_start_with_http(self, checker):
        """URL 必须以 http:// 或 https:// 开头"""
        result = checker.validate_parameters("network:http", {"url": "ftp://evil.com"})
        assert result["valid"] is False

    def test_network_http_with_valid_https_url(self, checker):
        result = checker.validate_parameters("network:http", {"url": "https://api.example.com"})
        assert result["valid"] is True

    def test_network_http_with_valid_http_url(self, checker):
        result = checker.validate_parameters("network:http", {"url": "http://localhost:8080"})
        assert result["valid"] is True

    def test_unknown_operation_returns_valid(self, checker):
        """未知操作默认返回有效（不检查参数）"""
        result = checker.validate_parameters("unknown:op", {"foo": "bar"})
        assert result["valid"] is True
        assert result["errors"] == []


class TestGetUserPermissions:
    """测试 get_user_permissions 方法"""

    @pytest.fixture
    def checker(self):
        return PermissionChecker()

    def test_admin_gets_all_permissions(self, checker):
        """admin 角色获得所有权限"""
        perms = checker.get_user_permissions("admin")
        assert "file:read" in perms
        assert "file:write" in perms
        assert "system:config" in perms
        assert "plugin:install" in perms

    def test_user_gets_limited_permissions(self, checker):
        """普通用户获得受限权限"""
        perms = checker.get_user_permissions("user")
        assert "file:read" in perms
        assert "file:write" in perms
        assert "system:config" not in perms
        assert "plugin:install" not in perms

    def test_user_cannot_access_admin_only(self, checker):
        """普通用户不能获得 admin_only 权限"""
        perms = checker.get_user_permissions("user")
        admin_ops = {"system:config", "user:manage", "plugin:install", "skill:install"}
        assert admin_ops.isdisjoint(set(perms))

    def test_unknown_role_gets_minimal_permissions(self, checker):
        """未知角色获得最小权限（仅 file:read 和 system:info）"""
        perms = checker.get_user_permissions("unknown")
        assert set(perms) == {"file:read", "system:info"}

    def test_returns_deduplicated_permissions(self, checker):
        """返回的权限列表无重复"""
        perms = checker.get_user_permissions("admin")
        assert len(perms) == len(set(perms))
