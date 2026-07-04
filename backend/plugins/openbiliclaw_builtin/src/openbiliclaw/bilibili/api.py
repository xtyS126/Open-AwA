"""Bilibili API 客户端。

与 Bilibili 交互的主接口，优先使用官方和逆向工程 API
以追求速度与效率。
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
from dataclasses import dataclass
from typing import Any, ClassVar, cast
from urllib.parse import quote, urlencode, urlparse

import httpx

logger = logging.getLogger(__name__)


class BilibiliAPIError(RuntimeError):
    """当 Bilibili API 请求返回应用错误时抛出。"""


class BilibiliAuthExpiredError(BilibiliAPIError):
    """当 Bilibili 报告当前 Cookie 已登出时抛出。"""


def _json_object(value: Any) -> dict[str, Any]:
    """将 JSON 值强制转换为对象以便严格类型校验。

    当 *value* 为 ``None`` 时返回空 dict（这在 B站 限流或
    排行榜分区为空时返回 ``"data": null`` 很常见），
    与 :func:`_json_list` 的 null 处理保持一致。
    """
    if value is None:
        return {}
    return cast("dict[str, Any]", value)


def _json_list(value: Any) -> list[dict[str, Any]]:
    """将 JSON 值强制转换为对象列表以便严格类型校验。

    当 *value* 为 ``None`` 时返回空列表（这在 B站 限流时
    返回 ``"result": null`` 很常见）。
    """
    if value is None:
        return []
    return cast("list[dict[str, Any]]", value)


@dataclass
class VideoInfo:
    """Bilibili 视频基本信息。"""

    bvid: str = ""
    aid: int = 0
    title: str = ""
    description: str = ""
    duration: int = 0  # 秒
    cover_url: str = ""
    up_name: str = ""
    up_mid: int = 0
    view_count: int = 0
    like_count: int = 0
    coin_count: int = 0
    favorite_count: int = 0
    share_count: int = 0
    danmaku_count: int = 0
    tags: list[str] | None = None
    pub_date: str = ""


@dataclass
class NavInfo:
    """来自 nav 端点的基本已登录用户信息。"""

    is_login: bool = False
    uname: str = ""
    mid: int = 0


@dataclass
class FavoriteFolder:
    """收藏夹元数据。"""

    media_id: int
    title: str
    media_count: int = 0


@dataclass
class FavoriteFolderWithItems:
    """收藏夹及其已抓取条目。"""

    folder: FavoriteFolder
    items: list[dict[str, Any]]
    truncated: bool = False


@dataclass
class FollowingUser:
    """基本关注用户信息。"""

    mid: int
    uname: str
    sign: str = ""


@dataclass
class CommentInfo:
    """基本评论信息。"""

    mid: int
    uname: str
    message: str
    like_count: int = 0


class BilibiliAPIClient:
    """Bilibili Web API 客户端。

    这是主数据访问层（API 优先策略）。
    对于 API 不支持的操作，请使用 BilibiliBrowser。
    """

    _BASE_URL = "https://api.bilibili.com"
    _SEARCH_WEB_LOCATION = 1430654
    # v_voucher 耗尽通常是可以恢复的 WBI 密钥轮换 / 轻度限流，
    # 所以采用短暂、逐步升级的退避。真正的 HTTP 412 是显式的
    # IP 级别封禁，会触发更长的硬冷却
    # （见 ``_SEARCH_COOLDOWN_412_SECONDS``）。
    _SEARCH_COOLDOWN_BASE_SECONDS: ClassVar[float] = 180.0
    _SEARCH_COOLDOWN_412_SECONDS: ClassVar[float] = 600.0
    _SEARCH_COOLDOWN_MAX_SECONDS: ClassVar[float] = 1800.0
    _SEARCH_DOM_FALLBACK_SECONDS: ClassVar[float] = 180.0
    # 单个关键词被挑战（瞬时轮换）不能清零整个搜索轮次 + 与之共享
    # 冷却的 explore 策略。只有连续 *多次* 关键词级 v_voucher 耗尽
    # 后才触发进程级冷却；任何一次成功都会重置连续计数。
    _SEARCH_VOUCHER_BLOCK_THRESHOLD: ClassVar[int] = 3
    _search_cooldown_until: ClassVar[float] = 0.0
    _search_cooldown_level: ClassVar[int] = 0
    _search_voucher_block_streak: ClassVar[int] = 0
    _search_dom_fallback_until: ClassVar[float] = 0.0
    _WBI_MIXIN_KEY_ENC_TAB = [
        46,
        47,
        18,
        2,
        53,
        8,
        23,
        32,
        15,
        50,
        10,
        31,
        58,
        3,
        45,
        35,
        27,
        43,
        5,
        49,
        33,
        9,
        42,
        19,
        29,
        28,
        14,
        39,
        12,
        38,
        41,
        13,
        37,
        48,
        7,
        16,
        24,
        55,
        40,
        61,
        26,
        17,
        0,
        1,
        60,
        51,
        30,
        4,
        22,
        25,
        54,
        21,
        56,
        59,
        6,
        63,
        57,
        62,
        11,
        36,
        20,
        34,
        44,
        52,
    ]

    _WBI_KEY_TTL: float = 300.0  # 每 5 分钟刷新一次 WBI 密钥

    def __init__(self, cookie: str = "", *, min_request_interval: float = 0.2) -> None:
        self._cookie = cookie
        self._min_request_interval = min_request_interval
        self._last_request_at = 0.0
        self._cached_wbi_keys: tuple[str, str] | None = None
        self._wbi_keys_fetched_at: float = 0.0
        self._client = httpx.AsyncClient(
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Referer": "https://www.bilibili.com",
            },
            timeout=30.0,
        )
        if cookie:
            self._client.headers["Cookie"] = cookie

    @property
    def is_authenticated(self) -> bool:
        """是否拥有有效的认证 Cookie。"""
        return bool(self._cookie)

    async def _respect_rate_limit(self) -> None:
        """等待以满足请求之间的最小间隔。"""
        elapsed = time.monotonic() - self._last_request_at
        remaining = self._min_request_interval - elapsed
        if remaining > 0:
            await asyncio.sleep(remaining)
        self._last_request_at = time.monotonic()

    @classmethod
    def search_cooldown_remaining(cls) -> float:
        """进程级 Bilibili 搜索冷却剩余秒数。"""
        return max(0.0, cls._search_cooldown_until - time.monotonic())

    @classmethod
    def search_dom_fallback_remaining(cls) -> float:
        """渲染页面搜索回退被偏好的剩余秒数。"""
        return max(0.0, cls._search_dom_fallback_until - time.monotonic())

    @classmethod
    def _activate_search_dom_fallback(cls, *, seconds: float | None = None) -> float:
        """请求扩展搜索生产者尽快尝试 DOM 搜索。

        这个信号故意弱于全局冷却：API 搜索可以继续探活，
        但浏览器扩展可以在 API 路径降级期间通过渲染的搜索
        页面进行回填。
        """
        duration = cls._SEARCH_DOM_FALLBACK_SECONDS if seconds is None else seconds
        cls._search_dom_fallback_until = max(
            cls._search_dom_fallback_until,
            time.monotonic() + duration,
        )
        return duration

    @classmethod
    def _activate_search_cooldown(cls, *, base_seconds: float | None = None) -> float:
        """在重复 v_voucher/412 封禁后让所有搜索客户端退避。

        ``base_seconds`` 覆盖每步基数（412 封禁传入更长的硬冷却
        基数）；升级倍数与绝对上限在两种原因之间共享。
        """
        cls._search_cooldown_level = min(cls._search_cooldown_level + 1, 3)
        base = cls._SEARCH_COOLDOWN_BASE_SECONDS if base_seconds is None else base_seconds
        duration = min(
            base * cls._search_cooldown_level,
            cls._SEARCH_COOLDOWN_MAX_SECONDS,
        )
        cls._search_cooldown_until = max(
            cls._search_cooldown_until,
            time.monotonic() + duration,
        )
        cls._activate_search_dom_fallback(seconds=duration)
        return duration

    @classmethod
    def _record_voucher_block(cls) -> float:
        """记录一个关键词耗尽其 v_voucher 重试。

        如果本次封禁跨越了连续失败阈值（整个搜索路径现在退避），
        返回冷却时长；若搜索保持可用、仅丢弃当前关键词，
        则返回 ``0.0`` —— 单个被挑战的关键词通常是瞬时 WBI
        轮换，并非 IP 级封禁，不应让整个搜索轮次 + explore
        在完整冷却中被搁置。
        """
        cls._search_voucher_block_streak += 1
        if cls._search_voucher_block_streak >= cls._SEARCH_VOUCHER_BLOCK_THRESHOLD:
            return cls._activate_search_cooldown()
        return 0.0

    @classmethod
    def _reset_search_cooldown_backoff(cls) -> None:
        """搜索再次成功后重置升级 + v_voucher 连续计数。"""
        cls._search_cooldown_level = 0
        cls._search_voucher_block_streak = 0

    async def _get_json(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """执行 GET 请求并返回解码后的 `data` 载荷。"""
        await self._respect_rate_limit()
        try:
            resp = await self._client.get(
                f"{self._BASE_URL}{path}",
                params=params,
                headers=headers,
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise BilibiliAPIError(str(exc)) from exc

        payload = _json_object(resp.json())
        code = int(payload.get("code", 0))
        if code != 0:
            message = str(payload.get("message", "Bilibili API request failed"))
            if path == "/x/web-interface/nav" and code == -101:
                detail = (
                    f"Bilibili session expired on {path} (-101): {message}. "
                    "Please re-authenticate in the browser or keep the extension "
                    "online to sync a fresh Cookie."
                )
                logger.warning("%s", detail)
                raise BilibiliAuthExpiredError(detail)
            raise BilibiliAPIError(message)
        return _json_object(payload.get("data", {}))

    async def _get_wbi_keys(self) -> tuple[str, str]:
        """获取并缓存用于签名搜索请求的 WBI image/sub 密钥。

        密钥在 :attr:`_WBI_KEY_TTL` 秒后刷新，因为 B站 会
        周期性轮换它们 —— 旧密钥会导致搜索返回空的
        ``v_voucher`` 响应而非真实结果。
        """
        if (
            self._cached_wbi_keys is not None
            and (time.monotonic() - self._wbi_keys_fetched_at) < self._WBI_KEY_TTL
        ):
            return self._cached_wbi_keys

        await self._respect_rate_limit()
        try:
            resp = await self._client.get(f"{self._BASE_URL}/x/web-interface/nav")
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise BilibiliAPIError(str(exc)) from exc

        payload = _json_object(resp.json())
        data = _json_object(payload.get("data", {}))
        wbi_img = _json_object(data.get("wbi_img", {}))
        img_key = self._extract_wbi_key_component(str(wbi_img.get("img_url", "")))
        sub_key = self._extract_wbi_key_component(str(wbi_img.get("sub_url", "")))
        if not img_key or not sub_key:
            raise BilibiliAPIError("Missing wbi keys in nav response")
        self._cached_wbi_keys = (img_key, sub_key)
        self._wbi_keys_fetched_at = time.monotonic()
        return self._cached_wbi_keys

    @staticmethod
    def _extract_wbi_key_component(url: str) -> str:
        """从 WBI 图片 URL 中返回密钥片段。"""
        path = urlparse(url).path
        filename = path.rsplit("/", 1)[-1]
        return filename.rsplit(".", 1)[0]

    @classmethod
    def _build_wbi_mixin_key(cls, img_key: str, sub_key: str) -> str:
        """构建 Bilibili WBI 请求签名使用的混合密钥。"""
        merged = img_key + sub_key
        return "".join(merged[index] for index in cls._WBI_MIXIN_KEY_ENC_TAB)[:32]

    @classmethod
    def _sign_wbi_params(
        cls,
        params: dict[str, object],
        *,
        img_key: str,
        sub_key: str,
    ) -> dict[str, str]:
        """使用 Bilibili 的 WBI 算法对搜索参数进行签名。"""
        mixin_key = cls._build_wbi_mixin_key(img_key, sub_key)
        signed_params = {**params, "wts": int(time.time())}
        ordered_items = sorted(signed_params.items())
        sanitized = {key: re.sub(r"[!'()*]", "", str(value)) for key, value in ordered_items}
        query = urlencode(sanitized)
        sanitized["w_rid"] = hashlib.md5((query + mixin_key).encode()).hexdigest()
        return sanitized

    async def get_nav_info(self) -> NavInfo:
        """从 Bilibili nav API 获取当前登录状态。"""
        data = await self._get_json("/x/web-interface/nav")
        return NavInfo(
            is_login=bool(data.get("isLogin", False)),
            uname=str(data.get("uname", "")),
            mid=int(data.get("mid", 0)),
        )

    async def get_video_info(self, bvid: str) -> VideoInfo:
        """根据 BV ID 获取视频信息。

        Args:
            bvid: Bilibili 视频 BV ID。

        Returns:
            VideoInfo 数据类。
        """
        resp = await self._client.get(
            f"{self._BASE_URL}/x/web-interface/view",
            params={"bvid": bvid},
        )
        resp.raise_for_status()
        payload = _json_object(resp.json())
        data = _json_object(payload.get("data"))
        stat = _json_object(data.get("stat", {}))
        owner = _json_object(data.get("owner", {}))

        return VideoInfo(
            bvid=data.get("bvid", bvid),
            aid=data.get("aid", 0),
            title=data.get("title", ""),
            description=data.get("desc", ""),
            duration=data.get("duration", 0),
            cover_url=data.get("pic", ""),
            up_name=owner.get("name", ""),
            up_mid=owner.get("mid", 0),
            view_count=stat.get("view", 0),
            like_count=stat.get("like", 0),
            coin_count=stat.get("coin", 0),
            favorite_count=stat.get("favorite", 0),
            share_count=stat.get("share", 0),
            danmaku_count=stat.get("danmaku", 0),
            pub_date=data.get("pubdate", ""),
        )

    async def search(
        self,
        keyword: str,
        page: int = 1,
        page_size: int = 20,
        order: str = "totalrank",
    ) -> list[dict[str, Any]]:
        """按关键词搜索视频。

        Args:
            keyword: 搜索查询。
            page: 页码。
            page_size: 每页结果数。

        Returns:
            搜索结果字典列表。
        """
        cooldown_remaining = self.search_cooldown_remaining()
        if cooldown_remaining > 0:
            logger.info(
                "Bilibili search cooldown active (%.0fs left) — skipping query=%r",
                cooldown_remaining,
                keyword,
            )
            return []

        # v0.3.55+：3 次尝试，指数退避（原来是 2 次、1.5s 线性）。
        # 生产日志（2026-05-05）显示 43 分钟内出现 141 次 v_voucher
        # 挑战；仅 1 次重试时，约 9 个完整搜索轮次返回 0 结果，
        # 因为关键词被挑战两次后我们就放弃。新调度（1.5s / 5s / 15s
        # = 每关键词约 21s）让 WBI 密钥轮换平息而不立即投降。
        # 稳态成本为零 —— 密钥健康时不会触发重试。
        #
        # 一旦疑似风暴就快速失败：每轮第一个失败的关键词获得
        # 完整重试预算以便瞬时轮换平息，但一旦已有某个关键词
        # 完全耗尽（streak>0），我们就降为单次快速探活 —— 用几次
        # 快速尝试确认真正的风暴，而不是对每个关键词都向 B站 砸
        # 约 21s 注定失败的重试链（那样只会加深封禁）。
        max_attempts = 1 if type(self)._search_voucher_block_streak > 0 else 3
        backoff_schedule = (1.5, 5.0, 15.0)
        for attempt in range(max_attempts):
            try:
                img_key, sub_key = await self._get_wbi_keys()
                data = await self._get_json(
                    "/x/web-interface/wbi/search/type",
                    params=self._sign_wbi_params(
                        {
                            "keyword": keyword,
                            "search_type": "video",
                            "page": page,
                            "page_size": page_size,
                            "order": order,
                            "web_location": self._SEARCH_WEB_LOCATION,
                        },
                        img_key=img_key,
                        sub_key=sub_key,
                    ),
                    headers={
                        "Referer": (
                            f"https://search.bilibili.com/all?keyword={quote(keyword, safe='')}"
                        ),
                        "Origin": "https://search.bilibili.com",
                    },
                )
            except BilibiliAPIError as exc:
                cause = exc.__cause__
                if isinstance(cause, httpx.HTTPStatusError) and cause.response.status_code == 412:
                    # 412 是显式的 IP 级封禁 —— 立即硬退避
                    # （无 streak 阈值），使用更长的基数。
                    duration = self._activate_search_cooldown(
                        base_seconds=self._SEARCH_COOLDOWN_412_SECONDS
                    )
                    logger.warning(
                        "Bilibili search blocked with 412 for query=%r — "
                        "cooling down search for %.0fs",
                        keyword,
                        duration,
                    )
                    return []
                self._activate_search_dom_fallback()
                raise

            # 检测仅 v_voucher 响应（WBI 密钥过期或限流）
            if "v_voucher" in data and data.get("result") is None:
                if attempt < max_attempts - 1:
                    delay = backoff_schedule[attempt]
                    logger.info(
                        "Search v_voucher challenge (attempt %d/%d) for query=%r — "
                        "refreshing WBI keys, retry in %.1fs",
                        attempt + 1,
                        max_attempts,
                        keyword,
                        delay,
                    )
                    self._cached_wbi_keys = None
                    await asyncio.sleep(delay)
                    continue
                # 最终尝试仍然得到 v_voucher。记录封禁；只有连续关键词
                # 失败跨越阈值时才触发共享冷却 —— 单个被挑战的关键词
                # 仅被丢弃，使本轮的其余部分（以及 explore）保持可用。
                self._activate_search_dom_fallback()
                duration = self._record_voucher_block()
                if duration > 0:
                    logger.warning(
                        "Search v_voucher storm confirmed (%d consecutive blocked "
                        "queries, latest=%r) — cooling down search for %.0fs "
                        "(likely WBI storm or IP rate limit)",
                        type(self)._search_voucher_block_streak,
                        keyword,
                        duration,
                    )
                else:
                    logger.info(
                        "Search v_voucher challenge persisted for query=%r "
                        "(streak %d/%d) — dropping this keyword; search stays live",
                        keyword,
                        type(self)._search_voucher_block_streak,
                        self._SEARCH_VOUCHER_BLOCK_THRESHOLD,
                    )
                return []

            results = _json_list(data.get("result", []))
            self._reset_search_cooldown_backoff()
            if not results:
                logger.debug("Search returned empty result for query=%r", keyword)
            return results
        return []

    async def get_user_history(self, max_items: int = 100) -> list[dict[str, Any]]:
        """获取已登录用户的观看历史。

        需要有效的认证 Cookie。

        Args:
            max_items: 最多抓取的历史条目数。0 表示抓取全部。

        Returns:
            历史条目字典列表。
        """
        if not self.is_authenticated:
            logger.warning("Cannot fetch history without authentication.")
            return []

        items: list[dict[str, Any]] = []
        cursor_params: dict[str, Any] = {"type": "archive"}
        while max_items == 0 or len(items) < max_items:
            data = await self._get_json(
                "/x/web-interface/history/cursor",
                params=cursor_params,
            )
            batch = _json_list(data.get("list", []))
            if not batch:
                break
            items.extend(batch)
            cursor = _json_object(data.get("cursor", {}))
            next_max = cursor.get("max")
            next_view_at = cursor.get("view_at")
            if not next_max or not next_view_at:
                break
            cursor_params = {
                "type": "archive",
                "max": next_max,
                "view_at": next_view_at,
            }
        return items if max_items == 0 else items[:max_items]

    async def get_favorites(
        self,
        media_id: int,
        *,
        max_items: int = 20,
        page_size: int = 20,
    ) -> list[dict[str, Any]]:
        """获取收藏夹中的内容。

        Args:
            media_id: 收藏夹 media ID。
            max_items: 最多抓取的收藏条目数。
            page_size: Bilibili resource list 端点的页大小。

        Returns:
            收藏条目字典列表。
        """
        item_limit = max(0, int(max_items))
        if item_limit <= 0:
            return []

        effective_page_size = max(1, min(int(page_size), 20))
        items: list[dict[str, Any]] = []
        page = 1
        while len(items) < item_limit:
            data = await self._get_json(
                "/x/v3/fav/resource/list",
                params={"media_id": media_id, "pn": page, "ps": effective_page_size},
            )
            batch = _json_list(data.get("medias", []))
            if not batch:
                break
            items.extend(batch)
            has_more = data.get("has_more")
            if has_more is not None:
                if not bool(has_more):
                    break
            elif len(batch) < effective_page_size:
                break
            page += 1
        return items[:item_limit]

    async def get_favorite_folders(self) -> list[FavoriteFolder]:
        """获取已登录用户的收藏夹元数据。"""
        nav = await self.get_nav_info()
        data = await self._get_json(
            "/x/v3/fav/folder/created/list-all",
            params={"up_mid": nav.mid},
        )
        folders = _json_list(data.get("list", []))
        return [
            FavoriteFolder(
                media_id=int(folder.get("id", 0)),
                title=str(folder.get("title", "")),
                media_count=int(folder.get("media_count", 0)),
            )
            for folder in folders
        ]

    async def get_all_favorites(
        self,
        *,
        max_folders: int = 10,
        max_items_per_folder: int = 50,
        max_total_items: int | None = None,
    ) -> list[FavoriteFolderWithItems]:
        """获取收藏夹并在预算内抓取每个收藏夹的条目。"""
        folders = await self.get_favorite_folders()
        folder_limit = max(0, int(max_items_per_folder))
        folder_count = max(0, int(max_folders))
        if folder_count <= 0 or folder_limit <= 0:
            return []

        remaining_total: int | None
        if max_total_items is None:
            remaining_total = None
        else:
            remaining_total = max(0, int(max_total_items))
            if remaining_total <= 0:
                return []

        aggregated: list[FavoriteFolderWithItems] = []
        for folder in folders[:folder_count]:
            if remaining_total is not None and remaining_total <= 0:
                break
            current_limit = folder_limit
            if remaining_total is not None:
                current_limit = min(current_limit, remaining_total)
            limited_items = await self.get_favorites(folder.media_id, max_items=current_limit)
            aggregated.append(
                FavoriteFolderWithItems(
                    folder=folder,
                    items=limited_items,
                    truncated=folder.media_count > len(limited_items),
                )
            )
            if remaining_total is not None:
                remaining_total -= len(limited_items)
        return aggregated

    async def get_following(
        self,
        *,
        page: int = 1,
        page_size: int = 50,
    ) -> list[FollowingUser]:
        """获取已登录用户的关注列表。"""
        nav = await self.get_nav_info()
        data = await self._get_json(
            "/x/relation/followings",
            params={"vmid": nav.mid, "pn": page, "ps": page_size},
        )
        users = _json_list(data.get("list", []))
        return [
            FollowingUser(
                mid=int(user.get("mid", 0)),
                uname=str(user.get("uname", "")),
                sign=str(user.get("sign", "")),
            )
            for user in users
        ]

    async def get_related_videos(self, bvid: str) -> list[dict[str, Any]]:
        """获取给定视频的相关/推荐视频。

        Args:
            bvid: 源视频 BV ID。

        Returns:
            相关视频字典列表。
        """
        resp = await self._client.get(
            f"{self._BASE_URL}/x/web-interface/archive/related",
            params={"bvid": bvid},
        )
        resp.raise_for_status()
        payload = _json_object(resp.json())
        return _json_list(payload.get("data", []))

    async def get_ranking(self, rid: int = 0) -> list[dict[str, Any]]:
        """获取排行榜/热门视频。

        Args:
            rid: 分区 ID（0 表示全部）。

        Returns:
            排行榜条目字典列表。
        """
        resp = await self._client.get(
            f"{self._BASE_URL}/x/web-interface/ranking/v2",
            params={"rid": rid, "type": "all"},
        )
        resp.raise_for_status()
        payload = _json_object(resp.json())
        data = _json_object(payload.get("data", {}))
        return _json_list(data.get("list", []))

    async def get_video_comments(self, bvid: str, limit: int = 20) -> list[CommentInfo]:
        """获取视频的热门评论。"""
        video = await self.get_video_info(bvid)
        data = await self._get_json(
            "/x/v2/reply/main",
            params={"oid": video.aid, "type": 1, "mode": 3, "ps": limit},
        )
        replies = _json_list(data.get("replies", []))
        comments = [
            CommentInfo(
                mid=int(reply.get("mid", 0)),
                uname=str(_json_object(reply.get("member", {})).get("uname", "")),
                message=str(_json_object(reply.get("content", {})).get("message", "")),
                like_count=int(reply.get("like", 0)),
            )
            for reply in replies
        ]
        return comments[:limit]

    async def close(self) -> None:
        """关闭 HTTP 客户端。"""
        await self._client.aclose()
