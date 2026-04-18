"""
记忆管理路由，提供短期/长期记忆 CRUD、混合检索、归档、质量评估与统计接口。
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from api.dependencies import get_current_user
from api.schemas import (
    LongTermMemoryCreate,
    LongTermMemoryResponse,
    MemoryArchiveRequest,
    MemoryQualityResponse,
    MemoryStatsResponse,
    MemoryVectorSearchRequest,
    ShortTermMemoryCreate,
    ShortTermMemoryResponse,
)
from db.models import ConversationRecord, LongTermMemory, ShortTermMemory, get_db
from memory.manager import MemoryManager


router = APIRouter(prefix="/memory", tags=["Memory"])


def get_memory_manager(db: Session = Depends(get_db)) -> MemoryManager:
    """
    为当前请求构建记忆管理器。
    """
    return MemoryManager(db)


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
    include_archived: bool = Query(False, description="是否包含已归档记忆"),
    manager: MemoryManager = Depends(get_memory_manager),
    current_user = Depends(get_current_user)
):
    memories = await manager.get_long_term_memories(
        limit=limit,
        offset=skip,
        user_id=str(current_user.id),
        include_archived=include_archived,
    )
    return memories


@router.post("/long-term", response_model=LongTermMemoryResponse)
async def add_long_term_memory(
    memory: LongTermMemoryCreate,
    manager: MemoryManager = Depends(get_memory_manager),
    current_user = Depends(get_current_user)
):
    return await manager.add_long_term_memory(
        user_id=str(current_user.id),
        content=memory.content,
        importance=memory.importance or 0.5,
        memory_metadata=memory.metadata or {},
        source_type=memory.source_type,
    )


@router.delete("/long-term/{memory_id}")
async def delete_long_term_memory(
    memory_id: int,
    manager: MemoryManager = Depends(get_memory_manager),
    current_user = Depends(get_current_user)
):
    memory = manager.db.query(LongTermMemory).filter(
        LongTermMemory.id == memory_id,
        LongTermMemory.user_id == str(current_user.id)
    ).first()
    if not memory:
        raise HTTPException(status_code=404, detail="Memory not found")

    await manager.delete_long_term_memory(memory_id)
    return {"message": "Memory deleted successfully"}


@router.get(
    "/search",
    summary="搜索长期记忆",
    description="根据关键词搜索长期记忆内容。"
)
async def search_memories(
    query: str,
    include_archived: bool = Query(False, description="是否包含已归档记忆"),
    manager: MemoryManager = Depends(get_memory_manager),
    current_user = Depends(get_current_user)
):
    return await manager.search_memories(
        query=query,
        user_id=str(current_user.id),
        include_archived=include_archived,
        use_vector=True,
    )


@router.post(
    "/vector-search",
    response_model=List[LongTermMemoryResponse],
    summary="向量混合搜索长期记忆",
    description="结合关键词匹配与向量相似度检索长期记忆。",
)
async def vector_search_memories(
    request: MemoryVectorSearchRequest,
    manager: MemoryManager = Depends(get_memory_manager),
    current_user = Depends(get_current_user),
):
    return await manager.search_memories(
        query=request.query,
        limit=request.limit,
        user_id=str(current_user.id),
        include_archived=request.include_archived,
        use_vector=True,
        keyword_weight=request.keyword_weight,
        vector_weight=request.vector_weight,
    )


@router.post(
    "/archive",
    summary="归档长期记忆",
    description="按时间、重要度和低质量规则归档长期记忆。",
)
async def archive_memories(
    request: MemoryArchiveRequest,
    manager: MemoryManager = Depends(get_memory_manager),
    current_user = Depends(get_current_user),
):
    archived_count = await manager.archive_memories(
        user_id=str(current_user.id),
        older_than_days=request.older_than_days,
        importance_threshold=request.importance_threshold,
        include_low_quality=request.include_low_quality,
    )
    return {"archived_count": archived_count}


@router.get(
    "/quality",
    response_model=List[MemoryQualityResponse],
    summary="获取记忆质量评估",
    description="查看单条或多条长期记忆的置信度、质量分和归档状态。",
)
async def get_memory_quality(
    memory_id: Optional[int] = Query(None, description="指定记忆 ID，留空时返回批量报告"),
    limit: int = Query(20, ge=1, le=100, description="批量报告数量"),
    manager: MemoryManager = Depends(get_memory_manager),
    current_user = Depends(get_current_user),
):
    return await manager.get_quality_report(
        user_id=str(current_user.id),
        memory_id=memory_id,
        limit=limit,
    )


@router.get(
    "/stats",
    response_model=MemoryStatsResponse,
    summary="获取增强记忆统计",
    description="返回长期记忆、工作内存与向量存储的综合统计信息。",
)
async def get_memory_stats(
    manager: MemoryManager = Depends(get_memory_manager),
    current_user = Depends(get_current_user),
):
    return await manager.get_memory_stats(user_id=str(current_user.id))
