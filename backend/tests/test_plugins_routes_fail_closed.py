"""
插件路由辅助函数 fail-closed 测试（删除兜底后的错误路径）。

覆盖：
- _read_json_file：文件存在但内容非法（解析失败 / 非对象）时必须抛异常显式报错，
  禁止静默降级为 None（plugins.py 曾吞掉解析异常返回 None）。
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.routes.plugins import _read_json_file


def test_read_json_file_returns_none_when_file_missing(tmp_path):
    """文件不存在返回 None（表示无该文件），这是显式语义而非异常降级。"""
    assert _read_json_file(str(tmp_path / "missing.json")) is None


def test_read_json_file_raises_on_parse_error(tmp_path):
    """JSON 解析失败必须抛异常，禁止静默降级为 None。"""
    broken = tmp_path / "broken.json"
    broken.write_text("{ not valid json", encoding="utf-8")
    with pytest.raises(Exception):
        _read_json_file(str(broken))


def test_read_json_file_raises_on_non_object_content(tmp_path):
    """文件内容非对象（如数组）必须抛 ValueError 显式报错。"""
    array_file = tmp_path / "array.json"
    array_file.write_text(json.dumps(["a", "b"]), encoding="utf-8")
    with pytest.raises(ValueError, match="必须是对象"):
        _read_json_file(str(array_file))


def test_read_json_file_returns_dict_on_valid_content(tmp_path):
    """合法对象内容正常返回。"""
    valid = tmp_path / "valid.json"
    valid.write_text(json.dumps({"key": "value"}), encoding="utf-8")
    assert _read_json_file(str(valid)) == {"key": "value"}
