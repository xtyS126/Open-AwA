"""
短期记忆 API 路由测试（Spec memory-quality-and-short-term-recovery Task 13 + 14）。

覆盖：
- Task 13 GET /api/memory/short-term
  - 用户隔离（通过 JOIN ConversationRecord 实现 user_id 过滤）
  - session_id 过滤
  - query 关键词模糊匹配
  - limit 控制
  - 按 timestamp 倒序
  - 路由顺序：/short-term 不会被 /short-term/{session_id} 捕获
- Task 14 GET /api/memory/short-term/recent
  - 用户隔离
  - limit 控制
  - 跨 session_id 返回
  - 路由顺序：/short-term/recent 不会被 /short-term/{session_id} 捕获
"""

from __future__ import annotations

import sys
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, List, Optional

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.dependencies import get_current_user, get_db
from api.routes.memory import get_memory_manager
from db.models import (
    ConversationRecord,
    ShortTermMemory,
    init_db,
)
from main import app
from memory.manager import MemoryManager


# ---------------------------------------------------------------------------
# 测试数据库与依赖注入覆盖
# ---------------------------------------------------------------------------

engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
init_db(bind_engine=engine)


def override_get_db():
    """覆盖 get_db 依赖，返回测试用 SessionLocal。"""
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


class _DummyUser:
    """测试用占位用户。"""

    def __init__(self, user_id: str, username: str = "test-user"):
        self.id = user_id
        self.username = username
        self.role = "user"


def override_get_current_user_factory(user_id: str):
    """生成绑定到指定 user_id 的 get_current_user 覆盖函数。"""

    def _override():
        return _DummyUser(user_id=user_id)

    return _override


@contextmanager
def _test_client(user_id: str = "user-1"):
    """
    构造 TestClient，覆盖 db 与 current_user 依赖。

    user_id 决定当前登录用户，便于测试用户隔离场景。
    """
    previous_overrides = dict(app.dependency_overrides)
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user_factory(user_id)
    # 覆盖记忆管理器依赖，确保使用测试库的会话工厂
    app.dependency_overrides[get_memory_manager] = lambda: MemoryManager(TestingSessionLocal)
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides = previous_overrides


# ---------------------------------------------------------------------------
# 数据准备工具
# ---------------------------------------------------------------------------


def _insert_conversation_record(
    *,
    session_id: str,
    user_id: str,
    timestamp: Optional[datetime] = None,
):
    """在 ConversationRecord 表插入一条会话记录，建立 session_id 与 user_id 的关联。"""
    db = TestingSessionLocal()
    try:
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
    finally:
        db.close()


def _insert_short_term_memory(
    *,
    session_id: str,
    role: str,
    content: str,
    timestamp: Optional[datetime] = None,
    workspace_id: str = "default",
):
    """在 ShortTermMemory 表插入一条短期记忆。"""
    db = TestingSessionLocal()
    try:
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
    finally:
        db.close()


def _reset_short_term_state():
    """每个用例前清空短期记忆与会话记录表。"""
    db = TestingSessionLocal()
    try:
        db.query(ShortTermMemory).delete()
        db.query(ConversationRecord).delete()
        db.commit()
    finally:
        db.close()


def setup_function():
    """每个用例前重置状态。"""
    _reset_short_term_state()


def teardown_function():
    """每个用例后再次重置状态。"""
    _reset_short_term_state()


# ---------------------------------------------------------------------------
# Task 13: GET /api/memory/short-term
# ---------------------------------------------------------------------------


