"""
灵魂状态管理器单元测试。
"""

import pytest
import tempfile
from pathlib import Path
from core.soul_state import SoulStateManager


class TestSoulStateManager:
    """灵魂状态管理器测试套件。"""
    
    def test_initial_state(self):
        """测试初始状态。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = SoulStateManager(workspace_id="test", state_dir=Path(tmpdir))
            state = manager.load_state()
            
            assert state.bootstrap_seeded_at is None
            assert state.bootstrap_completed_at is None
            assert state.injection_enabled is True
            assert state.last_injection_at is None
            assert state.injection_count == 0
    
    def test_mark_bootstrap_seeded(self):
        """测试标记引导已播种。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = SoulStateManager(workspace_id="test", state_dir=Path(tmpdir))
            
            manager.mark_bootstrap_seeded()
            state = manager.load_state()
            
            assert state.bootstrap_seeded_at is not None
    
    def test_mark_injection_completed(self):
        """测试标记注入完成。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = SoulStateManager(workspace_id="test", state_dir=Path(tmpdir))
            
            manager.mark_injection_completed()
            state = manager.load_state()
            
            assert state.bootstrap_seeded_at is not None
            assert state.bootstrap_completed_at is not None
            assert state.last_injection_at is not None
            assert state.injection_count == 1
    
    def test_injection_count_increments(self):
        """测试注入计数递增。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = SoulStateManager(workspace_id="test", state_dir=Path(tmpdir))
            
            manager.mark_injection_completed()
            manager.mark_injection_completed()
            manager.mark_injection_completed()
            
            state = manager.load_state()
            assert state.injection_count == 3
    
    def test_toggle_injection_enabled(self):
        """测试切换注入启用状态。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = SoulStateManager(workspace_id="test", state_dir=Path(tmpdir))
            
            # 初始为启用
            assert manager.is_injection_enabled() is True
            
            # 禁用
            manager.set_injection_enabled(False)
            assert manager.is_injection_enabled() is False
            
            # 重新启用
            manager.set_injection_enabled(True)
            assert manager.is_injection_enabled() is True
    
    def test_state_persistence(self):
        """测试状态持久化。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            
            # 创建并修改状态
            manager1 = SoulStateManager(workspace_id="test", state_dir=tmpdir_path)
            manager1.set_injection_enabled(False)
            manager1.mark_injection_completed()
            
            # 创建新实例，验证状态已持久化
            manager2 = SoulStateManager(workspace_id="test", state_dir=tmpdir_path)
            state = manager2.load_state()
            
            assert state.injection_enabled is False
            assert state.injection_count == 1
            assert state.bootstrap_seeded_at is not None
            assert state.bootstrap_completed_at is not None
    
    def test_different_workspaces_isolated(self):
        """测试不同工作区状态隔离。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            
            manager1 = SoulStateManager(workspace_id="ws1", state_dir=tmpdir_path)
            manager2 = SoulStateManager(workspace_id="ws2", state_dir=tmpdir_path)
            
            manager1.set_injection_enabled(False)
            manager2.set_injection_enabled(True)
            
            assert manager1.is_injection_enabled() is False
            assert manager2.is_injection_enabled() is True
    
    def test_reset_state(self):
        """测试重置状态。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = SoulStateManager(workspace_id="test", state_dir=Path(tmpdir))
            
            # 设置一些状态
            manager.mark_injection_completed()
            manager.set_injection_enabled(False)
            
            # 重置
            manager.reset_state()
            
            state = manager.load_state()
            assert state.bootstrap_seeded_at is None
            assert state.bootstrap_completed_at is None
            assert state.injection_enabled is True
            assert state.last_injection_at is None
            assert state.injection_count == 0
    
    def test_get_state_summary(self):
        """测试获取状态摘要。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = SoulStateManager(workspace_id="test", state_dir=Path(tmpdir))
            manager.mark_injection_completed()
            
            summary = manager.get_state_summary()
            
            assert summary["workspace_id"] == "test"
            assert summary["injection_enabled"] is True
            assert summary["bootstrap_seeded_at"] is not None
            assert summary["bootstrap_completed_at"] is not None
            assert summary["last_injection_at"] is not None
            assert summary["injection_count"] == 1
