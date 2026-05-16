"""
Todo 任务管理工具单元测试。
验证 TodoManager 的创建、更新、持久化、状态校验等功能。
"""

import sys
import tempfile
from pathlib import Path

import pytest

# 确保 backend 目录在 Python 搜索路径中
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.builtin_tools.todo import (  # noqa: E402
    TODO_STATE_PENDING,
    TODO_STATE_IN_PROGRESS,
    TODO_STATE_COMPLETED,
    VALID_TODO_STATES,
    TodoManager,
    _build_summary,
    _detect_multi_in_progress,
)


class TestBuildSummary:
    """测试 _build_summary 辅助函数"""

    def test_empty_todos(self):
        """空任务列表返回'暂无任务'"""
        result = _build_summary([])
        assert "暂无任务" in result

    def test_all_pending(self):
        """全部待处理状态"""
        todos = [
            {"id": "1", "content": "任务A", "status": TODO_STATE_PENDING},
            {"id": "2", "content": "任务B", "status": TODO_STATE_PENDING},
        ]
        result = _build_summary(todos)
        assert "共 2 项" in result
        assert "待处理 2" in result
        assert "进行中 0" in result
        assert "已完成 0" in result

    def test_mixed_status(self):
        """混合状态的任务列表"""
        todos = [
            {"id": "1", "content": "待办", "status": TODO_STATE_PENDING},
            {"id": "2", "content": "进行", "status": TODO_STATE_IN_PROGRESS},
            {"id": "3", "content": "完成", "status": TODO_STATE_COMPLETED},
        ]
        result = _build_summary(todos)
        assert "共 3 项" in result
        assert "待处理 1" in result
        assert "进行中 1" in result
        assert "已完成 1" in result

    def test_with_warning(self):
        """带警告信息的摘要"""
        result = _build_summary([], "测试警告")
        assert "测试警告" in result
        assert "暂无任务" in result


class TestDetectMultiInProgress:
    """测试 _detect_multi_in_progress 辅助函数"""

    def test_no_in_progress(self):
        """没有进行中任务"""
        todos = [
            {"id": "1", "content": "任务", "status": TODO_STATE_PENDING},
        ]
        assert _detect_multi_in_progress(todos) is None

    def test_single_in_progress(self):
        """单个进行中任务（正常）"""
        todos = [
            {"id": "1", "content": "任务", "status": TODO_STATE_IN_PROGRESS},
        ]
        assert _detect_multi_in_progress(todos) is None

    def test_multiple_in_progress(self):
        """多个进行中任务（触发警告）"""
        todos = [
            {"id": "1", "content": "任务A", "status": TODO_STATE_IN_PROGRESS},
            {"id": "2", "content": "任务B", "status": TODO_STATE_IN_PROGRESS},
        ]
        result = _detect_multi_in_progress(todos)
        assert result is not None
        assert "2 个" in result

    def test_mixed_with_multi_in_progress(self):
        """混合状态中有多个进行中"""
        todos = [
            {"id": "1", "content": "任务A", "status": TODO_STATE_IN_PROGRESS},
            {"id": "2", "content": "任务B", "status": TODO_STATE_IN_PROGRESS},
            {"id": "3", "content": "任务C", "status": TODO_STATE_PENDING},
            {"id": "4", "content": "任务D", "status": TODO_STATE_COMPLETED},
        ]
        result = _detect_multi_in_progress(todos)
        assert result is not None
        assert "2 个" in result


