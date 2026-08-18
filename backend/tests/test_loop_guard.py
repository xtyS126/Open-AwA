"""
循环守卫单元测试。
"""

import pytest
from core.loop_guard import LoopGuard, LoopGuardConfig, LoopStopReason


class TestLoopGuard:
    """循环守卫测试套件。"""
    
    def test_initial_state(self):
        """测试初始状态。"""
        guard = LoopGuard()
        
        assert guard.iteration_count == 0
        assert guard.elapsed_seconds == 0.0
        assert guard.is_stopped is False
        assert guard.stop_reason is None
    
    def test_iteration_limit(self):
        """测试迭代次数限制。"""
        config = LoopGuardConfig(max_iterations=3, timeout_seconds=10.0)
        guard = LoopGuard(config)
        guard.start()
        
        # 前 3 次迭代应该成功
        assert guard.check_iteration() is True
        guard.record_iteration()
        
        assert guard.check_iteration() is True
        guard.record_iteration()
        
        assert guard.check_iteration() is True
        guard.record_iteration()
        
        # 第 4 次应该被拒绝
        assert guard.check_iteration() is False
        assert guard.is_stopped is True
        assert guard.stop_reason == LoopStopReason.MAX_ITERATIONS
    
    def test_timeout_limit(self):
        """测试超时限制。"""
        config = LoopGuardConfig(max_iterations=100, timeout_seconds=0.1)
        guard = LoopGuard(config)
        guard.start()
        
        # 立即检查应该成功
        assert guard.check_iteration() is True
        
        # 等待超时
        import time
        time.sleep(0.15)
        
        # 应该被超时拒绝
        assert guard.check_iteration() is False
        assert guard.is_stopped is True
        assert guard.stop_reason == LoopStopReason.TIMEOUT
    
    def test_tool_result_tracking(self):
        """测试工具调用结果追踪。"""
        config = LoopGuardConfig(max_iterations=10, timeout_seconds=10.0, repeated_failure_threshold=3)
        guard = LoopGuard(config)
        guard.start()
        
        # 记录工具调用
        result1 = guard.record_tool_result("read_file", {"path": "/test.txt"}, success=True)
        assert result1 is None
        
        result2 = guard.record_tool_result("write_file", {"path": "/test.txt"}, success=False, error_message="Permission denied")
        assert result2 is None
        
        result3 = guard.record_tool_result("read_file", {"path": "/test.txt"}, success=True)
        assert result3 is None
    
    def test_repeated_failure_detection(self):
        """测试重复失败检测。"""
        config = LoopGuardConfig(max_iterations=10, timeout_seconds=10.0, repeated_failure_threshold=3)
        guard = LoopGuard(config)
        guard.start()
        
        # 连续 3 次相同工具调用失败
        result1 = guard.record_tool_result("read_file", {"path": "/test.txt"}, success=False, error_message="Not found")
        assert result1 is None
        
        result2 = guard.record_tool_result("read_file", {"path": "/test.txt"}, success=False, error_message="Not found")
        assert result2 is None
        
        result3 = guard.record_tool_result("read_file", {"path": "/test.txt"}, success=False, error_message="Not found")
        assert result3 == LoopStopReason.REPEATED_FAILURE
        assert guard.is_stopped is True
    
    def test_mark_success(self):
        """测试标记成功。"""
        guard = LoopGuard()
        guard.start()
        
        guard.mark_success()
        
        assert guard.is_stopped is True
        assert guard.stop_reason == LoopStopReason.SUCCESS
    
    def test_mark_cancelled(self):
        """测试标记取消。"""
        guard = LoopGuard()
        guard.start()
        
        guard.mark_cancelled()
        
        assert guard.is_stopped is True
        assert guard.stop_reason == LoopStopReason.CANCELLED
    
    def test_get_status(self):
        """测试获取状态。"""
        config = LoopGuardConfig(max_iterations=5, timeout_seconds=10.0)
        guard = LoopGuard(config)
        guard.start()
        
        guard.record_iteration()
        guard.record_iteration()
        
        status = guard.get_status()
        
        assert status["iteration_count"] == 2
        assert status["max_iterations"] == 5
        assert status["stopped"] is False
        assert status["stop_reason"] is None
    
    def test_get_stop_message(self):
        """测试获取停止消息。"""
        config = LoopGuardConfig(max_iterations=2, timeout_seconds=10.0)
        guard = LoopGuard(config)
        guard.start()
        
        guard.record_iteration()
        guard.record_iteration()
        guard.check_iteration()  # 触发停止
        
        message = guard.get_stop_message()
        
        assert message is not None
        assert "最大迭代次数" in message
    
    def test_create_loop_guard_helper(self):
        """测试创建循环守卫的便捷函数。"""
        from core.loop_guard import create_loop_guard
        
        guard = create_loop_guard(max_iterations=10, timeout_seconds=60.0, repeated_failure_threshold=5)
        
        assert guard.config.max_iterations == 10
        assert guard.config.timeout_seconds == 60.0
        assert guard.config.repeated_failure_threshold == 5


class TestSubagentLoopGuardIntegration:
    """子代理执行链接入循环守卫的单元测试（runners._apply_subagent_loop_guard）。"""

    def test_repeated_failure_terminates_subagent(self):
        """连续 3 次相同 (tool_name, args) 失败应触发重复失败终止。"""
        from core.task_runtime.runners import _apply_subagent_loop_guard

        guard = LoopGuard(
            LoopGuardConfig(max_iterations=100, timeout_seconds=100.0, repeated_failure_threshold=3)
        )
        guard.start()
        pending_args: dict = {}

        # 三轮：每轮 running(缓存 args) + error(相同 name 相同参数)
        for i in range(3):
            tool_id = f"call_{i}"
            assert _apply_subagent_loop_guard(
                guard,
                {"id": tool_id, "name": "read_file", "status": "running", "input": {"path": "/x"}},
                pending_args,
            ) is None
            result = _apply_subagent_loop_guard(
                guard,
                {"id": tool_id, "name": "read_file", "status": "error", "output": "Not found"},
                pending_args,
            )
            if i < 2:
                assert result is None
            else:
                assert result == LoopStopReason.REPEATED_FAILURE

        assert guard.is_stopped is True

    def test_success_resets_failure_chain(self):
        """成功调用应重置连续失败计数，不触发终止。"""
        from core.task_runtime.runners import _apply_subagent_loop_guard

        guard = LoopGuard(
            LoopGuardConfig(max_iterations=100, timeout_seconds=100.0, repeated_failure_threshold=3)
        )
        guard.start()
        pending_args: dict = {}

        # 两次失败后一次成功，失败链被重置，不应触发终止
        first = _apply_subagent_loop_guard(
            guard,
            {"id": "c1", "name": "read_file", "status": "running", "input": {"path": "/x"}},
            pending_args,
        )
        assert first is None
        fail = _apply_subagent_loop_guard(
            guard,
            {"id": "c1", "name": "read_file", "status": "error", "output": "Not found"},
            pending_args,
        )
        assert fail is None

        success = _apply_subagent_loop_guard(
            guard,
            {"id": "c2", "name": "read_file", "status": "running", "input": {"path": "/x"}},
            pending_args,
        )
        assert success is None
        ok = _apply_subagent_loop_guard(
            guard,
            {"id": "c2", "name": "read_file", "status": "completed", "output": "ok"},
            pending_args,
        )
        assert ok is None
        assert guard.is_stopped is False
