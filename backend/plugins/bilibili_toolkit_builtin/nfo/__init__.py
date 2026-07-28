"""bilibili-toolkit-builtin NFO 元数据生成模块。

为 B 站视频生成 Emby/Jellyfin 兼容的 NFO 元数据文件，包含四种模板：

- :func:`render_movie_nfo`：单页视频 Movie NFO（``{video_name}.nfo``）
- :func:`render_tvshow_nfo`：多页视频 TVShow NFO（``tvshow.nfo``）
- :func:`render_episode_nfo`：多页视频分集 Episode NFO（``{base_name} - S01E01.nfo``）
- :func:`render_upper_nfo`：UP 主 Person NFO（``person.nfo``）
- :func:`save_upper_avatar`：下载 UP 主头像为 ``folder.jpg``

参考实现：``bili-sync/crates/bili_sync/src/utils/nfo.rs`` 的
``write_movie_nfo`` / ``write_tvshow_nfo`` / ``write_episode_nfo`` /
``write_upper_nfo``。

XML 转义约定：title / plot / name 等用户可控字段使用
:func:`xml.sax.saxutils.escape` 处理 ``&`` / ``<`` / ``>`` 三种特殊字符，
避免破坏 XML 结构。
"""

from __future__ import annotations

from .avatar import save_upper_avatar
from .episode import render_episode_nfo
from .movie import render_movie_nfo
from .tvshow import render_tvshow_nfo
from .upper import render_upper_nfo

__all__ = [
    # Movie NFO（单页视频）
    "render_movie_nfo",
    # TVShow NFO（多页视频根）
    "render_tvshow_nfo",
    # Episode NFO（多页视频分集）
    "render_episode_nfo",
    # Upper NFO（UP 主 Person）
    "render_upper_nfo",
    # UP 主头像下载
    "save_upper_avatar",
]
