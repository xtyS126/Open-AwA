"""
记忆增强与工作流 API 集成测试。
"""

import math
import sys
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.dependencies import get_current_user, get_db
from db.models import LongTermMemory, init_db
from main import app
from memory.manager import MemoryManager
from memory.vector_store_manager import VectorStoreManager
from tools.registry import built_in_tool_registry


class SemanticTestEmbeddingProvider:
    """
    测试专用嵌入提供方。
    """

    provider_name = "test-semantic"

    def __init__(self):
        self.keyword_groups = [
            ["过拟合", "正则化", "机器学习"],
            ["数据库", "索引", "查询"],
            ["工作流", "自动化", "文件"],
        ]

    def embed_texts(self, texts):
        return [self._embed_single(text) for text in texts]

    def _embed_single(self, text):
        vector = []
        for group in self.keyword_groups:
            vector.append(1.0 if any(keyword in text for keyword in group) else 0.0)
        if not any(vector):
            vector = [1.0, 0.0, 0.0]
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]


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


def override_get_current_user():
    class DummyUser:
        id = "user-1"
        username = "test-user"
        role = "user"

    return DummyUser()


def _reset_state():
    db = TestingSessionLocal()
    try:
        db.query(LongTermMemory).delete()
        db.commit()
    finally:
        db.close()
    built_in_tool_registry._instances.clear()


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


def setup_function():
    _reset_state()


def teardown_function():
    _reset_state()


def test_memory_vector_search_archive_quality_and_stats_api(tmp_path):
    """
    验证记忆增强 API 的向量搜索、质量报告、统计与归档行为。
    """
    MemoryManager._shared_vector_store = VectorStoreManager(
        persist_directory=str(tmp_path / "memory_api_vector_db"),
        collection_name=f"memory_api_{uuid.uuid4().hex}",
        embedding_provider=SemanticTestEmbeddingProvider(),
    )

    with _test_client() as client:
        response = client.post(
            "/api/memory/long-term",
            json={
                "content": "过拟合问题经常通过正则化技术解决",
                "importance": 0.9,
                "metadata": {"source_type": "document"},
            },
        )
        assert response.status_code == 200
        first_memory_id = response.json()["id"]

        second_response = client.post(
            "/api/memory/long-term",
            json={
                "content": "数据库索引优化实践",
                "importance": 0.5,
                "metadata": {"source_type": "manual"},
            },
        )
        assert second_response.status_code == 200

        search_response = client.post(
            "/api/memory/vector-search",
            json={"query": "机器学习中的过拟合问题", "limit": 5},
        )
        assert search_response.status_code == 200
        search_data = search_response.json()
        assert search_data[0]["id"] == first_memory_id

        quality_response = client.get("/api/memory/quality")
        assert quality_response.status_code == 200
        assert len(quality_response.json()) == 2

        stats_response = client.get("/api/memory/stats")
        assert stats_response.status_code == 200
        assert stats_response.json()["vector_store_count"] == 2
        assert stats_response.json()["embedding_provider"] == "test-semantic"

        db = TestingSessionLocal()
        try:
            memory = db.query(LongTermMemory).filter(LongTermMemory.id == first_memory_id).first()
            memory.last_access = datetime.now(timezone.utc) - timedelta(days=45)
            memory.importance = 0.1
            memory.confidence = 0.1
            memory.access_count = 30
            db.commit()
        finally:
            db.close()

        archive_response = client.post(
            "/api/memory/archive",
            json={
                "older_than_days": 30,
                "importance_threshold": 0.3,
                "include_low_quality": True,
            },
        )
        assert archive_response.status_code == 200
        assert archive_response.json()["archived_count"] >= 1


def test_workflow_crud_execute_and_status_api(tmp_path):
    """
    验证工作流 API 的创建、更新、执行、状态查询与删除流程。
    """
    workdir = tmp_path / "workflow_api"
    workdir.mkdir(parents=True, exist_ok=True)
    source_file = workdir / "source.txt"
    target_file = workdir / "target.txt"
    source_file.write_text("workflow api", encoding="utf-8")

    definition = {
        "name": "workflow_api_demo",
        "description": "读取并写入文件",
        "steps": [
            {
                "id": "read_source",
                "type": "tool",
                "tool": "file_manager",
                "action": "read_file",
                "config": {"allowed_directories": [str(workdir)]},
                "params": {"path": str(source_file)},
            },
            {
                "id": "write_target",
                "type": "tool",
                "tool": "file_manager",
                "action": "write_file",
                "config": {"allowed_directories": [str(workdir)]},
                "params": {
                    "path": str(target_file),
                    "content": "{{steps.read_source.content}}",
                },
            },
        ],
    }

    with _test_client() as client:
        create_response = client.post(
            "/api/workflows",
            json={
                "name": "workflow_api_demo",
                "description": "读取并写入文件",
                "format": "yaml",
                "definition": definition,
                "enabled": True,
            },
        )
        assert create_response.status_code == 200
        workflow_id = create_response.json()["id"]

        list_response = client.get("/api/workflows")
        assert list_response.status_code == 200
        assert len(list_response.json()) == 1

        update_response = client.put(
            f"/api/workflows/{workflow_id}",
            json={"description": "更新后的描述"},
        )
        assert update_response.status_code == 200
        assert update_response.json()["description"] == "更新后的描述"

        execute_response = client.post(
            "/api/workflows/execute",
            json={"workflow_id": workflow_id, "input_context": {}},
        )
        assert execute_response.status_code == 200
        execution_id = execute_response.json()["id"]
        assert execute_response.json()["status"] == "completed"
        assert target_file.read_text(encoding="utf-8") == "workflow api"

        status_response = client.get(f"/api/workflows/executions/{execution_id}")
        assert status_response.status_code == 200
        assert status_response.json()["status"] == "completed"

        delete_response = client.delete(f"/api/workflows/{workflow_id}")
        assert delete_response.status_code == 200