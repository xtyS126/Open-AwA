"""
长期记忆写入去重与 PII 脱敏单元测试。

Spec memory-quality-and-short-term-recovery：
- 命中去重时合并到已有记忆而非新增
- 写入前调用 pii_guard.scrub 脱敏
- 内容过长（> 500 字符）拒绝写入
- 去重信息通过 memory_metadata._dedup_info 透出
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from db.models import LongTermMemory, init_db
from memory.manager import MemoryManager


class _ConstantEmbeddingProvider:
    """
    恒定向量嵌入提供方。

    所有文本返回 [1.0, 0.0, 0.0]，使任意两条内容的余弦相似度 = 1.0，
    必然命中 0.85 阈值的去重逻辑，便于测试去重合并路径。
    """

    provider_name = "constant"

    async def embed_texts(self, texts):
        return [[1.0, 0.0, 0.0] for _ in texts]


class _OrthogonalEmbeddingProvider:
    """
    正交向量嵌入提供方。

    每次调用返回 [0.0, 1.0, 0.0]，与 _ConstantEmbeddingProvider 的 [1.0, 0.0, 0.0]
    余弦相似度 = 0.0，永远不会命中去重，便于测试正常写入路径。
    """

    provider_name = "orthogonal"

    async def embed_texts(self, texts):
        return [[0.0, 1.0, 0.0] for _ in texts]


class _FakeVectorHit:
    def __init__(self, memory_id, score=0.95):
        self.memory_id = memory_id
        self.score = score
        self.content = ""
        self.metadata = {}


class _FakeVectorStore:
    """
    假向量库，search 结果可控。

    用法：测试时设置 search_results 为期望返回的 hits 列表，
    upsert_memory / update_memory_metadata 不做实际存储。
    """

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


def _build_manager_with_constant_embedding():
    """
    构造 MemoryManager + 恒定向量库 + 内存数据库。

    所有嵌入向量都是 [1.0, 0.0, 0.0]，因此任意两条记忆余弦相似度 = 1.0，
    第二次写入必然命中去重。
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


