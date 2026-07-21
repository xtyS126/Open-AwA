"""
验证 SubagentOrchestrator 及相关数据结构的核心逻辑。
覆盖隔离级别、生命周期状态机、资源限制、结果合并、安全性检查等场景。
参考: https://yangcazz.github.io/2026/05/22/subagent-architecture-isolation/
"""

import asyncio
import pytest

from core.subagent import (
    IsolationLevel,
    SubagentLifecycleState,
    VALID_LIFECYCLE_TRANSITIONS,
    validate_lifecycle_transition,
    ResourceLimits,
    DEFAULT_RESOURCE_LIMITS,
    SubagentTask,
    SubagentResult,
    ResultMergeStrategy,
    merge_results,
    merge_results_concatenate,
    merge_results_voting,
    SubagentOrchestrator,
    validate_task_security,
)


# ==================== 隔离级别测试 ====================


class TestIsolationLevel:
    """验证隔离级别枚举。"""

    def test_isolation_levels_have_correct_values(self):
        """三级隔离深度应分别对应 1/2/3。"""
        assert IsolationLevel.CONTEXT.value == 1
        assert IsolationLevel.PROCESS.value == 2
        assert IsolationLevel.SANDBOX.value == 3

    def test_isolation_level_is_comparable(self):
        """隔离级别应支持数值比较，越高越安全。"""
        assert IsolationLevel.SANDBOX > IsolationLevel.PROCESS
        assert IsolationLevel.PROCESS > IsolationLevel.CONTEXT


# ==================== 生命周期状态机测试 ====================


class TestLifecycleStateMachine:
    """验证子代理生命周期状态机。"""

    def test_created_can_transition_to_running(self):
        """Created 状态可转为 Running。"""
        assert validate_lifecycle_transition("created", "running") is True

    def test_created_can_transition_to_cancelled(self):
        """Created 状态可直接取消。"""
        assert validate_lifecycle_transition("created", "cancelled") is True

    def test_running_can_transition_to_waiting(self):
        """Running 状态可转为 Waiting（等待工具结果）。"""
        assert validate_lifecycle_transition("running", "waiting") is True

    def test_running_can_transition_to_terminal_states(self):
        """Running 状态可转为 Completed/Timeout/Error/Cancelled。"""
        for target in ("completed", "timeout", "error", "cancelled"):
            assert validate_lifecycle_transition("running", target) is True

    def test_waiting_can_transition_back_to_running(self):
        """Waiting 状态可回到 Running（收到工具结果后继续）。"""
        assert validate_lifecycle_transition("waiting", "running") is True

    def test_terminal_states_can_transition_to_terminated(self):
        """所有终态可转为 Terminated（资源释放）。"""
        for state in ("completed", "timeout", "error", "cancelled"):
            assert validate_lifecycle_transition(state, "terminated") is True

    def test_terminated_is_absorbing_state(self):
        """Terminated 是吸收态，不可再转换。"""
        for target in ("created", "running", "completed"):
            assert validate_lifecycle_transition("terminated", target) is False

    def test_invalid_transition_returns_false(self):
        """非法状态转换应返回 False。"""
        # Completed 不可回到 Running
        assert validate_lifecycle_transition("completed", "running") is False
        # Created 不可直接到 Completed
        assert validate_lifecycle_transition("created", "completed") is False


# ==================== 资源限制测试 ====================


class TestResourceLimits:
    """验证资源限制配置。"""

    def test_default_resource_limits_has_all_fields(self):
        """默认资源限制应包含所有必要字段。"""
        assert DEFAULT_RESOURCE_LIMITS.max_turns > 0
        assert DEFAULT_RESOURCE_LIMITS.max_tokens > 0
        assert DEFAULT_RESOURCE_LIMITS.max_time_seconds > 0
        assert DEFAULT_RESOURCE_LIMITS.max_tool_calls > 0
        assert DEFAULT_RESOURCE_LIMITS.max_output_tokens > 0
        assert DEFAULT_RESOURCE_LIMITS.soft_timeout_seconds > 0

    def test_soft_timeout_less_than_hard_timeout(self):
        """软超时应小于硬超时，给一轮收尾时间。"""
        limits = ResourceLimits()
        assert limits.soft_timeout_seconds < limits.max_time_seconds


# ==================== SubagentTask/SubagentResult 测试 ====================


