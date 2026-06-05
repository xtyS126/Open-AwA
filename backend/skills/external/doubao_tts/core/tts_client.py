"""
豆包 TTS API 客户端 — 封装火山引擎豆包语音合成 HTTP/SSE 接口。
支持非流式合成、流式合成（SSE）、异步长文本合成。
"""
import base64
import json
import os
from typing import AsyncIterator, Optional, Dict, Any

import httpx
from loguru import logger

from .models import TTSRequest, TTSResponse


# 预置音色列表（豆包 TTS 2.0 常用音色）
PRESET_SPEAKERS: Dict[str, Dict[str, str]] = {
    "zh_female_qingxin": {"name": "清新女声", "language": "zh", "description": "默认女声，清新自然"},
    "zh_male_qingse": {"name": "青涩男声", "language": "zh", "description": "青年男声，阳光活泼"},
    "zh_female_wenrou": {"name": "温柔女声", "language": "zh", "description": "温柔细腻女声"},
    "zh_male_chenwen": {"name": "沉稳男声", "language": "zh", "description": "成熟稳重男声"},
    "zh_female_zhixing": {"name": "知性女声", "language": "zh", "description": "知性优雅女声"},
    "zh_male_xiongying": {"name": "雄鹰男声", "language": "zh", "description": "磁性浑厚男声"},
    "en_female_natural": {"name": "Natural Female", "language": "en", "description": "Natural American female voice"},
    "en_male_natural": {"name": "Natural Male", "language": "en", "description": "Natural American male voice"},
}

# 豆包语音 API 基地址
DEFAULT_BASE_URL = "https://openspeech.bytedance.com"
DEFAULT_TTS_RESOURCE_ID = "seed-tts-2.0"
DEFAULT_CLONE_RESOURCE_ID = "seed-icl-2.0"


