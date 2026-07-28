"""UP 主投稿订阅源。

调用 ``GET /x/space/wbi/arc/search``（需 WBI 签名）拉取 UP 主投稿视频列表，
按 ``pubdate`` 倒序增量扫描，遇到 ``created <= latest_row_at`` 停止。

可选 ``use_dynamic_api``：额外调用 ``GET /x/polymer/web-dynamic/v1/feed/space``
拉取动态首页（含置顶视频），合并到结果列表头部。置顶视频在常规投稿列表中
可能缺失，需通过动态接口补全（参考 bili-sync migration
``m20251009_123713_add_use_dynamic_api.rs``）。

参考实现：
- ``bili-sync/crates/bili_sync/src/bilibili/submission.rs`` 的
  ``Submission::get_videos`` 与 ``into_video_stream``
- ``bili-sync/crates/bili_sync/src/bilibili/dynamic.rs`` 的
  ``Dynamic::get_dynamics`` 与 ``into_video_stream``
"""

from __future__ import annotations

from typing import Any, Optional

from loguru import logger

from ..bilibili.client import BilibiliClient
from ..bilibili.wbi import BilibiliAPIError
from .types import ScanResult

# 投稿每页条目数（与 bili-sync Rust 实现一致）
SUBMISSION_PAGE_SIZE: int = 30

# 动态视频条目类型标识
DYNAMIC_TYPE_AV: str = "DYNAMIC_TYPE_AV"


async def scan_submission(
    client: BilibiliClient,
    upper_mid: int,
    latest_row_at: Optional[int],
    use_dynamic_api: bool = False,
) -> list[ScanResult]:
    """扫描 UP 主投稿视频，按发布时间倒序增量返回。

    主路径调用 ``GET /x/space/wbi/arc/search?mid=&pn=&ps=30&order=pubdate``
    （需 WBI 签名），按 ``pubdate`` 倒序翻页，遇到
    ``created <= latest_row_at`` 的条目立即停止遍历。

    当 ``use_dynamic_api=True`` 时，先调用动态首页接口
    ``GET /x/polymer/web-dynamic/v1/feed/space?host_mid=&type=video``
    获取置顶视频，合并到结果列表头部（按 bvid 去重）。

    Args:
        client: :class:`BilibiliClient` 实例。
        upper_mid: UP 主 mid。
        latest_row_at: 增量水位线（投稿创建时间戳，秒）；``None`` 表示全量扫描。
        use_dynamic_api: 是否额外拉取动态首页置顶视频。

    Returns:
        :class:`ScanResult` 列表，动态置顶视频在前，其后为按 pubdate 倒序
        的投稿视频。

    Raises:
        RiskControlError: 触发风控时抛出，由编排层处理熔断（不在此处捕获）。
        BilibiliAPIError: 主路径 API 调用失败或响应结构异常时抛出
            （动态首页失败仅记录 WARNING，不抛出）。
    """
    # 1. 可选：拉取动态首页置顶视频
    dynamic_results: list[ScanResult] = []
    if use_dynamic_api:
        dynamic_results = await _scan_dynamic_first_page(client, upper_mid)

    # 2. 主路径：arc/search 翻页增量扫描
    arc_results: list[ScanResult] = []
    seen_bvids: set[str] = {r.bvid for r in dynamic_results}
    page: int = 1
    while True:
        payload = await client.request(
            method="GET",
            path="/x/space/wbi/arc/search",
            params={
                "mid": upper_mid,
                "pn": page,
                "ps": SUBMISSION_PAGE_SIZE,
                "order": "pubdate",
                "order_avoided": "true",
                "platform": "web",
                "web_location": "1550101",
            },
            need_wbi=True,
        )
        data = payload.get("data") or {}
        if not isinstance(data, dict):
            raise BilibiliAPIError(
                f"arc/search data 字段非对象: {type(data).__name__}"
            )

        list_node = data.get("list") or {}
        if not isinstance(list_node, dict):
            list_node = {}
        vlist = list_node.get("vlist") or []
        if not isinstance(vlist, list):
            raise BilibiliAPIError("arc/search vlist 字段非数组")
        if not vlist:
            break

        stop = False
        for item in vlist:
            if not isinstance(item, dict):
                continue
            result = _parse_vlist_item(item, upper_mid)
            if result is None:
                continue
            # 增量水位线：created(pubtime) <= latest_row_at 则停止
            if (
                latest_row_at is not None
                and result.pubtime <= latest_row_at
            ):
                stop = True
                break
            if result.bvid not in seen_bvids:
                arc_results.append(result)
                seen_bvids.add(result.bvid)

        if stop:
            break
        # 翻页终止条件：页内条目数 < ps
        if len(vlist) < SUBMISSION_PAGE_SIZE:
            break
        page += 1

    results = dynamic_results + arc_results
    logger.debug(
        "UP 主 {} 投稿扫描完成，动态 {} 条 + 投稿 {} 条 = {} 条新视频",
        upper_mid,
        len(dynamic_results),
        len(arc_results),
        len(results),
    )
    return results


