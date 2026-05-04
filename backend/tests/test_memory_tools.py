"""
记忆管理内置工具 MemoryTools 单元测试。
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.builtin_tools.memory_tools import MemoryTools, _truncate


class TestTruncate:
    def test_short_content_no_truncation(self):
        assert _truncate("hello", 10) == "hello"

    def test_long_content_truncated(self):
        result = _truncate("hello world this is long", 10)
        assert len(result) <= 10
        assert result.endswith("...")

    def test_exact_length_no_truncation(self):
        assert _truncate("hello", 5) == "hello"


@pytest.mark.asyncio
class TestMemoryTools:
    @pytest.fixture
    def tools(self):
        return MemoryTools()

    async def test_execute_unknown_action(self, tools):
        result = await tools.execute("unknown_action")
        assert result == {"success": False, "error": "未知记忆管理操作: unknown_action"}

    @patch("core.builtin_tools.memory_tools.MemoryManager")
    @patch("core.builtin_tools.memory_tools.SessionLocal")
    async def test_remember_success(self, mock_session_local, mock_memory_manager_cls, tools):
        mock_db = MagicMock()
        mock_session_local.return_value = mock_db
        mock_memory = MagicMock(id=42)
        mock_manager = MagicMock()
        mock_manager.add_long_term_memory = AsyncMock(return_value=mock_memory)
        mock_memory_manager_cls.return_value = mock_manager

        result = await tools._remember(content="用户偏好暗色主题", importance=0.8)
        assert result["success"] is True
        assert result["memory_id"] == 42

    @patch("core.builtin_tools.memory_tools.MemoryManager")
    @patch("core.builtin_tools.memory_tools.SessionLocal")
    async def test_remember_missing_content(self, mock_session_local, mock_memory_manager_cls, tools):
        result = await tools._remember(content="")
        assert result["success"] is False
        assert "content" in result["error"]

    @patch("core.builtin_tools.memory_tools.MemoryManager")
    @patch("core.builtin_tools.memory_tools.SessionLocal")
    async def test_remember_importance_clamped(self, mock_session_local, mock_memory_manager_cls, tools):
        mock_db = MagicMock()
        mock_session_local.return_value = mock_db
        mock_memory = MagicMock(id=1)
        mock_manager = MagicMock()
        mock_manager.add_long_term_memory = AsyncMock(return_value=mock_memory)
        mock_memory_manager_cls.return_value = mock_manager

        result = await tools._remember(content="test", importance=5.0)
        assert result["success"] is True
        result = await tools._remember(content="test", importance=-1.0)
        assert result["success"] is True

    @patch("core.builtin_tools.memory_tools.MemoryManager")
    @patch("core.builtin_tools.memory_tools.SessionLocal")
    async def test_recall_success(self, mock_session_local, mock_memory_manager_cls, tools):
        mock_db = MagicMock()
        mock_session_local.return_value = mock_db
        mock_memory = MagicMock()
        mock_memory.id = 1
        mock_memory.content = "用户偏好暗色"
        mock_memory.importance = 0.8
        mock_memory.confidence = 0.9
        mock_manager = MagicMock()
        mock_manager.search_memories = AsyncMock(return_value=[mock_memory])
        mock_memory_manager_cls.return_value = mock_manager

        result = await tools._recall(query="用户偏好")
        assert result["success"] is True
        assert result["count"] == 1
        assert result["memories"][0]["id"] == 1

    @patch("core.builtin_tools.memory_tools.MemoryManager")
    @patch("core.builtin_tools.memory_tools.SessionLocal")
    async def test_recall_empty_result(self, mock_session_local, mock_memory_manager_cls, tools):
        mock_db = MagicMock()
        mock_session_local.return_value = mock_db
        mock_manager = MagicMock()
        mock_manager.search_memories = AsyncMock(return_value=[])
        mock_memory_manager_cls.return_value = mock_manager

        result = await tools._recall(query="不存在的内容")
        assert result["success"] is True
        assert result["memories"] == []
        assert "未找到" in result["message"]

    @patch("core.builtin_tools.memory_tools.MemoryManager")
    @patch("core.builtin_tools.memory_tools.SessionLocal")
    async def test_recall_missing_query(self, mock_session_local, mock_memory_manager_cls, tools):
        result = await tools._recall(query="")
        assert result["success"] is False
        assert "query" in result["error"]

    @patch("core.builtin_tools.memory_tools.MemoryManager")
    @patch("core.builtin_tools.memory_tools.SessionLocal")
    async def test_forget_success(self, mock_session_local, mock_memory_manager_cls, tools):
        mock_db = MagicMock()
        mock_session_local.return_value = mock_db
        mock_manager = MagicMock()
        mock_manager.delete_long_term_memory = AsyncMock(return_value=True)
        mock_memory_manager_cls.return_value = mock_manager

        result = await tools._forget(memory_id=42)
        assert result["success"] is True
        assert "42" in result["message"]

    @patch("core.builtin_tools.memory_tools.MemoryManager")
    @patch("core.builtin_tools.memory_tools.SessionLocal")
    async def test_forget_not_found(self, mock_session_local, mock_memory_manager_cls, tools):
        mock_db = MagicMock()
        mock_session_local.return_value = mock_db
        mock_manager = MagicMock()
        mock_manager.delete_long_term_memory = AsyncMock(return_value=False)
        mock_memory_manager_cls.return_value = mock_manager

        result = await tools._forget(memory_id=999)
        assert result["success"] is False
        assert "不存在" in result["error"]

    async def test_forget_invalid_id(self, tools):
        result = await tools._forget(memory_id="not_a_number")
        assert result["success"] is False
        assert "memory_id" in result["error"]

    @patch("core.builtin_tools.memory_tools.MemoryManager")
    @patch("core.builtin_tools.memory_tools.SessionLocal")
    async def test_list_success(self, mock_session_local, mock_memory_manager_cls, tools):
        mock_db = MagicMock()
        mock_session_local.return_value = mock_db
        mock_memory = MagicMock()
        mock_memory.id = 1
        mock_memory.content = "测试记忆"
        mock_memory.importance = 0.5
        mock_memory.created_at = MagicMock()
        mock_memory.created_at.isoformat.return_value = "2025-01-01T00:00:00"
        mock_memory.archive_status = "active"
        mock_manager = MagicMock()
        mock_manager.get_long_term_memories = AsyncMock(return_value=[mock_memory])
        mock_memory_manager_cls.return_value = mock_manager

        result = await tools._list(limit=5)
        assert result["success"] is True
        assert result["count"] == 1
        assert result["memories"][0]["id"] == 1

    @patch("core.builtin_tools.memory_tools.MemoryManager")
    @patch("core.builtin_tools.memory_tools.SessionLocal")
    async def test_list_empty(self, mock_session_local, mock_memory_manager_cls, tools):
        mock_db = MagicMock()
        mock_session_local.return_value = mock_db
        mock_manager = MagicMock()
        mock_manager.get_long_term_memories = AsyncMock(return_value=[])
        mock_memory_manager_cls.return_value = mock_manager

        result = await tools._list()
        assert result["success"] is True
        assert result["memories"] == []

    @patch("core.builtin_tools.memory_tools.MemoryManager")
    @patch("core.builtin_tools.memory_tools.SessionLocal")
    async def test_stats_success(self, mock_session_local, mock_memory_manager_cls, tools):
        mock_db = MagicMock()
        mock_session_local.return_value = mock_db
        mock_manager = MagicMock()
        mock_manager.get_memory_stats = AsyncMock(return_value={
            "total_memories": 100,
            "active_memories": 80,
            "archived_memories": 20,
            "average_confidence": 0.75,
            "average_quality_score": 0.68,
            "total_access_count": 500,
        })
        mock_memory_manager_cls.return_value = mock_manager

        result = await tools._stats()
        assert result["success"] is True
        assert result["total_memories"] == 100
        assert result["active_memories"] == 80
        assert result["archived_memories"] == 20
