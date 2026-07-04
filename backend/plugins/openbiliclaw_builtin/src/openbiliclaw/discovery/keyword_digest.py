"""keyword-shaping profile 字段的稳定量化摘要 (P1.2)。

``profile_kw_digest`` 决定统一关键词缓存何时失效
(见 ``docs/plans/2026-06-14-discover-backpressure-refactor-design.md`` §8)。它是
**与路径无关的** — 它对 *当前* profile 计算哈希,不关心是哪条路径
(chat / feedback event / 12h consolidation) 修改了它 — 并且刻意如此设计:

- **覆盖**真正影响搜索关键词的慢变字段
  (interests、dislikes、traits、values、drivers、phase、cognitive style、style);
- **量化** interest / style 权重到粗糙的桶中,使单次事件的
  权重漂移不会让缓存反复失效;
- **排除**高变动 / 低关键词影响的状态 (``recent_awareness``、
  ``active_insights``) 和按 tag 的时间戳 (``first_seen`` / ``last_seen``),
  这些会随用户浏览不断变化但几乎不影响搜索词。

digest 不是新鲜度机制 (生成阶段始终读取 live profile)。它只在
profile 发生实质性变化时主动 flush 陈旧的 ``pending`` 关键词 —
完整理由见 spec。
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from openbiliclaw.soul.profile import SoulProfile

# 粗糙的桶,使单次 feedback 事件把权重挪动 <0.1 时折叠到
# 同一个 digest。0.1 步长 == discovery 已经在截断 interests 时使用的
# 同一粒度。
_WEIGHT_BUCKET = 0.1
# 限制参与 digest 的 interests 数量: 最强的 interests 主导
# 关键词生成,因此低于此上限的长尾变动不应翻转 digest。
# 上限足够宽松,可以捕获有意义的头部。
_TOP_INTERESTS = 64


def _bucket(weight: object) -> float:
    try:
        value = float(weight)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    return round(round(value / _WEIGHT_BUCKET) * _WEIGHT_BUCKET, 1)


def _clean_sorted(values: object) -> list[str]:
    if not isinstance(values, (list, tuple, set, frozenset)):
        return []
    return sorted({str(v).strip() for v in values if str(v).strip()})


def profile_kw_digest(profile: SoulProfile) -> str:
    """返回 keyword-shaping profile 字段的短小稳定 hex digest。"""
    prefs = profile.preferences
    ranked = sorted(prefs.interests, key=lambda tag: float(tag.weight or 0.0), reverse=True)
    interests = sorted(
        (str(tag.name).strip(), str(tag.category or "").strip(), _bucket(tag.weight))
        for tag in ranked[:_TOP_INTERESTS]
        if str(tag.name).strip()
    )
    style = prefs.style
    payload: dict[str, object] = {
        "interests": interests,
        "disliked_topics": _clean_sorted(prefs.disliked_topics),
        "core_traits": _clean_sorted(profile.core_traits),
        "values": _clean_sorted(profile.values),
        "motivational_drivers": _clean_sorted(profile.motivational_drivers),
        "cognitive_style": _clean_sorted(profile.cognitive_style),
        "current_phase": str(profile.current_phase or "").strip(),
        "life_stage": str(profile.life_stage or "").strip(),
        "style": {
            "preferred_duration": str(style.preferred_duration or "").strip(),
            "preferred_pace": str(style.preferred_pace or "").strip(),
            "depth": _bucket(style.depth_preference),
            "humor": _bucket(style.humor_preference),
        },
    }
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]
