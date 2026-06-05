"""
豆包 TTS 模块单元测试。
测试 TTS 客户端、声音复刻管理器、API 路由。
"""
import base64
import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from skills.external.doubao_tts.core.models import (
    TTSRequest,
    TTSResponse,
    VoiceCloneStatus,
    SpeakerInfo,
    TTSHealthResponse,
)
from skills.external.doubao_tts.core.tts_client import (
    DoubaoTTSService,
    PRESET_SPEAKERS,
    DEFAULT_BASE_URL,
)


class TestDoubaoTTSService:
    """TTS 客户端单元测试。"""

    def test_is_configured_returns_false_without_credentials(self):
        """未配置凭证时 is_configured 返回 False。"""
        service = DoubaoTTSService(app_id="", access_key="")
        assert service.is_configured is False

    def test_is_configured_returns_true_with_credentials(self):
        """配置凭证后 is_configured 返回 True。"""
        service = DoubaoTTSService(app_id="test_id", access_key="test_key")
        assert service.is_configured is True

    def test_list_preset_speakers_returns_all_entries(self):
        """list_preset_speakers 返回所有预置音色。"""
        speakers = DoubaoTTSService.list_preset_speakers()
        assert len(speakers) == len(PRESET_SPEAKERS)
        assert all("speaker_id" in s for s in speakers)
        assert all("name" in s for s in speakers)
        assert all("is_cloned" in s for s in speakers)
        assert all(s["is_cloned"] is False for s in speakers)

    def test_build_headers_includes_auth_info(self):
        """构建的请求头包含鉴权信息。"""
        service = DoubaoTTSService(app_id="my_app", access_key="my_key")
        headers = service._build_headers()
        assert headers["X-Api-App-Id"] == "my_app"
        assert headers["X-Api-Access-Key"] == "my_key"
        assert "X-Api-Resource-Id" in headers
        assert headers["Content-Type"] == "application/json"

    def test_build_headers_uses_custom_resource_id(self):
        """自定义 resource_id 覆盖默认值。"""
        service = DoubaoTTSService(app_id="a", access_key="b")
        headers = service._build_headers(resource_id="seed-icl-2.0")
        assert headers["X-Api-Resource-Id"] == "seed-icl-2.0"

    def test_build_payload_includes_all_fields(self):
        """构建的请求体包含所有 TTS 参数。"""
        service = DoubaoTTSService(app_id="a", access_key="b")
        request = TTSRequest(
            text="你好世界",
            speaker_id="zh_female_qingxin",
            audio_format="wav",
            sample_rate=16000,
            speed_ratio=1.2,
            volume_ratio=0.8,
            pitch_ratio=2.0,
            emotion="happy",
            emotion_scale=3,
            context_texts="上下文文本",
            language="zh",
        )
        payload = service._build_payload(request)
        assert payload["text"] == "你好世界"
        assert payload["speaker"] == "zh_female_qingxin"
        assert payload["audio_params"]["format"] == "wav"
        assert payload["audio_params"]["sample_rate"] == 16000
        assert payload["emotion"] == "happy"
        assert payload["emotion_scale"] == 3
        assert payload["context_texts"] == "上下文文本"

    def test_build_payload_omits_optional_emotion(self):
        """未指定情感时 payload 不含情感字段。"""
        service = DoubaoTTSService(app_id="a", access_key="b")
        request = TTSRequest(text="你好", speaker_id="default")
        payload = service._build_payload(request)
        assert "emotion" not in payload

    def test_synthesize_raises_when_not_configured(self):
        """未配置时 synthesize 抛出 RuntimeError。"""
        service = DoubaoTTSService(app_id="", access_key="")
        request = TTSRequest(text="test")
        with pytest.raises(RuntimeError, match="未配置"):
            import asyncio
            asyncio.get_event_loop().run_until_complete(
                service.synthesize(request)
            )

    @pytest.mark.asyncio
    async def test_synthesize_returns_audio_bytes(self):
        """配置后 synthesize 返回音频字节（mock HTTP）。"""
        service = DoubaoTTSService(app_id="test_id", access_key="test_key")
        request = TTSRequest(text="你好")

        # 模拟 API 返回的音频数据
        fake_audio = b"\xff\xfb\x90\x00" * 100  # 模拟 MP3 帧

        mock_response = AsyncMock()
        mock_response.headers = {"content-type": "audio/mpeg"}
        mock_response.content = fake_audio
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)
            result = await service.synthesize(request)

        assert result == fake_audio

    @pytest.mark.asyncio
    async def test_synthesize_stream_yields_chunks(self):
        """流式合成逐块产出音频数据。"""
        service = DoubaoTTSService(app_id="test_id", access_key="test_key")
        request = TTSRequest(text="流式测试")

        async def mock_stream():
            """模拟 SSE 流。"""
            pass  # mock_stream 在 patch 中使用

        chunks = []
        mock_resp = AsyncMock()
        mock_resp.raise_for_status = MagicMock()

        # 模拟两个音频块和一个 DONE
        mock_lines = [
            "data: " + base64.b64encode(b"chunk1").decode(),
            "data: " + base64.b64encode(b"chunk2").decode(),
            "data: [DONE]",
        ]

        mock_resp.aiter_lines = MagicMock(return_value=AsyncIterable(mock_lines))

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.stream = MagicMock()
            mock_client.stream.return_value.__aenter__ = AsyncMock(return_value=mock_resp)
            mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)

            async for chunk in service.synthesize_stream(request):
                chunks.append(chunk)

        assert len(chunks) == 2
        assert chunks[0] == b"chunk1"
        assert chunks[1] == b"chunk2"

    def test_base_url_default(self):
        """默认使用字节跳动 API 基地址。"""
        service = DoubaoTTSService(app_id="a", access_key="b")
        assert service.base_url == DEFAULT_BASE_URL.rstrip("/")


