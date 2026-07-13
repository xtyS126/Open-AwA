"""
微信多媒体消息处理与 WebSocket 事件总线测试。

覆盖范围：
1. WeixinEventBus 订阅/发布/取消订阅/队列满丢弃
2. extract_weixin_multimedia 识别图片/语音/文件/视频
3. build_multimedia_description 生成可读描述
4. normalize_inbound_message 多媒体消息标记为 replyable
5. 多媒体消息查询 API
6. WeixinSkillAdapter 多媒体上传与发送方法
7. 多媒体发送 API 路由与安全校验
8. 元数据解析与文件名清理辅助函数
"""

import asyncio
import io
import os
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.dependencies import get_current_user, get_db
from api.routes import weixin as weixin_routes
from api.routes.weixin import _parse_multimedia_metadata, _sanitize_upload_filename
from api.services.weixin_auto_reply import (
    WeixinEventBus,
    extract_weixin_multimedia,
    extract_weixin_media_credentials,
    build_multimedia_description,
    normalize_inbound_message,
    get_event_bus,
    MULTIMEDIA_TYPE_IMAGE,
    MULTIMEDIA_TYPE_VOICE,
    MULTIMEDIA_TYPE_FILE,
    MULTIMEDIA_TYPE_VIDEO,
)
from config.security import encrypt_secret_value
from db.models import Base, ShortTermMemory, WeixinBinding, WeixinMediaAsset
from main import app
from skills.weixin_skill_adapter import (
    WeixinAdapterError,
    WeixinRuntimeConfig,
    WeixinSkillAdapter,
)


engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base.metadata.create_all(bind=engine)


def override_get_db():
    """提供测试隔离数据库会话。"""
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


def override_get_current_user():
    """提供固定测试用户。"""

    class DummyUser:
        id = "user-1"
        username = "testuser"

    return DummyUser()


@contextmanager
def _test_client():
    """为 API 测试临时注入依赖。"""
    previous_overrides = dict(app.dependency_overrides)
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides = previous_overrides


@pytest.fixture(autouse=True)
def reset_state():
    """保证每个测试从干净的数据库状态开始。"""
    db = TestingSessionLocal()
    try:
        db.query(WeixinBinding).delete()
        db.query(WeixinMediaAsset).delete()
        db.query(ShortTermMemory).delete()
        db.commit()
    finally:
        db.close()
    yield
    db = TestingSessionLocal()
    try:
        db.query(WeixinBinding).delete()
        db.query(WeixinMediaAsset).delete()
        db.query(ShortTermMemory).delete()
        db.commit()
    finally:
        db.close()


# ──────────────────────────────────────────────
#  WeixinEventBus 测试
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_event_bus_subscribe_and_publish():
    """验证事件总线订阅与发布。"""
    bus = WeixinEventBus()
    queue = await bus.subscribe("user-A")
    event = {"event": "new_message", "text": "hello"}
    await bus.publish("user-A", event)
    received = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert received == event


@pytest.mark.asyncio
async def test_event_bus_unsubscribe_removes_queue():
    """验证取消订阅后不再接收事件。"""
    bus = WeixinEventBus()
    await bus.subscribe("user-B")
    await bus.unsubscribe("user-B")
    # 发布事件不应抛错，但内部队列已清理
    await bus.publish("user-B", {"event": "test"})
    # 队列已不存在，再次订阅会创建新队列
    queue = await bus.subscribe("user-B")
    assert queue.qsize() == 0


@pytest.mark.asyncio
async def test_event_bus_publish_to_nonexistent_subscriber_is_noop():
    """验证向未订阅用户发布事件是空操作。"""
    bus = WeixinEventBus()
    # 不应抛错
    await bus.publish("nonexistent", {"event": "test"})


@pytest.mark.asyncio
async def test_event_bus_queue_full_drops_oldest():
    """验证队列满时丢弃最旧事件。"""
    bus = WeixinEventBus()
    queue = await bus.subscribe("user-C", maxsize=2)
    await bus.publish("user-C", {"event": "msg1"})
    await bus.publish("user-C", {"event": "msg2"})
    await bus.publish("user-C", {"event": "msg3"})  # 应丢弃 msg1

    first = await asyncio.wait_for(queue.get(), timeout=1.0)
    second = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert first["event"] == "msg2"
    assert second["event"] == "msg3"


@pytest.mark.asyncio
async def test_event_bus_isolates_users():
    """验证不同用户队列相互隔离。"""
    bus = WeixinEventBus()
    queue_a = await bus.subscribe("user-A")
    queue_b = await bus.subscribe("user-B")
    await bus.publish("user-A", {"event": "for-A"})
    await bus.publish("user-B", {"event": "for-B"})

    a_event = await asyncio.wait_for(queue_a.get(), timeout=1.0)
    b_event = await asyncio.wait_for(queue_b.get(), timeout=1.0)
    assert a_event["event"] == "for-A"
    assert b_event["event"] == "for-B"