class TestSubagentTask:
    """验证 SubagentTask 数据结构。"""

    def test_task_requires_task_id(self):
        """task_id 为空时应抛出 ValueError。"""
        with pytest.raises(ValueError, match="task_id"):
            SubagentTask(task_id="", instruction="测试")

    def test_task_requires_instruction(self):
        """instruction 为空时应抛出 ValueError。"""
        with pytest.raises(ValueError, match="instruction"):
            SubagentTask(task_id="t1", instruction="")

    def test_task_default_isolation_level_is_context(self):
        """默认隔离级别应为 Level 1 上下文隔离。"""
        task = SubagentTask(task_id="t1", instruction="测试")
        assert task.isolation_level == IsolationLevel.CONTEXT

    def test_task_default_allowed_tools_is_empty(self):
        """默认工具白名单应为空列表。"""
        task = SubagentTask(task_id="t1", instruction="测试")
        assert task.allowed_tools == []


class TestSubagentResult:
    """验证 SubagentResult 数据结构。"""

    def test_result_to_dict_contains_all_fields(self):
        """to_dict 应包含所有字段。"""
        result = SubagentResult(
            task_id="t1",
            success=True,
            output="完成",
            tokens_used=100,
            elapsed_seconds=1.5,
        )
        d = result.to_dict()
        assert d["task_id"] == "t1"
        assert d["success"] is True
        assert d["output"] == "完成"
        assert d["tokens_used"] == 100
        assert d["elapsed_seconds"] == 1.5
        assert d["lifecycle_state"] == "completed"


# ==================== 结果合并策略测试 ====================


class TestResultMergeStrategies:
    """验证结果合并策略。"""

    def test_concatenate_merges_successful_results(self):
        """拼接策略应合并所有成功结果。"""
        results = [
            SubagentResult(task_id="t1", success=True, output="结果A"),
            SubagentResult(task_id="t2", success=True, output="结果B"),
        ]
        merged = merge_results_concatenate(results)
        assert "结果A" in merged
        assert "结果B" in merged
        assert "t1" in merged
        assert "t2" in merged

    def test_concatenate_includes_failed_results(self):
        """拼接策略应包含失败结果的错误信息。"""
        results = [
            SubagentResult(task_id="t1", success=True, output="成功"),
            SubagentResult(task_id="t2", success=False, output="", error="超时"),
        ]
        merged = merge_results_concatenate(results)
        assert "成功" in merged
        assert "FAILED" in merged
        assert "超时" in merged

    def test_voting_returns_majority_output(self):
        """投票策略应返回出现次数最多的输出。"""
        results = [
            SubagentResult(task_id="t1", success=True, output="答案A"),
            SubagentResult(task_id="t2", success=True, output="答案A"),
            SubagentResult(task_id="t3", success=True, output="答案B"),
        ]
        merged = merge_results_voting(results)
        assert "答案A" in merged
        assert "2/3" in merged

    def test_voting_falls_back_to_concatenate_when_no_success(self):
        """无成功结果时投票策略降级为拼接。"""
        results = [
            SubagentResult(task_id="t1", success=False, output="", error="失败"),
        ]
        merged = merge_results_voting(results)
        assert "FAILED" in merged

    def test_merge_results_dispatches_by_strategy(self):
        """merge_results 应根据策略分派。"""
        results = [
            SubagentResult(task_id="t1", success=True, output="A"),
        ]
        # 默认拼接
        merged = merge_results(results)
        assert "A" in merged

        # 投票
        merged = merge_results(results, ResultMergeStrategy.VOTING)
        assert "A" in merged

    def test_llm_summary_falls_back_to_concatenate(self):
        """LLM 摘要策略在无外部 LLM 时降级为拼接。"""
        results = [
            SubagentResult(task_id="t1", success=True, output="内容"),
        ]
        merged = merge_results(results, ResultMergeStrategy.LLM_SUMMARY)
        assert "内容" in merged
        assert "LLM_SUMMARY" in merged


# ==================== 安全性检查测试 ====================


