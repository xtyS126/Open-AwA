"""下载流水线集成测试（SubTask 51.2）。

验证 ``download_video`` / ``download_page`` 完整下载流程，覆盖：

1. 5 路并发子任务（Cover / Video / Nfo / Danmaku / Subtitle）位图状态记录
2. 子任务失败不阻塞其他子任务（位图正确标记 Failed / Ignored）
3. 视频层任务（UP 主头像 / TVShow NFO）执行
4. ``skip_option`` 跳过指定子任务

测试隔离：
- ``get_playurl_streams`` / ``download_with_backup`` / ``merge_video_audio`` /
  ``fetch_danmaku`` / ``save_subtitle`` / ``save_upper_avatar`` /
  ``render_*_nfo`` 全部 mock，不发起真实 HTTP 请求与 ffmpeg 调用
- 视频与封面用临时目录落地，验证文件产出
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# 将 backend 目录加入 sys.path
_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from plugins.bilibili_toolkit_builtin.bilibili.client import BilibiliClient  # noqa: E402
from plugins.bilibili_toolkit_builtin.bilibili.credential import Credential  # noqa: E402
from plugins.bilibili_toolkit_builtin.bilibili.risk_control import (  # noqa: E402
    RiskControlError,
)
from plugins.bilibili_toolkit_builtin.bilibili.video import Page, VideoInfo  # noqa: E402
from plugins.bilibili_toolkit_builtin.status import (  # noqa: E402
    INITIAL_STATUS,
    SubTask,
    SubTaskState,
    get_subtask_status,
    set_subtask_status,
)
from plugins.bilibili_toolkit_builtin.workflow.pipeline import (  # noqa: E402
    WorkflowResult,
    download_page,
    download_video,
)


# ---------------------------------------------------------------------------
# mock 工具
# ---------------------------------------------------------------------------


def _make_video_info(
    bvid: str = "BV1xx4y1A7B",
    title: str = "测试视频",
    upper_mid: int = 100,
    upper_name: str = "测试UP",
    pages_count: int = 1,
) -> VideoInfo:
    """构造测试用 VideoInfo，单 P 默认。"""
    pages = [
        Page(
            cid=1000 + i,
            page=i + 1,
            name=f"P{i + 1}",
            duration=60,
            width=1920,
            height=1080,
        )
        for i in range(pages_count)
    ]
    return VideoInfo(
        bvid=bvid,
        aid=12345,
        title=title,
        cover="https://example.com/cover.jpg",
        upper_mid=upper_mid,
        upper_name=upper_name,
        upper_face="https://example.com/avatar.jpg",
        pages=pages,
        pubtime=1700000000,
        ctime=1700000000,
        desc="测试简介",
        tags=["test", "demo"],
    )


def _make_mock_client() -> MagicMock:
    """构造 mock BilibiliClient，所有方法均 mock。"""
    client = MagicMock(spec=BilibiliClient)
    client.request = AsyncMock(return_value={})
    client.close = AsyncMock(return_value=None)
    return client


def _make_default_config(base_dir: Path) -> dict[str, Any]:
    """构造默认插件配置 dict，路径模板与跳过项均最小化。"""
    return {
        "video_name": "{{bvid}}",
        "page_name": "{{bvid}}_p{{pid}}",
        "upper_path": "upers",
        "filter_option": {},
        "concurrent_limit": {
            "page": 2,
            "download": {"threshold": 20 * 1024 * 1024},
        },
        "cdn_sorting": True,
        "skip_option": {},
        "danmaku_option": {},
    }


# ---------------------------------------------------------------------------
# download_page 测试
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_download_page_all_subtasks_succeed(tmp_path: Path):
    """5 路子任务全部成功时，位图应全部为 Succeeded，files 列表完整。"""
    client = _make_mock_client()
    video = _make_video_info()
    page = video.pages[0]
    config = _make_default_config(tmp_path)
    video_dir = tmp_path / "videos" / video.bvid
    video_dir.mkdir(parents=True, exist_ok=True)

    # mock 所有外部依赖
    with patch(
        "plugins.bilibili_toolkit_builtin.workflow.pipeline.get_playurl_streams",
        new_callable=AsyncMock,
    ) as mock_playurl, patch(
        "plugins.bilibili_toolkit_builtin.workflow.pipeline.select_best_stream"
    ) as mock_select, patch(
        "plugins.bilibili_toolkit_builtin.workflow.pipeline.download_with_backup",
        new_callable=AsyncMock,
    ) as mock_download, patch(
        "plugins.bilibili_toolkit_builtin.workflow.pipeline.merge_video_audio",
        new_callable=AsyncMock,
    ) as mock_merge, patch(
        "plugins.bilibili_toolkit_builtin.workflow.pipeline.fetch_danmaku",
        new_callable=AsyncMock,
    ) as mock_fetch, patch(
        "plugins.bilibili_toolkit_builtin.workflow.pipeline.render_ass"
    ) as mock_render, patch(
        "plugins.bilibili_toolkit_builtin.workflow.pipeline.save_subtitle",
        new_callable=AsyncMock,
    ) as mock_subtitle, patch(
        "plugins.bilibili_toolkit_builtin.workflow.pipeline.render_movie_nfo"
    ) as mock_movie_nfo:
        # playurl 返回任意 DashStreams（实际不解析，select_best_stream 返回 MixedStream）
        mock_playurl.return_value = MagicMock()
        # select_best_stream 返回 MixedStream（单混合流，无需 ffmpeg 合并）
        from plugins.bilibili_toolkit_builtin.analyzer import MixedStream
        mock_select.return_value = MixedStream(url="https://example.com/v.mp4")
        # download_with_backup 写入 dummy 文件
        async def _fake_download(urls, dest_path, **kwargs):
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            dest_path.write_bytes(b"fake video bytes")
            return str(dest_path)
        mock_download.side_effect = _fake_download
        # 弹幕返回非空列表，render_ass 返回 ASS 字符串
        mock_fetch.return_value = [MagicMock()]
        mock_render.return_value = "[V4+ Styles]\nDialogue: 0,0:00,0:01,Default,,Test"
        # 字幕返回 1 个 Path
        mock_subtitle.return_value = [tmp_path / "sub.srt"]
        # NFO 返回 XML 字符串
        mock_movie_nfo.return_value = "<movie></movie>"

        result: WorkflowResult = await download_page(client, video, page, config, video_dir)

    # 验证位图：5 路子任务全部 Succeeded
    assert get_subtask_status(result.status, SubTask.Cover) == SubTaskState.Succeeded
    assert get_subtask_status(result.status, SubTask.Video) == SubTaskState.Succeeded
    assert get_subtask_status(result.status, SubTask.Nfo) == SubTaskState.Succeeded
    assert get_subtask_status(result.status, SubTask.Danmaku) == SubTaskState.Succeeded
    assert get_subtask_status(result.status, SubTask.Subtitle) == SubTaskState.Succeeded
    # video_id / page_id 应正确填充
    assert result.video_id == video.bvid
    assert result.page_id == page.cid
    # error 应为 None（无失败）
    assert result.error is None
    # files 列表应包含封面、视频、NFO、弹幕文件
    assert len(result.files) >= 3
    # 关键 mock 应被调用
    mock_playurl.assert_awaited_once_with(client, video.bvid, page.cid)
    mock_download.assert_awaited()
    mock_fetch.assert_awaited_once()


@pytest.mark.asyncio
async def test_download_page_danmaku_ignored_when_empty(tmp_path: Path):
    """弹幕为空时 Danmaku 子任务应为 Ignored 状态（不计入失败）。"""
    client = _make_mock_client()
    video = _make_video_info()
    page = video.pages[0]
    config = _make_default_config(tmp_path)
    video_dir = tmp_path / "videos" / video.bvid
    video_dir.mkdir(parents=True, exist_ok=True)

    with patch(
        "plugins.bilibili_toolkit_builtin.workflow.pipeline.get_playurl_streams",
        new_callable=AsyncMock,
    ) as mock_playurl, patch(
        "plugins.bilibili_toolkit_builtin.workflow.pipeline.select_best_stream"
    ) as mock_select, patch(
        "plugins.bilibili_toolkit_builtin.workflow.pipeline.download_with_backup",
        new_callable=AsyncMock,
    ) as mock_download, patch(
        "plugins.bilibili_toolkit_builtin.workflow.pipeline.merge_video_audio",
        new_callable=AsyncMock,
    ), patch(
        "plugins.bilibili_toolkit_builtin.workflow.pipeline.fetch_danmaku",
        new_callable=AsyncMock,
    ) as mock_fetch, patch(
        "plugins.bilibili_toolkit_builtin.workflow.pipeline.save_subtitle",
        new_callable=AsyncMock,
    ) as mock_subtitle, patch(
        "plugins.bilibili_toolkit_builtin.workflow.pipeline.render_movie_nfo"
    ) as mock_movie_nfo:
        mock_playurl.return_value = MagicMock()
        from plugins.bilibili_toolkit_builtin.analyzer import MixedStream
        mock_select.return_value = MixedStream(url="https://example.com/v.mp4")
        async def _fake_download(urls, dest_path, **kwargs):
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            dest_path.write_bytes(b"data")
            return str(dest_path)
        mock_download.side_effect = _fake_download
        # 弹幕为空 → 应标记为 Ignored
        mock_fetch.return_value = []
        # 字幕为空 → 应标记为 Ignored
        mock_subtitle.return_value = []
        mock_movie_nfo.return_value = "<movie></movie>"

        result = await download_page(client, video, page, config, video_dir)

    # 弹幕与字幕应为 Ignored（非 Failed）
    assert get_subtask_status(result.status, SubTask.Danmaku) == SubTaskState.Ignored
    assert get_subtask_status(result.status, SubTask.Subtitle) == SubTaskState.Ignored
    # 其他子任务仍应成功
    assert get_subtask_status(result.status, SubTask.Cover) == SubTaskState.Succeeded
    assert get_subtask_status(result.status, SubTask.Video) == SubTaskState.Succeeded
    assert get_subtask_status(result.status, SubTask.Nfo) == SubTaskState.Succeeded
    # error 仍为 None（无失败）
    assert result.error is None


@pytest.mark.asyncio
async def test_download_page_video_subtask_failure_marks_failed(tmp_path: Path):
    """playurl 解析失败时 Video 子任务应标记为 Failed，其他子任务仍执行。"""
    client = _make_mock_client()
    video = _make_video_info()
    page = video.pages[0]
    config = _make_default_config(tmp_path)
    video_dir = tmp_path / "videos" / video.bvid
    video_dir.mkdir(parents=True, exist_ok=True)

    with patch(
        "plugins.bilibili_toolkit_builtin.workflow.pipeline.get_playurl_streams",
        new_callable=AsyncMock,
    ) as mock_playurl, patch(
        "plugins.bilibili_toolkit_builtin.workflow.pipeline.select_best_stream"
    ) as mock_select, patch(
        "plugins.bilibili_toolkit_builtin.workflow.pipeline.download_with_backup",
        new_callable=AsyncMock,
    ) as mock_download, patch(
        "plugins.bilibili_toolkit_builtin.workflow.pipeline.fetch_danmaku",
        new_callable=AsyncMock,
    ) as mock_fetch, patch(
        "plugins.bilibili_toolkit_builtin.workflow.pipeline.save_subtitle",
        new_callable=AsyncMock,
    ) as mock_subtitle, patch(
        "plugins.bilibili_toolkit_builtin.workflow.pipeline.render_movie_nfo"
    ) as mock_movie_nfo:
        # playurl 抛非风控异常 → Video 子任务 Failed
        mock_playurl.side_effect = RuntimeError("playurl network error")
        # select_best_stream 不应被调用（playurl 失败后流程提前 return）
        from plugins.bilibili_toolkit_builtin.analyzer import MixedStream
        mock_select.return_value = MixedStream(url="https://example.com/v.mp4")
        async def _fake_download(urls, dest_path, **kwargs):
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            dest_path.write_bytes(b"data")
            return str(dest_path)
        mock_download.side_effect = _fake_download
        mock_fetch.return_value = [MagicMock()]
        mock_subtitle.return_value = []
        mock_movie_nfo.return_value = "<movie></movie>"

        result = await download_page(client, video, page, config, video_dir)

    # Video 子任务应为 Failed
    assert get_subtask_status(result.status, SubTask.Video) == SubTaskState.Failed
    # 其他子任务仍应正常执行
    assert get_subtask_status(result.status, SubTask.Cover) == SubTaskState.Succeeded
    assert get_subtask_status(result.status, SubTask.Nfo) == SubTaskState.Succeeded
    assert get_subtask_status(result.status, SubTask.Danmaku) == SubTaskState.Succeeded


@pytest.mark.asyncio
async def test_download_page_skip_option_marks_skipped(tmp_path: Path):
    """skip_option 配置应让对应子任务标记为 Skipped，且不调用对应 mock。"""
    client = _make_mock_client()
    video = _make_video_info()
    page = video.pages[0]
    config = _make_default_config(tmp_path)
    # 跳过封面、弹幕、字幕
    config["skip_option"] = {
        "no_poster": True,
        "no_danmaku": True,
        "no_subtitle": True,
    }
    video_dir = tmp_path / "videos" / video.bvid
    video_dir.mkdir(parents=True, exist_ok=True)

    with patch(
        "plugins.bilibili_toolkit_builtin.workflow.pipeline.get_playurl_streams",
        new_callable=AsyncMock,
    ) as mock_playurl, patch(
        "plugins.bilibili_toolkit_builtin.workflow.pipeline.select_best_stream"
    ) as mock_select, patch(
        "plugins.bilibili_toolkit_builtin.workflow.pipeline.download_with_backup",
        new_callable=AsyncMock,
    ) as mock_download, patch(
        "plugins.bilibili_toolkit_builtin.workflow.pipeline.merge_video_audio",
        new_callable=AsyncMock,
    ), patch(
        "plugins.bilibili_toolkit_builtin.workflow.pipeline.fetch_danmaku",
        new_callable=AsyncMock,
    ) as mock_fetch, patch(
        "plugins.bilibili_toolkit_builtin.workflow.pipeline.save_subtitle",
        new_callable=AsyncMock,
    ) as mock_subtitle, patch(
        "plugins.bilibili_toolkit_builtin.workflow.pipeline.render_movie_nfo"
    ) as mock_movie_nfo:
        mock_playurl.return_value = MagicMock()
        from plugins.bilibili_toolkit_builtin.analyzer import MixedStream
        mock_select.return_value = MixedStream(url="https://example.com/v.mp4")
        async def _fake_download(urls, dest_path, **kwargs):
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            dest_path.write_bytes(b"data")
            return str(dest_path)
        mock_download.side_effect = _fake_download
        mock_movie_nfo.return_value = "<movie></movie>"

        result = await download_page(client, video, page, config, video_dir)

    # 被跳过的子任务应为 Skipped
    assert get_subtask_status(result.status, SubTask.Cover) == SubTaskState.Skipped
    assert get_subtask_status(result.status, SubTask.Danmaku) == SubTaskState.Skipped
    assert get_subtask_status(result.status, SubTask.Subtitle) == SubTaskState.Skipped
    # 未跳过的子任务应执行
    assert get_subtask_status(result.status, SubTask.Video) == SubTaskState.Succeeded
    assert get_subtask_status(result.status, SubTask.Nfo) == SubTaskState.Succeeded
    # 被跳过的子任务对应 mock 不应被调用
    mock_fetch.assert_not_awaited()
    mock_subtitle.assert_not_awaited()


@pytest.mark.asyncio
async def test_download_page_risk_control_terminates_subtasks(tmp_path: Path):
    """任一子任务抛 RiskControlError 时应触发风控熔断，error 字段含 risk_control 前缀。"""
    client = _make_mock_client()
    video = _make_video_info()
    page = video.pages[0]
    config = _make_default_config(tmp_path)
    video_dir = tmp_path / "videos" / video.bvid
    video_dir.mkdir(parents=True, exist_ok=True)

    with patch(
        "plugins.bilibili_toolkit_builtin.workflow.pipeline.get_playurl_streams",
        new_callable=AsyncMock,
    ) as mock_playurl:
        # playurl 抛 RiskControlError → Video 子任务触发熔断
        mock_playurl.side_effect = RiskControlError(
            reason="http_status", code=412, raw_response=""
        )

        result = await download_page(client, video, page, config, video_dir)

    # error 应含 risk_control 前缀
    assert result.error is not None
    assert result.error.startswith("risk_control:")
    assert "http_status" in result.error
    # 风控熔断时未完成的子任务保持 Skipped
    # Video 子任务在 gather 中抛异常，不会被标记为 Succeeded，应保持 Skipped
    assert get_subtask_status(result.status, SubTask.Video) == SubTaskState.Skipped


# ---------------------------------------------------------------------------
# download_video 测试
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_download_video_returns_one_result_per_page(tmp_path: Path):
    """download_video 应返回每个分 P 一个 WorkflowResult。"""
    client = _make_mock_client()
    # 多 P 视频（3 个分 P）
    video = _make_video_info(pages_count=3)
    config = _make_default_config(tmp_path)

    # mock download_page 返回成功结果
    async def _fake_download_page(client, v, p, cfg, video_dir):
        return WorkflowResult(
            video_id=v.bvid,
            page_id=p.cid,
            status=set_subtask_status(
                INITIAL_STATUS, SubTask.Video, SubTaskState.Succeeded
            ),
            files=[],
        )

    with patch(
        "plugins.bilibili_toolkit_builtin.workflow.pipeline.download_page",
        new=_fake_download_page,
    ), patch(
        "plugins.bilibili_toolkit_builtin.workflow.pipeline.save_upper_avatar",
        new_callable=AsyncMock,
    ) as mock_avatar:
        mock_avatar.return_value = None
        # 跳过 TVShow NFO（无 no_video_nfo 但单层 mock 即可，多 P 时会调用）
        with patch(
            "plugins.bilibili_toolkit_builtin.workflow.pipeline.render_tvshow_nfo"
        ) as mock_tvshow:
            mock_tvshow.return_value = "<tvshow></tvshow>"

            results = await download_video(client, video, config, tmp_path)

    # 3 个分 P 应返回 3 个 WorkflowResult
    assert len(results) == 3
    # 每个 result 的 video_id 应为视频 bvid
    for r in results:
        assert r.video_id == video.bvid
    # page_id 应分别对应 3 个分 P 的 cid
    page_ids = [r.page_id for r in results]
    expected_cids = [p.cid for p in video.pages]
    assert page_ids == expected_cids


@pytest.mark.asyncio
async def test_download_video_empty_pages_returns_empty(tmp_path: Path):
    """视频无分 P 时 download_video 应返回空列表。"""
    client = _make_mock_client()
    video = _make_video_info(pages_count=1)
    video.pages = []  # 强制无分 P
    config = _make_default_config(tmp_path)

    with patch(
        "plugins.bilibili_toolkit_builtin.workflow.pipeline.save_upper_avatar",
        new_callable=AsyncMock,
    ):
        results = await download_video(client, video, config, tmp_path)

    assert results == []


@pytest.mark.asyncio
async def test_download_video_runs_upper_avatar_subtask(tmp_path: Path):
    """download_video 应执行 UP 主头像下载子任务（视频层任务）。"""
    client = _make_mock_client()
    video = _make_video_info()
    config = _make_default_config(tmp_path)

    async def _fake_download_page(client, v, p, cfg, video_dir):
        return WorkflowResult(video_id=v.bvid, page_id=p.cid)

    with patch(
        "plugins.bilibili_toolkit_builtin.workflow.pipeline.download_page",
        new=_fake_download_page,
    ), patch(
        "plugins.bilibili_toolkit_builtin.workflow.pipeline.save_upper_avatar",
        new_callable=AsyncMock,
    ) as mock_avatar:
        mock_avatar.return_value = None

        await download_video(client, video, config, tmp_path)

    # UP 主头像子任务应被调用一次
    mock_avatar.assert_awaited_once()
    # 调用参数应包含 upper_mid / upper_name / avatar_url / upper_root
    # 注意：pipeline._download_upper_avatar_subtask 通过关键字参数调用 save_upper_avatar
    call_args = mock_avatar.await_args
    assert call_args.kwargs["upper_mid"] == video.upper_mid
    assert call_args.kwargs["upper_name"] == video.upper_name
    assert call_args.kwargs["avatar_url"] == video.upper_face


@pytest.mark.asyncio
async def test_download_video_skip_upper_avatar_when_no_upper(tmp_path: Path):
    """upper_mid 或 upper_face 为空时应跳过 UP 主头像子任务。"""
    client = _make_mock_client()
    video = _make_video_info()
    video.upper_mid = 0  # 无 UP 主信息
    config = _make_default_config(tmp_path)

    async def _fake_download_page(client, v, p, cfg, video_dir):
        return WorkflowResult(video_id=v.bvid, page_id=p.cid)

    with patch(
        "plugins.bilibili_toolkit_builtin.workflow.pipeline.download_page",
        new=_fake_download_page,
    ), patch(
        "plugins.bilibili_toolkit_builtin.workflow.pipeline.save_upper_avatar",
        new_callable=AsyncMock,
    ) as mock_avatar:
        await download_video(client, video, config, tmp_path)

    # UP 主头像子任务不应被调用
    mock_avatar.assert_not_awaited()


@pytest.mark.asyncio
async def test_download_video_concurrent_pages_respect_semaphore(tmp_path: Path):
    """多 P 视频应通过 Semaphore 限制并发数，所有分 P 最终完成。"""
    client = _make_mock_client()
    # 5 个分 P
    video = _make_video_info(pages_count=5)
    # concurrent_limit.page = 2
    config = _make_default_config(tmp_path)

    # 记录并发执行数
    current_concurrent = 0
    max_concurrent = 0

    async def _fake_download_page(client, v, p, cfg, video_dir):
        nonlocal current_concurrent, max_concurrent
        current_concurrent += 1
        max_concurrent = max(max_concurrent, current_concurrent)
        # 模拟下载耗时
        await asyncio.sleep(0.05)
        current_concurrent -= 1
        return WorkflowResult(video_id=v.bvid, page_id=p.cid)

    with patch(
        "plugins.bilibili_toolkit_builtin.workflow.pipeline.download_page",
        new=_fake_download_page,
    ), patch(
        "plugins.bilibili_toolkit_builtin.workflow.pipeline.save_upper_avatar",
        new_callable=AsyncMock,
    ), patch(
        "plugins.bilibili_toolkit_builtin.workflow.pipeline.render_tvshow_nfo"
    ) as mock_tvshow:
        mock_tvshow.return_value = "<tvshow></tvshow>"

        results = await download_video(client, video, config, tmp_path)

    # 所有分 P 都应完成
    assert len(results) == 5
    # 并发数不应超过配置的 page=2
    assert max_concurrent <= 2
    # 至少有一次并发（如果完全串行 max_concurrent=1）
    # 这里允许 1 或 2，关键是不超过 2
    assert max_concurrent >= 1