def _build_manager_with_orthogonal_embedding():
    """
    构造 MemoryManager + 正交向量库 + 内存数据库。

    嵌入向量都是 [0.0, 1.0, 0.0]，与已写入记忆的 [1.0, 0.0, 0.0] 余弦相似度 = 0.0，
    永远不会命中去重，可测正常写入路径。
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    init_db(bind_engine=engine)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    fake_vector_store = _FakeVectorStore()
    fake_vector_store.embedding_provider = _OrthogonalEmbeddingProvider()
    MemoryManager._shared_vector_store = fake_vector_store
    manager = MemoryManager(factory)
    return manager, factory, fake_vector_store


@pytest.fixture(autouse=True)
def _reset_shared_vector_store():
    """每个用例前清理类级共享向量库，避免污染后续测试。"""
    saved = MemoryManager._shared_vector_store
    yield
    MemoryManager._shared_vector_store = saved


@pytest.mark.asyncio
async def test_add_long_term_memory_writes_new_when_no_duplicate():
    """
    场景：未命中去重时正常写入新记忆。

    Given 数据库无相似记忆
    When 调用 add_long_term_memory 传入 content="用户喜欢 Python"
    Then 写入新记忆，metadata._dedup_info.deduplicated=False
    And metadata.similarity_hash 已计算
    And confidence 基于五因子加权计算
    """
    manager, factory, fake_vector_store = _build_manager_with_orthogonal_embedding()
    # 第一次写入：search 返回空
    fake_vector_store.search_results = []

    memory = await manager.add_long_term_memory(
        content="用户喜欢 Python",
        importance=0.8,
        user_id="user-1",
        source_type="user_input",
    )

    assert memory.id is not None
    assert memory.content == "用户喜欢 Python"
    assert memory.user_id == "user-1"
    assert memory.archive_status == "active"
    # metadata 应含去重信息与指纹
    assert memory.memory_metadata["_dedup_info"]["deduplicated"] is False
    assert "similarity_hash" in memory.memory_metadata
    assert memory.memory_metadata["source_type"] == "user_input"
    # confidence 基于五因子加权：source=1.0(0.3) + completeness=min(11/200,1)=0.055(0.25) + recency=1.0(0.2) + dedup=1.0(0.15) + access=0(0.1)
    # = 0.3 + 0.01375 + 0.2 + 0.15 + 0 = 0.66375
    assert 0.5 < memory.confidence < 0.9
    # 向量库 upsert 被调用
    assert len(fake_vector_store.upserts) == 1
    assert fake_vector_store.upserts[0][0] == memory.id


@pytest.mark.asyncio
async def test_add_long_term_memory_merges_when_duplicate_hit():
    """
    场景：命中去重时合并到已有记忆而非新增。

    Given 数据库已存在记忆 id=1, content="用户喜欢 Python"
    When 调用 add_long_term_memory 传入 content="用户偏爱 Python 编程语言"
    And 向量相似度 = 1.0（> 0.85）
    Then 不新增记忆，而是更新 id=1 的记忆
    And access_count +1
    And metadata._dedup_info.deduplicated=True / merged_into=1
    And confidence 提升（去重命中强化 +0.05）
    """
    manager, factory, fake_vector_store = _build_manager_with_constant_embedding()

    # 第一次写入：search 返回空，正常写入
    fake_vector_store.search_results = []
    first_memory = await manager.add_long_term_memory(
        content="用户喜欢 Python",
        importance=0.8,
        user_id="user-1",
        source_type="user_input",
    )
    assert first_memory.id is not None
    assert first_memory.access_count == 0

    # 第二次写入：search 返回命中（同向量，余弦相似度 = 1.0）
    fake_vector_store.search_results = [_FakeVectorHit(first_memory.id, score=0.95)]
    second_memory = await manager.add_long_term_memory(
        content="用户偏爱 Python 编程语言",
        importance=0.7,
        user_id="user-1",
        source_type="user_input",
    )

    # 验证：返回的是已有记忆（id 相同），不是新记忆
    assert second_memory.id == first_memory.id
    # access_count +1
    assert second_memory.access_count == 1
    # 去重信息已写入 metadata
    assert second_memory.memory_metadata["_dedup_info"]["deduplicated"] is True
    assert second_memory.memory_metadata["_dedup_info"]["merged_into"] == first_memory.id
    # content 已合并（确定性回退：拼接两段）
    assert "用户喜欢 Python" in second_memory.content
    assert "用户偏爱 Python 编程语言" in second_memory.content
    # DB 中只有一条记忆
    with factory() as db:
        memories = db.query(LongTermMemory).all()
        assert len(memories) == 1
        assert memories[0].id == first_memory.id
        assert memories[0].access_count == 1


@pytest.mark.asyncio
async def test_add_long_term_memory_scrubs_pii_before_write():
    """
    场景：内容含 API key 时脱敏后再写入。

    Given content="用户的 OpenAI key 是 sk-abc123def456789012345678901234567890"
    When 调用 add_long_term_memory
    Then DB 中存储的是脱敏后的内容（含 [REDACTED]）
    And 原始 API key 不出现在数据库
    """
    manager, factory, fake_vector_store = _build_manager_with_orthogonal_embedding()
    fake_vector_store.search_results = []

    api_key = "sk-abc123def456789012345678901234567890"
    content = f"用户的 OpenAI key 是 {api_key}"

    memory = await manager.add_long_term_memory(
        content=content,
        importance=0.5,
        user_id="user-1",
    )

    assert memory.content != content
    assert "[REDACTED]" in memory.content
    assert api_key not in memory.content
    # DB 中也是脱敏后的内容
    with factory() as db:
        db_memory = db.query(LongTermMemory).filter(LongTermMemory.id == memory.id).first()
        assert db_memory is not None
        assert "[REDACTED]" in db_memory.content
        assert api_key not in db_memory.content


@pytest.mark.asyncio
async def test_add_long_term_memory_rejects_oversized_content():
    """
    场景：内容过长（> 500 字符）时拒绝写入。

    Given content 长度 > 500
    When 调用 add_long_term_memory
    Then 抛出 ValueError
    And 不写入数据库
    And 不调用向量库
    """
    manager, factory, fake_vector_store = _build_manager_with_orthogonal_embedding()
    fake_vector_store.search_results = []

    oversized_content = "x" * 600
    with pytest.raises(ValueError, match="记忆内容过长"):
        await manager.add_long_term_memory(
            content=oversized_content,
            importance=0.5,
            user_id="user-1",
        )

    # 验证未写入 DB 与向量库
    with factory() as db:
        assert db.query(LongTermMemory).count() == 0
    assert len(fake_vector_store.upserts) == 0


@pytest.mark.asyncio
async def test_add_long_term_memory_rejects_empty_content():
    """
    场景：空内容拒绝写入。
    """
    manager, factory, fake_vector_store = _build_manager_with_orthogonal_embedding()
    fake_vector_store.search_results = []

    with pytest.raises(ValueError, match="不能为空"):
        await manager.add_long_term_memory(
            content="   ",
            importance=0.5,
            user_id="user-1",
        )


@pytest.mark.asyncio
async def test_find_duplicate_memory_returns_none_when_no_hits():
    """
    场景：去重查询时向量库返回空，应返回 None。
    """
    manager, factory, fake_vector_store = _build_manager_with_constant_embedding()
    fake_vector_store.search_results = []

    result = await manager._find_duplicate_memory(
        content="测试内容",
        embedding=[1.0, 0.0, 0.0],
        user_id="user-1",
    )
    assert result is None


@pytest.mark.asyncio
async def test_find_duplicate_memory_returns_none_when_similarity_below_threshold():
    """
    场景：相似度低于阈值（0.85）时返回 None。

    Given 向量库返回命中 memory_id=1
    And DB 中 memory_id=1 的 embedding 与查询 embedding 余弦相似度 = 0.5
    When 调用 _find_duplicate_memory
    Then 返回 None（未达阈值）
    """
    manager, factory, fake_vector_store = _build_manager_with_constant_embedding()

    # 在 DB 中插入一条记忆，embedding 与查询向量夹角使相似度 < 0.85
    # 查询向量 [1.0, 0.0, 0.0]，DB 中向量 [0.5, 0.866, 0.0]，余弦相似度 = 0.5
    with factory() as db:
        memory = LongTermMemory(
            content="已有记忆",
            importance=0.5,
            embedding=[0.5, 0.866, 0.0],
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
        memory_id = memory.id

    fake_vector_store.search_results = [_FakeVectorHit(memory_id, score=0.5)]
    result = await manager._find_duplicate_memory(
        content="查询内容",
        embedding=[1.0, 0.0, 0.0],
        user_id="user-1",
    )
    assert result is None


@pytest.mark.asyncio
async def test_find_duplicate_memory_returns_tuple_when_similarity_above_threshold():
    """
    场景：相似度高于阈值时返回 (memory_id, similarity)。

    Given 向量库返回命中 memory_id=1
    And DB 中 memory_id=1 的 embedding 与查询 embedding 余弦相似度 = 1.0
    When 调用 _find_duplicate_memory
    Then 返回 (1, 1.0)
    """
    manager, factory, fake_vector_store = _build_manager_with_constant_embedding()

    with factory() as db:
        memory = LongTermMemory(
            content="已有记忆",
            importance=0.5,
            embedding=[1.0, 0.0, 0.0],
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
        memory_id = memory.id

    fake_vector_store.search_results = [_FakeVectorHit(memory_id, score=0.95)]
    result = await manager._find_duplicate_memory(
        content="查询内容",
        embedding=[1.0, 0.0, 0.0],
        user_id="user-1",
    )
    assert result is not None
    assert result[0] == memory_id
    assert abs(result[1] - 1.0) < 0.001


@pytest.mark.asyncio
async def test_find_duplicate_memory_returns_none_when_vector_search_raises():
    """
    场景：向量库 search 抛异常时返回 None，不抛错给上层。

    Given vector_store.search 抛 RuntimeError
    When 调用 _find_duplicate_memory
    Then 返回 None（去重降级为正常写入）
    """
    manager, factory, fake_vector_store = _build_manager_with_constant_embedding()

    async def _raise(*args, **kwargs):
        raise RuntimeError("vector store offline")

    fake_vector_store.search = _raise
    result = await manager._find_duplicate_memory(
        content="测试",
        embedding=[1.0, 0.0, 0.0],
        user_id="user-1",
    )
    assert result is None


@pytest.mark.asyncio
async def test_merge_memory_content_falls_back_to_concat_when_no_llm_callback():
    """
    场景：未注入 LLM 合并回调时使用确定性合并。

    Given existing="用户喜欢 Python"
    And new="用户偏爱 Python 编程语言"
    When 调用 _merge_memory_content（无 LLM 回调）
    Then 返回拼接后的内容（含两段）
    """
    manager, _, _ = _build_manager_with_constant_embedding()

    result = await manager._merge_memory_content("用户喜欢 Python", "用户偏爱 Python 编程语言")
    assert "用户喜欢 Python" in result
    assert "用户偏爱 Python 编程语言" in result


@pytest.mark.asyncio
async def test_merge_memory_content_skips_substring():
    """
    场景：新内容是已有内容的子串时保留已有内容。

    Given existing="用户喜欢 Python 后端开发"
    And new="Python 后端开发"（子串）
    When 调用 _merge_memory_content
    Then 返回 existing（去重）
    """
    manager, _, _ = _build_manager_with_constant_embedding()

    result = await manager._merge_memory_content("用户喜欢 Python 后端开发", "Python 后端开发")
    assert result == "用户喜欢 Python 后端开发"


@pytest.mark.asyncio
async def test_merge_memory_content_uses_llm_callback_when_injected():
    """
    场景：注入 LLM 回调时使用回调结果。

    Given 注入回调返回 "合并后的内容"
    When 调用 _merge_memory_content
    Then 返回 "合并后的内容"
    """
    manager, _, _ = _build_manager_with_constant_embedding()

    async def _merge(existing, new):
        return f"合并后的内容: {existing} + {new}"

    manager.set_llm_merge_callback(_merge)
    result = await manager._merge_memory_content("用户喜欢 Python", "用户偏爱 Python")
    assert result == "合并后的内容: 用户喜欢 Python + 用户偏爱 Python"


@pytest.mark.asyncio
async def test_merge_memory_content_falls_back_when_llm_callback_raises():
    """
    场景：LLM 回调抛异常时回退到确定性合并。
    """
    manager, _, _ = _build_manager_with_constant_embedding()

    async def _raise(existing, new):
        raise RuntimeError("LLM service offline")

    manager.set_llm_merge_callback(_raise)
    result = await manager._merge_memory_content("已有内容", "新增内容")
    # 应回退到拼接（确定性合并）
    assert "已有内容" in result
    assert "新增内容" in result


@pytest.mark.asyncio
async def test_compute_similarity_hash_is_deterministic():
    """
    场景：相同内容的 similarity_hash 一致，不同内容不一致。
    """
    manager, _, _ = _build_manager_with_constant_embedding()

    hash1 = manager._compute_similarity_hash("用户喜欢 Python")
    hash2 = manager._compute_similarity_hash("用户喜欢 Python")
    hash3 = manager._compute_similarity_hash("用户喜欢 Java")

    assert hash1 == hash2
    assert hash1 != hash3
    # 大小写与空白归一化
    assert manager._compute_similarity_hash("  用户喜欢 Python  ") == hash1
    assert manager._compute_similarity_hash("用户 喜欢 PYTHON") != hash1  # 大小写归一化后不同（中文不变）


@pytest.mark.asyncio
async def test_add_long_term_memory_with_extracted_from_records_source():
    """
    场景：传入 extracted_from 时记录到 memory_metadata.extracted_from。

    Given extracted_from=[100, 101]
    When 调用 add_long_term_memory
    Then memory.memory_metadata.extracted_from == [100, 101]
    """
    manager, factory, fake_vector_store = _build_manager_with_orthogonal_embedding()
    fake_vector_store.search_results = []

    memory = await manager.add_long_term_memory(
        content="用户偏好 Python 后端",
        importance=0.7,
        user_id="user-1",
        extracted_from=[100, 101],
    )

    assert memory.memory_metadata["extracted_from"] == [100, 101]


@pytest.mark.asyncio
async def test_add_long_term_memory_dedup_merges_extracted_from():
    """
    场景：去重合并时新内容的 extracted_from 合并到已有记忆。

    Given 已有记忆 extracted_from=[100]
    When 第二次写入命中去重，extracted_from=[200]
    Then 合并后 extracted_from=[100, 200]
    """
    manager, factory, fake_vector_store = _build_manager_with_constant_embedding()
    fake_vector_store.search_results = []

    first_memory = await manager.add_long_term_memory(
        content="用户喜欢 Python",
        importance=0.8,
        user_id="user-1",
        extracted_from=[100],
    )

    fake_vector_store.search_results = [_FakeVectorHit(first_memory.id, score=0.95)]
    merged_memory = await manager.add_long_term_memory(
        content="用户偏爱 Python 编程语言",
        importance=0.7,
        user_id="user-1",
        extracted_from=[200],
    )

    assert merged_memory.id == first_memory.id
    extracted_from = merged_memory.memory_metadata["extracted_from"]
    assert 100 in extracted_from
    assert 200 in extracted_from
