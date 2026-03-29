from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from db.models import get_db, ShortTermMemory, LongTermMemory
from api.dependencies import get_current_user
from api.schemas import (
    ShortTermMemoryCreate, ShortTermMemoryResponse,
    LongTermMemoryCreate, LongTermMemoryResponse
)


router = APIRouter(prefix="/memory", tags=["Memory"])


@router.get("/short-term/{session_id}", response_model=List[ShortTermMemoryResponse])
async def get_short_term_memory(
    session_id: str,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    memories = db.query(ShortTermMemory).filter(
        ShortTermMemory.session_id == session_id
    ).order_by(ShortTermMemory.timestamp.desc()).limit(50).all()
    
    return memories


@router.post(
    "/short-term",
    response_model=ShortTermMemoryResponse,
    summary="新增短期记忆",
    description="向指定会话写入一条短期记忆记录。"
)
async def add_short_term_memory(
    memory: ShortTermMemoryCreate,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    new_memory = ShortTermMemory(
        session_id=memory.session_id,
        role=memory.role,
        content=memory.content
    )
    
    db.add(new_memory)
    db.commit()
    db.refresh(new_memory)
    
    return new_memory


@router.delete("/short-term/{memory_id}")
async def delete_short_term_memory(
    memory_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    memory = db.query(ShortTermMemory).filter(ShortTermMemory.id == memory_id).first()
    if not memory:
        raise HTTPException(status_code=404, detail="Memory not found")
    
    db.delete(memory)
    db.commit()
    
    return {"message": "Memory deleted successfully"}


@router.get(
    "/long-term",
    response_model=List[LongTermMemoryResponse],
    summary="获取长期记忆列表",
    description="按重要度返回长期记忆记录，支持分页参数。"
)
async def get_long_term_memories(
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    memories = db.query(LongTermMemory).order_by(
        LongTermMemory.importance.desc()
    ).offset(skip).limit(limit).all()
    
    return memories


@router.post("/long-term", response_model=LongTermMemoryResponse)
async def add_long_term_memory(
    memory: LongTermMemoryCreate,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    new_memory = LongTermMemory(
        content=memory.content,
        importance=memory.importance
    )
    
    db.add(new_memory)
    db.commit()
    db.refresh(new_memory)
    
    return new_memory


@router.delete("/long-term/{memory_id}")
async def delete_long_term_memory(
    memory_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    memory = db.query(LongTermMemory).filter(LongTermMemory.id == memory_id).first()
    if not memory:
        raise HTTPException(status_code=404, detail="Memory not found")
    
    db.delete(memory)
    db.commit()
    
    return {"message": "Memory deleted successfully"}


@router.get(
    "/search",
    summary="搜索长期记忆",
    description="根据关键词搜索长期记忆内容。"
)
async def search_memories(
    query: str,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    memories = db.query(LongTermMemory).filter(
        LongTermMemory.content.contains(query)
    ).all()
    
    return memories
