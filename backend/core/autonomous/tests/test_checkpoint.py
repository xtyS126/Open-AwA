"""
CheckpointManager 文件检查点单元测试。
"""

import asyncio
from pathlib import Path

import pytest

from core.autonomous.config import AutonomousConfig, AutonomousScope
from core.autonomous.checkpoint import CheckpointManager


class TestCheckpointManager:
    """检查点管理器测试"""

    @pytest.fixture
    def mgr(self, tmp_path: Path):
        config = AutonomousConfig(
            autonomous_mode=True,
            scope={AutonomousScope.CHAT},
            workspace_root=str(tmp_path),
            checkpoint_enabled=True,
        )
        return CheckpointManager(config)

    @pytest.mark.asyncio
    async def test_create_checkpoint(self, mgr, tmp_path: Path):
        """创建检查点"""
        test_file = tmp_path / "test.txt"
        test_file.write_text("original content")

        cp_id = await mgr.create(str(test_file), "write")
        assert cp_id is not None
        assert cp_id.startswith("ckpt_")

    @pytest.mark.asyncio
    async def test_create_checkpoint_nonexistent_file(self, mgr):
        """不存在的文件返回 None"""
        cp_id = await mgr.create("/nonexistent/file.txt", "write")
        assert cp_id is None

    @pytest.mark.asyncio
    async def test_restore_checkpoint(self, mgr, tmp_path: Path):
        """从检查点恢复文件"""
        test_file = tmp_path / "restore_test.txt"
        test_file.write_text("original content")

        cp_id = await mgr.create(str(test_file), "write")
        assert cp_id is not None

        # 修改文件
        test_file.write_text("modified content")
        assert test_file.read_text() == "modified content"

        # 恢复
        success = await mgr.restore(cp_id)
        assert success is True
        assert test_file.read_text() == "original content"

    @pytest.mark.asyncio
    async def test_restore_nonexistent_checkpoint(self, mgr):
        """恢复不存在的检查点返回 False"""
        success = await mgr.restore("nonexistent_id")
        assert success is False

    @pytest.mark.asyncio
    async def test_list_checkpoints(self, mgr, tmp_path: Path):
        """列出检查点"""
        for i in range(3):
            f = tmp_path / f"file_{i}.txt"
            f.write_text(f"content {i}")
            await mgr.create(str(f), "write")

        cps = await mgr.list_checkpoints()
        assert len(cps) == 3

    @pytest.mark.asyncio
    async def test_disabled_checkpoint_manager(self, tmp_path: Path):
        """检查点关闭时 create 返回 None"""
        config = AutonomousConfig(
            autonomous_mode=True,
            scope={AutonomousScope.CHAT},
            workspace_root=str(tmp_path),
            checkpoint_enabled=False,
        )
        mgr = CheckpointManager(config)
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")

        cp_id = await mgr.create(str(test_file))
        assert cp_id is None

    @pytest.mark.asyncio
    async def test_cleanup_old_checkpoints(self, mgr, tmp_path: Path):
        """清理超出上限的检查点"""
        # 创建多个检查点
        for i in range(10):
            f = tmp_path / f"cleanup_{i}.txt"
            f.write_text(f"content {i}")
            await mgr.create(str(f), "write")

        # 设置 max=3，清理多余的
        removed = await mgr.cleanup(max_checkpoints=3)
        assert removed > 0
        # 剩余不超过 3 个
        remaining = await mgr.list_checkpoints()
        assert len(remaining) <= 3
