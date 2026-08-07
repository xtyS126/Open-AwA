"""
ConsolidationRunner 单元测试。

Spec memory-quality-and-short-term-recovery：
- 触发条件：conversation_count_since_run >= N 或 force=True
- watermark 增量读取：仅处理 id > last_short_term_memory_id 的短期记忆
- fingerprint 跳过：已处理的短期记忆不再重复 LLM 调用
- 失败处理：watermark 不更新，下次重试
- 归档评估：低质量记忆标记 state=archived
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

from db.models import (
    ConsolidationFingerprint,
    ConsolidationState,
    LongTermMemory,
    ShortTermMemory,
    init_db,
)
from memory.consolidation_runner import ConsolidationRunner
from memory.manager import MemoryManager


class _ConstantEmbeddingProvider:
    """
    恒定向量嵌入提供方。

    所有文本返回 [1.0, 0.0, 0.0]，使任意两条内容的余弦相似度 = 1.0，
    必然命中 0.85 阈值的去重逻辑，便于测试巩固提炼结果复用去重路径。
    """

    provider_name = "constant"

    async def embed_texts(self, texts):
        return [[1.0, 0.0, 0.0] for _ in texts]


class _OrthogonalEmbeddingProvider:
    """
    正交向量嵌入提供方。

    每次调用返回 [0.0, 1.0, 0.0]，与 _ConstantEmbeddingProvider 的 [1.0, 0.0, 0.0]
    余弦相似度 = 0.0，永远不会命中去重，便于测试巩固提炼结果正常写入路径。
    """

    provider_name = "orthogonal"

    async def embed_texts(self, texts):
        return [[0.0, 1.0, 0.0] for _ in texts]


class _FakeVectorStore:
    """假向量库，与 test_memory_dedup.py 共享设计。"""

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


def _build_runner(with_constant: bool = True):
    """
    构造测试用 ConsolidationRunner + 内存数据库 + 假向量库。

    Args:
        with_constant: True 用恒定向量（必命中去重），False 用正交向量（永不命中去重）
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    init_db(bind_engine=engine)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    fake_vector_store = _FakeVectorStore()
    if not with_constant:
        fake_vector_store.embedding_provider = _OrthogonalEmbeddingProvider()
    MemoryManager._shared_vector_store = fake_vector_store
    manager = MemoryManager(factory)
    runner = ConsolidationRunner(manager, factory)
    return runner, manager, factory, fake_vector_store


def _insert_short_term_memory(factory, content: str, role: str = "user", session_id: str = "s1") -> ShortTermMemory:
    """插入一条短期记忆。"""
    with factory() as db:
        memory = ShortTermMemory(
            session_id=session_id,
            role=role,
            content=content,
            workspace_id="default",
        )
        db.add(memory)
        db.commit()
        db.refresh(memory)
        db.expunge(memory)
        return memory


@pytest.fixture(autouse=True)
def _reset_shared_vector_store():
    """每个用例前清理类级共享向量库，避免污染后续测试。"""
    saved = MemoryManager._shared_vector_store
    yield
    # 用例结束后关闭当前用例中可能创建的 vector_store（避免 Qdrant 文件锁跨用例残留）
    current = MemoryManager._shared_vector_store
    if current is not None and current is not saved:
        try:
            current.close()
        except Exception:
            pass
    MemoryManager._shared_vector_store = saved


# ---------------- 触发条件测试 ----------------


@pytest.mark.asyncio
async def test_run_if_due_below_threshold_returns_not_triggered():
    """
    场景：计数器未达阈值时不触发巩固。

    Given consolidation_state.conversation_count_since_run = 3，阈值 = 10
    When 调用 run_if_due(user_id="user-1")
    Then 返回 triggered=False, reason="below_threshold"
    And 不读短期记忆，不调用 LLM
    """
    runner, manager, factory, _ = _build_runner()
    runner.increment_conversation_count("user-1")
    runner.increment_conversation_count("user-1")
    runner.increment_conversation_count("user-1")

    result = await runner.run_if_due("user-1")

    assert result["triggered"] is False
    assert result["reason"] == "below_threshold"
    assert result["count"] == 3


