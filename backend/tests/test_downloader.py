"""下载器单元测试。

覆盖 ``downloader/serial.py``、``downloader/concurrent.py``、
``downloader/with_backup.py`` 三个模块：
- :func:`download_stream`：串行流式下载与字节数校验
- :func:`download_concurrent`：并发分块下载与回退串行
- :func:`download_with_backup`：多 URL 备份容错
- :class:`DownloadSizeMismatchError` / :class:`AllUrlsFailedError` 异常类

测试隔离：通过 ``monkeypatch`` 注入 ``httpx.MockTransport``，所有 HTTP
请求被路由到内存中的 handler 函数，不访问任何真实网络。

注入策略：定义 ``_PatchedAsyncClient`` 继承 ``httpx.AsyncClient``，
构造时若未显式传 transport 则注入 holder 中的 MockTransport。
被测模块 ``import httpx; httpx.AsyncClient(...)`` 在 monkeypatch 后
会调用 wrapper 类，从而走 MockTransport。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable, Optional

import httpx
import pytest

# 注入 backend 目录到 sys.path
_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from plugins.bilibili_toolkit_builtin.downloader.concurrent import (  # noqa: E402
    _probe_range_support,
    download_concurrent,
)
from plugins.bilibili_toolkit_builtin.downloader.serial import (  # noqa: E402
    DownloadSizeMismatchError,
    download_stream,
)
from plugins.bilibili_toolkit_builtin.downloader.with_backup import (  # noqa: E402
    AllUrlsFailedError,
    download_with_backup,
)


# ---------------------------------------------------------------------------
# MockTransport 注入工具
# ---------------------------------------------------------------------------


@pytest.fixture
def patch_http_client(monkeypatch: pytest.MonkeyPatch):
    """注入 MockTransport 替换 httpx.AsyncClient 的实际 HTTP 请求。

    返回一个 register 函数，调用方注册 handler 后所有 httpx.AsyncClient
    实例（包括被测模块内部创建的）都会使用 MockTransport。

    wrapper class 优先使用调用方显式传入的 transport 参数，便于
    _probe_range_support 等直接传 client 的测试在 fixture 之外独立构造。
    """
    holder: dict[str, Optional[httpx.MockTransport]] = {"transport": None}
    real_async_client = httpx.AsyncClient

    class _PatchedAsyncClient(real_async_client):
        """``httpx.AsyncClient`` 的注入子类，构造时强制注入 MockTransport。"""

        def __init__(self, *args, **kwargs):
            # 调用方未显式传 transport 且 holder 已注册时，注入 holder transport
            if "transport" not in kwargs and holder["transport"] is not None:
                kwargs["transport"] = holder["transport"]
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _PatchedAsyncClient)

    def _register(handler: Callable[[httpx.Request], httpx.Response]) -> None:
        holder["transport"] = httpx.MockTransport(handler)

    return _register


# ---------------------------------------------------------------------------
# download_stream
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_download_stream_writes_file_and_returns_bytes(
    tmp_path: Path,
    patch_http_client,
) -> None:
    """串行下载：写入文件并返回实际字节数。"""
    payload = b"hello world"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=payload,
            headers={"content-length": str(len(payload))},
        )

    patch_http_client(handler)
    dest = tmp_path / "video.m4s"
    received = await download_stream(
        "https://example.com/video.m4s", dest, timeout=5.0
    )
    assert received == len(payload)
    assert dest.read_bytes() == payload
    # 临时文件应已清理（rename 到目标路径）
    assert not dest.with_suffix(".m4s.tmp").exists()


@pytest.mark.asyncio
async def test_download_stream_creates_parent_dir(
    tmp_path: Path,
    patch_http_client,
) -> None:
    """父目录不存在时自动创建。"""
    payload = b"data"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=payload, headers={"content-length": str(len(payload))}
        )

    patch_http_client(handler)
    dest = tmp_path / "subdir" / "nested" / "video.m4s"
    received = await download_stream("https://example.com/v", dest, timeout=5.0)
    assert received == len(payload)
    assert dest.exists()
    assert dest.read_bytes() == payload


@pytest.mark.asyncio
async def test_download_stream_missing_content_length_skips_check(
    tmp_path: Path,
    patch_http_client,
) -> None:
    """响应头无 Content-Length 时跳过字节数校验。"""
    payload = b"no-length-header"

    def handler(request: httpx.Request) -> httpx.Response:
        # 不设置 content-length，模拟 chunked 编码
        return httpx.Response(200, content=payload)

    patch_http_client(handler)
    dest = tmp_path / "video.m4s"
    received = await download_stream("https://example.com/v", dest, timeout=5.0)
    assert received == len(payload)
    assert dest.read_bytes() == payload


@pytest.mark.asyncio
async def test_download_stream_size_mismatch_raises(
    tmp_path: Path,
    patch_http_client,
) -> None:
    """Content-Length 与实际字节数不一致时抛 DownloadSizeMismatchError。"""
    payload = b"short"

    def handler(request: httpx.Request) -> httpx.Response:
        # 声明 100 字节但只返回 5 字节
        return httpx.Response(
            200, content=payload, headers={"content-length": "100"}
        )

    patch_http_client(handler)
    dest = tmp_path / "video.m4s"
    with pytest.raises(DownloadSizeMismatchError) as exc_info:
        await download_stream("https://example.com/v", dest, timeout=5.0)
    assert exc_info.value.expected == 100
    assert exc_info.value.actual == 5
    # 失败时应清理临时文件
    assert not dest.exists()
    assert not dest.with_suffix(".m4s.tmp").exists()


@pytest.mark.asyncio
async def test_download_stream_http_error_raises(
    tmp_path: Path,
    patch_http_client,
) -> None:
    """HTTP 非 2xx 时抛 httpx.HTTPStatusError。"""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, content=b"not found")

    patch_http_client(handler)
    dest = tmp_path / "video.m4s"
    with pytest.raises(httpx.HTTPStatusError):
        await download_stream("https://example.com/v", dest, timeout=5.0)
    # 失败时不应留下目标文件
    assert not dest.exists()


@pytest.mark.asyncio
async def test_download_stream_passes_headers(
    tmp_path: Path,
    patch_http_client,
) -> None:
    """自定义 headers 应透传给 HTTP 请求。"""
    payload = b"data"
    captured_headers: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        # 捕获请求头
        for key, value in request.headers.items():
            captured_headers[key.lower()] = value
        return httpx.Response(
            200, content=payload, headers={"content-length": str(len(payload))}
        )

    patch_http_client(handler)
    dest = tmp_path / "video.m4s"
    await download_stream(
        "https://example.com/v",
        dest,
        headers={"Referer": "https://www.bilibili.com", "User-Agent": "TestAgent/1.0"},
        timeout=5.0,
    )
    assert captured_headers.get("referer") == "https://www.bilibili.com"
    assert captured_headers.get("user-agent") == "TestAgent/1.0"


# ---------------------------------------------------------------------------
# _probe_range_support
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_probe_range_support_returns_true_with_206() -> None:
    """206 响应 + Content-Range 表示支持 Range。"""
    transport = httpx.MockTransport(
        lambda req: httpx.Response(
            206, headers={"content-range": "bytes 0-0/1024"}
        )
    )
    async with httpx.AsyncClient(transport=transport) as client:
        supports, total = await _probe_range_support(
            client, "https://example.com/v", {}
        )
        assert supports is True
        assert total == 1024


@pytest.mark.asyncio
async def test_probe_range_support_returns_false_with_200() -> None:
    """200 响应表示不支持 Range，返回 Content-Length 作为 total。"""
    transport = httpx.MockTransport(
        lambda req: httpx.Response(
            200, headers={"content-length": "2048"}
        )
    )
    async with httpx.AsyncClient(transport=transport) as client:
        supports, total = await _probe_range_support(
            client, "https://example.com/v", {}
        )
        assert supports is False
        assert total == 2048


@pytest.mark.asyncio
async def test_probe_range_support_206_without_content_range() -> None:
    """206 但无 Content-Range 时视为不支持，返回 (False, 0)。"""
    transport = httpx.MockTransport(
        lambda req: httpx.Response(206)
    )
    async with httpx.AsyncClient(transport=transport) as client:
        supports, total = await _probe_range_support(
            client, "https://example.com/v", {}
        )
        assert supports is False
        assert total == 0


@pytest.mark.asyncio
async def test_probe_range_support_200_without_content_length() -> None:
    """200 且无 Content-Length 时返回 (False, 0)。"""
    transport = httpx.MockTransport(
        lambda req: httpx.Response(200)
    )
    async with httpx.AsyncClient(transport=transport) as client:
        supports, total = await _probe_range_support(
            client, "https://example.com/v", {}
        )
        assert supports is False
        assert total == 0


# ---------------------------------------------------------------------------
# download_concurrent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_download_concurrent_with_range_support(
    tmp_path: Path,
    patch_http_client,
) -> None:
    """支持 Range 时使用并发分块下载。"""
    # 100 字节文件，每字节值为索引
    payload = bytes(range(100))

    def handler(request: httpx.Request) -> httpx.Response:
        # 处理 probe 与分块下载两种请求
        range_header = request.headers.get("range", "")
        if range_header == "bytes=0-0":
            # probe 请求
            return httpx.Response(
                206,
                content=b"\x00",
                headers={
                    "content-range": "bytes 0-0/100",
                    "content-length": "1",
                },
            )
        # 分块下载
        # Range: bytes=start-end
        if range_header:
            parts = range_header.replace("bytes=", "").split("-")
            start = int(parts[0])
            end = int(parts[1])
            chunk = payload[start : end + 1]
            return httpx.Response(
                206,
                content=chunk,
                headers={
                    "content-range": f"bytes {start}-{end}/100",
                    "content-length": str(len(chunk)),
                },
            )
        return httpx.Response(200, content=payload)

    patch_http_client(handler)
    dest = tmp_path / "video.m4s"
    received = await download_concurrent(
        "https://example.com/v",
        dest,
        concurrency=4,
        threshold=10,  # 100/4=25 > 10，触发并发
        timeout=5.0,
    )
    assert received == 100
    assert dest.read_bytes() == payload


@pytest.mark.asyncio
async def test_download_concurrent_falls_back_to_serial_when_no_range(
    tmp_path: Path,
    patch_http_client,
) -> None:
    """不支持 Range 时回退串行下载。"""
    payload = b"x" * 50

    def handler(request: httpx.Request) -> httpx.Response:
        range_header = request.headers.get("range", "")
        if range_header == "bytes=0-0":
            # probe 返回 200，不支持 Range
            return httpx.Response(
                200, content=payload, headers={"content-length": "50"}
            )
        # 串行下载整个文件
        return httpx.Response(
            200, content=payload, headers={"content-length": "50"}
        )

    patch_http_client(handler)
    dest = tmp_path / "video.m4s"
    received = await download_concurrent(
        "https://example.com/v",
        dest,
        concurrency=4,
        threshold=10,  # 50/4=12 > 10，但 probe 返回不支持 → 回退串行
        timeout=5.0,
    )
    assert received == 50
    assert dest.read_bytes() == payload


@pytest.mark.asyncio
async def test_download_concurrent_invalid_concurrency_normalized_to_1(
    tmp_path: Path,
    patch_http_client,
) -> None:
    """concurrency <= 0 应被规范化为 1（串行回退路径）。"""
    payload = b"y" * 30

    def handler(request: httpx.Request) -> httpx.Response:
        range_header = request.headers.get("range", "")
        if range_header == "bytes=0-0":
            return httpx.Response(
                206,
                content=b"y",
                headers={
                    "content-range": "bytes 0-0/30",
                    "content-length": "1",
                },
            )
        # 串行下载（concurrency=1 不会分块）
        if range_header:
            parts = range_header.replace("bytes=", "").split("-")
            start = int(parts[0])
            end = int(parts[1])
            chunk = payload[start : end + 1]
            return httpx.Response(
                206,
                content=chunk,
                headers={
                    "content-range": f"bytes {start}-{end}/30",
                    "content-length": str(len(chunk)),
                },
            )
        return httpx.Response(
            200, content=payload, headers={"content-length": "30"}
        )

    patch_http_client(handler)
    dest = tmp_path / "video.m4s"
    # concurrency=0 应被规范化为 1
    received = await download_concurrent(
        "https://example.com/v",
        dest,
        concurrency=0,
        threshold=10,
        timeout=5.0,
    )
    assert received == 30
    assert dest.read_bytes() == payload


# ---------------------------------------------------------------------------
# download_with_backup
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_download_with_backup_first_url_succeeds(
    tmp_path: Path,
    patch_http_client,
) -> None:
    """首 URL 下载成功时直接返回，不尝试 backup。"""
    payload = b"first-success"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=payload, headers={"content-length": str(len(payload))}
        )

    patch_http_client(handler)
    dest = tmp_path / "video.m4s"
    used_url = await download_with_backup(
        ["https://a.example.com/v", "https://b.example.com/v"],
        dest,
        timeout=5.0,
    )
    assert used_url == "https://a.example.com/v"
    assert dest.read_bytes() == payload


@pytest.mark.asyncio
async def test_download_with_backup_falls_to_second_url(
    tmp_path: Path,
    patch_http_client,
) -> None:
    """首 URL 失败时回退到 backup URL。"""
    payload = b"second-success"

    def handler(request: httpx.Request) -> httpx.Response:
        if "a.example.com" in str(request.url):
            # 首 URL 返回 500
            return httpx.Response(500, content=b"server error")
        # backup URL 返回成功
        return httpx.Response(
            200, content=payload, headers={"content-length": str(len(payload))}
        )

    patch_http_client(handler)
    dest = tmp_path / "video.m4s"
    used_url = await download_with_backup(
        ["https://a.example.com/v", "https://b.example.com/v"],
        dest,
        timeout=5.0,
    )
    assert used_url == "https://b.example.com/v"
    assert dest.read_bytes() == payload


@pytest.mark.asyncio
async def test_download_with_backup_all_failed_raises(
    tmp_path: Path,
    patch_http_client,
) -> None:
    """所有 URL 都失败时抛 AllUrlsFailedError。"""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, content=b"server error")

    patch_http_client(handler)
    dest = tmp_path / "video.m4s"
    with pytest.raises(AllUrlsFailedError) as exc_info:
        await download_with_backup(
            ["https://a.example.com/v", "https://b.example.com/v"],
            dest,
            timeout=5.0,
        )
    # 异常应记录所有 URL 的错误
    assert exc_info.value.url_errors is not None
    assert len(exc_info.value.url_errors) == 2


@pytest.mark.asyncio
async def test_download_with_backup_empty_urls_raises(
    tmp_path: Path,
    patch_http_client,
) -> None:
    """空 URL 列表应抛 AllUrlsFailedError 或 ValueError。"""
    patch_http_client(lambda req: httpx.Response(200, content=b""))
    dest = tmp_path / "video.m4s"
    with pytest.raises((AllUrlsFailedError, ValueError)):
        await download_with_backup([], dest, timeout=5.0)


# ---------------------------------------------------------------------------
# 异常类属性测试
# ---------------------------------------------------------------------------


def test_download_size_mismatch_error_attributes() -> None:
    """DownloadSizeMismatchError 应携带 expected / actual 字段。"""
    err = DownloadSizeMismatchError(expected=100, actual=80)
    assert err.expected == 100
    assert err.actual == 80
    assert "100" in str(err)
    assert "80" in str(err)


def test_all_urls_failed_error_has_url_errors() -> None:
    """AllUrlsFailedError 应携带 url_errors 列表。"""
    err = AllUrlsFailedError(
        url_errors=[
            ("https://a.example.com/v", ValueError("a failed")),
            ("https://b.example.com/v", ValueError("b failed")),
        ]
    )
    assert err.url_errors is not None
    assert len(err.url_errors) == 2
    assert err.url_errors[0][0] == "https://a.example.com/v"
    assert isinstance(err.url_errors[0][1], ValueError)


def test_all_urls_failed_error_empty_url_errors() -> None:
    """AllUrlsFailedError 空 url_errors 列表也应可构造。"""
    err = AllUrlsFailedError(url_errors=[])
    assert err.url_errors == []


def test_download_size_mismatch_error_is_exception_subclass() -> None:
    """DownloadSizeMismatchError 应继承 Exception。"""
    assert issubclass(DownloadSizeMismatchError, Exception)


def test_all_urls_failed_error_is_exception_subclass() -> None:
    """AllUrlsFailedError 应继承 Exception。"""
    assert issubclass(AllUrlsFailedError, Exception)
