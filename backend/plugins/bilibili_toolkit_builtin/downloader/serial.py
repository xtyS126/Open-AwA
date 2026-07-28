"""串行流式下载器。

使用 ``httpx.AsyncClient.stream`` 执行单连接流式下载，写入临时文件，
完成后原子 rename 到目标路径，并校验 ``received_bytes`` 与
``Content-Length`` 一致。

参考实现：``bili-sync/crates/bili_sync/src/downloader.rs`` 的 ``fetch_serial``。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import httpx
from loguru import logger

# 流式下载缓冲区大小（2MB），与 Rust 实现的 BufWriter 容量对齐
_STREAM_BUFFER_SIZE: int = 2 * 1024 * 1024


class DownloadSizeMismatchError(Exception):
    """下载字节数与 ``Content-Length`` 不一致异常。

    Attributes:
        expected: 服务端 ``Content-Length`` 声明的字节数。
        actual: 实际接收到的字节数。
    """

    def __init__(self, expected: int, actual: int) -> None:
        self.expected: int = int(expected)
        self.actual: int = int(actual)
        super().__init__(
            f"下载字节数不匹配: expected={self.expected}, actual={self.actual}, "
            f"diff={self.expected - self.actual}"
        )


async def download_stream(
    url: str,
    dest_path: Path,
    headers: Optional[dict[str, str]] = None,
    timeout: float = 60.0,
) -> int:
    """流式下载文件到目标路径。

    使用 ``httpx.AsyncClient.stream`` 执行单连接 GET 请求，将响应字节流
    写入 ``dest_path.with_suffix(dest_path.suffix + ".tmp")`` 临时文件，
    完成后原子 rename 到 ``dest_path``。若响应头含 ``Content-Length``，
    会校验实际接收字节数与声明一致，不一致抛 :class:`DownloadSizeMismatchError`。

    Args:
        url: 文件下载 URL。
        dest_path: 目标文件路径。父目录会自动创建。
        headers: 额外的请求头（如 ``Referer`` / ``User-Agent``）。
        timeout: 单次请求超时（秒）。

    Returns:
        实际接收字节数。

    Raises:
        httpx.HTTPError: 网络层异常或 HTTP 状态码非 2xx。
        DownloadSizeMismatchError: 接收字节数与 ``Content-Length`` 不一致。
    """
    # 确保父目录存在
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    # 临时文件路径：在原扩展名后追加 .tmp，保证同目录 rename 原子
    tmp_path: Path = dest_path.with_suffix(dest_path.suffix + ".tmp")

    request_headers: dict[str, str] = dict(headers or {})
    received_bytes: int = 0

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("GET", url, headers=request_headers) as response:
                # 非 2xx 直接抛 HTTPStatusError
                response.raise_for_status()

                # 读取 Content-Length（可能缺失，如 chunked 编码）
                content_length_str: Optional[str] = response.headers.get("content-length")
                expected_bytes: Optional[int] = (
                    int(content_length_str) if content_length_str else None
                )

                # 同步打开临时文件，按块流式写入
                # 本地磁盘写入通常很快，且单连接不存在并发竞争
                with open(tmp_path, "wb") as fp:
                    async for chunk in response.aiter_bytes(_STREAM_BUFFER_SIZE):
                        fp.write(chunk)
                        received_bytes += len(chunk)

        # 校验字节数（Content-Length 缺失时跳过）
        if expected_bytes is not None and received_bytes != expected_bytes:
            raise DownloadSizeMismatchError(
                expected=expected_bytes, actual=received_bytes
            )

        # 原子 rename 到目标路径（同目录下 os.replace 是原子的）
        tmp_path.replace(dest_path)
        logger.debug(
            "串行下载完成: url={}, received={}B, dest={}",
            url,
            received_bytes,
            dest_path,
        )
        return received_bytes
    except Exception:
        # 失败时清理临时文件，避免残留影响下次下载
        # 这里捕获 Exception 是为了清理后重新抛出原始异常，符合 try/finally 语义
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError as cleanup_exc:
                logger.warning("清理临时文件失败: tmp={}, err={}", tmp_path, cleanup_exc)
        raise
