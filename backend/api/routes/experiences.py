"""
后端接口路由模块，负责接收请求、校验输入并协调业务层返回统一响应。
这些路由函数通常是前端或外部调用与后端内部能力之间的第一层行为边界。
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional, Any
from datetime import datetime, timezone
from db.models import get_db, ExperienceMemory, ExperienceExtractionLog
from api.dependencies import get_current_user
from api.schemas import (
    ExperienceCreate, ExperienceUpdate, ExperienceResponse,
    ExperienceExtractionRequest
)
from memory.experience_manager import ExperienceManager
import json

router = APIRouter(prefix="/experiences", tags=["Experience"])


def get_experience_manager(db: Session = Depends(get_db)) -> ExperienceManager:
    """
    获取experience、manager相关数据或当前状态。
    调用方通常依赖该结果继续进行后续判断、渲染或业务编排。
    """
    return ExperienceManager(db)


@router.get("", response_model=List[ExperienceResponse])
async def get_experiences(
    experience_type: Optional[str] = Query(None, description="经验类型筛选"),
    min_confidence: float = Query(0.0, ge=0.0, le=1.0, description="最低置信度"),
    source_task: Optional[str] = Query(None, description="来源任务筛选"),
    sort_by: str = Query("confidence", description="排序字段"),
    order: str = Query("desc", description="排序方向"),
    page: int = Query(1, ge=1, description="页码"),
    limit: int = Query(20, ge=1, le=100, description="每页数量"),
    manager: ExperienceManager = Depends(get_experience_manager),
    current_user = Depends(get_current_user)
):
    """
    获取experiences相关数据或当前状态。
    调用方通常依赖该结果继续进行后续判断、渲染或业务编排。
    """
    offset = (page - 1) * limit

    query = manager.db.query(ExperienceMemory).filter(
        ExperienceMemory.user_id == current_user.id
    )

    if experience_type:
        query = query.filter(ExperienceMemory.experience_type == experience_type)
    if min_confidence > 0:
        query = query.filter(ExperienceMemory.confidence >= min_confidence)
    if source_task:
        query = query.filter(ExperienceMemory.source_task == source_task)

    # 白名单校验排序字段，防止通过 getattr 访问内部属性
    ALLOWED_SORT_FIELDS = {"confidence", "created_at", "last_access", "title", "usage_count", "success_count"}
    if sort_by not in ALLOWED_SORT_FIELDS:
        sort_by = "confidence"
    sort_column = getattr(ExperienceMemory, sort_by)
    if order == "desc":
        query = query.order_by(sort_column.desc())
    else:
        query = query.order_by(sort_column)

    experiences = query.offset(offset).limit(limit).all()

    return experiences


@router.get("/{experience_id}", response_model=ExperienceResponse)
async def get_experience(
    experience_id: int,
    manager: ExperienceManager = Depends(get_experience_manager),
    current_user = Depends(get_current_user)
):
    """
    获取experience相关数据或当前状态。
    调用方通常依赖该结果继续进行后续判断、渲染或业务编排。
    """
    experience = manager.db.query(ExperienceMemory).filter(
        ExperienceMemory.id == experience_id,
        ExperienceMemory.user_id == current_user.id
    ).first()
    
    if not experience:
        raise HTTPException(status_code=404, detail="经验不存在")
    
    experience.usage_count += 1
    experience.last_access = datetime.now(timezone.utc)
    manager.db.commit()
    
    return experience


@router.post(
    "",
    response_model=ExperienceResponse,
    summary="创建经验",
    description="手动创建一条新的经验记录。"
)
async def create_experience(
    experience_data: ExperienceCreate,
    manager: ExperienceManager = Depends(get_experience_manager),
    current_user = Depends(get_current_user)
):
    """
    创建experience相关对象、记录或执行结果。
    实现过程中往往会涉及初始化、组装、持久化或返回统一结构。
    """
    experience = ExperienceMemory(
        experience_type=experience_data.experience_type,
        title=experience_data.title,
        content=experience_data.content,
        trigger_conditions=experience_data.trigger_conditions,
        confidence=experience_data.confidence,
        source_task=experience_data.source_task or "general",
        experience_metadata=json.dumps(experience_data.metadata or {}),
        user_id=current_user.id
    )
    
    manager.db.add(experience)
    manager.db.commit()
    manager.db.refresh(experience)
    
    return experience


@router.put(
    "/{experience_id}",
    response_model=ExperienceResponse,
    summary="更新经验",
    description="修改指定经验记录的内容、类型、置信度等字段。"
)
async def update_experience(
    experience_id: int,
    experience_data: ExperienceUpdate,
    manager: ExperienceManager = Depends(get_experience_manager),
    current_user = Depends(get_current_user)
):
    """
    更新experience相关数据、配置或状态。
    阅读时需要重点关注覆盖规则、副作用以及更新后的数据一致性。
    """
    experience = manager.db.query(ExperienceMemory).filter(
        ExperienceMemory.id == experience_id,
        ExperienceMemory.user_id == current_user.id
    ).first()
    
    if not experience:
        raise HTTPException(status_code=404, detail="经验不存在")
    
    update_data = experience_data.dict(exclude_unset=True)
    if 'metadata' in update_data and update_data['metadata']:
        update_data['experience_metadata'] = json.dumps(update_data['metadata'])
        del update_data['metadata']
    
    # 白名单限制可更新字段，防止通过 setattr 修改内部属性
    ALLOWED_UPDATE_FIELDS = {
        "title", "content", "confidence", "trigger_conditions",
        "experience_type", "source_task", "experience_metadata",
        "success_metrics",
    }
    for key, value in update_data.items():
        if key in ALLOWED_UPDATE_FIELDS:
            setattr(experience, key, value)
    
    manager.db.commit()
    manager.db.refresh(experience)
    
    return experience


@router.delete("/{experience_id}")
async def delete_experience(
    experience_id: int,
    manager: ExperienceManager = Depends(get_experience_manager),
    current_user = Depends(get_current_user)
):
    """
    删除experience相关对象或持久化记录。
    实现中通常还会同时处理资源释放、状态回收或关联数据清理。
    """
    experience = manager.db.query(ExperienceMemory).filter(
        ExperienceMemory.id == experience_id,
        ExperienceMemory.user_id == current_user.id
    ).first()
    
    if not experience:
        raise HTTPException(status_code=404, detail="经验不存在")
    
    manager.db.delete(experience)
    manager.db.commit()
    
    return {"message": "经验已删除"}


@router.post("/extract")
async def extract_experience(
    request: ExperienceExtractionRequest,
    manager: ExperienceManager = Depends(get_experience_manager),
    current_user = Depends(get_current_user)
):
    """
    处理extract、experience相关逻辑，并为调用方返回对应结果。
    阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
    """
    from skills.experience_extractor import ExperienceExtractor

    extractor = ExperienceExtractor()
    experience_data = await extractor.extract_from_session(
        user_goal=request.user_goal,
        execution_steps=request.execution_steps,
        final_result=request.final_result,
        status=request.status,
        session_id=request.session_id
    )

    if not experience_data:
        return {"status": "no_experience", "message": "未发现值得提取的经验"}

    log = ExperienceExtractionLog(
        session_id=request.session_id,
        task_summary=request.user_goal,
        extracted_experience=json.dumps(experience_data, ensure_ascii=False),
        extraction_trigger='manual',
        extraction_quality=experience_data['confidence'],
        user_id=current_user.id
    )
    manager.db.add(log)
    
    # 恢复双写机制：将提取的经验同时保存到数据库主表
    try:
        await manager.add_experience(
            experience_type=experience_data.get('experience_type', 'method'),
            title=experience_data.get('title', '未命名经验'),
            content=experience_data.get('content', ''),
            trigger_conditions=experience_data.get('trigger_conditions', ''),
            confidence=experience_data.get('confidence', 0.5),
            source_task='session_extraction',
            metadata={"session_id": request.session_id, "file": experience_data.get('save_result')},
            user_id=current_user.id
        )
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Failed to save extracted experience to DB: {e}")

    manager.db.commit()

    return {
        "status": "extracted",
        "experience": {
            "type": experience_data['experience_type'],
            "title": experience_data['title'],
            "confidence": experience_data['confidence'],
            "file": experience_data.get('save_result')
        }
    }



@router.get(
    "/search",
    summary="搜索经验",
    description="按关键词搜索与当前任务相关的经验记录。"
)
async def search_experiences(
    query: str = Query(..., description="搜索关键词"),
    experience_type: Optional[str] = Query(None, description="经验类型"),
    min_confidence: float = Query(0.3, ge=0.0, le=1.0, description="最低置信度"),
    limit: int = Query(10, ge=1, le=50, description="返回数量"),
    manager: ExperienceManager = Depends(get_experience_manager),
    current_user = Depends(get_current_user)
):
    """
    处理search、experiences相关逻辑，并为调用方返回对应结果。
    阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
    """
    experiences = await manager.search_experiences(
        query_text=query,
        experience_type=experience_type,
        min_confidence=min_confidence,
        limit=limit
    )
    
    experiences = [e for e in experiences if e.user_id == current_user.id]
    
    return {
        "count": len(experiences),
        "experiences": [
            {
                "id": e.id,
                "type": e.experience_type,
                "title": e.title,
                "confidence": e.confidence,
                "success_rate": e.success_count / e.usage_count if e.usage_count > 0 else 0
            }
            for e in experiences
        ]
    }


@router.get(
    "/stats/summary",
    summary="获取经验统计",
    description="返回当前用户经验库的数量、类型分布和平均指标。"
)
async def get_experience_stats(
    manager: ExperienceManager = Depends(get_experience_manager),
    current_user = Depends(get_current_user)
):
    """
    获取experience、stats相关数据或当前状态。
    调用方通常依赖该结果继续进行后续判断、渲染或业务编排。
    """
    user_experiences = manager.db.query(ExperienceMemory).filter(
        ExperienceMemory.user_id == current_user.id
    ).all()
    
    user_stats: dict[str, Any] = {
        'total_experiences': len(user_experiences),
        'type_distribution': {},
        'avg_confidence': sum(e.confidence for e in user_experiences) / len(user_experiences) if user_experiences else 0,
        'avg_success_rate': sum(e.success_count for e in user_experiences) / max(1, sum(e.usage_count for e in user_experiences))
    }
    
    for exp_type in ['strategy', 'method', 'error_pattern', 'tool_usage', 'context_handling']:
        user_stats['type_distribution'][exp_type] = len([
            e for e in user_experiences if e.experience_type == exp_type
        ])
    
    return user_stats


@router.get(
    "/logs",
    summary="获取经验提取日志",
    description="分页返回经验提取过程产生的日志记录。"
)
async def get_extraction_logs(
    page: int = Query(1, ge=1, description="页码"),
    limit: int = Query(20, ge=1, le=100, description="每页数量"),
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    获取extraction、logs相关数据或当前状态。
    调用方通常依赖该结果继续进行后续判断、渲染或业务编排。
    """
    offset = (page - 1) * limit
    
    logs = db.query(ExperienceExtractionLog).filter(
        ExperienceExtractionLog.user_id == current_user.id
    ).order_by(
        ExperienceExtractionLog.created_at.desc()
    ).offset(offset).limit(limit).all()
    
    return {
        "logs": [
            {
                "id": log.id,
                "session_id": log.session_id,
                "task_summary": log.task_summary,
                "trigger": log.extraction_trigger,
                "quality": log.extraction_quality,
                "reviewed": log.reviewed,
                "created_at": log.created_at
            }
            for log in logs
        ]
    }


@router.put("/{experience_id}/review")
async def review_experience(
    experience_id: int,
    approved: bool = Query(..., description="是否批准"),
    manager: ExperienceManager = Depends(get_experience_manager),
    current_user = Depends(get_current_user)
):
    """
    处理review、experience相关逻辑，并为调用方返回对应结果。
    阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
    """
    experience = manager.db.query(ExperienceMemory).filter(
        ExperienceMemory.id == experience_id,
        ExperienceMemory.user_id == current_user.id
    ).first()
    
    if not experience:
        raise HTTPException(status_code=404, detail="经验不存在")
    
    metadata = json.loads(experience.experience_metadata or '{}')
    metadata['reviewed'] = True
    metadata['approved'] = approved
    metadata['reviewed_at'] = datetime.now(timezone.utc).isoformat()
    experience.experience_metadata = json.dumps(metadata)
    
    if approved:
        experience.confidence = min(1.0, experience.confidence + 0.1)
    else:
        experience.confidence = max(0.0, experience.confidence - 0.2)
    
    manager.db.commit()
    
    return {
        "message": f"经验已{'批准' if approved else '拒绝'}",
        "new_confidence": experience.confidence
    }
