"""
测试 list_recent_multimedia 异步化后行为正确。

覆盖范围：
1. 异步路由通过 TestClient 正常返回多媒体消息
2. limit 参数被正确尊重（不超过 limit 条返回）
3. limit*2 拉取窗口生效（验证 SQL 拉取条数从 limit*10 改为 limit*2）
4. 抽取的同步函数 _list_recent_multimedia_sync 元数据解析正确
5. 同步函数可通过 asyncio.to_thread 在线程池中执行
6. 四种多媒体类型（image/voice/file/video）都能被识别和解析
"""

import asyncio
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.dependencies import get_current_user, get_db
from api.routes.weixin import (
    WeixinMultimediaMessageResponse,
    _list_recent_multimedia_sync,
)
from db.models import Base, ShortTermMemory
from main import app


# 测试专用内存数据库，StaticPool 保证同一连接共享给多个 session
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
        db.query(ShortTermMemory).delete()
        db.commit()
    finally:
        db.close()
    yield
    db = TestingSessionLocal()
    try:
        db.query(ShortTermMemory).delete()
        db.commit()
    finally:
        db.close()


def _seed_memory(session_id: str, content: str, timestamp: datetime) -> int:
    """插入一条 ShortTermMemory 记录并返回 ID。"""
    mem = ShortTermMemory(
        session_id=session_id,
        workspace_id="default",
        role="user",
        content=content,
        timestamp=timestamp,
    )
    db = TestingSessionLocal()
    try:
        db.add(mem)
        db.commit()
        db.refresh(mem)
        return mem.id
    finally:
        db.close()


# ──────────────────────────────────────────────
#  异步路由执行测试
# ──────────────────────────────────────────────


def test_list_recent_multimedia_async_via_test_client():
    """验证异步路由通过 TestClient 正常返回多媒体消息。"""
    base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    _seed_memory(
        "weixin:auto:acc-1:user-A",
        "[图片消息] URL: https://wx.example.com/1.jpg 格式: jpg",
        base_time + timedelta(seconds=2),
    )
    _seed_memory(
        "weixin:auto:acc-1:user-B",
        "普通文本消息",
        base_time + timedelta(seconds=1),
    )
    _seed_memory(
        "weixin:auto:acc-1:user-C",
        "[语音消息] 时长: 3000 毫秒 格式: amr",
        base_time,
    )

    with _test_client() as client:
        response = client.get("/api/weixin/multimedia/recent")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    media_types = {item["media_type"] for item in data}
    assert media_types == {"image", "voice"}


def test_list_recent_multimedia_respects_limit_parameter():
    """验证 limit 参数被正确尊重（不超过 limit 条返回）。"""
    base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    # 插入 10 条多媒体消息，时间从最旧到最新
    for i in range(10):
        _seed_memory(
            f"weixin:auto:acc-1:user-{i}",
            f"[图片消息] URL: https://wx.example.com/{i}.jpg 格式: jpg",
            base_time + timedelta(seconds=i),
        )

    with _test_client() as client:
        response = client.get("/api/weixin/multimedia/recent?limit=5")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 5
    # 应返回最新的 5 条（i=5..9）
    urls = {item["file_url"] for item in data}
    expected_urls = {f"https://wx.example.com/{i}.jpg" for i in range(5, 10)}
    assert urls == expected_urls


def test_list_recent_multimedia_limit_2_truncation():
    """
    验证 SQL 拉取窗口为 limit*2 而非 limit*10。

    场景：插入 21 条文本消息（最新）+ 1 条多媒体消息（最旧），
    调用 limit=10。limit*2=20，SQL 只拉取 20 条最新的（全文本），
    多媒体消息位于第 21 条不会被拉取，因此返回空列表。
    若改回 limit*10=100，则多媒体会被拉取并返回 1 条。
    """
    base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    # 21 条文本消息，时间从最新到最旧
    for i in range(21):
        _seed_memory(
            f"weixin:auto:acc-1:text-{i}",
            f"普通文本消息 {i}",
            base_time + timedelta(seconds=21 - i),
        )
    # 1 条多媒体消息，时间最旧
    _seed_memory(
        "weixin:auto:acc-1:multi",
        "[图片消息] URL: https://wx.example.com/hidden.jpg 格式: jpg",
        base_time,
    )

    with _test_client() as client:
        response = client.get("/api/weixin/multimedia/recent?limit=10")

    assert response.status_code == 200
    data = response.json()
    # limit*2=20 条拉取窗口内全是文本，多媒体被截断
    assert len(data) == 0


def test_list_recent_multimedia_filter_by_media_type_async():
    """验证异步路径下 media_type 过滤仍然生效。"""
    base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    _seed_memory(
        "weixin:auto:acc-1:user-A",
        "[图片消息] URL: https://wx.example.com/1.jpg 格式: jpg",
        base_time + timedelta(seconds=1),
    )
    _seed_memory(
        "weixin:auto:acc-1:user-B",
        "[文件消息] 文件名: doc.pdf",
        base_time,
    )

    with _test_client() as client:
        response = client.get("/api/weixin/multimedia/recent?media_type=image")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["media_type"] == "image"


