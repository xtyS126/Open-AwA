"""本地封面图磁盘缓存：共享键原语 + 清理。

图片代理（``GET /api/image-proxy``）会把成功抓取的封面图缓存到
``data/image-cache/`` 下，确保上游 CDN 的签名 URL token 过期后封面
仍可继续加载。这对小红书最为重要——其
``sns-webpic-qc.xhscdn.com`` URL 携带短生命周期的
``{timestamp}/{token}`` 前缀，一旦过期，封面唯一持久的副本就是缓存里
的那张。

本模块拥有缓存键归一化（单一事实源，也被
:mod:`openbiliclaw.api.app` 引用）以及考虑消费状态的清理逻辑，能在不
删除无法再抓取的封面的前提下，控制磁盘增长。

清理规则（联合生效），见 :func:`cleanup_image_cache`：

* **已消费 + 未收藏** —— ``pool_status`` 已终态的内容（用户已看 / 已
  跳过 / 已过期）的封面，且不在收藏或稍后再看中，会被驱逐。可再抓取
  的封面（Bilibili 等，URL 稳定）始终安全——下次浏览时会重新下载。
* **不可再抓取保护** —— 携带轮换 token 的封面（XHS）默认受保护，
  不会被消费型驱逐；缓存是它们唯一的副本。
* **老化孤儿** —— 没有任何活跃内容行引用的缓存文件，超过
  ``max_age_days`` 后会被移除（控制增长的兜底 / 降级模式）。
"""

from __future__ import annotations

import hashlib
import re
import time
from contextlib import suppress
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

import httpx

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

# 在配置的数据目录下懒解析（并缓存）——不是相对路径
# "data/image-cache"，那会相对进程 CWD 解析（打包 Windows 上是只读
# 安装目录），而不是用户的数据目录。
_CACHE_DIR: Path | None = None


def _resolve_cache_dir() -> Path:
    """在配置的数据目录下定位图片缓存。

    使用 ``Config.data_path``（它会遵守 ``OPENBILICLAW_PROJECT_ROOT``
    和自定义 ``data_dir``），所以缓存与用户数据放在一起——例如
    ``%LOCALAPPDATA%/OpenBiliClaw/data/image-cache``——而不是打包可执行
    文件旁边。如果配置尚未就绪，则回退到环境感知的项目根。
    """
    try:
        from openbiliclaw.config import load_config

        return load_config().data_path / "image-cache"
    except Exception:  # noqa: BLE001 — 配置未就绪 → 仍走环境感知的回退
        from openbiliclaw.config import _project_root

        return _project_root() / "data" / "image-cache"


# XHS CDN 签名 URL：https://sns-webpic-qc.xhscdn.com/{ts:12}/{token:hex}/{path}
# {ts}/{token} 前缀在每次重新生成时轮换；{path} 是稳定的。
_XHS_TOKEN_RE = re.compile(r"(https?://[^/]*xhscdn\.com)/\d{12}/[0-9a-f]+/(.*)")

# content_cache.pool_status 中表示"用户已结束这条内容"的值：
# 已被展示并处理过、或已过期。``fresh``（待处理）和 ``suppressed``
# （临时隐藏，可能复活为 fresh）被刻意排除——它们的封面仍然需要。
CONSUMED_POOL_STATUSES: frozenset[str] = frozenset(
    {"shown", "feedbacked", "stale", "purged_by_dislike"}
)

_VALID_IMAGE_EXTS: frozenset[str] = frozenset({"jpeg", "jpg", "png", "webp", "avif", "gif"})
_CONTENT_TYPE_BY_EXTENSION: dict[str, str] = {
    "jpeg": "image/jpeg",
    "jpg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "avif": "image/avif",
    "gif": "image/gif",
}


def _https_normalize(url: str) -> str:
    """与前端 ``normalizeCoverUrl`` 对齐：协议相对 / http → https。

    浏览器在构造代理 URL 之前会做这一步，所以缓存键基于 https 形式。
    清理逻辑读取原始 ``content_cache.cover_url``（可能是 ``//…`` 或
    ``http://…``），必须应用同样的步骤才能匹配。
    """
    u = (url or "").strip()
    if u.startswith("//"):
        return f"https:{u}"
    if u.startswith("http://"):
        return f"https://{u[len('http://') :]}"
    return u


def normalize_cache_url(url: str) -> str:
    """把封面 URL 归一化为稳定的缓存身份（https + 去 token）。"""
    u = _https_normalize(url)
    m = _XHS_TOKEN_RE.match(u)
    if m:
        return f"{m.group(1)}/{m.group(2)}"
    return u