class TestTodoManager:
    """测试 TodoManager 核心功能"""

    @pytest.fixture
    def tmpdir(self):
        """创建临时目录用于持久化测试"""
        with tempfile.TemporaryDirectory() as d:
            yield d

    def test_create_todos(self, tmpdir):
        """测试创建任务列表"""
        mgr = TodoManager(session_dir=tmpdir)

        todos = [
            {"id": "1", "content": "第一个任务", "status": "pending"},
            {"id": "2", "content": "第二个任务", "status": "pending"},
            {"id": "3", "content": "第三个任务", "status": "pending"},
        ]

        result = mgr.update_todos(todos)
        assert result["success"] is True
        assert result["counts"]["total"] == 3
        assert result["counts"]["pending"] == 3
        assert result["counts"]["in_progress"] == 0
        assert result["counts"]["completed"] == 0

    def test_update_status(self, tmpdir):
        """测试替换式更新任务状态"""
        mgr = TodoManager(session_dir=tmpdir)

        # 第一步：创建任务
        mgr.update_todos([
            {"id": "1", "content": "任务A", "status": "pending"},
            {"id": "2", "content": "任务B", "status": "pending"},
        ])

        # 第二步：更新状态（替换式，必须传入全部任务）
        mgr.update_todos([
            {"id": "1", "content": "任务A", "status": "completed"},
            {"id": "2", "content": "任务B", "status": "in_progress"},
        ])

        result = mgr.get_todos()
        assert result["count"] == 2
        todos = result["todos"]
        assert todos[0]["status"] == "completed"
        assert todos[1]["status"] == "in_progress"

    def test_persistence(self, tmpdir):
        """测试任务持久化与恢复"""
        # 第一个管理器实例：创建并持久化
        mgr1 = TodoManager(session_dir=tmpdir)
        mgr1.update_todos([
            {"id": "1", "content": "持久化任务", "status": "pending"},
        ])

        # 第二个管理器实例：从磁盘恢复
        mgr2 = TodoManager(session_dir=tmpdir)
        result = mgr2.get_todos()
        assert result["count"] == 1
        assert result["todos"][0]["content"] == "持久化任务"

    def test_empty_list_clears_todos(self, tmpdir):
        """测试传入空列表清空所有任务"""
        mgr = TodoManager(session_dir=tmpdir)

        mgr.update_todos([
            {"id": "1", "content": "任务", "status": "pending"},
        ])
        mgr.update_todos([])

        result = mgr.get_todos()
        assert result["count"] == 0

    def test_invalid_status_defaults_to_pending(self, tmpdir):
        """测试无效状态值自动回退为 pending"""
        mgr = TodoManager(session_dir=tmpdir)

        mgr.update_todos([
            {"id": "1", "content": "任务", "status": "invalid_status"},
        ])

        result = mgr.get_todos()
        assert result["todos"][0]["status"] == "pending"

    def test_remove_task_by_omission(self, tmpdir):
        """测试通过不再传入某个任务来删除它"""
        mgr = TodoManager(session_dir=tmpdir)

        mgr.update_todos([
            {"id": "1", "content": "保留任务", "status": "pending"},
            {"id": "2", "content": "移除任务", "status": "pending"},
        ])

        # 只传入 id=1 的任务，id=2 被隐式删除
        mgr.update_todos([
            {"id": "1", "content": "保留任务", "status": "in_progress"},
        ])

        result = mgr.get_todos()
        assert result["count"] == 1
        assert result["todos"][0]["id"] == "1"
        assert result["todos"][0]["status"] == "in_progress"

    def test_timestamps_preserved(self, tmpdir):
        """测试已有任务的时间戳在更新后被保留"""
        mgr = TodoManager(session_dir=tmpdir)

        mgr.update_todos([
            {"id": "1", "content": "原始任务", "status": "pending"},
        ])

        first_result = mgr.get_todos()
        original_created_at = first_result["todos"][0]["createdAt"]

        # 更新状态但不改变内容
        mgr.update_todos([
            {"id": "1", "content": "原始任务", "status": "completed"},
        ])

        second_result = mgr.get_todos()
        assert second_result["todos"][0]["createdAt"] == original_created_at
        assert second_result["todos"][0]["status"] == "completed"
        # updatedAt 应该被更新
        assert "updatedAt" in second_result["todos"][0]

    def test_no_session_dir(self):
        """测试不传 session_dir 时仅内存存储"""
        mgr = TodoManager(session_dir=None)

        mgr.update_todos([
            {"id": "1", "content": "纯内存任务", "status": "pending"},
        ])

        result = mgr.get_todos()
        assert result["count"] == 1

        # 创建新实例，不应有数据（因为没有持久化）
        mgr2 = TodoManager(session_dir=None)
        result2 = mgr2.get_todos()
        assert result2["count"] == 0

    def test_set_session_dir(self, tmpdir):
        """测试 set_session_dir 切换会话目录"""
        with tempfile.TemporaryDirectory() as tmpdir2:
            # 写入 dir1
            mgr = TodoManager(session_dir=tmpdir)
            mgr.update_todos([
                {"id": "1", "content": "dir1 的任务", "status": "pending"},
            ])

            # 切换到 dir2（清空内存，从 dir2 加载）
            mgr.set_session_dir(tmpdir2)
            result = mgr.get_todos()
            assert result["count"] == 0  # dir2 为空

            # 在 dir2 中创建新任务
            mgr.update_todos([
                {"id": "2", "content": "dir2 的任务", "status": "in_progress"},
            ])
            result = mgr.get_todos()
            assert result["count"] == 1
            assert result["todos"][0]["id"] == "2"

    def test_multi_in_progress_warning(self, tmpdir):
        """测试多个 in_progress 任务的警告"""
        mgr = TodoManager(session_dir=tmpdir)

        result = mgr.update_todos([
            {"id": "1", "content": "任务A", "status": "in_progress"},
            {"id": "2", "content": "任务B", "status": "in_progress"},
            {"id": "3", "content": "任务C", "status": "pending"},
        ])

        assert result["success"] is True
        assert "warning" in result
        assert "2 个" in result["warning"]
        assert result["counts"]["in_progress"] == 2

    def test_active_form_preserved(self, tmpdir):
        """测试 activeForm 字段在更新后被保留"""
        mgr = TodoManager(session_dir=tmpdir)

        mgr.update_todos([
            {"id": "1", "content": "任务", "status": "pending", "activeForm": "正在处理中..."},
        ])

        # 更新状态但不传 activeForm
        mgr.update_todos([
            {"id": "1", "content": "任务", "status": "completed"},
        ])

        result = mgr.get_todos()
        assert result["todos"][0]["activeForm"] == "正在处理中..."

    def test_active_form_overwritten(self, tmpdir):
        """测试 activeForm 在传入新值时被覆盖"""
        mgr = TodoManager(session_dir=tmpdir)

        mgr.update_todos([
            {"id": "1", "content": "任务", "status": "pending", "activeForm": "旧文本"},
        ])

        mgr.update_todos([
            {"id": "1", "content": "任务", "status": "in_progress", "activeForm": "新文本"},
        ])

        result = mgr.get_todos()
        assert result["todos"][0]["activeForm"] == "新文本"

    def test_summary_with_content_field(self, tmpdir):
        """测试返回结果包含 content 字段（Claude Code 协议兼容）"""
        mgr = TodoManager(session_dir=tmpdir)

        result = mgr.update_todos([
            {"id": "1", "content": "测试任务", "status": "pending"},
        ])

        assert "content" in result
        assert len(result["content"]) == 1
        assert result["content"][0]["type"] == "text"
        assert "共 1 项" in result["content"][0]["text"]


