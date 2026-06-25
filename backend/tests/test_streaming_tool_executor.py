"""
StreamingToolExecutor 单元测试：验证并发调度与串行回退。

覆盖：
- TrackedTool 初始状态与 ToolExecutionState 枚举
- can_execute_tool 真值表判定（空队列/只读并发/破坏性阻塞/队列破坏性阻塞）
- StreamingToolExecutor 的 submit/process_queue/yield_completed/_execute_tool
- 并发执行与串行回退的行为验证
- 异常处理
"""

import asyncio
import time

import pytest

from core.streaming_tool_executor import (
    StreamingToolExecutor,
    TrackedTool,
    ToolExecutionState,
    can_execute_tool,
)
from core.tool_registry import (
    ToolDefinition,
    tool_registry as global_tool_registry,
)


class TestTrackedTool:
    """TrackedTool dataclass 测试"""

    def test_tracked_tool_initial_state(self):
        """验证 TrackedTool 初始状态为 QUEUED，所有可选字段为 None"""
        tracked = TrackedTool(
            tool_call_id="call_1",
            tool_name="test_tool",
            input_params={"key": "value"},
        )
        assert tracked.tool_call_id == "call_1"
        assert tracked.tool_name == "test_tool"
        assert tracked.input_params == {"key": "value"}
        assert tracked.state == ToolExecutionState.QUEUED
        assert tracked.task is None
        assert tracked.abort_controller is None
        assert tracked.start_time is None
        assert tracked.end_time is None
        assert tracked.result is None
        assert tracked.error is None

    def test_tool_execution_state_enum(self):
        """验证状态枚举值与唯一性"""
        assert ToolExecutionState.QUEUED == "queued"
        assert ToolExecutionState.EXECUTING == "executing"
        assert ToolExecutionState.COMPLETED == "completed"
        assert ToolExecutionState.YIELDED == "yielded"
        # 验证枚举成员唯一
        states = {
            ToolExecutionState.QUEUED,
            ToolExecutionState.EXECUTING,
            ToolExecutionState.COMPLETED,
            ToolExecutionState.YIELDED,
        }
        assert len(states) == 4