def image_cache_key(url: str) -> str:
    """归一化后 URL 的 SHA-256——缓存文件名主干。"""
    return hashlib.sha256(normalize_cache_url(url).encode()).hexdigest()


def is_refetchable(url: str) -> bool:
    """驱逐后是否还能重新抓取封面。

    仅对携带轮换/过期 token 的 URL（XHS）返回 False——缓存副本是它们
    唯一持久的来源，所以清理时不能删除它们。
    """
    return _XHS_TOKEN_RE.match(_https_normalize(url)) is None


def image_cache_dir() -> Path:
    """返回缓存目录（在数据目录下解析一次），并创建它。"""
    global _CACHE_DIR
    if _CACHE_DIR is None:
        _CACHE_DIR = _resolve_cache_dir()
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return _CACHE_DIR


def image_cache_extension(content_type: str) -> str:
    """把 ``Content-Type`` 映射为缓存文件扩展名（默认 ``jpg``）。"""
    ext = content_type.split("/")[-1].split(";")[0].strip().lower()
    return ext if ext in _VALID_IMAGE_EXTS else "jpg"


@dataclass
class CleanupResult:
    """一次 :func:`cleanup_image_cache` 的结果。"""

    removed: int = 0
    freed_bytes: int = 0
    removed_consumed: int = 0
    removed_aged_orphans: int = 0
    protected_unrefetchable: int = 0


class CoverLifecycleSource(Protocol):
    """:func:`cleanup_image_cache` 所需的最小数据库接口。"""

    def iter_cover_lifecycle(self) -> Iterable[tuple[str, str, bool]]:
        """为每个被缓存的候选项产出 ``(cover_url, pool_status, is_saved)``。"""
        ...


def cleanup_image_cache(
    *,
    database: CoverLifecycleSource | None = None,
    max_age_days: int = 30,
    consumed_statuses: Iterable[str] = CONSUMED_POOL_STATUSES,
    protect_unrefetchable: bool = True,
    cache_dir: Path | None = None,
    now: float | None = None,
) -> CleanupResult:
    """修剪缓存的封面图。

    Args:
        database: 封面生命周期行的来源。当为 ``None``（降级模式）时，
            只运行老化孤儿兜底。
        max_age_days: 没有内容行引用的文件的老化孤儿截止时间。
        consumed_statuses: 视为已消费的 ``pool_status`` 值。
        protect_unrefetchable: 即使内容已消费 + 未收藏，也保留无法再
            抓取的封面（XHS token）。
        cache_dir: 覆盖缓存目录（测试用）。
        now: 覆盖当前 epoch 秒（测试用）。

    Returns:
        含计数和释放字节数的 :class:`CleanupResult`。
    """
    directory = cache_dir if cache_dir is not None else image_cache_dir()
    result = CleanupResult()
    current = time.time() if now is None else now
    cutoff = current - max_age_days * 86400

    files = [p for p in directory.glob("*.*") if p.is_file()]
    if not files:
        return result

    # 跨所有引用该缓存键的内容行聚合状态。
    needed: set[str] = set()  # 某行已收藏或仍在待处理 → 永不驱逐
    consumed_only: set[str] = set()  # 所有引用行都已消费 + 未收藏
    unrefetchable: set[str] = set()
    referenced: set[str] = set()
    consumed = frozenset(consumed_statuses)
    if database is not None:
        with suppress(Exception):
            for cover_url, status, is_saved in database.iter_cover_lifecycle():
                if not cover_url:
                    continue
                key = image_cache_key(cover_url)
                referenced.add(key)
                if not is_refetchable(cover_url):
                    unrefetchable.add(key)
                if is_saved or status not in consumed:
                    needed.add(key)
                else:
                    consumed_only.add(key)

    def _unlink(path: Path) -> int | None:
        try:
            size = path.stat().st_size
            path.unlink()
        except OSError:
            return None
        return size

    for path in files:
        key = path.stem
        if key not in referenced:
            # 孤儿：没有内容行指向这里。老化后再删除。
            with suppress(OSError):
                if path.stat().st_mtime >= cutoff:
                    continue
            size = _unlink(path)
            if size is not None:
                result.removed += 1
                result.freed_bytes += size
                result.removed_aged_orphans += 1
            continue
        if key in needed:
            # 仍在待处理或已收藏（收藏 / 稍后再看）——始终保留。
            continue
        if key not in consumed_only:
            continue
        if protect_unrefetchable and key in unrefetchable:
            result.protected_unrefetchable += 1
            continue
        size = _unlink(path)
        if size is not None:
            result.removed += 1
            result.freed_bytes += size
            result.removed_consumed += 1

    return result


