"""
Memory 模块单元测试。
测试短期记忆和长期记忆的管理功能。
"""

import pytest
from unittest.mock import MagicMock, patch
from sqlalchemy.orm import Session


class TestShortTermMemory:
    """测试短期记忆"""

    def test_add_short_term_memory(self, mock_db_session: Session):
        """测试添加短期记忆"""
        from memory.manager import MemoryManager
        
        manager = MemoryManager(mock_db_session)
        
        result = manager.add_short_term(
            session_id="test_session",
            role="user",
            content="Hello world"
        )
        
        assert result is not None

    def test_get_short_term_memory(self, mock_db_session: Session):
        """测试获取短期记忆"""
        from memory.manager import MemoryManager
        
        manager = MemoryManager(mock_db_session)
        
        result = manager.get_short_term("test_session")
        
        assert isinstance(result, list)

    def test_delete_short_term_memory(self, mock_db_session: Session):
        """测试删除短期记忆"""
        from memory.manager import MemoryManager
        
        manager = MemoryManager(mock_db_session)
        
        result = manager.delete_short_term(memory_id=1)
        
        assert result is not None


class TestLongTermMemory:
    """测试长期记忆"""

    def test_add_long_term_memory(self, mock_db_session: Session):
        """测试添加长期记忆"""
        from memory.manager import MemoryManager
        
        manager = MemoryManager(mock_db_session)
        
        result = manager.add_long_term(
            content="Important fact",
            importance=0.8
        )
        
        assert result is not None

    def test_get_long_term_memory(self, mock_db_session: Session):
        """测试获取长期记忆"""
        from memory.manager import MemoryManager
        
        manager = MemoryManager(mock_db_session)
        
        result = manager.get_long_term()
        
        assert isinstance(result, list)

    def test_delete_long_term_memory(self, mock_db_session: Session):
        """测试删除长期记忆"""
        from memory.manager import MemoryManager
        
        manager = MemoryManager(mock_db_session)
        
        result = manager.delete_long_term(memory_id=1)
        
        assert result is not None


class TestMemorySearch:
    """测试记忆搜索"""

    def test_search_memory(self, mock_db_session: Session):
        """测试搜索记忆"""
        from memory.manager import MemoryManager
        
        manager = MemoryManager(mock_db_session)
        
        result = manager.search("test query")
        
        assert isinstance(result, list)


@pytest.fixture
def mock_db_session():
    """模拟数据库会话"""
    session = MagicMock(spec=Session)
    return session
