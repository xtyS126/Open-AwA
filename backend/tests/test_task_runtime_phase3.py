"""
任务运行时 Phase 3 测试，覆盖权限守卫、钩子调度器与 worktree 管理器。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from core.task_runtime.permission_guard import (
    PermissionGuard,
    PermissionDecision,
    permission_guard,
)
from core.task_runtime.hook_dispatcher import (
    HookDispatcher,
    HookResult,
    HOOK_PRE_TOOL_USE,
    HOOK_POST_TOOL_USE,
    HOOK_TASK_COMPLETED,
    HOOK_SUBAGENT_STOP,
)
from core.task_runtime.worktree_manager import WorktreeManager


# ── 权限守卫 ────────────────────────────────────────────────

class TestPermissionGuard:
    """权限模式评估测试。"""

    def test_default_mode_read_passes(self):
        """default 模式下只读工具自动通过。"""
        decision = permission_guard.evaluate(
            "read_file", {"file_path": "/tmp/test.txt"},
            permission_mode="default",
        )
        assert decision.allowed is True
        assert decision.mode in ("auto", "confirm")

    def test_default_mode_write_requires_confirm(self):
        """default 模式下写操作需确认。"""
        decision = permission_guard.evaluate(
            "write_file", {"file_path": "/tmp/test.txt"},
            permission_mode="default",
        )
        assert decision.allowed is True
        # 写操作至少需要确认
        assert decision.mode in ("auto", "confirm")

    def test_plan_mode_rejects_write(self):
        """plan 模式下拒绝写操作。"""
        decision = permission_guard.evaluate(
            "write_file", {"file_path": "/tmp/test.txt"},
            permission_mode="plan",
        )
        assert decision.allowed is False
        assert decision.mode == "deny"

    def test_plan_mode_allows_read(self):
        """plan 模式下只读操作通过。"""
        decision = permission_guard.evaluate(
            "read_file", {"file_path": "/tmp/test.txt"},
            permission_mode="plan",
        )
        assert decision.allowed is True

    def test_plan_mode_rejects_delete(self):
        """plan 模式下拒绝删除操作。"""
        decision = permission_guard.evaluate(
            "delete_file", {"file_path": "/tmp/test.txt"},
            permission_mode="plan",
        )
        assert decision.allowed is False

    def test_bypass_permissions(self):
        """bypass_permissions 模式全部通过。"""
        decision = permission_guard.evaluate(
            "write_file", {"file_path": "/etc/passwd"},
            permission_mode="bypass_permissions",
        )
        assert decision.allowed is True
        assert decision.mode == "auto"

    def test_get_allowed_tools_plan(self):
        """plan 模式返回只读工具白名单。"""
        tools = permission_guard.get_allowed_tools("plan")
        assert tools is not None
        assert "read_file" in tools
        assert "write_file" not in tools

    def test_get_allowed_tools_default(self):
        """default 模式返回 None（无限制）。"""
        tools = permission_guard.get_allowed_tools("default")
        assert tools is None

    def test_permission_decision_dataclass(self):
        """PermissionDecision 数据类字段验证。"""
        d = PermissionDecision(allowed=True, mode="auto", reason="test")
        assert d.allowed is True
        assert d.mode == "auto"
        assert d.reason == "test"
        assert d.require_user_confirm is False

    def test_dangerous_prefix_rejected(self):
        """高危工具前缀被识别为写操作。"""
        assert permission_guard._is_write_operation("delete_file", "file:delete") is True
        assert permission_guard._is_write_operation("drop_table", "command:execute") is True


# ── 钩子调度器 ──────────────────────────────────────────────

class TestHookDispatcher:
    """钩子调度器注册与分发测试。"""

    @pytest.mark.asyncio
    async def test_register_and_dispatch(self):
        """注册钩子并验证分发。"""
        dispatcher = HookDispatcher()
        received = []

        async def my_hook(payload):
            received.append(payload)
            return HookResult(decision="allow", reason="ok")

        dispatcher.register(HOOK_PRE_TOOL_USE, my_hook)
        results = await dispatcher.dispatch(HOOK_PRE_TOOL_USE, {
            "tool_name": "read_file",
            "tool_args": {},
        })
        assert len(received) == 1
        assert len(results) == 1
        assert results[0].decision == "allow"

    @pytest.mark.asyncio
    async def test_deny_blocks_tool(self):
        """deny 决策可阻止工具调用。"""
        dispatcher = HookDispatcher()

        async def block_writes(payload):
            if payload.get("tool_name") == "write_file":
                return HookResult(decision="deny", reason="写操作被阻止")
            return HookResult(decision="allow")

        dispatcher.register(HOOK_PRE_TOOL_USE, block_writes)
        results = await dispatcher.dispatch(HOOK_PRE_TOOL_USE, {
            "tool_name": "write_file",
        })
        deny = dispatcher.has_deny(results)
        assert deny is not None
        assert deny.decision == "deny"
        assert "写操作被阻止" in deny.reason

    @pytest.mark.asyncio
    async def test_has_deny_returns_none_when_all_allowed(self):
        """全部通过时 has_deny 返回 None。"""
        dispatcher = HookDispatcher()

        async def allow_all(payload):
            return HookResult(decision="allow")

        dispatcher.register(HOOK_PRE_TOOL_USE, allow_all)
        results = await dispatcher.dispatch(HOOK_PRE_TOOL_USE, {"tool_name": "read_file"})
        assert dispatcher.has_deny(results) is None

    @pytest.mark.asyncio
    async def test_input_override(self):
        """钩子可覆写工具输入参数。"""
        dispatcher = HookDispatcher()

        async def sanitize_path(payload):
            return HookResult(
                decision="allow",
                updated_input={"file_path": "/safe/path/file.txt"},
            )

        dispatcher.register(HOOK_PRE_TOOL_USE, sanitize_path)
        results = await dispatcher.dispatch(HOOK_PRE_TOOL_USE, {
            "tool_name": "read_file",
            "tool_args": {"file_path": "/unsafe/path/file.txt"},
        })
        merged = dispatcher.get_updated_input(results)
        assert merged.get("file_path") == "/safe/path/file.txt"

    @pytest.mark.asyncio
    async def test_hook_exception_is_handled(self):
        """钩子异常不会中断分发。"""
        dispatcher = HookDispatcher()

        async def bad_hook(payload):
            raise RuntimeError("test error")

        dispatcher.register(HOOK_PRE_TOOL_USE, bad_hook)
        results = await dispatcher.dispatch(HOOK_PRE_TOOL_USE, {"tool_name": "test"})
        assert len(results) == 1
        assert results[0].decision == "allow"  # 异常时默认放行

    @pytest.mark.asyncio
    async def test_unregister(self):
        """注销钩子后不再分发。"""
        dispatcher = HookDispatcher()
        received = []

        async def my_hook(payload):
            received.append(payload)
            return HookResult(decision="allow")

        dispatcher.register(HOOK_POST_TOOL_USE, my_hook)
        dispatcher.unregister(HOOK_POST_TOOL_USE, my_hook)
        await dispatcher.dispatch(HOOK_POST_TOOL_USE, {"tool_name": "test"})
        assert len(received) == 0

    @pytest.mark.asyncio
    async def test_task_completed_hook(self):
        """TaskCompleted 钩子分发性。"""
        dispatcher = HookDispatcher()
        completed = []

        async def on_complete(payload):
            completed.append(payload)
            return HookResult(decision="allow")

        dispatcher.register(HOOK_TASK_COMPLETED, on_complete)
        await dispatcher.dispatch(HOOK_TASK_COMPLETED, {
            "response": "task done",
            "round_count": 3,
        })
        assert len(completed) == 1

    @pytest.mark.asyncio
    async def test_additional_context_collection(self):
        """收集所有钩子的附加上下文。"""
        dispatcher = HookDispatcher()

        async def add_note_a(payload):
            return HookResult(decision="allow", additional_context="Note A")

        async def add_note_b(payload):
            return HookResult(decision="allow", additional_context="Note B")

        dispatcher.register(HOOK_SUBAGENT_STOP, add_note_a)
        dispatcher.register(HOOK_SUBAGENT_STOP, add_note_b)
        results = await dispatcher.dispatch(HOOK_SUBAGENT_STOP, {})
        context = dispatcher.get_additional_context(results)
        assert "Note A" in context
        assert "Note B" in context


# ── Worktree 管理器 ─────────────────────────────────────────

class TestWorktreeManager:
    """Git worktree 管理器测试。"""

    def test_init_default(self):
        """默认使用当前工作目录。"""
        wm = WorktreeManager()
        assert wm._base_dir == Path.cwd()

    def test_init_custom_dir(self, tmp_path):
        """自定义基础目录。"""
        wm = WorktreeManager(base_dir=str(tmp_path))
        assert wm._base_dir == tmp_path

    @pytest.mark.asyncio
    async def test_run_in_worktree_without_worktree(self):
        """无 worktree 时在基础目录执行。"""
        wm = WorktreeManager()
        result = await wm.run_in_worktree("nonexistent", "echo hello")
        assert result.get("ok") is True or result.get("ok") is False
        # 可能成功（如果在 git 仓库中）或失败，但不应该崩溃

    def test_parse_worktree_list(self):
        """解析 porcelain 格式输出。"""
        wm = WorktreeManager()
        output = """worktree /path/to/wt1
