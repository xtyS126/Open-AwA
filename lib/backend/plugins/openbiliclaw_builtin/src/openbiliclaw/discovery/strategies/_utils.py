"""发现策略的共享工具和协议。"""

from __future__ import annotations

import asyncio
import math
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, TypeVar, cast, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from openbiliclaw.discovery.engine import DiscoveredContent
    from openbiliclaw.soul.profile import InterestDomain, OnionProfile, SoulProfile

_T = TypeVar("_T")

# Profile-summary 截断上限。列表在截断前按 weight 排序,
# 使最强的 interest 保留下来,而非恰好列在前面的那些。
_INTEREST_DOMAIN_CAP = 128
_SPECIFICS_PER_DOMAIN = 30
_INTEREST_TAG_CAP = 256
# 与 _DISLIKED_TOPICS_STORE_CAP 保持一致,使 avoid-topics 永远
# 不被从 prompt 中切掉: store 早于 recency-ordered union (v0.3.121),
# 所以遗留条目按字母顺序排列,任何低于 store cap 的切掉都会按 codepoint
# 而非按 relevance 丢掉 topics。
_DISLIKED_TOPICS_CAP = 128
_QUERY_PROFILE_LIST_CAP = 8
_QUERY_INTEREST_DOMAIN_CAP = 16
_QUERY_SPECIFICS_PER_DOMAIN = 8
_QUERY_INTEREST_TAG_CAP = 64
_QUERY_INTEREST_CANDIDATE_POOL_CAP = 128
_QUERY_DISLIKED_TOPICS_CAP = 64
_QUERY_DISLIKED_TOPIC_CANDIDATE_POOL_CAP = 128
_QUERY_SPECULATIVE_INTEREST_CAP = 8


@dataclass(frozen=True)
class _QueryInterestCandidate:
    output: dict[str, object]
    text: str
    category: str
    weight: float
    priority: float
    vector: list[float]


@dataclass(frozen=True)
class _QueryTextCandidate:
    text: str
    priority: float
    vector: list[float]


@runtime_checkable
class SupportsIsoformat(Protocol):
    def isoformat(self) -> str: ...


async def _gather_bounded(
    awaitables: list[Awaitable[_T]],
    *,
    runner: Callable[[Awaitable[_T]], Awaitable[_T]] | None = None,
) -> list[object]:
    """收集 awaitable,可选地通过有界 runner 路由它们。"""
    if runner is None:
        return cast(
            "list[object]",
            await asyncio.gather(*awaitables, return_exceptions=True),
        )
    return cast(
        "list[object]",
        await asyncio.gather(
            *(runner(awaitable) for awaitable in awaitables),
            return_exceptions=True,
        ),
    )


# ---------------------------------------------------------------------------
# Protocol classes
# ---------------------------------------------------------------------------


class SupportsSearchClient(Protocol):
    async def search(
        self,
        keyword: str,
        page: int = 1,
        page_size: int = 20,
        order: str = "totalrank",
    ) -> list[dict[str, object]]: ...


def search_cooldown_remaining(client: object) -> float:
    """当 client 暴露该方法时,返回 process/client 的 search cooldown 秒数。"""
    remaining = getattr(client, "search_cooldown_remaining", None)
    if not callable(remaining):
        return 0.0
    try:
        return max(0.0, float(remaining()))
    except Exception:
        return 0.0


class SupportsRankingClient(Protocol):
    async def get_ranking(self, rid: int = 0) -> list[dict[str, object]]: ...


class SupportsMemoryManager(Protocol):
    def query_events(
        self,
        *,
        event_types: list[str] | None = None,
        start_time: object | None = None,
        end_time: object | None = None,
        keyword: str = "",
        limit: int = 100,
    ) -> list[dict[str, object]]: ...


class SupportsSeedStrategy(Protocol):
    async def discover(self, profile: SoulProfile, limit: int = 20) -> list[DiscoveredContent]: ...


