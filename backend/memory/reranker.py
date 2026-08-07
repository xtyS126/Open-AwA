"""
记忆检索重排器（Spec memory-model-config-chain）。

在混合检索（BM25 + 向量）融合排序后，对候选记忆做二次相关性重排：
- 本地重排：CrossEncoder 交叉编码器（默认 ms-marco-MiniLM-L6-v2，
  可切换 bge-reranker-v2-m3 等），模型经 ModelScope 默认下载链加载
- 云端重排：OpenAI 兼容 rerank API（支持 Qwen3-VL-Reranker 多模态），
  请求结构 {model, query, documents} → {results: [{index, relevance_score}]}

重排为可选阶段：未配置（MEMORY_RERANK_PROVIDER=off/空）时不启用；
一旦显式配置，加载或调用失败直接抛错，检索不静默退回融合排序。
"""

from __future__ import annotations

import asyncio
import os
from typing import Dict, List, Optional, Protocol

import httpx
from loguru import logger

from config.runtime_paths import DATA_DIR


def _get_models_dir() -> str:
    """模型统一存储目录（与 vector_store_manager 保持一致）。"""
    models_dir = DATA_DIR / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    return str(models_dir)


_MODELS_DIR = _get_models_dir()
os.environ.setdefault("MODELSCOPE_CACHE", os.path.join(_MODELS_DIR, "modelscope"))
os.environ.setdefault("HF_HOME", os.path.join(_MODELS_DIR, "huggingface"))


class Reranker(Protocol):
    """重排器协议：对 query 与候选文档列表打分。"""

    provider_name: str

    async def rerank(self, query: str, documents: List[str]) -> List[float]:
        """返回与 documents 等长的相关性分数列表（分数越高越相关）。"""


class LocalCrossEncoderReranker:
    """
    基于 sentence-transformers CrossEncoder 的本地重排器。

    模型下载策略与嵌入模型一致：本地缓存命中优先，未命中时按
    MODEL_DOWNLOAD_SOURCE 指定的唯一下载源下载，主源失败直接抛错。
    """

    provider_name = "local-cross-encoder"

    def __init__(self, model_name: str = "ms-marco-MiniLM-L6-v2"):
        try:
            from sentence_transformers import CrossEncoder
        except ImportError as exc:
            raise RuntimeError("未安装 sentence-transformers，无法启用本地重排") from exc

        self.model_name = model_name
        self._model = None  # 延迟加载
        self._CrossEncoder = CrossEncoder

        from memory.model_registry import get_rerank_spec

        spec = get_rerank_spec(model_name)
        self._modelscope_id = (spec.modelscope_id if spec else "") or (
            f"cross-encoder/{model_name}"
        )
        self._huggingface_id = (spec.huggingface_id if spec else "") or model_name

    def _find_cached_model_path(self) -> Optional[str]:
        """查找已下载的模型快照（HF 风格 models--<org>--<name> 与 ModelScope hub 布局）。"""
        normalized_name = self.model_name.replace("/", "--")
        hf_org = self._huggingface_id.split("/")[0] if "/" in self._huggingface_id else "cross-encoder"
        candidates = (
            os.path.join(
                _MODELS_DIR,
                "sentence_transformers",
                f"models--{hf_org}--{normalized_name}",
                "snapshots",
            ),
            os.path.join(
                _MODELS_DIR,
                "huggingface",
                "hub",
                f"models--{hf_org}--{normalized_name}",
                "snapshots",
            ),
            os.path.join(
                _MODELS_DIR,
                "modelscope",
                "models",
                self._modelscope_id,
            ),
        )
        for snapshots_dir in candidates:
            if not os.path.isdir(snapshots_dir):
                continue
            if "snapshots" in snapshots_dir:
                for snapshot_name in sorted(os.listdir(snapshots_dir), reverse=True):
                    snapshot_path = os.path.join(snapshots_dir, snapshot_name)
                    if os.path.isfile(os.path.join(snapshot_path, "config.json")):
                        return snapshot_path
            else:
                if os.path.isfile(os.path.join(snapshots_dir, "config.json")):
                    return snapshots_dir
        return None

    def _download_from_modelscope(self) -> str:
        """从魔搭社区下载模型，失败直接抛错，不降级到其他下载源。"""
        try:
            from modelscope import snapshot_download
        except ImportError as exc:
            raise RuntimeError(
                "下载源为 modelscope，但未安装 modelscope 包，"
                "请执行 pip install modelscope"
            ) from exc
        try:
            local_path = snapshot_download(self._modelscope_id)
        except Exception as exc:
            raise RuntimeError(
                f"从魔搭社区下载重排模型失败 ({self._modelscope_id}): {exc}"
            ) from exc
        logger.info(f"从魔搭社区下载重排模型成功: {self._modelscope_id}")
        return str(local_path)

    def _download_from_huggingface(self) -> str:
        """从 HuggingFace 下载模型，失败直接抛错，不降级到其他下载源。"""
        try:
            from huggingface_hub import snapshot_download as hf_snapshot_download
        except ImportError as exc:
            raise RuntimeError(
                "下载源为 huggingface，但未安装 huggingface_hub 包，"
                "请执行 pip install huggingface_hub"
            ) from exc
        try:
            local_path = hf_snapshot_download(self._huggingface_id)
        except Exception as exc:
            raise RuntimeError(
                f"从 HuggingFace 下载重排模型失败 ({self._huggingface_id}): {exc}"
            ) from exc
        logger.info(f"从 HuggingFace 下载重排模型成功: {self._huggingface_id}")
        return str(local_path)

    def _ensure_model(self):
        """延迟加载模型：本地缓存命中优先，未命中时按配置的唯一下载源下载。"""
        if self._model is not None:
            return

        _cache_dir = os.path.join(_MODELS_DIR, "sentence_transformers")
        os.makedirs(_cache_dir, exist_ok=True)

        cached_model_path = self._find_cached_model_path()
        if cached_model_path:
            self._model = self._CrossEncoder(cached_model_path)
            logger.info(f"从本地缓存加载重排模型成功: {self.model_name}")
            return

        from config.settings import settings as _settings

        preferred_source = (_settings.MODEL_DOWNLOAD_SOURCE or "modelscope").strip().lower()
        if preferred_source not in {"modelscope", "huggingface"}:
            raise ValueError(f"未知的模型下载源: {preferred_source}")
        downloader = (
            self._download_from_modelscope
            if preferred_source == "modelscope"
            else self._download_from_huggingface
        )
        local_path = downloader()
        self._model = self._CrossEncoder(local_path)
        logger.info(
            f"从 {preferred_source} 下载并加载重排模型成功: {self.model_name}"
        )

    async def rerank(self, query: str, documents: List[str]) -> List[float]:
        """对候选文档打分（CPU 推理放线程池）。"""
        if not documents:
            return []
        self._ensure_model()
        pairs = [[query, doc] for doc in documents]
        scores = await asyncio.to_thread(self._model.predict, pairs)
        # 归一化到 0-1（sigmod 风格），保持与云端分数可比
        return [max(0.0, min(1.0, float(score))) for score in scores]


