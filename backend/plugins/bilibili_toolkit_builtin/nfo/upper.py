"""UP 主 Person NFO 元数据生成。

为 B 站 UP 主生成 Emby/Jellyfin 兼容的 Person NFO XML 字符串，
对应 ``person.nfo`` 文件，保存到 ``{upper_path}/{首字符}/{mid}/`` 目录。

参考实现：``bili-sync/crates/bili_sync/src/utils/nfo.rs`` 的 ``write_upper_nfo``。

字段映射：
- ``<title>``：UP 主名称（upper_name）
- ``<uniqueid type="bilibili">``：UP 主 mid（upper_mid）
- ``<country>``：固定为"中国"

注意：Rust 参考实现中 ``<title>`` 使用 ``upper_id``（mid 的字符串形式），
本实现按 spec 要求使用 ``upper_name``，更符合 Emby/Jellyfin 中 Person
元数据的展示语义（名称而非数字 ID）。
"""

from __future__ import annotations

from xml.sax.saxutils import escape


def render_upper_nfo(upper_mid: int, upper_name: str) -> str:
    """渲染 UP 主 Person NFO XML 字符串。

    用于 Emby/Jellyfin 的 Person 元数据，保存为 ``person.nfo``，
    与 UP 主头像 ``folder.jpg`` 同目录。

    Args:
        upper_mid: UP 主 mid（B 站用户唯一标识）。
        upper_name: UP 主名称（用于 ``<title>`` 展示）。

    Returns:
        XML 字符串（UTF-8 编码声明），结尾不含换行。
    """
    title_str = escape(upper_name)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<Person>\n"
        f"    <title>{title_str}</title>\n"
        f'    <uniqueid type="bilibili">{upper_mid}</uniqueid>\n'
        "    <country>中国</country>\n"
        "</Person>"
    )
