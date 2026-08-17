"""
记忆写入器：负责短期记忆和长期记忆的写入、去重、PII 脱敏、合并、归档。
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from loguru import logger

if TYPE_CHECKING:
    from memory.manager import MemoryManager


class MemoryWriter:
    """记忆写入器：处理记忆的创建、更新、归档和删除。"""

    def __init__(self, manager: "MemoryManager"):
        self._manager = manager

    async def add_short_term_memory(
        self,
        session_id: str,
        role: str,
        content: str,
        user_id: Optional[str] = None,
        reasoning_content: Optional[str] = None,
        tool_events: Optional[list] = None,
        workspace_id: str = "default",
    ):
        """添加短期记忆。"""
        from db.models import ShortTermMemory

        memory = await asyncio.to_thread(
            self._manager._add_short_term_memory_sync,
            session_id, role, content, user_id, reasoning_content, tool_events, workspace_id,
        )
        logger.debug(f"Added short-term memory for session {session_id}")
        return memory

    async def append_to_last_assistant_memory(
        self,
        session_id: str,
        content: str,
        user_id: Optional[str] = None,
        reasoning_content: Optional[str] = None,
        tool_events: Optional[list] = None,
    ):
        """追加到最近一条助手短期记忆。"""
        from db.models import ShortTermMemory

        memory = await asyncio.to_thread(
            self._manager._append_to_last_assistant_memory_sync,
            session_id,
            content,
            user_id,
            reasoning_content,
            tool_events,
        )
        logger.debug(f"Appended assistant short-term memory for session {session_id}")
        return memory

    async def clear_short_term_memory(self, session_id: str, workspace_id: str = "default") -> int:
        """清空指定会话的短期记忆。"""
        count = await asyncio.to_thread(
            self._manager._clear_short_term_memory_sync, session_id, workspace_id
        )
        logger.info(f"Cleared {count} short-term memories for session {session_id}")
        return count

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
    ):
        """写入一条长期记忆，自动执行 PII 脱敏 + 去重合并。"""
        from db.models import LongTermMemory

        scrubbed_content, vector = await self._manager._scrub_and_embed(content, embedding)

        metadata = dict(memory_metadata or {})
        if images:
            metadata["images"] = [dict(img) for img in images if isinstance(img, dict)]

        merged = await self._manager._try_dedup_merge(
            scrubbed_content,
            vector,
            importance=importance,
            user_id=user_id,
            memory_metadata=metadata,
            source_type=source_type,
            workspace_id=workspace_id,
            extracted_from=extracted_from,
        )
        if merged is not None:
            return merged

        return await self._manager._write_new_memory(
            scrubbed_content,
            vector,
            importance=importance,
            user_id=user_id,
            memory_metadata=metadata,
            source_type=source_type,
            workspace_id=workspace_id,
            memory_layer=memory_layer,
            extracted_from=extracted_from,
        )

    async def delete_long_term_memory(self, memory_id: int) -> bool:
        """删除长期记忆。"""
        result = await asyncio.to_thread(self._manager._delete_long_term_memory_sync, memory_id)
        if result:
            logger.info(f"Deleted long-term memory {memory_id}")
        return result

    async def archive_long_term_memory(
        self,
        memory_id: int,
        archive_status: str = "deprecated",
    ) -> bool:
        """归档单条长期记忆。"""
        result = await asyncio.to_thread(
            self._manager._archive_long_term_memory_sync,
            memory_id,
            archive_status,
        )
        if result:
            logger.info(
                f"Archived long-term memory {memory_id} (status={archive_status})"
            )
        return result

    async def validate_long_term_memory(self, memory_id: int) -> bool:
        """用户确认单条长期记忆准确（状态晋升为 validated）。"""
        result = await asyncio.to_thread(
            self._manager._validate_long_term_memory_sync,
            memory_id,
        )
        if result:
            logger.info(f"Validated long-term memory {memory_id}")
        return result

    async def archive_memories(
        self,
        user_id: Optional[str] = None,
        older_than_days: int = 30,
        importance_threshold: float = 0.3,
        include_low_quality: bool = True,
        workspace_id: str = "default",
    ) -> int:
        """批量归档长期记忆。"""
        archived_count = await asyncio.to_thread(
            self._manager._archive_memories_sync,
            user_id,
            older_than_days,
            importance_threshold,
            include_low_quality,
            workspace_id,
        )
        logger.info(f"Archived {archived_count} long-term memories")
        return archived_count

    async def update_memory_access(self, memory_id: int) -> None:
        """更新记忆访问记录。"""
        await asyncio.to_thread(self._manager._update_memory_access_sync, memory_id)

    async def consolidate_memories(self) -> int:
        """整理记忆（兼容旧接口）。"""
        return await asyncio.to_thread(self._manager._consolidate_memories_sync)

    def set_llm_merge_callback(self, callback) -> None:
        """注入 LLM 合并回调。"""
        self._manager._llm_merge_callback = callback