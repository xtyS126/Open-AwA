"""统一关键词规划器 —— 缺口拉动的合并关键词生成（P1.6）。

规划器是 Discover 双缓冲反压模型的生成半边（设计规范 §5.2）。它作为
独立后台对象运行（在 ``api/runtime_context.py`` 中构造，由刷新控制器
的 ``run_forever`` 启动），当 ``[discovery].unified_keyword_planner_enabled``
开关打开时，周期性地：

1. 找出 ``due`` 平台——其关键词缓存（当前 ``profile_kw_digest`` 下的
   ``pending`` 行）低于 ``kw_cache_low`` **且** 真实存在搜索缺口（控制
   器既有的内容池补货口径，含原料余量 + 在途行——不只是可见池行）。
   B 站额外在既有催化剂触发时进入 ``due``（池低于目标 或
   ``signal_event_threshold`` 待处理信号事件），即使其缓存不低于 low。
2. 对每个 due 平台，过期 stale-digest 的 ``pending`` 行，然后构造一个
   合并的 ``<platforms>`` 块，发起 **一次** 结构化 LLM 调用覆盖所有
   due 平台。解析出的关键词按平台以 ``pending`` 形式插入当前 digest。
3. 拒绝 vs 失败（P2.2）。当合并调用 **成功** 时，模型对某平台显式返回
   空列表 ``[]`` 视为 **主动拒绝**（其供给优势与用户不匹配）——本轮
   跳过且不使用兴趣名回退（保持当前 pending，若下次仍 due 再重新
   提供）。模型 **省略** 的平台仍走回退。当合并调用 **整体失败**
   （抛错 / 无可用响应）时，所有 due 平台回退到确定性兴趣名。
4. 轮换润色（P2.3）。``claim_keywords`` 是 FIFO（最老的 pending 优
   先），所以生成的词会被公平轮换。一轮生成后，未拒绝的 due 平台若
   pending 仍低于 ``kw_cache_low``，保守地从其最老的 ``used`` 词通过
   ``recycle_oldest_used`` 顶上（无额外 LLM 调用），让多样性持续流
   动；被拒绝的平台则不动。稀疏画像回收（生成 + 回退都没产生新词）
   仍作为更深层的安全阀保留。

它从不抓取——抓取（claim → search）属于 P1.7。单次并发通过 DB 级
规划器锁强制，其写事务在 LLM 调用 **之前** 释放，避免慢 provider
阻塞其他写者。
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import socket
import time
import uuid
from typing import TYPE_CHECKING, Any, Protocol, cast

from openbiliclaw.discovery.keyword_digest import profile_kw_digest
from openbiliclaw.discovery.pool_snapshot import (
    build_cold_start_pool_snapshot,
    build_pool_distribution_snapshot,
)
from openbiliclaw.discovery.strategies._utils import (
    build_query_generation_profile_summary,
    cached_embedding_lookup,
)
from openbiliclaw.llm.prompt_cache import PromptLayerRenderCache, profile_prompt_layers
from openbiliclaw.llm.prompts import (
    build_merged_keywords_prompt,
    parse_merged_keywords_with_presence,
)
from openbiliclaw.llm.task_options import without_core_memory_kwargs

if TYPE_CHECKING:
    from openbiliclaw.config import Config, DiscoveryConfig
    from openbiliclaw.soul.profile import SoulProfile

logger = logging.getLogger(__name__)

# 规范的长形平台标识。这些与关键词存储、pool-source 份额、合并 prompt
# 构建器所期望的键一致——这里不用短码（xhs/dy/yt/bili）。
_PLANNER_PLATFORMS: tuple[str, ...] = (
    "bilibili",
    "xiaohongshu",
    "douyin",
    "youtube",
    "twitter",
)
_BILIBILI = "bilibili"
# 规划器在每轮生成之前回收泄漏出 claim 租约的在途行。``executing`` 行
# 属于真正的异步（XHS）任务，所以给它们的超时比普通 claim 租约宽得多。
_EXECUTING_TIMEOUT_MULTIPLIER = 6
# P3.2 动态缓存高水位：当某平台观测 yield 较低（大量重复命中 → 需要
# 更多词才能填同样的缺口）时，其生成目标可放大到此倍数的静态
# ``kw_cache_high``。当已使用关键词少于 ``_DYNAMIC_MIN_SAMPLES`` 时
# yield 估计噪声太大 → 回退到静态 high。
_DYNAMIC_HIGH_CAP_MULT = 3
_DYNAMIC_MIN_SAMPLES = 10
# P3.1 各平台话题饱和度：某平台自身的 fresh 池化行少于该数时回退到
# 全局 avoid（数据太少无法判断）；超过底线后，某话题计数达到
# max(_MIN, platform_total // _DIV) 时视为"对该平台已饱和"。
_PER_PLATFORM_AVOID_FLOOR = 10
_PER_PLATFORM_AVOID_MIN_THRESHOLD = 5
_PER_PLATFORM_AVOID_DIVISOR = 5
# P3.3 数据驱动的供给优势：某平台实际准入（未踩踩、全时段）的
# topic_groups 排名前列者，作为 per-call 提示跟随，补充静态
# <supply_advantage> 表。平台至少需要 _FLOOR 条准入行后该信号才被
# 信任（否则冷启动 → 仅静态表）；某话题需要
# max(_MIN, total // _DIV) 条准入才算优势，最多呈现 _TOP 条。会减去
# 该平台当前的 avoid 集合，使某话题不会同时是"倾斜投入"和"回避"。
_PER_PLATFORM_SUPPLY_FLOOR = 10
_PER_PLATFORM_SUPPLY_MIN_THRESHOLD = 3
_PER_PLATFORM_SUPPLY_DIVISOR = 10
_PER_PLATFORM_SUPPLY_TOP = 8
# 合并生成的 token 预算。合并调用是系统中输出最大的调用（每个 due
# 平台 × 最多 gen_batch 个关键词，落在同一个 JSON 中），固定 max_tokens
# 可能截断尾部平台——它们会落到兴趣名回退。这里按每轮实际请求量
# （gen_batch 封顶后的 needs 之和）配额 max_tokens，并给每个词留出宽裕
# 预算（中文短语 + JSON 引号开销）。超额配额几乎是免费的：max_tokens
# 是按真实输出计费的上限，不是固定费用。绝不低于此前的 4096 默认值。
_MERGED_TOKENS_PER_KEYWORD = 48
_MERGED_JSON_OVERHEAD_TOKENS = 1024
_MERGED_MIN_MAX_TOKENS = 4096


def _as_str_list(value: object) -> list[str]:
    """把松散类型的 JSON 值整理成干净的 ``list[str]``。"""
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


class KeywordDeficitSource(Protocol):
    """规划器复用的缺口口径（由刷新控制器实现）。

    规划器刻意不重新计算池缺口——它询问控制器，以共享驱动
    ``_build_source_replenishment_plan`` 的同一份在途 / 原料余量核算。
    """

    def keyword_planner_real_deficit(self, platform: str) -> int: ...

    def keyword_planner_bilibili_catalyst(self) -> bool: ...


class _SoulEngineLike(Protocol):
    async def get_profile(self) -> Any: ...


class KeywordPlanner:
    """缺口拉动的合并关键词生成器（设计规范 §5.2）。

    自持 ``llm_service`` + ``database`` + ``config``（控制器没有 LLM
    字段）。缺口来源在构造后通过 :meth:`bind_deficit_source` 注入，
    因为控制器比规划器晚构建。
    """

    def __init__(
        self,
        *,
        llm_service: Any,
        database: Any,
        config: Config,
        soul_engine: _SoulEngineLike | None = None,
        pool_target_count: int | None = None,
        signal_event_threshold: int = 6,
        owner: str | None = None,
        embedding_service: Any | None = None,
    ) -> None:
        self._llm = llm_service
        self._db = database
        self._config = config
        self._soul_engine = soul_engine
        self._embedding_service = embedding_service
        self._deficit_source: KeywordDeficitSource | None = None
        self._pool_target_count = pool_target_count
        self._signal_event_threshold = signal_event_threshold
        # 进程内唯一的锁 owner，使 CAS 单次并发锁能区分本规划器实例与
        # 陈旧的崩溃实例。
        self._owner = owner or f"{socket.gethostname()}:{uuid.uuid4().hex[:8]}"
        # 进程内单次并发：DB 规划器锁对同一 ``owner`` 可重入（崩溃后
        # 重启的规划器可重新获取），所以它阻止不了同一实例上两次重叠
        # 的 ``run_once`` 调用各自生成。本锁负责此事——跨进程 / 跨实例
        # 冲突仍由下方 DB 锁处理。
        self._inflight_lock = asyncio.Lock()
        # P1.9 每轮可观测性台账：最近一次生成轮次产出的
        # ``{platform: {"generated": n, "yield": y}}`` 快照。在第一次
        # 实际生成之前为空。
        self.last_cycle_ledger: dict[str, dict[str, int]] = {}
        self._profile_prompt_cache = PromptLayerRenderCache()
        self._generation_cache: dict[
            str,
            tuple[float, dict[str, list[str]], set[str]],
        ] = {}

    # ── 装配 ────────────────────────────────────────────────────────────

    def bind_deficit_source(self, source: KeywordDeficitSource) -> None:
        """把控制器作为共享的池缺口 / 催化剂口径注入。"""
        self._deficit_source = source

    def bind_soul_engine(self, soul_engine: _SoulEngineLike) -> None:
        """注入 soul 引擎（规划器始终读取实时画像）。"""
        self._soul_engine = soul_engine

    @property
    def owner(self) -> str:
        return self._owner

    # ── 配置助手 ────────────────────────────────────────────────────────

    @property
    def _discovery(self) -> DiscoveryConfig:
        return self._config.discovery

    @property
    def enabled(self) -> bool:
        return bool(self._discovery.unified_keyword_planner_enabled)

    @property
    def poll_seconds(self) -> int:
        return max(1, int(self._discovery.planner_poll_seconds))

    def _resolved_pool_target(self) -> int:
        if self._pool_target_count is not None:
            return int(self._pool_target_count)
        scheduler = getattr(self._config, "scheduler", None)
        return int(getattr(scheduler, "pool_target_count", 300))

    # ── 循环 ────────────────────────────────────────────────────────────

    async def run(self) -> None:
        """轮询循环：回收租约 + 每个间隔跑一轮规划。

        当功能开关关闭时为纯 no-op（仍会 sleep，使 ``run_forever`` 的
        gather 保持任务存活，但绝不触碰存储或 LLM）——保证切换前行为
        零变化。
        """
        poll_seconds = self.poll_seconds
        while True:
            if self.enabled:
                try:
                    self.reclaim_leases()
                except Exception:
                    logger.exception("keyword planner lease reclaim failed")
                try:
                    await self.run_once()
                except Exception:
                    logger.exception("keyword planner run_once failed")
            await asyncio.sleep(poll_seconds)

    def reclaim_leases(self) -> None:
        reclaim = getattr(self._db, "reclaim_leased_keywords", None)
        if not callable(reclaim):
            return
        claim_lease_minutes = float(self._discovery.claim_lease_minutes)
        executing_timeout_minutes = claim_lease_minutes * _EXECUTING_TIMEOUT_MULTIPLIER
        reclaimed = int(
            reclaim(
                claim_lease_minutes=claim_lease_minutes,
                executing_timeout_minutes=executing_timeout_minutes,
            )
        )
        if reclaimed:
            logger.info("keyword planner reclaimed %d leased keyword(s) to pending", reclaimed)

    def _retire_min_age_minutes(self) -> float:
        """0-yield ``used`` 词可被淘汰前的年龄底线。

        必须宽裕地超过最差准入延迟，使刚 used、yield 仍待定的词
        （仅抓取的 X/YT、异步 XHS —— 在交接时标记为 ``used``，仅当共享
        管线准入后才计入 yield）不会被过早淘汰。复用（更宽的）
        ``executing`` 超时，确保在途 XHS 任务的最终准入也在淘汰之前
        完成。
        """
        claim_lease_minutes = float(self._discovery.claim_lease_minutes)
        return max(60.0, claim_lease_minutes * _EXECUTING_TIMEOUT_MULTIPLIER)

    def retire_zero_yield(self) -> int:
        """淘汰所有规划器平台下空 yield 的 ``used`` 词（P1.8）。

        尽力而为；某平台淘汰失败不会终止整轮。返回被淘汰的总行数
        （用于可观测性 / 测试）。
        """
        retire = getattr(self._db, "retire_zero_yield_keywords", None)
        if not callable(retire):
            return 0
        min_age = self._retire_min_age_minutes()
        total = 0
        for platform in _PLANNER_PLATFORMS:
            try:
                total += int(retire(platform, min_age_minutes=min_age))
            except Exception:
                logger.exception("retire_zero_yield_keywords failed for %s", platform)
        if total:
            logger.info("keyword planner retired %d zero-yield keyword(s)", total)
        return total

    # ── 单轮规划 ───────────────────────────────────────────────────────

    async def run_once(self) -> dict[str, int]:
        """跑一次缺口拉动的合并生成轮次。

        返回 per-platform ``{platform: inserted}`` 台账（无 due 或开关
        关闭时为空），供可观测性 / 测试使用。
        """
        if not self.enabled:
            return {}

        # P1.8：每轮淘汰明显空 barren 的搜索词（``used`` 且 yield 为 0，
        # 超过保守年龄底线）。廉价单条 UPDATE，在 due 短路之前运行，
        # 即使无 due 也会触发；与生成 / 抓取解耦。年龄底线保护刚 used
        # 仍在等待异步（X / YT / XHS）准入的词。
        self.retire_zero_yield()

        # 进程内单次并发：本实例上第二次重叠轮次立即退出（DB 锁对自身
        # owner 可重入）。
        if self._inflight_lock.locked():
            logger.debug("keyword planner pass skipped: a pass is already in flight")
            return {}
        async with self._inflight_lock:
            return await self._run_once_locked()

    async def _run_once_locked(self) -> dict[str, int]:
        profile = await self._load_profile()
        if profile is None:
            return {}

        digest = profile_kw_digest(profile)
        due = self._due_platforms(digest)
        if not due:
            return {}

        # 提前把每个 due 平台的 stale-digest pending 过期掉，使下方低于
        # low 的缓存计数与合并请求量都基于当前 digest。
        for platform in due:
            try:
                self._db.expire_pending_by_digest(platform, digest)
            except Exception:
                logger.exception("expire_pending_by_digest failed for %s", platform)

        # 单次并发：短 CAS 锁，在 LLM 调用之前释放。
        lease_seconds = max(1.0, float(self._discovery.claim_lease_minutes) * 60.0)
        if not self._acquire_lock(lease_seconds):
            logger.debug("keyword planner pass skipped: another owner holds the lock")
            return {}

        ledger: dict[str, int] = {}
        try:
            ledger = await self._generate_for(due, profile=profile, digest=digest)
        finally:
            self._release_lock()
        return ledger

    async def _generate_for(
        self,
        due: list[str],
        *,
        profile: SoulProfile,
        digest: str,
    ) -> dict[str, int]:
        hints_by_platform = self._avoid_hints(profile)
        supply_by_platform = self._supply_hints(hints_by_platform)
        blocks: list[dict[str, object]] = []
        needs: dict[str, int] = {}
        total_ask = 0
        gen_batch = max(0, int(self._discovery.gen_batch))
        for platform in due:
            current_pending = self._count_pending(platform, digest)
            need = max(0, self._target_high(platform) - current_pending)
            # 不要向模型请求超过本轮保留量：解析时每个平台以 gen_batch
            # 封顶，请求完整（可能动态、最高 high × _DYNAMIC_HIGH_CAP_MULT）
            # 缺口只会让合并 JSON 膨胀，并把尾部平台推向截断。封顶请求。
            shown_need = min(need, gen_batch)
            if shown_need <= 0:
                # 没有缺口要填（或 gen_batch 被禁用）。B 站催化剂可能在
                # 缓存已满时仍把某平台标记为 due —— 跳过。
                continue
            needs[platform] = need
            total_ask += shown_need
            avoid = hints_by_platform.get(platform, {})
            blocks.append(
                {
                    "platform": platform,
                    "need": shown_need,
                    "recent_keywords": self._history(platform),
                    "avoid_topics": _as_str_list(avoid.get("avoid_topics")),
                    "avoid_styles": _as_str_list(avoid.get("avoid_styles")),
                    "avoid_franchises": _as_str_list(avoid.get("avoid_franchises")),
                    "prefer_axes": _as_str_list(avoid.get("prefer_axes")),
                    "cold_start": bool(avoid.get("cold_start")),
                    "supply_hint": list(supply_by_platform.get(platform, [])),
                }
            )

        generated: dict[str, list[str]] = {}
        present: set[str] = set()
        # ``call_failed`` 区分"合并 LLM 调用抛错 / 没返回可用内容"
        # （→ 所有 due 平台回退）与"调用成功但平台 X 显式返回空列表"
        # （→ X 拒绝，跳过且不回退）。当 ``blocks`` 为空即没什么可调用
        # 时保持 False —— 不是失败，只是没事做。
        call_failed = False
        if blocks:
            target_platforms = [str(block["platform"]) for block in blocks]
            cache_key = self._generation_cache_key(digest, blocks)
            cached = self._cached_generation(cache_key)
            if cached is not None:
                generated, present = cached
            else:
                # 按实际请求量（gen_batch 封顶后的 needs 之和）为合并调用
                # 的 max_tokens 配额，使 JSON 尾部平台不会被截断到兴趣名
                # 回退。随平台数与 gen_batch 缩放；保底为此前 4096 默认值。
                merged_max_tokens = max(
                    _MERGED_MIN_MAX_TOKENS,
                    total_ask * _MERGED_TOKENS_PER_KEYWORD + _MERGED_JSON_OVERHEAD_TOKENS,
                )
                try:
                    profile_summary = build_query_generation_profile_summary(
                        profile,
                        embedding_lookup=cached_embedding_lookup(self._embedding_service),
                    )
                    profile_blocks = self._profile_prompt_cache.render_json_layers(
                        profile_prompt_layers(profile_summary)
                    )
                    messages = build_merged_keywords_prompt(
                        profile_summary=profile_summary,
                        profile_blocks=profile_blocks,
                        platform_blocks=blocks,
                    )
                    complete_structured = self._llm.complete_structured_task
                    response = await complete_structured(
                        system_instruction=messages[0]["content"],
                        user_input=messages[1]["content"],
                        caller="discovery.keyword_planner",
                        reasoning_effort="",
                        max_tokens=merged_max_tokens,
                        **without_core_memory_kwargs(complete_structured),
                    )
                    content = str(getattr(response, "content", "") or "")
                    generated, present = parse_merged_keywords_with_presence(
                        content,
                        target_platforms,
                        per_platform_cap=gen_batch,
                    )
                    self._store_generation(cache_key, generated, present)
                except Exception:
                    logger.exception(
                        "keyword planner merged generation failed; "
                        "falling back to interest names for %s",
                        target_platforms,
                    )
                    generated = {}
                    present = set()
                    call_failed = True

        low = int(self._discovery.kw_cache_low)
        ledger: dict[str, int] = {}
        # 只有真实有缺口（need > 0）的平台才生成 / 插入。仅因 B 站催化剂
        # 标记为 due、缓存已达 high（need == 0）的平台已在上方的
        # ``blocks`` 中被丢弃，绝不应收到回退插入。
        for platform in needs:
            words = generated.get(platform, [])
            declined = False
            if not words:
                if not call_failed and platform in present:
                    # P2.2 拒绝：合并调用成功且模型对该平台显式返回 []
                    # → 主动拒绝（兴趣与其供给优势不匹配）。跳过：不回退、
                    # 不回收。保持当前 pending，若下次仍 due 再重新提供。
                    declined = True
                else:
                    # 调用整体失败，或模型省略了该平台 → 确定性兴趣名
                    # 回退（P1.3 镜像）。
                    cap = max(0, int(self._discovery.gen_batch))
                    words = self._interest_fallback(profile, cap)

            if declined:
                ledger[platform] = 0
                continue

            inserted = self._insert(platform, words, digest)
            if inserted <= 0:
                # 稀疏画像：生成 + 回退对某 due 平台都没产生新词 → 回收
                # 其最老的已用关键词，避免缓存饿死。
                inserted += self._recycle(platform, needs[platform], digest)
            else:
                # P2.3 不足时回收：平台产生了 *一些* 新词但 pending 仍
                # 低于 low 水位 → 从其最老的 used 词顶上（无额外 LLM
                # 调用）让多样性持续流动。保守：只补到 low 的剩余缺口，
                # 且对已拒绝平台（已在上面处理）不执行。
                shortfall = low - self._count_pending(platform, digest)
                if shortfall > 0:
                    inserted += self._recycle(platform, shortfall, digest)
            ledger[platform] = inserted

        self._emit_cycle_ledger(ledger, digest)
        return ledger

    def _generation_cache_key(self, digest: str, blocks: list[dict[str, object]]) -> str:
        cache_blocks: list[dict[str, object]] = []
        for block in blocks:
            cache_blocks.append(
                {
                    "platform": str(block.get("platform", "")),
                    "need": int(cast("Any", block.get("need", 0)) or 0),
                    "avoid_topics": _as_str_list(block.get("avoid_topics")),
                    "avoid_styles": _as_str_list(block.get("avoid_styles")),
                    "avoid_franchises": _as_str_list(block.get("avoid_franchises")),
                    "prefer_axes": _as_str_list(block.get("prefer_axes")),
                    "cold_start": bool(block.get("cold_start")),
                    "supply_hint": _as_str_list(block.get("supply_hint")),
                }
            )
        blob = json.dumps(
            {
                "digest": digest,
                "gen_batch": int(self._discovery.gen_batch),
                "blocks": cache_blocks,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return blob

    def _generation_cache_ttl_seconds(self) -> float:
        return max(1.0, float(self._discovery.plan_ttl_hours) * 60.0 * 60.0)

    def _cached_generation(
        self,
        cache_key: str,
    ) -> tuple[dict[str, list[str]], set[str]] | None:
        cached = self._generation_cache.get(cache_key)
        if cached is None:
            return None
        expires_at, generated, present = cached
        if time.monotonic() >= expires_at:
            self._generation_cache.pop(cache_key, None)
            return None
        return ({platform: list(words) for platform, words in generated.items()}, set(present))

    def _store_generation(
        self,
        cache_key: str,
        generated: dict[str, list[str]],
        present: set[str],
    ) -> None:
        self._generation_cache[cache_key] = (
            time.monotonic() + self._generation_cache_ttl_seconds(),
            {platform: list(words) for platform, words in generated.items()},
            set(present),
        )

    # ── 每轮可观测性台账（P1.9） ───────────────────────────────────────

    def _emit_cycle_ledger(
        self, generated: dict[str, int], digest: str
    ) -> dict[str, dict[str, int]]:
        """记录 + 日志本轮 per-platform 的产出 / yield 台账。

        合并生成是 **一次** ``discovery.keyword_planner`` LLM 响应
        （P1.6），所以 token 成本 *无法* 按平台分摊——成本台账保留单一
        caller。为仍给运维 per-platform 可见性，这条结构化日志对每个本
        轮生成的平台呈现：它产出了多少关键词（``generated``）以及该
        平台累计准入计入的 ``yield``（通过
        :meth:`Database.keyword_yield_total` 廉价 ``SUM(yield_count)``，
        可用时）。它 *不* 伪造 token 级别的平台归因。

        存于 :attr:`last_cycle_ledger`（供可观测性 / 测试）并以一条
        ``logger.info`` 结构化行输出。返回结构化的
        ``{platform: {"generated": n, "yield": y}}`` dict。
        """
        structured: dict[str, dict[str, int]] = {}
        for platform, count in generated.items():
            structured[platform] = {
                "generated": int(count),
                "yield": self._yield_total(platform),
            }
        self.last_cycle_ledger = structured
        if structured:
            logger.info(
                "keyword planner cycle ledger (digest=%s): %s",
                digest,
                ", ".join(
                    f"{p}=generated:{v['generated']}/yield:{v['yield']}"
                    for p, v in structured.items()
                ),
            )
        return structured

    def _yield_total(self, platform: str) -> int:
        """某平台累计准入计入的 yield（不可用时为 0）。"""
        getter = getattr(self._db, "keyword_yield_total", None)
        if not callable(getter):
            return 0
        try:
            return int(getter(platform))
        except Exception:
            logger.debug("keyword_yield_total lookup failed for %s", platform, exc_info=True)
            return 0

    # ── due 计算 ───────────────────────────────────────────────────────

    def _due_platforms(self, digest: str) -> list[str]:
        low = int(self._discovery.kw_cache_low)
        due: list[str] = []
        for platform in _PLANNER_PLATFORMS:
            cache_below_low = self._count_pending(platform, digest) < low
            has_deficit = self._real_deficit(platform) > 0
            platform_due = cache_below_low and has_deficit
            if platform == _BILIBILI and not platform_due and self._bilibili_catalyst():
                platform_due = True
            if platform_due:
                due.append(platform)
        return due

    def _real_deficit(self, platform: str) -> int:
        source = self._deficit_source
        if source is None:
            return 0
        try:
            return max(0, int(source.keyword_planner_real_deficit(platform)))
        except Exception:
            logger.exception("keyword planner deficit lookup failed for %s", platform)
            return 0

    def _bilibili_catalyst(self) -> bool:
        source = self._deficit_source
        if source is None:
            return False
        try:
            return bool(source.keyword_planner_bilibili_catalyst())
        except Exception:
            logger.exception("keyword planner bilibili catalyst lookup failed")
            return False

    # ── 存储 + 快照助手 ────────────────────────────────────────────────

    def _count_pending(self, platform: str, digest: str) -> int:
        try:
            return int(self._db.count_pending_keywords(platform, digest))
        except Exception:
            logger.exception("count_pending_keywords failed for %s", platform)
            return 0

    def _history(self, platform: str) -> list[str]:
        try:
            return list(
                self._db.history_keywords(
                    platform,
                    int(self._discovery.history_window_size),
                    float(self._discovery.history_window_hours),
                )
            )
        except Exception:
            logger.exception("history_keywords failed for %s", platform)
            return []

    def _insert(self, platform: str, words: list[str], digest: str) -> int:
        if not words:
            return 0
        try:
            return int(self._db.insert_pending_keywords(platform, words, digest))
        except Exception:
            logger.exception("insert_pending_keywords failed for %s", platform)
            return 0

    def _recycle(self, platform: str, n: int, digest: str) -> int:
        recycle = getattr(self._db, "recycle_oldest_used", None)
        if not callable(recycle) or n <= 0:
            return 0
        try:
            return int(recycle(platform, n, digest))
        except Exception:
            logger.exception("recycle_oldest_used failed for %s", platform)
            return 0

    def _avoid_hints(self, profile: SoulProfile | None = None) -> dict[str, dict[str, object]]:
        """各平台的话题 avoid + 全局的风格 / 番剧 avoid（P3.1）。

        P1/P2 给每个平台喂的是 GLOBAL avoid，过度回避——在 B 站饱和的
        话题可能在小红书上根本没出现。P3.1 给每个平台自己的饱和话题
        （相对该平台自己的池）；风格和番剧保持全局（更粗，平台特异性
        弱）。某平台自身池数据太少时回退到全局话题 avoid。空池冷启动
        回退到画像派生的软多样性提示，使每个平台第一批关键词不会塌
        缩到同一个最高权重的兴趣上。
        """
        hints: dict[str, object] = {}
        try:
            snapshot = build_pool_distribution_snapshot(
                self._db,
                pool_target_count=self._resolved_pool_target(),
                source_targets=self._source_targets(),
            )
            if profile is not None and int(snapshot.pool_available_count) <= 0:
                cold_snapshot = build_cold_start_pool_snapshot(
                    profile,
                    pool_target_count=self._resolved_pool_target(),
                    source_targets=self._source_targets(),
                )
                if cold_snapshot is not None:
                    snapshot = cold_snapshot
            hints = snapshot.to_prompt_hints()
        except Exception:
            logger.exception("keyword planner failed to build pool distribution snapshot")
        global_topics = _as_str_list(hints.get("avoid_topics"))
        shared_styles = _as_str_list(hints.get("avoid_styles"))
        shared_franchises = _as_str_list(hints.get("avoid_franchises"))
        shared_prefer_axes = _as_str_list(hints.get("prefer_axes"))
        cold_start = bool(hints.get("cold_start"))

        per_platform: dict[str, dict[str, int]] = {}
        getter = getattr(self._db, "get_pool_topic_counts_by_platform", None)
        if callable(getter):
            try:
                per_platform = getter()
            except Exception:
                logger.exception("keyword planner failed to read per-platform topic counts")

        result: dict[str, dict[str, object]] = {}
        for platform in _PLANNER_PLATFORMS:
            topic_counts = per_platform.get(platform, {})
            total = sum(int(count) for count in topic_counts.values())
            if total < _PER_PLATFORM_AVOID_FLOOR:
                avoid_topics = list(global_topics)
            else:
                threshold = max(
                    _PER_PLATFORM_AVOID_MIN_THRESHOLD, total // _PER_PLATFORM_AVOID_DIVISOR
                )
                avoid_topics = [
                    topic
                    for topic, count in sorted(topic_counts.items(), key=lambda kv: (-kv[1], kv[0]))
                    if int(count) >= threshold
                ][:12]
            result[platform] = {
                "avoid_topics": avoid_topics,
                "avoid_styles": list(shared_styles),
                "avoid_franchises": list(shared_franchises),
                "prefer_axes": list(shared_prefer_axes),
                "cold_start": cold_start,
            }
        return result

    def _supply_hints(
        self, avoid_by_platform: dict[str, dict[str, object]]
    ) -> dict[str, list[str]]:
        """各平台数据驱动的供给优势话题（P3.3）。

        system prompt 中的静态 ``<supply_advantage>`` 表给出平台先验；
        这部分用 *本用户* 实际的准入历史做补充——各平台最常把哪些
        ``topic_group`` 投入到缓存。会减去该平台当前的 avoid 集合，
        使某话题不会同时是"倾斜投入"和"回避"（饱和-当下变 strength
        的，本轮只留在 avoid）。在平台准入行数达到
        ``_PER_PLATFORM_SUPPLY_FLOOR`` 之前为空（冷启动 → 仅静态表）。
        """
        admitted: dict[str, dict[str, int]] = {}
        getter = getattr(self._db, "get_admitted_topic_counts_by_platform", None)
        if callable(getter):
            try:
                admitted = getter()
            except Exception:
                logger.exception(
                    "keyword planner failed to read per-platform admitted topic counts"
                )
        result: dict[str, list[str]] = {}
        for platform in _PLANNER_PLATFORMS:
            topic_counts = admitted.get(platform, {})
            total = sum(int(count) for count in topic_counts.values())
            if total < _PER_PLATFORM_SUPPLY_FLOOR:
                result[platform] = []
                continue
            avoid = set(_as_str_list(avoid_by_platform.get(platform, {}).get("avoid_topics")))
            threshold = max(
                _PER_PLATFORM_SUPPLY_MIN_THRESHOLD, total // _PER_PLATFORM_SUPPLY_DIVISOR
            )
            result[platform] = [
                topic
                for topic, count in sorted(topic_counts.items(), key=lambda kv: (-kv[1], kv[0]))
                if int(count) >= threshold and topic not in avoid
            ][:_PER_PLATFORM_SUPPLY_TOP]
        return result

    def _target_high(self, platform: str) -> int:
        """P3.2 某平台的动态缓存高水位。

        按实时搜索缺口 ÷ 平台观测平均每词 yield 来设定 pending 目标，
        使低 yield 平台（重复命中多）生成 *更多* 词以填补同样缺口，
        高 yield 平台则更少。冷启动（yield 历史太少）、无缺口来源或
        缺口非正时回退到静态 ``kw_cache_high``。夹在
        ``[low+fetch_batch .. kw_cache_high × _DYNAMIC_HIGH_CAP_MULT]``
        区间内，使缓存仍能正常工作。
        """
        static_high = max(1, int(self._discovery.kw_cache_high))
        source = self._deficit_source
        if source is None:
            return static_high
        try:
            deficit = int(source.keyword_planner_real_deficit(platform))
        except Exception:
            return static_high
        if deficit <= 0:
            return static_high
        avg_yield = self._avg_yield(platform)
        if avg_yield <= 0.0:
            return static_high
        target = math.ceil(deficit / avg_yield)
        floor = max(1, int(self._discovery.kw_cache_low) + int(self._discovery.fetch_batch))
        cap = static_high * _DYNAMIC_HIGH_CAP_MULT
        return max(floor, min(target, cap))

    def _avg_yield(self, platform: str) -> float:
        """某平台观测的每词 yield（总 yield ÷ used 关键词数）。

        在 used 关键词少于 ``_DYNAMIC_MIN_SAMPLES`` 之前返回 0.0
        （→ 调用方使用静态 high），避免冷启动估计被一两个噪声样本
        主导。
        """
        used = 0
        getter = getattr(self._db, "used_keyword_count", None)
        if callable(getter):
            try:
                used = int(getter(platform))
            except Exception:
                used = 0
        if used < _DYNAMIC_MIN_SAMPLES:
            return 0.0
        total = 0
        total_getter = getattr(self._db, "keyword_yield_total", None)
        if callable(total_getter):
            try:
                total = int(total_getter(platform))
            except Exception:
                total = 0
        return total / used if used > 0 else 0.0

    def _source_targets(self) -> dict[str, int]:
        source = self._deficit_source
        getter = getattr(source, "_source_target_counts", None)
        if callable(getter):
            try:
                return {str(k): int(v) for k, v in dict(getter()).items()}
            except Exception:
                logger.exception("keyword planner source-target lookup failed")
        return {}

    # ── 锁 ──────────────────────────────────────────────────────────────

    def _acquire_lock(self, lease_seconds: float) -> bool:
        acquire = getattr(self._db, "acquire_planner_lock", None)
        if not callable(acquire):
            # 不支持锁 → 按单进程处理（测试中仍安全）。
            return True
        try:
            return bool(acquire(self._owner, lease_seconds))
        except Exception:
            logger.exception("acquire_planner_lock failed")
            return False

    def _release_lock(self) -> None:
        release = getattr(self._db, "release_planner_lock", None)
        if not callable(release):
            return
        try:
            release(self._owner)
        except Exception:
            logger.exception("release_planner_lock failed")

    # ── 画像 + 回退 ─────────────────────────────────────────────────────

    async def _load_profile(self) -> SoulProfile | None:
        if self._soul_engine is None:
            return None
        try:
            profile = await self._soul_engine.get_profile()
        except Exception:
            logger.info("keyword planner skipped: soul profile unavailable", exc_info=True)
            return None
        return cast("SoulProfile | None", profile)

    @staticmethod
    def _interest_fallback(profile: SoulProfile, count: int) -> list[str]:
        """按权重排序的确定性兴趣名（镜像 P1.3 XHS/X）。"""
        if count <= 0:
            return []
        ranked = sorted(
            profile.preferences.interests,
            key=lambda tag: float(tag.weight or 0.0),
            reverse=True,
        )
        seen: set[str] = set()
        out: list[str] = []
        for tag in ranked:
            name = str(tag.name).strip()
            if not name or name in seen:
                continue
            seen.add(name)
            out.append(name)
            if len(out) >= count:
                break
        return out
