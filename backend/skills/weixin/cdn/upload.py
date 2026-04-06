"""
CDN 上传模块
实现微信 CDN 文件上传功能，包括 AES-128-ECB 加密、getUploadUrl 接口调用和文件上传。
"""

from __future__ import annotations

import hashlib
import os
import secrets
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

import httpx
from loguru import logger

from backend.skills.weixin_skill_adapter import WeixinAdapterError, WeixinRuntimeConfig

DEFAULT_CDN_BASE_URL = "https://novac2c.cdn.weixin.qq.com/c2c"
MAX_UPLOAD_RETRIES = 3
RETRY_DELAY_SECONDS = 1


@dataclass
class UploadResult:
    """
    CDN 上传结果数据结构。
    包含上传后的文件信息，用于后续消息发送。
    """
    filekey: str
    aeskey: str
    raw_size: int
    encrypted_size: int
    download_query_param: str
    thumb_download_query_param: Optional[str] = None
    upload_url: Optional[str] = None


@dataclass
class UploadParams:
    """
    getUploadUrl 接口返回的上传参数。
    """
    upload_param: str
    thumb_upload_param: Optional[str] = None
    upload_full_url: Optional[str] = None


def aes_ecb_encrypt(plaintext: bytes, key: bytes) -> bytes:
    """
    使用 AES-128-ECB 模式加密数据。
    
    参数:
        plaintext: 原始数据
        key: 16 字节 AES 密钥
        
    返回:
        加密后的数据（包含 PKCS7 填充）
    """
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives import padding
    from cryptography.hazmat.backends import default_backend
    
    padder = padding.PKCS7(128).padder()
    padded_data = padder.update(plaintext) + padder.finalize()
    
    cipher = Cipher(algorithms.AES(key), modes.ECB(), backend=default_backend())
    encryptor = cipher.encryptor()
    
    return encryptor.update(padded_data) + encryptor.finalize()


