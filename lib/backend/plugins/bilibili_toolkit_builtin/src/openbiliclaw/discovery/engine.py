"""内容发现引擎。

协调多个发现策略，找到与用户 soul profile
匹配的内容。
"""

from __future__ import annotations

import asyncio
import contextvars
import inspect
import logging
import re
import time
from abc import ABC, abstractmethod
from collections import Counter
from contextlib import suppress
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, TypeVar, cast

from openbiliclaw.discovery.strategies._utils import build_profile_summary
from openbiliclaw.discovery.style_keys import VALID_STYLE_KEYS, normalize_style_key
from openbiliclaw.llm.json_utils import extract_llm_json_list, parse_llm_json_tolerant
from openbiliclaw.llm.prompt_cache import (
    PromptLayerRenderCache,
    profile_prompt_layers,
    stable_json_digest,
)
from openbiliclaw.llm.service import is_llm_rate_limit_error
from openbiliclaw.llm.task_options import without_core_memory_kwargs

if TYPE_CHECKING:
    from collections.abc import Awaitable, Sequence

    from openbiliclaw.llm.embedding import SupportsEmbeddingService
    from openbiliclaw.soul.profile import SoulProfile
    from openbiliclaw.storage.database import Database

logger = logging.getLogger(__name__)
_T = TypeVar("_T")
_EVALUATE_BATCH_HARD_CAP_DEFAULT: int = 90
_DEFAULT_EVAL_BATCH_SIZE: int = 45
_DEFAULT_EVAL_BATCH_CONCURRENCY: int = 2
_LLM_EVAL_OVERSAMPLE_FACTOR: int = 2
_LLM_EVAL_MIN_WINDOW: int = 6
_RAW_CANDIDATE_MODE: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "openbiliclaw_discovery_raw_candidate_mode",
    default=False,
)
_EVAL_PROFILE_CORE_CAP = 20
_EVAL_PROFILE_INTEREST_CAP = 64
_EVAL_PROFILE_DOMAIN_CAP = 32
_EVAL_PROFILE_SPECIFICS_PER_DOMAIN_CAP = 12
_EVAL_PROFILE_RECENT_CAP = 12
_EVAL_PROFILE_EVIDENCE_CAP = 8
_EVAL_PROFILE_SPECULATION_CAP = 12
_EVAL_BATCH_CACHE_VERSION = "batch-content-eval-v1"
_NEGATIVE_EXAMPLES_UNSET = object()


def discovery_raw_candidate_mode_enabled() -> bool:
    """返回当前协程是否应该跳过 LLM 评估直接拉取。"""

    return bool(_RAW_CANDIDATE_MODE.get())


def compact_evaluation_profile_summary(profile_summary: dict[str, object]) -> dict[str, object]:
    """返回更小的 profile 摘要，用于大批量候选评估。

    发现评估会为每个批次付出完整的 profile prompt 成本。保留信号最强的
    兴趣以及最新的 awareness/insight 窗口，同时保留
    ``disliked_topics`` 等硬性负样本不变。
    """

    compacted = dict(profile_summary)
    for key in ("core_traits", "cognitive_style", "values", "motivational_drivers", "deep_needs"):
        compacted[key] = _cap_profile_sequence(
            profile_summary.get(key),
            _EVAL_PROFILE_CORE_CAP,
        )
    compacted["interests"] = _cap_weighted_profile_dicts(
        profile_summary.get("interests"),
        _EVAL_PROFILE_INTEREST_CAP,
    )
    compacted["interest_domains"] = _compact_interest_domains(
        profile_summary.get("interest_domains"),
    )
    compacted["recent_awareness"] = _cap_profile_sequence(
        profile_summary.get("recent_awareness"),
        _EVAL_PROFILE_RECENT_CAP,
        newest=True,
    )
    compacted["active_insights"] = _compact_active_insights(
        profile_summary.get("active_insights"),
    )
    compacted["speculative_interests"] = _cap_profile_sequence(
        profile_summary.get("speculative_interests"),
        _EVAL_PROFILE_SPECULATION_CAP,
    )
    return compacted


def evaluation_profile_prompt_layers(
    profile_summary: dict[str, object],
) -> list[tuple[str, dict[str, object]]]:
    """将评估 profile 的 prompt 输入从最稳定到最易变进行分层。"""
    return profile_prompt_layers(profile_summary)


def _cap_profile_sequence(value: object, cap: int, *, newest: bool = False) -> object:
    if not isinstance(value, list):
        return value if value is not None else []
    if len(value) <= cap:
        return list(value)
    return list(value[-cap:] if newest else value[:cap])


