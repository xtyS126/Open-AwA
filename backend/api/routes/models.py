"""
模型管理路由，提供 Ollama 本地模型发现、提供商连接状态、故障转移与延迟监控接口。
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger
from typing import Optional

from api.dependencies import get_current_user, get_db
from core.litellm_adapter import litellm_check_provider_connection, litellm_list_models
from core.failover import get_failover_manager
from config.settings import settings
from billing.pricing_manager import PricingManager
from billing.models import ModelConfiguration
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