# ──────────────────────────────────────────────
#  抽取的同步函数直接测试
# ──────────────────────────────────────────────


def test_sync_function_returns_correct_metadata():
    """验证抽取的 _list_recent_multimedia_sync 正确解析元数据。"""
    base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    _seed_memory(
        "weixin:auto:acc-1:user-A",
        "[文件消息] 文件名: report.pdf 大小: 204800 字节 格式: pdf",
        base_time + timedelta(seconds=1),
    )
    _seed_memory(
        "weixin:auto:acc-1:user-B",
        "[语音消息] 时长: 5000 毫秒 格式: amr",
        base_time,
    )

    db = TestingSessionLocal()
    try:
        results = _list_recent_multimedia_sync(db, "user-1", 20, None)
    finally:
        db.close()

    assert len(results) == 2
    file_msg = next(m for m in results if m.media_type == "file")
    assert file_msg.file_name == "report.pdf"
    assert file_msg.file_size == 204800
    assert file_msg.media_format == "pdf"

    voice_msg = next(m for m in results if m.media_type == "voice")
    assert voice_msg.duration_ms == 5000
    assert voice_msg.media_format == "amr"


def test_sync_function_filter_by_media_type():
    """验证 _list_recent_multimedia_sync 的 media_type 过滤。"""
    base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    _seed_memory(
        "weixin:auto:acc-1:user-A",
        "[图片消息] URL: https://wx.example.com/1.jpg 格式: jpg",
        base_time + timedelta(seconds=1),
    )
    _seed_memory(
        "weixin:auto:acc-1:user-B",
        "[文件消息] 文件名: doc.pdf",
        base_time,
    )

    db = TestingSessionLocal()
    try:
        results = _list_recent_multimedia_sync(db, "user-1", 20, "image")
    finally:
        db.close()

    assert len(results) == 1
    assert results[0].media_type == "image"
    assert results[0].file_url == "https://wx.example.com/1.jpg"


def test_sync_function_returns_empty_for_no_multimedia():
    """验证无非多媒体消息时返回空列表。"""
    base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    _seed_memory(
        "weixin:auto:acc-1:user-A",
        "纯文本消息",
        base_time,
    )

    db = TestingSessionLocal()
    try:
        results = _list_recent_multimedia_sync(db, "user-1", 20, None)
    finally:
        db.close()

    assert results == []


def test_sync_function_extracts_all_media_types():
    """验证四种多媒体类型（image/voice/file/video）都能被识别和解析。"""
    base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    _seed_memory(
        "weixin:auto:acc-1:img",
        "[图片消息] URL: https://wx.example.com/img.jpg 格式: jpg",
        base_time + timedelta(seconds=4),
    )
    _seed_memory(
        "weixin:auto:acc-1:voice",
        "[语音消息] 时长: 3000 毫秒 格式: amr",
        base_time + timedelta(seconds=3),
    )
    _seed_memory(
        "weixin:auto:acc-1:file",
        "[文件消息] 文件名: doc.pdf 大小: 1024 字节",
        base_time + timedelta(seconds=2),
    )
    _seed_memory(
        "weixin:auto:acc-1:video",
        "[视频消息] URL: https://wx.example.com/v.mp4 时长: 10000 毫秒 格式: mp4",
        base_time + timedelta(seconds=1),
    )

    db = TestingSessionLocal()
    try:
        results = _list_recent_multimedia_sync(db, "user-1", 20, None)
    finally:
        db.close()

    assert len(results) == 4
    media_types = {m.media_type for m in results}
    assert media_types == {"image", "voice", "file", "video"}


def test_sync_function_can_be_called_via_to_thread():
    """验证同步函数可通过 asyncio.to_thread 在线程池中执行。"""
    base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    _seed_memory(
        "weixin:auto:acc-1:user-A",
        "[图片消息] URL: https://wx.example.com/1.jpg 格式: jpg",
        base_time,
    )

    db = TestingSessionLocal()
    try:
        results = asyncio.run(
            asyncio.to_thread(_list_recent_multimedia_sync, db, "user-1", 20, None)
        )
    finally:
        db.close()

    assert len(results) == 1
    assert results[0].media_type == "image"
    assert isinstance(results[0], WeixinMultimediaMessageResponse)


def test_sync_function_limit_caps_result_count():
    """验证同步函数在结果数达到 limit 时停止收集。"""
    base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    # 插入 8 条多媒体消息
    for i in range(8):
        _seed_memory(
            f"weixin:auto:acc-1:user-{i}",
            f"[图片消息] URL: https://wx.example.com/{i}.jpg 格式: jpg",
            base_time + timedelta(seconds=i),
        )

    db = TestingSessionLocal()
    try:
        results = _list_recent_multimedia_sync(db, "user-1", 3, None)
    finally:
        db.close()

    # 即使有 8 条多媒体，limit=3 只返回 3 条
    assert len(results) == 3
