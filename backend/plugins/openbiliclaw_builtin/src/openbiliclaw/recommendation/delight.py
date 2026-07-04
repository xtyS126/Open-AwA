"""Delight Scorer —— 识别会让用户惊喜的内容。

计算一个复合 ``delight_score``，度量一条内容与用户 soul profile 的
共鸣深度 —— 不仅是表面兴趣，还包括深层需求、活跃洞察假设和潜在
好奇心模式。

此分数刻意与 PoolCurator 的 ``rec_score``（处理常规推荐批次的
新鲜度/疲劳/单调）分离。delight 分数聚焦于**深度共鸣**，而非
近因性或多样性。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from openbiliclaw.llm.json_utils import extract_llm_json_list
from openbiliclaw.llm.prompt_cache import PromptLayerRenderCache, profile_prompt_layers
from openbiliclaw.llm.prompts import build_delight_score_batch_prompt
from openbiliclaw.llm.task_options import without_core_memory_kwargs

if TYPE_CHECKING:
    from openbiliclaw.llm.embedding import SupportsEmbeddingService

logger = logging.getLogger(__name__)


class SupportsDelightCandidate(Protocol):
    bvid: str
    title: str
    description: str
    view_count: int
    like_count: int
    topic_key: str
    topic_group: str
    source_strategy: str
    relevance_score: float


class SupportsRecommendationSignalStore(Protocol):
    def get_recent_recommendation_signals(self, *, limit: int = ...) -> list[dict[str, Any]]: ...


@dataclass(frozen=True)
class DelightSignals:
    """组成 delight 分数的各个信号分量。"""

    deep_need_alignment: float = 0.0
    insight_resonance: float = 0.0
    # 与用户实际 top likes 的嵌入匹配 —— 这是携带 deep_needs 单独
    # 遗漏的娱乐/玩乐维度的信号（deep_needs 对许多用户偏分析向）。
    likes_alignment: float = 0.0
    novelty_factor: float = 0.0
    quality_indicator: float = 0.0
    exploration_match: float = 0.0
    # 与用户 disliked_topics 的嵌入匹配。值越高意味着内容在语义上
    # 类似于他们明确拒绝的东西 → 从最终分数中减去。
    dislike_penalty: float = 0.0


@dataclass(frozen=True)
class DelightWeights:
    """复合 delight 分数的可调权重。"""

    deep_need: float = 0.20
    insight: float = 0.15
    likes: float = 0.30
    novelty: float = 0.15
    quality: float = 0.10
    exploration: float = 0.10
    # 在从正向和减去之前应用于 dislike_penalty 的乘数。0.50 意味着
    # 一个强 dislike 匹配（penalty=1.0）从分数中减去 0.50，通常
    # 将其推到阈值之下。
    dislike_penalty: float = 0.50


# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# Delight 阈值：
# 为 bge-m3 多语言嵌入（用户通过 Ollama 的主要本地嵌入）校准。
# bge-m3 的余弦分布比 Gemini 更紧 —— 即使强的 likes_alignment
# 匹配在原始余弦 0.85 处触顶，这在 ``(sim - 0.5) * 2.0`` 放大器
# 之后产生约 0.70 的贡献；结合 0.30 的权重，likes 信号单独的
# 上限是 0.21。
#
# 此常量的历史：
#   v0.3.31  0.65  Gemini 时代；在 bge-m3 下不可达，被砍掉的功能
#   v0.3.34  0.45  embedding-cosine 经验 p95（约 4-5/100）
#   v0.3.35  0.44  为约 12-18/600 重新调优（top-200 样本外推）
#   v0.3.39  0.55  ↓ 切换到 LLM 评分暴露了更宽的分数分布：使用
#                  rubric 驱动的理由，LLM 慷慨地给"常规匹配"内容
#                  0.45-0.55（钩子如「常规关联」/「常规推荐」）。
#                  2026-05-04 对 193 个评分项的经验观察：
#                    0.44-0.60:  9   ← "common" 层 —— LLM 对冲
#                    0.60-0.75: 14   ← 真正的跨域 delight
#                    0.75+   : 12   ← 卓越（"跨域惊喜"）
#                  35/193 = 18.1% = 642 池中约 116 —— 是 v0.3.35
#                  目标的 7 倍。提升到 0.55 切掉 LLM 的 rubric 中段
#                  "common" 层（对用户来说不像是惊喜），同时保留
#                  0.60+ 的真正令人愉悦的带。预期：~26/642 ≈ 4%
#                  通过率。
#   v0.3.41  0.57  ↑ 0.55 仍然放过了约 26/642，用户判定太多。
#                  0.57 将 "common" 尾巴切到更接近 0.60，那里 LLM
#                  的推理开始读起来像实际的惊喜而非对冲。预期：
#                  ~18-20/642 ≈ 3% 通过率，更接近 v0.3.35 的目标。
# CONSERVATIVE 阈值移到 0.67（对低探索用户比例上更紧 —— 仅
# 0.67+ "scoring rationale = surprise" 层）。
#
# v0.3.49: 跳 0.57 → 0.70 以实际对齐 `_DELIGHT_BATCH_SCORE_SYSTEM_PROMPT`
# 中的 LLM rubric，其本身定义：
#   0.70-0.85: 跨域呼应,用户大概率会感兴趣但自己不会主动找  ← 真正的 delight
#   0.55-0.70: 有惊喜潜力但相对常规                          ← 不是 delight
# 0.57 比 LLM 自己的"实际 delight"线低 13 个 tick，因此每批次
# 浮现大量"相对常规"内容作为 delight（43 分钟内 35 个候选，钩子
# 如"常规补给" / "实用工具" / "信息整合"）。越过 LLM 陈述的边界
# 将假阳性率切掉约 60% —— 只有评分器自己评为跨域呼应层或更高的
# 项被推送。CONSERVATIVE 阈值同样移到 0.80（上一档 —— "用户不会
# 主动找" + 额外谨慎）。
DEFAULT_DELIGHT_THRESHOLD: float = 0.70
CONSERVATIVE_DELIGHT_THRESHOLD: float = 0.80
_LOW_EXPLORATION_OPENNESS: float = 0.3
_DEFAULT_WEIGHTS = DelightWeights()


# LLM delight 评分的默认批次大小。5 保持每个 prompt 小（缓存友好、
# 快速），同时仍然摊销每次调用的 HTTP/握手成本。每个刷新 tick 约
# 30 个候选时，那是 6 个批次调用。
_DELIGHT_LLM_BATCH_SIZE: int = 5


class _SupportsStructuredLLM(Protocol):
    async def complete_structured_task(
        self,
        *,
        system_instruction: str,
        user_input: str,
        max_tokens: int = ...,
        caller: str = ...,
        inject_core_memory: bool = ...,
    ) -> Any: ...


@dataclass
class DelightLLMResult:
    """一个候选的 LLM 判定的 delight 结果。"""

    score: float = 0.0
    rationale: str = ""
    hook: str = ""


class LLMDelightScorer:
    """基于 LLM 的 delight 评分（替代 embedding-cosine 管道）。

    为什么用 LLM 而非 embedding 余弦：embedding 相似度奖励与用户
    现有 likes *相似* 的内容，这与"惊喜"相反。因此 2026-05-04 之前
    的 ``DelightScorer`` 浮现的是强化内容（对 AI 重度用户给更多
    DeepSeek 教程）而非跨域 delight。评估 rubric 的 LLM 可以用
    余弦无法做到的方式区分"概念桥接"和"话题重复"。

    成本：在 batch_size=5 且每个刷新 tick 约 30 个新候选时，每个
    周期 6 次 LLM 调用 × ~¥0.01 = ¥0.06/周期，8 个周期 ¥0.48/天。
    每次调用一次返回 score + rationale + hook，消除了次级
    ``_generate_delight_reason`` LLM 跳。
    """

    def __init__(
        self,
        llm_service: _SupportsStructuredLLM,
        *,
        threshold: float = DEFAULT_DELIGHT_THRESHOLD,
        batch_size: int = _DELIGHT_LLM_BATCH_SIZE,
    ) -> None:
        self._llm_service = llm_service
        self._threshold = threshold
        self._batch_size = max(1, batch_size)
        self._profile_prompt_cache = PromptLayerRenderCache()

    @property
    def threshold(self) -> float:
        return self._threshold

    def effective_threshold(self, exploration_openness: float) -> float:
        """对保守用户返回可能提高的阈值。"""
        if exploration_openness < _LOW_EXPLORATION_OPENNESS:
            return max(self._threshold, CONSERVATIVE_DELIGHT_THRESHOLD)
        return self._threshold

    async def score_batch(
        self,
        candidates: list[SupportsDelightCandidate],
        profile: Any,
    ) -> dict[str, DelightLLMResult]:
        """通过批次 LLM 调用为一组候选评分。

        返回映射 ``bvid -> DelightLLMResult``。LLM 遗漏或错误路由的
        项默认为 ``score=0.0``；调用方应将缺失条目视为"低于阈值"，
        不要重试同一批次（LLM 会持续丢弃它们 —— 通常是因为标题为
        空或无法翻译）。
        """
        if not candidates:
            return {}

        results: dict[str, DelightLLMResult] = {}
        profile_summary = _build_delight_profile_summary(profile)
        profile_blocks = self._profile_prompt_cache.render_json_layers(
            profile_prompt_layers(profile_summary)
        )

        for batch_start in range(0, len(candidates), self._batch_size):
            batch = candidates[batch_start : batch_start + self._batch_size]
            content_batch = [
                {
                    "bvid": c.bvid,
                    "title": (c.title or "")[:140],
                    "description": (c.description or "")[:400],
                    "topic_group": getattr(c, "topic_group", "") or "",
                    "source_strategy": getattr(c, "source_strategy", "") or "",
                    "relevance_score": round(float(c.relevance_score or 0.0), 3),
                }
                for c in batch
            ]
            messages = build_delight_score_batch_prompt(
                profile_summary=profile_summary,
                profile_blocks=profile_blocks,
                content_batch=content_batch,
            )
            try:
                complete_structured = self._llm_service.complete_structured_task
                response = await complete_structured(
                    system_instruction=messages[0]["content"],
                    user_input=messages[1]["content"],
                    max_tokens=2048,
                    caller="recommendation.delight_score",
                    **without_core_memory_kwargs(complete_structured),
                )
            except Exception:
                logger.warning(
                    "Delight LLM batch scoring failed for %d candidates",
                    len(batch),
                    exc_info=True,
                )
                continue

            entries = _extract_delight_entries(
                str(getattr(response, "content", "")), expected_count=len(batch)
            )
            if not entries:
                logger.warning(
                    "Delight LLM batch produced 0 parseable entries for %d candidates "
                    "(provider response shape mismatch?)",
                    len(batch),
                )
                continue

            for entry in entries:
                bvid = str(entry.get("bvid", "")).strip()
                if not bvid:
                    continue
                results[bvid] = DelightLLMResult(
                    score=max(0.0, min(1.0, float(entry.get("score", 0.0) or 0.0))),
                    rationale=str(entry.get("rationale", "")).strip(),
                    hook=str(entry.get("hook", "")).strip(),
                )

        return results


def _extract_delight_entries(content: str, *, expected_count: int) -> list[dict[str, Any]]:
    """从 LLM 响应中提取 {bvid, score, rationale, hook} 列表。

    JSON 模式下不同的 LLM 提供商/模型返回不同的根形状：
      - DeepSeek 通常返回干净的 ``[...]`` 列表（匹配 prompt 的
        <output_schema>）。
      - mimo-v2.5-pro 倾向于包装在对象中：``{"results": [...]}``、
        ``{"items": [...]}``、``{"delights": [...]}``，或有时发出
        多个根 JSON 对象以换行分隔（导致 ``json.JSONDecodeError:
        Extra data``）。
      - 某些模型在 batch=1 时将 schema 回显为单个对象。

    此 helper 委托给共享的 LLM JSON 提取器，因此数组片段、包装器、
    单条目和 JSONL 的处理方式与 recommendation/discovery 解析器一致。
    仅在无法提取任何有效条目时返回空列表。
    """
    text = content.strip()
    if not text:
        return []

    entries = extract_llm_json_list(
        text,
        wrapper_keys=(
            "results",
            "items",
            "delights",
            "data",
            "scores",
            "candidates",
            "output",
            "list",
            "array",
        ),
        allow_singleton=True,
        item_predicate=lambda item: "bvid" in item or "score" in item,
    )
    if not entries:
        return []
    result = [dict(item) for item in entries]
    return result[:expected_count] if expected_count > 0 else result


def _build_delight_profile_summary(profile: Any) -> dict[str, object]:
    """为 delight LLM prompt 构建的紧凑 profile 形状。

    仅保留 rubric 实际使用的字段：
      - top likes（domain + weight + 前 4 个 specifics）
      - deep_needs
      - active_insights（hypothesis + confidence）
      - exploration_openness
      - disliked_topics（top 8）
    """
    summary: dict[str, object] = {}

    interest_layer = getattr(profile, "interest", None)
    likes_src = getattr(interest_layer, "likes", []) if interest_layer is not None else []
    likes_out: list[dict[str, object]] = []
    for d in sorted(
        likes_src,
        key=lambda dom: float(getattr(dom, "weight", 0.0) or 0.0),
        reverse=True,
    )[:8]:
        domain = str(getattr(d, "domain", "")).strip()
        if not domain:
            continue
        specs = [
            str(getattr(s, "name", "")).strip()
            for s in (getattr(d, "specifics", []) or [])[:4]
            if str(getattr(s, "name", "")).strip()
        ]
        likes_out.append(
            {
                "domain": domain,
                "weight": round(float(getattr(d, "weight", 0.0) or 0.0), 2),
                "specifics": specs,
            }
        )
    summary["likes"] = likes_out

    deep_needs = [
        str(n).strip() for n in (getattr(profile, "deep_needs", []) or [])[:5] if str(n).strip()
    ]
    if not deep_needs:
        core = getattr(profile, "core", None)
        if core is not None:
            deep_needs = [
                str(n).strip()
                for n in (getattr(core, "deep_needs", []) or [])[:5]
                if str(n).strip()
            ]
    summary["deep_needs"] = deep_needs

    insights_out: list[dict[str, object]] = []
    # 时间顺序窗口：最新的 insights 在尾部。
    for ins in (getattr(profile, "active_insights", []) or [])[-5:]:
        hyp = str(getattr(ins, "hypothesis", "")).strip()
        if not hyp:
            continue
        insights_out.append(
            {
                "hypothesis": hyp[:200],
                "confidence": round(float(getattr(ins, "confidence", 0.5) or 0.5), 2),
            }
        )
    summary["active_insights"] = insights_out

    prefs = getattr(profile, "preferences", None)
    summary["exploration_openness"] = round(
        float(getattr(prefs, "exploration_openness", 0.5) or 0.5), 2
    )

    disliked = [
        str(t).strip() for t in (getattr(prefs, "disliked_topics", []) or [])[:8] if str(t).strip()
    ]
    summary["disliked_topics"] = disliked

    return summary


class DelightScorer:
    """基于与深度 profile 共鸣的内容 delight 分数计算。

    评分器使用 embedding 相似度将内容与用户的 deep_needs 和
    active_insights 匹配，结合新颖性和质量信号。
    """

    def __init__(
        self,
        embedding_service: SupportsEmbeddingService | None,
        database: SupportsRecommendationSignalStore,
        *,
        weights: DelightWeights | None = None,
        threshold: float = DEFAULT_DELIGHT_THRESHOLD,
    ) -> None:
        self._embedding = embedding_service
        self._database = database
        self._weights = weights or DelightWeights()
        self._threshold = threshold

    @property
    def threshold(self) -> float:
        return self._threshold

    def effective_threshold(self, exploration_openness: float) -> float:
        """对保守用户返回可能提高的阈值。"""
        if exploration_openness < _LOW_EXPLORATION_OPENNESS:
            return max(self._threshold, CONSERVATIVE_DELIGHT_THRESHOLD)
        return self._threshold

    async def score(
        self,
        candidate: SupportsDelightCandidate,
        profile: Any,
    ) -> tuple[float, DelightSignals, str]:
        """给定 soul profile 为候选计算 delight 分数。

        Returns:
            一个元组 (delight_score, signals, reason_stub)。
            reason_stub 是一个短提示，供 LLM 展开为完整的
            delight_reason。
        """
        w = self._weights
        signals = await self._compute_signals(candidate, profile)

        positive = (
            signals.deep_need_alignment * w.deep_need
            + signals.insight_resonance * w.insight
            + signals.likes_alignment * w.likes
            + signals.novelty_factor * w.novelty
            + signals.quality_indicator * w.quality
            + signals.exploration_match * w.exploration
        )
        penalty = signals.dislike_penalty * w.dislike_penalty
        score = positive - penalty

        reason_stub = self._build_reason_stub(signals, candidate, profile)
        return (min(1.0, max(0.0, score)), signals, reason_stub)

    async def _compute_signals(
        self,
        candidate: SupportsDelightCandidate,
        profile: Any,
    ) -> DelightSignals:
        """计算各个 delight 信号分量。"""
        content_text = f"{candidate.title} {candidate.description or ''}"

        # 用内容文本探测 embedding 子系统一次。如果返回空，provider
        # 确实坏了 —— 下游信号调用会全部静默返回 0.0。
        # 廉价：同一 content_text 的后续 embed() 调用命中 L1 缓存
        # （约 10µs）。
        embed_alive = True
        if self._embedding is not None:
            probe_vec = await self._embedding.embed(content_text)
            embed_alive = bool(probe_vec)

        deep_need = await self._deep_need_alignment(content_text, profile)
        insight = await self._insight_resonance(content_text, profile)
        likes = await self._likes_alignment(content_text, profile)
        novelty = self._novelty_factor(candidate)
        quality = self._quality_indicator(candidate)
        exploration = self._exploration_match(candidate, profile, novelty)
        dislike = await self._dislike_penalty(content_text, profile)

        # 暴露"embedding 子系统死亡"级联 —— 仅当 provider 实际上
        # 对内容文本返回了空向量时。早期版本（v0.3.31）在所有 4 个
        # embedding 驱动信号都为 0.0 时标记此情况，但对合法的
        # 内容-超出-用户兴趣项会触发假阳性：对技术专用用户的历史
        # 文档，likes=0.0 来自低余弦 + clamp，而非死的 embedding。
        # embed_alive 直接区分。
        if self._embedding is not None and not embed_alive:
            logger.warning(
                "Delight scoring degraded for %s: embedding provider "
                "returned empty vector for content text "
                "Score will be capped at non-embedding signals only.",
                getattr(candidate, "bvid", "?"),
            )

        return DelightSignals(
            deep_need_alignment=deep_need,
            insight_resonance=insight,
            likes_alignment=likes,
            novelty_factor=novelty,
            quality_indicator=quality,
            exploration_match=exploration,
            dislike_penalty=dislike,
        )

    async def _deep_need_alignment(
        self,
        content_text: str,
        profile: Any,
    ) -> float:
        """评分内容与用户深层需求的对齐度。"""
        if self._embedding is None:
            return 0.0

        deep_needs = getattr(profile, "deep_needs", [])
        if not deep_needs:
            return 0.0

        from openbiliclaw.llm.embedding import cosine_similarity

        content_vec = await self._embedding.embed(content_text)
        if not content_vec:
            return 0.0

        max_sim = 0.0
        for need in deep_needs[:5]:
            need_text = str(need).strip()
            if not need_text:
                continue
            need_vec = await self._embedding.embed(need_text)
            if not need_vec:
                continue
            sim = cosine_similarity(content_vec, need_vec)
            max_sim = max(max_sim, sim)

        # 归一化：相似度 0.5 → 0.0，相似度 1.0 → 1.0
        return max(0.0, min(1.0, (max_sim - 0.5) * 2.0))

    async def _insight_resonance(
        self,
        content_text: str,
        profile: Any,
    ) -> float:
        """评分内容与活跃洞察假设的对齐度。"""
        if self._embedding is None:
            return 0.0

        active_insights = getattr(profile, "active_insights", [])
        if not active_insights:
            return 0.0

        from openbiliclaw.llm.embedding import cosine_similarity

        content_vec = await self._embedding.embed(content_text)
        if not content_vec:
            return 0.0

        max_sim = 0.0
        # 时间顺序窗口：最新的 insights 在尾部。
        for insight in active_insights[-5:]:
            hypothesis = str(getattr(insight, "hypothesis", "")).strip()
            if not hypothesis:
                continue
            insight_vec = await self._embedding.embed(hypothesis)
            if not insight_vec:
                continue
            sim = cosine_similarity(content_vec, insight_vec)
            # 按 confidence 加权
            confidence = float(getattr(insight, "confidence", 0.5))
            weighted_sim = sim * (0.5 + confidence * 0.5)
            max_sim = max(max_sim, weighted_sim)

        return max(0.0, min(1.0, (max_sim - 0.4) * 2.5))

    async def _likes_alignment(
        self,
        content_text: str,
        profile: Any,
    ) -> float:
        """与用户实际 top likes 的 embedding 相似度评分。

        直接使用 onion ``interest.likes`` 树，因此每个 like 的文本
        输入将 domain 名与其 specifics 组合 —— 短类别词如"游戏"单独
        对 B 站标题产生弱 embedding 信号，但"游戏 / 自走棋 王者荣耀
        金铲铲"丰富到足以实际与内容关联。
        """
        if self._embedding is None:
            return 0.0

        # 优先使用 onion ``interest.likes`` 树（携带 specifics）。
        # 如果 onion 形状不存在，回退到扁平的 preferences.interests。
        like_texts: list[tuple[str, float]] = []  # (text, weight)
        interest_layer = getattr(profile, "interest", None)
        likes = getattr(interest_layer, "likes", []) if interest_layer is not None else []
        for dom in likes[:8]:
            domain = str(getattr(dom, "domain", "")).strip()
            if not domain:
                continue
            spec_names = [
                str(getattr(s, "name", "")).strip()
                for s in getattr(dom, "specifics", [])[:5]
                if str(getattr(s, "name", "")).strip()
            ]
            text = f"{domain}：{' '.join(spec_names)}" if spec_names else domain
            weight = float(getattr(dom, "weight", 0.0) or 0.0)
            like_texts.append((text, weight))

        if not like_texts:
            prefs = getattr(profile, "preferences", None)
            interests = getattr(prefs, "interests", []) if prefs is not None else []
            seen: set[str] = set()
            for tag in interests:
                name = str(getattr(tag, "name", "")).strip()
                weight = float(getattr(tag, "weight", 0.0) or 0.0)
                if not name or name in seen or weight <= 0:
                    continue
                seen.add(name)
                like_texts.append((name, weight))
            like_texts.sort(key=lambda x: x[1], reverse=True)
            like_texts = like_texts[:8]

        if not like_texts:
            return 0.0

        from openbiliclaw.llm.embedding import cosine_similarity

        content_vec = await self._embedding.embed(content_text)
        if not content_vec:
            return 0.0

        max_score = 0.0
        for text, weight in like_texts:
            tag_vec = await self._embedding.embed(text)
            if not tag_vec:
                continue
            sim = cosine_similarity(content_vec, tag_vec)
            # 对低权重 like 降权 —— 一个 0.4 权重的 tag 不如一个
            # 0.95 权重的那么重要。
            score = sim * (0.6 + 0.4 * min(1.0, weight))
            max_score = max(max_score, score)

        # 与 deep_need_alignment 同样归一化：相似度 0.5 → 0.0，
        # 1.0 → 1.0。避免我们最初尝试的过于激进的 2.857 乘数，
        # 它把典型分数压得太低。
        return max(0.0, min(1.0, (max_score - 0.5) * 2.0))

    async def _dislike_penalty(
        self,
        content_text: str,
        profile: Any,
    ) -> float:
        """基于 embedding 的负向信号：内容在多大程度上类似于用户
        明确 dislike 的话题。

        替代推送时的脆弱子串过滤器 —— embedding 相似度能捕获近义
        词（例如 ``手工木工`` 匹配一个关于 woodworking 的视频，即使
        字面短语不在标题中）而不会在公共词干上发生假阳性碰撞。
        """
        if self._embedding is None:
            return 0.0

        prefs = getattr(profile, "preferences", None)
        disliked = getattr(prefs, "disliked_topics", []) if prefs is not None else []
        # 过滤掉不携带话题信号的通用短语。
        skip_terms = {"低质内容", "虚假信息", "标题党", "低质", "虚假"}
        topical = [
            str(t).strip() for t in disliked if str(t).strip() and str(t).strip() not in skip_terms
        ]
        if not topical:
            return 0.0

        from openbiliclaw.llm.embedding import cosine_similarity

        content_vec = await self._embedding.embed(content_text)
        if not content_vec:
            return 0.0

        max_sim = 0.0
        for term in topical[:5]:
            term_vec = await self._embedding.embed(term)
            if not term_vec:
                continue
            sim = cosine_similarity(content_vec, term_vec)
            max_sim = max(max_sim, sim)

        # 为 bge-m3（多语言，用户的主要本地嵌入）校准的阈值 + 放大器。
        # bge-m3 将低语义中文片段 —— 直播标题如"青梅煮酒_20260425
        # dy主播"、短元数据字符串等 —— 放入一个"通用中文"嵌入簇，
        # 那里与任何中文短语的余弦相似度在 0.78-0.85 浮动。原来的
        # ``(sim - 0.55) * 2.5``（为 Gemini 更大的基线散布校准）
        # 冲过这个簇：任何低语义中文标题对任意 dislike 项得分
        # dislike_penalty ≈ 0.6-0.73，杀掉了合法的 delight 分数。
        # 对用户 disliked_topics 的经验 bge-m3 余弦分布：
        #   高语义内容（如"Scratch物理引擎"）:  0.02-0.05
        #   低语义片段（"dy主播 青梅煮酒"）:      0.78-0.85
        #   实际相似话题（真正匹配）:              0.88-0.95
        # 阈值 0.78 切掉假阳性簇；放大器 1.5 保持真阳性带（0.88+）
        # 可操作而不过度惩罚边界匹配。
        return max(0.0, min(1.0, (max_sim - 0.78) * 1.5))

    def _novelty_factor(self, candidate: SupportsDelightCandidate) -> float:
        """基于发现策略和话题新鲜度评分新颖性。"""
        # Explore 策略固有地携带更多新颖性
        strategy_novelty = {
            "explore": 0.9,
            "trending": 0.5,
            "related_chain": 0.3,
            "search": 0.2,
        }
        base_novelty = strategy_novelty.get(candidate.source_strategy, 0.3)

        # 检查此话题被推荐过的频率
        signals = self._database.get_recent_recommendation_signals(limit=30)
        topic = (candidate.topic_group or candidate.topic_key).strip().lower()
        if topic and signals:
            topic_count = sum(
                1 for s in signals if str(s.get("topic_key", "")).strip().lower() == topic
            )
            # 如果话题经常出现则惩罚
            repetition_penalty = min(1.0, topic_count / 5.0)
            base_novelty = base_novelty * (1.0 - repetition_penalty * 0.5)

        return max(0.0, min(1.0, base_novelty))

    @staticmethod
    def _quality_indicator(candidate: SupportsDelightCandidate) -> float:
        """从参与度信号评分内容质量。"""
        view_count = max(1, candidate.view_count)
        like_count = candidate.like_count

        if view_count < 100:
            return 0.3  # 数据不足

        like_ratio = like_count / view_count
        # 归一化：0.01 → 0.2，0.05 → 0.7，0.10+ → 1.0
        quality = min(1.0, like_ratio * 12.0)

        # 与 relevance_score 混合
        return quality * 0.5 + candidate.relevance_score * 0.5

    @staticmethod
    def _exploration_match(
        candidate: SupportsDelightCandidate,
        profile: Any,
        novelty: float,
    ) -> float:
        """基于用户探索开放度和内容新颖性评分。"""
        prefs = getattr(profile, "preferences", None)
        exploration_openness = float(getattr(prefs, "exploration_openness", 0.5))

        if exploration_openness > 0.6:
            # 开放用户在新颖的跨域内容中感到惊喜
            return novelty * exploration_openness
        else:
            # 保守用户在已知领域的深度潜入中感到惊喜
            # 已知领域的高相关性 = 深度满足
            depth_signal = candidate.relevance_score * (1.0 - novelty)
            return depth_signal * (1.0 - exploration_openness * 0.5)

    @staticmethod
    def _build_reason_stub(
        signals: DelightSignals,
        candidate: SupportsDelightCandidate,
        profile: Any,
    ) -> str:
        """为 LLM 展开构建结构化理由 stub。"""
        parts: list[str] = []

        if signals.likes_alignment >= 0.6:
            prefs = getattr(profile, "preferences", None)
            interests = getattr(prefs, "interests", []) if prefs is not None else []
            top_like = next(
                (
                    str(getattr(t, "name", "")).strip()
                    for t in interests
                    if str(getattr(t, "name", "")).strip()
                ),
                "",
            )
            if top_like:
                parts.append(f"likes:{top_like}")

        if signals.deep_need_alignment >= 0.6:
            deep_needs = getattr(profile, "deep_needs", [])
            if deep_needs:
                parts.append(f"deep_need:{deep_needs[0]}")

        if signals.insight_resonance >= 0.6:
            insights = getattr(profile, "active_insights", [])
            if insights:
                hypothesis = str(getattr(insights[0], "hypothesis", ""))
                if hypothesis:
                    parts.append(f"insight:{hypothesis[:60]}")

        if signals.novelty_factor >= 0.7:
            parts.append(f"novelty:{candidate.source_strategy}")

        if signals.exploration_match >= 0.7:
            parts.append("exploration:cross_domain")

        if not parts:
            parts.append(f"relevance:{candidate.relevance_score:.2f}")

        return "|".join(parts)
