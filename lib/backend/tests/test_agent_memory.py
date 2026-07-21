"""
Task 15: 代理记忆三级范围测试。

覆盖范围：
1. AgentMemoryEntry 数据类验证
2. load_agent_memory_prompt 三级范围加载（USER / PROJECT / LOCAL）
3. AgentMemorySnapshot 快照管理（add_entry / get_entries / to_prompt / sync）
4. save_agent_memory 三级范围保存
5. check_agent_memory_snapshot 快照检查
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

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


def test_agent_memory_entry_with_metadata():
    """验证 AgentMemoryEntry 可携带 metadata。"""
    entry = AgentMemoryEntry(
        agent_id="agt_002",
        scope=AgentMemoryScope.PROJECT,
        key="config",
        value="{}",
        timestamp="2026-06-19T10:00:00+00:00",
        metadata={"importance": 0.8},
    )
    assert entry.metadata == {"importance": 0.8}


# ──────────────────────────────────────────────
#  load_agent_memory_prompt 三级范围加载
# ──────────────────────────────────────────────

def test_load_agent_memory_prompt_user_scope():
    """验证 USER 范围从长期记忆表加载。"""
    mock_memory = MagicMock()
    mock_memory.id = 1
    mock_memory.content = "用户偏好暗色主题"
    mock_memory.importance = 0.8
    mock_memory.confidence = 0.9
    mock_memory.created_at = datetime(2026, 6, 19, 10, 0, 0, tzinfo=timezone.utc)
    mock_memory.memory_layer = "semantic"

    with patch("memory.manager.MemoryManager") as mock_manager_cls:
        mock_manager = MagicMock()
        mock_manager._get_and_evaluate_long_term_memories_sync.return_value = [mock_memory]
        mock_manager_cls.return_value = mock_manager

        result = load_agent_memory_prompt("agt_001", AgentMemoryScope.USER)

    assert "代理记忆" in result
    assert "用户偏好暗色主题" in result
    assert "user" in result


def test_load_agent_memory_prompt_project_scope(tmp_path):
    """验证 PROJECT 范围从 .openawa/agent_memories/{agent_id}.json 加载。"""
    agent_id = "agt_project_001"
    memory_dir = tmp_path / "agent_memories"
    memory_dir.mkdir()
    memory_file = memory_dir / f"{agent_id}.json"
    payload = {
        "agent_id": agent_id,
        "entries": [
            {
                "agent_id": agent_id,
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
        result = load_agent_memory_prompt(agent_id, AgentMemoryScope.PROJECT)

    assert "代理记忆" in result
    assert "使用 4 空格缩进" in result
    assert "project" in result


def test_load_agent_memory_prompt_local_scope():
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
        result = load_agent_memory_prompt(agent_id, AgentMemoryScope.LOCAL)

    assert "代理记忆" in result
    assert "临时笔记内容" in result
    assert "local" in result


def test_load_agent_memory_prompt_empty():
    """验证无记忆时返回空字符串。"""
    agent_id = "agt_empty_001"
    # 确保 LOCAL 缓存中没有该 agent 的记忆
    with patch.dict("core.task_runtime.agent_memory._LOCAL_MEMORY_CACHE", {}, clear=True):
        result = load_agent_memory_prompt(agent_id, AgentMemoryScope.LOCAL)
    assert result == ""


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
    with patch("core.task_runtime.agent_memory.save_agent_memory") as mock_save:
        await snapshot.sync()
    mock_save.assert_called_once_with(entry)
    assert snapshot._last_sync is not None


# ──────────────────────────────────────────────
#  save_agent_memory 三级范围保存
# ──────────────────────────────────────────────

def test_save_agent_memory_user():
    """验证 USER 范围保存到长期记忆表。"""
    entry = AgentMemoryEntry(
        agent_id="agt_save_user",
        scope=AgentMemoryScope.USER,
        key="user_pref",
        value="用户偏好暗色主题",
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
    with patch("memory.manager.MemoryManager") as mock_manager_cls:
        mock_manager = MagicMock()
        mock_manager_cls.return_value = mock_manager
        save_agent_memory(entry)
    mock_manager._add_long_term_memory_sync.assert_called_once()


def test_save_agent_memory_project(tmp_path):
    """验证 PROJECT 范围保存到 .openawa/agent_memories/{agent_id}.json。"""
    agent_id = "agt_save_project"
    entry = AgentMemoryEntry(
        agent_id=agent_id,
        scope=AgentMemoryScope.PROJECT,
        key="convention",
        value="使用 4 空格缩进",
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
    with patch(
        "core.task_runtime.agent_memory._PROJECT_MEMORY_BASE_DIR",
        tmp_path / "agent_memories",
    ):
        save_agent_memory(entry)
    memory_file = tmp_path / "agent_memories" / f"{agent_id}.json"
    assert memory_file.exists()
    data = json.loads(memory_file.read_text(encoding="utf-8"))
    assert len(data["entries"]) == 1
    assert data["entries"][0]["key"] == "convention"
    assert data["entries"][0]["value"] == "使用 4 空格缩进"


def test_save_agent_memory_local():
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
        save_agent_memory(entry)
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