# ──────────────────────────────────────────────
#  extract_weixin_multimedia 测试
# ──────────────────────────────────────────────

def test_extract_multimedia_image_message():
    """验证图片消息识别。"""
    message = {
        "from_user_id": "user-X",
        "context_token": "ctx-X",
        "item_list": [
            {
                "type": 2,
                "image_item": {
                    "media_id": "img-001",
                    "url": "https://wx.example.com/img/001.jpg",
                    "format": "jpg",
                },
            }
        ],
    }
    result = extract_weixin_multimedia(message)
    assert result["media_type"] == MULTIMEDIA_TYPE_IMAGE
    assert result["media_id"] == "img-001"
    assert result["file_url"] == "https://wx.example.com/img/001.jpg"
    assert result["format"] == "jpg"


def test_extract_multimedia_voice_message():
    """验证语音消息识别。"""
    message = {
        "from_user_id": "user-Y",
        "context_token": "ctx-Y",
        "item_list": [
            {
                "type": 3,
                "voice_item": {
                    "media_id": "voice-001",
                    "duration_ms": 3500,
                    "format": "amr",
                },
            }
        ],
    }
    result = extract_weixin_multimedia(message)
    assert result["media_type"] == MULTIMEDIA_TYPE_VOICE
    assert result["media_id"] == "voice-001"
    assert result["duration_ms"] == 3500
    assert result["format"] == "amr"


def test_extract_multimedia_file_message():
    """验证文件消息识别。"""
    message = {
        "from_user_id": "user-Z",
        "context_token": "ctx-Z",
        "item_list": [
            {
                "type": 5,
                "file_item": {
                    "media_id": "file-001",
                    "file_name": "report.pdf",
                    "file_size": 102400,
                    "format": "pdf",
                },
            }
        ],
    }
    result = extract_weixin_multimedia(message)
    assert result["media_type"] == MULTIMEDIA_TYPE_FILE
    assert result["media_id"] == "file-001"
    assert result["file_name"] == "report.pdf"
    assert result["file_size"] == 102400
    assert result["format"] == "pdf"


def test_extract_multimedia_video_message():
    """验证视频消息识别。"""
    message = {
        "from_user_id": "user-V",
        "context_token": "ctx-V",
        "item_list": [
            {
                "type": 4,
                "video_item": {
                    "media_id": "video-001",
                    "url": "https://wx.example.com/video/001.mp4",
                    "duration_ms": 10000,
                    "format": "mp4",
                },
            }
        ],
    }
    result = extract_weixin_multimedia(message)
    assert result["media_type"] == MULTIMEDIA_TYPE_VIDEO
    assert result["media_id"] == "video-001"
    assert result["file_url"] == "https://wx.example.com/video/001.mp4"
    assert result["duration_ms"] == 10000


def test_extract_multimedia_text_message_returns_empty():
    """验证纯文本消息不识别为多媒体。"""
    message = {
        "from_user_id": "user-T",
        "context_token": "ctx-T",
        "text": "你好",
    }
    result = extract_weixin_multimedia(message)
    assert result["media_type"] == ""


def test_extract_multimedia_top_level_message_type_field():
    """验证顶层 message_type 字段识别多媒体。"""
    message = {
        "from_user_id": "user-M",
        "context_token": "ctx-M",
        "message_type": "image",
        "media_id": "top-img-001",
        "file_url": "https://wx.example.com/top.jpg",
    }
    result = extract_weixin_multimedia(message)
    assert result["media_type"] == MULTIMEDIA_TYPE_IMAGE
    assert result["media_id"] == "top-img-001"
    assert result["file_url"] == "https://wx.example.com/top.jpg"


def test_extract_multimedia_invalid_input_returns_empty():
    """验证非字典输入返回空多媒体。"""
    assert extract_weixin_multimedia(None)["media_type"] == ""
    assert extract_weixin_multimedia("string")["media_type"] == ""


# ──────────────────────────────────────────────
#  build_multimedia_description 测试
# ──────────────────────────────────────────────

def test_build_multimedia_description_image():
    """验证图片描述生成。"""
    desc = build_multimedia_description({
        "media_type": MULTIMEDIA_TYPE_IMAGE,
        "file_url": "https://wx.example.com/img.jpg",
        "format": "jpg",
    })
    assert "[图片消息]" in desc
    assert "URL: https://wx.example.com/img.jpg" in desc
    assert "格式: jpg" in desc


def test_build_multimedia_description_voice_with_duration():
    """验证语音描述包含时长。"""
    desc = build_multimedia_description({
        "media_type": MULTIMEDIA_TYPE_VOICE,
        "duration_ms": 5000,
        "format": "amr",
    })
    assert "[语音消息]" in desc
    assert "时长: 5000 毫秒" in desc
    assert "格式: amr" in desc


