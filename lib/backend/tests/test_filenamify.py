"""路径模板渲染与文件名净化单元测试。

覆盖 ``path_template.py`` 的：
- :func:`filenamify`：非法字符替换 / 首尾点号 / Windows 保留名 / 空字符串
- :func:`render`：Jinja2 模板渲染（含路径分隔符占位符、StrictUndefined）
- :class:`PathTemplateError`：异常构造与属性
- 辅助常量与函数（``_ILLEGAL_CHARS_RE`` / ``_OUTER_PERIODS_RE`` /
  ``_WINDOWS_RESERVED_RE`` / ``_escape_separators`` / ``_restore_separators``）
- :func:`build_video_path` / :func:`build_page_path`：完整链路集成

测试隔离：纯本地函数测试，无外部依赖（httpx / 网络 / 文件系统）。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# 注入 backend 目录到 sys.path，便于直接 import 被测模块
_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from plugins.bilibili_toolkit_builtin.bilibili.video import (  # noqa: E402
    Page,
    VideoInfo,
)
from plugins.bilibili_toolkit_builtin.path_template import (  # noqa: E402
    PathTemplateError,
    _ILLEGAL_CHARS_RE,
    _OUTER_PERIODS_RE,
    _PATH_SEPARATOR_PLACEHOLDER,
    _WINDOWS_RESERVED_RE,
    _escape_separators,
    _restore_separators,
    build_page_path,
    build_video_path,
    filenamify,
    render,
)


# ---------------------------------------------------------------------------
# filenamify - 非法字符替换测试
# ---------------------------------------------------------------------------


def test_filenamify_replaces_angle_brackets():
    """``<`` 与 ``>`` 应替换为 ``_``。"""
    assert filenamify("a<b>c") == "a_b_c"


def test_filenamify_replaces_colon():
    """``:`` 应替换为 ``_``。"""
    assert filenamify("a:b") == "a_b"


def test_filenamify_replaces_quote():
    """``"`` 应替换为 ``_``。"""
    assert filenamify('a"b') == "a_b"


def test_filenamify_replaces_slash():
    """``/`` 应替换为 ``_``。"""
    assert filenamify("a/b") == "a_b"


def test_filenamify_replaces_backslash():
    """``\\`` 应替换为 ``_``。"""
    assert filenamify("a\\b") == "a_b"


def test_filenamify_replaces_pipe():
    """``|`` 应替换为 ``_``。"""
    assert filenamify("a|b") == "a_b"


def test_filenamify_replaces_question_mark():
    """``?`` 应替换为 ``_``。"""
    assert filenamify("a?b") == "a_b"


def test_filenamify_replaces_asterisk():
    """``*`` 应替换为 ``_``。"""
    assert filenamify("a*b") == "a_b"


def test_filenamify_consecutive_illegal_chars_collapse():
    """连续多个非法字符应合并为单个 ``_``。"""
    assert filenamify("a<>:?b") == "a_b"


def test_filenamify_replaces_control_chars():
    """控制字符 0x00-0x1F 应替换为 ``_``。"""
    assert filenamify("a\x00\x01\x1fb") == "a_b"


def test_filenamify_replaces_del_char():
    """DEL 字符 0x7F 应替换为 ``_``。"""
    assert filenamify("a\x7fb") == "a_b"


def test_filenamify_replaces_high_control_chars():
    """0x80-0x9F 高位控制字符应替换为 ``_``。"""
    assert filenamify("a\x80\x9fb") == "a_b"


def test_filenamify_preserves_legal_chars():
    """合法字符应保留不变。"""
    assert filenamify("视频标题-2023") == "视频标题-2023"


def test_filenamify_preserves_chinese():
    """中文字符应保留不变。"""
    assert filenamify("测试视频") == "测试视频"


def test_filenamify_preserves_underscore():
    """``_`` 字符应保留不变。"""
    assert filenamify("a_b") == "a_b"


def test_filenamify_preserves_dot_in_middle():
    """中间的点号应保留不变。"""
    assert filenamify("a.b.c") == "a.b.c"


# ---------------------------------------------------------------------------
# filenamify - 首尾点号测试
# ---------------------------------------------------------------------------


def test_filenamify_leading_dot_replaced():
    """开头一个或多个点应替换为单个 ``_``。"""
    assert filenamify(".hidden") == "_hidden"


