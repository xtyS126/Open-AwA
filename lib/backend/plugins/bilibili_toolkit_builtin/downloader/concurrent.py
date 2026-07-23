"""并发分块下载器。

通过 ``Range: bytes=start-end`` 请求将文件切分为 ``concurrency`` 块，
用 ``asyncio.gather`` 并发下载各块并写入文件对应偏移位置。服务器不支持
Range 时回退 :func:`download_stream`；单块过小时也回退串行。

参考实现：``bili-sync/crates/bili_sync/src/downloader.rs`` 的 ``fetch_parallel``。
"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import Optional

import httpx
from loguru import logger

from .serial import DownloadSizeMismatchError, download_stream

# 默认并发数
_DEFAULT_CONCURRENCY: int = 4

# 默认单块最小阈值（20MB），低于此值回退串行
_DEFAULT_THRESHOLD: int = 20 * 1024 * 1024

# 流式下载缓冲区大小（与 serial.py 对齐）
_STREAM_BUFFER_SIZE: int = 2 * 1024 * 1024


async def _probe_range_support(
    client: httpx.AsyncClient,
    url: str,
    headers: dict[str, str],
) -> tuple[bool, int]:
    """探测服务器是否支持 Range 请求。

    发送 ``Range: bytes=0-0`` 探测请求：
    - 206 + ``Content-Range: bytes 0-0/<total>`` → 支持 Range，返回 ``(True, total)``
    - 200 → 不支持 Range，返回 ``(False, content_length)``

    Args:
        client: 已配置好的 httpx 异步客户端。
        url: 文件 URL。
        headers: 基础请求头（不含 Range，函数内会追加）。

    Returns:
        ``(supports_range, total_size)`` 元组。``total_size`` 为文件总字节数；
        若服务端未声明大小则返回 0。

    Raises:
        httpx.HTTPError: 网络层异常或 HTTP 状态码非 2xx。
    """
    probe_headers: dict[str, str] = dict(headers)
    probe_headers["Range"] = "bytes=0-0"

    response = await client.get(url, headers=probe_headers)
    response.raise_for_status()

    if response.status_code == httpx.codes.PARTIAL_CONTENT:
        # 解析 Content-Range: bytes 0-0/<total>
        content_range: Optional[str] = response.headers.get("content-range")
        if content_range and "/" in content_range:
            total_str = content_range.rsplit("/", 1)[-1]
            try:
                return (True, int(total_str))
            except ValueError:
                # Content-Range 格式异常，视为不支持
                logger.warning("Content-Range 格式异常: {}", content_range)
                return (False, 0)
        # 206 但无 Content-Range，视为不支持
        return (False, 0)

    # 200 等普通响应：从 Content-Length 取大小
    content_length_str: Optional[str] = response.headers.get("content-length")
    if content_length_str:
        try:
            return (False, int(content_length_str))
        except ValueError:
            logger.warning("Content-Length 格式异常: {}", content_length_str)
    return (False, 0)


async def _download_chunk(
    client: httpx.AsyncClient,
    url: str,
    start: int,
    end: int,
    file_path: Path,
    offset: int,
    headers: dict[str, str],
) -> int:
    """下载单个字节范围并流式写入文件指定偏移位置。

    使用 ``client.stream("GET", url, Range=bytes=start-end)`` 流式获取响应，
    边接收边写入 ``file_path`` 的 ``offset`` 位置（``f.seek(offset)`` + ``f.write``）。
    完成后校验接收字节数与块大小一致。

    Args:
        client: 已配置好的 httpx 异步客户端。
        url: 文件 URL。
        start: Range 起始字节（含）。
        end: Range 结束字节（含）。
        file_path: 目标文件路径（需已预分配足够大小）。
        offset: 写入文件的起始偏移字节位置。
        headers: 基础请求头（不含 Range，函数内会追加）。

    Returns:
        实际接收字节数。

    Raises:
        httpx.HTTPError: 网络层异常或 HTTP 状态码非 2xx。
        DownloadSizeMismatchError: 接收字节数与块大小不一致。
    """
    chunk_headers: dict[str, str] = dict(headers)
    chunk_headers["Range"] = f"bytes={start}-{end}"
    expected_chunk_size: int = end - start + 1
    received: int = 0

    async with client.stream("GET", url, headers=chunk_headers) as response:
        response.raise_for_status()
        # r+b 模式：文件必须已存在，且不截断；CPython 在 Windows 上默认共享模式
        # 允许其他句柄同时写不同区域，asyncio 单线程内 seek+write 不会被打断
        with open(file_path, "r+b") as fp:
            fp.seek(offset)
            async for chunk in response.aiter_bytes(_STREAM_BUFFER_SIZE):
                fp.write(chunk)
                received += len(chunk)

    if received != expected_chunk_size:
        raise DownloadSizeMismatchError(
            expected=expected_chunk_size, actual=received
        )
    return received


async def _download_chunks_concurrent(
    url: str,
    file_path: Path,
    total_size: int,
    concurrency: int,
    threshold: int,
    headers: dict[str, str],
    timeout: float,
) -> int:
    """切分文件为 ``concurrency`` 块并发下载。

    单块小于 ``threshold`` 时回退串行：调用 :func:`download_stream` 下载该块
    到临时文件后 ``shutil.copyfileobj`` 写入目标偏移位置。所有块通过
    ``asyncio.gather`` 并发执行。

    Args:
        url: 文件 URL。
        file_path: 目标文件路径（需已预分配 ``total_size`` 大小）。
        total_size: 文件总字节数。
        concurrency: 并发块数。
        threshold: 单块回退串行的最小阈值（字节）。
        headers: 基础请求头。
        timeout: 单次请求超时（秒）。

    Returns:
        实际接收字节数（成功时等于 ``total_size``）。
    """
    chunk_size: int = total_size // concurrency
    if chunk_size < threshold:
        # 整体切分后单块过小，整体回退串行
        logger.debug(
            "单块大小 {}B 小于阈值 {}B，整体回退串行下载: url={}",
            chunk_size,
            threshold,
            url,
        )
        return await download_stream(url, file_path, headers=headers, timeout=timeout)

    # 构造各块的 (start, end, offset) 描述；offset 与 start 相同（连续块）
    ranges: list[tuple[int, int, int]] = []
    for i in range(concurrency):
        start: int = i * chunk_size
        # 最后一块承担余数（total_size 可能不被 concurrency 整除）
        end: int = (total_size if i == concurrency - 1 else start + chunk_size) - 1
        ranges.append((start, end, start))

    async with httpx.AsyncClient(timeout=timeout) as client:
        async def _run_one(start: int, end: int, offset: int) -> int:
            """单块下载任务，根据块大小决策并发或回退串行。"""
            block_size: int = end - start + 1
            if block_size < threshold:
                # 单块回退串行：下载到临时文件后 copyfileobj 到目标偏移
                logger.debug(
                    "块 [{}, {}] 大小 {}B 小于阈值，回退串行: url={}",
                    start,
                    end,
                    block_size,
                    url,
                )
                chunk_headers: dict[str, str] = dict(headers)
                chunk_headers["Range"] = f"bytes={start}-{end}"
                # download_stream 内部会创建 .tmp 并原子 rename 回 chunk_tmp_path
                chunk_tmp_path: Path = file_path.with_suffix(
                    file_path.suffix + f".part{offset}.tmp"
                )
                try:
                    received: int = await download_stream(
                        url,
                        chunk_tmp_path,
                        headers=chunk_headers,
                        timeout=timeout,
                    )
                    # 把下载好的块文件内容写入目标文件偏移
                    with open(chunk_tmp_path, "rb") as src, open(file_path, "r+b") as dst:
                        dst.seek(offset)
                        shutil.copyfileobj(src, dst)
                    return received
                finally:
                    if chunk_tmp_path.exists():
                        try:
                            chunk_tmp_path.unlink()
                        except OSError as cleanup_exc:
                            logger.warning(
                                "清理块临时文件失败: tmp={}, err={}",
                                chunk_tmp_path,
                                cleanup_exc,
                            )
            else:
                return await _download_chunk(
                    client, url, start, end, file_path, offset, headers
                )

        results: list[int] = await asyncio.gather(
            *[_run_one(s, e, o) for s, e, o in ranges]
        )

    return sum(results)


async def download_concurrent(
    url: str,
    dest_path: Path,
    concurrency: int = _DEFAULT_CONCURRENCY,
    threshold: int = _DEFAULT_THRESHOLD,
    headers: Optional[dict[str, str]] = None,
    timeout: float = 60.0,
) -> int:
    """并发分块下载文件。

    先发 ``Range: bytes=0-0`` 探测请求：
    - 服务器支持 Range（206）→ 走并发分块
    - 服务器不支持（200）→ 回退 :func:`download_stream`

    Args:
        url: 文件下载 URL。
        dest_path: 目标文件路径。父目录会自动创建。
        concurrency: 并发块数，默认 4。
        threshold: 单块最小阈值（字节），默认 20MB。低于此值回退串行。
        headers: 额外的请求头。
        timeout: 单次请求超时（秒）。

    Returns:
        实际接收字节数。

    Raises:
        httpx.HTTPError: 网络层异常或 HTTP 状态码非 2xx。
        DownloadSizeMismatchError: 接收字节数与文件总大小不一致。
    """
    # 边界保护：concurrency 至少为 1
    if concurrency < 1:
        concurrency = 1

    base_headers: dict[str, str] = dict(headers or {})
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    # 探测 Range 支持
    async with httpx.AsyncClient(timeout=timeout) as client:
        supports_range, total_size = await _probe_range_support(
            client, url, base_headers
        )

    if not supports_range or total_size <= 0:
        logger.debug(
            "服务器不支持 Range 或大小未知，回退串行: url={}, supports_range={}",
            url,
            supports_range,
        )
        return await download_stream(
            url, dest_path, headers=base_headers, timeout=timeout
        )

    # 预分配目标文件大小（用稀疏文件占位，便于各块按偏移 r+b 写入）
    with open(dest_path, "wb") as fp:
        fp.truncate(total_size)

    try:
        received: int = await _download_chunks_concurrent(
            url,
            dest_path,
            total_size,
            concurrency,
            threshold,
            base_headers,
            timeout,
        )
        if received != total_size:
            raise DownloadSizeMismatchError(
                expected=total_size, actual=received
            )
        logger.debug(
            "并发下载完成: url={}, received={}B, concurrency={}",
            url,
            received,
            concurrency,
        )
        return received
    except Exception:
        # 失败时清理部分写入的目标文件，避免残留
        # 捕获 Exception 是为了清理后重新抛出原始异常
        if dest_path.exists():
            try:
                dest_path.unlink()
            except OSError as cleanup_exc:
                logger.warning(
                    "清理下载失败文件失败: path={}, err={}",
                    dest_path,
                    cleanup_exc,
                )
        raise
