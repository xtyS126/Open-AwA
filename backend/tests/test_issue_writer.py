# -*- coding: utf-8 -*-
"""
问题反馈只写器单元测试。

覆盖：
1. write_issue 创建文件
2. 返回 file_id 格式匹配 timestamp_uuid
3. 文件内容包含所有 payload 字段
4. writer.py 源码不含读取/删除/列举文件的 API（静态源码扫描）
"""

import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from issue_writer import write_issue
from issue_writer import writer as writer_module


# ==================== 测试数据 ====================

_PAYLOAD = {
    "issue_type": "bug",
    "title": "测试标题",
    "content": "测试内容",
    "page_url": "/test",
    "submitted_at": "2026-07-10T00:00:00Z",
    "user_id_hash": "sha256:abc",
}


# ==================== 测试用例 ====================


def test_write_issue_creates_file(monkeypatch, tmp_path):
    """write_issue 应在目标目录创建一个 .json 文件。"""
    monkeypatch.setattr(writer_module, "_ISSUE_DIR", tmp_path)
    write_issue(_PAYLOAD)
    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1


def test_write_issue_returns_file_id(monkeypatch, tmp_path):
    """返回的 file_id 应匹配 timestamp_uuid 格式。"""
    monkeypatch.setattr(writer_module, "_ISSUE_DIR", tmp_path)
    file_id = write_issue(_PAYLOAD)
    assert re.match(r"^\d{8}_\d{6}_[a-f0-9]{8}$", file_id)


def test_write_issue_file_content(monkeypatch, tmp_path):
    """生成的文件应包含所有 payload 字段。"""
    monkeypatch.setattr(writer_module, "_ISSUE_DIR", tmp_path)
    file_id = write_issue(_PAYLOAD)
    file_path = tmp_path / f"{file_id}.json"
    content = json.loads(file_path.read_text(encoding="utf-8"))
    assert content["issue_type"] == "bug"
    assert content["title"] == "测试标题"
    assert content["content"] == "测试内容"
    assert content["page_url"] == "/test"
    assert content["submitted_at"] == "2026-07-10T00:00:00Z"
    assert content["user_id_hash"] == "sha256:abc"


def test_write_issue_no_read_api():
    """writer.py 源码不得包含读取/删除/列举文件的 API。"""
    source_path = Path(__file__).resolve().parents[1] / "issue_writer" / "writer.py"
    source = source_path.read_text(encoding="utf-8")
    forbidden = [
        "read_text",
        "read_bytes",
        "iterdir",
        "glob",
        "unlink",
        "rmdir",
        "os.remove",
        "os.listdir",
        "os.stat",
        "shutil",
        "Path.exists",
        "Path.replace",
        "Path.rename",
        "os.scandir",
        "open(",
    ]
    for keyword in forbidden:
        assert keyword not in source, f"writer.py 源码禁止包含 {keyword}"