def test_list_short_term_memories_returns_user_memories():
    """
    场景：返回当前用户的所有短期记忆（跨 session_id）。

    Given 用户 user-1 在 s1 中有 1 条记忆，在 s2 中有 2 条记忆
    When GET /api/memory/short-term
    Then 返回 3 条记忆，按 timestamp 倒序排列
    """
    base_time = datetime.now(timezone.utc)
    _insert_conversation_record(session_id="s1", user_id="user-1")
    _insert_conversation_record(session_id="s2", user_id="user-1")
    _insert_short_term_memory(
        session_id="s1", role="user", content="s1 消息", timestamp=base_time
    )
    _insert_short_term_memory(
        session_id="s2", role="assistant", content="s2 消息1", timestamp=base_time + timedelta(seconds=10)
    )
    _insert_short_term_memory(
        session_id="s2", role="user", content="s2 消息2", timestamp=base_time + timedelta(seconds=20)
    )

    with _test_client(user_id="user-1") as client:
        response = client.get("/api/memory/short-term")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 3
    # 倒序：最新在前
    assert data[0]["content"] == "s2 消息2"
    assert data[1]["content"] == "s2 消息1"
    assert data[2]["content"] == "s1 消息"


def test_list_short_term_memories_isolates_by_user():
    """
    场景：用户隔离，不返回其他用户的短期记忆。

    Given 用户 user-1 在 s1 中有 1 条记忆
    And 用户 user-2 在 s2 中有 1 条记忆
    When user-1 调用 GET /api/memory/short-term
    Then 只返回 user-1 的 1 条记忆，不包含 user-2 的
    """
    base_time = datetime.now(timezone.utc)
    _insert_conversation_record(session_id="s1", user_id="user-1")
    _insert_conversation_record(session_id="s2", user_id="user-2")
    _insert_short_term_memory(
        session_id="s1", role="user", content="user-1 的消息", timestamp=base_time
    )
    _insert_short_term_memory(
        session_id="s2", role="user", content="user-2 的消息", timestamp=base_time
    )

    with _test_client(user_id="user-1") as client:
        response = client.get("/api/memory/short-term")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["content"] == "user-1 的消息"
    assert data[0]["session_id"] == "s1"


def test_list_short_term_memories_filters_by_session_id():
    """
    场景：session_id 查询参数过滤。

    Given 用户 user-1 在 s1 中有 1 条，在 s2 中有 2 条
    When GET /api/memory/short-term?session_id=s2
    Then 只返回 s2 的 2 条
    """
    base_time = datetime.now(timezone.utc)
    _insert_conversation_record(session_id="s1", user_id="user-1")
    _insert_conversation_record(session_id="s2", user_id="user-1")
    _insert_short_term_memory(
        session_id="s1", role="user", content="s1 消息", timestamp=base_time
    )
    _insert_short_term_memory(
        session_id="s2", role="user", content="s2 消息1", timestamp=base_time + timedelta(seconds=10)
    )
    _insert_short_term_memory(
        session_id="s2", role="assistant", content="s2 消息2", timestamp=base_time + timedelta(seconds=20)
    )

    with _test_client(user_id="user-1") as client:
        response = client.get("/api/memory/short-term?session_id=s2")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    # 所有返回项都属于 s2
    for item in data:
        assert item["session_id"] == "s2"


def test_list_short_term_memories_filters_by_query_keyword():
    """
    场景：query 查询参数按内容关键词模糊匹配。

    Given 用户 user-1 有 3 条记忆，分别包含 "Python"、"Java"、"Python 学习"
    When GET /api/memory/short-term?query=Python
    Then 只返回包含 "Python" 的 2 条
    """
    base_time = datetime.now(timezone.utc)
    _insert_conversation_record(session_id="s1", user_id="user-1")
    _insert_short_term_memory(
        session_id="s1", role="user", content="我喜欢 Python", timestamp=base_time
    )
    _insert_short_term_memory(
        session_id="s1", role="assistant", content="Java 也是不错的选择", timestamp=base_time + timedelta(seconds=10)
    )
    _insert_short_term_memory(
        session_id="s1", role="user", content="Python 学习路径", timestamp=base_time + timedelta(seconds=20)
    )

    with _test_client(user_id="user-1") as client:
        response = client.get("/api/memory/short-term?query=Python")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    # 所有返回项都包含 Python
    for item in data:
        assert "Python" in item["content"]


