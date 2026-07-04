"""供 soul 流水线消费的统一跨源事件格式。

每个源适配器 —— Bilibili、小红书、通用 Web、未来平台 ——
都通过 ``build_event()`` 发出事件。返回的 dict 形状稳定，
使下游消费者（偏好分析器、感知分析器、画像构建器、记忆层）
看到一份统一契约，无论信号来自何处。

为何存在
--------

v0.3.22 之前，每个生产者都内联手写自己的事件 dict：
- B 站历史 → ``{event_type, title, url, metadata: {bvid, author}}``
- B 站收藏 → ``{event_type, title, metadata: {folder, upper}}``
- B 站关注 → ``{event_type, title, metadata: {up_name, sign}}``
- 小红书   → ``{event_type, title, url, context, metadata: {source_platform, ...}}``

存在三个问题：

1. 只有小红书填充了自然语言 ``context`` 字段。其他都作为原始 JSON
   blob 塞进 LLM 提示词，分析器在缺乏 schema 感知逻辑的情况下
   无法形成单一可读描述。
2. ``source_platform`` 仅出现在小红书事件中；
   ``compute_source_platform_mix`` 只能假设"缺失 = bilibili"，
   无法推广到未来源。
3. 作者 / 创作者命名散乱：``author`` / ``up_name`` / ``upper`` /
   ``author_name`` —— 每个消费者都要遍历一长串列表。

统一契约
--------

```python
{
    "event_type": str,         # "view" | "favorite" | "like" | "follow" | "dislike" | ...
    "title": str,
    "url": str,                 # 可选，可为空
    "context": str,             # 自然语言句子；LLM 的主要输入
    "metadata": {
        "source_platform": str,  # "bilibili" | "xiaohongshu" | "web" | ...
        "author": str,           # 规范的创作者/作者名；不适用时为空
        ...                      # 源特有附加字段（bvid / note_id / folder / ...）
    },
}
```

``context`` 字符串是 LLM 提示词的关键。它读起来像一句中文：
谁在哪个平台对哪条内容做了什么，可选地标注作者。过滤 / 加权
事件的代码应查看结构化字段（``event_type`` / ``metadata.source_platform``）；
LLM 消费 ``context``。
"""

from __future__ import annotations

import logging
from typing import Any, Literal

logger = logging.getLogger(__name__)

SatisfactionCategory = Literal["positive", "neutral", "negative", "unknown"]

# 点击事件满意度推断的停留阈值。
#
# - meaningful_dwell：至少 15 秒且至少为视频时长的 30%。
#   低于任一阈值时观看多半是探索性而非投入的。
# - quick_exit：5 秒以内。几乎总是被标题党诱骗后的关闭。
#
# 保守调校：目标是仅将我们高度确信反映真实兴趣的事件
# 输入偏好层，同时仍让真正短小的片段在用户观看了大部分时算数。
_MEANINGFUL_DWELL_MIN_SECONDS = 15
_MEANINGFUL_DWELL_MIN_RATIO = 0.3
_QUICK_EXIT_MAX_SECONDS = 5

# 显式互动事件类型（无需停留即可读出意图）。
_EXPLICIT_POSITIVE_EVENT_TYPES = frozenset({"like", "coin", "favorite", "comment"})

# 反馈元数据词汇表 —— 用于扩展 "thumbs_up / thumbs_down" UI
# 与推荐反馈端点发出的 `feedback` 事件。
_POSITIVE_FEEDBACK_TYPES = frozenset({"like"})
_NEUTRAL_FEEDBACK_TYPES = frozenset({"comment"})
_POSITIVE_REACTIONS = frozenset({"thumbs_up"})
_NEGATIVE_FEEDBACK_TYPES = frozenset({"dislike"})
_NEGATIVE_REACTIONS = frozenset({"thumbs_down"})

# 记录被动浏览的事件 —— 对上下文有用，但绝不是
# 直接的喜欢 / 不喜欢信号。
_PASSIVE_BROWSE_EVENT_TYPES = frozenset({"snapshot", "scroll", "hover", "search"})


