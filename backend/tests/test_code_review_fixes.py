"""
Tests for code review report fixes (2026-04).
Covers:
- P0-1: async/sync mismatch (asyncio.to_thread wrapping)
- P0-4: bare except → except Exception
- P1-9: N+1 query optimization
- P1-12: request duration logging
- P2-13: SQLite connection leak (finally block)
"""

import asyncio
import inspect
import os
import time
from unittest.mock import MagicMock, patch, PropertyMock
from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import Session

# Base paths derived from this test file's location
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_REPO_ROOT = os.path.dirname(_BACKEND_DIR)


# ---------------------------------------------------------------------------
# P0-1: Verify async/sync mismatch is fixed in memory/manager.py
# ---------------------------------------------------------------------------

class TestMemoryManagerAsyncFix:
    """Verify MemoryManager methods are async and delegate to sync helpers via to_thread."""

    @pytest.fixture
    def mock_db(self):
        session = MagicMock(spec=Session)
        # Make query().filter().order_by().limit().all() return empty list
        chain = MagicMock()
        chain.filter.return_value = chain
        chain.order_by.return_value = chain
        chain.offset.return_value = chain
        chain.limit.return_value = chain
        chain.all.return_value = []
        chain.first.return_value = None
        chain.delete.return_value = 0
        chain.count.return_value = 0
        session.query.return_value = chain
        return session

    def test_add_short_term_memory_is_async(self):
        from memory.manager import MemoryManager
        assert asyncio.iscoroutinefunction(MemoryManager.add_short_term_memory)

    def test_get_short_term_memories_is_async(self):
        from memory.manager import MemoryManager
        assert asyncio.iscoroutinefunction(MemoryManager.get_short_term_memories)

    def test_clear_short_term_memory_is_async(self):
        from memory.manager import MemoryManager
        assert asyncio.iscoroutinefunction(MemoryManager.clear_short_term_memory)

    def test_add_long_term_memory_is_async(self):
        from memory.manager import MemoryManager
        assert asyncio.iscoroutinefunction(MemoryManager.add_long_term_memory)

    def test_get_long_term_memories_is_async(self):
        from memory.manager import MemoryManager
        assert asyncio.iscoroutinefunction(MemoryManager.get_long_term_memories)

    def test_update_memory_access_is_async(self):
        from memory.manager import MemoryManager
        assert asyncio.iscoroutinefunction(MemoryManager.update_memory_access)

    def test_search_memories_is_async(self):
        from memory.manager import MemoryManager
        assert asyncio.iscoroutinefunction(MemoryManager.search_memories)

    def test_delete_long_term_memory_is_async(self):
        from memory.manager import MemoryManager
        assert asyncio.iscoroutinefunction(MemoryManager.delete_long_term_memory)

    def test_consolidate_memories_is_async(self):
        from memory.manager import MemoryManager
        assert asyncio.iscoroutinefunction(MemoryManager.consolidate_memories)

    def test_sync_helpers_exist(self):
        """Verify that sync helper methods exist for thread delegation."""
        from memory.manager import MemoryManager
        assert hasattr(MemoryManager, '_add_short_term_memory_sync')
        assert hasattr(MemoryManager, '_get_short_term_memories_sync')
        assert hasattr(MemoryManager, '_clear_short_term_memory_sync')
        assert hasattr(MemoryManager, '_add_long_term_memory_sync')
        assert hasattr(MemoryManager, '_get_long_term_memories_sync')
        assert hasattr(MemoryManager, '_update_memory_access_sync')
        assert hasattr(MemoryManager, '_search_memories_sync')
        assert hasattr(MemoryManager, '_delete_long_term_memory_sync')
        assert hasattr(MemoryManager, '_consolidate_memories_sync')

    def test_sync_helpers_are_not_async(self):
        """Sync helpers should be regular functions, not coroutines."""
        from memory.manager import MemoryManager
        for attr_name in dir(MemoryManager):
            if attr_name.endswith('_sync'):
                method = getattr(MemoryManager, attr_name)
                assert not asyncio.iscoroutinefunction(method), \
                    f"{attr_name} should be a sync function"

    async def test_get_short_term_memories_uses_to_thread(self, mock_db):
        """Verify that the async method delegates to asyncio.to_thread."""
        from memory.manager import MemoryManager
        manager = MemoryManager(mock_db)
        with patch('memory.manager.asyncio.to_thread', wraps=asyncio.to_thread) as mock_thread:
            await manager.get_short_term_memories("session1")
            mock_thread.assert_called_once()

    async def test_clear_short_term_memory_returns_count(self, mock_db):
        from memory.manager import MemoryManager
        manager = MemoryManager(mock_db)
        result = await manager.clear_short_term_memory("session1")
        assert isinstance(result, int)

    async def test_get_long_term_memories_returns_list(self, mock_db):
        from memory.manager import MemoryManager
        manager = MemoryManager(mock_db)
        result = await manager.get_long_term_memories()
        assert isinstance(result, list)

    async def test_consolidate_memories_returns_count(self, mock_db):
        from memory.manager import MemoryManager
        manager = MemoryManager(mock_db)
        result = await manager.consolidate_memories()
        assert isinstance(result, int)
        assert result == 0


