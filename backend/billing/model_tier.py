"""
模型等级（Model Tier）配置模块。

将系统内各类 LLM 调用归类为四档「等级」，每档可绑定一个 provider/model。
抽取层（companion/extraction.py）等调用方通过 resolve_tier_llm_config 解析
对应档位的模型配置；档位未显式指定时回退到默认模型配置。

Subagent 的模型由主 Agent 自行选择，不在此四档内固定设置（见 SUBAGENT_NOTE）。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from loguru import logger
from sqlalchemy.orm import Session

from db.models.model_tier import ModelTierConfig


# 四档等级元信息：说明文字供设置页展示
MODEL_TIERS: List[Dict[str, str]] = [
    {
        "tier": "fable",
        "name": "Fable（旗舰）",
        "description": "主对话回复：聊天生成回复的主力模型，需要最强推理与表达。",
    },
    {
        "tier": "opus",
        "name": "Opus（强）",
        "description": "复杂任务执行：规划、代码生成、多步工具调用等深度工作。",
    },
    {
        "tier": "sonnet",
        "name": "Sonnet（均衡）",
        "description": "后台常规任务：记忆整合、日记生成、摘要提炼。",
    },
    {
        "tier": "haiku",
        "name": "Haiku（轻量）",
        "description": "情感抽取层：把用户消息解析为情感/事件评估，快速、低成本。",
    },
]

# Subagent 模型选择说明
SUBAGENT_NOTE = (
    "Subagent（子代理）的模型由主 Agent 根据任务需求自行选择，不在此四档内固定设置。"
)

# 档位标识白名单
VALID_TIERS = frozenset(t["tier"] for t in MODEL_TIERS)

# 抽取层默认使用的档位
EXTRACTION_TIER = "haiku"


def ensure_tier_configs(db: Session) -> None:
    """确保四档等级配置行存在（幂等）。"""
    existing = {row.tier for row in db.query(ModelTierConfig).all()}
    missing = [t for t in VALID_TIERS if t not in existing]
    if missing:
        for tier in missing:
            db.add(ModelTierConfig(tier=tier, provider="", model=""))
        db.commit()
        logger.bind(event="model_tier_seeded", module="model_tier", tiers=missing).info(
            "已初始化模型等级配置"
        )


def get_tier_configs(db: Session) -> List[Dict[str, Any]]:
    """返回四档等级配置（含用途说明与绑定模型）。"""
    ensure_tier_configs(db)
    rows = {row.tier: row for row in db.query(ModelTierConfig).all()}
    result = []
    for meta in MODEL_TIERS:
        row = rows.get(meta["tier"])
        result.append({
            "tier": meta["tier"],
            "name": meta["name"],
            "description": meta["description"],
            "provider": (row.provider or "") if row else "",
            "model": (row.model or "") if row else "",
        })
    return result


def set_tier_config(
    db: Session,
    tier: str,
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """设置某档位绑定的 provider/model。"""
    if tier not in VALID_TIERS:
        raise ValueError(f"未知档位: {tier}")
    ensure_tier_configs(db)
    row = db.query(ModelTierConfig).filter(ModelTierConfig.tier == tier).first()
    if row is None:
        row = ModelTierConfig(tier=tier)
        db.add(row)
    if provider is not None:
        row.provider = provider.strip()
    if model is not None:
        row.model = model.strip()
    db.commit()
    logger.bind(event="model_tier_updated", module="model_tier", tier=tier).info(
        f"模型等级 {tier} 已设置为 {row.provider}/{row.model}"
    )
    return {"tier": tier, "provider": row.provider, "model": row.model}


def resolve_tier_llm_config(db: Session, tier: str) -> Dict[str, Any]:
    """
    解析某档位的 LLM 调用配置（provider/model/api_key/api_endpoint）。

    优先使用该档位绑定的 provider/model；未显式指定时回退到默认模型配置。

    Raises:
        RuntimeError: 未解析到模型配置或可用的 API Key——配置缺失是显式失败。
    """
    from billing.pricing_manager import PricingManager
    from config.security import decrypt_secret_value

    if tier not in VALID_TIERS:
        raise ValueError(f"未知档位: {tier}")

    ensure_tier_configs(db)
    row = db.query(ModelTierConfig).filter(ModelTierConfig.tier == tier).first()
    provider = (row.provider or "").strip() if row else ""
    model = (row.model or "").strip() if row else ""

    pricing_manager = PricingManager(db)
    config = None
    if provider and model:
        config = pricing_manager.get_configuration_by_provider_model(provider, model)
    if not config:
        config = pricing_manager.get_default_configuration()
    if not config:
        raise RuntimeError(f"档位 {tier} 未解析到任何模型配置（DB 无默认模型）")

    provider = provider or config.provider
    model = model or config.model
    api_endpoint = getattr(config, "api_endpoint", None) or ""

    # 解密 API Key：优先 ModelConfiguration.api_key，其次 ProviderCredential
    raw_key = getattr(config, "api_key", "") or ""
    api_key = ""
    cred = None
    try:
        cred = pricing_manager.get_provider_credential(provider)
    except Exception as exc:
        logger.warning(f"模型等级 {tier} 解析 ProviderCredential 失败 provider={provider}: {exc}")
    if raw_key and not raw_key.startswith("enc:"):
        api_key = decrypt_secret_value(raw_key)
    if not api_key and cred and cred.api_key and not cred.api_key.startswith("enc:"):
        api_key = decrypt_secret_value(cred.api_key)
    if not api_endpoint and cred and getattr(cred, "api_endpoint", None):
        api_endpoint = cred.api_endpoint

    if not api_key:
        raise RuntimeError(f"档位 {tier} 模型 {provider}/{model} 未解析到可用 API Key")

    return {
        "provider": provider,
        "model": model,
        "api_key": api_key,
        "api_endpoint": api_endpoint,
        "max_tokens": getattr(config, "max_tokens", None),
    }