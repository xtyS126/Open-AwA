"""
记忆管理内置工具。
提供 memory_remember / memory_recall / memory_forget / memory_list / memory_stats 五个工具，
允许 AI Agent 在工具调用环节直接操作用户的长期记忆系统。
"""

from __future__ import annotations

from typing import Any, Dict

from loguru import logger

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

    async def _remember(self, content: str, importance: float = 0.5, memory_layer: str = "auto", **_kwargs: Any) -> Dict[str, Any]:
        if not isinstance(content, str) or not content.strip():
            return {"success": False, "error": "缺少必填参数: content"}
        importance = max(0.0, min(1.0, float(importance or 0.5)))
        # 自动判断记忆层级
        if memory_layer == "auto":
            memory_layer = self._auto_detect_layer(content)
        manager = MemoryManager(SessionLocal)
        memory = await manager.add_long_term_memory(
            content=content.strip(),
            importance=importance,
            source_type="agent",
            memory_layer=memory_layer,
        )
        return {
            "success": True,
            "memory_id": memory.id,
            "memory_layer": memory_layer,
            "message": f"已记住 (id={memory.id}, layer={memory_layer}, importance={importance:.2f})",
        }

    async def _recall(self, query: str, limit: int = 5, memory_layers: list = None, **_kwargs: Any) -> Dict[str, Any]:
        if not isinstance(query, str) or not query.strip():
            return {"success": False, "error": "缺少必填参数: query"}
        limit = max(1, min(20, int(limit or 5)))
        manager = MemoryManager(SessionLocal)
        memories = await manager.search_memories(query=query.strip(), limit=limit)
        if not memories:
            return {"success": True, "memories": [], "message": "未找到相关记忆"}
        items = [
            {
                "id": m.id,
                "content": _truncate(m.content, 200),
                "importance": m.importance,
                "confidence": round(m.confidence, 4) if m.confidence else 0.0,
                "memory_layer": getattr(m, "memory_layer", "semantic"),
            }
            for m in memories
        ]
        return {"success": True, "memories": items, "count": len(items)}

    async def _forget(self, memory_id: int, **_kwargs: Any) -> Dict[str, Any]:
        try:
            memory_id = int(memory_id)
        except (TypeError, ValueError):
            return {"success": False, "error": "缺少必填参数: memory_id (需要整数)"}
        manager = MemoryManager(SessionLocal)
        # 标记为废弃而非删除，保留记忆数据用于后续分析
        archived = await manager.archive_long_term_memory(memory_id, archive_status="deprecated")
        if archived:
            return {"success": True, "message": f"已遗忘记忆 #{memory_id}（已归档）"}
        return {"success": False, "error": f"记忆不存在: {memory_id}"}

    async def _list(self, limit: int = 10, include_archived: bool = False, **_kwargs: Any) -> Dict[str, Any]:
        limit = max(1, min(50, int(limit or 10)))
        manager = MemoryManager(SessionLocal)
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

    async def _stats(self, **_kwargs: Any) -> Dict[str, Any]:
        manager = MemoryManager(SessionLocal)
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

    @staticmethod
    def _auto_detect_layer(content: str) -> str:
        """
        根据内容自动判断记忆层级。
        - core: 核心事实（用户身份、偏好、重要决策）
        - episodic: 情景记忆（具体事件、时间相关）
        - semantic: 语义知识（默认层级，通用知识）
        - working: 工作记忆（短期任务、临时信息）
        """
        content_lower = content.lower()
        # Core 核心记忆关键词
        core_keywords = [
            "我的名字", "我叫", "我是", "我的身份", "我的角色",
            "我的偏好", "我最喜欢", "我讨厌", "我的目标", "我的价值观",
            "我的 mbti", "我的性格", "我的技能", "我的职业",
        ]
        if any(kw in content_lower for kw in core_keywords):
            return "core"

        # Episodic 情景记忆关键词
        episodic_keywords = [
            "昨天", "今天", "上周", "上个月", "刚才", "刚刚",
            "发生", "经历", "事件", "回忆", "那次",
        ]
        if any(kw in content_lower for kw in episodic_keywords):
            return "episodic"

        # Working 工作记忆关键词
        working_keywords = [
            "当前任务", "正在进行", "现在在", "等一下", "稍后",
            "临时", "短期", "待办", "马上",
        ]
        if any(kw in content_lower for kw in working_keywords):
            return "working"

        return "semantic"