def test_filenamify_leading_multiple_dots_replaced():
    """开头多个点应合并为单个 ``_``。"""
    assert filenamify("...hidden") == "_hidden"


def test_filenamify_trailing_dot_replaced():
    """结尾一个或多个点应替换为单个 ``_``。"""
    assert filenamify("file.") == "file_"


def test_filenamify_trailing_multiple_dots_replaced():
    """结尾多个点应合并为单个 ``_``。"""
    assert filenamify("file...") == "file_"


def test_filenamify_both_sides_dots_replaced():
    """开头与结尾的点号都应分别替换为 ``_``。"""
    assert filenamify(".file.") == "_file_"


# ---------------------------------------------------------------------------
# filenamify - Windows 保留名测试
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "reserved",
    ["con", "prn", "aux", "nul", "CON", "PRN", "AUX", "NUL"],
)
def test_filenamify_windows_reserved_basic(reserved: str):
    """con / prn / aux / nul（含大小写）应追加 ``_`` 后缀。"""
    assert filenamify(reserved) == reserved + "_"


@pytest.mark.parametrize("i", range(1, 10))
def test_filenamify_windows_reserved_com(i: int):
    """com1-9 应追加 ``_`` 后缀。"""
    name = f"com{i}"
    assert filenamify(name) == name + "_"


@pytest.mark.parametrize("i", range(1, 10))
def test_filenamify_windows_reserved_lpt(i: int):
    """lpt1-9 应追加 ``_`` 后缀。"""
    name = f"lpt{i}"
    assert filenamify(name) == name + "_"


def test_filenamify_windows_reserved_case_insensitive():
    """Windows 保留名匹配应不区分大小写。"""
    assert filenamify("Com1") == "Com1_"
    assert filenamify("LPT9") == "LPT9_"


def test_filenamify_non_reserved_not_modified():
    """非保留名应保持不变。"""
    assert filenamify("video1") == "video1"
    assert filenamify("config") == "config"


# ---------------------------------------------------------------------------
# filenamify - 空字符串与边界
# ---------------------------------------------------------------------------


def test_filenamify_empty_string():
    """空字符串应返回 ``_``。"""
    assert filenamify("") == "_"


def test_filenamify_all_illegal_returns_single_underscore():
    """全部为非法字符时净化后应为 ``_``。"""
    assert filenamify("<>:?*") == "_"


# ---------------------------------------------------------------------------
# _ILLEGAL_CHARS_RE / _OUTER_PERIODS_RE / _WINDOWS_RESERVED_RE 正则验证
# ---------------------------------------------------------------------------


def test_illegal_chars_re_matches_all_target_chars():
    """正则应匹配全部 9 类非法字符。"""
    targets = '<>:"/\\|?*'
    for ch in targets:
        assert _ILLEGAL_CHARS_RE.search(ch) is not None, f"未匹配字符: {ch!r}"


def test_illegal_chars_re_matches_control_range():
    """正则应匹配 0x00-0x1F 控制字符。"""
    for code in range(0x00, 0x20):
        assert _ILLEGAL_CHARS_RE.search(chr(code)) is not None


def test_outer_periods_re_leading_dot():
    """正则应匹配开头的点号。"""
    match = _OUTER_PERIODS_RE.match("...file")
    assert match is not None


def test_outer_periods_re_trailing_dot():
    """正则应匹配结尾的点号（需 search）。"""
    match = _OUTER_PERIODS_RE.search("file...")
    assert match is not None


def test_outer_periods_re_no_middle_match():
    """正则不应匹配中间的点号。"""
    assert _OUTER_PERIODS_RE.search("a.b") is None


def test_windows_reserved_re_basic_names():
    """正则应匹配 con / prn / aux / nul。"""
    for name in ("con", "prn", "aux", "nul"):
        assert _WINDOWS_RESERVED_RE.match(name) is not None


def test_windows_reserved_re_com_lpt():
    """正则应匹配 com1-9 / lpt1-9。"""
    for i in range(1, 10):
        assert _WINDOWS_RESERVED_RE.match(f"com{i}") is not None
        assert _WINDOWS_RESERVED_RE.match(f"lpt{i}") is not None


def test_windows_reserved_re_case_insensitive():
    """正则匹配应不区分大小写。"""
    assert _WINDOWS_RESERVED_RE.match("CON") is not None
    assert _WINDOWS_RESERVED_RE.match("Aux") is not None


