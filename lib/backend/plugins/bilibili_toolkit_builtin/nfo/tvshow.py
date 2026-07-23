"""TVShow NFO 元数据生成。

为多页 B 站视频生成 Emby/Jellyfin 兼容的 TVShow NFO XML 字符串，
对应 ``tvshow.nfo`` 文件，作为整部"剧集"的根元数据。

参考实现：``bili-sync/crates/bili_sync/src/utils/nfo.rs`` 的 ``write_tvshow_nfo``，
并按 Jellyfin/Emby 官方 NFO 规范补全字段（参考：
https://jellyfin.org/docs/general/server/media/shows/）。

字段映射与 :mod:`nfo.movie` 基本一致，根元素改为 ``<tvshow>``：
- ``<title>``：视频（剧集）标题
- ``<sorttitle>``：排序标题
- ``<plot>``：简介 + 原始视频链接
- ``<outline>``：短简介（desc 截断至 150 字符）
- ``<runtime>``：剧集总时长（所有分 P duration 之和，秒 → 分钟）
- ``<mpaa>``：内容分级（固定 NR）
- ``<uniqueid default="true" type="bilibili">``：AV 号（aid）
- ``<genre>`` / ``<tag>``：每个 tag 输出一对 genre+tag
- ``<actor>``：UP 主信息（含 thumb 头像 URL + profile 个人页 URL）
- ``<country>`` / ``<year>`` / ``<premiered>`` / ``<studio>``：与 Movie 一致

多页视频下，每个分 P 额外生成 Episode NFO（见 :mod:`nfo.episode`）。
TVShow NFO 不输出 ``<thumb>``：Jellyfin 优先使用同目录 ``poster.jpg``，
封面下载子任务会把 ``video.cover`` 保存为分 P 同名 jpg，剧集根海报由
Jellyfin 在扫描时自动从分 P 封面中选取或由用户手动放置。
"""

from __future__ import annotations

from xml.sax.saxutils import escape

from ..bilibili.video import VideoInfo
from .movie import (
    _build_actor_block,
    _build_genre_and_tag_lines,
    _format_runtime_minutes,
    format_outline,
    format_plot,
    format_pubtime,
)


def _compute_total_runtime_seconds(video: VideoInfo) -> int:
    """计算剧集总时长（所有分 P duration 之和）。

    多页视频的 TVShow NFO ``<runtime>`` 应反映整部剧集总时长，
    便于 Jellyfin 在剧集列表中展示"总时长 X 小时"。

    Args:
        video: 视频元信息（含 pages 列表）。

    Returns:
        总时长（秒），pages 为空或 duration 全为 0 时返回 0。
    """
    if not video.pages:
        return 0
    return sum(max(0, p.duration) for p in video.pages)


def render_tvshow_nfo(video: VideoInfo) -> str:
    """渲染 TVShow NFO XML 字符串。

    用于多页 B 站视频根元数据，保存为 ``tvshow.nfo``，
    Emby/Jellyfin 识别为整部剧集。每个分 P 另存为 Episode NFO。

    Args:
        video: 视频元信息。

    Returns:
        XML 字符串（UTF-8 编码声明），结尾不含换行。
    """
    year_str, premiered_str = format_pubtime(video.pubtime)
    plot_str: str = format_plot(video.desc, video.bvid)
    outline_str: str = format_outline(video.desc)
    title_str: str = escape(video.title)
    # 剧集总时长 = 所有人分 P duration 之和
    total_seconds: int = _compute_total_runtime_seconds(video)
    runtime_str: str = _format_runtime_minutes(total_seconds)
    genre_tag_lines: str = _build_genre_and_tag_lines(video.tags)
    actor_block: str = _build_actor_block(video)

    parts: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<tvshow>",
        f"    <title>{title_str}</title>",
        f"    <sorttitle>{title_str}</sorttitle>",
        f"    <plot>{plot_str}</plot>",
        f"    <outline>{outline_str}</outline>",
        f"    <runtime>{runtime_str}</runtime>",
        "    <mpaa>NR</mpaa>",
        f'    <uniqueid default="true" type="bilibili">{video.aid}</uniqueid>',
    ]
    if genre_tag_lines:
        parts.append(genre_tag_lines)
    parts.extend([
        "    <country>中国</country>",
        f"    <year>{year_str}</year>",
        f"    <premiered>{premiered_str}</premiered>",
        "    <studio>bilibili</studio>",
        actor_block,
    ])
    parts.append("</tvshow>")
    return "\n".join(parts)