def test_build_multimedia_description_file_with_size_and_name():
    """验证文件描述包含文件名和大小。"""
    desc = build_multimedia_description({
        "media_type": MULTIMEDIA_TYPE_FILE,
        "file_name": "doc.pdf",
        "file_size": 2048,
    })
    assert "[文件消息]" in desc
    assert "文件名: doc.pdf" in desc
    assert "大小: 2048 字节" in desc


def test_build_multimedia_description_empty_for_text():
    """验证无多媒体时返回空字符串。"""
    assert build_multimedia_description({"media_type": ""}) == ""


# ──────────────────────────────────────────────
#  normalize_inbound_message 测试
# ──────────────────────────────────────────────

def test_normalize_inbound_multimedia_message_is_replyable():
    """验证多媒体消息即使无文本也标记为 replyable。"""
    message = {
        "from_user_id": "user-M",
        "context_token": "ctx-M",
        "item_list": [
            {"type": 2, "image_item": {"media_id": "img-001", "url": "https://wx.example.com/img.jpg"}}
        ],
    }
    result = normalize_inbound_message(message)
    assert result["replyable"] is True
    assert result["skip_reason"] == ""
    assert result["multimedia"]["media_type"] == MULTIMEDIA_TYPE_IMAGE
    assert "[图片消息]" in result["multimedia_description"]


def test_normalize_inbound_text_message_remains_replyable():
    """验证纯文本消息保持原有 replyable 行为。"""
    message = {
        "from_user_id": "user-T",
        "context_token": "ctx-T",
        "text": "你好",
    }
    result = normalize_inbound_message(message)
    assert result["replyable"] is True
    assert result["multimedia"]["media_type"] == ""
    assert result["multimedia_description"] == ""


def test_normalize_inbound_message_missing_text_and_multimedia_is_not_replyable():
    """验证既无文本又无多媒体的消息不可回复。"""
    message = {
        "from_user_id": "user-N",
        "context_token": "ctx-N",
    }
    result = normalize_inbound_message(message)
    assert result["replyable"] is False
    assert result["skip_reason"] == "missing_text"


# ──────────────────────────────────────────────
#  多媒体消息查询 API 测试
# ──────────────────────────────────────────────

def _seed_multimedia_memory(session_id: str, content: str, role: str = "user") -> int:
    """插入一条 ShortTermMemory 记录并返回 ID。"""
    from datetime import datetime, timezone
    mem = ShortTermMemory(
        session_id=session_id,
        workspace_id="default",
        role=role,
        content=content,
        timestamp=datetime.now(timezone.utc),
    )
    db = TestingSessionLocal()
    try:
        db.add(mem)
        db.commit()
        db.refresh(mem)
        return mem.id
    finally:
        db.close()


def test_list_recent_multimedia_returns_only_multimedia_messages():
    """验证只返回包含多媒体标记的消息。"""
    _seed_multimedia_memory("weixin:auto:acc-1:user-A", "[图片消息] URL: https://wx.example.com/1.jpg")
    _seed_multimedia_memory("weixin:auto:acc-1:user-B", "普通文本消息")
    _seed_multimedia_memory("weixin:auto:acc-1:user-C", "[语音消息] 时长: 3000 毫秒")

    with _test_client() as client:
        response = client.get("/api/weixin/multimedia/recent")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    media_types = {item["media_type"] for item in data}
    assert media_types == {"image", "voice"}


def test_list_recent_multimedia_filter_by_media_type():
    """验证 media_type 过滤。"""
    _seed_multimedia_memory("weixin:auto:acc-1:user-A", "[图片消息] URL: https://wx.example.com/1.jpg")
    _seed_multimedia_memory("weixin:auto:acc-1:user-B", "[文件消息] 文件名: doc.pdf")

    with _test_client() as client:
        response = client.get("/api/weixin/multimedia/recent?media_type=image")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["media_type"] == "image"


def test_get_multimedia_detail_returns_full_content():
    """验证获取多媒体消息详情。"""
    mem_id = _seed_multimedia_memory(
        "weixin:auto:acc-1:user-A",
        "[图片消息] URL: https://wx.example.com/detail.jpg 格式: jpg",
    )
    message_id = f"weixin:auto:acc-1:user-A:{mem_id}"

    with _test_client() as client:
        response = client.get(f"/api/weixin/multimedia/{message_id}")
    assert response.status_code == 200
    data = response.json()
    assert "https://wx.example.com/detail.jpg" in data["content"]
    assert data["session_id"] == "weixin:auto:acc-1:user-A"


def test_get_multimedia_detail_invalid_id_format():
    """验证无效 ID 格式返回 400。"""
    with _test_client() as client:
        response = client.get("/api/weixin/multimedia/invalid-id")
    assert response.status_code == 400


