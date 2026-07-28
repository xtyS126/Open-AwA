"""Movie NFO 元数据生成。

为单页 B 站视频生成 Emby/Jellyfin 兼容的 Movie NFO XML 字符串，
对应 ``{video_name}.nfo`` 文件。

参考实现：``bili-sync/crates/bili_sync/src/utils/nfo.rs`` 的 ``write_movie_nfo``，
并按 Jellyfin/Emby 官方 NFO 规范补全字段（参考：
https://jellyfin.org/docs/general/server/media/movies/）。

字段映射：
- ``<title>``：视频标题（VideoInfo.title）
- ``<sorttitle>``：排序标题（与 title 一致，便于 Jellyfin 按字母排序）
- ``<plot>``：视频简介 + 原始视频链接（``https://www.bilibili.com/video/{bvid}/``）
- ``<outline>``：短简介（desc 截断至 150 字符，Jellyfin 列表预览用）
- ``<runtime>``：分 P 时长（秒 → 分钟，至少 1 分钟）
- ``<mpaa>``：内容分级（固定 NR = Not Rated）
- ``<uniqueid default="true" type="bilibili">``：AV 号（aid），default 属性
  告知 Jellyfin 用此 ID 作为主匹配键
- ``<genre>``：视频分类（每个 tag 输出一个 genre 元素，Jellyfin 支持多 genre）
- ``<tag>``：标签（与 genre 同源，Jellyfin 区分 genre 与 tag 两个维度）
- ``<credits>``：编剧（UP 主名，B 站 UP 主承担内容创作角色）
- ``<director>``：导演（UP 主名）
- ``<actor>``：UP 主信息（upper_name / "UP主" 角色 / 头像 URL / 个人页 URL）
- ``<country>``：固定为"中国"
- ``<year>`` / ``<premiered>``：发布时间戳格式化（pubtime）
- ``<studio>``：固定为"bilibili"
- ``<thumb aspect="poster">``：视频封面 URL（Jellyfin 优先用同目录 jpg，NFO
  中显式声明可被元数据 API 检索）
- ``<thumb aspect="fanart">``：背景图 URL（B 站无独立背景图，复用封面）

注意：``VideoInfo`` 无 ``type_name`` 字段，``<genre>`` 改用 ``tags``
适配（与 spec 描述的"视频分类"语义一致）。``runtime`` 取 ``pages[0].duration``
（单页视频仅有一个分 P）。
"""

from __future__ import annotations

from datetime import datetime
from xml.sax.saxutils import escape

from ..bilibili.video import Page, VideoInfo

# outline 字段最大长度：Jellyfin/Emby 列表预览通常显示 1-2 行，
# 150 字符既能保留足够信息又不会撑爆列表 UI
_OUTLINE_MAX_LENGTH: int = 150

# UP 主个人页 URL 模板：B 站空间 URL，用于 NFO <actor><profile> 字段
_UPPER_PROFILE_URL_TEMPLATE: str = "https://space.bilibili.com/{mid}"


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


def format_outline(desc: str) -> str:
    """构造 outline 字段内容：desc 截断至 150 字符（XML 转义后）。

    Jellyfin/Emby 列表视图优先用 ``<outline>`` 显示短简介，过长会被截断
    显示省略号，因此主动截断可避免 UI 撑爆与无意义的传输开销。

    Args:
        desc: 视频简介（可能为空字符串）。

    Returns:
        截断并 XML 转义后的 outline 字符串。desc 为空时返回空字符串。
    """
    if not desc:
        return ""
    # 截断时按字符数（Unicode 码点）计算，中文一字一字符
    truncated: str = desc[:_OUTLINE_MAX_LENGTH]
    return escape(truncated)


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


