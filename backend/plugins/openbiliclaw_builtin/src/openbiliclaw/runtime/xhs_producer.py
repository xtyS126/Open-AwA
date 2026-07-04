"""Soul 驱动的 xhs 搜索任务 producer。

在与持续刷新控制器相同的循环上运行。每个节流窗口（默认 4h）一次，
它会：
  1. 读取当前的 SoulProfile
  2. 请求 LLM 将兴趣标签改写为 xhs 风格的关键词
  3. 为每个关键词入队一个 ``search`` 任务到 ``XhsTaskQueue``

扩展的后台 dispatcher 轮询队列，在隐藏标签页中打开每个
搜索页，并回报结果 —— 从而闭环 xiaohongshu 的 Soul → Discovery 链路。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from openbiliclaw.runtime.keyword_fetch import PLATFORM_XIAOHONGSHU as _PLATFORM_XIAOHONGSHU
from openbiliclaw.sources.xhs_keyword_gen import generate_xhs_keywords

if TYPE_CHECKING:
    from openbiliclaw.llm.service import LLMService
    from openbiliclaw.sources.xhs_tasks import XhsTaskQueue

logger = logging.getLogger(__name__)


@dataclass
class XhsTaskProducer:
    """在节流条件下从 SoulProfile 入队 xhs 搜索任务。

    producer 遵守两个限制：
    - ``daily_budget`` —— 由 ``XhsTaskQueue.enqueue`` 按类型强制执行；
      ``0`` 表示禁用每日上限
    - ``min_interval_hours`` —— 由此处通过检查最新任务的
      ``created_at`` 来强制执行
    """

    task_queue: XhsTaskQueue
    soul_engine: Any
    llm_service: LLMService
    enabled: bool = True
    daily_budget: int = 0
    # 统一关键词规划器 fetch coordinator (P1.7)。当已接入且开关
    # 打开时，producer 从关键词 store 中 claim 词，为每个词入队一个
    # xhs 搜索任务并携带其 ``source_keyword_id``，然后将词标记为
    # ``executing``（NOT ``used`` —— XHS 是真正的异步；任务结果处理器
    # 标记终态 ``used`` / ``failed``）。入队时预算拒绝
    # （``ok=False``）将词回滚到 ``pending``。``None``（默认 / 开关
    # 关闭）→ 传统自生成、无生命周期的入队。
    keyword_fetch: Any | None = None
    # v0.3.53+: 从 4 降到 1。生产日志 (2026-05-05) 显示
    # producer 在 43 分钟的会话中只触发了一次，因为
    # 4 小时节流对池新鲜度而言太长 —— 当用户持续 reshuffle 时
    # XHS 池实际上是静态的。1 小时节拍 + daily_budget=30
    # 每天最多入队 24/30，留 6 个余量给手动 / refresh-tick 触发。
    min_interval_hours: int = 1
    keywords_per_cycle: int = 5
    _last_skip_reason: str = field(default="", init=False)

    async def produce_if_due(
        self,
        *,
        limit: int | None = None,
        keywords: list[str] | None = None,
    ) -> dict[str, object]:
        """如果已过足够时间则运行一个 producer 周期。

        返回用于诊断的摘要 dict。当 producer 被禁用、节流，
        或没有可入队的有用内容时，结果携带 ``enqueued: 0`` 和一个
        ``reason`` 字符串 —— 调用方应将其视为 no-op。

        Args:
            limit: 对本周期生成的关键词数量的可选上限。
            keywords: 调用方提供的可选关键词（统一关键词规划器
                注入点）。当提供（非 None）时，它们被直接入队，
                内部的 ``generate_xhs_keywords`` LLM 调用被跳过。
                当为 ``None`` 时，producer 像以前一样从 profile
                生成自己的关键词。
        """
        if not self.enabled:
            return self._skip("disabled")

        if not self._is_due():
            return self._skip("throttled")

        keyword_count = min(
            self.keywords_per_cycle,
            max(1, int(limit or self.keywords_per_cycle)),
        )

        # 统一关键词规划器 fetch 路径 (P1.7，开关受控)。优先级高于
        # 外部注入和自生成：从 store claim 词，将每个作为携带其
        # ``source_keyword_id`` 的任务入队，并将其标记为
        # ``executing``（XHS 是真正的异步 —— 终态 ``used`` /
        # ``failed`` 是任务结果处理器的工作）。缺口门控在上游；
        # 区分下限是上面的 ``min_interval`` / ``_is_due``。
        coordinator = self.keyword_fetch
        if (
            keywords is None
            and coordinator is not None
            and bool(getattr(coordinator, "should_claim", lambda: False)())
        ):
            claimed = coordinator.claim(_PLATFORM_XIAOHONGSHU, keyword_count)
            if not claimed:
                # 开关打开但 store 没有 claimable 的 pending 词 → 跳过
                # 本周期（planner 会重新填充）。
                return self._skip("no_keywords")
            return self._enqueue_claimed_keywords(claimed)

        if keywords is not None:
            resolved_keywords = _dedupe_keywords(keywords)[:keyword_count]
            if not resolved_keywords:
                return self._skip("no_keywords")
            return self._enqueue_keywords(resolved_keywords)

        is_ready_fn = getattr(self.soul_engine, "is_profile_ready", None)
        if callable(is_ready_fn) and not is_ready_fn():
            # Init 的前 ~7 分钟 —— producer 每分钟 tick
            # 否则会 WARN。静默跳过；下个 tick 重试。
            logger.debug("xhs producer: soul profile not ready yet")
            return self._skip("no_profile")
        try:
            profile = await self.soul_engine.get_profile()
        except Exception as exc:
            logger.warning("xhs producer: soul profile unavailable: %s", exc)
            return self._skip("no_profile")

        if profile is None:
            return self._skip("no_profile")

        resolved_keywords = await generate_xhs_keywords(
            self.llm_service,
            profile,
            count=keyword_count,
        )
        if not resolved_keywords:
            return self._skip("no_keywords")
        return self._enqueue_keywords(resolved_keywords)

    def _enqueue_keywords(self, keywords: list[str]) -> dict[str, object]:
        """为每个关键词入队一个 ``search`` 任务，命中预算上限时停止。"""

        enqueued = 0
        for keyword in keywords:
            ok = self.task_queue.enqueue(
                "search",
                {"keyword": keyword},
                daily_budget=self.daily_budget,
            )
            if ok:
                enqueued += 1
            else:
                break  # 预算耗尽 —— 提前停止
        logger.info(
            "xhs producer enqueued %d/%d search tasks",
            enqueued,
            len(keywords),
        )
        return {"enqueued": enqueued, "attempted": len(keywords), "reason": "ok"}

    def _enqueue_claimed_keywords(self, claimed: list[Any]) -> dict[str, object]:
        """为每个 claimed 词入队一个任务（携带其 ``source_keyword_id``）。

        XHS 是真正的异步：入队只是把搜索交给扩展，因此每个入队的词
        被标记为 ``executing`` —— NOT ``used``（终态是任务结果处理器
        的工作）。一个被预算拒绝的词（``enqueue_with_id`` 返回
        ``None``）被回滚到 ``pending`` 而不是被消耗；入队在预算墙处
        提前停止。``source_keyword_id`` 是任务结果处理器回读以标记
        终态的生命周期关联（P1.8 将其扩展到候选以进行 yield）。
        """
        coordinator = self.keyword_fetch
        enqueued = 0
        for item in claimed:
            task_id = self.task_queue.enqueue_with_id(
                "search",
                {"keyword": item.keyword, "source_keyword_id": int(item.id)},
                daily_budget=self.daily_budget,
            )
            if task_id is not None:
                enqueued += 1
                if coordinator is not None:
                    coordinator.mark_executing(item)
            else:
                # 预算耗尽：将该词（以及其后每个未 claimed 的词）
                # 回滚到 pending，确保没有词被消耗。
                if coordinator is not None:
                    coordinator.rollback(item)
                break
        # 回滚任何我们没到达的词（循环在预算墙处中断）。
        if coordinator is not None and enqueued < len(claimed):
            for item in claimed[enqueued + 1 :]:
                coordinator.rollback(item)
        logger.info(
            "xhs producer enqueued %d/%d claimed search tasks (executing)",
            enqueued,
            len(claimed),
        )
        return {"enqueued": enqueued, "attempted": len(claimed), "reason": "ok"}

    def _is_due(self) -> bool:
        """如果最新的搜索任务最近刚入队则返回 False。"""
        if self.min_interval_hours <= 0:
            return True
        row = self.task_queue._db.conn.execute(
            "SELECT created_at FROM xhs_tasks "
            "WHERE type = 'search' ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return True
        created_at_str = str(row["created_at"] if "created_at" in row else row[0])
        last = _parse_sqlite_timestamp(created_at_str)
        if last is None:
            return True
        return datetime.now(UTC) - last >= timedelta(hours=self.min_interval_hours)

    def _skip(self, reason: str) -> dict[str, object]:
        # v0.3.53+: 在状态转换时记录 skip 原因（不是每分钟），以便
        # 运维可以 grep producer 为何不触发，而不会让日志淹没在
        # 相同 reason 的 WARNING 中。原因：
        #   disabled       —— 在配置中显式关闭
        #   throttled      —— 最后一次入队在 ``min_interval_hours`` 内
        #   no_profile     —— soul profile 尚未构建（init 窗口）
        #   no_keywords    —— LLM 关键词生成返回 0 项
        if reason != self._last_skip_reason:
            logger.info("xhs producer skip: reason=%s", reason)
        self._last_skip_reason = reason
        return {"enqueued": 0, "attempted": 0, "reason": reason}


def _dedupe_keywords(keywords: list[str]) -> list[str]:
    """对调用方注入的关键词进行 strip + 去重（统一 planner 注入）。"""
    seen: set[str] = set()
    out: list[str] = []
    for item in keywords:
        text = str(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _parse_sqlite_timestamp(value: str) -> datetime | None:
    """将 SQLite CURRENT_TIMESTAMP (``YYYY-MM-DD HH:MM:SS``) 解析为 UTC。"""
    if not value:
        return None
    try:
        dt = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        try:
            dt = datetime.fromisoformat(value)
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt
