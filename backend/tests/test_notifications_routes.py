# -*- coding: utf-8 -*-
"""
通知 HTTP API 路由单元测试。

覆盖：
1. POST /api/notifications 发送通知：成功/缺 title/非法 type
2. GET /api/notifications 列出通知：基本列表/limit 限制
3. GET /api/notifications/stream SSE：Content-Type/接收推送/跨用户隔离/断开清理
4. 环形缓冲区：超过 100 条后旧通知被丢弃
5. 未认证访问返回 401

非流式端点用 fastapi.testclient.TestClient；SSE 流式测试直接调用端点函数
（stream_notifications / create_notification），避免 httpx ASGITransport 无法
正确取消异步生成器导致测试挂起，且所有调用在同一事件循环中执行。
"""

from __future__ import annotations

import asyncio
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

import pytest
from fastapi import FastAPI, HTTPException, status
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.dependencies import get_current_user
from api.routes.notifications import (
    _notification_subscribers,
    _notifications_store,
    router as notifications_router,
)


# ==================== 测试用户与依赖覆盖 ====================


class _DummyUser:
    """测试用 DummyUser，仅暴露 id/username/role 三个字段。"""

    def __init__(self, user_id: str, username: str) -> None:
        self.id = user_id
        self.username = username
        self.role = "user"


_USER_A = _DummyUser("user-a", "alice")
_USER_B = _DummyUser("user-b", "bob")


def _override_user(user: _DummyUser):
    """生成 get_current_user 的依赖覆盖函数。"""

    def _override() -> _DummyUser:
        return user

    return _override


def _deny_user():
    """模拟未认证：依赖函数抛 401。"""

    def _raise() -> None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    return _raise


# ==================== 公共 fixture ====================


@pytest.fixture(autouse=True)
def _clear_global():
    """每个测试前清空全局存储，避免测试间状态污染。"""
    _notifications_store.clear()
    _notification_subscribers.clear()
    yield
    _notifications_store.clear()
    _notification_subscribers.clear()


@contextmanager
def _sync_client(user: Optional[_DummyUser] = _USER_A):
    """构造同步 TestClient。

    用于非流式端点（POST /、GET /）的测试。
    """
    app = FastAPI()
    app.include_router(notifications_router)
    if user is not None:
        app.dependency_overrides[get_current_user] = _override_user(user)
    else:
        app.dependency_overrides[get_current_user] = _deny_user()
    with TestClient(app) as client:
        yield client


def _build_async_app(user: _DummyUser) -> FastAPI:
    """构造挂载 notifications_router 的 FastAPI 应用（保留以备扩展使用）。"""
    app = FastAPI()
    app.include_router(notifications_router)
    app.dependency_overrides[get_current_user] = _override_user(user)
    return app


# ==================== POST / 测试 ====================


class TestCreateNotification:
    """POST /api/notifications 发送通知。"""

    def test_creates_notification_returns_ok_and_id(self) -> None:
        """成功发送通知应返回 ok=True 和非空 id。"""
        with _sync_client(_USER_A) as client:
            response = client.post(
                "/api/notifications",
                json={"title": "Hello", "body": "World", "notification_type": "info"},
            )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["ok"] is True
        assert isinstance(body["id"], str)
        assert len(body["id"]) > 0

    def test_missing_title_returns_422(self) -> None:
        """缺少 title 字段应返回 422。"""
        with _sync_client(_USER_A) as client:
            response = client.post(
                "/api/notifications",
                json={"body": "no title"},
            )

        assert response.status_code == 422, response.text

    def test_empty_title_returns_422(self) -> None:
        """title 为空字符串应返回 422（min_length=1）。"""
        with _sync_client(_USER_A) as client:
            response = client.post(
                "/api/notifications",
                json={"title": ""},
            )

        assert response.status_code == 422, response.text

    def test_invalid_notification_type_returns_422(self) -> None:
        """非法 notification_type 应返回 422。"""
        with _sync_client(_USER_A) as client:
            response = client.post(
                "/api/notifications",
                json={"title": "Test", "notification_type": "critical"},
            )

        assert response.status_code == 422, response.text
        assert "info" in response.text or "warning" in response.text

    def test_default_notification_type_is_info(self) -> None:
        """未指定 notification_type 时默认为 info。"""
        with _sync_client(_USER_A) as client:
            response = client.post(
                "/api/notifications",
                json={"title": "Default type"},
            )
            assert response.status_code == 200
            # 通过 GET 验证存储的类型
            list_resp = client.get("/api/notifications")

        assert list_resp.status_code == 200
        notifs = list_resp.json()["notifications"]
        assert len(notifs) == 1
        assert notifs[0]["notification_type"] == "info"


# ==================== GET / 测试 ====================


