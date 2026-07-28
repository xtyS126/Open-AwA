"""
豆包 TTS 语音合成与声音复刻 Skill 核心模块。
提供 DoubaoTTSService（语音合成）和 VoiceCloneManager（声音复刻）两个核心类。
"""
from .models import (
    TTSRequest,
    TTSResponse,
    VoiceCloneRequest,
    VoiceCloneStatus,
    SpeakerInfo,
)
from .tts_client import DoubaoTTSService
from .voice_clone import VoiceCloneManager

__all__ = [
    "DoubaoTTSService",
    "VoiceCloneManager",
    "TTSRequest",
    "TTSResponse",
    "VoiceCloneRequest",
    "VoiceCloneStatus",
    "SpeakerInfo",
]
