"""订阅级下载编排。

阶段 14 实现：根据订阅类型调用对应扫描函数拉取视频列表，逐个调用
:func:`download_video` 编排下载，统一以 :class:`WorkflowResult` 列表
向上层返回结果，不在本层写库。

风控熔断：任一视频在 ``get_video_info`` 或 ``download_video`` 阶段
触发 :class:`RiskControlError` 时，立即终止本轮所有视频处理，保留
已完成视频的 :class:`WorkflowResult`，水位线不前进，下一轮调度从
原水位线重新扫描（已完成视频由上层路由根据数据库状态去重）。

水位线策略：

- **Favorite**：水位线字段 ``fav_time``（收藏时间），增量扫描
- **Submission**：水位线字段 ``pubtime``（发布时间），增量扫描，WBI 签名
- **Season / Series**：水位线字段 ``pubtime``，全量扫描（不提前停止）
- **WatchLater**：全局唯一订阅（id=1），全量扫描，不更新水位线

参考实现：``bili-sync/crates/bili_sync/src/workflow.rs`` 的
``download_subscription`` 与 ``subscribe`` 函数。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from loguru import logger

from ..bilibili.client import BilibiliClient
from ..bilibili.risk_control import RiskControlError
from ..bilibili.video import VideoInfo, get_video_info
from ..sources import (
    ScanResult,
    scan_favorite,
    scan_season,
    scan_series,
    scan_submission,
    scan_watchlater,
)
from .pipeline import WorkflowResult, download_video

# 订阅类型常量：收藏夹
SUBSCRIPTION_TYPE_FAVORITE: str = "favorite"

# 订阅类型常量：合集（Season）
SUBSCRIPTION_TYPE_SEASON: str = "season"

# 订阅类型常量：视频列表（Series）
SUBSCRIPTION_TYPE_SERIES: str = "series"

# 订阅类型常量：UP 主投稿
SUBSCRIPTION_TYPE_SUBMISSION: str = "submission"

# 订阅类型常量：稍后再看
SUBSCRIPTION_TYPE_WATCHLATER: str = "watchlater"

# 支持的订阅类型集合（用于参数校验）
_SUPPORTED_SUBSCRIPTION_TYPES: frozenset[str] = frozenset(
    {
        SUBSCRIPTION_TYPE_FAVORITE,
        SUBSCRIPTION_TYPE_SEASON,
        SUBSCRIPTION_TYPE_SERIES,
        SUBSCRIPTION_TYPE_SUBMISSION,
        SUBSCRIPTION_TYPE_WATCHLATER,
    }
)


async def download_subscription(
    client: BilibiliClient,
    subscription_type: str,
    source_id: int,
    config: dict[str, Any],
    base_dir: Path,
    latest_row_at: Optional[int] = None,
) -> tuple[list[WorkflowResult], Optional[int]]:
    """订阅级下载编排。

    流程：

    1. 根据 ``subscription_type`` 调用对应 scan 函数拉取视频列表
    2. 逐个调用 :func:`get_video_info` 补全 :class:`VideoInfo` 的 pages 列表
       （scan 返回的 :class:`ScanResult` 不含分 P 信息）
    3. 逐个调用 :func:`download_video` 编排下载（视频层 + 分页层 5 路并发）
    4. 风控熔断：任一视频触发 :class:`RiskControlError` 立即终止本轮处理
    5. 计算新的水位线（风控触发时不前进，下一轮从原水位线重新扫描）

    失败不阻塞：非风控异常（网络错误、playurl 解析失败等）仅记录日志，
    跳过该视频继续处理下一个；视频级失败通过 :class:`WorkflowResult`
    位图体现，由上层路由根据数据库状态决定重试策略。

    Args:
        client: B 站异步客户端。
        subscription_type: 订阅类型（``favorite`` / ``season`` /
            ``series`` / ``submission`` / ``watchlater``）。
        source_id: 订阅源 ID。

            - ``favorite``：收藏夹 ``media_id``
            - ``season``：合集 ``season_id``
            - ``series``：视频列表 ``series_id``
            - ``submission``：UP 主 ``upper_mid``
            - ``watchlater``：忽略（全局唯一订阅 id=1）
        config: 插件配置 dict（透传给 :func:`download_video`）。
        base_dir: 视频根目录。
        latest_row_at: 增量水位线（秒）；``None`` 表示全量扫描。

            - ``favorite``：``fav_time`` 水位线
            - ``submission``：``pubtime`` 水位线
            - ``season`` / ``series`` / ``watchlater``：忽略（全量扫描）

    Returns:
        ``(所有分 P 的 :class:`WorkflowResult` 列表, 新的水位线值)``。

        - 风控熔断时水位线保持原值 ``latest_row_at``
        - 扫描结果为空时返回 ``([], latest_row_at)``
        - ``watchlater`` 订阅始终返回原水位线（全量扫描不更新）

    Raises:
        ValueError: 不支持的订阅类型时抛出。
        RiskControlError: scan 函数本身触发风控时向上传播（不在本层捕获）。
    """
    # 1. 校验订阅类型
    if subscription_type not in _SUPPORTED_SUBSCRIPTION_TYPES:
        raise ValueError(
            f"不支持的订阅类型: {subscription_type}, 支持的类型: "
            f"{sorted(_SUPPORTED_SUBSCRIPTION_TYPES)}"
        )

    # 2. 调用对应 scan 函数拉取视频列表（scan 内部风控异常向上传播）
    scan_results: list[ScanResult] = await _scan_subscription(
        client=client,
        subscription_type=subscription_type,
        source_id=source_id,
        latest_row_at=latest_row_at,
    )

    if not scan_results:
        logger.info(
            "订阅源无新增视频: type={}, source_id={}",
            subscription_type,
            source_id,
        )
        return [], latest_row_at

    logger.info(
        "订阅源扫描完成: type={}, source_id={}, count={}, old_watermark={}",
        subscription_type,
        source_id,
        len(scan_results),
        latest_row_at,
    )

    # 3. 逐个视频下载，风控熔断时立即终止
    all_results: list[WorkflowResult] = []
    risk_control_triggered: bool = False

    for idx, scan_result in enumerate(scan_results, start=1):
        logger.info(
            "处理订阅视频 [{}/{}]: bvid={}",
            idx,
            len(scan_results),
            scan_result.bvid,
        )

        # 3.1 通过 get_video_info 补全 pages 列表
        try:
            video_info: VideoInfo = await get_video_info(client, scan_result.bvid)
        except RiskControlError as exc:
            logger.warning(
                "get_video_info 触发风控，终止订阅处理: type={}, source_id={}, "
                "bvid={}, reason={}, code={}",
                subscription_type,
                source_id,
                scan_result.bvid,
                exc.reason,
                exc.code,
            )
            risk_control_triggered = True
            break
        except Exception as exc:
            # 非风控异常仅记录日志，跳过该视频，继续处理下一个
            logger.warning(
                "get_video_info 失败，跳过该视频: bvid={}, error={}: {}",
                scan_result.bvid,
                type(exc).__name__,
                exc,
            )
            continue

        # 3.2 调用 download_video 编排下载
        try:
            page_results: list[WorkflowResult] = await download_video(
                client=client,
                video=video_info,
                config=config,
                base_dir=base_dir,
            )
            all_results.extend(page_results)

            logger.info(
                "视频下载完成: bvid={}, pages={}",
                scan_result.bvid,
                len(page_results),
            )
        except RiskControlError as exc:
            logger.warning(
                "download_video 触发风控，终止订阅处理: type={}, source_id={}, "
                "bvid={}, reason={}, code={}",
                subscription_type,
                source_id,
                scan_result.bvid,
                exc.reason,
                exc.code,
            )
            risk_control_triggered = True
            break
        except Exception as exc:
            # 非风控异常仅记录日志，不阻塞其他视频
            logger.warning(
                "视频下载失败（非风控），跳过该视频: bvid={}, error={}: {}",
                scan_result.bvid,
                type(exc).__name__,
                exc,
            )
            continue

    # 4. 计算新的水位线
    if risk_control_triggered:
        # 风控触发，水位线不前进，下一轮从原水位线重新扫描
        # 已完成视频由上层路由根据数据库状态去重，不会重复下载
        new_watermark: Optional[int] = latest_row_at
        logger.info(
            "订阅处理因风控提前终止: type={}, source_id={}, "
            "completed={}/{}, watermark保持={}",
            subscription_type,
            source_id,
            len(all_results),
            len(scan_results),
            new_watermark,
        )
    else:
        # 全部处理完成（含成功与失败），推进水位线
        # 失败视频的位图已记录在 WorkflowResult 中，上层路由根据位图决定重试
        new_watermark = _calculate_new_watermark(
            subscription_type=subscription_type,
            scan_results=scan_results,
            old_watermark=latest_row_at,
        )
        logger.info(
            "订阅处理完成: type={}, source_id={}, results={}, "
            "old_watermark={}, new_watermark={}",
            subscription_type,
            source_id,
            len(all_results),
            latest_row_at,
            new_watermark,
        )

    return all_results, new_watermark


async def _scan_subscription(
    client: BilibiliClient,
    subscription_type: str,
    source_id: int,
    latest_row_at: Optional[int],
) -> list[ScanResult]:
    """根据订阅类型调用对应的 scan 函数。

    Args:
        client: B 站客户端。
        subscription_type: 订阅类型（已校验）。
        source_id: 订阅源 ID（watchlater 忽略）。
        latest_row_at: 增量水位线（仅 favorite / submission 使用）。

    Returns:
        :class:`ScanResult` 列表。

    Raises:
        RiskControlError: scan 函数触发风控时抛出（由上层 :func:`download_subscription` 处理）。
        BilibiliAPIError: API 调用失败时抛出。
    """
    if subscription_type == SUBSCRIPTION_TYPE_FAVORITE:
        return await scan_favorite(client, source_id, latest_row_at)
    if subscription_type == SUBSCRIPTION_TYPE_SEASON:
        return await scan_season(client, source_id)
    if subscription_type == SUBSCRIPTION_TYPE_SERIES:
        return await scan_series(client, source_id)
    if subscription_type == SUBSCRIPTION_TYPE_SUBMISSION:
        return await scan_submission(client, source_id, latest_row_at)
    if subscription_type == SUBSCRIPTION_TYPE_WATCHLATER:
        return await scan_watchlater(client)
    # 理论不可达（上层已校验），防御性抛出
    raise ValueError(f"不支持的订阅类型: {subscription_type}")


def _calculate_new_watermark(
    subscription_type: str,
    scan_results: list[ScanResult],
    old_watermark: Optional[int],
) -> Optional[int]:
    """根据订阅类型与扫描结果计算新的水位线。

    水位线字段：

    - ``favorite``：``fav_time``（收藏时间）
    - ``submission`` / ``season`` / ``series``：``pubtime``（发布时间）
    - ``watchlater``：不更新水位线（全量扫描）

    新水位线 = ``max(old_watermark, max(scan_results 的水位线字段))``。
    scan_results 为空或字段全为 0/None 时返回 old_watermark。

    Args:
        subscription_type: 订阅类型（已校验）。
        scan_results: 扫描结果列表。
        old_watermark: 旧水位线值。

    Returns:
        新的水位线值，或 ``old_watermark``（不更新时）。
    """
    if not scan_results:
        return old_watermark

    # WatchLater 全量扫描，不更新水位线
    if subscription_type == SUBSCRIPTION_TYPE_WATCHLATER:
        return old_watermark

    # 确定水位线字段
    if subscription_type == SUBSCRIPTION_TYPE_FAVORITE:
        # 收藏夹水位线 = max(fav_time)，fav_time 可能为 None
        candidate_values: list[int] = [
            r.fav_time for r in scan_results if r.fav_time is not None
        ]
    else:
        # Season / Series / Submission 水位线 = max(pubtime)
        candidate_values = [r.pubtime for r in scan_results if r.pubtime > 0]

    if not candidate_values:
        return old_watermark

    max_scanned: int = max(candidate_values)

    if old_watermark is not None:
        return max(old_watermark, max_scanned)
    return max_scanned


__all__ = [
    # 订阅类型常量
    "SUBSCRIPTION_TYPE_FAVORITE",
    "SUBSCRIPTION_TYPE_SEASON",
    "SUBSCRIPTION_TYPE_SERIES",
    "SUBSCRIPTION_TYPE_SUBMISSION",
    "SUBSCRIPTION_TYPE_WATCHLATER",
    # 订阅级编排
    "download_subscription",
]
