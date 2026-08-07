"""
记忆体验重设计 API 路由测试（Spec memory-experience-redesign）。

覆盖：
- POST /api/memory/long-term/{id}/validate：用户"准确"验证闭环（validated 晋升）
- POST /api/memory/long-term/{id}/deprecate：用户"不准确"主动遗忘（deprecated）
- GET /api/memory/long-term：响应暴露 source_type / memory_layer / state 字段
- POST /api/memory/consolidation/run：手动触发巩固（LLM 配置缺失时不抛 500）
- 所有权校验：他人记忆返回 403
"""

from __future__ import annotations

import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import pytest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.dependencies import get_current_user, get_db
from api.routes.memory import get_memory_manager
from db.models import LongTermMemory, init_db
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


class _ConstantEmbeddingProvider:
    """恒定向量嵌入提供方，避免测试触发真实嵌入调用。"""

    provider_name = "constant"

    async def embed_texts(self, texts):
        return [[1.0, 0.0, 0.0] for _ in texts]


class _FakeVectorStore:
    """假向量库：search 空结果 + 记录元数据更新。"""

    def __init__(self):
        self.embedding_provider = _ConstantEmbeddingProvider()
        self.provider_name = "constant"
        self.search_results: list = []
        self.metadata_updates: list = []
        self.upserts: list = []

    async def upsert_memory(self, memory_id, content, **kwargs):
        self.upserts.append((memory_id, content, kwargs))

    def update_memory_metadata(self, memory_id, **kwargs):
        self.metadata_updates.append((memory_id, kwargs))

    async def search(self, *args, **kwargs):
        return list(self.search_results)

    def delete_memory(self, memory_id):
        pass

    def count(self, **kwargs):
        return 0

    def close(self):
        pass


fake_vector_store = _FakeVectorStore()
MemoryManager._shared_vector_store = fake_vector_store


@pytest.fixture(autouse=True)
def _rearm_fake_vector_store():
    """
    每个用例前重装假向量库。

    conftest 的 teardown/setup 会在用例之间把 MemoryManager._shared_vector_store
    清空（强制下个用例重建真实 VectorStoreManager）；若本文件用例未在启动 TestClient
    前重装假向量库，lifespan 预热会构造真实 Qdrant 存储，而测试仅向 DB 插入记忆行
    （无向量 point），fail-closed 的 update_memory_metadata 会抛 KeyError 使用例 500。
    """
    MemoryManager._shared_vector_store = fake_vector_store
    yield


def override_get_db():
    """覆盖 get_db 依赖，返回测试用 SessionLocal。"""
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


class _DummyUser:
    """测试用占位用户。"""

    def __init__(self, user_id: str):
        self.id = user_id
        self.username = "test-user"
        self.role = "user"


def override_get_current_user_factory(user_id: str):
    """生成绑定到指定 user_id 的 get_current_user 覆盖函数。"""

    def _override():
        return _DummyUser(user_id=user_id)

    return _override


@contextmanager
def _test_client(user_id: str = "user-1", *, raise_server_exceptions: bool = True):
    """构造 TestClient，覆盖 db / current_user / memory_manager 依赖。

    raise_server_exceptions=False 用于断言未捕获异常被转换为 500 响应的用例
    （ServerErrorMiddleware 处理后会主动 re-raise 供服务器日志记录）。
    """
    previous_overrides = dict(app.dependency_overrides)
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user_factory(user_id)
    app.dependency_overrides[get_memory_manager] = lambda: MemoryManager(TestingSessionLocal)
    try:
        with TestClient(app, raise_server_exceptions=raise_server_exceptions) as client:
            yield client
    finally:
        app.dependency_overrides = previous_overrides


def _insert_long_term_memory(
    *,
    user_id: str = "user-1",
    content: str = "用户喜欢 Python 编程语言",
    state: str = "active",
    archive_status: str = "active",
    importance: float = 0.8,
    source_type: str = "preference",
    memory_layer: str = "semantic",
    confidence: float = 0.6,
) -> int:
    """在测试库插入一条长期记忆，返回 ID。"""
    db = TestingSessionLocal()
    try:
        memory = LongTermMemory(
            content=content,
            importance=importance,
            embedding=[1.0, 0.0, 0.0],
            user_id=user_id,
            workspace_id="default",
            confidence=confidence,
            quality_score=0.5,
            archive_status=archive_status,
            state=state,
            memory_metadata={"source_type": source_type},
            memory_layer=memory_layer,
            created_at=datetime.now(timezone.utc),
            last_access=datetime.now(timezone.utc),
        )
        db.add(memory)
        db.commit()
        db.refresh(memory)
        return memory.id
    finally:
        db.close()


# ---------------------------------------------------------------------------
# validate / deprecate
# ---------------------------------------------------------------------------


def test_validate_promotes_to_validated():
    """
    场景：用户点击"准确"调用 POST /api/memory/long-term/{id}/validate。

    Then 返回 ok=true、state=validated
    And DB 中 state=validated、confidence 提升至 0.9
    """
    memory_id = _insert_long_term_memory(state="active", confidence=0.6)

    with _test_client() as client:
        response = client.post(f"/api/memory/long-term/{memory_id}/validate")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["state"] == "validated"

    with TestingSessionLocal() as db:
        memory = db.query(LongTermMemory).filter(LongTermMemory.id == memory_id).first()
        assert memory.state == "validated"
        assert memory.confidence == 0.9


