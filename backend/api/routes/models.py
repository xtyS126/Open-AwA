"""
模型管理路由，提供 Ollama 本地模型发现、提供商连接状态、故障转移与延迟监控接口。
同时提供 LLM Registry（注册中心）、任务路由配置和用量统计接口。
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger
from typing import Optional
from datetime import datetime

from pydantic import BaseModel, Field
from sqlalchemy import func

from api.dependencies import get_current_user, get_db
from core.litellm_adapter import litellm_check_provider_connection, litellm_list_models
from core.failover import get_failover_manager
from config.settings import settings
from billing.pricing_manager import PricingManager
from billing.models import ModelConfiguration
from db.models import LLMUsage
from sqlalchemy.orm import Session

router = APIRouter(prefix="/api/models", tags=["models"])


@router.get("/ollama")
async def get_ollama_models(current_user=Depends(get_current_user)):
    """
    发现本地 Ollama 服务中的可用模型列表。
    当 Ollama 服务未运行时返回空列表。
    """
    logger.bind(event="ollama_discover", module="models").info("discovering ollama models")
    result = await litellm_list_models(
        provider="ollama",
        api_key="",
        api_base=settings.OLLAMA_BASE_URL,
    )
    models = result.get("models", [])
    return {
        "success": True,
        "provider": "ollama",
        "base_url": settings.OLLAMA_BASE_URL,
        "models": models,
        "count": len(models),
    }


@router.get("/providers")
async def get_providers_status(
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    获取所有已配置的模型提供商列表及其连接状态。
    遍历数据库中的提供商配置，逐个检测连通性。
    """
    logger.bind(event="providers_status", module="models").info("checking providers status")

    # 从数据库获取所有不同的 provider 配置
    configs = db.query(ModelConfiguration).filter(
        ModelConfiguration.is_active == True
    ).all()

    # 按 provider 分组，每个 provider 取第一个配置
    seen_providers = {}
    for config in configs:
        provider_id = PricingManager.normalize_provider(config.provider)
        if provider_id not in seen_providers:
            seen_providers[provider_id] = config

    # 添加 Ollama（即使数据库中未配置也始终显示）
    provider_status_list = []

    # 检查数据库中的已配置 provider
    for provider_id, config in seen_providers.items():
        base_url = config.api_endpoint or config.base_url if hasattr(config, 'base_url') else config.api_endpoint
        api_key = config.api_key or ""
        status = await litellm_check_provider_connection(provider=provider_id, api_base=base_url or "", api_key=api_key)
        status["display_name"] = config.display_name or provider_id
        provider_status_list.append(status)

    # 如果 Ollama 不在已配置列表中，单独检测
    if "ollama" not in seen_providers:
        ollama_status = await litellm_check_provider_connection(
            provider="ollama", api_base=settings.OLLAMA_BASE_URL, api_key=""
        )
        ollama_status["display_name"] = "Ollama (本地)"
        provider_status_list.append(ollama_status)

    return {
        "success": True,
        "providers": provider_status_list,
    }


@router.get("/{provider}/{model}/capabilities")
async def get_model_capabilities(
    provider: str,
    model: str,
    current_user=Depends(get_current_user),
):
    """
    获取指定模型的能力参数（是否支持视觉、多模态、函数调用等）。
    从 model_capabilities.json 配置文件中读取。
    """
    from pathlib import Path as FsPath
    import json

    capabilities_path = FsPath("config/pricing/model_capabilities.json")
    if not capabilities_path.exists():
        raise HTTPException(status_code=404, detail="模型能力配置文件未找到")

    capabilities_data = json.loads(capabilities_path.read_text(encoding="utf-8"))

    for entry in capabilities_data:
        provider_model = entry.get("provider_model", "")
        entry_provider = entry.get("provider", "")
        entry_model = entry.get("model", "")
        if (provider_model == f"{provider}/{model}" or
                (entry_provider == provider and entry_model == model)):
            return {
                "provider": entry_provider,
                "model": entry_model,
                "supports_vision": entry.get("supports_vision", False),
                "is_multimodal": entry.get("is_multimodal", False),
                "supports_temperature": entry.get("supports_temperature", True),
                "supports_top_k": entry.get("supports_top_k", True),
                "input_modality": entry.get("input_modality", []),
                "output_modality": entry.get("output_modality", []),
                "model_spec": entry.get("model_spec", {}),
            }

    raise HTTPException(status_code=404, detail=f"模型 {provider}/{model} 的能力信息未找到")


# ── 故障转移与延迟监控 API ──────────────────────────────────────────


