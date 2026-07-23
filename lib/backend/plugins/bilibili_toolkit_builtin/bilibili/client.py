"""B 站异步 API 客户端。

封装 httpx.AsyncClient + WBI 签名 + Cookie 注入 + User-Agent 注入 +
并发限流 + 风控检测，作为 ``bilibili/`` 模块内所有具体 API 调用
（playurl / video_info / subtitle / danmaku 等）的统一基础层。

参考实现：``bili-sync/crates/bili_sync/src/bilibili/client.rs`` 的
``BiliClient`` 与 vendored ``openbiliclaw/bilibili/api.py`` 的
``BilibiliAPIClient``。本实现与 vendored 的差异：
- 使用结构化 :class:`Credential` 而非裸 cookie 字符串
- 单独抽离 :mod:`risk_control` 与 :mod:`wbi` 模块，便于测试与复用
- 引入 ``asyncio.Semaphore`` 限流而非 ``min_request_interval`` 节流
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
from loguru import logger

from .credential import Credential
from .risk_control import RiskControlError, check_response
from .wbi import BilibiliAPIError, get_wbi_keys, sign_wbi

# 默认 User-Agent，与 vendored openbiliclaw 保持一致
DEFAULT_USER_AGENT: str = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# B 站 API 基础 URL
BILIBILI_API_BASE: str = "https://api.bilibili.com"

# WBI 密钥缓存时长（秒），与 vendored openbiliclaw 一致
WBI_KEY_TTL_SECONDS: float = 300.0


class BilibiliClient:
    """B 站异步 API 客户端。

    内部持有 ``httpx.AsyncClient``（base_url 固定为 ``https://api.bilibili.com``）、
    ``asyncio.Semaphore``（控制最大并发请求数）与缓存的 WBI 密钥
    （首次获取后 5 分钟内复用，避免每次请求都打 nav 端点）。

    所有具体 API 调用（如 ``get_playurl``）应通过 ``request`` 方法发起请求，
    以统一处理 Cookie/UA 注入、WBI 签名、风控检测。
    """

    def __init__(
        self,
        credential: Credential,
        user_agent: str = "",
        timeout: float = 15.0,
        max_concurrent: int = 5,
    ) -> None:
        """初始化 BilibiliClient。

        Args:
            credential: 登录凭据，包含 SESSDATA / bili_jct 等字段。
            user_agent: 自定义 User-Agent，留空使用 :data:`DEFAULT_USER_AGENT`。
            timeout: 单次请求超时（秒）。
            max_concurrent: 对 B 站 API 的最大并发请求数，超过则排队等待。
        """
        self.credential: Credential = credential
        self.user_agent: str = user_agent or DEFAULT_USER_AGENT
        self.timeout: float = float(timeout)
        self.max_concurrent: int = max(1, int(max_concurrent))
        self._semaphore: asyncio.Semaphore = asyncio.Semaphore(self.max_concurrent)
        # WBI 密钥缓存：(img_key, sub_key) 元组；None 表示未获取
        self._cached_wbi_keys: tuple[str, str] | None = None
        self._wbi_keys_fetched_at: float = 0.0
        # httpx.AsyncClient，初始化时注入 Cookie 与 UA
        self._http_client: httpx.AsyncClient = httpx.AsyncClient(
            base_url=BILIBILI_API_BASE,
            timeout=self.timeout,
            headers={
                "User-Agent": self.user_agent,
                "Referer": "https://www.bilibili.com",
                "Origin": "https://www.bilibili.com",
            },
            cookies=credential.to_cookie_dict() if credential.is_valid() else None,
        )

    async def request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        need_wbi: bool = False,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """发起对 B 站 API 的请求并返回 JSON。

        Args:
            method: HTTP 方法（``GET`` / ``POST``）。
            path: 接口路径，形如 ``/x/player/wbi/playurl``。
                由于 httpx base_url 已设置，path 不带域名即可。
            params: 查询参数（GET）或表单参数（POST）。
            need_wbi: 是否对参数进行 WBI 签名。WBI 签名要求 params 非 None。
            headers: 额外的请求头，会与默认 UA/Referer 合并。

        Returns:
            响应 JSON 的 ``dict`` 形式。

        Raises:
            BilibiliAPIError: HTTP 异常或响应非 JSON 时抛出。
            RiskControlError: 检测到风控信号（412/403/-352/v_voucher）时抛出。
        """
        # 构造最终请求参数
        request_params: dict[str, Any] = dict(params or {})
        if need_wbi:
            img_key, sub_key = await self.get_wbi_keys()
            # sign_wbi 返回 dict[str, str]，所有值转 str
            request_params = sign_wbi(request_params, img_key, sub_key)

        # 合并请求头
        request_headers: dict[str, str] = {}
        if headers:
            request_headers.update(headers)

        # 并发限流
        async with self._semaphore:
            try:
                response = await self._http_client.request(
                    method=method.upper(),
                    url=path,
                    params=request_params or None,
                    headers=request_headers or None,
                )
            except httpx.HTTPError as exc:
                raise BilibiliAPIError(f"HTTP 请求失败: {exc}") from exc

        # 风控检测（先于业务码校验，412/403 会直接抛 RiskControlError）
        check_response(response)

        # 解析 JSON
        try:
            payload = response.json()
        except Exception as exc:
            raise BilibiliAPIError(
                f"响应非 JSON: status={response.status_code}, body={response.text[:200]}"
            ) from exc

        if not isinstance(payload, dict):
            raise BilibiliAPIError(
                f"响应 JSON 不是对象: status={response.status_code}, type={type(payload).__name__}"
            )

        # 业务码校验（code != 0 视为业务错误）
        code = payload.get("code", 0)
        if isinstance(code, (int, float)) and code != 0:
            message = str(payload.get("message", "Bilibili API request failed"))
            # -101 表示登录态失效，单独记录日志便于排查
            if code == -101:
                logger.warning(
                    "B 站登录态失效: path={}, message={}",
                    path,
                    message,
                )
            raise BilibiliAPIError(message, code=int(code))

        return payload

    async def get_wbi_keys(self) -> tuple[str, str]:
        """获取并缓存 WBI img_key 与 sub_key。

        缓存时长 :data:`WBI_KEY_TTL_SECONDS`（默认 300 秒），
        过期后下次调用会重新请求 ``/x/web-interface/nav`` 刷新。

        Returns:
            ``(img_key, sub_key)`` 元组。

        Raises:
            BilibiliAPIError: nav 端点返回异常或 wbi_img 缺失时抛出。
            RiskControlError: nav 端点触发风控时抛出。
        """
        # 检查缓存是否有效（用 monotonic 时间避免时钟跳变影响）
        loop_time = asyncio.get_event_loop().time()
        if (
            self._cached_wbi_keys is not None
            and (loop_time - self._wbi_keys_fetched_at) < WBI_KEY_TTL_SECONDS
        ):
            return self._cached_wbi_keys

        # 通过 vendored openbiliclaw 风格的 get_wbi_keys 模块函数获取
        # 该函数内部会调用 check_response 检测风控
        try:
            img_key, sub_key = await get_wbi_keys(self._http_client)
        except RiskControlError:
            # 风控异常直接上抛，由 workflow 层处理
            raise
        except Exception as exc:
            raise BilibiliAPIError(f"获取 WBI 密钥失败: {exc}") from exc

        self._cached_wbi_keys = (img_key, sub_key)
        self._wbi_keys_fetched_at = loop_time
        logger.debug("WBI 密钥已刷新: img_key={}, sub_key={}", img_key, sub_key)
        return self._cached_wbi_keys

    async def close(self) -> None:
        """关闭 HTTP 客户端，释放连接池资源。

        调用后该实例不可再用。重复调用安全（幂等）。
        """
        await self._http_client.aclose()
        self._cached_wbi_keys = None

    async def __aenter__(self) -> "BilibiliClient":
        """支持 ``async with`` 上下文管理。"""
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        """退出上下文时自动关闭客户端。"""
        await self.close()