@pytest.mark.asyncio
async def test_run_if_due_force_bypasses_threshold():
    """
    场景：force=True 时无视阈值强制触发。

    Given consolidation_state.conversation_count_since_run = 0
    When 调用 run_if_due(user_id="user-1", force=True)
    Then 触发巩固，返回 triggered=True
    """
    runner, manager, factory, _ = _build_runner()

    result = await runner.run_if_due("user-1", force=True)

    assert result["triggered"] is True
    assert result["success"] is True
    # 无短期记忆时返回 reason="no_new_memories"
    assert result["reason"] == "no_new_memories"


@pytest.mark.asyncio
async def test_run_if_due_triggers_when_threshold_reached():
    """
    场景：计数器达到阈值时触发巩固。

    Given 增量 10 次对话（默认阈值），无短期记忆
    When 调用 run_if_due(user_id="user-1")
    Then 触发巩固但 reason="no_new_memories"
    And 计数器重置为 0
    """
    runner, manager, factory, _ = _build_runner()
    for _ in range(10):
        runner.increment_conversation_count("user-1")

    result = await runner.run_if_due("user-1")

    assert result["triggered"] is True
    assert result["success"] is True
    assert result["reason"] == "no_new_memories"

    # 验证计数器已重置
    with factory() as db:
        state = db.query(ConsolidationState).filter(ConsolidationState.user_id == "user-1").first()
        assert state.conversation_count_since_run == 0


# ---------------- watermark 增量读取测试 ----------------


@pytest.mark.asyncio
async def test_watermark_advances_after_consolidation():
    """
    场景：巩固成功后 watermark 推进到最大短期记忆 ID。

    Given 短期记忆 id=1,2,3 已写入，state.last_short_term_memory_id=0
    When 调用 run_if_due(force=True)
    Then 处理 3 条短期记忆
    And state.last_short_term_memory_id = 3
    """
    runner, manager, factory, _ = _build_runner()
    _insert_short_term_memory(factory, "用户喜欢 Python", role="user")
    _insert_short_term_memory(factory, "好的，我帮你处理", role="assistant")
    _insert_short_term_memory(factory, "用户偏好 FastAPI", role="user")

    # 注入提炼回调（无 LLM 提炼回调时巩固失败且不推进 watermark）
    async def extract_callback(messages, user_id):
        return []

    runner.set_extract_callback(extract_callback)

    result = await runner.run_if_due("user-1", force=True)

    assert result["triggered"] is True
    assert result["success"] is True
    assert result["processed"] == 3
    assert result["watermark"] == 3

    with factory() as db:
        state = db.query(ConsolidationState).filter(ConsolidationState.user_id == "user-1").first()
        assert state.last_short_term_memory_id == 3
        assert state.last_run_at is not None


@pytest.mark.asyncio
async def test_watermark_skips_already_processed_memories():
    """
    场景：watermark 已推进的短期记忆不再被读取。

    Given 短期记忆 id=1,2,3,4 已写入，state.last_short_term_memory_id=2
    When 调用 run_if_due(force=True)
    Then 只处理 id=3,4 两条
    And state.last_short_term_memory_id = 4
    """
    runner, manager, factory, _ = _build_runner()
    for i in range(1, 5):
        _insert_short_term_memory(factory, f"消息 {i}", role="user")
    # 手动设置 watermark=2
    with factory() as db:
        state = runner._get_or_create_state_in_session(db, "user-1", "default")
        state.last_short_term_memory_id = 2
        db.commit()

    # 注入提炼回调（无 LLM 提炼回调时巩固失败且不推进 watermark）
    async def extract_callback(messages, user_id):
        return []

    runner.set_extract_callback(extract_callback)

    result = await runner.run_if_due("user-1", force=True)

    assert result["processed"] == 2  # id=3,4
    assert result["watermark"] == 4


# ---------------- fingerprint 跳过测试 ----------------


