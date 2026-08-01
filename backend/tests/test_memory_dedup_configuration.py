"""
长期记忆去重阈值配置测试。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from db.models import LongTermMemory, init_db
from memory.manager import MemoryManager


class _VectorHit:
    """表示可控的向量检索候选。"""

    def __init__(self, memory_id: int):
        self.memory_id = memory_id


class _VectorStore:
    """提供可控候选结果的最小向量库替身。"""

    def __init__(self):
        self.search_results: list[_VectorHit] = []

    async def search(self, *args, **kwargs):
        return list(self.search_results)


def _build_manager(threshold: float):
    """构造使用内存数据库和显式阈值的记忆管理器。"""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    init_db(bind_engine=engine)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    vector_store = _VectorStore()
    MemoryManager._shared_vector_store = vector_store
    manager = MemoryManager(factory, dedup_similarity_threshold=threshold)
    return manager, factory, vector_store


def _insert_memory(factory, embedding: list[float]) -> int:
    """插入指定向量的长期记忆并返回主键。"""
    with factory() as db:
        memory = LongTermMemory(
            content="已有记忆",
            importance=0.5,
            embedding=embedding,
            user_id="user-1",
            workspace_id="default",
            confidence=0.5,
            archive_status="active",
            memory_metadata={},
            memory_layer="semantic",
        )
        db.add(memory)
        db.commit()
        db.refresh(memory)
        return memory.id


@pytest.fixture(autouse=True)
def _restore_shared_vector_store():
    """用例结束后恢复类级向量库，避免污染其他测试。"""
    saved = MemoryManager._shared_vector_store
    yield
    MemoryManager._shared_vector_store = saved


def test_threshold_defaults_to_previous_value_and_rejects_invalid_range():
    """构造边界保留 0.85 默认值，并拒绝超出有效区间的阈值。"""
    manager, factory, _ = _build_manager(0.85)

    assert manager.dedup_similarity_threshold == 0.85
    with pytest.raises(ValueError, match="0.0 到 1.0"):
        MemoryManager(factory, dedup_similarity_threshold=-0.01)
    with pytest.raises(ValueError, match="0.0 到 1.0"):
        MemoryManager(factory, dedup_similarity_threshold=1.01)


@pytest.mark.asyncio
async def test_custom_high_threshold_does_not_merge_lower_similarity():
    """较高阈值应阻止相似度不足的候选被合并。"""
    manager, factory, vector_store = _build_manager(0.95)
    memory_id = _insert_memory(factory, [0.9, 0.435889894, 0.0])
    vector_store.search_results = [_VectorHit(memory_id)]

    result = await manager._find_duplicate_memory(
        content="查询内容",
        embedding=[1.0, 0.0, 0.0],
        user_id="user-1",
    )

    assert result is None


@pytest.mark.asyncio
async def test_custom_low_threshold_merges_higher_similarity():
    """较低阈值应识别相似度超过阈值的候选。"""
    manager, factory, vector_store = _build_manager(0.8)
    memory_id = _insert_memory(factory, [0.9, 0.435889894, 0.0])
    vector_store.search_results = [_VectorHit(memory_id)]

    result = await manager._find_duplicate_memory(
        content="查询内容",
        embedding=[1.0, 0.0, 0.0],
        user_id="user-1",
    )

    assert result is not None
    assert result[0] == memory_id
    assert abs(result[1] - 0.9) < 0.001


@pytest.mark.asyncio
async def test_similarity_equal_to_threshold_is_not_duplicate():
    """相似度等于阈值时保持严格大于语义，不视为重复。"""
    manager, factory, vector_store = _build_manager(1.0)
    memory_id = _insert_memory(factory, [1.0, 0.0, 0.0])
    vector_store.search_results = [_VectorHit(memory_id)]

    result = await manager._find_duplicate_memory(
        content="查询内容",
        embedding=[1.0, 0.0, 0.0],
        user_id="user-1",
    )

    assert result is None