async def _scan_dynamic_first_page(
    client: BilibiliClient,
    upper_mid: int,
) -> list[ScanResult]:
    """拉取动态首页中的视频类型条目（含置顶视频）。

    调用 ``GET /x/polymer/web-dynamic/v1/feed/space?host_mid=&offset=&type=video``
    （需 WBI 签名），仅取首页（offset 为空），过滤 ``type=="DYNAMIC_TYPE_AV"``
    的条目并解析为 :class:`ScanResult`。

    动态接口失败时不阻塞主流程，记录 WARNING 后返回空列表
    （置顶视频为可选增强，非关键路径）。

    Args:
        client: :class:`BilibiliClient` 实例。
        upper_mid: UP 主 mid。

    Returns:
        :class:`ScanResult` 列表（动态首页视频条目）。接口失败时返回空列表。
    """
    results: list[ScanResult] = []
    try:
        payload = await client.request(
            method="GET",
            path="/x/polymer/web-dynamic/v1/feed/space",
            params={
                "host_mid": upper_mid,
                "offset": "",
                "type": "video",
            },
            need_wbi=True,
        )
    except BilibiliAPIError as exc:
        # 动态接口业务错误（非风控）不阻塞主流程；风控异常由调用方处理
        logger.warning(
            "UP 主 {} 动态首页拉取失败，跳过置顶视频补全: {}",
            upper_mid,
            exc,
        )
        return results

    data = payload.get("data") or {}
    if not isinstance(data, dict):
        return results
    items = data.get("items") or []
    if not isinstance(items, list):
        return results

    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get("type") != DYNAMIC_TYPE_AV:
            continue
        result = _parse_dynamic_item(item)
        if result is not None:
            results.append(result)

    logger.debug(
        "UP 主 {} 动态首页解析到 {} 条视频条目",
        upper_mid,
        len(results),
    )
    return results


def _parse_vlist_item(
    item: dict[str, Any],
    upper_mid: int,
) -> Optional[ScanResult]:
    """解析 ``arc/search`` 的 ``vlist[]`` 元素为 :class:`ScanResult`。

    vlist 中每个条目包含：``bvid``、``aid``、``title``、``pic``（封面）、
    ``created``（投稿创建时间戳，秒）、``mid``（UP 主 mid）、``author``
    （UP 主名）、``videos``（分 P 数）等字段。

    Args:
        item: ``vlist[]`` 中的单个 dict 元素。
        upper_mid: 调用方传入的 UP 主 mid，用于 ``mid`` 字段缺失时回退。

    Returns:
        :class:`ScanResult` 对象，或 ``None``（bvid 缺失时跳过）。
    """
    bvid = str(item.get("bvid") or "")
    if not bvid:
        return None

    created = item.get("created")
    pubtime = int(created) if isinstance(created, (int, float)) else 0

    return ScanResult(
        bvid=bvid,
        aid=int(item.get("aid") or 0),
        title=str(item.get("title") or ""),
        cover=str(item.get("pic") or ""),
        upper_mid=int(item.get("mid") or upper_mid),
        upper_name=str(item.get("author") or ""),
        pages_count=int(item.get("videos") or 0),
        pubtime=pubtime,
        fav_time=None,  # 投稿源无收藏时间
    )


def _parse_dynamic_item(item: dict[str, Any]) -> Optional[ScanResult]:
    """解析动态 feed ``items[]`` 元素为 :class:`ScanResult`。

    动态条目结构（参考 bili-sync ``dynamic.rs``）：
    - ``modules.module_dynamic.major.archive``：视频信息（bvid/aid/title/pic 等）
    - ``modules.module_author.pub_ts``：发布时间戳（秒）
    - ``modules.module_author.mid`` / ``name``：UP 主信息

    Args:
        item: 动态 feed ``items[]`` 中的单个 dict 元素。

    Returns:
        :class:`ScanResult` 对象，或 ``None``（archive 缺失或无 bvid 时跳过）。
    """
    modules = item.get("modules") or {}
    if not isinstance(modules, dict):
        return None

    module_dynamic = modules.get("module_dynamic") or {}
    if not isinstance(module_dynamic, dict):
        return None
    major = module_dynamic.get("major") or {}
    if not isinstance(major, dict):
        return None
    archive = major.get("archive") or {}
    if not isinstance(archive, dict):
        return None

    bvid = str(archive.get("bvid") or "")
    if not bvid:
        return None

    # 发布时间与 UP 主信息在 module_author 中
    module_author = modules.get("module_author") or {}
    if not isinstance(module_author, dict):
        module_author = {}

    pub_ts = module_author.get("pub_ts")
    pubtime = int(pub_ts) if isinstance(pub_ts, (int, float)) else 0

    return ScanResult(
        bvid=bvid,
        aid=int(archive.get("aid") or 0),
        title=str(archive.get("title") or ""),
        cover=str(archive.get("pic") or ""),
        upper_mid=int(module_author.get("mid") or 0),
        upper_name=str(module_author.get("name") or ""),
        pages_count=0,  # 动态 archive 无分 P 数，由后续 get_video_info 补全
        pubtime=pubtime,
        fav_time=None,  # 动态源无收藏时间
    )