class TestTodoManagerExecuteInterface:
    """测试 TodoManager 的 execute 工具接口"""

    @pytest.fixture
    def mgr(self):
        """创建无持久化的 TodoManager 实例"""
        return TodoManager(session_dir=None)

    async def test_execute_todo_write(self, mgr):
        """测试通过 execute 接口调用 todo_write"""
        result = await mgr.execute(
            "todo_write",
            todos=[
                {"id": "1", "content": "通过 execute 创建的任务", "status": "pending"},
                {"id": "2", "content": "进行中的任务", "status": "in_progress"},
            ],
        )

        assert result["success"] is True
        assert result["counts"]["total"] == 2
        assert result["counts"]["pending"] == 1
        assert result["counts"]["in_progress"] == 1

    async def test_execute_unknown_action(self, mgr):
        """测试未知操作返回错误"""
        result = await mgr.execute("unknown_action")
        assert result["success"] is False
        assert "未知" in result["error"]

    async def test_execute_empty_todos(self, mgr):
        """测试 execute 传入空数组"""
        # 先创建一些任务
        await mgr.execute(
            "todo_write",
            todos=[{"id": "1", "content": "临时任务", "status": "pending"}],
        )

        # 清空
        result = await mgr.execute("todo_write", todos=[])
        assert result["success"] is True
        assert result["counts"]["total"] == 0

    def test_get_tools(self, mgr):
        """测试 get_tools 返回工具定义"""
        tools = mgr.get_tools()
        assert len(tools) == 1
        assert tools[0]["name"] == "todo_write"
        assert "parameters" in tools[0]


class TestTodoConstants:
    """测试 Todo 常量定义"""

    def test_valid_states(self):
        """验证 VALID_TODO_STATES 包含正确的状态值"""
        assert TODO_STATE_PENDING in VALID_TODO_STATES
        assert TODO_STATE_IN_PROGRESS in VALID_TODO_STATES
        assert TODO_STATE_COMPLETED in VALID_TODO_STATES
        assert len(VALID_TODO_STATES) == 3
