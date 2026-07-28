"""
短期记忆 recent 查询单元测试（Spec memory-quality-and-short-term-recovery Task 11）。

覆盖：
- 按 user_id 过滤（通过 JOIN ConversationRecord 关联 session_id）
- 按 timestamp 倒序返回最近 N 条
- limit 限制
- workspace_id 隔离
- user_id 为空时抛 ValueError
- 跨 session_id 检索（用户的所有会话历史都参与）
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

from db.models import (
    ConversationRecord,
    ShortTermMemory,
    init_db,
)
from memory.manager import MemoryManager


def _build_manager():
    """构造 MemoryManager + 内存数据库。"""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    init_db(bind_engine=engine)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    # 短期记忆 recent 查询不依赖向量库，但 MemoryManager 初始化会创建共享向量库
    # 用一个最小的 fake 避免依赖 Qdrant
    class _FakeVectorStore:
        provider_name = "fake"
        embedding_provider = None

        async def search(self, *args, **kwargs):
            return []

        async def upsert_memory(self, *args, **kwargs):
            pass

        def update_memory_metadata(self, *args, **kwargs):
            pass

        def delete_memory(self, *args, **kwargs):
            pass

        def count(self, **kwargs):
            return 0

        def close(self):
            pass

    MemoryManager._shared_vector_store = _FakeVectorStore()
    manager = MemoryManager(factory)
    return manager, factory


@pytest.fixture(autouse=True)
def _reset_shared_vector_store():
    """每个用例前清理类级共享向量库。"""
    saved = MemoryManager._shared_vector_store
    yield
    MemoryManager._shared_vector_store = saved


def _insert_conversation_record(factory, *, session_id: str, user_id: str, timestamp=None):
    """在 ConversationRecord 表插入一条会话记录，建立 session_id 与 user_id 的关联。"""
    with factory() as db:
        record = ConversationRecord(
            session_id=session_id,
            user_id=user_id,
            node_type="user_message",
            user_message="测试消息",
            timestamp=timestamp or datetime.now(timezone.utc),
            status="success",
        )
        db.add(record)
        db.commit()
        return record.id


def _insert_short_term_memory(
    factory,
    *,
    session_id: str,
    role: str,
    content: str,
    timestamp=None,
    workspace_id: str = "default",
):
    """在 ShortTermMemory 表插入一条短期记忆。"""
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


# ---------------------------------------------------------------------------
# SubTask 11.1 & 11.2：基础查询与排序
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_returns_recent_short_term_memories_ordered_by_timestamp_desc():
    """
    场景：按 timestamp 倒序返回最近 N 条短期记忆。

    Given 用户 user-1 在 session-1 中有 3 条短期记忆（t1 < t2 < t3）
    When 调用 get_recent_short_term_memories(user_id="user-1", limit=20)
    Then 返回 3 条，按 timestamp 倒序排列（t3, t2, t1）
    """
    manager, factory = _build_manager()
    _insert_conversation_record(factory, session_id="s1", user_id="user-1")

    base_time = datetime.now(timezone.utc)
    _insert_short_term_memory(
        factory,
        session_id="s1",
        role="user",
        content="第一条消息",
        timestamp=base_time,
    )
    _insert_short_term_memory(
        factory,
        session_id="s1",
        role="assistant",
        content="第二条消息",
        timestamp=base_time + timedelta(seconds=10),
    )
    _insert_short_term_memory(
        factory,
        session_id="s1",
        role="user",
        content="第三条消息",
        timestamp=base_time + timedelta(seconds=20),
    )

    results = await manager.get_recent_short_term_memories(user_id="user-1", limit=20)

    assert len(results) == 3
    # 倒序：最新在前
    assert results[0].content == "第三条消息"
    assert results[1].content == "第二条消息"
    assert results[2].content == "第一条消息"


@pytest.mark.asyncio
async def test_limit_caps_result_count():
    """
    场景：limit 参数限制返回条数。

    Given 用户有 5 条短期记忆
    When 调用 get_recent_short_term_memories(user_id="user-1", limit=2)
    Then 只返回最新 2 条
    """
    manager, factory = _build_manager()
    _insert_conversation_record(factory, session_id="s1", user_id="user-1")

    base_time = datetime.now(timezone.utc)
    for i in range(5):
        _insert_short_term_memory(
            factory,
            session_id="s1",
            role="user",
            content=f"消息 {i}",
            timestamp=base_time + timedelta(seconds=i * 10),
        )

    results = await manager.get_recent_short_term_memories(user_id="user-1", limit=2)

    assert len(results) == 2
    # 最新 2 条
    assert results[0].content == "消息 4"
    assert results[1].content == "消息 3"


@pytest.mark.asyncio
async def test_limit_exceeds_max_is_capped_to_100():
    """
    场景：limit 超过 100 时被截断为 100。

    When 调用 get_recent_short_term_memories(user_id="user-1", limit=500)
    Then SQL 查询的 LIMIT 被截断为 100（避免一次性返回过多数据）
    """
    manager, factory = _build_manager()
    _insert_conversation_record(factory, session_id="s1", user_id="user-1")
    _insert_short_term_memory(
        factory, session_id="s1", role="user", content="单条"
    )

    # limit=500 应被截断为 100，不抛异常
    results = await manager.get_recent_short_term_memories(user_id="user-1", limit=500)
    assert len(results) == 1  # DB 中只有 1 条


@pytest.mark.asyncio
async def test_returns_empty_when_no_short_term_memories():
    """
    场景：用户没有任何短期记忆时返回空列表。

    Given 用户 user-new 没有任何 ConversationRecord 与 ShortTermMemory
    When 调用 get_recent_short_term_memories(user_id="user-new")
    Then 返回空列表
    """
    manager, _ = _build_manager()

    results = await manager.get_recent_short_term_memories(user_id="user-new")

    assert results == []


@pytest.mark.asyncio
async def test_user_id_isolation():
    """
    场景：用户隔离，不返回其他用户的短期记忆。

    Given user-1 在 s1 中有 2 条短期记忆
    And user-2 在 s2 中有 3 条短期记忆
    When 调用 get_recent_short_term_memories(user_id="user-1")
    Then 只返回 user-1 的 2 条，不包含 user-2 的
    """
    manager, factory = _build_manager()
    _insert_conversation_record(factory, session_id="s1", user_id="user-1")
    _insert_conversation_record(factory, session_id="s2", user_id="user-2")

    _insert_short_term_memory(factory, session_id="s1", role="user", content="user-1 msg1")
    _insert_short_term_memory(factory, session_id="s1", role="assistant", content="user-1 msg2")
    _insert_short_term_memory(factory, session_id="s2", role="user", content="user-2 msg1")
    _insert_short_term_memory(factory, session_id="s2", role="assistant", content="user-2 msg2")
    _insert_short_term_memory(factory, session_id="s2", role="user", content="user-2 msg3")

    user1_results = await manager.get_recent_short_term_memories(user_id="user-1")
    user2_results = await manager.get_recent_short_term_memories(user_id="user-2")

    assert len(user1_results) == 2
    assert all(m.content.startswith("user-1") for m in user1_results)
    assert len(user2_results) == 3
    assert all(m.content.startswith("user-2") for m in user2_results)


@pytest.mark.asyncio
async def test_cross_session_retrieval():
    """
    场景：跨 session_id 检索用户的所有短期记忆。

    Given 用户 user-1 在 s1 中有 1 条短期记忆（t1）
    And 用户 user-1 在 s2 中有 1 条短期记忆（t2 > t1）
    When 调用 get_recent_short_term_memories(user_id="user-1")
    Then 返回 2 条，按时间倒序（t2, t1），跨 session_id
    """
    manager, factory = _build_manager()
    _insert_conversation_record(factory, session_id="s1", user_id="user-1")
    _insert_conversation_record(factory, session_id="s2", user_id="user-1")

    base_time = datetime.now(timezone.utc)
    _insert_short_term_memory(
        factory,
        session_id="s1",
        role="user",
        content="s1 的消息（较早）",
        timestamp=base_time,
    )
    _insert_short_term_memory(
        factory,
        session_id="s2",
        role="user",
        content="s2 的消息（较晚）",
        timestamp=base_time + timedelta(seconds=30),
    )

    results = await manager.get_recent_short_term_memories(user_id="user-1")

    assert len(results) == 2
    # 最新在前：s2 的消息先返回
    assert results[0].content == "s2 的消息（较晚）"
    assert results[0].session_id == "s2"
    assert results[1].content == "s1 的消息（较早）"
    assert results[1].session_id == "s1"


@pytest.mark.asyncio
async def test_workspace_isolation():
    """
    场景：workspace_id 隔离。

    Given workspace=default 中用户 user-1 有 1 条短期记忆
    And workspace=other 中用户 user-1 有 1 条短期记忆
    When 调用 get_recent_short_term_memories(user_id="user-1", workspace_id="default")
    Then 只返回 workspace=default 的 1 条
    """
    manager, factory = _build_manager()
    _insert_conversation_record(factory, session_id="s1", user_id="user-1")

    _insert_short_term_memory(
        factory,
        session_id="s1",
        role="user",
        content="default workspace 消息",
        workspace_id="default",
    )
    _insert_short_term_memory(
        factory,
        session_id="s1",
        role="user",
        content="other workspace 消息",
        workspace_id="other",
    )

    results = await manager.get_recent_short_term_memories(
        user_id="user-1", workspace_id="default"
    )

    assert len(results) == 1
    assert results[0].content == "default workspace 消息"


# ---------------------------------------------------------------------------
# 异常路径
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_raises_value_error_when_user_id_is_empty():
    """
    场景：user_id 为空时抛 ValueError。

    When 调用 get_recent_short_term_memories(user_id="")
    Then 抛 ValueError
    """
    manager, _ = _build_manager()

    with pytest.raises(ValueError, match="user_id is required"):
        await manager.get_recent_short_term_memories(user_id="")


@pytest.mark.asyncio
async def test_returns_empty_when_user_has_no_conversation_records():
    """
    场景：用户没有 ConversationRecord（即从未发送过消息），但有 ShortTermMemory（理论上不应发生）。

    Given ShortTermMemory 中存在 session_id=s1 的记忆，但 ConversationRecord 中没有 user-1 关联 s1 的记录
    When 调用 get_recent_short_term_memories(user_id="user-1")
    Then 返回空列表（JOIN 失败，无法关联）
    """
    manager, factory = _build_manager()
    # 不创建 ConversationRecord，但创建 ShortTermMemory
    _insert_short_term_memory(factory, session_id="s1", role="user", content="孤儿消息")

    results = await manager.get_recent_short_term_memories(user_id="user-1")

    assert results == []


# ---------------------------------------------------------------------------
# 边界场景：role 与 timestamp 完整字段
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_result_includes_all_relevant_fields():
    """
    场景：返回结果包含 id / session_id / role / content / timestamp 等所有字段。

    Given 用户 user-1 在 s1 中有 1 条短期记忆
    When 调用 get_recent_short_term_memories(user_id="user-1")
    Then 返回结果包含 id, session_id, role, content, timestamp 字段
    """
    manager, factory = _build_manager()
    _insert_conversation_record(factory, session_id="s1", user_id="user-1")
    base_time = datetime.now(timezone.utc)
    _insert_short_term_memory(
        factory,
        session_id="s1",
        role="user",
        content="测试字段完整性",
        timestamp=base_time,
    )

    results = await manager.get_recent_short_term_memories(user_id="user-1")

    assert len(results) == 1
    memory = results[0]
    assert memory.id is not None
    assert memory.session_id == "s1"
    assert memory.role == "user"
    assert memory.content == "测试字段完整性"
    assert memory.timestamp is not None
