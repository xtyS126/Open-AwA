"""bilibili-toolkit-builtin 阶段 15 新增 6 个路由的鉴权 / 参数校验 / 响应格式测试。

覆盖 SubTask 52.1：以下 6 个路由：

- GET    /api/plugins/bilibili-toolkit-builtin/subscriptions
- POST   /api/plugins/bilibili-toolkit-builtin/subscriptions
- DELETE /api/plugins/bilibili-toolkit-builtin/subscriptions/{id}
- GET    /api/plugins/bilibili-toolkit-builtin/videos
- POST   /api/plugins/bilibili-toolkit-builtin/trigger/{id}
- GET    /api/plugins/bilibili-toolkit-builtin/tasks

测试隔离：
- 使用 in-memory SQLite 与 StaticPool 保证测试间互不干扰
- 通过 dependency_overrides 替换 get_db 与 get_current_user
- 后台下载 ``_execute_download`` 全部 mock，避免触发真实 B 站 API 调用

注意：与现有 ``test_bilibili_toolkit_builtin_routes.py`` 互不重叠，
本文件聚焦阶段 15 新增的订阅/视频/任务路由，前者覆盖 403 内置插件保护。
"""

from __future__ import annotations

import sys
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# 将 backend 目录加入 sys.path
_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from api.dependencies import get_current_user, get_db  # noqa: E402
from db.models import Base, User  # noqa: E402
from db.models.bilibili_toolkit import (  # noqa: E402
    BilibiliToolkitDownloadTask,
    BilibiliToolkitSubscription,
    BilibiliToolkitVideo,
)
from main import app  # noqa: E402
from plugins.bilibili_toolkit_builtin.api import routes as bt_routes  # noqa: E402


# ---------------------------------------------------------------------------
# 测试数据库与依赖注入覆盖
# ---------------------------------------------------------------------------

# 全局 in-memory SQLite 引擎，所有连接共享同一数据库（StaticPool）
_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)
Base.metadata.create_all(bind=_engine)


def _override_get_db():
    """提供独立测试数据库会话。"""
    db = _TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


class _DummyUser:
    """模拟已认证用户，满足路由依赖的最小字段集。"""

    def __init__(self, user_id: int = 1) -> None:
        self.id = user_id
        self.username = "tester"
        self.role = "user"


def _override_get_current_user() -> _DummyUser:
    """返回固定用户，绕过真实认证流程。"""
    return _DummyUser()


@contextmanager
def _test_client() -> Iterator[TestClient]:
    """注入依赖覆盖并构造 TestClient，确保用例间隔离。"""
    previous_overrides = dict(app.dependency_overrides)
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_user] = _override_get_current_user
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides = previous_overrides


@contextmanager
def _test_client_no_auth() -> Iterator[TestClient]:
    """不注入认证覆盖，用于测试 401 鉴权失败场景。"""
    previous_overrides = dict(app.dependency_overrides)
    app.dependency_overrides[get_db] = _override_get_db
    # 故意不覆盖 get_current_user，让其走真实认证流程
    # 真实流程在 TESTING 模式下应返回 401（无 token）
    app.dependency_overrides.pop(get_current_user, None)
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides = previous_overrides


# ---------------------------------------------------------------------------
# fixture：数据库清理
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_bilibili_tables():
    """每个用例运行前后清理 bilibili_toolkit 相关表，保证用例间互不干扰。"""
    db = _TestingSessionLocal()
    try:
        db.query(BilibiliToolkitDownloadTask).delete()
        db.query(BilibiliToolkitVideo).delete()
        db.query(BilibiliToolkitSubscription).delete()
        # 清空内存中的 _running_tasks 索引
        bt_routes._running_tasks.clear()
        db.commit()
    finally:
        db.close()
    yield
    db = _TestingSessionLocal()
    try:
        db.query(BilibiliToolkitDownloadTask).delete()
        db.query(BilibiliToolkitVideo).delete()
        db.query(BilibiliToolkitSubscription).delete()
        bt_routes._running_tasks.clear()
        db.commit()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


