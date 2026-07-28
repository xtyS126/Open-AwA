"""稍后再看订阅源。

调用 ``GET /x/v2/history/toview`` 拉取稍后再看视频列表，全量返回。
稍后再看为全局唯一订阅（id=1），不按时间排序、不增量扫描。

参考实现：``bili-sync/crates/bili_sync/src/bilibili/watch_later.rs``
的 ``WatchLater::get_videos`` 与 ``into_video_stream``。
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from ..bilibili.client import BilibiliClient
from ..bilibili.wbi import BilibiliAPIError
from .types import ScanResult


async def scan_watchlater(client: BilibiliClient) -> list[ScanResult]:
    """扫描稍后再看列表，全量返回。

    调用 ``GET /x/v2/history/toview``，响应 ``data.list[]`` 包含全部
    稍后再看视频。该订阅为全局唯一（id=1），不增量扫描。

    Args:
        client: :class:`BilibiliClient` 实例。

    Returns:
        :class:`ScanResult` 列表（全量）。

    Raises:
        RiskControlError: 触发风控时抛出，由编排层处理熔断（不在此处捕获）。
        BilibiliAPIError: API 调用失败或响应结构异常时抛出。
    """
    payload = await client.request(
        method="GET",
        path="/x/v2/history/toview",
        params=None,
        need_wbi=False,
    )
    data = payload.get("data") or {}
    if not isinstance(data, dict):
        raise BilibiliAPIError(
            f"history/toview data 字段非对象: {type(data).__name__}"
        )

    raw_list = data.get("list") or []
    if not isinstance(raw_list, list):
        raise BilibiliAPIError("history/toview list 字段非数组")

    results: list[ScanResult] = []
    for raw in raw_list:
        if not isinstance(raw, dict):
            continue
        result = _parse_watchlater_item(raw)
        if result is not None:
            results.append(result)

    logger.debug("稍后再看扫描完成，获取 {} 条视频", len(results))
    return results


def _parse_watchlater_item(raw: dict[str, Any]) -> ScanResult | None:
    """解析 ``history/toview`` 的 ``list[]`` 元素为 :class:`ScanResult`。

    稍后再看响应中每个条目包含：``bvid``、``aid``、``title``、``pic``
    （封面）、``owner{mid,name}``（UP 主信息）、``pubdate``（发布时间）、
    ``add_at``（加入稍后再看时间）、``videos``（分 P 数）等字段。

    Args:
        raw: ``list[]`` 中的单个 dict 元素。

    Returns:
        :class:`ScanResult` 对象，或 ``None``（bvid 缺失时跳过）。
    """
    bvid = str(raw.get("bvid") or "")
    if not bvid:
        return None

    owner = raw.get("owner") or {}
    if not isinstance(owner, dict):
        owner = {}

    # add_at 为加入稍后再看的时间戳，对应 ScanResult.fav_time
    add_at = raw.get("add_at")
    fav_time = int(add_at) if isinstance(add_at, (int, float)) else None

    return ScanResult(
        bvid=bvid,
        aid=int(raw.get("aid") or 0),
        title=str(raw.get("title") or ""),
        cover=str(raw.get("pic") or ""),
        upper_mid=int(owner.get("mid") or 0),
        upper_name=str(owner.get("name") or ""),
        pages_count=int(raw.get("videos") or 0),
        pubtime=int(raw.get("pubdate") or 0),
        fav_time=fav_time,
    )