@router.get("/failover/circuit-breakers")
async def get_circuit_breakers_status(
    current_user=Depends(get_current_user),
):
    """
    获取所有模型提供商的熔断器状态。
    返回每个提供商的熔断器状态（closed/open/half_open）、失败计数、恢复超时等。
    """
    manager = get_failover_manager()
    status = manager.get_circuit_breaker_status()
    return {
        "success": True,
        "circuit_breakers": status,
        "total": len(status),
    }


@router.get("/failover/chains")
async def get_failover_chains(
    current_user=Depends(get_current_user),
):
    """
    获取所有已注册的故障转移链。
    """
    manager = get_failover_manager()
    chains = manager.list_chains()
    return {
        "success": True,
        "chains": {
            key: [
                {
                    "provider": c.provider,
                    "model": c.model,
                    "priority": c.priority,
                    "weight": c.weight,
                    "tags": c.tags,
                }
                for c in candidates
            ]
            for key, candidates in chains.items()
        },
        "total": len(chains),
    }


@router.get("/failover/events")
async def get_failover_events(
    limit: int = Query(50, ge=1, le=500, description="返回事件数量"),
    chain_key: Optional[str] = Query(None, description="按链标识过滤"),
    current_user=Depends(get_current_user),
):
    """
    获取最近的故障转移事件列表。
    """
    manager = get_failover_manager()
    events = manager.get_events(limit=limit, chain_key=chain_key)
    return {
        "success": True,
        "events": [
            {
                "timestamp": e.timestamp.isoformat(),
                "primary_provider": e.primary_provider,
                "primary_model": e.primary_model,
                "fallback_provider": e.fallback_provider,
                "fallback_model": e.fallback_model,
                "reason": e.reason,
                "request_id": e.request_id,
            }
            for e in events
        ],
        "total": len(events),
    }


@router.get("/latency/stats")
async def get_latency_stats(
    provider: Optional[str] = Query(None, description="按提供商过滤"),
    model: Optional[str] = Query(None, description="按模型过滤"),
    limit: int = Query(100, ge=10, le=1000, description="统计样本数"),
    current_user=Depends(get_current_user),
):
    """
    获取模型调用的延迟统计。
    返回 count、avg_ms、p50_ms、p95_ms、p99_ms、ttft_avg_ms、success_rate。
    """
    manager = get_failover_manager()
    stats = manager.get_latency_stats(provider=provider, model=model, limit=limit)
    return {
        "success": True,
        "filter": {"provider": provider, "model": model, "limit": limit},
        "stats": stats,
    }


@router.get("/latency/providers")
async def get_providers_latency_summary(
    current_user=Depends(get_current_user),
):
    """
    获取所有提供商的延迟汇总，用于延迟 benchmark 面板。
    """
    manager = get_failover_manager()
    # 获取所有出现过的 provider
    providers_set = manager.list_latency_providers()
    summary: dict = {}
    for provider in providers_set:
        summary[provider] = manager.get_latency_stats(provider=provider)
    return {
        "success": True,
        "providers": summary,
        "total": len(summary),
    }


# ── LLM Registry 与路由配置 ──────────────────────────────────────────

# 任务路由规则存储（模块级，服务重启后重置）
# 格式：{task_type: [{"provider": "...", "model": "...", "priority": 1}, ...]}
_task_routing_rules: dict = {}


class LLMRoutingRuleRequest(BaseModel):
    """LLM 任务路由规则配置请求体。"""
    task_type: str = Field(..., description="任务类型：agent/chat/summary/code/vision 等")
    rules: list[dict] = Field(
        default_factory=list,
        description="路由规则列表，每项包含 provider/model/priority 字段",
    )


class LLMRoutingRulesResponse(BaseModel):
    """LLM 路由规则响应模型。"""
    task_type: str
    rules: list[dict]


