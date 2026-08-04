"""
记忆巩固运行器。

Spec memory-quality-and-short-term-recovery 阶段 2 的核心模块。
每 N 轮对话（默认 10）从短期记忆中提炼高价值信息（用户偏好/事实/决策）写入长期记忆。

设计借鉴（详见 spec.md "调研参考"章节）：
- OpenBiliClaw CognitionCycle：watermark 增量读取，避免全表扫描
- openhanako memory-ticker：fingerprint 跳过 + 断点续跑 Set，避免重复 LLM 调用
- OpenBiliClaw consolidator：no_merge_pairs 记忆，已合并过的对不再重复判断

触发方式：
- core/feedback.py 在每轮对话完成后递增 consolidation_state.conversation_count_since_run
- 当计数达到阈值 N 时，asyncio.create_task 异步调用 run_if_due
- 也可通过 force=True 强制触发（用于测试或运维手动触发）

失败处理：
- LLM 提炼失败 → 跳过提炼，但仍记录 fingerprint（避免重复调用），更新 watermark
- add_long_term_memory 失败 → 跳过该条，继续处理下一条
- 整体异常 → 记录 ERROR 日志与 last_error，watermark 不更新（下次重试）

回退策略：
- 未注入 extract_callback 时，跳过 LLM 提炼，直接持久化 fingerprint 并更新 watermark
  （用于测试环境与 LLM 不可达场景，保证 watermark 推进而非卡死）
"""

from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from loguru import logger
from sqlalchemy.orm import Session

from db.models import (
    ConsolidationFingerprint,
    ConsolidationState,
    ShortTermMemory,
)
from memory.manager import MemoryManager


# LLM 提炼回调签名
# 输入：短期记忆列表，每项含 id / role / content / session_id
# 输出：提炼结果列表，每项含 content / importance / source_type / source_short_term_memory_id（可选）
ExtractCallback = Callable[
    [List[Dict[str, Any]], Optional[str]],
    Awaitable[List[Dict[str, Any]]],
]


