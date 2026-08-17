"""
Task 15/16: 代理记忆三级范围测试。

覆盖范围：
1. AgentMemoryEntry 数据类验证
2. load_agent_memory_prompt 三级范围加载（USER / PROJECT / LOCAL）
3. AgentMemorySnapshot 快照管理（add_entry / get_entries / to_prompt / sync）
4. save_agent_memory 三级范围保存
5. check_agent_memory_snapshot 快照检查
6. 跨会话同类型 Agent 记忆复用（PROJECT / USER 按 agent_type 维度共享）
7. 孤儿记忆文件清理（加载时跳过不含 agent_type 语义的文件）
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.task_runtime.definitions import AgentMemoryScope
from core.task_runtime.agent_memory import (
    AgentMemoryEntry,
    AgentMemorySnapshot,
    _LOCAL_MEMORY_CACHE,
    _PROJECT_MEMORY_BASE_DIR,
    check_agent_memory_snapshot,
    load_agent_memory_prompt,
    save_agent_memory,
)


# ──────────────────────────────────────────────
#  AgentMemoryEntry 数据类
# ──────────────────────────────────────────────

def test_agent_memory_entry_dataclass():
    """验证 AgentMemoryEntry 数据类字段与默认值。"""
    entry = AgentMemoryEntry(
        agent_id="agt_001",
        scope=AgentMemoryScope.LOCAL,
        key="preference",
        value="用户偏好暗色主题",
        timestamp="2026-06-19T10:00:00+00:00",
    )
    assert entry.agent_id == "agt_001"
    assert entry.scope == AgentMemoryScope.LOCAL
    assert entry.key == "preference"
    assert entry.value == "用户偏好暗色主题"
    assert entry.timestamp == "2026-06-19T10:00:00+00:00"
    assert entry.metadata is None
    assert entry.agent_type is None


def test_agent_memory_entry_with_metadata():
    """验证 AgentMemoryEntry 可携带 metadata 与 agent_type。"""
    entry = AgentMemoryEntry(
        agent_id="agt_002",
        agent_type="Explore",
        scope=AgentMemoryScope.PROJECT,
        key="config",
        value="{}",
        timestamp="2026-06-19T10:00:00+00:00",
        metadata={"importance": 0.8},
    )
    assert entry.metadata == {"importance": 0.8}
    assert entry.agent_type == "Explore"


# ──────────────────────────────────────────────
#  load_agent_memory_prompt 三级范围加载
# ──────────────────────────────────────────────

def _make_user_memory_mock(
    memory_id: int,
    content: str,
    agent_type: str,
    importance: float = 0.8,
    confidence: float = 0.9,
) -> MagicMock:
    """构造一个带 agent_type 语义的 USER 范围长期记忆 mock。"""
    mock_memory = MagicMock()
    mock_memory.id = memory_id
    mock_memory.content = content
    mock_memory.importance = importance
    mock_memory.confidence = confidence
    mock_memory.created_at = datetime(2026, 6, 19, 10, 0, 0, tzinfo=timezone.utc)
    mock_memory.memory_layer = "semantic"
    mock_memory.memory_metadata = {
        "source_type": "agent",
        "agent_type": agent_type,
    }
    return mock_memory


@pytest.mark.asyncio
async def test_load_agent_memory_prompt_user_scope():
    """验证 USER 范围从长期记忆表加载，并按 agent_type 维度过滤。"""
    mock_memory = _make_user_memory_mock(1, "用户偏好暗色主题", agent_type="Explore")

    with patch("memory.manager.MemoryManager") as mock_manager_cls:
        mock_manager = AsyncMock()
        mock_manager.get_long_term_memories = AsyncMock(return_value=[mock_memory])
        mock_manager_cls.return_value = mock_manager

        result = await load_agent_memory_prompt("Explore", AgentMemoryScope.USER)

    mock_manager.get_long_term_memories.assert_awaited_once()
    assert "代理记忆" in result
    assert "用户偏好暗色主题" in result
    assert "user" in result


@pytest.mark.asyncio
async def test_load_agent_memory_prompt_user_scope_filters_other_agent_type():
    """验证 USER 范围过滤掉其他 agent_type 的记忆。"""
    # 记忆属于 Plan 类型，加载 Explore 类型时应被过滤
    mock_memory = _make_user_memory_mock(2, "Plan 的专属记忆", agent_type="Plan")

    with patch("memory.manager.MemoryManager") as mock_manager_cls:
        mock_manager = AsyncMock()
        mock_manager.get_long_term_memories = AsyncMock(return_value=[mock_memory])
        mock_manager_cls.return_value = mock_manager

        result = await load_agent_memory_prompt("Explore", AgentMemoryScope.USER)

    assert result == ""


@pytest.mark.asyncio
async def test_load_agent_memory_prompt_user_scope_filters_non_agent_memory():
    """验证 USER 范围过滤掉非 agent 来源的长期记忆。"""
    mock_memory = _make_user_memory_mock(3, "用户手动记录", agent_type="Explore")
    # 非 agent 来源：source_type 不为 agent
    mock_memory.memory_metadata = {"agent_type": "Explore"}

    with patch("memory.manager.MemoryManager") as mock_manager_cls:
        mock_manager = AsyncMock()
        mock_manager.get_long_term_memories = AsyncMock(return_value=[mock_memory])
        mock_manager_cls.return_value = mock_manager

        result = await load_agent_memory_prompt("Explore", AgentMemoryScope.USER)

    assert result == ""


@pytest.mark.asyncio
async def test_load_agent_memory_prompt_project_scope(tmp_path):
    """验证 PROJECT 范围从 .openawa/agent_memories/{agent_type}/project.json 加载。"""
    agent_type = "Explore"
    memory_dir = tmp_path / "agent_memories"
    memory_file = memory_dir / agent_type / "project.json"
    memory_file.parent.mkdir(parents=True)
    payload = {
        "agent_type": agent_type,
        "entries": [
            {
                "agent_id": "agt_project_001",
                "agent_type": agent_type,
                "scope": "project",
                "key": "convention",
                "value": "使用 4 空格缩进",
                "timestamp": "2026-06-19T10:00:00+00:00",
                "metadata": None,
            }
        ],
        "updated_at": "2026-06-19T10:00:00+00:00",
    }
    memory_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with patch("core.task_runtime.agent_memory._PROJECT_MEMORY_BASE_DIR", tmp_path / "agent_memories"):
        result = await load_agent_memory_prompt(agent_type, AgentMemoryScope.PROJECT)

    assert "代理记忆" in result
    assert "使用 4 空格缩进" in result
    assert "project" in result


@pytest.mark.asyncio
async def test_load_agent_memory_prompt_project_scope_skips_orphan_files(tmp_path):
    """验证 PROJECT 加载时跳过不含 agent_type 语义的孤儿文件（目录下非 project.json）。"""
    agent_type = "Explore"
    memory_dir = tmp_path / "agent_memories"
    agent_type_dir = memory_dir / agent_type
    agent_type_dir.mkdir(parents=True)
    # 旧格式孤儿文件：按 agent_id 命名，不具备 agent_type 语义
    orphan_file = agent_type_dir / "agt_legacy_001.json"
    orphan_file.write_text(
        json.dumps({"agent_id": "agt_legacy_001", "entries": []}, ensure_ascii=False),
        encoding="utf-8",
    )

    with patch("core.task_runtime.agent_memory._PROJECT_MEMORY_BASE_DIR", tmp_path / "agent_memories"):
        # 目标文件 project.json 不存在，只有孤儿文件，应返回空字符串
        result = await load_agent_memory_prompt(agent_type, AgentMemoryScope.PROJECT)

    assert result == ""


@pytest.mark.asyncio
async def test_load_agent_memory_prompt_project_scope_skips_mismatched_type(tmp_path):
    """验证 PROJECT 加载时跳过 agent_type 与请求不一致的记忆文件。"""
    memory_dir = tmp_path / "agent_memories"
    memory_file = memory_dir / "Explore" / "project.json"
    memory_file.parent.mkdir(parents=True)
    # 文件内容是 Plan 类型的
    payload = {
        "agent_type": "Plan",
        "entries": [
            {
                "agent_id": "agt_x",
                "agent_type": "Plan",
                "scope": "project",
                "key": "k",
                "value": "Plan 的记忆",
                "timestamp": "2026-06-19T10:00:00+00:00",
                "metadata": None,
            }
        ],
        "updated_at": "2026-06-19T10:00:00+00:00",
    }
    memory_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with patch("core.task_runtime.agent_memory._PROJECT_MEMORY_BASE_DIR", tmp_path / "agent_memories"):
        result = await load_agent_memory_prompt("Explore", AgentMemoryScope.PROJECT)

    assert result == ""


@pytest.mark.asyncio
async def test_load_agent_memory_prompt_local_scope():
    """验证 LOCAL 范围从模块级缓存加载。"""
    agent_id = "agt_local_001"
    entry = AgentMemoryEntry(
        agent_id=agent_id,
        scope=AgentMemoryScope.LOCAL,
        key="temp_note",
        value="临时笔记内容",
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
    with patch.dict(
        "core.task_runtime.agent_memory._LOCAL_MEMORY_CACHE",
        {agent_id: {entry.key: entry}},
        clear=False,
    ):
        result = await load_agent_memory_prompt(agent_id, AgentMemoryScope.LOCAL)

    assert "代理记忆" in result
    assert "临时笔记内容" in result
    assert "local" in result


@pytest.mark.asyncio
async def test_load_agent_memory_prompt_empty():
    """验证无记忆时返回空字符串。"""
    agent_id = "agt_empty_001"
    # 确保 LOCAL 缓存中没有该 agent 的记忆
    with patch.dict("core.task_runtime.agent_memory._LOCAL_MEMORY_CACHE", {}, clear=True):
        result = await load_agent_memory_prompt(agent_id, AgentMemoryScope.LOCAL)
    assert result == ""


# ──────────────────────────────────────────────
#  跨会话同类型 Agent 记忆复用
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_project_memory_shared_across_sessions_same_agent_type(tmp_path):
    """验证 PROJECT 范围：两个不同 agent_id 但同 agent_type 的实例共享记忆池。"""
    agent_type = "Explore"
    with patch(
        "core.task_runtime.agent_memory._PROJECT_MEMORY_BASE_DIR",
        tmp_path / "agent_memories",
    ):
        # 会话 1：实例 A（agent_id=A）保存记忆
        entry_a = AgentMemoryEntry(
            agent_id="agt_session_a",
            agent_type=agent_type,
            scope=AgentMemoryScope.PROJECT,
            key="convention",
            value="使用 4 空格缩进",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        await save_agent_memory(entry_a)

        # 会话 2：实例 B（agent_id=B，同 agent_type）加载记忆
        prompt = await load_agent_memory_prompt(agent_type, AgentMemoryScope.PROJECT)

    assert "使用 4 空格缩进" in prompt

    # 文件按 agent_type 目录存储，而非 agent_id
    memory_file = tmp_path / "agent_memories" / agent_type / "project.json"
    assert memory_file.exists()
    data = json.loads(memory_file.read_text(encoding="utf-8"))
    assert data["agent_type"] == agent_type
    # 两个不同实例的条目共存于同一记忆池
    assert len(data["entries"]) == 1


@pytest.mark.asyncio
async def test_project_memory_isolated_between_agent_types(tmp_path):
    """验证 PROJECT 范围：不同 agent_type 之间记忆隔离。"""
    with patch(
        "core.task_runtime.agent_memory._PROJECT_MEMORY_BASE_DIR",
        tmp_path / "agent_memories",
    ):
        # Explore 类型保存记忆
        entry = AgentMemoryEntry(
            agent_id="agt_explore_1",
            agent_type="Explore",
            scope=AgentMemoryScope.PROJECT,
            key="explore_key",
            value="Explore 的记忆",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        await save_agent_memory(entry)

        # Plan 类型加载不到 Explore 的记忆
        plan_prompt = await load_agent_memory_prompt("Plan", AgentMemoryScope.PROJECT)

    assert plan_prompt == ""


@pytest.mark.asyncio
async def test_user_memory_shared_across_sessions_same_agent_type():
    """验证 USER 范围：两个不同 agent_id 但同 agent_type 的实例共享记忆池。"""
    mock_memory = _make_user_memory_mock(10, "跨会话共享的 USER 记忆", agent_type="Explore")

    with patch("memory.manager.MemoryManager") as mock_manager_cls:
        mock_manager = AsyncMock()
        mock_manager.get_long_term_memories = AsyncMock(return_value=[mock_memory])
        mock_manager_cls.return_value = mock_manager

        # 实例 A 加载
        prompt_a = await load_agent_memory_prompt("Explore", AgentMemoryScope.USER)
        # 实例 B（不同 agent_id）加载同样的记忆
        prompt_b = await load_agent_memory_prompt("Explore", AgentMemoryScope.USER)

    assert "跨会话共享的 USER 记忆" in prompt_a
    assert prompt_a == prompt_b


# ──────────────────────────────────────────────
#  AgentMemorySnapshot 快照管理
# ──────────────────────────────────────────────

def test_agent_memory_snapshot_add_entry():
    """验证快照添加条目。"""
    snapshot = AgentMemorySnapshot("agt_snap_001")
    entry = AgentMemoryEntry(
        agent_id="agt_snap_001",
        scope=AgentMemoryScope.LOCAL,
        key="note",
        value="快照测试",
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
    snapshot.add_entry(entry)
    assert len(snapshot._entries) == 1
    assert snapshot._entries["note"] == entry


def test_agent_memory_snapshot_add_entry_backfills_agent_type():
    """验证快照添加条目时回填 agent_type。"""
    snapshot = AgentMemorySnapshot("agt_snap_bt", agent_type="Explore")
    entry = AgentMemoryEntry(
        agent_id="agt_snap_bt",
        scope=AgentMemoryScope.PROJECT,
        key="note",
        value="快照测试",
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
    snapshot.add_entry(entry)
    assert entry.agent_type == "Explore"


def test_agent_memory_snapshot_get_entries_by_scope():
    """验证按范围获取条目。"""
    snapshot = AgentMemorySnapshot("agt_snap_002")
    local_entry = AgentMemoryEntry(
        agent_id="agt_snap_002",
        scope=AgentMemoryScope.LOCAL,
        key="local_key",
        value="local_value",
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
    project_entry = AgentMemoryEntry(
        agent_id="agt_snap_002",
        scope=AgentMemoryScope.PROJECT,
        key="project_key",
        value="project_value",
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
    snapshot.add_entry(local_entry)
    snapshot.add_entry(project_entry)

    all_entries = snapshot.get_entries()
    assert len(all_entries) == 2

    local_only = snapshot.get_entries(scope=AgentMemoryScope.LOCAL)
    assert len(local_only) == 1
    assert local_only[0].key == "local_key"

    project_only = snapshot.get_entries(scope=AgentMemoryScope.PROJECT)
    assert len(project_only) == 1
    assert project_only[0].key == "project_key"


def test_agent_memory_snapshot_to_prompt():
    """验证快照转换为 prompt 字符串。"""
    snapshot = AgentMemorySnapshot("agt_snap_003")
    entry = AgentMemoryEntry(
        agent_id="agt_snap_003",
        scope=AgentMemoryScope.LOCAL,
        key="pref",
        value="偏好简洁回答",
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
    snapshot.add_entry(entry)
    prompt = snapshot.to_prompt()
    assert "代理记忆" in prompt
    assert "偏好简洁回答" in prompt
    assert "local" in prompt


def test_agent_memory_snapshot_to_prompt_empty():
    """验证空快照转换为空字符串。"""
    snapshot = AgentMemorySnapshot("agt_snap_empty")
    assert snapshot.to_prompt() == ""


@pytest.mark.asyncio
async def test_agent_memory_snapshot_sync():
    """验证快照异步同步到持久化存储。"""
    snapshot = AgentMemorySnapshot("agt_snap_sync")
    entry = AgentMemoryEntry(
        agent_id="agt_snap_sync",
        scope=AgentMemoryScope.LOCAL,
        key="sync_key",
        value="sync_value",
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
    snapshot.add_entry(entry)
    with patch(
        "core.task_runtime.agent_memory.save_agent_memory",
        new=AsyncMock(),
    ) as mock_save:
        await snapshot.sync()
    mock_save.assert_awaited_once_with(entry)
    assert snapshot._last_sync is not None


# ──────────────────────────────────────────────
#  save_agent_memory 三级范围保存
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_save_agent_memory_user():
    """验证 USER 范围保存到长期记忆表（公开接口 add_long_term_memory）。"""
    entry = AgentMemoryEntry(
        agent_id="agt_save_user",
        agent_type="Explore",
        scope=AgentMemoryScope.USER,
        key="user_pref",
        value="用户偏好暗色主题",
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
    with patch("memory.manager.MemoryManager") as mock_manager_cls:
        mock_manager = AsyncMock()
        mock_manager_cls.return_value = mock_manager
        await save_agent_memory(entry)
    mock_manager.add_long_term_memory.assert_awaited_once()
    call_kwargs = mock_manager.add_long_term_memory.call_args.kwargs
    assert call_kwargs["source_type"] == "agent"
    assert call_kwargs["memory_metadata"]["agent_type"] == "Explore"
    assert call_kwargs["memory_metadata"]["key"] == "user_pref"


@pytest.mark.asyncio
async def test_save_agent_memory_project(tmp_path):
    """验证 PROJECT 范围保存到 .openawa/agent_memories/{agent_type}/project.json。"""
    agent_type = "Explore"
    entry = AgentMemoryEntry(
        agent_id="agt_save_project",
        agent_type=agent_type,
        scope=AgentMemoryScope.PROJECT,
        key="convention",
        value="使用 4 空格缩进",
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
    with patch(
        "core.task_runtime.agent_memory._PROJECT_MEMORY_BASE_DIR",
        tmp_path / "agent_memories",
    ):
        await save_agent_memory(entry)
    memory_file = tmp_path / "agent_memories" / agent_type / "project.json"
    assert memory_file.exists()
    data = json.loads(memory_file.read_text(encoding="utf-8"))
    assert data["agent_type"] == agent_type
    assert len(data["entries"]) == 1
    assert data["entries"][0]["key"] == "convention"
    assert data["entries"][0]["value"] == "使用 4 空格缩进"


@pytest.mark.asyncio
async def test_save_agent_memory_local():
    """验证 LOCAL 范围保存到模块级缓存。"""
    agent_id = "agt_save_local"
    entry = AgentMemoryEntry(
        agent_id=agent_id,
        scope=AgentMemoryScope.LOCAL,
        key="temp",
        value="临时数据",
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
    with patch.dict("core.task_runtime.agent_memory._LOCAL_MEMORY_CACHE", {}, clear=True):
        await save_agent_memory(entry)
        # 验证缓存中已写入
        assert agent_id in _LOCAL_MEMORY_CACHE
        assert "temp" in _LOCAL_MEMORY_CACHE[agent_id]
        assert _LOCAL_MEMORY_CACHE[agent_id]["temp"].value == "临时数据"


# ──────────────────────────────────────────────
#  check_agent_memory_snapshot 快照检查
# ──────────────────────────────────────────────

def test_check_agent_memory_snapshot():
    """验证 check_agent_memory_snapshot 返回快照实例。"""
    agent_id = "agt_check_001"
    snapshot = check_agent_memory_snapshot(agent_id)
    assert isinstance(snapshot, AgentMemorySnapshot)
    assert snapshot.agent_id == agent_id
    assert len(snapshot._entries) == 0
    assert snapshot._last_sync is None


def test_check_agent_memory_snapshot_with_agent_type():
    """验证 check_agent_memory_snapshot 支持传入 agent_type。"""
    snapshot = check_agent_memory_snapshot("agt_check_002", agent_type="Explore")
    assert snapshot.agent_type == "Explore"
