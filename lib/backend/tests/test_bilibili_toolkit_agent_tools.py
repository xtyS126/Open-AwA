"""bilibili-toolkit-builtin Agent 工具函数与 schema 定义测试。

覆盖 SubTask 53.1：5 个 Agent 工具的参数 schema、返回格式与基本行为。

工具列表：
- ``bilibili_add_subscription``：添加订阅源
- ``bilibili_list_subscriptions``：列出订阅
- ``bilibili_trigger_download``：手动触发下载
- ``bilibili_get_download_status``：查询下载状态
- ``bilibili_list_videos``：列出已下载视频

测试隔离：
- 使用 in-memory SQLite 与 StaticPool
- mock ``_execute_download`` 避免触发真实 B 站 API 调用
- 每个 fixture 清理 bilibili_toolkit 表与 _running_tasks 索引
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

# 将 backend 目录加入 sys.path
_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from db.models import Base  # noqa: E402
from db.models.bilibili_toolkit import (  # noqa: E402
    BilibiliToolkitDownloadTask,
    BilibiliToolkitSubscription,
    BilibiliToolkitVideo,
)
from plugins.bilibili_toolkit_builtin.api import routes as bt_routes  # noqa: E402
from plugins.bilibili_toolkit_builtin.tools import (  # noqa: E402
    BILIBILI_TOOLKIT_TOOLS,
    bilibili_add_subscription,
    bilibili_get_download_status,
    bilibili_list_subscriptions,
    bilibili_list_videos,
    bilibili_trigger_download,
)


# ---------------------------------------------------------------------------
# 测试数据库
# ---------------------------------------------------------------------------

_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)
Base.metadata.create_all(bind=_engine)


@pytest.fixture
def db_session() -> Session:
    """提供独立数据库会话。"""
    db = _TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def _clear_bilibili_tables():
    """每个用例运行前后清理 bilibili_toolkit 表与 _running_tasks。"""
    db = _TestingSessionLocal()
    try:
        db.query(BilibiliToolkitDownloadTask).delete()
        db.query(BilibiliToolkitVideo).delete()
        db.query(BilibiliToolkitSubscription).delete()
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
    db: Session,
    sub_type: str = "favorite",
    source_id: int = 100,
    name: str = "测试订阅",
    path: str = "/tmp/test",
    enabled: bool = True,
    latest_row_at: int | None = None,
) -> BilibiliToolkitSubscription:
    """插入订阅记录，返回 ORM 实例。"""
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
    return sub


def _seed_video(
    db: Session,
    bvid: str = "BV1xxx",
    title: str = "测试视频",
    upper_name: str = "UP主",
    pages_count: int = 1,
    download_status: int = 0,
) -> BilibiliToolkitVideo:
    """插入视频记录，返回 ORM 实例。"""
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
    return video


def _seed_download_task(
    db: Session,
    video_id: int,
    subtask: str = "video",
    task_status: str = "succeeded",
    page_id: int | None = None,
    error: str | None = None,
) -> BilibiliToolkitDownloadTask:
    """插入下载任务记录，返回 ORM 实例。"""
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
    return task


# =============================================================================
# BILIBILI_TOOLKIT_TOOLS schema 测试
# =============================================================================


class TestBilibiliToolkitToolsSchema:
    """``BILIBILI_TOOLKIT_TOOLS`` 工具定义 schema 校验。"""

    def test_tools_count_is_five(self) -> None:
        """应有 5 个工具定义。"""
        assert len(BILIBILI_TOOLKIT_TOOLS) == 5

    def test_each_tool_has_required_fields(self) -> None:
        """每个工具定义应含 name / description / parameters / handler 字段。"""
        for tool in BILIBILI_TOOLKIT_TOOLS:
            assert "name" in tool
            assert isinstance(tool["name"], str)
            assert len(tool["name"]) > 0
            assert "description" in tool
            assert isinstance(tool["description"], str)
            assert len(tool["description"]) > 0
            assert "parameters" in tool
            assert isinstance(tool["parameters"], dict)
            assert "handler" in tool
            assert callable(tool["handler"])

    def test_tool_names_match_expected(self) -> None:
        """工具名应与 spec 一致。"""
        names = [t["name"] for t in BILIBILI_TOOLKIT_TOOLS]
        assert "bilibili_add_subscription" in names
        assert "bilibili_list_subscriptions" in names
        assert "bilibili_trigger_download" in names
        assert "bilibili_get_download_status" in names
        assert "bilibili_list_videos" in names

    def test_add_subscription_parameters_schema(self) -> None:
        """``bilibili_add_subscription`` 的 parameters schema 应含必填字段。"""
        tool = next(
            t for t in BILIBILI_TOOLKIT_TOOLS
            if t["name"] == "bilibili_add_subscription"
        )
        params = tool["parameters"]
        assert params["type"] == "object"
        properties = params["properties"]
        # 必填字段
        assert "subscription_type" in properties
        assert "source_id" in properties
        assert "name" in properties
        assert "path" in properties
        # 必填字段列表
        required = params["required"]
        assert "subscription_type" in required
        assert "source_id" in required
        assert "name" in required
        assert "path" in required
        # subscription_type 应有 enum 限定 5 种类型
        enum_values = properties["subscription_type"]["enum"]
        assert set(enum_values) == {
            "favorite", "season", "series", "submission", "watchlater"
        }

    def test_trigger_download_parameters_schema(self) -> None:
        """``bilibili_trigger_download`` 应有 subscription_id 必填字段。"""
        tool = next(
            t for t in BILIBILI_TOOLKIT_TOOLS
            if t["name"] == "bilibili_trigger_download"
        )
        params = tool["parameters"]
        assert "subscription_id" in params["properties"]
        assert "subscription_id" in params["required"]

    def test_get_download_status_parameters_schema(self) -> None:
        """``bilibili_get_download_status`` 应有可选 video_id 字段。"""
        tool = next(
            t for t in BILIBILI_TOOLKIT_TOOLS
            if t["name"] == "bilibili_get_download_status"
        )
        params = tool["parameters"]
        assert "video_id" in params["properties"]
        # video_id 应为可选（不在 required 中）
        assert "video_id" not in params.get("required", [])

    def test_list_videos_parameters_schema(self) -> None:
        """``bilibili_list_videos`` 应有 page / page_size 字段。"""
        tool = next(
            t for t in BILIBILI_TOOLKIT_TOOLS
            if t["name"] == "bilibili_list_videos"
        )
        params = tool["parameters"]
        assert "page" in params["properties"]
        assert "page_size" in params["properties"]
        # page 最小值约束
        assert params["properties"]["page"]["minimum"] == 1
        # page_size 最大值约束
        assert params["properties"]["page_size"]["maximum"] == 100


# =============================================================================
# bilibili_add_subscription 测试
# =============================================================================


class TestBilibiliAddSubscription:
    """``bilibili_add_subscription`` 工具函数。"""

    @pytest.mark.asyncio
    async def test_add_subscription_succeeds(self, db_session: Session) -> None:
        """正常添加订阅应返回 subscription_id 与 message。"""
        with patch(
            "plugins.bilibili_toolkit_builtin.api.routes._execute_download",
            new_callable=AsyncMock,
        ):
            result = await bilibili_add_subscription(
                db=db_session,
                user_id=1,
                subscription_type="favorite",
                source_id=100,
                name="测试收藏夹",
                path="/data/videos",
            )
        # 应返回成功结构
        assert "subscription_id" in result
        assert isinstance(result["subscription_id"], int)
        assert result["subscription_id"] > 0
        assert "message" in result
        assert "videos" in result
        assert result["videos"] == []

    @pytest.mark.asyncio
    async def test_add_subscription_invalid_type_returns_error(
        self, db_session: Session
    ) -> None:
        """不支持的订阅类型应返回 error 字典。"""
        result = await bilibili_add_subscription(
            db=db_session,
            user_id=1,
            subscription_type="invalid_type",
            source_id=100,
            name="测试",
            path="/data/videos",
        )
        assert "error" in result
        assert result["error"] == "invalid_subscription_type"
        assert "message" in result
        # 数据库中不应创建记录
        subs = db_session.query(BilibiliToolkitSubscription).all()
        assert len(subs) == 0

    @pytest.mark.asyncio
    async def test_add_subscription_duplicate_returns_error(
        self, db_session: Session
    ) -> None:
        """重复 (type, source_id) 应返回 error 字典。"""
        _seed_subscription(db_session, sub_type="favorite", source_id=100)
        result = await bilibili_add_subscription(
            db=db_session,
            user_id=1,
            subscription_type="favorite",
            source_id=100,
            name="重复订阅",
            path="/data/videos",
        )
        assert "error" in result
        assert result["error"] == "subscription_already_exists"
        # 数据库中应只有 1 条记录
        subs = db_session.query(BilibiliToolkitSubscription).all()
        assert len(subs) == 1

    @pytest.mark.asyncio
    async def test_add_subscription_with_filter_option(
        self, db_session: Session
    ) -> None:
        """带 filter_option 的订阅应序列化为 JSON 存储。"""
        with patch(
            "plugins.bilibili_toolkit_builtin.api.routes._execute_download",
            new_callable=AsyncMock,
        ):
            result = await bilibili_add_subscription(
                db=db_session,
                user_id=1,
                subscription_type="submission",
                source_id=200,
                name="UP主投稿",
                path="/data/videos",
                filter_option={
                    "video_max_quality": "1080p",
                    "video_codecs": ["avc"],
                },
            )
        assert "subscription_id" in result
        # 验证 filter_option 已序列化
        sub = db_session.query(BilibiliToolkitSubscription).first()
        assert sub is not None
        assert sub.filter_option is not None
        assert "video_max_quality" in sub.filter_option

    @pytest.mark.asyncio
    async def test_add_subscription_triggers_background_scan(
        self, db_session: Session
    ) -> None:
        """添加订阅应触发后台扫描（_execute_download 被调用）。

        注意：``tools.py`` 通过 ``from ... import _execute_download`` 导入，
        在 ``tools`` 模块命名空间建立本地绑定；patch ``routes`` 模块的属性
        不会影响 ``tools`` 模块的绑定。必须 patch
        ``plugins.bilibili_toolkit_builtin.tools._execute_download`` 才能让
        ``bilibili_add_subscription`` 内部的 ``asyncio.create_task`` 使用 mock。
        """
        mock_execute = AsyncMock()
        with patch(
            "plugins.bilibili_toolkit_builtin.tools._execute_download",
            new=mock_execute,
        ):
            await bilibili_add_subscription(
                db=db_session,
                user_id=1,
                subscription_type="favorite",
                source_id=100,
                name="测试",
                path="/data/videos",
            )
            # 让事件循环跑一下，让 create_task 启动
            await asyncio.sleep(0.05)

        # _execute_download 应被调用一次
        assert mock_execute.await_count >= 1
        # _running_tasks 应记录了 task_id
        # （后台任务可能已执行完毕并清理，所以只检查调用次数）


# =============================================================================
# bilibili_list_subscriptions 测试
# =============================================================================


class TestBilibiliListSubscriptions:
    """``bilibili_list_subscriptions`` 工具函数。"""

    @pytest.mark.asyncio
    async def test_list_subscriptions_returns_empty(
        self, db_session: Session
    ) -> None:
        """无订阅时返回空列表。"""
        result = await bilibili_list_subscriptions(db=db_session, user_id=1)
        assert result == []

    @pytest.mark.asyncio
    async def test_list_subscriptions_returns_records(
        self, db_session: Session
    ) -> None:
        """有订阅时返回列表，字段完整。"""
        _seed_subscription(
            db_session, sub_type="favorite", source_id=100, name="收藏夹1"
        )
        _seed_subscription(
            db_session, sub_type="submission", source_id=200, name="UP主1"
        )
        result = await bilibili_list_subscriptions(db=db_session, user_id=1)
        assert len(result) == 2
        # 字段完整性
        item = result[0]
        assert "id" in item
        assert "type" in item
        assert "source_id" in item
        assert "name" in item
        assert "path" in item
        assert "enabled" in item
        assert "latest_row_at" in item
        assert "created_at" in item

    @pytest.mark.asyncio
    async def test_list_subscriptions_ordered_by_id(
        self, db_session: Session
    ) -> None:
        """返回结果按 id 升序排列。"""
        _seed_subscription(db_session, sub_type="submission", source_id=200)
        _seed_subscription(db_session, sub_type="favorite", source_id=100)
        result = await bilibili_list_subscriptions(db=db_session, user_id=1)
        assert len(result) == 2
        # 第一个 id 应小于第二个
        assert result[0]["id"] < result[1]["id"]


# =============================================================================
# bilibili_trigger_download 测试
# =============================================================================


class TestBilibiliTriggerDownload:
    """``bilibili_trigger_download`` 工具函数。"""

    @pytest.mark.asyncio
    async def test_trigger_download_succeeds(self, db_session: Session) -> None:
        """触发存在的订阅应返回 task_id。"""
        sub = _seed_subscription(db_session, sub_type="favorite", source_id=100)
        with patch(
            "plugins.bilibili_toolkit_builtin.api.routes._execute_download",
            new_callable=AsyncMock,
        ):
            result = await bilibili_trigger_download(
                db=db_session, user_id=1, subscription_id=sub.id
            )
        assert "task_id" in result
        assert isinstance(result["task_id"], str)
        assert len(result["task_id"]) == 32  # uuid4().hex
        assert result["subscription_id"] == sub.id
        assert "message" in result

    @pytest.mark.asyncio
    async def test_trigger_download_nonexistent_returns_error(
        self, db_session: Session
    ) -> None:
        """触发不存在的订阅应返回 error 字典。"""
        result = await bilibili_trigger_download(
            db=db_session, user_id=1, subscription_id=99999
        )
        assert "error" in result
        assert result["error"] == "subscription_not_found"
        assert "message" in result

    @pytest.mark.asyncio
    async def test_trigger_download_starts_background_task(
        self, db_session: Session
    ) -> None:
        """触发后应在后台调用 _execute_download。

        注意：``tools.py`` 通过 ``from ... import _execute_download`` 导入，
        在 ``tools`` 模块命名空间建立本地绑定；必须 patch
        ``plugins.bilibili_toolkit_builtin.tools._execute_download`` 才能让
        ``bilibili_trigger_download`` 内部的 ``asyncio.create_task`` 使用 mock。
        """
        sub = _seed_subscription(db_session, sub_type="favorite", source_id=100)
        mock_execute = AsyncMock()
        with patch(
            "plugins.bilibili_toolkit_builtin.tools._execute_download",
            new=mock_execute,
        ):
            await bilibili_trigger_download(
                db=db_session, user_id=1, subscription_id=sub.id
            )
            # 让事件循环跑一下让 create_task 启动
            await asyncio.sleep(0.05)

        # _execute_download 应被调用
        assert mock_execute.await_count >= 1


# =============================================================================
# bilibili_get_download_status 测试
# =============================================================================


class TestBilibiliGetDownloadStatus:
    """``bilibili_get_download_status`` 工具函数。"""

    @pytest.mark.asyncio
    async def test_get_download_status_empty(self, db_session: Session) -> None:
        """无任务时返回空 tasks 列表与 summary.total=0。"""
        result = await bilibili_get_download_status(db=db_session, user_id=1)
        assert result["video_id"] is None
        assert result["tasks"] == []
        assert result["summary"]["total"] == 0
        assert result["summary"]["by_status"] == {}

    @pytest.mark.asyncio
    async def test_get_download_status_returns_records(
        self, db_session: Session
    ) -> None:
        """有任务时返回列表与状态汇总。"""
        video = _seed_video(db_session)
        _seed_download_task(
            db_session, video_id=video.id, subtask="cover", task_status="succeeded"
        )
        _seed_download_task(
            db_session, video_id=video.id, subtask="video", task_status="failed", error="ffmpeg"
        )
        _seed_download_task(
            db_session, video_id=video.id, subtask="nfo", task_status="succeeded"
        )
        result = await bilibili_get_download_status(db=db_session, user_id=1)
        assert result["summary"]["total"] == 3
        # by_status 应有 succeeded:2, failed:1
        assert result["summary"]["by_status"]["succeeded"] == 2
        assert result["summary"]["by_status"]["failed"] == 1
        # tasks 列表字段完整
        task = result["tasks"][0]
        assert "id" in task
        assert "video_id" in task
        assert "subtask" in task
        assert "status" in task
        assert "error" in task
        assert "retry_count" in task

    @pytest.mark.asyncio
    async def test_get_download_status_filter_by_video_id(
        self, db_session: Session
    ) -> None:
        """按 video_id 过滤任务。"""
        video1 = _seed_video(db_session, bvid="BV1aaa")
        video2 = _seed_video(db_session, bvid="BV2bbb")
        _seed_download_task(
            db_session, video_id=video1.id, subtask="cover", task_status="succeeded"
        )
        _seed_download_task(
            db_session, video_id=video2.id, subtask="video", task_status="failed"
        )
        result = await bilibili_get_download_status(
            db=db_session, user_id=1, video_id=video1.id
        )
        assert result["video_id"] == video1.id
        assert len(result["tasks"]) == 1
        assert result["tasks"][0]["subtask"] == "cover"
        # summary 应只统计过滤后的任务
        assert result["summary"]["total"] == 1

    @pytest.mark.asyncio
    async def test_get_download_status_limits_to_50(
        self, db_session: Session
    ) -> None:
        """未指定 video_id 时应限制返回 50 条。"""
        video = _seed_video(db_session)
        # 插入 60 条任务
        for i in range(60):
            _seed_download_task(
                db_session,
                video_id=video.id,
                subtask=f"task_{i}",
                task_status="succeeded",
            )
        result = await bilibili_get_download_status(db=db_session, user_id=1)
        # 应只返回最近 50 条
        assert len(result["tasks"]) == 50
        assert result["summary"]["total"] == 50


# =============================================================================
# bilibili_list_videos 测试
# =============================================================================


class TestBilibiliListVideos:
    """``bilibili_list_videos`` 工具函数。"""

    @pytest.mark.asyncio
    async def test_list_videos_empty(self, db_session: Session) -> None:
        """无视频时返回空列表。"""
        result = await bilibili_list_videos(db=db_session, user_id=1)
        assert result == []

    @pytest.mark.asyncio
    async def test_list_videos_returns_records(self, db_session: Session) -> None:
        """有视频时返回列表，字段完整。"""
        _seed_video(db_session, bvid="BV1aaa", title="视频1")
        _seed_video(db_session, bvid="BV2bbb", title="视频2")
        result = await bilibili_list_videos(db=db_session, user_id=1)
        assert len(result) == 2
        # 字段完整性
        item = result[0]
        assert "id" in item
        assert "bvid" in item
        assert "title" in item
        assert "cover" in item
        assert "upper_name" in item
        assert "pages_count" in item
        assert "download_status" in item
        assert "created_at" in item

    @pytest.mark.asyncio
    async def test_list_videos_pagination(self, db_session: Session) -> None:
        """分页参数生效。"""
        for i in range(5):
            _seed_video(db_session, bvid=f"BV{i}xxx", title=f"视频{i}")
        result = await bilibili_list_videos(
            db=db_session, user_id=1, page=1, page_size=2
        )
        assert len(result) == 2

        # 第二页
        result_page2 = await bilibili_list_videos(
            db=db_session, user_id=1, page=2, page_size=2
        )
        assert len(result_page2) == 2
        # 第二页的 id 应不同于第一页
        page1_ids = {v["id"] for v in result}
        page2_ids = {v["id"] for v in result_page2}
        assert page1_ids.isdisjoint(page2_ids)

    @pytest.mark.asyncio
    async def test_list_videos_default_page_size(
        self, db_session: Session
    ) -> None:
        """未指定 page_size 时默认 20。"""
        for i in range(25):
            _seed_video(db_session, bvid=f"BV{i:03d}", title=f"视频{i}")
        result = await bilibili_list_videos(db=db_session, user_id=1)
        # 默认 page_size=20
        assert len(result) == 20