def test_list_short_term_memories_query_keyword_with_special_chars():
    """
    场景：query 包含 LIKE 特殊字符（%、_、\）时不破坏查询。

    Given 用户有一条内容含 "50%_off" 的记忆
    When GET /api/memory/short-term?query=50%_off
    Then 仍能正确匹配（特殊字符被转义，不触发通配匹配）
    """
    base_time = datetime.now(timezone.utc)
    _insert_conversation_record(session_id="s1", user_id="user-1")
    _insert_short_term_memory(
        session_id="s1", role="user", content="促销码 50%_off 已生效", timestamp=base_time
    )
    # 干扰项：包含通配匹配会误命中
    _insert_short_term_memory(
        session_id="s1", role="user", content="另一条无关消息 abcdef", timestamp=base_time + timedelta(seconds=10)
    )

    with _test_client(user_id="user-1") as client:
        response = client.get("/api/memory/short-term?query=50%_off")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["content"] == "促销码 50%_off 已生效"


def test_list_short_term_memories_respects_limit():
    """
    场景：limit 查询参数控制返回数量。

    Given 用户有 5 条记忆
    When GET /api/memory/short-term?limit=2
    Then 只返回最新 2 条
    """
    base_time = datetime.now(timezone.utc)
    _insert_conversation_record(session_id="s1", user_id="user-1")
    for i in range(5):
        _insert_short_term_memory(
            session_id="s1", role="user", content=f"消息 {i}", timestamp=base_time + timedelta(seconds=i * 10)
        )

    with _test_client(user_id="user-1") as client:
        response = client.get("/api/memory/short-term?limit=2")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    # 最新 2 条
    assert data[0]["content"] == "消息 4"
    assert data[1]["content"] == "消息 3"


def test_list_short_term_memories_limit_default_is_50():
    """
    场景：默认 limit=50，避免一次性返回过多。

    Given 用户有 60 条记忆
    When GET /api/memory/short-term（不传 limit）
    Then 只返回最新 50 条
    """
    base_time = datetime.now(timezone.utc)
    _insert_conversation_record(session_id="s1", user_id="user-1")
    for i in range(60):
        _insert_short_term_memory(
            session_id="s1", role="user", content=f"消息 {i}", timestamp=base_time + timedelta(seconds=i)
        )

    with _test_client(user_id="user-1") as client:
        response = client.get("/api/memory/short-term")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 50


def test_list_short_term_memories_returns_empty_when_no_data():
    """
    场景：用户无任何短期记忆时返回空列表。

    Given 用户 user-new 没有 ConversationRecord 与 ShortTermMemory
    When GET /api/memory/short-term
    Then 返回 200 + 空列表
    """
    with _test_client(user_id="user-new") as client:
        response = client.get("/api/memory/short-term")

    assert response.status_code == 200
    assert response.json() == []


def test_list_short_term_memories_workspace_isolation():
    """
    场景：workspace_id 隔离，不同 workspace 的记忆互不可见。

    Given 用户 user-1 在 workspace=default 有 1 条
    And 用户 user-1 在 workspace=other 有 1 条
    When GET /api/memory/short-term?workspace_id=default
    Then 只返回 workspace=default 的 1 条
    """
    base_time = datetime.now(timezone.utc)
    _insert_conversation_record(session_id="s1", user_id="user-1")
    _insert_short_term_memory(
        session_id="s1", role="user", content="default workspace 消息", timestamp=base_time, workspace_id="default"
    )
    _insert_short_term_memory(
        session_id="s1", role="user", content="other workspace 消息", timestamp=base_time + timedelta(seconds=10), workspace_id="other"
    )

    with _test_client(user_id="user-1") as client:
        response = client.get("/api/memory/short-term?workspace_id=default")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["content"] == "default workspace 消息"


# ---------------------------------------------------------------------------
# Task 14: GET /api/memory/short-term/recent
# ---------------------------------------------------------------------------


