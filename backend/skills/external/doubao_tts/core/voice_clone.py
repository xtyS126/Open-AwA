"""
豆包声音复刻管理器 — 封装声音复刻 API（创建/查询/删除音色）。
使用火山引擎 Doubao-Seed-ICL 2.0 接口。
"""
import asyncio
import os
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

import httpx
from loguru import logger


DEFAULT_BASE_URL = "https://openspeech.bytedance.com"
DEFAULT_CLONE_RESOURCE_ID = "seed-icl-2.0"

# 声音复刻训练轮询配置
POLL_INTERVAL_SECONDS = 5
POLL_MAX_ATTEMPTS = 60  # 最多轮询 5 分钟


class VoiceCloneManager:
    """
    声音复刻管理器。
    上传音频样本 → 创建训练任务 → 轮询训练状态 → 获取 speaker_id。
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
        self.resource_id = resource_id or os.getenv("DOUBAO_ICL_RESOURCE_ID", DEFAULT_CLONE_RESOURCE_ID)
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")

        # 内存中跟踪训练状态（生产环境应使用数据库）
        self._speakers: Dict[str, Dict[str, Any]] = {}

    @property
    def is_configured(self) -> bool:
        """检查 API 凭证是否已配置。"""
        return bool(self.app_id and self.access_key)

    def _build_headers(self) -> Dict[str, str]:
        """构建 API 请求头。"""
        return {
            "X-Api-App-Id": self.app_id,
            "X-Api-Access-Key": self.access_key,
            "X-Api-Resource-Id": self.resource_id,
            "Content-Type": "application/json",
        }

    async def create_speaker(
        self,
        audio_bytes: bytes,
        voice_name: str,
        context_texts: Optional[str] = None,
        user_id: str = "",
    ) -> str:
        """
        上传音频样本并创建声音复刻训练任务。
        返回 speaker_id（可能处于 training 状态，需轮询至 ready）。

        Args:
            audio_bytes: WAV 格式音频字节（14~30 秒）
            voice_name: 音色名称
            context_texts: 音频对应的文本内容

        Returns:
            speaker_id: 音色唯一标识
        """
        if not self.is_configured:
            raise RuntimeError("Doubao 声音复刻 API 未配置，请设置 DOUBAO_APP_ID 和 DOUBAO_ACCESS_KEY 环境变量")

        # 校验音频时长
        audio_duration = self._estimate_audio_duration(audio_bytes)
        if audio_duration < 10 or audio_duration > 35:
            raise ValueError(
                f"音频时长 {audio_duration:.1f}s 不满足要求，需要 14~30 秒内的音频"
            )

        url = f"{self.base_url}/api/v3/icl/create"
        headers = self._build_headers()

        # 将音频转为 base64
        import base64
        audio_base64 = base64.b64encode(audio_bytes).decode("ascii")

        payload: Dict[str, Any] = {
            "voice_name": voice_name,
            "audio_data": audio_base64,
            "audio_format": "wav",
        }
        if context_texts:
            payload["context_texts"] = context_texts
            payload["language"] = "zh"  # 默认中文

        logger.bind(event="doubao_clone_create", voice_name=voice_name,
                     audio_len=len(audio_bytes), duration=audio_duration).info("提交声音复刻训练任务")

        async with httpx.AsyncClient(timeout=120, follow_redirects=False) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        speaker_id = data.get("speaker_id") or data.get("data", {}).get("speaker_id", "")
        if not speaker_id:
            raise RuntimeError(f"声音复刻创建失败：未获取到 speaker_id。响应: {str(data)[:300]}")

        # 记录训练状态
        self._speakers[speaker_id] = {
            "speaker_id": speaker_id,
            "voice_name": voice_name,
            "status": "training",
            "audio_duration": audio_duration,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "language": payload.get("language", "zh"),
            "user_id": user_id,
        }

        logger.bind(event="doubao_clone_created", speaker_id=speaker_id,
                     voice_name=voice_name).info("声音复刻训练任务已创建")
        return speaker_id

    async def get_status(self, speaker_id: str, user_id: str = "") -> Dict[str, Any]:
        """
        查询声音复刻训练状态。若提供 user_id，校验所有权。
        仅支持查询本地缓存的复刻音色，不允许绕过缓存直接查询远程 API。
        """
        # 仅从内存缓存查询，防止绕过所有权校验直接访问远程 API
        cached = self._speakers.get(speaker_id)
        if cached is None:
            # 音色不在本地缓存中（可能不存在或为预置音色）
            if user_id:
                raise PermissionError("无权访问此音色")
            return {"speaker_id": speaker_id, "status": "unknown", "message": "音色不存在"}

        owner = cached.get("user_id", "")
        if user_id and owner and owner != user_id:
            raise PermissionError("无权访问此音色")

        # 如果状态为 ready，直接返回缓存
        if cached.get("status") == "ready":
            return dict(cached)

        # 如果仍处于 training 状态且 API 已配置，查询最新状态
        if self.is_configured:
            url = f"{self.base_url}/api/v3/icl/status"
            headers = self._build_headers()
            payload = {"speaker_id": speaker_id}

            async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()

            status = data.get("status") or data.get("data", {}).get("status", "unknown")
            cached["status"] = status
            cached["updated_at"] = datetime.now(timezone.utc).isoformat()

        return dict(cached)

    async def wait_for_ready(self, speaker_id: str) -> Dict[str, Any]:
        """
        轮询等待复刻训练完成（阻塞，最长 5 分钟）。
        """
        for attempt in range(POLL_MAX_ATTEMPTS):
            status_info = await self.get_status(speaker_id)
            status = status_info.get("status", "")

            if status == "ready":
                logger.bind(event="doubao_clone_ready", speaker_id=speaker_id,
                             attempts=attempt + 1).info("声音复刻训练完成")
                return status_info

            if status == "failed":
                raise RuntimeError(f"声音复刻训练失败: {status_info.get('error_message', '未知错误')}")

            logger.bind(event="doubao_clone_polling", speaker_id=speaker_id, status=status,
                         attempt=attempt + 1).debug("等待复刻训练完成...")
            await asyncio.sleep(POLL_INTERVAL_SECONDS)

        raise TimeoutError(f"声音复刻训练超时（{POLL_MAX_ATTEMPTS * POLL_INTERVAL_SECONDS}秒），speaker_id={speaker_id}")

    async def list_speakers(self, user_id: str = "") -> List[Dict[str, Any]]:
        """
        列出所有音色（含预置音色 + 当前用户的复刻音色）。
        """
        from .tts_client import DoubaoTTSService

        # 预置音色
        speakers = DoubaoTTSService.list_preset_speakers()

        # 仅列出当前用户的复刻音色
        for sid, info in self._speakers.items():
            if user_id and info.get("user_id", "") != user_id:
                continue
            speakers.append({
                "speaker_id": sid,
                "name": info.get("voice_name", sid),
                "language": info.get("language", "zh"),
                "description": f"复刻音色（{info.get('status', 'unknown')}）",
                "is_cloned": True,
                "status": info.get("status", "unknown"),
                "audio_duration": info.get("audio_duration", 0.0),
                "created_at": info.get("created_at", ""),
            })

        return speakers

    async def delete_speaker(self, speaker_id: str, user_id: str = "") -> bool:
        """
        删除复刻音色。若提供 user_id，校验所有权。
        """
        # 不允许删除预置音色
        from .tts_client import PRESET_SPEAKERS
        if speaker_id in PRESET_SPEAKERS:
            raise ValueError(f"不允许删除预置音色: {speaker_id}")

        # 校验所有权：仅允许删除本地缓存的、属于当前用户的复刻音色
        cached = self._speakers.get(speaker_id)
        if cached is None:
            if user_id:
                raise PermissionError("无权删除此音色")
            return False  # 音色不存在
        if user_id:
            owner = cached.get("user_id", "")
            if owner and owner != user_id:
                raise PermissionError("无权删除此音色")

        # 从本地缓存和远程 API 删除
        if self.is_configured:
            url = f"{self.base_url}/api/v3/icl/delete"
            headers = self._build_headers()
            payload = {"speaker_id": speaker_id}
            async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()

        self._speakers.pop(speaker_id, None)
        logger.bind(event="doubao_clone_deleted", speaker_id=speaker_id).info("复刻音色已删除")
        return True

    @staticmethod
    def _estimate_audio_duration(audio_bytes: bytes) -> float:
        """
        估算 WAV 音频时长（秒）。
        WAV 头 44 字节，采样率在 24-27 字节，声道数在 22-23 字节，位深度在 34-35 字节。
        """
        if len(audio_bytes) < 44:
            return 0.0
        try:
            import struct
            sample_rate = struct.unpack_from("<I", audio_bytes, 24)[0]
            channels = struct.unpack_from("<H", audio_bytes, 22)[0]
            bits_per_sample = struct.unpack_from("<H", audio_bytes, 34)[0]
            data_size = len(audio_bytes) - 44
            if sample_rate > 0 and channels > 0 and bits_per_sample > 0:
                bytes_per_second = sample_rate * channels * (bits_per_sample // 8)
                return data_size / bytes_per_second if bytes_per_second > 0 else 0.0
        except Exception:
            pass
        return 0.0