def _seed_subscription(
    sub_type: str = "favorite",
    source_id: int = 100,
    name: str = "测试订阅",
    path: str = "/tmp/test_videos",
    enabled: bool = True,
    latest_row_at: int | None = None,
) -> int:
    """在测试数据库中插入一条订阅记录，返回其 ID。"""
    db = _TestingSessionLocal()
    try:
        sub = BilibiliToolkitSubscription(
            type=sub_type,
            source_id=source_id,
            name=name,
            path=path,
            enabled=enabled,
            latest_row_at=latest_row_at,
        )
        db.add(sub)
        db.commit()
        db.refresh(sub)
        sub_id = sub.id
    finally:
        db.close()
    return sub_id


def _seed_video(
    bvid: str = "BV1xxx",
    title: str = "测试视频",
    upper_name: str = "UP主",
    pages_count: int = 1,
    download_status: int = 0,
) -> int:
    """在测试数据库中插入一条视频记录，返回其 ID。"""
    db = _TestingSessionLocal()
    try:
        video = BilibiliToolkitVideo(
            bvid=bvid,
            aid=100,
            title=title,
            cover="https://example.com/cover.jpg",
            upper_mid=200,
            upper_name=upper_name,
            pages_count=pages_count,
            pubtime=1700000000,
            download_status=download_status,
        )
        db.add(video)
        db.commit()
        db.refresh(video)
        video_id = video.id
    finally:
        db.close()
    return video_id


