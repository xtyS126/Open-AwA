"""显式选择长期记忆时的顺序、隔离和 Agent 注入测试。"""

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.agent import AIAgent
from db.models import Base, LongTermMemory
from memory.manager import MemoryManager


engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base.metadata.create_all(bind=engine)


def setup_function() -> None:
    db = TestingSessionLocal()
    try:
        db.query(LongTermMemory).delete()
        db.commit()
    finally:
        db.close()


@pytest.mark.asyncio
async def test_get_memories_by_ids_preserves_order_and_visibility() -> None:
    """显式读取必须按请求顺序返回，且过滤其他用户和工作区。"""
    db = TestingSessionLocal()
    try:
        first = LongTermMemory(
            user_id="user-1",
            workspace_id="workspace-1",
            content="第一条",
            archive_status="active",
            state="active",
        )
        second = LongTermMemory(
            user_id="user-1",
            workspace_id="workspace-1",
            content="第二条",
            archive_status="active",
            state="validated",
        )
        foreign = LongTermMemory(
            user_id="user-2",
            workspace_id="workspace-1",
            content="不可见",
            archive_status="active",
            state="active",
        )
        archived = LongTermMemory(
            user_id="user-1",
            workspace_id="workspace-1",
            content="已归档",
            archive_status="archived",
            state="active",
        )
        deprecated = LongTermMemory(
            user_id="user-1",
            workspace_id="workspace-1",
            content="已废弃",
            archive_status="deprecated",
            state="active",
        )
        db.add_all([first, second, foreign, archived, deprecated])
        db.commit()
        db.refresh(first)
        db.refresh(second)
        db.refresh(foreign)
        db.refresh(archived)
        db.refresh(deprecated)
        requested_ids = [
            int(second.id),
            int(first.id),
            int(foreign.id),
            int(archived.id),
            int(deprecated.id),
        ]
    finally:
        db.close()

    manager = object.__new__(MemoryManager)
    manager.session_factory = TestingSessionLocal

    memories = await manager.get_memories_by_ids(
        requested_ids,
        user_id="user-1",
        workspace_id="workspace-1",
    )

    assert [memory.content for memory in memories] == ["第二条", "第一条"]


@pytest.mark.asyncio
async def test_agent_merges_selected_memories_before_workspace_search() -> None:
    """显式记忆排在相关性结果之前，并按 ID 去重合并。"""
    class _MemoryManagerStub:
        def __init__(self) -> None:
            self.selected_call = None
            self.search_call = None

        async def get_memories_by_ids(self, memory_ids, user_id, workspace_id):
            self.selected_call = {
                "memory_ids": memory_ids,
                "user_id": user_id,
                "workspace_id": workspace_id,
            }
            return [
                SimpleNamespace(
                    id=memory_ids[0],
                    content="显式记忆",
                    importance=0.9,
                    confidence=0.8,
                    quality_score=0.7,
                )
            ]

        async def search_memories(self, **kwargs):
            self.search_call = kwargs
            return [
                SimpleNamespace(
                    id=42,
                    content="重复记忆",
                    importance=0.8,
                    confidence=0.7,
                    quality_score=0.6,
                ),
                SimpleNamespace(
                    id=43,
                    content="相关记忆",
                    importance=0.7,
                    confidence=0.6,
                    quality_score=0.5,
                ),
            ]

    manager = _MemoryManagerStub()
    agent = object.__new__(AIAgent)
    agent.memory_manager = manager

    result = await agent._retrieve_relevant_memories(
        "不会用于自动搜索",
        {
            "user_id": "user-1",
            "workspace_id": "workspace-1",
            "selected_memory_ids": [42],
        },
    )

    assert manager.selected_call == {
        "memory_ids": [42],
        "user_id": "user-1",
        "workspace_id": "workspace-1",
    }
    assert manager.search_call == {
        "query": "不会用于自动搜索",
        "limit": 5,
        "user_id": "user-1",
        "include_archived": False,
        "use_vector": True,
        "workspace_id": "workspace-1",
    }
    assert [memory["id"] for memory in result] == [42, 43]
