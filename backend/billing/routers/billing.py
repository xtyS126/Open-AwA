"""
计费与用量管理模块，负责价格配置、预算控制、用量追踪与报表能力。
这一部分直接关联成本核算、调用统计以及运维观测。
"""

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from typing import List, Optional
from fastapi import Body
from datetime import datetime
from loguru import logger

from db.models import get_db
from api.dependencies import get_current_user
from billing.tracker import UsageTracker
from billing.pricing_manager import PricingManager
from billing.budget_manager import BudgetManager
from billing.reporter import BillingReporter
from config.config_loader import config_loader
from config.logging import REQUEST_ID_HEADER
from core.metrics import record_model_service_metric
from core.model_service import build_standard_error
from core.litellm_adapter import litellm_list_models
from pydantic import BaseModel

router = APIRouter(prefix="/api/billing", tags=["billing"])


class UsageRecordResponse(BaseModel):
    """
    封装与UsageRecordResponse相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    call_id: str
    user_id: Optional[str]
    session_id: Optional[str]
    provider: str
    model: str
    content_type: str
    input_tokens: int
    output_tokens: int
    input_cost: float
    output_cost: float
    total_cost: float
    currency: str
    cache_hit: bool
    duration_ms: int
    created_at: datetime


class PricingUpdateRequest(BaseModel):
    """
    封装与PricingUpdateRequest相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    input_price: Optional[float] = None
    output_price: Optional[float] = None
    currency: Optional[str] = None
    cache_hit_price: Optional[float] = None
    token_per_image: Optional[int] = None
    token_per_second_audio: Optional[int] = None
    token_per_second_video: Optional[int] = None


class BudgetCreateRequest(BaseModel):
    """
    封装与BudgetCreateRequest相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    budget_type: str
    max_amount: float
    scope_id: Optional[str] = None
    period_type: str = "monthly"
    currency: str = "USD"
    warning_threshold: float = 0.8


class BudgetUpdateRequest(BaseModel):
    """
    封装与BudgetUpdateRequest相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    max_amount: Optional[float] = None
    period_type: Optional[str] = None
    currency: Optional[str] = None
    warning_threshold: Optional[float] = None
    is_active: Optional[bool] = None


class ProviderModelSelectionRequest(BaseModel):
    """
    封装与ProviderModelSelectionRequest相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    selected_models: List[str] = []


class ModelConfigCreateRequest(BaseModel):
    """
    封装与ModelConfigCreateRequest相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    provider: str
    model: str
    display_name: Optional[str] = None
    description: Optional[str] = None
    icon: Optional[str] = None
    api_key: Optional[str] = None
    api_endpoint: Optional[str] = None
    selected_models: List[str] = []
    max_tokens: Optional[int] = None
    is_active: bool = True
    is_default: bool = False
    sort_order: int = 0


class ModelConfigUpdateRequest(BaseModel):
    """
    封装与ModelConfigUpdateRequest相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    provider: Optional[str] = None
    model: Optional[str] = None
    display_name: Optional[str] = None
    description: Optional[str] = None
    icon: Optional[str] = None
    api_key: Optional[str] = None
    api_endpoint: Optional[str] = None
    selected_models: Optional[List[str]] = None
    max_tokens: Optional[int] = None
    is_active: Optional[bool] = None
    is_default: Optional[bool] = None
    sort_order: Optional[int] = None


class RetentionUpdateRequest(BaseModel):
    """
    封装与RetentionUpdateRequest相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    retention_days: int = Query(..., ge=1, le=3650)
    cleanup: bool = Query(False)


class ModelParameterUpdateRequest(BaseModel):
    """更新模型运行参数的请求体。"""
    temperature: Optional[float] = None
    top_k: Optional[float] = None
    top_p: Optional[float] = None
    max_tokens_limit: Optional[int] = None


class BatchStatusUpdateRequest(BaseModel):
    """批量更新模型状态的请求体。"""
    config_ids: List[int]
    status: str


def _parse_model_spec(config) -> Optional[dict]:
    """安全解析 model_spec JSON 字段。"""
    raw = getattr(config, "model_spec", None)
    if not raw:
        return None
    if isinstance(raw, dict):
        return raw
    try:
        import json as _json
        return _json.loads(raw)
    except (TypeError, ValueError):
        return None