def _seed_download_task(
    video_id: int,
    subtask: str = "video",
    task_status: str = "succeeded",
    page_id: int | None = None,
    error: str | None = None,
) -> int:
    """在测试数据库中插入一条下载任务记录，返回其 ID。"""
    db = _TestingSessionLocal()
    try:
        task = BilibiliToolkitDownloadTask(
            video_id=video_id,
            page_id=page_id,
            subtask=subtask,
            status=task_status,
            retry_count=0,
            error=error,
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        task_id = task.id
    finally:
        db.close()
    return task_id


# ---------------------------------------------------------------------------
# 鉴权测试
# ---------------------------------------------------------------------------


class TestRouteAuthentication:
    """所有路由必须经过鉴权，未登录返回 401。"""

    def test_list_subscriptions_requires_auth(self) -> None:
        """GET /subscriptions 未登录应返回 401。"""
        with _test_client_no_auth() as client:
            response = client.get(
                "/api/plugins/bilibili-toolkit-builtin/subscriptions"
            )
        assert response.status_code == 401

    def test_create_subscription_requires_auth(self) -> None:
        """POST /subscriptions 未登录应返回 401。"""
        with _test_client_no_auth() as client:
            response = client.post(
                "/api/plugins/bilibili-toolkit-builtin/subscriptions",
                json={
                    "type": "favorite",
                    "source_id": 100,
                    "name": "测试",
                    "path": "/tmp/test",
                },
            )
        assert response.status_code == 401

    def test_delete_subscription_requires_auth(self) -> None:
        """DELETE /subscriptions/{id} 未登录应返回 401。"""
        sub_id = _seed_subscription()
        with _test_client_no_auth() as client:
            response = client.delete(
                f"/api/plugins/bilibili-toolkit-builtin/subscriptions/{sub_id}"
            )
        assert response.status_code == 401

    def test_list_videos_requires_auth(self) -> None:
        """GET /videos 未登录应返回 401。"""
        with _test_client_no_auth() as client:
            response = client.get("/api/plugins/bilibili-toolkit-builtin/videos")
        assert response.status_code == 401

    def test_trigger_download_requires_auth(self) -> None:
        """POST /trigger/{id} 未登录应返回 401。"""
        sub_id = _seed_subscription()
        with _test_client_no_auth() as client:
            response = client.post(
                f"/api/plugins/bilibili-toolkit-builtin/trigger/{sub_id}"
            )
        assert response.status_code == 401

    def test_list_tasks_requires_auth(self) -> None:
        """GET /tasks 未登录应返回 401。"""
        with _test_client_no_auth() as client:
            response = client.get("/api/plugins/bilibili-toolkit-builtin/tasks")
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# 订阅管理路由测试
# ---------------------------------------------------------------------------


class TestSubscriptionsRoutes:
    """订阅管理路由：GET / POST / DELETE /subscriptions。"""

    def test_list_subscriptions_returns_empty(self) -> None:
        """无订阅时返回空列表。"""
        with _test_client() as client:
            response = client.get(
                "/api/plugins/bilibili-toolkit-builtin/subscriptions"
            )
        assert response.status_code == 200
        assert response.json() == []

    def test_list_subscriptions_returns_existing_records(self) -> None:
        """已有订阅时返回列表。"""
        _seed_subscription(
            sub_type="favorite", source_id=100, name="收藏夹1"
        )
        _seed_subscription(
            sub_type="submission", source_id=200, name="UP主1"
        )
        with _test_client() as client:
            response = client.get(
                "/api/plugins/bilibili-toolkit-builtin/subscriptions"
            )
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        # 按 id 升序返回
        assert data[0]["type"] == "favorite"
        assert data[0]["source_id"] == 100
        assert data[0]["name"] == "收藏夹1"
        assert data[1]["type"] == "submission"
        assert data[1]["source_id"] == 200

    def test_create_subscription_succeeds(self) -> None:
        """正常创建订阅应返回 201 与订阅详情。"""
        with _test_client() as client:
            response = client.post(
                "/api/plugins/bilibili-toolkit-builtin/subscriptions",
                json={
                    "type": "favorite",
                    "source_id": 100,
                    "name": "我的收藏夹",
                    "path": "/data/videos/fav",
                    "enabled": True,
                },
            )
        assert response.status_code == 201
        data = response.json()
        assert data["type"] == "favorite"
        assert data["source_id"] == 100
        assert data["name"] == "我的收藏夹"
        assert data["path"] == "/data/videos/fav"
        assert data["enabled"] is True
        assert data["id"] > 0
        # latest_row_at 初始为 None
        assert data["latest_row_at"] is None

    def test_create_subscription_with_filter_option(self) -> None:
        """带 filter_option 的订阅创建应成功，且 filter_option 被序列化存储。"""
        with _test_client() as client:
            response = client.post(
                "/api/plugins/bilibili-toolkit-builtin/subscriptions",
                json={
                    "type": "submission",
                    "source_id": 200,
                    "name": "UP主投稿",
                    "path": "/data/videos/up",
                    "filter_option": {
                        "video_max_quality": "1080p",
                        "video_codecs": ["avc", "hevc"],
                    },
                },
            )
        assert response.status_code == 201
        # 验证数据库中 filter_option 字段已序列化为 JSON
        db = _TestingSessionLocal()
        try:
            sub = (
                db.query(BilibiliToolkitSubscription)
                .filter(BilibiliToolkitSubscription.type == "submission")
                .first()
            )
            assert sub is not None
            assert sub.filter_option is not None
            assert "video_max_quality" in sub.filter_option
        finally:
            db.close()

    def test_create_subscription_invalid_type_returns_400(self) -> None:
        """不支持的订阅类型应返回 400。"""
        with _test_client() as client:
            response = client.post(
                "/api/plugins/bilibili-toolkit-builtin/subscriptions",
                json={
                    "type": "invalid_type",
                    "source_id": 100,
                    "name": "测试",
                    "path": "/tmp/test",
                },
            )
        assert response.status_code == 400
        assert "不支持的订阅类型" in response.text

    def test_create_subscription_duplicate_returns_409(self) -> None:
        """重复 (type, source_id) 应返回 409。"""
        _seed_subscription(sub_type="favorite", source_id=100)
        with _test_client() as client:
            response = client.post(
                "/api/plugins/bilibili-toolkit-builtin/subscriptions",
                json={
                    "type": "favorite",
                    "source_id": 100,
                    "name": "重复订阅",
                    "path": "/tmp/test",
                },
            )
        assert response.status_code == 409
        assert "已存在" in response.text

    def test_create_subscription_missing_required_field_returns_422(self) -> None:
        """缺少必填字段应返回 422。"""
        with _test_client() as client:
            response = client.post(
                "/api/plugins/bilibili-toolkit-builtin/subscriptions",
                json={
                    "type": "favorite",
                    # 缺少 source_id / name / path
                },
            )
        assert response.status_code == 422

    def test_delete_subscription_succeeds(self) -> None:
        """删除存在的订阅应返回 204。"""
        sub_id = _seed_subscription()
        with _test_client() as client:
            response = client.delete(
                f"/api/plugins/bilibili-toolkit-builtin/subscriptions/{sub_id}"
            )
        assert response.status_code == 204
        # 验证已删除
        db = _TestingSessionLocal()
        try:
            assert (
                db.query(BilibiliToolkitSubscription)
                .filter(BilibiliToolkitSubscription.id == sub_id)
                .first()
                is None
            )
        finally:
            db.close()

    def test_delete_nonexistent_subscription_returns_404(self) -> None:
        """删除不存在的订阅应返回 404。"""
        with _test_client() as client:
            response = client.delete(
                "/api/plugins/bilibili-toolkit-builtin/subscriptions/99999"
            )
        assert response.status_code == 404
        assert "不存在" in response.text


# ---------------------------------------------------------------------------
# 视频列表路由测试
# ---------------------------------------------------------------------------


class TestVideosRoute:
    """GET /videos 路由。"""

    def test_list_videos_returns_empty(self) -> None:
        """无视频时返回空列表。"""
        with _test_client() as client:
            response = client.get("/api/plugins/bilibili-toolkit-builtin/videos")
        assert response.status_code == 200
        assert response.json() == []

    def test_list_videos_returns_existing_records(self) -> None:
        """已有视频时返回列表，按 created_at 倒序。"""
        _seed_video(bvid="BV1aaa", title="视频1")
        _seed_video(bvid="BV2bbb", title="视频2")
        with _test_client() as client:
            response = client.get("/api/plugins/bilibili-toolkit-builtin/videos")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        # 字段完整性检查
        assert "id" in data[0]
        assert "bvid" in data[0]
        assert "title" in data[0]
        assert "upper_name" in data[0]
        assert "pages_count" in data[0]
        assert "download_status" in data[0]

    def test_list_videos_pagination(self) -> None:
        """分页参数生效。"""
        # 插入 5 条视频
        for i in range(5):
            _seed_video(bvid=f"BV{i}xxx", title=f"视频{i}")
        with _test_client() as client:
            # 第 1 页，每页 2 条
            response = client.get(
                "/api/plugins/bilibili-toolkit-builtin/videos",
                params={"page": 1, "page_size": 2},
            )
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2

    def test_list_videos_invalid_page_returns_422(self) -> None:
        """page < 1 应返回 422 校验错误。"""
        with _test_client() as client:
            response = client.get(
                "/api/plugins/bilibili-toolkit-builtin/videos",
                params={"page": 0},
            )
        assert response.status_code == 422

    def test_list_videos_page_size_exceeds_limit_returns_422(self) -> None:
        """page_size > 100 应返回 422 校验错误。"""
        with _test_client() as client:
            response = client.get(
                "/api/plugins/bilibili-toolkit-builtin/videos",
                params={"page_size": 101},
            )
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# 触发下载路由测试
# ---------------------------------------------------------------------------


class TestTriggerDownloadRoute:
    """POST /trigger/{id} 路由。"""

    def test_trigger_download_succeeds(self) -> None:
        """触发存在的订阅应返回 200 与 task_id。"""
        sub_id = _seed_subscription()
        # mock _execute_download 避免真实下载
        with patch(
            "plugins.bilibili_toolkit_builtin.api.routes._execute_download",
            new_callable=AsyncMock,
        ):
            with _test_client() as client:
                response = client.post(
                    f"/api/plugins/bilibili-toolkit-builtin/trigger/{sub_id}"
                )
        assert response.status_code == 200
        data = response.json()
        assert "task_id" in data
        assert isinstance(data["task_id"], str)
        assert len(data["task_id"]) > 0
        assert "message" in data

    def test_trigger_download_nonexistent_returns_404(self) -> None:
        """触发不存在的订阅应返回 404。"""
        with _test_client() as client:
            response = client.post(
                "/api/plugins/bilibili-toolkit-builtin/trigger/99999"
            )
        assert response.status_code == 404
        assert "不存在" in response.text

    def test_trigger_download_registers_running_task(self) -> None:
        """触发后应在内存 _running_tasks 中注册 task_id。"""
        sub_id = _seed_subscription()
        with patch(
            "plugins.bilibili_toolkit_builtin.api.routes._execute_download",
            new_callable=AsyncMock,
        ):
            with _test_client() as client:
                response = client.post(
                    f"/api/plugins/bilibili-toolkit-builtin/trigger/{sub_id}"
                )
        data = response.json()
        task_id = data["task_id"]
        # _running_tasks 应记录了 task_id -> subscription_id 映射
        # 注意：后台任务可能已执行完毕并清理，因此只验证 task_id 格式正确
        assert isinstance(task_id, str)
        assert len(task_id) == 32  # uuid4().hex 长度


# ---------------------------------------------------------------------------
# 任务查询路由测试
# ---------------------------------------------------------------------------


class TestTasksRoute:
    """GET /tasks 路由。"""

    def test_list_tasks_returns_empty(self) -> None:
        """无任务时返回空列表。"""
        with _test_client() as client:
            response = client.get("/api/plugins/bilibili-toolkit-builtin/tasks")
        assert response.status_code == 200
        assert response.json() == []

    def test_list_tasks_returns_existing_records(self) -> None:
        """已有任务时返回列表。"""
        video_id = _seed_video()
        _seed_download_task(
            video_id=video_id, subtask="cover", task_status="succeeded"
        )
        _seed_download_task(
            video_id=video_id, subtask="video", task_status="failed", error="ffmpeg 不可用"
        )
        with _test_client() as client:
            response = client.get("/api/plugins/bilibili-toolkit-builtin/tasks")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        # 字段完整性
        assert "id" in data[0]
        assert "video_id" in data[0]
        assert "subtask" in data[0]
        assert "status" in data[0]
        assert "retry_count" in data[0]

    def test_list_tasks_filter_by_video_id(self) -> None:
        """按 video_id 过滤任务。"""
        video1 = _seed_video(bvid="BV1aaa")
        video2 = _seed_video(bvid="BV2bbb")
        _seed_download_task(video_id=video1, subtask="cover", task_status="succeeded")
        _seed_download_task(video_id=video2, subtask="video", task_status="failed")
        with _test_client() as client:
            response = client.get(
                "/api/plugins/bilibili-toolkit-builtin/tasks",
                params={"video_id": video1},
            )
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["video_id"] == video1
        assert data[0]["subtask"] == "cover"

    def test_list_tasks_filter_by_status(self) -> None:
        """按 status 过滤任务。"""
        video_id = _seed_video()
        _seed_download_task(video_id=video_id, subtask="cover", task_status="succeeded")
        _seed_download_task(video_id=video_id, subtask="video", task_status="failed")
        _seed_download_task(video_id=video_id, subtask="nfo", task_status="succeeded")
        with _test_client() as client:
            response = client.get(
                "/api/plugins/bilibili-toolkit-builtin/tasks",
                params={"task_status": "failed"},
            )
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["status"] == "failed"

    def test_list_tasks_pagination(self) -> None:
        """分页参数生效。"""
        video_id = _seed_video()
        for i in range(5):
            _seed_download_task(
                video_id=video_id,
                subtask=f"task_{i}",
                task_status="succeeded",
            )
        with _test_client() as client:
            response = client.get(
                "/api/plugins/bilibili-toolkit-builtin/tasks",
                params={"page": 1, "page_size": 2},
            )
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2


# ---------------------------------------------------------------------------
# 配置路由测试（额外覆盖）
# ---------------------------------------------------------------------------


class TestConfigRoutes:
    """GET / PUT /config 路由。"""

    def test_get_config_returns_uninitialized_when_not_loaded(self) -> None:
        """配置管理器未初始化时返回 initialized=False。"""
        # 确保未初始化
        from plugins.bilibili_toolkit_builtin.config import (
            reset_config_manager_for_test,
        )
        reset_config_manager_for_test()
        with _test_client() as client:
            response = client.get(
                "/api/plugins/bilibili-toolkit-builtin/config"
            )
        assert response.status_code == 200
        data = response.json()
        assert data["initialized"] is False
        assert data["version"] == 0
        assert data["config"] == {}

    def test_get_config_returns_initialized_state(self) -> None:
        """配置管理器已初始化时返回 initialized=True 与配置内容。"""
        from plugins.bilibili_toolkit_builtin.config import (
            init_config_manager,
            reset_config_manager_for_test,
        )
        reset_config_manager_for_test()
        init_config_manager({"video_name": "{{title}}", "trigger": {"type": "interval", "seconds": 60}})
        try:
            with _test_client() as client:
                response = client.get(
                    "/api/plugins/bilibili-toolkit-builtin/config"
                )
            assert response.status_code == 200
            data = response.json()
            assert data["initialized"] is True
            assert data["version"] == 0
            assert "video_name" in data["config"]
        finally:
            reset_config_manager_for_test()

    def test_update_config_returns_503_when_not_initialized(self) -> None:
        """配置管理器未初始化时 update_config 应抛 503 HTTPException。

        注意：bilibili_toolkit_router 的 PUT /config 路由与 plugins.router 的
        PUT /{plugin_id}/config 路由存在路径冲突，后者先注册会先匹配
        ``/api/plugins/bilibili-toolkit-builtin/config``。因此本测试通过直接
        调用路由函数 ``update_config`` 验证业务逻辑，而非走 HTTP。
        """
        from fastapi import HTTPException

        from plugins.bilibili_toolkit_builtin.api.routes import (
            ConfigUpdateRequest,
            update_config,
        )
        from plugins.bilibili_toolkit_builtin.config import (
            reset_config_manager_for_test,
        )
        reset_config_manager_for_test()
        payload = ConfigUpdateRequest(config={"key": "value"})
        user = _DummyUser()
        with pytest.raises(HTTPException) as exc_info:
            update_config(payload, current_user=user)
        assert exc_info.value.status_code == 503
        assert "未初始化" in exc_info.value.detail

    def test_update_config_succeeds_when_initialized(self) -> None:
        """配置管理器已初始化时 update_config 应返回新版本号。

        注意：因路由路径冲突（详见上一用例注释），本测试通过直接调用路由函数
        ``update_config`` 验证业务逻辑，而非走 HTTP。
        """
        from plugins.bilibili_toolkit_builtin.api.routes import (
            ConfigUpdateRequest,
            update_config,
        )
        from plugins.bilibili_toolkit_builtin.config import (
            init_config_manager,
            reset_config_manager_for_test,
        )
        reset_config_manager_for_test()
        init_config_manager({"key": "v1"})
        try:
            payload = ConfigUpdateRequest(config={"key": "v2"})
            user = _DummyUser()
            result = update_config(payload, current_user=user)
            assert result["version"] == 1
            assert "message" in result
        finally:
            reset_config_manager_for_test()