class TestSecurityValidation:
    """验证安全性检查清单。"""

    def test_valid_task_passes_security_check(self):
        """合规任务应无安全问题。"""
        task = SubagentTask(
            task_id="t1",
            instruction="搜索文档",
            allowed_tools=["search"],
            timeout_seconds=60,
        )
        issues = validate_task_security(task)
        assert issues == []

    def test_too_many_tools_flagged(self):
        """工具白名单过大应被标记。"""
        task = SubagentTask(
            task_id="t1",
            instruction="测试",
            allowed_tools=[f"tool_{i}" for i in range(15)],
        )
        issues = validate_task_security(task)
        assert any("工具白名单过大" in i for i in issues)

    def test_excessive_timeout_flagged(self):
        """超时设置过长应被标记。"""
        task = SubagentTask(
            task_id="t1",
            instruction="测试",
            timeout_seconds=700,
        )
        issues = validate_task_security(task)
        assert any("超时设置过长" in i for i in issues)

    def test_high_risk_instruction_with_low_isolation_flagged(self):
        """高风险指令使用 Level 1 隔离应被标记。"""
        task = SubagentTask(
            task_id="t1",
            instruction="rm -rf /tmp/data",
            isolation_level=IsolationLevel.CONTEXT,
        )
        issues = validate_task_security(task)
        assert any("高风险" in i for i in issues)

    def test_high_risk_instruction_with_high_isolation_passes(self):
        """高风险指令使用 Level 2+ 隔离应通过。"""
        task = SubagentTask(
            task_id="t1",
            instruction="rm -rf /tmp/data",
            isolation_level=IsolationLevel.PROCESS,
        )
        issues = validate_task_security(task)
        assert not any("高风险" in i for i in issues)


# ==================== SubagentOrchestrator 测试 ====================