def _profile_weight(value: object) -> float:
    if not isinstance(value, dict):
        return 0.0
    try:
        return float(value.get("weight", 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _cap_weighted_profile_dicts(value: object, cap: int) -> list[object]:
    if not isinstance(value, list):
        return []
    return sorted(list(value), key=_profile_weight, reverse=True)[:cap]


def _compact_interest_domains(value: object) -> list[object]:
    if not isinstance(value, list):
        return []
    domains = _cap_weighted_profile_dicts(value, _EVAL_PROFILE_DOMAIN_CAP)
    compacted: list[object] = []
    for domain in domains:
        if not isinstance(domain, dict):
            compacted.append(domain)
            continue
        item = dict(domain)
        specifics = item.get("specifics")
        item["specifics"] = _cap_weighted_profile_dicts(
            specifics,
            _EVAL_PROFILE_SPECIFICS_PER_DOMAIN_CAP,
        )
        compacted.append(item)
    return compacted


def _compact_active_insights(value: object) -> list[object]:
    if not isinstance(value, list):
        return []
    insights = list(value[-_EVAL_PROFILE_RECENT_CAP:])
    compacted: list[object] = []
    for insight in insights:
        if not isinstance(insight, dict):
            compacted.append(insight)
            continue
        item = dict(insight)
        evidence = item.get("evidence")
        if isinstance(evidence, list):
            item["evidence"] = list(evidence[:_EVAL_PROFILE_EVIDENCE_CAP])
        compacted.append(item)
    return compacted


@dataclass
class DiscoveryConcurrencyController:
    """用于发现外部依赖的共享有界并发控制。"""

    bilibili_request_concurrency: int = 2
    # 同时进行的发现 LLM 调用上限。规模设置使得一次典型的初始化
    # 发现 (4 策略 × ~8 批次 = ~32 批次) 能在一波内展开，
    # 而不是排在 cap 后面。每批是一次 max-thinking deepseek 调用
    # (~60-100s)；如果没有足够的并发，我们会把整个 P4 预算
    # 花在等信号量上 (在 40 批次 concurrency=8 时观测到 17 分钟
    # wall 时间，其中每批只有 ~100s 是实际 LLM 计算)。
    # deepseek 在我们的请求大小下没有有效的 RPM 上限，所以
    # 实际的限制只有本地事件循环开销和 ``chat_active`` 让步
    # (仍然能让交互式对话优先)。
    llm_evaluation_concurrency: int = 32
    search_budget_total: int = 30
    """每次发现运行允许的 B站 搜索 API 调用总数。

    预算在使用搜索的策略 (search、explore、related_chain) 之间
    平均分配，以防止任何单一策略耗尽 IP 层级的速率限制。
    """
    _search_strategy_count: int = field(init=False, default=3, repr=False)
    _loop: asyncio.AbstractEventLoop | None = field(init=False, default=None, repr=False)
    _bilibili_semaphore: asyncio.Semaphore | None = field(init=False, default=None, repr=False)
    _llm_semaphore: asyncio.Semaphore | None = field(init=False, default=None, repr=False)

    @property
    def search_budget_per_strategy(self) -> int:
        """搜索 API 预算的每策略份额。"""
        return max(1, self.search_budget_total // max(1, self._search_strategy_count))

    def _ensure_loop_bound(self) -> None:
        """当 controller 在新的事件循环中使用时重建信号量。"""
        loop = asyncio.get_running_loop()
        if self._loop is loop:
            return
        self._loop = loop
        self._bilibili_semaphore = asyncio.Semaphore(max(1, self.bilibili_request_concurrency))
        self._llm_semaphore = asyncio.Semaphore(max(1, self.llm_evaluation_concurrency))

    async def run_bilibili(self, awaitable: Awaitable[_T]) -> _T:
        """在请求限制内运行一个面向 B站 的 awaitable。"""
        self._ensure_loop_bound()
        assert self._bilibili_semaphore is not None
        async with self._bilibili_semaphore:
            return await awaitable

    chat_active: bool = False
    llm_throttle_seconds: float = 0.0
    """连续发现 LLM 调用之间的最小延迟。

    对于 deepseek 保持在 0，因为它在我们的请求大小下没有
    有效的 RPM 上限。当对接有严格 RPM 上限的 provider 时
    (例如 Gemini 免费层 15 RPM)，应提升到 0 以上。
    ``chat_active`` 标志已经在对话进行时让出通道，所以
    在 deepseek 上不再需要节流来保护对话。
    """

    async def run_llm(self, awaitable: Awaitable[_T]) -> _T:
        """在评估限制内运行一个面向 LLM 的 awaitable。

        当 ``chat_active`` 为 True (用户对话进行中) 时，
        发现 LLM 调用会让步直到对话完成。这能防止发现
        占满 LLM API 的 RPM 配额并饿死交互式 chat 请求。
        """
        while self.chat_active:
            await asyncio.sleep(0.5)
        self._ensure_loop_bound()
        assert self._llm_semaphore is not None
        async with self._llm_semaphore:
            result = await awaitable
            # 节流：间隔发现 LLM 调用以避免 RPM 耗尽
            if self.llm_throttle_seconds > 0:
                await asyncio.sleep(self.llm_throttle_seconds)
            return result


class SupportsStructuredTask(Protocol):
    async def complete_structured_task(
        self,
        *,
        system_instruction: str,
        user_input: str,
        history: list[dict[str, str]] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        caller: str = "",
        reasoning_effort: str | None = None,
        inject_core_memory: bool = True,
    ) -> object: ...


class SupportsNegativeExemplarStore(Protocol):
    """负锚点缓存失效所需的存储接口。"""

    def get_latest_event_id(self) -> int | None: ...

    def query_events(
        self,
        *,
        satisfaction_modes: frozenset[str] | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]: ...


def llm_eval_candidate_limit(limit: int) -> int:
    """返回请求结果限制对应的 LLM 前候选窗口大小。"""
    safe_limit = max(1, int(limit))
    return min(
        _EVALUATE_BATCH_HARD_CAP_DEFAULT,
        max(_LLM_EVAL_MIN_WINDOW, safe_limit * _LLM_EVAL_OVERSAMPLE_FACTOR),
    )


def trim_candidates_for_llm(
    candidates: Sequence[_T],
    *,
    limit: int,
    source_context: str,
) -> list[_T]:
    """保留有界的 LLM 前候选窗口，同时保留上游顺序。"""
    eval_limit = llm_eval_candidate_limit(limit)
    if len(candidates) <= eval_limit:
        return list(candidates)
    logger.info(
        "%s: trimming LLM eval candidates from %d to %d (result_limit=%d)",
        source_context,
        len(candidates),
        eval_limit,
        limit,
    )
    return list(candidates[:eval_limit])


def _parse_batch_evaluation_payload(raw: str) -> list[dict[str, Any]] | None:
    """从 provider 响应中提取已打分的结果数组。"""
    payload = extract_llm_json_list(
        raw,
        wrapper_keys=("results", "items", "evaluations", "scores", "data"),
        allow_singleton=True,
        item_predicate=lambda item: "score" in item,
    )
    if payload is None:
        parsed = parse_llm_json_tolerant(raw)
        if isinstance(parsed, dict):
            mapped_payload: list[dict[str, Any]] = []
            for key, value in parsed.items():
                if not isinstance(value, dict) or "score" not in value:
                    continue
                item = dict(value)
                identifier = str(key).strip()
                if identifier:
                    item.setdefault("content_id", identifier)
                    if identifier.startswith("BV"):
                        item.setdefault("bvid", identifier)
                mapped_payload.append(item)
            if mapped_payload:
                return mapped_payload
        return None
    return [dict(item) for item in payload]


def _content_result_keys(content: DiscoveredContent) -> set[str]:
    """在批量 LLM 结果中可能用于标识内容条目的稳定 key。"""
    return {
        key
        for key in {
            str(getattr(content, "bvid", "") or "").strip(),
            str(getattr(content, "content_id", "") or "").strip(),
        }
        if key
    }


_PROMPT_VISIBLE_METRIC_FIELDS: tuple[str, ...] = (
    "view_count",
    "like_count",
    "favorite_count",
    "collect_count",
    "comment_count",
    "share_count",
    "danmaku_count",
    "reply_count",
    "retweet_count",
    "bookmark_count",
)


def _prompt_visible_content_fields(content: DiscoveredContent) -> dict[str, object]:
    fields: dict[str, object] = {
        field_name: int(getattr(content, field_name, 0) or 0)
        for field_name in _PROMPT_VISIBLE_METRIC_FIELDS
    }
    fields["tags"] = list(getattr(content, "tags", []) or [])
    return fields


def _normalize_prompt_text_for_dedupe(value: str) -> str:
    return re.sub(r"\s+", "", value).strip()


def _prompt_description_for_content(
    content: DiscoveredContent,
    *,
    limit: int | None = None,
) -> str:
    description = str(content.description or "")
    if limit is not None:
        description = description[:limit]
    desc_key = _normalize_prompt_text_for_dedupe(description)
    body_key = _normalize_prompt_text_for_dedupe(str(content.body_text or ""))
    if desc_key and body_key.startswith(desc_key):
        return ""
    return description


def _batch_results_by_content_key(
    payload: list[dict[str, Any]],
    batch: list[DiscoveredContent],
) -> dict[str, dict[str, Any]] | None:
    """当 LLM 提供 ID 时，返回按 content ID 索引的 payload 条目。"""
    valid_keys: set[str] = set()
    for content in batch:
        valid_keys.update(_content_result_keys(content))

    matched: dict[str, dict[str, Any]] = {}
    saw_identifier = False
    for item in payload:
        raw_key = str(item.get("bvid") or item.get("content_id") or "").strip()
        if not raw_key:
            continue
        saw_identifier = True
        if raw_key not in valid_keys:
            continue
        matched[raw_key] = item

    return matched if saw_identifier else None


@dataclass
class DiscoveredContent:
    """由引擎发现的一条内容。"""

    bvid: str = ""  # Bilibili 视频 ID (旧字段；新代码请优先用 content_id)
    title: str = ""
    up_name: str = ""  # UP主名称 (旧字段；新代码请优先用 author_name)
    up_mid: int = 0  # UP主 ID
    cover_url: str = ""
    duration: int = 0  # 秒
    view_count: int = 0
    like_count: int = 0
    favorite_count: int = 0
    collect_count: int = 0
    comment_count: int = 0
    share_count: int = 0
    danmaku_count: int = 0
    reply_count: int = 0
    retweet_count: int = 0
    bookmark_count: int = 0
    tags: list[str] = field(default_factory=list)
    topic_key: str = ""
    topic_group: str = ""  # 粗粒度语义类别 (例如 "强化学习")，用于多样性
    style_key: str = ""
    # 在评估时由 LLM 标注的 Franchise / IP / 系列 key
    # (例如 "原神"、"崩坏:星穹铁道"、"ChatGPT"、"塞尔达传说")。
    # 普适兴趣内容为空。让 curator 在一次 dislike 后降权同一 IP
    # 的条目，并让 ``/api/recommendations`` 端点限制单个响应窗口
    # 中同 franchise 条目的数量。比启发式的标题子串方法更好
    # (v0.3.17 曾短暂尝试过)，因为 LLM 已经看到标题 + 描述 + topic，
    # 即使标题是双语或编码过的也能正确推断 IP
    # ("提瓦特摄影" → 原神, "宝可梦" → 精灵宝可梦, 等等)。
    franchise_key: str = ""
    description: str = ""
    source_strategy: str = ""  # 哪个策略发现了这条内容
    relevance_score: float = 0.0  # 0.0 - 1.0 (基于用户 soul)
    relevance_reason: str = ""  # 为什么这条内容与用户相关
    pool_expression: str = ""  # 预计算的推荐文案，用于快速弹窗路径
    pool_topic_label: str = ""  # 预计算的个性化 topic 标签，用于快速弹窗路径
    candidate_tier: str = "primary"  # 主发现 vs 补给 backfill
    discovered_at: str = ""  # 缓存时间戳，用于感知时效性的排序
    last_scored_at: str = ""  # 最后一次相关性打分时间戳

    # ── 多来源字段 (Phase 0) ───────────────────────────────
    content_id: str = ""  # 通用 content ID；对 Bilibili 内容等于 bvid
    content_url: str = ""  # 直接可点击的 URL
    source_platform: str = ""  # "bilibili" | "xiaohongshu" | "web" | ...
    author_name: str = ""  # 通用作者名；对 Bilibili 等于 up_name
    score_threshold: float = 0.0  # 策略特定的原始候选准入下限
    body_text: str = ""  # tweet/thread 全文；视频来源为空
    content_type: str = "video"  # 形态: "video" | "note" | "tweet" | "thread"
    # P1.8 yield provenance: 产生此条目的搜索词的 ``discovery_keywords.id``
    # (统一 keyword planner)。对于所有非搜索 / 旧版本 / flag 关闭路径
    # 为 ``None`` —— 此时 admit 时 yield 回填是 no-op，所以归因保持
    # 可选且字节兼容。
    source_keyword_id: int | None = None

    def __post_init__(self) -> None:
        if not self.content_id and self.bvid:
            self.content_id = self.bvid
        if not self.source_platform and self.bvid:
            self.source_platform = "bilibili"
        if not self.author_name and self.up_name:
            self.author_name = self.up_name
        if not self.content_url and self.bvid:
            self.content_url = f"https://www.bilibili.com/video/{self.bvid}"

    def to_cache_kwargs(self) -> dict[str, object]:
        """构建 ``Database.cache_content()`` 的 kwargs 字典。

        DiscoveredContent → content_cache 字段映射的单一真相来源。
        被发现的 ``_cache_results`` 和推荐引擎的
        ``classify_pool_backlog`` 持久化循环使用。
        """
        return {
            "title": self.title,
            "up_name": self.up_name,
            "up_mid": self.up_mid,
            "duration": self.duration,
            "tags": self.tags,
            "topic_key": self.topic_key,
            "topic_group": self.topic_group,
            "style_key": self.style_key,
            "franchise_key": self.franchise_key,
            "description": self.description,
            "cover_url": self.cover_url,
            "view_count": self.view_count,
            "like_count": self.like_count,
            "favorite_count": self.favorite_count,
            "collect_count": self.collect_count,
            "comment_count": self.comment_count,
            "share_count": self.share_count,
            "danmaku_count": self.danmaku_count,
            "reply_count": self.reply_count,
            "retweet_count": self.retweet_count,
            "bookmark_count": self.bookmark_count,
            "relevance_score": self.relevance_score,
            "relevance_reason": self.relevance_reason,
            "candidate_tier": self.candidate_tier,
            "source": self.source_strategy,
            "source_platform": self.source_platform or "bilibili",
            "content_id": self.content_id or self.bvid,
            "content_url": self.content_url,
            "author_name": self.author_name or self.up_name,
            "body_text": self.body_text,
            "content_type": self.content_type,
            "source_keyword_id": self.source_keyword_id,
        }


# v0.3.50+: ``_evaluate_batch`` 的每批次 franchise 上限。LLM
# 能正确识别一个批次中是否有大量同 IP 条目 (prompt 强制要求
# 批次内 franchise 一致性)，但 v0.3.50 之前我们全保留并让
# serve() 的多样化器去处理 —— 而到那时 pool 已经 franchise
# 倾斜了。Cap=4 让一个系列在每轮刷新中能有小幅立足点，但
# 阻止单次 ``related_chain`` 探索把同一 UP 的 13 条内容
# 倒进一个批次。
_BATCH_FRANCHISE_CAP: int = 4

# v0.3.51+: 每批次 style 上限。镜像上面的 franchise 上限 ——
# 没有它，单个 eval_batch 轻易就有 9-12 条同 style 内容
# (mood_release / story_immersion / social_chat / hands_on
# 在生产中都观测到 30-40% 浓度)。8/30 = ~27% 仍能让主导
# style 喘息，但阻止单一 style 称霸 pool。
_BATCH_STYLE_CAP: int = 8

# v0.3.50+: ``_cache_results`` 的 pool 级 franchise 配额。一旦
# 一个 franchise 在 pool 中已有这么多条目，新的同 franchise
# 条目会在它们竞争 serve() 槽位前被跳过。规模约为默认 pool
# 目标 (600) 的 ~1.5%，所以 9-10 条对用户主动追的系列来说
# 是足够的呼吸空间，但不足以扭曲整个 pool 的调性。
_POOL_FRANCHISE_QUOTA: int = 10

# v0.3.50+: 单次 related_chain 深度轮次内的每 UP 上限。
# 没有它，related_chain 跟随单个种子可能扇出同一 UP 的
# 13+ 条 (张雪机车 是生产触发案例)。
_RELATED_CHAIN_PER_UP_CAP: int = 3


class DiscoveryStrategy(ABC):
    """内容发现策略的基类。"""

    @property
    @abstractmethod
    def name(self) -> str:
        """策略名。"""
        ...

    @abstractmethod
    async def discover(self, profile: SoulProfile, limit: int = 20) -> list[DiscoveredContent]:
        """执行发现策略。

        Args:
            profile: 当前用户 soul profile，用于相关性引导。
            limit: 最多返回的条目数。

        Returns:
            发现的内容条目列表。
        """
        ...

    def create_backfill_strategy(self) -> DiscoveryStrategy | None:
        """如果支持，返回一个扩展/放宽的补给变体。"""
        return None


def _strategy_declares_param(fn: Any, name: str) -> bool:
    """返回策略 discover 可调用对象是否显式声明了 ``name`` 参数。"""
    try:
        signature = inspect.signature(fn)
    except (TypeError, ValueError):
        return False
    return name in signature.parameters


def _strategy_accepts_kwarg(fn: Any, name: str) -> bool:
    """返回策略 discover 可调用对象是否接受关键字 ``name``。"""
    try:
        signature = inspect.signature(fn)
    except (TypeError, ValueError):
        return True
    return name in signature.parameters or any(
        param.kind is inspect.Parameter.VAR_KEYWORD for param in signature.parameters.values()
    )


def _injected_keyword_kwarg(fn: Any) -> str | None:
    """返回统一 planner 注入词应该转发到的 kwarg 名称。

    真正的搜索子策略 (B站 ``SearchStrategy``、``XSearchStrategy``、
    ``YoutubeSearchStrategy``) 都读取一个显式的 ``queries`` 参数 ——
    而不是 ``keywords`` —— 所以引擎必须按策略实际声明的名字
    转发注入词，否则注入是静默 no-op (词被认领 + 标记 ``used``
    但搜索从未看到它)。优先顺序：

    1. 显式 ``queries`` 参数 (每个真正的搜索策略),
    2. 显式 ``keywords`` 参数 (旧/备用签名 + fake),
    3. 可调用对象只声明 ``**kwargs`` 时用 ``keywords`` (旧契约),
    4. ``None`` → 策略不接受注入词 (非搜索子策略)。
    """
    if _strategy_declares_param(fn, "queries"):
        return "queries"
    if _strategy_declares_param(fn, "keywords"):
        return "keywords"
    if _strategy_accepts_kwarg(fn, "keywords"):
        return "keywords"
    return None


def _strategy_accepts_pool_snapshot(fn: Any) -> bool:
    """返回策略 discover 可调用对象是否接受 ``pool_snapshot=``。"""
    return _strategy_accepts_kwarg(fn, "pool_snapshot")


def _strategy_accepts_keyword_ids(fn: Any) -> bool:
    """返回策略 discover 可调用对象是否声明了 ``keyword_ids=``。

    P1.8 yield provenance: 选择加入的搜索子策略声明一个显式
    ``keyword_ids`` 参数 (一个 ``keyword text → discovery_keywords.id`` 映射)
    并在其每关键词循环中为每条产出的条目打上 ``source_keyword_id``。
    我们只把映射转发给显式声明它的可调用对象 —— 绝不通过
    ``**kwargs`` —— 这样非搜索策略 + fake 保持字节一致。
    """
    return _strategy_declares_param(fn, "keyword_ids")


async def _call_strategy_discover(
    strategy: DiscoveryStrategy,
    profile: SoulProfile,
    *,
    limit: int,
    pool_snapshot: Any | None,
    keywords: list[str] | None = None,
    keyword_ids: dict[str, int] | None = None,
) -> list[DiscoveredContent]:
    discover_fn: Any = strategy.discover
    kwargs: dict[str, Any] = {"limit": limit}
    if _strategy_accepts_pool_snapshot(discover_fn):
        kwargs["pool_snapshot"] = pool_snapshot
    # 只有当调用方提供了关键词且策略实际接受时才转发注入词 ——
    # 用策略声明的名字 (真正的搜索策略读 ``queries``，不是 ``keywords``)。
    # 非搜索子策略两者都不声明，所以它们保持字节一致。
    if keywords is not None:
        inject_kwarg = _injected_keyword_kwarg(discover_fn)
        if inject_kwarg is not None:
            kwargs[inject_kwarg] = keywords
    # P1.8: 转发并行的 keyword→id 映射用于 yield 归因，但只转发给
    # 显式选择加入 (声明 ``keyword_ids``) 的策略。flag 关闭 /
    # 未注入的调用方传 ``None`` → 永不转发 → 不会打标。
    if keyword_ids and _strategy_accepts_keyword_ids(discover_fn):
        kwargs["keyword_ids"] = keyword_ids
    return cast("list[DiscoveredContent]", await discover_fn(profile, **kwargs))


class ContentDiscoveryEngine:
    """编排多个发现策略。

    可用策略:
    - Search: 基于关键词的搜索，关键词来自用户兴趣
    - Related: 跟随相关推荐链
    - Trending: 扫描 trending/排行内容
    - Comments: 从评论区挖掘推荐
    - UPTrack: 追踪关注/发现的 UP主
    - Explore: 跨域惊喜发现
    """

    def __init__(
        self,
        llm_service: SupportsStructuredTask | None = None,
        database: Database | None = None,
        *,
        concurrency: DiscoveryConcurrencyController | None = None,
        embedding_service: SupportsEmbeddingService | None = None,
        target_primary_count: int = 20,
        backfill_target_count: int = 40,
        multimodal_evaluation_enabled: bool = False,
        multimodal_batch_size: int = 8,
        multimodal_image_max_px: int = 384,
        multimodal_image_quality: int = 72,
        multimodal_image_timeout_seconds: int = 6,
        multimodal_vision_supported: bool | None = None,
        eval_batch_concurrency: int = _DEFAULT_EVAL_BATCH_CONCURRENCY,
    ) -> None:
        self._strategies: list[DiscoveryStrategy] = []
        self._llm_service = llm_service
        self._database = database
        self._concurrency = concurrency
        self._embedding_service = embedding_service
        self._target_primary_count = max(1, target_primary_count)
        self._backfill_target_count = max(self._target_primary_count, backfill_target_count)
        self.multimodal_evaluation_enabled = bool(multimodal_evaluation_enabled)
        self.multimodal_batch_size = max(1, min(12, int(multimodal_batch_size)))
        self.multimodal_image_max_px = max(128, min(768, int(multimodal_image_max_px)))
        self.multimodal_image_quality = max(40, min(90, int(multimodal_image_quality)))
        self.multimodal_image_timeout_seconds = max(
            1,
            min(20, int(multimodal_image_timeout_seconds)),
        )
        self.eval_batch_concurrency = max(1, min(16, int(eval_batch_concurrency)))
        self._multimodal_vision_supported_override = multimodal_vision_supported
        self.multimodal_unavailable_reason = ""
        self._eval_cache: dict[str, tuple[float, str, str, str, str]] = {}
        self._evaluation_profile_prompt_cache = PromptLayerRenderCache()
        # v0.3.x 负锚点缓存: (timestamp, latest_event_id,
        # exemplars)。当 latest event id 变化 (新负样本被分类)
        # 或 5 分钟过去时刷新。
        self._negative_exemplars_cache: tuple[float, int | None, list[dict[str, object]]] | None = (
            None
        )

    def _supports_multimodal_evaluation(self) -> bool:
        override = getattr(self, "_multimodal_vision_supported_override", None)
        if override is not None:
            return bool(override)
        service = self._llm_service
        if service is None:
            return False
        for attr in ("supports_image_input", "supports_vision"):
            value = getattr(service, attr, None)
            if callable(value):
                with suppress(Exception):
                    return bool(value())
            if value is not None:
                return bool(value)
        return callable(getattr(service, "complete_multimodal_structured_task", None))

    def _effective_eval_batch_size(
        self,
        contents: list[DiscoveredContent],
        requested_batch_size: int,
    ) -> int:
        batch_size = max(1, int(requested_batch_size))
        self.multimodal_unavailable_reason = ""
        if not bool(getattr(self, "multimodal_evaluation_enabled", False)):
            return batch_size
        if not any((content.cover_url or "").strip() for content in contents):
            return batch_size
        if not self._supports_multimodal_evaluation():
            self.multimodal_unavailable_reason = (
                "Current evaluation model is not vision-capable; using text-only evaluation."
            )
            return batch_size
        return min(batch_size, int(getattr(self, "multimodal_batch_size", 8)))

    def _effective_eval_batch_concurrency(self) -> int:
        try:
            configured = int(
                getattr(
                    self,
                    "eval_batch_concurrency",
                    _DEFAULT_EVAL_BATCH_CONCURRENCY,
                )
            )
        except (TypeError, ValueError):
            configured = _DEFAULT_EVAL_BATCH_CONCURRENCY
        return max(1, min(16, configured))

    def register_strategy(self, strategy: DiscoveryStrategy) -> None:
        """注册一个发现策略。"""
        self._strategies = [item for item in self._strategies if item.name != strategy.name]
        self._strategies.append(strategy)
        logger.info("Registered discovery strategy: %s", strategy.name)

    def register_adapter(self, adapter: Any) -> None:
        """注册一个 :class:`SourceAdapter` 用于多源发现。

        adapter 按 ``source_type`` 存入 ``_adapter_registry``。
        Phase 2+ 会在 recipe 驱动的发现周期中使用它。
        """
        if not hasattr(self, "_adapter_registry"):
            from openbiliclaw.sources.registry import AdapterRegistry

            self._adapter_registry = AdapterRegistry()
        self._adapter_registry.register(adapter)

    @property
    def adapter_registry(self) -> Any:
        """返回 adapter 注册表，按需懒创建。"""
        if not hasattr(self, "_adapter_registry"):
            from openbiliclaw.sources.registry import AdapterRegistry

            self._adapter_registry = AdapterRegistry()
        return self._adapter_registry

    async def discover(
        self,
        profile: SoulProfile,
        strategies: list[str] | None = None,
        limit: int = 30,
        *,
        fully_parallel: bool = False,
        strategy_limits: dict[str, int] | None = None,
        pool_snapshot: Any | None = None,
        keywords: list[str] | None = None,
        keyword_ids: dict[str, int] | None = None,
    ) -> list[DiscoveredContent]:
        """用选定 (或全部) 策略运行发现。

        Args:
            profile: 用户 soul profile，用于相关性评估。
            strategies: 可选的要运行的策略名列表。
                       如果为 None，运行所有已注册策略。
            fully_parallel: 为 True 时跳过默认的两阶段拆分
                (先搜索再其他)，把每个策略放进单个
                ``asyncio.gather`` 中运行。速率限制仍然生效 ——
                ``bilibili_request_concurrency`` 限制同时 HTTP
                请求，``search_budget_total`` 限制总搜索调用 ——
                所以这只牺牲两阶段之间 2s 冷却。用于延迟敏感
                流程 (init bootstrap)。
            strategy_limits: 可选的每策略运行限制。最终的
                ``limit`` 仍限制返回/缓存结果数；这只是防止
                分组刷新给每个策略完整的平台缺口。
            pool_snapshot: 可选的当前 pool 分布摘要，供
                能使用 pool 感知发现指导的策略使用。
            keywords: 可选的调用方提供的搜索关键词，转发给
                接受 ``keywords`` kwarg 的搜索子策略 (统一
                keyword planner 注入点)。非搜索策略从不声明
                该 kwarg，所以不受影响。为 ``None`` 时，
                策略按之前一样自己生成关键词。
            keyword_ids: 可选的 ``keyword text → discovery_keywords.id``
                映射 (P1.8 yield provenance)，与 ``keywords`` 一起
                转发给声明 ``keyword_ids`` kwarg 的搜索子策略，这样
                每条产出的条目都打上产生它的词的 id。``None``
                保持路径无归因。

        Returns:
            合并、去重、打分后的发现内容列表。
        """
        active = self._strategies
        if strategies:
            active = [s for s in self._strategies if s.name in strategies]

        if not active:
            return []

        effective_limit = max(1, min(limit, self._backfill_target_count))
        primary_results = await self._run_strategies(
            active,
            profile=profile,
            limit=effective_limit,
            fully_parallel=fully_parallel,
            strategy_limits=strategy_limits,
            pool_snapshot=pool_snapshot,
            keywords=keywords,
            keyword_ids=keyword_ids,
        )
        # 在去重前用 embedding 归一化 topic_group
        merged_primary = self._merge_and_rank(primary_results)
        await self._normalize_topic_groups(merged_primary)
        await self._normalize_topic_keys(merged_primary)
        merged_primary = self._apply_pool_snapshot_rerank(merged_primary, pool_snapshot)
        final_results = self._compress_topic_repeats(
            merged_primary,
            limit=effective_limit,
        )

        primary_target = min(self._target_primary_count, effective_limit)
        if len(final_results) < primary_target:
            backfill_results = await self._run_backfill(
                active,
                profile=profile,
                limit=effective_limit,
                existing=final_results,
                pool_snapshot=pool_snapshot,
            )
            all_results = self._merge_and_rank([*final_results, *backfill_results])
            await self._normalize_topic_groups(all_results)
            await self._normalize_topic_keys(all_results)
            all_results = self._apply_pool_snapshot_rerank(all_results, pool_snapshot)
            final_results = self._compress_topic_repeats(
                all_results,
                limit=effective_limit,
            )

        self._cache_results(final_results)
        return final_results

    async def produce_candidates(
        self,
        profile: SoulProfile,
        strategies: list[str] | None = None,
        limit: int = 30,
        *,
        fully_parallel: bool = False,
        strategy_limits: dict[str, int] | None = None,
        pool_snapshot: Any | None = None,
        keywords: list[str] | None = None,
        keyword_ids: dict[str, int] | None = None,
    ) -> list[DiscoveredContent]:
        """拉取原始候选，不做 LLM 评估或 content_cache 写入。"""

        active = self._strategies
        if strategies:
            active = [s for s in self._strategies if s.name in strategies]
        if not active:
            return []

        effective_limit = max(1, min(limit, self._backfill_target_count))
        token = _RAW_CANDIDATE_MODE.set(True)
        try:
            raw_results = await self._run_strategies(
                active,
                profile=profile,
                limit=effective_limit,
                fully_parallel=fully_parallel,
                strategy_limits=strategy_limits,
                pool_snapshot=pool_snapshot,
                keywords=keywords,
                keyword_ids=keyword_ids,
            )
        finally:
            _RAW_CANDIDATE_MODE.reset(token)

        self._stamp_raw_candidate_thresholds(raw_results, active)
        return self._merge_duplicates(raw_results)[:effective_limit]

    @staticmethod
    def _stamp_raw_candidate_thresholds(
        results: list[DiscoveredContent],
        strategies: list[DiscoveryStrategy],
    ) -> None:
        thresholds: dict[str, float] = {}
        for strategy in strategies:
            threshold = float(getattr(strategy, "score_threshold", 0.0) or 0.0)
            if threshold > 0:
                thresholds[str(strategy.name).strip().lower()] = threshold
        if not thresholds:
            return
        for item in results:
            if float(item.score_threshold or 0.0) > 0:
                continue
            strategy_key = str(item.source_strategy or "").strip().lower()
            item_threshold = thresholds.get(strategy_key)
            if item_threshold is not None:
                item.score_threshold = item_threshold

    async def _normalize_topic_groups(
        self,
        results: list[DiscoveredContent],
    ) -> None:
        """通过 embedding 相似度给缺少 topic_group 的条目赋值。

        已有 topic_group 的条目按原样信任 —— 它们由 LLM 评估
        或策略级推断设置，已经是粗粒度标签。用 embedding 重新
        合并短中文标签会产生误报 (例如在阈值 0.82 时
        "国际史实" → "人工智能")，因为短文本 embedding 在
        余弦空间里欺骗性地接近。

        本方法只处理没有 topic_group 的条目，尝试把它们分配到
        来自有 topic_group 条目的现有簇中。
        """
        if self._embedding_service is None or not results:
            return

        from openbiliclaw.llm.embedding import cosine_similarity

        # 从已有 topic_group 的条目构建簇质心
        clusters: dict[str, list[float]] = {}
        for item in results:
            group = (item.topic_group or "").strip().lower()
            if not group or group in clusters:
                continue
            vec = await self._embedding_service.embed(group)
            if vec:
                clusters[group] = vec

        if not clusters:
            return

        # 只给没有 topic_group 的条目尝试赋值
        # 对短标签合并使用更严格的阈值
        threshold = min(0.92, self._embedding_service.similarity_threshold + 0.10)
        for item in results:
            if (item.topic_group or "").strip():
                continue
            topic = (item.topic_key or "").strip().lower()
            if not topic:
                continue
            vec = await self._embedding_service.embed(topic)
            if not vec:
                continue

            best_label: str | None = None
            best_sim = 0.0
            for label, centroid in clusters.items():
                sim = cosine_similarity(vec, centroid)
                if sim > best_sim:
                    best_sim = sim
                    best_label = label

            if best_label is not None and best_sim >= threshold:
                item.topic_group = best_label
                logger.debug(
                    "Topic assigned: %r → %r (sim=%.3f)",
                    topic,
                    best_label,
                    best_sim,
                )

    async def _normalize_topic_keys(
        self,
        results: list[DiscoveredContent],
    ) -> None:
        """通过 embedding 聚类归一化跨策略的 topic_keys。

        不同策略产生不同粒度的 topic_keys:
        - search: 细粒度 LLM 短语 ("moba经济曲线动态博弈")
        - trending/related_chain: B站 tname 类别 ("网络游戏")
        - explore: 域标签 ("精密机械钟表修复与微观结构")

        本方法将语义相似的 key 聚类并重新分配到规范代表，
        这样 _compress_topic_repeats 中的下游多样性逻辑能
        正确识别同 topic 条目。
        """
        if self._embedding_service is None or not results:
            return

        from openbiliclaw.llm.embedding import cosine_similarity

        # 第 1 步: 收集唯一 topic_keys 并 embedding
        unique_keys: list[str] = []
        seen: set[str] = set()
        for item in results:
            key = (item.topic_key or "").strip().lower()
            if key and key not in seen:
                seen.add(key)
                unique_keys.append(key)

        if len(unique_keys) <= 1:
            return

        # 对所有唯一 key 做 embedding
        key_vectors: dict[str, list[float]] = {}
        for key in unique_keys:
            vec = await self._embedding_service.embed(key)
            if vec:
                key_vectors[key] = vec

        if len(key_vectors) <= 1:
            return

        # 第 2 步: 贪心凝聚聚类
        threshold = self._embedding_service.similarity_threshold  # ~0.82
        clusters: list[tuple[str, list[str]]] = []

        for key, vec in key_vectors.items():
            best_cluster_idx: int | None = None
            best_sim = 0.0
            for idx, (canonical, _members) in enumerate(clusters):
                centroid = key_vectors.get(canonical)
                if centroid is None:
                    continue
                sim = cosine_similarity(vec, centroid)
                if sim > best_sim:
                    best_sim = sim
                    best_cluster_idx = idx

            if best_cluster_idx is not None and best_sim >= threshold:
                clusters[best_cluster_idx][1].append(key)
            else:
                clusters.append((key, [key]))

        # 第 3 步: 为每个簇选规范标签 (优先中等长度)
        canonical_map: dict[str, str] = {}  # original_key → canonical_key
        for _canonical, members in clusters:
            if len(members) <= 1:
                continue
            best_label = members[0]
            best_score = self._label_quality_score(members[0])
            for member in members[1:]:
                score = self._label_quality_score(member)
                if score > best_score:
                    best_score = score
                    best_label = member
            for member in members:
                if member != best_label:
                    canonical_map[member] = best_label

        if not canonical_map:
            return

        # 第 4 步: 在条目上重新赋值 topic_key
        for item in results:
            key = (item.topic_key or "").strip().lower()
            canonical_key = canonical_map.get(key)
            if canonical_key:
                logger.debug(
                    "Topic key normalized: %r → %r (strategy=%s)",
                    item.topic_key,
                    canonical_key,
                    item.source_strategy,
                )
                item.topic_key = canonical_key

    @staticmethod
    def _label_quality_score(label: str) -> float:
        """为用作规范代表的 topic 标签打分。

        优先中等长度 (4-8 字符) 的标签 —— 描述性足够
        但不过于具体。
        """
        length = len(label)
        if length <= 2:
            return 0.2
        if length <= 4:
            return 0.6
        if length <= 8:
            return 1.0
        if length <= 12:
            return 0.7
        return 0.4

    async def evaluate_content(
        self,
        content: DiscoveredContent,
        profile: SoulProfile,
        *,
        source_context: str = "",
    ) -> float:
        """评估一条内容对用户的相关性。

        核心评估基于用户的 Soul —— 他们的深层人格和兴趣 ——
        而不是表面指标。

        Args:
            content: 要评估的内容。
            profile: 用户的 soul profile。
            source_context: 发现上下文提示，用于校准评估，
                例如 "search_query: 纪录片 原理" 或 "explore_domain: 城市建筑叙事"。

        Returns:
            相关性得分 (0.0 - 1.0)。
        """
        if self._llm_service is None:
            return 0.0

        # 检查评估缓存 (相同内容身份 + 相同 profile → 相同得分)
        cache_key = f"{self._content_identity(content)}:{id(profile)}"
        cached = self._eval_cache.get(cache_key)
        if cached is not None:
            score, reason, topic_group, style_key, franchise_key = cached
            style_key = normalize_style_key(style_key)
            content.relevance_score = score
            content.relevance_reason = reason
            if topic_group:
                content.topic_group = topic_group
            if style_key:
                content.style_key = style_key
            if franchise_key:
                content.franchise_key = franchise_key
            return score

        # embedding 预过滤: 对与任何用户兴趣相似度极低的内容跳过 LLM 调用
        # (节省 API 成本)
        if self._embedding_service is not None and profile.preferences.interests:
            from openbiliclaw.llm.embedding import cosine_similarity

            content_text = f"{content.title} {content.description or ''}"
            content_vec = await self._embedding_service.embed(content_text)
            if content_vec:
                max_sim = 0.0
                for interest_item in profile.preferences.interests[:10]:
                    interest_vec = await self._embedding_service.embed(interest_item.name)
                    if interest_vec:
                        sim = cosine_similarity(content_vec, interest_vec)
                        if sim > max_sim:
                            max_sim = sim
                # 与所有兴趣相似度都很低 且 不是来自 explore 策略
                # (explore 故意跨域，所以不过滤它)
                if max_sim < 0.3 and content.source_strategy != "explore":
                    content.relevance_score = round(max_sim * 0.5, 4)
                    content.relevance_reason = "embedding 预过滤: 与所有兴趣相似度极低"
                    self._eval_cache[cache_key] = (
                        content.relevance_score,
                        content.relevance_reason,
                        "",
                        "",
                        "",
                    )
                    return content.relevance_score

        from openbiliclaw.llm.prompts import build_content_evaluation_prompt

        messages = build_content_evaluation_prompt(
            profile_summary=build_profile_summary(profile),
            content_summary={
                "content_id": content.content_id or content.bvid,
                "content_url": content.content_url,
                "source_platform": content.source_platform or "bilibili",
                "content_type": content.content_type,
                "body_text": content.body_text,
                "title": content.title,
                "up_name": content.up_name,
                "author_name": content.author_name or content.up_name,
                "description": _prompt_description_for_content(content),
                "duration": content.duration,
                "source_strategy": content.source_strategy,
                **_prompt_visible_content_fields(content),
            },
            source_context=source_context or content.source_strategy,
            source_platform=content.source_platform or "bilibili",
        )
        try:
            complete_structured = self._llm_service.complete_structured_task
            llm_call = complete_structured(
                system_instruction=messages[0]["content"],
                user_input=messages[1]["content"],
                caller="discovery.evaluate_single",
                **without_core_memory_kwargs(complete_structured),
            )
            if self._concurrency is not None:
                response = await self._concurrency.run_llm(llm_call)
            else:
                response = await llm_call
            payload = parse_llm_json_tolerant(str(getattr(response, "content", "")).strip())
            if not isinstance(payload, dict):
                raise ValueError("Expected JSON object from content evaluation")
            if not isinstance(payload, dict):
                return 0.0
            score = self._clamp_score(payload.get("score", 0.0))
            reason = str(payload.get("reason", "")).strip()
            topic_group = str(payload.get("topic_group", "")).strip()
            style_key = normalize_style_key(payload.get("style_key", ""))
            franchise_key = str(payload.get("franchise_key", "")).strip()
        except Exception:
            logger.exception("Failed to evaluate discovered content: %s", content.bvid)
            return 0.0

        content.relevance_score = score
        content.relevance_reason = reason
        if topic_group:
            content.topic_group = topic_group
        if style_key in VALID_STYLE_KEYS:
            content.style_key = style_key
        if franchise_key:
            content.franchise_key = franchise_key
        self._eval_cache[cache_key] = (
            score,
            reason,
            topic_group,
            style_key,
            franchise_key,
        )
        return score

    # 在评估器层级施加的安全上限，与调用方无关。
    # 过度拉取的策略 (related_chain 深度 2 扇出、explore 扩大预算等)
    # 否则会把 400+ 条倒进单次发现运行。30 让每个策略的评估
    # 在 ``batch_size`` 与上限匹配时限于单次 LLM 调用 (v0.3.25+
    # 默认 —— 见下)。截断是列表顶部 (策略的自然排序)，
    # 并发出 WARNING 以便看到策略触及上限。
    #
    # v0.3.52+: 上限从 30 提到 90，每轮发现评估 ~3× 候选。
    # 生产日志 (2026-05-05) 经常把 300-480 候选截到 30 ——
    # 90% 数据浪费。30/批的常量保持不变，所以每次 LLM 调用
    # 大小相同，但 ``_run_batch`` 已经通过 ``asyncio.gather``
    # 并行收集多个批次，所以新上限意味着 3 个并行的 30 条
    # LLM 批次。并发受 ``llm_evaluation_concurrency`` 限制，
    # 不会打爆 provider 速率限制。配合 v0.3.51 的禁用
    # reasoning 批次 (每批 ~30s)，三个并行批次完成时间大致
    # 和以前一个批次相同。
    _EVALUATE_BATCH_HARD_CAP = _EVALUATE_BATCH_HARD_CAP_DEFAULT

    async def evaluate_content_batch(
        self,
        contents: list[DiscoveredContent],
        profile: SoulProfile,
        *,
        source_context: str = "",
        batch_size: int = _DEFAULT_EVAL_BATCH_SIZE,
    ) -> list[float]:
        """用批量 LLM 调用评估多条内容。

        把条目按 ``batch_size`` 分组，每批发一次 LLM 调用，
        而不是每条一次。批次中失败的条目回退到单条评估。

        默认文本批次大小是 45，硬上限 90，默认两个 worker 槽。
        这让多模态评估保持较小的图像感知批次大小，同时让
        长上下文文本模型在更多条目上摊销固定的 profile/system
        prompt 成本。

        返回得分顺序与 ``contents`` 一致。
        """
        if self._llm_service is None or not contents:
            return [0.0] * len(contents)

        original_len = len(contents)
        if original_len > self._EVALUATE_BATCH_HARD_CAP:
            logger.warning(
                "evaluate_content_batch: truncating %d -> %d items (source=%s)",
                original_len,
                self._EVALUATE_BATCH_HARD_CAP,
                source_context or "mixed",
            )
            contents = contents[: self._EVALUATE_BATCH_HARD_CAP]

        scores: list[float] = [0.0] * len(contents)
        viewed_content_keys = self._recent_viewed_content_keys()
        if viewed_content_keys:
            eval_pairs = [
                (index, content)
                for index, content in enumerate(contents)
                if self._candidate_view_keys(content).isdisjoint(viewed_content_keys)
            ]
            skipped_viewed = len(contents) - len(eval_pairs)
            if skipped_viewed > 0:
                logger.info(
                    "eval_batch skipped %d recently viewed candidate(s) before LLM (source=%s)",
                    skipped_viewed,
                    source_context or "mixed",
                )
        else:
            eval_pairs = list(enumerate(contents))

        if not eval_pairs:
            if len(scores) < original_len:
                scores = scores + [0.0] * (original_len - len(scores))
            return scores

        eval_indices = [index for index, _content in eval_pairs]
        eval_contents = [content for _index, content in eval_pairs]

        # 拆分缓存 vs 未缓存。批量评估会消费最近的负样本，
        # 所以内存中的得分缓存按实际 prompt 可见的负样本摘要
        # 版本化。一个新的不相关 event 可能移动 event-log 水位线，
        # 但当喂给模型的负锚点没变时不应驱逐精确评估结果。
        negative_examples = self._get_negative_exemplars()
        if not negative_examples:
            negative_examples = None
        profile_digest = self._evaluation_profile_digest(profile)
        negative_digest = self._negative_examples_digest(negative_examples)
        uncached_indices: list[int] = []
        for i, content in enumerate(eval_contents):
            cache_key = self._batch_eval_cache_key(
                content,
                profile_digest=profile_digest,
                negative_digest=negative_digest,
            )
            cached = self._eval_cache.get(cache_key)
            if cached is not None:
                # 缓存元组在 v0.3.18 中增长以携带 franchise_key。
                # 容忍旧的 4 元组形状，这样在升级前持有旧条目的
                # 进行中进程不会在下一次 eval 调用时崩溃。
                if len(cached) == 5:
                    score, reason, topic_group, style_key, franchise_key = cached
                else:
                    score, reason, topic_group, style_key = cached
                    franchise_key = ""
                style_key = normalize_style_key(style_key)
                content.relevance_score = score
                content.relevance_reason = reason
                if topic_group:
                    content.topic_group = topic_group
                if style_key:
                    content.style_key = style_key
                if franchise_key:
                    content.franchise_key = franchise_key
                scores[eval_indices[i]] = score
            else:
                uncached_indices.append(i)

        if not uncached_indices:
            if len(scores) < original_len:
                scores = scores + [0.0] * (original_len - len(scores))
            return scores

        batch_size = self._effective_eval_batch_size(
            [eval_contents[i] for i in uncached_indices],
            batch_size,
        )
        if self.multimodal_unavailable_reason:
            logger.info("eval_batch multimodal fallback: %s", self.multimodal_unavailable_reason)

        total_batches = (len(uncached_indices) + batch_size - 1) // batch_size
        eval_batch_concurrency = self._effective_eval_batch_concurrency()
        logger.info(
            "eval_batch start: source=%s items=%d batches=%d concurrency=%d (cached=%d)",
            source_context or "mixed",
            len(uncached_indices),
            total_batches,
            eval_batch_concurrency,
            len(eval_contents) - len(uncached_indices),
        )

        # 并发运行多个 LLM 批次，但保持本任务的扇出有界。
        # 共享的 ``run_llm`` 包装器仍是所有发现工作的全局
        # provider 面向上限；这个本地 worker 上限防止一个
        # 大评估作业创建无界子任务或占用每个全局 LLM 槽。
        async def _run_batch(
            batch_idx: int,
            batch_indices: list[int],
        ) -> tuple[list[int], list[float]]:
            batch_contents = [eval_contents[i] for i in batch_indices]
            t0 = time.monotonic()
            batch_scores = await self._evaluate_batch(
                batch_contents,
                profile,
                source_context=source_context,
                negative_examples=negative_examples,
            )
            elapsed = time.monotonic() - t0
            kept = sum(1 for s in batch_scores if s > 0)
            # v0.3.31+: 保留条目的多样性快照，以便我们能看到
            # 发现是给 pool 喂多样内容，还是 30 个候选全部
            # 塌缩到同一个 topic_group。
            kept_items = [batch_contents[i] for i, s in enumerate(batch_scores) if s > 0]
            topics: Counter[str] = Counter(
                (getattr(c, "topic_group", "") or "untagged").strip().lower() for c in kept_items
            )
            styles: Counter[str] = Counter(
                (getattr(c, "style_key", "") or "untagged").strip().lower() for c in kept_items
            )
            franchises: Counter[str] = Counter(
                (getattr(c, "franchise_key", "") or "").strip().lower() for c in kept_items
            )
            del franchises[""]  # 不计非 franchise 条目
            top_topic = topics.most_common(1)[0] if topics else ("", 0)
            top_franchise = franchises.most_common(1)[0] if franchises else ("", 0)
            logger.info(
                "eval_batch %d/%d done: source=%s size=%d elapsed=%.1fs kept=%d "
                "diversity={topics: %d uniq, top=%s×%d (%.0f%%); styles: %d uniq, "
                "top=%s×%d; franchises: %d uniq%s}",
                batch_idx,
                total_batches,
                source_context or "mixed",
                len(batch_indices),
                elapsed,
                kept,
                len(topics),
                top_topic[0] or "—",
                top_topic[1],
                (top_topic[1] / kept * 100) if kept else 0,
                len(styles),
                styles.most_common(1)[0][0] if styles else "—",
                styles.most_common(1)[0][1] if styles else 0,
                len(franchises),
                f", top_franchise={top_franchise[0]}×{top_franchise[1]}"
                if top_franchise[1] > 1
                else "",
            )
            return batch_indices, batch_scores

        batch_jobs: list[tuple[int, list[int]]] = []
        for batch_idx, batch_start in enumerate(
            range(0, len(uncached_indices), batch_size), start=1
        ):
            batch_indices = uncached_indices[batch_start : batch_start + batch_size]
            batch_jobs.append((batch_idx, batch_indices))

        results: list[tuple[list[int], list[float]] | None] = [None] * len(batch_jobs)
        next_job_index = 0
        worker_count = min(eval_batch_concurrency, len(batch_jobs))

        async def _worker() -> None:
            nonlocal next_job_index
            while next_job_index < len(batch_jobs):
                job_index = next_job_index
                next_job_index += 1
                batch_idx, batch_indices = batch_jobs[job_index]
                results[job_index] = await _run_batch(batch_idx, batch_indices)

        await asyncio.gather(*(_worker() for _ in range(worker_count)))

        for result in results:
            if result is None:
                continue
            batch_indices, batch_scores = result
            for idx, batch_score in zip(batch_indices, batch_scores, strict=True):
                scores[eval_indices[idx]] = batch_score

        # 为上面硬上限丢弃的条目补齐，这样调用方
        # ``zip(candidates, scores, strict=True)`` 仍能对齐。
        if len(scores) < original_len:
            scores = scores + [0.0] * (original_len - len(scores))

        return scores

    def _recent_viewed_content_keys(self) -> set[str]:
        database = getattr(self, "_database", None)
        get_recent = getattr(database, "get_recent_viewed_content_keys", None)
        log_name = "get_recent_viewed_content_keys"
        if not callable(get_recent):
            get_recent = getattr(database, "get_recent_viewed_bvids", None)
            log_name = "get_recent_viewed_bvids"
        if not callable(get_recent):
            return set()
        try:
            raw = get_recent()
        except Exception:
            logger.debug("%s failed", log_name, exc_info=True)
            return set()
        return {str(item).strip() for item in raw if str(item).strip()}

    @staticmethod
    def _candidate_view_keys(content: DiscoveredContent) -> set[str]:
        platform = (content.source_platform or ("bilibili" if content.bvid else "")).strip().lower()
        if platform == "xhs":
            platform = "xiaohongshu"
        elif platform == "dy":
            platform = "douyin"
        elif platform == "yt":
            platform = "youtube"
        elif platform == "bili":
            platform = "bilibili"

        keys: set[str] = set()
        for value in {content.bvid, content.content_id}:
            content_id = str(value or "").strip()
            if not content_id:
                continue
            keys.add(content_id)
            if platform:
                keys.add(f"{platform}:{content_id}")
        return keys

    def _negative_exemplar_revision(self) -> int | None:
        """返回用于负样本感知 eval 缓存 key 的 event-log 修订号。"""
        database = cast(
            "SupportsNegativeExemplarStore | None",
            getattr(self, "_database", None),
        )
        if database is None:
            return None
        try:
            latest_id = database.get_latest_event_id()
        except Exception:
            logger.debug("negative_exemplars: get_latest_event_id failed", exc_info=True)
            return None
        if latest_id is None:
            return None
        return int(latest_id)

    def _get_negative_exemplars(self) -> list[dict[str, object]] | None:
        """返回最近的负样本，过期时刷新缓存。

        缓存 key: (latest_event_id, 时间桶)。5 分钟 TTL 让 I/O 在批次间
        保持平稳；latest-event-id 失效在用户记录新负样本时立即拾取。
        存储失败返回 None，所以 eval-batch 总能运行。
        """
        # 防御性 getattr: 一些测试夹具通过 ``__new__`` 构造引擎并完全
        # 跳过 ``__init__``，所以 `_database` 和 `_negative_exemplars_cache`
        # 可能不作为属性存在。
        database = cast(
            "SupportsNegativeExemplarStore | None",
            getattr(self, "_database", None),
        )
        if database is None:
            return None

        from openbiliclaw.soul.negative_exemplars import recent_negative_exemplars

        latest_id = self._negative_exemplar_revision()

        cached = cast(
            "tuple[float, int | None, list[dict[str, object]]] | None",
            getattr(self, "_negative_exemplars_cache", None),
        )
        if cached is not None:
            cached_ts, cached_latest_id, cached_exemplars = cached
            if cached_latest_id == latest_id and (time.monotonic() - cached_ts) < 300:
                return cached_exemplars

        try:
            exemplars = recent_negative_exemplars(database)
        except Exception:
            logger.debug("negative_exemplars: refresh failed", exc_info=True)
            return None

        self._negative_exemplars_cache = (time.monotonic(), latest_id, exemplars)
        return exemplars

    def _evaluation_profile_digest(self, profile: SoulProfile) -> str:
        """对批量评估可见的完整结构化 profile 形状做摘要。"""

        return stable_json_digest(self._evaluation_profile_summary(profile))

    @staticmethod
    def _evaluation_profile_summary(profile: SoulProfile) -> dict[str, object]:
        return build_profile_summary(profile)

    def _evaluation_profile_prompt_cache_obj(self) -> PromptLayerRenderCache:
        """返回评估 profile 的 prompt 缓存，为轻量测试创建。"""

        cache = getattr(self, "_evaluation_profile_prompt_cache", None)
        if not isinstance(cache, PromptLayerRenderCache):
            cache = PromptLayerRenderCache()
            self._evaluation_profile_prompt_cache = cache
        return cache

    def evaluation_profile_prompt_cache_stats(self) -> dict[str, dict[str, Any]]:
        """返回评估 profile 的 prompt-layer 缓存统计。"""

        return self._evaluation_profile_prompt_cache_obj().stats()

    @staticmethod
    def _negative_examples_digest(examples: list[dict[str, object]] | None) -> str:
        return stable_json_digest(examples or [])

    def _batch_eval_cache_key(
        self,
        content: DiscoveredContent,
        *,
        profile_digest: str,
        negative_digest: str,
    ) -> str:
        return (
            f"{_EVAL_BATCH_CACHE_VERSION}:"
            f"{self._content_identity(content)}:"
            f"profile:{profile_digest}:neg:{negative_digest}"
        )

    async def _evaluate_batch(
        self,
        batch: list[DiscoveredContent],
        profile: SoulProfile,
        *,
        source_context: str = "",
        negative_examples: object = _NEGATIVE_EXAMPLES_UNSET,
    ) -> list[float]:
        """为一批条目发送一次 LLM 调用。"""
        from openbiliclaw.discovery.candidate_pool import resolve_content_type
        from openbiliclaw.llm.prompts import build_batch_content_evaluation_prompt

        profile_data = self._evaluation_profile_summary(profile)
        content_items: list[dict[str, object]] = []
        for c in batch:
            platform = (c.source_platform or ("bilibili" if c.bvid else "")).strip().lower()
            if platform == "xhs":
                platform = "xiaohongshu"
            elif platform == "dy":
                platform = "douyin"
            elif platform == "yt":
                platform = "youtube"
            elif platform == "bili":
                platform = "bilibili"
            if not platform:
                platform = "bilibili"
            content_items.append(
                {
                    "bvid": c.bvid,
                    "content_id": c.content_id or c.bvid,
                    "content_url": c.content_url,
                    "source_platform": platform,
                    "source_strategy": c.source_strategy,
                    "source_context": source_context or c.source_strategy,
                    "content_type": resolve_content_type(c.content_type, platform),
                    "body_text": c.body_text,
                    "title": c.title,
                    "up_name": c.up_name,
                    "author_name": c.author_name or c.up_name,
                    "description": _prompt_description_for_content(c, limit=400),
                    "cover_url": c.cover_url,
                    "duration": c.duration,
                    **_prompt_visible_content_fields(c),
                }
            )
        image_inputs: list[dict[str, str]] = []
        multimodal_enabled = bool(getattr(self, "multimodal_evaluation_enabled", False))
        if (
            multimodal_enabled
            and self._supports_multimodal_evaluation()
            and any((content.cover_url or "").strip() for content in batch)
        ):
            from openbiliclaw.discovery import multimodal

            prepared_images = await multimodal.prepare_cover_image_inputs(
                batch,
                max_px=int(getattr(self, "multimodal_image_max_px", 384)),
                quality=int(getattr(self, "multimodal_image_quality", 72)),
                timeout_seconds=int(getattr(self, "multimodal_image_timeout_seconds", 6)),
            )
            image_ids = {image.content_id for image in prepared_images}
            if image_ids:
                for item in content_items:
                    content_id = str(item.get("content_id") or item.get("bvid") or "")
                    if content_id in image_ids:
                        item["cover_image_ref"] = f"cover:{content_id}"
                image_inputs = [image.to_llm_input() for image in prepared_images]
        source_platforms = {
            str(item.get("source_platform") or "").strip()
            for item in content_items
            if str(item.get("source_platform") or "").strip()
        }
        batch_source_platform = (
            "mixed" if len(source_platforms) > 1 else next(iter(source_platforms), "bilibili")
        )
        if negative_examples is _NEGATIVE_EXAMPLES_UNSET:
            negative_examples = self._get_negative_exemplars()
        # 把空列表当作"无样本"，这样冷启动用户的 user-message 保持
        # 与无样本形状字节一致。
        if not negative_examples:
            negative_examples = None
        negative_examples_for_prompt = cast("list[dict[str, object]] | None", negative_examples)
        profile_digest = self._evaluation_profile_digest(profile)
        negative_digest = self._negative_examples_digest(negative_examples_for_prompt)
        profile_blocks = self._evaluation_profile_prompt_cache_obj().render_json_layers(
            evaluation_profile_prompt_layers(profile_data)
        )
        messages = build_batch_content_evaluation_prompt(
            profile_summary=profile_data,
            profile_blocks=profile_blocks,
            content_items=content_items,
            source_context=source_context or (batch[0].source_strategy if batch else ""),
            source_platform=batch_source_platform,
            negative_examples=negative_examples_for_prompt,
        )

        assert self._llm_service is not None
        try:
            multimodal_call = getattr(
                self._llm_service,
                "complete_multimodal_structured_task",
                None,
            )
            if image_inputs and callable(multimodal_call):
                kwargs: dict[str, Any] = {
                    "system_instruction": messages[0]["content"],
                    "user_input": messages[1]["content"],
                    "image_inputs": image_inputs,
                    "max_tokens": 16384,
                    "reasoning_effort": "",
                    "caller": "discovery.evaluate_batch",
                }
                kwargs.update(without_core_memory_kwargs(multimodal_call))
                llm_call = multimodal_call(**kwargs)
            else:
                kwargs = {
                    "system_instruction": messages[0]["content"],
                    "user_input": messages[1]["content"],
                    # v0.3.51+: 显式禁用 provider thinking。这个
                    # 任务是结构化打分 (返回 JSON 数组)，不是推理 ——
                    # 生产日志显示开启 reasoning 时 8-16 分钟/批，
                    # 关闭后降到 ~30s。16384 max_tokens 对 30 条
                    # JSON 数组现在需要的 1500-3000 token 输出
                    # 绰绰有余。
                    "max_tokens": 16384,
                    "reasoning_effort": "",
                    "caller": "discovery.evaluate_batch",
                }
                complete_structured = self._llm_service.complete_structured_task
                kwargs.update(without_core_memory_kwargs(complete_structured))
                llm_call = complete_structured(**kwargs)
            if self._concurrency is not None:
                response = await self._concurrency.run_llm(llm_call)
            else:
                response = await llm_call
            raw = str(getattr(response, "content", "")).strip()
            payload = _parse_batch_evaluation_payload(raw)
            if payload is None:
                raise ValueError("Expected scored JSON array from batch evaluation")
        except Exception as exc:
            if is_llm_rate_limit_error(exc):
                logger.warning(
                    "Batch evaluation is rate-limited for %d items; "
                    "propagating transient failure so callers can retry later: %s",
                    len(batch),
                    exc,
                )
                raise
            logger.warning(
                "Batch evaluation failed for %d items (%s: %s), falling back to single eval",
                len(batch),
                type(exc).__name__,
                exc,
            )
            # 回退：逐条评估
            return [
                await self.evaluate_content(c, profile, source_context=source_context)
                for c in batch
            ]

        payload_by_id = _batch_results_by_content_key(payload, batch)
        if payload_by_id is None and len(payload) != len(batch):
            logger.warning(
                "Batch evaluation result count mismatch without IDs (%d results for %d items), "
                "falling back to single eval",
                len(payload),
                len(batch),
            )
            return [
                await self.evaluate_content(c, profile, source_context=source_context)
                for c in batch
            ]

        results: list[float] = []
        for i, content in enumerate(batch):
            if payload_by_id is None:
                raw_item = payload[i] if i < len(payload) else None
            else:
                raw_item = next(
                    (
                        payload_by_id[key]
                        for key in _content_result_keys(content)
                        if key in payload_by_id
                    ),
                    None,
                )
            if raw_item is None:
                results.append(0.0)
                continue
            if not isinstance(raw_item, dict):
                results.append(0.0)
                continue
            item_result: dict[str, Any] = raw_item
            score = self._clamp_score(item_result.get("score", 0.0))
            reason = str(item_result.get("reason", "")).strip()
            topic_group = str(item_result.get("topic_group", "")).strip()
            style_key = normalize_style_key(item_result.get("style_key", ""))
            franchise_key = str(item_result.get("franchise_key", "")).strip()

            content.relevance_score = score
            content.relevance_reason = reason
            if topic_group:
                content.topic_group = topic_group
            if style_key in VALID_STYLE_KEYS:
                content.style_key = style_key
            if franchise_key:
                content.franchise_key = franchise_key

            cache_key = self._batch_eval_cache_key(
                content,
                profile_digest=profile_digest,
                negative_digest=negative_digest,
            )
            self._eval_cache[cache_key] = (
                score,
                reason,
                topic_group,
                style_key,
                franchise_key,
            )
            results.append(score)

        # v0.3.50+: 批次内 franchise 上限。LLM 会尽职地为 IP/系列
        # 内容填 franchise_key (按 prompt 的批次一致性规则)，但我们
        # 以前即使 ≥10 条共享一个 franchise 也保留全部 30 条 ——
        # 生产中观测到: 张雪机车×13 / 风犬少年的天空×7 / 咲间妮娜×7
        # 在单个批次中。按 ``_BATCH_FRANCHISE_CAP`` 每批上限: 每个
        # franchise 保留得分最高的 N 条，其余置零。空 franchise 豁免
        # (大多数通用内容没有 IP 信号)。
        cap = _BATCH_FRANCHISE_CAP
        if cap > 0 and batch:
            buckets: dict[str, list[int]] = {}
            for i, content in enumerate(batch):
                if i >= len(results) or results[i] <= 0:
                    continue
                key = (content.franchise_key or "").strip().lower()
                if not key:
                    continue
                buckets.setdefault(key, []).append(i)
            dropped = 0
            for _key, indices in buckets.items():
                if len(indices) <= cap:
                    continue
                # 按得分保留前 ``cap`` 条，丢弃其余。
                indices.sort(key=lambda idx: results[idx], reverse=True)
                for idx in indices[cap:]:
                    results[idx] = 0.0
                    batch[idx].relevance_score = 0.0
                    dropped += 1
            if dropped:
                logger.info(
                    "eval_batch franchise cap: dropped %d item(s) (cap=%d/franchise; offenders=%s)",
                    dropped,
                    cap,
                    ", ".join(f"{k}×{len(v)}" for k, v in buckets.items() if len(v) > cap),
                )

        # v0.3.51+: 同 style 上限 (镜像 v0.3.50 franchise 上限)。
        # 生产日志 (2026-05-05) 显示许多 eval 批次中单 style 浓度
        # 7-12/30 (mood_release×10、story_immersion×11、social_chat×11、
        # hands_on×10)。pool 继承这种倾斜，因为 eval_batch 保留全部
        # 30 条 —— serve 时的多样化器无法修正已经 30%+ 同 style 的
        # pool。Cap=8 (30 批的 27%) 让一个 style 有小立足点但阻止
        # 单 style 称霸本轮。
        style_cap = _BATCH_STYLE_CAP
        if style_cap > 0 and batch:
            style_buckets: dict[str, list[int]] = {}
            for i, content in enumerate(batch):
                if i >= len(results) or results[i] <= 0:
                    continue
                style_key = normalize_style_key(content.style_key)
                if not style_key:
                    continue
                style_buckets.setdefault(style_key, []).append(i)
            style_dropped = 0
            for _style_key, indices in style_buckets.items():
                if len(indices) <= style_cap:
                    continue
                indices.sort(key=lambda idx: results[idx], reverse=True)
                for idx in indices[style_cap:]:
                    results[idx] = 0.0
                    batch[idx].relevance_score = 0.0
                    style_dropped += 1
            if style_dropped:
                logger.info(
                    "eval_batch style cap: dropped %d item(s) (cap=%d/style; offenders=%s)",
                    style_dropped,
                    style_cap,
                    ", ".join(
                        f"{k}×{len(v)}" for k, v in style_buckets.items() if len(v) > style_cap
                    ),
                )

        return results

    @staticmethod
    def _clamp_score(raw_value: object) -> float:
        if isinstance(raw_value, bool | int | float):
            value = float(raw_value)
        elif isinstance(raw_value, str):
            try:
                value = float(raw_value)
            except ValueError:
                value = 0.0
        else:
            value = 0.0
        return max(0.0, min(1.0, round(value, 4)))

    @staticmethod
    def _merge_duplicates(results: list[DiscoveredContent]) -> list[DiscoveredContent]:
        by_identity: dict[str, DiscoveredContent] = {}
        for item in results:
            identity = ContentDiscoveryEngine._content_identity(item)
            existing = by_identity.get(identity)
            if existing is None or item.relevance_score > existing.relevance_score:
                by_identity[identity] = item
        return list(by_identity.values())

    @staticmethod
    def _content_identity(item: DiscoveredContent) -> str:
        platform = (item.source_platform or "bilibili").strip() or "bilibili"
        content_id = (item.content_id or item.bvid or item.content_url).strip()
        if content_id:
            return f"{platform}:{content_id}"
        return f"{platform}:title:{item.title}:{item.author_name or item.up_name}"

    async def _run_strategies(
        self,
        strategies: list[DiscoveryStrategy],
        *,
        profile: SoulProfile,
        limit: int,
        fully_parallel: bool = False,
        strategy_limits: dict[str, int] | None = None,
        pool_snapshot: Any | None = None,
        keywords: list[str] | None = None,
        keyword_ids: dict[str, int] | None = None,
    ) -> list[DiscoveredContent]:
        results: list[DiscoveredContent] = []
        run_entries = [
            (strategy, self._strategy_run_limit(strategy, limit, strategy_limits))
            for strategy in strategies
        ]
        run_entries = [
            (strategy, run_limit) for strategy, run_limit in run_entries if run_limit > 0
        ]
        if not run_entries:
            return []

        if fully_parallel:
            # 一次性: 每个策略在单个 gather 中运行。我们依赖
            # ``bilibili_request_concurrency`` + ``search_budget_total``
            # 限制 IP 层压力；默认的阶段拆分更安全但会在其他策略
            # 启动前增加 ~search_wall_time。
            names = [s.name for s, _ in run_entries]
            logger.info("discover start (fully_parallel): strategies=%s limit=%d", names, limit)
            t0 = time.monotonic()

            async def _timed(
                strategy: DiscoveryStrategy,
                run_limit: int,
            ) -> list[DiscoveredContent]:
                s_t0 = time.monotonic()
                logger.info("strategy %s: dispatch limit=%d", strategy.name, run_limit)
                try:
                    result = await _call_strategy_discover(
                        strategy,
                        profile,
                        limit=run_limit,
                        pool_snapshot=pool_snapshot,
                        keywords=keywords,
                        keyword_ids=keyword_ids,
                    )
                finally:
                    logger.info(
                        "strategy %s: done in %.1fs",
                        strategy.name,
                        time.monotonic() - s_t0,
                    )
                return result

            gathered = await asyncio.gather(
                *(_timed(s, run_limit) for s, run_limit in run_entries),
                return_exceptions=True,
            )
            results.extend(self._collect_strategy_results([s for s, _ in run_entries], gathered))
            logger.info(
                "discover done (fully_parallel): strategies=%s total_elapsed=%.1fs results=%d",
                names,
                time.monotonic() - t0,
                len(results),
            )
        else:
            # 把策略拆成两阶段以避免 B站 IP 层搜索速率限制。搜索
            # 先跑 (Phase 1)，用专用的无 cookie client，这样它能
            # 拿到干净的配额。其他策略 (explore、related_chain)
            # 也会调搜索 API，所以每个策略的调用都被
            # ``DiscoveryConcurrencyController`` 中的每策略搜索预算
            # 限制。
            search_entries = [(s, run_limit) for s, run_limit in run_entries if s.name == "search"]
            other_entries = [(s, run_limit) for s, run_limit in run_entries if s.name != "search"]

            # Phase 1: 先跑 search 策略以拿到干净的 IP 配额
            if search_entries:
                tasks = [
                    _call_strategy_discover(
                        s,
                        profile,
                        limit=run_limit,
                        pool_snapshot=pool_snapshot,
                        keywords=keywords,
                        keyword_ids=keyword_ids,
                    )
                    for s, run_limit in search_entries
                ]
                gathered = await asyncio.gather(*tasks, return_exceptions=True)
                results.extend(
                    self._collect_strategy_results([s for s, _ in search_entries], gathered)
                )

            # 阶段之间的短暂冷却，让 IP 层速率限制恢复
            if search_entries and other_entries:
                await asyncio.sleep(2.0)

            # Phase 2: 并发运行剩余策略
            if other_entries:
                tasks = [
                    _call_strategy_discover(
                        s,
                        profile,
                        limit=run_limit,
                        pool_snapshot=pool_snapshot,
                    )
                    for s, run_limit in other_entries
                ]
                gathered = await asyncio.gather(*tasks, return_exceptions=True)
                results.extend(
                    self._collect_strategy_results([s for s, _ in other_entries], gathered)
                )

        logger.info(
            "Discovery gather returned %d results for %d strategies: %s",
            len(results),
            len(run_entries),
            [s.name for s, _ in run_entries],
        )
        return results

    @staticmethod
    def _strategy_run_limit(
        strategy: DiscoveryStrategy,
        default_limit: int,
        strategy_limits: dict[str, int] | None,
    ) -> int:
        if not strategy_limits:
            return max(1, int(default_limit))
        raw_limit = strategy_limits.get(strategy.name, default_limit)
        try:
            run_limit = int(raw_limit)
        except (TypeError, ValueError):
            run_limit = default_limit
        return max(0, min(max(1, int(default_limit)), run_limit))

    @staticmethod
    def _collect_strategy_results(
        strategies: list[DiscoveryStrategy],
        gathered: Sequence[list[DiscoveredContent] | BaseException],
    ) -> list[DiscoveredContent]:
        results: list[DiscoveredContent] = []
        for strategy, outcome in zip(strategies, gathered, strict=True):
            if isinstance(outcome, BaseException):
                logger.exception(
                    "Strategy '%s' failed: %s: %s",
                    strategy.name,
                    type(outcome).__name__,
                    outcome,
                    exc_info=outcome,
                )
                continue
            if not isinstance(outcome, list):
                logger.error(
                    "Strategy '%s' returned unexpected outcome type: %s",
                    strategy.name,
                    type(outcome).__name__,
                )
                continue
            items: list[DiscoveredContent] = outcome
            results.extend(items)
            # v0.3.31+: 每策略原始多样性快照。此处的条目是
            # LLM 评估前的 (topic_group / style_key 尚未设置)，
            # 所以我们报告可观察的: 标题级唯一性、up_name 分布、
            # 平台组合。能捕捉 "search 返回 13 条但都来自同一 UP
            # / 全部相同标题前缀" 这类病态。
            ups: Counter[str] = Counter((c.up_name or "").strip().lower() for c in items)
            del ups[""]
            unique_titles = len({c.title.strip() for c in items if c.title})
            platforms: Counter[str] = Counter((c.source_platform or "bilibili") for c in items)
            top_up = ups.most_common(1)[0] if ups else ("", 0)
            logger.info(
                "Strategy '%s' found %d items.%s "
                "diversity={unique_titles=%d/%d, unique_ups=%d, top_up=%s×%d, platforms=%s}",
                strategy.name,
                len(items),
                "" if items else " (empty — all candidates filtered or generation failed)",
                unique_titles,
                len(items) or 1,
                len(ups),
                top_up[0] or "—",
                top_up[1],
                dict(platforms.most_common()),
            )
        return results

    async def _run_backfill(
        self,
        strategies: list[DiscoveryStrategy],
        *,
        profile: SoulProfile,
        limit: int,
        existing: list[DiscoveredContent],
        pool_snapshot: Any | None = None,
    ) -> list[DiscoveredContent]:
        remaining = limit - len(existing)
        if remaining <= 0:
            return []

        backfill_strategies: list[DiscoveryStrategy | None] = []
        for strategy in strategies:
            factory = getattr(strategy, "create_backfill_strategy", None)
            if not callable(factory):
                backfill_strategies.append(None)
                continue
            backfill_strategies.append(factory())
        active_backfill = [strategy for strategy in backfill_strategies if strategy is not None]
        results: list[DiscoveredContent] = []
        if active_backfill:
            results.extend(
                await self._run_strategies(
                    active_backfill,
                    profile=profile,
                    limit=remaining,
                    pool_snapshot=pool_snapshot,
                )
            )

        merged = self._merge_and_rank([*existing, *results])[:limit]
        if len(merged) >= limit:
            return results

        results.extend(
            self._load_cached_backfill(
                limit=limit,
                exclude_bvids={item.bvid for item in merged},
            )
        )
        return results

    def _load_cached_backfill(
        self,
        *,
        limit: int,
        exclude_bvids: set[str],
    ) -> list[DiscoveredContent]:
        if self._database is None:
            return []

        rows = self._database.get_unrecommended_content(limit=limit)
        candidates: list[DiscoveredContent] = []
        for row in rows:
            bvid = str(row.get("bvid", "")).strip()
            if not bvid or bvid in exclude_bvids:
                continue
            candidates.append(
                DiscoveredContent(
                    bvid=bvid,
                    title=str(row.get("title", "")),
                    up_name=str(row.get("up_name", "")),
                    up_mid=int(row.get("up_mid", 0) or 0),
                    duration=int(row.get("duration", 0) or 0),
                    tags=[],
                    topic_key=str(row.get("topic_key", "")),
                    topic_group=str(row.get("topic_group", "")),
                    style_key=str(row.get("style_key", "")),
                    description=str(row.get("description", "")),
                    cover_url=str(row.get("cover_url", "")),
                    view_count=int(row.get("view_count", 0) or 0),
                    like_count=int(row.get("like_count", 0) or 0),
                    source_strategy=str(row.get("source", "")),
                    relevance_score=self._clamp_score(row.get("relevance_score", 0.0)),
                    relevance_reason=str(row.get("relevance_reason", "")),
                    candidate_tier="backfill",
                    discovered_at=str(row.get("discovered_at", "")),
                    last_scored_at=str(row.get("last_scored_at", "")),
                    content_id=str(row.get("content_id", "") or bvid),
                    content_url=str(row.get("content_url", "")),
                    source_platform=str(row.get("source_platform", "") or "bilibili"),
                )
            )
            if len(candidates) >= limit:
                break
        return candidates

    @staticmethod
    def _merge_and_rank(results: list[DiscoveredContent]) -> list[DiscoveredContent]:
        merged = ContentDiscoveryEngine._merge_duplicates(results)
        merged.sort(
            key=lambda item: (
                item.candidate_tier != "primary",
                -item.relevance_score,
                -item.view_count,
                item.bvid,
            )
        )
        return merged

    @staticmethod
    def _apply_pool_snapshot_rerank(
        results: list[DiscoveredContent],
        pool_snapshot: Any | None,
    ) -> list[DiscoveredContent]:
        if pool_snapshot is None or len(results) <= 1:
            return list(results)

        saturated_topics = ContentDiscoveryEngine._normalized_snapshot_values(
            pool_snapshot,
            "saturated_topics",
        )
        saturated_styles = ContentDiscoveryEngine._normalized_snapshot_values(
            pool_snapshot,
            "saturated_styles",
        )
        saturated_franchises = ContentDiscoveryEngine._normalized_snapshot_values(
            pool_snapshot,
            "saturated_franchises",
        )
        undercovered_axes = ContentDiscoveryEngine._normalized_snapshot_values(
            pool_snapshot,
            "undercovered_axes",
        )
        if not (saturated_topics or saturated_styles or saturated_franchises or undercovered_axes):
            return list(results)

        indexed_results = list(enumerate(results))
        indexed_results.sort(
            key=lambda indexed: ContentDiscoveryEngine._pool_rerank_key(
                indexed[1],
                original_index=indexed[0],
                saturated_topics=saturated_topics,
                saturated_styles=saturated_styles,
                saturated_franchises=saturated_franchises,
                undercovered_axes=undercovered_axes,
            )
        )
        return [item for _, item in indexed_results]

    @staticmethod
    def _pool_rerank_key(
        item: DiscoveredContent,
        *,
        original_index: int,
        saturated_topics: set[str],
        saturated_styles: set[str],
        saturated_franchises: set[str],
        undercovered_axes: set[str],
    ) -> tuple[bool, bool, float, float, int]:
        raw_score = item.relevance_score
        adjusted_score = raw_score
        topic = ContentDiscoveryEngine._topic_bucket(item)
        style = ContentDiscoveryEngine._style_bucket(item)
        franchise = ContentDiscoveryEngine._normalize_topic_token(item.franchise_key)

        if topic in saturated_topics:
            adjusted_score -= 0.08
        if style in saturated_styles:
            adjusted_score -= 0.04
        if franchise in saturated_franchises:
            adjusted_score -= 0.10
        if topic in undercovered_axes:
            adjusted_score += 0.04

        return (
            item.candidate_tier != "primary",
            raw_score < 0.92,
            -adjusted_score,
            -raw_score,
            original_index,
        )

    @staticmethod
    def _normalized_snapshot_values(pool_snapshot: Any, attribute: str) -> set[str]:
        values = getattr(pool_snapshot, attribute, ()) or ()
        if not isinstance(values, (list, tuple, set, frozenset)):
            return set()
        if attribute == "saturated_styles":
            return {
                token
                for value in values
                if isinstance(value, str)
                if (
                    token := ContentDiscoveryEngine._normalize_topic_token(
                        normalize_style_key(value)
                    )
                )
            }
        return {
            token
            for value in values
            if isinstance(value, str)
            if (token := ContentDiscoveryEngine._normalize_topic_token(value))
        }

    @staticmethod
    def _compress_topic_repeats(
        results: list[DiscoveredContent],
        *,
        limit: int,
    ) -> list[DiscoveredContent]:
        if limit <= 1 or len(results) <= 1:
            return results[:limit]

        per_style_cap = ContentDiscoveryEngine._style_cap(limit)
        per_source_cap = ContentDiscoveryEngine._source_cap(limit)
        unique_sources = {
            ContentDiscoveryEngine._normalize_topic_token(item.source_strategy)
            for item in results
            if ContentDiscoveryEngine._normalize_topic_token(item.source_strategy)
        }
        unique_source_target = min(limit, len(unique_sources))

        # 第 0 步: 为每个 source 策略预留最少槽位。
        # 没有下限的话，高分来源 (related_chain) 会通过得分排序
        # 选择垄断所有槽位，让低分但新颖的来源 (search、explore)
        # 零代表。
        n_sources = max(1, len(unique_sources))
        per_source_floor = max(1, limit // n_sources) if unique_sources else 0
        # 硬上限: 单一来源不超过 ~35% 结果，即使它有无限的 topic
        # 多样性 (例如 trending)。
        per_source_ceiling = max(per_source_floor + 1, limit * 35 // 100)
        reserved, unreserved = ContentDiscoveryEngine._reserve_per_source(
            results,
            per_source_floor=per_source_floor,
            unique_sources=unique_sources,
        )

        # 第 1 步: 从未预留池中选多样子集。
        # 传入预留条目的 topics/sources，让 _select_diverse 知道
        # 已经承诺了什么。
        remaining_limit = limit - len(reserved)
        reserved_topics = {ContentDiscoveryEngine._topic_bucket(i) for i in reserved} - {""}
        reserved_sources = {
            ContentDiscoveryEngine._normalize_topic_token(i.source_strategy) for i in reserved
        } - {""}
        selected, overflow = ContentDiscoveryEngine._select_diverse(
            unreserved,
            limit=remaining_limit,
            per_style_cap=per_style_cap,
            per_source_cap=max(1, per_source_cap - per_source_floor),
            unique_source_target=unique_source_target,
            initial_seen_topics=reserved_topics,
            initial_seen_sources=reserved_sources,
        )

        # 合并 reserved + selected
        combined = list(reserved)
        reserved_keys = {ContentDiscoveryEngine._content_identity(item) for item in reserved}
        for item in selected:
            if ContentDiscoveryEngine._content_identity(item) not in reserved_keys:
                combined.append(item)
        if len(combined) >= limit:
            return combined[:limit]

        # 第 2 步: 从 overflow 回填，放宽约束
        combined = ContentDiscoveryEngine._backfill_from_overflow(
            combined,
            overflow,
            limit=limit,
            per_style_cap=per_style_cap,
            per_source_cap=per_source_cap,
            per_source_ceiling=per_source_ceiling,
        )
        return combined[:limit]

    @staticmethod
    def _reserve_per_source(
        results: list[DiscoveredContent],
        *,
        per_source_floor: int,
        unique_sources: set[str],
    ) -> tuple[list[DiscoveredContent], list[DiscoveredContent]]:
        """为每个来源预留最佳条目以保证代表。

        返回 (reserved, unreserved)，其中 reserved 包含每个来源最多
        *per_source_floor* 条 (得分最高的那些)，unreserved 包含
        其余全部。
        """
        if per_source_floor <= 0:
            return [], list(results)

        source_buckets: dict[str, list[DiscoveredContent]] = {s: [] for s in unique_sources}
        for item in results:
            source = ContentDiscoveryEngine._normalize_topic_token(item.source_strategy)
            if source in source_buckets:
                source_buckets[source].append(item)

        reserved: list[DiscoveredContent] = []
        reserved_keys: set[str] = set()
        # 跨所有来源跟踪 topics，避免预留重复 topics
        global_seen_topics: set[str] = set()
        source_counts: dict[str, int] = {s: 0 for s in unique_sources}

        # 轮询: 跨所有来源按得分迭代，预留条目直到每个来源达到其
        # 下限。跳过 topic 已经被预留 (来自任何来源) 的条目以最大化
        # topic 多样性。
        for item in results:
            source = ContentDiscoveryEngine._normalize_topic_token(item.source_strategy)
            if source not in source_counts or source_counts[source] >= per_source_floor:
                continue
            topic = ContentDiscoveryEngine._topic_bucket(item)
            if topic and topic in global_seen_topics:
                continue
            reserved.append(item)
            reserved_keys.add(ContentDiscoveryEngine._content_identity(item))
            source_counts[source] += 1
            if topic:
                global_seen_topics.add(topic)

        unreserved = [
            item
            for item in results
            if ContentDiscoveryEngine._content_identity(item) not in reserved_keys
        ]
        return reserved, unreserved

    @staticmethod
    def _select_diverse(
        results: list[DiscoveredContent],
        *,
        limit: int,
        per_style_cap: int,
        per_source_cap: int,
        unique_source_target: int,
        initial_seen_topics: set[str] | None = None,
        initial_seen_sources: set[str] | None = None,
    ) -> tuple[list[DiscoveredContent], list[DiscoveredContent]]:
        """选多样子集，把重复推迟到 overflow。"""
        selected: list[DiscoveredContent] = []
        overflow: list[DiscoveredContent] = []
        seen_topics: set[str] = set(initial_seen_topics or ())
        seen_sources: set[str] = set(initial_seen_sources or ())
        style_counts: dict[str, int] = {}
        source_counts: dict[str, int] = {}

        for item in results:
            topic = ContentDiscoveryEngine._topic_bucket(item)
            style = ContentDiscoveryEngine._style_bucket(item)
            source = ContentDiscoveryEngine._normalize_topic_token(item.source_strategy)
            is_new_source = (
                bool(source)
                and source not in seen_sources
                and len(seen_sources) < unique_source_target
            )

            if topic and topic in seen_topics:
                overflow.append(item)
                continue
            if not is_new_source and style and style_counts.get(style, 0) >= per_style_cap:
                overflow.append(item)
                continue
            if source and source_counts.get(source, 0) >= per_source_cap:
                overflow.append(item)
                continue
            # 优先来源代表: 推迟来自已见来源的条目，直到所有唯一来源
            # 至少有一条。
            if (
                not is_new_source
                and source
                and source in seen_sources
                and len(seen_sources) < unique_source_target
            ):
                overflow.append(item)
                continue

            selected.append(item)
            if topic:
                seen_topics.add(topic)
            if style:
                style_counts[style] = style_counts.get(style, 0) + 1
            if source:
                seen_sources.add(source)
                source_counts[source] = source_counts.get(source, 0) + 1
            if len(selected) >= limit:
                break

        return selected, overflow

    @staticmethod
    def _backfill_from_overflow(
        selected: list[DiscoveredContent],
        overflow: list[DiscoveredContent],
        *,
        limit: int,
        per_style_cap: int,
        per_source_cap: int,
        per_source_ceiling: int = 0,
    ) -> list[DiscoveredContent]:
        """从 overflow 填充剩余槽位，放宽 topic 约束。

        强制每 topic-group 上限，这样没有单一 topic_group 称霸
        最终结果集 (最多 ~limit 的 20%)，以及每来源上限，这样
        没有单一来源超过 ~35%。
        """
        # 每 topic 上限: 单一 topic_group 不超过 ~20% 结果。
        # 对小 limit (≤5) 这是 1，保留严格 topic 去重。
        per_topic_cap = max(1, limit // 5)
        # 硬来源上限: 即使有无限 topic 多样性，单一来源总共也
        # 不能超过这么多槽位。
        source_ceiling = (
            per_source_ceiling
            if per_source_ceiling > 0
            else max(per_source_cap + 1, limit * 35 // 100)
        )

        topic_counts: dict[str, int] = {}
        style_counts: dict[str, int] = {}
        source_counts: dict[str, int] = {}
        for item in selected:
            topic = ContentDiscoveryEngine._topic_bucket(item)
            style = ContentDiscoveryEngine._style_bucket(item)
            source = ContentDiscoveryEngine._normalize_topic_token(item.source_strategy)
            if topic:
                topic_counts[topic] = topic_counts.get(topic, 0) + 1
            if style:
                style_counts[style] = style_counts.get(style, 0) + 1
            if source:
                source_counts[source] = source_counts.get(source, 0) + 1

        # Pass 1: 允许 overflow 中新或未达上限的 topic
        remaining: list[DiscoveredContent] = []
        for item in overflow:
            if len(selected) >= limit:
                break
            topic = ContentDiscoveryEngine._topic_bucket(item)
            style = ContentDiscoveryEngine._style_bucket(item)
            source = ContentDiscoveryEngine._normalize_topic_token(item.source_strategy)
            if topic and topic_counts.get(topic, 0) >= per_topic_cap:
                remaining.append(item)
                continue
            if style and style_counts.get(style, 0) >= per_style_cap:
                remaining.append(item)
                continue
            if source and source_counts.get(source, 0) >= source_ceiling:
                remaining.append(item)
                continue
            selected.append(item)
            if topic:
                topic_counts[topic] = topic_counts.get(topic, 0) + 1
            if style:
                style_counts[style] = style_counts.get(style, 0) + 1
            if source:
                source_counts[source] = source_counts.get(source, 0) + 1

        # Pass 2: 用软上限填充剩余 (topic ≤30%, source ≤ 上限)
        max_per_topic = max(per_topic_cap + 1, limit * 3 // 10)
        leftover: list[DiscoveredContent] = []
        for item in remaining:
            if len(selected) >= limit:
                break
            topic = ContentDiscoveryEngine._topic_bucket(item)
            source = ContentDiscoveryEngine._normalize_topic_token(item.source_strategy)
            if source and source_counts.get(source, 0) >= source_ceiling:
                leftover.append(item)
                continue
            if topic and topic_counts.get(topic, 0) >= max_per_topic:
                leftover.append(item)
                continue
            selected.append(item)
            if topic:
                topic_counts[topic] = topic_counts.get(topic, 0) + 1
            if source:
                source_counts[source] = source_counts.get(source, 0) + 1

        # Pass 3: 仍不足则无条件填充
        for item in leftover:
            if len(selected) >= limit:
                break
            selected.append(item)

        return selected

    @staticmethod
    def _topic_bucket(item: DiscoveredContent) -> str:
        """用 topic_group (粗粒度) 做多样性分桶，回退到 topic_key。"""
        if item.topic_group.strip():
            return ContentDiscoveryEngine._normalize_topic_token(item.topic_group)
        if item.topic_key.strip():
            return ContentDiscoveryEngine._normalize_topic_token(item.topic_key)
        for tag in item.tags:
            token = ContentDiscoveryEngine._normalize_topic_token(tag)
            if token:
                return token
        return ""

    @staticmethod
    def _style_bucket(item: DiscoveredContent) -> str:
        return ContentDiscoveryEngine._normalize_topic_token(normalize_style_key(item.style_key))

    @staticmethod
    def _normalize_topic_token(value: str) -> str:
        compact = re.sub(r"\s+", "", value.strip().lower())
        return compact[:32]

    @staticmethod
    def _style_cap(limit: int) -> int:
        return max(1, min(3, (limit + 1) // 3))

    @staticmethod
    def _source_cap(limit: int) -> int:
        return 2 if limit <= 5 else 3

    @staticmethod
    def infer_style_key(
        *,
        title: str,
        description: str = "",
        reason: str = "",
        source_strategy: str = "",
    ) -> str:
        from openbiliclaw.discovery.style_rules import infer_style_key as _infer

        return _infer(
            title=title,
            description=description,
            reason=reason,
            source_strategy=source_strategy,
        )

    def _cached_result_count(self, results: list[DiscoveredContent]) -> int:
        database = getattr(self, "_database", None)
        if database is None or not results:
            return 0
        keys = [item.bvid or item.content_id for item in results if item.bvid or item.content_id]
        if not keys:
            return 0
        try:
            conn = database.conn
            placeholders = ", ".join("?" for _ in keys)
            cursor = conn.execute(
                f"SELECT COUNT(*) AS count FROM content_cache WHERE bvid IN ({placeholders})",
                keys,
            )
            row = cursor.fetchone()
        except Exception:
            logger.debug("cache_evaluated_results: cached-row count unavailable", exc_info=True)
            return 0
        if row is None:
            return 0
        return int(row["count"] if isinstance(row, dict) else row[0])

    def cache_evaluated_results(self, results: list[DiscoveredContent]) -> int:
        """持久化已评估的发现结果，返回新增缓存行数。"""

        if self._database is None or not results:
            return 0
        before = self._cached_result_count(results)
        self._cache_results(results)
        after = self._cached_result_count(results)
        return max(0, after - before)

    async def normalize_evaluated_results(self, results: list[DiscoveredContent]) -> None:
        """在已评估候选缓存前应用发现 topic 归一化。"""

        await self._normalize_topic_groups(results)
        await self._normalize_topic_keys(results)

    def cache_admission_block_reason(self, item: DiscoveredContent) -> str:
        """返回一个已评估条目不应写入 ``content_cache`` 的原因。"""

        if self._database is None:
            return ""
        viewed_content_keys = self._recent_viewed_content_keys()
        if viewed_content_keys and not self._candidate_view_keys(item).isdisjoint(
            viewed_content_keys
        ):
            return "recently_viewed"

        franchise_key = (item.franchise_key or "").strip().lower()
        if not franchise_key or _POOL_FRANCHISE_QUOTA <= 0:
            return ""
        try:
            existing_franchise_counts = self._database.count_pool_by_franchise()
        except Exception:
            logger.debug("count_pool_by_franchise unavailable", exc_info=True)
            return ""
        if int(existing_franchise_counts.get(franchise_key, 0)) >= _POOL_FRANCHISE_QUOTA:
            return "franchise_quota"
        return ""

    def _cache_results(self, results: list[DiscoveredContent]) -> None:
        if self._database is None or not results:
            return

        # v0.3.50+: pool 级 franchise 配额。没有它，多轮发现都能
        # 通过每批上限 (批 1 中 4 条张雪机车，批 2 中 4 条，...)，
        # pool 最终有 30+ 同 franchise 条目 —— serve 时的多样化器
        # 无法挽救已经 franchise 倾斜的 pool。
        existing_franchise_counts: dict[str, int] = {}
        if _POOL_FRANCHISE_QUOTA > 0:
            try:
                existing_franchise_counts = self._database.count_pool_by_franchise()
            except Exception:
                # 旧 DB 或没有 helper 的测试 stub —— 跳过配额检查，
                # 而不是让整个缓存失败。
                logger.debug("count_pool_by_franchise unavailable", exc_info=True)
                existing_franchise_counts = {}

        persisted: list[DiscoveredContent] = []
        skipped_franchise: dict[str, int] = {}
        skipped_viewed = 0
        round_franchise_counts: dict[str, int] = {}
        viewed_content_keys = self._recent_viewed_content_keys()
        for item in results:
            if viewed_content_keys and not self._candidate_view_keys(item).isdisjoint(
                viewed_content_keys
            ):
                skipped_viewed += 1
                continue
            franchise_key = (item.franchise_key or "").strip().lower()
            if franchise_key and _POOL_FRANCHISE_QUOTA > 0:
                pool_existing = existing_franchise_counts.get(franchise_key, 0)
                round_existing = round_franchise_counts.get(franchise_key, 0)
                if pool_existing + round_existing >= _POOL_FRANCHISE_QUOTA:
                    skipped_franchise[franchise_key] = skipped_franchise.get(franchise_key, 0) + 1
                    continue
            try:
                self._database.cache_content(item.bvid or item.content_id, **item.to_cache_kwargs())
                persisted.append(item)
                if franchise_key:
                    round_franchise_counts[franchise_key] = (
                        round_franchise_counts.get(franchise_key, 0) + 1
                    )
                # P1.8 yield 回填 —— 唯一的 admit 汇聚点。每个
                # 入池条目 (此处的内联 admit B站/抖音，以及同样
                # 经过 ``cache_evaluated_results`` → ``_cache_results``
                # 的共享 candidate-pipeline X/YT/XHS/抖音 路径)
                # 都归功于产生它的 keyword，对 (keyword, content)
                # 幂等。被跳过 (viewed / franchise-quota) 的条目
                # 永不走到这里，所以它们正确地不累计 yield。
                self._backfill_keyword_yield(item)
            except Exception:
                logger.exception("Failed to cache discovered content: %s", item.bvid)

        if skipped_viewed:
            logger.info(
                "pool cache skipped %d recently viewed item(s) before writing content_cache",
                skipped_viewed,
            )

        if skipped_franchise:
            logger.info(
                "pool franchise quota: skipped %d item(s) (cap=%d/franchise; %s)",
                sum(skipped_franchise.values()),
                _POOL_FRANCHISE_QUOTA,
                ", ".join(f"{k}×{v}" for k, v in skipped_franchise.items()),
            )

        # v0.3.45+: 在内存中还持有这些条目时预热推荐 MMR embedding
        # 缓存。没有这个 hook，发现运行后第一次 ``serve()`` 要为
        # 串行 API 调用支付 ~150ms × N —— 预热路径是 L2 SQLite，
        # 所以后续重排 <1s。在 detached task 中触发，这样我们
        # 不会因为慢的 embedding provider 阻塞发现收尾。
        if persisted and self._embedding_service is not None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                # _cache_results 有时从同步测试路径调用；
                # 静默返回而不是抛错。
                return
            loop.create_task(self._warm_mmr_embeddings(persisted))

    def _backfill_keyword_yield(self, item: DiscoveredContent) -> None:
        """把一个入池条目归功于产生它的 keyword (P1.8)，如有。

        当条目不带 ``source_keyword_id`` (每个非搜索 / 旧版本 /
        flag 关闭条目) 或数据库不暴露 yield DAO (旧 stub) 时
        为 no-op。尽力而为: yield 账本失败绝不能中止原本成功的
        pool 入池。
        """
        keyword_id = item.source_keyword_id
        if keyword_id is None:
            return
        increment = getattr(self._database, "increment_keyword_yield", None)
        if not callable(increment):
            return
        content_id = str(item.content_id or item.bvid or "").strip()
        if not content_id:
            return
        try:
            increment(int(keyword_id), content_id)
        except Exception:
            logger.debug("keyword yield backfill failed for id=%s", keyword_id, exc_info=True)

    async def _warm_mmr_embeddings(
        self,
        items: list[DiscoveredContent],
    ) -> None:
        """为新缓存的条目预热 MMR embedding 缓存。

        镜像 ``RecommendationEngine._mmr_embedding_text``，这样
        缓存 key 逐字节对齐。尽力而为 —— 永不抛错。
        """
        if self._embedding_service is None or not items:
            return
        embedding_service = self._embedding_service

        async def _warm(item: DiscoveredContent) -> None:
            text = (f"{item.title or ''} {(item.description or '')[:160]}").strip()[:200]
            if not text:
                return
            try:
                await embedding_service.embed(text)
            except Exception:
                logger.debug(
                    "discovery._warm_mmr_embeddings: embed failed for %s",
                    item.bvid,
                    exc_info=True,
                )

        await asyncio.gather(*(_warm(item) for item in items))