@pytest.mark.asyncio
async def test_fingerprint_skips_already_processed():
    """
    场景：已处理的短期记忆通过 fingerprint 跳过，不重复 LLM 调用。

    Given 短期记忆 id=1,2,3，其中 id=1,2 的 fingerprint 已存在
    When 调用 run_if_due(force=True)
    Then 只对 id=3 调用 LLM 提炼
    And 持久化 id=3 的 fingerprint
    """
    runner, manager, factory, _ = _build_runner()
    m1 = _insert_short_term_memory(factory, "用户喜欢 Python", role="user")
    m2 = _insert_short_term_memory(factory, "好的，已记录", role="assistant")
    m3 = _insert_short_term_memory(factory, "用户偏好 FastAPI", role="user")
    # 预置 fingerprint：m1 与 m2 已处理
    with factory() as db:
        for memory, _ in [(m1, "fp1"), (m2, "fp2")]:
            db.add(ConsolidationFingerprint(
                user_id="user-1",
                workspace_id="default",
                fingerprint=ConsolidationRunner._compute_fingerprint(memory.content),
                short_term_memory_id=memory.id,
                created_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
            ))
        db.commit()

    extract_called = []

    async def extract_callback(messages, user_id):
        extract_called.append([m["id"] for m in messages])
        return [{"content": "提炼事实", "importance": 0.7, "source_type": "llm_extracted"}]

    runner.set_extract_callback(extract_callback)

    result = await runner.run_if_due("user-1", force=True)

    assert result["success"] is True
    assert result["processed"] == 3  # 读了 3 条
    assert result["skipped"] == 2  # m1, m2 被 fingerprint 跳过
    # extract_callback 仅接收到 m3
    assert extract_called == [[m3.id]]
    # fingerprint 表新增 m3
    with factory() as db:
        fps = db.query(ConsolidationFingerprint).filter(
            ConsolidationFingerprint.user_id == "user-1",
            ConsolidationFingerprint.short_term_memory_id == m3.id,
        ).all()
        assert len(fps) == 1


@pytest.mark.asyncio
async def test_all_fingerprints_present_skips_llm_and_advances_watermark():
    """
    场景：所有短期记忆的 fingerprint 都已存在，跳过 LLM 调用但仍推进 watermark。

    Given 短期记忆 id=1,2，fingerprint 全部已存在
    When 调用 run_if_due(force=True)
    Then extracted=0, consolidated=0
    And watermark 推进到 2
    And 不调用 LLM
    """
    runner, manager, factory, _ = _build_runner()
    m1 = _insert_short_term_memory(factory, "消息 1", role="user")
    m2 = _insert_short_term_memory(factory, "消息 2", role="user")
    # 预置全部 fingerprint
    from datetime import datetime, timezone
    with factory() as db:
        for m in [m1, m2]:
            db.add(ConsolidationFingerprint(
                user_id="user-1",
                workspace_id="default",
                fingerprint=ConsolidationRunner._compute_fingerprint(m.content),
                short_term_memory_id=m.id,
                created_at=datetime.now(timezone.utc),
            ))
        db.commit()

    extract_called = []

    async def extract_callback(messages, user_id):
        extract_called.append(messages)
        return []

    runner.set_extract_callback(extract_callback)

    result = await runner.run_if_due("user-1", force=True)

    assert result["success"] is True
    assert result["processed"] == 2
    assert result["skipped"] == 2
    assert result["extracted"] == 0
    assert result["consolidated"] == 0
    assert result["watermark"] == 2
    # LLM 不应被调用
    assert extract_called == []


# ---------------- LLM 提炼失败处理测试 ----------------


@pytest.mark.asyncio
async def test_llm_extract_failure_does_not_advance_watermark():
    """
    场景：LLM 提炼失败时显式上报失败，watermark 不推进、fingerprint 不持久化。

    Given 短期记忆 id=1,2 + 注入会抛异常的 extract_callback
    When 调用 run_if_due(force=True)
    Then success=False 且 errors 非空（失败显式上报）
    And watermark 不推进（失败批次保留供重试）
    And fingerprint 不持久化（不得误标已处理）
    """
    runner, manager, factory, _ = _build_runner()
    _insert_short_term_memory(factory, "消息 1", role="user")
    _insert_short_term_memory(factory, "消息 2", role="user")

    async def extract_callback(messages, user_id):
        raise RuntimeError("LLM 服务不可用")

    runner.set_extract_callback(extract_callback)

    result = await runner.run_if_due("user-1", force=True)

    assert result["success"] is False
    assert result["errors"], "失败必须显式记录到 errors"
    assert result["extracted"] == 0
    assert result["consolidated"] == 0
    assert result["watermark"] == 0
    # fingerprint 未持久化，失败批次下次重试
    with factory() as db:
        fps = db.query(ConsolidationFingerprint).filter(
            ConsolidationFingerprint.user_id == "user-1",
        ).all()
        assert len(fps) == 0


