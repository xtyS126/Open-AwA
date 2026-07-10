"""
MemoryManager 向量检索 LRU 缓存与短消息跳过单元测试。

覆盖 backend/memory/manager.py 的 search_memories 行为：
- 短消息（<20 字符）跳过向量检索，只做关键词检索
- 相同 (query, user_id) 第二次命中 LRU 缓存
- 不同 user_id 的相同 query 不命中缓存
- 缓存超限（>128）时淘汰最旧条目

通过预置 _shared_vector_store 单例 + mock vector_store.search，
避免触发真实 Qdrant 初始化与嵌入计算。
"""

import sys
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
    - vector_store.search 替换为 AsyncMock，便于断言调用次数
    """
    fake_vector_store = MagicMock()
    fake_vector_store.search = AsyncMock(return_value=[])
    monkeypatch.setattr(
        MemoryManager, "_shared_vector_store", fake_vector_store
    )

    # session_factory 返回 MagicMock 上下文管理器，避免真实 DB 查询
    fake_session = MagicMock()
    fake_session.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []
    fake_session.expunge = MagicMock()
    fake_session.commit = MagicMock()
    fake_session.close = MagicMock()

    fake_session_factory = MagicMock()
    fake_session_factory.return_value.__enter__.return_value = fake_session
    fake_session_factory.return_value.__exit__.return_value = False

    manager = MemoryManager(fake_session_factory)
    return manager


@pytest.mark.asyncio
async def test_short_query_skips_vector_search(memory_manager: MemoryManager) -> None:
    """短消息（<20 字符）应跳过向量检索，只做关键词检索。"""
    short_query = "你好"  # 2 字符，远小于阈值 20

    await memory_manager.search_memories(short_query, user_id="user-1")

    # vector_store.search 不应被调用
    memory_manager.vector_store.search.assert_not_called()
    # 但关键词检索路径应执行（session_factory 被使用）
    assert memory_manager.session_factory.call_count >= 1


@pytest.mark.asyncio
async def test_long_query_triggers_vector_search(memory_manager: MemoryManager) -> None:
    """长消息（>=20 字符）应触发向量检索。"""
    long_query = "这是一段足够长的查询字符串用于触发向量检索"  # 22 字符

    await memory_manager.search_memories(long_query, user_id="user-1")

    # vector_store.search 应被调用一次
    assert memory_manager.vector_store.search.call_count == 1
    memory_manager.vector_store.search.assert_called_once()


@pytest.mark.asyncio
async def test_same_query_second_call_hits_lru_cache(memory_manager: MemoryManager) -> None:
    """相同 (query, user_id) 第二次应命中 LRU 缓存，不重复调用 vector_store.search。"""
    query = "这是一段足够长的查询字符串用于触发向量检索"

    await memory_manager.search_memories(query, user_id="user-1")
    await memory_manager.search_memories(query, user_id="user-1")

    # 第二次应命中缓存，vector_store.search 仅被调用一次
    assert memory_manager.vector_store.search.call_count == 1
    # 缓存中应有一条记录
    assert len(memory_manager._vector_search_cache) == 1


@pytest.mark.asyncio
async def test_different_user_id_does_not_hit_cache(memory_manager: MemoryManager) -> None:
    """不同 user_id 的相同 query 不应命中缓存。"""
    query = "这是一段足够长的查询字符串用于触发向量检索"

    await memory_manager.search_memories(query, user_id="user-1")
    await memory_manager.search_memories(query, user_id="user-2")

    # 两次不同 user_id 应分别调用 vector_store.search
    assert memory_manager.vector_store.search.call_count == 2
    # 缓存中应有两条记录
    assert len(memory_manager._vector_search_cache) == 2


@pytest.mark.asyncio
async def test_cache_evicts_oldest_when_exceeding_max(memory_manager: MemoryManager) -> None:
    """缓存超限（>128）时应淘汰最旧条目。"""
    # 通过直接操作缓存验证 LRU 淘汰行为，避免 129 次真实 search 调用开销
    memory_manager._VECTOR_CACHE_MAX = 2  # 临时缩小阈值便于测试

    # 模拟三次不同 query 的检索，每次都填充缓存
    queries = [
        "这是第一个足够长的查询字符串用于触发向量检索",
        "这是第二个足够长的查询字符串用于触发向量检索",
        "这是第三个足够长的查询字符串用于触发向量检索",
    ]
    for q in queries:
        await memory_manager.search_memories(q, user_id="user-1")

    # 缓存应只剩 2 条（淘汰最旧的第一个）
    assert len(memory_manager._vector_search_cache) == 2
    # 第一个 query 应已被淘汰
    cached_keys = list(memory_manager._vector_search_cache.keys())
    assert (queries[0], "user-1") not in cached_keys
    assert (queries[1], "user-1") in cached_keys
    assert (queries[2], "user-1") in cached_keys


@pytest.mark.asyncio
async def test_cache_hit_moves_entry_to_end(memory_manager: MemoryManager) -> None:
    """LRU 命中应将条目移动到队尾，避免被优先淘汰。"""
    memory_manager._VECTOR_CACHE_MAX = 2

    q1 = "这是第一个足够长的查询字符串用于触发向量检索"
    q2 = "这是第二个足够长的查询字符串用于触发向量检索"

    # 填充两条缓存
    await memory_manager.search_memories(q1, user_id="user-1")
    await memory_manager.search_memories(q2, user_id="user-1")

    # 再次访问 q1，将其 move_to_end
    await memory_manager.search_memories(q1, user_id="user-1")

    # 插入第三条，应淘汰最旧的 q2（因为 q1 刚被访问）
    q3 = "这是第三个足够长的查询字符串用于触发向量检索"
    await memory_manager.search_memories(q3, user_id="user-1")

    cached_keys = list(memory_manager._vector_search_cache.keys())
    assert (q2, "user-1") not in cached_keys  # q2 被淘汰
    assert (q1, "user-1") in cached_keys      # q1 因最近访问被保留
    assert (q3, "user-1") in cached_keys