def classify_event_satisfaction(event: dict[str, Any]) -> tuple[SatisfactionCategory, str]:
    """返回 ``(category, reason)``，描述用户在该事件中是否享受。

    纯函数、确定性、便于审计。永不抛出 —— 畸形 payload 返回
    ``("unknown", "fallback")``，使持久化路径总能存储*某物*，
    而不会因分类步骤崩溃请求。

    reason 字符串是简短的稳定标识符（snake_case），适合存储与
    可观测性看板使用；完整取值列表见设计文档。
    """
    try:
        event_type = str(event.get("event_type") or event.get("type") or "").strip()
        metadata_raw = event.get("metadata")
    except (TypeError, AttributeError):
        logger.debug("classify_event_satisfaction: malformed event payload", exc_info=True)
        return ("unknown", "fallback")

    # 非 None 且非 dict 的 metadata 违反契约（流水线其余部分假设
    # dict 形状的 metadata）。将其视为不可读，而非静默强制转换为 {}
    # 并发出 `missing_dwell`，那会暗示 payload 完整但缺少停留数据。
    if metadata_raw is None:
        metadata: dict[str, Any] = {}
    elif isinstance(metadata_raw, dict):
        metadata = metadata_raw
    else:
        logger.debug(
            "classify_event_satisfaction: metadata is %s (not dict); returning fallback",
            type(metadata_raw).__name__,
        )
        return ("unknown", "fallback")

    if event_type in _EXPLICIT_POSITIVE_EVENT_TYPES:
        return ("positive", "explicit_engagement")

    if event_type == "feedback":
        feedback_type = str(metadata.get("feedback_type") or "").strip().lower()
        reaction = str(metadata.get("reaction") or "").strip().lower()
        if feedback_type in _NEGATIVE_FEEDBACK_TYPES or reaction in _NEGATIVE_REACTIONS:
            return ("negative", "explicit_negative")
        if feedback_type in _POSITIVE_FEEDBACK_TYPES or reaction in _POSITIVE_REACTIONS:
            return ("positive", "explicit_engagement")
        if feedback_type in _NEUTRAL_FEEDBACK_TYPES:
            return ("neutral", "direct_feedback")
        return ("unknown", "fallback")

    if event_type == "click":
        return _classify_click_dwell(event, metadata)

    if event_type in _PASSIVE_BROWSE_EVENT_TYPES:
        return ("neutral", "passive_browse")

    return ("unknown", "fallback")


def _classify_click_dwell(
    event: dict[str, Any],
    metadata: dict[str, Any],
) -> tuple[SatisfactionCategory, str]:
    """点击事件的内部辅助 —— 单独抽出以使主规则表读起来更清晰。"""
    watch_seconds = _read_dwell_field(event, metadata, "watch_seconds")
    if watch_seconds is None:
        return ("unknown", "missing_dwell")

    if watch_seconds < _QUICK_EXIT_MAX_SECONDS:
        return ("negative", "quick_exit")

    duration = _read_dwell_field(event, metadata, "video_duration_seconds")
    if duration is None:
        # 遗留扩展事件使用 `duration` 键。
        duration = _read_dwell_field(event, metadata, "duration")

    meets_seconds = watch_seconds >= _MEANINGFUL_DWELL_MIN_SECONDS
    meets_ratio = (
        duration is not None
        and duration > 0
        and (watch_seconds / duration >= _MEANINGFUL_DWELL_MIN_RATIO)
    )

    if meets_seconds and (duration is None or meets_ratio):
        return ("positive", "meaningful_dwell")

    return ("neutral", "shallow_view")


def _read_dwell_field(
    event: dict[str, Any],
    metadata: dict[str, Any],
    key: str,
) -> float | None:
    """从顶层事件或其 metadata 读取数值字段。

    字段缺失或存储值无法转为 float（例如旧 payload 中的
    ``"unknown"`` 字符串）时返回 ``None``。
    """
    raw = event.get(key)
    if raw is None:
        raw = metadata.get(key)
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


# 源平台常量 —— 为分析器混合度计算保持稳定。
SOURCE_BILIBILI = "bilibili"
SOURCE_XIAOHONGSHU = "xiaohongshu"
SOURCE_DOUYIN = "douyin"
SOURCE_WEB = "web"
SOURCE_YOUTUBE = "youtube"
SOURCE_TWITTER = "twitter"
SOURCE_ZHIHU = "zhihu"

# 用于渲染 context 字符串的可读平台标签。
# 键必须与事件 metadata 中存储的 source_platform 值一致。
_PLATFORM_LABELS: dict[str, str] = {
    SOURCE_BILIBILI: "B 站",
    SOURCE_XIAOHONGSHU: "小红书",
    SOURCE_DOUYIN: "抖音",
    SOURCE_WEB: "网页",
    SOURCE_YOUTUBE: "YouTube",
    SOURCE_TWITTER: "X",
    SOURCE_ZHIHU: "知乎",
}

# 各 event_type 的动作动词。设计使渲染出的句子自然读作
# "在<platform>上<verb>了《<title>》" —— 中文无需冠词，
# 因此可保持简洁。
_EVENT_TYPE_LABELS: dict[str, str] = {
    "view": "看了",
    "favorite": "收藏了",
    "like": "点赞了",
    "follow": "关注了",
    "dislike": "标记不喜欢",
    "click": "点开了",
    "dialogue": "聊到",
    "feedback": "反馈过",
    "comment": "评论过",
    "share": "分享了",
}

_DEFAULT_SIGNAL_STRENGTH_BY_EVENT_TYPE: dict[str, float] = {
    "favorite": 1.0,
    "coin": 0.95,
    "share": 0.85,
    "like": 0.85,
    "comment": 0.75,
    "dialogue": 0.65,
    "follow": 0.6,
    "view": 0.35,
    "click": 0.3,
    "search": 0.25,
    "hover": 0.1,
    "scroll": 0.1,
    "snapshot": 0.1,
    "dislike": 1.0,
}