# ---------------- 巩固提炼结果写入测试 ----------------


@pytest.mark.asyncio
async def test_extracted_items_written_as_long_term_memory():
    """
    场景：LLM 提炼出的事实被写入长期记忆，复用去重逻辑。

    Given 短期记忆 id=1 + extract_callback 返回 [{content="用户偏好 Python", importance=0.8}]
    When 调用 run_if_due(force=True)
    Then 长期记忆表新增 1 条
    And metadata.extracted_from 包含短期记忆 id=1
    And fingerprint 表持久化记录
    """
    # 用正交向量：保证提炼内容不会触发去重命中
    runner, manager, factory, _ = _build_runner(with_constant=False)
    m1 = _insert_short_term_memory(factory, "用户：我喜欢用 Python 写后端", role="user")

    async def extract_callback(messages, user_id):
        return [
            {
                "content": "用户偏好 Python 后端开发",
                "importance": 0.8,
                "source_type": "llm_extracted",
            }
        ]

    runner.set_extract_callback(extract_callback)

    result = await runner.run_if_due("user-1", force=True)

    assert result["success"] is True
    assert result["extracted"] == 1
    assert result["consolidated"] == 1

    with factory() as db:
        long_term = db.query(LongTermMemory).filter(LongTermMemory.user_id == "user-1").all()
        assert len(long_term) == 1
        assert long_term[0].content == "用户偏好 Python 后端开发"
        assert long_term[0].importance == 0.8
        # extracted_from 应包含 m1.id
        extracted_from = long_term[0].extracted_from or []
        assert m1.id in extracted_from


@pytest.mark.asyncio
async def test_invalid_extracted_item_skipped():
    """
    场景：LLM 返回的提炼项中内容过长或为空时跳过。

    Given extract_callback 返回 [{content="", importance=0.5}, {content="x"*600, importance=0.5}, {content="有效内容"}]
    When 调用 run_if_due(force=True)
    Then 只写入 1 条长期记忆
    """
    runner, manager, factory, _ = _build_runner(with_constant=False)
    _insert_short_term_memory(factory, "消息 1", role="user")

    async def extract_callback(messages, user_id):
        return [
            {"content": "", "importance": 0.5},
            {"content": "x" * 600, "importance": 0.5},
            {"content": "有效内容", "importance": 0.7},
        ]

    runner.set_extract_callback(extract_callback)

    result = await runner.run_if_due("user-1", force=True)

    assert result["consolidated"] == 1
    with factory() as db:
        long_term = db.query(LongTermMemory).filter(LongTermMemory.user_id == "user-1").all()
        assert len(long_term) == 1
        assert long_term[0].content == "有效内容"


# ---------------- 失败重试测试 ----------------


@pytest.mark.asyncio
async def test_consolidation_single_add_failure_collected_in_errors():
    """
    场景：单条 add_long_term_memory 失败时收集到结果 errors，不静默跳过。

    Given 短期记忆 id=1,2 + add_long_term_memory 抛异常 + extract_callback 正常返回
    When 调用 run_if_due(force=True)
    Then success=True（提炼成功，整体流程完成）
    And consolidated=0（无成功写入）
    And errors 非空（写入失败显式上报）
    And watermark=2（提炼成功批次正常推进，避免重复 LLM 调用）
    And state.last_error 未记录（不是整体异常）
    """
    runner, manager, factory, _ = _build_runner()
    _insert_short_term_memory(factory, "消息 1", role="user")
    _insert_short_term_memory(factory, "消息 2", role="user")

    # 注入会抛异常的 add_long_term_memory
    async def fake_add(*args, **kwargs):
        raise RuntimeError("DB connection failed")

    with patch.object(manager, "add_long_term_memory", side_effect=fake_add):
        # 但 extract_callback 仍正常返回结果
        async def extract_callback(messages, user_id):
            return [{"content": "有效内容", "importance": 0.7}]

        runner.set_extract_callback(extract_callback)
        result = await runner.run_if_due("user-1", force=True)

    # 单条 add 失败收集到 errors：success=True, consolidated=0, errors 非空
    assert result["success"] is True
    assert result["consolidated"] == 0
    assert result["errors"], "写入失败必须显式收集到 errors"
    assert result["watermark"] == 2  # 提炼成功批次推进 watermark


