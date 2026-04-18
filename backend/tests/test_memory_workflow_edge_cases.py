"""
记忆、工作流和工具注册器的边界路径测试。
重点覆盖异常分支、兼容逻辑和辅助方法。
"""

import builtins
import math
import sys
import threading
import time
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.routes import memory as memory_routes
from db.models import LongTermMemory, WorkflowExecution, WorkflowStep, init_db
from memory import manager as memory_manager_module
from memory.manager import MemoryManager
from memory.vector_store_manager import (
    HashEmbeddingProvider,
    OpenAIEmbeddingProvider,
    SentenceTransformerEmbeddingProvider,
    VectorStoreManager,
    create_embedding_provider,
)
from memory.working_memory import WorkingMemoryStore
from tools import registry as registry_module
from tools.registry import BuiltInToolRegistry
from workflow.engine import WorkflowEngine
from workflow.parser import WorkflowParser


class FakeEmbeddingProvider:
    provider_name = "fake"

    def embed_texts(self, texts):
        return [[1.0, 0.0, 0.0] for _ in texts]


class FakeVectorHit:
    def __init__(self, memory_id, score):
        self.memory_id = memory_id
        self.score = score


class FakeVectorStore:
    def __init__(self):
        self.embedding_provider = FakeEmbeddingProvider()
        self.provider_name = "fake"
        self.search_results = []
        self.upserts = []
        self.metadata_updates = []
        self.deleted = []
        self.count_value = 0

    def upsert_memory(self, memory_id, content, **kwargs):
        self.upserts.append((memory_id, content, kwargs))

    def update_memory_metadata(self, memory_id, **kwargs):
        self.metadata_updates.append((memory_id, kwargs))

    def search(self, *args, **kwargs):
        return list(self.search_results)

    def delete_memory(self, memory_id):
        self.deleted.append(memory_id)

    def count(self, **kwargs):
        return self.count_value


class FakeCollection:
    def __init__(self):
        self.records = {}

    def upsert(self, ids, documents, embeddings, metadatas):
        for index, record_id in enumerate(ids):
            self.records[record_id] = {
                "document": documents[index],
                "embedding": embeddings[index],
                "metadata": metadatas[index],
            }

    def delete(self, ids):
        for record_id in ids:
            self.records.pop(record_id, None)

    def get(self, ids=None, include=None, where=None):
        selected = []
        if ids is not None:
            for record_id in ids:
                if record_id in self.records:
                    selected.append((record_id, self.records[record_id]))
        else:
            for record_id, record in self.records.items():
                if self._match_where(record["metadata"], where):
                    selected.append((record_id, record))
        return {
            "ids": [record_id for record_id, _ in selected],
            "documents": [record["document"] for _, record in selected],
            "metadatas": [record["metadata"] for _, record in selected],
            "embeddings": [record["embedding"] for _, record in selected],
        }

    def query(self, query_embeddings, n_results, where=None, include=None):
        selected = []
        for record_id, record in self.records.items():
            if not self._match_where(record["metadata"], where):
                continue
            distance = abs(sum(query_embeddings[0]) - sum(record["embedding"]))
            selected.append((distance, record_id, record))
        selected.sort(key=lambda item: item[0])
        selected = selected[:n_results]
        return {
            "ids": [[record_id for _, record_id, _ in selected]],
            "documents": [[record["document"] for _, _, record in selected]],
            "metadatas": [[record["metadata"] for _, _, record in selected]],
            "distances": [[distance for distance, _, _ in selected]],
        }

    def count(self):
        return len(self.records)

    def _match_where(self, metadata, where):
        if where is None:
            return True
        if "$and" in where:
            return all(self._match_where(metadata, item) for item in where["$and"])
        return all(metadata.get(key) == value for key, value in where.items())


class FakePersistentClient:
    def __init__(self, path):
        self.path = path
        self.collection = FakeCollection()

    def get_or_create_collection(self, name, metadata):
        return self.collection


