from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from fastapi import Body
from datetime import datetime

from db.models import get_db
from billing.tracker import UsageTracker
from billing.pricing_manager import PricingManager
from billing.budget_manager import BudgetManager
from billing.reporter import BillingReporter
from pydantic import BaseModel

router = APIRouter(prefix="/api/billing", tags=["billing"])


class UsageRecordResponse(BaseModel):
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
    input_price: Optional[float] = None
    output_price: Optional[float] = None
    currency: Optional[str] = None
    cache_hit_price: Optional[float] = None
    token_per_image: Optional[int] = None
    token_per_second_audio: Optional[int] = None
    token_per_second_video: Optional[int] = None


class BudgetCreateRequest(BaseModel):
    budget_type: str
    max_amount: float
    scope_id: Optional[str] = None
    period_type: str = "monthly"
    currency: str = "USD"
    warning_threshold: float = 0.8


class BudgetUpdateRequest(BaseModel):
    max_amount: Optional[float] = None
    period_type: Optional[str] = None
    currency: Optional[str] = None
    warning_threshold: Optional[float] = None
    is_active: Optional[bool] = None


class ProviderModelSelectionRequest(BaseModel):
    selected_models: List[str] = []


class ModelConfigCreateRequest(BaseModel):
    provider: str
    model: str
    display_name: Optional[str] = None
    description: Optional[str] = None
    icon: Optional[str] = None
    api_key: Optional[str] = None
    api_endpoint: Optional[str] = None
    selected_models: List[str] = []
    is_active: bool = True
    is_default: bool = False
    sort_order: int = 0


class ModelConfigUpdateRequest(BaseModel):
    provider: Optional[str] = None
    model: Optional[str] = None
    display_name: Optional[str] = None
    description: Optional[str] = None
    icon: Optional[str] = None
    api_key: Optional[str] = None
    api_endpoint: Optional[str] = None
    selected_models: Optional[List[str]] = None
    is_active: Optional[bool] = None
    is_default: Optional[bool] = None
    sort_order: Optional[int] = None


class RetentionUpdateRequest(BaseModel):
    retention_days: int = Query(..., ge=1, le=3650)
    cleanup: bool = Query(False)


def serialize_configuration(config, pricing_manager: PricingManager, include_secret: bool = False):
    selected_models = pricing_manager.parse_selected_models(config.selected_models)
    payload = {
        "id": config.id,
        "provider": config.provider,
        "model": config.model,
        "display_name": config.display_name or config.model,
        "description": config.description,
        "icon": getattr(config, "icon", None),
        "api_endpoint": config.api_endpoint,
        "has_api_key": bool(config.api_key),
        "selected_models": selected_models,
        "is_active": config.is_active,
        "is_default": config.is_default,
        "sort_order": config.sort_order,
        "created_at": config.created_at.isoformat() if config.created_at else None,
        "updated_at": config.updated_at.isoformat() if config.updated_at else None
    }

    if include_secret:
        payload["api_key"] = config.api_key

    return payload


@router.get("/usage")
async def get_usage(
    user_id: Optional[str] = Query(None),
    session_id: Optional[str] = Query(None),
    provider: Optional[str] = Query(None),
    model: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db)
):
    tracker = UsageTracker(db)
    records = tracker.get_usage_records(
        user_id=user_id,
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
    user_id: Optional[str] = Query(None),
    period: str = Query("monthly", regex="^(daily|weekly|monthly|yearly)$"),
    db: Session = Depends(get_db)
):
    reporter = BillingReporter(db)
    stats = reporter.get_cost_statistics(user_id=user_id, period=period)
    return stats


@router.get("/models")
async def get_models(
    provider: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
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
    db: Session = Depends(get_db)
):
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
    user_id: str = Query(...),
    db: Session = Depends(get_db)
):
    budget_manager = BudgetManager(db)
    status = budget_manager.get_budget_status(user_id)
    return status


@router.post("/budget")
async def create_budget(
    budget_data: BudgetCreateRequest,
    db: Session = Depends(get_db)
):
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
    db: Session = Depends(get_db)
):
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
    db: Session = Depends(get_db)
):
    budget_manager = BudgetManager(db)
    success = budget_manager.delete_budget(budget_id)
    
    if not success:
        raise HTTPException(status_code=404, detail="Budget not found")
    
    return {"success": True}


