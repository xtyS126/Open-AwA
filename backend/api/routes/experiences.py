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
    """获取ExperienceManager实例"""
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
    """获取经验列表"""
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

    sort_column = getattr(ExperienceMemory, sort_by, ExperienceMemory.confidence)
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
    """获取单个经验详情"""
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


@router.post("", response_model=ExperienceResponse)
async def create_experience(
    experience_data: ExperienceCreate,
    manager: ExperienceManager = Depends(get_experience_manager),
    current_user = Depends(get_current_user)
):
    """手动创建经验"""
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


@router.put("/{experience_id}", response_model=ExperienceResponse)
async def update_experience(
    experience_id: int,
    experience_data: ExperienceUpdate,
    manager: ExperienceManager = Depends(get_experience_manager),
    current_user = Depends(get_current_user)
):
    """更新经验"""
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
    
    for key, value in update_data.items():
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
    """删除经验"""
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
    """手动触发经验提取"""
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
    
    experience = await manager.add_experience(
        experience_type=experience_data['experience_type'],
        title=experience_data['title'],
        content=experience_data['content'],
        trigger_conditions=experience_data['trigger_conditions'],
        confidence=experience_data['confidence'],
        source_task=experience_data.get('source_task', 'general'),
        metadata=experience_data.get('metadata'),
        user_id=current_user.id
    )
    
    log = ExperienceExtractionLog(
        session_id=request.session_id,
        task_summary=request.user_goal,
        extracted_experience=json.dumps(experience_data),
        extraction_trigger='manual',
        extraction_quality=experience_data['confidence'],
        user_id=current_user.id
    )
    manager.db.add(log)
    manager.db.commit()
    
    return {
        "status": "extracted",
        "experience": {
            "id": experience.id,
            "type": experience.experience_type,
            "title": experience.title,
            "confidence": experience.confidence
        }
    }


@router.get("/search")
async def search_experiences(
    query: str = Query(..., description="搜索关键词"),
    experience_type: Optional[str] = Query(None, description="经验类型"),
    min_confidence: float = Query(0.3, ge=0.0, le=1.0, description="最低置信度"),
    limit: int = Query(10, ge=1, le=50, description="返回数量"),
    manager: ExperienceManager = Depends(get_experience_manager),
    current_user = Depends(get_current_user)
):
    """检索相关经验"""
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


@router.get("/stats/summary")
async def get_experience_stats(
    manager: ExperienceManager = Depends(get_experience_manager),
    current_user = Depends(get_current_user)
):
    """获取经验统计信息"""
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


@router.get("/logs")
async def get_extraction_logs(
    page: int = Query(1, ge=1, description="页码"),
    limit: int = Query(20, ge=1, le=100, description="每页数量"),
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取经验提取日志"""
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
    """审核经验"""
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