def test_get_multimedia_detail_not_found():
    """验证不存在的消息返回 404。"""
    with _test_client() as client:
        response = client.get("/api/weixin/multimedia/weixin:auto:acc-1:user-A:99999")
    assert response.status_code == 404


# ──────────────────────────────────────────────
#  get_event_bus 单例测试
# ──────────────────────────────────────────────

def test_get_event_bus_returns_singleton():
    """验证 get_event_bus 返回全局单例。"""
    bus1 = get_event_bus()
    bus2 = get_event_bus()
    assert bus1 is bus2


# ──────────────────────────────────────────────
#  _parse_multimedia_metadata 辅助函数测试
# ──────────────────────────────────────────────

def test_parse_multimedia_metadata_image():
    """验证图片消息元数据解析。"""
    content = "[图片消息] URL: https://wx.example.com/img.jpg 格式: jpg"
    result = _parse_multimedia_metadata(content)
    assert result["file_url"] == "https://wx.example.com/img.jpg"
    assert result["media_format"] == "jpg"
    assert result["file_size"] == 0
    assert result["duration_ms"] == 0


def test_parse_multimedia_metadata_voice():
    """验证语音消息元数据解析。"""
    content = "[语音消息] 时长: 3500 毫秒 格式: amr"
    result = _parse_multimedia_metadata(content)
    assert result["duration_ms"] == 3500
    assert result["media_format"] == "amr"


def test_parse_multimedia_metadata_file():
    """验证文件消息元数据解析。"""
    content = "[文件消息] 文件名: report.pdf 大小: 102400 字节 格式: pdf"
    result = _parse_multimedia_metadata(content)
    assert result["file_name"] == "report.pdf"
    assert result["file_size"] == 102400
    assert result["media_format"] == "pdf"


def test_parse_multimedia_metadata_video():
    """验证视频消息元数据解析。"""
    content = "[视频消息] URL: https://wx.example.com/v.mp4 时长: 10000 毫秒 格式: mp4"
    result = _parse_multimedia_metadata(content)
    assert result["file_url"] == "https://wx.example.com/v.mp4"
    assert result["duration_ms"] == 10000
    assert result["media_format"] == "mp4"


def test_parse_multimedia_metadata_empty():
    """验证空内容返回全空字段。"""
    result = _parse_multimedia_metadata("")
    assert result["media_id"] == ""
    assert result["file_url"] == ""
    assert result["file_size"] == 0


def test_parse_multimedia_metadata_with_media_id():
    """验证包含 media_id 的内容解析。"""
    content = "[图片消息] media_id: img-123 URL: https://wx.example.com/img.jpg"
    result = _parse_multimedia_metadata(content)
    assert result["media_id"] == "img-123"


# ──────────────────────────────────────────────
#  _sanitize_upload_filename 辅助函数测试
# ──────────────────────────────────────────────

def test_sanitize_upload_filename_normal():
    """验证普通文件名保持不变。"""
    assert _sanitize_upload_filename("photo.jpg") == "photo.jpg"
    assert _sanitize_upload_filename("document.pdf") == "document.pdf"


def test_sanitize_upload_filename_path_traversal():
    """验证路径穿越攻击被防御。"""
    assert _sanitize_upload_filename("../../../etc/passwd") == "passwd"
    assert _sanitize_upload_filename("..\\..\\windows\\system32") == "system32"


def test_sanitize_upload_filename_empty():
    """验证空文件名返回默认值。"""
    assert _sanitize_upload_filename("") == "upload.bin"
    assert _sanitize_upload_filename(None) == "upload.bin"


def test_sanitize_upload_filename_special_chars():
    """验证特殊字符被替换。"""
    result = _sanitize_upload_filename("file name with spaces.txt")
    assert " " not in result
    assert result.endswith(".txt")


# ──────────────────────────────────────────────
#  WeixinSkillAdapter 多媒体方法测试
# ──────────────────────────────────────────────

def _build_test_runtime_config() -> WeixinRuntimeConfig:
    """构建测试用 WeixinRuntimeConfig。"""
    return WeixinRuntimeConfig(
        account_id="test-account",
        token="test-token-12345678",
        base_url="https://ilinkai.weixin.qq.com",
        bot_type="3",
        channel_version="1.0.2",
        timeout_seconds=15,
        user_id="wx-user",
        binding_status="bound",
    )


