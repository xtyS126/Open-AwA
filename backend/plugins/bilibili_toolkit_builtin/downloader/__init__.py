"""bilibili-toolkit-builtin HTTP 文件下载器模块。

提供串行流式下载、并发分块下载与多 URL 备份容错三种下载能力，
作为阶段 5+ ffmpeg 合并与下载流水线的基础组件。

模块导出：

- :func:`download_stream`：串行流式下载（单连接）
- :func:`download_concurrent`：并发分块下载（多连接 Range）
- :func:`download_with_backup`：多 URL 备份容错下载
- :class:`DownloadSizeMismatchError`：下载字节数不匹配异常
- :class:`AllUrlsFailedError`：所有 URL 下载均失败异常

参考实现：``bili-sync/crates/bili_sync/src/downloader.rs``
"""

from __future__ import annotations

from .concurrent import download_concurrent
from .serial import DownloadSizeMismatchError, download_stream
from .with_backup import AllUrlsFailedError, download_with_backup

__all__ = [
    "download_stream",
    "download_concurrent",
    "download_with_backup",
    "DownloadSizeMismatchError",
    "AllUrlsFailedError",
]