class CloudReranker:
    """
    基于 OpenAI 兼容 rerank API 的云端重排器。

    支持 Qwen3-VL-Reranker 等多模态重排模型：documents 元素可为字符串
    或多模态内容对象（{"content": [{"type": "text"|"image_url", ...}]}）。
    响应结构兼容 {results: [{index, relevance_score}]}。
    """

    provider_name = "cloud-rerank"

    def __init__(
        self,
        api_key: str,
        model: str = "Qwen3-VL-Reranker",
        endpoint: str = "",
        timeout: float = 60.0,
    ):
        self.api_key = api_key
        self.model = model
        # 默认 endpoint 语义为 DashScope 文本重排接口；可通过配置覆盖
        self.endpoint = endpoint or (
            "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank"
        )
        self.timeout = timeout

    async def rerank(self, query: str, documents: List[str]) -> List[float]:
        """对候选文档打分。调用失败直接抛错，不允许重排阶段被静默跳过。"""
        if not documents:
            return []
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.endpoint,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "query": query,
                    "documents": documents,
                },
                timeout=self.timeout,
            )
        response.raise_for_status()
        payload = response.json()
        results = payload.get("results") or payload.get("data")
        if not isinstance(results, list):
            raise RuntimeError(
                f"云端重排响应缺少 results/data 字段: {str(payload)[:200]}"
            )
        scored: Dict[int, float] = {}
        for item in results:
            idx = item.get("index")
            score = item.get("relevance_score", item.get("score"))
            if isinstance(idx, int) and isinstance(score, (int, float)):
                scored[idx] = float(score)
        return [scored.get(i, 0.0) for i in range(len(documents))]


def create_reranker(provider_type: Optional[str] = None) -> Optional[Reranker]:
    """
    根据配置创建重排器；未配置或配置为 off 时返回 None（跳过重排）。

    优先级：
    1. 显式 provider_type（local | cloud | off）
    2. settings.MEMORY_RERANK_PROVIDER
    3. 空 = 关闭重排（默认）
    """
    from config.settings import settings as _settings
    from memory.model_registry import default_rerank_model, get_rerank_spec

    normalized = str(provider_type or _settings.MEMORY_RERANK_PROVIDER or "").strip().lower()
    if normalized in {"", "off", "none", "disabled"}:
        return None

    model_name = (_settings.MEMORY_RERANK_MODEL or "").strip()
    spec = get_rerank_spec(model_name) if model_name else None
    if spec is not None and normalized not in {"local", "cloud"}:
        normalized = spec.kind

    if normalized in {"local", "sentence-transformers", "cross-encoder"}:
        local_model = model_name or default_rerank_model("local")
        # Spec 模型进程化：本地重排模型在独立子进程加载（空闲自动卸载）；
        # 模型服务启用时启动/推理失败直接抛错，不回退主进程内加载
        if bool(_settings.MODEL_SERVICE_ENABLED):
            from model_service.client import (
                RemoteReranker,
                get_model_service_client,
            )

            client = get_model_service_client()
            client.configure(rerank_model=local_model)
            logger.info(f"本地重排模型切换到模型服务进程: {local_model}")
            return RemoteReranker(client)
        # 未开启模型服务时主进程内加载；依赖缺失或模型加载失败时直接抛错
        return LocalCrossEncoderReranker(model_name=local_model)

    if normalized in {"cloud", "api"}:
        api_key = _settings.MEMORY_RERANK_API_KEY or ""
        if not api_key:
            raise ValueError(
                "云端重排已启用但未配置 MEMORY_RERANK_API_KEY"
            )
        cloud_model = model_name or default_rerank_model("cloud")
        return CloudReranker(
            api_key=api_key,
            model=cloud_model,
            endpoint=_settings.MEMORY_RERANK_API_ENDPOINT or "",
        )

    raise ValueError(f"未知的重排提供方类型: {normalized}")