def test_windows_reserved_re_non_reserved():
    """正则不应匹配非保留名。

    注意：``com\\d`` 中 ``\\d`` 匹配 0-9 任意数字，所以 ``com0`` 也算保留名。
    这里只测明确非保留名的形式（无数字后缀或字母后缀）。
    """
    assert _WINDOWS_RESERVED_RE.match("video1") is None
    assert _WINDOWS_RESERVED_RE.match("com") is None  # 无数字
    assert _WINDOWS_RESERVED_RE.match("comX") is None  # 字母后缀非保留
    assert _WINDOWS_RESERVED_RE.match("config") is None
    assert _WINDOWS_RESERVED_RE.match("lptX") is None


# ---------------------------------------------------------------------------
# _escape_separators / _restore_separators 测试
# ---------------------------------------------------------------------------


def test_escape_separators_forward_slash():
    """``/`` 应被替换为占位符。"""
    assert _escape_separators("a/b") == f"a{_PATH_SEPARATOR_PLACEHOLDER}b"


def test_escape_separators_backslash():
    """``\\`` 应被替换为占位符。"""
    assert _escape_separators("a\\b") == f"a{_PATH_SEPARATOR_PLACEHOLDER}b"


def test_escape_separators_both():
    """同时含 ``/`` 与 ``\\`` 都应替换为占位符。"""
    result = _escape_separators("a/b\\c")
    assert result == f"a{_PATH_SEPARATOR_PLACEHOLDER}b{_PATH_SEPARATOR_PLACEHOLDER}c"


def test_escape_separators_no_separators():
    """无分隔符时返回原字符串。"""
    assert _escape_separators("abc") == "abc"


def test_restore_separators_to_os_sep():
    """占位符应还原为当前平台 ``os.sep``。"""
    assert _restore_separators(
        f"a{_PATH_SEPARATOR_PLACEHOLDER}b"
    ) == f"a{os.sep}b"


def test_restore_separators_multiple():
    """多个占位符应全部还原。"""
    result = _restore_separators(
        f"a{_PATH_SEPARATOR_PLACEHOLDER}b{_PATH_SEPARATOR_PLACEHOLDER}c"
    )
    assert result == f"a{os.sep}b{os.sep}c"


def test_restore_separators_no_placeholder():
    """无占位符时返回原字符串。"""
    assert _restore_separators("abc") == "abc"


def test_escape_restore_round_trip():
    """escape → restore 应恢复原分隔符（按平台 sep）。"""
    original = "a/b\\c"
    escaped = _escape_separators(original)
    restored = _restore_separators(escaped)
    expected = original.replace("/", os.sep).replace("\\", os.sep)
    assert restored == expected


# ---------------------------------------------------------------------------
# render 测试
# ---------------------------------------------------------------------------


def test_render_simple_variable():
    """简单变量替换应正确。"""
    result = render("{{title}}", {"title": "hello"})
    assert result == "hello"


def test_render_multiple_variables():
    """多个变量替换应正确。"""
    result = render("{{a}}-{{b}}", {"a": "1", "b": "2"})
    assert result == "1-2"


def test_render_keeps_separator_placeholder():
    """render 输出应保留占位符（不还原为 os.sep）。"""
    result = render("videos/{{title}}", {"title": "hello"})
    assert _PATH_SEPARATOR_PLACEHOLDER in result
    assert "videos/" not in result  # 占位符未还原


def test_render_undefined_variable_raises():
    """引用未定义变量应抛 PathTemplateError。"""
    with pytest.raises(PathTemplateError):
        render("{{undefined_var}}", {"title": "hello"})


def test_render_syntax_error_raises():
    """模板语法错误应抛 PathTemplateError。"""
    with pytest.raises(PathTemplateError):
        render("{{title", {"title": "hello"})


def test_render_empty_template():
    """空模板应返回空字符串。"""
    assert render("", {}) == ""


def test_render_static_text():
    """无变量的纯文本应原样返回。"""
    assert render("static text", {}) == "static text"


# ---------------------------------------------------------------------------
# PathTemplateError 测试
# ---------------------------------------------------------------------------


def test_path_template_error_has_template_attr():
    """异常应携带原始 template 字符串。"""
    try:
        render("{{undefined}}", {"x": "1"})
    except PathTemplateError as e:
        assert e.template == "{{undefined}}"
    else:
        raise AssertionError("应抛 PathTemplateError")


