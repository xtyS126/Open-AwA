"""
插件市场远端下载器。

负责从远端仓库下载插件包，执行 SHA256 校验，并安全解压到目标目录。
遵循后端规范：超时控制、路径穿越防护、文件大小限制。
"""
import hashlib
import os
import shutil
import zipfile
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import urlparse

import httpx
from loguru import logger

# 下载限制常量
MAX_DOWNLOAD_SIZE_BYTES = 50 * 1024 * 1024  # 50MB
DOWNLOAD_TIMEOUT_SECONDS = 60
DOWNLOAD_CHUNK_SIZE = 8192

# 允许的下载协议白名单
ALLOWED_DOWNLOAD_SCHEMES = {"https", "http"}


class DownloadError(Exception):
    """下载过程基础异常。"""


class DownloadChecksumError(DownloadError):
    """SHA256 校验失败异常。"""


class DownloadSizeError(DownloadError):
    """文件大小超限异常。"""


class DownloadSecurityError(DownloadError):
    """下载源或内容安全违规异常。"""


def _validate_download_url(url: str) -> None:
    """校验下载 URL 的合法性与安全性。"""
    parsed = urlparse(url)
    if parsed.scheme not in ALLOWED_DOWNLOAD_SCHEMES:
        raise DownloadSecurityError(f"不允许的下载协议: {parsed.scheme}")
    if not parsed.netloc:
        raise DownloadSecurityError("下载 URL 缺少域名")


def _validate_zip_member(member_path: str, target_dir: Path) -> Path:
    """
    校验 ZIP 成员路径，防止路径穿越攻击。
    返回解压后的绝对路径。
    """
    target_dir_resolved = target_dir.resolve()
    member_resolved = (target_dir_resolved / member_path).resolve()
    try:
        member_resolved.relative_to(target_dir_resolved)
    except ValueError as exc:
        raise DownloadSecurityError(f"ZIP 成员路径越权: {member_path}") from exc
    return member_resolved


def compute_sha256(file_path: Path) -> str:
    """计算文件的 SHA256 哈希值。"""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(DOWNLOAD_CHUNK_SIZE), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


async def download_plugin_package(
    download_url: str,
    expected_sha256: Optional[str],
    cache_dir: Path,
) -> Tuple[Path, str]:
    """
    异步下载插件包到缓存目录。

    Args:
        download_url: 远端下载地址
        expected_sha256: 期望的 SHA256 校验和（为空则跳过校验）
        cache_dir: 缓存目录

    Returns:
        (下载后的文件路径, 实际 SHA256 值)

    Raises:
        DownloadSecurityError: URL 不合法
        DownloadSizeError: 文件大小超限
        DownloadChecksumError: SHA256 校验失败
        DownloadError: 其他下载失败
    """
    _validate_download_url(download_url)
    cache_dir.mkdir(parents=True, exist_ok=True)

    # 从 URL 提取文件名，回退到默认名称
    parsed = urlparse(download_url)
    file_name = os.path.basename(parsed.path) or "plugin_package.zip"
    if not file_name.endswith(".zip"):
        file_name = f"{file_name}.zip"
    target_path = cache_dir / file_name

    logger.info(
        f"开始下载插件包: url={download_url}, target={target_path}"
    )

    timeout = httpx.Timeout(DOWNLOAD_TIMEOUT_SECONDS, connect=10.0)
    total_size = 0

    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            async with client.stream("GET", download_url) as response:
                response.raise_for_status()
                with open(target_path, "wb") as f:
                    async for chunk in response.aiter_bytes(chunk_size=DOWNLOAD_CHUNK_SIZE):
                        total_size += len(chunk)
                        if total_size > MAX_DOWNLOAD_SIZE_BYTES:
                            raise DownloadSizeError(
                                f"下载文件超过最大限制 {MAX_DOWNLOAD_SIZE_BYTES} 字节"
                            )
                        f.write(chunk)
    except DownloadSizeError:
        # 清理不完整文件后重新抛出
        target_path.unlink(missing_ok=True)
        raise
    except httpx.HTTPStatusError as exc:
        target_path.unlink(missing_ok=True)
        raise DownloadError(f"下载失败，HTTP 状态码: {exc.response.status_code}") from exc
    except httpx.RequestError as exc:
        target_path.unlink(missing_ok=True)
        raise DownloadError(f"下载请求异常: {exc}") from exc

    actual_sha256 = compute_sha256(target_path)
    if expected_sha256 and expected_sha256.lower() != actual_sha256.lower():
        target_path.unlink(missing_ok=True)
        raise DownloadChecksumError(
            f"SHA256 校验失败: 期望 {expected_sha256}, 实际 {actual_sha256}"
        )

    logger.info(
        f"插件包下载完成: path={target_path}, size={total_size}, sha256={actual_sha256}"
    )
    return target_path, actual_sha256


def extract_plugin_package(
    package_path: Path,
    target_dir: Path,
) -> Path:
    """
    安全解压插件包到目标目录。

    Args:
        package_path: 插件包路径
        target_dir: 解压目标目录

    Returns:
        解压后的根目录路径

    Raises:
        DownloadSecurityError: ZIP 成员路径越权
        DownloadError: 解压失败
    """
    target_dir.mkdir(parents=True, exist_ok=True)

    try:
        with zipfile.ZipFile(package_path, "r") as zf:
            # 先校验所有成员路径，防止路径穿越
            for member in zf.namelist():
                _validate_zip_member(member, target_dir)
            # 安全解压
            zf.extractall(target_dir)
    except zipfile.BadZipFile as exc:
        raise DownloadError(f"无效的 ZIP 文件: {exc}") from exc
    except Exception as exc:
        # 解压失败时清理目标目录
        if target_dir.exists():
            shutil.rmtree(target_dir, ignore_errors=True)
        raise DownloadError(f"解压失败: {exc}") from exc

    logger.info(f"插件包解压完成: target={target_dir}")
    return target_dir


def cleanup_package(package_path: Path) -> None:
    """清理下载的插件包文件。"""
    try:
        package_path.unlink(missing_ok=True)
    except Exception as exc:
        logger.warning(f"清理插件包失败: {package_path}, 错误: {exc}")