class DoubaoTTSService:
    """
    豆包语音合成服务客户端。
    封装火山引擎 TTS API 的非流式、流式（SSE）和异步长文本合成。
    鉴权通过 X-Api-App-Id 和 X-Api-Access-Key 头完成。
    """

    def __init__(
        self,
        app_id: Optional[str] = None,
        access_key: Optional[str] = None,
        resource_id: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        self.app_id = app_id or os.getenv("DOUBAO_APP_ID", "")
        self.access_key = access_key or os.getenv("DOUBAO_ACCESS_KEY", "")
        self.resource_id = resource_id or os.getenv("DOUBAO_TTS_RESOURCE_ID", DEFAULT_TTS_RESOURCE_ID)
        self.clone_resource_id = os.getenv("DOUBAO_ICL_RESOURCE_ID", DEFAULT_CLONE_RESOURCE_ID)
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")

    @property
    def is_configured(self) -> bool:
        """检查 API 凭证是否已配置。"""
        return bool(self.app_id and self.access_key)

    def _build_headers(self, resource_id: Optional[str] = None) -> Dict[str, str]:
        """构建 API 请求头。"""
        rid = resource_id or self.resource_id
        return {
            "X-Api-App-Id": self.app_id,
            "X-Api-Access-Key": self.access_key,
            "X-Api-Resource-Id": rid,
            "Content-Type": "application/json",
        }

    def _build_payload(self, request: TTSRequest) -> Dict[str, Any]:
        """构建 TTS 请求体。"""
        payload: Dict[str, Any] = {
            "text": request.text,
            "speaker": request.speaker_id,
            "audio_params": {
                "format": request.audio_format,
                "sample_rate": request.sample_rate,
                "speed_ratio": request.speed_ratio,
                "volume_ratio": request.volume_ratio,
                "pitch_ratio": request.pitch_ratio,
            },
        }
        if request.emotion:
            payload["emotion"] = request.emotion
            payload["emotion_scale"] = request.emotion_scale
        if request.context_texts:
            payload["context_texts"] = request.context_texts
        if request.language:
            payload["language"] = request.language
        if request.ssml:
            payload["ssml"] = request.ssml
        return payload

    async def synthesize(self, request: TTSRequest) -> bytes:
        """
        非流式语音合成，返回完整音频字节。
        """
        if not self.is_configured:
            raise RuntimeError("Doubao TTS API 未配置，请设置 DOUBAO_APP_ID 和 DOUBAO_ACCESS_KEY 环境变量")

        url = f"{self.base_url}/api/v1/tts"
        headers = self._build_headers(request.resource_id)
        payload = self._build_payload(request)

        logger.bind(event="doubao_tts_synthesize", speaker=request.speaker_id,
                     text_len=len(request.text)).info("开始非流式 TTS 合成")

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()

            content_type = resp.headers.get("content-type", "")
            if "audio" in content_type:
                return resp.content
            # 可能返回 JSON 格式（含 base64 编码音频）
            try:
                data = resp.json()
                if data.get("audio"):
                    return base64.b64decode(data["audio"])
                raise RuntimeError(f"TTS 响应中未找到音频数据: {str(data)[:200]}")
            except (json.JSONDecodeError, KeyError):
                return resp.content

    async def synthesize_stream(self, request: TTSRequest) -> AsyncIterator[bytes]:
        """
        流式语音合成（SSE），逐块产出音频字节。
        参考豆包 V3 流式接口规范。
        """
        if not self.is_configured:
            raise RuntimeError("Doubao TTS API 未配置，请设置 DOUBAO_APP_ID 和 DOUBAO_ACCESS_KEY 环境变量")

        url = f"{self.base_url}/api/v3/tts/unidirectional/stream"
        headers = self._build_headers(request.resource_id)
        headers["Accept"] = "text/event-stream"
        payload = self._build_payload(request)

        logger.bind(event="doubao_tts_stream", speaker=request.speaker_id,
                     text_len=len(request.text)).info("开始流式 TTS 合成")

        async with httpx.AsyncClient(timeout=120, follow_redirects=False) as client:
            async with client.stream("POST", url, json=payload, headers=headers) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if line.startswith("data:"):
                        data_str = line[5:].strip()
                        if data_str == "[DONE]":
                            break
                        if not data_str:
                            continue
                        try:
                            # 数据可能是 base64 编码的音频块
                            audio_chunk = base64.b64decode(data_str)
                            yield audio_chunk
                        except Exception:
                            # 如果不是 base64，可能是 JSON 事件
                            try:
                                event = json.loads(data_str)
                                if event.get("audio"):
                                    yield base64.b64decode(event["audio"])
                            except (json.JSONDecodeError, KeyError):
                                continue

    async def submit_long_text(self, request: TTSRequest, callback_url: str = "") -> str:
        """
        提交异步长文本合成任务，返回 task_id。
        适用于超过 1000 字符的长文本，最大支持 10 万字符。
        """
        if not self.is_configured:
            raise RuntimeError("Doubao TTS API 未配置")

        url = f"{self.base_url}/api/v3/tts/submit"
        headers = self._build_headers(request.resource_id)
        payload = self._build_payload(request)
        if callback_url:
            payload["callback_url"] = callback_url

        logger.bind(event="doubao_tts_long_text", speaker=request.speaker_id,
                     text_len=len(request.text)).info("提交异步长文本合成任务")

        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            task_id = data.get("task_id") or data.get("data", {}).get("task_id", "")
            if not task_id:
                raise RuntimeError(f"未获取到 task_id: {str(data)[:200]}")
            return task_id

    async def query_task(self, task_id: str) -> Dict[str, Any]:
        """
        查询异步合成任务状态，完成时返回音频下载地址。
        """
        url = f"{self.base_url}/api/v3/tts/query"
        headers = self._build_headers()
        payload = {"task_id": task_id}

        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            return resp.json()

    @staticmethod
    def list_preset_speakers() -> list:
        """列出预置音色。"""
        return [
            {
                "speaker_id": sid,
                "name": info["name"],
                "language": info["language"],
                "description": info.get("description", ""),
                "is_cloned": False,
                "status": "ready",
            }
            for sid, info in PRESET_SPEAKERS.items()
        ]
