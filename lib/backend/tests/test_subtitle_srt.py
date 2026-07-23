"""字幕 SRT 转换与 AI 字幕过滤单元测试。

覆盖 ``subtitle.py`` 的：
- :class:`SubtitleInfo`：数据类与 ``is_ai_subtitle`` 双重判定
- :func:`to_srt`：JSON body → SRT 格式字符串
- :func:`_filter_ai_subtitles`：AI 字幕过滤
- :func:`_format_time`：秒数 → HH:MM:SS,mmm 时间戳
- :func:`_parse_subtitles`：原始 dict 列表解析

测试隔离：所有用例使用静态构造的 dict / SubtitleInfo 输入，不调用网络 API。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict

import pytest

# 注入 backend 目录到 sys.path
_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from plugins.bilibili_toolkit_builtin.subtitle import (  # noqa: E402
    SubtitleInfo,
    _filter_ai_subtitles,
    _format_time,
    _parse_subtitles,
    to_srt,
)


# ---------------------------------------------------------------------------
# SubtitleInfo.is_ai_subtitle
# ---------------------------------------------------------------------------


def test_subtitle_info_non_ai_subtitle() -> None:
    """非 AI 字幕：subtitle_url 不含 ai_subtitle，ai_type=0。"""
    sub = SubtitleInfo(
        lan="zh-CN",
        subtitle_url="https://aisubtitle.hdslb.com/cn/123.json",
        ai_type=0,
    )
    # URL 不含 "ai_subtitle" 子串
    assert sub.is_ai_subtitle() is False


def test_subtitle_info_ai_subtitle_by_url() -> None:
    """AI 字幕判定 1：subtitle_url 含 ``ai_subtitle`` 子串。"""
    sub = SubtitleInfo(
        lan="zh-CN",
        subtitle_url="https://aisubtitle.hdslb.com/bfs/ai_subtitle/123.json",
        ai_type=0,
    )
    assert sub.is_ai_subtitle() is True


def test_subtitle_info_ai_subtitle_by_ai_type() -> None:
    """AI 字幕判定 2：ai_type 非 0。"""
    sub = SubtitleInfo(
        lan="zh-CN",
        subtitle_url="https://aisubtitle.hdslb.com/cn/123.json",
        ai_type=1,
    )
    assert sub.is_ai_subtitle() is True


def test_subtitle_info_ai_subtitle_both_conditions() -> None:
    """AI 字幕判定：两个条件同时满足仍为 AI 字幕。"""
    sub = SubtitleInfo(
        lan="zh-CN",
        subtitle_url="https://aisubtitle.hdslb.com/bfs/ai_subtitle/123.json",
        ai_type=1,
    )
    assert sub.is_ai_subtitle() is True


# ---------------------------------------------------------------------------
# _filter_ai_subtitles
# ---------------------------------------------------------------------------


def test_filter_ai_subtitles_removes_ai_only() -> None:
    """过滤后仅保留非 AI 字幕。"""
    subtitles = [
        SubtitleInfo(lan="zh-CN", subtitle_url="https://x.com/cn.json", ai_type=0),
        SubtitleInfo(
            lan="zh-CN",
            subtitle_url="https://x.com/bfs/ai_subtitle/cn.json",
            ai_type=0,
        ),
        SubtitleInfo(lan="en-US", subtitle_url="https://x.com/en.json", ai_type=1),
    ]
    filtered = _filter_ai_subtitles(subtitles)
    assert len(filtered) == 1
    assert filtered[0].lan == "zh-CN"
    assert filtered[0].subtitle_url == "https://x.com/cn.json"


def test_filter_ai_subtitles_empty_input() -> None:
    """空列表输入返回空列表。"""
    assert _filter_ai_subtitles([]) == []


def test_filter_ai_subtitles_all_ai_returns_empty() -> None:
    """全部为 AI 字幕时返回空列表。"""
    subtitles = [
        SubtitleInfo(
            lan="zh-CN",
            subtitle_url="https://x.com/bfs/ai_subtitle/cn.json",
            ai_type=0,
        ),
        SubtitleInfo(lan="en-US", subtitle_url="https://x.com/en.json", ai_type=1),
    ]
    assert _filter_ai_subtitles(subtitles) == []


# ---------------------------------------------------------------------------
# to_srt
# ---------------------------------------------------------------------------


def test_to_srt_basic_format() -> None:
    """单条字幕正确转换为 SRT 格式（序号 / 时间区间 / 内容 / 空行）。"""
    body: Dict[str, Any] = {
        "body": [
            {"from": 1.5, "to": 3.0, "content": "Hello"}
        ]
    }
    srt = to_srt(body)
    # 序号从 0 开始
    assert srt.startswith("0\n")
    # 时间区间格式
    assert "00:00:01,500 --> 00:00:03,000" in srt
    # 字幕内容
    assert "Hello" in srt


def test_to_srt_multiple_entries() -> None:
    """多条字幕按序号 0,1,2,... 生成。"""
    body: Dict[str, Any] = {
        "body": [
            {"from": 0.0, "to": 1.0, "content": "first"},
            {"from": 1.5, "to": 2.5, "content": "second"},
            {"from": 3.0, "to": 4.0, "content": "third"},
        ]
    }
    srt = to_srt(body)
    assert "0\n" in srt
    assert "1\n" in srt
    assert "2\n" in srt
    assert "first" in srt
    assert "second" in srt
    assert "third" in srt


def test_to_srt_empty_body() -> None:
    """空 body 数组返回空字符串。"""
    assert to_srt({"body": []}) == ""


def test_to_srt_missing_body_field() -> None:
    """缺 body 字段返回空字符串。"""
    assert to_srt({}) == ""


def test_to_srt_skips_non_dict_entries() -> None:
    """body 中的非 dict 元素应被跳过（不抛异常），序号使用 enumerate 原索引。"""
    body: Dict[str, Any] = {
        "body": [
            {"from": 0.0, "to": 1.0, "content": "first"},
            "not a dict",  # 跳过
            {"from": 2.0, "to": 3.0, "content": "second"},
        ]
    }
    srt = to_srt(body)
    assert "first" in srt
    assert "second" in srt
    # to_srt 用 enumerate 保留原索引：第一条序号 0，第二条序号 2（跳过索引 1）
    assert "0\n00:00:00,000 --> 00:00:01,000\nfirst" in srt
    assert "2\n00:00:02,000 --> 00:00:03,000\nsecond" in srt


def test_to_srt_missing_from_to_defaults_to_zero() -> None:
    """缺 from / to 字段时默认为 0。"""
    body: Dict[str, Any] = {"body": [{"content": "no time"}]}
    srt = to_srt(body)
    assert "00:00:00,000 --> 00:00:00,000" in srt
    assert "no time" in srt


def test_to_srt_missing_content_defaults_to_empty() -> None:
    """缺 content 字段时默认为空字符串。"""
    body: Dict[str, Any] = {"body": [{"from": 0.0, "to": 1.0}]}
    srt = to_srt(body)
    # 仍生成序号与时间区间，content 为空
    assert "0\n" in srt
    assert "00:00:00,000 --> 00:00:01,000" in srt


# ---------------------------------------------------------------------------
# _format_time
# ---------------------------------------------------------------------------


def test_format_time_zero_seconds() -> None:
    """0 秒 → 00:00:00,000。"""
    assert _format_time(0.0) == "00:00:00,000"


def test_format_time_seconds_only() -> None:
    """仅含秒数：1.5s → 00:00:01,500。"""
    assert _format_time(1.5) == "00:00:01,500"


def test_format_time_minutes() -> None:
    """含分钟：65.25s → 00:01:05,250。"""
    assert _format_time(65.25) == "00:01:05,250"


def test_format_time_hours() -> None:
    """含小时：3661.999s → 01:01:01,999（毫秒精度可能受 float 误差影响 ±1ms）。"""
    # _format_time 用 int((time - int(time)) * 1000) 计算毫秒，
    # float 精度问题可能导致 999 → 998，因此只校验到秒级，毫秒单独软校验
    result = _format_time(3661.999)
    assert result.startswith("01:01:01,")
    # 毫秒部分应为 998 或 999（float 误差容忍）
    ms_str = result.split(",")[1]
    assert ms_str in {"998", "999"}


def test_format_time_hours_exceed_99() -> None:
    """小时数超过 99 时仍正常输出（360001.229 → 100:00:01,22x）。"""
    # _format_time 用 int((time - int(time)) * 1000) 计算毫秒，
    # float 精度问题可能导致 229 → 228，因此只校验前缀与毫秒容忍范围
    result = _format_time(360001.229)
    assert result.startswith("100:00:01,")
    ms_str = result.split(",")[1]
    assert ms_str in {"228", "229"}


# ---------------------------------------------------------------------------
# _parse_subtitles
# ---------------------------------------------------------------------------


def test_parse_subtitles_valid_entries() -> None:
    """有效 dict 列表正确解析为 SubtitleInfo 列表。"""
    raw = [
        {"lan": "zh-CN", "subtitle_url": "https://x.com/cn.json", "ai_type": 0},
        {"lan": "en-US", "subtitle_url": "https://x.com/en.json", "ai_type": 1},
    ]
    result = _parse_subtitles(raw, bvid="BV1xxx", cid=123)
    assert len(result) == 2
    assert result[0].lan == "zh-CN"
    assert result[0].ai_type == 0
    assert result[1].lan == "en-US"
    assert result[1].ai_type == 1


def test_parse_subtitles_skips_non_dict() -> None:
    """非 dict 元素应被跳过。"""
    raw = [
        {"lan": "zh-CN", "subtitle_url": "https://x.com/cn.json"},
        "not a dict",
        None,
        {"lan": "en-US", "subtitle_url": "https://x.com/en.json"},
    ]
    result = _parse_subtitles(raw, bvid="BV1xxx", cid=123)
    assert len(result) == 2


def test_parse_subtitles_skips_missing_lan_or_url() -> None:
    """缺 lan 或 subtitle_url 字段的条目应被跳过。"""
    raw = [
        {"subtitle_url": "https://x.com/cn.json"},  # 缺 lan
        {"lan": "zh-CN"},  # 缺 subtitle_url
        {"lan": "en-US", "subtitle_url": "https://x.com/en.json"},
    ]
    result = _parse_subtitles(raw, bvid="BV1xxx", cid=123)
    assert len(result) == 1
    assert result[0].lan == "en-US"


def test_parse_subtitles_default_ai_type_zero() -> None:
    """缺 ai_type 字段时默认为 0（非 AI 字幕）。"""
    raw = [{"lan": "zh-CN", "subtitle_url": "https://x.com/cn.json"}]
    result = _parse_subtitles(raw, bvid="BV1xxx", cid=123)
    assert result[0].ai_type == 0


def test_parse_subtitles_empty_input() -> None:
    """空列表输入返回空列表。"""
    assert _parse_subtitles([], bvid="BV1xxx", cid=123) == []


def test_parse_subtitles_ai_type_coerced_to_int() -> None:
    """ai_type 字符串应被强制转换为 int。"""
    raw = [
        {"lan": "zh-CN", "subtitle_url": "https://x.com/cn.json", "ai_type": "1"},
    ]
    result = _parse_subtitles(raw, bvid="BV1xxx", cid=123)
    assert result[0].ai_type == 1
