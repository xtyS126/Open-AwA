"""
记忆管理模块，负责短期记忆、长期记忆、工作内存与向量检索能力的统一编排。
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Dict, List, Optional

from loguru import logger
from sqlalchemy import func, case

from db.models import LongTermMemory, ShortTermMemory
from core.conversation_sessions import ensure_conversation
from memory.vector_store_manager import VectorStoreManager
from memory.working_memory import working_memory_store


class MemoryManager:
    """
    记忆管理器。
    提供长期记忆的向量化写入、混合检索、质量评估、归档与统计功能。
    """

    _shared_vector_store: Optional[VectorStoreManager] = None
    _shared_vector_store_lock = Lock()

    def __init__(self, session_factory):
        # 使用会话工厂而非固定会话，确保每次线程内操作都使用独立短生命周期会话，避免 Session 被跨线程共享
        self.session_factory = session_factory
        if self.__class__._shared_vector_store is None:
            with self.__class__._shared_vector_store_lock:
                if self.__class__._shared_vector_store is None:
                    self.__class__._shared_vector_store = VectorStoreManager()
        self.vector_store = self.__class__._shared_vector_store
        self.working_memory = working_memory_store
        logger.info("MemoryManager initialized")

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
    ) -> float:
        reference_time = self._ensure_aware_datetime(reference_time or datetime.now(timezone.utc))
        last_access = self._ensure_aware_datetime(memory.last_access)
        days_since_access = max(0.0, (reference_time - last_access).total_seconds() / 86400)
        weeks_since_access = days_since_access / 7
        base_confidence = max(memory.confidence or 0.0, 0.35 + (memory.importance * 0.45))
        return max(0.0, min(1.0, base_confidence * (0.95 ** weeks_since_access)))

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

    def _sync_runtime_layers(self, memory: LongTermMemory) -> None:
        last_access = self._ensure_aware_datetime(memory.last_access)
        self.working_memory.put(str(memory.id), self._build_runtime_payload(memory), user_id=memory.user_id)
        self.vector_store.update_memory_metadata(
            memory.id,
            importance=memory.importance,
            archive_status=memory.archive_status,
            confidence=memory.confidence,
            quality_score=memory.quality_score,
            access_count=memory.access_count,
            last_access=last_access.isoformat(),
        )

    def _evaluate_memory_in_session(self, db, memory: LongTermMemory) -> Dict[str, Any]:
        """
        在调用方提供的 db 会话中原位评估记忆质量，不自行创建会话。
        要求 memory 对象已挂在该 db 会话上，确保 commit 有效。
        """
        reference_time = datetime.now(timezone.utc)
        memory.confidence = self._calculate_confidence(memory, reference_time=reference_time)
        memory.quality_score = self._calculate_quality_score(memory, reference_time=reference_time)
        if memory.archive_status != "archived" and self._should_archive(memory, reference_time=reference_time):
            memory.archive_status = "archived"
        db.commit()
        self._sync_runtime_layers(memory)
        return {
            "memory_id": memory.id,
            "confidence": round(memory.confidence, 4),
            "quality_score": round(memory.quality_score, 4),
            "archive_status": memory.archive_status,
            "importance": memory.importance,
            "access_count": memory.access_count,
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
        memory = await asyncio.to_thread(
            self._add_short_term_memory_sync,
            session_id, role, content, user_id, reasoning_content, tool_events, workspace_id,
        )
        logger.debug(f"Added short-term memory for session {session_id}")
        return memory

    def _append_to_last_assistant_memory_sync(
        self,
        session_id: str,
        content: str,
        user_id: Optional[str] = None,
        workspace_id: str = "default",
    ) -> ShortTermMemory:
        normalized_content = str(content or "").strip()
        if not normalized_content:
            raise ValueError("content cannot be empty")

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
                memory = ShortTermMemory(session_id=session_id, role="assistant", content=normalized_content, workspace_id=workspace_id)
                db.add(memory)
            else:
                previous_content = str(memory.content or "").strip()
                memory.content = (
                    f"{previous_content}\n\n{normalized_content}" if previous_content else normalized_content
                )
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
            db.refresh(memory)
            db.expunge(memory)
            return memory

    async def append_to_last_assistant_memory(
        self,
        session_id: str,
        content: str,
        user_id: Optional[str] = None,
    ) -> ShortTermMemory:
        memory = await asyncio.to_thread(self._append_to_last_assistant_memory_sync, session_id, content, user_id)
        logger.debug(f"Appended assistant short-term memory for session {session_id}")
        return memory

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
        return await asyncio.to_thread(self._get_short_term_memories_sync, session_id, limit, workspace_id)

    def _clear_short_term_memory_sync(self, session_id: str, workspace_id: str = "default") -> int:
        with self.session_factory() as db:
            count = db.query(ShortTermMemory).filter(
                ShortTermMemory.session_id == session_id,
                ShortTermMemory.workspace_id == workspace_id,
            ).delete()
            db.commit()
            return count

    async def clear_short_term_memory(self, session_id: str, workspace_id: str = "default") -> int:
        count = await asyncio.to_thread(self._clear_short_term_memory_sync, session_id, workspace_id)
        logger.info(f"Cleared {count} short-term memories for session {session_id}")
        return count

    def _add_long_term_memory_sync(
        self,
        content: str,
        importance: float,
        embedding: Optional[List[float]],
        user_id: Optional[str] = None,
        memory_metadata: Optional[Dict[str, Any]] = None,
        source_type: Optional[str] = None,
        workspace_id: str = "default",
    ) -> LongTermMemory:
        metadata = dict(memory_metadata or {})
        if source_type and "source_type" not in metadata:
            metadata["source_type"] = source_type
        now = datetime.now(timezone.utc)
        memory = LongTermMemory(
            content=content,
            importance=importance,
            embedding=embedding,
            user_id=user_id,
            workspace_id=workspace_id,
            created_at=now,
            last_access=now,
            confidence=max(0.35, min(1.0, 0.45 + (importance * 0.4))),
            archive_status="active",
            memory_metadata=metadata,
        )
        memory.quality_score = self._calculate_quality_score(memory, reference_time=now)
        with self.session_factory() as db:
            db.add(memory)
            db.commit()
            db.refresh(memory)
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
    ) -> LongTermMemory:
        vector = embedding
        if vector is None:
            vector = await asyncio.to_thread(self.vector_store.embedding_provider.embed_texts, [content])
            vector = vector[0]

        memory = await asyncio.to_thread(
            self._add_long_term_memory_sync,
            content,
            importance,
            vector,
            user_id,
            memory_metadata,
            source_type,
            workspace_id,
        )
        await asyncio.to_thread(
            self.vector_store.upsert_memory,
            memory.id,
            content,
            user_id=user_id,
            importance=importance,
            archive_status=memory.archive_status,
            metadata={
                **(memory.memory_metadata or {}),
                "confidence": memory.confidence,
                "quality_score": memory.quality_score,
                "access_count": memory.access_count,
                "last_access": memory.last_access.isoformat(),
            },
            embedding=vector,
        )
        self.working_memory.put(str(memory.id), self._build_runtime_payload(memory), user_id=user_id)
        logger.debug(f"Added long-term memory with importance {importance}")
        return memory

    def _get_and_evaluate_long_term_memories_sync(
        self,
        min_importance: float,
        limit: int,
        offset: int = 0,
        user_id: Optional[str] = None,
        include_archived: bool = False,
        workspace_id: str = "default",
    ) -> List[LongTermMemory]:
        """
        在同一会话内完成记忆加载与质量评估，避免跨会话传递 ORM 对象。
        """
        with self.session_factory() as db:
            query = db.query(LongTermMemory).filter(LongTermMemory.importance >= min_importance)
            if user_id is not None:
                query = query.filter(LongTermMemory.user_id == user_id)
            query = query.filter(LongTermMemory.workspace_id == workspace_id)
            if not include_archived:
                query = query.filter(LongTermMemory.archive_status != "archived")
            memories = (
                query.order_by(LongTermMemory.importance.desc(), LongTermMemory.quality_score.desc())
                .offset(offset)
                .limit(limit)
                .all()
            )
            for memory in memories:
                self._evaluate_memory_in_session(db, memory)
                db.expunge(memory)
            return memories

    async def get_long_term_memories(
        self,
        min_importance: float = 0.0,
        limit: int = 50,
        offset: int = 0,
        user_id: Optional[str] = None,
        include_archived: bool = False,
        workspace_id: str = "default",
    ) -> List[LongTermMemory]:
        # 加载与评估合并在同一个同步函数内，避免跨线程传递 ORM 对象
        return await asyncio.to_thread(
            self._get_and_evaluate_long_term_memories_sync,
            min_importance,
            limit,
            offset,
            user_id,
            include_archived,
            workspace_id,
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
        await asyncio.to_thread(self._update_memory_access_sync, memory_id)

    def _search_memories_sync(
        self,
        query: str,
        limit: int,
        user_id: Optional[str] = None,
        include_archived: bool = False,
        workspace_id: str = "default",
    ) -> List[LongTermMemory]:
        with self.session_factory() as db:
            db_query = db.query(LongTermMemory).filter(LongTermMemory.content.contains(query))
            if user_id is not None:
                db_query = db_query.filter(LongTermMemory.user_id == user_id)
            db_query = db_query.filter(LongTermMemory.workspace_id == workspace_id)
            if not include_archived:
                db_query = db_query.filter(LongTermMemory.archive_status != "archived")
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
        workspace_id: str = "default",
    ) -> List[LongTermMemory]:
        if not memory_ids:
            return []
        with self.session_factory() as db:
            query = db.query(LongTermMemory).filter(LongTermMemory.id.in_(memory_ids))
            if user_id is not None:
                query = query.filter(LongTermMemory.user_id == user_id)
            query = query.filter(LongTermMemory.workspace_id == workspace_id)
            if not include_archived:
                query = query.filter(LongTermMemory.archive_status != "archived")
            results = query.all()
            for m in results:
                db.expunge(m)
            return results

    async def search_memories(
        self,
        query: str,
        limit: int = 10,
        user_id: Optional[str] = None,
        include_archived: bool = False,
        use_vector: bool = True,
        keyword_weight: float = 0.35,
        vector_weight: float = 0.65,
        workspace_id: str = "default",
    ) -> List[LongTermMemory]:
        keyword_matches = await asyncio.to_thread(
            self._search_memories_sync,
            query,
            limit,
            user_id,
            include_archived,
            workspace_id,
        )
        keyword_scores = {
            memory.id: min(1.0, 0.45 + (memory.importance * 0.3) + min(memory.access_count / 20, 0.25))
            for memory in keyword_matches
        }

        vector_scores: Dict[int, float] = {}
        if use_vector:
            vector_hits = await asyncio.to_thread(
                self.vector_store.search,
                query,
                user_id=user_id,
                limit=limit,
                include_archived=include_archived,
            )
            vector_scores = {hit.memory_id: hit.score for hit in vector_hits}

        candidate_ids = list(dict.fromkeys([*keyword_scores.keys(), *vector_scores.keys()]))
        if not candidate_ids:
            return []

        memories = await asyncio.to_thread(
            self._get_memories_by_ids_sync,
            candidate_ids,
            user_id,
            include_archived,
            workspace_id,
        )
        combined = []
        for memory in memories:
            combined_score = (keyword_scores.get(memory.id, 0.0) * keyword_weight) + (
                vector_scores.get(memory.id, 0.0) * vector_weight
            )
            combined.append((combined_score, memory))

        combined.sort(
            key=lambda item: (item[0], item[1].quality_score, item[1].importance, item[1].access_count),
            reverse=True,
        )
        ranked_memories = [memory for _, memory in combined[:limit]]
        for memory in ranked_memories:
            await self.update_memory_access(memory.id)
        return ranked_memories

    async def auto_search_memories(
        self,
        query: str,
        workspace_id: str = "default",
        max_results: int = 5,
        min_score: float = 0.6,
        user_id: Optional[str] = None,
    ) -> list[dict]:
        """
        自动搜索与当前对话相关的记忆（每次对话自动调用）。
        返回经过分数筛选的相关记忆条目。

        Args:
            query: 搜索查询（通常是用户当前消息）
            workspace_id: 工作区 ID
            max_results: 最大返回数量
            min_score: 最低相关性分数阈值
            user_id: 用户 ID

        Returns:
            相关记忆列表，每项包含 content 和相关度分数
        """
        try:
            memories = await self.search_memories(
                query=query,
                limit=max_results * 2,  # 多取一些用于筛选
                user_id=user_id,
                workspace_id=workspace_id,
                use_vector=True,
            )

            # 筛选高相关度记忆（仅按 min_score 过滤，取前 max_results）
            results = []
            for m in memories:
                if m.importance >= min_score:
                    results.append({
                        "id": m.id,
                        "content": m.content[:500],
                        "importance": m.importance,
                        "access_count": m.access_count,
                        "created_at": str(m.created_at) if m.created_at else "",
                        "type": m.type or "fact",
                    })

            # 按重要度排序，取前 max_results
            results.sort(key=lambda x: x["importance"], reverse=True)
            return results[:max_results]

        except Exception as e:
            logger.bind(event="auto_memory_search_error").warning(f"自动记忆搜索失败: {str(e)}")
            return []

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
        result = await asyncio.to_thread(self._delete_long_term_memory_sync, memory_id)
        if result:
            logger.info(f"Deleted long-term memory {memory_id}")
        return result

    def _archive_memories_sync(
        self,
        user_id: Optional[str],
        older_than_days: int,
        importance_threshold: float,
        include_low_quality: bool,
        workspace_id: str = "default",
    ) -> int:
        with self.session_factory() as db:
            query = db.query(LongTermMemory)
            if user_id is not None:
                query = query.filter(LongTermMemory.user_id == user_id)
            query = query.filter(LongTermMemory.workspace_id == workspace_id)
            query = query.filter(LongTermMemory.archive_status != "archived")

            archived_count = 0
            # 使用 yield_per 分批加载，避免一次性将所有记忆加载到内存导致 OOM
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
                    archived_count += 1
                    self.vector_store.update_memory_metadata(memory.id, archive_status="archived")

                # 分批提交，避免单次事务过大
                if archived_count > 0 and archived_count % batch_size == 0:
                    db.commit()

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
        archived_count = await asyncio.to_thread(
            self._archive_memories_sync,
            user_id,
            older_than_days,
            importance_threshold,
            include_low_quality,
            workspace_id,
        )
        logger.info(f"Archived {archived_count} long-term memories")
        return archived_count

    async def evaluate_memory_quality(self, memory_id: int) -> Optional[Dict[str, Any]]:
        def _do() -> Optional[Dict[str, Any]]:
            with self.session_factory() as db:
                memory = db.query(LongTermMemory).filter(LongTermMemory.id == memory_id).first()
                if memory is None:
                    return None
                return self._evaluate_memory_in_session(db, memory)
        return await asyncio.to_thread(_do)

    async def get_quality_report(
        self,
        user_id: Optional[str] = None,
        memory_id: Optional[int] = None,
        limit: int = 20,
        workspace_id: str = "default",
    ) -> List[Dict[str, Any]]:
        def _do() -> List[Dict[str, Any]]:
            with self.session_factory() as db:
                query = db.query(LongTermMemory)
                if user_id is not None:
                    query = query.filter(LongTermMemory.user_id == user_id)
                query = query.filter(LongTermMemory.workspace_id == workspace_id)
                if memory_id is not None:
                    query = query.filter(LongTermMemory.id == memory_id)
                memories = query.order_by(LongTermMemory.last_access.asc()).limit(limit).all()
                return [self._evaluate_memory_in_session(db, m) for m in memories]
        return await asyncio.to_thread(_do)

    async def get_memory_stats(self, user_id: Optional[str] = None, workspace_id: str = "default") -> Dict[str, Any]:
        def _collect_stats() -> Dict[str, Any]:
            with self.session_factory() as db:
                query = db.query(LongTermMemory)
                if user_id is not None:
                    query = query.filter(LongTermMemory.user_id == user_id)
                query = query.filter(LongTermMemory.workspace_id == workspace_id)
                # 使用 SQL 聚合查询替代全量加载 + Python 循环，避免大量数据导致 OOM。
                # COUNT + CASE WHEN 计算 active/archived 数量，SUM/AVG 计算聚合值。
                stats_row = (
                    db.query(
                        func.count(LongTermMemory.id).label("total"),
                        func.sum(
                            case((LongTermMemory.archive_status != "archived", 1), else_=0)
                        ).label("active"),
                        func.sum(
                            case((LongTermMemory.archive_status == "archived", 1), else_=0)
                        ).label("archived"),
                        func.coalesce(func.sum(LongTermMemory.access_count), 0).label("total_access"),
                        func.coalesce(func.avg(LongTermMemory.confidence), 0.0).label("avg_confidence"),
                        func.coalesce(func.avg(LongTermMemory.quality_score), 0.0).label("avg_quality"),
                    )
                    .filter(LongTermMemory.workspace_id == workspace_id)
                )
                if user_id is not None:
                    stats_row = stats_row.filter(LongTermMemory.user_id == user_id)
                row = stats_row.first()
                return {
                    'total_memories': row.total,
                    'active_memories': row.active or 0,
                    'archived_memories': row.archived or 0,
                    'average_confidence': round(row.avg_confidence or 0.0, 4),
                    'average_quality_score': round(row.avg_quality or 0.0, 4),
                    'total_access_count': row.total_access or 0,
                }

        stats = await asyncio.to_thread(_collect_stats)
        stats.update(
            {
                'working_memory_count': self.working_memory.stats(user_id).get('count', 0),
                'vector_store_count': await asyncio.to_thread(
                    self.vector_store.count,
                    user_id=user_id,
                    include_archived=True,
                ),
                'embedding_provider': self.vector_store.provider_name,
            }
        )
        return stats

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
        return await asyncio.to_thread(self._consolidate_memories_sync)

    async def get_context_for_session(self, session_id: str, max_memories: int = 10) -> str:
        short_term = await self.get_short_term_memories(session_id, limit=max_memories)
        context_parts = []
        for memory in reversed(short_term):
            role_marker = "User" if memory.role == "user" else "Assistant"
            context_parts.append(f"{role_marker}: {memory.content}")
        return "\n".join(context_parts)
