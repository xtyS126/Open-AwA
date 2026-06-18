"""
微信多媒体消息处理与 WebSocket 事件总线测试。

覆盖范围：
1. WeixinEventBus 订阅/发布/取消订阅/队列满丢弃
2. extract_weixin_multimedia 识别图片/语音/文件/视频
3. build_multimedia_description 生成可读描述
4. normalize_inbound_message 多媒体消息标记为 replyable
5. 多媒体消息查询 API
"""

import asyncio
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.dependencies import get_current_user, get_db
from api.routes import weixin as weixin_routes
from api.services.weixin_auto_reply import (
    WeixinEventBus,
    extract_weixin_multimedia,
    build_multimedia_description,
    normalize_inbound_message,
    get_event_bus,
    MULTIMEDIA_TYPE_IMAGE,
    MULTIMEDIA_TYPE_VOICE,
    MULTIMEDIA_TYPE_FILE,
    MULTIMEDIA_TYPE_VIDEO,
)
from config.security import encrypt_secret_value
from db.models import Base, ShortTermMemory, WeixinBinding
from main import app


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
        db.query(ShortTermMemory).delete()
        db.commit()
    finally:
        db.close()
    yield
    db = TestingSessionLocal()
    try:
        db.query(WeixinBinding).delete()
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
