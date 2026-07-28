"""
WorkspaceBoundary 工作区边界校验单元测试。
"""

import os
import tempfile
from pathlib import Path

import pytest

from core.autonomous.config import AutonomousConfig, AutonomousScope
from core.autonomous.workspace_boundary import WorkspaceBoundary


class TestWorkspaceBoundary:
    """工作区边界测试"""

    @pytest.fixture
    def boundary(self, tmp_path: Path):
        config = AutonomousConfig(
            autonomous_mode=True,
            scope={AutonomousScope.CHAT},
            workspace_root=str(tmp_path),
        )
        return WorkspaceBoundary(config)

    def test_inside_workspace(self, boundary, tmp_path: Path):
        """工作区内路径通过检查"""
        inner = tmp_path / "src" / "main.py"
        inner.parent.mkdir(parents=True, exist_ok=True)
        inner.write_text("test")

        is_inside, _ = boundary.check(str(inner))
        assert is_inside is True

    def test_inside_workspace_relative(self, boundary, tmp_path: Path):
        """相对路径相对于工作区根解析"""
        is_inside, _ = boundary.check("src/main.py")
        assert is_inside is True

    def test_outside_workspace(self, boundary):
        """工作区外路径被拒绝"""
        outside = "/etc/passwd" if os.name != "nt" else "C:\\Windows\\System32\\drivers\\etc\\hosts"
        is_inside, reason = boundary.check(outside)
        assert is_inside is False
        assert "工作区" in reason

    def test_parent_traversal(self, boundary, tmp_path: Path):
        """../ 路径穿越被拒绝"""
        is_inside, reason = boundary.check("../../etc/passwd")
        assert is_inside is False

    def test_check_all_returns_denial(self, boundary):
        """check_all 返回拒绝结构"""
        result = boundary.check_all("/etc/passwd")
        assert result is not None
        assert result["ok"] is False
        assert result["denied_by"] == "workspace"
        assert result["recoverable"] is True
        assert "suggestion" in result

    def test_check_all_passes(self, boundary, tmp_path: Path):
        """check_all 通过工作区内路径"""
        inner = tmp_path / "data.json"
        inner.write_text("{}")
        result = boundary.check_all(str(inner))
        assert result is None

    def test_empty_path_passes(self, boundary):
        """空路径通过检查"""
        is_inside, _ = boundary.check("")
        assert is_inside is True

    def test_missing_workspace_raises(self):
        """未配置工作区时抛出异常"""
        config = AutonomousConfig.model_construct(
            autonomous_mode=True,
            scope={AutonomousScope.CHAT},
            workspace_root="",
        )
        with pytest.raises(ValueError):
            WorkspaceBoundary(config)

    def test_nonexistent_workspace_raises(self):
        """不存在的路径抛出异常"""
        config = AutonomousConfig.model_construct(
            autonomous_mode=True,
            scope={AutonomousScope.CHAT},
            workspace_root="/nonexistent/path/12345",
        )
        with pytest.raises(ValueError, match="不存在"):
            WorkspaceBoundary(config)


class TestSymlinkCheck:
    """符号链接检查测试（需要操作系统支持）"""

    @pytest.fixture
    def boundary(self, tmp_path: Path):
        config = AutonomousConfig(
            autonomous_mode=True,
            scope={AutonomousScope.CHAT},
            workspace_root=str(tmp_path),
        )
        return WorkspaceBoundary(config)

    def test_symlink_inside_workspace(self, boundary, tmp_path: Path):
        """工作区内符号链接通过检查"""
        try:
            target = tmp_path / "target.txt"
            target.write_text("hello")
            link = tmp_path / "link.txt"
            link.symlink_to(target)
        except (OSError, NotImplementedError):
            pytest.skip("符号链接在此环境不可用")

        inside, _ = boundary.check_symlink(str(link))
        assert inside is True

    def test_symlink_outside_workspace(self, boundary, tmp_path: Path):
        """指向工作区外的符号链接被拒绝"""
        outside = tmp_path.parent / "outside.txt"
        outside.write_text("outside")
        link = tmp_path / "bad_link.txt"
        try:
            link.symlink_to(outside)
        except (OSError, NotImplementedError):
            pytest.skip("符号链接在此环境不可用")

        inside, reason = boundary.check_symlink(str(link))
        assert inside is False
