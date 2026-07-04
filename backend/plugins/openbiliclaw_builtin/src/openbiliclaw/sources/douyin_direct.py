"""直连 Cookie 抖音发现客户端及规范化辅助函数。"""

from __future__ import annotations

import logging
from typing import Any, Protocol
from urllib.parse import urlencode

import httpx

from openbiliclaw.discovery.engine import DiscoveredContent
from openbiliclaw.sources.douyin_signature import XBogusSigner

logger = logging.getLogger(__name__)

_DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


class DouyinDirectError(RuntimeError):
    """直连 Cookie 抖音发现的基类错误。"""


class DouyinDirectAuthError(DouyinDirectError):
    """直连 Cookie 模式没有可用 Cookie 时抛出。"""


class DouyinDirectSignatureError(DouyinDirectError):
    """URL 签名失败时抛出。"""


class UrlSigner(Protocol):
    user_agent: str

    def sign(self, url: str) -> str: ...


def parse_cookie_header(cookie: str) -> dict[str, str]:
    """将浏览器 Cookie 头解析为名称/值对。"""
    pairs: dict[str, str] = {}
    for part in cookie.split(";"):
        if "=" not in part:
            continue
        name, value = part.split("=", 1)
        name = name.strip()
        value = value.strip()
        if not name or not value:
            continue
        pairs[name] = value
    return pairs


def normalize_aweme_item(
    item: dict[str, Any],
    *,
    source_strategy: str,
) -> DiscoveredContent | None:
    """将一个抖音 aweme JSON 对象映射为 ``DiscoveredContent``。"""
    aweme_id = str(item.get("aweme_id", "") or "").strip()
    if not aweme_id:
        return None

    title = _first_text(
        item.get("desc"),
        _get_nested(item, ("share_info", "share_title")),
        _get_nested(item, ("share_info", "share_desc")),
    )
    author = _first_text(
        _get_nested(item, ("author", "nickname")),
        _get_nested(item, ("author", "unique_id")),
    )
    cover_url = _first_url(
        _get_nested(item, ("video", "cover", "url_list")),
        _get_nested(item, ("video", "origin_cover", "url_list")),
        _get_nested(item, ("video", "animated_cover", "url_list")),
    )
    duration_ms = _to_int(_get_nested(item, ("video", "duration")))
    raw_statistics = item.get("statistics")
    if not isinstance(raw_statistics, dict):
        raw_statistics = item.get("stats")
    statistics: dict[str, Any] = raw_statistics if isinstance(raw_statistics, dict) else {}

    return DiscoveredContent(
        bvid=f"dy:{aweme_id}",
        title=title,
        up_name=author,
        cover_url=cover_url,
        duration=duration_ms // 1000 if duration_ms else 0,
        view_count=_to_int(statistics.get("play_count")),
        like_count=_to_int(statistics.get("digg_count")),
        collect_count=_to_int(statistics.get("collect_count")),
        comment_count=_to_int(statistics.get("comment_count")),
        share_count=_to_int(statistics.get("share_count")),
        description=title,
        source_strategy=source_strategy,
        content_id=aweme_id,
        content_url=f"https://www.douyin.com/video/{aweme_id}",
        source_platform="douyin",
        author_name=author,
    )