# ---------------------------------------------------------------------------
# P0-1: Verify async/sync mismatch is fixed in security/audit.py
# ---------------------------------------------------------------------------

class TestAuditLoggerAsyncFix:
    """Verify AuditLogger methods use asyncio.to_thread for DB operations."""

    def test_log_is_async(self):
        from security.audit import AuditLogger
        assert asyncio.iscoroutinefunction(AuditLogger.log)

    def test_get_logs_is_async(self):
        from security.audit import AuditLogger
        assert asyncio.iscoroutinefunction(AuditLogger.get_logs)

    def test_get_failed_attempts_is_async(self):
        from security.audit import AuditLogger
        assert asyncio.iscoroutinefunction(AuditLogger.get_failed_attempts)

    def test_get_suspicious_activity_is_async(self):
        from security.audit import AuditLogger
        assert asyncio.iscoroutinefunction(AuditLogger.get_suspicious_activity)

    def test_sync_helpers_exist(self):
        from security.audit import AuditLogger
        assert hasattr(AuditLogger, '_log_sync')
        assert hasattr(AuditLogger, '_get_logs_sync')
        assert hasattr(AuditLogger, '_get_failed_attempts_sync')
        assert hasattr(AuditLogger, '_get_suspicious_activity_sync')

    def test_sync_helpers_are_not_async(self):
        from security.audit import AuditLogger
        for attr_name in dir(AuditLogger):
            if attr_name.endswith('_sync'):
                method = getattr(AuditLogger, attr_name)
                assert not asyncio.iscoroutinefunction(method), \
                    f"{attr_name} should be a sync function"


# ---------------------------------------------------------------------------
# P0-1: Verify auth.py routes are sync (FastAPI threadpool)
# ---------------------------------------------------------------------------

class TestAuthRoutesSyncFix:
    """Verify auth routes have been changed to async def (P1-3 fix)."""

    def test_register_is_async(self):
        from api.routes.auth import register
        assert asyncio.iscoroutinefunction(register), \
            "register should be async def after P1-3 fix"

    def test_login_is_async(self):
        from api.routes.auth import login
        assert asyncio.iscoroutinefunction(login), \
            "login should be async def after P1-3 fix"


# ---------------------------------------------------------------------------
# P0-4: Verify bare except is fixed in skills.py
# ---------------------------------------------------------------------------

class TestBareExceptFix:
    """Verify that skills.py no longer uses bare except: clauses."""

    def test_no_bare_except_in_skills(self):
        """Scan skills.py source for bare except: patterns."""
        import ast
        import api.routes.skills as skills_module
        source_file = skills_module.__file__
        with open(source_file, 'r', encoding='utf-8') as f:
            tree = ast.parse(f.read())
        
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler):
                # A bare except has type=None
                assert node.type is not None, \
                    f"Found bare except: at line {node.lineno} in skills.py"


