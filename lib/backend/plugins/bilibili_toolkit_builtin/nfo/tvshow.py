"""TVShow NFO 元数据生成。

为多页 B 站视频生成 Emby/Jellyfin 兼容的 TVShow NFO XML 字符串，
对应 ``tvshow.nfo`` 文件，作为整部"剧集"的根元数据。

参考实现：``bili-sync/crates/bili_sync/src/utils/nfo.rs`` 的 ``write_tvshow_nfo``。

字段映射与 :mod:`nfo.movie` 基本一致，根元素改为 ``<tvshow>``：
- ``<title>``：视频（剧集）标题
- ``<plot>``：简介 + 原始视频链接
- ``<actor>``：UP 主信息
- ``<genre>``：视频分类（``tags[0]`` 适配）
- ``<country>`` / ``<year>`` / ``<premiered>`` / ``<studio>``：与 Movie 一致
- ``<uniqueid type="bilibili">``：AV 号（aid）

多页视频下，每个分 P 额外生成 Episode NFO（见 :mod:`nfo.episode`）。
"""

from __future__ import annotations

from xml.sax.saxutils import escape

from ..bilibili.video import VideoInfo
from .movie import format_plot, format_pubtime


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
    plot_str = format_plot(video.desc, video.bvid)
    title_str = escape(video.title)
    upper_name_str = escape(video.upper_name)
    # 视频分类：使用首个 tag（VideoInfo 无 type_name 字段，以 tags 适配）
    genre_str = escape(video.tags[0]) if video.tags else ""

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<tvshow>\n"
        f"    <title>{title_str}</title>\n"
        f"    <plot>{plot_str}</plot>\n"
        "    <actor>\n"
        f"        <name>{upper_name_str}</name>\n"
        "        <role>UP主</role>\n"
        "    </actor>\n"
        f"    <genre>{genre_str}</genre>\n"
        "    <country>中国</country>\n"
        f"    <year>{year_str}</year>\n"
        f"    <premiered>{premiered_str}</premiered>\n"
        "    <studio>bilibili</studio>\n"
        f'    <uniqueid type="bilibili">{video.aid}</uniqueid>\n'
        "</tvshow>"
    )
