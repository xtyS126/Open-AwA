"""
模型管理路由，提供 Ollama 本地模型发现和提供商连接状态查询接口。
"""

from fastapi import APIRouter, Depends
from loguru import logger

from api.dependencies import get_current_user, get_db
from core.litellm_adapter import litellm_check_provider_connection, litellm_list_models
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