class TestCanExecuteTool:
    """can_execute_tool 真值表判定测试"""

    # 测试中使用的工具名称，用于自动清理
    _TEST_TOOL_NAMES = [
        "test_read_only_safe",
        "test_destructive",
        "test_unsafe",
    ]

    @pytest.fixture(autouse=True)
    def cleanup_registry(self):
        """每个测试前后清理全局注册中心中的测试工具"""
        yield
        for name in self._TEST_TOOL_NAMES:
            global_tool_registry.unregister(name)

    def test_can_execute_tool_empty_queue(self):
        """验证空队列时任何工具都可执行"""
        tool_def = ToolDefinition(
            name="test_read_only_safe",
            description="read only safe tool",
            is_read_only=True,
            is_concurrency_safe=True,
        )
        tracked = TrackedTool(
            tool_call_id="call_1",
            tool_name="test_read_only_safe",
            input_params={},
        )
        # 空队列，可以执行
        assert can_execute_tool(tracked, [], tool_def) is True

    def test_can_execute_tool_read_only_concurrent(self):
        """验证只读并发安全工具可与队列中的只读工具并发执行"""
        # 注册队列中的工具（只读并发安全）
        queue_tool_def = ToolDefinition(
            name="test_read_only_safe",
            description="read only safe tool",
            is_read_only=True,
            is_concurrency_safe=True,
        )
        global_tool_registry.register(queue_tool_def)

        queue_tracked = TrackedTool(
            tool_call_id="call_executing",
            tool_name="test_read_only_safe",
            input_params={},
        )
        new_tracked = TrackedTool(
            tool_call_id="call_new",
            tool_name="test_read_only_safe",
            input_params={},
        )
        # 队列中有只读工具，新工具也是只读并发安全，可以并发执行
        assert can_execute_tool(new_tracked, [queue_tracked], queue_tool_def) is True

    def test_can_execute_tool_destructive_blocks(self):
        """验证破坏性工具不能并发执行"""
        # 注册队列中的只读工具
        queue_tool_def = ToolDefinition(
            name="test_read_only_safe",
            description="read only safe tool",
            is_read_only=True,
            is_concurrency_safe=True,
        )
        global_tool_registry.register(queue_tool_def)

        queue_tracked = TrackedTool(
            tool_call_id="call_executing",
            tool_name="test_read_only_safe",
            input_params={},
        )
        # 新工具是破坏性的
        destructive_def = ToolDefinition(
            name="test_destructive",
            description="destructive tool",
            is_destructive=True,
        )
        new_tracked = TrackedTool(
            tool_call_id="call_new",
            tool_name="test_destructive",
            input_params={},
        )
        # 破坏性工具不能并发执行
        assert can_execute_tool(new_tracked, [queue_tracked], destructive_def) is False

    def test_can_execute_tool_destructive_in_queue_blocks(self):
        """验证队列中有破坏性工具时阻塞新工具"""
        # 注册破坏性工具到全局注册中心（can_execute_tool 通过全局注册中心查找队列工具定义）
        destructive_def = ToolDefinition(
            name="test_destructive",
            description="destructive tool",
            is_destructive=True,
        )
        global_tool_registry.register(destructive_def)

        queue_tracked = TrackedTool(
            tool_call_id="call_executing",
            tool_name="test_destructive",
            input_params={},
        )
        # 新工具是只读并发安全的
        read_only_def = ToolDefinition(
            name="test_read_only_safe",
            description="read only safe tool",
            is_read_only=True,
            is_concurrency_safe=True,
        )
        new_tracked = TrackedTool(
            tool_call_id="call_new",
            tool_name="test_read_only_safe",
            input_params={},
        )
        # 队列中有破坏性工具，新工具被阻塞
        assert can_execute_tool(new_tracked, [queue_tracked], read_only_def) is False

    def test_can_execute_tool_unsafe_conservative(self):
        """验证非并发安全工具被保守策略阻塞"""
        # 注册队列中的只读工具
        queue_tool_def = ToolDefinition(
            name="test_read_only_safe",
            description="read only safe tool",
            is_read_only=True,
            is_concurrency_safe=True,
        )
        global_tool_registry.register(queue_tool_def)

        queue_tracked = TrackedTool(
            tool_call_id="call_executing",
            tool_name="test_read_only_safe",
            input_params={},
        )
        # 新工具不是并发安全的（保守策略返回 False）
        unsafe_def = ToolDefinition(
            name="test_unsafe",
            description="unsafe tool",
            is_concurrency_safe=False,
        )
        new_tracked = TrackedTool(
            tool_call_id="call_new",
            tool_name="test_unsafe",
            input_params={},
        )
        # 非并发安全工具被保守策略阻塞
        assert can_execute_tool(new_tracked, [queue_tracked], unsafe_def) is False


