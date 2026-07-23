"""在 prompt 上限边界处对喜欢 / 厌恶话题做 LLM 评判的整理。

兴趣标签和厌恶话题会永远积累措辞变体：合并路径只会折叠精确的
``(name, category)`` 匹配，而权重衰减永远不会移除一个持续被强化的
变体。在真实画像上，这会让按权重排序的 top-64（真正进入 LLM
prompt 的切片）被同一概念的重复占用一半，把真正不同的兴趣挤出边界。

整理器运行一条分阶段、几乎不耗成本的流水线：

1. **规则层** —— 同一类别内的同名在代码中合并（无 LLM）；不同类别
   的同名作为防多义词簇强制交给 LLM 评判。
2. **聚类** —— embedding 余弦相似度（或子串回退）把疑似重复分组。
   只有多成员簇继续往下走。
3. **不合并记忆** —— 早期运行已判定为「不同」的对不再重问；
   没有未判定对的簇被跳过，所以稳态运行零 LLM 调用。
4. **LLM 评判** —— 分批调用（每次 32 个簇）返回 merge/keep
   *操作*，从不返回重写后的列表。
5. **确定性应用** —— 代码校验每个操作（成员逐字、整簇覆盖、
   反泛化规范名规则）并应用到扁平 preference 层；
   Onion 兴趣树通过 ``populate_from_flat_preference`` 重建，
   与常规层更新路径一致。

每次应用的运行都会把完整前快照写到
``data/memory/consolidation_runs/<run_id>.json``（回滚源），
并把审计条目写到 ``soul_changelog.md``。
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from openbiliclaw.llm.json_utils import (
    DEFAULT_STRUCTURED_MAX_TOKENS,
    parse_llm_json_tolerant,
)
from openbiliclaw.llm.prompts import build_profile_consolidation_prompt

if TYPE_CHECKING:
    from openbiliclaw.llm.base import LLMResponse
    from openbiliclaw.memory.manager import MemoryManager

logger = logging.getLogger(__name__)

# 整理在 64 条 prompt 上限之后仍然有效：按权重的 top-512 喜欢和
# 完整的厌恶存储（<= 128，受 _DISLIKED_TOPICS_STORE_CAP 限制）。
# 真实画像会积累 1000+ 兴趣标签；过窄的边界（v0.3.121 之前是 128）
# 让大多数措辞变体未被触及，所以重复权重分散在变体上，
# 永远进不了被截断的 top-64。512 覆盖整个有意义的存储；
# 只有深度 <0.5 权重的尾部留给衰减。
_LIKES_BOUNDARY = 512
_SIMILARITY_THRESHOLD = 0.85
_OVER_TARGET_SIMILARITY_FLOOR = 0.75
_OVER_TARGET_SIMILARITY_MAX_DROP = 0.10
_DEFAULT_MIN_INTERVAL_SECONDS = 12 * 3600
_STATE_FILENAME = "consolidation_state.json"
_RUNS_DIRNAME = "consolidation_runs"
_CHANGELOG_FILENAME = "soul_changelog.md"
# 已知「不同」对的记忆有上限，让状态文件保持有界，
# 即便连续数月的 12 小时运行也是如此。按 512 喜欢边界容量设定：
# 一次宽首轮可能评判数百个簇。
_NO_MERGE_PAIRS_CAP = 16000
# 每次 LLM 评判调用的簇数。一次跨越宽边界的巨型调用
# 风险是输出 token 上限在 JSON 中途爆掉（解析随后失败，
# 每个簇都被拒绝）；分批让每个响应更小，单个失败的批次
# 只损失自己的簇。
_JUDGE_CLUSTER_BATCH = 32
# 规范名的反泛化守卫。裸伞形词会把一个具体回避模式
# 变成宽泛的内容封禁。
_BANNED_GENERIC_CANONICALS = frozenset(
    {
        "低质",
        "低质内容",
        "营销",
        "营销内容",
        "标题党",
        "广告",
        "无聊",
        "套路",
        "水分",
        "游戏",
        "视频",
        "内容",
    }
)


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
    ) -> LLMResponse: ...


class SupportsEmbed(Protocol):
    async def embed(self, text: str) -> list[float]: ...


def rebuild_profile_tree(memory: MemoryManager, preference_data: dict[str, object]) -> None:
    """从扁平 preference 载荷重建 Onion 兴趣树。"""
    from openbiliclaw.soul.profile import OnionProfile

    soul_layer = memory.get_layer("soul")
    if not soul_layer.data:
        return
    try:
        profile = OnionProfile.from_dict(dict(soul_layer.data))
        profile.populate_from_flat_preference(preference_data)
        soul_layer.data.clear()
        soul_layer.data.update(profile.to_dict())
        soul_layer.save()
        sync = getattr(memory, "sync_profile_files", None)
        if callable(sync):
            sync(profile)
    except Exception:
        logger.exception("Failed to rebuild profile tree after consolidation")


@dataclass
class ConsolidationReport:
    """一次整理运行的结果。"""

    ran: bool = False
    throttled: bool = False
    skipped_clean: bool = False
    dry_run: bool = False
    run_id: str = ""
    rule_merges: list[str] = field(default_factory=list)
    clusters_sent: int = 0
    llm_batches: int = 0
    merges: list[dict[str, object]] = field(default_factory=list)
    rejected_clusters: list[str] = field(default_factory=list)
    likes_before: int = 0
    likes_after: int = 0
    dislikes_before: int = 0
    dislikes_after: int = 0
    likes_target_upper: int = _LIKES_BOUNDARY
    likes_target_soft: int = 450
    like_similarity_threshold: float = _SIMILARITY_THRESHOLD
    archived_interests: list[str] = field(default_factory=list)
    protected_interests: list[str] = field(default_factory=list)
    inventory_reason: str = ""
    errors: list[str] = field(default_factory=list)


@dataclass
class _Cluster:
    cluster_id: str
    scope: str  # "likes" | "dislikes"
    members: list[str]
    member_categories: list[str] | None = None

    @property
    def member_keys(self) -> list[str]:
        """不合并对的键。多义词簇按类别区分重复名。"""
        if self.member_categories is None:
            return list(self.members)
        return [
            f"{name}::{category}"
            for name, category in zip(self.members, self.member_categories, strict=True)
        ]


def _pair_key(a: str, b: str) -> str:
    return "||".join(sorted((a, b)))


def _batch_count(item_count: int, batch_size: int) -> int:
    if item_count <= 0 or batch_size <= 0:
        return 0
    return (item_count + batch_size - 1) // batch_size


def _log_run_summary(report: ConsolidationReport, *, changed: bool) -> None:
    logger.info(
        "profile consolidation run completed: "
        "run_id=%s dry_run=%s clusters=%d llm_batches=%d changed=%s "
        "merges=%d rule_merges=%d rejected=%d archived=%d "
        "likes=%d->%d dislikes=%d->%d errors=%d",
        report.run_id,
        report.dry_run,
        report.clusters_sent,
        report.llm_batches,
        changed,
        len(report.merges),
        len(report.rule_merges),
        len(report.rejected_clusters),
        len(report.archived_interests),
        report.likes_before,
        report.likes_after,
        report.dislikes_before,
        report.dislikes_after,
        len(report.errors),
    )


def _qualified_member_key(name: str, category: str) -> str:
    return f"{name}::{category}" if category else name


def _member_name(ref: object) -> str:
    if isinstance(ref, dict):
        return str(ref.get("name", "")).strip()
    return str(ref).strip()


def _member_ref_key(ref: object) -> str:
    if isinstance(ref, dict):
        return _qualified_member_key(
            str(ref.get("name", "")).strip(),
            str(ref.get("category", "")).strip(),
        )
    return str(ref).strip()


def _interest_member_key(item: dict[str, Any]) -> str:
    return _qualified_member_key(
        str(item.get("name", "")).strip(),
        str(item.get("category", "")).strip(),
    )


def _normalize_name(name: str) -> str:
    return re.sub(r"\s+", "", str(name or "")).lower()


def _as_str_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value]
    return []


def _cosine(a: list[float], b: list[float]) -> float:
    from openbiliclaw.llm.embedding import cosine_similarity

    return cosine_similarity(a, b)


class ProfileConsolidator:
    """分阶段的喜欢/厌恶话题整理，含 LLM 评判的合并。"""

    def __init__(
        self,
        *,
        memory: MemoryManager,
        llm_service: SupportsStructuredTask | None,
        embedding_service: SupportsEmbed | None = None,
        data_dir: Path | str | None = None,
        min_interval_seconds: int = _DEFAULT_MIN_INTERVAL_SECONDS,
        likes_boundary: int = _LIKES_BOUNDARY,
        similarity_threshold: float = _SIMILARITY_THRESHOLD,
        like_target_upper: int = _LIKES_BOUNDARY,
        like_target_soft: int = 450,
        archive_enabled: bool = True,
    ) -> None:
        self._memory = memory
        self._llm_service = llm_service
        self._embedding_service = embedding_service
        resolved_dir = data_dir or getattr(memory, "_data_dir", None)
        self._data_dir = Path(resolved_dir) if resolved_dir else None
        self._min_interval_seconds = int(min_interval_seconds)
        self._likes_boundary = int(likes_boundary)
        self._similarity_threshold = float(similarity_threshold)
        self._like_target_upper = max(1, int(like_target_upper))
        self._like_target_soft = max(1, int(like_target_soft))
        self._archive_enabled = bool(archive_enabled)

    # -- 公开 API -----------------------------------------------------------

    def set_embedding_service(self, embedding_service: SupportsEmbed | None) -> None:
        """在构造之后挂载或替换 embedding 服务。"""
        self._embedding_service = embedding_service

    async def run_if_due(self, *, now: datetime | None = None) -> ConsolidationReport:
        """若节流间隔已到，则运行一次整理。

        当边界区域输入自上次完成的运行以来未变化时也会（廉价地）跳过，
        这样稳定画像上的 12 小时 tick 几乎零开销。
        """
        current = now or datetime.now()
        state = self._load_state()
        last_run_at = _parse_iso(str(state.get("last_run_at", "")))
        if (
            last_run_at is not None
            and (current - last_run_at).total_seconds() < self._min_interval_seconds
        ):
            return ConsolidationReport(throttled=True)

        digest = self._input_digest()
        if (
            digest
            and digest == state.get("last_input_digest")
            and not self._is_like_inventory_over_target()
        ):
            state["last_run_at"] = current.isoformat()
            self._save_state(state)
            return ConsolidationReport(skipped_clean=True)

        return await self.run(dry_run=False, now=current)

    async def run(self, *, dry_run: bool, now: datetime | None = None) -> ConsolidationReport:
        """执行一次整理运行。``dry_run`` 永不写入任何东西。"""
        current = now or datetime.now()
        report = ConsolidationReport(
            ran=True,
            dry_run=dry_run,
            run_id=current.strftime("%Y%m%d-%H%M%S"),
            likes_target_upper=self._like_target_upper,
            likes_target_soft=min(self._like_target_soft, self._like_target_upper),
        )

        preference_layer = self._memory.get_layer("preference")
        interests_raw = [
            dict(item)
            for item in preference_layer.data.get("interests", [])
            if isinstance(item, dict) and str(item.get("name", "")).strip()
        ]
        dislikes_raw = [
            str(item).strip()
            for item in preference_layer.data.get("disliked_topics", [])
            if str(item).strip()
        ]
        archived_raw = [
            dict(item)
            for item in preference_layer.data.get("archived_interests", [])
            if isinstance(item, dict) and str(item.get("name", "")).strip()
        ]
        report.likes_before = len(interests_raw)
        report.dislikes_before = len(dislikes_raw)

        before_snapshot = {
            "interests": [dict(item) for item in interests_raw],
            "archived_interests": [dict(item) for item in archived_raw],
            "disliked_topics": list(dislikes_raw),
        }

        # ── 阶段 0：规则层 —— 同名 + 同类别 ───────────────
        interests, rule_merges, homonym_groups = self._rule_merge_exact_names(interests_raw)
        report.rule_merges = rule_merges

        # ── 边界切片 ─────────────────────────────────────────────────
        ranked = sorted(interests, key=lambda item: _coerce_float(item.get("weight")), reverse=True)
        likes_boundary = (
            len(ranked) if len(ranked) > self._like_target_upper else self._likes_boundary
        )
        like_similarity_threshold = self._effective_like_similarity_threshold(len(ranked))
        report.like_similarity_threshold = like_similarity_threshold
        like_slice_names = [str(item["name"]) for item in ranked[:likes_boundary]]

        # ── 阶段 1：聚类 ────────────────────────────────────────────
        state = self._load_state()
        no_merge: set[str] = set(str(p) for p in state.get("no_merge_pairs", []))
        forced_clusters = [
            _Cluster(
                cluster_id=f"H{idx + 1}",
                scope="likes",
                members=[str(item.get("name", "")) for item in group],
                member_categories=[str(item.get("category", "")) for item in group],
            )
            for idx, group in enumerate(homonym_groups)
        ]
        like_clusters = await self._cluster(
            like_slice_names,
            scope="likes",
            similarity_threshold=like_similarity_threshold,
        )
        dislike_clusters = await self._cluster(dislikes_raw, scope="dislikes")
        clusters = [
            cluster
            for cluster in (*forced_clusters, *like_clusters, *dislike_clusters)
            if self._has_unjudged_pair(cluster, no_merge)
        ]
        report.clusters_sent = len(clusters)
        if clusters and self._llm_service is not None:
            report.llm_batches = _batch_count(len(clusters), _JUDGE_CLUSTER_BATCH)

        # ── 阶段 2：LLM 评判 ─────────────────────────────────────────
        valid_ops: list[dict[str, object]] = []
        judged_clusters: list[_Cluster] = []
        if clusters and self._llm_service is not None:
            try:
                ops_by_cluster = await self._judge(clusters)
            except Exception as exc:
                logger.warning("profile consolidation LLM call failed: %s", exc)
                report.errors.append(f"llm: {exc}")
                ops_by_cluster = {}
            for cluster in clusters:
                ops = ops_by_cluster.get(cluster.cluster_id, [])
                problem = self._validate_cluster_ops(cluster, ops)
                if problem:
                    report.rejected_clusters.append(f"{cluster.cluster_id}: {problem}")
                    continue
                judged_clusters.append(cluster)
                valid_ops.extend(
                    {**op, "scope": cluster.scope, "cluster_id": cluster.cluster_id}
                    for op in ops
                    if op.get("op") == "merge"
                )
        elif clusters:
            report.errors.append("llm: service unavailable")

        # ── 阶段 3：应用 ─────────────────────────────────────────────
        rename_map: dict[str, str] = {}
        for op in valid_ops:
            raw_members = op.get("members")
            display_members = raw_members if isinstance(raw_members, list) else []
            members = [_member_name(member) for member in display_members]
            member_keys = _as_str_list(op.get("_member_keys"))
            canonical = str(op.get("canonical", ""))
            if op["scope"] == "likes":
                interests = self._apply_like_merge(
                    interests, members, canonical, member_keys=member_keys
                )
            else:
                dislikes_raw = self._apply_dislike_merge(dislikes_raw, members, canonical)
            for member in display_members:
                if isinstance(member, str) and member != canonical:
                    rename_map[member] = canonical
            report.merges.append(
                {
                    "scope": op["scope"],
                    "members": display_members,
                    "canonical": canonical,
                    "reason": str(op.get("reason", "")),
                }
            )

        interests, archived_raw = self._apply_inventory_target(interests, archived_raw, report)

        report.likes_after = len(interests)
        report.dislikes_after = len(dislikes_raw)

        changed = bool(rule_merges or valid_ops or report.archived_interests)
        if dry_run:
            _log_run_summary(report, changed=changed)
            return report

        if changed:
            preference_layer.data["interests"] = interests
            preference_layer.data["archived_interests"] = archived_raw
            preference_layer.data["disliked_topics"] = dislikes_raw
            preference_layer.save()
            self._rebuild_profile_tree(preference_layer.data)
            overrides_before = self._remap_overrides(rename_map)
            self._write_run_record(report, before_snapshot, rename_map, overrides_before)
            self._append_changelog(report, current)

        # 记录已判定为不同的对，让未来运行跳过它们；
        # 即便无操作运行也要推进运行簿记。
        for cluster in judged_clusters:
            if cluster.member_categories is not None:
                if not any(op.get("cluster_id") == cluster.cluster_id for op in valid_ops):
                    keys = cluster.member_keys
                    for i, a in enumerate(keys):
                        for b in keys[i + 1 :]:
                            no_merge.add(_pair_key(a, b))
                continue
            survivors = self._cluster_survivors(cluster, valid_ops)
            for i, a in enumerate(survivors):
                for b in survivors[i + 1 :]:
                    no_merge.add(_pair_key(a, b))
        state["no_merge_pairs"] = sorted(no_merge)[:_NO_MERGE_PAIRS_CAP]
        state["last_run_at"] = current.isoformat()
        state["last_input_digest"] = self._input_digest()
        if changed:
            state["last_applied_run_id"] = report.run_id
        self._save_state(state)
        _log_run_summary(report, changed=changed)
        return report

    # -- 阶段 0：规则合并 ---------------------------------------------------

    def _is_like_inventory_over_target(self) -> bool:
        preference_layer = self._memory.get_layer("preference")
        interests = [
            item
            for item in preference_layer.data.get("interests", [])
            if isinstance(item, dict) and str(item.get("name", "")).strip()
        ]
        return len(interests) > self._like_target_upper

    def _apply_inventory_target(
        self,
        interests: list[dict[str, Any]],
        archived: list[dict[str, Any]],
        report: ConsolidationReport,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """归档低价值活跃喜欢，直到活跃库存低于目标。"""
        report.likes_target_upper = self._like_target_upper
        report.likes_target_soft = min(self._like_target_soft, self._like_target_upper)
        if not self._archive_enabled:
            if len(interests) > self._like_target_upper:
                report.inventory_reason = "archive_disabled"
            return interests, archived
        if len(interests) <= self._like_target_upper:
            return interests, archived

        protected_keys = self._protected_like_keys()
        protected_names = [
            str(item.get("name", "")).strip()
            for item in interests
            if _normalize_name(str(item.get("name", ""))) in protected_keys
        ]
        report.protected_interests = list(dict.fromkeys(name for name in protected_names if name))

        target = report.likes_target_soft
        protected_count = len(report.protected_interests)
        if protected_count > self._like_target_upper:
            report.inventory_reason = "protected_inventory_exceeds_target"
            target = protected_count

        archive_count = max(0, len(interests) - target)
        if archive_count <= 0:
            return interests, archived

        candidates = [
            item
            for item in interests
            if _normalize_name(str(item.get("name", ""))) not in protected_keys
        ]
        candidates.sort(key=_archive_rank_key)
        to_archive = candidates[:archive_count]
        if len(to_archive) < archive_count and not report.inventory_reason:
            report.inventory_reason = "no_archive_candidates"

        archive_keys = {_interest_member_key(item) for item in to_archive}
        active = [item for item in interests if _interest_member_key(item) not in archive_keys]
        new_archived = [dict(item) for item in to_archive]
        report.archived_interests = [str(item.get("name", "")) for item in new_archived]
        return active, [*new_archived, *archived]

    def _protected_like_keys(self) -> set[str]:
        loader = getattr(self._memory, "load_profile_overrides", None)
        if not callable(loader):
            return set()
        try:
            overrides = loader()
            interest_edits = getattr(overrides, "interest_edits", {})
            likes = interest_edits.get("likes") if isinstance(interest_edits, dict) else None
            if likes is None:
                return set()
            names: list[str] = []
            names.extend(
                str(add.domain)
                for add in getattr(likes, "add_domains", [])
                if str(getattr(add, "domain", "")).strip()
            )
            names.extend(str(name) for name in getattr(likes, "weight_pins", {}) if str(name))
            names.extend(str(name) for name in getattr(likes, "specific_edits", {}) if str(name))
            return {_normalize_name(name) for name in names if _normalize_name(name)}
        except Exception:
            logger.debug("Failed to load profile overrides for archive protection", exc_info=True)
            return set()

    def _effective_like_similarity_threshold(self, active_like_count: int) -> float:
        if active_like_count <= self._like_target_upper:
            return round(self._similarity_threshold, 4)
        target_span = max(
            self._like_target_upper - min(self._like_target_soft, self._like_target_upper),
            1,
        )
        pressure = min(1.0, (active_like_count - self._like_target_upper) / target_span)
        floor = min(self._similarity_threshold, _OVER_TARGET_SIMILARITY_FLOOR)
        threshold = self._similarity_threshold - (_OVER_TARGET_SIMILARITY_MAX_DROP * pressure)
        return round(max(floor, threshold), 4)

    def _rule_merge_exact_names(
        self, interests: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], list[str], list[list[dict[str, Any]]]]:
        """仅合并同一类别内同规范化名的条目。"""
        by_key: dict[tuple[str, str], dict[str, Any]] = {}
        order: list[tuple[str, str]] = []
        merges: list[str] = []
        for item in interests:
            category = str(item.get("category", "")).strip()
            key = (_normalize_name(str(item["name"])), category)
            existing = by_key.get(key)
            if existing is None:
                by_key[key] = item
                order.append(key)
                continue
            winner, loser = (
                (item, existing)
                if _coerce_float(item.get("weight")) > _coerce_float(existing.get("weight"))
                else (existing, item)
            )
            merged = dict(winner)
            merged["weight"] = max(
                _coerce_float(winner.get("weight")), _coerce_float(loser.get("weight"))
            )
            merged["first_seen"] = _earliest(winner.get("first_seen"), loser.get("first_seen"))
            merged["last_seen"] = _latest(winner.get("last_seen"), loser.get("last_seen"))
            by_key[key] = merged
            merges.append(f"同名同类合并: {winner.get('name')} ({category})")

        result = [by_key[key] for key in order]
        homonym_by_name: dict[str, list[dict[str, Any]]] = {}
        for item in result:
            homonym_by_name.setdefault(_normalize_name(str(item.get("name", ""))), []).append(item)
        homonym_groups = [group for group in homonym_by_name.values() if len(group) >= 2]
        return result, merges, homonym_groups

    # -- 阶段 1：聚类 ------------------------------------------------------

    async def _cluster(
        self,
        names: list[str],
        *,
        scope: str,
        similarity_threshold: float | None = None,
    ) -> list[_Cluster]:
        unique_names = list(dict.fromkeys(name for name in names if name))
        if len(unique_names) < 2:
            return []
        prefix = "L" if scope == "likes" else "D"
        threshold = (
            self._similarity_threshold if similarity_threshold is None else similarity_threshold
        )

        groups: list[list[str]] = []
        if self._embedding_service is not None:
            vectors: dict[str, list[float]] = {}
            for name in unique_names:
                try:
                    vec = await self._embedding_service.embed(name)
                except Exception:
                    vec = []
                if vec:
                    vectors[name] = vec
            embeddable = [n for n in unique_names if n in vectors]
            assigned: set[str] = set()
            for i, name in enumerate(embeddable):
                if name in assigned:
                    continue
                group = [name]
                assigned.add(name)
                for other in embeddable[i + 1 :]:
                    if other in assigned:
                        continue
                    if _cosine(vectors[name], vectors[other]) >= threshold:
                        group.append(other)
                        assigned.add(other)
                if len(group) >= 2:
                    groups.append(group)
        else:
            # 无 embedding 时回退：子串包含分组。
            assigned = set()
            for i, name in enumerate(unique_names):
                if name in assigned:
                    continue
                norm = _normalize_name(name)
                group = [name]
                for other in unique_names[i + 1 :]:
                    if other in assigned:
                        continue
                    other_norm = _normalize_name(other)
                    if norm and other_norm and (norm in other_norm or other_norm in norm):
                        group.append(other)
                        assigned.add(other)
                if len(group) >= 2:
                    assigned.add(name)
                    groups.append(group)

        return [
            _Cluster(cluster_id=f"{prefix}{idx + 1}", scope=scope, members=group)
            for idx, group in enumerate(groups)
        ]

    @staticmethod
    def _has_unjudged_pair(cluster: _Cluster, no_merge: set[str]) -> bool:
        keys = cluster.member_keys
        for i, a in enumerate(keys):
            for b in keys[i + 1 :]:
                if _pair_key(a, b) not in no_merge:
                    return True
        return False

    # -- 阶段 2：LLM 评判 ----------------------------------------------------

    async def _judge(self, clusters: list[_Cluster]) -> dict[str, list[dict[str, Any]]]:
        """按每次 ``_JUDGE_CLUSTER_BATCH`` 个簇分批评判。

        一个批次失败只会丢自己的簇（下次运行重新聚类）；只有当
        *所有* 批次都失败时调用才上抛，以便调用方的错误报告
        在 LLM 完全不可用时仍能触发。
        """
        if self._llm_service is None:
            return {}
        ops_by_cluster: dict[str, list[dict[str, Any]]] = {}
        batches = [
            clusters[i : i + _JUDGE_CLUSTER_BATCH]
            for i in range(0, len(clusters), _JUDGE_CLUSTER_BATCH)
        ]
        last_error: Exception | None = None
        succeeded = 0
        for batch in batches:
            try:
                ops_by_cluster.update(await self._judge_batch(batch))
                succeeded += 1
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "profile consolidation judge batch failed (%d clusters): %s",
                    len(batch),
                    exc,
                )
        if batches and succeeded == 0 and last_error is not None:
            raise last_error
        return ops_by_cluster

    async def _judge_batch(self, clusters: list[_Cluster]) -> dict[str, list[dict[str, Any]]]:
        if self._llm_service is None:
            return {}
        preference_layer = self._memory.get_layer("preference")
        weight_by_name = {
            str(item.get("name", "")): _coerce_float(item.get("weight"))
            for item in preference_layer.data.get("interests", [])
            if isinstance(item, dict)
        }
        weight_by_key: dict[str, float] = {}
        category_by_name: dict[str, str] = {}
        best_weight_by_name: dict[str, float] = {}
        for item in preference_layer.data.get("interests", []):
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", ""))
            weight = _coerce_float(item.get("weight"))
            key = _interest_member_key(item)
            weight_by_key[key] = max(weight_by_key.get(key, 0.0), weight)
            if name not in best_weight_by_name or weight > best_weight_by_name[name]:
                best_weight_by_name[name] = weight
                category_by_name[name] = str(item.get("category", ""))

        ops_by_cluster: dict[str, list[dict[str, Any]]] = {}
        likes_payload: list[dict[str, object]] = [
            {
                "cluster_id": c.cluster_id,
                "members": [
                    {
                        "name": name,
                        "weight": round(
                            weight_by_key.get(
                                _qualified_member_key(
                                    name,
                                    c.member_categories[idx]
                                    if c.member_categories is not None
                                    else category_by_name.get(name, ""),
                                ),
                                weight_by_name.get(name, 0.0),
                            ),
                            3,
                        ),
                        "category": (
                            c.member_categories[idx]
                            if c.member_categories is not None
                            else category_by_name.get(name, "")
                        ),
                    }
                    for idx, name in enumerate(c.members)
                ],
            }
            for c in clusters
            if c.scope == "likes"
        ]
        dislikes_payload: list[dict[str, object]] = [
            {"cluster_id": c.cluster_id, "members": list(c.members)}
            for c in clusters
            if c.scope == "dislikes"
        ]
        messages = build_profile_consolidation_prompt(
            likes_clusters=likes_payload,
            dislikes_clusters=dislikes_payload,
        )
        response = await self._llm_service.complete_structured_task(
            system_instruction=messages[0]["content"],
            user_input=messages[1]["content"],
            temperature=0.2,
            max_tokens=DEFAULT_STRUCTURED_MAX_TOKENS,
            caller="soul.consolidation",
        )
        parsed = parse_llm_json_tolerant(response.content)
        if not isinstance(parsed, dict):
            raise ValueError("consolidation response is not a JSON object")
        for scope_key in ("likes", "dislikes"):
            entries = parsed.get(scope_key)
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                cluster_id = str(entry.get("cluster_id", ""))
                if cluster_id:
                    ops_by_cluster.setdefault(cluster_id, []).append(entry)
        return ops_by_cluster

    def _validate_cluster_ops(self, cluster: _Cluster, ops: list[dict[str, Any]]) -> str:
        """返回拒绝原因，若簇操作有效则返回 ''。"""
        if not ops:
            return "no ops returned"
        records = [
            {
                "name": name,
                "category": (
                    cluster.member_categories[idx] if cluster.member_categories is not None else ""
                ),
                "key": (
                    _qualified_member_key(name, cluster.member_categories[idx])
                    if cluster.member_categories is not None
                    else name
                ),
            }
            for idx, name in enumerate(cluster.members)
        ]
        record_keys = {record["key"] for record in records}
        covered: list[str] = []

        def consume(ref: object) -> tuple[str, str] | None:
            name = _member_name(ref)
            if not name:
                return None
            if isinstance(ref, dict):
                key = _member_ref_key(ref)
                if key in record_keys and key not in covered:
                    return key, name
                return None
            if cluster.member_categories is not None:
                for record in records:
                    if record["name"] == name and record["key"] not in covered:
                        return record["key"], name
                return None
            if name in record_keys and name not in covered:
                return name, name
            return None

        for op in ops:
            kind = str(op.get("op", ""))
            if kind == "keep":
                ref = op.get("member", op.get("name", ""))
                consumed = consume(ref)
                if consumed is None:
                    return f"keep references unknown member: {ref!r}"
                key, _name = consumed
                covered.append(key)
                op["_member_keys"] = [key]
            elif kind == "merge":
                raw_members = op.get("members", [])
                member_refs = raw_members if isinstance(raw_members, list) else []
                members: list[str] = []
                member_keys: list[str] = []
                for member_ref in member_refs:
                    consumed = consume(member_ref)
                    if consumed is None:
                        return f"merge references unknown member: {member_ref!r}"
                    key, name = consumed
                    member_keys.append(key)
                    members.append(name)
                    covered.append(key)
                if len(members) < 2:
                    return "merge with fewer than 2 members"
                canonical = str(op.get("canonical", "")).strip()
                problem = self._validate_canonical(canonical, members, scope=cluster.scope)
                if problem:
                    return problem
                op["_member_keys"] = member_keys
            else:
                return f"unknown op kind: {kind!r}"
        if sorted(covered) != sorted(record_keys):
            return "ops do not cover each member exactly once"
        return ""

    @staticmethod
    def _validate_canonical(canonical: str, members: list[str], *, scope: str) -> str:
        if not canonical:
            return "merge without canonical"
        if _normalize_name(canonical) in {_normalize_name(b) for b in _BANNED_GENERIC_CANONICALS}:
            return f"canonical is a banned umbrella term: {canonical!r}"
        shortest = min(len(m) for m in members)
        member_norms = {_normalize_name(member) for member in members}
        # 规范名比每个成员都短得多是向上泛化的特征
        # （"低质内容" <- 长的具体回避模式）。成员自身豁免
        # （选最短成员作为规范名对 likes 来说没问题）。
        if _normalize_name(canonical) not in member_norms and len(canonical) < shortest * 0.5:
            return f"canonical looks over-generalized for {scope}: {canonical!r}"
        return ""

    @staticmethod
    def _cluster_survivors(cluster: _Cluster, valid_ops: list[dict[str, object]]) -> list[str]:
        """本簇操作后仍然不同的名字（保留项 + 规范名）。"""
        merged_away: set[str] = set()
        canonicals: list[str] = []
        for op in valid_ops:
            if op.get("cluster_id") != cluster.cluster_id:
                continue
            members = _as_str_list(op.get("_member_keys"))
            if not members:
                raw_members = op.get("members", [])
                member_refs = raw_members if isinstance(raw_members, list) else []
                members = [_member_name(member) for member in member_refs if member]
            canonical = str(op.get("canonical", ""))
            canonicals.append(canonical)
            merged_away.update(m for m in members if m != canonical)
        kept = [key for key in cluster.member_keys if key not in merged_away]
        return list(dict.fromkeys([*kept, *canonicals]))

    # -- 阶段 3：应用 --------------------------------------------------------------

    @staticmethod
    def _apply_like_merge(
        interests: list[dict[str, Any]],
        members: list[str],
        canonical: str,
        *,
        member_keys: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        member_set = set(member_keys or members)
        has_qualified_keys = any("::" in key for key in member_set)

        def is_member(item: dict[str, Any]) -> bool:
            name = str(item.get("name", "")).strip()
            key = _interest_member_key(item)
            return key in member_set or (not has_qualified_keys and name in member_set)

        member_items = [item for item in interests if is_member(item)]
        if not member_items:
            return interests
        base = max(member_items, key=lambda item: _coerce_float(item.get("weight")))
        canonical_category = str(base.get("category", "")).strip()

        def is_existing_canonical(item: dict[str, Any]) -> bool:
            if str(item.get("name", "")).strip() != canonical:
                return False
            if not has_qualified_keys:
                return True
            return str(item.get("category", "")).strip() == canonical_category

        # 一条已存在、名字就叫 `canonical` 的条目也会折进合并，
        # 否则重命名会产生重复。对多义词簇，只折入合并类别的
        # canonical；另一个类别中的同名是不同兴趣。
        involved = [item for item in interests if is_member(item) or is_existing_canonical(item)]
        base = max(involved, key=lambda item: _coerce_float(item.get("weight")))
        merged = dict(base)
        merged["name"] = canonical
        merged["weight"] = max(_coerce_float(item.get("weight")) for item in involved)
        merged["first_seen"] = _earliest(*(item.get("first_seen") for item in involved))
        merged["last_seen"] = _latest(*(item.get("last_seen") for item in involved))
        aliases = _merged_aliases(involved, canonical)
        if aliases:
            merged["aliases"] = aliases
        else:
            merged.pop("aliases", None)

        result: list[dict[str, Any]] = []
        inserted = False
        for item in interests:
            if is_member(item) or is_existing_canonical(item):
                if not inserted:
                    result.append(merged)
                    inserted = True
                continue
            result.append(item)
        return result

    @staticmethod
    def _apply_dislike_merge(dislikes: list[str], members: list[str], canonical: str) -> list[str]:
        member_set = set(members)
        result: list[str] = []
        inserted = False
        for topic in dislikes:
            if topic in member_set or topic == canonical:
                if not inserted:
                    # 保留最前（最近）成员的位置，让时序在整理后仍能保留。
                    result.append(canonical)
                    inserted = True
                continue
            result.append(topic)
        if not inserted and members:
            result.append(canonical)
        return result

    def _rebuild_profile_tree(self, preference_data: dict[str, object]) -> None:
        """从整理后的扁平 preference 重建 Onion 兴趣树。"""
        rebuild_profile_tree(self._memory, preference_data)

    # -- 覆盖透传 + 回滚 ------------------------------------------------

    def _remap_overrides(self, rename_map: dict[str, str]) -> dict[str, object] | None:
        """把合并重命名映射应用到用户画像覆盖。

        覆盖按精确字符串匹配（例如被移除的厌恶话题），所以原存储重命名
        会让用户的编辑静默失配，使被移除的回避话题以规范名复活。
        当有变更时返回重映射前的覆盖字典（用于回滚）。
        """
        if not rename_map:
            return None
        loader = getattr(self._memory, "load_profile_overrides", None)
        saver = getattr(self._memory, "save_profile_overrides", None)
        if not callable(loader) or not callable(saver):
            return None
        try:
            from openbiliclaw.soul.overrides import ProfileOverrides

            overrides = loader()
            raw: dict[str, object] = dict(overrides.to_dict())
            remapped = _remap_strings(raw, rename_map)
            if json.dumps(raw, ensure_ascii=False, sort_keys=True) == json.dumps(
                remapped, ensure_ascii=False, sort_keys=True
            ):
                return None
            saver(ProfileOverrides.from_dict(remapped))
            return raw
        except Exception:
            logger.exception("Failed to remap profile overrides after consolidation")
            return None

    def revert(self, run_id: str) -> bool:
        """从运行记录恢复 preference 存储（及覆盖）。

        被回滚的合并的成员对会加入不合并记忆，
        这样下次计划运行不会简单重做用户刚回滚的同一合并。
        """
        if self._data_dir is None:
            return False
        record_path = self._data_dir / _RUNS_DIRNAME / f"{run_id}.json"
        if not record_path.exists():
            return False
        try:
            record = json.loads(record_path.read_text(encoding="utf-8"))
        except Exception:
            logger.exception("Failed to read consolidation run record %s", run_id)
            return False
        before = record.get("before")
        if not isinstance(before, dict):
            return False

        preference_layer = self._memory.get_layer("preference")
        preference_layer.data["interests"] = [
            dict(item) for item in before.get("interests", []) if isinstance(item, dict)
        ]
        preference_layer.data["archived_interests"] = [
            dict(item) for item in before.get("archived_interests", []) if isinstance(item, dict)
        ]
        preference_layer.data["disliked_topics"] = _as_str_list(before.get("disliked_topics"))
        preference_layer.save()
        self._rebuild_profile_tree(preference_layer.data)

        overrides_before = record.get("overrides_before")
        if isinstance(overrides_before, dict):
            saver = getattr(self._memory, "save_profile_overrides", None)
            if callable(saver):
                try:
                    from openbiliclaw.soul.overrides import ProfileOverrides

                    saver(ProfileOverrides.from_dict(overrides_before))
                except Exception:
                    logger.exception("Failed to restore profile overrides for %s", run_id)

        # 把被回滚的合并钉为已知「不同」，让下次运行不会重做。
        state = self._load_state()
        no_merge = set(str(p) for p in state.get("no_merge_pairs", []))
        for merge in record.get("merges", []):
            if not isinstance(merge, dict):
                continue
            names = [*_as_str_list(merge.get("members")), str(merge.get("canonical", ""))]
            names = [n for n in dict.fromkeys(names) if n]
            for i, a in enumerate(names):
                for b in names[i + 1 :]:
                    no_merge.add(_pair_key(a, b))
        state["no_merge_pairs"] = sorted(no_merge)[:_NO_MERGE_PAIRS_CAP]
        state["last_input_digest"] = ""
        self._save_state(state)

        try:
            with (self._data_dir / _CHANGELOG_FILENAME).open("a", encoding="utf-8") as fh:
                fh.write(f"\n## 画像整理回滚 {run_id}（{datetime.now().isoformat()}）\n")
        except Exception:
            logger.debug("Failed to append revert changelog", exc_info=True)
        return True

    # -- 持久化 -------------------------------------------------------------------

    def _state_path(self) -> Path | None:
        return self._data_dir / _STATE_FILENAME if self._data_dir else None

    def _load_state(self) -> dict[str, Any]:
        path = self._state_path()
        if path is None or not path.exists():
            return {}
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            return loaded if isinstance(loaded, dict) else {}
        except Exception:
            return {}

    def _save_state(self, state: dict[str, Any]) -> None:
        path = self._state_path()
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            logger.debug("Failed to save consolidation state", exc_info=True)

    def _input_digest(self) -> str:
        import hashlib

        preference_layer = self._memory.get_layer("preference")
        interests = [
            (
                str(item.get("name", "")),
                str(item.get("category", "")),
                round(_coerce_float(item.get("weight")), 3),
            )
            for item in preference_layer.data.get("interests", [])
            if isinstance(item, dict)
        ]
        ranked = sorted(interests, key=lambda item: item[2], reverse=True)
        boundary_items = sorted(
            (name, category) for name, category, _ in ranked[: self._likes_boundary]
        )
        dislikes = sorted(str(item) for item in preference_layer.data.get("disliked_topics", []))
        payload = json.dumps([boundary_items, dislikes], ensure_ascii=False)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]

    def _write_run_record(
        self,
        report: ConsolidationReport,
        before_snapshot: dict[str, object],
        rename_map: dict[str, str],
        overrides_before: dict[str, object] | None = None,
    ) -> None:
        if self._data_dir is None:
            return
        runs_dir = self._data_dir / _RUNS_DIRNAME
        try:
            runs_dir.mkdir(parents=True, exist_ok=True)
            record = {
                "run_id": report.run_id,
                "kind": "consolidation",
                "before": before_snapshot,
                "like_similarity_threshold": report.like_similarity_threshold,
                "rule_merges": report.rule_merges,
                "merges": report.merges,
                "rename_map": rename_map,
                "rejected_clusters": report.rejected_clusters,
                "overrides_before": overrides_before,
            }
            (runs_dir / f"{report.run_id}.json").write_text(
                json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception:
            logger.debug("Failed to write consolidation run record", exc_info=True)

    def _append_changelog(self, report: ConsolidationReport, now: datetime) -> None:
        if self._data_dir is None:
            return
        lines = [
            f"\n## 画像整理 {report.run_id}（{now.strftime('%Y-%m-%d %H:%M')}）\n",
            f"- 兴趣 {report.likes_before} → {report.likes_after}，"
            f"避雷 {report.dislikes_before} → {report.dislikes_after}\n",
        ]
        if report.archived_interests:
            lines.append(f"- [归档] {len(report.archived_interests)} 个低权重长尾兴趣\n")
        if report.inventory_reason:
            lines.append(f"- [库存] {report.inventory_reason}\n")
        for merge in report.merges:
            members = " / ".join(_as_str_list(merge.get("members")))
            lines.append(f"- [{merge.get('scope')}] {members} → {merge.get('canonical')}\n")
        for rule_merge in report.rule_merges:
            lines.append(f"- [规则] {rule_merge}\n")
        try:
            with (self._data_dir / _CHANGELOG_FILENAME).open("a", encoding="utf-8") as fh:
                fh.writelines(lines)
        except Exception:
            logger.debug("Failed to append consolidation changelog", exc_info=True)


def _coerce_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _archive_rank_key(item: dict[str, Any]) -> tuple[float, str, str, str]:
    return (
        _coerce_float(item.get("weight")),
        str(item.get("last_seen", "")),
        str(item.get("first_seen", "")),
        str(item.get("name", "")),
    )


def _merged_aliases(items: list[dict[str, Any]], canonical: str) -> list[str]:
    aliases: list[str] = []
    seen: set[str] = set()
    canonical_norm = _normalize_name(canonical)
    for item in items:
        raw_terms: list[object] = [item.get("name", "")]
        existing_aliases = item.get("aliases", [])
        if isinstance(existing_aliases, list):
            raw_terms.extend(existing_aliases)
        for raw in raw_terms:
            alias = str(raw).strip()
            alias_norm = _normalize_name(alias)
            if not alias or not alias_norm or alias_norm == canonical_norm or alias_norm in seen:
                continue
            aliases.append(alias)
            seen.add(alias_norm)
    return aliases


def _parse_iso(raw: str) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _earliest(*values: object) -> str:
    candidates = [str(v) for v in values if v]
    return min(candidates) if candidates else ""


def _latest(*values: object) -> str:
    candidates = [str(v) for v in values if v]
    return max(candidates) if candidates else ""


def _remap_strings(value: object, rename_map: dict[str, str]) -> Any:
    """按 ``rename_map`` 递归替换精确字符串匹配。

    只重写整串相等（绝不替换子串），覆盖列表项、字典字符串值和字典键。
    冲突的重命名键保留首次出现。
    """
    if isinstance(value, str):
        return rename_map.get(value, value)
    if isinstance(value, list):
        seen: set[str] = set()
        result: list[Any] = []
        for item in value:
            remapped = _remap_strings(item, rename_map)
            if isinstance(remapped, str):
                if remapped in seen:
                    continue
                seen.add(remapped)
            result.append(remapped)
        return result
    if isinstance(value, dict):
        out: dict[Any, Any] = {}
        for key, item in value.items():
            new_key = rename_map.get(key, key) if isinstance(key, str) else key
            if new_key in out:
                continue
            out[new_key] = _remap_strings(item, rename_map)
        return out
    return value
