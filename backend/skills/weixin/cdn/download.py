"""
CDN 下载与解密模块
实现微信 CDN 文件下载、AES 解密和缓存管理功能。
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import httpx
from loguru import logger

from backend.skills.weixin_skill_adapter import WeixinAdapterError

DEFAULT_CDN_BASE_URL = "https://novac2c.cdn.weixin.qq.com/c2c"
DEFAULT_CACHE_DIR = "cdn_cache"
CACHE_EXPIRE_SECONDS = 3600 * 24
MAX_DOWNLOAD_RETRIES = 3
RETRY_DELAY_SECONDS = 1


@dataclass
class DownloadResult:
    """
    CDN 下载结果数据结构。
    包含解密后的文件数据和元信息。
    """
    data: bytes
    raw_size: int
    content_type: str
    cache_hit: bool
    download_time_seconds: float


@dataclass
class CacheEntry:
    """
    缓存条目数据结构。
    """
    file_path: str
    raw_size: int
    content_type: str
    created_at: float
    aeskey: str


def aes_ecb_decrypt(ciphertext: bytes, key: bytes) -> bytes:
    """
    使用 AES-128-ECB 模式解密数据。
    
    参数:
        ciphertext: 加密数据
        key: 16 字节 AES 密钥
        
    返回:
        解密后的原始数据（自动去除 PKCS7 填充）
    """
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives import padding
    from cryptography.hazmat.backends import default_backend
    
    cipher = Cipher(algorithms.AES(key), modes.ECB(), backend=default_backend())
    decryptor = cipher.decryptor()
    
    padded_data = decryptor.update(ciphertext) + decryptor.finalize()
    
    unpadder = padding.PKCS7(128).unpadder()
    return unpadder.update(padded_data) + unpadder.finalize()


def build_cdn_download_url(
    cdn_base_url: str,
    encrypt_query_param: str,
) -> str:
    """
    构建 CDN 下载 URL。
    
    参数:
        cdn_base_url: CDN 基础地址
        encrypt_query_param: 加密的查询参数
        
    返回:
        完整的下载 URL
    """
    base = cdn_base_url.rstrip("/")
    return f"{base}/download?download_encrypted_query_param={encrypt_query_param}"


def decode_aes_key(aes_key_str: str) -> bytes:
    """
    解码 AES 密钥。
    支持十六进制字符串和 Base64 编码。
    
    参数:
        aes_key_str: AES 密钥字符串
        
    返回:
        16 字节 AES 密钥
    """
    aes_key_str = aes_key_str.strip()
    
    if len(aes_key_str) == 32:
        try:
            return bytes.fromhex(aes_key_str)
        except ValueError:
            pass
    
    try:
        decoded = base64.b64decode(aes_key_str)
        if len(decoded) == 16:
            return decoded
    except Exception:
        pass
    
    raise ValueError(f"无法解码 AES 密钥: {aes_key_str[:20]}...")


async def download_from_cdn(
    download_url: str,
    timeout_seconds: int = 60,
) -> bytes:
    """
    从 CDN 下载加密数据。
    
    参数:
        download_url: 下载 URL
        timeout_seconds: 超时时间（秒）
        
    返回:
        加密的文件数据
        
    异常:
        WeixinAdapterError: 下载失败时抛出
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "*/*",
    }
    
    last_error = None
    for attempt in range(1, MAX_DOWNLOAD_RETRIES + 1):
        try:
            async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                response = await client.get(download_url, headers=headers)
            
            if response.status_code >= 400:
                raise WeixinAdapterError(
                    code="WEIXIN_CDN_DOWNLOAD_FAILED",
                    message=f"CDN 下载失败: HTTP {response.status_code}",
                    details={"status_code": response.status_code, "url": download_url},
                    suggestions=["检查网络连接或稍后重试"]
                )
            
            return response.content
            
        except WeixinAdapterError:
            raise
        except httpx.TimeoutException:
            last_error = WeixinAdapterError(
                code="WEIXIN_CDN_DOWNLOAD_TIMEOUT",
                message="CDN 下载超时",
                details={"url": download_url},
                suggestions=["检查网络连接或增加超时时间"]
            )
        except Exception as exc:
            last_error = WeixinAdapterError(
                code="WEIXIN_CDN_DOWNLOAD_ERROR",
                message=f"CDN 下载异常: {exc}",
                details={"exception": type(exc).__name__},
                suggestions=["检查网络和配置"]
            )
        
        logger.warning(f"CDN 下载失败 (尝试 {attempt}/{MAX_DOWNLOAD_RETRIES}): {last_error.message}")
        
        if attempt < MAX_DOWNLOAD_RETRIES:
            await _async_sleep(RETRY_DELAY_SECONDS * attempt)
    
    raise last_error