class AsyncIterable:
    """将列表包装为异步可迭代对象，用于 mock aiter_lines。"""
    def __init__(self, items):
        self._items = items

    def __aiter__(self):
        self._iter = iter(self._items)
        return self

    async def __anext__(self):
        try:
            return next(self._iter)
        except StopIteration:
            raise StopAsyncIteration


class TestVoiceCloneManager:
    """声音复刻管理器测试。"""

    def test_is_configured_without_credentials(self):
        """未配置时返回 False。"""
        from skills.external.doubao_tts.core.voice_clone import VoiceCloneManager
        manager = VoiceCloneManager(app_id="", access_key="")
        assert manager.is_configured is False

    def test_is_configured_with_credentials(self):
        """配置后返回 True。"""
        from skills.external.doubao_tts.core.voice_clone import VoiceCloneManager
        manager = VoiceCloneManager(app_id="test", access_key="test")
        assert manager.is_configured is True

    def test_estimate_audio_duration_valid_wav(self):
        """正确估算 WAV 音频时长。"""
        from skills.external.doubao_tts.core.voice_clone import VoiceCloneManager
        import struct

        # 构建模拟 WAV 头（44 bytes）
        sample_rate = 16000
        channels = 1
        bits_per_sample = 16
        data_size = sample_rate * channels * (bits_per_sample // 8) * 4  # 4秒

        header = bytearray(44)
        header[0:4] = b"RIFF"
        struct.pack_into("<I", header, 4, 36 + data_size)
        header[8:12] = b"WAVE"
        header[12:16] = b"fmt "
        struct.pack_into("<I", header, 16, 16)  # chunk size
        struct.pack_into("<H", header, 20, 1)   # PCM
        struct.pack_into("<H", header, 22, channels)
        struct.pack_into("<I", header, 24, sample_rate)
        struct.pack_into("<H", header, 34, bits_per_sample)
        header[36:40] = b"data"
        struct.pack_into("<I", header, 40, data_size)

        fake_audio = bytes(header) + b"\x00" * data_size
        duration = VoiceCloneManager._estimate_audio_duration(fake_audio)
        assert 3.9 <= duration <= 4.1

    def test_estimate_audio_duration_short_bytes(self):
        """过短的字节返回 0。"""
        from skills.external.doubao_tts.core.voice_clone import VoiceCloneManager
        assert VoiceCloneManager._estimate_audio_duration(b"short") == 0.0

    @pytest.mark.asyncio
    async def test_create_speaker_returns_speaker_id(self):
        """创建复刻任务返回 speaker_id（mock HTTP）。"""
        from skills.external.doubao_tts.core.voice_clone import VoiceCloneManager

        manager = VoiceCloneManager(app_id="test", access_key="test")

        # 构建足够长的假音频（绕过时长检查）
        fake_wav = bytearray(44 + 16000 * 2 * 15)  # ~15 秒
        fake_wav[0:4] = b"RIFF"
        fake_wav[8:12] = b"WAVE"
        fake_wav[12:16] = b"fmt "
        import struct
        struct.pack_into("<H", fake_wav, 22, 1)
        struct.pack_into("<I", fake_wav, 24, 16000)
        struct.pack_into("<H", fake_wav, 34, 16)
        fake_wav[36:40] = b"data"
        struct.pack_into("<I", fake_wav, 40, 16000 * 2 * 15)

        mock_resp = AsyncMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json = MagicMock(return_value={"speaker_id": "spk_test_001"})

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)

            speaker_id = await manager.create_speaker(
                audio_bytes=bytes(fake_wav),
                voice_name="测试音色",
            )

        assert speaker_id == "spk_test_001"

    @pytest.mark.asyncio
    async def test_list_speakers_includes_presets(self):
        """list_speakers 包含预置音色。"""
        from skills.external.doubao_tts.core.voice_clone import VoiceCloneManager
        manager = VoiceCloneManager(app_id="test", access_key="test")
        speakers = await manager.list_speakers()
        # 至少包含 8 个预置音色
        assert len(speakers) >= 8
        assert any(not s["is_cloned"] for s in speakers)

    def test_delete_preset_speaker_raises(self):
        """不允许删除预置音色。"""
        from skills.external.doubao_tts.core.voice_clone import VoiceCloneManager
        import asyncio

        manager = VoiceCloneManager(app_id="test", access_key="test")
        with pytest.raises(ValueError, match="不允许删除预置音色"):
            asyncio.get_event_loop().run_until_complete(
                manager.delete_speaker("zh_female_qingxin")
            )


