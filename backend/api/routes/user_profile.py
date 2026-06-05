"""
用户画像 API 路由，提供画像提取、事实管理、统计查询和导出功能。
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from db.models import ProfileFact, ProfileExtractionLog, get_db
from api.dependencies import get_current_user
from plugins.user_profile_builtin.profile_extractor import ProfileExtractor
from plugins.user_profile_builtin.profile_lifecycle import ProfileLifecycle
from plugins.user_profile_builtin.profile_injector import ProfileInjector
from plugins.user_profile_builtin.profile_dimensions import PROFILE_CATEGORIES
from loguru import logger

router = APIRouter(prefix="/user/profile", tags=["用户画像"])


# ── Pydantic 模型 ──────────────────────────────────────────────

class ExtractRequest(BaseModel):
    """手动触发画像提取的请求"""
    session_ids: Optional[List[str]] = Field(None, description="要分析的会话 ID 列表")
    model_name: Optional[str] = Field("gpt-4o-mini", description="使用的 LLM 模型")


class ExtractResult(BaseModel):
    """画像提取结果"""
    extraction_id: str
    status: str
    message: str
    conversation_turns_analyzed: int
    behavior_logs_analyzed: int
    facts_added: int
    facts_updated: int
    facts_deleted: int
    facts_unchanged: int = 0
    model: str = ""
    duration_ms: int = 0


class FactUpdate(BaseModel):
    """手动编辑画像事实的请求"""
    fact_value: str = Field(..., description="新的事实值")
    category: Optional[str] = Field(None, description="画像维度分类")
    fact_key: Optional[str] = Field(None, description="事实键名")


class FactCreate(BaseModel):
    """手动添加画像事实的请求"""
    category: str = Field(..., description="画像维度分类")
    fact_key: str = Field(..., description="事实键名")
    fact_value: str = Field(..., description="事实值")
    confidence: float = Field(0.90, ge=0.0, le=1.0, description="置信度")


class FactResponse(BaseModel):
    """画像事实响应"""
    id: str
    category: str
    category_label: str
    fact_key: str
    fact_value: str
    confidence: float
    confidence_label: str
    source_type: str
    is_active: bool
    verification_count: int
    access_count: int
    first_observed_at: Optional[str]
    last_updated_at: Optional[str]
    source_session_id: Optional[str] = None

    class Config:
        from_attributes = True


class FactsListResponse(BaseModel):
    """画像事实列表响应"""
    facts: List[FactResponse]
    total: int
    categories: Dict[str, int]


class ProfileStatsResponse(BaseModel):
    """画像统计响应"""
    total_active_facts: int
    total_archived_facts: int
    category_distribution: Dict[str, int]
    confidence_distribution: Dict[str, int]
    source_distribution: Dict[str, int]
    dimensions_filled: int
    total_dimensions: int
    completeness_pct: float
    avg_confidence: float


class ProfileSummaryResponse(BaseModel):
    """画像摘要响应"""
    total_facts: int
    categories: Dict[str, Any]
    high_confidence_count: int
    medium_confidence_count: int
    low_confidence_count: int


class ExtractionLogResponse(BaseModel):
    """提取日志响应"""
    id: str
    trigger_type: str
    status: str
    conversation_turns_analyzed: int
    behavior_logs_analyzed: int
    facts_added: int
    facts_updated: int
    facts_deleted: int
    facts_unchanged: int
    llm_model_used: Optional[str]
    extraction_duration_ms: Optional[int]
    error_message: Optional[str]
    created_at: str

    class Config:
        from_attributes = True


# ── 辅助函数 ──────────────────────────────────────────────────

def _fact_to_response(fact: ProfileFact) -> FactResponse:
    """将 ORM 对象转换为响应模型"""
    cat_config = PROFILE_CATEGORIES.get(fact.category, {})
    from plugins.user_profile_builtin.profile_confidence import ConfidenceModel
    return FactResponse(
        id=fact.id,
        category=fact.category,
        category_label=cat_config.get("label", fact.category),
        fact_key=fact.fact_key,
        fact_value=fact.fact_value,
        confidence=fact.confidence,
        confidence_label=ConfidenceModel.get_confidence_label(fact.confidence),
        source_type=fact.source_type,
        is_active=fact.is_active,
        verification_count=fact.verification_count,
        access_count=fact.access_count,
        first_observed_at=fact.first_observed_at.isoformat() if fact.first_observed_at else None,
        last_updated_at=fact.last_updated_at.isoformat() if fact.last_updated_at else None,
        source_session_id=fact.source_session_id,
    )


# ── 画像提取 ──────────────────────────────────────────────────

@router.post("/extract", response_model=ExtractResult)
async def extract_profile(
    payload: ExtractRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    手动触发用户画像提取。
    分析用户的对话历史和行为日志，提取结构化的用户特征。
    """
    user_id = current_user.id
    extractor = ProfileExtractor(db, user_id)
    result = await extractor.extract(
        session_ids=payload.session_ids,
        trigger_type="manual",
        model_name=payload.model_name or "gpt-4o-mini",
    )
    return result