class TestStreamingToolExecutor:
    """StreamingToolExecutor 调度测试"""

    # 测试中使用的工具名称，用于自动清理
    _TEST_TOOL_NAMES = [
        "test_concurrent_read_a",
        "test_concurrent_read_b",
        "test_serial_destructive_a",
        "test_serial_destructive_b",
        "test_exception_tool",
    ]

    @pytest.fixture(autouse=True)
    def cleanup_registry(self):
        """每个测试前后清理全局注册中心中的测试工具"""
        yield
        for name in self._TEST_TOOL_NAMES:
            global_tool_registry.unregister(name)

    def test_submit_adds_to_queue(self):
        """验证 submit 添加工具到队列并设置初始状态"""
        executor = StreamingToolExecutor(
            tool_registry=global_tool_registry,
            max_concurrent=5,
        )
        executor.submit("call_1", "test_tool", {"param": "value"})
        assert len(executor._queue) == 1
        tracked = executor._queue[0]
        assert tracked.tool_call_id == "call_1"
        assert tracked.tool_name == "test_tool"
        assert tracked.input_params == {"param": "value"}
        assert tracked.state == ToolExecutionState.QUEUED
        assert executor._total_submitted == 1

    @pytest.mark.asyncio
    async def test_process_queue_executes_concurrent_read_only(self):
        """验证只读并发安全工具并发执行（执行时间重叠）"""
        # 注册只读并发安全工具
        tool_a_def = ToolDefinition(
            name="test_concurrent_read_a",
            description="read only tool A",
            is_read_only=True,
            is_concurrency_safe=True,
        )
        tool_b_def = ToolDefinition(
            name="test_concurrent_read_b",
            description="read only tool B",
            is_read_only=True,
            is_concurrency_safe=True,
        )
        global_tool_registry.register(tool_a_def)
        global_tool_registry.register(tool_b_def)

        executor = StreamingToolExecutor(
            tool_registry=global_tool_registry,
            max_concurrent=5,
        )

        # 记录执行时间戳用于验证并发性
        execution_log: list[tuple[str, str, float]] = []

        async def execute_fn(tool_name: str, input_params: dict) -> dict:
            start = time.perf_counter()
            execution_log.append((tool_name, "start", start))
            await asyncio.sleep(0.1)  # 模拟工作
            end = time.perf_counter()
            execution_log.append((tool_name, "end", end))
            return {"ok": True, "tool_name": tool_name}

        executor.submit("call_a", "test_concurrent_read_a", {})
        executor.submit("call_b", "test_concurrent_read_b", {})

        # 启动调度循环（后台任务）
        schedule_task = asyncio.create_task(executor.process_queue(execute_fn))

        # 收集结果
        results: list[TrackedTool] = []
        async for tracked in executor.yield_completed():
            results.append(tracked)

        await schedule_task

        # 验证两个工具都完成
        assert len(results) == 2

        # 提取每个工具的开始和结束时间
        def _get_time(tool_name: str, event: str) -> float:
            for name, evt, t in execution_log:
                if name == tool_name and evt == event:
                    return t
            raise AssertionError(f"未找到 {tool_name} 的 {event} 事件")

        tool_a_start = _get_time("test_concurrent_read_a", "start")
        tool_a_end = _get_time("test_concurrent_read_a", "end")
        tool_b_start = _get_time("test_concurrent_read_b", "start")
        tool_b_end = _get_time("test_concurrent_read_b", "end")

        # 并发执行：B 在 A 结束前开始
        assert tool_b_start < tool_a_end, "工具 B 应在工具 A 完成前开始（并发执行）"
        # 总时间应小于串行时间（0.2s），接近 0.1s
        total_time = max(tool_a_end, tool_b_end) - min(tool_a_start, tool_b_start)
        assert total_time < 0.18, f"并发执行总时间应小于 0.18s，实际: {total_time}"

    @pytest.mark.asyncio
    async def test_process_queue_serial_destructive(self):
        """验证破坏性工具串行执行（执行时间不重叠）"""
        # 注册破坏性工具
        tool_a_def = ToolDefinition(
            name="test_serial_destructive_a",
            description="destructive tool A",
            is_destructive=True,
            is_concurrency_safe=False,
        )
        tool_b_def = ToolDefinition(
            name="test_serial_destructive_b",
            description="destructive tool B",
            is_destructive=True,
            is_concurrency_safe=False,
        )
        global_tool_registry.register(tool_a_def)
        global_tool_registry.register(tool_b_def)

        executor = StreamingToolExecutor(
            tool_registry=global_tool_registry,
            max_concurrent=5,
        )

        execution_log: list[tuple[str, str, float]] = []

        async def execute_fn(tool_name: str, input_params: dict) -> dict:
            start = time.perf_counter()
            execution_log.append((tool_name, "start", start))
            await asyncio.sleep(0.1)  # 模拟工作
            end = time.perf_counter()
            execution_log.append((tool_name, "end", end))
            return {"ok": True, "tool_name": tool_name}

        executor.submit("call_a", "test_serial_destructive_a", {})
        executor.submit("call_b", "test_serial_destructive_b", {})

        schedule_task = asyncio.create_task(executor.process_queue(execute_fn))

        results: list[TrackedTool] = []
        async for tracked in executor.yield_completed():
            results.append(tracked)

        await schedule_task

        assert len(results) == 2

        def _get_time(tool_name: str, event: str) -> float:
            for name, evt, t in execution_log:
                if name == tool_name and evt == event:
                    return t
            raise AssertionError(f"未找到 {tool_name} 的 {event} 事件")

        tool_a_start = _get_time("test_serial_destructive_a", "start")
        tool_a_end = _get_time("test_serial_destructive_a", "end")
        tool_b_start = _get_time("test_serial_destructive_b", "start")
        tool_b_end = _get_time("test_serial_destructive_b", "end")

        # 串行执行：B 在 A 结束后开始
        assert tool_b_start >= tool_a_end, "工具 B 应在工具 A 完成后开始（串行执行）"
        # 总时间应接近串行时间（0.2s）
        total_time = max(tool_a_end, tool_b_end) - min(tool_a_start, tool_b_start)
        assert total_time >= 0.18, f"串行执行总时间应大于等于 0.18s，实际: {total_time}"

    @pytest.mark.asyncio
    async def test_yield_completed_returns_results(self):
        """验证 yield_completed 返回完成的工具结果并标记为 YIELDED"""
        tool_def = ToolDefinition(
            name="test_concurrent_read_a",
            description="read only tool",
            is_read_only=True,
            is_concurrency_safe=True,
        )
        global_tool_registry.register(tool_def)

        executor = StreamingToolExecutor(
            tool_registry=global_tool_registry,
            max_concurrent=5,
        )

        async def execute_fn(tool_name: str, input_params: dict) -> dict:
            return {"ok": True, "result": f"result_{tool_name}_{input_params}"}

        executor.submit("call_1", "test_concurrent_read_a", {"x": 1})
        executor.submit("call_2", "test_concurrent_read_a", {"x": 2})

        schedule_task = asyncio.create_task(executor.process_queue(execute_fn))

        results: list[TrackedTool] = []
        async for tracked in executor.yield_completed():
            results.append(tracked)

        await schedule_task

        # 验证结果数量
        assert len(results) == 2
        # 验证状态为 YIELDED
        for tracked in results:
            assert tracked.state == ToolExecutionState.YIELDED
            assert tracked.result is not None
            assert tracked.error is None
        # 验证结果按 tool_call_id 映射
        results_by_id = {t.tool_call_id: t for t in results}
        assert "call_1" in results_by_id
        assert "call_2" in results_by_id
        # 验证结果内容
        assert results_by_id["call_1"].result == {"ok": True, "result": "result_test_concurrent_read_a_{'x': 1}"}
        assert results_by_id["call_2"].result == {"ok": True, "result": "result_test_concurrent_read_a_{'x': 2}"}

    @pytest.mark.asyncio
    async def test_execute_tool_handles_exception(self):
        """验证异常处理：工具执行抛异常时被捕获并记录到 error 字段"""
        tool_def = ToolDefinition(
            name="test_exception_tool",
            description="tool that raises exception",
            is_read_only=True,
            is_concurrency_safe=True,
        )
        global_tool_registry.register(tool_def)

        executor = StreamingToolExecutor(
            tool_registry=global_tool_registry,
            max_concurrent=5,
        )

        async def execute_fn(tool_name: str, input_params: dict) -> dict:
            raise RuntimeError("工具执行失败")

        executor.submit("call_1", "test_exception_tool", {})

        schedule_task = asyncio.create_task(executor.process_queue(execute_fn))

        results: list[TrackedTool] = []
        async for tracked in executor.yield_completed():
            results.append(tracked)

        await schedule_task

        # 验证异常被捕获
        assert len(results) == 1
        tracked = results[0]
        assert tracked.error is not None
        assert isinstance(tracked.error, RuntimeError)
        assert str(tracked.error) == "工具执行失败"
        assert tracked.result is None
        assert tracked.state == ToolExecutionState.YIELDED
