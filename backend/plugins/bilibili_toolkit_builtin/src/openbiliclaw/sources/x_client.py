"""服务端 X (Twitter) 读取客户端 —— ``twitter-cli`` 的轻量异步封装。

X 内容源的发现是服务端 Cookie 回放（像 Bilibili / Douyin-direct，
而非 XHS 式的桩）。此客户端采集用户的 ``auth_token`` + ``ct0`` Cookie
并驱动 ``twitter_cli.client.TwitterClient`` 的**同步**读取方法。

设计契约（见 ``docs/plans/2026-06-08-x-twitter-source-plan.md`` Task 6）：

* **惰性导入。** ``twitter_cli``（及其 ``curl_cffi`` 传递依赖）在
  网络边界*内部*导入，从不在模块顶部。当 X 内容源被禁用时，导入此模块
  不得触碰该依赖或失败；``openbiliclaw[x]`` 仅作为向后兼容的安装别名保留。
  ``tests/test_x_client.py`` 对此进行回归测试。
* **异步封装。** ``twitter_cli`` 的读取是同步的（curl_cffi），因此公开的
  ``search`` / ``for_you`` / ``user_tweets``（发现）和 ``likes`` /
  ``bookmarks``（初始化偏好回填）协程通过 :func:`asyncio.to_thread` 运行它们。
* **返回形状。** 每个公开方法返回 ``list[dict]`` —— 即
  ``twitter_cli.serialization.tweet_to_dict`` 的输出。键为 camelCase/JSON 安全的：
  ``id``（即 rest_id）、``text``、``author``（``{id, name, screenName,
  profileImageUrl, verified}``）、``metrics``（``{likes, retweets, replies,
  quotes, views, bookmarks}``）、``createdAt`` / ``createdAtISO``、``media``、
  ``urls``、``isRetweet``、``retweetedBy``、``lang``、``score``，以及可选的
  ``articleTitle`` / ``articleText``（长文 note_tweet）/ ``quotedTweet``。
  Task 7 的 ``normalize_tweet`` 消费这些字典。
* **类型化错误。** 底层的 ``TwitterAPIError`` / ``AuthenticationError``
  映射到一个小型层次结构，以便 Task 10 的源健康状态机能干净地分支处理：
  缺少 Cookie → :class:`XMissingCookieError`（``missing_cookie``）；401 →
  :class:`XAuthError`（``expired_cookie``）；403 → :class:`XBlockedError`
  （``blocked``）；429 → :class:`XRateLimitError`（``rate_limited``）。
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - 仅用于类型标注，运行时从不导入
    from twitter_cli.models import Tweet


class XClientError(RuntimeError):
    """所有 X 客户端失败的基类。"""


class XMissingCookieError(XClientError):
    """没有可用的 Cookie（``auth_token`` 和/或 ``ct0`` 缺失）。

    在首次使用时惰性抛出 —— 在任何 ``twitter_cli`` 导入之前 —— 这样
    禁用/未配置的路径永远不会触碰 X 依赖。
    """


class XAuthError(XClientError):
    """认证失败（HTTP 401 / ``AuthenticationError``）—— Cookie 已过期。"""


class XBlockedError(XClientError):
    """请求被拒绝（HTTP 403）—— 账号/地区/端点被禁。"""


class XRateLimitError(XClientError):
    """被限流（HTTP 429）—— 稍后重试。"""


def _parse_cookie(cookie: str) -> tuple[str, str]:
    """从 Cookie 头字符串中提取 ``auth_token`` 和 ``ct0``。

    接受常见的 ``"auth_token=...; ct0=...; other=..."`` 形式。
    如果任一值缺失或为空，抛出 :class:`XMissingCookieError`。
    """
    pairs: dict[str, str] = {}
    for chunk in (cookie or "").split(";"):
        name, sep, value = chunk.partition("=")
        if not sep:
            continue
        pairs[name.strip()] = value.strip()
    auth_token = pairs.get("auth_token", "")
    ct0 = pairs.get("ct0", "")
    if not auth_token or not ct0:
        missing = [k for k, v in (("auth_token", auth_token), ("ct0", ct0)) if not v]
        raise XMissingCookieError(f"x cookie missing required field(s): {', '.join(missing)}")
    return auth_token, ct0


class XClient:
    """``twitter_cli.client.TwitterClient`` 读取方法的异步封装。

    Cookie 是惰性解析的（在首次调用时），因此构造 ``XClient`` 很廉价，
    且从不导入 ``twitter_cli``。
    """

    def __init__(self, cookie: str) -> None:
        self._cookie = cookie or ""

    # -- 内部辅助方法 ---------------------------------------------------

    def _auth_pair(self) -> tuple[str, str]:
        """惰性解析并返回 Cookie 中的 ``(auth_token, ct0)``。"""
        return _parse_cookie(self._cookie)

    def _client(self) -> Any:
        """构建一个 ``twitter_cli`` 客户端（惰性导入在此进行）。"""
        from twitter_cli.client import TwitterClient

        auth_token, ct0 = self._auth_pair()
        return TwitterClient(auth_token, ct0)

    # -- 网络边界（同步；测试中被 monkeypatch）-------------------------
    #
    # 这些是 ``twitter_cli`` 被驱动的唯一位置。测试会替换它们，
    # 这样就不需要真实网络调用（也不需要真实 Cookie）。

    def _raw_search(self, query: str, *, count: int, product: str) -> list[Tweet]:
        return list(self._client().fetch_search(query, count=count, product=product))

    def _raw_for_you(self, *, count: int) -> list[Tweet]:
        # home_timeline 是 "For You" 信息流；fetch_following_feed 是按时间顺序的。
        return list(self._client().fetch_home_timeline(count=count))

    def _raw_user_tweets(self, handle: str, *, count: int) -> list[Tweet]:
        client = self._client()
        user_id = client.resolve_user_id(handle)
        return list(client.fetch_user_tweets(user_id, count=count))

    def _raw_likes(self, *, count: int) -> list[Tweet]:
        # 当前认证用户自己的点赞时间线。fetch_user_likes 需要 user_id，
        # 所以先解析 "me"（仅初始化时多一次读取）。
        client = self._client()
        me = client.fetch_me()
        user_id = str(getattr(me, "id", "") or "")
        if not user_id:
            raise XClientError("could not resolve authenticated user id for likes")
        return list(client.fetch_user_likes(user_id, count=count))

    def _raw_bookmarks(self, *, count: int) -> list[Tweet]:
        return list(self._client().fetch_bookmarks(count=count))

    # -- 公开异步 API ---------------------------------------------------

    async def search(self, query: str, *, limit: int, product: str = "Top") -> list[dict[str, Any]]:
        """搜索 X。返回最多 ``limit`` 个 ``tweet_to_dict`` 字典。"""
        tweets = await self._run(self._raw_search, query, count=limit, product=product)
        return self._serialize(tweets, limit)

    async def for_you(self, *, limit: int) -> list[dict[str, Any]]:
        """获取 "For You" 主页时间线。返回 ``tweet_to_dict`` 字典。"""
        tweets = await self._run(self._raw_for_you, count=limit)
        return self._serialize(tweets, limit)

    async def user_tweets(self, handle: str, *, limit: int) -> list[dict[str, Any]]:
        """按 handle 获取创作者最近的推文。返回 ``tweet_to_dict`` 字典。"""
        tweets = await self._run(self._raw_user_tweets, handle, count=limit)
        return self._serialize(tweets, limit)

    async def likes(self, *, limit: int) -> list[dict[str, Any]]:
        """获取当前认证用户自己点赞的推文（初始化偏好回填）。

        与 ``search`` / ``for_you``（发现）不同，此方法读取用户*自己的*
        历史互动数据来播种 Soul 画像 —— 是 B 站收藏回填的 X 对应物。
        返回 ``tweet_to_dict`` 字典。
        """
        tweets = await self._run(self._raw_likes, count=limit)
        return self._serialize(tweets, limit)

    async def bookmarks(self, *, limit: int) -> list[dict[str, Any]]:
        """获取当前认证用户自己收藏的推文（初始化偏好回填）。

        返回 ``tweet_to_dict`` 字典。
        """
        tweets = await self._run(self._raw_bookmarks, count=limit)
        return self._serialize(tweets, limit)

    # -- 管道 -----------------------------------------------------------

    async def _run(self, fn: Any, *args: Any, **kwargs: Any) -> list[Tweet]:
        """在离线线程中运行同步边界方法，将 twitter_cli 错误映射到我们的错误。

        ``XMissingCookieError`` 原样传播（在任何导入之前抛出）。
        """
        try:
            return await asyncio.to_thread(fn, *args, **kwargs)
        except XClientError:
            raise
        except Exception as exc:  # noqa: BLE001 - 规范化 twitter_cli 表面
            raise _map_exception(exc) from exc

    @staticmethod
    def _serialize(tweets: list[Tweet], limit: int) -> list[dict[str, Any]]:
        from twitter_cli.serialization import tweet_to_dict

        capped = tweets[:limit] if limit and limit > 0 else tweets
        return [tweet_to_dict(t) for t in capped]


def _map_exception(exc: Exception) -> XClientError:
    """将 ``twitter_cli`` 异常转换为本地类型化层次结构。"""
    # 惰性导入，这样非 X 安装仍能导入此模块来映射空（except 路径仅在
    # twitter_cli 已介入时才运行）。
    from twitter_cli.client import TwitterAPIError
    from twitter_cli.exceptions import AuthenticationError

    if isinstance(exc, TwitterAPIError):
        status = getattr(exc, "status_code", None)
        if status == 401:
            return XAuthError(str(exc))
        if status == 403:
            return XBlockedError(str(exc))
        if status == 429:
            return XRateLimitError(str(exc))
        return XClientError(str(exc))
    if isinstance(exc, AuthenticationError):
        # AuthenticationError 没有 status_code；视为过期/无效的 Cookie。
        return XAuthError(str(exc))
    return XClientError(str(exc))