async def download_and_decrypt(
    encrypt_query_param: str,
    aes_key: str,
    cdn_base_url: Optional[str] = None,
    timeout_seconds: int = 60,
) -> bytes:
    """
    下载并解密 CDN 文件。
    
    参数:
        encrypt_query_param: 加密的查询参数
        aes_key: AES 密钥（十六进制或 Base64）
        cdn_base_url: CDN 基础地址（可选）
        timeout_seconds: 超时时间（秒）
        
    返回:
        解密后的文件数据
        
    异常:
        WeixinAdapterError: 下载或解密失败时抛出
    """
    cdn_url = cdn_base_url or DEFAULT_CDN_BASE_URL
    download_url = build_cdn_download_url(cdn_url, encrypt_query_param)
    
    ciphertext = await download_from_cdn(download_url, timeout_seconds)
    
    try:
        key = decode_aes_key(aes_key)
        plaintext = aes_ecb_decrypt(ciphertext, key)
        return plaintext
    except Exception as exc:
        raise WeixinAdapterError(
            code="WEIXIN_CDN_DECRYPT_ERROR",
            message=f"CDN 文件解密失败: {exc}",
            details={"exception": type(exc).__name__},
            suggestions=["检查 AES 密钥是否正确"]
        )


class CdnCacheManager:
    """
    CDN 下载缓存管理器。
    支持基于文件哈希的本地缓存，避免重复下载。
    """
    
    def __init__(self, cache_dir: Optional[str] = None):
        """
        初始化缓存管理器。
        
        参数:
            cache_dir: 缓存目录路径（可选）
        """
        self.cache_dir = Path(cache_dir or DEFAULT_CACHE_DIR)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.index_file = self.cache_dir / "cache_index.json"
        self._index: Dict[str, Dict[str, Any]] = {}
        self._load_index()
    
    def _load_index(self) -> None:
        """
        加载缓存索引。
        """
        if self.index_file.exists():
            try:
                with open(self.index_file, "r", encoding="utf-8") as f:
                    self._index = json.load(f)
            except Exception as exc:
                logger.warning(f"加载缓存索引失败: {exc}")
                self._index = {}
    
    def _save_index(self) -> None:
        """
        保存缓存索引。
        """
        try:
            with open(self.index_file, "w", encoding="utf-8") as f:
                json.dump(self._index, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            logger.warning(f"保存缓存索引失败: {exc}")
    
    def _compute_cache_key(self, encrypt_query_param: str, aes_key: str) -> str:
        """
        计算缓存键。
        
        参数:
            encrypt_query_param: 加密查询参数
            aes_key: AES 密钥
            
        返回:
            缓存键（MD5 哈希）
        """
        combined = f"{encrypt_query_param}:{aes_key}"
        return hashlib.md5(combined.encode()).hexdigest()
    
    def get(
        self,
        encrypt_query_param: str,
        aes_key: str,
    ) -> Optional[bytes]:
        """
        从缓存获取文件。
        
        参数:
            encrypt_query_param: 加密查询参数
            aes_key: AES 密钥
            
        返回:
            缓存的文件数据，未命中返回 None
        """
        cache_key = self._compute_cache_key(encrypt_query_param, aes_key)
        
        if cache_key not in self._index:
            return None
        
        entry = self._index[cache_key]
        
        if time.time() - entry.get("created_at", 0) > CACHE_EXPIRE_SECONDS:
            self._remove_cache_entry(cache_key)
            return None
        
        file_path = self.cache_dir / entry["filename"]
        if not file_path.exists():
            self._remove_cache_entry(cache_key)
            return None
        
        try:
            with open(file_path, "rb") as f:
                return f.read()
        except Exception as exc:
            logger.warning(f"读取缓存文件失败: {exc}")
            self._remove_cache_entry(cache_key)
            return None
    
    def put(
        self,
        encrypt_query_param: str,
        aes_key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> str:
        """
        将文件存入缓存。
        
        参数:
            encrypt_query_param: 加密查询参数
            aes_key: AES 密钥
            data: 文件数据
            content_type: 内容类型
            
        返回:
            缓存文件路径
        """
        cache_key = self._compute_cache_key(encrypt_query_param, aes_key)
        
        ext = self._get_extension_from_content_type(content_type)
        filename = f"{cache_key}{ext}"
        file_path = self.cache_dir / filename
        
        try:
            with open(file_path, "wb") as f:
                f.write(data)
            
            self._index[cache_key] = {
                "filename": filename,
                "raw_size": len(data),
                "content_type": content_type,
                "created_at": time.time(),
                "aeskey": aes_key[:8] + "...",
            }
            self._save_index()
            
            return str(file_path)
        except Exception as exc:
            logger.warning(f"写入缓存文件失败: {exc}")
            return ""
    
    def _remove_cache_entry(self, cache_key: str) -> None:
        """
        移除缓存条目。
        
        参数:
            cache_key: 缓存键
        """
        if cache_key in self._index:
            entry = self._index[cache_key]
            file_path = self.cache_dir / entry.get("filename", "")
            if file_path.exists():
                try:
                    file_path.unlink()
                except Exception:
                    pass
            del self._index[cache_key]
            self._save_index()
    
    def clear_expired(self) -> int:
        """
        清理过期缓存。
        
        返回:
            清理的文件数量
        """
        current_time = time.time()
        expired_keys = [
            key for key, entry in self._index.items()
            if current_time - entry.get("created_at", 0) > CACHE_EXPIRE_SECONDS
        ]
        
        for key in expired_keys:
            self._remove_cache_entry(key)
        
        return len(expired_keys)
    
    def clear_all(self) -> None:
        """
        清空所有缓存。
        """
        for key in list(self._index.keys()):
            self._remove_cache_entry(key)
    
    @staticmethod
    def _get_extension_from_content_type(content_type: str) -> str:
        """
        根据内容类型获取文件扩展名。
        
        参数:
            content_type: 内容类型
            
        返回:
            文件扩展名
        """
        mime_to_ext = {
            "image/jpeg": ".jpg",
            "image/png": ".png",
            "image/gif": ".gif",
            "image/webp": ".webp",
            "video/mp4": ".mp4",
            "audio/mpeg": ".mp3",
            "audio/wav": ".wav",
            "audio/silk": ".silk",
            "application/pdf": ".pdf",
            "application/zip": ".zip",
        }
        
        content_type_lower = content_type.lower().split(";")[0].strip()
        return mime_to_ext.get(content_type_lower, ".bin")


async def download_with_cache(
    encrypt_query_param: str,
    aes_key: str,
    cdn_base_url: Optional[str] = None,
    cache_manager: Optional[CdnCacheManager] = None,
    timeout_seconds: int = 60,
    use_cache: bool = True,
) -> DownloadResult:
    """
    带缓存的下载并解密。
    
    参数:
        encrypt_query_param: 加密查询参数
        aes_key: AES 密钥
        cdn_base_url: CDN 基础地址（可选）
        cache_manager: 缓存管理器（可选）
        timeout_seconds: 超时时间（秒）
        use_cache: 是否使用缓存
        
    返回:
        DownloadResult 下载结果
    """
    start_time = time.time()
    
    if cache_manager is None:
        cache_manager = CdnCacheManager()
    
    if use_cache:
        cached_data = cache_manager.get(encrypt_query_param, aes_key)
        if cached_data is not None:
            return DownloadResult(
                data=cached_data,
                raw_size=len(cached_data),
                content_type="application/octet-stream",
                cache_hit=True,
                download_time_seconds=time.time() - start_time,
            )
    
    data = await download_and_decrypt(
        encrypt_query_param=encrypt_query_param,
        aes_key=aes_key,
        cdn_base_url=cdn_base_url,
        timeout_seconds=timeout_seconds,
    )
    
    if use_cache:
        cache_manager.put(encrypt_query_param, aes_key, data)
    
    return DownloadResult(
        data=data,
        raw_size=len(data),
        content_type="application/octet-stream",
        cache_hit=False,
        download_time_seconds=time.time() - start_time,
    )


async def download_image(
    image_item: Dict[str, Any],
    cdn_base_url: Optional[str] = None,
    cache_manager: Optional[CdnCacheManager] = None,
) -> DownloadResult:
    """
    下载图片消息中的图片。
    
    参数:
        image_item: 图片消息项
        cdn_base_url: CDN 基础地址（可选）
        cache_manager: 缓存管理器（可选）
        
    返回:
        DownloadResult 下载结果
    """
    encrypt_param = image_item.get("download_encrypted_query_param", "")
    aes_key = image_item.get("aeskey", "")
    
    if not encrypt_param or not aes_key:
        raise WeixinAdapterError(
            code="WEIXIN_CDN_MISSING_PARAM",
            message="图片消息缺少下载参数",
            details={"image_item": image_item},
            suggestions=["检查消息格式是否正确"]
        )
    
    return await download_with_cache(
        encrypt_query_param=encrypt_param,
        aes_key=aes_key,
        cdn_base_url=cdn_base_url,
        cache_manager=cache_manager,
    )


async def download_video(
    video_item: Dict[str, Any],
    cdn_base_url: Optional[str] = None,
    cache_manager: Optional[CdnCacheManager] = None,
    include_thumb: bool = False,
) -> Dict[str, Any]:
    """
    下载视频消息中的视频。
    
    参数:
        video_item: 视频消息项
        cdn_base_url: CDN 基础地址（可选）
        cache_manager: 缓存管理器（可选）
        include_thumb: 是否下载缩略图
        
    返回:
        包含视频和可选缩略图的字典
    """
    encrypt_param = video_item.get("download_encrypted_query_param", "")
    aes_key = video_item.get("aeskey", "")
    
    if not encrypt_param or not aes_key:
        raise WeixinAdapterError(
            code="WEIXIN_CDN_MISSING_PARAM",
            message="视频消息缺少下载参数",
            details={"video_item": video_item},
            suggestions=["检查消息格式是否正确"]
        )
    
    result = {
        "video": await download_with_cache(
            encrypt_query_param=encrypt_param,
            aes_key=aes_key,
            cdn_base_url=cdn_base_url,
            cache_manager=cache_manager,
        )
    }
    
    if include_thumb:
        thumb_param = video_item.get("thumb_download_encrypted_query_param", "")
        if thumb_param:
            try:
                result["thumb"] = await download_with_cache(
                    encrypt_query_param=thumb_param,
                    aes_key=aes_key,
                    cdn_base_url=cdn_base_url,
                    cache_manager=cache_manager,
                )
            except Exception as exc:
                logger.warning(f"下载视频缩略图失败: {exc}")
    
    return result


async def download_file(
    file_item: Dict[str, Any],
    cdn_base_url: Optional[str] = None,
    cache_manager: Optional[CdnCacheManager] = None,
) -> DownloadResult:
    """
    下载文件消息中的文件。
    
    参数:
        file_item: 文件消息项
        cdn_base_url: CDN 基础地址（可选）
        cache_manager: 缓存管理器（可选）
        
    返回:
        DownloadResult 下载结果
    """
    encrypt_param = file_item.get("download_encrypted_query_param", "")
    aes_key = file_item.get("aeskey", "")
    
    if not encrypt_param or not aes_key:
        raise WeixinAdapterError(
            code="WEIXIN_CDN_MISSING_PARAM",
            message="文件消息缺少下载参数",
            details={"file_item": file_item},
            suggestions=["检查消息格式是否正确"]
        )
    
    return await download_with_cache(
        encrypt_query_param=encrypt_param,
        aes_key=aes_key,
        cdn_base_url=cdn_base_url,
        cache_manager=cache_manager,
    )


async def download_voice(
    voice_item: Dict[str, Any],
    cdn_base_url: Optional[str] = None,
    cache_manager: Optional[CdnCacheManager] = None,
) -> DownloadResult:
    """
    下载语音消息中的语音文件。
    
    参数:
        voice_item: 语音消息项
        cdn_base_url: CDN 基础地址（可选）
        cache_manager: 缓存管理器（可选）
        
    返回:
        DownloadResult 下载结果
    """
    encrypt_param = voice_item.get("download_encrypted_query_param", "")
    aes_key = voice_item.get("aeskey", "")
    
    if not encrypt_param or not aes_key:
        raise WeixinAdapterError(
            code="WEIXIN_CDN_MISSING_PARAM",
            message="语音消息缺少下载参数",
            details={"voice_item": voice_item},
            suggestions=["检查消息格式是否正确"]
        )
    
    return await download_with_cache(
        encrypt_query_param=encrypt_param,
        aes_key=aes_key,
        cdn_base_url=cdn_base_url,
        cache_manager=cache_manager,
    )


async def _async_sleep(seconds: float) -> None:
    """
    异步睡眠。
    
    参数:
        seconds: 睡眠秒数
    """
    import asyncio
    await asyncio.sleep(seconds)