def default_signal_strength_for_event(
    event_type: str,
    metadata: dict[str, Any] | None = None,
) -> float | None:
    """返回事件的跨源兜底证据强度。

    平台适配器可传入更精确的 ``metadata.signal_strength``。
    此兜底仅填充缺失值；它描述证据强度，
    而非情感极性或最终兴趣权重。
    """
    normalized_event_type = event_type.strip().lower()
    metadata = metadata or {}

    if normalized_event_type == "feedback":
        feedback_type = str(metadata.get("feedback_type") or "").strip().lower()
        reaction = str(metadata.get("reaction") or "").strip().lower()
        if feedback_type == "dislike" or reaction == "thumbs_down":
            return 1.0
        if feedback_type == "like" or reaction == "thumbs_up":
            return 1.0
        if feedback_type == "comment":
            return 0.8
        if feedback_type == "dismiss":
            return 0.5
        return 0.5

    return _DEFAULT_SIGNAL_STRENGTH_BY_EVENT_TYPE.get(normalized_event_type)


def format_event_context(
    *,
    event_type: str,
    source_platform: str,
    title: str,
    author: str = "",
    extra: str = "",
) -> str:
    """渲染单句中文事件描述。

    Examples
    --------
    >>> format_event_context(
    ...     event_type="favorite",
    ...     source_platform="bilibili",
    ...     title="讲透历史叙事",
    ...     author="历史实验室",
    ... )
    '在 B 站收藏了《讲透历史叙事》,作者:历史实验室'

    >>> format_event_context(
    ...     event_type="like",
    ...     source_platform="xiaohongshu",
    ...     title="手冲咖啡入门",
    ...     author="豆子老师",
    ... )
    '在小红书点赞了《手冲咖啡入门》,作者:豆子老师'

    >>> format_event_context(
    ...     event_type="follow",
    ...     source_platform="bilibili",
    ...     title="历史实验室",
    ...     extra="签名:专注于讲透中国近代史",
    ... )
    '在 B 站关注了《历史实验室》(签名:专注于讲透中国近代史)'

    输出有意简短 —— LLM 提示词将许多这样的句子首尾拼接，
    冗长措辞会浪费上下文窗口。
    """
    platform_label = _PLATFORM_LABELS.get(source_platform, source_platform or "")
    action_label = _EVENT_TYPE_LABELS.get(event_type, "记录了")

    title = (title or "").strip()
    author = (author or "").strip()
    extra = (extra or "").strip()

    parts: list[str] = []
    if platform_label:
        parts.append(f"在{platform_label}")
    parts.append(action_label)
    parts.append(f"《{title}》" if title else "一条内容")
    if author:
        parts.append(f",作者:{author}")
    if extra:
        parts.append(f"({extra})")
    return "".join(parts).strip()


def build_event(
    *,
    event_type: str,
    source_platform: str,
    title: str = "",
    url: str = "",
    author: str = "",
    context: str = "",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """构造统一事件 dict。

    Parameters
    ----------
    event_type
        标准动作类型。识别集合见 ``_EVENT_TYPE_LABELS``；
        未知值在渲染 context 时退化为字面字符串。
    source_platform
        ``SOURCE_*`` 常量之一。被标记入 ``metadata``，
        以便分析器的源混合度代码可找到它。
    title
        内容标题（视频 / 笔记 / 页面名）。同时用于结构化字段
        与自然语言 context。
    url
        可选的标准 URL。存于顶层，使记忆层去重逻辑可跨事件
        匹配而无需深入 metadata。
    author
        规范的创作者名。存入 ``metadata.author``；
        生产者应在此传入，无论平台原生命名（``up_name`` /
        ``upper`` / ``nickname``）为何，以保持消费侧 schema 无关。
    context
        预格式化的自然语言句子。为空时由 ``format_event_context``
        基于结构化字段构建。拥有更丰富 context 的生产者
        （如小红书 scope、B 站收藏夹成员）可覆盖。
    metadata
        源特有附加字段。``source_platform`` 由参数自动填充；
        显式传入的 ``metadata.source_platform`` 优先。
        ``author`` 在未存在时也会同步。

    Returns
    -------
    dict
        已就绪供 ``MemoryManager.propagate_event``、
        ``SoulEngine.analyze_events`` 等使用的统一事件。
    """
    final_metadata: dict[str, Any] = dict(metadata) if metadata else {}
    final_metadata.setdefault("source_platform", source_platform)
    if author and "author" not in final_metadata:
        final_metadata["author"] = author
    if "signal_strength" not in final_metadata:
        signal_strength = default_signal_strength_for_event(event_type, final_metadata)
        if signal_strength is not None:
            final_metadata["signal_strength"] = signal_strength

    # 若调用方未显式传入 author，则复用 metadata 中的 author ——
    # 处理仅在 metadata 内设置 author 的生产者。
    effective_author = author or str(final_metadata.get("author", "") or "")

    if not context:
        context = format_event_context(
            event_type=event_type,
            source_platform=source_platform,
            title=title,
            author=effective_author,
        )

    event: dict[str, Any] = {
        "event_type": event_type,
        "title": title,
        "context": context,
        "metadata": final_metadata,
    }
    if url:
        event["url"] = url
    return event
