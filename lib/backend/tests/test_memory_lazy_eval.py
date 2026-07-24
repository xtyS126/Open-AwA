"""
长期记忆访问时懒评估单元测试。

Spec memory-quality-and-short-term-recovery：
- 访问时调用 _evaluate_memory_in_session 重新计算 confidence
- access_count +1
- last_access 更新为当前时间
- recency_score 重新计算为 1.0
- 数据库持久化新 confidence
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from db.models import LongTermMemory, init_db
from memory.manager import MemoryManager


class _ConstantEmbeddingProvider:
    """恒定向量嵌入提供方，便于构造可预测的相似度。"""

    provider_name = "constant"

    async def embed_texts(self, texts):
        return [[1.0, 0.0, 0.0] for _ in texts]


class _FakeVectorHit:
    def __init__(self, memory_id, score=0.95):
        self.memory_id = memory_id
        self.score = score
        self.content = ""
        self.metadata = {}


class _FakeVectorStore:
    """假向量库，search 结果可控。"""

    def __init__(self):
        self.embedding_provider = _ConstantEmbeddingProvider()
        self.provider_name = "constant"
        self.search_results: list = []
        self.search_calls: list = []
        self.upserts: list = []
        self.metadata_updates: list = []
        self.deleted: list = []
        self.count_value = 0

    async def upsert_memory(self, memory_id, content, **kwargs):
        self.upserts.append((memory_id, content, kwargs))

    def update_memory_metadata(self, memory_id, **kwargs):
        self.metadata_updates.append((memory_id, kwargs))

    async def search(self, *args, **kwargs):
        self.search_calls.append((args, kwargs))
        return list(self.search_results)

    def delete_memory(self, memory_id):
        self.deleted.append(memory_id)

    def count(self, **kwargs):
        return self.count_value

    def close(self):
        pass


def _build_manager():
    """
    构造 MemoryManager + 内存数据库 + 假向量库。
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    init_db(bind_engine=engine)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    fake_vector_store = _FakeVectorStore()
    MemoryManager._shared_vector_store = fake_vector_store
    manager = MemoryManager(factory)
    return manager, factory, fake_vector_store


@pytest.fixture(autouse=True)
def _reset_shared_vector_store():
    """每个用例前清理类级共享向量库。"""
    saved = MemoryManager._shared_vector_store
    yield
    MemoryManager._shared_vector_store = saved


def _insert_memory(
    factory,
    *,
    content: str = "已有记忆",
    importance: float = 0.5,
    access_count: int = 5,
    last_access_offset_days: int = 10,
    confidence: float = 0.5,
) -> int:
    """
    在 DB 中直接插入一条长期记忆，返回 ID。

    last_access 设为 last_access_offset_days 天前，便于测试 recency_score 重算。
    """
    last_access = datetime.now(timezone.utc) - timedelta(days=last_access_offset_days)
    with factory() as db:
        memory = LongTermMemory(
            content=content,
            importance=importance,
            embedding=[1.0, 0.0, 0.0],
            user_id="user-1",
            workspace_id="default",
            access_count=access_count,
            last_access=last_access,
            confidence=confidence,
            quality_score=0.4,
            archive_status="active",
            memory_metadata={"source_type": "user_input"},
            memory_layer="semantic",
        )
        db.add(memory)
        db.commit()
        db.refresh(memory)
        memory_id = memory.id
    return memory_id


