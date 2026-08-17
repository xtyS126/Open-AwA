"""
记忆管理模块，负责短期记忆、长期记忆、工作内存与向量检索能力的统一编排。

MemoryManager 作为薄门面层，委托给以下子组件：
- MemoryCacheManager：缓存管理（向量搜索缓存、历史缓存）
- MemoryWriter：写入操作（短期/长期记忆的创建、更新、归档、删除）
- MemoryReader：读取操作（检索、查询、统计、质量评估）
"""

from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from loguru import logger

from db.models import ConversationRecord, LongTermMemory, ShortTermMemory
from core.conversation_sessions import ensure_conversation
from memory.consolidation import calculate_similarity
from memory.memory_cache import MemoryCacheManager
from memory.memory_reader import MemoryReader
from memory.memory_writer import MemoryWriter
from memory.pii_guard import scrub as pii_scrub
from memory.vector_store_manager import VectorStoreManager
from memory.working_memory import working_memory_store


class MemoryManager:
    """
    记忆管理器（门面层）。

    委托给以下子组件：
    - MemoryCacheManager：缓存管理（向量搜索缓存、历史缓存）
    - MemoryWriter：写入操作（短期/长期记忆的创建、更新、归档、删除）
    - MemoryReader：读取操作（检索、查询、统计、质量评估）
    """

    _shared_vector_store: Optional[VectorStoreManager] = None
    _shared_vector_store_lock = Lock()
    _MAX_SEARCH_QUERY_CHARS = 1024
    # Spec memory-quality-and-short-term-recovery：长期记忆原始内容长度上限
    _MAX_LONG_TERM_CONTENT_CHARS = 500

    def __init__(
        self,
        session_factory,
        dedup_similarity_threshold: float = 0.85,
    ):
        # 使用会话工厂而非固定会话，确保每次线程内操作都使用独立短生命周期会话，避免 Session 被跨线程共享
        self.session_factory = session_factory
        threshold = float(dedup_similarity_threshold)
        if not 0.0 <= threshold <= 1.0:
            raise ValueError("记忆去重相似度阈值必须位于 0.0 到 1.0 之间")
        self.dedup_similarity_threshold = threshold
        if self.__class__._shared_vector_store is None:
            with self.__class__._shared_vector_store_lock:
                if self.__class__._shared_vector_store is None:
                    self.__class__._shared_vector_store = VectorStoreManager()
        self.vector_store = self.__class__._shared_vector_store
        self.working_memory = working_memory_store
        # 短消息阈值：低于此长度的查询跳过向量检索，只做关键词检索
        self._SHORT_QUERY_THRESHOLD = 4
        # Spec memory-quality-and-short-term-recovery：写入去重时合并内容的 LLM callback
        self._llm_merge_callback: Optional[Callable[[str, str], Awaitable[str]]] = None
        # Spec memory-model-config-chain：检索重排器（可选，未配置时为 None）
        self._reranker = None
        self._reranker_failure: Optional[Exception] = None
        self._reranker_lock = Lock()

        # 子组件：缓存管理器、写入器、读取器
        self._cache = MemoryCacheManager()
        self._writer = MemoryWriter(self)
        self._reader = MemoryReader(self, self._cache)

        logger.info("MemoryManager initialized")

    def __getattr__(self, name: str):
        """
        懒初始化子组件，支持 object.__new__ 绕过 __init__ 的测试场景。

        当 __init__ 未被调用时，首次访问 _cache/_writer/_reader 时自动创建。
        """
        if name in ('_cache', '_writer', '_reader'):
            if name == '_cache':
                val = MemoryCacheManager()
            elif name == '_writer':
                val = MemoryWriter(self)
            else:  # '_reader'
                if '_cache' not in self.__dict__:
                    object.__setattr__(self, '_cache', MemoryCacheManager())
                val = MemoryReader(self, self._cache)
            object.__setattr__(self, name, val)
            return val
        raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")

    # ------------------------------------------------------------------
    # 向后兼容属性：旧缓存属性委托给 self._cache
    # ------------------------------------------------------------------

    @property
    def _vector_search_cache(self):
        return self._cache._vector_search_cache

    @property
    def _vector_search_cache_lock(self):
        return self._cache._vector_search_cache_lock

    @property
    def _VECTOR_CACHE_MAX(self):
        return self._cache._max_vector_cache_size

    @_VECTOR_CACHE_MAX.setter
    def _VECTOR_CACHE_MAX(self, value):
        self._cache._max_vector_cache_size = value

    @property
    def _history_cache(self):
        return self._cache._history_cache

    @property
    def _history_cache_lock(self):
        return self._cache._history_cache_lock

    @property
    def _history_cache_maxsize(self):
        return self._cache._history_cache_maxsize

    @property
    def _history_cache_ttl(self):
        return self._cache._history_cache_ttl

    def _get_reranker(self):
        """
        懒加载检索重排器（Spec memory-model-config-chain）。

        重排器加载失败时缓存异常并直接抛出（fail-fast），
        不允许检索静默退回融合排序；后续调用复用缓存的失败原因。
        """
        if self._reranker_failure is not None:
            raise self._reranker_failure
        if self._reranker is not None:
            return self._reranker
        with self._reranker_lock:
            if self._reranker_failure is not None:
                raise self._reranker_failure
            if self._reranker is not None:
                return self._reranker
            try:
                from memory.reranker import create_reranker

                self._reranker = create_reranker()
            except Exception as exc:
                self._reranker_failure = exc
                raise
            return self._reranker

    async def _apply_rerank(
        self,
        query: str,
        memories: List[LongTermMemory],
        limit: int,
    ) -> List[LongTermMemory]:
        """
        对混合检索候选做二次相关性重排（Spec memory-model-config-chain）。

        重排分数与融合分数独立：候选数量大于 1 且重排器可用时，
        按重排分数重新排序后截断到 limit；否则原样返回（未配置重排）。
        重排执行失败或分数不匹配时直接抛错，不允许静默跳过。
        """
        reranker = self._get_reranker()
        if reranker is None or len(memories) <= 1:
            return memories
        scores = await reranker.rerank(query, [m.content for m in memories])
        if len(scores) != len(memories):
            raise RuntimeError(
                f"重排分数数量不匹配（{len(scores)} != {len(memories)}），"
                f"重排器实现异常，拒绝使用不可信的重排结果"
            )
        paired = sorted(
            zip(memories, scores), key=lambda item: item[1], reverse=True
        )
        return [memory for memory, _ in paired[:limit]]

    def set_llm_merge_callback(self, callback: Callable[[str, str], Awaitable[str]]) -> None:
        """注入 LLM 合并回调（委托给写入器）。"""
        self._writer.set_llm_merge_callback(callback)

    def _compute_similarity_hash(self, content: str) -> str:
        """
        计算内容的去重指纹（SHA-256 截断 16 字节）。

        用于快速判断完全相同的内容是否已写入，避免重复嵌入计算。
        指纹基于已脱敏后的内容，避免敏感字段影响指纹稳定性。
        """
        normalized = " ".join(str(content or "").split()).lower()
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:32]

    async def _merge_memory_content(self, existing_content: str, new_content: str) -> str:
        """
        合并两段内容生成新的记忆文本。

        - 注入 LLM 合并回调时：回调失败或返回空 → 直接抛错（传播），
          不允许以低质量拼接作为静默兜底
        - 未注入回调时：仅当两段内容存在无损包含关系时才可确定性合并
          （new 是 existing 的子串 → 保留 existing；existing 是 new 的子串
          → 用 new 替换）；其余情况无法保证合并质量，显式抛错
        """
        existing_normalized = str(existing_content or "").strip()
        new_normalized = str(new_content or "").strip()
        if not existing_normalized:
            return new_normalized
        if not new_normalized:
            return existing_normalized
        if self._llm_merge_callback is not None:
            try:
                merged = await self._llm_merge_callback(existing_normalized, new_normalized)
            except Exception as exc:
                raise RuntimeError(
                    f"LLM 记忆合并失败，去重合并中止（不静默降级为拼接）: {exc}"
                ) from exc
            if not merged or not merged.strip():
                raise RuntimeError("LLM 记忆合并回调未返回有效内容，去重合并中止")
            return merged.strip()[: self._MAX_LONG_TERM_CONTENT_CHARS]
        # 无损子串规则（不依赖 LLM 的确定性合并）
        if new_normalized in existing_normalized:
            return existing_normalized
        if existing_normalized in new_normalized:
            return new_normalized
        raise RuntimeError(
            "未注入 LLM 合并回调，且两段内容无包含关系，"
            "无法执行去重合并；请为 MemoryManager 注入合并回调"
        )

    async def _find_duplicate_memory(
        self,
        content: str,
        embedding: List[float],
        user_id: Optional[str],
        workspace_id: str = "default",
    ) -> Optional[Tuple[int, float]]:
        """
        查找与给定内容最相似的已有记忆，返回 (memory_id, similarity) 或 None。

        实现：
        1. 用 vector_store.search 拿候选 top-K（RRF 融合分数）
        2. 从 DB 读出每个候选的 embedding
        3. 用 calculate_similarity 计算真正的余弦相似度
        4. 取最大值，与构造时注入的去重阈值比较

        Args:
            content: 已脱敏的内容文本
            embedding: content 的嵌入向量
            user_id: 用户隔离
            workspace_id: 工作区隔离

        Returns:
            (memory_id, similarity) 当且仅当 similarity > 阈值时返回，否则 None。
        """
        # 向量检索失败直接传播：去重防线不得静默失效（否则重复记忆会落库）
        vector_hits = await self.vector_store.search(
            content,
            user_id=user_id,
            limit=5,
            include_archived=False,
        )

        if not vector_hits:
            return None

        candidate_ids = [hit.memory_id for hit in vector_hits]
        # 同步读出候选记忆的 embedding
        candidate_embeddings: Dict[int, List[float]] = {}
        with self.session_factory() as db:
            rows = (
                db.query(LongTermMemory.id, LongTermMemory.embedding)
                .filter(
                    LongTermMemory.id.in_(candidate_ids),
                    LongTermMemory.workspace_id == workspace_id,
                )
                .all()
            )
            for row in rows:
                if row.embedding:
                    candidate_embeddings[row.id] = row.embedding

        best_id: Optional[int] = None
        best_score: float = 0.0
        for hit in vector_hits:
            candidate_emb = candidate_embeddings.get(hit.memory_id)
            if not candidate_emb:
                continue
            similarity = calculate_similarity(embedding, candidate_emb)
            if similarity > best_score:
                best_score = similarity
                best_id = hit.memory_id

        if best_id is None or best_score <= self.dedup_similarity_threshold:
            return None
        return best_id, best_score

    def _source_score(self, metadata: Optional[Dict[str, Any]]) -> float:
        source_type = str((metadata or {}).get("source_type", "user_input")).strip().lower()
        score_map = {
            "system": 0.95,
            "workflow": 0.85,
            "document": 0.8,
            "agent": 0.75,
            "user_input": 0.65,
            "manual": 0.7,
        }
        return score_map.get(source_type, 0.55)

    def _source_score_for_confidence(self, metadata: Optional[Dict[str, Any]]) -> float:
        """
        计算五因子加权 confidence 使用的来源权重。

        Spec memory-quality-and-short-term-recovery：
        - user_input=1.0（用户直接声明，可信度最高）
        - llm_extracted=0.8（LLM 从对话中提炼的事实）
        - plugin=0.6（插件上报的派生数据）
        - 默认 0.5（未知来源）

        向后兼容：现有 source_type 值（agent/system/workflow/document/manual）
        按可信度等价映射到上述三档。
        """
        source_type = str((metadata or {}).get("source_type", "")).strip().lower()
        score_map = {
            "user_input": 1.0,
            "llm_extracted": 0.8,
            "plugin": 0.6,
            # 向后兼容：将现有 source_type 值映射到 spec 三档
            "agent": 0.8,        # agent 提取 ≈ llm_extracted
            "system": 0.8,       # 系统注入 ≈ llm_extracted
            "workflow": 0.6,     # 工作流派生 ≈ plugin
            "document": 0.6,
            "manual": 1.0,       # 手动写入 ≈ user_input
        }
        return score_map.get(source_type, 0.5)

    def _ensure_aware_datetime(self, value: Optional[datetime]) -> datetime:
        """
        将数据库返回的时间统一转换为带 UTC 时区的 datetime。
        """
        if value is None:
            return datetime.now(timezone.utc)
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def _calculate_confidence(
        self,
        memory: LongTermMemory,
        reference_time: Optional[datetime] = None,
        *,
        dedup_hit: bool = False,
    ) -> float:
        """
        五因子加权 confidence 计算（spec: memory-quality-and-short-term-recovery）。

        公式：
            confidence = source_score * 0.3
                       + completeness_score * 0.25
                       + recency_score * 0.2
                       + dedup_penalty * 0.15
                       + access_factor * 0.1

        - source_score: 来自 metadata.source_type（user_input=1.0 / llm_extracted=0.8 / plugin=0.6 / 默认 0.5）
        - completeness_score: min(len(content.strip()) / 200, 1.0)
        - recency_score: max(0.0, 1.0 - (age_days / 30))，age_days 基于 last_access
        - dedup_penalty: 默认 1.0，去重命中时为 0.0（减分）
        - access_factor: min(access_count / 20, 1.0)

        去重命中时额外 +0.05 强化（不超过 1.0 上限）。

        Args:
            memory: 长期记忆 ORM 对象。
            reference_time: 评估基准时间，默认当前 UTC 时间。
            dedup_hit: 是否在本次写入流程中命中去重（去重合并路径专用）。
        """
        reference_time = self._ensure_aware_datetime(reference_time or datetime.now(timezone.utc))
        metadata = memory.memory_metadata or {}
        source_score = self._source_score_for_confidence(metadata)
        completeness_score = min(len((memory.content or "").strip()) / 200, 1.0)
        last_access = self._ensure_aware_datetime(memory.last_access)
        age_days = max(0.0, (reference_time - last_access).total_seconds() / 86400)
        recency_score = max(0.0, 1.0 - (age_days / 30))
        dedup_penalty = 0.0 if dedup_hit else 1.0
        access_factor = min((memory.access_count or 0) / 20, 1.0)
        confidence = (
            source_score * 0.3
            + completeness_score * 0.25
            + recency_score * 0.2
            + dedup_penalty * 0.15
            + access_factor * 0.1
        )
        if dedup_hit:
            # 去重命中时额外强化 +0.05（不超过 1.0）
            confidence = min(1.0, confidence + 0.05)
        return max(0.0, min(1.0, confidence))

    def _calculate_quality_score(
        self,
        memory: LongTermMemory,
        reference_time: Optional[datetime] = None,
    ) -> float:
        reference_time = self._ensure_aware_datetime(reference_time or datetime.now(timezone.utc))
        created_at = self._ensure_aware_datetime(memory.created_at)
        metadata = memory.memory_metadata or {}
        source_score = self._source_score(metadata)
        completeness_score = min(len((memory.content or "").strip()) / 400, 1.0)
        age_days = max(0.0, (reference_time - created_at).total_seconds() / 86400)
        recency_score = max(0.0, 1.0 - (age_days / 30))
        importance_score = max(0.0, min(1.0, memory.importance))
        return round(
            (source_score * 0.3)
            + (completeness_score * 0.25)
            + (recency_score * 0.25)
            + (importance_score * 0.2),
            4,
        )

    def _should_archive(
        self,
        memory: LongTermMemory,
        reference_time: Optional[datetime] = None,
        *,
        older_than_days: int = 30,
        importance_threshold: float = 0.3,
        include_low_quality: bool = True,
    ) -> bool:
        reference_time = self._ensure_aware_datetime(reference_time or datetime.now(timezone.utc))
        last_access = self._ensure_aware_datetime(memory.last_access)
        inactive_days = max(0.0, (reference_time - last_access).total_seconds() / 86400)
        stale_and_unimportant = inactive_days >= older_than_days and memory.importance < importance_threshold
        low_quality = include_low_quality and memory.confidence < 0.2 and memory.access_count > 20
        return stale_and_unimportant or low_quality

    def _build_runtime_payload(self, memory: LongTermMemory) -> Dict[str, Any]:
        last_access = self._ensure_aware_datetime(memory.last_access)
        return {
            "id": memory.id,
            "content": memory.content,
            "importance": memory.importance,
            "confidence": memory.confidence,
            "quality_score": memory.quality_score,
            "archive_status": memory.archive_status,
            "last_access": last_access.isoformat(),
        }

    def _sync_runtime_layers(self, memory: LongTermMemory) -> Optional[str]:
        """
        同步运行时层（working_memory + 向量库元数据）。

        向量 point 缺失（KeyError）说明 DB 行与向量库不一致：记录 ERROR 日志、
        在记忆对象上标记 ``vector_sync_error`` 并返回错误信息——单条缺失不拖垮
        列表/检索等读取路径；其余 Qdrant 异常（连接/存储故障）仍直接传播（fail-closed）。
        写入路径（合并）必须检查返回值并显式抛错，维持 DB/向量一致性。
        """
        last_access = self._ensure_aware_datetime(memory.last_access)
        self.working_memory.put(str(memory.id), self._build_runtime_payload(memory), user_id=memory.user_id)
        try:
            self.vector_store.update_memory_metadata(
                memory.id,
                importance=memory.importance,
                archive_status=memory.archive_status,
                confidence=memory.confidence,
                quality_score=memory.quality_score,
                access_count=memory.access_count,
                last_access=last_access.isoformat(),
            )
        except KeyError as exc:
            error_message = f"向量库缺少记忆 id={memory.id} 的 point，元数据同步失败: {exc}"
            logger.bind(
                event="memory_vector_sync_failed",
                module="memory",
                memory_id=memory.id,
            ).error(error_message)
            memory.vector_sync_error = error_message
            return error_message
        memory.vector_sync_error = None
        return None

    def _evaluate_memory_in_session(
        self,
        db,
        memory: LongTermMemory,
        commit: bool = True,
        *,
        increment_access: bool = False,
    ) -> Dict[str, Any]:
        """
        在调用方提供的 db 会话中原位评估记忆质量，不自行创建会话。
        要求 memory 对象已挂在该 db 会话上，确保 commit 有效。

        Spec memory-quality-and-short-term-recovery：访问时懒评估强化。
        - increment_access=True 时执行：access_count +1、last_access 更新为当前时间
        - 重新计算 confidence（五因子加权）与 quality_score
        - recency_score 因 last_access 更新而提升到 1.0
        - access_count 因子从 (n-1)/20 提升到 n/20
        - 数据库持久化新值（commit=True 时）

        Args:
            db: 数据库会话
            memory: 记忆 ORM 对象
            commit: 是否在评估后立即提交。批量循环调用时传 False，由调用方统一 commit
                    避免每条记忆一次 commit 造成的性能损耗（原 N 次 commit → 1 次）
            increment_access: 是否在评估时 +1 access_count 并刷新 last_access。
                              memory_recall 命中时传 True；批量列表查询时传 False。
        """
        reference_time = datetime.now(timezone.utc)
        if increment_access:
            memory.access_count = (memory.access_count or 0) + 1
            memory.last_access = reference_time
        memory.confidence = self._calculate_confidence(memory, reference_time=reference_time)
        memory.quality_score = self._calculate_quality_score(memory, reference_time=reference_time)
        if memory.archive_status != "archived" and self._should_archive(memory, reference_time=reference_time):
            memory.archive_status = "archived"
        if commit:
            db.commit()
        # 向量 point 缺失时返回该条目的显式错误状态（vector_sync_error），
        # 不拖垮整个列表/质量报告
        vector_sync_error = self._sync_runtime_layers(memory)
        return {
            "memory_id": memory.id,
            "confidence": round(memory.confidence, 4),
            "quality_score": round(memory.quality_score, 4),
            "archive_status": memory.archive_status,
            "importance": memory.importance,
            "access_count": memory.access_count,
            "vector_sync_error": vector_sync_error,
        }

    def _add_short_term_memory_sync(
        self,
        session_id: str,
        role: str,
        content: str,
        user_id: Optional[str] = None,
        reasoning_content: Optional[str] = None,
        tool_events: Optional[list] = None,
        workspace_id: str = "default",
    ) -> ShortTermMemory:
        with self.session_factory() as db:
            ensure_conversation(
                db,
                session_id=session_id,
                user_id=user_id,
                content=content,
                role=role,
                increment_message_count=True,
            )
            memory = ShortTermMemory(
                session_id=session_id,
                role=role,
                content=content,
                reasoning_content=reasoning_content or None,
                tool_events=tool_events or None,
                workspace_id=workspace_id,
            )
            db.add(memory)
            db.commit()
            # 提交成功后失效对话历史缓存，避免后续读取拿到陈旧数据
            self.invalidate_history_cache(session_id)
            db.refresh(memory)
            # expunge 使对象脱离会话但保留已加载的列属性，供调用方使用
            db.expunge(memory)
            return memory

    async def add_short_term_memory(
        self,
        session_id: str,
        role: str,
        content: str,
        user_id: Optional[str] = None,
        reasoning_content: Optional[str] = None,
        tool_events: Optional[list] = None,
        workspace_id: str = "default",
    ) -> ShortTermMemory:
        """添加短期记忆（委托给写入器）。"""
        return await self._writer.add_short_term_memory(
            session_id, role, content, user_id, reasoning_content, tool_events, workspace_id,
        )

    def _append_to_last_assistant_memory_sync(
        self,
        session_id: str,
        content: str,
        user_id: Optional[str] = None,
        reasoning_content: Optional[str] = None,
        tool_events: Optional[list] = None,
        workspace_id: str = "default",
    ) -> ShortTermMemory:
        normalized_content = str(content or "").strip()
        normalized_reasoning = str(reasoning_content or "").strip()
        if not normalized_content and not normalized_reasoning and not tool_events:
            raise ValueError("content, reasoning_content and tool_events cannot all be empty")

        with self.session_factory() as db:
            memory = (
                db.query(ShortTermMemory)
                .filter(
                    ShortTermMemory.session_id == session_id,
                    ShortTermMemory.role == "assistant",
                    ShortTermMemory.workspace_id == workspace_id,
                )
                .order_by(ShortTermMemory.timestamp.desc(), ShortTermMemory.id.desc())
                .first()
            )

            if memory is None:
                # 不存在则内联创建，避免嵌套调用引入第二个会话
                ensure_conversation(
                    db,
                    session_id=session_id,
                    user_id=user_id,
                    content=normalized_content,
                    role="assistant",
                    increment_message_count=True,
                )
                memory = ShortTermMemory(
                    session_id=session_id,
                    role="assistant",
                    content=normalized_content,
                    reasoning_content=normalized_reasoning or None,
                    tool_events=tool_events or None,
                    workspace_id=workspace_id,
                )
                db.add(memory)
            else:
                previous_content = str(memory.content or "").strip()
                if normalized_content:
                    memory.content = (
                        f"{previous_content}\n\n{normalized_content}" if previous_content else normalized_content
                    )
                previous_reasoning = str(memory.reasoning_content or "").strip()
                if normalized_reasoning:
                    memory.reasoning_content = (
                        f"{previous_reasoning}\n\n{normalized_reasoning}"
                        if previous_reasoning else normalized_reasoning
                    )
                if tool_events:
                    merged_events = list(memory.tool_events or [])
                    event_index = {
                        str(event.get("id")): index
                        for index, event in enumerate(merged_events)
                        if isinstance(event, dict) and event.get("id")
                    }
                    for event in tool_events:
                        if not isinstance(event, dict):
                            continue
                        event_id = str(event.get("id") or "")
                        if event_id and event_id in event_index:
                            merged_events[event_index[event_id]] = {
                                **merged_events[event_index[event_id]],
                                **event,
                            }
                        else:
                            merged_events.append(event)
                            if event_id:
                                event_index[event_id] = len(merged_events) - 1
                    memory.tool_events = merged_events or None
                memory.timestamp = datetime.now(timezone.utc)
                ensure_conversation(
                    db,
                    session_id=session_id,
                    user_id=user_id,
                    content=memory.content,
                    role="assistant",
                    occurred_at=memory.timestamp,
                    increment_message_count=False,
                )

            db.commit()
            # 提交成功后失效对话历史缓存，避免后续读取拿到陈旧数据
            self.invalidate_history_cache(session_id)
            db.refresh(memory)
            db.expunge(memory)
            return memory

    async def append_to_last_assistant_memory(
        self,
        session_id: str,
        content: str,
        user_id: Optional[str] = None,
        reasoning_content: Optional[str] = None,
        tool_events: Optional[list] = None,
    ) -> ShortTermMemory:
        """追加到最近一条助手短期记忆（委托给写入器）。"""
        return await self._writer.append_to_last_assistant_memory(
            session_id, content, user_id, reasoning_content, tool_events,
        )

    def _get_short_term_memories_sync(self, session_id: str, limit: int, workspace_id: str = "default") -> List[ShortTermMemory]:
        with self.session_factory() as db:
            memories = (
                db.query(ShortTermMemory)
                .filter(ShortTermMemory.session_id == session_id)
                .filter(ShortTermMemory.workspace_id == workspace_id)
                .order_by(ShortTermMemory.timestamp.desc())
                .limit(limit)
                .all()
            )
            for m in memories:
                db.expunge(m)
            return memories

    async def get_short_term_memories(self, session_id: str, limit: int = 50, workspace_id: str = "default") -> List[ShortTermMemory]:
        """获取短期记忆（委托给读取器，带缓存）。"""
        return await self._reader.get_short_term_memories(session_id, limit, workspace_id)

    def invalidate_history_cache(self, session_id: str) -> None:
        """失效指定 session_id 的对话历史缓存（委托给缓存管理器）。"""
        self._cache.invalidate_history_cache(session_id)

    # ------------------------------------------------------------------
    # Spec memory-quality-and-short-term-recovery Task 11
    # 短期记忆上下文恢复：获取用户最近 N 条短期记忆
    # ------------------------------------------------------------------

    def _get_recent_short_term_memories_sync(
        self,
        user_id: str,
        limit: int = 20,
        workspace_id: str = "default",
    ) -> List[ShortTermMemory]:
        """同步查询用户最近 N 条短期记忆。

        Spec memory-quality-and-short-term-recovery Task 11：
        通过 JOIN ``ConversationRecord`` 实现按 user_id 过滤短期记忆
        （ShortTermMemory 本身只有 session_id 字段，无 user_id）。

        实现策略：
        1. 通过 ConversationRecord 查询用户的所有 session_id（去重）
        2. 在 ShortTermMemory 表上按 session_id IN (...) + workspace_id 过滤
        3. 按 timestamp 倒序取前 limit 条

        Args:
            user_id: 用户 ID
            limit: 返回上限，默认 20
            workspace_id: 工作区隔离

        Returns:
            短期记忆列表，按时间倒序排列
        """
        if not user_id:
            return []
        with self.session_factory() as db:
            # 子查询：用户的所有 session_id（去重）
            session_ids_subq = (
                db.query(ConversationRecord.session_id)
                .filter(ConversationRecord.user_id == user_id)
                .distinct()
                .subquery()
            )
            query = (
                db.query(ShortTermMemory)
                .join(
                    session_ids_subq,
                    ShortTermMemory.session_id == session_ids_subq.c.session_id,
                )
                .filter(ShortTermMemory.workspace_id == workspace_id)
                .order_by(
                    ShortTermMemory.timestamp.desc(),
                    ShortTermMemory.id.desc(),
                )
                .limit(limit)
            )
            results = query.all()
            for m in results:
                db.expunge(m)
            return results

    async def get_recent_short_term_memories(
        self,
        user_id: str,
        limit: int = 20,
        workspace_id: str = "default",
    ) -> List[ShortTermMemory]:
        """获取用户最近 N 条短期记忆（委托给读取器）。"""
        return await self._reader.get_recent_short_term_memories(user_id, limit, workspace_id)

    def _clear_short_term_memory_sync(self, session_id: str, workspace_id: str = "default") -> int:
        with self.session_factory() as db:
            count = db.query(ShortTermMemory).filter(
                ShortTermMemory.session_id == session_id,
                ShortTermMemory.workspace_id == workspace_id,
            ).delete()
            db.commit()
            # 清空后旧缓存不再有效，失效对话历史缓存
            self.invalidate_history_cache(session_id)
            return count

    async def clear_short_term_memory(self, session_id: str, workspace_id: str = "default") -> int:
        """清空短期记忆（委托给写入器）。"""
        return await self._writer.clear_short_term_memory(session_id, workspace_id)

    def _search_short_term_memories_sync(
        self,
        query: str,
        session_id: Optional[str] = None,
        limit: int = 10,
        workspace_id: str = "default",
    ) -> List[ShortTermMemory]:
        """
        Spec memory-quality-and-short-term-recovery Task 15：
        按关键词模糊匹配短期记忆（content LIKE 查询）。

        用于 builtin_memory_search_short_term 工具，让 AI 能检索最近对话内容中
        包含特定关键词的消息，回顾用户曾提到的具体细节。

        Args:
            query: 搜索关键词（非空，去除首尾空白后必须非空）
            session_id: 可选，按会话 ID 过滤。不传时搜索全部短期记忆
            limit: 返回上限，默认 10，最大 50
            workspace_id: 工作区隔离

        Returns:
            匹配的短期记忆列表，按 timestamp 倒序排列。
            使用 contains + autoescape 自动转义 LIKE 特殊字符（%、_、\\），
            避免关键词包含通配符时破坏查询语义。
        """
        normalized = (query or "").strip()
        if not normalized:
            return []
        limit = max(1, min(50, int(limit or 10)))
        with self.session_factory() as db:
            base_query = db.query(ShortTermMemory).filter(
                ShortTermMemory.workspace_id == workspace_id
            )
            if session_id:
                base_query = base_query.filter(ShortTermMemory.session_id == session_id)
            # autoescape=True 让 SQLAlchemy 自动转义 LIKE 特殊字符并设置 ESCAPE '\'
            base_query = base_query.filter(
                ShortTermMemory.content.contains(normalized, autoescape=True)
            )
            results = (
                base_query.order_by(
                    ShortTermMemory.timestamp.desc(),
                    ShortTermMemory.id.desc(),
                )
                .limit(limit)
                .all()
            )
            for m in results:
                db.expunge(m)
            return results

    async def search_short_term_memories(
        self,
        query: str,
        session_id: Optional[str] = None,
        limit: int = 10,
        workspace_id: str = "default",
    ) -> List[ShortTermMemory]:
        """搜索短期记忆（委托给读取器）。"""
        return await self._reader.search_short_term_memories(query, session_id, limit, workspace_id)

    def _add_long_term_memory_sync(
        self,
        content: str,
        importance: float,
        embedding: Optional[List[float]],
        user_id: Optional[str] = None,
        memory_metadata: Optional[Dict[str, Any]] = None,
        source_type: Optional[str] = None,
        workspace_id: str = "default",
        memory_layer: str = "semantic",
        dedup_info: Optional[Dict[str, Any]] = None,
    ) -> LongTermMemory:
        """
        写入一条新的长期记忆（同步实现）。

        Spec memory-quality-and-short-term-recovery：
        - 调用方应在调用前完成 PII 脱敏
        - 调用方应在调用前完成去重查询，命中时不应走到这里而应调用 _merge_into_existing_memory_sync
        - dedup_info 用于把去重结果透传到调用方（写到 memory_metadata._dedup_info）

        Args:
            dedup_info: 去重信息字典，None 表示正常写入，dict 表示去重流程的结果。
        """
        metadata = dict(memory_metadata or {})
        if source_type and "source_type" not in metadata:
            metadata["source_type"] = source_type
        now = datetime.now(timezone.utc)

        # 根据记忆层级设置不同的初始权重和衰减策略
        if memory_layer == "core":
            # Core Memory：永久保留，高权重
            importance = max(importance, 0.9)
            metadata["memory_layer"] = "core"
        elif memory_layer == "episodic":
            # Episodic Memory：时间衰减，按访问频率强化
            importance = max(importance, 0.5)
            metadata["memory_layer"] = "episodic"
        elif memory_layer == "working":
            # Working Memory：会话级，结束清理
            importance = min(importance, 0.3)
            metadata["memory_layer"] = "working"
        else:
            # Semantic Memory：默认层，关联强化
            metadata["memory_layer"] = memory_layer

        # 写入去重指纹（基于已脱敏的内容）
        # Spec memory-quality-and-short-term-recovery：similarity_hash 同时写入
        # 专用列与 metadata，专用列支持索引查询，metadata 兼容旧读取路径
        similarity_hash = self._compute_similarity_hash(content)
        metadata["similarity_hash"] = similarity_hash
        # extracted_from 提升到专用列，同时保留 metadata 副本用于旧读取路径
        extracted_from_list: Optional[List[int]] = None
        if metadata.get("extracted_from"):
            extracted_from_list = list(metadata.get("extracted_from") or [])
        # 去重信息透传到 metadata，便于调用方读取
        if dedup_info is not None:
            metadata["_dedup_info"] = dedup_info

        memory = LongTermMemory(
            content=content,
            importance=importance,
            embedding=embedding,
            user_id=user_id,
            workspace_id=workspace_id,
            created_at=now,
            last_access=now,
            # 占位 0.0，下面通过 _calculate_confidence 真实计算
            confidence=0.0,
            archive_status="active",
            memory_metadata=metadata,
            memory_layer=memory_layer,
            state="active",
            similarity_hash=similarity_hash,
            extracted_from=extracted_from_list,
        )
        # confidence 真实计算（五因子加权），依赖 memory 对象本身，故先创建再算
        memory.confidence = self._calculate_confidence(memory, reference_time=now)
        memory.quality_score = self._calculate_quality_score(memory, reference_time=now)
        with self.session_factory() as db:
            db.add(memory)
            db.commit()
            db.refresh(memory)
            db.expunge(memory)
        return memory

    def _merge_into_existing_memory_sync(
        self,
        memory_id: int,
        merged_content: str,
        new_embedding: Optional[List[float]],
        new_importance: float,
        new_metadata: Optional[Dict[str, Any]] = None,
        new_source_type: Optional[str] = None,
        extracted_from: Optional[List[int]] = None,
    ) -> Optional[LongTermMemory]:
        """
        将新内容合并到已有长期记忆（同步实现）。

        Spec memory-quality-and-short-term-recovery：
        - 命中去重时合并 content（由调用方通过 LLM 或确定性合并生成）
        - access_count +1
        - last_access 更新为当前时间
        - confidence 重新计算（去重命中强化 +0.05）
        - similarity_hash 更新为新内容的指纹
        - 通过 memory_metadata._dedup_info 标记 deduplicated=True / merged_into=memory_id

        Args:
            memory_id: 已有记忆 ID
            merged_content: LLM 或确定性合并后的新内容
            new_embedding: 合并后内容的嵌入向量（None 时保留原 embedding）
            new_importance: 新内容的重要度（取 max(existing, new)）
            new_metadata: 新内容携带的 metadata（合并到已有 metadata）
            new_source_type: 新内容来源类型（写入 _dedup_info）
            extracted_from: 来源短期记忆 ID 列表（合并到已有 extracted_from）
        """
        now = datetime.now(timezone.utc)
        with self.session_factory() as db:
            memory = db.query(LongTermMemory).filter(LongTermMemory.id == memory_id).first()
            if memory is None:
                return None

            existing_metadata = dict(memory.memory_metadata or {})
            if new_metadata:
                for key, value in new_metadata.items():
                    if key not in existing_metadata:
                        existing_metadata[key] = value
            # 合并 extracted_from 列表
            existing_extracted_from: List[int] = list(existing_metadata.get("extracted_from") or [])
            if extracted_from:
                for short_term_id in extracted_from:
                    if short_term_id not in existing_extracted_from:
                        existing_extracted_from.append(short_term_id)
                existing_metadata["extracted_from"] = existing_extracted_from

            memory.content = merged_content
            memory.importance = max(memory.importance, new_importance)
            if new_embedding is not None:
                memory.embedding = new_embedding
            memory.last_access = now
            memory.access_count = (memory.access_count or 0) + 1
            # 更新 similarity_hash（基于合并后的内容）
            existing_metadata["similarity_hash"] = self._compute_similarity_hash(merged_content)
            # 标记去重结果
            existing_metadata["_dedup_info"] = {
                "deduplicated": True,
                "merged_into": memory_id,
                "merged_at": now.isoformat(),
                "new_source_type": new_source_type,
            }
            memory.memory_metadata = existing_metadata
            # 去重命中时 confidence 强化 +0.05
            memory.confidence = self._calculate_confidence(memory, reference_time=now, dedup_hit=True)
            memory.quality_score = self._calculate_quality_score(memory, reference_time=now)
            db.commit()
            db.refresh(memory)
            # 写入路径 fail-closed：合并后的向量元数据同步失败必须显式抛错，
            # 不允许 DB 侧已合并、向量侧仍为旧状态的一致性分叉
            sync_error = self._sync_runtime_layers(memory)
            if sync_error:
                raise RuntimeError(sync_error)
            db.expunge(memory)
            return memory

    async def add_long_term_memory(
        self,
        content: str,
        importance: float = 0.5,
        embedding: Optional[List[float]] = None,
        user_id: Optional[str] = None,
        memory_metadata: Optional[Dict[str, Any]] = None,
        source_type: Optional[str] = None,
        workspace_id: str = "default",
        memory_layer: str = "semantic",
        extracted_from: Optional[List[int]] = None,
        images: Optional[List[Dict[str, Any]]] = None,
    ) -> LongTermMemory:
        """写入长期记忆（委托给写入器，含 PII 脱敏 + 去重合并）。"""
        return await self._writer.add_long_term_memory(
            content, importance, embedding, user_id, memory_metadata,
            source_type, workspace_id, memory_layer, extracted_from, images,
        )

    async def _scrub_and_embed(
        self,
        content: str,
        embedding: Optional[List[float]],
    ) -> tuple[str, List[float]]:
        """
        长度校验 + PII 脱敏 + 嵌入向量计算。

        Raises:
            ValueError: 内容为空或超过 _MAX_LONG_TERM_CONTENT_CHARS
        """
        raw_content = str(content or "")
        if len(raw_content) > self._MAX_LONG_TERM_CONTENT_CHARS:
            raise ValueError(
                f"记忆内容过长（{len(raw_content)} > {self._MAX_LONG_TERM_CONTENT_CHARS}），请提炼后重试"
            )
        if not raw_content.strip():
            raise ValueError("记忆内容不能为空")

        scrubbed_content = pii_scrub(raw_content)

        vector = embedding
        if vector is None:
            vector = await self.vector_store.embedding_provider.embed_texts([scrubbed_content])
            vector = vector[0]

        return scrubbed_content, vector

    async def _try_dedup_merge(
        self,
        scrubbed_content: str,
        vector: List[float],
        *,
        importance: float,
        user_id: Optional[str],
        memory_metadata: Optional[Dict[str, Any]],
        source_type: Optional[str],
        workspace_id: str,
        extracted_from: Optional[List[int]],
    ) -> Optional[LongTermMemory]:
        """
        去重查询 + 合并写入。

        命中时合并到已有记忆并返回 merged_memory；未命中（正常去重漏检）返回 None，
        由调用方走 :meth:`_write_new_memory`。去重命中后的一切合并失败（目标消失、
        合并函数返回 None、向量写入失败）都直接传播异常，不允许静默退化为重复写入。
        """
        duplicate = await self._find_duplicate_memory(
            scrubbed_content,
            vector,
            user_id=user_id,
            workspace_id=workspace_id,
        )
        if duplicate is None:
            return None

        duplicate_id, similarity_score = duplicate
        existing_memory = await asyncio.to_thread(
            self._get_memories_by_ids_sync,
            [duplicate_id],
            user_id,
            False,
            workspace_id,
        )
        if not existing_memory:
            # 向量库命中但 DB 行不存在：向量库与数据库不一致，显式报错
            raise RuntimeError(
                f"去重命中的记忆 id={duplicate_id} 在数据库中不存在，"
                f"向量库与数据库状态不一致"
            )

        existing = existing_memory[0]
        # 捕获合并前快照，向量写入失败时用于回滚 DB 合并（保证原子性）
        snapshot = self._capture_memory_snapshot(existing)
        merged_content = await self._merge_memory_content(existing.content, scrubbed_content)
        if len(merged_content) > self._MAX_LONG_TERM_CONTENT_CHARS:
            merged_content = merged_content[: self._MAX_LONG_TERM_CONTENT_CHARS]
        merged_vector = await self.vector_store.embedding_provider.embed_texts([merged_content])
        merged_vector = merged_vector[0]

        merged_metadata = dict(memory_metadata or {})
        if source_type:
            merged_metadata.setdefault("source_type", source_type)
        if extracted_from:
            merged_metadata.setdefault("extracted_from", list(extracted_from))

        merged_memory = await asyncio.to_thread(
            self._merge_into_existing_memory_sync,
            duplicate_id,
            merged_content,
            merged_vector,
            importance,
            merged_metadata,
            source_type,
            extracted_from,
        )
        if merged_memory is None:
            # 合并目标在合并过程中被并发删除，显式报错而非退化为重复写入
            raise RuntimeError(
                f"合并记忆 id={duplicate_id} 失败：合并目标已不存在"
            )

        try:
            await self.vector_store.upsert_memory(
                merged_memory.id,
                merged_content,
                user_id=user_id,
                importance=merged_memory.importance,
                archive_status=merged_memory.archive_status,
                metadata={
                    **(merged_memory.memory_metadata or {}),
                    "memory_layer": merged_memory.memory_layer,
                    "confidence": merged_memory.confidence,
                    "quality_score": merged_memory.quality_score,
                    "access_count": merged_memory.access_count,
                    "last_access": merged_memory.last_access.isoformat(),
                    "similarity_score": similarity_score,
                },
                embedding=merged_vector,
            )
        except Exception:
            # 向量写入失败：回滚 DB 侧已提交的合并，避免 DB/向量不一致
            try:
                await asyncio.to_thread(
                    self._restore_memory_snapshot_sync, duplicate_id, snapshot
                )
            except Exception as rollback_exc:
                logger.bind(
                    event="memory_merge_rollback_failed",
                    module="memory",
                    memory_id=duplicate_id,
                ).error(f"回滚合并记忆失败 memory_id={duplicate_id}: {rollback_exc}")
            raise
        self.working_memory.put(
            str(merged_memory.id),
            self._build_runtime_payload(merged_memory),
            user_id=user_id,
        )
        logger.bind(
            event="memory_dedup_merged",
            module="memory",
            duplicate_id=duplicate_id,
            similarity=round(similarity_score, 4),
        ).info(f"长期记忆写入去重命中，合并到 id={duplicate_id}（相似度 {similarity_score:.4f}）")
        return merged_memory

    async def _write_new_memory(
        self,
        scrubbed_content: str,
        vector: List[float],
        *,
        importance: float,
        user_id: Optional[str],
        memory_metadata: Optional[Dict[str, Any]],
        source_type: Optional[str],
        workspace_id: str,
        memory_layer: str,
        extracted_from: Optional[List[int]],
    ) -> LongTermMemory:
        """
        写入新 memory 并同步 vector_store 与 working_memory。

        Args:
            scrubbed_content: 已脱敏的内容
            vector: 已计算的嵌入向量
        """
        write_metadata = dict(memory_metadata or {})
        if extracted_from:
            write_metadata.setdefault("extracted_from", list(extracted_from))

        memory = await asyncio.to_thread(
            self._add_long_term_memory_sync,
            scrubbed_content,
            importance,
            vector,
            user_id,
            write_metadata,
            source_type,
            workspace_id,
            memory_layer,
            dedup_info={"deduplicated": False},
        )
        try:
            await self.vector_store.upsert_memory(
                memory.id,
                scrubbed_content,
                user_id=user_id,
                importance=memory.importance,
                archive_status=memory.archive_status,
                metadata={
                    **(memory.memory_metadata or {}),
                    "memory_layer": memory.memory_layer,
                    "confidence": memory.confidence,
                    "quality_score": memory.quality_score,
                    "access_count": memory.access_count,
                    "last_access": memory.last_access.isoformat(),
                },
                embedding=vector,
            )
        except Exception:
            # 向量写入失败：回滚刚插入的 DB 行，避免产生"DB 有行、向量无 point"的
            # 缺失 point 状态（update_memory_metadata 对缺失 point 已改为显式抛错）
            try:
                await asyncio.to_thread(self._delete_long_term_memory_sync, memory.id)
            except Exception as rollback_exc:
                logger.bind(
                    event="memory_write_rollback_failed",
                    module="memory",
                    memory_id=memory.id,
                ).error(f"回滚新记忆失败 memory_id={memory.id}: {rollback_exc}")
            raise
        self.working_memory.put(str(memory.id), self._build_runtime_payload(memory), user_id=user_id)
        logger.debug(f"Added long-term memory with importance {importance}")
        return memory

    def _capture_memory_snapshot(self, memory: LongTermMemory) -> Dict[str, Any]:
        """
        捕获记忆合并前的字段快照，供向量写入失败时回滚 DB 合并使用。
        """
        return {
            "content": memory.content,
            "embedding": memory.embedding,
            "importance": memory.importance,
            "memory_metadata": dict(memory.memory_metadata or {}),
            "access_count": memory.access_count,
            "last_access": memory.last_access,
            "confidence": memory.confidence,
            "quality_score": memory.quality_score,
            "similarity_hash": memory.similarity_hash,
            "extracted_from": list(memory.extracted_from or []) if memory.extracted_from else None,
        }

    def _restore_memory_snapshot_sync(
        self,
        memory_id: int,
        snapshot: Dict[str, Any],
    ) -> None:
        """
        将合并后的记忆字段回滚到合并前快照（同步实现）。

        用于向量写入失败时的补偿操作，保证 DB 与向量库状态一致。
        """
        with self.session_factory() as db:
            memory = db.query(LongTermMemory).filter(LongTermMemory.id == memory_id).first()
            if memory is None:
                return
            memory.content = snapshot["content"]
            memory.embedding = snapshot["embedding"]
            memory.importance = snapshot["importance"]
            memory.memory_metadata = snapshot["memory_metadata"]
            memory.access_count = snapshot["access_count"]
            memory.last_access = snapshot["last_access"]
            memory.confidence = snapshot["confidence"]
            memory.quality_score = snapshot["quality_score"]
            memory.similarity_hash = snapshot["similarity_hash"]
            memory.extracted_from = snapshot["extracted_from"]
            db.commit()

    @classmethod
    def _normalize_search_query(cls, query: str) -> str:
        """压缩超长检索文本，避免 SQLite LIKE 与嵌入模型接收整段代理转录。"""
        normalized = " ".join(str(query or "").split())
        if len(normalized) <= cls._MAX_SEARCH_QUERY_CHARS:
            return normalized

        half = cls._MAX_SEARCH_QUERY_CHARS // 2
        return f"{normalized[:half]} ... {normalized[-half:]}"

    def _get_and_evaluate_long_term_memories_sync(
        self,
        min_importance: float,
        limit: int,
        offset: int = 0,
        user_id: Optional[str] = None,
        include_archived: bool = False,
        include_deprecated: bool = False,
        workspace_id: str = "default",
    ) -> List[LongTermMemory]:
        """
        在同一会话内完成记忆加载与质量评估，避免跨会话传递 ORM 对象。

        Spec memory-quality-and-short-term-recovery Task 9：
        默认排除 ``state="deprecated"`` 的记忆（用户主动遗忘，不注入 LLM 上下文）。
        ``include_deprecated=true`` 时返回 deprecated 状态（用于审计页面）。
        """
        with self.session_factory() as db:
            query = db.query(LongTermMemory).filter(LongTermMemory.importance >= min_importance)
            if user_id is not None:
                query = query.filter(LongTermMemory.user_id == user_id)
            query = query.filter(LongTermMemory.workspace_id == workspace_id)
            if not include_archived:
                query = query.filter(LongTermMemory.archive_status != "archived")
                # Spec Task 9：state 字段同步过滤（archived 状态）
                query = query.filter(LongTermMemory.state != "archived")
            if not include_deprecated:
                # deprecated 状态（用户主动遗忘）默认不返回
                query = query.filter(LongTermMemory.state != "deprecated")
            memories = (
                query.order_by(LongTermMemory.importance.desc(), LongTermMemory.quality_score.desc())
                .offset(offset)
                .limit(limit)
                .all()
            )
            # 批量评估时禁用单次 commit，循环结束后统一提交一次（原 N 次 commit → 1 次）
            for memory in memories:
                self._evaluate_memory_in_session(db, memory, commit=False)
                db.expunge(memory)
            db.commit()
            return memories

    async def get_long_term_memories(
        self,
        min_importance: float = 0.0,
        limit: int = 50,
        offset: int = 0,
        user_id: Optional[str] = None,
        include_archived: bool = False,
        include_deprecated: bool = False,
        workspace_id: str = "default",
    ) -> List[LongTermMemory]:
        """获取长期记忆列表（委托给读取器）。"""
        return await self._reader.get_long_term_memories(
            min_importance, limit, offset, user_id, include_archived, include_deprecated, workspace_id,
        )

    def _update_memory_access_sync(self, memory_id: int) -> None:
        with self.session_factory() as db:
            memory = db.query(LongTermMemory).filter(LongTermMemory.id == memory_id).first()
            if memory:
                memory.access_count += 1
                memory.last_access = datetime.now(timezone.utc)
                memory.confidence = self._calculate_confidence(memory)
                memory.quality_score = self._calculate_quality_score(memory)
                db.commit()
                self._sync_runtime_layers(memory)

    async def update_memory_access(self, memory_id: int) -> None:
        """更新记忆访问记录（委托给写入器）。"""
        await self._writer.update_memory_access(memory_id)

    def _batch_update_memory_access_sync(self, memory_ids: List[int]) -> None:
        """
        批量更新记忆访问记录，单次会话完成全部更新。

        PERF-10: 将 N 次独立的 DB 加载+更新+提交合并为 1 次批量操作，
        显著减少数据库往返次数（从 N 次降为 1 次）。
        同时同步 working_memory 与 vector_store 运行时层。
        """
        if not memory_ids:
            return
        now = datetime.now(timezone.utc)
        with self.session_factory() as db:
            memories = (
                db.query(LongTermMemory)
                .filter(LongTermMemory.id.in_(memory_ids))
                .all()
            )
            for memory in memories:
                memory.access_count += 1
                memory.last_access = now
                memory.confidence = self._calculate_confidence(memory)
                memory.quality_score = self._calculate_quality_score(memory)
            db.commit()
            # 提交后同步运行时层（working_memory + vector_store），无需额外 DB 查询
            for memory in memories:
                db.refresh(memory)
                self._sync_runtime_layers(memory)

    def _search_memories_sync(
        self,
        query: str,
        limit: int,
        user_id: Optional[str] = None,
        include_archived: bool = False,
        include_deprecated: bool = False,
        workspace_id: str = "default",
    ) -> List[LongTermMemory]:
        """Spec memory-quality-and-short-term-recovery Task 9：
        基于 state 字段过滤检索结果。

        - ``deprecated`` 状态（用户主动遗忘）默认不返回，``include_deprecated=true`` 时返回
        - ``archived`` 状态（长期未访问或低质量）默认不返回，``include_archived=true`` 时返回
        - ``active`` / ``validated`` 状态始终返回

        兼容保留 ``archive_status != "archived"`` 过滤（旧字段，向 DB 中已有数据兼容）。
        """
        with self.session_factory() as db:
            db_query = db.query(LongTermMemory).filter(LongTermMemory.content.contains(query))
            if user_id is not None:
                db_query = db_query.filter(LongTermMemory.user_id == user_id)
            db_query = db_query.filter(LongTermMemory.workspace_id == workspace_id)
            if not include_archived:
                db_query = db_query.filter(LongTermMemory.archive_status != "archived")
                # Spec Task 9：state 字段同步过滤（archived 状态）
                db_query = db_query.filter(LongTermMemory.state != "archived")
            if not include_deprecated:
                # deprecated 状态（用户主动遗忘）默认不返回
                db_query = db_query.filter(LongTermMemory.state != "deprecated")
            results = (
                db_query.order_by(LongTermMemory.access_count.desc(), LongTermMemory.importance.desc())
                .limit(limit)
                .all()
            )
            for m in results:
                db.expunge(m)
            return results

    def _get_memories_by_ids_sync(
        self,
        memory_ids: List[int],
        user_id: Optional[str] = None,
        include_archived: bool = False,
        include_deprecated: bool = False,
        workspace_id: str = "default",
    ) -> List[LongTermMemory]:
        """Spec memory-quality-and-short-term-recovery Task 9：
        向量检索命中后从 DB 取记忆时同步按 state 过滤。

        - ``deprecated`` 默认排除（用户主动遗忘）
        - ``archived`` 默认排除（除非 ``include_archived=true``）
        """
        if not memory_ids:
            return []
        with self.session_factory() as db:
            query = db.query(LongTermMemory).filter(LongTermMemory.id.in_(memory_ids))
            if user_id is not None:
                query = query.filter(LongTermMemory.user_id == user_id)
            query = query.filter(LongTermMemory.workspace_id == workspace_id)
            if not include_archived:
                query = query.filter(LongTermMemory.archive_status != "archived")
                # Spec Task 9：state 字段同步过滤（archived 状态）
                query = query.filter(LongTermMemory.state != "archived")
            if not include_deprecated:
                query = query.filter(LongTermMemory.archive_status != "deprecated")
                query = query.filter(LongTermMemory.state != "deprecated")
            results = query.all()
            for m in results:
                db.expunge(m)
            return results

    async def get_memories_by_ids(
        self,
        memory_ids: List[int],
        user_id: Optional[str] = None,
        workspace_id: str = "default",
    ) -> List[LongTermMemory]:
        """按 ID 列表获取记忆（委托给读取器）。"""
        return await self._reader.get_memories_by_ids(memory_ids, user_id, workspace_id)

    async def search_memories(
        self,
        query: str,
        limit: int = 10,
        user_id: Optional[str] = None,
        include_archived: bool = False,
        include_deprecated: bool = False,
        use_vector: bool = True,
        keyword_weight: float = 0.35,
        vector_weight: float = 0.65,
        workspace_id: str = "default",
    ) -> List[LongTermMemory]:
        """混合检索长期记忆（委托给读取器，关键词 + 向量 + 重排）。"""
        return await self._reader.search_memories(
            query, limit, user_id, include_archived, include_deprecated,
            use_vector, keyword_weight, vector_weight, workspace_id,
        )

    async def auto_search_memories(
        self,
        query: str,
        workspace_id: str = "default",
        max_results: int = 5,
        min_score: float = 0.6,
        user_id: Optional[str] = None,
    ) -> list[dict]:
        """自动搜索相关记忆（委托给读取器）。"""
        return await self._reader.auto_search_memories(
            query, workspace_id, max_results, min_score, user_id,
        )

    def _delete_long_term_memory_sync(self, memory_id: int) -> bool:
        with self.session_factory() as db:
            memory = db.query(LongTermMemory).filter(LongTermMemory.id == memory_id).first()
            if memory:
                user_id = memory.user_id
                db.delete(memory)
                db.commit()
                self.working_memory.pop(str(memory_id), user_id=user_id)
                self.vector_store.delete_memory(memory_id)
                return True
        return False

    async def delete_long_term_memory(self, memory_id: int) -> bool:
        """删除长期记忆（委托给写入器）。"""
        return await self._writer.delete_long_term_memory(memory_id)

    def _archive_long_term_memory_sync(
        self,
        memory_id: int,
        archive_status: str = "deprecated",
    ) -> bool:
        """同步归档单条长期记忆。

        与 :meth:`delete_long_term_memory` 不同：归档保留 DB 行与向量数据，
        仅更新 ``archive_status`` 与 ``state`` 字段，使该记忆在后续
        ``search_memories`` / ``get_long_term_memories`` 等查询中被自动过滤
        （默认 ``archive_status != "archived"`` 且 ``state NOT IN
        ('archived','deprecated')``）。

        Spec memory-quality-and-short-term-recovery Task 9：
        - ``archive_status="deprecated"`` 时同步设置 ``state="deprecated"``
          （用户主动遗忘，保留审计痕迹，不再被检索返回）
        - ``archive_status="archived"`` 时同步设置 ``state="archived"``
          （长期未访问或低质量，默认不返回但 ``include_archived=true`` 时可检索）
        - ``archive_status="active"`` 时同步设置 ``state="active"``
          （恢复记忆用，从 archived/deprecated 恢复为活跃状态）

        Args:
            memory_id: 长期记忆 ID。
            archive_status: 归档状态值，支持 ``deprecated`` / ``archived`` / ``active``。

        Returns:
            ``True`` 表示归档成功，``False`` 表示记忆不存在或状态未变化。
        """
        # archive_status → state 映射（Spec memory-quality-and-short-term-recovery Task 9）
        # deprecated 与 archived 都映射到同名 state；active 也映射到 active（用于恢复）
        state_mapping = {
            "deprecated": "deprecated",
            "archived": "archived",
            "active": "active",
        }
        target_state = state_mapping.get(archive_status, archive_status)
        with self.session_factory() as db:
            memory = db.query(LongTermMemory).filter(
                LongTermMemory.id == memory_id
            ).first()
            if memory is None:
                return False
            if (
                memory.archive_status == archive_status
                and getattr(memory, "state", None) == target_state
            ):
                # 状态已是目标值，无需重复写入
                return True
            memory.archive_status = archive_status
            # Spec memory-quality-and-short-term-recovery Task 9：同步 state 字段
            # 保持与 archive_status 一致，便于检索层用 state 过滤
            memory.state = target_state
            # 先同步向量库元数据再提交 DB（fail-closed）：向量同步失败时抛错，
            # DB 不提交，归档状态保持不变，避免"DB 已归档、向量仍返回"的分叉
            self.vector_store.update_memory_metadata(
                memory_id,
                archive_status=archive_status,
                state=target_state,
            )
            db.commit()
            return True

    async def validate_long_term_memory(self, memory_id: int) -> bool:
        """用户确认记忆准确（委托给写入器）。"""
        return await self._writer.validate_long_term_memory(memory_id)

    def _validate_long_term_memory_sync(self, memory_id: int) -> bool:
        """同步晋升单条长期记忆为 validated 状态。"""
        with self.session_factory() as db:
            memory = db.query(LongTermMemory).filter(
                LongTermMemory.id == memory_id
            ).first()
            if memory is None:
                return False
            if getattr(memory, "state", None) == "validated":
                # 已是目标状态，无需重复写入
                return True
            memory.state = "validated"
            # validated 语义：用户确认后 confidence 提升至 0.9
            memory.confidence = max(0.9, float(memory.confidence or 0))
            memory.archive_status = "active"
            memory.last_access = self._ensure_aware_datetime(datetime.now(timezone.utc))
            # 先同步向量库元数据再提交 DB（fail-closed）：同步失败时抛错，
            # DB 不提交，验证状态保持不变
            self.vector_store.update_memory_metadata(
                memory_id,
                state="validated",
                archive_status="active",
                confidence=memory.confidence,
            )
            db.commit()
            return True

    async def archive_long_term_memory(
        self,
        memory_id: int,
        archive_status: str = "deprecated",
    ) -> bool:
        """归档单条长期记忆（委托给写入器）。"""
        return await self._writer.archive_long_term_memory(memory_id, archive_status)

    def _archive_memories_sync(
        self,
        user_id: Optional[str],
        older_than_days: int,
        importance_threshold: float,
        include_low_quality: bool,
        workspace_id: str = "default",
    ) -> int:
        """批量归档长期记忆。

        Spec memory-quality-and-short-term-recovery Task 9：
        批量归档同时更新 ``archive_status`` 与 ``state`` 字段，
        保持两字段一致性，便于检索层用任一字段过滤。
        """
        with self.session_factory() as db:
            query = db.query(LongTermMemory)
            if user_id is not None:
                query = query.filter(LongTermMemory.user_id == user_id)
            query = query.filter(LongTermMemory.workspace_id == workspace_id)
            query = query.filter(LongTermMemory.archive_status != "archived")

            archived_count = 0
            archive_ids: list[int] = []
            batch_size = 500
            for memory in query.yield_per(batch_size):
                memory.confidence = self._calculate_confidence(memory)
                memory.quality_score = self._calculate_quality_score(memory)
                if self._should_archive(
                    memory,
                    older_than_days=older_than_days,
                    importance_threshold=importance_threshold,
                    include_low_quality=include_low_quality,
                ):
                    memory.archive_status = "archived"
                    # Spec Task 9：同步 state 字段，保持与 archive_status 一致
                    memory.state = "archived"
                    archived_count += 1
                    archive_ids.append(memory.id)

                # 分批更新：先更新向量库，再提交 DB。
                # 若向量库失败则异常传播，DB 事务自动回滚，保证数据一致性。
                if len(archive_ids) >= batch_size:
                    for mid in archive_ids:
                        self.vector_store.update_memory_metadata(
                            mid, archive_status="archived", state="archived"
                        )
                    db.commit()
                    archive_ids.clear()

            # 处理剩余批次：同样先向量库后 DB
            for mid in archive_ids:
                self.vector_store.update_memory_metadata(
                    mid, archive_status="archived", state="archived"
                )
            db.commit()
            return archived_count

    async def archive_memories(
        self,
        user_id: Optional[str] = None,
        older_than_days: int = 30,
        importance_threshold: float = 0.3,
        include_low_quality: bool = True,
        workspace_id: str = "default",
    ) -> int:
        """批量归档长期记忆（委托给写入器）。"""
        return await self._writer.archive_memories(
            user_id, older_than_days, importance_threshold, include_low_quality, workspace_id,
        )

    async def evaluate_memory_quality(self, memory_id: int) -> Optional[Dict[str, Any]]:
        """评估记忆质量（委托给读取器）。"""
        return await self._reader.evaluate_memory_quality(memory_id)

    async def get_quality_report(
        self,
        user_id: Optional[str] = None,
        memory_id: Optional[int] = None,
        limit: int = 20,
        workspace_id: str = "default",
    ) -> List[Dict[str, Any]]:
        """获取记忆质量报告（委托给读取器）。"""
        return await self._reader.get_quality_report(user_id, memory_id, limit, workspace_id)

    async def get_memory_stats(self, user_id: Optional[str] = None, workspace_id: str = "default") -> Dict[str, Any]:
        """获取记忆统计信息（委托给读取器）。"""
        return await self._reader.get_memory_stats(user_id, workspace_id)

    def _consolidate_memories_sync(self) -> int:
        """
        兼容旧接口，内部复用当前归档策略整理低价值长期记忆。
        """
        return self._archive_memories_sync(
            user_id=None,
            older_than_days=30,
            importance_threshold=0.3,
            include_low_quality=True,
        )

    async def consolidate_memories(self) -> int:
        """整理记忆（委托给写入器）。"""
        return await self._writer.consolidate_memories()

    async def get_context_for_session(self, session_id: str, max_memories: int = 10) -> str:
        """获取会话上下文文本（委托给读取器）。"""
        return await self._reader.get_context_for_session(session_id, max_memories)