# ── 封面抓取（代理路由和预取扫描共用） ────────────────────────────────────
#
# 下方的白名单 + 重定向 + 大小/类型校验是所有服务端图片抓取的 SSRF
# 防护边界。它放在这里（单一事实源），让 ``api.app`` 的
# ``/api/image-proxy`` 路由与 RefreshRuntime 的预取扫描共享完全相同的
# 安全检查。失败时抛出 CoverFetchError，携带代理暴露的 HTTP 状态码；
# 路由会把它映射为 HTTPException。

ALLOWED_IMAGE_HOST_SUFFIXES: tuple[str, ...] = (
    "hdslb.com",
    "xhscdn.com",
    "pstatp.com",
    "douyinpic.com",
    "douyinvod.com",
    "ytimg.com",
    "ggpht.com",
)
MAX_IMAGE_BYTES = 10 * 1024 * 1024
_FETCH_TIMEOUT_SECONDS = 10.0
_MAX_REDIRECTS = 3
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_UPSTREAM_HEADERS = {
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36"
    ),
}


class CoverFetchError(Exception):
    """封面抓取失败。``status_code`` 与代理的 HTTP 语义一致。"""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def is_allowed_image_host(hostname: str) -> bool:
    """域边界白名单匹配（``host == suffix`` 或 ``*.suffix``）。"""
    host = hostname.rstrip(".").lower()
    return any(
        host == suffix or host.endswith(f".{suffix}") for suffix in ALLOWED_IMAGE_HOST_SUFFIXES
    )


def is_allowed_image_url(url: str) -> bool:
    """廉价预检（无网络），用于跳过不可代理的 URL。

    接受存储在 ``content_cache.cover_url`` 中的协议相对 ``//host/…``
    和 ``http://`` 形式，先归一化为 https（与缓存键一致）。
    """
    try:
        parsed = httpx.URL(_https_normalize(url))
    except httpx.InvalidURL:
        return False
    return bool(
        parsed.scheme in {"http", "https"}
        and parsed.host
        and not parsed.userinfo
        and is_allowed_image_host(parsed.host)
    )


def _parse_image_url(raw_url: str) -> httpx.URL:
    # 先把 //host 和 http:// 归一化为 https，使预取路径（读取原始
    # content_cache.cover_url）与代理路径（已归一化）保持一致，且抓取
    # 到的字节缓存到代理查找的同一个键下。
    try:
        parsed = httpx.URL(_https_normalize(raw_url))
    except httpx.InvalidURL as exc:
        raise CoverFetchError(400, "Invalid URL") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.host:
        raise CoverFetchError(400, "Invalid URL")
    if parsed.userinfo:
        raise CoverFetchError(400, "Invalid URL")
    if not is_allowed_image_host(parsed.host):
        raise CoverFetchError(403, "Domain not in whitelist")
    return parsed


def _validate_content_headers(headers: httpx.Headers) -> str:
    content_type = str(headers.get("content-type", "")).strip()
    if not content_type.lower().startswith("image/"):
        raise CoverFetchError(400, "Not an image")
    content_length = headers.get("content-length")
    if content_length:
        try:
            size = int(content_length)
        except ValueError as exc:
            raise CoverFetchError(502, "Invalid upstream content length") from exc
        if size > MAX_IMAGE_BYTES:
            raise CoverFetchError(413, "Image too large")
    return content_type


async def _send_with_redirects(client: httpx.AsyncClient, url: httpx.URL) -> httpx.Response:
    current = url
    seen: set[str] = set()
    for _ in range(_MAX_REDIRECTS + 1):
        current = _parse_image_url(str(current))
        current_key = str(current)
        if current_key in seen:
            raise CoverFetchError(502, "Redirect loop")
        seen.add(current_key)
        request = client.build_request("GET", current_key, headers=_UPSTREAM_HEADERS)
        response = await client.send(request, stream=True)
        if response.status_code in _REDIRECT_STATUSES:
            location = response.headers.get("location", "").strip()
            await response.aclose()
            if not location:
                raise CoverFetchError(502, "Invalid redirect")
            current = current.join(location)
            continue
        return response
    raise CoverFetchError(502, "Too many redirects")