class TestListNotifications:
    """GET /api/notifications 列出通知。"""

    def test_lists_recent_notifications(self) -> None:
        """先 POST 几条再 GET，应返回最近通知（最新在前）。"""
        with _sync_client(_USER_A) as client:
            client.post("/api/notifications", json={"title": "First"})
            client.post("/api/notifications", json={"title": "Second"})
            client.post("/api/notifications", json={"title": "Third"})

            response = client.get("/api/notifications")

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["count"] == 3
        assert body["total"] == 3
        titles = [n["title"] for n in body["notifications"]]
        # 最新在前
        assert titles == ["Third", "Second", "First"]

    def test_limit_parameter_restricts_count(self) -> None:
        """limit 参数应限制返回数量。"""
        with _sync_client(_USER_A) as client:
            for i in range(5):
                client.post("/api/notifications", json={"title": f"Msg-{i}"})

            response = client.get("/api/notifications", params={"limit": 2})

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["count"] == 2
        # total 仍是全部存储数
        assert body["total"] == 5
        titles = [n["title"] for n in body["notifications"]]
        # 最新 2 条
        assert titles == ["Msg-4", "Msg-3"]

    def test_limit_exceeds_total_returns_all(self) -> None:
        """limit 大于存储数时应返回全部。"""
        with _sync_client(_USER_A) as client:
            client.post("/api/notifications", json={"title": "Only one"})
            response = client.get("/api/notifications", params={"limit": 100})

        assert response.status_code == 200
        assert response.json()["count"] == 1

    def test_empty_store_returns_empty_list(self) -> None:
        """无通知时应返回空列表。"""
        with _sync_client(_USER_A) as client:
            response = client.get("/api/notifications")

        assert response.status_code == 200
        body = response.json()
        assert body["count"] == 0
        assert body["total"] == 0
        assert body["notifications"] == []

    def test_limit_below_minimum_returns_422(self) -> None:
        """limit < 1 应返回 422。"""
        with _sync_client(_USER_A) as client:
            response = client.get("/api/notifications", params={"limit": 0})

        assert response.status_code == 422

    def test_limit_above_maximum_returns_422(self) -> None:
        """limit > 100 应返回 422。"""
        with _sync_client(_USER_A) as client:
            response = client.get("/api/notifications", params={"limit": 101})

        assert response.status_code == 422


# ==================== 未认证测试 ====================


class TestAuth:
    """认证相关测试。"""

    def test_unauthenticated_post_returns_401(self) -> None:
        """未认证 POST 应返回 401。"""
        with _sync_client(user=None) as client:
            response = client.post(
                "/api/notifications",
                json={"title": "Should fail"},
            )

        assert response.status_code == 401, response.text

    def test_unauthenticated_get_returns_401(self) -> None:
        """未认证 GET 应返回 401。"""
        with _sync_client(user=None) as client:
            response = client.get("/api/notifications")

        assert response.status_code == 401, response.text

    def test_unauthenticated_stream_returns_401(self) -> None:
        """未认证 GET /stream 应返回 401。"""
        with _sync_client(user=None) as client:
            response = client.get("/api/notifications/stream")

        assert response.status_code == 401, response.text


# ==================== 环形缓冲区测试 ====================


class TestRingBuffer:
    """环形缓冲区容量限制。"""

    def test_drops_old_after_100(self) -> None:
        """超过 100 条后最旧的应被丢弃。"""
        with _sync_client(_USER_A) as client:
            # 写入 105 条
            for i in range(105):
                client.post("/api/notifications", json={"title": f"Msg-{i:03d}"})

            response = client.get("/api/notifications", params={"limit": 100})

        assert response.status_code == 200, response.text
        body = response.json()
        # total 应为 100（环形缓冲上限）
        assert body["total"] == 100
        assert body["count"] == 100
        titles = [n["title"] for n in body["notifications"]]
        # 最新在前，第一条应是 Msg-104
        assert titles[0] == "Msg-104"
        # 最旧的 Msg-000 ~ Msg-004 应已被丢弃
        assert "Msg-000" not in titles
        assert "Msg-004" not in titles
        # Msg-005 应还存在（最旧的一条）
        assert "Msg-005" in titles


# ==================== SSE 流式测试 ====================


# 直接调用端点函数的辅助工具
from api.routes.notifications import (
    NotificationCreateRequest,
    create_notification,
    stream_notifications,
)


