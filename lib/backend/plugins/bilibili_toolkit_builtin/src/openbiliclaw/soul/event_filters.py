"""inferred_satisfaction 信号的过滤辅助函数。

``openbiliclaw.sources.event_format`` 里的分类器在摄入时给每条
事件打标签。下游消费者（preference 分析器、awareness 分析器……）
调用 ``filter_events_by_satisfaction`` 把分类器标记为快速退出或
显式负向的行丢掉，再喂给 LLM。

别名规则：请求 ``"unknown"`` 也匹配 ``inferred_satisfaction``
缺失或为 ``None`` 的行。这让调用者可以选择未分类的旧事件
（迁移前的行），而无需手写 NULL 分支。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable


def filter_events_by_satisfaction(
    events: Iterable[dict[str, Any]],
    *,
    modes: frozenset[str],
) -> list[dict[str, Any]]:
    """只返回 ``inferred_satisfaction`` 在 ``modes`` 中的事件。

    顺序保留。空的 ``modes`` 集合返回 ``[]``（调用者显式什么
    都不要 —— 不要静默回退到「全部」）。

    ``inferred_satisfaction`` 为 ``None`` 或缺失的行被视作
    ``"unknown"``，这样当调用者用
    ``modes={"positive", "unknown"}`` 选中时，旧行能存活。
    """
    if not modes:
        return []
    keep: list[dict[str, Any]] = []
    for row in events:
        raw = row.get("inferred_satisfaction")
        category = raw if isinstance(raw, str) and raw else "unknown"
        if category in modes:
            keep.append(row)
    return keep