@pytest.mark.asyncio
async def test_download_media_decrypts_ilink_cdn_payload(monkeypatch):
    """验证 iLink CDN 多媒体下载会使用 AES-128-ECB 解密并移除 PKCS7 填充。"""
    plaintext = b"weixin voice payload"
    key = bytes.fromhex("00112233445566778899aabbccddeeff")
    padding_size = 16 - len(plaintext) % 16
    encryptor = Cipher(algorithms.AES(key), modes.ECB()).encryptor()
    ciphertext = encryptor.update(plaintext + bytes([padding_size]) * padding_size) + encryptor.finalize()

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_value, traceback):
            return False

        async def get(self, url):
            assert "encrypted_query_param=cdn%2Btoken" in url
            return type("Response", (), {"status_code": 200, "content": ciphertext})()

    monkeypatch.setattr("skills.weixin_skill_adapter.httpx.AsyncClient", lambda timeout: FakeClient())
    adapter = WeixinSkillAdapter(project_root="d:/tmp/openawa")

    result = await adapter.download_media("cdn+token", key.hex())

    assert result == plaintext


def test_parse_cdn_aes_key_accepts_base64_raw_key():
    """验证 iLink Base64 原始 AES 密钥可以解析。"""
    encoded_key = "ABEiM0RVZneImaq7zN3u/w=="
    assert WeixinSkillAdapter._parse_cdn_aes_key(encoded_key) == bytes.fromhex("00112233445566778899aabbccddeeff")


def test_extract_weixin_media_credentials_supports_nested_message():
    """验证 iLink 嵌套 msg 结构中的媒体凭据可以被安全提取。"""
    credentials = extract_weixin_media_credentials({
        "msg": {
            "item_list": [{
                "type": 3,
                "voice_item": {"media": {"encrypt_query_param": "download-param", "aes_key": "base64-key"}},
            }],
        },
    })
    assert credentials == {"encrypted_query_param": "download-param", "aes_key": "base64-key"}


def test_download_multimedia_asset_returns_content_without_secrets(monkeypatch):
    """验证资产下载只返回媒体内容，不泄露 CDN 凭据。"""
    db = TestingSessionLocal()
    try:
        db.add(WeixinMediaAsset(
            user_id="user-1",
            message_id="asset-message-1",
            media_type="voice",
            media_format="amr",
            encrypted_query_param=encrypt_secret_value("download-param"),
            encrypted_aes_key=encrypt_secret_value("aes-key"),
        ))
        db.commit()
    finally:
        db.close()

    async def fake_download(self, encrypted_query_param, aes_key, **kwargs):
        assert encrypted_query_param == "download-param"
        assert aes_key == "aes-key"
        return b"voice-content"

    monkeypatch.setattr(WeixinSkillAdapter, "download_media", fake_download)
    with _test_client() as client:
        response = client.get("/api/weixin/multimedia/assets/asset-message-1/download")
    assert response.status_code == 200
    assert response.content == b"voice-content"
    assert "download-param" not in response.text
    assert "aes-key" not in response.text


@pytest.mark.asyncio
async def test_upload_media_success(monkeypatch):
    """验证 upload_media 通过 iLink 参数和 CDN 加密上传返回媒体描述。"""
    adapter = WeixinSkillAdapter(project_root="d:/tmp/openawa")

    # 创建临时文件模拟上传
    with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
        tmp.write(b"fake-image-data")
        tmp_path = tmp.name

    try:
        captured = {}

        async def fake_api_post(self, config, endpoint, body, timeout_seconds=None):
            captured["endpoint"] = endpoint
            captured["body"] = body
            return {"upload_param": "upload-param-001"}

        class FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc_value, traceback):
                return False

            async def post(self, url, content, headers):
                captured["url"] = url
                captured["content"] = content
                return type("Response", (), {"status_code": 200, "headers": {"x-encrypted-param": "download-param-001"}})()

        monkeypatch.setattr(WeixinSkillAdapter, "_api_post", fake_api_post)
        monkeypatch.setattr("skills.weixin_skill_adapter.httpx.AsyncClient", lambda timeout: FakeClient())

        config = _build_test_runtime_config()
        result = await adapter.upload_media(config, "image", tmp_path, "target-user")
        assert result["media_id"] == "download-param-001"
        assert result["media_type"] == "image"
        assert result["media"]["encrypt_query_param"] == "download-param-001"
        assert result["media"]["encrypt_type"] == 1
        assert captured["endpoint"] == "ilink/bot/getuploadurl"
        assert captured["body"]["to_user_id"] == "target-user"
        assert "encrypted_query_param=upload-param-001" in captured["url"]
        assert len(captured["content"]) % 16 == 0
    finally:
        os.remove(tmp_path)


@pytest.mark.asyncio
async def test_upload_media_invalid_media_type():
    """验证无效 media_type 抛出异常。"""
    adapter = WeixinSkillAdapter(project_root="d:/tmp/openawa")
    config = _build_test_runtime_config()
    with pytest.raises(WeixinAdapterError) as exc_info:
        await adapter.upload_media(config, "invalid_type", "/tmp/fake.jpg", "target-user")
    assert exc_info.value.code == "WEIXIN_INVALID_MEDIA_TYPE"