class TestSSEStream:
    """GET /api/notifications/stream SSE 流式推送。

    直接调用端点函数（stream_notifications / create_notification）而非通过 HTTP 层，
    避免 httpx ASGITransport 无法正确取消异步生成器导致测试挂起。
    所有调用在同一事件循环中，asyncio.Queue.put_nowait 能正确唤醒等待的 get()。
    """

    async def test_returns_text_event_stream_content_type(self) -> None:
        """SSE 端点应返回 text/event-stream Content-Type。"""
        response = await stream_notifications(current_user=_USER_A)
        try:
            assert response.media_type == "text/event-stream"
            # headers 中应包含禁用缓冲的控制头
            assert response.headers.get("cache-control") == "no-cache, no-transform"
            assert response.headers.get("x-accel-buffering") == "no"
        finally:
            # 关闭生成器，触发 finally 清理订阅
            await response.body_iterator.aclose()

    async def test_stream_receives_new_notification(self) -> None:
        """SSE 流应接收 POST 推送的新通知。"""
        # 调用端点函数获取 StreamingResponse（Queue 已注册到订阅集合）
        response = await stream_notifications(current_user=_USER_A)
        received_chunks: list[str] = []

        async def _consume() -> None:
            async for chunk in response.body_iterator:
                text = chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk
                received_chunks.append(text)
                if "data:" in text:
                    return

        consume_task = asyncio.create_task(_consume())
        # 等待生成器进入 await queue.get()
        await asyncio.sleep(0.1)

        # 直接调用 create_notification 推送通知
        create_req = NotificationCreateRequest(
            title="Stream Hello", body="From POST", notification_type="info"
        )
        await create_notification(request=create_req, current_user=_USER_A)

        # 等待消费任务完成
        await asyncio.wait_for(consume_task, timeout=5.0)

        # 应收到 event: notification 和 data: {...}
        body = "".join(received_chunks)
        assert "event: notification" in body
        assert "data:" in body

        import json as _json
        data_line = [l for l in body.split("\n") if l.startswith("data:")][0]
        payload = _json.loads(data_line[len("data:"):].strip())
        assert payload["title"] == "Stream Hello"
        assert payload["body"] == "From POST"

        # 清理生成器
        await response.body_iterator.aclose()

    async def test_stream_cross_user_isolation(self) -> None:
        """用户 A 发送通知不应推送到用户 B 的 SSE 流。"""
        # 用户 B 订阅
        response_b = await stream_notifications(current_user=_USER_B)
        received_b: list[str] = []

        async def _consume_b() -> None:
            async for chunk in response_b.body_iterator:
                text = chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk
                received_b.append(text)
                if "data:" in text:
                    return

        consume_b = asyncio.create_task(_consume_b())
        await asyncio.sleep(0.1)

        # 用户 A 发送通知
        create_req_a = NotificationCreateRequest(title="User A message")
        await create_notification(request=create_req_a, current_user=_USER_A)

        # 用户 B 的流不应收到 A 的通知，等待 1s 确认无推送
        done, pending = await asyncio.wait({consume_b}, timeout=1.0)
        assert consume_b in pending, "用户 B 的流不应收到用户 A 的通知"

        # 用户 B 发送自己的通知
        create_req_b = NotificationCreateRequest(title="User B message")
        await create_notification(request=create_req_b, current_user=_USER_B)

        # 用户 B 的流现在应收到通知
        await asyncio.wait_for(consume_b, timeout=5.0)
        body_b = "".join(received_b)
        assert "User B message" in body_b
        assert "User A message" not in body_b

        # 清理
        await response_b.body_iterator.aclose()

    async def test_subscriber_cleanup_on_disconnect(self) -> None:
        """SSE 客户端断开后订阅集合应被清理。

        生成器必须先启动（通过 __anext__ 进入 await queue.get()），
        再取消消费任务让 CancelledError 传播进生成器，触发 finally 块的
        subs.discard(queue)。直接对未启动的生成器调 aclose() 不会执行 finally。
        """
        response = await stream_notifications(current_user=_USER_A)
        assert len(_notification_subscribers.get("user-a", set())) == 1

        # 启动生成器（进入 await queue.get() 等待状态）
        async def _consume():
            async for _ in response.body_iterator:
                pass

        consume_task = asyncio.create_task(_consume())
        await asyncio.sleep(0.1)  # 等待生成器进入 await queue.get()

        # 取消消费任务，CancelledError 传播进生成器，触发 finally 清理
        consume_task.cancel()
        try:
            await consume_task
        except asyncio.CancelledError:
            pass

        # 验证订阅集合已清空
        subs = _notification_subscribers.get("user-a", set())
        assert len(subs) == 0, f"断开后订阅集合应清空，但残留 {len(subs)} 个"

    async def test_multiple_subscribers_all_receive(self) -> None:
        """多个 SSE 订阅者应同时收到通知。"""
        response_1 = await stream_notifications(current_user=_USER_A)
        response_2 = await stream_notifications(current_user=_USER_A)
        received_1: list[str] = []
        received_2: list[str] = []

        # 验证两个订阅者都已注册
        assert len(_notification_subscribers.get("user-a", set())) == 2

        async def _consume(response, target: list[str]) -> None:
            async for chunk in response.body_iterator:
                text = chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk
                target.append(text)
                if "data:" in text:
                    return

        t1 = asyncio.create_task(_consume(response_1, received_1))
        t2 = asyncio.create_task(_consume(response_2, received_2))
        await asyncio.sleep(0.1)

        # 发送通知
        create_req = NotificationCreateRequest(title="Broadcast test")
        await create_notification(request=create_req, current_user=_USER_A)

        await asyncio.wait_for(asyncio.gather(t1, t2), timeout=5.0)

        # 两个订阅者都应收到通知
        assert any("data:" in c for c in received_1), "订阅者 1 未收到通知"
        assert any("data:" in c for c in received_2), "订阅者 2 未收到通知"

        # 清理
        await response_1.body_iterator.aclose()
        await response_2.body_iterator.aclose()