def test_deprecate_marks_deprecated():
    """
    场景：用户点击"不准确"调用 POST /api/memory/long-term/{id}/deprecate。

    Then 返回 ok=true、state=deprecated
    And DB 中 state=deprecated、archive_status=deprecated
    """
    memory_id = _insert_long_term_memory(state="active")

    with _test_client() as client:
        response = client.post(f"/api/memory/long-term/{memory_id}/deprecate")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["state"] == "deprecated"

    with TestingSessionLocal() as db:
        memory = db.query(LongTermMemory).filter(LongTermMemory.id == memory_id).first()
        assert memory.state == "deprecated"
        assert memory.archive_status == "deprecated"


def test_validate_other_users_memory_returns_403():
    """
    场景：操作他人记忆。

    Given 记忆属于 user-2
    When user-1 调用 validate
    Then 返回 403
    """
    memory_id = _insert_long_term_memory(user_id="user-2")

    with _test_client(user_id="user-1") as client:
        response = client.post(f"/api/memory/long-term/{memory_id}/validate")

    assert response.status_code == 403


def test_validate_missing_memory_returns_404():
    """
    场景：验证不存在的记忆。

    When 调用 validate id=99999
    Then 返回 404
    """
    with _test_client() as client:
        response = client.post("/api/memory/long-term/99999/validate")

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# 响应字段暴露
# ---------------------------------------------------------------------------


def test_long_term_list_exposes_source_type_layer_state():
    """
    场景：GET /api/memory/long-term 暴露真实元数据。

    Given 一条 source_type=preference / memory_layer=semantic / state=active 的记忆
    When 调用 GET /api/memory/long-term
    Then 响应含 source_type=preference / memory_layer=semantic / state=active
    """
    _insert_long_term_memory(
        content="用户喜欢 Python",
        state="active",
        source_type="preference",
        memory_layer="semantic",
    )

    with _test_client() as client:
        response = client.get("/api/memory/long-term")

    assert response.status_code == 200
    items = response.json()
    target = next(
        (m for m in items if m.get("content") == "用户喜欢 Python"), None
    )
    assert target is not None, f"未找到目标记忆，实际: {items}"
    assert target["source_type"] == "preference"
    assert target["memory_layer"] == "semantic"
    assert target["state"] == "active"


def test_long_term_list_source_type_fallback_manual():
    """
    场景：历史数据 memory_metadata 无 source_type 时回退 manual。

    Given 一条 memory_metadata 为空、无顶层来源的记忆
    When 调用 GET /api/memory/long-term
    Then source_type="manual"
    """
    db = TestingSessionLocal()
    try:
        memory = LongTermMemory(
            content="历史遗留记忆",
            importance=0.5,
            embedding=[1.0, 0.0, 0.0],
            user_id="user-1",
            workspace_id="default",
            confidence=0.5,
            quality_score=0.5,
            archive_status="active",
            state="active",
            memory_metadata={},
            memory_layer="semantic",
            created_at=datetime.now(timezone.utc),
            last_access=datetime.now(timezone.utc),
        )
        db.add(memory)
        db.commit()
    finally:
        db.close()

    with _test_client() as client:
        response = client.get("/api/memory/long-term")

    assert response.status_code == 200
    target = next(
        (m for m in response.json() if m.get("content") == "历史遗留记忆"), None
    )
    assert target is not None
    assert target["source_type"] == "manual"


# ---------------------------------------------------------------------------
# 手动巩固
# ---------------------------------------------------------------------------


def test_consolidation_run_propagates_unexpected_exception_as_500(monkeypatch):
    """
    场景：手动巩固执行抛出未预期异常（删除兜底后的错误路径）。

    When 调用 POST /api/memory/consolidation/run 且 run_if_due 抛错
    Then 返回 500（异常自然传播，禁止以 success=False 伪装成功返回）
    """
    from memory.consolidation_runner import ConsolidationRunner

    async def _boom(self, **kwargs):
        raise RuntimeError("consolidation crashed")

    monkeypatch.setattr(ConsolidationRunner, "run_if_due", _boom)

    with _test_client(raise_server_exceptions=False) as client:
        response = client.post("/api/memory/consolidation/run")

    assert response.status_code == 500
    # 结构化错误体：统一 error.message 字段（code=internal_server_error）
    assert response.json()["error"]["code"] == "internal_server_error"


def test_consolidation_run_returns_statistics():
    """
    场景：手动触发记忆巩固。

    When 调用 POST /api/memory/consolidation/run
    Then 返回含 triggered/processed 等字段的统计（LLM 配置缺失时不抛 500）
    """
    with _test_client() as client:
        response = client.post("/api/memory/consolidation/run")

    # 无论 LLM 配置是否可用，端点都必须返回 200 结构化结果
    assert response.status_code == 200
    body = response.json()
    assert body["triggered"] is True
    assert "processed" in body
    assert "extracted" in body
    assert "consolidated" in body
