from typing import List, Dict, Any, Optional
from datetime import datetime
from sqlalchemy.orm import Session
from db.models import ShortTermMemory, LongTermMemory
from loguru import logger


class MemoryManager:
    def __init__(self, db: Session):
        self.db = db
        logger.info("MemoryManager initialized")
    
    async def add_short_term_memory(
        self,
        session_id: str,
        role: str,
        content: str
    ) -> ShortTermMemory:
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
        memories = self.db.query(ShortTermMemory).filter(
            ShortTermMemory.session_id == session_id
        ).order_by(
            ShortTermMemory.timestamp.desc()
        ).limit(limit).all()
        
        return memories
    
    async def clear_short_term_memory(self, session_id: str) -> int:
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
        memories = self.db.query(LongTermMemory).filter(
            LongTermMemory.importance >= min_importance
        ).order_by(
            LongTermMemory.importance.desc()
        ).limit(limit).all()
        
        return memories
    
    async def update_memory_access(self, memory_id: int) -> None:
        memory = self.db.query(LongTermMemory).filter(
            LongTermMemory.id == memory_id
        ).first()
        
        if memory:
            memory.access_count += 1
            memory.last_access = datetime.utcnow()
            self.db.commit()
    
    async def search_memories(
        self,
        query: str,
        limit: int = 10
    ) -> List[LongTermMemory]:
        memories = self.db.query(LongTermMemory).filter(
            LongTermMemory.content.contains(query)
        ).order_by(
            LongTermMemory.access_count.desc()
        ).limit(limit).all()
        
        for memory in memories:
            await self.update_memory_access(memory.id)
        
        return memories
    
    async def delete_long_term_memory(self, memory_id: int) -> bool:
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
        short_term = await self.get_short_term_memories(
            session_id, limit=max_memories
        )
        
        context_parts = []
        for memory in reversed(short_term):
            role_marker = "User" if memory.role == "user" else "Assistant"
            context_parts.append(f"{role_marker}: {memory.content}")
        
        return "\n".join(context_parts)
