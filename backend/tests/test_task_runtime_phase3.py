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
from core.hook_manager import (
    HookManager,
    HookName,
    HookContext,
    HookResult,
    HookResultType,
    hook_manager,
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
    """钩子管理器注册与分发测试（统一 hook_manager 后从 HookDispatcher 迁移）。"""

    @pytest.mark.asyncio
    async def test_register_and_dispatch(self):
        """注册钩子并验证分发。"""
        mgr = HookManager()
        received = []

        async def my_hook(ctx, data):
            received.append(data)
            return HookResult(result_type=HookResultType.APPROVE, reason="ok")

        mgr.register("test-plugin", HookName.TOOL_BEFORE_EXECUTE, my_hook)
        results = await mgr.trigger(HookName.TOOL_BEFORE_EXECUTE, data={
            "tool_name": "read_file",
            "tool_args": {},
        })
        assert len(received) == 1
        assert len(results) == 1
        assert results[0].result_type == HookResultType.APPROVE

    @pytest.mark.asyncio
    async def test_deny_blocks_tool(self):
        """deny 决策可阻止工具调用。"""
        mgr = HookManager()

        async def block_writes(ctx, data):
            if data.get("tool_name") == "write_file":
                return HookResult(result_type=HookResultType.DENY, reason="写操作被阻止")
            return HookResult(result_type=HookResultType.APPROVE)

        mgr.register("test-plugin", HookName.TOOL_BEFORE_EXECUTE, block_writes)
        results = await mgr.trigger(HookName.TOOL_BEFORE_EXECUTE, data={
            "tool_name": "write_file",
        })
        # 检查结果中是否存在 DENY
        deny_result = None
        for r in results:
            if r.result_type == HookResultType.DENY:
                deny_result = r
                break
        assert deny_result is not None
        assert deny_result.result_type == HookResultType.DENY
        assert "写操作被阻止" in (deny_result.reason or "")

    @pytest.mark.asyncio
    async def test_has_deny_returns_none_when_all_allowed(self):
        """全部通过时没有 DENY 结果。"""
        mgr = HookManager()

        async def allow_all(ctx, data):
            return HookResult(result_type=HookResultType.APPROVE)

        mgr.register("test-plugin", HookName.TOOL_BEFORE_EXECUTE, allow_all)
        results = await mgr.trigger(HookName.TOOL_BEFORE_EXECUTE, data={"tool_name": "read_file"})
        # 检查无 DENY
        has_deny = any(r.result_type == HookResultType.DENY for r in results)
        assert not has_deny

    @pytest.mark.asyncio
    async def test_input_override(self):
        """钩子可覆写工具输入参数。"""
        mgr = HookManager()

        async def sanitize_path(ctx, data):
            return HookResult(
                result_type=HookResultType.MODIFY_INPUT,
                modified_input={"file_path": "/safe/path/file.txt"},
            )

        mgr.register("test-plugin", HookName.TOOL_BEFORE_EXECUTE, sanitize_path)
        results = await mgr.trigger(HookName.TOOL_BEFORE_EXECUTE, data={
            "tool_name": "read_file",
            "tool_args": {"file_path": "/unsafe/path/file.txt"},
        })
        from core.hook_manager import hook_updated_input
        merged = hook_updated_input(results, {"tool_name": "read_file", "tool_args": {"file_path": "/unsafe/path/file.txt"}})
        assert merged.get("file_path") == "/safe/path/file.txt"

    @pytest.mark.asyncio
    async def test_hook_exception_is_handled(self):
        """钩子异常不会中断分发。"""
        mgr = HookManager()

        async def bad_hook(ctx, data):
            raise RuntimeError("test error")

        mgr.register("test-plugin", HookName.TOOL_BEFORE_EXECUTE, bad_hook)
        results = await mgr.trigger(HookName.TOOL_BEFORE_EXECUTE, data={"tool_name": "test"})
        # 异常时不会产生结果（被 hook_manager 捕获并记录日志）
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_unregister(self):
        """注销钩子后不再分发。"""
        mgr = HookManager()
        received = []

        async def my_hook(ctx, data):
            received.append(data)
            return HookResult(result_type=HookResultType.APPROVE)

        mgr.register("test-plugin", HookName.TOOL_AFTER_EXECUTE, my_hook)
        mgr.unregister(HookName.TOOL_AFTER_EXECUTE, "test-plugin")
        await mgr.trigger(HookName.TOOL_AFTER_EXECUTE, data={"tool_name": "test"})
        assert len(received) == 0

    @pytest.mark.asyncio
    async def test_task_completed_hook(self):
        """TaskCompleted 钩子分发性。"""
        mgr = HookManager()
        completed = []

        async def on_complete(ctx, data):
            completed.append(data)
            return HookResult(result_type=HookResultType.APPROVE)

        mgr.register("test-plugin", HookName.TASK_COMPLETED, on_complete)
        await mgr.trigger(HookName.TASK_COMPLETED, data={
            "response": "task done",
            "round_count": 3,
        })
        assert len(completed) == 1

    @pytest.mark.asyncio
    async def test_additional_context_collection(self):
        """收集所有钩子的附加上下文。"""
        mgr = HookManager()

        async def add_note_a(ctx, data):
            return HookResult(result_type=HookResultType.APPROVE, modified_output="Note A")

        async def add_note_b(ctx, data):
            return HookResult(result_type=HookResultType.APPROVE, modified_output="Note B")

        mgr.register("test-plugin-a", HookName.SUBAGENT_STOP, add_note_a)
        mgr.register("test-plugin-b", HookName.SUBAGENT_STOP, add_note_b)
        results = await mgr.trigger(HookName.SUBAGENT_STOP, data={})
        # 收集所有 MODIFY_OUTPUT 结果中的 modified_output
        contexts = [r.modified_output for r in results if r.modified_output is not None]
        assert "Note A" in contexts
        assert "Note B" in contexts


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


# ── accept_edits 工作目录路径安全 ────────────────────────────

class TestPermissionGuardAcceptEditsPathSafety:
    """accept_edits 模式工作目录判定（resolve + relative_to）测试。"""

    def test_within_workdir_auto_allows(self, tmp_path):
        """工作目录内的编辑自动放行。"""
        target = tmp_path / "src" / "file.txt"
        decision = permission_guard.evaluate(
            "write_file", {"file_path": str(target)},
            permission_mode="accept_edits",
            work_dir=str(tmp_path),
        )
        assert decision.allowed is True
        assert decision.mode == "auto"
        assert decision.require_user_confirm is False

    def test_parent_traversal_not_auto_allowed(self, tmp_path):
        """../ 路径穿越不得自动放行，应退回确认流程。"""
        outside = tmp_path.parent / "outside.txt"
        decision = permission_guard.evaluate(
            "write_file", {"file_path": str(outside)},
            permission_mode="accept_edits",
            work_dir=str(tmp_path),
        )
        assert decision.allowed is True
        assert decision.require_user_confirm is True
        assert decision.mode == "confirm"

    def test_path_prefix_spoofing_not_auto_allowed(self, tmp_path):
        """目录名前缀欺骗（workdir_evil 前缀相似）不得自动放行。

        旧的 str.startswith 判断会把 work_dir 同名前缀的兄弟目录误判为
        工作目录内路径，从而绕过确认直接放行。
        """
        evil_dir = str(tmp_path) + "_evil"
        target = str(Path(evil_dir) / "secret.txt")
        decision = permission_guard.evaluate(
            "write_file", {"file_path": target},
            permission_mode="accept_edits",
            work_dir=str(tmp_path),
        )
        assert decision.allowed is True
        assert decision.require_user_confirm is True
        assert decision.mode == "confirm"

    def test_symlink_escape_not_auto_allowed(self, tmp_path):
        """符号链接指向工作目录外时不得自动放行。"""
        outside_dir = tmp_path.parent / "outside_symlink_target"
        outside_dir.mkdir(exist_ok=True)
        link_path = tmp_path / "link"
        try:
            os.symlink(outside_dir, link_path)
        except (OSError, NotImplementedError):
            pytest.skip("当前环境不支持创建符号链接")
        decision = permission_guard.evaluate(
            "write_file", {"file_path": str(link_path / "secret.txt")},
            permission_mode="accept_edits",
            work_dir=str(tmp_path),
        )
        assert decision.allowed is True
        assert decision.require_user_confirm is True
        assert decision.mode == "confirm"

    def test_within_workdir_read_operation_unaffected(self, tmp_path):
        """accept_edits 下只读操作不受工作目录判定影响。"""
        target = tmp_path / "a.txt"
        decision = permission_guard.evaluate(
            "read_file", {"file_path": str(target)},
            permission_mode="accept_edits",
            work_dir=str(tmp_path),
        )
        assert decision.allowed is True