class SupportsRelatedClient(Protocol):
    async def get_related_videos(self, bvid: str) -> list[dict[str, object]]: ...

    async def search(
        self,
        keyword: str,
        page: int = 1,
        page_size: int = 20,
        order: str = "totalrank",
    ) -> list[dict[str, object]]: ...


# ---------------------------------------------------------------------------
# 共享辅助函数 (从 SearchStrategy 静态方法中提取)
# ---------------------------------------------------------------------------


def clean_text(value: str) -> str:
    """从 *value* 中去除 HTML 标签。"""
    return re.sub(r"<[^>]+>", "", value).strip()


def to_int(raw_value: object) -> int:
    """将 *raw_value* 尽力转换为 ``int``。"""
    if isinstance(raw_value, bool):
        return int(raw_value)
    if isinstance(raw_value, int):
        return raw_value
    if isinstance(raw_value, float):
        return int(raw_value)
    if isinstance(raw_value, str):
        digits = raw_value.replace(",", "").strip()
        if digits.isdigit():
            return int(digits)
    return 0


def parse_duration(raw_value: object) -> int:
    """解析时长值 (int 秒数或 ``HH:MM:SS`` / ``MM:SS`` 字符串)。"""
    if isinstance(raw_value, int):
        return raw_value
    if isinstance(raw_value, str) and ":" in raw_value:
        parts = [part for part in raw_value.split(":") if part.isdigit()]
        if len(parts) == 2:
            minutes, seconds = parts
            return int(minutes) * 60 + int(seconds)
        if len(parts) == 3:
            hours, minutes, seconds = parts
            return int(hours) * 3600 + int(minutes) * 60 + int(seconds)
    return to_int(raw_value)


def normalize_match_text(value: str) -> str:
    """折叠空白并小写化,用于模糊匹配。"""
    return re.sub(r"\s+", "", value).strip().lower()


def _format_profile_timestamp(value: object) -> str:
    """为 JSON prompt summary 序列化 profile 类时间戳值。"""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, SupportsIsoformat):
        return value.isoformat()
    return str(value)