@pytest.mark.asyncio
async def test_upload_media_file_not_found():
    """验证文件不存在时抛出异常。"""
    adapter = WeixinSkillAdapter(project_root="d:/tmp/openawa")
    config = _build_test_runtime_config()
    with pytest.raises(WeixinAdapterError) as exc_info:
        await adapter.upload_media(config, "image", "/nonexistent/path/file.jpg", "target-user")
    assert exc_info.value.code == "WEIXIN_MEDIA_FILE_NOT_FOUND"


@pytest.mark.asyncio
async def test_upload_media_missing_upload_parameter(monkeypatch):
    """验证 iLink 未返回 CDN 上传参数时抛出异常。"""
    adapter = WeixinSkillAdapter(project_root="d:/tmp/openawa")

    with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
        tmp.write(b"fake")
        tmp_path = tmp.name

    try:
        async def fake_api_post(self, config, endpoint, body, timeout_seconds=None):
            return {}

        monkeypatch.setattr(WeixinSkillAdapter, "_api_post", fake_api_post)
        config = _build_test_runtime_config()
        with pytest.raises(WeixinAdapterError) as exc_info:
            await adapter.upload_media(config, "image", tmp_path, "target-user")
        assert exc_info.value.code == "WEIXIN_UPLOAD_URL_MISSING"
    finally:
        os.remove(tmp_path)


@pytest.mark.asyncio
async def test_upload_media_cdn_response_missing_download_parameter(monkeypatch):
    """验证 CDN 响应缺少下载参数时抛出异常。"""
    adapter = WeixinSkillAdapter(project_root="d:/tmp/openawa")

    with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
        tmp.write(b"fake")
        tmp_path = tmp.name

    try:
        async def fake_api_post(self, config, endpoint, body, timeout_seconds=None):
            return {"upload_param": "upload-param"}

        class FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc_value, traceback):
                return False

            async def post(self, url, content, headers):
                return type("Response", (), {"status_code": 200, "headers": {}})()

        monkeypatch.setattr(WeixinSkillAdapter, "_api_post", fake_api_post)
        monkeypatch.setattr("skills.weixin_skill_adapter.httpx.AsyncClient", lambda timeout: FakeClient())
        config = _build_test_runtime_config()
        with pytest.raises(WeixinAdapterError) as exc_info:
            await adapter.upload_media(config, "image", tmp_path, "target-user")
        assert exc_info.value.code == "WEIXIN_CDN_UPLOAD_RESPONSE_INVALID"
    finally:
        os.remove(tmp_path)


@pytest.mark.asyncio
async def test_send_image_message_success(monkeypatch):
    """验证 send_image_message 成功构建请求并调用 API。"""
    adapter = WeixinSkillAdapter(project_root="d:/tmp/openawa")
    captured = {}

    async def fake_api_post(self, config, endpoint, body, timeout_seconds=None):
        captured["endpoint"] = endpoint
        captured["body"] = body
        return {"errcode": 0, "errmsg": "ok"}

    monkeypatch.setattr(WeixinSkillAdapter, "_api_post", fake_api_post)
    monkeypatch.setattr(WeixinSkillAdapter, "_get_context_token", lambda self, account_id, user_id: "ctx-token-001")

    config = _build_test_runtime_config()
    result = await adapter.send_image_message(config, "target-user", "img-media-001")
    assert result["request"]["to_user_id"] == "target-user"
    assert result["request"]["media_id"] == "img-media-001"
    assert result["request"]["item_type"] == 2
    assert result["request"]["item_key"] == "image_item"
    assert captured["endpoint"] == "ilink/bot/sendmessage"
    item = captured["body"]["msg"]["item_list"][0]
    assert item["type"] == 2
    assert item["image_item"]["media_id"] == "img-media-001"


@pytest.mark.asyncio
async def test_send_voice_message_success(monkeypatch):
    """验证 send_voice_message 使用 voice_item 和 type=3。"""
    adapter = WeixinSkillAdapter(project_root="d:/tmp/openawa")
    captured = {}

    async def fake_api_post(self, config, endpoint, body, timeout_seconds=None):
        captured["body"] = body
        return {"errcode": 0}

    monkeypatch.setattr(WeixinSkillAdapter, "_api_post", fake_api_post)
    monkeypatch.setattr(WeixinSkillAdapter, "_get_context_token", lambda self, account_id, user_id: "ctx-token")

    config = _build_test_runtime_config()
    await adapter.send_voice_message(config, "user-1", "voice-001")
    item = captured["body"]["msg"]["item_list"][0]
    assert item["type"] == 3
    assert item["voice_item"]["media_id"] == "voice-001"