@pytest.mark.asyncio
async def test_state_recorded_with_last_error_on_critical_failure():
    """
    场景：_consolidate 主流程抛异常时 last_error 被记录。

    Given 短期记忆 id=1,2 + _read_short_term_memories_sync 抛异常
    When 调用 run_if_due(force=True)
    Then success=False, error 非空
    And state.last_error 已记录异常信息
    """
    runner, manager, factory, _ = _build_runner()
    _insert_short_term_memory(factory, "消息 1", role="user")

    # 模拟 _read_short_term_memories_sync 抛异常
    def fake_read(*args, **kwargs):
        raise RuntimeError("DB read failed")

    with patch.object(runner, "_read_short_term_memories_sync", side_effect=fake_read):
        result = await runner.run_if_due("user-1", force=True)

    assert result["success"] is False
    assert "DB read failed" in result["error"]
    with factory() as db:
        state = db.query(ConsolidationState).filter(ConsolidationState.user_id == "user-1").first()
        assert state.last_error is not None
        assert "DB read failed" in state.last_error


# ---------------- 计数器递增测试 ----------------


@pytest.mark.asyncio
async def test_increment_conversation_count_accumulates():
    """
    场景：increment_conversation_count 累加计数。

    Given 新用户 state 不存在
    When 连续调用 increment 3 次
    Then state.conversation_count_since_run = 3
    """
    runner, manager, factory, _ = _build_runner()

    c1 = runner.increment_conversation_count("user-1")
    c2 = runner.increment_conversation_count("user-1")
    c3 = runner.increment_conversation_count("user-1")

    assert c1 == 1
    assert c2 == 2
    assert c3 == 3

    with factory() as db:
        state = db.query(ConsolidationState).filter(ConsolidationState.user_id == "user-1").first()
        assert state.conversation_count_since_run == 3


def test_increment_conversation_count_with_empty_user_returns_zero():
    """
    场景：空 user_id 时返回 0 不创建 state。
    """
    runner, manager, factory, _ = _build_runner()

    result = runner.increment_conversation_count("")

    assert result == 0
    with factory() as db:
        states = db.query(ConsolidationState).all()
        assert len(states) == 0


# ---------------- 归档评估测试（Task 10 联动）----------------


@pytest.mark.asyncio
async def test_low_quality_memory_archived_after_consolidation():
    """
    场景：巩固完成后归档低质量记忆。

    Given state=active 的长期记忆 confidence < 0.2 且 access_count > 20
    When 调用 run_if_due(force=True)
    Then 该记忆 state 变为 archived
    """
    runner, manager, factory, _ = _build_runner()
    # 预置一条低质量长期记忆
    from datetime import datetime, timezone, timedelta
    old_time = datetime.now(timezone.utc) - timedelta(days=5)
    with factory() as db:
        memory = LongTermMemory(
            user_id="user-1",
            workspace_id="default",
            content="低质量记忆",
            importance=0.1,
            confidence=0.1,  # < 0.2
            quality_score=0.05,
            access_count=25,  # > 20
            last_access=old_time,
            archive_status="active",
            state="active",
            memory_metadata={"source_type": "user_input"},
        )
        db.add(memory)
        db.commit()

    result = await runner.run_if_due("user-1", force=True)

    assert result["success"] is True
    assert result["archived"] >= 1
    with factory() as db:
        m = db.query(LongTermMemory).filter(LongTermMemory.user_id == "user-1").first()
        assert m.state == "archived"
        assert m.archive_status == "archived"


