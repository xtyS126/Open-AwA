"""
记忆管理内置工具。
提供 memory_remember / memory_recall / memory_forget / memory_list / memory_stats 五个工具，
允许 AI Agent 在工具调用环节直接操作用户的长期记忆系统。
"""

from __future__ import annotations

from typing import Any, Dict

from loguru import logger
from sqlalchemy.orm import Session

from db.models import SessionLocal
from memory.manager import MemoryManager


def _truncate(content: str, max_len: int) -> str:
    if len(content) <= max_len:
        return content
    return content[: max_len - 3] + "..."


class MemoryTools:
    """记忆管理工具类，对外暴露 execute(action, **params) 统一接口。"""

    def __init__(self):
        self.name = "memory_manager"
        self.description = "AI 记忆管理工具，提供长期记忆的增删查和统计能力"
        self.version = "1.0.0"

    async def initialize(self) -> None:
        pass

    def get_tools(self) -> list:
        return ["remember", "recall", "forget", "list", "stats"]

    def _get_db(self) -> Session:
        return SessionLocal()

    async def execute(self, action: str, **params: Any) -> Dict[str, Any]:
        action_map = {
            "remember": self._remember,
            "recall": self._recall,
            "forget": self._forget,
            "list": self._list,
            "stats": self._stats,
        }
        handler = action_map.get(action)
        if handler is None:
            return {"success": False, "error": f"未知记忆管理操作: {action}"}
        try:
            return await handler(**params)
        except Exception as exc:
            logger.bind(module="memory_tools", action=action).exception(
                f"memory_tools 执行失败: {exc}"
            )
            return {"success": False, "error": str(exc)}

    async def _remember(self, content: str, importance: float = 0.5, **_kwargs: Any) -> Dict[str, Any]:
        if not isinstance(content, str) or not content.strip():
            return {"success": False, "error": "缺少必填参数: content"}
        importance = max(0.0, min(1.0, float(importance or 0.5)))
        db = self._get_db()
        try:
            manager = MemoryManager(db)
            memory = await manager.add_long_term_memory(
                content=content.strip(),
                importance=importance,
                source_type="agent",
            )
            return {
                "success": True,
                "memory_id": memory.id,
                "message": f"已记住 (id={memory.id}, importance={importance:.2f})",
            }
        finally:
            db.close()

    async def _recall(self, query: str, limit: int = 5, **_kwargs: Any) -> Dict[str, Any]:
        if not isinstance(query, str) or not query.strip():
            return {"success": False, "error": "缺少必填参数: query"}
        limit = max(1, min(20, int(limit or 5)))
        db = self._get_db()
        try:
            manager = MemoryManager(db)
            memories = await manager.search_memories(query=query.strip(), limit=limit)
            if not memories:
                return {"success": True, "memories": [], "message": "未找到相关记忆"}
            items = [
                {
                    "id": m.id,
                    "content": _truncate(m.content, 200),
                    "importance": m.importance,
                    "confidence": round(m.confidence, 4) if m.confidence else 0.0,
                }
                for m in memories
            ]
            return {"success": True, "memories": items, "count": len(items)}
        finally:
            db.close()

    async def _forget(self, memory_id: int, **_kwargs: Any) -> Dict[str, Any]:
        try:
            memory_id = int(memory_id)
        except (TypeError, ValueError):
            return {"success": False, "error": "缺少必填参数: memory_id (需要整数)"}
        db = self._get_db()
        try:
            manager = MemoryManager(db)
            deleted = await manager.delete_long_term_memory(memory_id)
            if deleted:
                return {"success": True, "message": f"已遗忘记忆 #{memory_id}"}
            return {"success": False, "error": f"记忆不存在: {memory_id}"}
        finally:
            db.close()

    async def _list(self, limit: int = 10, include_archived: bool = False, **_kwargs: Any) -> Dict[str, Any]:
        limit = max(1, min(50, int(limit or 10)))
        db = self._get_db()
        try:
            manager = MemoryManager(db)
            memories = await manager.get_long_term_memories(
                min_importance=0.0,
                limit=limit,
                include_archived=include_archived,
            )
            if not memories:
                return {"success": True, "memories": [], "message": "暂无长期记忆"}
            items = [
                {
                    "id": m.id,
                    "content": _truncate(m.content, 100),
                    "importance": m.importance,
                    "created_at": m.created_at.isoformat() if m.created_at else "",
                    "archive_status": m.archive_status,
                }
                for m in memories
            ]
            return {"success": True, "memories": items, "count": len(items)}
        finally:
            db.close()

    async def _stats(self, **_kwargs: Any) -> Dict[str, Any]:
        db = self._get_db()
        try:
            manager = MemoryManager(db)
            stats = await manager.get_memory_stats()
            return {
                "success": True,
                "total_memories": stats["total_memories"],
                "active_memories": stats["active_memories"],
                "archived_memories": stats["archived_memories"],
                "average_confidence": stats["average_confidence"],
                "average_quality_score": stats["average_quality_score"],
                "total_access_count": stats["total_access_count"],
            }
        finally:
            db.close()
