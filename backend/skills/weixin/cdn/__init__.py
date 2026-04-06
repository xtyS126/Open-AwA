"""
CDN 模块
提供微信 CDN 文件上传和下载功能。
"""

from skills.weixin.cdn.upload import (
    UploadResult,
    UploadParams,
    aes_ecb_encrypt,
    aes_ecb_padded_size,
    compute_md5_hex,
    generate_random_aes_key,
    generate_random_filekey,
    get_upload_url,
    upload_buffer_to_cdn,
    upload_media_to_cdn,
    upload_bytes_to_cdn,
    build_image_message_item,
    build_video_message_item,
    build_file_message_item,
)

from skills.weixin.cdn.download import (
    DownloadResult,
    CacheEntry,
    CdnCacheManager,
    aes_ecb_decrypt,
    build_cdn_download_url,
    decode_aes_key,
    download_from_cdn,
    download_and_decrypt,
    download_with_cache,
    download_image,
    download_video,
    download_file,
    download_voice,
)

__all__ = [
    "UploadResult",
    "UploadParams",
    "aes_ecb_encrypt",
    "aes_ecb_padded_size",
    "compute_md5_hex",
    "generate_random_aes_key",
    "generate_random_filekey",
    "get_upload_url",
    "upload_buffer_to_cdn",
    "upload_media_to_cdn",
    "upload_bytes_to_cdn",
    "build_image_message_item",
    "build_video_message_item",
    "build_file_message_item",
    "DownloadResult",
    "CacheEntry",
    "CdnCacheManager",
    "aes_ecb_decrypt",
    "build_cdn_download_url",
    "decode_aes_key",
    "download_from_cdn",
    "download_and_decrypt",
    "download_with_cache",
    "download_image",
    "download_video",
    "download_file",
    "download_voice",
]

