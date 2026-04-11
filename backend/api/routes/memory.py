"""
后端接口路由模块，负责接收请求、校验输入并协调业务层返回统一响应。
这些路由函数通常是前端或外部调用与后端内部能力之间的第一层行为边界。
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from db.models import get_db, ShortTermMemory, LongTermMemory, ConversationRecord
from api.dependencies import get_current_user
from api.schemas import (
    ShortTermMemoryCreate, ShortTermMemoryResponse,
    LongTermMemoryCreate, LongTermMemoryResponse
)


router = APIRouter(prefix="/memory", tags=["Memory"])


def _verify_session_ownership(db: Session, session_id: str, user_id: str, allow_missing: bool = False) -> bool:
    """
    验证会话是否属于当前用户。
    通过 ConversationRecord 表的 user_id 字段判断会话owner。
    如果会话尚未建立且允许缺失，则返回 False，便于前端读取空会话。
    如果会话存在但不属于当前用户，则抛出 403 异常。
    """
    record = db.query(ConversationRecord).filter(
        ConversationRecord.session_id == session_id
    ).order_by(ConversationRecord.timestamp.desc()).first()
    if not record:
        if allow_missing:
            return False
        raise HTTPException(status_code=404, detail="Session not found")
    if record.user_id != user_id:
        raise HTTPException(status_code=403, detail="Access denied: session does not belong to current user")
    return True


@router.get("/short-term/{session_id}", response_model=List[ShortTermMemoryResponse])
async def get_short_term_memory(
    session_id: str,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    获取短期记忆，先验证会话所有权。
    只有会话属于当前用户时才允许访问。
    """
    has_session_record = _verify_session_ownership(db, session_id, current_user.id, allow_missing=True)
    if not has_session_record:
        return []
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
    """
    新增短期记忆，先验证会话所有权。
    只有会话属于当前用户时才允许写入。
    """
    _verify_session_ownership(db, memory.session_id, current_user.id, allow_missing=True)
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
    """
    删除短期记忆，先验证该记忆所属会话是否属于当前用户。
    防止越权删除其他用户的记忆。
    """
    memory = db.query(ShortTermMemory).filter(ShortTermMemory.id == memory_id).first()
    if not memory:
        raise HTTPException(status_code=404, detail="Memory not found")
    
    # 验证记忆所属会话的所有权
    _verify_session_ownership(db, memory.session_id, current_user.id)
    
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
    """
    获取long、term、memories相关数据或当前状态。
    调用方通常依赖该结果继续进行后续判断、渲染或业务编排。
    """
    memories = db.query(LongTermMemory).filter(
        LongTermMemory.user_id == str(current_user.id)
    ).order_by(
        LongTermMemory.importance.desc()
    ).offset(skip).limit(limit).all()
    
    return memories


@router.post("/long-term", response_model=LongTermMemoryResponse)
async def add_long_term_memory(
    memory: LongTermMemoryCreate,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    处理add、long、term、memory相关逻辑，并为调用方返回对应结果。
    阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
    """
    new_memory = LongTermMemory(
        user_id=str(current_user.id),
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
    """
    删除long、term、memory相关对象或持久化记录。
    实现中通常还会同时处理资源释放、状态回收或关联数据清理。
    """
    memory = db.query(LongTermMemory).filter(
        LongTermMemory.id == memory_id,
        LongTermMemory.user_id == str(current_user.id)
    ).first()
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
    """
    处理search、memories相关逻辑，并为调用方返回对应结果。
    阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
    """
    memories = db.query(LongTermMemory).filter(
        LongTermMemory.user_id == str(current_user.id),
        LongTermMemory.content.contains(query)
    ).all()
    
    return memories
