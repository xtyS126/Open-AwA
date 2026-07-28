"""合集与视频列表订阅源。

支持两种合集类型：

- Season（合集）：调用 ``GET /x/polymer/web-space/seasons_archives_list``，
  按 ``page_num`` / ``page_size`` 翻页。
- Series（视频列表）：调用 ``GET /x/series/archives``，
  按 ``pn`` / ``ps`` 翻页。

两者均采用全量拉取（不按时间排序、不增量扫描），由编排层在拉取完成后
过滤已下载视频。这是 bili-sync Rust 实现中明确的设计决策：合集/列表
返回的视频并非严格按照时间排序，不同合集排序方式也不同，为保证程序
正确性，每次都全量拉取（参考 ``adapter/collection.rs`` 的 ``should_take``
始终返回 ``true``）。

参考实现：``bili-sync/crates/bili_sync/src/bilibili/collection.rs``
的 ``Collection::get_videos`` 与 ``into_video_stream``。
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from ..bilibili.client import BilibiliClient
from ..bilibili.wbi import BilibiliAPIError
from .types import ScanResult

# 合集/列表每页条目数（与 bili-sync Rust 实现一致）
COLLECTION_PAGE_SIZE: int = 30


async def scan_season(
    client: BilibiliClient,
    season_id: int,
) -> list[ScanResult]:
    """扫描合集（Season）视频列表，全量拉取。

    调用 ``GET /x/polymer/web-space/seasons_archives_list?season_id=&page_num=&page_size=30&sort_reverse=true``，
    按 ``page_num`` 翻页直到 ``archives`` 为空或页内条目数小于 ``page_size``。

    Args:
        client: :class:`BilibiliClient` 实例。
        season_id: 合集 ID。

    Returns:
        :class:`ScanResult` 列表（全量，不按时间增量扫描）。

    Raises:
        RiskControlError: 触发风控时抛出，由编排层处理熔断（不在此处捕获）。
        BilibiliAPIError: API 调用失败或响应结构异常时抛出。
    """
    results: list[ScanResult] = []
    page_num: int = 1
    while True:
        payload = await client.request(
            method="GET",
            path="/x/polymer/web-space/seasons_archives_list",
            params={
                "season_id": season_id,
                "page_num": page_num,
                "page_size": COLLECTION_PAGE_SIZE,
                "sort_reverse": "true",
            },
            need_wbi=False,
        )
        data = payload.get("data") or {}
        if not isinstance(data, dict):
            raise BilibiliAPIError(
                f"seasons_archives_list data 字段非对象: {type(data).__name__}"
            )

        archives = data.get("archives") or []
        if not isinstance(archives, list):
            raise BilibiliAPIError("seasons_archives_list archives 字段非数组")
        if not archives:
            break

        for archive in archives:
            if not isinstance(archive, dict):
                continue
            result = _parse_archive(archive)
            if result is not None:
                results.append(result)

        # 翻页终止条件：页内条目数 < page_size
        if len(archives) < COLLECTION_PAGE_SIZE:
            break
        page_num += 1

    logger.debug("合集 Season {} 扫描完成，获取 {} 条视频", season_id, len(results))
    return results


async def scan_series(
    client: BilibiliClient,
    series_id: int,
) -> list[ScanResult]:
    """扫描视频列表（Series）视频列表，全量拉取。

    调用 ``GET /x/series/archives?series_id=&pn=&ps=30&only_normal=true&sort=desc``，
    按 ``pn`` 翻页直到 ``archives`` 为空或页内条目数小于 ``ps``。

    Args:
        client: :class:`BilibiliClient` 实例。
        series_id: 视频列表 ID。

    Returns:
        :class:`ScanResult` 列表（全量，不按时间增量扫描）。

    Raises:
        RiskControlError: 触发风控时抛出，由编排层处理熔断（不在此处捕获）。
        BilibiliAPIError: API 调用失败或响应结构异常时抛出。
    """
    results: list[ScanResult] = []
    page: int = 1
    while True:
        payload = await client.request(
            method="GET",
            path="/x/series/archives",
            params={
                "series_id": series_id,
                "pn": page,
                "ps": COLLECTION_PAGE_SIZE,
                "only_normal": "true",
                "sort": "desc",
            },
            need_wbi=False,
        )
        data = payload.get("data") or {}
        if not isinstance(data, dict):
            raise BilibiliAPIError(
                f"series/archives data 字段非对象: {type(data).__name__}"
            )

        archives = data.get("archives") or []
        if not isinstance(archives, list):
            raise BilibiliAPIError("series/archives archives 字段非数组")
        if not archives:
            break

        for archive in archives:
            if not isinstance(archive, dict):
                continue
            result = _parse_archive(archive)
            if result is not None:
                results.append(result)

        # 翻页终止条件：页内条目数 < ps
        if len(archives) < COLLECTION_PAGE_SIZE:
            break
        page += 1

    logger.debug("视频列表 Series {} 扫描完成，获取 {} 条视频", series_id, len(results))
    return results


def _parse_archive(archive: dict[str, Any]) -> ScanResult | None:
    """解析合集/列表 ``archives[]`` 元素为 :class:`ScanResult`。

    合集与列表响应中每个 archive 包含：``bvid``、``aid``、``title``、
    ``pic``（封面）、``pubdate``、``videos``（分 P 数）等字段。
    部分 archive 不含 ``upper`` 字段（合集所属 UP 主信息在 ``meta`` 中），
    此时 ``upper_mid`` / ``upper_name`` 默认为 0 / 空字符串，由后续
    ``get_video_info`` 补全。

    Args:
        archive: ``archives[]`` 中的单个 dict 元素。

    Returns:
        :class:`ScanResult` 对象，或 ``None``（bvid 缺失时跳过）。
    """
    bvid = str(archive.get("bvid") or "")
    if not bvid:
        return None

    upper = archive.get("upper") or {}
    if not isinstance(upper, dict):
        upper = {}

    return ScanResult(
        bvid=bvid,
        aid=int(archive.get("aid") or 0),
        title=str(archive.get("title") or ""),
        cover=str(archive.get("pic") or ""),
        upper_mid=int(upper.get("mid") or 0),
        upper_name=str(upper.get("name") or ""),
        pages_count=int(archive.get("videos") or 0),
        pubtime=int(archive.get("pubdate") or 0),
        fav_time=None,  # 合集源无收藏时间
    )
