"""猜测兴趣生命周期 —— 主动探索兴趣边界。

周期性地通过 LLM 生成猜测兴趣方向，跟踪用户事件的确认情况，并在
满足条件时晋升或拒绝（带冷却）。

生命周期：生成 → 活跃 → 晋升（已确认）/ 拒绝 + 冷却（已过期）
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from openbiliclaw.llm.json_utils import (
    DEFAULT_STRUCTURED_MAX_TOKENS,
    parse_llm_json_tolerant,
)
from openbiliclaw.llm.task_options import without_core_memory_kwargs

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from openbiliclaw.soul.profile import OnionProfile

logger = logging.getLogger(__name__)

_CHALLENGE_PROBE_MODES = {"lateral", "bridge", "wildcard"}
_DEFAULT_CHALLENGE_MAX_ACTIVE = 3


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------


@dataclass
class SpeculativeSpecific:
    """猜测领域内的一个窄兴趣话题。"""

    name: str = ""
    confirmation_count: int = 0
    confirming_events: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "confirmation_count": self.confirmation_count,
            "confirming_events": list(self.confirming_events),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SpeculativeSpecific:
        return cls(
            name=str(data.get("name", "")),
            confirmation_count=int(data.get("confirmation_count", 0)),
            confirming_events=list(data.get("confirming_events") or []),
        )


@dataclass
class SpeculativeInterest:
    """一个猜测的兴趣方向（领域），可附带窄兴趣。"""

    domain: str = ""
    category: str = ""
    reason: str = ""
    experience_mode: str = ""
    entry_load: str = ""
    confidence: float = 0.4
    weight: float = 0.4
    created_at: str = ""
    ttl_days: int = 14
    confirmation_count: int = 0
    confirmation_threshold: int = 3
    status: str = "active"  # "active" | "confirmed" | "promoted" | "rejected"
    confirming_events: list[str] = field(default_factory=list)
    specifics: list[SpeculativeSpecific] = field(default_factory=list)
    probe_mode: str = "near"
    confirmation_source: str = ""
    confirmed_at: str = ""

    @property
    def challenge(self) -> bool:
        return self.probe_mode in {"lateral", "bridge", "wildcard"}

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "category": self.category,
            "reason": self.reason,
            "experience_mode": self.experience_mode,
            "entry_load": self.entry_load,
            "confidence": self.confidence,
            "weight": self.weight,
            "created_at": self.created_at,
            "ttl_days": self.ttl_days,
            "confirmation_count": self.confirmation_count,
            "confirmation_threshold": self.confirmation_threshold,
            "status": self.status,
            "confirming_events": list(self.confirming_events),
            "specifics": [s.to_dict() for s in self.specifics],
            "probe_mode": self.probe_mode,
            "confirmation_source": self.confirmation_source,
            "confirmed_at": self.confirmed_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SpeculativeInterest:
        return cls(
            domain=str(data.get("domain", "")),
            category=str(data.get("category", "")),
            reason=str(data.get("reason", "")),
            experience_mode=str(data.get("experience_mode", "")),
            entry_load=str(data.get("entry_load", "")),
            confidence=float(data.get("confidence", 0.4)),
            weight=float(data.get("weight", 0.4)),
            created_at=str(data.get("created_at", "")),
            ttl_days=int(data.get("ttl_days", 14)),
            confirmation_count=int(data.get("confirmation_count", 0)),
            confirmation_threshold=int(data.get("confirmation_threshold", 3)),
            status=str(data.get("status", "active")),
            confirming_events=list(data.get("confirming_events") or []),
            specifics=[
                SpeculativeSpecific.from_dict(s)
                for s in (data.get("specifics") or [])
                if isinstance(s, dict)
            ],
            probe_mode=_normalize_probe_mode(data.get("probe_mode")),
            confirmation_source=str(data.get("confirmation_source", "")),
            confirmed_at=str(data.get("confirmed_at", "")),
        )


@dataclass
class CooldownEntry:
    """一条被拒绝的猜测，短期内不应再被猜。"""

    domain: str = ""
    category: str = ""
    rejected_at: str = ""
    cooldown_until: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "category": self.category,
            "rejected_at": self.rejected_at,
            "cooldown_until": self.cooldown_until,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CooldownEntry:
        return cls(
            domain=str(data.get("domain", "")),
            category=str(data.get("category", "")),
            rejected_at=str(data.get("rejected_at", "")),
            cooldown_until=str(data.get("cooldown_until", "")),
        )


@dataclass
class SpeculativeState:
    """所有猜测兴趣生命周期的状态容器。"""

    active: list[SpeculativeInterest] = field(default_factory=list)
    cooldown: list[CooldownEntry] = field(default_factory=list)
    last_generation_at: str = ""
    total_promoted: int = 0
    total_rejected: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "active": [s.to_dict() for s in self.active],
            "cooldown": [c.to_dict() for c in self.cooldown],
            "last_generation_at": self.last_generation_at,
            "total_promoted": self.total_promoted,
            "total_rejected": self.total_rejected,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SpeculativeState:
        return cls(
            active=[
                SpeculativeInterest.from_dict(s)
                for s in (data.get("active") or [])
                if isinstance(s, dict)
            ],
            cooldown=[
                CooldownEntry.from_dict(c)
                for c in (data.get("cooldown") or [])
                if isinstance(c, dict)
            ],
            last_generation_at=str(data.get("last_generation_at", "")),
            total_promoted=int(data.get("total_promoted", 0)),
            total_rejected=int(data.get("total_rejected", 0)),
        )


@dataclass
class SpeculatorTickResult:
    """一次 speculator tick 的摘要。"""

    generated: list[SpeculativeInterest] = field(default_factory=list)
    promoted: list[SpeculativeInterest] = field(default_factory=list)
    rejected: list[SpeculativeInterest] = field(default_factory=list)
    observed_matches: int = 0


# ---------------------------------------------------------------------------
# 观测（关键词匹配，不调用 LLM）
# ---------------------------------------------------------------------------


def _tokenize(text: str) -> set[str]:
    """从文本中抽取有意义的 token 用于匹配。"""
    # 按常见分隔符切分，保留长度 >= 2 的 token
    tokens: set[str] = set()
    for part in text.replace("·", " ").replace("、", " ").replace("/", " ").split():
        cleaned = part.strip().lower()
        if len(cleaned) >= 2:
            tokens.add(cleaned)
    return tokens


def _split_chinese_keywords(text: str) -> list[str]:
    """按常见分隔符把中文文本切成关键词片段。"""
    import re

    # 按连词、标点、助词切分
    parts = re.split(r"[与和·、/\s及]+", text)
    return [p.strip() for p in parts if len(p.strip()) >= 2]


def _chinese_bigrams(text: str) -> set[str]:
    """从连续中文片段中抽取去重的 2 字 bigram。

    对于 LLM 生成的 probe domain，例如 ``"AI图像生成工作流深度拆解"``，
    基于分隔符的切分 + 空白 token 化都会失败（没有分隔符，整段 11 字
    是一个 token）。bigram 让 matcher 有足够粒度去对照真实视频标题
    确认 probe，例如 "ComfyUI图像生成入门"（重叠 图像、像生、生成）。
    """
    import re

    bigrams: set[str] = set()
    for run in re.findall(r"[一-鿿]+", text):
        if len(run) < 2:
            continue
        for i in range(len(run) - 1):
            bigrams.add(run[i : i + 2])
    return bigrams


def _build_event_text(event: dict[str, Any]) -> str:
    """从事件中抽取可搜索的文本。"""
    title = str(event.get("title", "")).lower()
    tags = str(event.get("tags", "")).lower()
    category = str(event.get("category", "")).lower()
    return f"{title} {tags} {category}"


def _text_matches_keywords(event_text: str, name: str, category: str = "") -> bool:
    """通过子串或 token 重叠检查 event_text 是否匹配 name/category。"""
    name_lower = name.lower()
    cat_lower = category.lower()

    if name_lower and name_lower in event_text:
        return True
    if cat_lower and len(cat_lower) >= 2 and cat_lower in event_text:
        return True

    for keyword in _split_chinese_keywords(name):
        if keyword.lower() in event_text:
            return True

    spec_tokens = _tokenize(name) | _tokenize(category)
    event_tokens = _tokenize(event_text)
    if spec_tokens and len(spec_tokens & event_tokens) >= 2:
        return True

    # 中文 bigram 兜底，处理分隔符切分和空白 token 化都无法拆开的
    # 长复合短语。要求 name 一侧的 bigram 池至少有 4 个独立 bigram
    # （即 ≥5 字中文片段），以防止对短通用名过度匹配；并要求 ≥2 个
    # 重叠 bigram 才算命中。在上游 ``confirmation_threshold=3`` 的
    # 约束下，三个不相关事件里出现两次偶发 bigram 命中也不会让 probe
    # 晋升。
    name_bigrams = _chinese_bigrams(name) | _chinese_bigrams(category)
    if len(name_bigrams) < 4:
        return False
    return len(name_bigrams & _chinese_bigrams(event_text)) >= 2


def _event_matches_speculation(
    event: dict[str, Any],
    spec: SpeculativeInterest,
) -> bool:
    """检查事件是否在领域级别匹配某条猜测兴趣。"""
    event_text = _build_event_text(event)
    return _text_matches_keywords(event_text, spec.domain, spec.category)


def _event_matches_specific(
    event_text: str,
    specific: SpeculativeSpecific,
) -> bool:
    """检查事件文本是否匹配某个窄兴趣。"""
    return _text_matches_keywords(event_text, specific.name)


def _normalize_probe_term(value: Any) -> str:
    """规范化 probe 项用于本地去重检查。"""
    return "".join(str(value or "").strip().lower().split())

NEGATIVE_PROBE_FEEDBACK_RESPONSES = {"reject", "chat_negative", "chat_rejected"}
HANDLED_PROBE_FEEDBACK_RESPONSES = {
    "confirm",
    "confirmed",
    "reject",
    "rejected",
    "chat_positive",
    "chat_negative",
    "chat_rejected",
}


def _string_field(value: Any) -> str:
    return str(value or "").strip()


def _specific_names(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    names: list[str] = []
    for item in value:
        text = _string_field(item)
        if text:
            names.append(text)
    return names


def normalize_probe_feedback_history(history: object) -> list[dict[str, object]]:
    """返回已清洗的 probe 反馈记录，截断到最近窗口。"""
    if not isinstance(history, list):
        return []

    records: list[dict[str, object]] = []
    for item in history:
        if not isinstance(item, dict):
            continue
        domain = _string_field(item.get("domain"))
        response = _string_field(item.get("response")).lower()
        if not domain or not response:
            continue
        record: dict[str, object] = {
            "domain": domain,
            "response": response,
        }
        for key in (
            "axis",
            "category",
            "reason",
            "message",
            "raw_text_excerpt",
            "classification",
            "classifier",
            "resulting_action",
            "created_at",
            "source_mode",
            "source_signal",
        ):
            text = _string_field(item.get(key))
            if text:
                record[key] = text[:240] if key == "raw_text_excerpt" else text
        specifics = _specific_names(item.get("specifics"))
        if specifics:
            record["specifics"] = specifics
        records.append(record)
    return records


def append_probe_feedback_history(
    history: object,
    entry: dict[str, object],
) -> list[dict[str, object]]:
    """把一条已清洗的 probe 反馈记录追加到运行时历史。"""
    payload = dict(entry)
    if not _string_field(payload.get("created_at")):
        payload["created_at"] = datetime.now().isoformat()
    records = normalize_probe_feedback_history(history)
    records.append(payload)
    return normalize_probe_feedback_history(records)


def _negative_probe_feedback_domains(feedback_history: object) -> list[str]:
    return [
        str(item.get("domain", ""))
        for item in normalize_probe_feedback_history(feedback_history)
        if str(item.get("response", "")) in NEGATIVE_PROBE_FEEDBACK_RESPONSES
        and str(item.get("domain", "")).strip()
    ]


def _negative_probe_feedback_axes(feedback_history: object) -> set[str]:
    return {
        str(item.get("axis", "")).strip()
        for item in normalize_probe_feedback_history(feedback_history)
        if str(item.get("response", "")) in NEGATIVE_PROBE_FEEDBACK_RESPONSES
        and str(item.get("axis", "")).strip()
    }


def _handled_probe_feedback_domains(feedback_history: object) -> list[str]:
    return [
        str(item.get("domain", ""))
        for item in normalize_probe_feedback_history(feedback_history)
        if str(item.get("response", "")).lower() in HANDLED_PROBE_FEEDBACK_RESPONSES
        and str(item.get("domain", "")).strip()
    ]


def _has_probe_term_overlap(candidate: str, existing: str) -> bool:
    """当两个 probe 项明显覆盖同一范畴时返回 True。

    这里刻意保持保守：精确/子串匹配可捕获英文与混合词，而中文 bigram
    重叠捕获明显的短语扩展，例如 "ComfyUI工作流" → "ComfyUI工作流拆解"。
    """
    normalized_candidate = _normalize_probe_term(candidate)
    normalized_existing = _normalize_probe_term(existing)
    if not normalized_candidate or not normalized_existing:
        return False
    if (
        normalized_candidate == normalized_existing
        or normalized_candidate in normalized_existing
        or normalized_existing in normalized_candidate
    ):
        return True

    candidate_bigrams = _chinese_bigrams(normalized_candidate)
    existing_bigrams = _chinese_bigrams(normalized_existing)
    return len(candidate_bigrams) >= 4 and len(candidate_bigrams & existing_bigrams) >= 2


@dataclass
class ProbeNoveltyGuard:
    """猜测兴趣 probe 的本地去重守卫。"""

    exact_terms: set[str] = field(default_factory=set)
    fuzzy_terms: set[str] = field(default_factory=set)

    @classmethod
    def from_profile_and_state(
        cls,
        profile: OnionProfile | None,
        state: SpeculativeState,
        *,
        probed_domains: set[str] | None = None,
        feedback_history: object | None = None,
    ) -> ProbeNoveltyGuard:
        exact_terms: set[str] = set()
        fuzzy_terms: set[str] = set()

        def add_term(value: Any, *, exact: bool = True, fuzzy: bool = True) -> None:
            raw = str(value or "").strip()
            normalized = _normalize_probe_term(raw)
            if not normalized:
                return
            if exact:
                exact_terms.add(normalized)
            if fuzzy:
                fuzzy_terms.add(raw)

        if profile is not None:
            for domain in getattr(getattr(profile, "interest", None), "likes", []) or []:
                add_term(getattr(domain, "domain", ""))
                for specific in getattr(domain, "specifics", []) or []:
                    add_term(getattr(specific, "name", ""))

        for spec in state.active:
            add_term(spec.domain)
            for specific in spec.specifics:
                add_term(specific.name)
        for cooldown in state.cooldown:
            add_term(cooldown.domain)
        for domain in probed_domains or set():
            add_term(domain)
        for item in normalize_probe_feedback_history(feedback_history):
            response = str(item.get("response", "")).lower()
            if response not in HANDLED_PROBE_FEEDBACK_RESPONSES:
                continue
            add_term(item.get("domain", ""))
            for specific in _specific_names(item.get("specifics")):
                add_term(specific)

        return cls(exact_terms=exact_terms, fuzzy_terms=fuzzy_terms)

    def is_duplicate_domain(self, domain: str) -> bool:
        normalized = _normalize_probe_term(domain)
        if not normalized:
            return False
        if normalized in self.exact_terms:
            return True
        return any(_has_probe_term_overlap(domain, term) for term in self.fuzzy_terms)

    def filter_specifics(self, specifics: list[str]) -> list[str]:
        return [specific for specific in specifics if not self.is_duplicate_domain(specific)]


def observe_events(
    events: list[dict[str, Any]],
    state: SpeculativeState,
) -> tuple[SpeculativeState, int]:
    """在领域与窄兴趣两个层级把事件与活跃猜测进行对照。

    匹配是自底向上的：若某个窄兴趣命中，对应领域也获得计数。直接
    的领域命中（无窄兴趣）同样计数。
    """
    match_count = 0
    for spec in state.active:
        if spec.status != "active":
            continue
        for event in events:
            event_text = _build_event_text(event)
            title_short = str(event.get("title", ""))[:50]

            # 先检查窄兴趣（粒度更细）
            specific_matched = False
            for specific in spec.specifics:
                if _event_matches_specific(event_text, specific):
                    specific.confirmation_count += 1
                    specific.confirming_events.append(title_short)
                    specific_matched = True

            # 领域级确认：窄兴趣命中 或 领域直接命中
            if specific_matched or _text_matches_keywords(event_text, spec.domain, spec.category):
                spec.confirmation_count += 1
                spec.confirming_events.append(title_short)
                match_count += 1
    return state, match_count


# ---------------------------------------------------------------------------
# 晋升与过期（纯逻辑，不调用 LLM）
# ---------------------------------------------------------------------------


def promote_ready(state: SpeculativeState) -> tuple[list[SpeculativeInterest], SpeculativeState]:
    """抽取已准备好从"猜测"毕业到"已确认"的猜测。

    两条收敛的晋升路径：

      1. **自然** —— ``status == "active"`` 且行为信号把
         ``confirmation_count`` 推到了 ``confirmation_threshold``。用户
         持续点击该话题；系统自主晋升。
      2. **用户驱动** —— ``status == "confirmed"``。用户在弹窗或
         CLI ``probe`` 里点了"喜欢" / "是"；
         ``user_confirm_speculation`` 把 ``status`` 设为
         ``"confirmed"`` 并预填 ``confirmation_count = threshold``。
         没有这第二条分支的话，该行会永远卡在 ``state.active``：
         ``promote_ready`` 忽略它（status != "active"），
         ``expire_stale`` 也忽略它（同样的门限），而 ``_generate``
         会把它算进 ``len(state.active) >= max_active``，最终彻底
         卡死 probe 生成。这是 v0.3.32 时代一份报告的回归：``openbiliclaw
         probe`` 返回 "no active speculations"，但 ``force_tick
         generated=0``，因为 active 列表里默默积着 N 条
         confirmed-but-unmoved 条目。
    """
    promoted: list[SpeculativeInterest] = []
    remaining: list[SpeculativeInterest] = []
    for spec in state.active:
        ready = (
            spec.status == "active" and spec.confirmation_count >= spec.confirmation_threshold
        ) or spec.status == "confirmed"
        if ready:
            spec.status = "promoted"
            promoted.append(spec)
            state.total_promoted += 1
        else:
            remaining.append(spec)
    state.active = remaining
    return promoted, state


def expire_stale(
    state: SpeculativeState,
    now: datetime,
    cooldown_days: int = 30,
) -> tuple[list[SpeculativeInterest], SpeculativeState]:
    """让超过 TTL 的猜测过期，加入冷却，并清理过期冷却条目。"""
    rejected: list[SpeculativeInterest] = []
    remaining: list[SpeculativeInterest] = []
    for spec in state.active:
        if spec.status != "active":
            remaining.append(spec)
            continue
        try:
            created = datetime.fromisoformat(spec.created_at)
        except (ValueError, TypeError):
            remaining.append(spec)
            continue
        if now > created + timedelta(days=spec.ttl_days):
            spec.status = "rejected"
            rejected.append(spec)
            state.total_rejected += 1
            state.cooldown.append(
                CooldownEntry(
                    domain=spec.domain,
                    category=spec.category,
                    rejected_at=now.isoformat(),
                    cooldown_until=(now + timedelta(days=cooldown_days)).isoformat(),
                )
            )
        else:
            remaining.append(spec)
    state.active = remaining

    # 清理过期冷却
    valid_cooldowns: list[CooldownEntry] = []
    for entry in state.cooldown:
        try:
            until = datetime.fromisoformat(entry.cooldown_until)
        except (ValueError, TypeError):
            continue
        if now <= until:
            valid_cooldowns.append(entry)
    state.cooldown = valid_cooldowns

    return rejected, state


# ---------------------------------------------------------------------------
# 状态持久化
# ---------------------------------------------------------------------------


def load_speculative_state(data_dir: Path) -> SpeculativeState:
    """从磁盘加载猜测状态。"""
    path = data_dir / "memory" / "speculative_state.json"
    if not path.exists():
        return SpeculativeState()
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return SpeculativeState.from_dict(data)
    except (json.JSONDecodeError, OSError):
        return SpeculativeState()


def save_speculative_state(data_dir: Path, state: SpeculativeState) -> None:
    """把猜测状态持久化到磁盘。"""
    update_speculative_state(data_dir, lambda _state: state)


def update_speculative_state(
    data_dir: Path,
    mutator: Callable[[SpeculativeState], SpeculativeState | None],
) -> SpeculativeState:
    """基于最新的磁盘数据原子地更新猜测兴趣状态。"""
    from openbiliclaw.memory.json_state import update_json_state

    path = data_dir / "memory" / "speculative_state.json"

    def _mutate(state: SpeculativeState) -> SpeculativeState:
        result = mutator(state)
        return state if result is None else result

    return update_json_state(
        path,
        default_factory=SpeculativeState,
        normalize=lambda raw: (
            SpeculativeState.from_dict(raw) if isinstance(raw, dict) else SpeculativeState()
        ),
        serialize=lambda state: state.to_dict(),
        mutate=_mutate,
    )


# ---------------------------------------------------------------------------
# 核心引擎
# ---------------------------------------------------------------------------


class InterestSpeculator:
    """编排猜测兴趣的生命周期。

    职责：
    - 通过 LLM 生成新的猜测（周期性）
    - 观察事件以做确认（每次 ingest）
    - 把已确认的猜测晋升为正式兴趣
    - 让被拒绝的猜测过期并进入冷却
    """

    def __init__(
        self,
        *,
        llm_service: Any,
        data_dir: Path | None = None,
        generation_interval_minutes: int = 10,
        default_ttl_days: int = 3,
        cooldown_days: int = 7,
        confirmation_threshold: int = 3,
        max_active: int = 5,
        challenge_max_active: int = _DEFAULT_CHALLENGE_MAX_ACTIVE,
        max_primary_interests: int = 15,
        max_secondary_interests: int = 60,
        min_confidence: float = 0.30,
    ) -> None:
        self._llm_service = llm_service
        self._data_dir = data_dir
        self._generation_interval_minutes = generation_interval_minutes
        self._default_ttl_days = default_ttl_days
        self._cooldown_days = cooldown_days
        self._confirmation_threshold = confirmation_threshold
        self._max_active = max_active
        self._challenge_max_active = challenge_max_active
        self._max_primary_interests = max_primary_interests
        self._max_secondary_interests = max_secondary_interests
        # 质量门：丢弃自评置信度低于该阈值的候选。阈值历史：
        #   0.48 → 0.40（v0.3.x，"DeepSeek 在画像有 25+ likes 后
        #               打分 0.35-0.46；0.40 让典型输出能过")
        #   0.40 → 0.30（v0.3.53，2026-05-05）：生产日志显示
        #               speculator force_tick generated=5 / promoted=0
        #               —— 每个候选都正好命中 confidence=0.35，即 LLM
        #               对一个已校准用户死钉在 0.35。0.40 刚好高于 LLM
        #               的实际输出带，把 5 个全砍了。0.30 让 LLM 的自然
        #               置信带能通过；下游流水线（specifics≥2 /
        #               reason≥20chars / domain 不遮盖既有 like / 对
        #               active+cooldown 去重）仍会拒绝偷懒候选。低于
        #               0.30 就是"随便报域名"的领地。
        self._min_confidence = min_confidence

    def _load_state(self) -> SpeculativeState:
        if self._data_dir:
            return load_speculative_state(self._data_dir)
        return SpeculativeState()

    def _save_state(self, state: SpeculativeState) -> None:
        if self._data_dir:
            save_speculative_state(self._data_dir, state)

    def _update_state(
        self,
        mutator: Callable[[SpeculativeState], SpeculativeState | None],
    ) -> SpeculativeState:
        if self._data_dir:
            return update_speculative_state(self._data_dir, mutator)
        state = SpeculativeState()
        result = mutator(state)
        return state if result is None else result

    @staticmethod
    def _latest_feedback_history(
        *,
        feedback_history: object | None,
        feedback_history_loader: Callable[[], object] | None,
    ) -> object | None:
        if feedback_history_loader is None:
            return feedback_history
        try:
            return feedback_history_loader()
        except Exception:
            logger.debug("Failed to load latest probe feedback history", exc_info=True)
            return feedback_history

    def _merge_generated_candidates(
        self,
        candidates: list[SpeculativeInterest],
        profile: OnionProfile,
        *,
        feedback_history: object | None,
    ) -> list[SpeculativeInterest]:
        if not candidates:
            return []
        generated: list[SpeculativeInterest] = []

        def _mutate(state: SpeculativeState) -> None:
            nonlocal generated
            near_slots, challenge_slots = _available_probe_slots(
                state.active,
                near_limit=self._max_active,
                challenge_limit=self._challenge_max_active,
            )
            if near_slots + challenge_slots <= 0:
                return
            novelty_guard = ProbeNoveltyGuard.from_profile_and_state(
                profile,
                state,
                feedback_history=feedback_history,
            )
            existing_domains = {
                str(item.domain).strip().lower()
                for item in state.active
                if str(item.domain).strip()
                and item.status in {"active", "confirmed", "user_rejected", "rejected"}
            }
            selected: list[SpeculativeInterest] = []
            for candidate in _select_candidates_for_probe_slots(
                candidates,
                near_limit=near_slots,
                challenge_limit=challenge_slots,
                existing=[item for item in state.active if item.status == "active"],
                feedback_history=feedback_history,
            ):
                domain_key = candidate.domain.strip().lower()
                if not domain_key or domain_key in existing_domains:
                    continue
                if novelty_guard.is_duplicate_domain(candidate.domain):
                    continue
                if not _probe_slot_available(
                    state.active,
                    candidate.probe_mode,
                    near_limit=self._max_active,
                    challenge_limit=self._challenge_max_active,
                ):
                    continue
                state.active.append(candidate)
                existing_domains.add(domain_key)
                selected.append(candidate)
            generated = selected

        self._update_state(_mutate)
        return generated

    # -- 公共 API -----------------------------------------------------------

    async def tick(
        self,
        profile: OnionProfile,
        *,
        feedback_history: object | None = None,
        feedback_history_loader: Callable[[], object] | None = None,
    ) -> SpeculatorTickResult:
        """周期性主入口：过期 → 晋升 → 生成 → 保存。"""
        now = datetime.now()
        result = SpeculatorTickResult()

        def _prepare(state: SpeculativeState) -> SpeculativeState:
            rejected, next_state = expire_stale(state, now, self._cooldown_days)
            result.rejected = rejected
            promoted, next_state = promote_ready(next_state)
            result.promoted = promoted
            return next_state

        state = self._update_state(_prepare)

        # 3. 若间隔已过且未达上限，则生成新的猜测
        if self._should_generate(state, now, profile):
            pre_active_domains = {s.domain for s in state.active if s.status == "active"}
            snapshot = await self._generate(
                profile,
                state,
                now,
                feedback_history=feedback_history,
            )
            candidates = [
                s
                for s in snapshot.active
                if s.status == "active" and s.domain not in pre_active_domains
            ]
            latest_feedback = self._latest_feedback_history(
                feedback_history=feedback_history,
                feedback_history_loader=feedback_history_loader,
            )
            result.generated = self._merge_generated_candidates(
                candidates,
                profile,
                feedback_history=latest_feedback,
            )

        if result.promoted:
            logger.info(
                "Speculator promoted %d interests: %s",
                len(result.promoted),
                [s.domain for s in result.promoted],
            )
        if result.rejected:
            logger.info(
                "Speculator rejected %d speculations: %s",
                len(result.rejected),
                [s.domain for s in result.rejected],
            )
        if result.generated:
            logger.info(
                "Speculator generated %d new speculations: %s",
                len(result.generated),
                [s.domain for s in result.generated],
            )

        return result

    async def force_tick(
        self,
        profile: OnionProfile,
        *,
        feedback_history: object | None = None,
        feedback_history_loader: Callable[[], object] | None = None,
    ) -> SpeculatorTickResult:
        """忽略间隔计时器强制执行一次 speculator tick。

        在 init 与进程启动时使用，确保猜测能立即出现。
        仍会遵守兴趣层级上限与 max_active。
        """
        now = datetime.now()
        result = SpeculatorTickResult()

        def _prepare(state: SpeculativeState) -> SpeculativeState:
            rejected, next_state = expire_stale(state, now, self._cooldown_days)
            result.rejected = rejected
            promoted, next_state = promote_ready(next_state)
            result.promoted = promoted
            return next_state

        state = self._update_state(_prepare)

        # 不论间隔都生成（但仍遵守上限）。
        # "primary interests" 上限历史上以 ``confirmed_domains +
        # active_count`` 为门，一旦用户已确认兴趣超过上限就会死锁整个
        # probe 流水线（例如画像有 21 个 confirmed likes 而上限=15 →
        # 永远不触发 probe）。该上限的本意是限制 *猜测* fanout，不是
        # 惩罚兴趣已充分画像的用户。这里只对 ``active_count`` 设门，
        # 这样无论已确认多少兴趣，probe 仍能流动。
        active_count = sum(1 for s in state.active if s.status == "active")
        near_slots, challenge_slots = _available_probe_slots(
            state.active,
            near_limit=self._max_active,
            challenge_limit=self._challenge_max_active,
        )
        can_generate = (
            near_slots + challenge_slots > 0
            and active_count < self._max_primary_interests
            and self._llm_service is not None
        )
        if can_generate:
            pre_active_domains = {s.domain for s in state.active if s.status == "active"}
            snapshot = await self._generate(
                profile,
                state,
                now,
                feedback_history=feedback_history,
            )
            candidates = [
                s
                for s in snapshot.active
                if s.status == "active" and s.domain not in pre_active_domains
            ]
            latest_feedback = self._latest_feedback_history(
                feedback_history=feedback_history,
                feedback_history_loader=feedback_history_loader,
            )
            result.generated = self._merge_generated_candidates(
                candidates,
                profile,
                feedback_history=latest_feedback,
            )
        # 只有发生有意义事件时才打 INFO，否则降级到 DEBUG，
        # 避免空闲 force_tick 污染日志。
        if result.generated or result.promoted or result.rejected:
            logger.info(
                "Speculator force_tick: generated=%d, promoted=%d, rejected=%d",
                len(result.generated),
                len(result.promoted),
                len(result.rejected),
            )
        else:
            near_count, challenge_count = _active_probe_slot_counts(state.active)
            logger.debug(
                "Speculator force_tick: no-op "
                "(near=%d/%d, challenge=%d/%d, nothing to expire/promote)",
                near_count,
                self._max_active,
                challenge_count,
                self._challenge_max_active,
            )
        return result

    def observe(self, events: list[dict[str, Any]]) -> int:
        """把事件对活跃猜测进行观测。返回命中数。"""
        if not events:
            return 0
        match_count = 0
        active_count = 0

        def _mutate(state: SpeculativeState) -> None:
            nonlocal active_count, match_count
            active_count = sum(1 for s in state.active if s.status == "active")
            if active_count == 0:
                return
            _state, match_count = observe_events(events, state)

        self._update_state(_mutate)
        if match_count > 0:
            # 升级到 INFO，让生产日志能看到实时确认脉动（在我们的默认
            # file_level 下 DEBUG 实际不可见）。同时附上 active probe
            # 数量，便于读者核查"事件到达但 5 个 active probe 命中 0"
            # 这类诊断。
            logger.info(
                "Speculator observed %d match(es) from %d event(s) against %d active probe(s)",
                match_count,
                len(events),
                active_count,
            )
        return match_count

    def ingest_seeds(
        self,
        seeds: list[dict[str, Any]],
        *,
        profile: OnionProfile | None = None,
        probed_domains: set[str] | None = None,
        feedback_history: object | None = None,
    ) -> int:
        """把 PreferenceAnalyzer 输出的猜测兴趣作为种子候选 ingest。"""
        if not seeds:
            return 0

        now = datetime.now()
        added = 0

        def _mutate(state: SpeculativeState) -> None:
            nonlocal added
            existing_domains = {s.domain.lower() for s in state.active}
            cooldown_domains = {c.domain.lower() for c in state.cooldown}
            novelty_guard = ProbeNoveltyGuard.from_profile_and_state(
                profile,
                state,
                probed_domains=probed_domains,
                feedback_history=feedback_history,
            )

            for seed in seeds:
                domain = str(seed.get("domain") or seed.get("name", "")).strip()
                if not domain:
                    continue
                if domain.lower() in existing_domains or domain.lower() in cooldown_domains:
                    continue
                if novelty_guard.is_duplicate_domain(domain):
                    continue
                probe_mode = _normalize_probe_mode(seed.get("probe_mode"))
                if not _probe_slot_available(
                    state.active,
                    probe_mode,
                    near_limit=self._max_active,
                    challenge_limit=self._challenge_max_active,
                ):
                    continue

                state.active.append(
                    SpeculativeInterest(
                        domain=domain,
                        category=str(seed.get("category", "")),
                        reason=str(seed.get("reason", "")),
                        confidence=float(seed.get("confidence") or seed.get("weight", 0.4)),
                        weight=float(seed.get("weight", 0.4)),
                        created_at=now.isoformat(),
                        ttl_days=self._default_ttl_days,
                        confirmation_threshold=self._confirmation_threshold,
                        probe_mode=probe_mode,
                    )
                )
                existing_domains.add(domain.lower())
                added += 1

        self._update_state(_mutate)
        if added > 0:
            logger.info("Speculator ingested %d seed speculations", added)
        return added

    def get_active_speculations(self) -> list[SpeculativeInterest]:
        """返回当前活跃的猜测（供 discovery 集成使用）。"""
        state = self._load_state()
        return [s for s in state.active if s.status == "active"]

    def user_confirm_speculation(
        self,
        domain: str,
        *,
        confirmation_source: str = "probe_confirmed",
    ) -> bool:
        """用户显式确认了一条猜测兴趣。强制晋升它。

        把 ``status`` 设为 ``"confirmed"``，让 API 不再把这一行作为
        speculative 列表暴露在弹窗里（晋升为真正的兴趣标签仍在
        :meth:`force_tick` 内异步发生）。没有这一步的话，
        profile-summary 会持续返回 ``confirmation_count == threshold``
        的这一行，弹窗在用户点 "喜欢" 几秒后又重新渲染它 —— 看起来
        像动作被忽略了。
        """
        now = datetime.now().isoformat()
        found = False

        def _mutate(state: SpeculativeState) -> None:
            nonlocal found
            for spec in state.active:
                if spec.domain.lower() == domain.lower() and spec.status == "active":
                    spec.confirmation_count = spec.confirmation_threshold
                    spec.confirming_events.append(confirmation_source)
                    spec.confirmation_source = confirmation_source
                    spec.confirmed_at = now
                    spec.status = "confirmed"
                    found = True
                    return

        self._update_state(_mutate)
        return found

    def user_reject_speculation(self, domain: str, cooldown_days: int = 30) -> bool:
        """用户显式拒绝了一条猜测兴趣。把它移入冷却。"""
        found = False
        now = datetime.now()

        def _mutate(state: SpeculativeState) -> None:
            nonlocal found
            remaining = []
            for spec in state.active:
                if spec.domain.lower() == domain.lower() and spec.status == "active":
                    spec.status = "rejected"
                    state.total_rejected += 1
                    state.cooldown.append(
                        CooldownEntry(
                            domain=spec.domain,
                            category=spec.category,
                            rejected_at=now.isoformat(),
                            cooldown_until=(now + timedelta(days=cooldown_days)).isoformat(),
                        )
                    )
                    found = True
                else:
                    remaining.append(spec)
            state.active = remaining

        self._update_state(_mutate)
        return found

    # -- 内部 -------------------------------------------------------------

    def _should_generate(
        self,
        state: SpeculativeState,
        now: datetime,
        profile: OnionProfile | None = None,
    ) -> bool:
        """检查是否应该执行生成。

        跳过的情况：
        - 活跃猜测已达 max_active
        - primary interests（已确认 domain + 活跃猜测）达上限
        - secondary interests（已确认窄兴趣 + 活跃猜测）达上限
        - 间隔未过
        """
        active_count = sum(1 for s in state.active if s.status == "active")
        near_slots, challenge_slots = _available_probe_slots(
            state.active,
            near_limit=self._max_active,
            challenge_limit=self._challenge_max_active,
        )
        available_slots = near_slots + challenge_slots
        if available_slots <= 0:
            return False

        # 槽位感知的节流：当只剩 1 个空槽时，去重门
        # （existing_domains）几乎总会赢，因为 LLM 倾向于按名字重复
        # 提出卡住的 active probe。我们观察到连续 7+ 个 30 分钟 tick
        # 都生成同样的 2 个卡住 domain，新增 0 个 probe，每次 tick
        # 烧掉约 ¥0.005 一无所获。要求至少 2 个空槽，使候选产出对
        # LLM 调用成本而言更现实。
        if available_slots < 2:
            near_count, challenge_count = _active_probe_slot_counts(state.active)
            logger.debug(
                "Speculation skipped: only %d slot(s) free "
                "(near=%d/%d, challenge=%d/%d), "
                "not worth an LLM call (most candidates would dedup-fail).",
                available_slots,
                near_count,
                self._max_active,
                challenge_count,
                self._challenge_max_active,
            )
            return False

        # 检查活跃猜测层级上限。这里只对 ``active_count`` 设门，而非
        # ``confirmed + active`` —— 见 ``force_tick`` 中的注释：在旧
        # 门限下，一个已确认兴趣很多的用户会被永久死锁。
        if profile is not None:
            if active_count >= self._max_primary_interests:
                logger.debug(
                    "Speculation skipped: active speculations at primary cap (%d/%d)",
                    active_count,
                    self._max_primary_interests,
                )
                return False

            # secondary 上限同样修复 —— 只对活跃猜测计数设门，而不是
            # ``confirmed_specifics + active``，这样画像丰富的用户
            # 不会被永久静音 probe 循环。
            if active_count >= self._max_secondary_interests:
                logger.debug(
                    "Speculation skipped: active speculations at secondary cap (%d/%d)",
                    active_count,
                    self._max_secondary_interests,
                )
                return False

        if not state.last_generation_at:
            return True
        try:
            last = datetime.fromisoformat(state.last_generation_at)
        except (ValueError, TypeError):
            return True
        return now > last + timedelta(minutes=self._generation_interval_minutes)

    async def _generate(
        self,
        profile: OnionProfile,
        state: SpeculativeState,
        now: datetime,
        *,
        feedback_history: object | None = None,
    ) -> SpeculativeState:
        """用 LLM 生成新的猜测兴趣方向。"""
        from openbiliclaw.llm.prompts import build_speculation_generation_prompt

        existing_domains = {s.domain.lower() for s in state.active}
        cooldown_domains = [c.domain for c in state.cooldown]
        confirmed_domains = [d.domain for d in profile.interest.likes]

        near_slots, challenge_slots = _available_probe_slots(
            state.active,
            near_limit=self._max_active,
            challenge_limit=self._challenge_max_active,
        )
        slots = near_slots + challenge_slots
        if slots <= 0:
            return state

        messages = build_speculation_generation_prompt(
            profile_summary=profile.to_llm_context(include_portrait=False),
            existing_speculations=[s.domain for s in state.active],
            cooldown_domains=cooldown_domains,
            confirmed_domains=confirmed_domains,
            count=min(max(slots * 2, 5), 10),
            probe_mode_request=_probe_mode_request_for_slots(
                near_slots=near_slots,
                challenge_slots=challenge_slots,
            ),
        )

        try:
            from openbiliclaw.llm.base import LLMProviderError
            from openbiliclaw.llm.service import LLMServiceError

            complete_structured = self._llm_service.complete_structured_task
            response = await complete_structured(
                system_instruction=messages[0]["content"],
                user_input=messages[1]["content"],
                max_tokens=DEFAULT_STRUCTURED_MAX_TOKENS,
                caller="soul.speculate",
                **without_core_memory_kwargs(complete_structured),
            )
            raw = _parse_speculation_response(response.content)
        except (LLMProviderError, LLMServiceError):
            logger.warning("Speculation generation LLM call failed", exc_info=True)
            return state
        except Exception:
            logger.warning("Speculation generation failed", exc_info=True)
            return state

        # 用户既有顶层 like domain 名集合（小写）。用作质量检查：若 LLM
        # 生成的 probe ``domain`` 等于用户实际的某个 like domain，就是
        # 偷懒 probe（例如 domain="娱乐" 而用户已有 娱乐 0.95）—— 丢弃。
        like_domain_set = {
            str(getattr(d, "domain", "")).strip().lower()
            for d in getattr(profile.interest, "likes", [])
            if str(getattr(d, "domain", "")).strip()
        }
        novelty_guard = ProbeNoveltyGuard.from_profile_and_state(
            profile,
            state,
            feedback_history=feedback_history,
        )

        candidates: list[SpeculativeInterest] = []
        rejected_reasons: list[str] = []
        for item in raw:
            domain = str(item.get("domain", "")).strip()
            if not domain or domain.lower() in existing_domains:
                continue

            raw_specifics = item.get("specifics") or []
            specifics = [
                SpeculativeSpecific(name=str(s).strip())
                for s in raw_specifics
                if isinstance(s, str) and str(s).strip()
            ]
            confidence = float(item.get("confidence", 0.4))
            reason_text = str(item.get("reason", "")).strip()

            # ── 质量门 ────────────────────────────────────────
            # 跳过低置信 probe（LLM 自己的含糊其辞）。
            if confidence < self._min_confidence:
                rejected_reasons.append(
                    f"{domain} (conf={confidence:.2f} < {self._min_confidence})"
                )
                continue
            # 跳过 domain 就是用户主轴名 的 probe。
            if domain.lower() in like_domain_set:
                rejected_reasons.append(f"{domain} (domain shadows existing like)")
                continue
            # 跳过重复 profile/active/cooldown 覆盖范围的 probe。
            if novelty_guard.is_duplicate_domain(domain):
                rejected_reasons.append(f"{domain} (duplicate coverage)")
                continue
            # 跳过没有可用 specifics 的 probe。
            filtered_specific_names = novelty_guard.filter_specifics([s.name for s in specifics])
            specifics = [SpeculativeSpecific(name=name) for name in filtered_specific_names]
            if len(specifics) < 2:
                rejected_reasons.append(f"{domain} (specifics<2)")
                continue
            # 跳过理由短得离谱的 probe（LLM 在敷衍）。
            if len(reason_text) < 20:
                rejected_reasons.append(f"{domain} (reason<20chars)")
                continue

            candidates.append(
                SpeculativeInterest(
                    domain=domain,
                    category=str(item.get("category", "")),
                    reason=reason_text,
                    experience_mode=_normalize_experience_mode(item.get("experience_mode")),
                    entry_load=_normalize_entry_load(item.get("entry_load")),
                    probe_mode=_normalize_probe_mode(item.get("probe_mode")),
                    confidence=confidence,
                    weight=confidence,
                    created_at=now.isoformat(),
                    ttl_days=self._default_ttl_days,
                    confirmation_threshold=self._confirmation_threshold,
                    specifics=specifics,
                )
            )

        if rejected_reasons:
            logger.info(
                "Speculator quality gate dropped %d candidate(s): %s",
                len(rejected_reasons),
                "; ".join(rejected_reasons),
            )

        existing_active = [s for s in state.active if s.status == "active"]
        for candidate in _select_candidates_for_probe_slots(
            candidates,
            near_limit=near_slots,
            challenge_limit=challenge_slots,
            existing=existing_active,
            feedback_history=feedback_history,
        ):
            if not _probe_slot_available(
                state.active,
                candidate.probe_mode,
                near_limit=self._max_active,
                challenge_limit=self._challenge_max_active,
            ):
                continue
            state.active.append(candidate)
            existing_domains.add(candidate.domain.lower())

        state.last_generation_at = now.isoformat()
        return state


def _parse_speculation_response(content: str) -> list[dict[str, Any]]:
    """从 LLM 响应中抽取猜测列表。

    接受裸列表或 ``{"speculations": [...]}`` 对象，并对半截被截断的
    响应回退到截断抢救。
    """
    data = parse_llm_json_tolerant(content)
    if isinstance(data, dict):
        speculations = data.get("speculations", [])
        if isinstance(speculations, list):
            return [item for item in speculations if isinstance(item, dict)]
        return []
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


def _normalize_experience_mode(value: Any) -> str:
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    allowed = {
        "knowledge",
        "aesthetic",
        "hands_on",
        "people_story",
        "wander_observe",
    }
    return text if text in allowed else ""


def _normalize_entry_load(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text if text in {"light", "heavy"} else ""


def _normalize_probe_mode(value: Any) -> str:
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    return text if text in {"near", "lateral", "bridge", "wildcard"} else "near"


def _is_challenge_probe_mode(value: Any) -> bool:
    return _normalize_probe_mode(value) in _CHALLENGE_PROBE_MODES


def _active_probe_slot_counts(specs: list[SpeculativeInterest]) -> tuple[int, int]:
    near_count = 0
    challenge_count = 0
    for spec in specs:
        if spec.status != "active":
            continue
        if _is_challenge_probe_mode(spec.probe_mode):
            challenge_count += 1
        else:
            near_count += 1
    return near_count, challenge_count


def _available_probe_slots(
    specs: list[SpeculativeInterest],
    *,
    near_limit: int,
    challenge_limit: int,
) -> tuple[int, int]:
    near_count, challenge_count = _active_probe_slot_counts(specs)
    return (
        max(0, near_limit - near_count),
        max(0, challenge_limit - challenge_count),
    )


def _probe_slot_available(
    specs: list[SpeculativeInterest],
    probe_mode: Any,
    *,
    near_limit: int,
    challenge_limit: int,
) -> bool:
    near_slots, challenge_slots = _available_probe_slots(
        specs,
        near_limit=near_limit,
        challenge_limit=challenge_limit,
    )
    if _is_challenge_probe_mode(probe_mode):
        return challenge_slots > 0
    return near_slots > 0


def _probe_mode_request_for_slots(*, near_slots: int, challenge_slots: int) -> str:
    if near_slots <= 0 and challenge_slots > 0:
        return (
            "本轮普通 near 池已满，只补挑战探针。"
            "所有候选的 probe_mode 必须从 lateral / bridge / wildcard 中选择，"
            "不要输出 near。"
        )
    if challenge_slots <= 0 and near_slots > 0:
        return "本轮挑战池已满，只补普通探针。所有候选的 probe_mode 必须是 near。"
    if near_slots > 0 and challenge_slots > 0:
        return (
            f"本轮还有 {near_slots} 个 near 普通槽和 {challenge_slots} 个挑战槽；"
            "请同时给 near 和 lateral / bridge / wildcard 候选，避免全部输出 near。"
        )
    return "本轮没有可用探针槽位。"


def _candidate_priority(
    candidate: SpeculativeInterest,
    selected: list[SpeculativeInterest],
    *,
    avoid_axes: set[str] | None = None,
) -> tuple[float, float]:
    score = float(candidate.confidence)
    axis = build_probe_axis(
        experience_mode=candidate.experience_mode,
        entry_load=candidate.entry_load,
    )
    selected_modes = {item.experience_mode for item in selected if item.experience_mode}
    selected_loads = {item.entry_load for item in selected if item.entry_load}
    if candidate.experience_mode and candidate.experience_mode not in selected_modes:
        score += 0.08
    if candidate.entry_load and candidate.entry_load not in selected_loads:
        score += 0.05
    if candidate.entry_load == "light" and "light" not in selected_loads:
        score += 0.05
    if candidate.experience_mode and candidate.experience_mode != "knowledge":
        score += 0.05
    if axis and axis in (avoid_axes or set()):
        score -= 0.6
    return (score, float(candidate.weight))


def _pick_best_candidate(
    candidates: list[SpeculativeInterest],
    selected: list[SpeculativeInterest],
    predicate: Any,
    *,
    avoid_axes: set[str] | None = None,
) -> SpeculativeInterest | None:
    matching = [
        candidate for candidate in candidates if candidate not in selected and predicate(candidate)
    ]
    if not matching:
        return None
    return max(
        matching,
        key=lambda candidate: _candidate_priority(
            candidate,
            selected,
            avoid_axes=avoid_axes,
        ),
    )


def _probe_mode(candidate: SpeculativeInterest) -> str:
    return _normalize_probe_mode(candidate.probe_mode)


def _best_unselected_by_probe_mode(
    ordered: list[SpeculativeInterest],
    selected: list[SpeculativeInterest],
    context: list[SpeculativeInterest],
    *,
    avoid_axes: set[str],
    modes: set[str],
) -> SpeculativeInterest | None:
    pool = [
        candidate
        for candidate in ordered
        if candidate not in selected and _probe_mode(candidate) in modes
    ]
    if not pool:
        return None
    return max(
        pool,
        key=lambda candidate: _candidate_priority(
            candidate,
            context + selected,
            avoid_axes=avoid_axes,
        ),
    )


def _replace_weakest_selected(
    selected: list[SpeculativeInterest],
    replacement: SpeculativeInterest,
    context: list[SpeculativeInterest],
    *,
    avoid_axes: set[str],
    replace_modes: set[str],
) -> bool:
    replaceable = [candidate for candidate in selected if _probe_mode(candidate) in replace_modes]
    if not replaceable:
        return False
    weakest = min(
        replaceable,
        key=lambda candidate: _candidate_priority(
            candidate,
            context + selected,
            avoid_axes=avoid_axes,
        ),
    )
    selected[selected.index(weakest)] = replacement
    return True


def _apply_probe_mode_quotas(
    ordered: list[SpeculativeInterest],
    selected: list[SpeculativeInterest],
    *,
    limit: int,
    context: list[SpeculativeInterest],
    avoid_axes: set[str],
) -> list[SpeculativeInterest]:
    if not selected:
        return selected

    available_modes = {_probe_mode(candidate) for candidate in ordered}
    challenge_modes = {"lateral", "bridge", "wildcard"}
    challenge_available = bool(available_modes & challenge_modes)
    if challenge_available and not any(_probe_mode(item) in challenge_modes for item in selected):
        replacement = _best_unselected_by_probe_mode(
            ordered,
            selected,
            context,
            avoid_axes=avoid_axes,
            modes=challenge_modes,
        )
        if replacement is not None:
            _replace_weakest_selected(
                selected,
                replacement,
                context,
                avoid_axes=avoid_axes,
                replace_modes={"near"},
            )

    if challenge_available:
        near_max = max(1, math.ceil(limit * 0.40))
        while sum(1 for item in selected if _probe_mode(item) == "near") > near_max:
            replacement = _best_unselected_by_probe_mode(
                ordered,
                selected,
                context,
                avoid_axes=avoid_axes,
                modes=challenge_modes,
            )
            if replacement is None:
                break
            if not _replace_weakest_selected(
                selected,
                replacement,
                context,
                avoid_axes=avoid_axes,
                replace_modes={"near"},
            ):
                break

    selected_modes = {_probe_mode(item) for item in selected}
    if limit >= 4 and len(available_modes) >= 2 and len(selected_modes) < 2:
        replacement = _best_unselected_by_probe_mode(
            ordered,
            selected,
            context,
            avoid_axes=avoid_axes,
            modes=available_modes - selected_modes,
        )
        if replacement is not None:
            _replace_weakest_selected(
                selected,
                replacement,
                context,
                avoid_axes=avoid_axes,
                replace_modes=selected_modes,
            )

    return selected


def _select_diverse_candidates(
    candidates: list[SpeculativeInterest],
    *,
    limit: int,
    existing: list[SpeculativeInterest] | None = None,
    feedback_history: object | None = None,
) -> list[SpeculativeInterest]:
    if limit <= 0 or not candidates:
        return []
    if len(candidates) <= limit:
        return list(candidates)

    ordered = sorted(
        candidates,
        key=lambda item: (float(item.confidence), float(item.weight)),
        reverse=True,
    )
    context = list(existing or [])
    avoid_axes = _negative_probe_feedback_axes(feedback_history)
    selected: list[SpeculativeInterest] = []

    if not any(item.entry_load == "light" for item in context):
        light_pick = _pick_best_candidate(
            ordered,
            context + selected,
            lambda item: item.entry_load == "light",
            avoid_axes=avoid_axes,
        )
        if light_pick is not None:
            selected.append(light_pick)

    if not any(
        item.experience_mode and item.experience_mode != "knowledge" for item in context + selected
    ):
        non_knowledge_pick = _pick_best_candidate(
            ordered,
            context + selected,
            lambda item: item.experience_mode and item.experience_mode != "knowledge",
            avoid_axes=avoid_axes,
        )
        if non_knowledge_pick is not None:
            selected.append(non_knowledge_pick)

    while len(selected) < limit:
        remaining = [candidate for candidate in ordered if candidate not in selected]
        if not remaining:
            break
        selected.append(
            max(
                remaining,
                key=lambda candidate: _candidate_priority(
                    candidate,
                    context + selected,
                    avoid_axes=avoid_axes,
                ),
            )
        )
    return _apply_probe_mode_quotas(
        ordered,
        selected[:limit],
        limit=limit,
        context=context,
        avoid_axes=avoid_axes,
    )


def _select_candidates_for_probe_slots(
    candidates: list[SpeculativeInterest],
    *,
    near_limit: int,
    challenge_limit: int,
    existing: list[SpeculativeInterest] | None = None,
    feedback_history: object | None = None,
) -> list[SpeculativeInterest]:
    selected: list[SpeculativeInterest] = []
    context = list(existing or [])

    if near_limit > 0:
        near_candidates = [
            candidate
            for candidate in candidates
            if not _is_challenge_probe_mode(candidate.probe_mode)
        ]
        selected.extend(
            _select_diverse_candidates(
                near_candidates,
                limit=near_limit,
                existing=context,
                feedback_history=feedback_history,
            )
        )

    if challenge_limit > 0:
        challenge_candidates = [
            candidate for candidate in candidates if _is_challenge_probe_mode(candidate.probe_mode)
        ]
        selected.extend(
            _select_diverse_candidates(
                challenge_candidates,
                limit=challenge_limit,
                existing=context + selected,
                feedback_history=feedback_history,
            )
        )

    return selected


def build_probe_axis(*, experience_mode: Any, entry_load: Any) -> str:
    mode = _normalize_experience_mode(experience_mode)
    load = _normalize_entry_load(entry_load)
    if not mode and not load:
        return ""
    return f"{mode}|{load}"


def choose_next_probe_candidate(
    specs: list[Any],
    *,
    probed_domains: set[str] | None = None,
    probed_axes: set[str] | None = None,
    probed_probe_modes: set[str] | None = None,
    feedback_history: object | None = None,
) -> Any | None:
    recent_domains = probed_domains or set()
    recent_axes = probed_axes or set()
    recent_probe_modes = {_normalize_probe_mode(mode) for mode in (probed_probe_modes or set())}
    negative_domains = _negative_probe_feedback_domains(feedback_history)
    negative_axes = _negative_probe_feedback_axes(feedback_history)
    candidates = []
    for candidate in specs:
        if str(getattr(candidate, "status", "active")).strip().lower() != "active":
            continue
        domain = str(getattr(candidate, "domain", "")).strip().lower()
        if not domain or domain in recent_domains:
            continue
        if any(_has_probe_term_overlap(domain, term) for term in negative_domains):
            continue
        candidates.append(candidate)
    if not candidates:
        return None

    min_confirmation = min(
        int(getattr(candidate, "confirmation_count", 0) or 0) for candidate in candidates
    )
    same_pressure = [
        candidate
        for candidate in candidates
        if int(getattr(candidate, "confirmation_count", 0) or 0) == min_confirmation
    ]
    fresh_axis = [
        candidate
        for candidate in same_pressure
        if (
            axis := build_probe_axis(
                experience_mode=getattr(candidate, "experience_mode", ""),
                entry_load=getattr(candidate, "entry_load", ""),
            )
        )
        and axis not in recent_axes
    ]
    axis_pool = fresh_axis or same_pressure
    fresh_probe_mode = [
        candidate
        for candidate in axis_pool
        if _normalize_probe_mode(getattr(candidate, "probe_mode", "")) not in recent_probe_modes
    ]
    pool = fresh_probe_mode or axis_pool
    return max(
        pool,
        key=lambda candidate: (
            build_probe_axis(
                experience_mode=getattr(candidate, "experience_mode", ""),
                entry_load=getattr(candidate, "entry_load", ""),
            )
            not in negative_axes,
            _normalize_probe_mode(getattr(candidate, "probe_mode", "")) not in recent_probe_modes,
            float(getattr(candidate, "weight", 0.0) or 0.0),
            float(getattr(candidate, "confidence", 0.0) or 0.0),
        ),
    )
