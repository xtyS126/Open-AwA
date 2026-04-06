"""
媒体处理模块
提供语音转码、语音识别等功能。
"""

from backend.skills.weixin.media.transcode import (
    TranscodeResult,
    VoiceRecognitionResult,
    VoiceRecognizer,
    is_silk_format,
    has_ffmpeg,
    has_silk_decoder,
    silk_to_wav,
    transcode_voice,
    voice_to_text,
    get_mime_type,
    get_file_extension,
)

__all__ = [
    "TranscodeResult",
    "VoiceRecognitionResult",
    "VoiceRecognizer",
    "is_silk_format",
    "has_ffmpeg",
    "has_silk_decoder",
    "silk_to_wav",
    "transcode_voice",
    "voice_to_text",
    "get_mime_type",
    "get_file_extension",
]
