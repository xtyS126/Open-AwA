"""
语音转文本（ASR）API 路由模块。
提供音频文件上传与语音识别端点，对接外部 ASR 服务（如 Whisper API）。
当前为占位实现，后续可对接真实 ASR 服务。
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from loguru import logger

from api.dependencies import get_current_user
from db.models import User

router = APIRouter(prefix="/api/voice", tags=["语音"])


# ---- Response Schemas ----

class TranscribeResponse(BaseModel):
    """语音转文本响应体。"""
    text: str
    language: Optional[str] = None
    duration: Optional[float] = None


# ---- Routes ----

@router.post("/transcribe", response_model=TranscribeResponse)
async def transcribe_voice(
    audio_file: UploadFile = File(..., description="音频文件（audio/webm 或 audio/wav 格式）"),
    language: Optional[str] = Form(default=None, description="指定语言代码（如 zh、en），不指定则自动检测"),
    current_user: User = Depends(get_current_user),
) -> TranscribeResponse:
    """
    语音转文本端点。

    接收音频文件，调用 ASR 服务进行语音识别并返回文本。
    当前为占位实现：由于 ASR 服务（Whisper API 等）可能未配置，
    返回占位文本并记录日志，后续可对接真实 ASR 服务。

    支持的音频格式：audio/webm、audio/wav、audio/mp3 等。
    最大文件大小：10MB（由中间件统一限制）。
    """
    # 校验文件类型
    if not audio_file.content_type:
        raise HTTPException(status_code=400, detail="无法识别音频文件类型")

    allowed_types = {"audio/webm", "audio/wav", "audio/mp3", "audio/mpeg", "audio/ogg", "audio/flac"}
    if audio_file.content_type not in allowed_types:
        raise HTTPException(status_code=400, detail=f"不支持的音频格式: {audio_file.content_type}，支持: {', '.join(sorted(allowed_types))}")

    # 读取音频内容（不记录日志，保护用户隐私）
    audio_bytes = await audio_file.read()
    audio_size_kb = len(audio_bytes) / 1024

    logger.bind(
        event="voice_transcribe",
        user_id=current_user.id,
        file_name=audio_file.filename,
        content_type=audio_file.content_type,
        size_kb=round(audio_size_kb, 1),
        language=language,
    ).info("收到语音转文本请求")

    # 文件大小限制：10MB
    max_size = 10 * 1024 * 1024
    if len(audio_bytes) > max_size:
        raise HTTPException(status_code=400, detail=f"音频文件过大，最大支持 10MB，当前大小: {round(audio_size_kb / 1024, 1)}MB")

    # 占位实现：返回提示文本，后续对接真实 ASR 服务
    # 对接方式示例：
    #   1. OpenAI Whisper API: POST https://api.openai.com/v1/audio/transcriptions
    #   2. 本地 Whisper 模型: 使用 faster-whisper 或 whisper.cpp
    #   3. 火山引擎/阿里云 ASR: 使用对应 SDK
    logger.bind(event="voice_transcribe", user_id=current_user.id).warning(
        "ASR 服务未配置，返回占位文本。请对接真实 ASR 服务（Whisper API 等）"
    )

    return TranscribeResponse(
        text="[语音识别服务待配置]",
        language=language,
        duration=None,
    )