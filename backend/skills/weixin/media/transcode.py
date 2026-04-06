"""
语音转码模块
实现 SILK 语音格式解码、语音转文字和转码失败降级处理。
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from skills.weixin.errors import WeixinAdapterError

SILK_MAGIC_HEADER = b"\x02#!SILK_V3"
SILK_SAMPLE_RATE = 24000
DEFAULT_WAV_SAMPLE_RATE = 16000
DEFAULT_WAV_CHANNELS = 1
DEFAULT_WAV_SAMPLE_WIDTH = 2


@dataclass
class TranscodeResult:
    """
    语音转码结果数据结构。
    """
    success: bool
    output_data: Optional[bytes] = None
    output_format: str = "wav"
    sample_rate: int = DEFAULT_WAV_SAMPLE_RATE
    duration_seconds: float = 0.0
    error_message: Optional[str] = None
    fallback_used: bool = False


@dataclass
class VoiceRecognitionResult:
    """
    语音识别结果数据结构。
    """
    success: bool
    text: str = ""
    confidence: float = 0.0
    language: str = "zh"
    error_message: Optional[str] = None


def is_silk_format(data: bytes) -> bool:
    """
    检查数据是否为 SILK 格式。
    
    参数:
        data: 音频数据
        
    返回:
        是否为 SILK 格式
    """
    if len(data) < 10:
        return False
    
    if data.startswith(SILK_MAGIC_HEADER):
        return True
    
    if data[:9] == b"#!SILK_V3":
        return True
    
    return False


def has_ffmpeg() -> bool:
    """
    检查系统是否安装了 ffmpeg。
    
    返回:
        是否安装了 ffmpeg
    """
    return shutil.which("ffmpeg") is not None


def has_silk_decoder() -> bool:
    """
    检查是否有可用的 SILK 解码器。
    
    返回:
        是否有 SILK 解码器
    """
    if has_ffmpeg():
        return True
    
    try:
        import pilk
        return True
    except ImportError:
        pass
    
    return False


async def silk_to_wav_with_ffmpeg(
    silk_data: bytes,
    output_sample_rate: int = DEFAULT_WAV_SAMPLE_RATE,
) -> bytes:
    """
    使用 ffmpeg 将 SILK 转换为 WAV。
    
    参数:
        silk_data: SILK 音频数据
        output_sample_rate: 输出采样率
        
    返回:
        WAV 音频数据
        
    异常:
        WeixinAdapterError: 转码失败时抛出
    """
    if not has_ffmpeg():
        raise WeixinAdapterError(
            code="WEIXIN_FFMPEG_NOT_FOUND",
            message="系统未安装 ffmpeg",
            details={},
            suggestions=["安装 ffmpeg: winget install ffmpeg 或 choco install ffmpeg"]
        )
    
    with tempfile.TemporaryDirectory() as temp_dir:
        silk_path = os.path.join(temp_dir, "input.silk")
        wav_path = os.path.join(temp_dir, "output.wav")
        
        with open(silk_path, "wb") as f:
            f.write(silk_data)
        
        cmd = [
            "ffmpeg",
            "-y",
            "-i", silk_path,
            "-ar", str(output_sample_rate),
            "-ac", "1",
            "-f", "wav",
            wav_path,
        ]
        
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode != 0:
                error_msg = stderr.decode("utf-8", errors="ignore")
                raise WeixinAdapterError(
                    code="WEIXIN_FFMPEG_TRANSCODE_FAILED",
                    message=f"ffmpeg 转码失败: {error_msg[:200]}",
                    details={"returncode": process.returncode},
                    suggestions=["检查 SILK 文件是否有效"]
                )
            
            with open(wav_path, "rb") as f:
                return f.read()
                
        except FileNotFoundError:
            raise WeixinAdapterError(
                code="WEIXIN_FFMPEG_NOT_FOUND",
                message="ffmpeg 命令未找到",
                details={},
                suggestions=["安装 ffmpeg: winget install ffmpeg 或 choco install ffmpeg"]
            )


async def silk_to_wav_with_pilk(
    silk_data: bytes,
    output_sample_rate: int = DEFAULT_WAV_SAMPLE_RATE,
) -> bytes:
    """
    使用 pilk 库将 SILK 转换为 WAV。
    
    参数:
        silk_data: SILK 音频数据
        output_sample_rate: 输出采样率
        
    返回:
        WAV 音频数据
        
    异常:
        WeixinAdapterError: 转码失败时抛出
    """
    try:
        import pilk
    except ImportError:
        raise WeixinAdapterError(
            code="WEIXIN_PILK_NOT_FOUND",
            message="pilk 库未安装",
            details={},
            suggestions=["安装 pilk: pip install pilk"]
        )
    
    with tempfile.TemporaryDirectory() as temp_dir:
        silk_path = os.path.join(temp_dir, "input.silk")
        pcm_path = os.path.join(temp_dir, "output.pcm")
        
        with open(silk_path, "wb") as f:
            f.write(silk_data)
        
        try:
            pilk.decode(silk_path, pcm_path, pcm_rate=output_sample_rate)
            
            with open(pcm_path, "rb") as f:
                pcm_data = f.read()
            
            return _pcm_to_wav(pcm_data, output_sample_rate)
            
        except Exception as exc:
            raise WeixinAdapterError(
                code="WEIXIN_PILK_DECODE_FAILED",
                message=f"pilk 解码失败: {exc}",
                details={"exception": type(exc).__name__},
                suggestions=["检查 SILK 文件是否有效"]
            )


def _pcm_to_wav(
    pcm_data: bytes,
    sample_rate: int = DEFAULT_WAV_SAMPLE_RATE,
    channels: int = DEFAULT_WAV_CHANNELS,
    sample_width: int = DEFAULT_WAV_SAMPLE_WIDTH,
) -> bytes:
    """
    将 PCM 数据转换为 WAV 格式。
    
    参数:
        pcm_data: PCM 音频数据
        sample_rate: 采样率
        channels: 声道数
        sample_width: 采样宽度（字节）
        
    返回:
        WAV 音频数据
    """
    import io
    
    buffer = io.BytesIO()
    
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(sample_width)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm_data)
    
    buffer.seek(0)
    return buffer.read()


async def silk_to_wav(
    silk_data: bytes,
    output_sample_rate: int = DEFAULT_WAV_SAMPLE_RATE,
    prefer_decoder: str = "auto",
) -> TranscodeResult:
    """
    将 SILK 语音转换为 WAV 格式。
    
    参数:
        silk_data: SILK 音频数据
        output_sample_rate: 输出采样率
        prefer_decoder: 首选解码器（auto, ffmpeg, pilk）
        
    返回:
        TranscodeResult 转码结果
    """
    if not is_silk_format(silk_data):
        return TranscodeResult(
            success=False,
            error_message="输入数据不是 SILK 格式",
            fallback_used=False,
        )
    
    decoders_to_try: List[str] = []
    
    if prefer_decoder == "ffmpeg":
        decoders_to_try = ["ffmpeg", "pilk"]
    elif prefer_decoder == "pilk":
        decoders_to_try = ["pilk", "ffmpeg"]
    else:
        if has_ffmpeg():
            decoders_to_try = ["ffmpeg", "pilk"]
        else:
            decoders_to_try = ["pilk", "ffmpeg"]
    
    last_error = None
    
    for decoder in decoders_to_try:
        try:
            if decoder == "ffmpeg":
                wav_data = await silk_to_wav_with_ffmpeg(silk_data, output_sample_rate)
            elif decoder == "pilk":
                wav_data = await silk_to_wav_with_pilk(silk_data, output_sample_rate)
            else:
                continue
            
            duration = _calculate_wav_duration(wav_data)
            
            logger.info(f"SILK 转码成功: decoder={decoder}, sample_rate={output_sample_rate}, duration={duration:.2f}s")
            
            return TranscodeResult(
                success=True,
                output_data=wav_data,
                output_format="wav",
                sample_rate=output_sample_rate,
                duration_seconds=duration,
                fallback_used=(decoder != decoders_to_try[0]),
            )
            
        except WeixinAdapterError as exc:
            last_error = exc
            logger.warning(f"SILK 转码失败 (decoder={decoder}): {exc.message}")
            continue
        except Exception as exc:
            last_error = WeixinAdapterError(
                code="WEIXIN_TRANSCODE_ERROR",
                message=f"转码异常: {exc}",
                details={"decoder": decoder, "exception": type(exc).__name__},
            )
            logger.warning(f"SILK 转码异常 (decoder={decoder}): {exc}")
            continue
    
    return TranscodeResult(
        success=False,
        error_message=str(last_error) if last_error else "所有解码器都失败",
        fallback_used=True,
    )


def _calculate_wav_duration(wav_data: bytes) -> float:
    """
    计算 WAV 文件的时长。
    
    参数:
        wav_data: WAV 音频数据
        
    返回:
        时长（秒）
    """
    try:
        import io
        
        buffer = io.BytesIO(wav_data)
        with wave.open(buffer, "rb") as wav_file:
            frames = wav_file.getnframes()
            rate = wav_file.getframerate()
            return frames / float(rate) if rate > 0 else 0.0
    except Exception:
        return 0.0


async def transcode_voice(
    voice_data: bytes,
    input_format: str = "silk",
    output_format: str = "wav",
    output_sample_rate: int = DEFAULT_WAV_SAMPLE_RATE,
) -> TranscodeResult:
    """
    通用语音转码函数。
    
    参数:
        voice_data: 语音数据
        input_format: 输入格式（silk, wav, mp3 等）
        output_format: 输出格式
        output_sample_rate: 输出采样率
        
    返回:
        TranscodeResult 转码结果
    """
    input_format = input_format.lower().strip()
    output_format = output_format.lower().strip()
    
    if input_format == "silk":
        return await silk_to_wav(voice_data, output_sample_rate)
    
    if input_format == output_format:
        return TranscodeResult(
            success=True,
            output_data=voice_data,
            output_format=output_format,
            sample_rate=output_sample_rate,
            duration_seconds=_calculate_wav_duration(voice_data) if output_format == "wav" else 0.0,
        )
    
    if has_ffmpeg():
        return await _transcode_with_ffmpeg(voice_data, input_format, output_format, output_sample_rate)
    
    return TranscodeResult(
        success=False,
        error_message="不支持该格式转换，请安装 ffmpeg",
        fallback_used=False,
    )


async def _transcode_with_ffmpeg(
    input_data: bytes,
    input_format: str,
    output_format: str,
    output_sample_rate: int,
) -> TranscodeResult:
    """
    使用 ffmpeg 进行通用转码。
    
    参数:
        input_data: 输入音频数据
        input_format: 输入格式
        output_format: 输出格式
        output_sample_rate: 输出采样率
        
    返回:
        TranscodeResult 转码结果
    """
    if not has_ffmpeg():
        return TranscodeResult(
            success=False,
            error_message="ffmpeg 未安装",
            fallback_used=False,
        )
    
    with tempfile.TemporaryDirectory() as temp_dir:
        input_path = os.path.join(temp_dir, f"input.{input_format}")
        output_path = os.path.join(temp_dir, f"output.{output_format}")
        
        with open(input_path, "wb") as f:
            f.write(input_data)
        
        cmd = [
            "ffmpeg",
            "-y",
            "-i", input_path,
            "-ar", str(output_sample_rate),
            "-ac", "1",
            "-f", output_format,
            output_path,
        ]
        
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode != 0:
                error_msg = stderr.decode("utf-8", errors="ignore")
                return TranscodeResult(
                    success=False,
                    error_message=f"ffmpeg 转码失败: {error_msg[:200]}",
                    fallback_used=False,
                )
            
            with open(output_path, "rb") as f:
                output_data = f.read()
            
            duration = 0.0
            if output_format == "wav":
                duration = _calculate_wav_duration(output_data)
            
            return TranscodeResult(
                success=True,
                output_data=output_data,
                output_format=output_format,
                sample_rate=output_sample_rate,
                duration_seconds=duration,
            )
            
        except Exception as exc:
            return TranscodeResult(
                success=False,
                error_message=f"转码异常: {exc}",
                fallback_used=False,
            )


class VoiceRecognizer:
    """
    语音识别器基类。
    支持多种语音识别后端的集成。
    """
    
    def __init__(self, provider: str = "none"):
        """
        初始化语音识别器。
        
        参数:
            provider: 识别服务提供者（none, whisper, azure, custom）
        """
        self.provider = provider
    
    async def recognize(
        self,
        audio_data: bytes,
        language: str = "zh",
        audio_format: str = "wav",
    ) -> VoiceRecognitionResult:
        """
        识别语音内容。
        
        参数:
            audio_data: 音频数据
            language: 语言代码
            audio_format: 音频格式
            
        返回:
            VoiceRecognitionResult 识别结果
        """
        if self.provider == "none":
            return VoiceRecognitionResult(
                success=False,
                error_message="未配置语音识别服务",
            )
        
        if self.provider == "whisper":
            return await self._recognize_with_whisper(audio_data, language)
        
        if self.provider == "azure":
            return await self._recognize_with_azure(audio_data, language)
        
        return VoiceRecognitionResult(
            success=False,
            error_message=f"不支持的识别服务: {self.provider}",
        )
    
    async def _recognize_with_whisper(
        self,
        audio_data: bytes,
        language: str,
    ) -> VoiceRecognitionResult:
        """
        使用 Whisper 进行语音识别。
        
        参数:
            audio_data: 音频数据
            language: 语言代码
            
        返回:
            VoiceRecognitionResult 识别结果
        """
        try:
            import whisper
        except ImportError:
            return VoiceRecognitionResult(
                success=False,
                error_message="whisper 库未安装，请执行: pip install openai-whisper",
            )
        
        try:
            model = whisper.load_model("base")
            
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_file:
                temp_file.write(audio_data)
                temp_path = temp_file.name
            
            try:
                result = model.transcribe(temp_path, language=language)
                
                return VoiceRecognitionResult(
                    success=True,
                    text=result.get("text", "").strip(),
                    confidence=1.0,
                    language=language,
                )
            finally:
                os.unlink(temp_path)
                
        except Exception as exc:
            return VoiceRecognitionResult(
                success=False,
                error_message=f"Whisper 识别失败: {exc}",
            )
    
    async def _recognize_with_azure(
        self,
        audio_data: bytes,
        language: str,
    ) -> VoiceRecognitionResult:
        """
        使用 Azure Speech Services 进行语音识别。
        
        参数:
            audio_data: 音频数据
            language: 语言代码
            
        返回:
            VoiceRecognitionResult 识别结果
        """
        try:
            import azure.cognitiveservices.speech as speechsdk
        except ImportError:
            return VoiceRecognitionResult(
                success=False,
                error_message="azure-cognitiveservices-speech 库未安装",
            )
        
        speech_key = os.environ.get("AZURE_SPEECH_KEY")
        service_region = os.environ.get("AZURE_SPEECH_REGION")
        
        if not speech_key or not service_region:
            return VoiceRecognitionResult(
                success=False,
                error_message="未配置 Azure Speech 服务凭证",
            )
        
        try:
            speech_config = speechsdk.SpeechConfig(
                subscription=speech_key,
                region=service_region,
            )
            speech_config.speech_recognition_language = language
            
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_file:
                temp_file.write(audio_data)
                temp_path = temp_file.name
            
            try:
                audio_config = speechsdk.AudioConfig(filename=temp_path)
                recognizer = speechsdk.SpeechRecognizer(
                    speech_config=speech_config,
                    audio_config=audio_config,
                )
                
                result = recognizer.recognize_once()
                
                if result.reason == speechsdk.ResultReason.RecognizedSpeech:
                    return VoiceRecognitionResult(
                        success=True,
                        text=result.text.strip(),
                        confidence=1.0,
                        language=language,
                    )
                else:
                    return VoiceRecognitionResult(
                        success=False,
                        error_message=f"Azure 识别失败: {result.reason}",
                    )
            finally:
                os.unlink(temp_path)
                
        except Exception as exc:
            return VoiceRecognitionResult(
                success=False,
                error_message=f"Azure 识别异常: {exc}",
            )


async def voice_to_text(
    voice_data: bytes,
    input_format: str = "silk",
    language: str = "zh",
    recognizer: Optional[VoiceRecognizer] = None,
) -> VoiceRecognitionResult:
    """
    将语音转换为文字。
    
    参数:
        voice_data: 语音数据
        input_format: 输入格式
        language: 语言代码
        recognizer: 语音识别器（可选）
        
    返回:
        VoiceRecognitionResult 识别结果
    """
    if input_format == "silk":
        transcode_result = await silk_to_wav(voice_data)
        if not transcode_result.success:
            return VoiceRecognitionResult(
                success=False,
                error_message=f"语音转码失败: {transcode_result.error_message}",
            )
        wav_data = transcode_result.output_data
    else:
        wav_data = voice_data
    
    if recognizer is None:
        recognizer = VoiceRecognizer(provider="none")
    
    return await recognizer.recognize(wav_data, language, "wav")


def get_mime_type(format_name: str) -> str:
    """
    根据格式名称获取 MIME 类型。
    
    参数:
        format_name: 格式名称
        
    返回:
        MIME 类型字符串
    """
    mime_map = {
        "wav": "audio/wav",
        "mp3": "audio/mpeg",
        "ogg": "audio/ogg",
        "silk": "audio/silk",
        "m4a": "audio/mp4",
        "flac": "audio/flac",
    }
    
    return mime_map.get(format_name.lower(), "application/octet-stream")


def get_file_extension(mime_type: str) -> str:
    """
    根据 MIME 类型获取文件扩展名。
    
    参数:
        mime_type: MIME 类型
        
    返回:
        文件扩展名
    """
    mime_to_ext = {
        "audio/wav": ".wav",
        "audio/x-wav": ".wav",
        "audio/mpeg": ".mp3",
        "audio/mp3": ".mp3",
        "audio/ogg": ".ogg",
        "audio/silk": ".silk",
        "audio/mp4": ".m4a",
        "audio/flac": ".flac",
    }
    
    return mime_to_ext.get(mime_type.lower(), ".bin")

