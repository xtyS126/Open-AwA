"""
测试 get_plugin_rating 异步化与 SQL 合并后行为正确。

覆盖范围：
1. 异步路由通过 TestClient 正常返回评分汇总
2. COUNT + AVG 合并查询结果正确（原 2 次查询合并为 1 次）
3. GROUP BY 评分分布查询正确
4. 当前用户评分查询正确
5. 同步函数可通过 asyncio.to_thread 在线程池中执行
6. 1-5 星所有评分都能被正确统计
7. 空数据集与用户未评分场景的边界条件
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

from api.dependencies import get_current_user, get_db
from api.routes.marketplace import _get_plugin_rating_sync
from db.models import Base, Plugin, PluginRating
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


def override_get_current_user():
    """提供固定测试用户（id=user-1）。"""

    class DummyUser:
        id = "user-1"
        username = "testuser"

    return DummyUser()


@contextmanager
def _test_client():
    """为 API 测试临时注入依赖。"""
    previous_overrides = dict(app.dependency_overrides)
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
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
        db.query(PluginRating).delete()
        db.query(Plugin).delete()
        db.commit()
    finally:
        db.close()
    yield
    db = TestingSessionLocal()
    try:
        db.query(PluginRating).delete()
        db.query(Plugin).delete()
        db.commit()
    finally:
        db.close()


def _seed_rating(plugin_id: str, user_id: str, score: int) -> None:
    """插入一条插件评分记录。"""
    rating = PluginRating(plugin_id=plugin_id, user_id=user_id, score=score)
    db = TestingSessionLocal()
    try:
        db.add(rating)
        db.commit()
    finally:
        db.close()


# ──────────────────────────────────────────────
#  异步路由执行测试
# ──────────────────────────────────────────────


def test_get_plugin_rating_async_via_test_client():
    """验证异步路由通过 TestClient 正常返回评分汇总。"""
    _seed_rating("plugin-A", "user-1", 5)
    _seed_rating("plugin-A", "user-2", 3)
    _seed_rating("plugin-A", "user-3", 4)

    with _test_client() as client:
        response = client.get("/api/marketplace/plugins/plugin-A/rating")

    assert response.status_code == 200
    data = response.json()
    assert data["plugin_id"] == "plugin-A"
    assert data["total_count"] == 3
    assert data["average_score"] == round((5 + 3 + 4) / 3, 2)
    # JSON 序列化会把 dict 的 int 键转为 string
    assert data["distribution"] == {"1": 0, "2": 0, "3": 1, "4": 1, "5": 1}
    assert data["user_score"] == 5  # user-1 的评分


def test_get_plugin_rating_no_ratings():
    """验证无评分时返回零值。"""
    with _test_client() as client:
        response = client.get("/api/marketplace/plugins/plugin-empty/rating")

    assert response.status_code == 200
    data = response.json()
    assert data["total_count"] == 0
    assert data["average_score"] == 0.0
    # JSON 序列化会把 dict 的 int 键转为 string
    assert data["distribution"] == {"1": 0, "2": 0, "3": 0, "4": 0, "5": 0}
    assert data["user_score"] is None


def test_get_plugin_rating_user_not_rated():
    """验证当前用户未评分时 user_score 为 None。"""
    _seed_rating("plugin-B", "user-2", 4)
    _seed_rating("plugin-B", "user-3", 2)

    with _test_client() as client:
        response = client.get("/api/marketplace/plugins/plugin-B/rating")

    assert response.status_code == 200
    data = response.json()
    assert data["total_count"] == 2
    assert data["user_score"] is None


# ──────────────────────────────────────────────
#  SQL 合并查询正确性测试
# ──────────────────────────────────────────────


def test_sync_function_count_avg_merged_query():
    """验证 COUNT + AVG 合并查询结果与原串行查询一致。"""
    _seed_rating("plugin-X", "user-a", 5)
    _seed_rating("plugin-X", "user-b", 3)
    _seed_rating("plugin-X", "user-c", 5)
    _seed_rating("plugin-X", "user-d", 1)

    db = TestingSessionLocal()
    try:
        result = _get_plugin_rating_sync(db, "plugin-X", "user-1")
    finally:
        db.close()

    assert result["plugin_id"] == "plugin-X"
    assert result["total_count"] == 4
    assert result["average_score"] == round((5 + 3 + 5 + 1) / 4, 2)


def test_sync_function_distribution_group_by():
    """验证 GROUP BY 评分分布查询正确。"""
    _seed_rating("plugin-Y", "user-a", 5)
    _seed_rating("plugin-Y", "user-b", 5)
    _seed_rating("plugin-Y", "user-c", 3)
    _seed_rating("plugin-Y", "user-d", 3)
    _seed_rating("plugin-Y", "user-e", 3)
    _seed_rating("plugin-Y", "user-f", 1)

    db = TestingSessionLocal()
    try:
        result = _get_plugin_rating_sync(db, "plugin-Y", "user-1")
    finally:
        db.close()

    assert result["distribution"] == {1: 1, 2: 0, 3: 3, 4: 0, 5: 2}


def test_sync_function_user_rating_query():
    """验证当前用户评分查询正确。"""
    _seed_rating("plugin-Z", "user-1", 4)
    _seed_rating("plugin-Z", "user-2", 2)

    db = TestingSessionLocal()
    try:
        result = _get_plugin_rating_sync(db, "plugin-Z", "user-1")
    finally:
        db.close()

    assert result["user_score"] == 4


def test_sync_function_user_rating_none_when_not_rated():
    """验证用户未评分时 user_score 为 None。"""
    _seed_rating("plugin-W", "user-2", 5)

    db = TestingSessionLocal()
    try:
        result = _get_plugin_rating_sync(db, "plugin-W", "user-1")
    finally:
        db.close()

    assert result["user_score"] is None


def test_sync_function_returns_correct_structure():
    """验证同步函数返回结构包含所有必需字段。"""
    _seed_rating("plugin-S", "user-1", 5)

    db = TestingSessionLocal()
    try:
        result = _get_plugin_rating_sync(db, "plugin-S", "user-1")
    finally:
        db.close()

    expected_keys = {"plugin_id", "average_score", "total_count", "distribution", "user_score"}
    assert set(result.keys()) == expected_keys


def test_sync_function_handles_all_five_star_scores():
    """验证 1-5 星所有评分都能被正确统计。"""
    for i, score in enumerate([1, 2, 3, 4, 5], start=1):
        _seed_rating("plugin-Full", f"user-{i}", score)

    db = TestingSessionLocal()
    try:
        result = _get_plugin_rating_sync(db, "plugin-Full", "user-1")
    finally:
        db.close()

    assert result["total_count"] == 5
    assert result["average_score"] == round(3.0, 2)
    assert result["distribution"] == {1: 1, 2: 1, 3: 1, 4: 1, 5: 1}
    assert result["user_score"] == 1


def test_sync_function_isolates_plugins():
    """验证不同插件的评分互不干扰。"""
    _seed_rating("plugin-1", "user-a", 5)
    _seed_rating("plugin-2", "user-a", 1)
    _seed_rating("plugin-2", "user-b", 2)

    db = TestingSessionLocal()
    try:
        result_1 = _get_plugin_rating_sync(db, "plugin-1", "user-1")
        result_2 = _get_plugin_rating_sync(db, "plugin-2", "user-1")
    finally:
        db.close()

    assert result_1["total_count"] == 1
    assert result_1["average_score"] == 5.0
    assert result_2["total_count"] == 2
    assert result_2["average_score"] == round((1 + 2) / 2, 2)


def test_sync_function_can_be_called_via_to_thread():
    """验证同步函数可通过 asyncio.to_thread 在线程池中执行。"""
    _seed_rating("plugin-T", "user-1", 5)
    _seed_rating("plugin-T", "user-2", 3)

    db = TestingSessionLocal()
    try:
        result = asyncio.run(
            asyncio.to_thread(_get_plugin_rating_sync, db, "plugin-T", "user-1")
        )
    finally:
        db.close()

    assert result["total_count"] == 2
    assert result["user_score"] == 5


def test_sync_function_empty_plugin():
    """验证无评分的插件返回零值且不抛错。"""
    db = TestingSessionLocal()
    try:
        result = _get_plugin_rating_sync(db, "plugin-Empty", "user-1")
    finally:
        db.close()

    assert result["total_count"] == 0
    assert result["average_score"] == 0.0
    assert result["distribution"] == {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    assert result["user_score"] is None
