"""
豆包 TTS 数据模型 — Pydantic 请求/响应定义。
"""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class TTSRequest(BaseModel):
    """语音合成请求参数。"""
    text: str = Field(..., min_length=1, max_length=100000, description="合成文本内容")
    speaker_id: str = Field(default="zh_female_qingxin", description="音色 ID（预置或复刻）")
    audio_format: str = Field(default="mp3", description="音频格式：mp3/wav/pcm/ogg_opus")
    sample_rate: int = Field(default=24000, ge=8000, le=48000, description="采样率（Hz）")
    speed_ratio: float = Field(default=1.0, ge=0.5, le=2.0, description="语速倍率")
    volume_ratio: float = Field(default=1.0, ge=0.1, le=3.0, description="音量倍率")
    pitch_ratio: float = Field(default=0.0, ge=-12.0, le=12.0, description="音调偏移（半音）")
    emotion: Optional[str] = Field(default=None, description="情感类型：happy/sad/angry/fearful/surprised/neutral")
    emotion_scale: float = Field(default=1.0, ge=1.0, le=5.0, description="情感强度")
    context_texts: Optional[str] = Field(default=None, max_length=500, description="上下文文本，提升情感演绎准确度")
    language: str = Field(default="zh", description="语言代码：zh/en/ja/es/id/pt/de/fr")
    resource_id: Optional[str] = Field(default=None, description="资源 ID，默认使用 seed-tts-2.0")
    ssml: Optional[str] = Field(default=None, max_length=100000, description="SSML 标记文本（与 text 二选一）")


class TTSResponse(BaseModel):
    """语音合成响应（非流式）。"""
    success: bool = True
    audio_format: str = "mp3"
    audio_size: int = 0
    speaker_id: str = ""
    text: str = ""


class VoiceCloneRequest(BaseModel):
    """声音复刻请求参数。"""
    voice_name: str = Field(..., min_length=1, max_length=50, description="音色名称")
    context_texts: Optional[str] = Field(default=None, max_length=500, description="音频对应的文本内容")
    language: str = Field(default="zh", description="语言代码")


class VoiceCloneStatus(BaseModel):
    """声音复刻训练状态。"""
    speaker_id: str = ""
    voice_name: str = ""
    status: str = Field(default="pending", description="训练状态：pending/training/ready/failed")
    progress: float = Field(default=0.0, ge=0.0, le=100.0, description="训练进度百分比")
    audio_duration: float = Field(default=0.0, description="训练音频时长（秒）")
    created_at: str = ""
    updated_at: str = ""
    error_message: Optional[str] = Field(default=None, description="失败时的错误信息")


class SpeakerInfo(BaseModel):
    """音色信息。"""
    speaker_id: str = Field(..., description="音色唯一标识")
    name: str = Field(..., description="音色名称")
    status: str = Field(default="ready", description="状态：training/ready/failed")
    language: str = Field(default="zh", description="语言")
    is_cloned: bool = Field(default=False, description="是否为复刻音色")
    audio_duration: float = Field(default=0.0, description="复刻音频时长（秒）")
    created_at: Optional[datetime] = Field(default=None, description="创建时间")
    description: str = Field(default="", description="音色描述")


class TTSHealthResponse(BaseModel):
    """健康检查响应。"""
    status: str = "ok"
    service: str = "doubao-tts"
    configured: bool = False
    resource_id: str = "seed-tts-2.0"
    message: str = ""