def serialize_configuration(config, pricing_manager: PricingManager, include_secret: bool = False):
    """
    将configuration相关对象序列化为接口或存储所需格式。
    通常用于在内部对象与外部输出结构之间建立稳定映射。
    """
    selected_models = pricing_manager.parse_selected_models(config.selected_models)
    spec = _parse_model_spec(config)
    payload = {
        "id": config.id,
        "provider": config.provider,
        "model": config.model,
        "display_name": config.display_name or config.model,
        "description": config.description,
        "icon": getattr(config, "icon", None),
        "api_endpoint": config.api_endpoint,
        "base_url": config.api_endpoint,
        "has_api_key": bool(config.api_key),
        "selected_models": selected_models,
        "max_tokens": getattr(config, "max_tokens", None),
        "is_active": config.is_active,
        "is_default": config.is_default,
        "sort_order": config.sort_order,
        "temperature": getattr(config, "temperature", 0.7),
        "top_k": getattr(config, "top_k", 0.9),
        "top_p": getattr(config, "top_p", None),
        "max_tokens_limit": getattr(config, "max_tokens_limit", None),
        "supports_temperature": getattr(config, "supports_temperature", True),
        "supports_top_k": getattr(config, "supports_top_k", True),
        "supports_vision": getattr(config, "supports_vision", False),
        "is_multimodal": getattr(config, "is_multimodal", False),
        "model_spec": spec,
        "status": getattr(config, "status", "active"),
        "created_at": config.created_at.isoformat() if config.created_at else None,
        "updated_at": config.updated_at.isoformat() if config.updated_at else None
    }

    if include_secret:
        payload["api_key"] = config.api_key

    return payload