def aes_ecb_padded_size(size: int) -> int:
    """
    计算 AES-ECB 加密后的数据大小。
    
    参数:
        size: 原始数据大小
        
    返回:
        加密后的大小（16 字节对齐）
    """
    block_size = 16
    return ((size + block_size - 1) // block_size) * block_size


def compute_md5_hex(data: bytes) -> str:
    """
    计算数据的 MD5 哈希值（十六进制字符串）。
    
    参数:
        data: 原始数据
        
    返回:
        MD5 哈希值（32 位小写十六进制字符串）
    """
    return hashlib.md5(data).hexdigest().lower()


def generate_random_aes_key() -> bytes:
    """
    生成随机的 16 字节 AES 密钥。
    
    返回:
        16 字节随机密钥
    """
    return secrets.token_bytes(16)


def generate_random_filekey() -> str:
    """
    生成随机的文件标识符（32 位十六进制字符串）。
    
    返回:
        32 位十六进制字符串
    """
    return secrets.token_hex(16)


async def get_upload_url(
    config: WeixinRuntimeConfig,
    filekey: str,
    media_type: int,
    to_user_id: str,
    raw_size: int,
    raw_md5: str,
    encrypted_size: int,
    aeskey: str,
    thumb_raw_size: Optional[int] = None,
    thumb_md5: Optional[str] = None,
    thumb_encrypted_size: Optional[int] = None,
) -> UploadParams:
    """
    调用 getUploadUrl 接口获取 CDN 上传预签名参数。
    
    参数:
        config: 微信运行时配置
        filekey: 文件标识符（32 位十六进制）
        media_type: 媒体类型（1=图片, 2=视频, 3=文件）
        to_user_id: 接收者用户 ID
        raw_size: 原始文件大小
        raw_md5: 原始文件 MD5
        encrypted_size: 加密后文件大小
        aeskey: AES 密钥（十六进制字符串）
        thumb_raw_size: 缩略图原始大小（可选）
        thumb_md5: 缩略图 MD5（可选）
        thumb_encrypted_size: 缩略图加密后大小（可选）
        
    返回:
        UploadParams 上传参数对象
        
    异常:
        WeixinAdapterError: 接口调用失败时抛出
    """
    request_body = {
        "filekey": filekey,
        "media_type": media_type,
        "to_user_id": to_user_id,
        "rawsize": raw_size,
        "rawfilemd5": raw_md5,
        "filesize": encrypted_size,
        "aeskey": aeskey,
    }
    
    if thumb_raw_size is not None and thumb_md5 is not None and thumb_encrypted_size is not None:
        request_body["thumb_rawsize"] = thumb_raw_size
        request_body["thumb_rawfilemd5"] = thumb_md5
        request_body["thumb_filesize"] = thumb_encrypted_size
    
    url = f"{config.base_url}/ilink/bot/getuploadurl"
    headers = {
        "Content-Type": "application/json",
        "AuthorizationType": "ilink_bot_token",
        "Authorization": f"Bearer {config.token}",
        "X-WECHAT-UIN": _build_random_wechat_uin(),
        "iLink-App-ClientVersion": "1",
    }
    
    try:
        async with httpx.AsyncClient(timeout=config.timeout_seconds) as client:
            response = await client.post(url, json=request_body, headers=headers)
        
        if response.status_code >= 400:
            raise WeixinAdapterError(
                code="WEIXIN_CDN_GET_UPLOAD_URL_FAILED",
                message=f"获取上传地址失败: HTTP {response.status_code}",
                details={"status_code": response.status_code, "response": response.text[:500]},
                suggestions=["检查 token 是否有效、网络是否正常"]
            )
        
        data = response.json()
        
        errcode = data.get("errcode") or data.get("ret")
        if errcode and errcode != 0:
            raise WeixinAdapterError(
                code="WEIXIN_CDN_GET_UPLOAD_URL_ERROR",
                message=f"获取上传地址返回错误: {data.get('errmsg', '未知错误')}",
                details={"errcode": errcode, "response": data},
                suggestions=["检查文件参数是否正确"]
            )
        
        return UploadParams(
            upload_param=data.get("upload_param", ""),
            thumb_upload_param=data.get("thumb_upload_param"),
            upload_full_url=data.get("upload_full_url"),
        )
        
    except WeixinAdapterError:
        raise
    except httpx.TimeoutException:
        raise WeixinAdapterError(
            code="WEIXIN_CDN_TIMEOUT",
            message="获取上传地址超时",
            details={"url": url},
            suggestions=["检查网络连接或增加超时时间"]
        )
    except Exception as exc:
        raise WeixinAdapterError(
            code="WEIXIN_CDN_ERROR",
            message=f"获取上传地址异常: {exc}",
            details={"exception": type(exc).__name__},
            suggestions=["检查网络和配置"]
        )


async def upload_buffer_to_cdn(
    buffer: bytes,
    upload_url: str,
    upload_param: str,
    timeout_seconds: int = 60,
) -> Dict[str, Any]:
    """
    将加密后的数据上传到 CDN。
    
    参数:
        buffer: 加密后的数据
        upload_url: 上传地址
        upload_param: 上传参数
        timeout_seconds: 超时时间（秒）
        
    返回:
        上传响应数据
        
    异常:
        WeixinAdapterError: 上传失败时抛出
    """
    headers = {
        "Content-Type": "application/octet-stream",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }
    
    params = {"upload_param": upload_param} if upload_param else {}
    
    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            response = await client.post(
                upload_url,
                content=buffer,
                headers=headers,
                params=params,
            )
        
        if response.status_code >= 400:
            raise WeixinAdapterError(
                code="WEIXIN_CDN_UPLOAD_FAILED",
                message=f"CDN 上传失败: HTTP {response.status_code}",
                details={"status_code": response.status_code, "response": response.text[:500]},
                suggestions=["检查网络连接或稍后重试"]
            )
        
        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type.lower():
            return response.json()
        
        return {"raw_text": response.text, "status_code": response.status_code}
        
    except WeixinAdapterError:
        raise
    except httpx.TimeoutException:
        raise WeixinAdapterError(
            code="WEIXIN_CDN_UPLOAD_TIMEOUT",
            message="CDN 上传超时",
            details={"upload_url": upload_url},
            suggestions=["检查网络连接或增加超时时间"]
        )
    except Exception as exc:
        raise WeixinAdapterError(
            code="WEIXIN_CDN_UPLOAD_ERROR",
            message=f"CDN 上传异常: {exc}",
            details={"exception": type(exc).__name__},
            suggestions=["检查网络和配置"]
        )


async def upload_media_to_cdn(
    config: WeixinRuntimeConfig,
    file_path: str,
    to_user_id: str,
    media_type: int,
    cdn_base_url: Optional[str] = None,
    thumb_file_path: Optional[str] = None,
) -> UploadResult:
    """
    完整的媒体文件上传流程。
    
    流程:
    1. 读取文件并计算 MD5
    2. 生成随机 AES 密钥和 filekey
    3. 调用 getUploadUrl 获取上传参数
    4. AES 加密文件
    5. 上传到 CDN（支持重试）
    
    参数:
        config: 微信运行时配置
        file_path: 本地文件路径
        to_user_id: 接收者用户 ID
        media_type: 媒体类型（1=图片, 2=视频, 3=文件）
        cdn_base_url: CDN 基础地址（可选）
        thumb_file_path: 缩略图文件路径（可选，用于视频）
        
    返回:
        UploadResult 上传结果
        
    异常:
        WeixinAdapterError: 上传失败时抛出
        FileNotFoundError: 文件不存在时抛出
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"文件不存在: {file_path}")
    
    plaintext = _read_file(file_path)
    raw_md5 = compute_md5_hex(plaintext)
    raw_size = len(plaintext)
    
    aeskey = generate_random_aes_key()
    filekey = generate_random_filekey()
    
    encrypted_size = aes_ecb_padded_size(raw_size)
    
    thumb_raw_size = None
    thumb_md5 = None
    thumb_encrypted_size = None
    thumb_aeskey = None
    thumb_encrypted = None
    
    if thumb_file_path and os.path.exists(thumb_file_path):
        thumb_plaintext = _read_file(thumb_file_path)
        thumb_md5 = compute_md5_hex(thumb_plaintext)
        thumb_raw_size = len(thumb_plaintext)
        thumb_aeskey = generate_random_aes_key()
        thumb_encrypted = aes_ecb_encrypt(thumb_plaintext, thumb_aeskey)
        thumb_encrypted_size = len(thumb_encrypted)
    
    upload_params = await get_upload_url(
        config=config,
        filekey=filekey,
        media_type=media_type,
        to_user_id=to_user_id,
        raw_size=raw_size,
        raw_md5=raw_md5,
        encrypted_size=encrypted_size,
        aeskey=aeskey.hex(),
        thumb_raw_size=thumb_raw_size,
        thumb_md5=thumb_md5,
        thumb_encrypted_size=thumb_encrypted_size,
    )
    
    ciphertext = aes_ecb_encrypt(plaintext, aeskey)
    
    cdn_url = cdn_base_url or DEFAULT_CDN_BASE_URL
    upload_url = upload_params.upload_full_url or f"{cdn_url}/upload"
    
    last_error = None
    for attempt in range(1, MAX_UPLOAD_RETRIES + 1):
        try:
            await upload_buffer_to_cdn(
                buffer=ciphertext,
                upload_url=upload_url,
                upload_param=upload_params.upload_param,
                timeout_seconds=60,
            )
            
            if thumb_encrypted and upload_params.thumb_upload_param:
                thumb_upload_url = f"{cdn_url}/upload"
                await upload_buffer_to_cdn(
                    buffer=thumb_encrypted,
                    upload_url=thumb_upload_url,
                    upload_param=upload_params.thumb_upload_param,
                    timeout_seconds=30,
                )
            
            logger.info(f"CDN 上传成功: filekey={filekey}, size={raw_size}, attempts={attempt}")
            
            return UploadResult(
                filekey=filekey,
                aeskey=aeskey.hex(),
                raw_size=raw_size,
                encrypted_size=len(ciphertext),
                download_query_param=upload_params.upload_param,
                thumb_download_query_param=upload_params.thumb_upload_param,
                upload_url=upload_url,
            )
            
        except WeixinAdapterError as exc:
            last_error = exc
            logger.warning(f"CDN 上传失败 (尝试 {attempt}/{MAX_UPLOAD_RETRIES}): {exc.message}")
            
            if attempt < MAX_UPLOAD_RETRIES:
                await _async_sleep(RETRY_DELAY_SECONDS * attempt)
    
    raise WeixinAdapterError(
        code="WEIXIN_CDN_UPLOAD_MAX_RETRIES",
        message=f"CDN 上传失败，已重试 {MAX_UPLOAD_RETRIES} 次",
        details={"last_error": str(last_error) if last_error else None},
        suggestions=["检查网络连接、CDN 服务状态后重试"]
    )


async def upload_bytes_to_cdn(
    config: WeixinRuntimeConfig,
    data: bytes,
    to_user_id: str,
    media_type: int,
    cdn_base_url: Optional[str] = None,
) -> UploadResult:
    """
    上传字节数据到 CDN。
    
    参数:
        config: 微信运行时配置
        data: 文件数据
        to_user_id: 接收者用户 ID
        media_type: 媒体类型
        cdn_base_url: CDN 基础地址（可选）
        
    返回:
        UploadResult 上传结果
    """
    raw_md5 = compute_md5_hex(data)
    raw_size = len(data)
    
    aeskey = generate_random_aes_key()
    filekey = generate_random_filekey()
    
    encrypted_size = aes_ecb_padded_size(raw_size)
    
    upload_params = await get_upload_url(
        config=config,
        filekey=filekey,
        media_type=media_type,
        to_user_id=to_user_id,
        raw_size=raw_size,
        raw_md5=raw_md5,
        encrypted_size=encrypted_size,
        aeskey=aeskey.hex(),
    )
    
    ciphertext = aes_ecb_encrypt(data, aeskey)
    
    cdn_url = cdn_base_url or DEFAULT_CDN_BASE_URL
    upload_url = upload_params.upload_full_url or f"{cdn_url}/upload"
    
    last_error = None
    for attempt in range(1, MAX_UPLOAD_RETRIES + 1):
        try:
            await upload_buffer_to_cdn(
                buffer=ciphertext,
                upload_url=upload_url,
                upload_param=upload_params.upload_param,
                timeout_seconds=60,
            )
            
            logger.info(f"CDN 字节数据上传成功: filekey={filekey}, size={raw_size}")
            
            return UploadResult(
                filekey=filekey,
                aeskey=aeskey.hex(),
                raw_size=raw_size,
                encrypted_size=len(ciphertext),
                download_query_param=upload_params.upload_param,
                upload_url=upload_url,
            )
            
        except WeixinAdapterError as exc:
            last_error = exc
            logger.warning(f"CDN 上传失败 (尝试 {attempt}/{MAX_UPLOAD_RETRIES}): {exc.message}")
            
            if attempt < MAX_UPLOAD_RETRIES:
                await _async_sleep(RETRY_DELAY_SECONDS * attempt)
    
    raise WeixinAdapterError(
        code="WEIXIN_CDN_UPLOAD_MAX_RETRIES",
        message=f"CDN 上传失败，已重试 {MAX_UPLOAD_RETRIES} 次",
        details={"last_error": str(last_error) if last_error else None},
        suggestions=["检查网络连接、CDN 服务状态后重试"]
    )


def build_image_message_item(upload_result: UploadResult) -> Dict[str, Any]:
    """
    构建图片消息项。
    
    参数:
        upload_result: 上传结果
        
    返回:
        消息项字典
    """
    return {
        "type": 2,
        "image_item": {
            "filekey": upload_result.filekey,
            "aeskey": upload_result.aeskey,
            "rawsize": upload_result.raw_size,
            "filesize": upload_result.encrypted_size,
            "download_encrypted_query_param": upload_result.download_query_param,
        }
    }


def build_video_message_item(upload_result: UploadResult) -> Dict[str, Any]:
    """
    构建视频消息项。
    
    参数:
        upload_result: 上传结果
        
    返回:
        消息项字典
    """
    item = {
        "type": 5,
        "video_item": {
            "filekey": upload_result.filekey,
            "aeskey": upload_result.aeskey,
            "rawsize": upload_result.raw_size,
            "filesize": upload_result.encrypted_size,
            "download_encrypted_query_param": upload_result.download_query_param,
        }
    }
    
    if upload_result.thumb_download_query_param:
        item["video_item"]["thumb_download_encrypted_query_param"] = upload_result.thumb_download_query_param
    
    return item


def build_file_message_item(upload_result: UploadResult, filename: str) -> Dict[str, Any]:
    """
    构建文件消息项。
    
    参数:
        upload_result: 上传结果
        filename: 文件名
        
    返回:
        消息项字典
    """
    return {
        "type": 4,
        "file_item": {
            "filekey": upload_result.filekey,
            "aeskey": upload_result.aeskey,
            "rawsize": upload_result.raw_size,
            "filesize": upload_result.encrypted_size,
            "download_encrypted_query_param": upload_result.download_query_param,
            "filename": filename,
        }
    }


def _read_file(file_path: str) -> bytes:
    """
    读取文件内容。
    
    参数:
        file_path: 文件路径
        
    返回:
        文件内容
    """
    with open(file_path, "rb") as f:
        return f.read()


async def _async_sleep(seconds: float) -> None:
    """
    异步睡眠。
    
    参数:
        seconds: 睡眠秒数
    """
    import asyncio
    await asyncio.sleep(seconds)


def _build_random_wechat_uin() -> str:
    """
    构建随机的 X-WECHAT-UIN 请求头值。
    
    返回:
        Base64 编码的随机值
    """
    import base64
    raw = str(int.from_bytes(os.urandom(4), byteorder="big", signed=False))
    return base64.b64encode(raw.encode("utf-8")).decode("utf-8")
