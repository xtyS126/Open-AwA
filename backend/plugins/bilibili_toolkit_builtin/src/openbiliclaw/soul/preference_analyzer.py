"""基于结构化 LLM 抽取的偏好层分析。"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Protocol, cast

from openbiliclaw.llm.base import LLMProviderError, LLMResponse
from openbiliclaw.llm.json_utils import (
    DEFAULT_STRUCTURED_MAX_TOKENS,
    format_parse_failure,
    parse_llm_json_tolerant,
)
from openbiliclaw.llm.prompts import build_preference_analysis_prompt
from openbiliclaw.llm.service import LLMServiceError
from openbiliclaw.llm.task_options import without_core_memory_kwargs
from openbiliclaw.soul.event_filters import filter_events_by_satisfaction
from openbiliclaw.soul.taxonomy import SupportsEmbed, resolve_category

if TYPE_CHECKING:
    from collections.abc import Iterable

logger = logging.getLogger(__name__)


# 存储中的 disliked_topics 按近度排序并设上限，让列表（以及回显它的
# 偏好分析 prompt）保持有界。下游 prompt 的上限（discovery 里的
# _DISLIKED_TOPICS_CAP 和推荐摘要）等于这个存储上限，因此每个存储
# 的 avoid-topic 都能进入 LLM prompt；当重新被标记的条目不断冒到
# 前面时，最旧的主题会从这一上限之外衰减掉。
_DISLIKED_TOPICS_STORE_CAP = 128

DEFAULT_PREFERENCE_EVENT_CHUNK_SIZE = 200
MAX_CONCURRENT_PREFERENCE_CHUNKS = 16
INIT_COGNITION_CONTEXT_KEY = "_init_cognition_context"
_INIT_AWARENESS_CANDIDATES_CAP = 12
_INIT_INSIGHT_CANDIDATES_CAP = 8

_COMPACT_METADATA_KEYS = frozenset(
    {
        "source_platform",
        "up_name",
        "author",
        "bvid",
        "aid",
        "content_id",
        "folder",
        "duration",
        "watch_seconds",
        "video_duration_seconds",
        "feedback_type",
        "reaction",
        "signal_strength",
    }
)


class SupportsCoreMemoryTask(Protocol):
    async def complete_structured_task(
        self,
        *,
        system_instruction: str,
        user_input: str,
        history: list[dict[str, str]] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        caller: str = "",
        inject_core_memory: bool = True,
    ) -> LLMResponse: ...


class PreferenceAnalysisError(Exception):
    """当偏好抽取失败或返回无效数据时抛出。"""


@dataclass
class PreferenceAnalyzer:
    """把近期事件分析为结构化的偏好画像。"""

    registry: SupportsCoreMemoryTask
    decay_factor_per_week: float = 0.9
    min_interest_weight: float = 0.05
    # EMA 混合：0.3 * 最新批次 + 0.7 * 先前混合。这样选是为了让一次性的
    # 跨平台批次不会抹掉长期积累的 bilibili 历史。
    source_mix_blend_alpha: float = 0.3
    # v0.3.x 事件满意度信号：为 True 时，在构造 LLM prompt 之前丢弃
    # 被动的负向事件（如快速退出）。显式的 dislike 反馈作为负向证据
    # 保留，让分析器可以更新 disliked_topics，又不会把那个标题误判
    # 为正向兴趣。
    satisfaction_filter_enabled: bool = True
    embedding_service: SupportsEmbed | None = None
    max_prompt_chars: int = 24_000
    compact_title_chars: int = 180
    compact_context_chars: int = 600
    compact_metadata_value_chars: int = 300

    def __post_init__(self) -> None:
        if not hasattr(self.registry, "complete_structured_task"):
            raise TypeError(
                "PreferenceAnalyzer requires a service with complete_structured_task()."
            )

    async def analyze_events(
        self,
        *,
        events: list[dict[str, object]],
        existing_preference: dict[str, object],
        event_chunk_size: int = 0,
    ) -> dict[str, object]:
        """执行结构化抽取，并把结果与现有偏好状态合并。

        当 ``event_chunk_size`` > 0 且事件数达到该值时，输入被切分为
        每块至多 ``event_chunk_size`` 条事件的分块，每块在独立的 LLM
        调用里并发分析。每块的部分偏好随后通过常规的
        ``merge_preferences`` 路径折叠进 ``existing_preference``，
        保留加权兴趣合并和认知风格并集。适用于对延迟敏感的流程
        （例如初始化时面对数百条历史事件，单次 max-thinking 调用整批
        会阻塞数分钟）。
        """
        events = self._maybe_filter_events(events)
        if event_chunk_size > 0 and len(events) >= event_chunk_size:
            return await self._analyze_events_chunked(
                events=events,
                existing_preference=existing_preference,
                chunk_size=event_chunk_size,
            )

        whole_batch_prompt = build_preference_analysis_prompt(
            events=events,
            existing_preference=existing_preference,
        )
        prompt_chars = self._prompt_char_count(whole_batch_prompt)
        should_chunk_by_budget = self.max_prompt_chars > 0 and prompt_chars > self.max_prompt_chars
        if should_chunk_by_budget:
            initial_chunk_size = (
                event_chunk_size
                if event_chunk_size > 0
                else self._estimate_budget_chunk_size(
                    event_count=len(events),
                    prompt_chars=prompt_chars,
                )
            )
            return await self._analyze_events_chunked(
                events=events,
                existing_preference=existing_preference,
                chunk_size=initial_chunk_size,
            )
        return await self._analyze_events_single(
            events=events,
            existing_preference=existing_preference,
        )

    def _maybe_filter_events(
        self,
        events: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        """开关打开时丢弃被动的负向事件。

        包含 ``"unknown"`` 桶是为了让分类之前的旧行（NULL
        ``inferred_satisfaction``）仍能喂给分析器。包含 ``"neutral"``
        是因为搜索 / 浅浏览不是满意度证据，但仍是有效的偏好上下文。
        显式的 dislike 反馈被保留，以便喂给 disliked_topics。
        """
        if not self.satisfaction_filter_enabled:
            return events
        filtered = [event for event in events if self._keeps_event_under_satisfaction_filter(event)]
        if len(filtered) != len(events):
            logger.info(
                "satisfaction_filter dropped %d/%d events before preference analysis",
                len(events) - len(filtered),
                len(events),
            )
        return filtered

    @staticmethod
    def _keeps_event_under_satisfaction_filter(event: dict[str, object]) -> bool:
        if event in filter_events_by_satisfaction(
            [event], modes=frozenset({"positive", "neutral", "unknown"})
        ):
            return True
        return PreferenceAnalyzer._is_explicit_negative_feedback(event)

    @staticmethod
    def _is_explicit_negative_feedback(event: dict[str, object]) -> bool:
        event_type = str(event.get("event_type") or event.get("type") or "").strip().lower()
        metadata = event.get("metadata")
        feedback_type = ""
        reaction = ""
        if isinstance(metadata, dict):
            feedback_type = str(metadata.get("feedback_type") or "").strip().lower()
            reaction = str(metadata.get("reaction") or "").strip().lower()
        return event_type in {"feedback", "dislike"} and (
            feedback_type == "dislike" or reaction == "thumbs_down" or event_type == "dislike"
        )

    async def _analyze_events_single(
        self,
        *,
        events: list[dict[str, object]],
        existing_preference: dict[str, object],
    ) -> dict[str, object]:
        messages = build_preference_analysis_prompt(
            events=events,
            existing_preference=existing_preference,
        )
        try:
            response = await self._complete_cacheable_preference_task(
                system_instruction=messages[0]["content"],
                user_input=messages[1]["content"],
                max_tokens=DEFAULT_STRUCTURED_MAX_TOKENS,
                caller="soul.preference",
            )
        except (LLMProviderError, LLMServiceError) as exc:
            raise PreferenceAnalysisError(str(exc)) from exc

        raw_preference = self._parse_response(response.content)
        normalized = await self._normalize_and_resolve(raw_preference)
        merged = self.merge_preferences(existing_preference, normalized, now=datetime.now())
        init_cognition = self._extract_init_cognition_context(raw_preference)
        if init_cognition:
            merged[INIT_COGNITION_CONTEXT_KEY] = init_cognition
        merged["source_platform_mix"] = self._merge_source_mix(
            existing_preference.get("source_platform_mix"),
            self.compute_source_platform_mix(events),
        )
        # 保留 LLM 输出里的 cognitive_style（PreferenceLayer 不建模该字段）
        raw_cs = raw_preference.get("cognitive_style")
        if isinstance(raw_cs, list):
            merged["cognitive_style"] = [str(s) for s in raw_cs if s]
        elif "cognitive_style" not in merged:
            existing_cs = existing_preference.get("cognitive_style")
            if isinstance(existing_cs, list):
                merged["cognitive_style"] = existing_cs
        return merged

    async def _complete_cacheable_preference_task(
        self,
        *,
        system_instruction: str,
        user_input: str,
        max_tokens: int,
        caller: str,
    ) -> LLMResponse:
        """执行偏好抽取，不带动态核心记忆的 system 后缀。"""
        kwargs: dict[str, Any] = {
            "system_instruction": system_instruction,
            "user_input": user_input,
            "max_tokens": max_tokens,
            "caller": caller,
        }
        complete = cast("Any", self.registry.complete_structured_task)
        kwargs.update(without_core_memory_kwargs(complete))
        return cast("LLMResponse", await complete(**kwargs))

    def _prompt_char_count(self, messages: list[dict[str, str]]) -> int:
        return sum(len(message.get("content", "")) for message in messages)

    def _prompt_fits_budget(self, messages: list[dict[str, str]]) -> bool:
        return (
            self.max_prompt_chars <= 0 or self._prompt_char_count(messages) <= self.max_prompt_chars
        )

    def _estimate_budget_chunk_size(self, *, event_count: int, prompt_chars: int) -> int:
        if event_count <= 0:
            return 1
        if self.max_prompt_chars <= 0 or prompt_chars <= self.max_prompt_chars:
            return max(1, event_count)
        estimated = event_count * self.max_prompt_chars // max(prompt_chars, 1)
        return max(1, min(event_count, estimated))

    @staticmethod
    def _is_context_overflow_error(exc: PreferenceAnalysisError) -> bool:
        text = str(exc).lower()
        markers = (
            "context length",
            "maximum context",
            "n_ctx",
            "n_keep",
            "tokens to keep",
            "prompt is too long",
            "input is too long",
        )
        return any(marker in text for marker in markers)

    def _compact_event_for_prompt(self, event: dict[str, object]) -> dict[str, object]:
        compact: dict[str, object] = {}
        for key in (
            "event_type",
            "type",
            "created_at",
            "inferred_satisfaction",
            "satisfaction_reason",
        ):
            value = event.get(key)
            if value not in (None, ""):
                compact[key] = value

        title = event.get("title")
        if title not in (None, ""):
            compact["title"] = self._truncate_for_prompt(title, self.compact_title_chars)

        context = event.get("context")
        if context not in (None, ""):
            compact["context"] = self._truncate_for_prompt(context, self.compact_context_chars)

        url = event.get("url")
        if url not in (None, ""):
            compact["url"] = self._truncate_for_prompt(url, self.compact_metadata_value_chars)

        metadata = event.get("metadata")
        if isinstance(metadata, dict):
            compact_metadata: dict[str, object] = {}
            for key in sorted(_COMPACT_METADATA_KEYS):
                value = metadata.get(key)
                if value in (None, ""):
                    continue
                if isinstance(value, str):
                    compact_metadata[key] = self._truncate_for_prompt(
                        value,
                        self.compact_metadata_value_chars,
                    )
                elif isinstance(value, bool | int | float):
                    compact_metadata[key] = value
            if compact_metadata:
                compact["metadata"] = compact_metadata
        return compact

    def _safe_compact_event_for_invalid_json_retry(
        self,
        event: dict[str, object],
    ) -> dict[str, object]:
        """为重试模型拒答构造一份更低风险的 prompt 事件。

        长自然语言页面上下文可能触发 provider 的安全拒答，即使偏好
        抽取本身是无害的。仅保留 title/URL/source 的重试在保留有效
        偏好信号的同时，移除可能冒犯的正文。
        """
        compact = self._compact_event_for_prompt(event)
        compact.pop("context", None)
        return compact

    @staticmethod
    def _truncate_for_prompt(value: object, max_chars: int) -> str:
        if max_chars <= 0:
            return ""
        text = str(value or "").strip()
        if len(text) <= max_chars:
            return text
        if max_chars <= 3:
            return text[:max_chars]
        return text[: max_chars - 3].rstrip() + "..."

    async def _analyze_events_chunked(
        self,
        *,
        events: list[dict[str, object]],
        existing_preference: dict[str, object],
        chunk_size: int,
    ) -> dict[str, object]:
        """把事件切成有界的并发分块，然后折叠。"""
        import asyncio as _asyncio

        chunk_size = max(1, chunk_size)
        chunks = [events[i : i + chunk_size] for i in range(0, len(events), chunk_size)]
        logger.info(
            "analyze_events chunked: total_events=%d chunks=%d chunk_size=%d",
            len(events),
            len(chunks),
            chunk_size,
        )

        # 每块都对着空种子分析，这样 LLM 调用真正独立 —— 我们不希望
        # 一块的部分状态泄漏进另一块的 prompt。下面的最终合并步骤
        # 用 merge_preferences 把每块归一化后的输出折叠进真实的
        # ``existing_preference``，merge_preferences 已经处理跨调用的
        # 加权兴趣聚合。
        async def _run_chunk_once(
            chunk: list[dict[str, object]],
        ) -> tuple[dict[str, object], dict[str, object]]:
            messages = build_preference_analysis_prompt(
                events=chunk,
                existing_preference={},
            )
            try:
                response = await self._complete_cacheable_preference_task(
                    system_instruction=messages[0]["content"],
                    user_input=messages[1]["content"],
                    max_tokens=DEFAULT_STRUCTURED_MAX_TOKENS,
                    caller="soul.preference.chunk",
                )
            except (LLMProviderError, LLMServiceError) as exc:
                raise PreferenceAnalysisError(str(exc)) from exc
            raw = self._parse_response(response.content, log_error=False)
            return raw, await self._normalize_and_resolve(raw)

        async def _retry_single_event_without_context(
            event: dict[str, object],
        ) -> tuple[dict[str, object], dict[str, object]] | None:
            safe_event = self._safe_compact_event_for_invalid_json_retry(event)
            if not safe_event:
                return None
            safe_messages = build_preference_analysis_prompt(
                events=[safe_event],
                existing_preference={},
            )
            if not self._prompt_fits_budget(safe_messages):
                logger.warning(
                    "preference event skipped because safe compact prompt still exceeds "
                    "budget: title=%r prompt_chars=%d budget=%d",
                    str(event.get("title", "")),
                    self._prompt_char_count(safe_messages),
                    self.max_prompt_chars,
                )
                return None
            try:
                return await _run_chunk_once([safe_event])
            except PreferenceAnalysisError as retry_exc:
                if retry_exc.__cause__ is not None and not self._is_context_overflow_error(
                    retry_exc
                ):
                    raise
                logger.warning(
                    "preference chunk skipped after safe compact retry failed: title=%r",
                    str(event.get("title", "")),
                )
                return None

        async def _split_or_compact_chunk(
            chunk: list[dict[str, object]],
        ) -> list[tuple[dict[str, object], dict[str, object]]]:
            if len(chunk) <= 1:
                compact = self._compact_event_for_prompt(chunk[0]) if chunk else {}
                compact_messages = build_preference_analysis_prompt(
                    events=[compact],
                    existing_preference={},
                )
                if not self._prompt_fits_budget(compact_messages):
                    logger.warning(
                        "preference event skipped because compact prompt still exceeds "
                        "budget: title=%r prompt_chars=%d budget=%d",
                        str(chunk[0].get("title", ""))
                        if chunk and isinstance(chunk[0], dict)
                        else "",
                        self._prompt_char_count(compact_messages),
                        self.max_prompt_chars,
                    )
                    return []
                return [await _run_chunk_once([compact])]
            midpoint = max(1, len(chunk) // 2)
            left, right = await _asyncio.gather(
                _run_chunk_resilient(chunk[:midpoint]),
                _run_chunk_resilient(chunk[midpoint:]),
            )
            return [*left, *right]

        async def _run_chunk_resilient(
            chunk: list[dict[str, object]],
        ) -> list[tuple[dict[str, object], dict[str, object]]]:
            messages = build_preference_analysis_prompt(events=chunk, existing_preference={})
            if not self._prompt_fits_budget(messages):
                return await _split_or_compact_chunk(chunk)
            try:
                return [await _run_chunk_once(chunk)]
            except PreferenceAnalysisError as exc:
                if exc.__cause__ is not None:
                    if self._is_context_overflow_error(exc):
                        logger.warning(
                            "preference chunk exceeded provider context; splitting: "
                            "events=%d error=%s",
                            len(chunk),
                            exc,
                        )
                        return await _split_or_compact_chunk(chunk)
                    raise
                # 无效 JSON / 模型拒答通常是内容局部的：拆分批次以隔离
                # 出问题的那条事件，然后如果仅用 title/source 重试仍被
                # 拒答，就只跳过那最后一条事件。
                if len(chunk) <= 1:
                    event = chunk[0] if chunk else {}
                    if isinstance(event, dict):
                        retry_outcome = await _retry_single_event_without_context(event)
                        if retry_outcome is not None:
                            return [retry_outcome]
                    logger.warning(
                        "preference chunk skipped after invalid LLM response: title=%r",
                        str(event.get("title", "")) if isinstance(event, dict) else "",
                    )
                    return []
                return await _split_or_compact_chunk(chunk)

        outcome_groups: list[list[tuple[dict[str, object], dict[str, object]]]] = []
        for batch_start in range(0, len(chunks), MAX_CONCURRENT_PREFERENCE_CHUNKS):
            batch = chunks[batch_start : batch_start + MAX_CONCURRENT_PREFERENCE_CHUNKS]
            outcome_groups.extend(
                await _asyncio.gather(*(_run_chunk_resilient(chunk) for chunk in batch))
            )
        outcomes = [item for group in outcome_groups for item in group]

        # 把每块归一化后的偏好逐一折叠进运行中的合并结果。
        # merge_preferences 已做加权兴趣聚合 + dislike 列表并集，所以
        # 级联调用的聚合效果在精神上与单次大 prompt 分析相当。
        merged: dict[str, object] = dict(existing_preference)
        cognitive_style_union: list[str] = []
        for raw_preference, normalized in outcomes:
            merged = self.merge_preferences(merged, normalized, now=datetime.now())
            raw_cs = raw_preference.get("cognitive_style")
            if isinstance(raw_cs, list):
                for item in raw_cs:
                    if item and str(item) not in cognitive_style_union:
                        cognitive_style_union.append(str(item))

        merged["source_platform_mix"] = self._merge_source_mix(
            existing_preference.get("source_platform_mix"),
            self.compute_source_platform_mix(events),
        )
        if cognitive_style_union:
            merged["cognitive_style"] = cognitive_style_union
        elif "cognitive_style" not in merged:
            existing_cs = existing_preference.get("cognitive_style")
            if isinstance(existing_cs, list):
                merged["cognitive_style"] = existing_cs
        init_cognition = self._merge_init_cognition_contexts(
            raw_preference for raw_preference, _normalized in outcomes
        )
        if init_cognition:
            merged[INIT_COGNITION_CONTEXT_KEY] = init_cognition
        logger.info(
            "analyze_events chunked done: total_events=%d chunks=%d",
            len(events),
            len(chunks),
        )
        return merged

    @staticmethod
    def compute_source_platform_mix(
        events: list[dict[str, object]],
    ) -> dict[str, float]:
        """按 source_platform 统计事件数，返回归一化的份额 dict。"""
        counts: dict[str, int] = {}
        for event in events:
            if not isinstance(event, dict):
                continue
            metadata = event.get("metadata")
            source = ""
            if isinstance(metadata, dict):
                raw = metadata.get("source_platform")
                if isinstance(raw, str):
                    source = raw.strip()
            if not source:
                # 早于 source_platform 字段的事件都是 bilibili。
                source = "bilibili"
            counts[source] = counts.get(source, 0) + 1
        total = sum(counts.values())
        if total == 0:
            return {}
        return {name: count / total for name, count in counts.items()}

    def _merge_init_cognition_contexts(
        self,
        raw_preferences: Iterable[dict[str, object]],
    ) -> dict[str, object]:
        awareness: list[dict[str, object]] = []
        insights: list[dict[str, object]] = []
        seen_awareness: set[str] = set()
        seen_insights: set[str] = set()
        for raw in raw_preferences:
            context = self._extract_init_cognition_context(raw)
            for item in self._as_list(context.get("awareness")):
                if not isinstance(item, dict):
                    continue
                key = self._normalize_context_text(str(item.get("observation", "")))
                if not key or key in seen_awareness:
                    continue
                seen_awareness.add(key)
                awareness.append(item)
                if len(awareness) >= _INIT_AWARENESS_CANDIDATES_CAP:
                    break
            for item in self._as_list(context.get("insights")):
                if not isinstance(item, dict):
                    continue
                key = self._normalize_context_text(str(item.get("hypothesis", "")))
                if not key or key in seen_insights:
                    continue
                seen_insights.add(key)
                insights.append(item)
                if len(insights) >= _INIT_INSIGHT_CANDIDATES_CAP:
                    break
            if (
                len(awareness) >= _INIT_AWARENESS_CANDIDATES_CAP
                and len(insights) >= _INIT_INSIGHT_CANDIDATES_CAP
            ):
                break
        result: dict[str, object] = {}
        if awareness:
            result["awareness"] = awareness
        if insights:
            result["insights"] = insights
        return result

    def _extract_init_cognition_context(
        self, raw_preference: dict[str, object]
    ) -> dict[str, object]:
        awareness = self._normalize_init_awareness_candidates(
            raw_preference.get("awareness_candidates")
        )
        insights = self._normalize_init_insight_candidates(raw_preference.get("insight_candidates"))
        result: dict[str, object] = {}
        if awareness:
            result["awareness"] = awareness
        if insights:
            result["insights"] = insights
        return result

    def _normalize_init_awareness_candidates(self, raw_value: object) -> list[dict[str, object]]:
        candidates: list[dict[str, object]] = []
        seen: set[str] = set()
        for raw_item in self._as_list(raw_value):
            if not isinstance(raw_item, dict):
                continue
            observation = str(raw_item.get("observation", "")).strip()
            key = self._normalize_context_text(observation)
            if not key or key in seen:
                continue
            seen.add(key)
            item: dict[str, object] = {
                "date": str(raw_item.get("date") or "init"),
                "observation": observation,
                "trend": str(raw_item.get("trend", "")).strip(),
                "emotion_guess": str(raw_item.get("emotion_guess", "")).strip(),
            }
            candidates.append(item)
            if len(candidates) >= _INIT_AWARENESS_CANDIDATES_CAP:
                break
        return candidates

    def _normalize_init_insight_candidates(self, raw_value: object) -> list[dict[str, object]]:
        candidates: list[dict[str, object]] = []
        seen: set[str] = set()
        for raw_item in self._as_list(raw_value):
            if not isinstance(raw_item, dict):
                continue
            hypothesis = str(raw_item.get("hypothesis", "")).strip()
            key = self._normalize_context_text(hypothesis)
            if not key or key in seen:
                continue
            seen.add(key)
            evidence = self._as_str_list(raw_item.get("evidence", []))[:5]
            item: dict[str, object] = {
                "hypothesis": hypothesis,
                "evidence": evidence,
                "confidence": self._clamp_weight(self._to_float(raw_item.get("confidence", 0.5))),
                "validated": bool(raw_item.get("validated", False)),
                "created_at": str(raw_item.get("created_at") or "init"),
            }
            candidates.append(item)
            if len(candidates) >= _INIT_INSIGHT_CANDIDATES_CAP:
                break
        return candidates

    @staticmethod
    def _normalize_context_text(value: str) -> str:
        return " ".join(value.strip().lower().split())

    def _merge_source_mix(
        self,
        existing: object,
        batch: dict[str, float],
    ) -> dict[str, float]:
        """用 EMA 把已持久化的混合与最新批次混合。"""
        prior: dict[str, float] = {}
        if isinstance(existing, dict):
            for key, value in existing.items():
                if isinstance(key, str) and key:
                    try:
                        prior[key] = float(value)
                    except (TypeError, ValueError):
                        continue
        if not batch:
            return prior
        if not prior:
            return dict(batch)
        alpha = max(0.0, min(1.0, self.source_mix_blend_alpha))
        keys = set(prior) | set(batch)
        blended = {
            key: alpha * batch.get(key, 0.0) + (1.0 - alpha) * prior.get(key, 0.0) for key in keys
        }
        total = sum(blended.values())
        if total <= 0:
            return {}
        return {key: round(value / total, 4) for key, value in blended.items() if value > 0}

    def merge_preferences(
        self,
        existing_preference: dict[str, object],
        new_preference: dict[str, object],
        *,
        now: datetime,
    ) -> dict[str, object]:
        """合并并衰减偏好状态。"""
        existing_interests = self._decay_interests(
            existing_preference.get("interests", []),
            now=now,
        )
        merged_interests: dict[tuple[str, str], dict[str, object]] = {
            (str(item["name"]), str(item["category"])): item for item in existing_interests
        }
        active_aliases = self._alias_key_map(merged_interests.values())
        archived_interests = [
            dict(item)
            for item in self._as_list(existing_preference.get("archived_interests", []))
            if isinstance(item, dict) and str(item.get("name", "")).strip()
        ]
        archived_by_key: dict[tuple[str, str], dict[str, object]] = {
            (str(item.get("name", "")), str(item.get("category", ""))): item
            for item in archived_interests
        }
        archived_aliases = self._alias_key_map(archived_interests)
        reactivated_archive_keys: set[tuple[str, str]] = set()

        for item in self._as_list(new_preference.get("interests", [])):
            if not isinstance(item, dict):
                continue
            raw_key = (str(item["name"]), str(item["category"]))
            key = raw_key
            existing = merged_interests.get(key)
            if existing is None:
                alias_key = active_aliases.get(raw_key)
                if alias_key is not None:
                    key = alias_key
                    existing = merged_interests.get(key)
            if existing is None:
                archived_key = key if key in archived_by_key else archived_aliases.get(raw_key)
                archived = archived_by_key.get(archived_key) if archived_key is not None else None
                if archived is not None:
                    reactivated_archive_keys.add(archived_key)  # type: ignore[arg-type]
                    canonical_key = (
                        str(archived.get("name", "")),
                        str(archived.get("category", "")),
                    )
                    merged_interests[canonical_key] = self._merge_interest_record(
                        archived,
                        item,
                        now=now,
                    )
                    active_aliases = self._alias_key_map(merged_interests.values())
                    continue
                merged_interests[key] = {
                    **item,
                    "first_seen": now.isoformat(),
                    "last_seen": now.isoformat(),
                }
                active_aliases = self._alias_key_map(merged_interests.values())
                continue
            if key in archived_by_key:
                reactivated_archive_keys.add(key)
            merged_interests[key] = self._merge_interest_record(existing, item, now=now)
            active_aliases = self._alias_key_map(merged_interests.values())

        # 新旧 UP 用户取并集，跨批次累积。
        # 单个批次可能只提到一个子集；直接替换会丢失此前已确认的 UP
        # 用户。
        new_up = self._as_str_list(new_preference.get("favorite_up_users", []))
        old_up = self._as_str_list(existing_preference.get("favorite_up_users", []))
        # 新旧取并集以跨批次累积。一个批次可能只提到 UP 用户的子集，
        # 因此用本批次列表替换（之前的行为）会在批次提到任何创作者时
        # 静默丢弃之前已确认的创作者。
        favorite_up_users = sorted(set(old_up) | set(new_up))
        # 按近度排序的并集：本轮 avoid-topics 在前，让最近被强化的主题
        # 在下游 top-N 截断中存活，且每轮都被重新标记的主题会持续冒到
        # 前面。旧的字母序排序意味着 top-N 截断保留的是字母序靠前的
        # 主题，而不是最新/最相关的。最旧的主题会越过存储上限衰减掉。
        disliked_topics = list(
            dict.fromkeys(
                [
                    *self._as_str_list(new_preference.get("disliked_topics", [])),
                    *self._as_str_list(existing_preference.get("disliked_topics", [])),
                ]
            )
        )[:_DISLIKED_TOPICS_STORE_CAP]

        default_preference = self._default_preference()
        style = self._as_dict(default_preference["style"]).copy()
        style.update(self._as_dict(existing_preference.get("style", {})))
        style.update(self._as_dict(new_preference.get("style", {})))
        context = self._as_dict(default_preference["context"]).copy()
        context.update(self._as_dict(existing_preference.get("context", {})))
        context.update(self._as_dict(new_preference.get("context", {})))

        # 保留新分析里的 speculative_interests（用于 speculator 播种）
        speculative = self._as_list(new_preference.get("speculative_interests", []))

        merged = {
            "interests": sorted(
                merged_interests.values(),
                key=lambda item: self._to_float(item.get("weight", 0.0)),
                reverse=True,
            ),
            "style": style,
            "context": context,
            "exploration_openness": self._clamp_weight(
                self._to_float(
                    new_preference.get(
                        "exploration_openness",
                        existing_preference.get("exploration_openness", 0.5),
                    )
                )
            ),
            "disliked_topics": disliked_topics,
            "favorite_up_users": favorite_up_users,
            "speculative_interests": speculative,
            "archived_interests": [
                item
                for item in archived_interests
                if (str(item.get("name", "")), str(item.get("category", "")))
                not in reactivated_archive_keys
            ],
        }
        return merged

    def _decay_interests(
        self,
        interests: object,
        *,
        now: datetime,
    ) -> list[dict[str, object]]:
        if not isinstance(interests, list):
            return []

        decayed: list[dict[str, object]] = []
        for raw_item in interests:
            if not isinstance(raw_item, dict):
                continue
            item = self._normalize_interest(raw_item)
            last_seen_text = str(item.get("last_seen") or "")
            try:
                last_seen = datetime.fromisoformat(last_seen_text) if last_seen_text else now
            except ValueError:
                last_seen = now
            weeks = max((now - last_seen).days, 0) / 7
            decayed_weight = self._clamp_weight(
                self._to_float(item.get("weight", 0.0)) * (self.decay_factor_per_week**weeks)
            )
            if decayed_weight < self.min_interest_weight:
                continue
            item["weight"] = decayed_weight
            decayed.append(item)
        return decayed

    def _parse_response(self, content: str, *, log_error: bool = True) -> dict[str, object]:
        parsed = parse_llm_json_tolerant(content)
        if parsed is None:
            exc = ValueError("unrecoverable JSON")
            if log_error:
                logger.error(
                    "%s",
                    format_parse_failure(content, exc, label="preference analysis"),
                )
            raise PreferenceAnalysisError(
                f"LLM returned invalid JSON for preference analysis "
                f"(raw_len={len(content.strip())})"
            )
        if not isinstance(parsed, dict):
            raise PreferenceAnalysisError("LLM preference response must be a JSON object.")
        return {key: value for key, value in parsed.items()}

    def _normalize_preference(self, raw_preference: dict[str, object]) -> dict[str, object]:
        normalized = self._default_preference()
        style = self._as_dict(normalized["style"]).copy()
        style.update(self._as_dict(raw_preference.get("style")))
        context = self._as_dict(normalized["context"]).copy()
        context.update(self._as_dict(raw_preference.get("context")))
        normalized["interests"] = [
            self._normalize_interest(item)
            for item in self._as_list(raw_preference.get("interests", []))
            if isinstance(item, dict)
        ]
        normalized["style"] = style
        normalized["context"] = context
        normalized["exploration_openness"] = self._clamp_weight(
            self._to_float(raw_preference.get("exploration_openness", 0.5))
        )
        normalized["disliked_topics"] = self._as_str_list(raw_preference.get("disliked_topics", []))
        normalized["favorite_up_users"] = self._as_str_list(
            raw_preference.get("favorite_up_users", [])
        )
        # 保留 LLM 输出里的 speculative interests
        raw_speculative = self._as_list(raw_preference.get("speculative_interests", []))
        normalized["speculative_interests"] = [
            {
                "name": str(item.get("name", "")).strip(),
                "category": str(item.get("category", "")).strip(),
                "weight": self._clamp_weight(self._to_float(item.get("weight", 0.4))),
                "reason": str(item.get("reason", "")),
            }
            for item in raw_speculative
            if isinstance(item, dict) and str(item.get("name", "")).strip()
        ]
        return normalized

    async def _normalize_and_resolve(self, raw_preference: dict[str, object]) -> dict[str, object]:
        normalized = self._normalize_preference(raw_preference)
        for key in ("interests", "speculative_interests"):
            items = normalized.get(key, [])
            if not isinstance(items, list):
                continue
            for item in items:
                if isinstance(item, dict):
                    item["category"] = await resolve_category(
                        str(item.get("category", "")),
                        self.embedding_service,
                    )
        return normalized

    def _normalize_interest(self, raw_item: dict[str, object]) -> dict[str, object]:
        name = str(raw_item.get("name", "")).strip()
        normalized = {
            "name": str(raw_item.get("name", "")).strip(),
            "category": str(raw_item.get("category", "")).strip(),
            "weight": self._clamp_weight(self._to_float(raw_item.get("weight", 0.0))),
            "first_seen": raw_item.get("first_seen", ""),
            "last_seen": raw_item.get("last_seen", ""),
            "source": str(raw_item.get("source", "")).strip(),
        }
        aliases = self._interest_aliases(raw_item, canonical_name=name)
        if aliases:
            normalized["aliases"] = aliases
        return normalized

    def _merge_interest_record(
        self,
        existing: dict[str, object],
        incoming: dict[str, object],
        *,
        now: datetime,
    ) -> dict[str, object]:
        canonical_name = str(existing.get("name", "")).strip()
        canonical_category = str(existing.get("category", "")).strip()
        merged = {
            **existing,
            **incoming,
            "name": canonical_name,
            "category": canonical_category,
            "first_seen": existing.get("first_seen") or now.isoformat(),
            "last_seen": now.isoformat(),
            "weight": self._clamp_weight(
                max(
                    self._to_float(existing.get("weight", 0.0)),
                    self._to_float(incoming.get("weight", 0.0)),
                )
            ),
        }
        aliases = self._merged_interest_aliases(existing, incoming, canonical_name)
        if aliases:
            merged["aliases"] = aliases
        else:
            merged.pop("aliases", None)
        return merged

    def _alias_key_map(self, interests: Iterable[object]) -> dict[tuple[str, str], tuple[str, str]]:
        result: dict[tuple[str, str], tuple[str, str]] = {}
        for item in interests:
            if not isinstance(item, dict):
                continue
            canonical_name = str(item.get("name", "")).strip()
            category = str(item.get("category", "")).strip()
            canonical_key = (canonical_name, category)
            for alias in self._interest_aliases(item, canonical_name=canonical_name):
                result.setdefault((alias, category), canonical_key)
        return result

    def _merged_interest_aliases(
        self,
        existing: dict[str, object],
        incoming: dict[str, object],
        canonical_name: str,
    ) -> list[str]:
        raw_terms: list[object] = [*self._interest_aliases(existing, canonical_name=canonical_name)]
        incoming_name = str(incoming.get("name", "")).strip()
        if incoming_name:
            raw_terms.append(incoming_name)
        raw_terms.extend(self._interest_aliases(incoming, canonical_name=canonical_name))
        return self._clean_aliases(raw_terms, canonical_name=canonical_name)

    def _interest_aliases(
        self,
        item: dict[str, object],
        *,
        canonical_name: str,
    ) -> list[str]:
        return self._clean_aliases(
            self._as_list(item.get("aliases", [])),
            canonical_name=canonical_name,
        )

    def _clean_aliases(self, raw_aliases: object, *, canonical_name: str) -> list[str]:
        aliases: list[str] = []
        seen: set[str] = set()
        canonical_norm = canonical_name.strip().casefold()
        for raw_alias in self._as_list(raw_aliases):
            alias = str(raw_alias).strip()
            alias_norm = alias.casefold()
            if not alias or not alias_norm or alias_norm == canonical_norm or alias_norm in seen:
                continue
            aliases.append(alias)
            seen.add(alias_norm)
        return aliases

    @staticmethod
    def _as_dict(raw_value: object) -> dict[str, object]:
        return raw_value if isinstance(raw_value, dict) else {}

    @staticmethod
    def _as_list(raw_value: object) -> list[object]:
        return raw_value if isinstance(raw_value, list) else []

    @staticmethod
    def _as_str_list(raw_value: object) -> list[str]:
        if not isinstance(raw_value, list):
            return []
        return [str(item) for item in raw_value]

    @staticmethod
    def _to_float(raw_value: object) -> float:
        if isinstance(raw_value, bool):
            return float(raw_value)
        if isinstance(raw_value, (int, float)):
            return float(raw_value)
        if isinstance(raw_value, str):
            try:
                return float(raw_value)
            except ValueError:
                return 0.0
        return 0.0

    @staticmethod
    def _clamp_weight(value: float) -> float:
        return max(0.0, min(1.0, round(value, 4)))

    @staticmethod
    def _default_preference() -> dict[str, object]:
        return {
            "interests": [],
            "style": {
                "preferred_duration": "",
                "preferred_pace": "",
                "quality_sensitivity": 0.5,
                "humor_preference": 0.5,
                "depth_preference": 0.5,
            },
            "context": {
                "weekday_patterns": "",
                "weekend_patterns": "",
                "time_of_day_patterns": "",
                "session_type": "",
            },
            "exploration_openness": 0.5,
            "disliked_topics": [],
            "favorite_up_users": [],
        }