class FakeTool:
    def __init__(self, config=None):
        self.config = config or {}
        self.name = self.config.get("name", "fake_tool")
        self.description = self.config.get("description", "fake description")
        self.version = "9.9.9"
        self.initialized = False

    async def initialize(self):
        self.initialized = True
        return True

    async def execute(self, **kwargs):
        return {"success": True, "config": self.config, **kwargs}

    def get_tools(self):
        return {"demo": {"name": "demo"}}


class FakeLoader:
    def __init__(self, db_session):
        self.db_session = db_session
        self.converted = []

    def load_from_file(self, file_path):
        if str(file_path).endswith("skip.yaml"):
            return {"name": "skip"}
        return {"name": Path(file_path).stem, "builtin_tool": True}

    def convert_to_skill_model(self, config):
        self.converted.append(config)


class FakeDbSession:
    def __init__(self):
        self.commit_count = 0

    def commit(self):
        self.commit_count += 1


class FakeSkillEngine:
    def __init__(self, result=None):
        self.result = result or {"success": True, "outputs": {"value": "ok"}}

    async def execute_skill(self, **kwargs):
        return dict(self.result)


class FakePluginManager:
    def __init__(self, load_result=True, execute_result=None):
        self.loaded_plugins = set()
        self.load_result = load_result
        self.execute_result = execute_result or {"status": "success", "message": "ok"}

    def load_plugin(self, plugin_name):
        if self.load_result:
            self.loaded_plugins.add(plugin_name)
        return self.load_result

    async def execute_plugin_async(self, plugin_name, plugin_method, **kwargs):
        return dict(self.execute_result)


def build_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    init_db(bind_engine=engine)
    session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return session_local()


def test_working_memory_store_eviction_and_access_patterns():
    """
    验证工作内存的访问刷新、淘汰、列出和统计逻辑。
    """
    store = WorkingMemoryStore(capacity_per_user=2)
    old_entry = store.put("1", {"value": 1}, user_id="user-1")
    fresh_entry = store.put("2", {"value": 2}, user_id="user-1")
    old_entry.last_accessed_at = datetime.now(timezone.utc) - timedelta(hours=12)
    old_entry.access_count = 1
    fresh_entry.access_count = 5

    store.put("3", {"value": 3}, user_id="user-1")

    assert store.get("1", user_id="user-1") is None
    touched = store.get("2", user_id="user-1")
    assert touched is not None
    assert touched.access_count >= 6
    assert [entry.memory_id for entry in store.list_entries("user-1")] == ["2", "3"]
    popped = store.pop("3", user_id="user-1")
    assert popped is not None
    assert store.stats("user-1")["count"] == 1
    assert store.stats(None)["capacity"] == 2