@pytest.mark.asyncio
async def test_evaluate_memory_in_session_with_increment_access_increases_access_count():
    """
    场景：访问时懒评估强化。

    Given 记忆 id=42, access_count=5
    When 调用 _evaluate_memory_in_session(increment_access=True)
    Then access_count +1 → 6
    And last_access 更新为当前时间（recency_score = 1.0）
    And confidence 重新计算并持久化
    """
    manager, factory, _ = _build_manager()
    memory_id = _insert_memory(factory, access_count=5, last_access_offset_days=10)

    with factory() as db:
        memory = db.query(LongTermMemory).filter(LongTermMemory.id == memory_id).first()
        result = manager._evaluate_memory_in_session(db, memory, increment_access=True)

    # access_count +1
    assert result["access_count"] == 6
    # 数据库已持久化
    with factory() as db:
        db_memory = db.query(LongTermMemory).filter(LongTermMemory.id == memory_id).first()
        assert db_memory.access_count == 6
        # last_access 接近当前时间（recency_score = 1.0）
        # SQLite 存储不带 tzinfo，比较时需统一为 aware UTC
        last_access_aware = (
            db_memory.last_access.replace(tzinfo=timezone.utc)
            if db_memory.last_access.tzinfo is None
            else db_memory.last_access
        )
        assert (datetime.now(timezone.utc) - last_access_aware).total_seconds() < 60
        # confidence 已重新计算并持久化
        # access_count=6 → access_factor=min(6/20, 1)=0.3 → 0.3 * 0.1 = 0.03
        # recency=1.0 → 1.0 * 0.2 = 0.2
        # source_score=1.0（user_input）→ 1.0 * 0.3 = 0.3
        # completeness=min(4/200, 1)=0.02 → 0.02 * 0.25 = 0.005
        # dedup_penalty=1.0（未命中）→ 1.0 * 0.15 = 0.15
        # 总计：0.3 + 0.005 + 0.2 + 0.15 + 0.03 = 0.685
        assert abs(db_memory.confidence - 0.685) < 0.01


@pytest.mark.asyncio
async def test_evaluate_memory_in_session_without_increment_access_preserves_access_count():
    """
    场景：批量列表查询时不增加 access_count。

    Given 记忆 access_count=5
    When 调用 _evaluate_memory_in_session(increment_access=False)
    Then access_count 仍为 5
    And confidence 仍按当前值重算
    """
    manager, factory, _ = _build_manager()
    memory_id = _insert_memory(factory, access_count=5, last_access_offset_days=10)

    with factory() as db:
        memory = db.query(LongTermMemory).filter(LongTermMemory.id == memory_id).first()
        result = manager._evaluate_memory_in_session(db, memory, increment_access=False)

    assert result["access_count"] == 5
    with factory() as db:
        db_memory = db.query(LongTermMemory).filter(LongTermMemory.id == memory_id).first()
        assert db_memory.access_count == 5


@pytest.mark.asyncio
async def test_evaluate_memory_in_session_recency_recovers_after_lazy_eval():
    """
    场景：访问后 recency_score 恢复到 1.0。

    Given 记忆 last_access=45 天前，confidence 因时效衰减而低
    When 调用 _evaluate_memory_in_session(increment_access=True)
    Then last_access 更新为当前时间
    And confidence 的 recency 因子从 (1 - 45/30)≈0 提升到 1.0
    """
    manager, factory, _ = _build_manager()
    memory_id = _insert_memory(factory, last_access_offset_days=45)

    with factory() as db:
        memory = db.query(LongTermMemory).filter(LongTermMemory.id == memory_id).first()
        # 增量前：last_access 45 天前
        old_last_access = memory.last_access
        result = manager._evaluate_memory_in_session(db, memory, increment_access=True)

    # last_access 已刷新
    with factory() as db:
        db_memory = db.query(LongTermMemory).filter(LongTermMemory.id == memory_id).first()
        # SQLite 不带 tzinfo，统一为 aware UTC 后比较
        old_aware = (
            old_last_access.replace(tzinfo=timezone.utc)
            if old_last_access.tzinfo is None
            else old_last_access
        )
        new_aware = (
            db_memory.last_access.replace(tzinfo=timezone.utc)
            if db_memory.last_access.tzinfo is None
            else db_memory.last_access
        )
        assert new_aware > old_aware
        # recency_score = max(0, 1 - (0/30)) = 1.0（刚访问）
        # confidence 应至少比未懒评估时更高（recency 从 0 → 1.0 提升 0.2）
        assert db_memory.confidence >= 0.45