@pytest.mark.asyncio
async def test_send_video_message_success(monkeypatch):
    """验证 send_video_message 使用 video_item 和 type=4。"""
    adapter = WeixinSkillAdapter(project_root="d:/tmp/openawa")
    captured = {}

    async def fake_api_post(self, config, endpoint, body, timeout_seconds=None):
        captured["body"] = body
        return {"errcode": 0}

    monkeypatch.setattr(WeixinSkillAdapter, "_api_post", fake_api_post)
    monkeypatch.setattr(WeixinSkillAdapter, "_get_context_token", lambda self, account_id, user_id: "ctx-token")

    config = _build_test_runtime_config()
    await adapter.send_video_message(config, "user-1", "video-001")
    item = captured["body"]["msg"]["item_list"][0]
    assert item["type"] == 4
    assert item["video_item"]["media_id"] == "video-001"


@pytest.mark.asyncio
async def test_send_file_message_success(monkeypatch):
    """验证 send_file_message 使用 file_item 和 type=5。"""
    adapter = WeixinSkillAdapter(project_root="d:/tmp/openawa")
    captured = {}

    async def fake_api_post(self, config, endpoint, body, timeout_seconds=None):
        captured["body"] = body
        return {"errcode": 0}

    monkeypatch.setattr(WeixinSkillAdapter, "_api_post", fake_api_post)
    monkeypatch.setattr(WeixinSkillAdapter, "_get_context_token", lambda self, account_id, user_id: "ctx-token")

    config = _build_test_runtime_config()
    await adapter.send_file_message(config, "user-1", "file-001")
    item = captured["body"]["msg"]["item_list"][0]
    assert item["type"] == 5
    assert item["file_item"]["media_id"] == "file-001"


@pytest.mark.asyncio
async def test_send_media_message_missing_user_id():
    """验证缺少 user_id 时抛出异常。"""
    adapter = WeixinSkillAdapter(project_root="d:/tmp/openawa")
    config = _build_test_runtime_config()
    with pytest.raises(WeixinAdapterError) as exc_info:
        await adapter.send_image_message(config, "", "media-001")
    assert exc_info.value.code == "WEIXIN_INPUT_MISSING_FIELDS"
    assert "to_user_id" in exc_info.value.details["missing_fields"]


@pytest.mark.asyncio
async def test_send_media_message_missing_media_id():
    """验证缺少 media_id 时抛出异常。"""
    adapter = WeixinSkillAdapter(project_root="d:/tmp/openawa")
    config = _build_test_runtime_config()
    with pytest.raises(WeixinAdapterError) as exc_info:
        await adapter.send_image_message(config, "user-1", "")
    assert exc_info.value.code == "WEIXIN_INPUT_MISSING_FIELDS"
    assert "media_id" in exc_info.value.details["missing_fields"]


@pytest.mark.asyncio
async def test_send_media_message_missing_context_token(monkeypatch):
    """验证缺少 context_token 时抛出异常。"""
    adapter = WeixinSkillAdapter(project_root="d:/tmp/openawa")
    monkeypatch.setattr(WeixinSkillAdapter, "_get_context_token", lambda self, account_id, user_id: "")
    config = _build_test_runtime_config()
    with pytest.raises(WeixinAdapterError) as exc_info:
        await adapter.send_image_message(config, "user-1", "media-001")
    assert exc_info.value.code == "WEIXIN_INPUT_MISSING_FIELDS"
    assert "context_token" in exc_info.value.details["missing_fields"]


# ──────────────────────────────────────────────
#  多媒体发送 API 路由测试
# ──────────────────────────────────────────────

def _seed_binding(user_id: str = "user-1"):
    """在测试数据库中插入微信绑定记录。"""
    db = TestingSessionLocal()
    try:
        binding = WeixinBinding(
            user_id=user_id,
            weixin_account_id="test-account",
            token=encrypt_secret_value("test-token-12345678"),
            base_url="https://ilinkai.weixin.qq.com",
            bot_type="3",
            channel_version="1.0.2",
            binding_status="bound",
            weixin_user_id="wx-user",
        )
        db.add(binding)
        db.commit()
    finally:
        db.close()


def test_send_multimedia_success(monkeypatch):
    """验证多媒体消息发送 API 成功路径。"""
    _seed_binding("user-1")

    async def fake_upload_media(self, config, media_type, file_path, to_user_id):
        return {"media_type": media_type, "media_id": "media-001", "media": {"encrypt_query_param": "media-001", "aes_key": "key"}}

    async def fake_send_image(self, config, user_id, media):
        return {"request": {"to_user_id": user_id, "media_id": media["media_id"]}, "response": {"errcode": 0}}

    monkeypatch.setattr(WeixinSkillAdapter, "upload_media", fake_upload_media)
    monkeypatch.setattr(WeixinSkillAdapter, "send_image_message", fake_send_image)

    with _test_client() as client:
        response = client.post(
            "/api/weixin/multimedia/send",
            data={"to_user": "target-user", "media_type": "image"},
            files={"file": ("test.jpg", io.BytesIO(b"fake-image-data"), "image/jpeg")},
        )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["media_type"] == "image"
    assert data["media_id"] == "media-001"
    assert data["to_user"] == "target-user"
    assert data["file_name"] == "test.jpg"
    assert data["file_size"] > 0


