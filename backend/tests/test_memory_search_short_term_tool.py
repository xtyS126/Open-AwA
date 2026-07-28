"""
builtin_memory_search_short_term 工具测试（Spec memory-quality-and-short-term-recovery Task 15）。

覆盖：
- 工具注册（BUILTIN_TOOL_ACTION_MAP / BUILTIN_TOOL_DEFINITIONS）
- MemoryTools.execute(action="search_short_term", ...) 调度
- _search_short_term 工具方法
  - 缺少 query 参数返回错误
  - 正常搜索返回匹配的短期记忆
  - 无匹配时返回空列表
  - session_id 过滤
  - limit 控制
  - LIKE 特殊字符（%、_、\）转义
  - content 截断到 200 字符
  - timestamp ISO 格式
"""

from __future__ import annotations

import sys
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.builtin_tools.manager import (
    BUILTIN_TOOL_ACTION_MAP,
    BUILTIN_TOOL_DEFINITIONS,
)
from core.builtin_tools.memory_tools import MemoryTools
from db.models import ShortTermMemory, init_db
from memory.manager import MemoryManager
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


# ---------------------------------------------------------------------------
# 测试数据库与 MemoryManager 装配
# ---------------------------------------------------------------------------


@contextmanager
def _build_memory_tools():
    """构造 MemoryTools + 内存数据库 + 注入 MemoryManager.SessionLocal。

    通过替换 db.models.SessionLocal 让 MemoryTools 内部的
    `MemoryManager(SessionLocal)` 使用测试库的会话工厂。
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    init_db(bind_engine=engine)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    # 测试用 fake vector store 避免依赖 Qdrant
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

    # 替换共享向量库，避免初始化真实 Qdrant
    saved_vector_store = MemoryManager._shared_vector_store
    MemoryManager._shared_vector_store = _FakeVectorStore()

    # 替换 SessionLocal，让 MemoryTools 内部 `MemoryManager(SessionLocal)`
    # 使用测试库的会话工厂
    import db.models as db_models_module
    saved_session_local = db_models_module.SessionLocal
    db_models_module.SessionLocal = factory

    tools = MemoryTools()

    try:
        yield tools, factory
    finally:
        # 清理：恢复原始 SessionLocal 与共享向量库
        db_models_module.SessionLocal = saved_session_local
        MemoryManager._shared_vector_store = saved_vector_store


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
# 工具注册测试
# ---------------------------------------------------------------------------


def test_action_map_contains_memory_search_short_term():
    """
    场景：BUILTIN_TOOL_ACTION_MAP 必须包含 memory_search_short_term 映射。

    When 检查 BUILTIN_TOOL_ACTION_MAP
    Then 存在 "memory_search_short_term": ("memory_manager", "search_short_term")
    """
    assert "memory_search_short_term" in BUILTIN_TOOL_ACTION_MAP
    assert BUILTIN_TOOL_ACTION_MAP["memory_search_short_term"] == (
        "memory_manager",
        "search_short_term",
    )


def test_tool_definitions_contains_builtin_memory_search_short_term():
    """
    场景：BUILTIN_TOOL_DEFINITIONS 必须包含 builtin_memory_search_short_term 工具定义。

    When 检查 BUILTIN_TOOL_DEFINITIONS
    Then 存在 name="builtin_memory_search_short_term" 的工具
    And parameters 中 query 是必填字段
    And session_id / limit 是可选字段
    """
    tool_def = next(
        (
            t
            for t in BUILTIN_TOOL_DEFINITIONS
            if t.get("function", {}).get("name") == "builtin_memory_search_short_term"
        ),
        None,
    )
    assert tool_def is not None, "builtin_memory_search_short_term 工具未注册"
    func = tool_def["function"]
    assert "短期记忆" in func["description"] or "对话" in func["description"]
    props = func["parameters"]["properties"]
    assert "query" in props
    assert "session_id" in props
    assert "limit" in props
    assert func["parameters"]["required"] == ["query"]


def test_memory_tools_get_tools_includes_search_short_term():
    """
    场景：MemoryTools.get_tools() 必须包含 "search_short_term"。

    When 调用 MemoryTools().get_tools()
    Then 返回列表包含 "search_short_term"
    """
    tools = MemoryTools()
    assert "search_short_term" in tools.get_tools()


# ---------------------------------------------------------------------------
# 工具行为测试
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_short_term_returns_matching_memories():
    """
    场景：搜索包含关键词的短期记忆。

    Given DB 中有 3 条短期记忆（"Python 学习"、"Java 编程"、"Python 实战"）
    When 调用 _search_short_term(query="Python")
    Then 返回 success=True，count=2，包含 "Python 学习" 与 "Python 实战"
    """
    with _build_memory_tools() as (tools, factory):
        _insert_short_term_memory(factory, session_id="s1", role="user", content="Python 学习")
        _insert_short_term_memory(factory, session_id="s1", role="assistant", content="Java 编程")
        _insert_short_term_memory(factory, session_id="s1", role="user", content="Python 实战")

        result = await tools._search_short_term(query="Python")

    assert result["success"] is True
    assert result["count"] == 2
    contents = {m["content"] for m in result["memories"]}
    assert contents == {"Python 学习", "Python 实战"}


@pytest.mark.asyncio
async def test_search_short_term_returns_empty_when_no_match():
    """
    场景：无匹配的短期记忆时返回空列表。

    Given DB 中有 1 条短期记忆 "Python"
    When 调用 _search_short_term(query="Java")
    Then 返回 success=True，count=0，memories 为空列表
    """
    with _build_memory_tools() as (tools, factory):
        _insert_short_term_memory(factory, session_id="s1", role="user", content="Python 学习")

        result = await tools._search_short_term(query="Java")

    assert result["success"] is True
    assert result["count"] == 0
    assert result["memories"] == []


@pytest.mark.asyncio
async def test_search_short_term_requires_query():
    """
    场景：缺少 query 参数返回错误。

    When 调用 _search_short_term(query="")
    Then 返回 success=False，error 包含 "query"
    """
    with _build_memory_tools() as (tools, _factory):
        result = await tools._search_short_term(query="")

    assert result["success"] is False
    assert "query" in result["error"]


@pytest.mark.asyncio
async def test_search_short_term_strips_query_whitespace():
    """
    场景：query 仅包含空白时视为缺失。

    When 调用 _search_short_term(query="   ")
    Then 返回 success=False
    """
    with _build_memory_tools() as (tools, _factory):
        result = await tools._search_short_term(query="   ")

    assert result["success"] is False


@pytest.mark.asyncio
async def test_search_short_term_filters_by_session_id():
    """
    场景：session_id 过滤，只返回指定会话的记忆。

    Given s1 中有 1 条 "Python"，s2 中有 1 条 "Python"
    When 调用 _search_short_term(query="Python", session_id="s1")
    Then 只返回 s1 的 1 条
    """
    with _build_memory_tools() as (tools, factory):
        _insert_short_term_memory(factory, session_id="s1", role="user", content="Python s1")
        _insert_short_term_memory(factory, session_id="s2", role="user", content="Python s2")

        result = await tools._search_short_term(query="Python", session_id="s1")

    assert result["success"] is True
    assert result["count"] == 1
    assert result["memories"][0]["session_id"] == "s1"
    assert result["memories"][0]["content"] == "Python s1"


@pytest.mark.asyncio
async def test_search_short_term_respects_limit():
    """
    场景：limit 控制返回数量。

    Given DB 中有 5 条包含 "Python" 的短期记忆
    When 调用 _search_short_term(query="Python", limit=2)
    Then 返回 success=True，count=2（最新 2 条）
    """
    base_time = datetime.now(timezone.utc)
    with _build_memory_tools() as (tools, factory):
        for i in range(5):
            _insert_short_term_memory(
                factory,
                session_id="s1",
                role="user",
                content=f"Python 消息 {i}",
                timestamp=base_time + timedelta(seconds=i * 10),
            )

        result = await tools._search_short_term(query="Python", limit=2)

    assert result["success"] is True
    assert result["count"] == 2
    # 倒序：最新在前
    assert result["memories"][0]["content"] == "Python 消息 4"
    assert result["memories"][1]["content"] == "Python 消息 3"


@pytest.mark.asyncio
async def test_search_short_term_default_limit_is_10():
    """
    场景：默认 limit=10。

    Given DB 中有 15 条包含 "Python" 的短期记忆
    When 调用 _search_short_term(query="Python")（不传 limit）
    Then 返回 10 条（默认上限）
    """
    base_time = datetime.now(timezone.utc)
    with _build_memory_tools() as (tools, factory):
        for i in range(15):
            _insert_short_term_memory(
                factory,
                session_id="s1",
                role="user",
                content=f"Python 消息 {i}",
                timestamp=base_time + timedelta(seconds=i),
            )

        result = await tools._search_short_term(query="Python")

    assert result["success"] is True
    assert result["count"] == 10


@pytest.mark.asyncio
async def test_search_short_term_caps_limit_to_50():
    """
    场景：limit 超过 50 时被截断为 50。

    When 调用 _search_short_term(query="Python", limit=500)
    Then 返回不超过 50 条
    """
    base_time = datetime.now(timezone.utc)
    with _build_memory_tools() as (tools, factory):
        for i in range(60):
            _insert_short_term_memory(
                factory,
                session_id="s1",
                role="user",
                content=f"Python 消息 {i}",
                timestamp=base_time + timedelta(seconds=i),
            )

        result = await tools._search_short_term(query="Python", limit=500)

    assert result["success"] is True
    assert result["count"] <= 50


@pytest.mark.asyncio
async def test_search_short_term_escapes_like_special_chars():
    """
    场景：query 包含 LIKE 特殊字符（%、_、\\）时不破坏查询。

    Given DB 中有 1 条内容含 "50%_off" 的记忆
    And 1 条干扰项 "abcdefg"（若 % 当通配符会误命中）
    When 调用 _search_short_term(query="50%_off")
    Then 只返回 1 条精确匹配
    """
    with _build_memory_tools() as (tools, factory):
        _insert_short_term_memory(
            factory, session_id="s1", role="user", content="促销码 50%_off 已生效"
        )
        _insert_short_term_memory(
            factory, session_id="s1", role="user", content="另一个无关消息 abcdef"
        )

        result = await tools._search_short_term(query="50%_off")

    assert result["success"] is True
    assert result["count"] == 1
    assert result["memories"][0]["content"] == "促销码 50%_off 已生效"


@pytest.mark.asyncio
async def test_search_short_term_truncates_long_content():
    """
    场景：超长 content 被截断到 200 字符（含 ... 后缀）。

    Given DB 中有 1 条 content 长度为 300 字符的短期记忆
    When 调用 _search_short_term(query="Python")
    Then 返回的 content 不超过 200 字符
    And content 以 "..." 结尾
    """
    long_content = "Python" + "x" * 300
    with _build_memory_tools() as (tools, factory):
        _insert_short_term_memory(
            factory, session_id="s1", role="user", content=long_content
        )

        result = await tools._search_short_term(query="Python")

    assert result["success"] is True
    assert result["count"] == 1
    returned_content = result["memories"][0]["content"]
    assert len(returned_content) == 200
    assert returned_content.endswith("...")


@pytest.mark.asyncio
async def test_search_short_term_returns_iso_timestamp():
    """
    场景：timestamp 字段返回 ISO 格式字符串。

    Given DB 中有 1 条短期记忆，timestamp 为 2026-07-24T10:00:00+00:00
    When 调用 _search_short_term(query="Python")
    Then 返回的 timestamp 是 ISO 格式字符串
    """
    fixed_time = datetime(2026, 7, 24, 10, 0, 0, tzinfo=timezone.utc)
    with _build_memory_tools() as (tools, factory):
        _insert_short_term_memory(
            factory,
            session_id="s1",
            role="user",
            content="Python 学习",
            timestamp=fixed_time,
        )

        result = await tools._search_short_term(query="Python")

    assert result["success"] is True
    timestamp = result["memories"][0]["timestamp"]
    assert isinstance(timestamp, str)
    # ISO 格式应包含日期与时间
    assert "2026-07-24" in timestamp
    assert "10:00:00" in timestamp


@pytest.mark.asyncio
async def test_search_short_term_workspace_isolation():
    """
    场景：workspace_id 隔离，不同 workspace 的记忆互不可见。

    Given workspace=default 有 1 条 "Python"
    And workspace=other 有 1 条 "Python"
    When 调用 _search_short_term(query="Python")（默认 workspace_id="default"）
    Then 只返回 default workspace 的 1 条
    """
    with _build_memory_tools() as (tools, factory):
        _insert_short_term_memory(
            factory, session_id="s1", role="user", content="Python default", workspace_id="default"
        )
        _insert_short_term_memory(
            factory, session_id="s1", role="user", content="Python other", workspace_id="other"
        )

        result = await tools._search_short_term(query="Python")

    assert result["success"] is True
    assert result["count"] == 1
    assert result["memories"][0]["content"] == "Python default"


@pytest.mark.asyncio
async def test_execute_dispatches_search_short_term_action():
    """
    场景：execute(action="search_short_term", ...) 正确调度到 _search_short_term。

    Given DB 中有 1 条 "Python" 短期记忆
    When 调用 tools.execute(action="search_short_term", query="Python")
    Then 返回与直接调用 _search_short_term 一致的结果
    """
    with _build_memory_tools() as (tools, factory):
        _insert_short_term_memory(factory, session_id="s1", role="user", content="Python 学习")

        result = await tools.execute(action="search_short_term", query="Python")

    assert result["success"] is True
    assert result["count"] == 1


@pytest.mark.asyncio
async def test_execute_unknown_action_returns_error():
    """
    场景：execute 收到未知 action 时返回错误。

    When 调用 tools.execute(action="unknown_action")
    Then 返回 success=False，error 包含 "未知"
    """
    with _build_memory_tools() as (tools, _factory):
        result = await tools.execute(action="unknown_action")

    assert result["success"] is False
    assert "未知" in result["error"]
