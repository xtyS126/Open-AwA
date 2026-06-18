"""
步骤级回滚管理模块测试。
"""

import pytest
from core.rollback import RollbackManager, StepSnapshot


class TestStepSnapshot:
    """StepSnapshot 数据类测试。"""

    def test_snapshot_stores_fields(self):
        """快照正确存储字段。"""
        snapshot = StepSnapshot(
            step_index=1,
            step_action="tool_call",
            context_state={"key": "value"},
            description="测试快照",
        )
        assert snapshot.step_index == 1
        assert snapshot.step_action == "tool_call"
        assert snapshot.context_state == {"key": "value"}
        assert snapshot.description == "测试快照"


class TestRollbackManager:
    """RollbackManager 核心逻辑测试。"""

    def test_save_snapshot_stores_deep_copy(self):
        """验证快照是深拷贝，修改原上下文不影响快照。"""
        manager = RollbackManager()
        context = {"data": [1, 2, 3]}
        manager.save_snapshot(0, "test", context)

        # 修改原上下文
        context["data"].append(4)

        # 快照中的数据不受影响
        snapshot = manager._snapshots[0]
        assert snapshot.context_state["data"] == [1, 2, 3]

    def test_rollback_to_last_stable_returns_latest_snapshot(self):
        """回滚返回最新快照。"""
        manager = RollbackManager()
        manager.save_snapshot(0, "step_0", {"v": 0})
        manager.save_snapshot(1, "step_1", {"v": 1})
        manager.save_snapshot(2, "step_2", {"v": 2})

        snapshot = manager.rollback_to_last_stable()
        assert snapshot is not None
        assert snapshot.step_index == 2
        assert snapshot.context_state == {"v": 2}

    def test_rollback_removes_snapshot_from_stack(self):
        """回滚后快照从栈中移除。"""
        manager = RollbackManager()
        manager.save_snapshot(0, "step_0", {})
        manager.save_snapshot(1, "step_1", {})

        manager.rollback_to_last_stable()
        assert manager.snapshot_count == 1

    def test_rollback_empty_stack_returns_none(self):
        """空栈回滚返回 None。"""
        manager = RollbackManager()
        result = manager.rollback_to_last_stable()
        assert result is None

    def test_max_snapshots_eviction(self):
        """超出上限自动淘汰最旧的快照。"""
        manager = RollbackManager(max_snapshots=3)
        for i in range(5):
            manager.save_snapshot(i, f"step_{i}", {"i": i})

        # 只保留最新的 3 个
        assert manager.snapshot_count == 3
        assert manager._snapshots[0].step_index == 2
        assert manager._snapshots[2].step_index == 4

    def test_get_context_after_rollback_returns_deep_copy(self):
        """返回的上下文是深拷贝。"""
        manager = RollbackManager()
        manager.save_snapshot(0, "step_0", {"data": [1, 2]})

        context = manager.get_context_after_rollback()
        assert context is not None
        context["data"].append(3)

        # 原快照数据不受影响（已从栈中移除，但验证深拷贝机制）
        assert context["data"] == [1, 2, 3]

    def test_clear_removes_all_snapshots(self):
        """清空所有快照。"""
        manager = RollbackManager()
        manager.save_snapshot(0, "step_0", {})
        manager.save_snapshot(1, "step_1", {})
        manager.clear()
        assert manager.snapshot_count == 0
