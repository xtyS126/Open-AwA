"""Movie NFO 元数据生成。

为单页 B 站视频生成 Emby/Jellyfin 兼容的 Movie NFO XML 字符串，
对应 ``{video_name}.nfo`` 文件。

参考实现：``bili-sync/crates/bili_sync/src/utils/nfo.rs`` 的 ``write_movie_nfo``。

字段映射：
- ``<title>``：视频标题（VideoInfo.title）
- ``<plot>``：视频简介 + 原始视频链接（``https://www.bilibili.com/video/{bvid}/``）
- ``<actor>``：UP 主信息（upper_name / "UP主" 角色）
- ``<genre>``：视频分类（VideoInfo.tags 首个标签，若存在；否则空字符串）
- ``<country>``：固定为"中国"
- ``<year>`` / ``<premiered>``：发布时间戳格式化（pubtime）
- ``<studio>``：固定为"bilibili"
- ``<uniqueid type="bilibili">``：AV 号（aid）

注意：``VideoInfo`` 无 ``type_name`` 字段，``<genre>`` 改用 ``tags[0]``
适配（与 spec 描述的"视频分类"语义一致）。
"""

from __future__ import annotations

from datetime import datetime
from xml.sax.saxutils import escape

from ..bilibili.video import VideoInfo


def format_plot(desc: str, bvid: str) -> str:
    """构造 plot 字段内容：简介 + 原始视频链接（XML 转义后）。

    Args:
        desc: 视频简介（可能为空字符串）。
        bvid: BV 号。

    Returns:
        拼接后的 plot 字符串，已做 XML 转义。
        desc 为空时仅保留链接，避免前导空格。
    """
    if desc:
        raw = f"{desc} https://www.bilibili.com/video/{bvid}/"
    else:
        raw = f"https://www.bilibili.com/video/{bvid}/"
    return escape(raw)


def format_pubtime(pubtime: int) -> tuple[str, str]:
    """将 unix 秒级时间戳格式化为 (year, YYYY-MM-DD) 元组。

    Args:
        pubtime: unix 秒级时间戳。

    Returns:
        (year_str, premiered_str) 元组。pubtime <= 0 时返回 ("", "")，
        避免产生 1970-01-01 这种无意义日期。
    """
    if pubtime <= 0:
        return "", ""
    dt = datetime.fromtimestamp(pubtime)
    return dt.strftime("%Y"), dt.strftime("%Y-%m-%d")


def render_movie_nfo(video: VideoInfo) -> str:
    """渲染 Movie NFO XML 字符串。

    用于单页 B 站视频，保存为 ``{video_name}.nfo``，Emby/Jellyfin 识别为电影。

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
        "<movie>\n"
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
        "</movie>"
    )