@router.get("/llm/registry")
async def get_llm_registry(
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    获取已注册的 LLM Provider 列表。
    从数据库 model_configurations 表中提取所有活跃的提供商及其模型。
    """
    # 查询所有活跃的模型配置
    configs = (
        db.query(ModelConfiguration)
        .filter(ModelConfiguration.is_active == True)
        .all()
    )
    # 按 provider 分组，收集每个 provider 下的模型列表
    registry: dict = {}
    for config in configs:
        provider = PricingManager.normalize_provider(config.provider)
        if provider not in registry:
            registry[provider] = {
                "provider": provider,
                "display_name": config.display_name or provider,
                "models": [],
            }
        registry[provider]["models"].append({
            "model": config.model,
            "display_name": config.display_name or config.model,
            "max_tokens": config.max_tokens,
            "is_default": config.is_default,
        })
    return {
        "success": True,
        "data": {
            "providers": list(registry.values()),
            "total": len(registry),
        },
        "message": "LLM Provider 注册列表",
    }


@router.put("/llm/routing")
async def update_llm_routing(
    request: LLMRoutingRuleRequest,
    current_user=Depends(get_current_user),
):
    """
    配置指定任务类型的 LLM 路由规则。
    路由规则按优先级排序，客户端在调用时根据 task_type 选择对应规则链。
    """
    # 按 priority 排序规则列表
    sorted_rules = sorted(request.rules, key=lambda r: r.get("priority", 99))
    _task_routing_rules[request.task_type] = sorted_rules
    logger.bind(
        event="llm_routing_updated",
        module="models",
        task_type=request.task_type,
        rules_count=len(sorted_rules),
    ).info("LLM 路由规则已更新")
    return {
        "success": True,
        "data": {
            "task_type": request.task_type,
            "rules": sorted_rules,
        },
        "message": "路由规则已更新",
    }


@router.get("/llm/routing")
async def get_llm_routing(
    task_type: Optional[str] = Query(None, description="按任务类型过滤，不传则返回全部"),
    current_user=Depends(get_current_user),
):
    """
    获取已配置的 LLM 路由规则。
    可按 task_type 过滤，不传参数则返回全部已配置规则。
    """
    if task_type:
        rules = _task_routing_rules.get(task_type, [])
        return {
            "success": True,
            "data": {
                "task_type": task_type,
                "rules": rules,
            },
            "message": "路由规则查询结果",
        }
    return {
        "success": True,
        "data": {
            "routing_rules": {
                task: rules
                for task, rules in _task_routing_rules.items()
            },
            "total": len(_task_routing_rules),
        },
        "message": "全部路由规则",
    }


@router.get("/llm/usage")
async def get_llm_usage(
    user_id: Optional[str] = Query(None, description="按用户 ID 过滤"),
    task_type: Optional[str] = Query(None, description="按任务类型过滤"),
    provider: Optional[str] = Query(None, description="按 Provider 过滤"),
    limit: int = Query(100, ge=1, le=1000, description="返回记录数"),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    获取 LLM 用量统计，支持按用户、任务类型和 Provider 维度过滤。
    返回详细记录及聚合统计（总 token 数、总成本、平均延迟等）。
    """
    # 构建查询条件
    query = db.query(LLMUsage)
    if user_id:
        query = query.filter(LLMUsage.user_id == user_id)
    if task_type:
        query = query.filter(LLMUsage.task_type == task_type)
    if provider:
        query = query.filter(LLMUsage.provider == provider)
    # 获取最近记录
    records = query.order_by(LLMUsage.created_at.desc()).limit(limit).all()
    # 聚合统计
    agg = (
        db.query(
            func.count(LLMUsage.id).label("total_calls"),
            func.sum(LLMUsage.total_tokens).label("total_tokens"),
            func.sum(LLMUsage.prompt_tokens).label("total_prompt_tokens"),
            func.sum(LLMUsage.completion_tokens).label("total_completion_tokens"),
            func.sum(LLMUsage.cost).label("total_cost"),
            func.avg(LLMUsage.latency_ms).label("avg_latency_ms"),
            func.sum(
                func.case((LLMUsage.success == True, 1), else_=0)
            ).label("success_count"),
            func.sum(
                func.case((LLMUsage.success == False, 1), else_=0)
            ).label("failure_count"),
        )
    )
    if user_id:
        agg = agg.filter(LLMUsage.user_id == user_id)
    if task_type:
        agg = agg.filter(LLMUsage.task_type == task_type)
    if provider:
        agg = agg.filter(LLMUsage.provider == provider)
    agg_row = agg.first()
    return {
        "success": True,
        "data": {
            "records": [
                {
                    "id": r.id,
                    "user_id": r.user_id,
                    "task_type": r.task_type,
                    "provider": r.provider,
                    "model": r.model,
                    "prompt_tokens": r.prompt_tokens,
                    "completion_tokens": r.completion_tokens,
                    "total_tokens": r.total_tokens,
                    "cost": round(r.cost, 6),
                    "latency_ms": r.latency_ms,
                    "success": r.success,
                    "error_message": r.error_message,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in records
            ],
            "summary": {
                "total_calls": agg_row.total_calls or 0,
                "total_tokens": agg_row.total_tokens or 0,
                "total_prompt_tokens": agg_row.total_prompt_tokens or 0,
                "total_completion_tokens": agg_row.total_completion_tokens or 0,
                "total_cost": round(agg_row.total_cost or 0.0, 6),
                "avg_latency_ms": round(agg_row.avg_latency_ms or 0.0, 2),
                "success_count": agg_row.success_count or 0,
                "failure_count": agg_row.failure_count or 0,
            },
            "filter": {
                "user_id": user_id,
                "task_type": task_type,
                "provider": provider,
                "limit": limit,
            },
        },
        "message": "LLM 用量统计",
    }
