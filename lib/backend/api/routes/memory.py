"""
记忆管理路由，提供短期/长期记忆 CRUD、混合检索、归档、质量评估与统计接口。
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
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
from db.models import ConversationRecord, LongTermMemory, MemoryDecayConfig, ShortTermMemory, SessionLocal, User, get_db
from memory.manager import MemoryManager


router = APIRouter(prefix="/memory", tags=["Memory"])


def get_memory_manager() -> MemoryManager:
    """
    为当前请求构建记忆管理器。
    使用会话工厂而非请求级 Session，确保线程内部操作各自持有独立会话。
    """
    return MemoryManager(SessionLocal)


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


@router.get(
    "/short-term/recent",
    response_model=List[ShortTermMemoryResponse],
    summary="获取最近 N 条短期记忆（Spec memory-quality-and-short-term-recovery Task 14）",
    description="返回当前用户最近的短期记忆，用于新对话上下文恢复。"
)
async def get_recent_short_term_memories_endpoint(
    limit: int = Query(20, ge=1, le=100, description="返回数量上限，默认 20"),
    manager: MemoryManager = Depends(get_memory_manager),
    current_user: User = Depends(get_current_user),
    workspace_id: str = "default",
) -> List[Dict[str, Any]]:
    """
    Spec memory-quality-and-short-term-recovery Task 14：
    GET /api/memory/short-term/recent - 返回最近 N 条短期记忆。

    用于前端 useChatStream 在新对话开始时加载，注入上下文恢复。
    通过 JOIN ConversationRecord 实现按 user_id 过滤（ShortTermMemory 本身无 user_id）。

    注意：本路由必须在 /short-term/{session_id} 之前声明，
    否则 'recent' 会被当作 session_id 捕获。
    """
    return await manager.get_recent_short_term_memories(
        user_id=str(current_user.id),
        limit=limit,
        workspace_id=workspace_id,
    )


@router.get(
    "/short-term",
    response_model=List[ShortTermMemoryResponse],
    summary="按 session 分组返回短期记忆（Spec memory-quality-and-short-term-recovery Task 13）",
    description="返回当前用户的所有短期记忆，支持 session_id 过滤和关键词搜索。"
)
async def list_short_term_memories(
    limit: int = Query(50, ge=1, le=500, description="返回数量上限，默认 50"),
    session_id: Optional[str] = Query(None, description="按会话 ID 过滤"),
    query: Optional[str] = Query(None, description="按内容关键词模糊匹配"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    workspace_id: str = "default",
) -> List[Dict[str, Any]]:
    """
    Spec memory-quality-and-short-term-recovery Task 13：
    GET /api/memory/short-term - 按 session 分组返回短期记忆。

    实现策略：
    1. 通过 ConversationRecord JOIN 查询当前用户的所有短期记忆
       （ShortTermMemory 本身无 user_id 字段，需通过 session_id 关联）
    2. 支持按 session_id 过滤（验证所有权）
    3. 支持按 query 在 content 上做 LIKE 模糊匹配
    4. 按 timestamp 倒序返回

    前端拿到扁平列表后按 session_id 字段做分组展示。
    """
    # 子查询：当前用户的所有 session_id（去重）
    session_ids_subq = (
        db.query(ConversationRecord.session_id)
        .filter(ConversationRecord.user_id == str(current_user.id))
        .distinct()
        .subquery()
    )
    base_query = (
        db.query(ShortTermMemory)
        .join(
            session_ids_subq,
            ShortTermMemory.session_id == session_ids_subq.c.session_id,
        )
        .filter(ShortTermMemory.workspace_id == workspace_id)
    )
    if session_id:
        base_query = base_query.filter(ShortTermMemory.session_id == session_id)
    if query:
        # 使用 contains + autoescape 让 SQLAlchemy 自动转义 LIKE 特殊字符（%、_、\），
        # 避免关键词中包含通配符时破坏查询语义。
        # autoescape=True 会自动转义并设置 ESCAPE '\'，跨 SQLite/PostgreSQL 兼容。
        base_query = base_query.filter(
            ShortTermMemory.content.contains(query, autoescape=True)
        )
    memories = (
        base_query.order_by(
            ShortTermMemory.timestamp.desc(),
            ShortTermMemory.id.desc(),
        )
        .limit(limit)
        .all()
    )
    return memories


@router.get("/short-term/{session_id}", response_model=List[ShortTermMemoryResponse])
async def get_short_term_memory(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    workspace_id: str = "default",
) -> Dict[str, Any]:
    """
    获取短期记忆，先验证会话所有权并限制工作区范围。
    """
    has_session_record = _verify_session_ownership(db, session_id, current_user.id, allow_missing=True)
    if not has_session_record:
        return []
    memories = db.query(ShortTermMemory).filter(
        ShortTermMemory.session_id == session_id,
        ShortTermMemory.workspace_id == workspace_id,
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
    current_user: User = Depends(get_current_user),
    workspace_id: str = "default",
) -> Dict[str, Any]:
    """
    新增短期记忆，先验证会话所有权并绑定工作区。
    """
    _verify_session_ownership(db, memory.session_id, current_user.id, allow_missing=True)
    new_memory = ShortTermMemory(
        session_id=memory.session_id,
        role=memory.role,
        content=memory.content,
        workspace_id=workspace_id,
    )
    
    db.add(new_memory)
    db.commit()
    db.refresh(new_memory)
    
    return new_memory


@router.delete("/short-term/{memory_id}")
async def delete_short_term_memory(
    memory_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Dict[str, Any]:
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
    current_user: User = Depends(get_current_user)
) -> Dict[str, Any]:
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
    current_user: User = Depends(get_current_user)
) -> Dict[str, Any]:
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
    current_user: User = Depends(get_current_user)
) -> Dict[str, Any]:
    db = manager.session_factory()
    try:
        memory = db.query(LongTermMemory).filter(
            LongTermMemory.id == memory_id,
            LongTermMemory.user_id == str(current_user.id)
        ).first()
        if not memory:
            raise HTTPException(status_code=404, detail="Memory not found")
    finally:
        db.close()

    await manager.delete_long_term_memory(memory_id)
    return {"message": "Memory deleted successfully"}


@router.get(
    "/search",
    response_model=List[LongTermMemoryResponse],
    summary="搜索长期记忆",
    description="根据关键词搜索长期记忆内容，支持按记忆层级过滤。"
)
async def search_memories(
    query: str,
    include_archived: bool = Query(False, description="是否包含已归档记忆"),
    layer: Optional[str] = Query(None, description="记忆层级过滤：core（核心事实）/episodic（情景记忆）/semantic（语义知识）/working（工作记忆）"),
    manager: MemoryManager = Depends(get_memory_manager),
    current_user: User = Depends(get_current_user)
) -> List[LongTermMemoryResponse]:
    # 执行搜索，获取候选记忆列表（含关键词检索 + 向量检索的混合排序结果）
    results = await manager.search_memories(
        query=query,
        user_id=str(current_user.id),
        include_archived=include_archived,
        use_vector=True,
    )
    # 如果指定了层级过滤，按 memory_layer 字段筛选
    if layer:
        results = [m for m in results if getattr(m, 'memory_layer', None) == layer]
    return results


@router.post(
    "/vector-search",
    response_model=List[LongTermMemoryResponse],
    summary="向量混合搜索长期记忆",
    description="结合关键词匹配与向量相似度检索长期记忆。",
)
async def vector_search_memories(
    request: MemoryVectorSearchRequest,
    manager: MemoryManager = Depends(get_memory_manager),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
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
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
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
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    return await manager.get_quality_report(
        user_id=str(current_user.id),
        memory_id=memory_id,
        limit=limit,
    )


@router.get(
    "/stats",
    summary="获取增强记忆统计",
    description="返回长期记忆、工作内存、向量存储及分层记忆统计信息。",
)
async def get_memory_stats(
    manager: MemoryManager = Depends(get_memory_manager),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    # 获取基础统计数据
    base_stats = await manager.get_memory_stats(user_id=str(current_user.id))
    # 查询各记忆层级的计数
    layer_counts = (
        db.query(
            LongTermMemory.memory_layer,
            func.count(LongTermMemory.id).label("count"),
        )
        .filter(
            LongTermMemory.user_id == str(current_user.id),
            LongTermMemory.archive_status != "archived",
        )
        .group_by(LongTermMemory.memory_layer)
        .all()
    )
    # 构建层级统计，确保所有层级都有默认值
    layer_stats = {
        "core": 0,
        "episodic": 0,
        "semantic": 0,
        "working": 0,
    }
    for layer_name, count in layer_counts:
        if layer_name in layer_stats:
            layer_stats[layer_name] = count
    return {
        **base_stats,
        "layer_stats": layer_stats,
    }


# ── 记忆衰减配置请求模型 ──────────────────────────────────────────


class MemoryDecayConfigRequest(BaseModel):
    """记忆衰减配置请求体，按层级设置衰减参数。"""
    layer: str = Field(..., description="记忆层级：core/episodic/semantic/working")
    decay_function: str = Field(default="exponential", description="衰减函数：exponential/linear/none")
    half_life_days: int = Field(default=30, ge=1, le=3650, description="半衰期（天）")
    threshold: float = Field(default=0.1, ge=0.0, le=1.0, description="衰减阈值（低于此值归档）")
    enabled: bool = Field(default=True, description="是否启用衰减")


@router.put(
    "/decay-config",
    summary="配置记忆衰减参数",
    description="为指定记忆层级设置衰减函数、半衰期和阈值参数。",
)
async def update_decay_config(
    config: MemoryDecayConfigRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    # 查找或创建该层级的衰减配置
    existing = db.query(MemoryDecayConfig).filter(
        MemoryDecayConfig.layer == config.layer
    ).first()
    if existing:
        # 更新已有配置
        existing.decay_function = config.decay_function
        existing.half_life_days = config.half_life_days
        existing.threshold = config.threshold
        existing.enabled = config.enabled
    else:
        # 创建新配置
        existing = MemoryDecayConfig(
            layer=config.layer,
            decay_function=config.decay_function,
            half_life_days=config.half_life_days,
            threshold=config.threshold,
            enabled=config.enabled,
        )
        db.add(existing)
    db.commit()
    db.refresh(existing)
    return {
        "success": True,
        "data": {
            "layer": existing.layer,
            "decay_function": existing.decay_function,
            "half_life_days": existing.half_life_days,
            "threshold": existing.threshold,
            "enabled": existing.enabled,
        },
        "message": "衰减配置已更新",
    }
