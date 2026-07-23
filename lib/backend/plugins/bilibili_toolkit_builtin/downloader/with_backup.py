"""多 URL 备份容错下载器。

按序尝试每个 URL：先并发分块下载，失败则尝试串行。任一 URL 成功立即返回；
所有 URL 失败抛 :class:`AllUrlsFailedError`。

参考实现：``bili-sync/crates/bili_sync/src/downloader.rs`` 的
``multi_fetch_internal``。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from loguru import logger

from .concurrent import download_concurrent
from .serial import download_stream

# 默认并发分块单块最小阈值（20MB），与 concurrent.py 对齐
_DEFAULT_CONCURRENT_THRESHOLD: int = 20 * 1024 * 1024


class AllUrlsFailedError(Exception):
    """所有 URL 下载均失败异常。

    Attributes:
        url_errors: 每个 URL 与对应异常的列表，``[(url, exc), ...]``。
    """

    def __init__(self, url_errors: list[tuple[str, Exception]]) -> None:
        self.url_errors: list[tuple[str, Exception]] = list(url_errors)
        # 聚合每条 URL 的失败原因，便于排查
        parts: list[str] = []
        for url, exc in self.url_errors:
            parts.append(f"  - {url}: {type(exc).__name__}: {exc}")
        joined = "\n".join(parts)
        super().__init__(
            f"所有 URL 下载失败（共 {len(self.url_errors)} 个）:\n{joined}"
        )


async def download_with_backup(
    urls: list[str],
    dest_path: Path,
    headers: Optional[dict[str, str]] = None,
    timeout: float = 60.0,
    concurrent_threshold: int = _DEFAULT_CONCURRENT_THRESHOLD,
) -> str:
    """按序尝试多个 URL 下载到目标路径。

    每个 URL 先尝试 :func:`download_concurrent`，失败则尝试 :func:`download_stream`。
    任一 URL 成功立即返回该 URL；所有 URL 失败才抛 :class:`AllUrlsFailedError`。

    Args:
        urls: 候选 URL 列表（按优先级排序）。
        dest_path: 目标文件路径。
        headers: 额外的请求头。
        timeout: 单次请求超时（秒）。
        concurrent_threshold: 并发分块下载的单块最小阈值（字节）。

    Returns:
        成功下载所使用的 URL。

    Raises:
        AllUrlsFailedError: 所有 URL 均下载失败。
        ValueError: ``urls`` 为空。
    """
    if not urls:
        raise ValueError("urls 不能为空")

    base_headers: dict[str, str] = dict(headers or {})
    url_errors: list[tuple[str, Exception]] = []

    for idx, url in enumerate(urls):
        # 先尝试并发分块下载
        try:
            await download_concurrent(
                url,
                dest_path,
                threshold=concurrent_threshold,
                headers=base_headers,
                timeout=timeout,
            )
            logger.debug(
                "URL 下载成功（并发）: url={}, idx={}/{}",
                url,
                idx,
                len(urls),
            )
            return url
        except Exception as concurrent_exc:
            # 并发下载失败，尝试串行
            # 捕获 Exception 是因为下游可能抛任何异常（HTTP/IO/SizeMismatch），
            # 这里要记录后继续尝试串行而非中断
            logger.debug(
                "并发下载失败，尝试串行: url={}, error={}: {}",
                url,
                type(concurrent_exc).__name__,
                concurrent_exc,
            )
            try:
                await download_stream(
                    url, dest_path, headers=base_headers, timeout=timeout
                )
                logger.debug(
                    "URL 下载成功（串行）: url={}, idx={}/{}",
                    url,
                    idx,
                    len(urls),
                )
                return url
            except Exception as stream_exc:
                logger.debug(
                    "串行下载也失败: url={}, error={}: {}",
                    url,
                    type(stream_exc).__name__,
                    stream_exc,
                )
                url_errors.append((url, stream_exc))
                # 继续尝试下一个 URL

    raise AllUrlsFailedError(url_errors)
