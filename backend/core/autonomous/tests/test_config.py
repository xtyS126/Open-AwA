"""
AutonomousConfig 配置加载与验证单元测试。
"""

import os
import tempfile
from pathlib import Path

import pytest

from core.autonomous.config import (
    AutonomousConfig,
    AutonomousScope,
    NetworkPolicy,
    AuditLevel,
)


class TestAutonomousConfig:
    """配置加载测试"""

    def test_defaults_disabled(self):
        """默认配置：自主模式关闭"""
        config = AutonomousConfig()
        assert config.autonomous_mode is False
        assert len(config.scope) == 0
        assert config.network_policy == NetworkPolicy.ALLOW_ALL

    def test_disabled_mode_passes_validation(self):
        """关闭状态下配置验证应始终通过"""
        config = AutonomousConfig(autonomous_mode=False)
        # 不会抛出异常
        assert config.is_active is False

    def _make_config(self, **kwargs) -> AutonomousConfig:
        """创建配置并跳过自动验证（用于测试验证逻辑）。"""
        return AutonomousConfig.model_construct(**kwargs)

    def test_enabled_missing_workspace_fails(self):
        """开启自主模式但未配置工作区：验证失败"""
        config = self._make_config(
            autonomous_mode=True,
            scope={AutonomousScope.CHAT},
            workspace_root="",
        )
        with pytest.raises(ValueError, match="WORKSPACE"):
            config.validate_consistency()

    def test_enabled_missing_scope_fails(self):
        """开启自主模式但未指定 scope：验证失败"""
        config = self._make_config(
            autonomous_mode=True,
            workspace_root="/tmp",
        )
        with pytest.raises(ValueError, match="SCOPE"):
            config.validate_consistency()

    def test_enabled_with_valid_config(self, tmp_path: Path):
        """有效配置：通过验证"""
        config = AutonomousConfig(
            autonomous_mode=True,
            scope={AutonomousScope.CHAT, AutonomousScope.SCHEDULED},
            workspace_root=str(tmp_path),
        )
        # 不应抛出异常
        config.validate_consistency()

    def test_cmd_timeout_range_validation(self, tmp_path: Path):
        """CMD_TIMEOUT 范围校验"""
        config = self._make_config(
            autonomous_mode=True,
            scope={AutonomousScope.CHAT},
            workspace_root=str(tmp_path),
            cmd_timeout=0,  # 无效值
        )
        with pytest.raises(ValueError, match="CMD_TIMEOUT"):
            config.validate_consistency()

        config.cmd_timeout = 999  # 超出上限
        with pytest.raises(ValueError, match="CMD_TIMEOUT"):
            config.validate_consistency()

    def test_memory_limit_range_validation(self, tmp_path: Path):
        """MEMORY_LIMIT 范围校验"""
        config = self._make_config(
            autonomous_mode=True,
            scope={AutonomousScope.CHAT},
            workspace_root=str(tmp_path),
            memory_limit=0,  # 无效值
        )
        with pytest.raises(ValueError, match="MEMORY_LIMIT"):
            config.validate_consistency()

        config.memory_limit = 99999  # 超出上限
        with pytest.raises(ValueError, match="MEMORY_LIMIT"):
            config.validate_consistency()

    def test_is_scope_enabled(self, tmp_path: Path):
        """scope 生效检查"""
        config = AutonomousConfig(
            autonomous_mode=True,
            scope={AutonomousScope.CHAT, AutonomousScope.CI},
            workspace_root=str(tmp_path),
        )
        assert config.is_scope_enabled("chat") is True
        assert config.is_scope_enabled("ci") is True
        assert config.is_scope_enabled("scheduled") is False
        assert config.is_scope_enabled("unknown") is False

    def test_get_effective_summary(self, tmp_path: Path):
        """配置摘要不泄露密钥"""
        config = AutonomousConfig(
            autonomous_mode=True,
            scope={AutonomousScope.CHAT},
            workspace_root=str(tmp_path),
            alert_webhook="https://hooks.slack.com/secret",
        )
        summary = config.get_effective_summary()
        assert summary["autonomous_mode"] is True
        assert "secret" not in str(summary)
        assert summary["alert_webhook_configured"] is True

    def test_network_policy_values(self, tmp_path: Path):
        """网络策略枚举值验证"""
        config = AutonomousConfig(
            autonomous_mode=True,
            scope={AutonomousScope.CHAT},
            workspace_root=str(tmp_path),
            network_policy=NetworkPolicy.BLOCK_LOCAL,
        )
        assert config.network_policy == NetworkPolicy.BLOCK_LOCAL

        config.network_policy = NetworkPolicy.ALLOWLIST
        assert config.network_policy == NetworkPolicy.ALLOWLIST

    def test_audit_level_values(self):
        """审计级别枚举值"""
        config = AutonomousConfig(audit_level=AuditLevel.MINIMAL)
        assert config.audit_level == AuditLevel.MINIMAL

        config.audit_level = AuditLevel.FULL
        assert config.audit_level == AuditLevel.FULL


class TestAutonomousConfigFromEnv:
    """从环境变量加载配置测试"""

    def test_from_env_disabled_default(self):
        """环境变量未设置时默认关闭"""
        # 确保环境变量未设置
        for key in list(os.environ.keys()):
            if key.startswith("OPENAWA_AUTONOMOUS_"):
                del os.environ[key]

        config = AutonomousConfig.from_env()
        assert config.autonomous_mode is False

    def test_from_env_enabled(self, tmp_path: Path):
        """环境变量正确加载"""
        os.environ["OPENAWA_AUTONOMOUS_MODE"] = "true"
        os.environ["OPENAWA_AUTONOMOUS_SCOPE"] = "chat,scheduled"
        os.environ["OPENAWA_AUTONOMOUS_WORKSPACE"] = str(tmp_path)
        os.environ["OPENAWA_AUTONOMOUS_NETWORK_POLICY"] = "block_local"
        os.environ["OPENAWA_AUTONOMOUS_CMD_TIMEOUT"] = "180"

        try:
            config = AutonomousConfig.from_env()
            assert config.autonomous_mode is True
            assert AutonomousScope.CHAT in config.scope
            assert AutonomousScope.SCHEDULED in config.scope
            assert config.network_policy == NetworkPolicy.BLOCK_LOCAL
            assert config.cmd_timeout == 180
        finally:
            # 清理
            for key in list(os.environ.keys()):
                if key.startswith("OPENAWA_AUTONOMOUS_"):
                    del os.environ[key]
