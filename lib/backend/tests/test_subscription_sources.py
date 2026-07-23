"""四种订阅源扫描的集成测试（SubTask 51.1）。

覆盖 favorite / season / series / submission / watchlater 五种订阅源
的 scan_* 函数，通过 mock ``BilibiliClient.request`` 返回 canned JSON
响应验证：

1. 收藏夹源：增量水位线（``fav_time``），遇到早于水位线的条目立即停止
2. 合集源（Season / Series）：全量翻页拉取，不增量扫描
3. 投稿源：WBI 签名（``need_wbi=True``），增量水位线（``pubtime``）
4. 稍后再看源：全局唯一订阅，单次拉取全量返回

测试隔离原则：
- 不发起真实 HTTP 请求，全部通过 ``AsyncMock`` 返回 canned dict
- 每个用例独立构造 mock client，不依赖全局状态
- 验证 ``need_wbi`` 参数传递正确性（投稿源为 True，其他源为 False）
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

# 将 backend 目录加入 sys.path，便于导入 plugins 包
_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from plugins.bilibili_toolkit_builtin.bilibili.client import BilibiliClient  # noqa: E402
from plugins.bilibili_toolkit_builtin.bilibili.credential import Credential  # noqa: E402
from plugins.bilibili_toolkit_builtin.sources import (  # noqa: E402
    ScanResult,
    scan_favorite,
    scan_season,
    scan_series,
    scan_submission,
    scan_watchlater,
)


# ---------------------------------------------------------------------------
# mock 工具
# ---------------------------------------------------------------------------


def _make_mock_client() -> MagicMock:
    """构造一个 mock BilibiliClient，request 方法为 AsyncMock。

    返回的 mock 对象满足 scan_* 函数对 client 的最小契约：
    - ``request`` 是 async callable，返回 dict
    """
    client = MagicMock(spec=BilibiliClient)
    client.request = AsyncMock(return_value={})
    return client


def _build_favorite_media(
    bvid: str,
    aid: int,
    title: str,
    fav_time: int,
    pubdate: int = 1700000000,
    upper_mid: int = 100,
    upper_name: str = "UP",
    cover: str = "https://example.com/cover.jpg",
) -> dict[str, Any]:
    """构造收藏夹 ``medias[]`` 元素。"""
    return {
        "id": aid,
        "bvid": bvid,
        "aid": aid,
        "title": title,
        "cover": cover,
        "upper": {"mid": upper_mid, "name": upper_name},
        "pubdate": pubdate,
        "fav_time": fav_time,
    }


def _build_archive(
    bvid: str,
    aid: int,
    title: str,
    pubdate: int,
    pic: str = "https://example.com/p.jpg",
    upper_mid: int = 100,
    upper_name: str = "UP",
    videos: int = 1,
) -> dict[str, Any]:
    """构造合集/列表 ``archives[]`` 元素。"""
    return {
        "bvid": bvid,
        "aid": aid,
        "title": title,
        "pic": pic,
        "upper": {"mid": upper_mid, "name": upper_name},
        "pubdate": pubdate,
        "videos": videos,
    }


def _build_vlist_item(
    bvid: str,
    aid: int,
    title: str,
    created: int,
    pic: str = "https://example.com/v.jpg",
    mid: int = 100,
    author: str = "UP",
    videos: int = 1,
) -> dict[str, Any]:
    """构造投稿 ``vlist[]`` 元素。"""
    return {
        "bvid": bvid,
        "aid": aid,
        "title": title,
        "pic": pic,
        "created": created,
        "mid": mid,
        "author": author,
        "videos": videos,
    }


def _build_watchlater_item(
    bvid: str,
    aid: int,
    title: str,
    add_at: int,
    pubdate: int = 1700000000,
    owner_mid: int = 100,
    owner_name: str = "UP",
    videos: int = 1,
) -> dict[str, Any]:
    """构造稍后再看 ``list[]`` 元素。"""
    return {
        "bvid": bvid,
        "aid": aid,
        "title": title,
        "pic": "https://example.com/w.jpg",
        "owner": {"mid": owner_mid, "name": owner_name},
        "pubdate": pubdate,
        "add_at": add_at,
        "videos": videos,
    }


# ---------------------------------------------------------------------------
# 收藏夹源测试
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scan_favorite_returns_all_items_when_no_watermark():
    """无水位线时（latest_row_at=None）应全量返回所有视频，按 fav_time 倒序。"""
    client = _make_mock_client()
    # 单页 2 条，无翻页
    client.request.return_value = {
        "code": 0,
        "data": {
            "medias": [
                _build_favorite_media("BV1", 1, "video 1", fav_time=2000),
                _build_favorite_media("BV2", 2, "video 2", fav_time=1000),
            ],
            "has_more": False,
        },
    }

    results: list[ScanResult] = await scan_favorite(client, media_id=999, latest_row_at=None)

    assert len(results) == 2
    assert results[0].bvid == "BV1"
    assert results[0].fav_time == 2000
    assert results[1].bvid == "BV2"
    assert results[1].fav_time == 1000
    # 无水位线时 need_wbi=False
    client.request.assert_awaited_once()
    call_kwargs = client.request.await_args.kwargs
    assert call_kwargs["need_wbi"] is False
    assert call_kwargs["path"] == "/x/v3/fav/resource/list"


@pytest.mark.asyncio
async def test_scan_favorite_stops_at_watermark():
    """fav_time <= latest_row_at 的条目应触发立即停止，不返回后续条目。"""
    client = _make_mock_client()
    # 3 条目，fav_time 分别为 3000 / 2000 / 1000，水位线 2000
    # 应在遍历到 fav_time=2000 时停止，仅返回 fav_time=3000 的条目
    client.request.return_value = {
        "code": 0,
        "data": {
            "medias": [
                _build_favorite_media("BV1", 1, "newer", fav_time=3000),
                _build_favorite_media("BV2", 2, "watermark-equal", fav_time=2000),
                _build_favorite_media("BV3", 3, "older", fav_time=1000),
            ],
            "has_more": True,
        },
    }

    results = await scan_favorite(client, media_id=999, latest_row_at=2000)

    # 只应返回 fav_time > 2000 的条目
    assert len(results) == 1
    assert results[0].bvid == "BV1"
    assert results[0].fav_time == 3000


@pytest.mark.asyncio
async def test_scan_favorite_handles_empty_medias():
    """响应 medias 为空时应立即返回空列表，不翻页。"""
    client = _make_mock_client()
    client.request.return_value = {
        "code": 0,
        "data": {"medias": [], "has_more": False},
    }

    results = await scan_favorite(client, media_id=999, latest_row_at=None)

    assert results == []
    client.request.assert_awaited_once()


@pytest.mark.asyncio
async def test_scan_favorite_paginates_until_has_more_false():
    """has_more=True 且页内条目数等于 ps 时应继续翻页，直到 has_more=False。"""
    client = _make_mock_client()
    # 构造 2 页响应：第 1 页 20 条 + has_more=True，第 2 页 5 条 + has_more=False
    page1_medias = [
        _build_favorite_media(f"BV{i}", i, f"title {i}", fav_time=10000 - i)
        for i in range(1, 21)
    ]
    page2_medias = [
        _build_favorite_media(f"BV{i}", i, f"title {i}", fav_time=9980 - i)
        for i in range(21, 26)
    ]

    client.request.side_effect = [
        {"code": 0, "data": {"medias": page1_medias, "has_more": True}},
        {"code": 0, "data": {"medias": page2_medias, "has_more": False}},
    ]

    results = await scan_favorite(client, media_id=999, latest_row_at=None)

    # 总数应为 20 + 5 = 25 条
    assert len(results) == 25
    # 应调用 2 次 request
    assert client.request.await_count == 2
    # 第 1 次页码 pn=1，第 2 次 pn=2
    first_call = client.request.await_args_list[0]
    second_call = client.request.await_args_list[1]
    assert first_call.kwargs["params"]["pn"] == 1
    assert second_call.kwargs["params"]["pn"] == 2


@pytest.mark.asyncio
async def test_scan_favorite_skips_non_dict_media():
    """medias 数组中的非 dict 元素应被跳过，不抛异常。"""
    client = _make_mock_client()
    client.request.return_value = {
        "code": 0,
        "data": {
            "medias": [
                "not-a-dict",
                None,
                _build_favorite_media("BV1", 1, "valid", fav_time=1000),
                42,
            ],
            "has_more": False,
        },
    }

    results = await scan_favorite(client, media_id=999, latest_row_at=None)

    assert len(results) == 1
    assert results[0].bvid == "BV1"


@pytest.mark.asyncio
async def test_scan_favorite_skips_media_without_bvid():
    """bvid 缺失的 media 元素应被跳过。"""
    client = _make_mock_client()
    bad_media = _build_favorite_media("", 1, "no-bvid", fav_time=1000)
    good_media = _build_favorite_media("BV1", 2, "with-bvid", fav_time=2000)
    client.request.return_value = {
        "code": 0,
        "data": {"medias": [bad_media, good_media], "has_more": False},
    }

    results = await scan_favorite(client, media_id=999, latest_row_at=None)

    assert len(results) == 1
    assert results[0].bvid == "BV1"


# ---------------------------------------------------------------------------
# 合集 Season 源测试
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scan_season_full_scan_no_pagination():
    """Season 合集应全量拉取，单页 < page_size 时停止。"""
    client = _make_mock_client()
    client.request.return_value = {
        "code": 0,
        "data": {
            "archives": [
                _build_archive("BV1", 1, "season 1", pubdate=1000),
                _build_archive("BV2", 2, "season 2", pubdate=2000),
            ],
        },
    }

    results = await scan_season(client, season_id=12345)

    assert len(results) == 2
    assert results[0].bvid == "BV1"
    assert results[0].pubtime == 1000
    assert results[1].bvid == "BV2"
    # Season 不使用 WBI 签名
    call_kwargs = client.request.await_args.kwargs
    assert call_kwargs["need_wbi"] is False
    assert call_kwargs["path"] == "/x/polymer/web-space/seasons_archives_list"
    # 全量扫描：不应传 latest_row_at（参数列表里不含该字段）
    assert "latest_row_at" not in call_kwargs["params"]


@pytest.mark.asyncio
async def test_scan_season_paginates_until_full_page_below_threshold():
    """页内条目数 < page_size（30）时应停止翻页。"""
    client = _make_mock_client()
    # 构造 1 页 30 条 + 1 页 5 条
    page1 = [_build_archive(f"BV{i}", i, f"title{i}", pubdate=i) for i in range(30)]
    page2 = [_build_archive(f"BV{i}", i, f"title{i}", pubdate=i) for i in range(30, 35)]

    client.request.side_effect = [
        {"code": 0, "data": {"archives": page1}},
        {"code": 0, "data": {"archives": page2}},
    ]

    results = await scan_season(client, season_id=1)

    assert len(results) == 35
    assert client.request.await_count == 2


@pytest.mark.asyncio
async def test_scan_season_empty_archives_returns_empty():
    """archives 为空时应立即返回空列表。"""
    client = _make_mock_client()
    client.request.return_value = {
        "code": 0,
        "data": {"archives": []},
    }

    results = await scan_season(client, season_id=1)

    assert results == []


# ---------------------------------------------------------------------------
# 视频列表 Series 源测试
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scan_series_full_scan():
    """Series 视频列表应全量拉取，单页 < page_size 时停止。"""
    client = _make_mock_client()
    client.request.return_value = {
        "code": 0,
        "data": {
            "archives": [
                _build_archive("BVS1", 1, "series 1", pubdate=5000),
                _build_archive("BVS2", 2, "series 2", pubdate=6000),
            ],
        },
    }

    results = await scan_series(client, series_id=888)

    assert len(results) == 2
    assert results[0].bvid == "BVS1"
    assert results[0].pubtime == 5000
    # Series 不使用 WBI
    call_kwargs = client.request.await_args.kwargs
    assert call_kwargs["need_wbi"] is False
    assert call_kwargs["path"] == "/x/series/archives"


@pytest.mark.asyncio
async def test_scan_series_empty_response_returns_empty():
    """archives 为空时应返回空列表。"""
    client = _make_mock_client()
    client.request.return_value = {
        "code": 0,
        "data": {"archives": []},
    }

    results = await scan_series(client, series_id=1)

    assert results == []


# ---------------------------------------------------------------------------
# 投稿源测试
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scan_submission_uses_wbi_signature():
    """投稿源 scan_submission 调用 arc/search 时必须传 need_wbi=True。"""
    client = _make_mock_client()
    client.request.return_value = {
        "code": 0,
        "data": {
            "list": {
                "vlist": [
                    _build_vlist_item("BV1", 1, "submission 1", created=2000),
                ],
            },
        },
    }

    results = await scan_submission(
        client, upper_mid=100, latest_row_at=None, use_dynamic_api=False
    )

    assert len(results) == 1
    assert results[0].bvid == "BV1"
    assert results[0].pubtime == 2000
    # 关键断言：投稿源必须启用 WBI 签名
    call_kwargs = client.request.await_args.kwargs
    assert call_kwargs["need_wbi"] is True
    assert call_kwargs["path"] == "/x/space/wbi/arc/search"


@pytest.mark.asyncio
async def test_scan_submission_stops_at_watermark():
    """投稿源增量扫描，pubtime <= latest_row_at 时应停止。"""
    client = _make_mock_client()
    client.request.return_value = {
        "code": 0,
        "data": {
            "list": {
                "vlist": [
                    _build_vlist_item("BV1", 1, "newer", created=3000),
                    _build_vlist_item("BV2", 2, "watermark-equal", created=2000),
                    _build_vlist_item("BV3", 3, "older", created=1000),
                ],
            },
        },
    }

    results = await scan_submission(
        client, upper_mid=100, latest_row_at=2000, use_dynamic_api=False
    )

    # 仅返回 pubtime > 2000 的条目
    assert len(results) == 1
    assert results[0].bvid == "BV1"


@pytest.mark.asyncio
async def test_scan_submission_with_dynamic_api_merges_pinned_video():
    """use_dynamic_api=True 时应先拉取动态首页，合并置顶视频到结果头部。"""
    client = _make_mock_client()
    # 动态首页响应（含 1 个置顶视频）
    dynamic_response = {
        "code": 0,
        "data": {
            "items": [
                {
                    "type": "DYNAMIC_TYPE_AV",
                    "modules": {
                        "module_dynamic": {
                            "major": {
                                "archive": {
                                    "bvid": "BVDYN1",
                                    "aid": 999,
                                    "title": "pinned video",
                                    "pic": "https://example.com/pin.jpg",
                                }
                            }
                        },
                        "module_author": {
                            "mid": 100,
                            "name": "UP",
                            "pub_ts": 5000,
                        },
                    },
                },
                {
                    "type": "DYNAMIC_TYPE_DRAW",  # 非视频类型，应被跳过
                    "modules": {},
                },
            ]
        },
    }
    # arc/search 响应（1 条常规投稿）
    arc_response = {
        "code": 0,
        "data": {
            "list": {
                "vlist": [
                    _build_vlist_item("BV1", 1, "regular submission", created=3000),
                ],
            },
        },
    }

    client.request.side_effect = [dynamic_response, arc_response]

    results = await scan_submission(
        client, upper_mid=100, latest_row_at=None, use_dynamic_api=True
    )

    # 动态置顶 + 投稿 = 2 条，置顶视频在首位
    assert len(results) == 2
    assert results[0].bvid == "BVDYN1"
    assert results[0].title == "pinned video"
    assert results[1].bvid == "BV1"

    # 应调用 2 次 request（动态首页 + arc/search）
    assert client.request.await_count == 2
    # 两个请求都应启用 WBI 签名
    first_call = client.request.await_args_list[0]
    second_call = client.request.await_args_list[1]
    assert first_call.kwargs["need_wbi"] is True
    assert second_call.kwargs["need_wbi"] is True
    assert first_call.kwargs["path"] == "/x/polymer/web-dynamic/v1/feed/space"
    assert second_call.kwargs["path"] == "/x/space/wbi/arc/search"


@pytest.mark.asyncio
async def test_scan_submission_dynamic_failure_does_not_block_main_path():
    """动态首页拉取失败（BilibiliAPIError）时应跳过，不阻塞主路径。"""
    from plugins.bilibili_toolkit_builtin.bilibili.wbi import BilibiliAPIError

    client = _make_mock_client()
    # 第 1 次（动态首页）抛 BilibiliAPIError，第 2 次（arc/search）正常返回
    client.request.side_effect = [
        BilibiliAPIError("dynamic api failed"),
        {
            "code": 0,
            "data": {
                "list": {
                    "vlist": [
                        _build_vlist_item("BV1", 1, "fallback", created=3000),
                    ],
                },
            },
        },
    ]

    results = await scan_submission(
        client, upper_mid=100, latest_row_at=None, use_dynamic_api=True
    )

    # 仅返回 arc/search 的 1 条，动态失败不阻塞主路径
    assert len(results) == 1
    assert results[0].bvid == "BV1"


# ---------------------------------------------------------------------------
# 稍后再看源测试
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scan_watchlater_returns_all_items():
    """稍后再看源应单次拉取全部列表，不做增量扫描。"""
    client = _make_mock_client()
    client.request.return_value = {
        "code": 0,
        "data": {
            "list": [
                _build_watchlater_item("BV1", 1, "watchlater 1", add_at=1000),
                _build_watchlater_item("BV2", 2, "watchlater 2", add_at=2000),
                _build_watchlater_item("BV3", 3, "watchlater 3", add_at=3000),
            ]
        },
    }

    results = await scan_watchlater(client)

    assert len(results) == 3
    assert results[0].bvid == "BV1"
    assert results[0].fav_time == 1000  # add_at 映射到 fav_time
    assert results[1].bvid == "BV2"
    assert results[2].bvid == "BV3"
    # 单次请求，不翻页
    client.request.assert_awaited_once()
    call_kwargs = client.request.await_args.kwargs
    assert call_kwargs["need_wbi"] is False
    assert call_kwargs["path"] == "/x/v2/history/toview"
    # params 为 None
    assert call_kwargs["params"] is None


@pytest.mark.asyncio
async def test_scan_watchlater_empty_list_returns_empty():
    """稍后再看为空时应返回空列表。"""
    client = _make_mock_client()
    client.request.return_value = {
        "code": 0,
        "data": {"list": []},
    }

    results = await scan_watchlater(client)

    assert results == []


@pytest.mark.asyncio
async def test_scan_watchlater_skips_items_without_bvid():
    """bvid 缺失的条目应被跳过。"""
    client = _make_mock_client()
    bad_item = _build_watchlater_item("", 1, "no-bvid", add_at=1000)
    good_item = _build_watchlater_item("BV1", 2, "with-bvid", add_at=2000)
    client.request.return_value = {
        "code": 0,
        "data": {"list": [bad_item, good_item]},
    }

    results = await scan_watchlater(client)

    assert len(results) == 1
    assert results[0].bvid == "BV1"


# ---------------------------------------------------------------------------
# ScanResult 数据类测试
# ---------------------------------------------------------------------------


def test_scan_result_defaults():
    """ScanResult 字段应有合理默认值。"""
    result = ScanResult(bvid="BV1xx")
    assert result.aid == 0
    assert result.title == ""
    assert result.cover == ""
    assert result.upper_mid == 0
    assert result.upper_name == ""
    assert result.pages_count == 0
    assert result.pubtime == 0
    assert result.fav_time is None


def test_scan_result_full_fields():
    """ScanResult 应正确承载所有字段。"""
    result = ScanResult(
        bvid="BV1xx",
        aid=12345,
        title="测试视频",
        cover="https://example.com/c.jpg",
        upper_mid=999,
        upper_name="UP主",
        pages_count=3,
        pubtime=1700000000,
        fav_time=1700000100,
    )
    assert result.bvid == "BV1xx"
    assert result.aid == 12345
    assert result.title == "测试视频"
    assert result.upper_mid == 999
    assert result.pages_count == 3
    assert result.pubtime == 1700000000
    assert result.fav_time == 1700000100
