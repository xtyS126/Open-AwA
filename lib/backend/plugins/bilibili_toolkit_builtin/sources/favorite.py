"""收藏夹订阅源。

调用 ``GET /x/v3/fav/resource/list`` 拉取收藏夹视频列表，按 ``mtime``
（收藏时间）倒序遍历，实现增量扫描水位线：遇到 ``fav_time <= latest_row_at``
立即停止，避免每次全量拉取。

参考实现：``bili-sync/crates/bili_sync/src/bilibili/favorite_list.rs``
的 ``FavoriteList::get_videos`` 与 ``into_video_stream``。
"""

from __future__ import annotations

from typing import Any, Optional

from loguru import logger

from ..bilibili.client import BilibiliClient
from ..bilibili.wbi import BilibiliAPIError
from .types import ScanResult

# 收藏夹每页条目数（与 bili-sync Rust 实现一致）
FAVORITE_PAGE_SIZE: int = 20


async def scan_favorite(
    client: BilibiliClient,
    media_id: int,
    latest_row_at: Optional[int],
) -> list[ScanResult]:
    """扫描收藏夹视频列表，按收藏时间倒序增量返回。

    调用 ``GET /x/v3/fav/resource/list?media_id=&pn=&ps=20&order=mtime``，
    翻页拉取直到 ``has_more != true`` 或页内条目数小于 ``ps``。
    增量扫描：遇到 ``fav_time <= latest_row_at`` 的条目立即停止遍历
    （收藏夹按 mtime 倒序返回，故后续条目必然更早，可安全跳过）。

    Args:
        client: :class:`BilibiliClient` 实例。
        media_id: 收藏夹 ID（``media_id`` / ``fid``）。
        latest_row_at: 增量水位线（收藏时间戳，秒）；``None`` 表示全量扫描。

    Returns:
        :class:`ScanResult` 列表，按收藏时间倒序排列，
        仅包含 ``fav_time > latest_row_at`` 的条目。

    Raises:
        RiskControlError: 触发风控时抛出，由编排层处理熔断（不在此处捕获）。
        BilibiliAPIError: API 调用失败或响应结构异常时抛出。
    """
    results: list[ScanResult] = []
    page: int = 1
    while True:
        payload = await client.request(
            method="GET",
            path="/x/v3/fav/resource/list",
            params={
                "media_id": media_id,
                "pn": page,
                "ps": FAVORITE_PAGE_SIZE,
                "order": "mtime",
                "type": 0,
                "tid": 0,
            },
            need_wbi=False,
        )
        data = payload.get("data") or {}
        if not isinstance(data, dict):
            raise BilibiliAPIError(
                f"fav/resource/list data 字段非对象: {type(data).__name__}"
            )

        medias = data.get("medias") or []
        if not isinstance(medias, list):
            raise BilibiliAPIError("fav/resource/list medias 字段非数组")
        # 空列表表示已到末页
        if not medias:
            break

        stop = False
        for media in medias:
            if not isinstance(media, dict):
                continue
            scan_result = _parse_favorite_media(media)
            if scan_result is None:
                continue
            # 增量水位线：fav_time <= latest_row_at 则停止（按 mtime 倒序）
            if (
                latest_row_at is not None
                and scan_result.fav_time is not None
                and scan_result.fav_time <= latest_row_at
            ):
                stop = True
                break
            results.append(scan_result)

        if stop:
            break

        # 翻页终止条件：页内条目数 < ps 或 has_more != true
        if len(medias) < FAVORITE_PAGE_SIZE:
            break
        has_more = data.get("has_more")
        if has_more is not True:
            break
        page += 1

    logger.debug("收藏夹 {} 扫描完成，获取 {} 条新视频", media_id, len(results))
    return results


def _parse_favorite_media(media: dict[str, Any]) -> Optional[ScanResult]:
    """解析 ``fav/resource/list`` 的 ``medias[]`` 元素为 :class:`ScanResult`。

    收藏夹响应中每个 media 包含：``id``（avid）、``bvid``、``title``、
    ``cover``、``upper{mid,name}``、``pubdate``、``fav_time`` 等字段。
    非视频条目（无 bvid）返回 ``None`` 跳过。

    Args:
        media: ``medias[]`` 中的单个 dict 元素。

    Returns:
        :class:`ScanResult` 对象，或 ``None``（bvid 缺失时跳过）。
    """
    bvid = str(media.get("bvid") or "")
    if not bvid:
        return None

    upper = media.get("upper") or {}
    if not isinstance(upper, dict):
        upper = {}

    # aid 优先取 aid 字段，回退到 id 字段（收藏夹响应中 id 即 avid）
    aid_raw = media.get("aid")
    if not isinstance(aid_raw, (int, float)):
        aid_raw = media.get("id") or 0
    aid = int(aid_raw) if isinstance(aid_raw, (int, float)) else 0

    # fav_time 仅在响应中存在时填充
    fav_time_raw = media.get("fav_time")
    fav_time = (
        int(fav_time_raw) if isinstance(fav_time_raw, (int, float)) else None
    )

    return ScanResult(
        bvid=bvid,
        aid=aid,
        title=str(media.get("title") or ""),
        cover=str(media.get("cover") or ""),
        upper_mid=int(upper.get("mid") or 0),
        upper_name=str(upper.get("name") or ""),
        pages_count=int(media.get("videos") or 0),  # 收藏夹响应通常无 videos，默认 0
        pubtime=int(media.get("pubdate") or 0),
        fav_time=fav_time,
    )
