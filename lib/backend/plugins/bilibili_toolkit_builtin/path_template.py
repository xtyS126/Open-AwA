"""路径模板渲染与文件名净化。

移植自 bili-sync Rust 实现：
- ``bili-sync/crates/bili_sync/src/utils/filenamify.rs`` 文件名净化规则
- ``bili-sync/crates/bili_sync/src/config/handlebar.rs`` + ``config/item.rs``
  的 ``PathSafeTemplate`` 机制（注册时把路径分隔符替换为占位符，渲染后
  filenamify 再还原分隔符）

Python 版用 Jinja2 替代 Handlebars：
- ``render`` 使用 :class:`jinja2.Environment(autoescape=False, undefined=StrictUndefined)`
  严格未定义变量
- 渲染失败统一抛 :class:`PathTemplateError`，携带 ``template`` 与
  ``context_keys`` 字段便于定位
- 路径分隔符（``/`` 与 ``\\``）在渲染前 escape 为 ``__SEP__`` 占位符，
  filenamify 不会影响 ``_`` 字符，最后由 ``build_video_path`` /
  ``build_page_path`` 还原为当前平台 ``os.sep``

支持的模板变量：
- video 模板：``bvid`` / ``title`` / ``upper_name`` / ``upper_mid`` /
  ``pubtime`` / ``fav_time``
- page 模板：在 video 变量基础上追加 ``ptitle`` / ``pid``

``fav_time`` 变量在 :class:`VideoInfo` 中不存在（收藏时间属于订阅源扫描
元数据，由阶段 14 下载流水线在调用 ``render`` 时通过 context 传入）；
``build_video_path`` 仅基于 :class:`VideoInfo` 构造 context，因此不含
``fav_time``。用户若在模板中引用 ``{{fav_time}}`` 会触发 StrictUndefined
并抛 :class:`PathTemplateError`。
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jinja2 import Environment, StrictUndefined, TemplateError

from .bilibili.video import Page, VideoInfo


# 默认时间格式（与 schema.json 的 time_format 默认值一致）
_DEFAULT_TIME_FORMAT: str = "%Y-%m-%d %H:%M:%S"

# 路径分隔符占位符：渲染前把 / 与 \ 替换为此串，filenamify 不会处理 _
# 字符，最后还原为 os.sep
_PATH_SEPARATOR_PLACEHOLDER: str = "__SEP__"

# Jinja2 环境：关闭自动转义（路径模板需要原样输出），严格未定义变量
_JINJA_ENV: Environment = Environment(
    autoescape=False,
    undefined=StrictUndefined,
    keep_trailing_newline=False,
)

# 非法字符正则：匹配 < > : " / \ | ? * 及控制字符 0x00-0x1F、0x7F、
# 0x80-0x9F（与 Rust filenamify 一致），连续字符替换为单个 _
_ILLEGAL_CHARS_RE: re.Pattern[str] = re.compile(
    r'[<>:"/\\|?*\x00-\x1f\x7f\x80-\x9f]+'
)

# 首尾点号正则：匹配开头一个或多个点 OR 结尾一个或多个点，替换为单个 _
# （与 Rust 的 ^\.+|\.+$ 一致，不是去除而是替换为 _）
_OUTER_PERIODS_RE: re.Pattern[str] = re.compile(r'^\.+|\.+$')

# Windows 保留名正则：con / prn / aux / nul / com1-9 / lpt1-9，不区分大小写
_WINDOWS_RESERVED_RE: re.Pattern[str] = re.compile(
    r'^(con|prn|aux|nul|com\d|lpt\d)$',
    re.IGNORECASE,
)


class PathTemplateError(Exception):
    """路径模板渲染失败。

    Attributes:
        template: 触发错误的原始模板字符串。
        context_keys: 渲染时 context 中可用的变量名列表。
    """

    def __init__(
        self,
        template: str,
        context_keys: list[str],
        message: str,
    ) -> None:
        self.template = template
        self.context_keys: list[str] = list(context_keys)
        super().__init__(message)


def _escape_separators(template: str) -> str:
    """把模板字符串中的路径分隔符替换为占位符。

    同时处理 ``/`` 与 ``\\``，跨平台一致：用户在模板里写的任意一种分隔符
    都会被保留为路径分隔符，不会被 filenamify 替换为 ``_``。

    Args:
        template: 原始模板字符串。

    Returns:
        替换后的模板字符串（含 ``__SEP__`` 占位符）。
    """
    return template.replace("/", _PATH_SEPARATOR_PLACEHOLDER).replace(
        "\\", _PATH_SEPARATOR_PLACEHOLDER
    )


def _restore_separators(rendered: str) -> str:
    """把占位符还原为当前平台的路径分隔符。

    Args:
        rendered: filenamify 后的字符串（含 ``__SEP__`` 占位符）。

    Returns:
        还原后的字符串（``__SEP__`` 替换为 ``os.sep``）。
    """
    return rendered.replace(_PATH_SEPARATOR_PLACEHOLDER, os.sep)


def render(template: str, context: dict[str, Any]) -> str:
    """用 Jinja2 渲染路径模板。

    渲染前自动 escape 路径分隔符为 ``__SEP__`` 占位符，渲染后返回的字符串
    仍含占位符，需由调用方（如 :func:`build_video_path`）在 filenamify
    之后还原。

    Args:
        template: Jinja2 模板字符串，如 ``"{{title}}"`` 或
            ``"videos/{{title}}"``。
        context: 模板变量字典，支持 ``bvid`` / ``title`` / ``upper_name`` /
            ``upper_mid`` / ``pubtime`` / ``fav_time`` / ``ptitle`` / ``pid``
            等键。

    Returns:
        渲染后的字符串（含 ``__SEP__`` 占位符，未做 filenamify）。

    Raises:
        PathTemplateError: Jinja2 渲染失败（变量未定义、模板语法错误等）。
    """
    escaped_template = _escape_separators(template)
    context_keys = list(context.keys())
    try:
        rendered = _JINJA_ENV.from_string(escaped_template).render(**context)
    except TemplateError as exc:
        raise PathTemplateError(
            template=template,
            context_keys=context_keys,
            message=f"路径模板渲染失败: {exc}",
        ) from exc
    return rendered


def filenamify(name: str) -> str:
    """净化文件名，替换非法字符并处理 Windows 保留名。

    规则（对齐 Rust ``filenamify``）：
    1. 替换 ``< > : " / \\ | ? *`` 及控制字符（0x00-0x1F、0x7F、
       0x80-0x9F）为 ``_``（连续字符替换为单个 ``_``）；
    2. 替换首尾点号为 ``_``（开头一个或多个点、结尾一个或多个点各替换为
       单个 ``_``）；
    3. 检测 Windows 保留名（``con`` / ``prn`` / ``aux`` / ``nul`` /
       ``com1-9`` / ``lpt1-9``，不区分大小写），追加 ``_`` 后缀；
    4. 空字符串或净化后为空时返回 ``_``。

    全角字符与 Unicode 字符保留不动。

    Args:
        name: 待净化的字符串。

    Returns:
        净化后的字符串，永不为空（最短为 ``_``）。
    """
    # 第一步：替换非法字符与控制字符为 _
    sanitized = _ILLEGAL_CHARS_RE.sub("_", name)
    # 第二步：替换首尾点号为 _
    sanitized = _OUTER_PERIODS_RE.sub("_", sanitized)
    # 第三步：Windows 保留名追加 _ 后缀
    if _WINDOWS_RESERVED_RE.match(sanitized):
        sanitized = sanitized + "_"
    # 第四步：空字符串回退为 _
    if not sanitized:
        sanitized = "_"
    return sanitized


def _format_timestamp(pubtime: int) -> str:
    """把 Unix 时间戳（秒）格式化为字符串。

    使用 UTC 时区（与 Rust ``pubtime.and_utc().format(...)`` 一致），
    格式由模块常量 :data:`_DEFAULT_TIME_FORMAT` 决定。

    Args:
        pubtime: Unix 时间戳（秒）。0 或负数返回空字符串。

    Returns:
        格式化后的时间字符串，如 ``"2023-11-14 22:13:20"``。
    """
    if pubtime <= 0:
        return ""
    return datetime.fromtimestamp(pubtime, tz=timezone.utc).strftime(
        _DEFAULT_TIME_FORMAT
    )


def _build_video_context(video: VideoInfo) -> dict[str, Any]:
    """基于 :class:`VideoInfo` 构造 video 模板渲染 context。

    含 ``bvid`` / ``title`` / ``upper_name`` / ``upper_mid`` / ``pubtime``
    五个变量。``fav_time`` 不在 :class:`VideoInfo` 中，由阶段 14 下载流水线
    在调用 :func:`render` 时通过 context 传入。

    Args:
        video: 视频元信息。

    Returns:
        模板变量字典。
    """
    return {
        "bvid": video.bvid,
        "title": video.title,
        "upper_name": video.upper_name,
        "upper_mid": video.upper_mid,
        "pubtime": _format_timestamp(video.pubtime),
    }


def _build_page_context(video: VideoInfo, page: Page) -> dict[str, Any]:
    """基于 :class:`VideoInfo` 与 :class:`Page` 构造 page 模板渲染 context。

    在 video context 基础上追加 ``ptitle``（分 P 标题）与 ``pid``
    （分 P 序号）。

    Args:
        video: 视频元信息。
        page: 分 P 信息。

    Returns:
        模板变量字典。
    """
    context = _build_video_context(video)
    context["ptitle"] = page.name
    context["pid"] = page.page
    return context


def build_video_path(
    video_name_template: str,
    base_dir: Path,
    video: VideoInfo,
) -> Path:
    """渲染 video 模板并拼接视频目录路径。

    流程：渲染模板 → filenamify → 还原路径分隔符 → 拼接到 ``base_dir``。

    Args:
        video_name_template: video 名称 Jinja2 模板，如 ``"{{title}}"``。
        base_dir: 视频根目录（如 ``videos/``）。
        video: 视频元信息。

    Returns:
        完整视频目录路径，如 ``base_dir / "净化后的标题"``。

    Raises:
        PathTemplateError: 模板渲染失败（如引用了未定义变量 ``fav_time``）。
    """
    context = _build_video_context(video)
    rendered = render(video_name_template, context)
    sanitized = filenamify(rendered)
    restored = _restore_separators(sanitized)
    return base_dir / restored


def build_page_path(
    page_name_template: str,
    video_dir: Path,
    video: VideoInfo,
    page: Page,
) -> Path:
    """渲染 page 模板并拼接分 P 文件路径。

    流程：渲染模板（含 ``ptitle`` / ``pid``）→ filenamify → 还原路径分隔符
    → 拼接到 ``video_dir``。

    Args:
        page_name_template: page 名称 Jinja2 模板，如 ``"{{bvid}}"``。
        video_dir: 视频目录（由 :func:`build_video_path` 生成）。
        video: 视频元信息。
        page: 分 P 信息。

    Returns:
        完整分 P 文件路径（无扩展名），如
        ``video_dir / "BV1gLfnY8E6D"``。

    Raises:
        PathTemplateError: 模板渲染失败。
    """
    context = _build_page_context(video, page)
    rendered = render(page_name_template, context)
    sanitized = filenamify(rendered)
    restored = _restore_separators(sanitized)
    return video_dir / restored
