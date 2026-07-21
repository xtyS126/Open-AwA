"""
JSONL 旁路日志测试模块，验证 JsonlTranscriptWriter 写入与 replay_transcript 回放行为。
覆盖单行写入、多行写入、父链关系、回放一致性、目录自动创建等场景。
"""

import json
from pathlib import Path

import pytest

from core.conversation_recorder import JsonlTranscriptWriter, replay_transcript


def test_append_writes_jsonl_line(tmp_path: Path) -> None:
    """
    验证 append 写入一行合法 JSON 到 JSONL 文件。
    """
    base_dir = str(tmp_path / "transcripts")
    writer = JsonlTranscriptWriter(session_id="session-1", base_dir=base_dir)

    writer.append(
        uuid="msg-1",
        parent_uuid=None,
        type="user",
        content="你好",
        timestamp="2026-01-01T00:00:00+00:00",
    )
    writer.close()

    file_path = tmp_path / "transcripts" / "session-1.jsonl"
    assert file_path.exists()

    lines = file_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1

    record = json.loads(lines[0])
    assert record["uuid"] == "msg-1"
    assert record["parent_uuid"] is None
    assert record["type"] == "user"
    assert record["content"] == "你好"
    assert record["timestamp"] == "2026-01-01T00:00:00+00:00"


def test_append_multiple_lines(tmp_path: Path) -> None:
    """
    验证多次 append 写入多行 JSON，每行独立可解析。
    """
    base_dir = str(tmp_path / "transcripts")
    writer = JsonlTranscriptWriter(session_id="session-2", base_dir=base_dir)

    writer.append(
        uuid="msg-a",
        parent_uuid=None,
        type="user",
        content="第一条消息",
        timestamp="2026-01-01T00:00:00+00:00",
    )
    writer.append(
        uuid="msg-b",
        parent_uuid="msg-a",
        type="assistant",
        content="第二条消息",
        timestamp="2026-01-01T00:00:01+00:00",
    )
    writer.append(
        uuid="msg-c",
        parent_uuid="msg-b",
        type="tool",
        content={"tool": "search", "result": "ok"},
        timestamp="2026-01-01T00:00:02+00:00",
    )
    writer.close()

    file_path = tmp_path / "transcripts" / "session-2.jsonl"
    lines = file_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3

    uuids = [json.loads(line)["uuid"] for line in lines]
    assert uuids == ["msg-a", "msg-b", "msg-c"]


def test_parent_uuid_chain(tmp_path: Path) -> None:
    """
    验证 parent_uuid 形成父链：每条消息的 parent_uuid 指向前一条消息的 uuid。
    """
    base_dir = str(tmp_path / "transcripts")
    writer = JsonlTranscriptWriter(session_id="session-3", base_dir=base_dir)

    # 构造一条父链：root -> child1 -> child2
    writer.append(
        uuid="root",
        parent_uuid=None,
        type="user",
        content="根消息",
        timestamp="2026-01-01T00:00:00+00:00",
    )
    writer.append(
        uuid="child1",
        parent_uuid="root",
        type="assistant",
        content="子消息1",
        timestamp="2026-01-01T00:00:01+00:00",
    )
    writer.append(
        uuid="child2",
        parent_uuid="child1",
        type="tool",
        content="子消息2",
        timestamp="2026-01-01T00:00:02+00:00",
    )
    writer.close()

    messages = replay_transcript("session-3", base_dir=base_dir)
    assert len(messages) == 3

    # 根消息 parent_uuid 为 None
    assert messages[0]["uuid"] == "root"
    assert messages[0]["parent_uuid"] is None

    # child1 的 parent_uuid 指向 root
    assert messages[1]["uuid"] == "child1"
    assert messages[1]["parent_uuid"] == "root"

    # child2 的 parent_uuid 指向 child1
    assert messages[2]["uuid"] == "child2"
    assert messages[2]["parent_uuid"] == "child1"

    # 验证父链可追溯：从最后一条消息沿 parent_uuid 回溯到根
    uuid_to_parent = {m["uuid"]: m["parent_uuid"] for m in messages}
    chain: list[str] = []
    current = "child2"
    while current is not None:
        chain.append(current)
        current = uuid_to_parent[current]
    assert chain == ["child2", "child1", "root"]


def test_replay_transcript_returns_messages(tmp_path: Path) -> None:
    """
    验证 replay_transcript 返回消息列表，且顺序与写入顺序一致。
    """
    base_dir = str(tmp_path / "transcripts")
    writer = JsonlTranscriptWriter(session_id="session-4", base_dir=base_dir)

    writer.append(
        uuid="u-1",
        parent_uuid=None,
        type="user",
        content="hello",
        timestamp="2026-01-01T00:00:00+00:00",
    )
    writer.append(
        uuid="u-2",
        parent_uuid="u-1",
        type="assistant",
        content="hi",
        timestamp="2026-01-01T00:00:01+00:00",
    )
    writer.close()

    messages = replay_transcript("session-4", base_dir=base_dir)
    assert isinstance(messages, list)
    assert len(messages) == 2
    assert messages[0]["uuid"] == "u-1"
    assert messages[1]["uuid"] == "u-2"


def test_replay_transcript_empty_for_missing_file(tmp_path: Path) -> None:
    """
    验证文件不存在时 replay_transcript 返回空列表，不抛出异常。
    """
    base_dir = str(tmp_path / "transcripts")
    # 不创建任何文件，直接回放
    messages = replay_transcript("nonexistent-session", base_dir=base_dir)
    assert messages == []
    assert isinstance(messages, list)


