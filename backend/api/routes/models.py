"""
模型管理路由，提供 Ollama 本地模型发现、提供商连接状态、故障转移与延迟监控接口。
同时提供 LLM Registry（注册中心）、任务路由配置和用量统计接口。
"""

import asyncio
import threading
from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field
from sqlalchemy import func

from api.dependencies import get_current_user, get_db
from core.litellm_adapter import litellm_check_provider_connection, litellm_list_models
from core.failover import get_failover_manager
from config.settings import settings
from billing.pricing_manager import PricingManager
from billing.models import ModelConfiguration
from db.models import LLMUsage, User, VectorModelConfig
from sqlalchemy.orm import Session

router = APIRouter(prefix="/api/models", tags=["models"])


@router.get("/ollama")
async def get_ollama_models(current_user=Depends(get_current_user)) -> Dict[str, Any]:
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
) -> Dict[str, Any]:
    """
    获取所有已配置的模型提供商列表及其连接状态。
    遍历数据库中的提供商配置，逐个检测连通性。
    """
    logger.bind(event="providers_status", module="models").info("checking providers status")

    pricing_manager = PricingManager(db)

    # 从数据库获取所有不同的 provider 配置
    configs = db.query(ModelConfiguration).filter(
        ModelConfiguration.is_active
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
    from config.security import decrypt_secret_value
    for provider_id, config in seen_providers.items():
        base_url = config.api_endpoint or getattr(config, 'base_url', None) or ""

        # 优先从 ProviderCredential 获取 API Key（单一来源，与 billing 路由保持一致）
        raw_key = ""
        api_endpoint_from_cred = None
        credential = pricing_manager.get_provider_credential(provider_id)
        if credential:
            api_endpoint_from_cred = credential.api_endpoint
            raw_key = credential.api_key or ""
        # 降级到 ModelConfiguration 的 api_key 字段（legacy）
        if not raw_key:
            raw_key = config.api_key or ""

        # 解密 API Key：旧算法密文（enc: 前缀）已失效，跳过解密
        api_key = ""
        if raw_key and not raw_key.startswith("enc:"):
            api_key = decrypt_secret_value(raw_key)

        # 凭据中的 endpoint 优先级高于 ModelConfiguration
        effective_base_url = api_endpoint_from_cred or base_url

        status = await litellm_check_provider_connection(provider=provider_id, api_base=effective_base_url, api_key=api_key)
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
) -> Dict[str, Any]:
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
) -> Dict[str, Any]:
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
) -> Dict[str, Any]:
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
) -> Dict[str, Any]:
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
) -> Dict[str, Any]:
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
) -> Dict[str, Any]:
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
# 并发安全：使用 asyncio.Lock 保护并发写入，防止多请求并发更新读到中间状态
_task_routing_rules: dict = {}
_task_routing_rules_lock = asyncio.Lock()


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
) -> Dict[str, Any]:
    """
    获取已注册的 LLM Provider 列表。
    从数据库 model_configurations 表中提取所有活跃的提供商及其模型。
    """
    # 查询所有活跃的模型配置
    configs = (
        db.query(ModelConfiguration)
        .filter(ModelConfiguration.is_active)
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
) -> Dict[str, Any]:
    """
    配置指定任务类型的 LLM 路由规则。
    路由规则按优先级排序，客户端在调用时根据 task_type 选择对应规则链。
    """
    # 按 priority 排序规则列表
    sorted_rules = sorted(request.rules, key=lambda r: r.get("priority", 99))
    # 加锁保护并发写入，防止多请求同时更新不同 task_type 时读到中间状态
    async with _task_routing_rules_lock:
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
) -> Dict[str, Any]:
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
) -> Dict[str, Any]:
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
                func.case((LLMUsage.success, 1), else_=0)
            ).label("success_count"),
            func.sum(
                func.case((not LLMUsage.success, 1), else_=0)
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


# ===========================================================================
# 向量模型管理与配置（Spec memory-model-config-chain）
# 端点前缀：/api/models/vector/*
# ===========================================================================


class DownloadState:
    """进程内下载状态：单模型同时只允许一个下载任务。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tasks: dict = {}

    def start(self, key: str) -> bool:
        with self._lock:
            if key in self._tasks:
                return False
            self._tasks[key] = {"status": "downloading", "progress": 0.0, "error": None}
            return True

    def finish(self, key: str, error: Optional[str] = None) -> None:
        with self._lock:
            self._tasks[key] = {
                "status": "failed" if error else "completed",
                "progress": 100.0 if not error else 0.0,
                "error": error,
            }

    def list(self) -> List[dict]:
        with self._lock:
            return [dict(v) for v in self._tasks.values()]


download_states = DownloadState()


class ModelDownloadRequest(BaseModel):
    """模型下载请求体。"""

    model: str = Field(..., description="注册表内模型名")
    kind: str = Field(default="embedding", description="模型类型：embedding | rerank")


class VectorModelConfigRequest(BaseModel):
    """向量模型配置请求体（全部可选，仅更新提供的字段）。"""

    embedding_provider: Optional[str] = None  # local | cloud | hash
    embedding_model: Optional[str] = None
    embedding_api_key: Optional[str] = None
    embedding_api_endpoint: Optional[str] = None
    rerank_provider: Optional[str] = None  # local | cloud | off
    rerank_model: Optional[str] = None
    rerank_api_key: Optional[str] = None
    rerank_api_endpoint: Optional[str] = None
    model_download_source: Optional[str] = None  # modelscope | huggingface


def model_downloaded_path(modelscope_id: str) -> bool:
    """检查本地模型是否已下载（缓存目录存在 config.json 即视为已下载）。"""
    from config.runtime_paths import DATA_DIR

    models_dir = DATA_DIR / "models"
    normalized = modelscope_id.replace("/", "--")
    hf_org = modelscope_id.split("/")[0] if "/" in modelscope_id else "sentence-transformers"
    candidates = (
        models_dir / "sentence_transformers" / f"models--{hf_org}--{normalized}" / "snapshots",
        models_dir / "modelscope" / "models" / modelscope_id,
    )
    for base in candidates:
        if not base.is_dir():
            continue
        if base.name == "snapshots":
            for snapshot in base.iterdir():
                if (snapshot / "config.json").is_file():
                    return True
        elif (base / "config.json").is_file():
            return True
    return False


def build_vector_registry() -> List[dict]:
    """构建注册表响应：嵌入 + 重排模型，附下载状态。"""
    from memory.model_registry import EMBEDDING_MODELS, RERANK_MODELS

    items: List[dict] = []
    for spec in EMBEDDING_MODELS.values():
        items.append({
            "name": spec.name,
            "kind": spec.kind,
            "label": spec.label,
            "description": spec.description,
            "model_type": "embedding",
            "dimension": spec.dimension,
            "capabilities": spec.capabilities,
            "downloaded": spec.kind == "cloud" or model_downloaded_path(spec.modelscope_id),
        })
    for spec in RERANK_MODELS.values():
        items.append({
            "name": spec.name,
            "kind": spec.kind,
            "label": spec.label,
            "description": spec.description,
            "model_type": "rerank",
            "dimension": None,
            "capabilities": spec.capabilities,
            "downloaded": spec.kind == "cloud" or model_downloaded_path(spec.modelscope_id),
        })
    return items


def download_model_sync(model_name: str, modelscope_id: str, huggingface_id: str) -> None:
    """同步执行模型下载（线程池中运行）：默认 ModelScope → HuggingFace 降级。"""
    source = (settings.MODEL_DOWNLOAD_SOURCE or "modelscope").strip().lower()
    if source == "huggingface":
        try:
            from huggingface_hub import snapshot_download

            snapshot_download(huggingface_id)
            return
        except Exception as exc:
            logger.warning(f"HuggingFace 下载失败，降级 ModelScope: {exc}")
    try:
        from modelscope import snapshot_download

        snapshot_download(modelscope_id)
        return
    except Exception as exc:
        if source == "modelscope":
            logger.warning(f"ModelScope 下载失败，降级 HuggingFace: {exc}")
            try:
                from huggingface_hub import snapshot_download

                snapshot_download(huggingface_id)
                return
            except Exception as hf_exc:
                raise RuntimeError(
                    f"模型 {model_name} 下载失败（ModelScope 与 HuggingFace 均失败）: {hf_exc}"
                ) from hf_exc
        raise RuntimeError(f"模型 {model_name} 下载失败: {exc}") from exc


@router.get("/vector/registry")
async def get_vector_model_registry(
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Spec memory-model-config-chain：注册表 + 下载状态。"""
    return {"success": True, "data": {"models": build_vector_registry()}}


@router.post("/vector/download")
async def download_vector_model(
    request: ModelDownloadRequest,
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Spec memory-model-config-chain：触发模型下载（后台任务不阻塞请求）。"""
    from memory.model_registry import get_embedding_spec, get_rerank_spec

    model_name = request.model.strip()
    kind = request.kind.strip().lower()

    spec = get_embedding_spec(model_name) if kind == "embedding" else get_rerank_spec(model_name)
    if spec is None or spec.kind != "local":
        raise HTTPException(
            status_code=404,
            detail=f"模型 {model_name} 不在本地注册表中（kind={kind}）",
        )

    task_key = f"{kind}:{model_name}"
    if not download_states.start(task_key):
        raise HTTPException(status_code=409, detail=f"模型 {model_name} 正在下载中")

    async def _run_download() -> None:
        try:
            await asyncio.to_thread(
                download_model_sync, model_name, spec.modelscope_id, spec.huggingface_id
            )
            download_states.finish(task_key)
        except Exception as exc:
            logger.opt(exception=True).error(f"模型下载失败 {model_name}: {exc}")
            download_states.finish(task_key, error=str(exc))

    asyncio.create_task(_run_download())
    return {"success": True, "message": f"模型 {model_name} 下载任务已启动", "task": task_key}


@router.get("/vector/download/status")
async def get_vector_download_status(
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Spec memory-model-config-chain：下载进度查询。"""
    return {"success": True, "data": {"tasks": download_states.list()}}


@router.get("/vector/config")
async def get_vector_model_config(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Spec memory-model-config-chain：读取当前生效配置（DB 叠加 settings）。"""
    rows = db.query(VectorModelConfig).all()
    stored = {row.key: row.value for row in rows}
    resolved = {
        "embedding_provider": stored.get("embedding_provider") or settings.MEMORY_EMBEDDING_PROVIDER or "auto",
        "embedding_model": stored.get("embedding_model") or settings.MEMORY_EMBEDDING_MODEL or "",
        "embedding_api_key": stored.get("embedding_api_key") or settings.MEMORY_EMBEDDING_API_KEY or "",
        "embedding_api_endpoint": stored.get("embedding_api_endpoint") or settings.MEMORY_EMBEDDING_API_ENDPOINT or "",
        "rerank_provider": stored.get("rerank_provider") or settings.MEMORY_RERANK_PROVIDER or "off",
        "rerank_model": stored.get("rerank_model") or settings.MEMORY_RERANK_MODEL or "",
        "rerank_api_key": stored.get("rerank_api_key") or settings.MEMORY_RERANK_API_KEY or "",
        "rerank_api_endpoint": stored.get("rerank_api_endpoint") or settings.MEMORY_RERANK_API_ENDPOINT or "",
        "model_download_source": stored.get("model_download_source") or settings.MODEL_DOWNLOAD_SOURCE or "modelscope",
    }
    return {"success": True, "data": resolved}


@router.put("/vector/config")
async def update_vector_model_config(
    request: VectorModelConfigRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Spec memory-model-config-chain：写入配置（key-value 持久化，API Key 密文存储）。"""
    from config.security import encrypt_secret_value

    secret_keys = {"embedding_api_key", "rerank_api_key"}
    payload = request.model_dump(exclude_unset=True)
    for key, value in payload.items():
        if value is None:
            continue
        stored_value = str(value)
        if key in secret_keys and stored_value and not stored_value.startswith("enc:"):
            stored_value = encrypt_secret_value(stored_value)
        row = db.query(VectorModelConfig).filter(VectorModelConfig.key == key).first()
        if row is None:
            row = VectorModelConfig(key=key, value=stored_value)
            db.add(row)
        else:
            row.value = stored_value
    db.commit()

    logger.info(f"向量模型配置已更新: {sorted(payload.keys())}")
    return {"success": True, "message": "向量模型配置已更新"}
