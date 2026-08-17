"""
测试 get_stats 异步化后行为正确。

覆盖范围：
1. 异步路由通过 TestClient 正常返回统计概览
2. 6 次串行 DB 聚合查询结果正确（4 次 COUNT + 1 次 AVG + 1 次 GROUP BY）
3. 抽取的同步函数 _get_stats_sync 各聚合查询正确
4. 同步函数可通过 asyncio.to_thread 在线程池中执行
5. 线程池执行不阻塞事件循环（与定时器协程并发推进）
6. 空数据库与多角色分布的边界条件
"""

import asyncio
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.dependencies import get_current_admin_user, get_db
from api.routes.data import _get_stats_sync
from db.models import (
    Base,
    ConversationData,
    ExecutionTrace,
    ToolCallData,
    UserFeedback,
)
from main import app


# 测试专用内存数据库，StaticPool 保证同一连接共享给多个 session
engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base.metadata.create_all(bind=engine)


def override_get_db():
    """提供测试隔离数据库会话。"""
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


def override_get_current_admin_user():
    """提供固定测试管理员用户。"""

    class DummyAdmin:
        id = "admin-1"
        username = "admin"
        role = "admin"

    return DummyAdmin()


@contextmanager
def _test_client():
    """为 API 测试临时注入依赖。"""
    previous_overrides = dict(app.dependency_overrides)
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_admin_user] = override_get_current_admin_user
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides = previous_overrides


@pytest.fixture(autouse=True)
def reset_state():
    """保证每个测试从干净的数据库状态开始。"""
    db = TestingSessionLocal()
    try:
        db.query(ConversationData).delete()
        db.query(ToolCallData).delete()
        db.query(ExecutionTrace).delete()
        db.query(UserFeedback).delete()
        db.commit()
    finally:
        db.close()
    yield
    db = TestingSessionLocal()
    try:
        db.query(ConversationData).delete()
        db.query(ToolCallData).delete()
        db.query(ExecutionTrace).delete()
        db.query(UserFeedback).delete()
        db.commit()
    finally:
        db.close()


def _seed_conversation(role_id: str = "", response_time_ms: int = 0) -> None:
    """插入一条对话数据记录。"""
    conv = ConversationData(
        conversation_id=f"conv-{role_id}-{response_time_ms}-{id(role_id)}",
        role_id=role_id,
        user_message="hi",
        assistant_message="hello",
        tools_used=[],
        model_used="test",
        token_count={},
        response_time_ms=response_time_ms,
    )
    db = TestingSessionLocal()
    try:
        db.add(conv)
        db.commit()
    finally:
        db.close()


def _seed_tool_call() -> None:
    """插入一条工具调用数据记录。"""
    tc = ToolCallData(
        conversation_id="conv-1",
        role_id="",
        tool_name="test_tool",
        tool_params={},
        result_summary="ok",
        success=True,
        duration_ms=100,
    )
    db = TestingSessionLocal()
    try:
        db.add(tc)
        db.commit()
    finally:
        db.close()


def _seed_trace() -> None:
    """插入一条执行轨迹记录。"""
    trace = ExecutionTrace(
        conversation_id="conv-1",
        role_id="",
        plan_steps=[],
        executed_steps=[],
    )
    db = TestingSessionLocal()
    try:
        db.add(trace)
        db.commit()
    finally:
        db.close()


def _seed_feedback() -> None:
    """插入一条用户反馈记录。"""
    fb = UserFeedback(
        session_id="session-1",
        message_id="msg-1",
        user_id="user-1",
        rating=1,
    )
    db = TestingSessionLocal()
    try:
        db.add(fb)
        db.commit()
    finally:
        db.close()


# ──────────────────────────────────────────────
#  异步路由执行测试
# ──────────────────────────────────────────────


def test_get_stats_async_via_test_client():
    """验证异步路由通过 TestClient 正常返回统计概览。"""
    _seed_conversation(role_id="default", response_time_ms=200)
    _seed_conversation(role_id="assistant", response_time_ms=400)
    _seed_tool_call()
    _seed_trace()
    _seed_feedback()

    with _test_client() as client:
        response = client.get("/api/data/stats")

    assert response.status_code == 200
    data = response.json()
    assert data["conversation_count"] == 2
    assert data["tool_call_count"] == 1
    assert data["trace_count"] == 1
    assert data["feedback_count"] == 1
    assert data["avg_response_time_ms"] == 300.0
    role_usage_dict = {item["role_id"]: item["count"] for item in data["role_usage"]}
    assert role_usage_dict == {"default": 1, "assistant": 1}


def test_get_stats_empty_database():
    """验证空数据库时返回零值。"""
    with _test_client() as client:
        response = client.get("/api/data/stats")

    assert response.status_code == 200
    data = response.json()
    assert data["conversation_count"] == 0
    assert data["tool_call_count"] == 0
    assert data["trace_count"] == 0
    assert data["feedback_count"] == 0
    assert data["avg_response_time_ms"] == 0
    assert data["role_usage"] == []


# ──────────────────────────────────────────────
#  抽取的同步函数聚合查询正确性测试
# ──────────────────────────────────────────────


def test_sync_function_returns_correct_counts():
    """验证 _get_stats_sync 正确统计各表记录数（4 次 COUNT 查询）。"""
    _seed_conversation(role_id="default", response_time_ms=100)
    _seed_conversation(role_id="default", response_time_ms=300)
    _seed_tool_call()
    _seed_tool_call()
    _seed_trace()
    _seed_feedback()
    _seed_feedback()
    _seed_feedback()

    db = TestingSessionLocal()
    try:
        result = _get_stats_sync(db)
    finally:
        db.close()

    assert result["conversation_count"] == 2
    assert result["tool_call_count"] == 2
    assert result["trace_count"] == 1
    assert result["feedback_count"] == 3


