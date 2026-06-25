"""
豆包 TTS API 路由模块。
提供语音合成、声音复刻、音色管理等 REST API。
"""
import base64
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse, Response
from pydantic import BaseModel
from loguru import logger

from api.dependencies import get_current_user
from skills.external.doubao_tts.core.models import (
    TTSRequest as TTSRequestModel,
    TTSResponse,
    VoiceCloneStatus,
    SpeakerInfo,
    TTSHealthResponse,
)
from skills.external.doubao_tts.core.tts_client import DoubaoTTSService
from skills.external.doubao_tts.core.voice_clone import VoiceCloneManager
from db.models import User

router = APIRouter(prefix="/api/tts", tags=["TTS"])

# 全局服务实例（无状态，线程安全）
_tts_service: Optional[DoubaoTTSService] = None
_clone_manager: Optional[VoiceCloneManager] = None


def _get_tts_service() -> DoubaoTTSService:
    """获取 TTS 服务实例（惰性初始化）。"""
    global _tts_service
    if _tts_service is None:
        _tts_service = DoubaoTTSService()
    return _tts_service


def _get_clone_manager() -> VoiceCloneManager:
    """获取声音复刻管理器实例（惰性初始化）。"""
    global _clone_manager
    if _clone_manager is None:
        _clone_manager = VoiceCloneManager()
    return _clone_manager


# ---- Request Schemas ----

class SynthesizeRequest(BaseModel):
    """非流式合成请求体。"""
    text: str
    speaker_id: str = "zh_female_qingxin"
    audio_format: str = "mp3"
    sample_rate: int = 24000
    speed_ratio: float = 1.0
    volume_ratio: float = 1.0
    pitch_ratio: float = 0.0
    emotion: Optional[str] = None
    emotion_scale: float = 1.0
    context_texts: Optional[str] = None
    language: str = "zh"
    ssml: Optional[str] = None


class StreamSynthesizeRequest(BaseModel):
    """流式合成请求体。"""
    text: str
    speaker_id: str = "zh_female_qingxin"
    audio_format: str = "mp3"
    sample_rate: int = 24000
    speed_ratio: float = 1.0
    volume_ratio: float = 1.0
    pitch_ratio: float = 0.0
    emotion: Optional[str] = None
    emotion_scale: float = 1.0
    context_texts: Optional[str] = None
    language: str = "zh"


# ---- TTS 合成端点 ----

@router.post("/synthesize")
async def synthesize_tts(
    body: SynthesizeRequest,
    current_user=Depends(get_current_user),
):
    """
    非流式语音合成，返回完整音频文件。
    """
    service = _get_tts_service()
    if not service.is_configured:
        raise HTTPException(
            status_code=503,
            detail="豆包 TTS 服务未配置，请设置 DOUBAO_APP_ID 和 DOUBAO_ACCESS_KEY 环境变量",
        )

    request = TTSRequestModel(
        text=body.text,
        speaker_id=body.speaker_id,
        audio_format=body.audio_format,
        sample_rate=body.sample_rate,
        speed_ratio=body.speed_ratio,
        volume_ratio=body.volume_ratio,
        pitch_ratio=body.pitch_ratio,
        emotion=body.emotion,
        emotion_scale=body.emotion_scale,
        context_texts=body.context_texts,
        language=body.language,
        ssml=body.ssml,
    )

    try:
        audio_bytes = await service.synthesize(request)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.bind(event="tts_synthesize_error", error=str(e)).error("TTS 合成失败")
        raise HTTPException(status_code=500, detail=f"TTS 合成失败: {str(e)}")

    # 根据音频格式确定 MIME 类型
    mime_map = {
        "mp3": "audio/mpeg",
        "wav": "audio/wav",
        "pcm": "audio/pcm",
        "ogg_opus": "audio/ogg",
    }
    media_type = mime_map.get(body.audio_format, "audio/mpeg")

    return Response(
        content=audio_bytes,
        media_type=media_type,
        headers={
            "Content-Disposition": f"attachment; filename=tts_output.{body.audio_format}",
            "X-Audio-Format": body.audio_format,
            "X-Speaker-Id": body.speaker_id,
        },
    )