def test_send_multimedia_invalid_mime_type():
    """验证不支持的 MIME 类型返回 400。"""
    _seed_binding("user-1")
    with _test_client() as client:
        response = client.post(
            "/api/weixin/multimedia/send",
            data={"to_user": "target-user", "media_type": "image"},
            files={"file": ("test.txt", io.BytesIO(b"text"), "text/plain")},
        )
    assert response.status_code == 400
    assert "不支持" in response.json()["error"]["message"]


def test_send_multimedia_media_type_mismatch():
    """验证 media_type 与 MIME 类型不匹配返回 400。"""
    _seed_binding("user-1")
    with _test_client() as client:
        response = client.post(
            "/api/weixin/multimedia/send",
            data={"to_user": "target-user", "media_type": "voice"},
            files={"file": ("test.jpg", io.BytesIO(b"fake"), "image/jpeg")},
        )
    assert response.status_code == 400
    assert "不匹配" in response.json()["error"]["message"]


def test_send_multimedia_file_too_large():
    """验证文件超过 50MB 限制返回 413。"""
    _seed_binding("user-1")
    # 构造超过 50MB 的假数据
    large_data = b"\x00" * (50 * 1024 * 1024 + 1)
    with _test_client() as client:
        response = client.post(
            "/api/weixin/multimedia/send",
            data={"to_user": "target-user", "media_type": "image"},
            files={"file": ("large.jpg", io.BytesIO(large_data), "image/jpeg")},
        )
    assert response.status_code == 413


def test_send_multimedia_empty_file():
    """验证空文件返回 400。"""
    _seed_binding("user-1")
    with _test_client() as client:
        response = client.post(
            "/api/weixin/multimedia/send",
            data={"to_user": "target-user", "media_type": "image"},
            files={"file": ("empty.jpg", io.BytesIO(b""), "image/jpeg")},
        )
    assert response.status_code == 400
    assert "为空" in response.json()["error"]["message"]


def test_send_multimedia_no_binding():
    """验证无微信绑定时返回 400。"""
    with _test_client() as client:
        response = client.post(
            "/api/weixin/multimedia/send",
            data={"to_user": "target-user", "media_type": "image"},
            files={"file": ("test.jpg", io.BytesIO(b"fake"), "image/jpeg")},
        )
    assert response.status_code == 400
    assert "绑定" in response.json()["error"]["message"]


def test_send_multimedia_upload_failure(monkeypatch):
    """验证上传素材失败时返回 502。"""
    _seed_binding("user-1")

    async def fake_upload_media(self, config, media_type, file_path, to_user_id):
        raise WeixinAdapterError(code="WEIXIN_UPLOAD_FAILED", message="上传失败")

    monkeypatch.setattr(WeixinSkillAdapter, "upload_media", fake_upload_media)

    with _test_client() as client:
        response = client.post(
            "/api/weixin/multimedia/send",
            data={"to_user": "target-user", "media_type": "image"},
            files={"file": ("test.jpg", io.BytesIO(b"fake"), "image/jpeg")},
        )
    assert response.status_code == 502
    assert "上传素材失败" in response.json()["error"]["message"]


def test_list_recent_multimedia_extracts_metadata():
    """验证 list_recent_multimedia 从内容中提取元数据字段。"""
    _seed_multimedia_memory(
        "weixin:auto:acc-1:user-A",
        "[文件消息] 文件名: report.pdf 大小: 204800 字节 格式: pdf",
    )
    _seed_multimedia_memory(
        "weixin:auto:acc-1:user-B",
        "[语音消息] 时长: 5000 毫秒 格式: amr",
    )

    with _test_client() as client:
        response = client.get("/api/weixin/multimedia/recent")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2

    file_msg = next(m for m in data if m["media_type"] == "file")
    assert file_msg["file_name"] == "report.pdf"
    assert file_msg["file_size"] == 204800
    assert file_msg["media_format"] == "pdf"

    voice_msg = next(m for m in data if m["media_type"] == "voice")
    assert voice_msg["duration_ms"] == 5000
    assert voice_msg["media_format"] == "amr"


def test_list_recent_multimedia_image_with_url():
    """验证图片消息 URL 元数据提取。"""
    _seed_multimedia_memory(
        "weixin:auto:acc-1:user-A",
        "[图片消息] URL: https://wx.example.com/photo.jpg 格式: jpg",
    )

    with _test_client() as client:
        response = client.get("/api/weixin/multimedia/recent?media_type=image")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["file_url"] == "https://wx.example.com/photo.jpg"
    assert data[0]["media_format"] == "jpg"