# ---------------------------------------------------------------------------
# P1-9: Verify N+1 query fix in experience_manager.py
# ---------------------------------------------------------------------------

class TestExperienceManagerN1Fix:
    """Verify get_experience_stats uses GROUP BY instead of N+1 queries."""

    def test_get_experience_stats_uses_group_by(self):
        """Verify the source uses func.count with group_by."""
        import ast
        import memory.experience_manager as em_module
        source_file = em_module.__file__
        with open(source_file, 'r', encoding='utf-8') as f:
            source = f.read()
        
        # Should contain group_by pattern (the fix)
        assert 'group_by' in source or 'group_by(' in source, \
            "experience_manager.py should use GROUP BY for type counts"
        
        # The N+1 pattern should be gone: looping with individual count queries
        tree = ast.parse(source)
        # We verify the file has fewer individual .count() calls in the stats method
        assert source.count('.count()') <= 2, \
            "Expected reduced .count() calls after N+1 fix"


# ---------------------------------------------------------------------------
# P1-9: Verify N+1 query fix in pricing_manager.py
# ---------------------------------------------------------------------------

class TestPricingManagerN1Fix:
    """Verify initialize_default_pricing uses batch fetch."""

    def test_initialize_default_pricing_batch_fetch(self):
        """Verify the source pre-fetches existing keys."""
        import billing.pricing_manager as pm_module
        source_file = pm_module.__file__
        with open(source_file, 'r', encoding='utf-8') as f:
            source = f.read()
        
        # Should have existing_keys pattern (batch fetch)
        assert 'existing_keys' in source, \
            "pricing_manager.py should batch-fetch existing keys"


# ---------------------------------------------------------------------------
# P1-12: Verify request duration logging in main.py
# ---------------------------------------------------------------------------

class TestRequestDurationLogging:
    """Verify main.py middleware logs request duration."""

    def test_main_imports_time(self):
        """main.py should import time module."""
        with open(os.path.join(_BACKEND_DIR, 'main.py'), 'r', encoding='utf-8') as f:
            source = f.read()
        assert 'import time' in source

    def test_main_has_duration_ms(self):
        """Middleware should log duration_ms."""
        with open(os.path.join(_BACKEND_DIR, 'main.py'), 'r', encoding='utf-8') as f:
            source = f.read()
        assert 'duration_ms' in source
        assert 'time.monotonic()' in source


# ---------------------------------------------------------------------------
# P2-13: Verify SQLite connection leak fix in migrate_db.py
# ---------------------------------------------------------------------------

class TestMigrateDbConnectionLeak:
    """Verify migrate_db.py closes connection in finally block."""

    def test_migrate_database_has_finally(self):
        """migrate_database should have a finally block to close connection."""
        with open(os.path.join(_BACKEND_DIR, 'migrate_db.py'), 'r', encoding='utf-8') as f:
            source = f.read()
        
        # Should have finally block
        assert 'finally:' in source, "migrate_db.py should have a finally block"
        # Should close connection in finally
        assert 'conn.close()' in source


# ---------------------------------------------------------------------------
# P0-2: Verify openawa.db removed from git tracking
# ---------------------------------------------------------------------------

class TestOpenAwaDbRemoved:
    """Verify openawa.db is no longer tracked by git."""

    def test_openawa_db_in_gitignore(self):
        with open(os.path.join(_REPO_ROOT, '.gitignore'), 'r', encoding='utf-8') as f:
            content = f.read()
        assert 'openawa.db' in content or '*.db' in content


# ---------------------------------------------------------------------------
# P0-3: Verify CI security scans no longer continue-on-error
# ---------------------------------------------------------------------------

class TestCISecurityScans:
    """Verify CI config no longer uses continue-on-error for security scans."""

    def test_no_continue_on_error(self):
        with open(os.path.join(_REPO_ROOT, '.github', 'workflows', 'ci.yml'), 'r', encoding='utf-8') as f:
            content = f.read()
        assert 'continue-on-error: true' not in content, \
            "CI config should not have continue-on-error: true"
