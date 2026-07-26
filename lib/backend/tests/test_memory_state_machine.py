"""
长期记忆状态机单元测试（Spec memory-quality-and-short-term-recovery Task 9）。

覆盖四状态转换：
- active（初始状态，可被定期归档评估降级）
- validated（用户确认晋升，confidence 提升至 0.9，不参与归档）
- archived（长期未访问或低质量，不注入 LLM 上下文但 include_archived=true 时可检索）
- deprecated（用户主动遗忘，不注入 LLM 上下文也不被检索返回，数据保留用于审计）

核心规则：
1. memory_forget 工具调用 archive_long_term_memory(memory_id, "deprecated")
   必须同时设置 archive_status="deprecated" 与 state="deprecated"
2. search_memories 默认不返回 deprecated 与 archived 状态的记忆
3. search_memories(include_deprecated=True) 返回 deprecated 状态
4. search_memories(include_archived=True) 返回 archived 状态
5. get_long_term_memories 默认不返回 deprecated 状态
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
    content: str = "测试记忆内容",
    importance: float = 0.7,
    state: str = "active",
    archive_status: str = "active",
    access_count: int = 5,
    last_access_offset_days: int = 1,
    confidence: float = 0.6,
    user_id: str = "user-1",
    memory_id: int | None = None,
) -> int:
    """在 DB 中直接插入一条长期记忆，返回 ID。"""
    last_access = datetime.now(timezone.utc) - timedelta(days=last_access_offset_days)
    with factory() as db:
        memory = LongTermMemory(
            content=content,
            importance=importance,
            embedding=[1.0, 0.0, 0.0],
            user_id=user_id,
            workspace_id="default",
            access_count=access_count,
            last_access=last_access,
            confidence=confidence,
            quality_score=0.5,
            archive_status=archive_status,
            state=state,
            memory_metadata={"source_type": "user_input"},
            memory_layer="semantic",
        )
        if memory_id is not None:
            memory.id = memory_id
        db.add(memory)
        db.commit()
        db.refresh(memory)
        return memory.id


# ---------------------------------------------------------------------------
# SubTask 9.1：archive_long_term_memory 同步设置 state
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_archive_deprecated_sets_both_archive_status_and_state():
    """
    场景：memory_forget 调用 archive_long_term_memory(memory_id, "deprecated")。

    Given DB 中存在一条 state="active" 的记忆
    When 调用 archive_long_term_memory(memory_id, archive_status="deprecated")
    Then archive_status="deprecated" 且 state="deprecated"
    And 向量库 update_memory_metadata 被调用并传入 state="deprecated"
    """
    manager, factory, fake_store = _build_manager()
    memory_id = _insert_memory(factory, state="active", archive_status="active")

    result = await manager.archive_long_term_memory(memory_id, archive_status="deprecated")

    assert result is True
    with factory() as db:
        memory = db.query(LongTermMemory).filter(LongTermMemory.id == memory_id).first()
        assert memory.archive_status == "deprecated"
        # Spec Task 9：state 字段必须同步为 deprecated
        assert memory.state == "deprecated"

    # 向量库元数据同步：应包含 archive_status 与 state 两字段
    assert any(
        mid == memory_id and kwargs.get("state") == "deprecated" and kwargs.get("archive_status") == "deprecated"
        for mid, kwargs in fake_store.metadata_updates
    ), f"向量库应同步 state=deprecated, 实际: {fake_store.metadata_updates}"


@pytest.mark.asyncio
async def test_archive_archived_sets_state_archived():
    """
    场景：批量归档路径调用 archive_long_term_memory(memory_id, "archived")。

    Given DB 中存在一条 state="active" 的记忆
    When 调用 archive_long_term_memory(memory_id, archive_status="archived")
    Then archive_status="archived" 且 state="archived"
    """
    manager, factory, fake_store = _build_manager()
    memory_id = _insert_memory(factory, state="active", archive_status="active")

    result = await manager.archive_long_term_memory(memory_id, archive_status="archived")

    assert result is True
    with factory() as db:
        memory = db.query(LongTermMemory).filter(LongTermMemory.id == memory_id).first()
        assert memory.archive_status == "archived"
        assert memory.state == "archived"


@pytest.mark.asyncio
async def test_archive_idempotent_when_already_in_target_state():
    """
    场景：记忆已是目标状态时，archive_long_term_memory 不重复写入。

    Given DB 中存在一条 state="deprecated" 的记忆
    When 再次调用 archive_long_term_memory(memory_id, "deprecated")
    Then 返回 True，不产生 DB 写入，不产生向量库元数据更新
    """
    manager, factory, fake_store = _build_manager()
    memory_id = _insert_memory(
        factory, state="deprecated", archive_status="deprecated"
    )
    metadata_count_before = len(fake_store.metadata_updates)

    result = await manager.archive_long_term_memory(memory_id, archive_status="deprecated")

    assert result is True
    # 状态已是目标值，不产生新的元数据更新
    assert len(fake_store.metadata_updates) == metadata_count_before


@pytest.mark.asyncio
async def test_archive_nonexistent_memory_returns_false():
    """
    场景：归档不存在的记忆 ID。

    When 调用 archive_long_term_memory(99999, "deprecated")
    Then 返回 False
    """
    manager, _, _ = _build_manager()

    result = await manager.archive_long_term_memory(99999, archive_status="deprecated")

    assert result is False


# ---------------------------------------------------------------------------
# SubTask 9.2 & 9.3：search_memories 默认过滤 deprecated/archived
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_memories_excludes_deprecated_by_default():
    """
    场景：search_memories 默认不返回 deprecated 状态的记忆。

    Given DB 中存在两条相同内容的记忆，一条 state="active"，一条 state="deprecated"
    When 调用 search_memories(query, include_deprecated=False)（默认）
    Then 只返回 active 的那条，deprecated 的被过滤
    """
    manager, factory, fake_store = _build_manager()
    active_id = _insert_memory(
        factory, content="Python 是用户最喜爱的编程语言", state="active"
    )
    _insert_memory(
        factory, content="Python 是用户最喜爱的编程语言", state="deprecated"
    )

    # 强制走关键词检索路径，避免向量库返回
    fake_store.search_results = []
    results = await manager.search_memories(
        query="Python", limit=10, use_vector=False
    )

    ids = [m.id for m in results]
    assert active_id in ids
    assert all(m.state != "deprecated" for m in results), (
        f"deprecated 状态不应被默认返回: {[m.state for m in results]}"
    )


@pytest.mark.asyncio
async def test_search_memories_includes_deprecated_when_flag_true():
    """
    场景：search_memories(include_deprecated=True) 返回 deprecated 状态。

    Given DB 中存在一条 state="deprecated" 的记忆
    When 调用 search_memories(query, include_deprecated=True)
    Then deprecated 的记忆被返回
    """
    manager, factory, fake_store = _build_manager()
    deprecated_id = _insert_memory(
        factory, content="测试 deprecated 检索", state="deprecated"
    )

    fake_store.search_results = []
    results = await manager.search_memories(
        query="deprecated", limit=10, use_vector=False, include_deprecated=True
    )

    ids = [m.id for m in results]
    assert deprecated_id in ids


@pytest.mark.asyncio
async def test_search_memories_excludes_archived_by_default():
    """
    场景：search_memories 默认不返回 archived 状态的记忆。

    Given DB 中存在一条 state="archived" 的记忆
    When 调用 search_memories(query)（默认 include_archived=False）
    Then archived 的记忆被过滤
    """
    manager, factory, fake_store = _build_manager()
    _insert_memory(factory, content="archived 状态的记忆", state="archived")

    fake_store.search_results = []
    results = await manager.search_memories(
        query="archived", limit=10, use_vector=False
    )

    assert all(m.state != "archived" for m in results), (
        f"archived 状态不应被默认返回: {[m.state for m in results]}"
    )


@pytest.mark.asyncio
async def test_search_memories_includes_archived_when_flag_true():
    """
    场景：search_memories(include_archived=True) 返回 archived 状态。

    Given DB 中存在一条 state="archived" 的记忆
    When 调用 search_memories(query, include_archived=True)
    Then archived 的记忆被返回
    """
    manager, factory, fake_store = _build_manager()
    archived_id = _insert_memory(
        factory, content="archived 状态的记忆", state="archived"
    )

    fake_store.search_results = []
    results = await manager.search_memories(
        query="archived", limit=10, use_vector=False, include_archived=True
    )

    ids = [m.id for m in results]
    assert archived_id in ids


@pytest.mark.asyncio
async def test_search_memories_returns_active_and_validated_by_default():
    """
    场景：active 与 validated 状态始终被返回。

    Given DB 中存在一条 active 与一条 validated 状态的记忆
    When 调用 search_memories(query)（默认参数）
    Then 两条都被返回
    """
    manager, factory, fake_store = _build_manager()
    active_id = _insert_memory(
        factory, content="active 状态的记忆内容 unique-active", state="active"
    )
    validated_id = _insert_memory(
        factory, content="validated 状态的记忆内容 unique-validated", state="validated"
    )

    fake_store.search_results = []
    # 关键词检索会同时命中两条
    results = await manager.search_memories(
        query="状态的记忆内容", limit=10, use_vector=False
    )

    ids = [m.id for m in results]
    assert active_id in ids
    assert validated_id in ids


# ---------------------------------------------------------------------------
# SubTask 9.2：get_long_term_memories 默认排除 deprecated
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_long_term_memories_excludes_deprecated_by_default():
    """
    场景：get_long_term_memories 默认不返回 deprecated 状态。

    Given DB 中存在一条 active 与一条 deprecated 状态的记忆
    When 调用 get_long_term_memories(min_importance=0.0)（默认参数）
    Then 只返回 active 的，deprecated 被过滤
    """
    manager, factory, _ = _build_manager()
    active_id = _insert_memory(
        factory, content="active 记忆", state="active", importance=0.8
    )
    deprecated_id = _insert_memory(
        factory, content="deprecated 记忆", state="deprecated", importance=0.8
    )

    results = await manager.get_long_term_memories(min_importance=0.0, limit=50)

    ids = [m.id for m in results]
    assert active_id in ids
    assert deprecated_id not in ids


@pytest.mark.asyncio
async def test_get_long_term_memories_includes_deprecated_when_flag_true():
    """
    场景：get_long_term_memories(include_deprecated=True) 返回 deprecated。

    Given DB 中存在一条 deprecated 状态的记忆
    When 调用 get_long_term_memories(include_deprecated=True)
    Then deprecated 的记忆被返回
    """
    manager, factory, _ = _build_manager()
    deprecated_id = _insert_memory(
        factory, content="deprecated 记忆", state="deprecated", importance=0.8
    )

    results = await manager.get_long_term_memories(
        min_importance=0.0, limit=50, include_deprecated=True
    )

    ids = [m.id for m in results]
    assert deprecated_id in ids


# ---------------------------------------------------------------------------
# SubTask 9.4：四状态转换覆盖
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_state_transition_active_to_deprecated():
    """
    场景：active → deprecated（用户主动遗忘）。

    Given DB 中存在一条 state="active" 的记忆
    When 调用 archive_long_term_memory(memory_id, "deprecated")
    Then state 变为 "deprecated"
    """
    manager, factory, _ = _build_manager()
    memory_id = _insert_memory(factory, state="active")

    await manager.archive_long_term_memory(memory_id, archive_status="deprecated")

    with factory() as db:
        memory = db.query(LongTermMemory).filter(LongTermMemory.id == memory_id).first()
        assert memory.state == "deprecated"


@pytest.mark.asyncio
async def test_state_transition_active_to_archived():
    """
    场景：active → archived（定期归档评估降级）。

    Given DB 中存在一条 state="active" 的记忆
    When 调用 archive_long_term_memory(memory_id, "archived")
    Then state 变为 "archived"
    """
    manager, factory, _ = _build_manager()
    memory_id = _insert_memory(factory, state="active")

    await manager.archive_long_term_memory(memory_id, archive_status="archived")

    with factory() as db:
        memory = db.query(LongTermMemory).filter(LongTermMemory.id == memory_id).first()
        assert memory.state == "archived"


@pytest.mark.asyncio
async def test_state_transition_archived_to_active_via_archive_active():
    """
    场景：archived → active（恢复记忆，archive_status="active" 同步设置 state="active"）。

    Given DB 中存在一条 state="archived" 的记忆
    When 调用 archive_long_term_memory(memory_id, "active")
    Then state 变为 "active"，archive_status 变为 "active"
    """
    manager, factory, _ = _build_manager()
    memory_id = _insert_memory(factory, state="archived", archive_status="archived")

    await manager.archive_long_term_memory(memory_id, archive_status="active")

    with factory() as db:
        memory = db.query(LongTermMemory).filter(LongTermMemory.id == memory_id).first()
        assert memory.state == "active"
        assert memory.archive_status == "active"


@pytest.mark.asyncio
async def test_state_transition_deprecated_to_active_via_archive_active():
    """
    场景：deprecated → active（用户恢复误删记忆）。

    Given DB 中存在一条 state="deprecated" 的记忆
    When 调用 archive_long_term_memory(memory_id, "active")
    Then state 变为 "active"，可重新被检索返回
    """
    manager, factory, _ = _build_manager()
    memory_id = _insert_memory(
        factory, state="deprecated", archive_status="deprecated"
    )

    await manager.archive_long_term_memory(memory_id, archive_status="active")

    with factory() as db:
        memory = db.query(LongTermMemory).filter(LongTermMemory.id == memory_id).first()
        assert memory.state == "active"
        assert memory.archive_status == "active"


# ---------------------------------------------------------------------------
# 工具端测试：memory_forget 工具调用后 state 正确设置
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_memory_forget_tool_sets_state_deprecated(monkeypatch):
    """
    场景：memory_forget 工具调用后，记忆 state 被设为 deprecated。

    Spec memory-quality-and-short-term-recovery Task 9：
    memory_forget 调用 archive_long_term_memory(memory_id, "deprecated")，
    期望 state="deprecated" 与 archive_status="deprecated" 同时被设置。
    """
    from core.builtin_tools.memory_tools import MemoryTools

    # 构造独立 DB 与 manager，避免污染其他测试
    _, factory, _ = _build_manager()
    memory_id = _insert_memory(factory, state="active", archive_status="active")

    # MemoryTools 运行时从 db.models 动态查找工厂，测试必须替换权威命名空间
    import db.models as db_models

    monkeypatch.setattr(db_models, "SessionLocal", factory)
    tools = MemoryTools()
    result = await tools.execute("forget", memory_id=memory_id)

    assert result["success"] is True
    assert result["state"] == "deprecated"
    with factory() as db:
        memory = db.query(LongTermMemory).filter(LongTermMemory.id == memory_id).first()
        assert memory.state == "deprecated"
        assert memory.archive_status == "deprecated"


@pytest.mark.asyncio
async def test_memory_forget_tool_returns_error_for_nonexistent(monkeypatch):
    """
    场景：memory_forget 工具调用不存在的记忆 ID。

    When 调用 execute("forget", memory_id=99999)
    Then 返回 success=False, error 包含"记忆不存在"
    """
    from core.builtin_tools.memory_tools import MemoryTools

    _, factory, _ = _build_manager()
    import db.models as db_models

    monkeypatch.setattr(db_models, "SessionLocal", factory)
    tools = MemoryTools()
    result = await tools.execute("forget", memory_id=99999)

    assert result["success"] is False
    assert "不存在" in result["error"]