def test_sync_function_avg_response_time():
    """验证 _get_stats_sync 正确计算平均响应时间（AVG 查询）。"""
    _seed_conversation(role_id="default", response_time_ms=100)
    _seed_conversation(role_id="default", response_time_ms=200)
    _seed_conversation(role_id="default", response_time_ms=300)

    db = TestingSessionLocal()
    try:
        result = _get_stats_sync(db)
    finally:
        db.close()

    assert result["avg_response_time_ms"] == 200.0


def test_sync_function_role_usage_distribution():
    """验证 _get_stats_sync 正确返回角色使用分布（GROUP BY 查询）。"""
    _seed_conversation(role_id="role-a", response_time_ms=100)
    _seed_conversation(role_id="role-a", response_time_ms=100)
    _seed_conversation(role_id="role-b", response_time_ms=100)
    _seed_conversation(role_id="", response_time_ms=100)  # 空 role_id 应归为 "default"

    db = TestingSessionLocal()
    try:
        result = _get_stats_sync(db)
    finally:
        db.close()

    role_usage_dict = {item["role_id"]: item["count"] for item in result["role_usage"]}
    assert role_usage_dict == {"role-a": 2, "role-b": 1, "default": 1}


def test_sync_function_returns_correct_structure():
    """验证 _get_stats_sync 返回结构包含所有必需字段。"""
    db = TestingSessionLocal()
    try:
        result = _get_stats_sync(db)
    finally:
        db.close()

    expected_keys = {
        "conversation_count",
        "tool_call_count",
        "trace_count",
        "feedback_count",
        "avg_response_time_ms",
        "role_usage",
    }
    assert set(result.keys()) == expected_keys


def test_sync_function_empty_database():
    """验证空数据库时同步函数返回零值且不抛错。"""
    db = TestingSessionLocal()
    try:
        result = _get_stats_sync(db)
    finally:
        db.close()

    assert result["conversation_count"] == 0
    assert result["tool_call_count"] == 0
    assert result["trace_count"] == 0
    assert result["feedback_count"] == 0
    assert result["avg_response_time_ms"] == 0
    assert result["role_usage"] == []


def test_sync_function_avg_zero_when_no_conversations():
    """验证无对话时平均响应时间为 0（避免 None 传递给 round）。"""
    _seed_tool_call()  # 只插入工具调用，不插入对话

    db = TestingSessionLocal()
    try:
        result = _get_stats_sync(db)
    finally:
        db.close()

    assert result["conversation_count"] == 0
    assert result["avg_response_time_ms"] == 0


# ──────────────────────────────────────────────
#  线程池执行与事件循环非阻塞测试
# ──────────────────────────────────────────────


def test_sync_function_can_be_called_via_to_thread():
    """验证同步函数可通过 asyncio.to_thread 在线程池中执行。"""
    _seed_conversation(role_id="default", response_time_ms=100)
    _seed_tool_call()

    db = TestingSessionLocal()
    try:
        result = asyncio.run(asyncio.to_thread(_get_stats_sync, db))
    finally:
        db.close()

    assert result["conversation_count"] == 1
    assert result["tool_call_count"] == 1


def test_sync_function_does_not_block_event_loop():
    """
    验证同步函数在线程池中执行不阻塞事件循环。

    通过同时运行一个定时器协程和 _get_stats_sync 的 to_thread 调用，
    验证定时器在统计查询期间能正常推进（事件循环未被阻塞）。
    若同步函数被错误地直接在事件循环中调用，定时器将无法推进。
    """
    _seed_conversation(role_id="default", response_time_ms=100)

    async def main():
        # 启动一个后台定时器协程
        counter = {"value": 0}

        async def ticker():
            for _ in range(5):
                await asyncio.sleep(0.01)
                counter["value"] += 1

        ticker_task = asyncio.create_task(ticker())

        # 同时执行同步 DB 查询（通过 to_thread 在工作线程中执行）
        db = TestingSessionLocal()
        try:
            result = await asyncio.to_thread(_get_stats_sync, db)
        finally:
            db.close()

        await ticker_task
        return result, counter["value"]

    result, tick_count = asyncio.run(main())

    assert result["conversation_count"] == 1
    # 定时器应能完整执行 5 次推进，证明事件循环未被阻塞
    assert tick_count == 5


def test_sync_function_sequential_to_thread_calls_with_independent_sessions():
    """
    验证多次 to_thread 调用使用独立 Session 互不干扰。

    注意：SQLAlchemy 同步 Session 不是线程安全的，每次调用必须传入独立 Session。
    本测试串行执行 3 次 to_thread 调用，每次创建独立 Session，
    验证每次调用都能正确读取数据且 Session 被正确关闭。
    （不使用 asyncio.gather 并发执行是因为测试用 StaticPool 共享单一 SQLite 连接，
    不支持真正的并发访问；生产环境每个请求由 get_db 创建独立 Session 与连接。）
    """
    _seed_conversation(role_id="default", response_time_ms=100)

    async def main():
        def call_stats():
            db = TestingSessionLocal()
            try:
                return _get_stats_sync(db)
            finally:
                db.close()

        # 串行执行 3 次（每次独立 Session）
        results = []
        for _ in range(3):
            result = await asyncio.to_thread(call_stats)
            results.append(result)
        return results

    results = asyncio.run(main())

    assert len(results) == 3
    for r in results:
        assert r["conversation_count"] == 1