def test_vector_embedding_providers_and_factory(monkeypatch):
    """
    验证哈希、OpenAI、本地 sentence-transformers 以及工厂分支逻辑。
    """
    hash_provider = HashEmbeddingProvider(dimension=4)
    vector = hash_provider.embed_texts([""])[0]
    assert len(vector) == 4
    assert pytest.approx(math.sqrt(sum(item * item for item in vector)), rel=1e-6) == 1.0

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "data": [
                    {"index": 1, "embedding": [0.0, 1.0]},
                    {"index": 0, "embedding": [1.0, 0.0]},
                ]
            }

    monkeypatch.setattr("memory.vector_store_manager.httpx.post", lambda *args, **kwargs: FakeResponse())
    openai_provider = OpenAIEmbeddingProvider(api_key="secret")
    assert openai_provider.embed_texts(["a", "b"]) == [[1.0, 0.0], [0.0, 1.0]]

    class FakeEncodedVectors:
        def tolist(self):
            return [[1.0, 2.0], [3.0, 4.0]]

    class FakeSentenceTransformer:
        def __init__(self, model_name):
            self.model_name = model_name

        def encode(self, texts, normalize_embeddings=True):
            return FakeEncodedVectors()

    monkeypatch.setitem(sys.modules, "sentence_transformers", types.SimpleNamespace(SentenceTransformer=FakeSentenceTransformer))
    local_provider = SentenceTransformerEmbeddingProvider("fake-model")
    assert local_provider.embed_texts(["a", "b"]) == [[1.0, 2.0], [3.0, 4.0]]

    monkeypatch.setattr("memory.vector_store_manager.settings.OPENAI_API_KEY", None, raising=False)
    with pytest.raises(RuntimeError):
        create_embedding_provider("openai")

    class Secret:
        def get_secret_value(self):
            return "secret"

    monkeypatch.setattr("memory.vector_store_manager.settings.OPENAI_API_KEY", Secret(), raising=False)
    assert isinstance(create_embedding_provider("openai"), OpenAIEmbeddingProvider)
    assert isinstance(create_embedding_provider("hash"), HashEmbeddingProvider)
    assert isinstance(create_embedding_provider("local"), SentenceTransformerEmbeddingProvider)

    original_import = builtins.__import__

    def failing_import(name, *args, **kwargs):
        if name == "sentence_transformers":
            raise ImportError("missing")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", failing_import)
    monkeypatch.setattr("memory.vector_store_manager.settings.OPENAI_API_KEY", None, raising=False)
    fallback = create_embedding_provider(None)
    assert isinstance(fallback, HashEmbeddingProvider)


def test_vector_store_manager_helper_paths(monkeypatch, tmp_path):
    """
    验证向量管理器的初始化、元数据处理、更新与计数辅助逻辑。
    """
    monkeypatch.setattr("memory.vector_store_manager.chromadb.PersistentClient", FakePersistentClient)
    manager = VectorStoreManager(
        persist_directory=str(tmp_path / "vector_store"),
        collection_name="helpers",
        embedding_provider=HashEmbeddingProvider(dimension=4),
    )

    assert manager.provider_name == "hash"
    assert manager._document_id(7) == "memory:7"
    assert manager._sanitize_metadata({"a": 1, "b": None, "c": {"nested": True}})["c"] == "{'nested': True}"
    assert manager._extract_first_item([[1, 2, 3]]) == [1, 2, 3]
    assert manager._extract_first_item([{"ok": True}]) == {"ok": True}
    assert manager._build_where_clause(user_id=None, include_archived=True) is None
    assert manager._build_where_clause(user_id="u", include_archived=True) == {"user_id": "u"}
    assert manager._build_where_clause(user_id="u", include_archived=False) == {
        "$and": [{"user_id": "u"}, {"archive_status": "active"}]
    }

    manager.update_memory_metadata(999, foo="bar")
    manager.upsert_memory(1, "hello", user_id="user-1", metadata={"nested": {"value": 1}})
    manager.update_memory_metadata(1, foo="bar")

    record = manager.collection.get(ids=[manager._document_id(1)], include=["documents", "metadatas", "embeddings"])
    assert record["metadatas"][0]["foo"] == "bar"
    assert manager.count() == 1
    assert manager.count(user_id="user-1", include_archived=False) == 1


