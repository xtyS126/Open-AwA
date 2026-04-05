"""
记忆管理模块，负责短期记忆、长期记忆或经验数据的存储、检索与维护。
它是上下文连续性和经验复用能力的重要支撑层。
"""

from typing import List, Optional
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from db.models import ShortTermMemory, LongTermMemory
from loguru import logger


class MemoryManager:
    """
    封装与MemoryManager相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    def __init__(self, db: Session):
        """
        处理init相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        self.db = db
        logger.info("MemoryManager initialized")
    
    async def add_short_term_memory(
        self,
        session_id: str,
        role: str,
        content: str
    ) -> ShortTermMemory:
        """
        处理add、short、term、memory相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        memory = ShortTermMemory(
            session_id=session_id,
            role=role,
            content=content
        )
        self.db.add(memory)
        self.db.commit()
        self.db.refresh(memory)
        
        logger.debug(f"Added short-term memory for session {session_id}")
        return memory
    
    async def get_short_term_memories(
        self,
        session_id: str,
        limit: int = 50
    ) -> List[ShortTermMemory]:
        """
        获取short、term、memories相关数据或当前状态。
        调用方通常依赖该结果继续进行后续判断、渲染或业务编排。
        """
        memories = self.db.query(ShortTermMemory).filter(
            ShortTermMemory.session_id == session_id
        ).order_by(
            ShortTermMemory.timestamp.desc()
        ).limit(limit).all()
        
        return memories
    
    async def clear_short_term_memory(self, session_id: str) -> int:
        """
        处理clear、short、term、memory相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        count = self.db.query(ShortTermMemory).filter(
            ShortTermMemory.session_id == session_id
        ).delete()
        self.db.commit()
        
        logger.info(f"Cleared {count} short-term memories for session {session_id}")
        return count
    
    async def add_long_term_memory(
        self,
        content: str,
        importance: float = 0.5,
        embedding: Optional[str] = None
    ) -> LongTermMemory:
        """
        处理add、long、term、memory相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        memory = LongTermMemory(
            content=content,
            importance=importance,
            embedding=embedding
        )
        self.db.add(memory)
        self.db.commit()
        self.db.refresh(memory)
        
        logger.debug(f"Added long-term memory with importance {importance}")
        return memory
    
    async def get_long_term_memories(
        self,
        min_importance: float = 0.0,
        limit: int = 50
    ) -> List[LongTermMemory]:
        """
        获取long、term、memories相关数据或当前状态。
        调用方通常依赖该结果继续进行后续判断、渲染或业务编排。
        """
        memories = self.db.query(LongTermMemory).filter(
            LongTermMemory.importance >= min_importance
        ).order_by(
            LongTermMemory.importance.desc()
        ).limit(limit).all()
        
        return memories
    
    async def update_memory_access(self, memory_id: int) -> None:
        """
        更新memory、access相关数据、配置或状态。
        阅读时需要重点关注覆盖规则、副作用以及更新后的数据一致性。
        """
        memory = self.db.query(LongTermMemory).filter(
            LongTermMemory.id == memory_id
        ).first()
        
        if memory:
            memory.access_count += 1
            memory.last_access = datetime.now(timezone.utc)
            self.db.commit()
    
    async def search_memories(
        self,
        query: str,
        limit: int = 10
    ) -> List[LongTermMemory]:
        """
        处理search、memories相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        memories = self.db.query(LongTermMemory).filter(
            LongTermMemory.content.contains(query)
        ).order_by(
            LongTermMemory.access_count.desc()
        ).limit(limit).all()
        
        for memory in memories:
            await self.update_memory_access(memory.id)
        
        return memories
    
    async def delete_long_term_memory(self, memory_id: int) -> bool:
        """
        删除long、term、memory相关对象或持久化记录。
        实现中通常还会同时处理资源释放、状态回收或关联数据清理。
        """
        memory = self.db.query(LongTermMemory).filter(
            LongTermMemory.id == memory_id
        ).first()
        
        if memory:
            self.db.delete(memory)
            self.db.commit()
            logger.info(f"Deleted long-term memory {memory_id}")
            return True
        
        return False
    
    async def consolidate_memories(self) -> int:
        """
        处理consolidate、memories相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        all_memories = self.db.query(LongTermMemory).all()
        consolidated = 0
        
        for memory in all_memories:
            if memory.access_count < 2 and memory.importance < 0.3:
                self.db.delete(memory)
                consolidated += 1
        
        self.db.commit()
        
        logger.info(f"Consolidated {consolidated} low-importance memories")
        return consolidated
    
    async def get_context_for_session(
        self,
        session_id: str,
        max_memories: int = 10
    ) -> str:
        """
        获取context、for、session相关数据或当前状态。
        调用方通常依赖该结果继续进行后续判断、渲染或业务编排。
        """
        short_term = await self.get_short_term_memories(
            session_id, limit=max_memories
        )
        
        context_parts = []
        for memory in reversed(short_term):
            role_marker = "User" if memory.role == "user" else "Assistant"
            context_parts.append(f"{role_marker}: {memory.content}")
        
        return "\n".join(context_parts)