class TestTTSModels:
    """Pydantic 模型校验测试。"""

    def test_tts_request_defaults(self):
        """TTSRequest 默认值测试。"""
        req = TTSRequest(text="你好")
        assert req.speaker_id == "zh_female_qingxin"
        assert req.audio_format == "mp3"
        assert req.sample_rate == 24000
        assert req.speed_ratio == 1.0
        assert req.emotion is None
        assert req.language == "zh"

    def test_tts_request_validation(self):
        """TTSRequest 参数校验。"""
        with pytest.raises(Exception):  # Pydantic ValidationError
            TTSRequest(text="")  # min_length=1

        with pytest.raises(Exception):
            TTSRequest(text="你好", speed_ratio=3.0)  # > 2.0

        with pytest.raises(Exception):
            TTSRequest(text="你好", pitch_ratio=20.0)  # > 12

    def test_speaker_info_model(self):
        """SpeakerInfo 模型字段。"""
        info = SpeakerInfo(
            speaker_id="spk_001",
            name="测试音色",
            status="ready",
            language="zh",
        )
        assert info.is_cloned is False
        assert info.description == ""
        assert info.audio_duration == 0.0

    def test_tts_health_response(self):
        """健康检查响应模型。"""
        resp = TTSHealthResponse(configured=True)
        assert resp.status == "ok"
        assert resp.service == "doubao-tts"
        assert resp.configured is True
