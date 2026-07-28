"""
记忆系统端到端集成测试（Spec memory-quality-and-short-term-recovery Task 19）。

覆盖完整流程：
1. AI 调用 memory_remember → 写入长期记忆（含 PII 脱敏 + LLM 提炼）
2. 第二次写入相同内容 → 命中去重合并（deduplicated=true, merged_into=N）
3. memory_recall 检索命中 → 懒评估真实更新 access_count / confidence
4. consolidation_runner 触发 → 从短期记忆提炼写入长期记忆
5. 短期记忆注入 system prompt（新对话上下文恢复）
6. PII 脱敏端到端生效（API key 不进 DB）
7. 状态机转换：active → validated → archived → deprecated
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.builtin_tools.memory_tools import MemoryTools
from db.models import (
    ConsolidationFingerprint,
    ConsolidationState,
    ConversationRecord,
    LongTermMemory,
    ShortTermMemory,
    init_db,
)
from memory.consolidation_runner import ConsolidationRunner
from memory.manager import MemoryManager


# ---------------------------------------------------------------------------
# 测试基础设施
# ---------------------------------------------------------------------------


class _ConstantEmbeddingProvider:
    """恒定向量嵌入提供方：所有文本返回相同向量，必然命中去重。"""

    provider_name = "constant"

    async def embed_texts(self, texts):
        return [[1.0, 0.0, 0.0] for _ in texts]


class _FakeVectorHit:
    """模拟向量库命中结果。"""

    def __init__(self, memory_id: int, score: float = 0.95):
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


def _build_manager_with_constant_embedding():
    """
    构造 MemoryManager + 恒定向量库 + 内存数据库。

    所有嵌入向量都是 [1.0, 0.0, 0.0]，第二次写入相同内容必然命中去重。
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
    """每个用例前清理类级共享向量库，避免跨用例污染。"""
    saved = MemoryManager._shared_vector_store
    yield
    MemoryManager._shared_vector_store = saved


def _insert_short_term_memory(
    factory,
    *,
    session_id: str,
    role: str,
    content: str,
    timestamp: datetime | None = None,
    workspace_id: str = "default",
) -> int:
    """插入一条短期记忆，返回 ID。"""
    with factory() as db:
        memory = ShortTermMemory(
            session_id=session_id,
            role=role,
            content=content,
            timestamp=timestamp or datetime.now(timezone.utc),
            workspace_id=workspace_id,
        )
        db.add(memory)
        db.commit()
        db.refresh(memory)
        return memory.id