def test_path_template_error_has_context_keys_attr():
    """异常应携带 context_keys 列表。"""
    try:
        render("{{undefined}}", {"x": "1", "y": "2"})
    except PathTemplateError as e:
        assert "x" in e.context_keys
        assert "y" in e.context_keys
    else:
        raise AssertionError("应抛 PathTemplateError")


def test_path_template_error_is_exception_subclass():
    """PathTemplateError 应继承 Exception。"""
    assert issubclass(PathTemplateError, Exception)


def test_path_template_error_str_contains_message():
    """异常字符串应包含 message 内容。"""
    try:
        render("{{undefined}}", {})
    except PathTemplateError as e:
        assert str(e)  # 非空
    else:
        raise AssertionError("应抛 PathTemplateError")


# ---------------------------------------------------------------------------
# build_video_path / build_page_path 集成测试
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_video() -> VideoInfo:
    """构造 VideoInfo 测试样本。"""
    return VideoInfo(
        bvid="BV1gLfnY8E6D",
        aid=123,
        title="测试标题",
        upper_mid=456,
        upper_name="UP主",
        pages=[
            Page(cid=111, page=1, name="分P一", duration=120, width=1920, height=1080),
        ],
        pubtime=1700000000,
        ctime=1700000000,
        desc="简介",
        tags=["tag1"],
    )


def test_build_video_path_basic(sample_video: VideoInfo):
    """build_video_path 应返回 base_dir / filenamified(title)。"""
    base_dir = Path("/tmp/videos")
    result = build_video_path("{{title}}", base_dir, sample_video)
    assert result == base_dir / "测试标题"


def test_build_video_path_with_subdir(sample_video: VideoInfo):
    """模板含子目录时应保留为路径分隔符。"""
    base_dir = Path("/tmp/videos")
    result = build_video_path("upper-{{upper_name}}/{{title}}", base_dir, sample_video)
    # 路径中应含 os.sep 还原后的分隔符
    assert "upper-UP主" in str(result)
    assert "测试标题" in str(result)
    assert result.is_absolute() == base_dir.is_absolute()


def test_build_video_path_filenamifies_title(sample_video: VideoInfo):
    """title 含非法字符时应被 filenamify 净化。"""
    sample_video.title = "a<b>c"
    base_dir = Path("/tmp/videos")
    result = build_video_path("{{title}}", base_dir, sample_video)
    assert result == base_dir / "a_b_c"


def test_build_video_path_undefined_var_raises(sample_video: VideoInfo):
    """模板引用未定义变量应抛 PathTemplateError。"""
    with pytest.raises(PathTemplateError):
        build_video_path("{{fav_time}}", Path("/tmp"), sample_video)


def test_build_page_path_basic(sample_video: VideoInfo):
    """build_page_path 应返回 video_dir / filenamified(bvid)。"""
    video_dir = Path("/tmp/videos/BV1xx")
    result = build_page_path("{{bvid}}", video_dir, sample_video, sample_video.pages[0])
    assert result == video_dir / "BV1gLfnY8E6D"


def test_build_page_path_with_pid_and_ptitle(sample_video: VideoInfo):
    """page 模板支持 ptitle 与 pid 变量。"""
    video_dir = Path("/tmp/videos/BV1xx")
    page = sample_video.pages[0]
    result = build_page_path("{{pid}}_{{ptitle}}", video_dir, sample_video, page)
    assert result == video_dir / "1_分P一"


def test_build_page_path_filenamifies_ptitle(sample_video: VideoInfo):
    """ptitle 含非法字符时应被 filenamify 净化。"""
    sample_video.pages[0].name = "a:b"
    video_dir = Path("/tmp/videos/BV1xx")
    result = build_page_path("{{ptitle}}", video_dir, sample_video, sample_video.pages[0])
    assert result == video_dir / "a_b"


def test_build_page_path_inherits_video_context(sample_video: VideoInfo):
    """page context 应继承 video context 的 bvid / title 等变量。"""
    video_dir = Path("/tmp")
    page = sample_video.pages[0]
    result = build_page_path("{{bvid}}_{{pid}}", video_dir, sample_video, page)
    assert result == video_dir / "BV1gLfnY8E6D_1"