@router.post("/synthesize/stream")
async def synthesize_tts_stream(
    body: StreamSynthesizeRequest,
    current_user=Depends(get_current_user),
):
    """
    流式语音合成（SSE），实时推送 base64 编码的音频块。
    前端可通过 EventSource 或 fetch + ReadableStream 消费。
    """
    service = _get_tts_service()
    if not service.is_configured:
        raise HTTPException(
            status_code=503,
            detail="豆包 TTS 服务未配置",
        )

    request = TTSRequestModel(
        text=body.text,
        speaker_id=body.speaker_id,
        audio_format=body.audio_format,
        sample_rate=body.sample_rate,
        speed_ratio=body.speed_ratio,
        volume_ratio=body.volume_ratio,
        pitch_ratio=body.pitch_ratio,
        emotion=body.emotion,
        emotion_scale=body.emotion_scale,
        context_texts=body.context_texts,
        language=body.language,
    )

    async def audio_generator():
        """SSE 音频流生成器。"""
        try:
            async for chunk in service.synthesize_stream(request):
                encoded = base64.b64encode(chunk).decode("ascii")
                yield f"data: {encoded}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            logger.bind(event="tts_stream_error", error=str(e)).error("TTS 流式合成失败")
            yield "data: [ERROR] 流式合成服务暂不可用，请稍后重试\n\n"

    return StreamingResponse(
        audio_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ---- 声音复刻端点 ----

# 声音复刻音频上传安全限制
TTS_CLONE_MAX_SIZE_BYTES = 50 * 1024 * 1024  # 50MB
TTS_CLONE_ALLOWED_MIME_TYPES = {"audio/wav", "audio/wave", "audio/x-wav", "audio/vnd.wave"}


@router.post("/clone")
async def clone_voice(
    voice_name: str = Form(..., description="音色名称"),
    audio_file: UploadFile = File(..., description="音频文件（WAV，14~30秒）"),
    context_texts: Optional[str] = Form(default=None, description="音频对应文本"),
    current_user: User = Depends(get_current_user),
):
    """
    上传音频样本，创建声音复刻训练任务。
    返回 speaker_id，可通过 GET /clone/{speaker_id} 查询训练进度。
    """
    manager = _get_clone_manager()
    if not manager.is_configured:
        raise HTTPException(
            status_code=503,
            detail="豆包声音复刻服务未配置",
        )

    # 校验文件名扩展
    if not audio_file.filename or not audio_file.filename.lower().endswith(".wav"):
        raise HTTPException(status_code=400, detail="仅支持 WAV 格式音频文件")

    # 校验 MIME 类型白名单
    content_type = (audio_file.content_type or "").lower()
    if content_type and content_type not in TTS_CLONE_ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的音频 MIME 类型: {content_type}，仅支持 WAV",
        )

    try:
        audio_bytes = await audio_file.read()
        # 校验文件大小上限（防止 DoS）
        if len(audio_bytes) > TTS_CLONE_MAX_SIZE_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"音频文件过大（{len(audio_bytes)} 字节），最大允许 {TTS_CLONE_MAX_SIZE_BYTES} 字节",
            )
        if len(audio_bytes) < 1024:  # 至少 1KB
            raise HTTPException(status_code=400, detail="音频文件过小，需要至少 14 秒的 WAV 文件")

        speaker_id = await manager.create_speaker(
            audio_bytes=audio_bytes,
            voice_name=voice_name,
            context_texts=context_texts,
            user_id=str(current_user.id),
        )

        return {
            "success": True,
            "speaker_id": speaker_id,
            "voice_name": voice_name,
            "message": f"声音复刻训练已提交，speaker_id: {speaker_id}。请使用 GET /api/tts/clone/{speaker_id} 查询进度。",
        }
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.bind(event="clone_voice_error", error=str(e)).error("声音复刻失败")
        raise HTTPException(status_code=500, detail=f"声音复刻失败: {str(e)}")


@router.get("/clone/{speaker_id}")
async def get_clone_status(
    speaker_id: str,
    current_user: User = Depends(get_current_user),
):
    """
    查询声音复刻训练状态。
    """
    manager = _get_clone_manager()
    try:
        status_info = await manager.get_status(
            speaker_id,
            user_id=str(current_user.id),
        )
        return {"success": True, **status_info}
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="查询失败")


@router.delete("/clone/{speaker_id}")
async def delete_cloned_speaker(
    speaker_id: str,
    current_user: User = Depends(get_current_user),
):
    """
    删除复刻音色。
    """
    manager = _get_clone_manager()
    try:
        await manager.delete_speaker(
            speaker_id,
            user_id=str(current_user.id),
        )
        return {"success": True, "message": f"音色 {speaker_id} 已删除"}
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="删除失败")


# ---- 音色库端点 ----

@router.get("/speakers")
async def list_speakers(
    current_user: User = Depends(get_current_user),
):
    """
    列出所有可用音色（预置 + 复刻）。
    """
    manager = _get_clone_manager()
    try:
        speakers = await manager.list_speakers(
            user_id=str(current_user.id),
        )
        return {
            "success": True,
            "speakers": speakers,
            "total": len(speakers),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail="获取音色列表失败")


@router.get("/speakers/{speaker_id}")
async def get_speaker_info(
    speaker_id: str,
    current_user: User = Depends(get_current_user),
):
    """
    获取音色详细信息。
    """
    manager = _get_clone_manager()
    speakers = await manager.list_speakers(
        user_id=str(current_user.id),
    )
    for spk in speakers:
        if spk["speaker_id"] == speaker_id:
            return {"success": True, "speaker": spk}
    raise HTTPException(status_code=404, detail=f"音色 {speaker_id} 不存在")


# ---- 健康检查端点 ----

@router.get("/health")
async def tts_health():
    """
    豆包 TTS 服务连通性检查。
    """
    service = _get_tts_service()
    configured = service.is_configured
    return {
        "status": "healthy" if configured else "not_configured",
        "service": "doubao-tts",
        "configured": configured,
        "resource_id": service.resource_id,
        "preset_speakers": len(DoubaoTTSService.list_preset_speakers()),
        "message": "豆包 TTS 服务已配置" if configured else "请在环境变量中设置 DOUBAO_APP_ID 和 DOUBAO_ACCESS_KEY",
    }
