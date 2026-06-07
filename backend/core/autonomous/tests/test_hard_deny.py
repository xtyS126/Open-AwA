"""
HardDenyChecker 硬底线检查单元测试。
"""

import os
import tempfile
from pathlib import Path

import pytest

from core.autonomous.config import AutonomousConfig, AutonomousScope
from core.autonomous.hard_deny import HardDenyChecker


class TestHardDenyCheckerCommands:
    """命令黑名单测试"""

    @pytest.fixture
    def checker(self, tmp_path: Path):
        config = AutonomousConfig(
            autonomous_mode=True,
            scope={AutonomousScope.CHAT},
            workspace_root=str(tmp_path),
        )
        return HardDenyChecker(config)

    def test_allow_safe_command(self, checker):
        """安全命令通过检查"""
        safe, _ = checker.check_command("ls -la")
        assert safe is True

    def test_deny_rm_rf_root(self, checker):
        """rm -rf / 被拒绝"""
        safe, reason = checker.check_command("rm -rf / --no-preserve-root")
        assert safe is False
        assert "rm -rf" in reason

    def test_deny_sudo(self, checker):
        """sudo 被拒绝"""
        safe, reason = checker.check_command("sudo apt-get install vim")
        assert safe is False

    def test_deny_reboot(self, checker):
        """reboot 被拒绝"""
        safe, _ = checker.check_command("reboot")
        assert safe is False

    def test_deny_shutdown(self, checker):
        """shutdown 被拒绝"""
        safe, _ = checker.check_command("shutdown -h now")
        assert safe is False

    def test_deny_format(self, checker):
        """format 被拒绝"""
        safe, _ = checker.check_command("format C:")
        assert safe is False

    def test_empty_command_passes(self, checker):
        """空命令通过检查"""
        safe, _ = checker.check_command("")
        assert safe is True

    def test_check_all_returns_denial(self, checker):
        """check_all 返回拒绝结构"""
        result = checker.check_all("execute_command", {"command": "rm -rf /"})
        assert result is not None
        assert result["ok"] is False
        assert result["denied_by"] == "hard_deny"
        assert result["recoverable"] is False

    def test_check_all_passes_safe(self, checker):
        """check_all 通过安全操作"""
        result = checker.check_all("execute_command", {"command": "ls -la"})
        assert result is None


class TestHardDenyCheckerPaths:
    """路径保护测试"""

    @pytest.fixture
    def checker(self, tmp_path: Path):
        config = AutonomousConfig(
            autonomous_mode=True,
            scope={AutonomousScope.CHAT},
            workspace_root=str(tmp_path),
        )
        return HardDenyChecker(config)

    def test_deny_etc_shadow(self, checker):
        """拒绝访问敏感系统路径"""
        # /etc/shadow 可能不存在，但路径匹配应拒绝
        safe, reason = checker.check_path("/etc/shadow")
        assert safe is False

    def test_deny_proc(self, checker):
        """拒绝访问 /proc"""
        safe, reason = checker.check_path("/proc/cpuinfo")
        assert safe is False

    def test_allow_workspace_path(self, checker, tmp_path: Path):
        """工作区路径通过检查"""
        safe_file = tmp_path / "src" / "main.py"
        safe_file.parent.mkdir(parents=True, exist_ok=True)
        safe_file.write_text("test")
        safe, _ = checker.check_path(str(safe_file))
        assert safe is True

    def test_check_all_write_protected_file(self, checker, tmp_path: Path):
        """修改 .env 文件被拒绝"""
        # 在 checker 能发现的范围内创建 .env
        env_file = tmp_path / ".env"
        env_file.write_text("SECRET_KEY=test")

        # 重新创建 checker 以确保 glob 能发现新文件
        from core.autonomous.config import AutonomousConfig, AutonomousScope
        from core.autonomous.hard_deny import HardDenyChecker
        config = AutonomousConfig(
            autonomous_mode=True,
            scope={AutonomousScope.CHAT},
            workspace_root=str(tmp_path),
        )
        checker2 = HardDenyChecker(config)

        result = checker2.check_all("write_file", {"path": str(env_file)})
        assert result is not None
        assert result["ok"] is False
        assert result["denied_by"] == "hard_deny"


class TestHardDenyCheckerProtectedConfig:
    """自身配置保护测试"""

    @pytest.fixture
    def checker_with_protected(self, tmp_path: Path):
        """创建含受保护文件的工作区"""
        # 创建受保护文件
        (tmp_path / ".env").write_text("TEST=1")
        (tmp_path / ".env.local").write_text("TEST_LOCAL=1")
        (tmp_path / "CLAUDE.md").write_text("# CLAUDE")

        config = AutonomousConfig(
            autonomous_mode=True,
            scope={AutonomousScope.CHAT},
            workspace_root=str(tmp_path),
        )
        return HardDenyChecker(config)

    def test_deny_write_env(self, checker_with_protected, tmp_path: Path):
        """拒绝修改 .env"""
        result = checker_with_protected.check_all("write_file", {"path": str(tmp_path / ".env")})
        assert result is not None
        assert result["ok"] is False

    def test_allow_read_env(self, checker_with_protected, tmp_path: Path):
        """允许读取 .env"""
        result = checker_with_protected.check_all("read_file", {"path": str(tmp_path / ".env")})
        assert result is None  # 读取操作通过

    def test_deny_delete_claude_md(self, checker_with_protected, tmp_path: Path):
        """拒绝删除 CLAUDE.md"""
        result = checker_with_protected.check_all("delete_file", {"path": str(tmp_path / "CLAUDE.md")})
        assert result is not None
        assert result["ok"] is False