def test_memory_manager_shared_vector_store_is_initialized_once(monkeypatch):
    """
    验证共享向量存储在并发初始化时只会构造一次实例。
    """
    previous_shared_vector_store = MemoryManager._shared_vector_store
    MemoryManager._shared_vector_store = None

    class SlowVectorStore:
        init_count = 0

        def __init__(self):
            type(self).init_count += 1
            time.sleep(0.02)

    created_instances = []
    failures = []

    def create_manager():
        try:
            manager = MemoryManager(object())
            created_instances.append(manager.vector_store)
        except Exception as exc:  # pragma: no cover - 仅用于保留线程内异常
            failures.append(exc)

    monkeypatch.setattr(memory_manager_module, "VectorStoreManager", SlowVectorStore)

    try:
        threads = [threading.Thread(target=create_manager) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert failures == []
        assert SlowVectorStore.init_count == 1
        assert len({id(instance) for instance in created_instances}) == 1
    finally:
        MemoryManager._shared_vector_store = previous_shared_vector_store


@pytest.mark.asyncio
async def test_memory_route_long_term_listing_uses_offset_pagination():
    """
    验证长期记忆列表路由会把 skip/limit 映射为底层 offset/limit 分页参数。
    """

    class DummyManager:
        def __init__(self):
            self.calls = []

        async def get_long_term_memories(self, **kwargs):
            self.calls.append(kwargs)
            return []

    class DummyUser:
        id = "user-1"

    manager = DummyManager()
    result = await memory_routes.get_long_term_memories(
        skip=2,
        limit=3,
        include_archived=True,
        manager=manager,
        current_user=DummyUser(),
    )

    assert result == []
    assert manager.calls == [
        {
            "limit": 3,
            "offset": 2,
            "user_id": "user-1",
            "include_archived": True,
        }
    ]


@pytest.mark.asyncio
async def test_memory_manager_short_term_context_and_edge_paths():
    """
    验证短期记忆、上下文拼装、质量评估空路径和删除空路径。
    """
    session = build_session()
    fake_vector_store = FakeVectorStore()
    fake_vector_store.count_value = 0
    MemoryManager._shared_vector_store = fake_vector_store
    manager = MemoryManager(session)

    assert manager._source_score({"source_type": "unknown"}) == 0.55
    assert manager._ensure_aware_datetime(None).tzinfo is not None
    assert manager._ensure_aware_datetime(datetime(2026, 1, 1, 0, 0, 0)).tzinfo is not None

    await manager.add_short_term_memory("session-1", "user", "你好")
    await manager.add_short_term_memory("session-1", "assistant", "世界")
    short_term = await manager.get_short_term_memories("session-1")
    context = await manager.get_context_for_session("session-1")

    assert len(short_term) == 2
    assert context == "User: 你好\nAssistant: 世界"
    assert await manager.clear_short_term_memory("session-1") == 2
    assert await manager.evaluate_memory_quality(99999) is None
    assert await manager.delete_long_term_memory(99999) is False
    await manager.update_memory_access(99999)

    session.close()


@pytest.mark.asyncio
async def test_memory_manager_long_term_listing_supports_offset():
    """
    验证长期记忆列表支持真正的 offset/limit 分页。
    """
    session = build_session()
    fake_vector_store = FakeVectorStore()
    MemoryManager._shared_vector_store = fake_vector_store
    manager = MemoryManager(session)

    await manager.add_long_term_memory(
        content="第一条长期记忆",
        importance=0.9,
        user_id="user-1",
        memory_metadata={},
    )
    second_memory = await manager.add_long_term_memory(
        content="第二条长期记忆",
        importance=0.7,
        user_id="user-1",
        memory_metadata={},
    )
    await manager.add_long_term_memory(
        content="第三条长期记忆",
        importance=0.5,
        user_id="user-1",
        memory_metadata={},
    )

    page = await manager.get_long_term_memories(
        user_id="user-1",
        include_archived=False,
        limit=1,
        offset=1,
    )

    assert [item.id for item in page] == [second_memory.id]
    session.close()


@pytest.mark.asyncio
async def test_memory_manager_long_term_listing_search_archive_and_delete():
    """
    验证长期记忆的列出、空检索、归档、统计与删除路径。
    """
    session = build_session()
    fake_vector_store = FakeVectorStore()
    fake_vector_store.count_value = 1
    MemoryManager._shared_vector_store = fake_vector_store
    manager = MemoryManager(session)

    memory = await manager.add_long_term_memory(
        content="仅用于边界路径覆盖的长期记忆",
        importance=0.6,
        user_id="user-1",
        memory_metadata={},
    )

    visible_memories = await manager.get_long_term_memories(user_id="user-1", include_archived=False)
    assert [item.id for item in visible_memories] == [memory.id]

    memory.archive_status = "archived"
    session.commit()
    assert await manager.get_long_term_memories(user_id="user-1", include_archived=False) == []
    assert len(await manager.get_long_term_memories(user_id="user-1", include_archived=True)) == 1

    fake_vector_store.search_results = []
    assert await manager.search_memories("完全不存在", user_id="user-1", include_archived=False) == []

    memory.archive_status = "active"
    memory.importance = 0.9
    memory.confidence = 0.9
    memory.access_count = 1
    session.commit()

    quality_report = await manager.get_quality_report(user_id="user-1", memory_id=memory.id, limit=1)
    stats = await manager.get_memory_stats(user_id="user-1")
    archive_count = await manager.archive_memories(user_id="user-1", include_low_quality=False)

    assert len(quality_report) == 1
    assert stats["total_memories"] == 1
    assert archive_count == 0
    assert await manager.consolidate_memories() == 0
    assert await manager.delete_long_term_memory(memory.id) is True
    assert fake_vector_store.deleted == [memory.id]
    assert (await manager.get_memory_stats(user_id="user-1"))["total_memories"] == 0

    session.close()


@pytest.mark.asyncio
async def test_tool_registry_and_seed_paths(monkeypatch):
    """
    验证工具注册器的缓存、重建、列出、执行与技能同步逻辑。
    """
    registry = BuiltInToolRegistry()
    monkeypatch.setattr(registry_module, "FileManagerSkill", FakeTool)
    monkeypatch.setattr(registry_module, "TerminalExecutorSkill", FakeTool)
    monkeypatch.setattr(registry_module, "WebSearchSkill", FakeTool)

    first = await registry._initialize_tool("file_manager")
    second = await registry._initialize_tool("file_manager")
    third = await registry._initialize_tool("file_manager", config={"name": "custom"})
    tool_list = await registry.list_tools()
    execution = await registry.execute_tool("terminal_executor", action="run_command", params={"command": "echo hi"})

    assert first is second
    assert third is not first
    assert tool_list["file_manager"]["version"] == "9.9.9"
    assert execution["success"] is True

    with pytest.raises(ValueError):
        await registry._initialize_tool("unknown")

    monkeypatch.setattr(registry_module, "SkillLoader", FakeLoader)
    monkeypatch.setattr(registry, "_config_files", lambda: [Path("file_manager.yaml"), Path("skip.yaml")])
    fake_db = FakeDbSession()
    assert registry.seed_built_in_skills(fake_db) == 1
    assert fake_db.commit_count == 1


def test_workflow_parser_covers_json_yaml_and_validation_errors():
    """
    验证工作流解析器的 JSON/YAML 路径和错误分支。
    """
    parser = WorkflowParser()
    parsed_json = parser.parse_definition('{"steps":[{"type":"tool"}]}', format_hint="json")
    parsed_yaml = parser.parse_definition(
        """
name: yaml_flow
steps:
  - type: condition
    expression: context.flag == True
    on_true:
      - type: tool
        action: read_file
        tool: file_manager
        params:
          path: demo.txt
"""
    )

    assert parsed_json["name"] == "unnamed_workflow"
    assert parsed_yaml["steps"][0]["on_true"][0]["id"] == "step_1"

    with pytest.raises(ValueError):
        parser.parse_definition("")
    with pytest.raises(ValueError):
        parser.parse_definition(["not", "a", "dict"])
    with pytest.raises(ValueError):
        parser.parse_definition({"steps": []})
    with pytest.raises(ValueError):
        parser.parse_definition({"steps": ["bad-step"]})


@pytest.mark.asyncio
async def test_workflow_engine_helper_and_error_paths(monkeypatch):
    """
    验证工作流引擎的占位符解析、条件校验、插件分支与失败记录路径。
    """
    fake_plugin_manager = FakePluginManager()
    monkeypatch.setattr("workflow.engine.plugin_instance.get", lambda: fake_plugin_manager)

    engine_without_db = WorkflowEngine(db_session=None, skill_engine=FakeSkillEngine())
    assert engine_without_db._create_execution_record(
        workflow_id=None,
        workflow_name="demo",
        user_id="user-1",
        input_context={},
    ) is None
    engine_without_db.sync_workflow_steps(1, [])

    runtime = {
        "context": {"name": "ok", "items": [{"value": 3}], "fallback": "ctx"},
        "steps": {"one": {"value": 1, "success": True}, "list_step": [{"name": "first"}]},
        "last_result": {"value": 99},
    }

    rendered = engine_without_db._render_data(
        {
            "plain": "text",
            "direct": "{{steps.one.value}}",
            "mixed": "name={{context.name}}",
            "list": "{{context.items.0.value}}",
        },
        runtime,
    )
    assert rendered == {"plain": "text", "direct": 1, "mixed": "name=ok", "list": 3}
    assert engine_without_db._resolve_placeholder("missing.value", runtime) is None
    assert engine_without_db._evaluate_condition("steps.one.value == 1 and context.name == 'ok'", runtime) is True
    with pytest.raises(ValueError):
        engine_without_db._evaluate_condition("len(context.items) > 0", runtime)

    with pytest.raises(ValueError):
        await engine_without_db._execute_condition_step({"id": "cond", "type": "condition", "expression": ""}, runtime)
    with pytest.raises(ValueError):
        await engine_without_db._execute_tool_step({"id": "tool", "type": "tool"}, runtime)
    with pytest.raises(ValueError):
        await engine_without_db._execute_step({"id": "unknown", "type": "nope"}, runtime)

    engine_no_skill = WorkflowEngine(db_session=None, skill_engine=None)
    with pytest.raises(RuntimeError):
        await engine_no_skill._execute_skill_step({"id": "skill", "type": "skill", "skill_name": "demo"}, runtime)

    engine_with_skill = WorkflowEngine(db_session=None, skill_engine=FakeSkillEngine())
    with pytest.raises(ValueError):
        await engine_with_skill._execute_skill_step({"id": "skill", "type": "skill"}, runtime)
    with pytest.raises(ValueError):
        await engine_with_skill._execute_plugin_step({"id": "plugin", "type": "plugin"}, runtime)

    failing_plugin_manager = FakePluginManager(load_result=False)
    engine_with_skill.plugin_manager = failing_plugin_manager
    with pytest.raises(RuntimeError):
        await engine_with_skill._execute_plugin_step(
            {"id": "plugin", "type": "plugin", "plugin_name": "demo", "plugin_method": "run"},
            runtime,
        )

    error_plugin_manager = FakePluginManager(execute_result={"status": "error", "message": "failed"})
    engine_with_skill.plugin_manager = error_plugin_manager
    plugin_result = await engine_with_skill._execute_plugin_step(
        {
            "id": "plugin",
            "type": "plugin",
            "plugin_name": "demo",
            "plugin_method": "run",
            "kwargs": {"value": "{{last_result.value}}"},
        },
        runtime,
    )
    assert plugin_result["success"] is False
    assert plugin_result["error"] == "failed"

    session = build_session()
    engine_with_db = WorkflowEngine(db_session=session, skill_engine=FakeSkillEngine())
    failed_result = await engine_with_db.execute_definition(
        {"name": "failed_flow", "steps": [{"id": "bad_tool", "type": "tool", "tool": "file_manager"}]},
        user_id="user-1",
    )

    assert failed_result["status"] == "failed"
    execution = session.query(WorkflowExecution).filter(WorkflowExecution.id == failed_result["execution_id"]).first()
    assert execution is not None
    assert execution.status == "failed"

    engine_with_db.sync_workflow_steps(11, [{"id": "step_a", "type": "tool", "tool": "file_manager", "action": "read_file"}])
    assert session.query(WorkflowStep).filter(WorkflowStep.workflow_id == 11).count() == 1
    session.close()