"""
记忆增强与工作流引擎测试。
覆盖长期记忆的混合检索、归档、统计，以及工作流执行的顺序与条件分支逻辑。
"""

import math
import shutil
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from db.models import LongTermMemory, init_db
from memory.manager import MemoryManager
from memory.vector_store_manager import VectorStoreManager
from tools.registry import built_in_tool_registry
from workflow.engine import WorkflowEngine


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


def build_session():
    """
    创建独立的内存数据库会话。
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    init_db(bind_engine=engine)
    session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return session_local()


@pytest.mark.asyncio
async def test_memory_manager_hybrid_search_archive_and_stats(tmp_path):
    """
    验证长期记忆支持混合搜索、质量评估、归档与统计。
    """
    session = build_session()
    MemoryManager._shared_vector_store = VectorStoreManager(
        persist_directory=str(tmp_path / "memory_vector_db"),
        collection_name=f"memory_{uuid.uuid4().hex}",
        embedding_provider=SemanticTestEmbeddingProvider(),
    )
    manager = MemoryManager(session)

    ml_memory = await manager.add_long_term_memory(
        content="过拟合问题通常需要配合正则化技术处理",
        importance=0.9,
        user_id="user-1",
        memory_metadata={"source_type": "document"},
    )
    await manager.add_long_term_memory(
        content="数据库索引可以提升查询性能",
        importance=0.4,
        user_id="user-1",
        memory_metadata={"source_type": "manual"},
    )

    hits = await manager.search_memories("机器学习中的过拟合问题", user_id="user-1", limit=5)
    quality_report = await manager.get_quality_report(user_id="user-1")

    assert hits
    assert hits[0].id == ml_memory.id
    assert quality_report
    assert quality_report[0]["quality_score"] >= 0.0

    stale_memory = session.query(LongTermMemory).filter(LongTermMemory.id == ml_memory.id).first()
    stale_memory.last_access = datetime.now(timezone.utc) - timedelta(days=45)
    stale_memory.importance = 0.1
    stale_memory.confidence = 0.1
    stale_memory.access_count = 30
    session.commit()

    archived_count = await manager.archive_memories(user_id="user-1")
    stats = await manager.get_memory_stats(user_id="user-1")

    assert archived_count >= 1
    assert stats["archived_memories"] >= 1
    assert stats["vector_store_count"] == 2
    assert stats["embedding_provider"] == "test-semantic"

    session.close()


@pytest.mark.asyncio
async def test_workflow_engine_executes_tool_and_condition_steps(tmp_path):
    """
    验证工作流引擎支持文件工具步骤和条件分支。
    """
    session = build_session()
    built_in_tool_registry._instances.clear()
    engine = WorkflowEngine(db_session=session)

    workdir = tmp_path / "workflow_tool"
    workdir.mkdir(parents=True, exist_ok=True)
    source_file = workdir / "source.txt"
    target_file = workdir / "target.txt"
    source_file.write_text("hello workflow", encoding="utf-8")

    definition = {
        "name": "tool_pipeline",
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
                "id": "branch_write",
                "type": "condition",
                "expression": "steps.read_source.success == True",
                "on_true": [
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
                    }
                ],
                "on_false": [],
            },
        ],
    }

    result = await engine.execute_definition(definition, user_id="user-1")

    assert result["status"] == "completed"
    assert target_file.read_text(encoding="utf-8") == "hello workflow"
    session.close()


@pytest.mark.asyncio
async def test_workflow_engine_executes_built_in_skill_step(tmp_path):
    """
    验证工作流引擎可通过技能步骤调用已注册的内置工具技能。
    """
    session = build_session()
    built_in_tool_registry.seed_built_in_skills(session)
    built_in_tool_registry._instances.clear()

    engine = WorkflowEngine(db_session=session)
    workdir = Path.cwd() / ".pytest_workflow_skill"
    if workdir.exists():
        shutil.rmtree(workdir)
    workdir.mkdir(parents=True, exist_ok=True)

    try:
        source_file = workdir / "skill_source.txt"
        target_file = workdir / "skill_target.txt"
        source_file.write_text("skill based workflow", encoding="utf-8")

        definition = {
            "name": "skill_pipeline",
            "steps": [
                {
                    "id": "read_via_skill",
                    "type": "skill",
                    "skill_name": "file_manager",
                    "inputs": {
                        "action": "read_file",
                        "params": {"path": str(source_file)},
                    },
                },
                {
                    "id": "write_via_tool",
                    "type": "tool",
                    "tool": "file_manager",
                    "action": "write_file",
                    "config": {"allowed_directories": [str(workdir)]},
                    "params": {
                        "path": str(target_file),
                        "content": "{{steps.read_via_skill.outputs.content}}",
                    },
                },
            ],
        }

        result = await engine.execute_definition(definition, user_id="user-1")

        assert result["status"] == "completed"
        assert target_file.read_text(encoding="utf-8") == "skill based workflow"
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
        session.close()