def test_recent_short_term_memories_returns_latest_n():
    """
    场景：返回最近 N 条短期记忆（用于新对话上下文恢复）。

    Given 用户 user-1 在 s1 中有 3 条记忆（t1 < t2 < t3）
    When GET /api/memory/short-term/recent?limit=20
    Then 返回 3 条，按 timestamp 倒序排列（t3, t2, t1）
    """
    base_time = datetime.now(timezone.utc)
    _insert_conversation_record(session_id="s1", user_id="user-1")
    _insert_short_term_memory(
        session_id="s1", role="user", content="第一条", timestamp=base_time
    )
    _insert_short_term_memory(
        session_id="s1", role="assistant", content="第二条", timestamp=base_time + timedelta(seconds=10)
    )
    _insert_short_term_memory(
        session_id="s1", role="user", content="第三条", timestamp=base_time + timedelta(seconds=20)
    )

    with _test_client(user_id="user-1") as client:
        response = client.get("/api/memory/short-term/recent?limit=20")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 3
    # 倒序：最新在前
    assert data[0]["content"] == "第三条"
    assert data[1]["content"] == "第二条"
    assert data[2]["content"] == "第一条"


def test_recent_short_term_memories_cross_session():
    """
    场景：跨 session_id 返回最近 N 条。

    Given 用户 user-1 在 s1 中有 1 条记忆（t1）
    And 用户 user-1 在 s2 中有 1 条记忆（t2 > t1）
    When GET /api/memory/short-term/recent
    Then 返回 2 条，按 timestamp 倒序（t2 在前）
    And 包含两个不同的 session_id
    """
    base_time = datetime.now(timezone.utc)
    _insert_conversation_record(session_id="s1", user_id="user-1")
    _insert_conversation_record(session_id="s2", user_id="user-1")
    _insert_short_term_memory(
        session_id="s1", role="user", content="s1 消息", timestamp=base_time
    )
    _insert_short_term_memory(
        session_id="s2", role="user", content="s2 消息", timestamp=base_time + timedelta(seconds=30)
    )

    with _test_client(user_id="user-1") as client:
        response = client.get("/api/memory/short-term/recent")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    # 最新在前
    assert data[0]["content"] == "s2 消息"
    assert data[0]["session_id"] == "s2"
    assert data[1]["content"] == "s1 消息"
    assert data[1]["session_id"] == "s1"


def test_recent_short_term_memories_user_isolation():
    """
    场景：用户隔离，不返回其他用户的短期记忆。

    Given 用户 user-1 在 s1 中有 1 条记忆
    And 用户 user-2 在 s2 中有 1 条记忆
    When user-1 调用 GET /api/memory/short-term/recent
    Then 只返回 user-1 的 1 条记忆
    """
    base_time = datetime.now(timezone.utc)
    _insert_conversation_record(session_id="s1", user_id="user-1")
    _insert_conversation_record(session_id="s2", user_id="user-2")
    _insert_short_term_memory(
        session_id="s1", role="user", content="user-1 消息", timestamp=base_time
    )
    _insert_short_term_memory(
        session_id="s2", role="user", content="user-2 消息", timestamp=base_time + timedelta(seconds=10)
    )

    with _test_client(user_id="user-1") as client:
        response = client.get("/api/memory/short-term/recent")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["content"] == "user-1 消息"
    assert data[0]["session_id"] == "s1"


def test_recent_short_term_memories_respects_limit():
    """
    场景：limit 参数控制返回数量。

    Given 用户有 5 条记忆
    When GET /api/memory/short-term/recent?limit=2
    Then 只返回最新 2 条
    """
    base_time = datetime.now(timezone.utc)
    _insert_conversation_record(session_id="s1", user_id="user-1")
    for i in range(5):
        _insert_short_term_memory(
            session_id="s1", role="user", content=f"消息 {i}", timestamp=base_time + timedelta(seconds=i * 10)
        )

    with _test_client(user_id="user-1") as client:
        response = client.get("/api/memory/short-term/recent?limit=2")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert data[0]["content"] == "消息 4"
    assert data[1]["content"] == "消息 3"


