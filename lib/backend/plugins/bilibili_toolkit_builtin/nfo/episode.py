"""Episode NFO 元数据生成。

为多页 B 站视频的单个分 P 生成 Emby/Jellyfin 兼容的 Episode NFO XML
字符串，对应 ``{base_name}.nfo`` 文件（与分 P 视频文件同名）。

参考实现：``bili-sync/crates/bili_sync/src/utils/nfo.rs`` 的 ``write_episode_nfo``，
并按 Jellyfin/Emby 官方 NFO 规范补全字段（参考：
https://jellyfin.org/docs/general/server/media/shows/）。

字段映射：
- ``<title>``：分 P 标题（Page.name）
- ``<showtitle>``：剧集标题（VideoInfo.title），Jellyfin 用此字段关联
  本 Episode 与父 TVShow，缺失会导致 Episode 在列表中"无所属剧集"
- ``<season>``：固定为 1（B 站多 P 视频作为单季剧集处理）
- ``<episode>``：分 P 序号（Page.page，从 1 开始）
- ``<plot>``：视频简介 + 原始视频链接
- ``<outline>``：短简介（desc 截断至 150 字符）
- ``<runtime>``：分 P 时长（Page.duration 秒 → 分钟）
- ``<aired>``：发布日期（YYYY-MM-DD）
- ``<studio>``：固定为"bilibili"
- ``<uniqueid default="true" type="bilibili">``：``{aid}_{cid}`` 复合 ID，
  保证分 P 维度唯一；``default="true"`` 告知 Jellyfin 用此 ID 作为主匹配键
- ``<thumb>``：分 P 封面 URL（Jellyfin 优先用同目录 jpg，NFO 中显式声明
  可被元数据 API 检索，并作为 Episode 缩略图 fallback）

Episode NFO 与 TVShow NFO 配套使用，根元素为 ``<episodedetails>``。
Episode NFO 不含 ``<actor>`` 块（UP 主信息在 ``tvshow.nfo`` 中集中声明）。
"""

from __future__ import annotations

from xml.sax.saxutils import escape

from ..bilibili.video import Page, VideoInfo
from .movie import (
    _format_runtime_minutes,
    format_outline,
    format_plot,
    format_pubtime,
)


def render_episode_nfo(video: VideoInfo, page: Page) -> str:
    """渲染 Episode NFO XML 字符串。

    用于多页 B 站视频的单个分 P，保存为 ``{base_name}.nfo``（与分 P 视频
    文件同名），与 ``tvshow.nfo`` 配套使用。

    Args:
        video: 视频元信息（提供 title / desc / bvid / aid / pubtime / cover）。
        page: 分 P 信息（提供 cid / page / name / duration）。

    Returns:
        XML 字符串（UTF-8 编码声明），结尾不含换行。
    """
    # 复用 format_pubtime 仅取 premiered（YYYY-MM-DD），year 在 Episode NFO 中不输出
    _year_str, aired_str = format_pubtime(video.pubtime)
    plot_str: str = format_plot(video.desc, video.bvid)
    outline_str: str = format_outline(video.desc)
    title_str: str = escape(page.name)
    showtitle_str: str = escape(video.title)
    # 分 P 时长：page.duration 秒 → 分钟
    runtime_str: str = _format_runtime_minutes(page.duration)
    # 复合 ID：{aid}_{cid}，保证分 P 维度唯一
    uniqueid_str: str = f"{video.aid}_{page.cid}"

    parts: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<episodedetails>",
        f"    <title>{title_str}</title>",
        f"    <showtitle>{showtitle_str}</showtitle>",
        "    <season>1</season>",
        f"    <episode>{page.page}</episode>",
        f"    <plot>{plot_str}</plot>",
        f"    <outline>{outline_str}</outline>",
        f"    <runtime>{runtime_str}</runtime>",
        f"    <aired>{aired_str}</aired>",
        "    <studio>bilibili</studio>",
        f'    <uniqueid default="true" type="bilibili">{uniqueid_str}</uniqueid>',
    ]
    # 分 P 封面 URL：Jellyfin 优先用同目录同名 jpg，NFO 中显式声明可被 API 检索
    if video.cover:
        parts.append(f"    <thumb>{escape(video.cover)}</thumb>")
    parts.append("</episodedetails>")
    return "\n".join(parts)
