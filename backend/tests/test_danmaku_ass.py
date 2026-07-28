"""弹幕 protobuf 解析与 ASS 渲染单元测试。

覆盖 ``danmaku/proto.py`` 与 ``danmaku/ass.py``：
- :class:`DanmakuElem`：protobuf Message 类的字段定义与序列化
- :func:`parse_danmaku_segs`：protobuf 二进制响应解析
- :class:`DanmakuOption`：渲染选项默认值与边界
- :func:`render_ass`：ASS 字幕字符串生成
- lane 碰撞算法：滚动 / 顶部 / 底部弹幕布局

测试隔离：所有用例使用程序构造的 DanmakuElem 实例，不调用网络 API。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# 注入 backend 目录到 sys.path
_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from plugins.bilibili_toolkit_builtin.danmaku.ass import (  # noqa: E402
    ASS_PLAY_RES_X,
    ASS_PLAY_RES_Y,
    DanmakuOption,
    render_ass,
)
from plugins.bilibili_toolkit_builtin.danmaku.proto import (  # noqa: E402
    DanmakuElem,
    parse_danmaku_segs,
)
import plugins.bilibili_toolkit_builtin.danmaku.proto as _proto_module  # noqa: E402


# ---------------------------------------------------------------------------
# 辅助构造函数
# ---------------------------------------------------------------------------


def _make_elem(
    *,
    elem_id: int = 1,
    progress: int = 1000,
    mode: int = 1,
    fontsize: int = 25,
    color: int = 16777215,
    mid: str = "abc123",
    content: str = "hello",
) -> DanmakuElem:
    """构造 DanmakuElem 实例，简化测试用例构造。"""
    elem = DanmakuElem()
    elem.id = elem_id
    elem.progress = progress
    elem.mode = mode
    elem.fontsize = fontsize
    elem.color = color
    elem.mid = mid
    elem.content = content
    return elem


def _build_reply_bytes(elems: list) -> bytes:
    """手动构造 DmSegMobileReply 的 protobuf wire format。

    用于验证 :func:`parse_danmaku_segs` 能正确解码 protobuf 二进制响应，
    不依赖被测模块的 ``_DmSegMobileReplyClass``（避免循环自证）。

    wire format：``repeated DanmakuElem elems = 1``，每个元素编码为：
    - tag: ``(field=1 << 3) | wire_type=2`` = 0x0a
    - varint: 元素字节长度
    - payload: DanmakuElem.SerializeToString()
    """
    result: bytes = b""
    for elem in elems:
        elem_bytes = elem.SerializeToString()
        # tag for field 1, wire type 2 (LENGTH_DELIMITED)
        tag = (1 << 3) | 2
        result += bytes([tag])
        # varint length encoding
        length = len(elem_bytes)
        while length > 0x7F:
            result += bytes([(length & 0x7F) | 0x80])
            length >>= 7
        result += bytes([length & 0x7F])
        result += elem_bytes
    return result


# ---------------------------------------------------------------------------
# DanmakuElem 字段定义
# ---------------------------------------------------------------------------


def test_danmaku_elem_has_all_13_fields() -> None:
    """DanmakuElem 必须定义 13 个字段（与 B 站 dm.proto 一致）。"""
    elem = DanmakuElem()
    expected_fields = {
        "id",
        "progress",
        "mode",
        "fontsize",
        "color",
        "mid",
        "content",
        "ctime",
        "weight",
        "action",
        "pool",
        "dmid_str",
        "attr",
    }
    actual_fields = {f.name for f in elem.DESCRIPTOR.fields}
    assert actual_fields == expected_fields


def test_danmaku_elem_serialize_round_trip() -> None:
    """DanmakuElem 序列化后反序列化保持字段值一致。"""
    elem = _make_elem(content="测试弹幕")
    serialized = elem.SerializeToString()
    parsed = DanmakuElem()
    parsed.ParseFromString(serialized)
    assert parsed.id == 1
    assert parsed.progress == 1000
    assert parsed.mode == 1
    assert parsed.color == 16777215
    assert parsed.content == "测试弹幕"


def test_danmaku_elem_default_values() -> None:
    """DanmakuElem 默认值符合 proto3 规范（数值 0，字符串空）。"""
    elem = DanmakuElem()
    assert elem.id == 0
    assert elem.progress == 0
    assert elem.mode == 0
    assert elem.color == 0
    assert elem.content == ""


# ---------------------------------------------------------------------------
# parse_danmaku_segs
# ---------------------------------------------------------------------------


def test_parse_danmaku_segs_empty_bytes() -> None:
    """空字节输入返回空列表。"""
    assert parse_danmaku_segs(b"") == []


def test_parse_danmaku_segs_single_elem() -> None:
    """单个 DanmakuElem 解析后字段保持一致。"""
    elem = _make_elem(
        elem_id=42, progress=2500, mode=1, color=16711680, content="红色弹幕"
    )
    raw = _build_reply_bytes([elem])
    parsed = parse_danmaku_segs(raw)
    assert len(parsed) == 1
    assert parsed[0].id == 42
    assert parsed[0].progress == 2500
    assert parsed[0].mode == 1
    assert parsed[0].color == 16711680
    assert parsed[0].content == "红色弹幕"


def test_parse_danmaku_segs_multiple_elems() -> None:
    """多个 DanmakuElem 解析后顺序与字段保持一致。"""
    elems = [
        _make_elem(elem_id=1, progress=1000, content="first"),
        _make_elem(elem_id=2, progress=2000, content="second"),
        _make_elem(elem_id=3, progress=3000, content="third"),
    ]
    raw = _build_reply_bytes(elems)
    parsed = parse_danmaku_segs(raw)
    assert len(parsed) == 3
    assert parsed[0].id == 1
    assert parsed[0].content == "first"
    assert parsed[1].id == 2
    assert parsed[1].content == "second"
    assert parsed[2].id == 3
    assert parsed[2].content == "third"


def test_parse_danmaku_segs_preserves_all_fields() -> None:
    """所有 13 个字段在序列化-解析往返后保持一致。"""
    elem = DanmakuElem()
    elem.id = 100
    elem.progress = 5000
    elem.mode = 4
    elem.fontsize = 36
    elem.color = 65280
    elem.mid = "user_mid_hash"
    elem.content = "底部弹幕"
    elem.ctime = 1700000000
    elem.weight = 10
    elem.action = "action_str"
    elem.pool = 1
    elem.dmid_str = "dmid_123"
    elem.attr = 5

    raw = _build_reply_bytes([elem])
    parsed = parse_danmaku_segs(raw)
    assert len(parsed) == 1
    p = parsed[0]
    assert p.id == 100
    assert p.progress == 5000
    assert p.mode == 4
    assert p.fontsize == 36
    assert p.color == 65280
    assert p.mid == "user_mid_hash"
    assert p.content == "底部弹幕"
    assert p.ctime == 1700000000
    assert p.weight == 10
    assert p.action == "action_str"
    assert p.pool == 1
    assert p.dmid_str == "dmid_123"
    assert p.attr == 5


# ---------------------------------------------------------------------------
# DanmakuOption 默认值
# ---------------------------------------------------------------------------


def test_danmaku_option_defaults() -> None:
    """DanmakuOption 默认值与 schema.json 描述一致。"""
    opt = DanmakuOption()
    assert opt.font == "sans-serif"
    assert opt.font_size == 1.0
    assert opt.alpha == 0.7
    assert opt.stroke == 1.5
    assert opt.lane_size == 32
    assert opt.duration == 15.0
    assert opt.width_ratio == 1.2
    assert opt.horizontal_gap == 20.0
    assert opt.float_percentage == 0.5
    assert opt.bottom_percentage == 0.3
    assert opt.bold is True
    assert opt.time_offset == 0.0


def test_danmaku_option_font_size_lower_bound() -> None:
    """font_size 不得低于 0.1（Pydantic ge 约束）。"""
    with pytest.raises(Exception):
        DanmakuOption(font_size=0.05)


def test_danmaku_option_alpha_upper_bound() -> None:
    """alpha 不得高于 1.0（Pydantic le 约束）。"""
    with pytest.raises(Exception):
        DanmakuOption(alpha=1.5)


# ---------------------------------------------------------------------------
# render_ass
# ---------------------------------------------------------------------------


def test_render_ass_constants() -> None:
    """ASS 画布分辨率为 1920x1080。"""
    assert ASS_PLAY_RES_X == 1920
    assert ASS_PLAY_RES_Y == 1080


def test_render_ass_empty_input() -> None:
    """空弹幕列表渲染为仅含 header 的 ASS 字符串。"""
    result = render_ass([], duration_sec=60)
    assert "[Script Info]" in result
    assert "[V4+ Styles]" in result
    assert "[Events]" in result
    assert "PlayResX: 1920" in result
    assert "PlayResY: 1080" in result


def test_render_ass_contains_three_styles() -> None:
    """ASS 文件必须含 Float / Bottom / Top 三种 Style。"""
    result = render_ass([], duration_sec=60)
    assert "Style: Float" in result
    assert "Style: Bottom" in result
    assert "Style: Top" in result


def test_render_ass_float_danmaku_emits_dialogue() -> None:
    """滚动弹幕（mode=1）生成 Dialogue 行，含 \\move 效果标签。"""
    elem = _make_elem(
        progress=1000, mode=1, content="滚动弹幕", color=16777215
    )
    result = render_ass([elem], duration_sec=60)
    assert "Dialogue:" in result
    assert "Float" in result
    assert "\\move(" in result
    assert "滚动弹幕" in result


def test_render_ass_top_danmaku_emits_pos() -> None:
    """顶部弹幕（mode=5）生成 Dialogue 行，含 \\pos 效果标签。"""
    elem = _make_elem(progress=1000, mode=5, content="顶部弹幕")
    result = render_ass([elem], duration_sec=60)
    assert "Dialogue:" in result
    assert "Top" in result
    assert "\\pos(" in result


def test_render_ass_bottom_danmaku_emits_pos() -> None:
    """底部弹幕（mode=4）生成 Dialogue 行，含 \\pos 效果标签。"""
    elem = _make_elem(progress=1000, mode=4, content="底部弹幕")
    result = render_ass([elem], duration_sec=60)
    assert "Dialogue:" in result
    assert "Bottom" in result
    assert "\\pos(" in result


def test_render_ass_skips_unsupported_mode() -> None:
    """高级弹幕（mode=7）应被跳过，不生成 Dialogue。"""
    elem = _make_elem(progress=1000, mode=7, content="高级弹幕")
    result = render_ass([elem], duration_sec=60)
    assert "Dialogue:" not in result


def test_render_ass_color_tag_in_dialogue() -> None:
    """Dialogue 行含 \\c&H<BBGGRR>& 颜色标签。"""
    # color=0x00FF00 (R=0, G=255, B=0) → ASS: BB=00, GG=FF, RR=00 → 00FF00
    elem = _make_elem(progress=0, mode=1, content="green", color=0x00FF00)
    result = render_ass([elem], duration_sec=60)
    assert "\\c&H0000FF00&" in result or "\\c&H00FF00&" in result


def test_render_ass_time_offset_applied() -> None:
    """time_offset 选项应整体偏移弹幕时间轴。"""
    elem = _make_elem(progress=0, mode=1, content="offset")
    opt = DanmakuOption(time_offset=5.0)
    result = render_ass([elem], duration_sec=60, option=opt)
    # 偏移 5 秒后起始时间应为 0:00:05.00
    assert "0:00:05" in result


def test_render_ass_negative_timeline_skipped() -> None:
    """time_offset 导致弹幕时间轴为负时应跳过该弹幕。"""
    elem = _make_elem(progress=0, mode=1, content="skipped")
    opt = DanmakuOption(time_offset=-10.0)
    result = render_ass([elem], duration_sec=60, option=opt)
    assert "skipped" not in result


def test_render_ass_multiple_danmaku_separate_lanes() -> None:
    """同时刻多条滚动弹幕应分配到不同 lane（避免碰撞）。"""
    elems = [
        _make_elem(elem_id=1, progress=0, mode=1, content="first"),
        _make_elem(elem_id=2, progress=0, mode=1, content="second"),
        _make_elem(elem_id=3, progress=0, mode=1, content="third"),
    ]
    result = render_ass(elems, duration_sec=60)
    # 三条弹幕都应被渲染（lane 池容量充足）
    assert result.count("Dialogue:") == 3


def test_render_ass_strips_text_whitespace() -> None:
    """弹幕文本首尾空白应被去除。"""
    elem = _make_elem(progress=0, mode=1, content="  hello  ")
    result = render_ass([elem], duration_sec=60)
    # 渲染后的文本不应含首尾空格（在 Dialogue 行内）
    assert "  hello  " not in result


def test_render_ass_newline_replaced_with_ass_newline() -> None:
    """弹幕文本中的 \\n 应被替换为 ASS 的 \\N。"""
    elem = _make_elem(progress=0, mode=1, content="line1\nline2")
    result = render_ass([elem], duration_sec=60)
    assert "line1\\Nline2" in result