def test_recent_short_term_memories_default_limit_is_20():
    """
    场景：默认 limit=20，符合 spec 中"默认 20"的要求。
    """
    base_time = datetime.now(timezone.utc)
    _insert_conversation_record(session_id="s1", user_id="user-1")
    for i in range(25):
        _insert_short_term_memory(
            session_id="s1", role="user", content=f"消息 {i}", timestamp=base_time + timedelta(seconds=i)
        )

    with _test_client(user_id="user-1") as client:
        response = client.get("/api/memory/short-term/recent")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 20


def test_recent_short_term_memories_returns_empty_when_no_data():
    """
    场景：用户无任何短期记忆时返回空列表。

    Given 用户 user-new 没有 ConversationRecord 与 ShortTermMemory
    When GET /api/memory/short-term/recent
    Then 返回 200 + 空列表
    """
    with _test_client(user_id="user-new") as client:
        response = client.get("/api/memory/short-term/recent")

    assert response.status_code == 200
    assert response.json() == []


# ---------------------------------------------------------------------------
# 路由顺序回归：/short-term/recent 与 /short-term 不被 /short-term/{session_id} 捕获
# ---------------------------------------------------------------------------


def test_recent_route_not_captured_by_session_id_path():
    """
    回归测试：/short-term/recent 必须在 /short-term/{session_id} 之前声明。

    Given 路由顺序正确
    When GET /api/memory/short-term/recent
    Then 路由命中 get_recent_short_term_memories_endpoint（不调用 get_short_term_memory）
    And 返回 200 而非 404/422（若 'recent' 被当作 session_id，会返回 200 但内容为空，而非按 user_id 跨 session 查询）

    验证方式：
    - 创建一条记忆，session_id 为 'recent' 的字符串
    - 调用 /api/memory/short-term/recent 应当通过 user_id JOIN 查询返回该记忆
    - 若被 /short-term/{session_id} 捕获，会按 session_id='recent' 查询 DB（可能返回空或不同结果）
    """
    base_time = datetime.now(timezone.utc)
    # 用户的 session_id 用 'real-session'，确保不会与 'recent' 字符串混淆
    _insert_conversation_record(session_id="real-session", user_id="user-1")
    _insert_short_term_memory(
        session_id="real-session", role="user", content="这条应被 recent 端点返回", timestamp=base_time
    )

    with _test_client(user_id="user-1") as client:
        response = client.get("/api/memory/short-term/recent")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["content"] == "这条应被 recent 端点返回"
    assert data[0]["session_id"] == "real-session"


def test_list_route_not_captured_by_session_id_path():
    """
    回归测试：/short-term（无 path 参数）必须与 /short-term/{session_id} 区分。

    Given 路由顺序正确
    When GET /api/memory/short-term
    Then 路由命中 list_short_term_memories（不调用 get_short_term_memory）
    And 返回所有用户的记忆（跨 session_id），而非按某个 session_id 过滤
    """
    base_time = datetime.now(timezone.utc)
    _insert_conversation_record(session_id="s1", user_id="user-1")
    _insert_conversation_record(session_id="s2", user_id="user-1")
    _insert_short_term_memory(
        session_id="s1", role="user", content="s1 内容", timestamp=base_time
    )
    _insert_short_term_memory(
        session_id="s2", role="user", content="s2 内容", timestamp=base_time + timedelta(seconds=10)
    )

    with _test_client(user_id="user-1") as client:
        response = client.get("/api/memory/short-term")

    assert response.status_code == 200
    data = response.json()
    # 应当返回所有 session_id 的记忆（list 端点行为）
    session_ids = {item["session_id"] for item in data}
    assert session_ids == {"s1", "s2"}