@router.get("/usage")
async def get_usage(
    session_id: Optional[str] = Query(None),
    provider: Optional[str] = Query(None),
    model: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    获取当前用户的用量记录。
    使用 current_user.id 代替查询参数，防止越权访问他人用量数据。
    """
    tracker = UsageTracker(db)
    records = tracker.get_usage_records(
        user_id=current_user.id,
        session_id=session_id,
        provider=provider,
        model=model,
        limit=limit,
        offset=offset
    )
    
    return {
        "records": [
            {
                "call_id": r.call_id,
                "user_id": r.user_id,
                "session_id": r.session_id,
                "provider": r.provider,
                "model": r.model,
                "content_type": r.content_type,
                "input_tokens": r.input_tokens,
                "output_tokens": r.output_tokens,
                "input_cost": r.input_cost,
                "output_cost": r.output_cost,
                "total_cost": r.total_cost,
                "currency": r.currency,
                "cache_hit": r.cache_hit,
                "duration_ms": r.duration_ms,
                "created_at": r.created_at.isoformat() if r.created_at else None
            }
            for r in records
        ],
        "total": len(records)
    }


@router.get("/cost")
async def get_cost_statistics(
    period: str = Query("monthly", regex="^(daily|weekly|monthly|yearly)$"),
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    获取当前用户的成本统计。
    使用 current_user.id 代替查询参数，防止越权访问他人成本数据。
    """
    reporter = BillingReporter(db)
    stats = reporter.get_cost_statistics(user_id=current_user.id, period=period)
    return stats


@router.get("/models")
async def get_models(
    provider: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    获取models相关数据或当前状态。
    调用方通常依赖该结果继续进行后续判断、渲染或业务编排。
    """
    pricing_manager = PricingManager(db)
    models = pricing_manager.get_all_pricing(provider=provider)
    
    return {
        "models": [
            {
                "id": m.id,
                "provider": m.provider,
                "model": m.model,
                "input_price": m.input_price,
                "output_price": m.output_price,
                "currency": m.currency,
                "cache_hit_price": m.cache_hit_price,
                "context_window": m.context_window,
                "is_active": m.is_active,
                "supports_vision": m.supports_vision,
                "is_multimodal": m.is_multimodal,
                "updated_at": m.updated_at.isoformat() if m.updated_at else None
            }
            for m in models
        ],
        "providers": pricing_manager.get_providers()
    }


@router.put("/models/{model_id}")
async def update_model_pricing(
    model_id: int,
    update_data: PricingUpdateRequest,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    更新model、pricing相关数据、配置或状态。
    阅读时需要重点关注覆盖规则、副作用以及更新后的数据一致性。
    """
    pricing_manager = PricingManager(db)
    
    update_dict = {k: v for k, v in update_data.dict().items() if v is not None}
    
    if not update_dict:
        raise HTTPException(status_code=400, detail="No fields to update")
    
    is_valid, errors = pricing_manager.validate_pricing_data(update_dict)
    if not is_valid:
        raise HTTPException(status_code=400, detail=str(errors))
    
    updated = pricing_manager.update_pricing(model_id, update_dict)
    
    if not updated:
        raise HTTPException(status_code=404, detail="Model pricing not found")
    
    return {
        "success": True,
        "id": updated.id,
        "provider": updated.provider,
        "model": updated.model,
        "input_price": updated.input_price,
        "output_price": updated.output_price
    }


@router.get("/budget")
async def get_budget(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    获取当前登录用户的预算状态。
    使用 current_user.id 代替查询参数，防止越权访问他人预算。
    """
    budget_manager = BudgetManager(db)
    status = budget_manager.get_budget_status(current_user.id)
    return status


@router.post("/budget")
async def create_budget(
    budget_data: BudgetCreateRequest,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    创建budget相关对象、记录或执行结果。
    实现过程中往往会涉及初始化、组装、持久化或返回统一结构。
    """
    budget_manager = BudgetManager(db)
    
    if budget_data.budget_type not in ["global", "user", "project", "model"]:
        raise HTTPException(status_code=400, detail="Invalid budget type")
    
    if budget_data.period_type not in ["daily", "weekly", "monthly", "yearly"]:
        raise HTTPException(status_code=400, detail="Invalid period type")
    
    if budget_data.currency not in ["USD", "CNY"]:
        raise HTTPException(status_code=400, detail="Invalid currency")
    
    budget = budget_manager.create_budget(
        budget_type=budget_data.budget_type,
        max_amount=budget_data.max_amount,
        scope_id=budget_data.scope_id,
        period_type=budget_data.period_type,
        currency=budget_data.currency,
        warning_threshold=budget_data.warning_threshold
    )
    
    return {
        "success": True,
        "id": budget.id,
        "budget_type": budget.budget_type,
        "max_amount": budget.max_amount,
        "period_type": budget.period_type
    }


@router.put("/budget/{budget_id}")
async def update_budget(
    budget_id: int,
    update_data: BudgetUpdateRequest,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    更新budget相关数据、配置或状态。
    阅读时需要重点关注覆盖规则、副作用以及更新后的数据一致性。
    """
    budget_manager = BudgetManager(db)
    
    update_dict = {k: v for k, v in update_data.dict().items() if v is not None}
    
    if not update_dict:
        raise HTTPException(status_code=400, detail="No fields to update")
    
    updated = budget_manager.update_budget(budget_id, update_dict)
    
    if not updated:
        raise HTTPException(status_code=404, detail="Budget not found")
    
    return {
        "success": True,
        "id": updated.id,
        "max_amount": updated.max_amount,
        "period_type": updated.period_type
    }


@router.delete("/budget/{budget_id}")
async def delete_budget(
    budget_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    删除budget相关对象或持久化记录。
    实现中通常还会同时处理资源释放、状态回收或关联数据清理。
    """
    budget_manager = BudgetManager(db)
    success = budget_manager.delete_budget(budget_id)
    
    if not success:
        raise HTTPException(status_code=404, detail="Budget not found")
    
    return {"success": True}


@router.get("/report")
async def get_report(
    period: str = Query("monthly", regex="^(daily|weekly|monthly|yearly)$"),
    format: str = Query("json", regex="^(json|csv)$"),
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    获取当前登录用户的计费报告。
    使用 current_user.id 代替查询参数，防止越权查看他人报告。
    """
    reporter = BillingReporter(db)
    
    # 使用当前用户ID，防止越权
    user_id = current_user.id
    
    if format == "csv":
        csv_content = reporter.generate_csv_report(user_id=user_id, period=period)
        return {
            "format": "csv",
            "content": csv_content
        }
    
    stats = reporter.get_cost_statistics(user_id=user_id, period=period)
    model_report = reporter.get_model_usage_report(user_id=user_id, period=period)
    content_analysis = reporter.get_content_type_analysis(user_id=user_id, period=period)
    
    return {
        "format": "json",
        "statistics": stats,
        "model_usage": model_report,
        "content_analysis": content_analysis
    }


@router.get("/session/{session_id}")
async def get_session_usage(
    session_id: str,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    获取session、usage相关数据或当前状态。
    调用方通常依赖该结果继续进行后续判断、渲染或业务编排。
    """
    tracker = UsageTracker(db)
    usage = tracker.get_session_usage(session_id)
    return usage


@router.get("/estimate")
async def estimate_cost(
    provider: str = Query(...),
    model: str = Query(...),
    text: str = Query(""),
    num_images: int = Query(0, ge=0),
    audio_seconds: float = Query(0, ge=0),
    video_seconds: float = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    处理estimate、cost相关逻辑，并为调用方返回对应结果。
    阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
    """
    pricing_manager = PricingManager(db)
    pricing = pricing_manager.get_pricing(provider, model)
    
    if not pricing:
        raise HTTPException(status_code=404, detail=f"Pricing not found for {provider}:{model}")
    
    from billing.calculator import CostCalculator
    calculator = CostCalculator()
    
    tokens_result = calculator.calculate_multimodal_tokens(
        text=text,
        num_images=num_images,
        audio_seconds=audio_seconds,
        video_seconds=video_seconds
    )
    
    cost_result = calculator.calculate_cost(
        input_tokens=tokens_result["total_tokens"],
        output_tokens=0,
        input_price=pricing.input_price,
        output_price=pricing.output_price
    )
    
    return {
        "provider": provider,
        "model": model,
        "tokens_breakdown": tokens_result,
        "estimated_cost": cost_result,
        "currency": pricing.currency
    }


@router.post("/initialize-pricing")
async def initialize_default_pricing(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    处理initialize、default、pricing相关逻辑，并为调用方返回对应结果。
    阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
    """
    pricing_manager = PricingManager(db)
    count = pricing_manager.initialize_default_pricing()
    
    return {
        "success": True,
        "message": f"Initialized {count} model prices"
    }


@router.get("/retention")
async def get_retention_config(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    获取retention、config相关数据或当前状态。
    调用方通常依赖该结果继续进行后续判断、渲染或业务编排。
    """
    from config.settings import settings
    
    tracker = UsageTracker(db)
    record_count = tracker.get_record_count()
    oldest_date = tracker.get_oldest_record_date()
    newest_date = tracker.get_newest_record_date()
    
    return {
        "retention_days": settings.USAGE_RETENTION_DAYS,
        "total_records": record_count,
        "oldest_record": oldest_date.isoformat() if oldest_date else None,
        "newest_record": newest_date.isoformat() if newest_date else None
    }


@router.put("/retention")
async def update_retention_config(
    retention_days: int = Query(..., ge=1, le=3650, description="Retention days (1-3650)"),
    cleanup: bool = Query(False, description="Whether to cleanup old records"),
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    更新retention、config相关数据、配置或状态。
    阅读时需要重点关注覆盖规则、副作用以及更新后的数据一致性。
    """
    from config.settings import settings
    
    old_value = settings.USAGE_RETENTION_DAYS
    settings.USAGE_RETENTION_DAYS = retention_days
    
    deleted_count = 0
    if cleanup:
        tracker = UsageTracker(db)
        deleted_count = tracker.cleanup_old_records(retention_days)
    
    return {
        "success": True,
        "old_retention_days": old_value,
        "new_retention_days": retention_days,
        "deleted_records": deleted_count
    }


@router.get("/configurations")
async def get_configurations(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    获取configurations相关数据或当前状态。
    调用方通常依赖该结果继续进行后续判断、渲染或业务编排。
    """
    pricing_manager = PricingManager(db)
    configs = pricing_manager.get_active_configurations()
    
    return {
        "configurations": [
            serialize_configuration(c, pricing_manager)
            for c in configs
        ]
    }


@router.get("/configurations/{config_id}")
async def get_configuration(
    config_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    获取configuration相关数据或当前状态。
    调用方通常依赖该结果继续进行后续判断、渲染或业务编排。
    """
    pricing_manager = PricingManager(db)
    config = pricing_manager.get_configuration(config_id)
    
    if not config:
        raise HTTPException(status_code=404, detail="Configuration not found")
    
    return serialize_configuration(config, pricing_manager)


@router.post("/configurations")
async def create_configuration(
    config_data: ModelConfigCreateRequest,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    创建configuration相关对象、记录或执行结果。
    实现过程中往往会涉及初始化、组装、持久化或返回统一结构。
    """
    pricing_manager = PricingManager(db)
    try:
        config = pricing_manager.create_configuration(config_data.dict())
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    
    return {
        "success": True,
        "configuration": serialize_configuration(config, pricing_manager)
    }


@router.put("/configurations/{config_id}")
async def update_configuration(
    config_id: int,
    update_data: ModelConfigUpdateRequest,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    更新configuration相关数据、配置或状态。
    阅读时需要重点关注覆盖规则、副作用以及更新后的数据一致性。
    """
    pricing_manager = PricingManager(db)
    update_dict = update_data.dict(exclude_unset=True)
    
    if not update_dict:
        raise HTTPException(status_code=400, detail="No fields to update")

    try:
        updated = pricing_manager.update_configuration(config_id, update_dict)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    
    if not updated:
        raise HTTPException(status_code=404, detail="Configuration not found")
    
    return {
        "success": True,
        "configuration": serialize_configuration(updated, pricing_manager)
    }


@router.delete("/configurations/{config_id}")
async def delete_configuration(
    config_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    删除configuration相关对象或持久化记录。
    实现中通常还会同时处理资源释放、状态回收或关联数据清理。
    """
    pricing_manager = PricingManager(db)
    success = pricing_manager.delete_configuration(config_id)
    
    if not success:
        raise HTTPException(status_code=404, detail="Configuration not found")
    
    return {"success": True}


@router.put("/configurations/{config_id}/set-default")
async def set_default_configuration(
    config_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    设置default、configuration相关配置或运行状态。
    此类方法通常会直接影响后续执行路径或运行上下文中的关键数据。
    """
    pricing_manager = PricingManager(db)
    config = pricing_manager.set_default_configuration(config_id)
    
    if not config:
        raise HTTPException(status_code=404, detail="Configuration not found")
    
    return {
        "success": True,
        "configuration": serialize_configuration(config, pricing_manager)
    }


@router.put("/configurations/{config_id}/parameters")
async def update_configuration_parameters(
    config_id: int,
    params: ModelParameterUpdateRequest,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    更新指定模型配置的运行参数（temperature、top_k、top_p、max_tokens_limit）。
    """
    pricing_manager = PricingManager(db)
    config = pricing_manager.get_configuration(config_id)

    if not config:
        raise HTTPException(status_code=404, detail="Configuration not found")

    update_dict = {}

    if params.temperature is not None:
        if not (0.0 <= params.temperature <= 2.0):
            raise HTTPException(status_code=422, detail="temperature must be between 0.0 and 2.0")
        if getattr(config, "supports_temperature", True):
            update_dict["temperature"] = params.temperature

    if params.top_k is not None:
        if not (0.0 <= params.top_k <= 1.0):
            raise HTTPException(status_code=422, detail="top_k must be between 0.0 and 1.0")
        if getattr(config, "supports_top_k", True):
            update_dict["top_k"] = params.top_k

    if params.top_p is not None:
        if not (0.0 <= params.top_p <= 1.0):
            raise HTTPException(status_code=422, detail="top_p must be between 0.0 and 1.0")
        update_dict["top_p"] = params.top_p

    if params.max_tokens_limit is not None:
        if params.max_tokens_limit < 1:
            raise HTTPException(status_code=422, detail="max_tokens_limit must be at least 1")
        spec = _parse_model_spec(config)
        if spec and spec.get("context_window"):
            if params.max_tokens_limit > spec["context_window"]:
                raise HTTPException(
                    status_code=422,
                    detail=f"max_tokens_limit cannot exceed model context window ({spec['context_window']})"
                )
        update_dict["max_tokens_limit"] = params.max_tokens_limit

    if not update_dict:
        return {
            "success": True,
            "configuration": serialize_configuration(config, pricing_manager)
        }

    updated = pricing_manager.update_configuration(config_id, update_dict)
    return {
        "success": True,
        "configuration": serialize_configuration(updated, pricing_manager)
    }


@router.get("/configurations/{config_id}/capabilities")
async def get_configuration_capabilities(
    config_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    获取指定模型配置的能力信息、默认参数与限制范围。
    """
    pricing_manager = PricingManager(db)
    config = pricing_manager.get_configuration(config_id)

    if not config:
        raise HTTPException(status_code=404, detail="Configuration not found")

    spec = _parse_model_spec(config)
    context_window = (spec or {}).get("context_window") or getattr(config, "max_tokens", None) or 128000

    return {
        "config_id": config.id,
        "provider": config.provider,
        "model": config.model,
        "capabilities": {
            "supports_temperature": getattr(config, "supports_temperature", True),
            "supports_top_k": getattr(config, "supports_top_k", True),
            "supports_vision": getattr(config, "supports_vision", False),
            "is_multimodal": getattr(config, "is_multimodal", False),
            "supports_function_calling": (spec or {}).get("supports_function_calling", False),
            "supports_streaming": (spec or {}).get("supports_streaming", True),
        },
        "defaults": {
            "temperature": getattr(config, "temperature", 0.7) or 0.7,
            "top_k": getattr(config, "top_k", 0.9) or 0.9,
            "max_tokens": context_window,
        },
        "limits": {
            "temperature_min": 0.0,
            "temperature_max": 2.0,
            "top_k_min": 0.0,
            "top_k_max": 1.0,
            "max_tokens_min": 1,
            "max_tokens_max": context_window,
        }
    }


@router.post("/configurations/{config_id}/reset-parameters")
async def reset_configuration_parameters(
    config_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    将指定模型配置的 temperature、top_k、max_tokens_limit 重置为系统默认值。
    """
    pricing_manager = PricingManager(db)
    config = pricing_manager.get_configuration(config_id)

    if not config:
        raise HTTPException(status_code=404, detail="Configuration not found")

    defaults = pricing_manager.get_model_defaults(config.provider, config.model)

    update_dict = {
        "temperature": defaults.get("temperature", 0.7),
        "top_k": defaults.get("top_k", 0.9),
        "max_tokens_limit": defaults.get("max_tokens_limit"),
    }

    updated = pricing_manager.update_configuration(config_id, update_dict)
    return {
        "success": True,
        "configuration": serialize_configuration(updated, pricing_manager)
    }


@router.put("/configurations/batch-status")
async def batch_update_configuration_status(
    payload: BatchStatusUpdateRequest,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    批量更新模型配置状态。
    """
    if payload.status not in ("active", "inactive", "error", "deprecated"):
        raise HTTPException(status_code=400, detail="Invalid status value")

    pricing_manager = PricingManager(db)
    updated_count = pricing_manager.batch_update_status(payload.config_ids, payload.status)

    return {
        "success": True,
        "updated_count": updated_count
    }

@router.get("/providers")
async def get_providers(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    获取providers相关数据或当前状态。
    调用方通常依赖该结果继续进行后续判断、渲染或业务编排。
    """
    pricing_manager = PricingManager(db)
    providers = pricing_manager.get_provider_catalog()
    
    return {
        "providers": providers,
        "total": len(providers)
    }


@router.get("/providers/{provider}")
async def get_provider_detail(
    provider: str,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    获取provider、detail相关数据或当前状态。
    调用方通常依赖该结果继续进行后续判断、渲染或业务编排。
    """
    pricing_manager = PricingManager(db)
    provider_id = pricing_manager.normalize_provider(provider)
    config = pricing_manager.get_default_provider_configuration(provider_id)

    if not config:
        raise HTTPException(status_code=404, detail="Provider configuration not found")

    return {
        "provider": {
            "id": provider_id,
            "name": config.display_name or provider_id.upper(),
            "icon": getattr(config, "icon", None),
            "api_endpoint": config.api_endpoint,
            "base_url": config.api_endpoint,
            "has_api_key": bool(config.api_key),
            "selected_models": pricing_manager.parse_selected_models(config.selected_models)
        },
        "configuration": serialize_configuration(config, pricing_manager)
    }


@router.delete("/providers/{provider}")
async def delete_provider(
    provider: str,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    删除provider相关对象或持久化记录。
    实现中通常还会同时处理资源释放、状态回收或关联数据清理。
    """
    pricing_manager = PricingManager(db)
    provider_id = pricing_manager.normalize_provider(provider)
    deleted_count = pricing_manager.delete_provider_configurations(provider_id)

    if deleted_count == 0:
        raise HTTPException(status_code=404, detail="Provider configuration not found")

    return {
        "success": True,
        "provider": provider_id,
        "deleted_count": deleted_count
    }


@router.put("/providers/{provider}/selected-models")
async def update_provider_selected_models(
    provider: str,
    payload: ProviderModelSelectionRequest,
    db: Session = Depends(get_db)
):
    """
    更新provider、selected、models相关数据、配置或状态。
    阅读时需要重点关注覆盖规则、副作用以及更新后的数据一致性。
    """
    pricing_manager = PricingManager(db)
    provider_id = pricing_manager.normalize_provider(provider)
    config = pricing_manager.get_default_provider_configuration(provider_id)

    if not config:
        raise HTTPException(status_code=404, detail="Provider configuration not found")

    updated = pricing_manager.update_configuration(
        config.id,
        {"selected_models": payload.selected_models}
    )

    return {
        "success": True,
        "provider": provider_id,
        "selected_models": pricing_manager.parse_selected_models(updated.selected_models)
    }


@router.get("/models-by-provider/{provider}")
async def get_models_by_provider(
    provider: str,
    request: Request,
    db: Session = Depends(get_db)
):
    """
    获取models、by、provider相关数据或当前状态。
    调用方通常依赖该结果继续进行后续判断、渲染或业务编排。
    """
    pricing_manager = PricingManager(db)
    provider_id = pricing_manager.normalize_provider(provider)
    config = pricing_manager.get_default_provider_configuration(provider_id)
    selected_models = pricing_manager.parse_selected_models(config.selected_models if config else None)
    base_url = config.api_endpoint if config else None
    request_id = getattr(request.state, "request_id", "") or request.headers.get(REQUEST_ID_HEADER, "")
    client_version = request.headers.get("X-Client-Ver", "")

    try:
        remote_models: List[dict] = []
        source = "local"
        if base_url:
            try:
                started_at = datetime.now().timestamp()
                result = await litellm_list_models(
                    provider=provider_id,
                    api_key=config.api_key if config else "",
                    api_base=base_url,
                    request_id=request_id,
                )
                duration_ms = int((datetime.now().timestamp() - started_at) * 1000)
                if result.get("ok"):
                    record_model_service_metric(provider_id, "models", "success", duration_ms)
                    data = result.get("models", [])
                    if isinstance(data, list):
                        for index, item in enumerate(data):
                            if isinstance(item, dict):
                                model_name = str(item.get("id") or item.get("name") or "").strip()
                                if model_name.startswith("models/"):
                                    model_name = model_name.split("/", 1)[1]
                                if model_name:
                                    remote_models.append({
                                        "id": -(index + 1),
                                        "provider": provider_id,
                                        "model": model_name,
                                        "input_price": 0,
                                        "output_price": 0,
                                        "currency": "USD",
                                        "context_window": None,
                                        "selected": model_name in selected_models
                                    })
                    source = "remote"
                else:
                    record_model_service_metric(provider_id, "models", "error", duration_ms)
                    error_detail = result.get("error", {})
                    raise RuntimeError(error_detail.get("message", "远程模型列表拉取失败"))
            except RuntimeError:
                raise
            except Exception as fetch_exc:
                duration_ms = 0
                record_model_service_metric(provider_id, "models", "error", duration_ms)
                logger.bind(
                    event="provider_models_fetch_error",
                    module="billing",
                    error_type=type(fetch_exc).__name__,
                    provider=provider_id,
                ).opt(exception=True).error(f"远程模型列表拉取失败: {fetch_exc}")
                raise fetch_exc

        if remote_models:
            return {
                "success": True,
                "provider": provider_id,
                "models": remote_models,
                "selected_models": selected_models,
                "source": source,
                "error": None
            }

        models = pricing_manager.get_all_pricing(provider=provider_id)
        return {
            "success": True,
            "provider": provider_id,
            "models": [
                {
                    "id": m.id,
                    "provider": m.provider,
                    "model": m.model,
                    "input_price": m.input_price,
                    "output_price": m.output_price,
                    "currency": m.currency,
                    "context_window": m.context_window,
                    "selected": m.model in selected_models
                }
                for m in models
            ],
            "selected_models": selected_models,
            "source": source,
            "error": None
        }
    except Exception as exc:
        logger.bind(
            event="provider_models_fallback",
            module="billing",
            error_type=type(exc).__name__,
            provider=provider_id,
        ).opt(exception=True).warning(f"模型列表获取失败，回退到本地列表: {exc}")
        models = pricing_manager.get_all_pricing(provider=provider_id)
        return {
            "success": False,
            "provider": provider_id,
            "models": [
                {
                    "id": m.id,
                    "provider": m.provider,
                    "model": m.model,
                    "input_price": m.input_price,
                    "output_price": m.output_price,
                    "currency": m.currency,
                    "context_window": m.context_window,
                    "selected": m.model in selected_models
                }
                for m in models
            ],
            "selected_models": selected_models,
            "source": "local",
            "error": build_standard_error(
                "provider_models_fetch_failed",
                "模型列表获取失败，已回退到本地模型列表",
                request_id=request_id,
                details={"reason": str(exc), "provider": provider_id},
                retryable=True,
            ),
        }


@router.post("/retention")
async def update_retention(
    retention_days: int = Body(..., ge=1, le=3650),
    cleanup: bool = Body(False),
    db: Session = Depends(get_db)
):
    """
    更新retention相关数据、配置或状态。
    阅读时需要重点关注覆盖规则、副作用以及更新后的数据一致性。
    """
    from config.settings import settings
    
    old_value = settings.USAGE_RETENTION_DAYS
    settings.USAGE_RETENTION_DAYS = retention_days
    
    deleted_count = 0
    if cleanup:
        tracker = UsageTracker(db)
        deleted_count = tracker.cleanup_old_records(retention_days)
    
    return {
        "success": True,
        "old_retention_days": old_value,
        "new_retention_days": retention_days,
        "deleted_records": deleted_count
    }

CONFIG_TYPE_MAP = {
    "pricing": ("pricing_data", "load_pricing_data_async"),
    "configurations": ("default_configurations", "load_default_configurations_async"),
    "capabilities": ("model_capabilities", "load_model_capabilities_async"),
    "legacy-keys": ("legacy_config_keys", "load_legacy_config_keys_async"),
}


@router.get("/configs")
async def get_all_configs(current_user = Depends(get_current_user)):
    try:
        pricing_task = config_loader.load_pricing_data_async()
        configs_task = config_loader.load_default_configurations_async()
        caps_task = config_loader.load_model_capabilities_async()
        legacy_task = config_loader.load_legacy_config_keys_async()

        pricing, configs, capabilities, legacy_keys = await asyncio.gather(
            pricing_task, configs_task, caps_task, legacy_task
        )

        return {
            "success": True,
            "data": {
                "pricing": pricing,
                "configurations": configs,
                "capabilities": capabilities,
                "legacy_keys": legacy_keys,
            }
        }
    except Exception as e:
        logger.error("获取配置数据失败: %s", e)
        raise HTTPException(status_code=500, detail=f"获取配置数据失败: {str(e)}")


@router.get("/configs/{config_type}")
async def get_config_by_type(
    config_type: str,
    current_user = Depends(get_current_user),
):
    if config_type not in CONFIG_TYPE_MAP:
        raise HTTPException(
            status_code=400,
            detail=f"无效的配置类型: {config_type}，可选值: {', '.join(CONFIG_TYPE_MAP.keys())}"
        )

    method_name = CONFIG_TYPE_MAP[config_type][1]
    load_method = getattr(config_loader, method_name)

    try:
        data = await load_method()
        return {"success": True, "data": data}
    except Exception as e:
        logger.error("获取配置[%s]失败: %s", config_type, e)
        raise HTTPException(status_code=500, detail=f"获取配置[{config_type}]失败: {str(e)}")
