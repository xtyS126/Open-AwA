"""B 站弹幕分段并发拉取。

按 360 秒一段切分视频时长，并发调用 ``/x/v2/dm/wbi/web/seg.so`` 端点
（WBI 签名），将 protobuf 二进制响应解析为 ``DanmakuElem`` 列表，按
弹幕 id 去重后按出现时间（``progress``）升序排序。

参考实现：
- ``bili-sync/crates/bili_sync/src/bilibili/video.rs`` 的
  ``get_danmaku_writer`` 与 ``get_danmaku_segment``
- B 站官方端点：``GET https://api.bilibili.com/x/v2/dm/wbi/web/seg.so``
  参数 ``type=1`` / ``oid=<cid>`` / ``segment_index=<i>``
"""

from __future__ import annotations

import asyncio
import math
from typing import Any

from loguru import logger

from ..bilibili.client import BilibiliClient
from .proto import DanmakuElem, parse_danmaku_segs

# 每段弹幕覆盖的视频时长（秒），与 bili-sync Rust 实现保持一致
SEGMENT_DURATION_SECONDS: int = 360

# 弹幕分段端点路径（B 站 API 相对路径，base_url 已在 BilibiliClient 中配置）
DANMAKU_SEG_ENDPOINT: str = "/x/v2/dm/wbi/web/seg.so"

# 弹幕类型固定为 1（视频弹幕），与 bili-sync 一致
_DANMAKU_TYPE: int = 1


async def fetch_danmaku(
    client: BilibiliClient,
    bvid: str,
    cid: int,
    duration: int,
) -> list[DanmakuElem]:
    """拉取视频全部分 P 的弹幕并合并去重。

    按 :data:`SEGMENT_DURATION_SECONDS`（360 秒）一段切分视频时长，
    并发请求 ``/x/v2/dm/wbi/web/seg.so``，解析 protobuf 响应，
    按 ``id`` 去重后按 ``progress``（出现时间，毫秒）升序排序。

    Args:
        client: :class:`BilibiliClient` 实例。
        bvid: BV 号（仅用于日志，请求参数中不携带）。
        cid: 分 P cid（请求参数 ``oid``）。
        duration: 视频/分 P 时长（秒），用于计算分段数。

    Returns:
        :class:`DanmakuElem` 列表，按出现时间升序排序。

    Raises:
        RiskControlError: 任一段请求触发风控（412/403）时抛出，
            立即取消其他并发请求。
        BilibiliAPIError: HTTP 异常时抛出。
    """
    # 计算分段数：duration / 360 向上取整，至少 1 段
    segment_count = max(1, math.ceil(max(0, duration) / SEGMENT_DURATION_SECONDS))
    logger.debug(
        "拉取弹幕: bvid={}, cid={}, duration={}s, segment_count={}",
        bvid,
        cid,
        duration,
        segment_count,
    )

    # 并发拉取所有分段
    tasks = [
        asyncio.create_task(_fetch_segment(client, cid, idx))
        for idx in range(1, segment_count + 1)
    ]
    try:
        segments: list[list[DanmakuElem]] = await asyncio.gather(*tasks)
    except BaseException:
        # 风控等异常触发时取消未完成的并发任务，避免资源泄漏
        for task in tasks:
            if not task.done():
                task.cancel()
        # 等待取消完成（忽略 CancelledError）
        await asyncio.gather(*tasks, return_exceptions=True)
        raise

    # 合并去重（按弹幕 id），同一 id 取首次出现
    seen_ids: set[int] = set()
    merged: list[DanmakuElem] = []
    for seg in segments:
        for elem in seg:
            elem_id = int(elem.id)
            if elem_id in seen_ids:
                continue
            seen_ids.add(elem_id)
            merged.append(elem)

    # 按出现时间（progress，毫秒）升序排序，与 Rust sort_by_key 一致
    merged.sort(key=lambda e: int(e.progress))
    logger.info(
        "弹幕拉取完成: bvid={}, cid={}, total={}, unique={}",
        bvid,
        cid,
        sum(len(s) for s in segments),
        len(merged),
    )
    return merged


async def _fetch_segment(
    client: BilibiliClient,
    cid: int,
    segment_index: int,
) -> list[DanmakuElem]:
    """拉取单个分段的弹幕。

    Args:
        client: :class:`BilibiliClient` 实例。
        cid: 分 P cid。
        segment_index: 分段序号，从 1 开始。

    Returns:
        :class:`DanmakuElem` 列表。空响应返回空列表。

    Raises:
        RiskControlError: 触发风控时抛出。
        BilibiliAPIError: HTTP 异常时抛出。
    """
    params: dict[str, Any] = {
        "type": _DANMAKU_TYPE,
        "oid": cid,
        "segment_index": segment_index,
    }
    raw = await client.request_raw(
        method="GET",
        path=DANMAKU_SEG_ENDPOINT,
        params=params,
        need_wbi=True,
    )
    return parse_danmaku_segs(raw)


__all__ = [
    "DANMAKU_SEG_ENDPOINT",
    "SEGMENT_DURATION_SECONDS",
    "fetch_danmaku",
]
