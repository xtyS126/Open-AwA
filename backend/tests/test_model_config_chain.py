"""
向量模型配置链测试（Spec memory-model-config-chain）。

覆盖：
- 模型注册表：嵌入/重排模型规格查询与默认模型
- 重排器：本地 CrossEncoder（mock）、云端 API（mock httpx）、create_reranker 分支
- MemoryManager._apply_rerank 检索接入
- API 路由：registry / config GET+PUT / download 触发
"""

from __future__ import annotations

import sys
from contextlib import contextmanager
from pathlib import Path
from typing import List
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.dependencies import get_current_user, get_db
from db.models import VectorModelConfig, init_db
from main import app
from memory.manager import MemoryManager
from memory.model_registry import (
    default_embedding_model,
    default_rerank_model,
    get_embedding_spec,
    get_rerank_spec,
)
from memory.reranker import CloudReranker, LocalCrossEncoderReranker, create_reranker


# ---------------------------------------------------------------------------
# 注册表
# ---------------------------------------------------------------------------


def test_registry_contains_key_models():
    """注册表包含目标模型：bge-small-zh-v1.5 / ms-marco-MiniLM-L6-v2 / Qwen3 系列。"""
    bge = get_embedding_spec("bge-small-zh-v1.5")
    assert bge is not None
    assert bge.kind == "local"
    assert bge.dimension == 512
    assert bge.modelscope_id  # ModelScope 仓库 ID 已配置

    ms = get_rerank_spec("ms-marco-MiniLM-L6-v2")
    assert ms is not None
    assert ms.kind == "local"
    assert ms.modelscope_id

    qwen_emb = get_embedding_spec("Qwen3-VL-Embedding")
    assert qwen_emb is not None
    assert qwen_emb.kind == "cloud"
    assert "multimodal" in qwen_emb.capabilities

    qwen_rerank = get_rerank_spec("Qwen3-VL-Reranker")
    assert qwen_rerank is not None
    assert qwen_rerank.kind == "cloud"
    assert "multimodal" in qwen_rerank.capabilities


def test_registry_defaults():
    """默认模型：本地 all-MiniLM-L6-v2 / ms-marco-MiniLM-L6-v2，云端 Qwen3 系列。"""
    assert default_embedding_model("local") == "all-MiniLM-L6-v2"
    assert default_embedding_model("cloud") == "Qwen3-VL-Embedding"
    assert default_rerank_model("local") == "ms-marco-MiniLM-L6-v2"
    assert default_rerank_model("cloud") == "Qwen3-VL-Reranker"


def test_registry_unknown_model_returns_none():
    """未注册模型返回 None。"""
    assert get_embedding_spec("not-exists-model") is None
    assert get_rerank_spec("not-exists-model") is None


# ---------------------------------------------------------------------------
# 重排器
# ---------------------------------------------------------------------------


class _FakeCrossEncoder:
    """模拟 CrossEncoder 的 predict 行为。"""

    def __init__(self, model_path, **kwargs):
        self.model_path = model_path

    def predict(self, pairs):
        # 第一对最相关，分数递减
        return [1.0 - i * 0.1 for i in range(len(pairs))]


@pytest.mark.asyncio
async def test_local_cross_encoder_reranker(monkeypatch, tmp_path):
    """本地 CrossEncoder 重排器：缓存命中加载 + 打分。"""
    import sys as _sys
    import types as _types

    fake_snapshot = tmp_path / "snapshot"
    fake_snapshot.mkdir()
    (fake_snapshot / "config.json").write_text("{}")
    monkeypatch.setattr(
        LocalCrossEncoderReranker,
        "_find_cached_model_path",
        lambda self: str(fake_snapshot),
    )
    monkeypatch.setitem(
        _sys.modules,
        "sentence_transformers",
        _types.SimpleNamespace(CrossEncoder=_FakeCrossEncoder),
    )

    reranker = LocalCrossEncoderReranker(model_name="ms-marco-MiniLM-L6-v2")
    scores = await reranker.rerank("喜欢什么编程语言", ["Python 用户", "Java 用户"])

    assert len(scores) == 2
    assert scores[0] > scores[1]


@pytest.mark.asyncio
async def test_cloud_reranker_api(monkeypatch):
    """云端重排器：调用 API 并解析 results[index, relevance_score]。"""

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "results": [
                    {"index": 1, "relevance_score": 0.9},
                    {"index": 0, "relevance_score": 0.3},
                ]
            }

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr("memory.reranker.httpx.AsyncClient", FakeAsyncClient)
    reranker = CloudReranker(api_key="secret", model="Qwen3-VL-Reranker")
    scores = await reranker.rerank("query", ["doc1", "doc2"])

    assert scores == [0.3, 0.9]


@pytest.mark.asyncio
async def test_cloud_reranker_failure_returns_zeros(monkeypatch):
    """云端重排调用失败时返回全 0（不抛异常，检索退回融合排序）。"""

    class FailingClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, *args, **kwargs):
            raise RuntimeError("network down")

    monkeypatch.setattr("memory.reranker.httpx.AsyncClient", FailingClient)
    reranker = CloudReranker(api_key="secret")
    scores = await reranker.rerank("query", ["doc1", "doc2"])

    # 调用失败返回空列表，由 _apply_rerank 检测长度不匹配后跳过重排
    assert scores == []


