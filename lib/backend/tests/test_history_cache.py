"""
MemoryManager 对话历史缓存单元测试。

覆盖 backend/memory/manager.py 的 get_short_term_memories 行为：
- 5 秒内第二次调用命中 _history_cache（不重复查询 DB）
- invalidate_history_cache(session_id) 后下次查询重新走 DB
- 不同 session_id 不共享缓存
- 不同 limit 参数的查询不共享缓存
- 缓存命中后 invalidate 只影响目标 session，不影响其他 session

通过预置 _shared_vector_store 单例 + mock _get_short_term_memories_sync，
避免触发真实 Qdrant 初始化与 DB 查询。
"""

import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from memory.manager import MemoryManager


@pytest.fixture
def memory_manager(monkeypatch) -> MemoryManager:
    """构造一个绕过 Qdrant/VectorStoreManager 初始化的 MemoryManager。

    - 预置 _shared_vector_store 为 MagicMock，跳过真实 VectorStoreManager 创建
    - session_factory 返回 MagicMock 上下文管理器，避免触发 DB 查询
    """
    fake_vector_store = MagicMock()
    fake_vector_store.search = AsyncMock(return_value=[])
    monkeypatch.setattr(
        MemoryManager, "_shared_vector_store", fake_vector_store
    )

    # session_factory 返回 MagicMock 上下文管理器，避免真实 DB 查询
    fake_session = MagicMock()
    fake_session.query.return_value.filter.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []
    fake_session.expunge = MagicMock()
    fake_session.commit = MagicMock()
    fake_session.close = MagicMock()

    fake_session_factory = MagicMock()
    fake_session_factory.return_value.__enter__.return_value = fake_session
    fake_session_factory.return_value.__exit__.return_value = False

    manager = MemoryManager(fake_session_factory)
    return manager


def _make_fake_memory(role: str, content: str) -> MagicMock:
    """构造一个模拟 ShortTermMemory 的 MagicMock 对象。"""
    m = MagicMock()
    m.role = role
    m.content = content
    return m


@pytest.mark.asyncio
async def test_get_short_term_memories_caches_result(memory_manager: MemoryManager) -> None:
    """5 秒内第二次调用应命中缓存，_get_short_term_memories_sync 只被调用一次。"""
    fake_memories = [_make_fake_memory("user", "hello")]
    memory_manager._get_short_term_memories_sync = MagicMock(return_value=fake_memories)

    # 第一次调用：缓存未命中，查询 DB
    result1 = await memory_manager.get_short_term_memories("sess-1", limit=10)
    assert result1 == fake_memories
    assert memory_manager._get_short_term_memories_sync.call_count == 1

    # 第二次调用：5 秒内应命中缓存，不再次查询 DB
    result2 = await memory_manager.get_short_term_memories("sess-1", limit=10)
    assert result2 == fake_memories
    assert memory_manager._get_short_term_memories_sync.call_count == 1

    # 缓存中应有一条记录
    assert len(memory_manager._history_cache) == 1


@pytest.mark.asyncio
async def test_invalidate_history_cache_clears_cache(memory_manager: MemoryManager) -> None:
    """invalidate_history_cache(session_id) 后下次查询应重新走 DB。"""
    fake_memories = [_make_fake_memory("user", "hello")]
    memory_manager._get_short_term_memories_sync = MagicMock(return_value=fake_memories)

    # 第一次调用填充缓存
    await memory_manager.get_short_term_memories("sess-1", limit=10)
    assert memory_manager._get_short_term_memories_sync.call_count == 1
    assert len(memory_manager._history_cache) == 1

    # 失效缓存
    memory_manager.invalidate_history_cache("sess-1")
    assert len(memory_manager._history_cache) == 0

    # 第二次调用应重新查询 DB
    result2 = await memory_manager.get_short_term_memories("sess-1", limit=10)
    assert result2 == fake_memories
    assert memory_manager._get_short_term_memories_sync.call_count == 2


@pytest.mark.asyncio
async def test_different_sessions_have_separate_cache(memory_manager: MemoryManager) -> None:
    """不同 session_id 不共享缓存，各自独立查询 DB。"""
    fake_memories_1 = [_make_fake_memory("user", "hello from sess-1")]
    fake_memories_2 = [_make_fake_memory("user", "hello from sess-2")]

    def side_effect(session_id, limit, workspace_id="default"):
        if session_id == "sess-1":
            return fake_memories_1
        return fake_memories_2

    memory_manager._get_short_term_memories_sync = MagicMock(side_effect=side_effect)

    # 两个 session 各查询一次
    result1 = await memory_manager.get_short_term_memories("sess-1", limit=10)
    result2 = await memory_manager.get_short_term_memories("sess-2", limit=10)

    assert result1 == fake_memories_1
    assert result2 == fake_memories_2
    assert memory_manager._get_short_term_memories_sync.call_count == 2
    # 缓存中应有两条记录
    assert len(memory_manager._history_cache) == 2

    # 再次查询应命中各自缓存，不触发 DB 查询
    result1_2 = await memory_manager.get_short_term_memories("sess-1", limit=10)
    result2_2 = await memory_manager.get_short_term_memories("sess-2", limit=10)

    assert result1_2 == fake_memories_1
    assert result2_2 == fake_memories_2
    assert memory_manager._get_short_term_memories_sync.call_count == 2


