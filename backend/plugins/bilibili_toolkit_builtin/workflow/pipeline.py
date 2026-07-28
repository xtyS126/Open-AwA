"""下载流水线编排核心。

实现单个视频与单个分 P 的下载编排，含 5 路并发子任务、状态位图
更新与风控熔断。

5 路并发子任务（对应 :class:`SubTask` 位图的 5 个槽位）：

- **Cover**：分 P 封面下载（使用视频封面 URL，落到 ``{base_name}.jpg``）
- **Video**：playurl 解析 + 流筛选 + 下载 + ffmpeg 合并
- **Nfo**：NFO 元数据生成（单 P → Movie NFO；多 P → Episode NFO）
- **Danmaku**：弹幕 protobuf 拉取 + ASS 渲染
- **Subtitle**：字幕列表获取 + SRT 转换

风控熔断：任一子任务抛 :class:`RiskControlError` 时，``asyncio.gather``
自动取消其他子任务，主流程捕获后保留已完成子任务的位图，未完成的
子任务保持 ``Skipped`` 状态。

失败不阻塞：除风控异常外，子任务失败仅标记自身为 ``Failed``，不影响
其他子任务继续执行。

参考实现：``bili-sync/crates/bili_sync/src/workflow.rs`` 的
``download_video_pages`` / ``dispatch_download_page`` / ``download_page``。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Optional

from loguru import logger
from pydantic import BaseModel, Field

from ..analyzer import (
    BestStream,
    FilterOption,
    MixedStream,
    VideoAudioStream,
    select_best_stream,
    sort_all_urls,
)
from ..bilibili.client import DEFAULT_USER_AGENT, BilibiliClient
from ..bilibili.risk_control import RiskControlError
from ..bilibili.video import Page, VideoInfo, get_playurl_streams
from ..danmaku import DanmakuOption, fetch_danmaku, render_ass
from ..downloader import download_with_backup
from ..merger import MergeFailedError, merge_video_audio
from ..nfo import (
    render_episode_nfo,
    render_movie_nfo,
    render_tvshow_nfo,
    save_upper_avatar,
)
from ..path_template import PathTemplateError, build_page_path, build_video_path
from ..status import INITIAL_STATUS, SubTask, SubTaskState, set_subtask_status
from ..subtitle import save_subtitle

# 默认视频文件扩展名
_VIDEO_EXTENSION: str = ".mp4"

# 默认封面文件扩展名
_COVER_EXTENSION: str = ".jpg"

# 默认 NFO 文件扩展名
_NFO_EXTENSION: str = ".nfo"

# 默认 ASS 弹幕文件扩展名
_DANMAKU_EXTENSION: str = ".ass"

# 默认字幕文件扩展名
_SUBTITLE_EXTENSION: str = ".srt"

# 默认视频/封面下载请求头（Referer 设置为 B 站主页以绕过基础防盗链）
_DOWNLOAD_HEADERS: dict[str, str] = {
    "User-Agent": DEFAULT_USER_AGENT,
    "Referer": "https://www.bilibili.com/",
}

# 默认并发分块下载阈值（20MB），与 schema.json 默认值一致
_DEFAULT_CONCURRENT_THRESHOLD: int = 20 * 1024 * 1024

# 默认下载超时（秒）
_DEFAULT_DOWNLOAD_TIMEOUT: float = 60.0

# 默认分 P 并发数，与 schema.json 默认值一致
_DEFAULT_PAGE_CONCURRENCY: int = 2

# TVShow NFO 文件名（多 P 视频根目录）
_TVSHOW_NFO_FILENAME: str = "tvshow.nfo"


class WorkflowResult(BaseModel):
    """单次下载任务结果（分页级）。

    作为 workflow 层向上层返回的纯数据载体，不在 workflow 层写库。
    持久化由上层路由（阶段 15）根据 :attr:`status` 位图与 :attr:`files`
    列表处理。

    Attributes:
        video_id: 视频 BV 号。
        page_id: 分 P cid。``None`` 表示视频级任务（当前实现中分页层
            5 路子任务均填充 page_id）。
        status: 子任务状态位图（5 子任务 × 2 bit = 10 bit）。
            初始为 :data:`status.INITIAL_STATUS` (0)，表示所有子任务均为
            ``Skipped``。每个子任务完成后通过 :func:`set_subtask_status`
            不可变更新。
        error: 失败原因摘要。风控熔断时填充 ``risk_control: {reason}``；
            其他异常不填充（子任务级失败通过位图体现）。
        files: 已产出文件的路径列表（字符串形式）。仅包含成功完成的
            子任务产出的文件。
    """

    video_id: str = Field(..., description="视频 BV 号")
    page_id: Optional[int] = Field(default=None, description="分 P cid，None 表示视频级任务")
    status: int = Field(default=INITIAL_STATUS, description="子任务状态位图")
    error: Optional[str] = Field(default=None, description="失败原因摘要")
    files: list[str] = Field(default_factory=list, description="已产出文件路径列表")


class WorkflowError(Exception):
    """下载流水线异常。

    携带 ``reason`` 标识用于上层判断错误类型（如路径模板渲染失败、
    配置缺失等）。

    Attributes:
        reason: 失败原因标识，如 ``path_template_error`` /
            ``config_invalid`` / ``no_pages``。
    """

    def __init__(self, reason: str, message: str = "") -> None:
        self.reason: str = reason
        super().__init__(message or reason)


async def download_video(
    client: BilibiliClient,
    video: VideoInfo,
    config: dict[str, Any],
    base_dir: Path,
) -> list[WorkflowResult]:
    """下载单个视频的所有分 P。

    流程：
    1. 渲染视频目录路径（:func:`build_video_path`）
    2. 视频层并发任务（``asyncio.gather``）：
       - UP 主头像 + Person NFO（:func:`save_upper_avatar`，``no_upper``
         跳过时省略）
       - TVShow NFO（多 P 视频时生成 ``tvshow.nfo``）
    3. 分页层：对每个 :class:`Page` 调用 :func:`download_page`，按
       ``concurrent_limit.page`` 并发数限制
    4. 收集所有 :class:`WorkflowResult` 返回

    风控熔断：视频层任务（UP 主头像下载）触发风控时，异常向上传播
    由 :func:`download_subscription` 处理订阅级熔断。

    Args:
        client: B 站异步客户端。
        video: 视频元信息（含 pages 列表）。
        config: 插件配置 dict（含 ``video_name`` / ``page_name`` /
            ``upper_path`` / ``skip_option`` / ``concurrent_limit`` 等字段）。
        base_dir: 视频根目录（如 ``videos/``）。

    Returns:
        各分 P 的 :class:`WorkflowResult` 列表，按 ``page.page`` 顺序排列。
        视频无 pages 时返回空列表。

    Raises:
        WorkflowError: 视频目录路径模板渲染失败时抛出。
        RiskControlError: 视频层任务触发风控时抛出。
    """
    # 1. 渲染视频目录路径
    video_name_template: str = config.get("video_name") or "{{title}}"
    try:
        video_dir: Path = build_video_path(video_name_template, base_dir, video)
    except PathTemplateError as exc:
        raise WorkflowError(
            reason="path_template_error",
            message=f"视频目录模板渲染失败: bvid={video.bvid}, template={exc.template}",
        ) from exc
    video_dir.mkdir(parents=True, exist_ok=True)

    # 2. 视频层并发任务：UP 主头像 + TVShow NFO（多 P 时）
    skip_option: dict[str, Any] = config.get("skip_option") or {}
    video_layer_tasks: list[Any] = []

    # UP 主头像 + Person NFO
    if not skip_option.get("no_upper") and video.upper_mid and video.upper_face:
        upper_root_name: str = config.get("upper_path") or "upers"
        upper_root: Path = base_dir / upper_root_name
        video_layer_tasks.append(
            _download_upper_avatar_subtask(
                upper_mid=video.upper_mid,
                upper_name=video.upper_name,
                avatar_url=video.upper_face,
                upper_root=upper_root,
            )
        )

    # TVShow NFO（多 P 视频时）
    is_multi_page: bool = len(video.pages) > 1
    if is_multi_page and not skip_option.get("no_video_nfo"):
        tvshow_nfo_path: Path = video_dir / _TVSHOW_NFO_FILENAME
        video_layer_tasks.append(
            _write_tvshow_nfo_subtask(video, tvshow_nfo_path)
        )

    # 执行视频层任务（任一风控异常向上传播）
    if video_layer_tasks:
        await asyncio.gather(*video_layer_tasks)

    # 3. 分页层：对每个 page 调用 download_page
    if not video.pages:
        logger.warning("视频无分 P，跳过下载: bvid={}", video.bvid)
        return []

    concurrent_limit: dict[str, Any] = config.get("concurrent_limit") or {}
    page_concurrency: int = max(
        1, int(concurrent_limit.get("page") or _DEFAULT_PAGE_CONCURRENCY)
    )

    # 用 Semaphore 限制分 P 并发数
    semaphore: asyncio.Semaphore = asyncio.Semaphore(page_concurrency)

    async def _run_page(page: Page) -> WorkflowResult:
        """单分 P 下载任务，受 semaphore 限流。"""
        async with semaphore:
            return await download_page(client, video, page, config, video_dir)

    results: list[WorkflowResult] = await asyncio.gather(
        *[_run_page(p) for p in video.pages]
    )
    return list(results)


async def download_page(
    client: BilibiliClient,
    video: VideoInfo,
    page: Page,
    config: dict[str, Any],
    video_dir: Path,
) -> WorkflowResult:
    """下载单个分 P 的 5 路子任务。

    5 路并发子任务（对应 :class:`SubTask` 位图）：

    - **Cover**：分 P 封面（使用 ``video.cover`` URL）
    - **Video**：playurl 解析 + 流筛选 + 下载 + ffmpeg 合并
    - **Nfo**：NFO 元数据（单 P → Movie NFO；多 P → Episode NFO）
    - **Danmaku**：弹幕 protobuf 拉取 + ASS 渲染
    - **Subtitle**：字幕列表获取 + SRT 转换

    每子任务独立捕获非风控异常，失败仅标记自身为 ``Failed``，不影响
    其他子任务。任一子任务抛 :class:`RiskControlError` 时
    ``asyncio.gather`` 自动取消其他子任务，主流程捕获后保留已完成
    子任务的位图，未完成的子任务保持 ``Skipped`` 状态。

    Args:
        client: B 站异步客户端。
        video: 视频元信息。
        page: 分 P 信息。
        config: 插件配置 dict。
        video_dir: 视频目录路径（由 :func:`download_video` 通过
            :func:`build_video_path` 渲染）。

    Returns:
        该分 P 的 :class:`WorkflowResult`，含位图与产出文件列表。
    """
    # 初始化位图与产出文件列表
    status: int = INITIAL_STATUS
    files: list[str] = []

    # 解析 skip_option
    skip_option: dict[str, Any] = config.get("skip_option") or {}

    # 渲染分 P 文件名（不含扩展名）
    page_name_template: str = config.get("page_name") or "{{bvid}}"
    try:
        base_name_path: Path = build_page_path(
            page_name_template, video_dir, video, page
        )
    except PathTemplateError as exc:
        # 模板渲染失败属于配置问题，整页标记为 Failed
        return WorkflowResult(
            video_id=video.bvid,
            page_id=page.cid,
            status=set_subtask_status(status, SubTask.Video, SubTaskState.Failed),
            error=f"path_template_error: {exc}",
            files=files,
        )
    base_name: str = base_name_path.name

    # 构造各子任务输出路径
    cover_path: Path = video_dir / f"{base_name}{_COVER_EXTENSION}"
    video_path: Path = video_dir / f"{base_name}{_VIDEO_EXTENSION}"
    nfo_path: Path = video_dir / f"{base_name}{_NFO_EXTENSION}"
    danmaku_path: Path = video_dir / f"{base_name}{_DANMAKU_EXTENSION}"

    # 预先标记跳过的子任务
    skip_cover: bool = bool(skip_option.get("no_poster"))
    skip_nfo: bool = bool(skip_option.get("no_video_nfo"))
    skip_danmaku: bool = bool(skip_option.get("no_danmaku"))
    skip_subtitle: bool = bool(skip_option.get("no_subtitle"))

    if skip_cover:
        status = set_subtask_status(status, SubTask.Cover, SubTaskState.Skipped)
    if skip_nfo:
        status = set_subtask_status(status, SubTask.Nfo, SubTaskState.Skipped)
    if skip_danmaku:
        status = set_subtask_status(status, SubTask.Danmaku, SubTaskState.Skipped)
    if skip_subtitle:
        status = set_subtask_status(status, SubTask.Subtitle, SubTaskState.Skipped)

    # 构造 5 路子任务协程列表：(子任务枚举, 协程, 成功时记录的文件路径)
    subtask_coros: list[tuple[SubTask, Any, Optional[Path]]] = []

    if not skip_cover:
        subtask_coros.append((
            SubTask.Cover,
            _download_cover_subtask(video, page, config, cover_path),
            cover_path,
        ))

    subtask_coros.append((
        SubTask.Video,
        _download_video_subtask(client, video, page, config, video_path),
        video_path,
    ))

    if not skip_nfo:
        subtask_coros.append((
            SubTask.Nfo,
            _download_nfo_subtask(video, page, config, nfo_path),
            nfo_path,
        ))

    if not skip_danmaku:
        subtask_coros.append((
            SubTask.Danmaku,
            _download_danmaku_subtask(client, video, page, config, danmaku_path),
            danmaku_path,
        ))

    if not skip_subtitle:
        subtask_coros.append((
            SubTask.Subtitle,
            _download_subtitle_subtask(
                client, video, page, config, video_dir, base_name
            ),
            None,  # 字幕可能多文件，由 _scan_subtitle_files 扫描
        ))

    # 并发执行 5 路子任务
    # asyncio.gather 默认 return_exceptions=False，任一异常立即传播
    # 子任务内部已捕获非风控异常，仅 RiskControlError 会向上传播
    try:
        results: list[SubTaskState] = await asyncio.gather(
            *[coro for _, coro, _ in subtask_coros]
        )
    except RiskControlError as exc:
        # 风控熔断：其他子任务已被 asyncio.gather 自动取消
        # 保留当前位图（已跳过的子任务已标记），未完成的子任务保持 Skipped
        logger.warning(
            "分页下载触发风控熔断: bvid={}, cid={}, reason={}, code={}",
            video.bvid,
            page.cid,
            exc.reason,
            exc.code,
        )
        return WorkflowResult(
            video_id=video.bvid,
            page_id=page.cid,
            status=status,
            error=f"risk_control: {exc.reason}",
            files=files,
        )

    # 更新位图与文件列表
    for (subtask, _, file_path), state in zip(subtask_coros, results):
        status = set_subtask_status(status, subtask, state)
        if state == SubTaskState.Succeeded:
            if file_path is not None:
                files.append(str(file_path))
            # 字幕子任务成功时扫描产出文件
            if subtask == SubTask.Subtitle:
                subtitle_files = _scan_subtitle_files(video_dir, base_name)
                files.extend(str(p) for p in subtitle_files)

    return WorkflowResult(
        video_id=video.bvid,
        page_id=page.cid,
        status=status,
        files=files,
    )


async def _download_cover_subtask(
    video: VideoInfo,
    page: Page,
    config: dict[str, Any],
    output_path: Path,
) -> SubTaskState:
    """下载分 P 封面子任务。

    使用 ``video.cover`` URL 下载封面到 ``output_path``。封面 URL 为空
    或下载失败时返回 :class:`SubTaskState.Failed`。

    Args:
        video: 视频元信息（使用 ``video.cover`` 字段）。
        page: 分 P 信息（当前仅用于日志）。
        config: 插件配置 dict（当前未使用，保留以统一子任务签名）。
        output_path: 封面输出路径。

    Returns:
        :class:`SubTaskState.Succeeded` 表示成功；``Failed`` 表示失败。
    """
    if not video.cover:
        logger.warning("封面 URL 为空，跳过: bvid={}", video.bvid)
        return SubTaskState.Failed

    try:
        await download_with_backup(
            urls=[video.cover],
            dest_path=output_path,
            headers=_DOWNLOAD_HEADERS,
            timeout=_DEFAULT_DOWNLOAD_TIMEOUT,
        )
        logger.debug(
            "封面下载成功: bvid={}, cid={}, dest={}",
            video.bvid,
            page.cid,
            output_path,
        )
        return SubTaskState.Succeeded
    except RiskControlError:
        # 风控异常向上传播触发熔断
        raise
    except Exception as exc:
        # 非风控异常仅记录日志，不向上传播，避免阻塞其他子任务
        logger.warning(
            "封面下载失败: bvid={}, cid={}, error={}: {}",
            video.bvid,
            page.cid,
            type(exc).__name__,
            exc,
        )
        return SubTaskState.Failed


async def _download_video_subtask(
    client: BilibiliClient,
    video: VideoInfo,
    page: Page,
    config: dict[str, Any],
    output_path: Path,
) -> SubTaskState:
    """下载视频流子任务（playurl + 流筛选 + 下载 + 合并）。

    流程：
    1. 调用 :func:`get_playurl_streams` 获取流容器
    2. 调用 :func:`select_best_stream` 选择最佳流
    3. 根据流类型分支：
       - :class:`MixedStream`：单混合流，直接下载到 ``output_path``
       - :class:`VideoAudioStream`：DASH 分离流，分别下载视频/音频到
         临时文件后调用 :func:`merge_video_audio` 合并到 ``output_path``
    4. 下载使用 :func:`download_with_backup` 多 URL 容错

    风控异常（ :class:`RiskControlError`）不在此捕获，向上传播触发
    :func:`download_page` 的风控熔断。

    Args:
        client: B 站客户端。
        video: 视频元信息（使用 ``bvid`` 字段）。
        page: 分 P 信息（使用 ``cid`` 字段）。
        config: 插件配置 dict（使用 ``filter_option`` /
            ``concurrent_limit.download`` / ``cdn_sorting`` 字段）。
        output_path: 视频输出路径。

    Returns:
        :class:`SubTaskState.Succeeded` 表示成功；``Failed`` 表示失败
        （流解析失败、下载失败、合并失败等）。
    """
    try:
        # 1. 获取 playurl 流
        dash_streams = await get_playurl_streams(client, video.bvid, page.cid)
    except RiskControlError:
        # 风控异常向上传播触发熔断
        raise
    except Exception as exc:
        logger.warning(
            "playurl 解析失败: bvid={}, cid={}, error={}: {}",
            video.bvid,
            page.cid,
            type(exc).__name__,
            exc,
        )
        return SubTaskState.Failed

    # 2. 选择最佳流
    filter_option_dict: dict[str, Any] = config.get("filter_option") or {}
    try:
        filter_option: FilterOption = FilterOption(**filter_option_dict)
    except Exception as exc:
        logger.warning(
            "FilterOption 配置异常，使用默认值: bvid={}, error={}: {}",
            video.bvid,
            type(exc).__name__,
            exc,
        )
        filter_option = FilterOption()

    try:
        best_stream: BestStream = select_best_stream(dash_streams, filter_option)
    except ValueError as exc:
        logger.warning(
            "无符合条件的流: bvid={}, cid={}, error={}",
            video.bvid,
            page.cid,
            exc,
        )
        return SubTaskState.Failed

    # 3. 解析下载配置
    concurrent_limit: dict[str, Any] = config.get("concurrent_limit") or {}
    download_config: dict[str, Any] = concurrent_limit.get("download") or {}
    concurrent_threshold: int = int(
        download_config.get("threshold") or _DEFAULT_CONCURRENT_THRESHOLD
    )
    cdn_sorting: bool = bool(config.get("cdn_sorting", True))

    # 4. 根据流类型分支下载
    try:
        if isinstance(best_stream, MixedStream):
            # 单混合流：直接下载到 output_path
            urls: list[str] = (
                sort_all_urls(best_stream.url, best_stream.backup_url)
                if cdn_sorting
                else [best_stream.url, *best_stream.backup_url]
            )
            await download_with_backup(
                urls=urls,
                dest_path=output_path,
                headers=_DOWNLOAD_HEADERS,
                timeout=_DEFAULT_DOWNLOAD_TIMEOUT,
                concurrent_threshold=concurrent_threshold,
            )
        elif isinstance(best_stream, VideoAudioStream):
            # DASH 分离流：分别下载视频/音频到临时文件后合并
            video_tmp: Path = output_path.with_suffix(
                output_path.suffix + ".video.tmp"
            )
            audio_tmp: Path = output_path.with_suffix(
                output_path.suffix + ".audio.tmp"
            )

            # 视频流下载
            video_urls: list[str] = (
                sort_all_urls(
                    best_stream.video.base_url,
                    best_stream.video.backup_url,
                )
                if cdn_sorting
                else [
                    best_stream.video.base_url,
                    *best_stream.video.backup_url,
                ]
            )
            await download_with_backup(
                urls=video_urls,
                dest_path=video_tmp,
                headers=_DOWNLOAD_HEADERS,
                timeout=_DEFAULT_DOWNLOAD_TIMEOUT,
                concurrent_threshold=concurrent_threshold,
            )

            # 音频流下载（无声视频时 audio 为 None，跳过合并）
            if best_stream.audio is not None:
                audio_urls: list[str] = (
                    sort_all_urls(
                        best_stream.audio.base_url,
                        best_stream.audio.backup_url,
                    )
                    if cdn_sorting
                    else [
                        best_stream.audio.base_url,
                        *best_stream.audio.backup_url,
                    ]
                )
                await download_with_backup(
                    urls=audio_urls,
                    dest_path=audio_tmp,
                    headers=_DOWNLOAD_HEADERS,
                    timeout=_DEFAULT_DOWNLOAD_TIMEOUT,
                    concurrent_threshold=concurrent_threshold,
                )
                # ffmpeg 合并
                await merge_video_audio(video_tmp, audio_tmp, output_path)
            else:
                # 无声视频：直接重命名视频流文件
                video_tmp.replace(output_path)
        else:
            logger.error(
                "未知流类型: bvid={}, cid={}, type={}",
                video.bvid,
                page.cid,
                type(best_stream).__name__,
            )
            return SubTaskState.Failed
    except RiskControlError:
        # 风控异常向上传播触发熔断
        raise
    except MergeFailedError as exc:
        logger.warning(
            "ffmpeg 合并失败: bvid={}, cid={}, reason={}, stderr={}",
            video.bvid,
            page.cid,
            exc.reason,
            exc.stderr[:200],
        )
        return SubTaskState.Failed
    except Exception as exc:
        logger.warning(
            "视频下载/合并失败: bvid={}, cid={}, error={}: {}",
            video.bvid,
            page.cid,
            type(exc).__name__,
            exc,
        )
        return SubTaskState.Failed

    logger.info(
        "视频下载成功: bvid={}, cid={}, dest={}",
        video.bvid,
        page.cid,
        output_path,
    )
    return SubTaskState.Succeeded


async def _download_nfo_subtask(
    video: VideoInfo,
    page: Page,
    config: dict[str, Any],
    output_path: Path,
) -> SubTaskState:
    """生成 NFO 元数据子任务。

    单 P 视频生成 Movie NFO（:func:`render_movie_nfo`），多 P 视频生成
    Episode NFO（:func:`render_episode_nfo`）。TVShow NFO 由
    :func:`download_video` 在视频层单独处理。

    Args:
        video: 视频元信息。
        page: 分 P 信息。
        config: 插件配置 dict（当前未使用，保留以统一子任务签名）。
        output_path: NFO 输出路径。

    Returns:
        :class:`SubTaskState.Succeeded` 表示成功；``Failed`` 表示失败。
    """
    # 通过 pages 数量判断单 P / 多 P
    is_multi_page: bool = len(video.pages) > 1
    try:
        if is_multi_page:
            nfo_content: str = render_episode_nfo(video, page)
        else:
            nfo_content = render_movie_nfo(video)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(nfo_content, encoding="utf-8")
        logger.debug(
            "NFO 生成成功: bvid={}, cid={}, multi_page={}, dest={}",
            video.bvid,
            page.cid,
            is_multi_page,
            output_path,
        )
        return SubTaskState.Succeeded
    except Exception as exc:
        logger.warning(
            "NFO 生成失败: bvid={}, cid={}, error={}: {}",
            video.bvid,
            page.cid,
            type(exc).__name__,
            exc,
        )
        return SubTaskState.Failed


async def _download_danmaku_subtask(
    client: BilibiliClient,
    video: VideoInfo,
    page: Page,
    config: dict[str, Any],
    output_path: Path,
) -> SubTaskState:
    """下载弹幕并渲染 ASS 子任务。

    流程：
    1. 调用 :func:`fetch_danmaku` 拉取弹幕（按 360 秒分段并发）
    2. 调用 :func:`render_ass` 渲染为 ASS 字幕字符串
    3. 落盘到 ``output_path``

    弹幕为空时返回 :class:`SubTaskState.Ignored`（不计入失败）。
    风控异常向上传播触发熔断。

    Args:
        client: B 站客户端。
        video: 视频元信息（使用 ``bvid`` 字段）。
        page: 分 P 信息（使用 ``cid`` / ``duration`` 字段）。
        config: 插件配置 dict（使用 ``danmaku_option`` 字段）。
        output_path: ASS 弹幕输出路径。

    Returns:
        :class:`SubTaskState.Succeeded` 表示成功；``Ignored`` 表示弹幕为空；
        ``Failed`` 表示失败。
    """
    duration: int = page.duration if page.duration > 0 else 0
    if duration <= 0:
        logger.warning(
            "分 P 时长为 0，跳过弹幕下载: bvid={}, cid={}",
            video.bvid,
            page.cid,
        )
        return SubTaskState.Ignored

    try:
        danmaku_list = await fetch_danmaku(
            client=client,
            bvid=video.bvid,
            cid=page.cid,
            duration=duration,
        )
    except RiskControlError:
        raise
    except Exception as exc:
        logger.warning(
            "弹幕拉取失败: bvid={}, cid={}, error={}: {}",
            video.bvid,
            page.cid,
            type(exc).__name__,
            exc,
        )
        return SubTaskState.Failed

    if not danmaku_list:
        logger.info(
            "弹幕为空，标记为 Ignored: bvid={}, cid={}",
            video.bvid,
            page.cid,
        )
        return SubTaskState.Ignored

    # 渲染 ASS
    danmaku_option_dict: dict[str, Any] = config.get("danmaku_option") or {}
    try:
        danmaku_option: DanmakuOption = DanmakuOption(**danmaku_option_dict)
    except Exception as exc:
        logger.warning(
            "DanmakuOption 配置异常，使用默认值: bvid={}, error={}: {}",
            video.bvid,
            type(exc).__name__,
            exc,
        )
        danmaku_option = DanmakuOption()

    try:
        ass_content: str = render_ass(
            danmaku_list=danmaku_list,
            duration_sec=duration,
            option=danmaku_option,
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(ass_content, encoding="utf-8")
        logger.debug(
            "弹幕渲染成功: bvid={}, cid={}, count={}, dest={}",
            video.bvid,
            page.cid,
            len(danmaku_list),
            output_path,
        )
        return SubTaskState.Succeeded
    except Exception as exc:
        logger.warning(
            "弹幕渲染失败: bvid={}, cid={}, error={}: {}",
            video.bvid,
            page.cid,
            type(exc).__name__,
            exc,
        )
        return SubTaskState.Failed


async def _download_subtitle_subtask(
    client: BilibiliClient,
    video: VideoInfo,
    page: Page,
    config: dict[str, Any],
    output_dir: Path,
    base_name: str,
) -> SubTaskState:
    """下载字幕并转 SRT 子任务。

    调用 :func:`save_subtitle` 获取字幕列表（过滤 AI 字幕）并转 SRT
    落盘。多语言字幕分别保存为 ``{base_name}.{lan}.srt``，单语言字幕
    保存为 ``{base_name}.srt``。

    无可用字幕（或全部被 AI 过滤）时返回 :class:`SubTaskState.Ignored`
    （不计入失败）。风控异常向上传播触发熔断。

    Args:
        client: B 站客户端。
        video: 视频元信息（使用 ``bvid`` 字段）。
        page: 分 P 信息（使用 ``cid`` 字段）。
        config: 插件配置 dict（当前未使用）。
        output_dir: 字幕输出目录。
        base_name: 字幕文件名前缀（不含扩展名）。

    Returns:
        :class:`SubTaskState.Succeeded` 表示成功；``Ignored`` 表示无字幕；
        ``Failed`` 表示失败。
    """
    try:
        saved_paths = await save_subtitle(
            client=client,
            bvid=video.bvid,
            cid=page.cid,
            base_name=base_name,
            output_dir=output_dir,
        )
    except RiskControlError:
        raise
    except Exception as exc:
        logger.warning(
            "字幕下载失败: bvid={}, cid={}, error={}: {}",
            video.bvid,
            page.cid,
            type(exc).__name__,
            exc,
        )
        return SubTaskState.Failed

    if not saved_paths:
        logger.info(
            "无可用字幕，标记为 Ignored: bvid={}, cid={}",
            video.bvid,
            page.cid,
        )
        return SubTaskState.Ignored

    logger.debug(
        "字幕下载成功: bvid={}, cid={}, count={}",
        video.bvid,
        page.cid,
        len(saved_paths),
    )
    return SubTaskState.Succeeded


async def _download_upper_avatar_subtask(
    upper_mid: int,
    upper_name: str,
    avatar_url: str,
    upper_root: Path,
) -> None:
    """下载 UP 主头像与 Person NFO（视频层任务）。

    调用 :func:`save_upper_avatar` 下载头像为 ``folder.jpg`` 并在同目录
    写入 ``person.nfo``。失败时仅记录日志，不影响分页层任务。

    风控异常向上传播触发 :func:`download_video` 的视频层风控熔断
    （视频层任务在分页层之前执行，风控会直接传播到
    :func:`download_subscription` 处理订阅级熔断）。

    Args:
        upper_mid: UP 主 mid。
        upper_name: UP 主名称。
        avatar_url: 头像 URL。
        upper_root: UP 主元数据根目录。
    """
    try:
        await save_upper_avatar(
            upper_mid=upper_mid,
            upper_name=upper_name,
            avatar_url=avatar_url,
            upper_root=upper_root,
        )
        logger.debug(
            "UP 主头像已保存: mid={}, name={}",
            upper_mid,
            upper_name,
        )
    except RiskControlError:
        raise
    except Exception as exc:
        # UP 主头像失败不影响视频下载，仅记录日志
        logger.warning(
            "UP 主头像下载失败: mid={}, name={}, error={}: {}",
            upper_mid,
            upper_name,
            type(exc).__name__,
            exc,
        )


async def _write_tvshow_nfo_subtask(
    video: VideoInfo,
    output_path: Path,
) -> None:
    """写入 TVShow NFO（多 P 视频层任务）。

    调用 :func:`render_tvshow_nfo` 渲染并落盘到 ``tvshow.nfo``。
    失败时仅记录日志，不影响分页层任务。

    Args:
        video: 视频元信息。
        output_path: NFO 输出路径（通常为 ``{video_dir}/tvshow.nfo``）。
    """
    try:
        nfo_content: str = render_tvshow_nfo(video)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(nfo_content, encoding="utf-8")
        logger.debug(
            "TVShow NFO 已保存: bvid={}, dest={}",
            video.bvid,
            output_path,
        )
    except Exception as exc:
        logger.warning(
            "TVShow NFO 生成失败: bvid={}, error={}: {}",
            video.bvid,
            type(exc).__name__,
            exc,
        )


def _scan_subtitle_files(output_dir: Path, base_name: str) -> list[Path]:
    """扫描字幕子任务产出的 SRT 文件。

    匹配 ``{base_name}.srt`` 与 ``{base_name}.*.srt`` 两种命名。

    Args:
        output_dir: 字幕输出目录。
        base_name: 文件名前缀。

    Returns:
        匹配到的 SRT 文件路径列表（按文件名排序）。
    """
    if not output_dir.exists():
        return []
    result: list[Path] = []
    # 单语言：{base_name}.srt
    single: Path = output_dir / f"{base_name}{_SUBTITLE_EXTENSION}"
    if single.exists():
        result.append(single)
    # 多语言：{base_name}.{lan}.srt
    for path in output_dir.glob(f"{base_name}.*{_SUBTITLE_EXTENSION}"):
        if path not in result:
            result.append(path)
    return sorted(result)
