"""近期快速退出 / 负向标题的近度加权列表。

v0.3.x ``inferred_satisfaction`` 信号的下游消费者。被
``discovery/engine.py`` 的 eval-batch 调用点用于把 LLM 评估器
锚定到用户实际不喜欢的具体示例上，这样类似标题党或课程推销
话术的候选项会被降权，而无需依赖手工维护的正则黑名单。

纯函数、确定性、无 LLM 调用。存储失败被吞掉 —— 当负向存储
为空或不可用时，eval-batch 仍必须能跑。
"""

from __future__ import annotations

import logging
import math
import re
from datetime import datetime
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from collections.abc import Iterable  # noqa: F401  # documentation

logger = logging.getLogger(__name__)

MAX_LIMIT = 16
DEFAULT_HALF_LIFE_DAYS = 14
TITLE_MAX_CHARS = 80

# 在近度加权 / 去重之前从事件存储拉取的候选行数。比 ``limit``
# 大，让评分器有素材可以丢弃。
_FETCH_LIMIT = 200

# 用于去重的归一化前缀长度。20 字符足以捕获同一钩子的标题党
# 变体，又不会把真正不同的标题折叠到一起。
_DEDUPE_PREFIX_CHARS = 20

# 计算去重键前从标题里剥离的字符。哈希 / emoji / 常见标点噪音
# 被移除；字母数字和 CJK 字符原样保留。
_DEDUPE_STRIP_PATTERN = re.compile(r"[\s#​]+|[!！?？.。,，~～\-—•·]+")


class EventStore(Protocol):
    def query_events(
        self,
        *,
        satisfaction_modes: frozenset[str] | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]: ...


def recent_negative_exemplars(
    event_store: EventStore,
    *,
    limit: int = MAX_LIMIT,
    half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """返回最多 ``limit`` 条近度加权的近期负向示例。

    每条记录携带 ``{"title": str, "reason": str, "age_days": int}``。
    存储异常被吞掉并返回空列表 —— 消费者（eval-batch）必须
    始终能跑。
    """
    capped_limit = min(int(limit), MAX_LIMIT)
    if capped_limit <= 0:
        return []
    now_ts = now or datetime.now()

    try:
        rows = event_store.query_events(
            satisfaction_modes=frozenset({"negative"}),
            limit=_FETCH_LIMIT,
        )
    except Exception:
        logger.debug("recent_negative_exemplars: query_events failed", exc_info=True)
        return []

    scored: list[tuple[float, dict[str, Any]]] = []
    for row in rows:
        title = str(row.get("title") or "").strip()
        if not title:
            continue
        age_days = _event_age_days(row, now_ts)
        weight = math.exp(-age_days / half_life_days) if half_life_days > 0 else 0.0
        scored.append(
            (
                weight,
                {
                    "title": _truncate_title(title),
                    "reason": str(row.get("satisfaction_reason") or "negative"),
                    "age_days": int(round(age_days)),
                    # 携带原始权重 + 原始标题用于去重决策；
                    # 两者都在下面返回的记录里被剥离。
                    "_raw_title": title,
                    "_weight": weight,
                },
            )
        )

    # 按权重降序排序（更新的胜出）；稳定排序让平局优先选择
    # 事件存储里的第一行（已按 created_at DESC 排序）。
    scored.sort(key=lambda pair: pair[0], reverse=True)

    deduped: list[dict[str, Any]] = []
    seen_prefixes: set[str] = set()
    for _weight, record in scored:
        prefix = _normalize_prefix(record["_raw_title"])
        if prefix in seen_prefixes:
            continue
        seen_prefixes.add(prefix)
        deduped.append(record)
        if len(deduped) >= capped_limit:
            break

    return [
        {
            "title": record["title"],
            "reason": record["reason"],
            "age_days": record["age_days"],
        }
        for record in deduped
    ]


def _event_age_days(row: dict[str, Any], now: datetime) -> float:
    """从行的 ``created_at`` 或回退字段计算以天为单位的年龄。"""
    raw = row.get("created_at") or row.get("timestamp")
    if isinstance(raw, str) and raw:
        try:
            created = datetime.fromisoformat(raw.replace(" ", "T"))
        except ValueError:
            return 0.0
    elif isinstance(raw, datetime):
        created = raw
    else:
        return 0.0
    delta = now - created
    return max(0.0, delta.total_seconds() / 86400.0)


def _truncate_title(title: str) -> str:
    if len(title) <= TITLE_MAX_CHARS:
        return title
    return title[: TITLE_MAX_CHARS - 1] + "…"


def _normalize_prefix(title: str) -> str:
    """计算去重键。剥离空白、井号、标点。"""
    lowered = title.lower()
    stripped = _DEDUPE_STRIP_PATTERN.sub("", lowered)
    return stripped[:_DEDUPE_PREFIX_CHARS]
