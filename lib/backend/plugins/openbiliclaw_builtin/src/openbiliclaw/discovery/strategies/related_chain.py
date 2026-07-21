"""相关链内容发现策略。"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING

from openbiliclaw.discovery.engine import (
    ContentDiscoveryEngine,
    DiscoveredContent,
    DiscoveryConcurrencyController,
    DiscoveryStrategy,
    SupportsStructuredTask,
    discovery_raw_candidate_mode_enabled,
    llm_eval_candidate_limit,
)
from openbiliclaw.discovery.strategies._utils import (
    SupportsMemoryManager,
    SupportsRelatedClient,
    SupportsSeedStrategy,
    _gather_bounded,
    clean_text,
    parse_duration,
    search_cooldown_remaining,
    to_int,
)

if TYPE_CHECKING:
    from openbiliclaw.soul.profile import SoulProfile
    from openbiliclaw.storage.database import Database

logger = logging.getLogger(__name__)


@dataclass
class RelatedChainStrategy(DiscoveryStrategy):
    """通过追踪相关推荐链发现内容。"""

    bilibili_client: SupportsRelatedClient
    llm_service: SupportsStructuredTask
    memory_manager: SupportsMemoryManager
    search_strategy: SupportsSeedStrategy | None = None
    trending_strategy: SupportsSeedStrategy | None = None
    concurrency: DiscoveryConcurrencyController | None = None
    database: Database | None = None
    score_threshold: float = 0.60
    llm_evaluation: bool = True
    max_seeds: int = 5
    related_per_seed: int = 8
    max_depth: int = 2
    # 限制每轮 depth 传给 LLM evaluator 的候选数。
    # 没有这一步,depth-2 fanout (可达 ``max_seeds * related_per_seed`` ×
    # 下一层大小) 会把数百个 item 发给 ``evaluate_content_batch``
    # — 比其他策略产出的多一个数量级 — 这会
    # 主导 discover wall time。40 使一轮的 eval 工作量大致
    # 与 search/trending/explore 平衡,同时仍允许 depth-2
    # 探索发生。
    max_eval_candidates_per_round: int = 40
    last_intermediates: dict[str, object] = field(default_factory=dict)

    @property
    def name(self) -> str:
        return "related_chain"

    def create_backfill_strategy(self) -> DiscoveryStrategy | None:
        if self.score_threshold <= 0.60:
            return None
        return replace(
            self,
            score_threshold=max(0.60, round(self.score_threshold - 0.07, 2)),
            related_per_seed=max(self.related_per_seed, 10),
            last_intermediates={},
        )

    async def discover(self, profile: SoulProfile, limit: int = 20) -> list[DiscoveredContent]:
        """从已知好内容出发,探索相关链。

        Args:
            profile: 用户 soul profile。
            limit: 最大结果数。

        Returns:
            发现的内容列表。
        """
        evaluator = ContentDiscoveryEngine(
            llm_service=self.llm_service,
            database=self.database,
            concurrency=self.concurrency,
        )
        seed_descriptors = await self._select_seed_descriptors(profile)
        self.last_intermediates = {
            "seeds": [(bvid, topic) for bvid, topic in seed_descriptors],
        }
        if not seed_descriptors:
            return []

        results: list[DiscoveredContent] = []
        seen_bvids = {seed_bvid for seed_bvid, _ in seed_descriptors}
        visited_source_bvids: set[str] = set()

        # 层级并行 BFS: 每层 depth 同时处理
        current_layer: list[tuple[str, int, int, str]] = [
            (seed_bvid, 1, seed_index, topic_key)
            for seed_index, (seed_bvid, topic_key) in enumerate(seed_descriptors)
        ]

        runner = self.concurrency.run_bilibili if self.concurrency is not None else None

        for _depth_round in range(self.max_depth):
            if not current_layer or len(results) >= limit:
                break

            # 层内去重并过滤已访问
            layer_items: list[tuple[str, int, int, str]] = []
            for item in current_layer:
                if item[0] not in visited_source_bvids:
                    visited_source_bvids.add(item[0])
                    layer_items.append(item)

            if not layer_items:
                break

            # 并发抓取整层的相关视频
            related_outcomes = await _gather_bounded(
                [self.bilibili_client.get_related_videos(bvid) for bvid, _, _, _ in layer_items],
                runner=runner,
            )

            # 从所有结果中收集候选
            batch_candidates: list[tuple[DiscoveredContent, int, int, str]] = []
            # v0.3.50+: 一个 depth round 内的 per-UP 上限。没有这个
            # 上限,related_chain 在跟 "popular UP" 种子时可能
            # 在单批里倒出 13+ 个同一 UP 的 item (真实
            # 案例: 张雪机车×13 — 2026-05-05 观察)。我们在本
            # round 跨所有种子追踪 per up_name 计数,而不是
            # per seed,因为用户真的关注某 UP 时,该 UP 会通过
            # 多个种子出现。
            from openbiliclaw.discovery.engine import _RELATED_CHAIN_PER_UP_CAP

            up_counts: dict[str, int] = {}
            up_skipped: dict[str, int] = {}
            for (seed_bvid, depth, seed_index, seed_topic_key), outcome in zip(
                layer_items,
                related_outcomes,
                strict=True,
            ):
                if isinstance(outcome, BaseException):
                    logger.error(
                        "Related videos request failed: %s",
                        seed_bvid,
                        exc_info=outcome,
                        extra={
                            "strategy": "related_chain",
                            "seed_bvid": seed_bvid,
                            "depth": depth,
                            "error_type": type(outcome).__name__,
                        },
                    )
                    continue
                if not isinstance(outcome, list):
                    continue
                for item in outcome[: self.related_per_seed]:
                    content = self._map_related_item(item, seed_topic_key=seed_topic_key)
                    if content is None or content.bvid in seen_bvids:
                        continue
                    up_name_norm = (content.up_name or "").strip().lower()
                    if (
                        _RELATED_CHAIN_PER_UP_CAP > 0
                        and up_name_norm
                        and up_counts.get(up_name_norm, 0) >= _RELATED_CHAIN_PER_UP_CAP
                    ):
                        up_skipped[up_name_norm] = up_skipped.get(up_name_norm, 0) + 1
                        continue
                    seen_bvids.add(content.bvid)
                    if up_name_norm:
                        up_counts[up_name_norm] = up_counts.get(up_name_norm, 0) + 1
                    batch_candidates.append((content, depth, seed_index, seed_topic_key))
            if up_skipped:
                logger.info(
                    "related_chain per-UP cap: skipped %d item(s) (cap=%d/UP per round; %s)",
                    sum(up_skipped.values()),
                    _RELATED_CHAIN_PER_UP_CAP,
                    ", ".join(f"{k}×{v}" for k, v in up_skipped.items()),
                )

            # 限制单轮候选数,避免 depth-2 fanout
            # 把数百个 item 倒进 evaluate_content_batch。我们
            # 优先为每个 distinct seed_index 保留一个 slot,使
            # 每个 seed 血统在 cap 触发前仍能贡献。
            eval_candidate_limit = min(
                self.max_eval_candidates_per_round,
                llm_eval_candidate_limit(limit),
            )
            if eval_candidate_limit > 0 and len(batch_candidates) > eval_candidate_limit:
                original_count = len(batch_candidates)
                by_seed: dict[int, list[tuple[DiscoveredContent, int, int, str]]] = {}
                for entry in batch_candidates:
                    by_seed.setdefault(entry[2], []).append(entry)
                trimmed: list[tuple[DiscoveredContent, int, int, str]] = []
                index = 0
                while len(trimmed) < eval_candidate_limit:
                    appended = False
                    for seed_index in sorted(by_seed):
                        bucket = by_seed[seed_index]
                        if index < len(bucket):
                            trimmed.append(bucket[index])
                            appended = True
                            if len(trimmed) >= eval_candidate_limit:
                                break
                    if not appended:
                        break
                    index += 1
                logger.info(
                    "related_chain: trimming depth-round candidates from %d to %d",
                    original_count,
                    len(trimmed),
                )
                batch_candidates = trimmed

            # 在批量 LLM 调用中评估所有候选
            contents = [c for c, _, _, _ in batch_candidates]
            if not self.llm_evaluation or discovery_raw_candidate_mode_enabled():
                results.extend(contents)
                if len(results) >= limit:
                    break
                current_layer = [
                    (content.bvid, depth + 1, seed_index, seed_topic_key)
                    for content, depth, seed_index, seed_topic_key in batch_candidates
                    if depth < self.max_depth
                ]
                continue
            scores = await evaluator.evaluate_content_batch(contents, profile)

            next_layer: list[tuple[str, int, int, str]] = []
            for (content, depth, seed_index, seed_topic_key), score in zip(
                batch_candidates,
                scores,
                strict=True,
            ):
                bonus = self._seed_bonus(seed_index) + self._depth_bonus(depth)
                content.relevance_score = min(1.0, round(score + bonus, 4))
                if content.relevance_score < self.score_threshold:
                    continue
                results.append(content)
                if depth < self.max_depth:
                    next_layer.append((content.bvid, depth + 1, seed_index, seed_topic_key))
                if len(results) >= limit:
                    break

            current_layer = next_layer

        results.sort(key=lambda item: item.relevance_score, reverse=True)
        return results

    async def _select_seed_descriptors(self, profile: SoulProfile) -> list[tuple[str, str]]:
        seeds: list[tuple[str, str]] = []
        seen: set[str] = set()

        # 为跨域种子预留 slot 以对抗 echo chamber
        cross_domain_slots = max(1, self.max_seeds // 3)
        interest_slots = self.max_seeds - cross_domain_slots

        # 阶段 1: 填充基于兴趣的种子 (事件 + preferences)
        for bvid, title in self._event_seed_bvids_with_title():
            if bvid in seen:
                continue
            seen.add(bvid)
            seeds.append((bvid, self._topic_key_from_title(title)))
            if len(seeds) >= interest_slots:
                break

        if len(seeds) < interest_slots:
            for bvid in await self._preference_seed_bvids(profile):
                if bvid in seen:
                    continue
                seen.add(bvid)
                seeds.append((bvid, self._topic_key_from_seed_bvid(bvid)))
                if len(seeds) >= interest_slots:
                    break

        # 阶段 2: 从 explore/trending 策略填充跨域种子
        for strategy in (self.search_strategy, self.trending_strategy):
            if strategy is None:
                continue
            remaining = self.max_seeds - len(seeds)
            if remaining <= 0:
                break
            try:
                items = await strategy.discover(profile, limit=remaining)
            except Exception:
                logger.exception(
                    "Fallback seed strategy failed: %s",
                    getattr(strategy, "name", "unknown"),
                )
                continue
            for item in items:
                if item.bvid in seen or not item.bvid:
                    continue
                seen.add(item.bvid)
                seeds.append((item.bvid, self._topic_key_from_title(item.title)))
                if len(seeds) >= self.max_seeds:
                    return seeds

        return seeds

    def _event_seed_bvids_with_title(self) -> list[tuple[str, str]]:
        events = self.memory_manager.query_events(
            event_types=["favorite", "like", "coin", "share", "feedback", "view"],
            limit=max(self.max_seeds * 5, 20),
        )
        # 多样化种子: 从不同 title/topic 选取以避免 echo chamber
        seed_pairs: list[tuple[str, str]] = []
        seen_title_prefixes: set[str] = set()
        ranked_events = sorted(
            enumerate(events),
            key=lambda pair: (-self._event_seed_priority(pair[1]), pair[0]),
        )
        for _, event in ranked_events:
            if self._event_seed_priority(event) < 0:
                continue
            bvid = self._extract_bvid_from_event(event)
            if not bvid:
                continue
            full_title = str(event.get("title", "")).strip()
            # 用 title 前 4 个字符作为粗略的 topic 去重 key
            prefix = full_title[:4]
            if prefix and prefix in seen_title_prefixes:
                continue
            if prefix:
                seen_title_prefixes.add(prefix)
            seed_pairs.append((bvid, full_title))
        return seed_pairs

    @classmethod
    def _event_seed_priority(cls, event: dict[str, object]) -> int:
        event_type = str(event.get("event_type", "") or "").strip().lower()
        metadata = cls._event_metadata(event)
        feedback_type = str(metadata.get("feedback_type", "") or "").strip().lower()
        reaction = str(metadata.get("reaction", "") or "").strip().lower()
        satisfaction = str(event.get("inferred_satisfaction", "") or "").strip().lower()
        if satisfaction == "negative" or feedback_type == "dislike" or reaction == "thumbs_down":
            return -1
        if event_type in {"favorite", "coin", "share"}:
            return 100
        if event_type == "like":
            return 90
        if event_type == "feedback" and (
            satisfaction == "positive" or feedback_type in {"like", "favorite", "positive"}
        ):
            return 85
        if event_type == "view" and satisfaction == "positive":
            return 60
        if satisfaction == "positive":
            return 50
        if event_type == "view":
            return 10
        return 20

    @staticmethod
    def _event_metadata(event: dict[str, object]) -> dict[str, object]:
        metadata = event.get("metadata", {})
        if isinstance(metadata, str):
            try:
                parsed = json.loads(metadata)
            except json.JSONDecodeError:
                return {}
            return parsed if isinstance(parsed, dict) else {}
        return metadata if isinstance(metadata, dict) else {}

    async def _preference_seed_bvids(self, profile: SoulProfile) -> list[str]:
        cooldown_remaining = search_cooldown_remaining(self.bilibili_client)
        if cooldown_remaining > 0:
            logger.info(
                "related_chain: Bilibili search cooldown active (%.0fs left); "
                "skipping preference seed search",
                cooldown_remaining,
            )
            return []

        queries: list[str] = []
        queries.extend(
            interest_item.name.strip()
            for interest_item in profile.preferences.interests[:2]
            if interest_item.name.strip()
        )
        queries.extend(
            up_name.strip()
            for up_name in profile.preferences.favorite_up_users[:1]
            if up_name.strip()
        )

        # 遵守单策略搜索预算。
        if self.concurrency is not None:
            budget = self.concurrency.search_budget_per_strategy
            queries = queries[:budget]

        seeds: list[str] = []
        seen: set[str] = set()
        for query in queries:
            try:
                items = await self.bilibili_client.search(query, page=1, page_size=2)
            except Exception:
                logger.exception("Preference seed search failed: %s", query)
                continue
            for item in items:
                bvid = str(item.get("bvid", "")).strip()
                if not bvid or bvid in seen:
                    continue
                seen.add(bvid)
                seeds.append(bvid)
                if len(seeds) >= self.max_seeds:
                    return seeds
        return seeds

    @staticmethod
    def _extract_bvid_from_event(event: dict[str, object]) -> str:
        metadata = RelatedChainStrategy._event_metadata(event)
        bvid = str(metadata.get("bvid", "")).strip()
        if bvid:
            return bvid

        url = str(event.get("url", "")).strip()
        match = re.search(r"/video/(BV[\w]+)", url)
        return match.group(1) if match else ""

    def _map_related_item(
        self,
        item: dict[str, object],
        *,
        seed_topic_key: str,
    ) -> DiscoveredContent | None:
        bvid = str(item.get("bvid", "")).strip()
        if not bvid:
            return None
        owner = item.get("owner")
        up_name = ""
        up_mid = 0
        if isinstance(owner, dict):
            up_name = clean_text(str(owner.get("name", "")))
            up_mid = to_int(owner.get("mid", 0))

        stat = item.get("stat")
        view_count = 0
        like_count = 0
        favorite_count = 0
        danmaku_count = 0
        comment_count = 0
        share_count = 0
        if isinstance(stat, dict):
            view_count = to_int(stat.get("view", 0))
            like_count = to_int(stat.get("like", 0))
            favorite_count = to_int(stat.get("favorite", 0))
            danmaku_count = to_int(stat.get("danmaku", 0))
            comment_count = to_int(stat.get("reply", 0))
            share_count = to_int(stat.get("share", 0))

        title_text = clean_text(str(item.get("title", "")))
        # 优先用 B站分区名 (tname) 作为 topic_key,回退到 seed 的 key
        tname = str(item.get("tname", "")).strip()
        item_topic_key = re.sub(r"\s+", "", tname).lower()[:16] if tname else seed_topic_key
        return DiscoveredContent(
            bvid=bvid,
            title=title_text,
            up_name=up_name,
            up_mid=up_mid,
            cover_url=str(item.get("pic", "")),
            duration=parse_duration(item.get("duration", 0)),
            view_count=view_count,
            like_count=like_count,
            favorite_count=favorite_count,
            danmaku_count=danmaku_count,
            comment_count=comment_count,
            share_count=share_count,
            topic_key=item_topic_key,
            topic_group=self._topic_group_from_title(title_text),
            description=clean_text(str(item.get("desc", item.get("description", "")))),
            style_key=ContentDiscoveryEngine.infer_style_key(
                title=title_text,
                description=clean_text(str(item.get("desc", item.get("description", "")))),
                source_strategy=self.name,
            ),
            source_strategy=self.name,
        )

    @staticmethod
    def _topic_key_from_seed_bvid(seed_bvid: str) -> str:
        """无 title 可用时的回退 — 为 preference seed 保留。"""
        return f"related:{seed_bvid.strip().lower()}"

    @staticmethod
    def _topic_key_from_title(title: str) -> str:
        """从视频标题派生语义 topic_key。

        策略:
        1. 若存在括号包裹的标签则提取 (如 【科技】→ 科技)
        2. 否则按标点/虚词切分,保留核心名词短语
        3. 截断到 8 字符以保持品类粒度,不落到视频级
        """
        if not title:
            return ""
        # 先尝试提取括号包裹的标签: 【xxx】、[xxx]、《xxx》
        bracket_match = re.search(r"[【\[《「]([^】\]》」]{2,8})[】\]》」]", title)
        if bracket_match:
            return re.sub(r"\s+", "", bracket_match.group(1)).lower()[:8]
        # 去除所有括号、标点、emoji、数字密集前缀
        cleaned = re.sub(
            r"[【】\[\]《》「」（）()！!？?：:，,。.·\-—|／/～~\d]+",
            " ",
            title,
        ).strip()
        # 按空白和常见中文虚词/连接词切分
        parts = re.split(r"[\s,，、]+", cleaned)
        # 过滤: 保留 2-8 字符的分段 (太短 = 噪声,太长 = 句子)
        meaningful = [p for p in parts if 2 <= len(p) <= 8]
        if meaningful:
            return re.sub(r"\s+", "", meaningful[0]).lower()[:8]
        # 回退: 清理后 title 的前 6 个字符
        fallback = re.sub(r"\s+", "", cleaned).lower()
        return fallback[:6] if fallback else ""

    @staticmethod
    def _topic_group_from_title(title: str) -> str:
        """从 title 提取粗粒度 topic group 用于多样性分桶。"""
        cleaned = re.sub(r"[【】\[\]《》「」\s]+", " ", title).strip()
        parts = cleaned.split()
        if parts:
            return re.sub(r"\s+", "", parts[0]).lower()[:8]
        return ""

    @staticmethod
    def _seed_bonus(seed_index: int) -> float:
        return max(0.0, 0.03 - seed_index * 0.01)

    @staticmethod
    def _depth_bonus(depth: int) -> float:
        return max(0.0, 0.02 - max(0, depth - 1) * 0.01)