@pytest.mark.asyncio
async def test_stale_unimportant_memory_archived():
    """
    场景：30 天未访问且 importance < 0.3 的记忆被归档。
    """
    runner, manager, factory, _ = _build_runner()
    from datetime import datetime, timezone, timedelta
    old_time = datetime.now(timezone.utc) - timedelta(days=45)
    with factory() as db:
        memory = LongTermMemory(
            user_id="user-1",
            workspace_id="default",
            content="过时低重要性记忆",
            importance=0.2,  # < 0.3
            confidence=0.5,
            quality_score=0.4,
            access_count=2,
            last_access=old_time,  # 45 天前
            archive_status="active",
            state="active",
            memory_metadata={"source_type": "user_input"},
        )
        db.add(memory)
        db.commit()

    result = await runner.run_if_due("user-1", force=True)

    assert result["archived"] >= 1
    with factory() as db:
        m = db.query(LongTermMemory).filter(LongTermMemory.user_id == "user-1").first()
        assert m.state == "archived"


@pytest.mark.asyncio
async def test_validated_memory_not_archived():
    """
    场景：state=validated 的记忆不参与归档评估。
    """
    runner, manager, factory, _ = _build_runner()
    from datetime import datetime, timezone, timedelta
    old_time = datetime.now(timezone.utc) - timedelta(days=45)
    with factory() as db:
        memory = LongTermMemory(
            user_id="user-1",
            workspace_id="default",
            content="已确认记忆",
            importance=0.2,
            confidence=0.1,
            quality_score=0.05,
            access_count=25,
            last_access=old_time,
            archive_status="active",
            state="validated",  # 用户已确认，不参与归档
            memory_metadata={"source_type": "user_input"},
        )
        db.add(memory)
        db.commit()

    result = await runner.run_if_due("user-1", force=True)

    assert result["archived"] == 0
    with factory() as db:
        m = db.query(LongTermMemory).filter(LongTermMemory.user_id == "user-1").first()
        assert m.state == "validated"


# ---------------- fingerprint 计算一致性测试 ----------------


def test_compute_fingerprint_is_deterministic():
    """
    场景：相同内容的 fingerprint 一致；多余空白被归一化；大小写不敏感；不同内容 fingerprint 不同。

    归一化策略：``" ".join(content.split()).lower()`` 即按任意空白切分后用单空格连接。
    - 多个连续空格 → 单个空格（"用户\\t喜欢  Python" 与 "用户 喜欢 Python" 同）
    - 前后空格被剥离
    - 大小写不敏感（"用户喜欢 Python" 与 "用户喜欢 PYTHON" 同）
    """
    fp1 = ConsolidationRunner._compute_fingerprint("用户喜欢 Python")
    fp2 = ConsolidationRunner._compute_fingerprint("用户喜欢 Python   ")
    fp3 = ConsolidationRunner._compute_fingerprint("用户喜欢 Python\n")
    fp4 = ConsolidationRunner._compute_fingerprint("用户喜欢 PYTHON")
    fp5 = ConsolidationRunner._compute_fingerprint("完全不同的内容")

    # 同内容前后空白差异：归一化后一致
    assert fp1 == fp2
    assert fp1 == fp3
    # 大小写差异：归一化后一致
    assert fp1 == fp4
    # 不同内容：fingerprint 不同
    assert fp1 != fp5


def test_compute_fingerprint_returns_32_chars():
    """
    场景：fingerprint 长度为 32（SHA-256 截断）。
    """
    fp = ConsolidationRunner._compute_fingerprint("测试内容")
    assert len(fp) == 32


# ---------------- 未注入 callback 测试 ----------------


@pytest.mark.asyncio
async def test_no_callback_reports_failure_and_keeps_watermark():
    """
    场景：未注入 extract_callback 时显式失败，watermark 不推进。

    Given 短期记忆 id=1,2 + 未注入 callback
    When 调用 run_if_due(force=True)
    Then success=False 且 errors 非空（LLM 提炼不可用显式上报）
    And watermark 保持 0（失败批次保留供重试）
    And fingerprint 未持久化
    """
    runner, manager, factory, _ = _build_runner()
    _insert_short_term_memory(factory, "消息 1", role="user")
    _insert_short_term_memory(factory, "消息 2", role="user")

    result = await runner.run_if_due("user-1", force=True)

    assert result["success"] is False
    assert result["errors"], "LLM 提炼不可用必须显式记录"
    assert result["extracted"] == 0
    assert result["consolidated"] == 0
    assert result["watermark"] == 0
    with factory() as db:
        fps = db.query(ConsolidationFingerprint).filter(
            ConsolidationFingerprint.user_id == "user-1",
        ).all()
        assert len(fps) == 0


# ---------------------------------------------------------------------------
# Spec memory-experience-redesign：extract_turn_async 即时提炼
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extract_turn_async_persists_extracted_memories():
    """
    场景：关键词命中后调用 extract_turn_async 即时提炼。

    Given 注入 mock 提炼回调（返回 2 条提炼结果）
    When 调用 extract_turn_async("请记住我喜欢 Python", "好的", "user-1")
    Then 返回 2（写入条数）
    And 长期记忆表存在 2 条提炼内容（不含原文）
    And 每条含 LLM 评估的 importance 与 source_type
    """
    runner, manager, factory, _ = _build_runner(with_constant=False)

    async def _fake_callback(messages, user_id):
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "请记住我喜欢 Python"
        assert messages[1]["role"] == "assistant"
        return [
            {
                "content": "用户喜欢 Python 编程语言",
                "importance": 0.8,
                "source_type": "preference",
                "source_short_term_memory_id": None,
            },
            {
                "content": "用户偏好使用虚拟环境管理依赖",
                "importance": 0.6,
                "source_type": "knowledge",
                "source_short_term_memory_id": None,
            },
        ]

    runner.set_extract_callback(_fake_callback)

    result = await runner.extract_turn_async(
        "请记住我喜欢 Python", "好的", "user-1", "default"
    )

    assert result["persisted"] == 2
    assert result["errors"] == []
    with factory() as db:
        memories = db.query(LongTermMemory).filter(
            LongTermMemory.user_id == "user-1"
        ).all()
        contents = [m.content for m in memories]
        assert "用户喜欢 Python 编程语言" in contents
        assert "用户偏好使用虚拟环境管理依赖" in contents
        # 原文不落库
        assert not any("请记住我喜欢 Python" in c for c in contents)
        memories_by_content = {m.content: m for m in memories}
        assert memories_by_content["用户喜欢 Python 编程语言"].importance == 0.8
        assert memories_by_content["用户喜欢 Python 编程语言"].source_type == "preference"


@pytest.mark.asyncio
async def test_extract_turn_async_failure_propagates():
    """
    场景：LLM 提炼失败（回调抛异常）时异常传播，不产生假成功。

    Given 注入抛异常的 mock 回调
    When 调用 extract_turn_async
    Then 抛出 RuntimeError（由 feedback 后台任务包装显式记录）
    And 长期记忆表为空（原文不落库）
    """
    runner, manager, factory, _ = _build_runner()

    async def _failing_callback(messages, user_id):
        raise RuntimeError("LLM 不可用")

    runner.set_extract_callback(_failing_callback)

    with pytest.raises(RuntimeError, match="LLM 不可用"):
        await runner.extract_turn_async("请记住 X", "好的", "user-1")
    with factory() as db:
        assert db.query(LongTermMemory).filter(
            LongTermMemory.user_id == "user-1"
        ).count() == 0


@pytest.mark.asyncio
async def test_extract_turn_async_without_callback_raises():
    """
    场景：未注入提炼回调时显式抛错。

    Given runner 未 set_extract_callback
    When 调用 extract_turn_async
    Then 抛出 RuntimeError（提炼不可用不得伪装为"无价值内容"）
    """
    runner, manager, factory, _ = _build_runner()

    with pytest.raises(RuntimeError, match="未注入提炼回调"):
        await runner.extract_turn_async("请记住 X", "好的", "user-1")


@pytest.mark.asyncio
async def test_extract_turn_async_empty_result_skips():
    """
    场景：LLM 提炼返回空数组（无高价值内容）时不写入。

    Given 注入返回 [] 的 mock 回调
    When 调用 extract_turn_async
    Then 返回 {"persisted": 0, "errors": []}
    And 长期记忆表为空
    """
    runner, manager, factory, _ = _build_runner()

    async def _empty_callback(messages, user_id):
        return []

    runner.set_extract_callback(_empty_callback)

    result = await runner.extract_turn_async("今天天气不错", "是的", "user-1")

    assert result == {"persisted": 0, "errors": []}
    with factory() as db:
        assert db.query(LongTermMemory).filter(
            LongTermMemory.user_id == "user-1"
        ).count() == 0
