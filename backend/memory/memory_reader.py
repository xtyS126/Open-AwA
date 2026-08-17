"""
记忆读取器：负责记忆检索、重排、缓存、批量访问更新。
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from loguru import logger

if TYPE_CHECKING:
    from memory.manager import MemoryManager
    from memory.memory_cache import MemoryCacheManager


class MemoryReader:
    """记忆读取器：处理记忆的检索和查询。"""

    def __init__(self, manager: "MemoryManager", cache_manager: "MemoryCacheManager"):
        self._manager = manager
        self._cache = cache_manager

    async def get_short_term_memories(
        self, session_id: str, limit: int = 50, workspace_id: str = "default"
    ):
        """从短期记忆中获取指定会话的历史消息（带 5 秒 TTL 缓存）。"""
        from db.models import ShortTermMemory

        cache_key: Tuple[str, int, str] = (session_id, limit, workspace_id)

        cached = self._cache.get_history_cache(cache_key)
        if cached is not None:
            logger.bind(
                event="history_cache_hit",
                module="memory",
                session_id=session_id,
            ).debug("对话历史缓存命中")
            return cached

        memories = await asyncio.to_thread(
            self._manager._get_short_term_memories_sync, session_id, limit, workspace_id
        )

        self._cache.set_history_cache(cache_key, memories)
        return memories

    async def get_recent_short_term_memories(
        self,
        user_id: str,
        limit: int = 20,
        workspace_id: str = "default",
    ):
        """获取用户最近 N 条短期记忆。"""
        from db.models import ShortTermMemory

        if not user_id:
            raise ValueError("user_id is required for get_recent_short_term_memories")
        limit = max(1, min(100, int(limit or 20)))
        return await asyncio.to_thread(
            self._manager._get_recent_short_term_memories_sync,
            user_id,
            limit,
            workspace_id,
        )

    async def search_short_term_memories(
        self,
        query: str,
        session_id: Optional[str] = None,
        limit: int = 10,
        workspace_id: str = "default",
    ):
        """按关键词模糊匹配短期记忆。"""
        from db.models import ShortTermMemory

        return await asyncio.to_thread(
            self._manager._search_short_term_memories_sync,
            query,
            session_id,
            limit,
            workspace_id,
        )

    async def get_long_term_memories(
        self,
        min_importance: float = 0.0,
        limit: int = 50,
        offset: int = 0,
        user_id: Optional[str] = None,
        include_archived: bool = False,
        include_deprecated: bool = False,
        workspace_id: str = "default",
    ):
        """获取长期记忆列表。"""
        from db.models import LongTermMemory

        return await asyncio.to_thread(
            self._manager._get_and_evaluate_long_term_memories_sync,
            min_importance,
            limit,
            offset,
            user_id,
            include_archived,
            include_deprecated,
            workspace_id,
        )

    async def get_memories_by_ids(
        self,
        memory_ids: List[int],
        user_id: Optional[str] = None,
        workspace_id: str = "default",
    ):
        """按输入顺序读取当前用户和工作区内仍可用的长期记忆。"""
        from db.models import LongTermMemory

        normalized_ids = list(dict.fromkeys(memory_ids))
        memories = await asyncio.to_thread(
            self._manager._get_memories_by_ids_sync,
            normalized_ids,
            user_id,
            False,
            False,
            workspace_id,
        )
        by_id = {int(memory.id): memory for memory in memories}
        return [by_id[memory_id] for memory_id in normalized_ids if memory_id in by_id]

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
    ):
        """混合检索长期记忆（关键词 + 向量 + 重排）。"""
        from db.models import LongTermMemory

        normalized_query = self._manager._normalize_search_query(query)
        if not normalized_query:
            return []

        keyword_matches = await asyncio.to_thread(
            self._manager._search_memories_sync,
            normalized_query,
            limit,
            user_id,
            include_archived,
            include_deprecated,
            workspace_id,
        )
        keyword_scores = {
            memory.id: min(1.0, 0.45 + (memory.importance * 0.3) + min(memory.access_count / 20, 0.25))
            for memory in keyword_matches
        }

        vector_scores: Dict[int, float] = {}
        if use_vector:
            if len(normalized_query) < self._manager._SHORT_QUERY_THRESHOLD:
                logger.debug(
                    f"Query too short ({len(normalized_query)} chars), skipping vector search"
                )
                vector_hits = []
            else:
                cache_key: Tuple[str, Optional[str]] = (normalized_query, user_id)
                cached_hits = self._cache.get_vector_cache(cache_key)
                if cached_hits is not None:
                    vector_hits = cached_hits
                else:
                    vector_hits = await self._manager.vector_store.search(
                        normalized_query,
                        user_id=user_id,
                        limit=limit,
                        include_archived=include_archived,
                    )
                    self._cache.set_vector_cache(cache_key, vector_hits)
            vector_scores = {hit.memory_id: hit.score for hit in vector_hits}

        candidate_ids = list(dict.fromkeys([*keyword_scores.keys(), *vector_scores.keys()]))
        if not candidate_ids:
            return []

        memories = await asyncio.to_thread(
            self._manager._get_memories_by_ids_sync,
            candidate_ids,
            user_id,
            include_archived,
            include_deprecated,
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
        rerank_candidate_limit = limit * 3
        ranked_memories = [memory for _, memory in combined[:rerank_candidate_limit]]
        if len(ranked_memories) > limit:
            ranked_memories = await self._manager._apply_rerank(
                normalized_query, ranked_memories, limit
            )
        if ranked_memories:
            await asyncio.to_thread(
                self._manager._batch_update_memory_access_sync,
                [m.id for m in ranked_memories],
            )
        return ranked_memories

    async def auto_search_memories(
        self,
        query: str,
        workspace_id: str = "default",
        max_results: int = 5,
        min_score: float = 0.6,
        user_id: Optional[str] = None,
    ) -> list[dict]:
        """自动搜索与当前对话相关的记忆。"""
        from db.models import LongTermMemory

        memories = await self.search_memories(
            query=query,
            limit=max_results * 2,
            user_id=user_id,
            workspace_id=workspace_id,
            use_vector=True,
        )

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

        results.sort(key=lambda x: x["importance"], reverse=True)
        return results[:max_results]

    async def evaluate_memory_quality(self, memory_id: int) -> Optional[Dict[str, Any]]:
        """评估单条记忆质量。"""
        from db.models import LongTermMemory

        def _do() -> Optional[Dict[str, Any]]:
            with self._manager.session_factory() as db:
                memory = db.query(LongTermMemory).filter(LongTermMemory.id == memory_id).first()
                if memory is None:
                    return None
                return self._manager._evaluate_memory_in_session(db, memory)
        return await asyncio.to_thread(_do)

    async def get_quality_report(
        self,
        user_id: Optional[str] = None,
        memory_id: Optional[int] = None,
        limit: int = 20,
        workspace_id: str = "default",
    ) -> List[Dict[str, Any]]:
        """获取记忆质量报告。"""
        from db.models import LongTermMemory

        def _do() -> List[Dict[str, Any]]:
            with self._manager.session_factory() as db:
                query = db.query(LongTermMemory)
                if user_id is not None:
                    query = query.filter(LongTermMemory.user_id == user_id)
                query = query.filter(LongTermMemory.workspace_id == workspace_id)
                if memory_id is not None:
                    query = query.filter(LongTermMemory.id == memory_id)
                memories = query.order_by(LongTermMemory.last_access.asc()).limit(limit).all()
                results = [self._manager._evaluate_memory_in_session(db, m, commit=False) for m in memories]
                db.commit()
                return results
        return await asyncio.to_thread(_do)

    async def get_memory_stats(self, user_id: Optional[str] = None, workspace_id: str = "default") -> Dict[str, Any]:
        """获取记忆统计信息。"""
        from sqlalchemy import func, case
        from db.models import LongTermMemory

        def _collect_stats() -> Dict[str, Any]:
            with self._manager.session_factory() as db:
                query = db.query(LongTermMemory)
                if user_id is not None:
                    query = query.filter(LongTermMemory.user_id == user_id)
                query = query.filter(LongTermMemory.workspace_id == workspace_id)
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
                'working_memory_count': self._manager.working_memory.stats(user_id).get('count', 0),
                'vector_store_count': await asyncio.to_thread(
                    self._manager.vector_store.count,
                    user_id=user_id,
                    include_archived=True,
                ),
                'embedding_provider': self._manager.vector_store.provider_name,
            }
        )
        return stats

    async def get_context_for_session(self, session_id: str, max_memories: int = 10) -> str:
        """获取会话上下文文本。"""
        short_term = await self.get_short_term_memories(session_id, limit=max_memories)
        context_parts = []
        for memory in reversed(short_term):
            role_marker = "User" if memory.role == "user" else "Assistant"
            context_parts.append(f"{role_marker}: {memory.content}")
        return "\n".join(context_parts)