@pytest.mark.asyncio
async def test_different_limits_have_separate_cache(memory_manager: MemoryManager) -> None:
    """同一 session_id 但 limit 不同应使用独立缓存条目。"""
    fake_memories_10 = [_make_fake_memory("user", "limit=10")]
    fake_memories_20 = [_make_fake_memory("user", "limit=20")]

    def side_effect(session_id, limit, workspace_id="default"):
        if limit == 10:
            return fake_memories_10
        return fake_memories_20

    memory_manager._get_short_term_memories_sync = MagicMock(side_effect=side_effect)

    # 同一 session 但 limit 不同
    result_10 = await memory_manager.get_short_term_memories("sess-1", limit=10)
    result_20 = await memory_manager.get_short_term_memories("sess-1", limit=20)

    assert result_10 == fake_memories_10
    assert result_20 == fake_memories_20
    assert memory_manager._get_short_term_memories_sync.call_count == 2
    # 缓存中应有两条记录（key 包含 limit）
    assert len(memory_manager._history_cache) == 2

    # 再次查询相同参数应命中缓存
    result_10_2 = await memory_manager.get_short_term_memories("sess-1", limit=10)
    assert result_10_2 == fake_memories_10
    assert memory_manager._get_short_term_memories_sync.call_count == 2


@pytest.mark.asyncio
async def test_invalidate_one_session_does_not_affect_others(memory_manager: MemoryManager) -> None:
    """invalidate 一个 session 的缓存不应影响其他 session 的缓存。"""
    fake_memories_1 = [_make_fake_memory("user", "sess-1")]
    fake_memories_2 = [_make_fake_memory("user", "sess-2")]

    def side_effect(session_id, limit, workspace_id="default"):
        if session_id == "sess-1":
            return fake_memories_1
        return fake_memories_2

    memory_manager._get_short_term_memories_sync = MagicMock(side_effect=side_effect)

    # 两个 session 各填充缓存
    await memory_manager.get_short_term_memories("sess-1", limit=10)
    await memory_manager.get_short_term_memories("sess-2", limit=10)
    assert memory_manager._get_short_term_memories_sync.call_count == 2
    assert len(memory_manager._history_cache) == 2

    # 只失效 sess-1
    memory_manager.invalidate_history_cache("sess-1")
    assert len(memory_manager._history_cache) == 1

    # sess-1 重新查询应触发 DB
    await memory_manager.get_short_term_memories("sess-1", limit=10)
    assert memory_manager._get_short_term_memories_sync.call_count == 3

    # sess-2 仍命中缓存，不触发 DB
    await memory_manager.get_short_term_memories("sess-2", limit=10)
    assert memory_manager._get_short_term_memories_sync.call_count == 3


@pytest.mark.asyncio
async def test_ttl_expiration_triggers_db_query(memory_manager: MemoryManager) -> None:
    """缓存 TTL 过期后应重新查询 DB。

    通过直接修改缓存条目的 expired_at 模拟过期，避免真实等待 5 秒。
    """
    fake_memories = [_make_fake_memory("user", "hello")]
    memory_manager._get_short_term_memories_sync = MagicMock(return_value=fake_memories)

    # 第一次调用填充缓存
    await memory_manager.get_short_term_memories("sess-1", limit=10)
    assert memory_manager._get_short_term_memories_sync.call_count == 1

    # 模拟 TTL 过期：将 expired_at 回拨到 1 秒前
    cache_key = ("sess-1", 10, "default")
    memories, _ = memory_manager._history_cache[cache_key]
    memory_manager._history_cache[cache_key] = (memories, time.time() - 1)

    # 第二次调用应判定为过期，重新查询 DB
    result2 = await memory_manager.get_short_term_memories("sess-1", limit=10)
    assert result2 == fake_memories
    assert memory_manager._get_short_term_memories_sync.call_count == 2


@pytest.mark.asyncio
async def test_invalidate_nonexistent_session_is_noop(memory_manager: MemoryManager) -> None:
    """invalidate 不存在的 session_id 应安全返回，不抛异常。"""
    fake_memories = [_make_fake_memory("user", "hello")]
    memory_manager._get_short_term_memories_sync = MagicMock(return_value=fake_memories)

    # 填充 sess-1 缓存
    await memory_manager.get_short_term_memories("sess-1", limit=10)
    assert len(memory_manager._history_cache) == 1

    # invalidate 不存在的 session，不应影响已有缓存
    memory_manager.invalidate_history_cache("sess-nonexistent")
    assert len(memory_manager._history_cache) == 1

    # sess-1 缓存仍应命中
    result = await memory_manager.get_short_term_memories("sess-1", limit=10)
    assert result == fake_memories
    assert memory_manager._get_short_term_memories_sync.call_count == 1