@router.post("/extract/auto", response_model=ExtractResult)
async def auto_extract_profile(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    自动检查并触发画像提取（由定时任务或对话后钩子调用）。
    仅在满足提取条件时执行。
    """
    from plugins.user_profile_builtin.profile_confidence import ConfidenceModel

    # 检查上次提取时间
    last_log = db.query(ProfileExtractionLog).filter(
        ProfileExtractionLog.user_id == current_user.id,
        ProfileExtractionLog.status == "success",
    ).order_by(ProfileExtractionLog.created_at.desc()).first()

    last_extraction_at = last_log.created_at if last_log else None

    should, reason = ConfidenceModel.should_extract(
        last_extraction_at=last_extraction_at,
        conversation_turns_since_last=10,  # 由调用方传入实际值
    )

    if not should:
        return ExtractResult(
            extraction_id="",
            status="skipped",
            message=reason,
            conversation_turns_analyzed=0,
            behavior_logs_analyzed=0,
            facts_added=0,
            facts_updated=0,
            facts_deleted=0,
        )

    extractor = ProfileExtractor(db, current_user.id)
    return await extractor.extract(trigger_type="auto")


# ── 画像事实 CRUD ──────────────────────────────────────────────

@router.get("/facts", response_model=FactsListResponse)
async def list_profile_facts(
    category: Optional[str] = Query(None, description="按类别筛选"),
    min_confidence: float = Query(0.0, ge=0.0, le=1.0, description="最低置信度"),
    active_only: bool = Query(True, description="仅显示活跃事实"),
    limit: int = Query(100, ge=1, le=500, description="返回条数"),
    offset: int = Query(0, ge=0, description="偏移量"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    获取当前用户的所有画像事实。
    支持按类别、置信度和活跃状态筛选，支持分页。
    """
    base_query = db.query(ProfileFact).filter(
        ProfileFact.user_id == current_user.id,
    )

    if active_only:
        base_query = base_query.filter(ProfileFact.is_active == True)
    if category:
        base_query = base_query.filter(ProfileFact.category == category)
    if min_confidence > 0:
        base_query = base_query.filter(ProfileFact.confidence >= min_confidence)

    total = base_query.count()

    facts = base_query.order_by(
        ProfileFact.confidence.desc()
    ).offset(offset).limit(limit).all()

    # 类别分布（基于与筛选条件一致的匹配结果，不含分页限制）
    category_counts: Dict[str, int] = {}
    all_matching = base_query.all()
    for f in all_matching:
        category_counts[f.category] = category_counts.get(f.category, 0) + 1

    return FactsListResponse(
        facts=[_fact_to_response(f) for f in facts],
        total=total,
        categories=category_counts,
    )


@router.get("/facts/{fact_id}", response_model=FactResponse)
async def get_profile_fact(
    fact_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    获取单个画像事实的详细信息。
    """
    fact = db.query(ProfileFact).filter(
        ProfileFact.id == fact_id,
        ProfileFact.user_id == current_user.id,
    ).first()

    if not fact:
        raise HTTPException(status_code=404, detail="画像事实不存在")

    return _fact_to_response(fact)


@router.put("/facts/{fact_id}", response_model=FactResponse)
async def update_profile_fact(
    fact_id: str,
    payload: FactUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    手动编辑画像事实。编辑后来源类型自动设为 manual。
    """
    fact = db.query(ProfileFact).filter(
        ProfileFact.id == fact_id,
        ProfileFact.user_id == current_user.id,
    ).first()

    if not fact:
        raise HTTPException(status_code=404, detail="画像事实不存在")

    fact.fact_value = payload.fact_value
    fact.source_type = "manual"
    fact.confidence = 0.90
    fact.last_updated_at = datetime.now(timezone.utc)

    if payload.category:
        fact.category = payload.category
    if payload.fact_key:
        fact.fact_key = payload.fact_key

    db.commit()
    logger.bind(
        user_id=current_user.id, fact_id=fact_id, category=fact.category
    ).info("用户手动编辑画像事实")

    return _fact_to_response(fact)


@router.post("/facts", response_model=FactResponse)
async def create_profile_fact(
    payload: FactCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    手动添加画像事实。
    """
    from plugins.user_profile_builtin.profile_confidence import generate_fact_id

    fact = ProfileFact(
        id=generate_fact_id(),
        user_id=current_user.id,
        category=payload.category,
        fact_key=payload.fact_key,
        fact_value=payload.fact_value,
        confidence=payload.confidence,
        source_type="manual",
        first_observed_at=datetime.now(timezone.utc),
        last_updated_at=datetime.now(timezone.utc),
    )
    db.add(fact)
    db.commit()

    logger.bind(
        user_id=current_user.id, fact_id=fact.id, category=fact.category
    ).info("用户手动添加画像事实")

    return _fact_to_response(fact)


@router.delete("/facts/{fact_id}")
async def delete_profile_fact(
    fact_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    删除画像事实（软删除，设置 is_active=False）。
    """
    fact = db.query(ProfileFact).filter(
        ProfileFact.id == fact_id,
        ProfileFact.user_id == current_user.id,
    ).first()

    if not fact:
        raise HTTPException(status_code=404, detail="画像事实不存在")

    fact.is_active = False
    fact.last_updated_at = datetime.now(timezone.utc)
    db.commit()

    logger.bind(
        user_id=current_user.id, fact_id=fact_id, category=fact.category
    ).info("用户删除画像事实")

    return {"message": "画像事实已删除", "fact_id": fact_id}


@router.post("/facts/{fact_id}/verify")
async def verify_profile_fact(
    fact_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    用户确认画像事实。提高置信度并增加验证计数。
    """
    lifecycle = ProfileLifecycle(db, current_user.id)
    result = lifecycle.enhance_fact(fact_id)
    return result


@router.post("/facts/{fact_id}/dispute")
async def dispute_profile_fact(
    fact_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    用户否定画像事实。降低置信度。
    """
    lifecycle = ProfileLifecycle(db, current_user.id)
    result = lifecycle.weaken_fact(fact_id)
    return result


# ── 全局操作 ──────────────────────────────────────────────────

@router.post("/refresh")
async def refresh_profile(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    全局刷新画像：重新计算所有事实的有效置信度，归档低于阈值的事实。
    """
    lifecycle = ProfileLifecycle(db, current_user.id)
    stats = lifecycle.refresh_all_facts()
    return {
        "message": "画像已刷新",
        "refreshed": stats["refreshed"],
        "archived": stats["archived"],
    }


@router.get("/summary", response_model=ProfileSummaryResponse)
async def get_profile_summary(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    获取画像摘要（用于前端仪表盘展示）。
    """
    injector = ProfileInjector(db, current_user.id)
    return injector.build_profile_summary()


@router.get("/context")
async def get_profile_context(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    获取 Agent 上下文注入用的画像文本（调试用）。
    """
    injector = ProfileInjector(db, current_user.id)
    context = injector.build_profile_context()
    return {
        "profile_context": context,
        "char_count": len(context),
    }


@router.get("/export")
async def export_profile(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    导出用户画像为 JSON（用于数据可移植性）。
    """
    facts = db.query(ProfileFact).filter(
        ProfileFact.user_id == current_user.id,
    ).all()

    return {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "user_id": current_user.id,
        "total_facts": len(facts),
        "facts": [
            {
                "category": f.category,
                "fact_key": f.fact_key,
                "fact_value": f.fact_value,
                "confidence": f.confidence,
                "source_type": f.source_type,
                "is_active": f.is_active,
                "first_observed_at": f.first_observed_at.isoformat() if f.first_observed_at else None,
                "last_updated_at": f.last_updated_at.isoformat() if f.last_updated_at else None,
            }
            for f in facts
        ],
    }


@router.delete("/purge")
async def purge_profile(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    清空所有画像数据（用户控制的"遗忘权"）。
    """
    facts = db.query(ProfileFact).filter(
        ProfileFact.user_id == current_user.id,
    ).all()

    count = len(facts)
    for f in facts:
        db.delete(f)

    # 同时删除提取日志
    logs = db.query(ProfileExtractionLog).filter(
        ProfileExtractionLog.user_id == current_user.id,
    ).all()
    for log in logs:
        db.delete(log)

    db.commit()

    logger.bind(
        user_id=current_user.id, deleted_facts=count
    ).info("用户清空所有画像数据")

    return {"message": f"已清空所有画像数据（{count} 条事实和关联日志）"}


# ── 统计与日志 ──────────────────────────────────────────────────

@router.get("/stats", response_model=ProfileStatsResponse)
async def get_profile_stats(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    获取画像统计数据：总量、分布、完整度等。
    """
    lifecycle = ProfileLifecycle(db, current_user.id)
    return lifecycle.get_stats()


@router.get("/extraction-logs")
async def get_extraction_logs(
    limit: int = Query(20, ge=1, le=100, description="返回条数"),
    offset: int = Query(0, ge=0, description="偏移量"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    获取画像提取历史日志。
    """
    total = db.query(ProfileExtractionLog).filter(
        ProfileExtractionLog.user_id == current_user.id,
    ).count()

    logs = db.query(ProfileExtractionLog).filter(
        ProfileExtractionLog.user_id == current_user.id,
    ).order_by(
        ProfileExtractionLog.created_at.desc()
    ).offset(offset).limit(limit).all()

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "logs": [
            {
                "id": log.id,
                "trigger_type": log.trigger_type,
                "status": log.status,
                "conversation_turns_analyzed": log.conversation_turns_analyzed,
                "behavior_logs_analyzed": log.behavior_logs_analyzed,
                "facts_added": log.facts_added,
                "facts_updated": log.facts_updated,
                "facts_deleted": log.facts_deleted,
                "facts_unchanged": log.facts_unchanged,
                "llm_model_used": log.llm_model_used,
                "extraction_duration_ms": log.extraction_duration_ms,
                "error_message": log.error_message,
                "created_at": log.created_at.isoformat() if log.created_at else None,
            }
            for log in logs
        ],
    }


@router.get("/dimensions")
async def get_profile_dimensions():
    """
    获取画像维度定义（用于前端渲染类别筛选器和表单）。
    """
    return {
        "categories": {
            key: {
                "label": config["label"],
                "description": config["description"],
                "priority": config["priority"],
                "fact_keys": config["fact_keys"],
            }
            for key, config in PROFILE_CATEGORIES.items()
        }
    }