def test_create_reranker_disabled_by_default(monkeypatch):
    """默认不配置时重排关闭（返回 None）。"""
    monkeypatch.setattr("memory.reranker._settings", None, raising=False)
    # 使用真实的 settings：未配置 MEMORY_RERANK_PROVIDER → None
    from config.settings import settings

    monkeypatch.setattr(settings, "MEMORY_RERANK_PROVIDER", "")
    assert create_reranker() is None


# ---------------------------------------------------------------------------
# MemoryManager 检索接入重排
# ---------------------------------------------------------------------------


class _FakeMemory:
    """模拟 LongTermMemory 对象。"""

    def __init__(self, memory_id: int, content: str):
        self.id = memory_id
        self.content = content


@pytest.mark.asyncio
async def test_apply_rerank_reorders_by_score():
    """_apply_rerank 按重排分数重排并截断到 limit。"""

    class FakeReranker:
        provider_name = "fake"

        async def rerank(self, query: str, documents: List[str]) -> List[float]:
            # 与输入顺序相反的分数：doc3 最相关
            return [0.2, 0.8, 0.9]

    manager = MagicMock(spec=MemoryManager)
    manager._get_reranker = lambda: FakeReranker()
    memories = [
        _FakeMemory(1, "Python"),
        _FakeMemory(2, "Java"),
        _FakeMemory(3, "Rust"),
    ]
    result = await MemoryManager._apply_rerank(manager, "编程", memories, limit=2)

    assert [m.id for m in result] == [3, 2]


@pytest.mark.asyncio
async def test_apply_rerank_no_reranker_returns_input():
    """未配置重排器时原样返回。"""
    manager = MagicMock(spec=MemoryManager)
    manager._reranker = None
    memories = [_FakeMemory(1, "a"), _FakeMemory(2, "b")]
    result = await MemoryManager._apply_rerank(manager, "q", memories, limit=2)

    assert result == memories


# ---------------------------------------------------------------------------
# API 路由
# ---------------------------------------------------------------------------

engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
init_db(bind_engine=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


class _DummyUser:
    def __init__(self, user_id: str):
        self.id = user_id
        self.username = "test-user"
        self.role = "admin"


def override_get_current_user():
    return _DummyUser(user_id="user-1")


@contextmanager
def _test_client():
    previous_overrides = dict(app.dependency_overrides)
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides = previous_overrides


def test_vector_registry_api():
    """GET /api/models/vector/registry 返回注册表。"""
    with _test_client() as client:
        response = client.get("/api/models/vector/registry")

    assert response.status_code == 200
    models = response.json()["data"]["models"]
    names = [m["name"] for m in models]
    assert "bge-small-zh-v1.5" in names
    assert "ms-marco-MiniLM-L6-v2" in names
    assert "Qwen3-VL-Embedding" in names
    assert "Qwen3-VL-Reranker" in names
    # 字段完整性
    bge = next(m for m in models if m["name"] == "bge-small-zh-v1.5")
    assert bge["model_type"] == "embedding"
    assert bge["dimension"] == 512
    assert "downloaded" in bge


def test_vector_config_get_and_put():
    """GET/PUT /api/models/vector/config 读写持久化。"""
    with _test_client() as client:
        # 初始读取（未配置 → 默认值；conftest 测试环境可能注入 MEMORY_EMBEDDING_PROVIDER=hash）
        response = client.get("/api/models/vector/config")
        assert response.status_code == 200
        assert response.json()["data"]["embedding_provider"] in ("auto", "", "hash")
        assert response.json()["data"]["rerank_provider"] in ("off", "")

        # 更新配置
        response = client.put(
            "/api/models/vector/config",
            json={
                "embedding_provider": "local",
                "embedding_model": "bge-small-zh-v1.5",
                "rerank_provider": "local",
                "rerank_model": "ms-marco-MiniLM-L6-v2",
            },
        )
        assert response.status_code == 200

        # 再次读取应持久化
        response = client.get("/api/models/vector/config")
        data = response.json()["data"]
        assert data["embedding_provider"] == "local"
        assert data["embedding_model"] == "bge-small-zh-v1.5"
        assert data["rerank_provider"] == "local"
        assert data["rerank_model"] == "ms-marco-MiniLM-L6-v2"


def test_vector_config_api_key_encrypted():
    """API Key 写入时密文存储。"""
    with _test_client() as client:
        response = client.put(
            "/api/models/vector/config",
            json={"embedding_api_key": "sk-test-secret"},
        )
        assert response.status_code == 200

    with TestingSessionLocal() as db:
        row = db.query(VectorModelConfig).filter(
            VectorModelConfig.key == "embedding_api_key"
        ).first()
        assert row is not None
        # 新算法密文前缀为 enc2:（config.security.encrypt_secret_value）
        assert row.value.startswith(("enc:", "enc2:"))


def test_vector_download_unknown_model_404():
    """下载未注册模型返回 404。"""
    with _test_client() as client:
        response = client.post(
            "/api/models/vector/download",
            json={"model": "not-exists", "kind": "embedding"},
        )

    assert response.status_code == 404