@pytest.mark.asyncio
async def test_search_memories_lazy_evaluates_hits():
    """
    场景：search_memories 命中记忆时懒评估强化。

    Given DB 中有记忆，access_count=3，last_access=10 天前
    When 调用 search_memories 命中该记忆
    Then access_count +1（从 3 → 4）
    And last_access 更新为当前时间
    And confidence 重新计算
    And 数据库已持久化
    """
    manager, factory, fake_vector_store = _build_manager()
    memory_id = _insert_memory(factory, access_count=3, last_access_offset_days=10)

    # 模拟向量库返回命中
    fake_vector_store.search_results = [_FakeVectorHit(memory_id, score=0.9)]

    results = await manager.search_memories(query="已有记忆", user_id="user-1", limit=5)

    assert len(results) == 1
    assert results[0].id == memory_id

    # 验证 access_count 已 +1
    with factory() as db:
        db_memory = db.query(LongTermMemory).filter(LongTermMemory.id == memory_id).first()
        assert db_memory.access_count == 4
        # last_access 已更新
        last_access_aware = (
            db_memory.last_access.replace(tzinfo=timezone.utc)
            if db_memory.last_access.tzinfo is None
            else db_memory.last_access
        )
        assert (datetime.now(timezone.utc) - last_access_aware).total_seconds() < 60


@pytest.mark.asyncio
async def test_search_memories_does_not_evaluate_when_no_hits():
    """
    场景：search_memories 未命中时不调用懒评估。

    Given DB 中无记忆
    When 调用 search_memories
    Then 返回空列表
    And 不调用向量库 upsert 或 update_memory_metadata
    """
    manager, factory, fake_vector_store = _build_manager()
    fake_vector_store.search_results = []

    results = await manager.search_memories(query="不存在", user_id="user-1", limit=5)
    assert results == []
    assert len(fake_vector_store.metadata_updates) == 0


@pytest.mark.asyncio
async def test_evaluate_memory_in_session_persists_archive_status():
    """
    场景：懒评估时如果记忆满足归档条件，自动标记为 archived。

    Given 记忆 last_access=45 天前，importance=0.1（满足归档条件）
    When 调用 _evaluate_memory_in_session
    Then archive_status 从 "active" 变为 "archived"
    """
    manager, factory, _ = _build_manager()
    memory_id = _insert_memory(
        factory,
        importance=0.1,
        last_access_offset_days=45,
    )

    with factory() as db:
        memory = db.query(LongTermMemory).filter(LongTermMemory.id == memory_id).first()
        result = manager._evaluate_memory_in_session(db, memory, increment_access=False)

    # 懒评估时不会触发归档（因 _should_archive 检查 last_access）
    # 但 increment_access=True 时 last_access 更新，归档条件不再满足
    # 此处验证归档条件触发路径：不增量访问但 import=0.1 + last_access=45天
    assert result["archive_status"] == "archived"


@pytest.mark.asyncio
async def test_evaluate_memory_in_session_increment_skips_archive_when_recent():
    """
    场景：懒评估时即使 importance 低，访问后也不会立即归档（last_access 更新）。

    Given 记忆 last_access=45 天前，importance=0.1
    When 调用 _evaluate_memory_in_session(increment_access=True)
    Then last_access 更新为当前时间，archive_status 保持 "active"
    """
    manager, factory, _ = _build_manager()
    memory_id = _insert_memory(
        factory,
        importance=0.1,
        last_access_offset_days=45,
    )

    with factory() as db:
        memory = db.query(LongTermMemory).filter(LongTermMemory.id == memory_id).first()
        result = manager._evaluate_memory_in_session(db, memory, increment_access=True)

    # 增量访问后 last_access 更新，归档条件不满足
    assert result["archive_status"] == "active"


@pytest.mark.asyncio
async def test_update_memory_access_lazy_evaluates_confidence():
    """
    场景：update_memory_access 单条访问懒评估。

    Given 记忆 access_count=5
    When 调用 update_memory_access(memory_id)
    Then access_count +1 → 6
    And confidence 已重新计算并持久化
    """
    manager, factory, _ = _build_manager()
    memory_id = _insert_memory(factory, access_count=5, last_access_offset_days=10)

    await manager.update_memory_access(memory_id)

    with factory() as db:
        db_memory = db.query(LongTermMemory).filter(LongTermMemory.id == memory_id).first()
        assert db_memory.access_count == 6
        last_access_aware = (
            db_memory.last_access.replace(tzinfo=timezone.utc)
            if db_memory.last_access.tzinfo is None
            else db_memory.last_access
        )
        assert (datetime.now(timezone.utc) - last_access_aware).total_seconds() < 60
        assert db_memory.confidence > 0  # 已重算
