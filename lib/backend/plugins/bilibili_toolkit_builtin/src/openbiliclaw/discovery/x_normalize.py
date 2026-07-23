"""将 X (Twitter) tweet dict 归一化为 :class:`DiscoveredContent`。

**输入契约。** ``normalize_tweet`` 消费一个 dict,其形状由
``twitter_cli.serialization.tweet_to_dict`` 产出 — 即 ``twitter-cli`` 已经
解析并解包了原始 GraphQL 响应 (``TweetWithVisibilityResults`` /
``note_tweet`` 长文 / retweet-quote 嵌套)。我们不再这里重新实现
``prinsss/twitter-web-exporter`` 的 ``extractDataFromResponse``;该库
拥有那部分逻辑。我们只把普通 dict 映射到统一的 ``DiscoveredContent`` 形状
(见 ``docs/plans/2026-06-08-x-twitter-source-spec.md`` §5.2)。

``tweet_to_dict`` 产出的键 (镜像 ``x_client.py`` 的契约):

``id`` (rest_id)、``text`` (完整推文文本)、``author``
(``{id, name, screenName, profileImageUrl, verified}``)、``metrics``
(``{likes, retweets, replies, quotes, views, bookmarks}``)、
``createdAt`` / ``createdAtLocal`` / ``createdAtISO``、``media``
(``[{type, url, width, height}]``)、``urls``、``isRetweet``、``retweetedBy``、
``lang``、``score``,以及可选的 ``articleTitle`` / ``articleText``
(长文 note_tweet) / ``quotedTweet``。

本函数是 **纯函数且离线**: 它从不导入 ``twitter_cli``,也从不
触碰网络。对墓碑 / 不可用推文返回 ``None`` — 这些在
``tweet_to_dict`` 运行后会以缺失/空 ``id`` 的形式暴露。
"""

from __future__ import annotations

import re
from typing import Any

from openbiliclaw.discovery.engine import DiscoveredContent

# 卡片标题短一些更好;完整文本始终在 body_text 里。
_TITLE_MAX_LEN = 140

# 自线程头部常用的前导 thread 标记: "1/"、"1/7"、
# "1."、"(1/n)",或第一行任意位置出现 [THREAD] emoji。
_THREAD_MARKER_RE = re.compile(r"^\s*\(?\s*1\s*[/.)]")
_THREAD_EMOJI = "\U0001f9f5"  # [THREAD] emoji 用于文本匹配

# Hashtags: "#word" 含 unicode 字母/数字/下划线,不允许纯数字开头。
_HASHTAG_RE = re.compile(r"#(\w*[^\W\d_]\w*)", re.UNICODE)


def _as_str(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _first_media_url(media: Any) -> str:
    """返回第一个媒体缩略图 URL,纯文本推文返回 ""。"""
    if not isinstance(media, list):
        return ""
    for entry in media:
        if isinstance(entry, dict):
            url = _as_str(entry.get("url"))
            if url:
                return url
    return ""


def _extract_hashtags(text: str) -> list[str]:
    """从推文文本中提取 hashtags (去重、保序)。

    ``tweet_to_dict`` 不输出 ``entities``/``hashtags`` 块,所以我们
    从文本中恢复它们。返回不带前导 ``#`` 的 tag 内容。
    """
    seen: set[str] = set()
    tags: list[str] = []
    for match in _HASHTAG_RE.finditer(text or ""):
        tag = match.group(1)
        if tag and tag not in seen:
            seen.add(tag)
            tags.append(tag)
    return tags


def _first_line(text: str) -> str:
    for line in (text or "").splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return (text or "").strip()


def _truncate(text: str, limit: int = _TITLE_MAX_LEN) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"  # … 省略号


def _looks_like_thread(text: str) -> bool:
    first = _first_line(text)
    if _THREAD_MARKER_RE.match(first):
        return True
    return _THREAD_EMOJI in first


def normalize_tweet(
    raw: dict[str, Any],
    *,
    source_strategy: str = "",
) -> DiscoveredContent | None:
    """把一个 ``tweet_to_dict`` dict 映射到 :class:`DiscoveredContent`。

    对墓碑 / 不可用推文返回 ``None`` — 检测方式是缺失或空的
    ``id`` (``tweet_to_dict`` 解析原始响应后唯一可靠的信号)。
    """
    if not isinstance(raw, dict):
        return None

    tweet_id = _as_str(raw.get("id"))
    if not tweet_id:
        return None

    raw_author = raw.get("author")
    author: dict[str, Any] = raw_author if isinstance(raw_author, dict) else {}
    screen_name = _as_str(author.get("screenName"))
    handle = screen_name or "i"  # x.com/i/status/<id> 即使没有 handle 也能解析
    author_name = f"@{screen_name}" if screen_name else ""

    text = _as_str(raw.get("text"))
    article_text = _as_str(raw.get("articleText"))
    article_title = _as_str(raw.get("articleTitle"))

    # body_text: 长文 note_tweet 优先,否则用完整推文文本。
    body_text = article_text or text

    # title: note 自己的标题优先;否则用 (截断的) 第一行。
    title = _truncate(article_title) if article_title else _truncate(_first_line(text))

    # content_type: note_tweet 长文 OR 带 thread 标记的头部 → "thread"。
    is_thread = bool(article_text) or _looks_like_thread(text)
    content_type = "thread" if is_thread else "tweet"

    raw_metrics = raw.get("metrics")
    metrics: dict[str, Any] = raw_metrics if isinstance(raw_metrics, dict) else {}
    view_count = _as_int(metrics.get("views"))
    like_count = _as_int(metrics.get("likes"))
    reply_count = _as_int(metrics.get("replies"))
    retweet_count = _as_int(metrics.get("retweets"))
    quote_count = _as_int(metrics.get("quotes"))
    bookmark_count = _as_int(metrics.get("bookmarks"))

    cover_url = _first_media_url(raw.get("media"))
    tags = _extract_hashtags(text)

    return DiscoveredContent(
        title=title,
        content_id=tweet_id,
        content_url=f"https://x.com/{handle}/status/{tweet_id}",
        source_platform="twitter",
        source_strategy=source_strategy,
        author_name=author_name,
        body_text=body_text,
        content_type=content_type,
        cover_url=cover_url,
        view_count=view_count,
        like_count=like_count,
        favorite_count=bookmark_count,
        comment_count=reply_count,
        share_count=retweet_count + quote_count,
        reply_count=reply_count,
        retweet_count=retweet_count,
        bookmark_count=bookmark_count,
        tags=tags,
        description=body_text,
    )