async def _read_bounded(response: httpx.Response) -> bytes:
    chunks: list[bytes] = []
    total = 0
    async for chunk in response.aiter_bytes():
        total += len(chunk)
        if total > MAX_IMAGE_BYTES:
            raise CoverFetchError(413, "Image too large")
        chunks.append(chunk)
    return b"".join(chunks)


async def fetch_cover_bytes(url: str) -> tuple[bytes, str]:
    """抓取白名单内的封面图，返回 ``(data, content_type)``。

    强制 scheme/host 白名单、手动重定向再校验（最多 3 跳）、
    ``image/*`` content type，以及 10MB 上限（当 ``Content-Length``
    超限时在读 body 之前就拒绝，否则在读过程中拒绝）。任何失败都抛出
    :class:`CoverFetchError`（400/403/413/502/504）。
    """
    parsed = _parse_image_url(url)
    try:
        async with httpx.AsyncClient(
            timeout=_FETCH_TIMEOUT_SECONDS,
            follow_redirects=False,
        ) as client:
            response = await _send_with_redirects(client, parsed)
            try:
                if response.status_code < 200 or response.status_code >= 300:
                    raise CoverFetchError(502, "Upstream request failed")
                content_type = _validate_content_headers(response.headers)
                data = await _read_bounded(response)
            finally:
                await response.aclose()
    except httpx.TimeoutException as exc:
        raise CoverFetchError(504, "Upstream request timed out") from exc
    except httpx.HTTPError as exc:
        raise CoverFetchError(502, "Upstream request failed") from exc
    return data, content_type


def save_image_bytes(url: str, data: bytes, content_type: str) -> None:
    """把抓取到的封面字节持久化到磁盘缓存（尽力而为）。"""
    path = image_cache_dir() / f"{image_cache_key(url)}.{image_cache_extension(content_type)}"
    with suppress(OSError):
        path.write_bytes(data)


def is_cover_cached(url: str) -> bool:
    """若磁盘上已有该封面的非空缓存副本，返回 True。"""
    for candidate in image_cache_dir().glob(f"{image_cache_key(url)}.*"):
        with suppress(OSError):
            if candidate.stat().st_size > 0:
                return True
    return False


def _cached_cover_bytes(url: str) -> tuple[bytes, str] | None:
    """当存在非空缓存文件时，返回缓存的封面字节。"""
    for candidate in image_cache_dir().glob(f"{image_cache_key(url)}.*"):
        ext = candidate.suffix.lower().lstrip(".")
        if ext not in _CONTENT_TYPE_BY_EXTENSION:
            continue
        with suppress(OSError):
            data = candidate.read_bytes()
            if data:
                return data, _CONTENT_TYPE_BY_EXTENSION[ext]
    return None


async def get_or_fetch_cover_bytes(url: str) -> tuple[bytes, str]:
    """优先从磁盘缓存返回封面字节，未命中时抓取并缓存。"""
    _parse_image_url(url)
    cached = _cached_cover_bytes(url)
    if cached is not None:
        return cached

    data, content_type = await fetch_cover_bytes(url)
    save_image_bytes(url, data, content_type)
    return data, content_type


def select_prefetch_targets(urls: Iterable[str], *, max_fetch: int) -> list[str]:
    """挑选当前值得预取的候选封面 URL。

    只保留白名单内、尚未缓存的 URL（去重，保持输入顺序），把不可再抓取
    （XHS 轮换 token）的封面排到前面——因为它们会过期，而可再抓取的
    不会；最后用 ``max_fetch`` 截断结果。
    """
    todo: list[str] = []
    seen: set[str] = set()
    for url in urls:
        if url in seen:
            continue
        seen.add(url)
        if not is_allowed_image_url(url) or is_cover_cached(url):
            continue
        todo.append(url)
    # is_refetchable 为 False（XHS token）排到 True 之前 → 易失封面优先。
    todo.sort(key=is_refetchable)
    return todo[:max_fetch]


async def prefetch_cover(url: str) -> bool:
    """在 CDN token 仍新鲜时抓取 + 缓存封面（尽力而为）。

    仅当写入了新的缓存条目时返回 True。永不抛异常——预取是机会主义
    行为，任何白名单 / 网络 / 上游失败都会被吞掉。
    """
    if not is_allowed_image_url(url) or is_cover_cached(url):
        return False
    try:
        data, content_type = await fetch_cover_bytes(url)
    except Exception:
        return False
    save_image_bytes(url, data, content_type)
    return True
