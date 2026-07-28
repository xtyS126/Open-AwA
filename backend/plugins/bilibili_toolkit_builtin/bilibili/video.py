"""B 站视频元信息与 playurl API。

封装 ``/x/web-interface/view`` 与 ``/x/player/wbi/playurl`` 两个端点，
将原始 JSON 响应解析为 :class:`VideoInfo` / :class:`DashStreams` 类型化对象。

参考实现：
- ``bili-sync/crates/bili_sync/src/bilibili/video.rs`` 的
  ``Video::get_view_info`` 与 ``Video::get_page_analyzer``
- vendored ``openbiliclaw/bilibili/api.py`` 的 ``get_video_info``
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .client import BilibiliClient
from .stream_types import DashStreams, parse_playurl
from .wbi import BilibiliAPIError


class Page(BaseModel):
    """B 站视频分 P 信息。

    对应 ``/x/web-interface/view`` 响应中 ``data.pages[]`` 元素。
    """

    cid: int = Field(..., description="分 P 的 cid（用于 playurl / 弹幕 / 字幕调用）")
    page: int = Field(..., description="分 P 序号，从 1 开始")
    name: str = Field(default="", description="分 P 标题（part 字段）")
    duration: int = Field(default=0, description="分 P 时长（秒）")
    width: int = Field(default=0, description="视频宽度（像素），dimension.width")
    height: int = Field(default=0, description="视频高度（像素），dimension.height")


class VideoInfo(BaseModel):
    """B 站视频元信息。

    对应 ``/x/web-interface/view`` 响应的 ``data`` 字段。
    """

    bvid: str = Field(..., description="BV 号")
    aid: int = Field(default=0, description="AV 号")
    title: str = Field(default="", description="视频标题")
    cover: str = Field(default="", description="封面 URL（pic 字段）")
    upper_mid: int = Field(default=0, description="UP 主 mid（owner.mid）")
    upper_name: str = Field(default="", description="UP 主名称（owner.name）")
    upper_face: str = Field(default="", description="UP 主头像 URL（owner.face）")
    pages: list[Page] = Field(default_factory=list, description="分 P 列表")
    pubtime: int = Field(default=0, description="发布时间戳（秒，pubdate 字段）")
    ctime: int = Field(default=0, description="创建时间戳（秒，ctime 字段）")
    desc: str = Field(default="", description="视频简介（desc 字段）")
    tags: list[str] = Field(default_factory=list, description="视频标签列表")


async def get_video_info(client: BilibiliClient, bvid: str) -> VideoInfo:
    """获取视频元信息（含分 P 列表）。

    调用 ``GET /x/web-interface/view``，响应为：

    .. code-block:: json

        {
          "code": 0,
          "data": {
            "bvid": "...", "aid": 123, "title": "...", "pic": "...",
            "desc": "...", "pubdate": 1700000000, "ctime": 1700000000,
            "owner": {"mid": 1, "name": "...", "face": "..."},
            "pages": [{"cid": 1, "page": 1, "part": "...", "duration": 100,
                       "dimension": {"width": 1920, "height": 1080}}]
          }
        }

    Args:
        client: :class:`BilibiliClient` 实例。
        bvid: BV 号（如 ``BV1gLfnY8E6D``）。

    Returns:
        :class:`VideoInfo` 对象，包含视频基本信息与分 P 列表。

    Raises:
        BilibiliAPIError: API 返回非零 code 时抛出。
        RiskControlError: 触发风控时抛出。
    """
    payload = await client.request(
        method="GET",
        path="/x/web-interface/view",
        params={"bvid": bvid},
        need_wbi=False,
    )
    data = payload.get("data") or {}
    if not isinstance(data, dict):
        raise BilibiliAPIError(f"view 响应 data 字段非对象: {type(data).__name__}")
    return _parse_video_info(data, fallback_bvid=bvid)


async def get_playurl(client: BilibiliClient, bvid: str, cid: int) -> dict[str, Any]:
    """获取视频 playurl 响应（原始 dict 形式）。

    调用 ``GET /x/player/wbi/playurl``，参数：

    - ``bvid`` / ``cid``：视频与分 P 标识
    - ``qn=127``：请求最高清晰度（8K）
    - ``otype=json``：响应格式
    - ``fnval=4048``：DASH 格式标志（同时请求视频/音频/Dolby/HDR/HiRes）
    - ``fourk=1``：允许 4K

    WBI 签名必须开启，否则服务端返回 -352 风控或空数据。

    Args:
        client: :class:`BilibiliClient` 实例。
        bvid: BV 号。
        cid: 分 P cid。

    Returns:
        playurl 响应的 ``data`` 字段（原始 dict）。后续可用
        :func:`parse_playurl` 解析为类型化对象。

    Raises:
        BilibiliAPIError: API 返回非零 code 时抛出。
        RiskControlError: 触发风控时抛出。
    """
    payload = await client.request(
        method="GET",
        path="/x/player/wbi/playurl",
        params={
            "bvid": bvid,
            "cid": cid,
            "qn": 127,
            "otype": "json",
            "fnval": 4048,
            "fourk": 1,
        },
        need_wbi=True,
    )
    data = payload.get("data") or {}
    if not isinstance(data, dict):
        raise BilibiliAPIError(f"playurl 响应 data 字段非对象: {type(data).__name__}")
    return data


async def get_playurl_streams(
    client: BilibiliClient,
    bvid: str,
    cid: int,
) -> DashStreams:
    """获取 playurl 并解析为类型化对象。

    封装 :func:`get_playurl` + :func:`parse_playurl`，便于上层直接得到
    类型化流对象。Stage 4 ``analyzer`` 模块可直接基于 :class:`DashStreams`
    做 FilterOption 筛选与 best_stream 选择。

    Args:
        client: :class:`BilibiliClient` 实例。
        bvid: BV 号。
        cid: 分 P cid。

    Returns:
        :class:`DashStreams` 容器，包含流类型标签与流对象列表。

    Raises:
        BilibiliAPIError: API 返回非零 code 或流字段缺失时抛出。
        RiskControlError: 触发风控时抛出。
        ValueError: playurl data 中无任何可用流字段时抛出。
    """
    data = await get_playurl(client, bvid, cid)
    return parse_playurl(data)


def _parse_video_info(data: dict[str, Any], *, fallback_bvid: str = "") -> VideoInfo:
    """将 view 端点响应的 data 字段解析为 :class:`VideoInfo`。

    Args:
        data: ``/x/web-interface/view`` 响应的 ``data`` 字段。
        fallback_bvid: 当响应中 bvid 缺失时的回退值（通常等于请求参数）。

    Returns:
        :class:`VideoInfo` 对象。
    """
    owner = data.get("owner") or {}
    if not isinstance(owner, dict):
        owner = {}
    pages_raw = data.get("pages") or []
    if not isinstance(pages_raw, list):
        pages_raw = []
    pages: list[Page] = []
    for raw in pages_raw:
        if not isinstance(raw, dict):
            continue
        page = _parse_page(raw)
        if page is not None:
            pages.append(page)
    return VideoInfo(
        bvid=str(data.get("bvid") or fallback_bvid),
        aid=int(data.get("aid") or 0),
        title=str(data.get("title") or ""),
        cover=str(data.get("pic") or ""),
        upper_mid=int(owner.get("mid") or 0),
        upper_name=str(owner.get("name") or ""),
        upper_face=str(owner.get("face") or ""),
        pages=pages,
        pubtime=int(data.get("pubdate") or 0),
        ctime=int(data.get("ctime") or 0),
        desc=str(data.get("desc") or ""),
        tags=[],  # tags 需调用 /x/web-interface/view/detail/tag 单独获取
    )


def _parse_page(raw: dict[str, Any]) -> Page | None:
    """解析 ``data.pages[]`` 元素为 :class:`Page`。

    Args:
        raw: pages 数组中的单个 dict 元素。

    Returns:
        :class:`Page` 对象，或 ``None``（cid 缺失时跳过）。
    """
    cid = raw.get("cid")
    if not isinstance(cid, int):
        return None
    page_num = raw.get("page")
    if not isinstance(page_num, int):
        page_num = 0
    dimension = raw.get("dimension") or {}
    if not isinstance(dimension, dict):
        dimension = {}
    return Page(
        cid=cid,
        page=page_num,
        name=str(raw.get("part") or ""),
        duration=int(raw.get("duration") or 0),
        width=int(dimension.get("width") or 0),
        height=int(dimension.get("height") or 0),
    )
