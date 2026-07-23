"""Episode NFO 元数据生成。

为多页 B 站视频的单个分 P 生成 Emby/Jellyfin 兼容的 Episode NFO XML
字符串，对应 ``{base_name} - S01E01.nfo`` 文件。

参考实现：``bili-sync/crates/bili_sync/src/utils/nfo.rs`` 的 ``write_episode_nfo``。

字段映射：
- ``<title>``：分 P 标题（Page.name）
- ``<season>``：固定为 1（B 站多 P 视频作为单季剧集处理）
- ``<episode>``：分 P 序号（Page.page，从 1 开始）
- ``<plot>``：视频简介 + 原始视频链接
- ``<aired>``：发布日期（YYYY-MM-DD）
- ``<studio>``：固定为"bilibili"
- ``<uniqueid type="bilibili">``：``{aid}_{cid}`` 复合 ID，保证分 P 维度唯一

Episode NFO 与 TVShow NFO 配套使用，根元素为 ``<episodedetails>``。
"""

from __future__ import annotations

from xml.sax.saxutils import escape

from ..bilibili.video import Page, VideoInfo
from .movie import format_plot, format_pubtime


def render_episode_nfo(video: VideoInfo, page: Page) -> str:
    """渲染 Episode NFO XML 字符串。

    用于多页 B 站视频的单个分 P，保存为
    ``{base_name} - S01E{page:02d}.nfo``，与 ``tvshow.nfo`` 配套使用。

    Args:
        video: 视频元信息（提供 desc / bvid / aid / pubtime）。
        page: 分 P 信息（提供 cid / page / name）。

    Returns:
        XML 字符串（UTF-8 编码声明），结尾不含换行。
    """
    # 复用 format_pubtime 仅取 premiered（YYYY-MM-DD），year 在 Episode NFO 中不输出
    _year_str, aired_str = format_pubtime(video.pubtime)
    plot_str = format_plot(video.desc, video.bvid)
    title_str = escape(page.name)
    # 复合 ID：{aid}_{cid}，保证分 P 维度唯一
    uniqueid_str = f"{video.aid}_{page.cid}"

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<episodedetails>\n"
        f"    <title>{title_str}</title>\n"
        "    <season>1</season>\n"
        f"    <episode>{page.page}</episode>\n"
        f"    <plot>{plot_str}</plot>\n"
        f"    <aired>{aired_str}</aired>\n"
        "    <studio>bilibili</studio>\n"
        f'    <uniqueid type="bilibili">{uniqueid_str}</uniqueid>\n'
        "</episodedetails>"
    )