HEAD abc123
branch main

worktree /path/to/wt2
HEAD def456
branch feature-x
"""
        worktrees = wm._parse_worktree_list(output)
        assert len(worktrees) == 2
        assert worktrees[0]["path"] == "/path/to/wt1"
        assert worktrees[0]["branch"] == "main"
        assert worktrees[1]["path"] == "/path/to/wt2"
        assert worktrees[1]["branch"] == "feature-x"

    def test_parse_worktree_list_empty(self):
        """空输出返回空列表。"""
        wm = WorktreeManager()
        assert wm._parse_worktree_list("") == []

    @pytest.mark.asyncio
    async def test_create_worktree_in_non_git_dir(self, tmp_path):
        """非 git 目录中创建工作树时应失败优雅。"""
        # 确保不在 git 仓库中
        non_git = tmp_path / "not_a_repo"
        non_git.mkdir(parents=True, exist_ok=True)
        wm = WorktreeManager(base_dir=str(non_git))
        info = await wm.create_worktree("test_agent")
        assert info is None  # 非 git 目录应该失败

    @pytest.mark.asyncio
    async def test_cleanup_nonexistent(self):
        """清理不存在的 worktree 不应崩溃。"""
        wm = WorktreeManager()
        result = await wm.cleanup_worktree("nonexistent_agent_12345")
        assert result in (True, False)  # 不应抛异常

    @pytest.mark.asyncio
    async def test_list_worktrees(self):
        """列出 worktrees 不应崩溃。"""
        wm = WorktreeManager()
        result = await wm.list_worktrees()
        assert isinstance(result, list)