class DouyinDirectClient:
    """轻量直连 Cookie 抖音 Web API 客户端。

    该客户端仅覆盖发现接口，并非下载器，也不会持久化 Cookie。
    """

    BASE_URL = "https://www.douyin.com"

    def __init__(
        self,
        *,
        cookie: str,
        http_client: httpx.AsyncClient | None = None,
        signer: UrlSigner | None = None,
        user_agent: str = _DEFAULT_USER_AGENT,
    ) -> None:
        self.cookie = cookie.strip()
        self.cookies = parse_cookie_header(self.cookie)
        if not self.cookie or not self.cookies:
            raise DouyinDirectAuthError("Douyin direct discovery requires a cookie.")

        self._owns_http_client = http_client is None
        self._http = http_client or httpx.AsyncClient(timeout=30.0)
        self._signer = signer or XBogusSigner(user_agent)
        self._user_agent = self._signer.user_agent

    async def __aenter__(self) -> DouyinDirectClient:
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_http_client:
            await self._http.aclose()

    async def search_aweme(self, keyword: str, *, limit: int = 30) -> list[dict[str, Any]]:
        """获取 *keyword* 的抖音视频搜索结果。"""
        if not keyword.strip() or limit <= 0:
            return []

        collected: list[dict[str, Any]] = []
        offset = 0
        while len(collected) < limit:
            count = min(20, limit - len(collected))
            data = await self._request_json(
                "/aweme/v1/web/general/search/single/",
                {
                    "search_channel": "aweme_video_web",
                    "keyword": keyword,
                    "search_source": "normal_search",
                    "query_correct_type": 1,
                    "is_filter_search": 0,
                    "offset": offset,
                    "count": count,
                },
            )
            page_items = _extract_search_items(data)
            collected.extend(page_items)
            if len(collected) >= limit or not _has_more(data):
                break
            next_offset = _cursor_value(data)
            if next_offset == offset:
                break
            offset = next_offset
        return _dedupe_awemes(collected)[:limit]

    async def get_hot_board(self, *, limit: int = 30) -> list[dict[str, Any]]:
        """获取抖音热搜榜行所附带的 aweme 条目。"""
        if limit <= 0:
            return []
        data = await self._request_json(
            "/aweme/v1/web/hot/search/list/",
            {
                "detail_list": 1,
                "source": 6,
            },
        )
        return _dedupe_awemes(_extract_hot_awemes(data))[:limit]

    async def get_hot_terms(self, *, limit: int = 30) -> list[dict[str, Any]]:
        """获取带 ``sentence_id`` 的抖音热搜行，供 /hot 路由使用。"""
        if limit <= 0:
            return []
        data = await self._request_json(
            "/aweme/v1/web/hot/search/list/",
            {
                "detail_list": 1,
                "source": 6,
            },
        )
        return _extract_hot_terms(data)[:limit]

    async def get_creator_posts(self, sec_uid: str, *, limit: int = 30) -> list[dict[str, Any]]:
        """获取某创作者 ``sec_uid`` 的近期作品。"""
        sec_uid = sec_uid.strip()
        if not sec_uid or limit <= 0:
            return []

        collected: list[dict[str, Any]] = []
        max_cursor = 0
        while len(collected) < limit:
            count = min(20, limit - len(collected))
            data = await self._request_json(
                "/aweme/v1/web/aweme/post/",
                {
                    "sec_user_id": sec_uid,
                    "max_cursor": max_cursor,
                    "count": count,
                    "locate_query": "false",
                    "show_live_replay_strategy": 1,
                },
            )
            page_items = data.get("aweme_list")
            if not isinstance(page_items, list):
                break
            collected.extend(item for item in page_items if isinstance(item, dict))
            if len(collected) >= limit or not _has_more(data):
                break
            next_cursor = _cursor_value(data)
            if next_cursor == max_cursor:
                break
            max_cursor = next_cursor
        return _dedupe_awemes(collected)[:limit]

    async def get_recommend_feed(self, *, limit: int = 30) -> list[dict[str, Any]]:
        """通过直连 Cookie 模式获取抖音首页推荐信息流。

        该源优先使用浏览器插件路径，因为该端点对页面会话状态敏感。
        此兜底仅为完整客户端协议保留，便于诊断。
        """
        if limit <= 0:
            return []
        data = await self._request_json(
            "/aweme/v1/web/tab/feed/",
            {
                "count": min(20, max(1, limit)),
                "tag_id": "",
                "share_aweme_id": "",
                "live_insert_type": "",
                "refresh_index": 1,
                "video_type_select": 1,
                "aweme_pc_rec_raw_data": '{"is_client":"false"}',
                "globalwid": "",
                "pull_type": "",
                "min_window": "",
                "free_right": "",
                "ug_source": "",
                "creative_id": "",
            },
        )
        raw_items = data.get("aweme_list")
        if not isinstance(raw_items, list):
            raw_items = data.get("data")
        if not isinstance(raw_items, list):
            return []
        items = [item for item in raw_items if isinstance(item, dict)]
        return _dedupe_awemes(items)[:limit]

    async def _request_json(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        query = {**self._default_query(), **params}
        unsigned = f"{self.BASE_URL}{path}?{urlencode(query)}"
        try:
            url = self._signer.sign(unsigned)
        except Exception as exc:  # pragma: no cover - 防御性缝隙，应对实时签名器漂移
            raise DouyinDirectSignatureError("Failed to sign Douyin request URL.") from exc

        try:
            response = await self._http.get(
                url,
                headers={
                    "Accept": "application/json",
                    "Accept-Language": "zh-CN,zh;q=0.9",
                    "Cookie": self.cookie,
                    "Referer": "https://www.douyin.com/",
                    "User-Agent": self._user_agent,
                },
            )
        except httpx.HTTPError as exc:
            logger.info("douyin direct request failed for %s: %s", path, exc)
            return {}
        if response.status_code != 200:
            logger.info("douyin direct request returned HTTP %s for %s", response.status_code, path)
            return {}
        try:
            data = response.json()
        except ValueError:
            logger.info("douyin direct request returned non-JSON body for %s", path)
            return {}
        return data if isinstance(data, dict) else {}

    def _default_query(self) -> dict[str, Any]:
        return {
            "device_platform": "webapp",
            "aid": "6383",
            "channel": "channel_pc_web",
            "pc_client_type": "1",
            "version_code": "290100",
            "version_name": "29.1.0",
            "cookie_enabled": "true",
            "screen_width": "1920",
            "screen_height": "1080",
            "browser_language": "zh-CN",
            "browser_platform": "Win32",
            "browser_name": "Chrome",
            "browser_version": "131.0.0.0",
            "browser_online": "true",
            "engine_name": "Blink",
            "engine_version": "131.0.0.0",
            "os_name": "Windows",
            "os_version": "10",
            "platform": "PC",
            "msToken": self.cookies.get("msToken", ""),
        }


def _get_nested(item: dict[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = item
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _first_url(*values: Any) -> str:
    for value in values:
        if isinstance(value, list):
            for item in value:
                text = str(item or "").strip()
                if text:
                    return text
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _to_int(value: Any) -> int:
    try:
        return int(float(str(value or 0)))
    except (TypeError, ValueError):
        return 0


def _has_more(data: dict[str, Any]) -> bool:
    value = data.get("has_more", False)
    if isinstance(value, bool):
        return value
    return _to_int(value) > 0


def _cursor_value(data: dict[str, Any]) -> int:
    return _to_int(data.get("cursor", data.get("max_cursor", 0)))


def _extract_search_items(data: dict[str, Any]) -> list[dict[str, Any]]:
    raw_items = data.get("data")
    if not isinstance(raw_items, list):
        raw_items = data.get("aweme_list")
    if not isinstance(raw_items, list):
        return []

    items: list[dict[str, Any]] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        aweme = raw.get("aweme_info") or raw.get("item") or raw
        if isinstance(aweme, dict):
            items.append(aweme)
    return items


def _extract_hot_awemes(data: dict[str, Any]) -> list[dict[str, Any]]:
    container = data.get("data")
    if isinstance(container, dict):
        raw_items = container.get("word_list") or container.get("trending_list")
    else:
        raw_items = data.get("word_list")
    if not isinstance(raw_items, list):
        return []

    items: list[dict[str, Any]] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        aweme = raw.get("aweme_info") or raw.get("aweme")
        if isinstance(aweme, dict):
            items.append(aweme)
    return items


def _extract_hot_terms(data: dict[str, Any]) -> list[dict[str, Any]]:
    container = data.get("data")
    if isinstance(container, dict):
        raw_items = container.get("word_list") or container.get("trending_list")
    else:
        raw_items = data.get("word_list")
    if not isinstance(raw_items, list):
        return []

    terms: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        sentence_id = _first_text(raw.get("sentence_id"), raw.get("sentenceId"), raw.get("id"))
        if not sentence_id or sentence_id in seen:
            continue
        seen.add(sentence_id)

        term: dict[str, Any] = {
            "word": _first_text(raw.get("word"), raw.get("sentence"), raw.get("event_word")),
            "sentence_id": sentence_id,
        }
        for key in ("hot_value", "position", "rank", "event_time"):
            if key in raw:
                term[key] = raw[key]
        seed_aweme_id = _first_text(raw.get("group_id"), raw.get("aweme_id"))
        if seed_aweme_id:
            term["group_id"] = seed_aweme_id
            term["seed_aweme_id"] = seed_aweme_id
        aweme = raw.get("aweme_info") or raw.get("aweme")
        if isinstance(aweme, dict):
            term["aweme"] = aweme
        terms.append(term)
    return terms


def _dedupe_awemes(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for item in items:
        aweme_id = str(item.get("aweme_id", "") or "").strip()
        if not aweme_id or aweme_id in seen:
            continue
        seen.add(aweme_id)
        deduped.append(item)
    return deduped