def _format_runtime_minutes(duration_seconds: int) -> str:
    """把秒级时长转换为分钟字符串。

    Jellyfin ``<runtime>`` 字段单位为分钟（整数）。0 秒返回 "0"，
    不足 1 分钟的向上取 1（避免 0 分钟被 Jellyfin 视为缺失）。

    Args:
        duration_seconds: 秒级时长。

    Returns:
        分钟字符串（如 "120"）。
    """
    if duration_seconds <= 0:
        return "0"
    minutes: int = max(1, duration_seconds // 60)
    return str(minutes)


def _build_genre_and_tag_lines(tags: list[str]) -> str:
    """根据 tags 列表生成 ``<genre>`` 与 ``<tag>`` XML 行。

    Jellyfin 区分 ``<genre>``（分类）与 ``<tag>``（标签）两个维度，
    B 站 ``tags`` 同时承载两者语义，因此在两个元素中各输出一份，
    让 Jellyfin 用户可按分类或标签两个维度过滤。

    Args:
        tags: 视频标签列表（可能为空）。

    Returns:
        多行 XML 字符串（已含缩进与换行），tags 为空时返回空字符串。
    """
    if not tags:
        return ""
    lines: list[str] = []
    for tag in tags:
        escaped: str = escape(tag)
        lines.append(f"    <genre>{escaped}</genre>")
    for tag in tags:
        escaped = escape(tag)
        lines.append(f"    <tag>{escaped}</tag>")
    return "\n".join(lines)


def _build_actor_block(video: VideoInfo) -> str:
    """构造 ``<actor>`` 块：name + role + thumb + profile。

    Jellyfin Person 元数据会从 ``<actor><thumb>`` 抓取头像缩略图，
    从 ``<actor><profile>`` 跳转个人页。``upper_face`` / ``upper_mid``
    缺失时省略对应子元素，避免输出空 URL。

    Args:
        video: 视频元信息（取 upper_name / upper_face / upper_mid）。

    Returns:
        ``<actor>...</actor>`` XML 块（含缩进）。
    """
    name_str: str = escape(video.upper_name)
    actor_lines: list[str] = [
        "    <actor>",
        f"        <name>{name_str}</name>",
        "        <role>UP主</role>",
    ]
    if video.upper_face:
        actor_lines.append(
            f"        <thumb>{escape(video.upper_face)}</thumb>"
        )
    if video.upper_mid:
        profile_url: str = _UPPER_PROFILE_URL_TEMPLATE.format(mid=video.upper_mid)
        actor_lines.append(
            f"        <profile>{escape(profile_url)}</profile>"
        )
    actor_lines.append("    </actor>")
    return "\n".join(actor_lines)


def _build_thumb_lines(video: VideoInfo) -> str:
    """构造 ``<thumb aspect="...">`` 行：poster + fanart。

    Jellyfin 优先使用同目录的 ``poster.jpg`` / ``fanart.jpg``，
    NFO 中显式声明 URL 可作为元数据 API 检索与fallback。
    B 站无独立背景图，``fanart`` 复用封面 URL。

    Args:
        video: 视频元信息（取 cover URL）。

    Returns:
        多行 XML 字符串，cover 为空时返回空字符串。
    """
    if not video.cover:
        return ""
    escaped: str = escape(video.cover)
    return (
        f'    <thumb aspect="poster">{escaped}</thumb>\n'
        f'    <thumb aspect="fanart">{escaped}</thumb>'
    )


def render_movie_nfo(video: VideoInfo) -> str:
    """渲染 Movie NFO XML 字符串。

    用于单页 B 站视频，保存为 ``{video_name}.nfo``，Emby/Jellyfin 识别为电影。

    Args:
        video: 视频元信息。``pages`` 应至少含一个分 P，``pages[0].duration``
            用于计算 ``<runtime>``。

    Returns:
        XML 字符串（UTF-8 编码声明），结尾不含换行。
    """
    year_str, premiered_str = format_pubtime(video.pubtime)
    plot_str: str = format_plot(video.desc, video.bvid)
    outline_str: str = format_outline(video.desc)
    title_str: str = escape(video.title)
    upper_name_str: str = escape(video.upper_name)
    # 单页视频 runtime 取 pages[0].duration；pages 为空时取 0
    duration_seconds: int = (
        video.pages[0].duration if video.pages else 0
    )
    runtime_str: str = _format_runtime_minutes(duration_seconds)
    genre_tag_lines: str = _build_genre_and_tag_lines(video.tags)
    actor_block: str = _build_actor_block(video)
    thumb_lines: str = _build_thumb_lines(video)

    # 拼接 XML：固定字段 + 动态字段，按 Jellyfin NFO 惯例字段顺序输出
    parts: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<movie>",
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
        f"    <credits>{upper_name_str}</credits>",
        f"    <director>{upper_name_str}</director>",
        "    <country>中国</country>",
        f"    <year>{year_str}</year>",
        f"    <premiered>{premiered_str}</premiered>",
        "    <studio>bilibili</studio>",
        actor_block,
    ])
    if thumb_lines:
        parts.append(thumb_lines)
    parts.append("</movie>")
    return "\n".join(parts)