def test_replay_transcript_roundtrip(tmp_path: Path) -> None:
    """
    验证写入后回放的数据一致性：字段、类型、内容完全匹配。
    """
    base_dir = str(tmp_path / "transcripts")
    writer = JsonlTranscriptWriter(session_id="session-5", base_dir=base_dir)

    original_messages = [
        {
            "uuid": "rt-1",
            "parent_uuid": None,
            "type": "user",
            "content": "roundtrip 测试",
            "timestamp": "2026-01-01T00:00:00+00:00",
        },
        {
            "uuid": "rt-2",
            "parent_uuid": "rt-1",
            "type": "assistant",
            "content": {"text": "回复", "tokens": 10},
            "timestamp": "2026-01-01T00:00:01+00:00",
        },
        {
            "uuid": "rt-3",
            "parent_uuid": "rt-2",
            "type": "tool",
            "content": ["item1", "item2"],
            "timestamp": "2026-01-01T00:00:02+00:00",
        },
    ]

    for msg in original_messages:
        writer.append(
            uuid=msg["uuid"],
            parent_uuid=msg["parent_uuid"],
            type=msg["type"],
            content=msg["content"],
            timestamp=msg["timestamp"],
        )
    writer.close()

    replayed = replay_transcript("session-5", base_dir=base_dir)

    assert len(replayed) == len(original_messages)
    for original, replayed_msg in zip(original_messages, replayed):
        assert replayed_msg["uuid"] == original["uuid"]
        assert replayed_msg["parent_uuid"] == original["parent_uuid"]
        assert replayed_msg["type"] == original["type"]
        assert replayed_msg["content"] == original["content"]
        assert replayed_msg["timestamp"] == original["timestamp"]


def test_jsonl_writer_creates_directory(tmp_path: Path) -> None:
    """
    验证目录不存在时 JsonlTranscriptWriter 自动创建目录及文件。
    """
    # 使用嵌套目录路径，确保父目录也不存在
    base_dir = str(tmp_path / "nested" / "deep" / "transcripts")
    nested_dir = tmp_path / "nested"
    assert not nested_dir.exists()

    writer = JsonlTranscriptWriter(session_id="session-6", base_dir=base_dir)
    writer.append(
        uuid="dir-1",
        parent_uuid=None,
        type="system",
        content="目录创建测试",
        timestamp="2026-01-01T00:00:00+00:00",
    )
    writer.close()

    # 目录已自动创建
    assert (tmp_path / "nested" / "deep" / "transcripts").is_dir()
    # 文件已创建且包含内容
    file_path = tmp_path / "nested" / "deep" / "transcripts" / "session-6.jsonl"
    assert file_path.exists()

    lines = file_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["uuid"] == "dir-1"


def test_append_default_timestamp(tmp_path: Path) -> None:
    """
    验证未提供 timestamp 时自动生成 ISO 8601 格式时间戳。
    """
    base_dir = str(tmp_path / "transcripts")
    writer = JsonlTranscriptWriter(session_id="session-7", base_dir=base_dir)

    writer.append(
        uuid="ts-1",
        parent_uuid=None,
        type="user",
        content="默认时间戳测试",
    )
    writer.close()

    messages = replay_transcript("session-7", base_dir=base_dir)
    assert len(messages) == 1
    timestamp = messages[0]["timestamp"]
    # ISO 8601 格式应包含时区偏移或 T 分隔符
    assert isinstance(timestamp, str)
    assert "T" in timestamp


def test_writer_close_prevents_further_append(tmp_path: Path) -> None:
    """
    验证 close 后再次 append 抛出 RuntimeError，防止误写。
    """
    base_dir = str(tmp_path / "transcripts")
    writer = JsonlTranscriptWriter(session_id="session-8", base_dir=base_dir)
    writer.append(
        uuid="c-1",
        parent_uuid=None,
        type="user",
        content="关闭前写入",
        timestamp="2026-01-01T00:00:00+00:00",
    )
    writer.close()

    with pytest.raises(RuntimeError):
        writer.append(
            uuid="c-2",
            parent_uuid="c-1",
            type="assistant",
            content="关闭后写入",
            timestamp="2026-01-01T00:00:01+00:00",
        )

    # 确认只有关闭前的一行被写入
    messages = replay_transcript("session-8", base_dir=base_dir)
    assert len(messages) == 1
    assert messages[0]["uuid"] == "c-1"


def test_append_preserves_non_ascii_content(tmp_path: Path) -> None:
    """
    验证 ensure_ascii=False 保留中文等非 ASCII 字符的可读性。
    """
    base_dir = str(tmp_path / "transcripts")
    writer = JsonlTranscriptWriter(session_id="session-9", base_dir=base_dir)

    chinese_content = "你好世界，Open-AwA 测试"
    writer.append(
        uuid="zh-1",
        parent_uuid=None,
        type="user",
        content=chinese_content,
        timestamp="2026-01-01T00:00:00+00:00",
    )
    writer.close()

    file_path = tmp_path / "transcripts" / "session-9.jsonl"
    raw_text = file_path.read_text(encoding="utf-8")
    # ensure_ascii=False 时中文字符应原样存在于文件中
    assert chinese_content in raw_text

    messages = replay_transcript("session-9", base_dir=base_dir)
    assert messages[0]["content"] == chinese_content