class TestSubagentOrchestrator:
    """验证 SubagentOrchestrator 编排器。"""

    @pytest.mark.asyncio
    async def test_delegate_all_executes_tasks_in_parallel(self):
        """delegate_all 应并行执行所有任务并返回结果。"""
        orchestrator = SubagentOrchestrator(max_parallel=2)

        async def executor(task: SubagentTask) -> SubagentResult:
            await asyncio.sleep(0.01)
            return SubagentResult(
                task_id=task.task_id,
                success=True,
                output=f"完成: {task.instruction}",
            )

        tasks = [
            SubagentTask(task_id="t1", instruction="任务1"),
            SubagentTask(task_id="t2", instruction="任务2"),
        ]

        results, merged = await orchestrator.delegate_all(tasks, executor)

        assert len(results) == 2
        assert all(r.success for r in results)
        assert "任务1" in merged
        assert "任务2" in merged

    @pytest.mark.asyncio
    async def test_delegate_all_handles_empty_task_list(self):
        """空任务列表应返回空结果。"""
        orchestrator = SubagentOrchestrator(max_parallel=2)

        async def executor(task: SubagentTask) -> SubagentResult:
            return SubagentResult(task_id=task.task_id, success=True, output="")

        results, merged = await orchestrator.delegate_all([], executor)
        assert results == []
        assert merged == ""

    @pytest.mark.asyncio
    async def test_delegate_all_normalizes_executor_exception(self):
        """执行器抛出异常时应转换为失败结果。"""
        orchestrator = SubagentOrchestrator(max_parallel=2)

        async def executor(task: SubagentTask) -> SubagentResult:
            raise RuntimeError("执行器崩溃")

        tasks = [SubagentTask(task_id="t1", instruction="测试")]
        results, _ = await orchestrator.delegate_all(tasks, executor)

        assert len(results) == 1
        assert results[0].success is False
        assert "执行器崩溃" in results[0].error

    @pytest.mark.asyncio
    async def test_hard_timeout_terminates_long_running_task(self):
        """硬超时应强制终止长时间运行的任务。"""
        orchestrator = SubagentOrchestrator(max_parallel=1)

        async def executor(task: SubagentTask) -> SubagentResult:
            await asyncio.sleep(10)
            return SubagentResult(task_id=task.task_id, success=True, output="不应到达")

        task = SubagentTask(
            task_id="t1",
            instruction="慢任务",
            resource_limits=ResourceLimits(max_time_seconds=1),
        )

        result = await orchestrator.delegate_one(task, executor)

        assert result.success is False
        assert result.lifecycle_state == SubagentLifecycleState.TIMEOUT
        assert "硬超时" in result.error

    @pytest.mark.asyncio
    async def test_output_truncation_enforces_max_length(self):
        """结果长度超过限制时应被截断。"""
        orchestrator = SubagentOrchestrator(max_parallel=1)

        long_output = "x" * 500

        async def executor(task: SubagentTask) -> SubagentResult:
            return SubagentResult(
                task_id=task.task_id,
                success=True,
                output=long_output,
            )

        task = SubagentTask(
            task_id="t1",
            instruction="测试",
            resource_limits=ResourceLimits(max_output_tokens=100),
        )

        result = await orchestrator.delegate_one(task, executor)

        assert result.success is True
        assert len(result.output) < len(long_output)
        assert "截断" in result.output
        assert result.metadata.get("truncated") is True

    @pytest.mark.asyncio
    async def test_executor_returning_string_is_wrapped(self):
        """执行器返回字符串时应自动包装为 SubagentResult。"""
        orchestrator = SubagentOrchestrator(max_parallel=1)

        async def executor(task: SubagentTask):
            # 返回原始字符串而非 SubagentResult
            return "原始输出"

        task = SubagentTask(task_id="t1", instruction="测试")
        result = await orchestrator.delegate_one(task, executor)

        assert result.success is True
        assert result.output == "原始输出"

    @pytest.mark.asyncio
    async def test_cancel_terminated_task_returns_false(self):
        """取消已完成的任务应返回 False。"""
        orchestrator = SubagentOrchestrator(max_parallel=1)

        async def executor(task: SubagentTask) -> SubagentResult:
            return SubagentResult(task_id=task.task_id, success=True, output="完成")

        task = SubagentTask(task_id="t1", instruction="测试")
        await orchestrator.delegate_one(task, executor)

        # 任务已完成，取消应失败
        cancelled = await orchestrator.cancel("t1")
        assert cancelled is False

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_task_returns_false(self):
        """取消不存在的任务应返回 False。"""
        orchestrator = SubagentOrchestrator(max_parallel=1)
        cancelled = await orchestrator.cancel("nonexistent")
        assert cancelled is False

    @pytest.mark.asyncio
    async def test_get_active_tasks_returns_current_state(self):
        """get_active_tasks 应返回当前活跃任务的状态。"""
        orchestrator = SubagentOrchestrator(max_parallel=2)

        # 初始无活跃任务
        assert orchestrator.get_active_tasks() == {}

        async def executor(task: SubagentTask) -> SubagentResult:
            return SubagentResult(task_id=task.task_id, success=True, output="完成")

        task = SubagentTask(task_id="t1", instruction="测试")
        await orchestrator.delegate_one(task, executor)

        # 任务完成后应能在活跃列表中观察到终态（TERMINATED 被排除）
        active = orchestrator.get_active_tasks()
        # TERMINATED 状态被排除
        assert "t1" not in active or active["t1"] != "terminated"

    def test_init_rejects_invalid_max_parallel(self):
        """max_parallel < 1 应抛出 ValueError。"""
        with pytest.raises(ValueError, match="max_parallel"):
            SubagentOrchestrator(max_parallel=0)

    @pytest.mark.asyncio
    async def test_level2_isolation_degrades_without_worktree_manager(self):
        """无 WorktreeManager 时 Level 2 隔离应降级为 Level 1。"""
        orchestrator = SubagentOrchestrator(max_parallel=1, worktree_manager=None)

        async def executor(task: SubagentTask) -> SubagentResult:
            return SubagentResult(task_id=task.task_id, success=True, output="完成")

        task = SubagentTask(
            task_id="t1",
            instruction="测试",
            isolation_level=IsolationLevel.PROCESS,
        )

        # 应正常执行（降级为 Level 1）
        result = await orchestrator.delegate_one(task, executor)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_level3_isolation_degrades_to_level2(self):
        """Level 3 沙箱隔离应降级为 Level 2。"""
        orchestrator = SubagentOrchestrator(max_parallel=1, worktree_manager=None)

        async def executor(task: SubagentTask) -> SubagentResult:
            return SubagentResult(task_id=task.task_id, success=True, output="完成")

        task = SubagentTask(
            task_id="t1",
            instruction="测试",
            isolation_level=IsolationLevel.SANDBOX,
        )

        # 应正常执行（降级）
        result = await orchestrator.delegate_one(task, executor)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_merge_strategy_voting_in_delegate_all(self):
        """delegate_all 应支持投票合并策略。"""
        orchestrator = SubagentOrchestrator(max_parallel=3)

        async def executor(task: SubagentTask) -> SubagentResult:
            return SubagentResult(
                task_id=task.task_id,
                success=True,
                output="共识答案",
            )

        tasks = [
            SubagentTask(task_id=f"t{i}", instruction=f"任务{i}")
            for i in range(3)
        ]

        results, merged = await orchestrator.delegate_all(
            tasks, executor, merge_strategy=ResultMergeStrategy.VOTING
        )

        assert len(results) == 3
        assert all(r.success for r in results)
        assert "共识答案" in merged
        assert "VOTING" in merged
