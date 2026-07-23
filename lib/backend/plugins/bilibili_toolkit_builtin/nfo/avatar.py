"""UP 主头像下载与 Person NFO 落盘。

下载 UP 主头像保存为 ``folder.jpg``，并在同目录写入 ``person.nfo``，
目录结构为 ``{upper_root}/{首字符}/{upper_mid}/``。

参考实现：``bili-sync/crates/bili_sync/src/utils/nfo.rs`` 的
``write_upper_nfo`` 与 ``bili-sync`` workflow 中 UP 主头像下载逻辑。

目录结构设计：``{首字符}`` 分桶避免单目录过多 UP 主子目录，提升文件系统
列举性能；``{upper_mid}`` 作为最终目录名保证全局唯一。

调用 :func:`downloader.serial.download_stream` 执行 HTTP 下载，请求头
携带 B 站 User-Agent 与 Referer 避免触发防盗链。
"""

from __future__ import annotations

from pathlib import Path

from loguru import logger

from ..bilibili.client import DEFAULT_USER_AGENT
from ..downloader.serial import download_stream
from .upper import render_upper_nfo

# UP 主头像下载请求超时（秒），头像文件通常较小，30 秒足够
_AVATAR_DOWNLOAD_TIMEOUT: float = 30.0

# UP 主头像在 Emby/Jellyfin 中的标准文件名
_AVATAR_FILENAME: str = "folder.jpg"

# UP 主 Person NFO 文件名
_PERSON_NFO_FILENAME: str = "person.nfo"

# 头像下载请求头：Referer 设置为 B 站主页以绕过基础防盗链
_AVATAR_REQUEST_HEADERS: dict[str, str] = {
    "User-Agent": DEFAULT_USER_AGENT,
    "Referer": "https://www.bilibili.com/",
}


def _compute_first_char(upper_name: str, upper_mid: int) -> str:
    """计算 UP 主目录分桶首字符。

    优先使用 ``upper_name`` 首字符；名称为空时回退到 ``upper_mid``
    字符串首字符（避免空目录名）。

    Args:
        upper_name: UP 主名称。
        upper_mid: UP 主 mid。

    Returns:
        单字符字符串，用作目录分桶。
    """
    if upper_name:
        return upper_name[0]
    return str(upper_mid)[0] if upper_mid else "_"


async def save_upper_avatar(
    upper_mid: int,
    upper_name: str,
    avatar_url: str,
    upper_root: Path,
) -> Path:
    """下载 UP 主头像并写入 Person NFO。

    将头像保存为 ``{upper_root}/{首字符}/{upper_mid}/folder.jpg``，
    同目录写入 ``person.nfo``。目录不存在时自动创建。

    Args:
        upper_mid: UP 主 mid（B 站用户唯一标识）。
        upper_name: UP 主名称（用于 NFO ``<title>`` 与首字符分桶）。
        avatar_url: UP 主头像 URL（通常来自 ``VideoInfo.upper_face``）。
        upper_root: UP 主元数据根目录（对应配置项 ``upper_path``）。

    Returns:
        保存目录路径（``{upper_root}/{首字符}/{upper_mid}/``）。

    Raises:
        httpx.HTTPError: 头像下载网络层异常。
        DownloadSizeMismatchError: 头像字节数与 Content-Length 不一致。
    """
    # 计算分桶首字符与目标目录
    first_char: str = _compute_first_char(upper_name, upper_mid)
    dest_dir: Path = upper_root / first_char / str(upper_mid)
    dest_dir.mkdir(parents=True, exist_ok=True)

    # 下载头像为 folder.jpg
    avatar_path: Path = dest_dir / _AVATAR_FILENAME
    await download_stream(
        url=avatar_url,
        dest_path=avatar_path,
        headers=_AVATAR_REQUEST_HEADERS,
        timeout=_AVATAR_DOWNLOAD_TIMEOUT,
    )
    logger.debug(
        "UP 主头像已保存: mid={}, name={}, dest={}",
        upper_mid,
        upper_name,
        avatar_path,
    )

    # 同目录写入 person.nfo
    nfo_path: Path = dest_dir / _PERSON_NFO_FILENAME
    nfo_content: str = render_upper_nfo(upper_mid, upper_name)
    # 同步写入即可，NFO 文件很小（< 1KB），无需异步 I/O
    nfo_path.write_text(nfo_content, encoding="utf-8")
    logger.debug("UP 主 Person NFO 已保存: dest={}", nfo_path)

    return dest_dir