def _coerce_profile_float(value: object, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return default
    return default


def _coerce_profile_str_list(value: object, limit: int = 5) -> list[str]:
    if not isinstance(value, list):
        return []
    values: list[str] = []
    for item in value[:limit]:
        text = str(item).strip()
        if text:
            values.append(text)
    return values


def _likes_by_weight(profile: OnionProfile) -> list[InterestDomain]:
    """按 weight 降序排列的 interest domain,空值已丢弃。"""
    return sorted(
        (dom for dom in profile.interest.likes if dom.domain.strip()),
        key=lambda dom: dom.weight,
        reverse=True,
    )


def _entry_weight(entry: dict[str, object]) -> float:
    weight = entry.get("weight")
    return float(weight) if isinstance(weight, (int, float)) else 0.0


def _extract_interest_domains(profile: SoulProfile) -> list[dict[str, object]]:
    """从 profile 提取 domain 级别 (一级) 的 interest 层次结构。

    返回类似如下的列表:
    [{"domain": "AI/ML", "weight": 0.9, "specifics": ["强化学习", "ppo算法"]}, ...]

    这让 LLM prompt 既能看到宽泛的 domain 也能看到具体的子 interest,
    使 query 能在不同粒度上生成。
    """
    from openbiliclaw.soul.profile import OnionProfile

    # OnionProfile 直接具有树结构
    if isinstance(profile, OnionProfile):
        return [
            {
                "domain": dom.domain,
                "weight": dom.weight,
                "specifics": [s.name for s in dom.specifics[:_SPECIFICS_PER_DOMAIN]],
                "first_seen": _format_profile_timestamp(dom.first_seen),
                "last_seen": _format_profile_timestamp(dom.last_seen),
                "source": dom.source,
            }
            for dom in _likes_by_weight(profile)[:_INTEREST_DOMAIN_CAP]
        ]

    # 平坦的 SoulProfile: 从 category 分组重建 domain
    ranked_tags = sorted(profile.preferences.interests, key=lambda tag: tag.weight, reverse=True)
    domain_map: dict[str, dict[str, object]] = {}
    for tag in ranked_tags[:_INTEREST_TAG_CAP]:
        key = tag.category or tag.name
        if key not in domain_map:
            domain_map[key] = {
                "domain": key,
                "weight": tag.weight,
                "specifics": [],
                "first_seen": _format_profile_timestamp(tag.first_seen),
                "last_seen": _format_profile_timestamp(tag.last_seen),
                "source": tag.source,
            }
        existing = domain_map[key]
        if tag.name != key:
            specs = existing["specifics"]
            if isinstance(specs, list) and len(specs) < _SPECIFICS_PER_DOMAIN:
                specs.append(tag.name)
        existing_weight = existing.get("weight", 0)
        if tag.weight > (
            float(existing_weight) if isinstance(existing_weight, (int, float)) else 0
        ):
            existing["weight"] = tag.weight
            existing["source"] = tag.source
        if not existing.get("first_seen"):
            existing["first_seen"] = _format_profile_timestamp(tag.first_seen)
        existing["last_seen"] = _format_profile_timestamp(tag.last_seen) or existing.get(
            "last_seen", ""
        )
    return sorted(domain_map.values(), key=_entry_weight, reverse=True)[:_INTEREST_DOMAIN_CAP]


def _extract_interest_tags(profile: SoulProfile) -> list[dict[str, object]]:
    """提取带 provenance 元数据的平坦 interest tag。"""
    from openbiliclaw.soul.profile import OnionProfile

    if isinstance(profile, OnionProfile):
        ranked = _likes_by_weight(profile)
        interests: list[dict[str, object]] = []
        seen_names: set[str] = set()
        # 先放 domain tag: 每个排名的 domain 保留 tag 级别的曝光,
        # 即使更高 weight 的 domain 带了很多 specifics。
        for dom in ranked:
            if len(interests) >= _INTEREST_TAG_CAP:
                break
            interests.append(
                {
                    "name": dom.domain,
                    "category": dom.domain,
                    "weight": dom.weight,
                    "first_seen": _format_profile_timestamp(dom.first_seen),
                    "last_seen": _format_profile_timestamp(dom.last_seen),
                    "source": dom.source,
                }
            )
            seen_names.add(dom.domain)
        # 剩余槽位: specifics 按它们在所有 domain 之间自己的 weight 排序。
        # 这里若设 per-domain 配额会让 umbrella domain (真实 profile 上
        # 有 200+ specifics) 把 0.8-weight tag 藏在其 top-5 后面,而来自
        # 小 domain 的 0.4-weight tag 反而进来了。Per-domain 曝光已由
        # 上面的 domain tag 和 interest_domains 段保证,所以平坦列表可
        # 以纯粹按 weight 排序。
        all_specifics = sorted(
            ((spec, dom) for dom in ranked for spec in dom.specifics if spec.name.strip()),
            key=lambda pair: pair[0].weight,
            reverse=True,
        )
        for spec, dom in all_specifics:
            if len(interests) >= _INTEREST_TAG_CAP:
                break
            if spec.name in seen_names:
                continue
            seen_names.add(spec.name)
            interests.append(
                {
                    "name": spec.name,
                    "category": dom.domain,
                    "weight": spec.weight,
                    "first_seen": _format_profile_timestamp(dom.first_seen),
                    "last_seen": _format_profile_timestamp(dom.last_seen),
                    "source": dom.source,
                }
            )
        return interests

    ranked_flat = sorted(
        (tag for tag in profile.preferences.interests if tag.name.strip()),
        key=lambda tag: tag.weight,
        reverse=True,
    )
    return [
        {
            "name": interest.name,
            "category": interest.category,
            "weight": interest.weight,
            "first_seen": _format_profile_timestamp(interest.first_seen),
            "last_seen": _format_profile_timestamp(interest.last_seen),
            "source": interest.source,
        }
        for interest in ranked_flat[:_INTEREST_TAG_CAP]
    ]


def _summarize_mbti(profile: SoulProfile) -> dict[str, object] | None:
    """可用时返回紧凑的 MBTI 上下文。"""
    from openbiliclaw.soul.profile import OnionProfile

    if isinstance(profile, OnionProfile):
        mbti = profile.core.mbti
        if not mbti.type.strip():
            return None
        return {
            "type": mbti.type,
            "confidence": mbti.confidence,
            "dimensions": {
                key: {"pole": dim.pole, "strength": dim.strength}
                for key, dim in mbti.dimensions.items()
            },
            "inferred_from": mbti.inferred_from[:30],
        }

    raw_mbti = getattr(profile, "_raw_mbti", None)
    if not isinstance(raw_mbti, dict):
        return None
    raw_type = raw_mbti.get("type")
    mbti_type = raw_type if isinstance(raw_type, str) else ""
    if not mbti_type.strip():
        return None

    dimensions: dict[str, dict[str, object]] = {}
    raw_dimensions = raw_mbti.get("dimensions")
    if isinstance(raw_dimensions, dict):
        for key, raw_dimension in raw_dimensions.items():
            if not isinstance(key, str) or not isinstance(raw_dimension, dict):
                continue
            dimensions[key] = {
                "pole": str(raw_dimension.get("pole", "")),
                "strength": _coerce_profile_float(raw_dimension.get("strength", 0.5), 0.5),
            }

    return {
        "type": mbti_type,
        "confidence": _coerce_profile_float(raw_mbti.get("confidence", 0.0), 0.0),
        "dimensions": dimensions,
        "inferred_from": _coerce_profile_str_list(raw_mbti.get("inferred_from"), limit=30),
    }


def _summarize_recent_awareness(profile: SoulProfile) -> list[dict[str, str]]:
    notes: list[dict[str, str]] = []
    # 窗口是按时间最早→最新排列,所以最新的 note 在尾部 —
    # [:5] 会喂给 LLM *最旧* 的 observation。
    for note in profile.recent_awareness[-30:]:
        item = {
            "date": note.date,
            "observation": note.observation,
            "trend": note.trend,
            "emotion_guess": note.emotion_guess,
        }
        if any(value.strip() for value in item.values()):
            notes.append(item)
    return notes


def _summarize_active_insights(profile: SoulProfile) -> list[dict[str, object]]:
    insights: list[dict[str, object]] = []
    # 按时间窗口: 最新的 insight 在尾部。
    for insight in profile.active_insights[-30:]:
        item: dict[str, object] = {
            "hypothesis": insight.hypothesis,
            "evidence": insight.evidence[:30],
            "confidence": insight.confidence,
            "validated": insight.validated,
        }
        if insight.created_at:
            item["created_at"] = insight.created_at
        if insight.hypothesis.strip() or insight.evidence:
            insights.append(item)
    return insights


def build_profile_summary(
    profile: SoulProfile,
    *,
    interests: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    """构建每个 prompt 共享的规范结构化 profile 输入。

    这是喂给 LLM 的单一 profile 表示,适用于所有源平台内容调用 —
    discovery (search / trending / explore / evaluation) 和
    recommendation (evaluation / expression / reason) 都一样。

    自由形式的 ``personality_portrait`` 叙述被刻意排除: 下面的结构化
    字段已携带相同信号,而 prose summary 只是在重复它 (并用其装饰性
    比喻偏置 query/expression 生成)。portrait 仍会生成并显示在
    profile UI 中 — 只是不再进入任何 LLM prompt。

    同时包含 domain 级别 (一级) 和 specific (二级) interest,使
    discovery prompt 能在不同粒度级别上生成 query。传入 ``interests``
    以覆盖默认的按 weight 排序的 tag 列表 (例如 recommendation 的
    embedding-selected、content-relevant interest)。
    """
    interest_domains = _extract_interest_domains(profile)
    summary: dict[str, object] = {
        "core_traits": profile.core_traits[:30],
        "cognitive_style": profile.cognitive_style[:30],
        "values": profile.values[:30],
        "motivational_drivers": profile.motivational_drivers[:30],
        "current_phase": profile.current_phase,
        "life_stage": profile.life_stage,
        "interest_domains": interest_domains,
        "interests": interests if interests is not None else _extract_interest_tags(profile),
        # favorite_up_users 被有意从 LLM 可见的 profile 输出中排除:
        # "常看某创作者" ≠ "对该创作者内容类型感兴趣",且只会诱导模型
        # 从创作者名反推 interest。用户的 UP 列表仍存在于
        # /api/profile-summary (他们自己的视图) 并直接 seed
        # related_chain — 只是不在这里。
        "disliked_topics": profile.preferences.disliked_topics[:_DISLIKED_TOPICS_CAP],
        "deep_needs": profile.deep_needs[:30],
        "style": {
            "preferred_duration": profile.preferences.style.preferred_duration,
            "preferred_pace": profile.preferences.style.preferred_pace,
            "quality_sensitivity": profile.preferences.style.quality_sensitivity,
            "humor_preference": profile.preferences.style.humor_preference,
            "depth_preference": profile.preferences.style.depth_preference,
        },
        "context": {
            "weekday_patterns": profile.preferences.context.weekday_patterns,
            "weekend_patterns": profile.preferences.context.weekend_patterns,
            "time_of_day_patterns": profile.preferences.context.time_of_day_patterns,
            "session_type": profile.preferences.context.session_type,
        },
        "exploration_openness": profile.preferences.exploration_openness,
        "source_platform_mix": dict(profile.preferences.source_platform_mix),
        "recent_awareness": _summarize_recent_awareness(profile),
        "active_insights": _summarize_active_insights(profile),
    }
    mbti = _summarize_mbti(profile)
    if mbti:
        summary["mbti"] = mbti
    # 可用时包含活跃的 speculative interest
    speculations = getattr(profile, "_active_speculations", None)
    if speculations:
        summary["speculative_interests"] = [
            {
                "domain": s.domain if hasattr(s, "domain") else str(s.get("domain", "")),
                "reason": s.reason if hasattr(s, "reason") else str(s.get("reason", "")),
            }
            for s in speculations[:30]
        ]
    return summary


def _compact_query_interest_domains(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    compacted: list[dict[str, object]] = []
    for item in value[:_QUERY_INTEREST_DOMAIN_CAP]:
        if not isinstance(item, dict):
            continue
        specifics = item.get("specifics")
        if not isinstance(specifics, list):
            specifics = []
        domain = str(item.get("domain", "")).strip()
        if not domain:
            continue
        compacted.append(
            {
                "domain": domain,
                "weight": item.get("weight", 0),
                "specifics": [
                    str(spec).strip()
                    for spec in specifics[:_QUERY_SPECIFICS_PER_DOMAIN]
                    if str(spec).strip()
                ],
            }
        )
    return compacted


def cached_embedding_lookup(
    embedding_service: object | None,
) -> Callable[[str], list[float]] | None:
    """为 prompt shaping 返回安全的 cache-only embedding 查找。

    Query-generation prompt 不得触发新的 embedding API 调用;那会把
    成本从 chat completion 转移到 embedding 并给每个 planner/search
    周期增加延迟。``lookup_cached`` 让此 helper 保持 opportunistic:
    cache 温时用语义多样性,否则保留旧的确定性顺序。
    """
    lookup = getattr(embedding_service, "lookup_cached", None)
    if not callable(lookup):
        return None

    def _lookup(text: str) -> list[float]:
        try:
            return _coerce_query_embedding_vector(lookup(text))
        except Exception:
            return []

    return _lookup


def _coerce_query_embedding_vector(value: object) -> list[float]:
    if not isinstance(value, list):
        return []
    vector: list[float] = []
    for item in value:
        if not isinstance(item, (int, float)):
            return []
        number = float(item)
        if not math.isfinite(number):
            return []
        vector.append(number)
    return vector


def _lookup_query_embedding(
    text: str,
    embedding_lookup: Callable[[str], list[float] | None] | None,
) -> list[float]:
    if embedding_lookup is None:
        return []
    try:
        return _coerce_query_embedding_vector(embedding_lookup(text))
    except Exception:
        return []


def _clamp_similarity(value: float) -> float:
    return max(0.0, min(1.0, value))


def _cosine_similarity_safe(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    from openbiliclaw.llm.embedding import cosine_similarity

    return _clamp_similarity(cosine_similarity(a, b))


def _char_bigrams(text: str) -> set[str]:
    normalized = normalize_match_text(text)
    if not normalized:
        return set()
    if len(normalized) == 1:
        return {normalized}
    return {normalized[index : index + 2] for index in range(len(normalized) - 1)}


def _lexical_similarity(left: str, right: str) -> float:
    left_norm = normalize_match_text(left)
    right_norm = normalize_match_text(right)
    if not left_norm or not right_norm:
        return 0.0
    if left_norm == right_norm:
        return 1.0
    if left_norm in right_norm or right_norm in left_norm:
        return 0.88
    left_bigrams = _char_bigrams(left_norm)
    right_bigrams = _char_bigrams(right_norm)
    if not left_bigrams or not right_bigrams:
        return 0.0
    overlap = len(left_bigrams & right_bigrams)
    if overlap <= 0:
        return 0.0
    return min(0.75, overlap / max(len(left_bigrams), len(right_bigrams)))


def _interest_similarity(
    left: _QueryInterestCandidate,
    right: _QueryInterestCandidate,
) -> float:
    semantic = _cosine_similarity_safe(left.vector, right.vector)
    lexical = _lexical_similarity(left.text, right.text)
    category = (
        0.62
        if left.category
        and right.category
        and normalize_match_text(left.category) == normalize_match_text(right.category)
        else 0.0
    )
    return max(semantic, lexical, category)


def _interest_to_text_similarity(
    interest: _QueryInterestCandidate,
    topic: _QueryTextCandidate,
) -> float:
    semantic = _cosine_similarity_safe(interest.vector, topic.vector)
    lexical = _lexical_similarity(interest.text, topic.text)
    return max(semantic, lexical)


def _text_candidate_similarity(left: _QueryTextCandidate, right: _QueryTextCandidate) -> float:
    semantic = _cosine_similarity_safe(left.vector, right.vector)
    lexical = _lexical_similarity(left.text, right.text)
    return max(semantic, lexical)


def _normalized_weight(
    candidate: _QueryInterestCandidate, candidates: list[_QueryInterestCandidate]
) -> float:
    weights = [item.weight for item in candidates]
    max_weight = max(weights, default=0.0)
    min_weight = min(weights, default=0.0)
    span = max_weight - min_weight
    if span <= 1e-9:
        return candidate.priority
    return (candidate.weight - min_weight) / span


def _select_diverse_query_interests(
    candidates: list[_QueryInterestCandidate],
    *,
    disliked_topics: list[_QueryTextCandidate],
    cap: int,
) -> list[_QueryInterestCandidate]:
    if len(candidates) <= cap:
        return candidates
    if not any(candidate.vector for candidate in candidates) and not any(
        topic.vector for topic in disliked_topics
    ):
        return candidates[:cap]

    selected: list[_QueryInterestCandidate] = []
    remaining = list(candidates)
    while remaining and len(selected) < cap:
        selected_categories = {
            normalize_match_text(item.category) for item in selected if item.category.strip()
        }

        def score(
            candidate: _QueryInterestCandidate,
            selected_categories: set[str] = selected_categories,
        ) -> tuple[float, float, float]:
            weight_score = _normalized_weight(candidate, candidates)
            dislike_penalty = max(
                (_interest_to_text_similarity(candidate, topic) for topic in disliked_topics),
                default=0.0,
            )
            category_key = normalize_match_text(candidate.category)
            category_novelty = (
                0.5 if not category_key else float(category_key not in selected_categories)
            )
            if not selected:
                mmr = (
                    0.72 * weight_score
                    + 0.18 * category_novelty
                    + 0.10 * candidate.priority
                    - 0.55 * dislike_penalty
                )
                return (mmr, weight_score, candidate.priority)

            nearest_selected = max(
                (_interest_similarity(candidate, item) for item in selected),
                default=0.0,
            )
            novelty = 1.0 - nearest_selected
            mmr = (
                0.46 * novelty
                + 0.27 * weight_score
                + 0.19 * category_novelty
                + 0.08 * candidate.priority
                - 0.48 * dislike_penalty
            )
            return (mmr, weight_score, candidate.priority)

        best = max(remaining, key=score)
        selected.append(best)
        remaining.remove(best)
    return selected


def _select_diverse_query_texts(
    candidates: list[_QueryTextCandidate],
    *,
    cap: int,
) -> list[_QueryTextCandidate]:
    if len(candidates) <= cap:
        return candidates
    if not any(candidate.vector for candidate in candidates):
        return candidates[:cap]

    selected: list[_QueryTextCandidate] = []
    remaining = list(candidates)
    while remaining and len(selected) < cap:

        def score(candidate: _QueryTextCandidate) -> tuple[float, float]:
            if not selected:
                return (candidate.priority, candidate.priority)
            nearest_selected = max(
                (_text_candidate_similarity(candidate, item) for item in selected),
                default=0.0,
            )
            novelty = 1.0 - nearest_selected
            return (0.72 * novelty + 0.28 * candidate.priority, candidate.priority)

        best = max(remaining, key=score)
        selected.append(best)
        remaining.remove(best)
    return selected


def _compact_query_interests(
    value: object,
    *,
    disliked_topics: list[str],
    embedding_lookup: Callable[[str], list[float] | None] | None,
) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    candidates: list[_QueryInterestCandidate] = []
    pool = value[:_QUERY_INTEREST_CANDIDATE_POOL_CAP]
    pool_size = max(1, len(pool) - 1)
    for index, item in enumerate(pool):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        category = str(item.get("category", "")).strip()
        weight = _coerce_profile_float(item.get("weight"), 0.0)
        output = {
            "name": name,
            "category": category,
            "weight": item.get("weight", 0),
        }
        candidates.append(
            _QueryInterestCandidate(
                output=output,
                text=name,
                category=category,
                weight=weight,
                priority=1.0 - index / pool_size,
                vector=_lookup_query_embedding(name, embedding_lookup),
            )
        )

    disliked_candidates = _query_text_candidates(
        disliked_topics,
        cap=_QUERY_DISLIKED_TOPIC_CANDIDATE_POOL_CAP,
        embedding_lookup=embedding_lookup,
    )
    return [
        candidate.output
        for candidate in _select_diverse_query_interests(
            candidates,
            disliked_topics=disliked_candidates,
            cap=_QUERY_INTEREST_TAG_CAP,
        )
    ]


def _query_text_candidates(
    values: list[str],
    *,
    cap: int,
    embedding_lookup: Callable[[str], list[float] | None] | None,
) -> list[_QueryTextCandidate]:
    pool = values[:cap]
    pool_size = max(1, len(pool) - 1)
    candidates: list[_QueryTextCandidate] = []
    for index, text in enumerate(pool):
        clean = str(text).strip()
        if not clean:
            continue
        candidates.append(
            _QueryTextCandidate(
                text=clean,
                priority=1.0 - index / pool_size,
                vector=_lookup_query_embedding(clean, embedding_lookup),
            )
        )
    return candidates


def _compact_query_disliked_topics(
    value: object,
    *,
    embedding_lookup: Callable[[str], list[float] | None] | None,
) -> list[str]:
    if not isinstance(value, list):
        return []
    candidates = _query_text_candidates(
        [str(item).strip() for item in value if str(item).strip()],
        cap=_QUERY_DISLIKED_TOPIC_CANDIDATE_POOL_CAP,
        embedding_lookup=embedding_lookup,
    )
    return [
        candidate.text
        for candidate in _select_diverse_query_texts(
            candidates,
            cap=_QUERY_DISLIKED_TOPICS_CAP,
        )
    ]


def _compact_query_speculations(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    compacted: list[dict[str, object]] = []
    for item in value[:_QUERY_SPECULATIVE_INTEREST_CAP]:
        if not isinstance(item, dict):
            continue
        domain = str(item.get("domain", "")).strip()
        if domain:
            compacted.append({"domain": domain})
    return compacted


def _compact_query_str_list(value: object, cap: int) -> list[str]:
    if not isinstance(value, list):
        return []
    return [text for text in (str(item).strip() for item in value[:cap]) if text]


def build_query_generation_profile_summary(
    profile: SoulProfile,
    *,
    embedding_lookup: Callable[[str], list[float] | None] | None = None,
) -> dict[str, object]:
    """为 discovery query 生成构建紧凑、稳定的 profile 上下文。

    Search keyword、trending RID、explore domain 和 keyword-planner 批次
    需要用户稳定的口味形状,而非完整的高 churn profile 状态。这里刻意
    排除 recent awareness、active insight、时间戳、source provenance
    和 session context,以保持 prompt 成本有界、cache key 稳定,同时
    保留真正塑造搜索词的字段。
    """
    full = build_profile_summary(profile)
    disliked_topic_candidates = _compact_query_str_list(
        full.get("disliked_topics"),
        _QUERY_DISLIKED_TOPIC_CANDIDATE_POOL_CAP,
    )
    summary: dict[str, object] = {
        "core_traits": _compact_query_str_list(full.get("core_traits"), _QUERY_PROFILE_LIST_CAP),
        "cognitive_style": _compact_query_str_list(
            full.get("cognitive_style"), _QUERY_PROFILE_LIST_CAP
        ),
        "values": _compact_query_str_list(full.get("values"), _QUERY_PROFILE_LIST_CAP),
        "motivational_drivers": _compact_query_str_list(
            full.get("motivational_drivers"), _QUERY_PROFILE_LIST_CAP
        ),
        "current_phase": full.get("current_phase", ""),
        "life_stage": full.get("life_stage", ""),
        "interest_domains": _compact_query_interest_domains(full.get("interest_domains")),
        "interests": _compact_query_interests(
            full.get("interests"),
            disliked_topics=disliked_topic_candidates,
            embedding_lookup=embedding_lookup,
        ),
        "disliked_topics": _compact_query_disliked_topics(
            disliked_topic_candidates,
            embedding_lookup=embedding_lookup,
        ),
        "deep_needs": _compact_query_str_list(full.get("deep_needs"), _QUERY_PROFILE_LIST_CAP),
        "style": full.get("style", {}),
        "exploration_openness": full.get("exploration_openness", 0.0),
    }
    speculations = _compact_query_speculations(full.get("speculative_interests"))
    if speculations:
        summary["speculative_interests"] = speculations
    mbti = full.get("mbti")
    if isinstance(mbti, dict) and mbti.get("type"):
        summary["mbti"] = {
            "type": mbti.get("type", ""),
            "confidence": mbti.get("confidence", 0.0),
            "dimensions": mbti.get("dimensions", {}),
        }
    return summary


def interest_aliases(name: str) -> set[str]:
    """为给定 interest *name* 返回一组归一化的别名 token。"""
    cleaned = re.sub(r"\s+", "", name).strip().lower()
    if not cleaned:
        return set()
    aliases = {cleaned}
    stripped = re.sub(r"(系列|作品集|作品)$", "", cleaned).strip()
    if stripped:
        aliases.add(stripped)
    for token in re.split(r"[\s/&、，,+\-]+|与|和|及|之|的", cleaned):
        token = token.strip()
        if not token:
            continue
        if token.isascii():
            if len(token) >= 2:
                aliases.add(token)
            continue
        if len(token) >= 2:
            aliases.add(token)
    return aliases


def interest_anchors(profile: SoulProfile) -> list[tuple[str, float]]:
    """从顶层 profile interest 构建带权重的 interest anchor 对。"""
    anchors: dict[str, float] = {}
    for interest_item in profile.preferences.interests[:5]:
        raw_name = str(interest_item.name).strip()
        if not raw_name:
            continue
        weight = max(0.0, min(1.0, float(interest_item.weight)))
        for alias in interest_aliases(raw_name):
            anchors[alias] = max(anchors.get(alias, 0.0), weight)
    return list(anchors.items())