class ConsolidationRunner:
    """
    记忆巩固运行器。

    通过 :meth:`run_if_due` 触发，依据 ``consolidation_state`` 表的水位线
    增量读取短期记忆，调用 LLM 提炼高价值信息后写入长期记忆。
    """

    # 默认触发阈值：每 N 轮对话触发一次
    DEFAULT_CONVERSATION_THRESHOLD = 10
    # 默认单次批量大小：限制单次巩固处理的短期记忆数量，避免 LLM 上下文过长
    DEFAULT_BATCH_SIZE = 50
    # 单条短期记忆内容参与 LLM 提炼时的截断长度（避免超长内容炸 LLM 上下文）
    SHORT_TERM_CONTENT_TRUNCATE = 500

    def __init__(
        self,
        memory_manager: MemoryManager,
        session_factory,
        extract_callback: Optional[ExtractCallback] = None,
        conversation_threshold: int = DEFAULT_CONVERSATION_THRESHOLD,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        self.memory_manager = memory_manager
        self.session_factory = session_factory
        self._extract_callback = extract_callback
        self._conversation_threshold = max(1, int(conversation_threshold))
        self._batch_size = max(1, int(batch_size))

    def set_extract_callback(self, callback: ExtractCallback) -> None:
        """
        注入 LLM 提炼回调。

        生产环境注入真实 LLM 调用，测试环境可注入 mock 或不注入（跳过提炼）。
        """
        self._extract_callback = callback

    # ---------------- 对外接口 ----------------

    async def run_if_due(
        self,
        user_id: str,
        force: bool = False,
        workspace_id: str = "default",
    ) -> Dict[str, Any]:
        """
        检查触发条件并执行巩固。

        Args:
            user_id: 用户 ID（隔离维度）
            force: True 时无视计数阈值强制触发（用于运维/测试）
            workspace_id: 工作区隔离

        Returns:
            执行结果字典，包含 triggered / success / processed / skipped /
            extracted / consolidated / archived / watermark / error 等字段。
        """
        if not user_id:
            return {
                "triggered": False,
                "success": False,
                "error": "user_id is required",
            }

        state = self._get_or_create_state_sync(user_id, workspace_id)

        if not force and state.conversation_count_since_run < self._conversation_threshold:
            return {
                "triggered": False,
                "reason": "below_threshold",
                "count": state.conversation_count_since_run,
                "threshold": self._conversation_threshold,
            }

        try:
            result = await self._consolidate(user_id, state, workspace_id)
            # Spec Task 10：巩固末尾（无论是否处理新短期记忆）都触发归档评估
            # 早期返回路径（no_new_memories）也需评估，避免低质量记忆永驻 active 状态
            archived_count = await asyncio.to_thread(
                self._evaluate_and_archive_low_quality_sync,
                user_id,
                workspace_id,
            )
            result["archived"] = archived_count
            return result
        except Exception as exc:
            # 失败时记录 last_error，watermark 不更新（下次重试）
            self._record_failure_sync(user_id, workspace_id, exc)
            logger.bind(
                event="consolidation_failed",
                module="memory",
                user_id=user_id,
            ).exception(f"记忆巩固失败 user_id={user_id}: {exc}")
            return {
                "triggered": True,
                "success": False,
                "error": str(exc),
            }

    async def extract_turn_async(
        self,
        user_input: str,
        response: str,
        user_id: str,
        workspace_id: str = "default",
    ) -> int:
        """
        关键词即时路径：将单轮对话异步提交 LLM 提炼后写入长期记忆。

        与 :meth:`_consolidate` 的区别：输入来自内存中的本轮对话（尚未
        落库为短期记忆），输出直接调用 add_long_term_memory。提炼失败或
        无价值内容时静默跳过、不落原文，由 feedback.py 以 create_task
        后台调用，不阻塞对话主流程。

        Returns:
            成功写入长期记忆的条数（0 表示跳过）。
        """
        if self._extract_callback is None:
            logger.bind(
                event="immediate_extract_no_callback",
                module="memory",
                user_id=user_id,
            ).warning("即时提炼跳过：未注入提炼回调")
            return 0
        logger.bind(
            event="immediate_extract_start",
            module="memory",
            user_id=user_id,
        ).info(f"即时提炼触发 user_id={user_id}")
        try:
            messages_for_llm = [
                {
                    "id": None,
                    "role": "user",
                    "content": (user_input or "")[: self.SHORT_TERM_CONTENT_TRUNCATE],
                    "session_id": None,
                },
                {
                    "id": None,
                    "role": "assistant",
                    "content": (response or "")[: self.SHORT_TERM_CONTENT_TRUNCATE],
                    "session_id": None,
                },
            ]
            extracted = await self._extract_callback(messages_for_llm, user_id)
        except Exception as exc:
            logger.bind(
                event="immediate_extract_failed",
                module="memory",
                user_id=user_id,
            ).warning(f"即时提炼失败，跳过本轮持久化: {exc}")
            return 0

        count = 0
        for item in extracted or []:
            content = str(item.get("content", "")).strip()
            if not content or len(content) > self.memory_manager._MAX_LONG_TERM_CONTENT_CHARS:
                continue
            try:
                await self.memory_manager.add_long_term_memory(
                    content=content,
                    importance=float(item.get("importance", 0.5)),
                    user_id=user_id,
                    source_type=item.get("source_type", "llm_extracted"),
                    workspace_id=workspace_id,
                )
                count += 1
            except Exception as exc:
                logger.bind(
                    event="immediate_extract_add_failed",
                    module="memory",
                    user_id=user_id,
                ).warning(f"即时提炼写入单条失败（跳过）: {exc}")
        return count

    def increment_conversation_count(
        self,
        user_id: str,
        workspace_id: str = "default",
        delta: int = 1,
    ) -> int:
        """
        递增对话计数器（由 core/feedback.py 在每轮对话完成后调用）。

        Args:
            user_id: 用户 ID
            workspace_id: 工作区隔离
            delta: 增量，默认 1

        Returns:
            递增后的新计数值
        """
        if not user_id:
            return 0
        with self.session_factory() as db:
            state = self._get_or_create_state_in_session(db, user_id, workspace_id)
            state.conversation_count_since_run = (state.conversation_count_since_run or 0) + int(delta)
            new_count = state.conversation_count_since_run
            db.commit()
            return new_count

    # ---------------- 内部实现 ----------------

    async def _consolidate(
        self,
        user_id: str,
        state: ConsolidationState,
        workspace_id: str,
    ) -> Dict[str, Any]:
        """
        执行巩固主流程。

        实现已拆分为四个内部 helper（brooks-lint D2 Cognitive Overload）：
        - :meth:`_read_candidates`：增量读取短期记忆 + fingerprint 过滤
        - :meth:`_extract_insights`：LLM 提炼高价值信息（含失败降级）
        - :meth:`_persist_extracted_memories`：循环 add_long_term_memory 写入
        - :meth:`_persist_fingerprints_and_watermark`：fingerprint 持久化 + watermark 推进
        """
        watermark = state.last_short_term_memory_id or 0

        # 1. 增量读取短期记忆
        new_memories = await asyncio.to_thread(
            self._read_short_term_memories_sync,
            user_id,
            watermark,
            workspace_id,
            self._batch_size,
        )

        if not new_memories:
            self._reset_counter_sync(user_id, workspace_id)
            return {
                "triggered": True,
                "success": True,
                "processed": 0,
                "skipped": 0,
                "extracted": 0,
                "consolidated": 0,
                "archived": 0,
                "watermark": watermark,
                "reason": "no_new_memories",
            }

        # 2. fingerprint 过滤
        candidates = await self._filter_unprocessed_candidates(
            new_memories, user_id, workspace_id
        )

        if not candidates:
            new_watermark = max(m.id for m in new_memories)
            self._update_watermark_sync(user_id, workspace_id, new_watermark)
            self._reset_counter_sync(user_id, workspace_id)
            return {
                "triggered": True,
                "success": True,
                "processed": len(new_memories),
                "skipped": len(new_memories),
                "extracted": 0,
                "consolidated": 0,
                "archived": 0,
                "watermark": new_watermark,
                "reason": "all_skipped_by_fingerprint",
            }

        # 3. LLM 提炼
        extracted_items = await self._extract_insights(candidates, user_id)

        # 4. 写入长期记忆
        consolidated_memory_ids = await self._persist_extracted_memories(
            candidates, extracted_items, user_id, workspace_id
        )

        # 5. 持久化 fingerprint + 更新 watermark
        new_watermark = await self._persist_fingerprints_and_watermark(
            candidates, consolidated_memory_ids, new_memories, user_id, workspace_id
        )

        # 6. 触发归档评估（Spec Task 10）
        archived_count = await asyncio.to_thread(
            self._evaluate_and_archive_low_quality_sync,
            user_id,
            workspace_id,
        )

        logger.bind(
            event="consolidation_completed",
            module="memory",
            user_id=user_id,
            processed=len(new_memories),
            skipped=len(new_memories) - len(candidates),
            extracted=len(extracted_items),
            consolidated=len(consolidated_memory_ids),
            archived=archived_count,
            watermark=new_watermark,
        ).info(
            f"记忆巩固完成 user_id={user_id}: "
            f"processed={len(new_memories)} skipped={len(new_memories) - len(candidates)} "
            f"extracted={len(extracted_items)} consolidated={len(consolidated_memory_ids)} "
            f"archived={archived_count} watermark={new_watermark}"
        )

        return {
            "triggered": True,
            "success": True,
            "processed": len(new_memories),
            "skipped": len(new_memories) - len(candidates),
            "extracted": len(extracted_items),
            "consolidated": len(consolidated_memory_ids),
            "archived": archived_count,
            "watermark": new_watermark,
        }

    async def _filter_unprocessed_candidates(
        self,
        new_memories: List[ShortTermMemory],
        user_id: str,
        workspace_id: str,
    ) -> List[Tuple[ShortTermMemory, str]]:
        """计算 fingerprint 并过滤已处理的短期记忆。"""
        existing_fingerprints = await asyncio.to_thread(
            self._get_existing_fingerprints_sync,
            user_id,
            workspace_id,
            [m.id for m in new_memories],
        )
        candidates: List[Tuple[ShortTermMemory, str]] = []
        for m in new_memories:
            fp = self._compute_fingerprint(m.content)
            if fp in existing_fingerprints:
                continue
            candidates.append((m, fp))
        return candidates

    async def _extract_insights(
        self,
        candidates: List[Tuple[ShortTermMemory, str]],
        user_id: str,
    ) -> List[Dict[str, Any]]:
        """调用 LLM 提炼高价值信息，失败时返回空列表（不阻塞 watermark 推进）。"""
        if self._extract_callback is None:
            logger.bind(
                event="consolidation_no_callback",
                module="memory",
                user_id=user_id,
            ).debug("未注入 extract_callback，跳过 LLM 提炼阶段")
            return []

        try:
            messages_for_llm = [
                {
                    "id": m.id,
                    "role": m.role,
                    "content": (m.content or "")[: self.SHORT_TERM_CONTENT_TRUNCATE],
                    "session_id": m.session_id,
                }
                for m, _ in candidates
            ]
            return await self._extract_callback(messages_for_llm, user_id)
        except Exception as exc:
            logger.bind(
                event="consolidation_extract_failed",
                module="memory",
                user_id=user_id,
            ).warning(f"LLM 提炼失败，跳过提炼阶段: {exc}")
            return []

    async def _persist_extracted_memories(
        self,
        candidates: List[Tuple[ShortTermMemory, str]],
        extracted_items: List[Dict[str, Any]],
        user_id: str,
        workspace_id: str,
    ) -> List[int]:
        """对每条提炼结果调用 add_long_term_memory，单条失败被吞不阻塞整体流程。"""
        consolidated_memory_ids: List[int] = []
        candidate_ids = [m.id for m, _ in candidates]
        for item in extracted_items:
            content = str(item.get("content", "")).strip()
            if not content or len(content) > self.memory_manager._MAX_LONG_TERM_CONTENT_CHARS:
                continue
            try:
                source_id = item.get("source_short_term_memory_id")
                if isinstance(source_id, int) and source_id in candidate_ids:
                    extracted_from = [source_id]
                else:
                    extracted_from = list(candidate_ids)
                memory = await self.memory_manager.add_long_term_memory(
                    content=content,
                    importance=float(item.get("importance", 0.5)),
                    user_id=user_id,
                    source_type=item.get("source_type", "llm_extracted"),
                    workspace_id=workspace_id,
                    extracted_from=extracted_from,
                )
                consolidated_memory_ids.append(memory.id)
            except ValueError as exc:
                logger.bind(
                    event="consolidation_add_skipped",
                    module="memory",
                    user_id=user_id,
                ).warning(f"巩固写入跳过单条: {exc}")
            except Exception as exc:
                logger.bind(
                    event="consolidation_add_failed",
                    module="memory",
                    user_id=user_id,
                ).warning(f"巩固写入单条失败: {exc}")
        return consolidated_memory_ids

    async def _persist_fingerprints_and_watermark(
        self,
        candidates: List[Tuple[ShortTermMemory, str]],
        consolidated_memory_ids: List[int],
        new_memories: List[ShortTermMemory],
        user_id: str,
        workspace_id: str,
    ) -> int:
        """
        持久化 fingerprint（即使提炼失败也标记已处理，避免重复 LLM 调用），
        更新 watermark 与重置计数器，返回新 watermark。
        """
        await asyncio.to_thread(
            self._persist_fingerprints_sync,
            user_id,
            workspace_id,
            candidates,
            consolidated_memory_ids,
        )
        new_watermark = max(m.id for m in new_memories)
        self._update_watermark_sync(user_id, workspace_id, new_watermark)
        self._reset_counter_sync(user_id, workspace_id)
        return new_watermark

    # ---------------- 同步 DB 操作 ----------------

    def _get_or_create_state_sync(
        self,
        user_id: str,
        workspace_id: str,
    ) -> ConsolidationState:
        """读取或创建用户的巩固状态行。"""
        with self.session_factory() as db:
            return self._get_or_create_state_in_session(db, user_id, workspace_id)

    def _get_or_create_state_in_session(
        self,
        db: Session,
        user_id: str,
        workspace_id: str,
    ) -> ConsolidationState:
        from db.models import ConsolidationState as _CS

        state = db.query(_CS).filter(_CS.user_id == user_id).first()
        if state is None:
            state = _CS(
                user_id=user_id,
                workspace_id=workspace_id,
                last_short_term_memory_id=0,
                last_run_at=None,
                conversation_count_since_run=0,
                last_error=None,
            )
            db.add(state)
            db.commit()
            db.refresh(state)
        return state

    def _read_short_term_memories_sync(
        self,
        user_id: str,
        watermark: int,
        workspace_id: str,
        batch_size: int,
    ) -> List[ShortTermMemory]:
        """
        增量读取 id > watermark 的短期记忆。

        按 id 升序读取，限制 batch_size 条。
        工作区隔离过滤（user_id 在 ShortTermMemory 表中无字段，依赖 session_id 隔离；
        workspace_id 作为顶层隔离）。
        """
        with self.session_factory() as db:
            query = (
                db.query(ShortTermMemory)
                .filter(ShortTermMemory.id > watermark)
                .filter(ShortTermMemory.workspace_id == workspace_id)
                .order_by(ShortTermMemory.id.asc())
                .limit(batch_size)
            )
            rows = query.all()
            # expunge 后对象仍可访问列属性，供异步线程使用
            for row in rows:
                db.expunge(row)
            return rows

    def _get_existing_fingerprints_sync(
        self,
        user_id: str,
        workspace_id: str,
        short_term_memory_ids: List[int],
    ) -> set:
        """查询已处理的指纹集合（基于 short_term_memory_id 关联）。"""
        if not short_term_memory_ids:
            return set()
        with self.session_factory() as db:
            rows = (
                db.query(ConsolidationFingerprint.fingerprint)
                .filter(ConsolidationFingerprint.user_id == user_id)
                .filter(
                    ConsolidationFingerprint.short_term_memory_id.in_(
                        short_term_memory_ids
                    )
                )
                .all()
            )
            return {row[0] for row in rows}

    def _persist_fingerprints_sync(
        self,
        user_id: str,
        workspace_id: str,
        candidates: List[Tuple[ShortTermMemory, str]],
        consolidated_memory_ids: List[int],
    ) -> None:
        """持久化 fingerprint 表（按 candidate 顺序与 consolidated_memory_ids 顺序对齐）。"""
        if not candidates:
            return
        with self.session_factory() as db:
            now = datetime.now(timezone.utc)
            # consolidated_memory_ids 顺序与 candidates 顺序对齐：
            # 当 LLM 提炼出 N 条结果时，每条结果对应一个或多个来源候选；
            # 此处采用简化策略：将所有候选标记为已处理，consolidated_memory_id
            # 仅记录到第一个（便于追溯），其余为 None。
            first_consolidated_id = consolidated_memory_ids[0] if consolidated_memory_ids else None
            for idx, (memory, fingerprint) in enumerate(candidates):
                # 已存在则跳过（避免主键冲突，理论上不会发生因 _get_existing_fingerprints 已过滤）
                existing = (
                    db.query(ConsolidationFingerprint)
                    .filter(
                        ConsolidationFingerprint.user_id == user_id,
                        ConsolidationFingerprint.short_term_memory_id == memory.id,
                    )
                    .first()
                )
                if existing is not None:
                    # 更新 consolidated_memory_id（若此前为空现在有值）
                    if existing.consolidated_memory_id is None and first_consolidated_id is not None:
                        existing.consolidated_memory_id = first_consolidated_id
                    continue
                fp_record = ConsolidationFingerprint(
                    user_id=user_id,
                    workspace_id=workspace_id,
                    fingerprint=fingerprint,
                    short_term_memory_id=memory.id,
                    consolidated_memory_id=first_consolidated_id if idx == 0 else None,
                    created_at=now,
                )
                db.add(fp_record)
            db.commit()

    def _update_watermark_sync(
        self,
        user_id: str,
        workspace_id: str,
        new_watermark: int,
    ) -> None:
        """更新 watermark 与 last_run_at。"""
        with self.session_factory() as db:
            state = self._get_or_create_state_in_session(db, user_id, workspace_id)
            state.last_short_term_memory_id = new_watermark
            state.last_run_at = datetime.now(timezone.utc)
            state.last_error = None  # 成功后清空错误
            db.commit()

    def _reset_counter_sync(
        self,
        user_id: str,
        workspace_id: str,
    ) -> None:
        """重置 conversation_count_since_run。"""
        with self.session_factory() as db:
            state = self._get_or_create_state_in_session(db, user_id, workspace_id)
            state.conversation_count_since_run = 0
            db.commit()

    def _record_failure_sync(
        self,
        user_id: str,
        workspace_id: str,
        exc: Exception,
    ) -> None:
        """失败时记录 last_error，watermark 不更新（下次重试）。"""
        with self.session_factory() as db:
            state = self._get_or_create_state_in_session(db, user_id, workspace_id)
            state.last_error = f"{type(exc).__name__}: {exc}"[:2000]
            db.commit()

    def _evaluate_and_archive_low_quality_sync(
        self,
        user_id: str,
        workspace_id: str,
    ) -> int:
        """
        评估并归档低质量记忆（Spec Task 10）。

        规则：
        - confidence < 0.2 且 access_count > 20 → state=archived
          （语义：写入以来 confidence 一直很低，但被频繁访问说明 LLM 经常检索到
          却又未被认可为高质量，应归档避免污染上下文）
        - 30 天未访问且 importance < 0.3 → state=archived
        - state=validated 的记忆不参与归档（用户已确认）

        归档判断使用"重算前的旧 confidence"：因为五因子公式中 access_factor
        会随 access_count 线性提升，重算后原本低 confidence 的记忆会被推高，
        导致归档条件永不可达。旧 confidence 反映"写入后从未被认可"的真实状态。

        但 confidence 字段仍按重算结果持久化（用于检索时返回最新值）。

        Returns:
            归档的记忆数量
        """
        from db.models import LongTermMemory

        reference_time = datetime.now(timezone.utc)
        archived_count = 0
        with self.session_factory() as db:
            # 仅评估 state=active 的记忆
            query = (
                db.query(LongTermMemory)
                .filter(
                    LongTermMemory.user_id == user_id,
                    LongTermMemory.workspace_id == workspace_id,
                    LongTermMemory.state == "active",
                )
            )
            for memory in query.yield_per(200):
                # 保留旧 confidence 用于归档判断（避免 access_factor 推高后无法归档）
                old_confidence = float(memory.confidence or 0)
                old_access_count = int(memory.access_count or 0)
                # 评估归档条件：用旧 confidence（重算前）+ 当前 access_count
                last_access = self.memory_manager._ensure_aware_datetime(memory.last_access)
                age_days = max(0.0, (reference_time - last_access).total_seconds() / 86400)
                low_quality = old_confidence < 0.2 and old_access_count > 20
                stale_and_unimportant = age_days >= 30 and (memory.importance or 0) < 0.3
                # 重算 confidence 与 quality_score 持久化（即使不归档也更新）
                memory.confidence = self.memory_manager._calculate_confidence(
                    memory, reference_time=reference_time
                )
                memory.quality_score = self.memory_manager._calculate_quality_score(
                    memory, reference_time=reference_time
                )
                if low_quality or stale_and_unimportant:
                    memory.state = "archived"
                    # 同步 archive_status（向后兼容）
                    memory.archive_status = "archived"
                    archived_count += 1
                    # 同步向量库元数据
                    try:
                        self.memory_manager.vector_store.update_memory_metadata(
                            memory.id,
                            archive_status="archived",
                            confidence=memory.confidence,
                            quality_score=memory.quality_score,
                        )
                    except Exception as exc:
                        logger.warning(
                            f"向量库归档元数据同步失败 memory_id={memory.id}: {exc}"
                        )
            db.commit()
        return archived_count

    # ---------------- 工具方法 ----------------

    @staticmethod
    def _compute_fingerprint(content: str) -> str:
        """
        计算短期记忆内容的指纹（SHA-256 截断 32 字符）。

        与 LongTermMemory.similarity_hash 算法一致（基于归一化内容），
        便于跨表对账与一致性校验。
        """
        normalized = " ".join(str(content or "").split()).lower()
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:32]