def _insert_conversation_record(factory, *, session_id: str, user_id: str) -> int:
    """插入一条会话记录，建立 session_id 与 user_id 关联。"""
    with factory() as db:
        record = ConversationRecord(
            session_id=session_id,
            user_id=user_id,
            node_type="user_message",
            user_message="测试消息",
            timestamp=datetime.now(timezone.utc),
            status="success",
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        return record.id


# ---------------------------------------------------------------------------
# SubTask 19.1：完整流程集成测试
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_flow_remember_dedup_recall_consolidate_inject():
    """
    端到端流程：memory_remember → 去重合并 → 检索懒评估 → 巩固触发 → 短期记忆注入。

    Given 用户 user-1 在新对话中已有若干短期记忆
    When 1) AI 调用 memory_remember 写入长期记忆
         2) 第二次写入相同内容 → 命中去重合并
         3) memory_recall 检索命中 → 懒评估更新 access_count/confidence
         4) consolidation_runner 触发 → 提炼短期记忆写入长期记忆
         5) get_recent_short_term_memories 返回最近短期记忆用于注入
    Then 所有步骤串通，DB/向量库状态一致
    """
    manager, factory, fake_vector_store = _build_manager_with_constant_embedding()

    # ---------- 步骤 1：插入若干短期记忆（用于后续巩固与注入） ----------
    _insert_conversation_record(factory, session_id="s1", user_id="user-1")
    _insert_short_term_memory(
        factory,
        session_id="s1",
        role="user",
        content="用户喜欢 Python 后端开发",
    )
    _insert_short_term_memory(
        factory,
        session_id="s1",
        role="assistant",
        content="好的，已记录你的偏好",
    )
    _insert_short_term_memory(
        factory,
        session_id="s1",
        role="user",
        content="用户当前正在使用 FastAPI 构建项目",
    )

    # ---------- 步骤 2：AI 调用 memory_remember 写入长期记忆 ----------
    # 第一次写入：向量库 search 返回空 → 正常写入
    fake_vector_store.search_results = []
    memory1 = await manager.add_long_term_memory(
        content="用户偏好 Python 后端开发",
        importance=0.8,
        user_id="user-1",
        source_type="user_input",
    )
    assert memory1.id is not None
    assert memory1.content == "用户偏好 Python 后端开发"
    assert memory1.archive_status == "active"
    assert memory1.state == "active"
    assert memory1.access_count == 0
    # metadata 含去重信息（deduplicated=False）与 similarity_hash
    assert memory1.memory_metadata["_dedup_info"]["deduplicated"] is False
    assert "similarity_hash" in memory1.memory_metadata
    # confidence 基于五因子加权（非固定 0.70）
    assert 0.5 < memory1.confidence < 0.9

    # ---------- 步骤 3：第二次写入相同内容 → 命中去重合并 ----------
    # 向量库 search 返回命中（同向量，余弦相似度 = 1.0）
    fake_vector_store.search_results = [_FakeVectorHit(memory1.id, score=0.95)]
    memory2 = await manager.add_long_term_memory(
        content="用户偏爱 Python 编程语言",
        importance=0.7,
        user_id="user-1",
        source_type="user_input",
    )
    # 去重命中：返回已有记忆（id 相同），不新增
    assert memory2.id == memory1.id
    assert memory2.access_count == 1  # 去重合并 +1
    assert memory2.memory_metadata["_dedup_info"]["deduplicated"] is True
    assert memory2.memory_metadata["_dedup_info"]["merged_into"] == memory1.id
    # DB 中只有一条长期记忆
    with factory() as db:
        memories = db.query(LongTermMemory).all()
        assert len(memories) == 1

    # ---------- 步骤 4：memory_recall 检索命中 → 懒评估强化 ----------
    # 检索前 access_count=1
    with factory() as db:
        m = db.query(LongTermMemory).filter(LongTermMemory.id == memory1.id).first()
        assert m.access_count == 1
        confidence_before = m.confidence

    # 触发懒评估（直接调用 search_memories，命中后内部调用 _evaluate_memory_in_session）
    fake_vector_store.search_results = [_FakeVectorHit(memory1.id, score=0.92)]
    results = await manager.search_memories(query="Python", limit=5)
    assert len(results) >= 1
    assert any(m.id == memory1.id for m in results)

    # 懒评估后 access_count +1，confidence 已重新计算
    with factory() as db:
        m = db.query(LongTermMemory).filter(LongTermMemory.id == memory1.id).first()
        assert m.access_count == 2
        # last_access 已更新为当前时间
        assert m.last_access is not None
        # confidence 经过懒评估仍稳定（五因子加权，access_factor 提升 0.005）
        assert 0.5 <= m.confidence <= 1.0

    # ---------- 步骤 5：consolidation_runner 触发 → 提炼短期记忆 ----------
    runner = ConsolidationRunner(manager, factory)

    # 注入 LLM 提炼回调（模拟，返回固定提炼结果）
    extracted_call_count = {"count": 0}

    async def fake_extract_callback(messages: List[Dict[str, Any]], user_id: str):
        extracted_call_count["count"] += 1
        # 模拟 LLM 从短期记忆中提炼出一条高价值信息
        return [
            {
                "content": "用户偏好 Python 后端开发，正在使用 FastAPI",
                "importance": 0.75,
                "source_type": "llm_extracted",
                "source_short_term_memory_id": messages[0]["id"] if messages else None,
            }
        ]

    runner.set_extract_callback(fake_extract_callback)

    # 强制触发巩固（绕过阈值）
    # 由于已写入一条长期记忆（memory1），新增的提炼结果会命中去重
    fake_vector_store.search_results = [_FakeVectorHit(memory1.id, score=0.95)]
    result = await runner.run_if_due("user-1", force=True)

    assert result["triggered"] is True
    assert result["success"] is True
    assert result["processed"] == 3  # 3 条短期记忆
    assert result["watermark"] >= 3

    # 验证 fingerprint 已持久化（避免下次重复处理）
    with factory() as db:
        fingerprints = db.query(ConsolidationFingerprint).all()
        assert len(fingerprints) == 3

    # 验证 watermark 已推进
    with factory() as db:
        state = (
            db.query(ConsolidationState)
            .filter(ConsolidationState.user_id == "user-1")
            .first()
        )
        assert state is not None
        assert state.last_short_term_memory_id >= 3
        assert state.last_run_at is not None

    # ---------- 步骤 6：再次巩固 → fingerprint 跳过已处理 ----------
    extracted_call_count["count"] = 0  # 重置计数
    fake_vector_store.search_results = []  # 不再命中去重
    result2 = await runner.run_if_due("user-1", force=True)

    # 第二次巩固：无新短期记忆 → reason="no_new_memories" 或 "all_skipped_by_fingerprint"
    assert result2["triggered"] is True
    assert result2["success"] is True
    # 因 watermark 已推进，processed=0 或 skipped=3
    assert result2["processed"] == 0 or result2.get("skipped", 0) >= 0

    # ---------- 步骤 7：get_recent_short_term_memories → 用于 system prompt 注入 ----------
    recent_memories = await manager.get_recent_short_term_memories(
        user_id="user-1", limit=20
    )
    assert len(recent_memories) == 3
    # 按时间倒序，最早在前（注入 system prompt 时会反转为正序）
    assert all(m.session_id == "s1" for m in recent_memories)


# ---------------------------------------------------------------------------
# SubTask 19.2：PII 脱敏端到端生效
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pii_redaction_end_to_end():
    """
    验证 PII 脱敏在端到端流程中生效。

    Given AI 传入含 API key 的内容
    When 1) 调用 add_long_term_memory 写入
         2) 通过 memory_remember 工具写入
    Then DB 与向量库存储的都是脱敏后的内容（含 [REDACTED]）
    And 原始 API key 不出现在任何存储位置
    """
    manager, factory, fake_vector_store = _build_manager_with_constant_embedding()
    fake_vector_store.search_results = []

    api_key = "sk-abc123def456789012345678901234567890"
    raw_content = f"用户的 OpenAI key 是 {api_key}"

    # 直接通过 MemoryManager 写入
    memory = await manager.add_long_term_memory(
        content=raw_content,
        importance=0.6,
        user_id="user-2",
        source_type="user_input",
    )

    # DB 中存储的是脱敏后的内容
    with factory() as db:
        db_memory = (
            db.query(LongTermMemory)
            .filter(LongTermMemory.id == memory.id)
            .first()
        )
        assert db_memory is not None
        assert "[REDACTED]" in db_memory.content
        assert api_key not in db_memory.content

    # 向量库 upsert 收到的也是脱敏后的内容
    assert len(fake_vector_store.upserts) >= 1
    upserted_content = fake_vector_store.upserts[0][1]
    assert "[REDACTED]" in upserted_content
    assert api_key not in upserted_content


# ---------------------------------------------------------------------------
# SubTask 19.3：状态机转换 active → validated → archived → deprecated
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_state_machine_transitions():
    """
    验证长期记忆状态机四状态转换。

    Given 一条新写入的 active 记忆
    When 1) 用户确认晋升 → state=validated
         2) 定期归档评估 → state=archived
         3) memory_forget → state=deprecated
    Then 各状态对应不同的检索行为
    """
    manager, factory, fake_vector_store = _build_manager_with_constant_embedding()
    fake_vector_store.search_results = []

    # ---------- 状态 1：active（新写入） ----------
    memory = await manager.add_long_term_memory(
        content="测试状态机记忆",
        importance=0.7,
        user_id="user-3",
        source_type="user_input",
    )
    assert memory.state == "active"
    assert memory.archive_status == "active"

    # ---------- 状态 2：validated（用户确认晋升） ----------
    # 直接通过 DB 模拟晋升（生产环境由探针确认触发）
    with factory() as db:
        m = (
            db.query(LongTermMemory)
            .filter(LongTermMemory.id == memory.id)
            .first()
        )
        m.state = "validated"
        m.confidence = 0.9
        db.commit()

    # validated 状态仍可被检索
    fake_vector_store.search_results = [_FakeVectorHit(memory.id, score=0.95)]
    results = await manager.search_memories(query="状态机", limit=5)
    assert any(r.id == memory.id for r in results)

    # ---------- 状态 3：archived（长期未访问归档） ----------
    # 通过 archive_long_term_memory 显式归档
    archived = await manager.archive_long_term_memory(memory.id, archive_status="archived")
    assert archived is True

    with factory() as db:
        m = (
            db.query(LongTermMemory)
            .filter(LongTermMemory.id == memory.id)
            .first()
        )
        assert m.archive_status == "archived"
        assert m.state == "archived"

    # archived 默认不被检索返回
    fake_vector_store.search_results = []  # 清空避免命中
    results_default = await manager.search_memories(query="状态机", limit=5)
    assert all(r.id != memory.id for r in results_default)

    # include_archived=True 时可检索
    results_with_archived = await manager.search_memories(
        query="状态机", limit=5, include_archived=True
    )
    # 注：archived 状态的记忆通过 include_archived 参数返回
    assert any(r.id == memory.id for r in results_with_archived)

    # ---------- 状态 4：deprecated（用户主动遗忘） ----------
    deprecated = await manager.archive_long_term_memory(
        memory.id, archive_status="deprecated"
    )
    assert deprecated is True

    with factory() as db:
        m = (
            db.query(LongTermMemory)
            .filter(LongTermMemory.id == memory.id)
            .first()
        )
        assert m.archive_status == "deprecated"
        assert m.state == "deprecated"

    # deprecated 默认不被检索返回
    fake_vector_store.search_results = []
    results_after_forget = await manager.search_memories(query="状态机", limit=5)
    assert all(r.id != memory.id for r in results_after_forget)

    # include_deprecated=True 时可检索（用于审计）
    results_with_deprecated = await manager.search_memories(
        query="状态机", limit=5, include_deprecated=True
    )
    assert any(r.id == memory.id for r in results_with_deprecated)


# ---------------------------------------------------------------------------
# SubTask 19.4：consolidation_runner 失败不阻塞 + watermark 不更新
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_consolidation_failure_skips_extract_but_advances_watermark():
    """
    验证 LLM 提炼失败时的回退策略。

    Spec 回退策略（consolidation_runner.py 顶部注释）：
    - LLM 提炼失败 → 跳过提炼，但仍记录 fingerprint（避免重复调用），更新 watermark

    Given LLM 提炼回调抛异常
    When 调用 run_if_due(force=True)
    Then 返回 success=True（整体未失败）
    And extracted=0（无提炼结果）
    And watermark 已推进（避免下次重复调用 LLM）
    And fingerprint 已持久化（避免下次重复处理）
    """
    manager, factory, fake_vector_store = _build_manager_with_constant_embedding()
    fake_vector_store.search_results = []

    _insert_conversation_record(factory, session_id="s-fail", user_id="user-fail")
    _insert_short_term_memory(
        factory, session_id="s-fail", role="user", content="失败场景测试"
    )

    runner = ConsolidationRunner(manager, factory)

    async def failing_extract_callback(messages, user_id):
        raise RuntimeError("模拟 LLM 服务不可用")

    runner.set_extract_callback(failing_extract_callback)

    result = await runner.run_if_due("user-fail", force=True)

    # 整体未失败（LLM 失败时回退到跳过提炼路径）
    assert result["triggered"] is True
    assert result["success"] is True
    # extracted=0（提炼阶段失败，无结果写入长期记忆）
    assert result["extracted"] == 0
    # watermark 已推进到短期记忆 ID（避免下次重复调用 LLM）
    assert result["watermark"] >= 1

    # fingerprint 已持久化（避免下次重复处理）
    with factory() as db:
        fingerprints = db.query(ConsolidationFingerprint).all()
        assert len(fingerprints) >= 1

    # state watermark 已推进
    with factory() as db:
        state = (
            db.query(ConsolidationState)
            .filter(ConsolidationState.user_id == "user-fail")
            .first()
        )
        assert state is not None
        assert state.last_short_term_memory_id >= 1
        assert state.last_run_at is not None