@router.get("/report")
async def get_report(
    user_id: Optional[str] = Query(None),
    period: str = Query("monthly", regex="^(daily|weekly|monthly|yearly)$"),
    format: str = Query("json", regex="^(json|csv)$"),
    db: Session = Depends(get_db)
):
    reporter = BillingReporter(db)
    
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
    db: Session = Depends(get_db)
):
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
    db: Session = Depends(get_db)
):
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
    db: Session = Depends(get_db)
):
    pricing_manager = PricingManager(db)
    count = pricing_manager.initialize_default_pricing()
    
    return {
        "success": True,
        "message": f"Initialized {count} model prices"
    }


@router.get("/retention")
async def get_retention_config(
    db: Session = Depends(get_db)
):
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
    db: Session = Depends(get_db)
):
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
    db: Session = Depends(get_db)
):
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
    db: Session = Depends(get_db)
):
    pricing_manager = PricingManager(db)
    config = pricing_manager.get_configuration(config_id)
    
    if not config:
        raise HTTPException(status_code=404, detail="Configuration not found")
    
    return serialize_configuration(config, pricing_manager, include_secret=True)


@router.post("/configurations")
async def create_configuration(
    config_data: ModelConfigCreateRequest,
    db: Session = Depends(get_db)
):
    pricing_manager = PricingManager(db)
    config = pricing_manager.create_configuration(config_data.dict())
    
    return {
        "success": True,
        "configuration": serialize_configuration(config, pricing_manager)
    }


@router.put("/configurations/{config_id}")
async def update_configuration(
    config_id: int,
    update_data: ModelConfigUpdateRequest,
    db: Session = Depends(get_db)
):
    pricing_manager = PricingManager(db)
    update_dict = {k: v for k, v in update_data.dict().items() if v is not None}
    
    if not update_dict:
        raise HTTPException(status_code=400, detail="No fields to update")
    
    updated = pricing_manager.update_configuration(config_id, update_dict)
    
    if not updated:
        raise HTTPException(status_code=404, detail="Configuration not found")
    
    return {
        "success": True,
        "configuration": serialize_configuration(updated, pricing_manager)
    }


@router.delete("/configurations/{config_id}")
async def delete_configuration(
    config_id: int,
    db: Session = Depends(get_db)
):
    pricing_manager = PricingManager(db)
    success = pricing_manager.delete_configuration(config_id)
    
    if not success:
        raise HTTPException(status_code=404, detail="Configuration not found")
    
    return {"success": True}


@router.put("/configurations/{config_id}/set-default")
async def set_default_configuration(
    config_id: int,
    db: Session = Depends(get_db)
):
    pricing_manager = PricingManager(db)
    config = pricing_manager.set_default_configuration(config_id)
    
    if not config:
        raise HTTPException(status_code=404, detail="Configuration not found")
    
    return {
        "success": True,
        "configuration": serialize_configuration(config, pricing_manager)
    }


@router.get("/providers")
async def get_providers(
    db: Session = Depends(get_db)
):
    pricing_manager = PricingManager(db)
    providers = pricing_manager.get_provider_catalog()
    
    return {
        "providers": providers,
        "total": len(providers)
    }


@router.get("/providers/{provider}")
async def get_provider_detail(
    provider: str,
    db: Session = Depends(get_db)
):
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
            "has_api_key": bool(config.api_key),
            "selected_models": pricing_manager.parse_selected_models(config.selected_models)
        },
        "configuration": serialize_configuration(config, pricing_manager, include_secret=True)
    }


@router.delete("/providers/{provider}")
async def delete_provider(
    provider: str,
    db: Session = Depends(get_db)
):
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
    db: Session = Depends(get_db)
):
    pricing_manager = PricingManager(db)
    provider_id = pricing_manager.normalize_provider(provider)
    config = pricing_manager.get_default_provider_configuration(provider_id)
    selected_models = pricing_manager.parse_selected_models(config.selected_models if config else None)

    try:
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
            "error": None
        }
    except Exception as exc:
        return {
            "success": False,
            "provider": provider_id,
            "models": [],
            "selected_models": selected_models,
            "error": {
                "code": "provider_models_fetch_failed",
                "message": "模型列表获取失败",
                "detail": str(exc)
            }
        }


@router.post("/retention")
async def update_retention(
    retention_days: int = Body(..., ge=1, le=3650),
    cleanup: bool = Body(False),
    db: Session = Depends(get_db)
):
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
