"""
向量存储管理模块，负责长期记忆的向量化存储与语义检索。
默认使用 Qdrant 嵌入式模式作为持久化后端，原生支持 dense + sparse 混合检索。
根据环境自动选择可用的嵌入提供方，并保留哈希嵌入作为兜底。
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import hashlib
import math
import os
import re
import threading
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Protocol

import httpx
from loguru import logger
from qdrant_client import QdrantClient, models

from config.runtime_paths import DATA_DIR
from config.settings import settings

# 模型下载统一存储到项目根 var/data/models/ 目录，不散落到系统各处。
def _get_models_dir() -> str:
    models_dir = DATA_DIR / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    return str(models_dir)

_MODELS_DIR = _get_models_dir()
os.environ.setdefault("MODELSCOPE_CACHE", os.path.join(_MODELS_DIR, "modelscope"))
os.environ.setdefault("HF_HOME", os.path.join(_MODELS_DIR, "huggingface"))
# 离线模式：跳过 huggingface.co 远程检查，避免网络不可达时启动卡顿 30s+
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")


DEFAULT_COLLECTION_NAME = "long_term_memory"
DEFAULT_HASH_DIMENSION = 32

# Qdrant 命名向量字段
DENSE_VECTOR_NAME = "dense"
SPARSE_VECTOR_NAME = "sparse"

# 稀疏向量哈希空间大小（2^16），平衡碰撞率与索引内存占用
SPARSE_HASH_SPACE = 65536

# 中英文混合分词正则：英文单词 / 单个中文字符 / 数字串
_TOKEN_RE = re.compile(r"[a-zA-Z]+|[一-鿿]|\d+")


class EmbeddingProvider(Protocol):
    """
    嵌入提供方协议，统一不同向量化实现的调用方式。
    """

    provider_name: str

    async def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """
        批量生成文本嵌入向量。
        """


@dataclass
class VectorSearchHit:
    """
    向量检索结果项。
    """

    memory_id: int
    score: float
    content: str
    metadata: Dict[str, Any]


class HashEmbeddingProvider:
    """
    轻量哈希嵌入提供方。
    主要用于开发、测试以及缺少外部模型依赖时的兜底场景。
    """

    provider_name = "hash"

    def __init__(self, dimension: int = DEFAULT_HASH_DIMENSION):
        self.dimension = dimension

    def _embed_single(self, text: str) -> List[float]:
        raw = (text or "").encode("utf-8")
        digest = hashlib.sha256(raw).digest()
        values: List[float] = []

        while len(values) < self.dimension:
            for byte in digest:
                values.append((byte / 255.0) * 2.0 - 1.0)
                if len(values) >= self.dimension:
                    break
            digest = hashlib.sha256(digest + raw).digest()

        norm = math.sqrt(sum(value * value for value in values)) or 1.0
        return [value / norm for value in values]

    async def embed_texts(self, texts: List[str]) -> List[List[float]]:
        return [self._embed_single(text) for text in texts]


class OpenAIEmbeddingProvider:
    """
    基于 OpenAI Embeddings API 的嵌入提供方。
    """

    provider_name = "openai"

    def __init__(
        self,
        api_key: str,
        model: str = "text-embedding-3-small",
        endpoint: str = "https://api.openai.com/v1/embeddings",
        timeout: float = 20.0,
    ):
        self.api_key = api_key
        self.model = model
        self.endpoint = endpoint
        self.timeout = timeout

    async def embed_texts(self, texts: List[str]) -> List[List[float]]:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.endpoint,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "input": texts,
                },
                timeout=self.timeout,
            )
        response.raise_for_status()
        payload = response.json()
        data = sorted(payload.get("data", []), key=lambda item: item.get("index", 0))
        return [item.get("embedding", []) for item in data]


class CloudEmbeddingProvider:
    """
    基于 OpenAI 兼容 Embeddings API 的云端嵌入提供方。

    支持多模态模型（如 Qwen3-VL-Embedding，DashScope / vLLM 兼容接口）：
    input 数组元素可为纯文本字符串，或含图像的多模态对象
    （{"content": [{"type": "text", "text": "..."}, {"type": "image_url", "image_url": {"url": "..."}}]}）。
    """

    provider_name = "cloud"

    def __init__(
        self,
        api_key: str,
        model: str = "text-embedding-3-small",
        endpoint: str = "",
        timeout: float = 60.0,
    ):
        self.api_key = api_key
        self.model = model
        self.endpoint = endpoint or "https://api.openai.com/v1/embeddings"
        self.timeout = timeout

    @property
    def dimension(self) -> Optional[int]:
        """云端模型维度未知，由 collection 探测决定。"""
        return None

    async def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """文本嵌入（OpenAI 兼容：input 为字符串数组）。"""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.endpoint,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "input": texts,
                },
                timeout=self.timeout,
            )
        response.raise_for_status()
        payload = response.json()
        data = sorted(payload.get("data", []), key=lambda item: item.get("index", 0))
        return [item.get("embedding", []) for item in data]

    async def embed_inputs(self, inputs: List[Any]) -> List[List[float]]:
        """
        多模态嵌入：input 元素可为字符串或多模态内容对象。
        纯文本场景与 embed_texts 行为一致；多模态场景（Qwen3-VL-Embedding）
        由服务端（DashScope / vLLM）按 OpenAI 兼容格式解析。
        """
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.endpoint,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "input": inputs,
                },
                timeout=self.timeout,
            )
        response.raise_for_status()
        payload = response.json()
        data = sorted(payload.get("data", []), key=lambda item: item.get("index", 0))
        return [item.get("embedding", []) for item in data]


class SentenceTransformerEmbeddingProvider:
    """
    基于 sentence-transformers 的本地嵌入提供方。

    模型下载策略（Spec memory-model-config-chain）：默认优先从魔搭社区
    （ModelScope）下载（国内网络友好），失败后降级 HuggingFace，最后兜底
    本地缓存；下载源可通过 MODEL_DOWNLOAD_SOURCE 切换为 huggingface。
    """

    provider_name = "sentence-transformers"

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError("未安装 sentence-transformers，无法启用本地向量模式") from exc

        self.model_name = model_name
        self._model = None  # 延迟加载
        self._SentenceTransformer = SentenceTransformer
        # 按注册表解析 ModelScope / HuggingFace 仓库 ID
        from memory.model_registry import get_embedding_spec

        spec = get_embedding_spec(model_name)
        self._modelscope_id = (spec.modelscope_id if spec else "") or (
            f"sentence-transformers/{model_name}"
        )
        self._huggingface_id = (spec.huggingface_id if spec else "") or model_name

    @property
    def dimension(self) -> Optional[int]:
        """本地模型维度由注册表提供，未注册模型返回 None（运行时探测）。"""
        from memory.model_registry import get_embedding_spec

        spec = get_embedding_spec(self.model_name)
        return spec.dimension if spec else None

    def _try_download_from_modelscope(self) -> Optional[str]:
        """
        尝试从魔搭社区下载模型，返回本地路径。
        下载失败时返回 None。
        """
        try:
            from modelscope import snapshot_download
        except ImportError:
            logger.debug("modelscope 未安装，跳过魔搭社区下载")
            return None

        try:
            local_path = snapshot_download(self._modelscope_id)
            logger.info(f"从魔搭社区下载模型成功: {self._modelscope_id} -> {local_path}")
            return local_path
        except Exception as exc:
            logger.warning(f"从魔搭社区下载模型失败 ({self._modelscope_id}): {exc}")
            return None

    def _try_download_from_huggingface(self) -> Optional[str]:
        """
        尝试从 HuggingFace 下载模型，返回本地路径。
        下载失败时返回 None。
        """
        try:
            from huggingface_hub import snapshot_download as hf_snapshot_download
        except ImportError:
            logger.debug("huggingface_hub 未安装，跳过 HuggingFace 下载")
            return None

        try:
            local_path = hf_snapshot_download(self._huggingface_id)
            logger.info(f"从 HuggingFace 下载模型成功: {self._huggingface_id} -> {local_path}")
            return local_path
        except Exception as exc:
            logger.warning(f"从 HuggingFace 下载模型失败 ({self._huggingface_id}): {exc}")
            return None

    def _find_cached_model_path(self) -> Optional[str]:
        """
        查找项目模型目录中已完整下载的模型快照，优先完全离线加载。

        兼容两类缓存布局：
        1. sentence_transformers 目录（models--<org>--<name> 布局，HF 风格）
        2. modelscope 缓存目录（hub/<org>/<name> 布局）
        """
        normalized_name = self.model_name.replace("/", "--")
        hf_org = self._huggingface_id.split("/")[0] if "/" in self._huggingface_id else "sentence-transformers"
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
                # HF 风格：snapshots/<hash>/config.json
                for snapshot_name in sorted(os.listdir(snapshots_dir), reverse=True):
                    snapshot_path = os.path.join(snapshots_dir, snapshot_name)
                    if os.path.isfile(os.path.join(snapshot_path, "config.json")):
                        return snapshot_path
            else:
                # ModelScope 风格：hub/<org>/<name>/ 下直接是模型文件
                if os.path.isfile(os.path.join(snapshots_dir, "config.json")):
                    return snapshots_dir
        return None

    def _ensure_model(self):
        """
        延迟初始化模型，按优先级尝试加载（Spec memory-model-config-chain）：
        1. 本地缓存（离线优先）
        2. 默认下载源 ModelScope（国内网络友好），失败后降级 HuggingFace
        （MODEL_DOWNLOAD_SOURCE=huggingface 时交换 2/3 顺序）
        """
        if self._model is not None:
            return

        # 使用项目内的模型缓存目录，避免每次重启重复下载
        _cache_dir = os.path.join(_MODELS_DIR, "sentence_transformers")
        os.makedirs(_cache_dir, exist_ok=True)

        cached_model_path = self._find_cached_model_path()
        if cached_model_path:
            self._model = self._SentenceTransformer(cached_model_path, cache_folder=_cache_dir)
            logger.info(f"从本地缓存加载嵌入模型成功: {self.model_name} -> {cached_model_path}")
            return

        from config.settings import settings as _settings

        preferred_source = (_settings.MODEL_DOWNLOAD_SOURCE or "modelscope").strip().lower()
        downloaders = [
            ("modelscope", self._try_download_from_modelscope),
            ("huggingface", self._try_download_from_huggingface),
        ]
        if preferred_source != "modelscope":
            # 显式切到 HuggingFace 优先
            downloaders.reverse()

        for source_name, downloader in downloaders:
            local_path = downloader()
            if local_path:
                self._model = self._SentenceTransformer(local_path, cache_folder=_cache_dir)
                logger.info(
                    f"从 {source_name} 下载并加载嵌入模型成功: {self.model_name} -> {local_path}"
                )
                return

        raise RuntimeError(
            f"无法加载模型 {self.model_name}，ModelScope 和 HuggingFace 均下载失败。"
            f"请检查网络连接，或安装 modelscope: pip install modelscope"
        )

    async def embed_texts(self, texts: List[str]) -> List[List[float]]:
        self._ensure_model()
        # CPU 密集型推理，放到线程池避免阻塞事件循环
        vectors = await asyncio.to_thread(self._model.encode, texts, normalize_embeddings=True)
        return [list(map(float, vector)) for vector in vectors.tolist()]


def create_embedding_provider(provider_type: Optional[str] = None) -> EmbeddingProvider:
    """
    根据配置选择可用的嵌入提供方（Spec memory-model-config-chain）。

    配置优先级：
    1. 显式 provider_type 参数（MemoryManager 注入）
    2. settings.MEMORY_EMBEDDING_PROVIDER（local | cloud | hash | 空=自动）
    3. 注册表模型名解析：MEMORY_EMBEDDING_MODEL 指定注册表内模型时按 kind 决定

    local：sentence-transformers 本地推理（ModelScope 默认下载链）
    cloud：OpenAI 兼容 Embeddings API（支持 Qwen3-VL-Embedding 多模态）
    hash：无语义降级（开发/测试兜底）
    """
    from config.settings import settings as _settings
    from memory.model_registry import (
        default_embedding_model,
        get_embedding_spec,
    )

    normalized = str(provider_type or _settings.MEMORY_EMBEDDING_PROVIDER or "").strip().lower()
    model_name = (_settings.MEMORY_EMBEDDING_MODEL or "").strip()

    # 注册表模型名优先决定 provider 类型（云端模型名 → cloud）
    spec = get_embedding_spec(model_name) if model_name else None
    if spec is not None and not normalized:
        normalized = spec.kind

    if normalized in {"cloud", "openai"}:
        api_key = _settings.MEMORY_EMBEDDING_API_KEY or ""
        if not api_key:
            secret = _settings.OPENAI_API_KEY
            api_key = secret.get_secret_value() if secret else ""
        if not api_key:
            raise RuntimeError("云端嵌入模式已启用，但未配置 MEMORY_EMBEDDING_API_KEY 或 OPENAI_API_KEY")
        cloud_model = model_name or default_embedding_model("cloud")
        return CloudEmbeddingProvider(
            api_key=api_key,
            model=cloud_model,
            endpoint=_settings.MEMORY_EMBEDDING_API_ENDPOINT or "",
        )

    if normalized in {"hash", "simple"}:
        return HashEmbeddingProvider()

    # local（默认）与自动路径：sentence-transformers 本地推理
    local_model = model_name or (
        _settings.MEMORY_LOCAL_EMBEDDING_MODEL or default_embedding_model("local")
    )
    if normalized in {"local", "sentence-transformers"} or not normalized:
        # Spec 模型进程化：开启模型服务时本地模型在独立子进程加载推理，
        # 主进程不占模型内存（空闲自动卸载、按需加载）
        if bool(_settings.MODEL_SERVICE_ENABLED):
            try:
                from model_service.client import (
                    RemoteEmbeddingProvider,
                    get_model_service_client,
                )

                client = get_model_service_client()
                client.configure(embedding_model=local_model)
                logger.info(f"本地嵌入模型切换到模型服务进程: {local_model}")
                return RemoteEmbeddingProvider(client)
            except Exception as exc:
                logger.warning(f"模型服务不可用，回退主进程内加载: {exc}")
        try:
            return SentenceTransformerEmbeddingProvider(model_name=local_model)
        except RuntimeError as exc:
            if normalized:
                # 显式选择 local 但依赖缺失时直接报错，不静默降级
                raise
            logger.warning(
                f"sentence-transformers 不可用，自动降级到 Hash 嵌入模式；"
                f"向量检索质量将下降。原因: {exc}"
            )
            return HashEmbeddingProvider()

    raise ValueError(f"未知的嵌入提供方类型: {normalized}")


def _tokenize(text: str) -> List[str]:
    """
    中英文混合分词：小写化后提取英文单词、单个中文字符、数字串。
    用于 Qdrant 稀疏向量（BM25 风格）的构造。
    """
    if not text:
        return []
    return _TOKEN_RE.findall(text.lower())


def _hash_token(token: str) -> int:
    """
    将 token 哈希到固定大小的稀疏空间，作为 sparse vector 的索引。
    使用 sha256 前 4 字节，碰撞率可控且无需维护词表。
    """
    digest = hashlib.sha256(token.encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") % SPARSE_HASH_SPACE


def compute_sparse_vector(text: str) -> models.SparseVector:
    """
    根据文本构造 Qdrant 稀疏向量。
    使用 token 词频作为权重，Qdrant 内部基于 IDF 维护 BM25 风格的评分。

    若文本为空，返回带哨兵索引的稀疏向量（Qdrant 要求 indices/values 非空）。
    """
    tokens = _tokenize(text)
    if not tokens:
        return models.SparseVector(indices=[0], values=[0.0])

    counter: Dict[int, float] = {}
    for token in tokens:
        index = _hash_token(token)
        counter[index] = counter.get(index, 0.0) + 1.0

    # 合并相同哈希桶的权重，避免重复索引
    indices = sorted(counter.keys())
    values = [counter[i] for i in indices]
    return models.SparseVector(indices=indices, values=values)


def _probe_dimension_in_thread(provider: EmbeddingProvider) -> int:
    """
    在独立线程的事件循环中执行嵌入调用以探测维度。
    用于规避当前线程已有运行中事件循环时无法直接 run_until_complete 的问题。
    """
    loop = asyncio.new_event_loop()
    try:
        vectors = loop.run_until_complete(provider.embed_texts(["dimension_probe"]))
        if vectors and vectors[0]:
            return len(vectors[0])
    finally:
        loop.close()
    return DEFAULT_HASH_DIMENSION


def _detect_dense_dimension(provider: EmbeddingProvider) -> int:
    """
    探测嵌入提供方的向量维度，用于创建 Qdrant collection。
    优先从 provider.dimension 属性读取（HashEmbeddingProvider 等同步提供方），
    否则在独立线程中执行嵌入调用探测，避免与已运行的事件循环冲突。
    """
    # HashEmbeddingProvider 等带 dimension 属性的提供方直接读取
    dim = getattr(provider, "dimension", None)
    if isinstance(dim, int) and dim > 0:
        return dim

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_probe_dimension_in_thread, provider)
            return future.result(timeout=60)
    except Exception as exc:
        raise RuntimeError(f"探测嵌入模型维度失败，拒绝使用不确定维度创建向量库: {exc}") from exc


def _sync_vector_model_config_from_db() -> None:
    """
    将 DB vector_model_config 表配置同步到 settings（Spec memory-model-config-chain）。

    前端通过 PUT /api/models/vector/config 持久化的模型选择（embedding/rerank provider、
    模型名、API Key/Endpoint、下载源）在服务初始化时叠加到 settings 之上，
    使 MemoryManager/VectorStoreManager 创建 provider 时读到最新配置。

    DB 键（小写）映射到 settings 字段（大写前缀 MEMORY_）；同步失败仅记录警告，
    不影响向量存储初始化（回退 env 默认值）。
    """
    try:
        from db.models import SessionLocal, VectorModelConfig

        with SessionLocal() as db:
            rows = db.query(VectorModelConfig).all()
        if not rows:
            return
        for row in rows:
            field_name = f"MEMORY_{row.key.upper()}"
            if hasattr(settings, field_name):
                setattr(settings, field_name, row.value)
        logger.info(
            f"已从 DB 同步向量模型配置: {sorted(row.key for row in rows)}"
        )
    except Exception as exc:
        logger.opt(exception=True).warning(
            f"向量模型配置同步失败（回退 env 默认值）: {exc}"
        )


class VectorStoreManager:
    """
    Qdrant 向量存储封装。
    负责长期记忆的 upsert、删除、混合查询与基础统计。
    使用 Qdrant 嵌入式模式（path=...），原生支持 dense + sparse 混合检索（RRF 融合）。
    """

    def __init__(
        self,
        persist_directory: Optional[str] = None,
        collection_name: str = DEFAULT_COLLECTION_NAME,
        provider_type: Optional[str] = None,
        embedding_provider: Optional[EmbeddingProvider] = None,
    ):
        # Spec memory-model-config-chain：先同步 DB 持久化配置（vector_model_config 表）
        # 到 settings，使前端保存的模型选择在服务初始化时生效（DB 优先于 env）
        _sync_vector_model_config_from_db()
        self.persist_directory = persist_directory or settings.VECTOR_DB_PATH
        os.makedirs(self.persist_directory, exist_ok=True)

        self.embedding_provider = embedding_provider or create_embedding_provider(provider_type)
        self.collection_name = collection_name
        self._base_collection_name = collection_name

        # 嵌入式 Qdrant，数据持久化到本地路径
        self.client = QdrantClient(path=self.persist_directory)
        # qdrant_client 本地模式内部使用单个 SQLite 连接，多线程并发访问会触发
        # sqlite3.OperationalError: cannot start a transaction within a transaction
        # 通过 threading.Lock 串行化所有 client 操作，确保事务不嵌套
        self._client_lock = threading.Lock()
        self._ensure_collection()

        logger.info(
            f"VectorStoreManager initialized with provider={self.embedding_provider.provider_name} "
            f"path={self.persist_directory} collection={collection_name}"
        )

    def _ensure_collection(self) -> None:
        """
        确保 Qdrant collection 存在；若不存在则按嵌入维度创建，并配置 dense + sparse 双向量字段。
        """
        with self._client_lock:
            if self.client.collection_exists(self.collection_name):
                return

            dimension = _detect_dense_dimension(self.embedding_provider)
            self._create_collection_locked(self.collection_name, dimension)

    def _create_collection(self, collection_name: str, dimension: int) -> None:
        """按指定稠密向量维度创建带稀疏向量的 collection（加锁版本）。"""
        with self._client_lock:
            self._create_collection_locked(collection_name, dimension)

    def _create_collection_locked(self, collection_name: str, dimension: int) -> None:
        """创建 collection 的内部实现，调用方必须已持有 _client_lock。"""
        self.client.create_collection(
            collection_name=collection_name,
            vectors_config={
                DENSE_VECTOR_NAME: models.VectorParams(
                    size=dimension,
                    distance=models.Distance.COSINE,
                )
            },
            sparse_vectors_config={
                SPARSE_VECTOR_NAME: models.SparseVectorParams()
            },
        )

    def _get_dense_dimension(self, collection_name: str) -> Optional[int]:
        """读取 collection 的稠密向量维度，旧格式或读取失败时返回 None。"""
        try:
            with self._client_lock:
                collection = self.client.get_collection(collection_name)
            vectors = collection.config.params.vectors
            vector_params = vectors.get(DENSE_VECTOR_NAME) if isinstance(vectors, dict) else None
            dimension = getattr(vector_params, "size", None)
            return dimension if isinstance(dimension, int) and dimension > 0 else None
        except Exception as exc:
            logger.bind(
                event="vector_collection_dimension_read_failed",
                module="vector_store",
                collection=collection_name,
                error_type=type(exc).__name__,
            ).warning(f"读取向量 collection 维度失败: {exc}")
            return None

    def _ensure_collection_dimension(self, dimension: int) -> None:
        """为当前嵌入维度选择兼容 collection，保留旧 collection 以避免丢失用户数据。"""
        if dimension <= 0:
            raise ValueError("嵌入向量不能为空")

        current_dimension = self._get_dense_dimension(self.collection_name)
        if current_dimension is None or current_dimension == dimension:
            return

        previous_collection = self.collection_name
        compatible_collection = f"{self._base_collection_name}__d{dimension}"
        self.collection_name = compatible_collection

        if self._collection_exists_locked(compatible_collection):
            compatible_dimension = self._get_dense_dimension(compatible_collection)
            if compatible_dimension != dimension:
                raise RuntimeError(
                    f"向量 collection {compatible_collection} 维度为 {compatible_dimension}，"
                    f"与当前嵌入维度 {dimension} 不兼容"
                )
        else:
            self._create_collection(compatible_collection, dimension)

        logger.bind(
            event="vector_collection_dimension_migrated",
            module="vector_store",
            previous_collection=previous_collection,
            compatible_collection=compatible_collection,
            previous_dimension=current_dimension,
            dimension=dimension,
        ).warning(
            "检测到嵌入维度变更，已切换到兼容 collection；旧 collection 保留，未删除用户数据"
        )

    def _collection_exists_locked(self, collection_name: str) -> bool:
        """检查 collection 是否存在（加锁）。"""
        with self._client_lock:
            return self.client.collection_exists(collection_name)

    @property
    def provider_name(self) -> str:
        return self.embedding_provider.provider_name

    def _document_id(self, memory_id: int) -> str:
        """
        兼容旧 ChromaDB 风格的文档 ID 字符串表示。
        实际 Qdrant point ID 使用整型 memory_id，此处仅用于日志与外部展示。
        """
        return f"memory:{memory_id}"

    def _sanitize_metadata(self, metadata: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        sanitized: Dict[str, Any] = {}
        for key, value in (metadata or {}).items():
            if value is None:
                continue
            if isinstance(value, (str, int, float, bool)):
                sanitized[key] = value
            else:
                sanitized[key] = str(value)
        return sanitized

    async def upsert_memory(
        self,
        memory_id: int,
        content: str,
        *,
        user_id: Optional[str] = None,
        importance: float = 0.5,
        archive_status: str = "active",
        metadata: Optional[Dict[str, Any]] = None,
        embedding: Optional[List[float]] = None,
    ) -> None:
        """
        新增或更新一条长期记忆向量记录。
        同时写入 dense 与 sparse 向量，供混合检索使用。
        """
        vector = embedding or (await self.embedding_provider.embed_texts([content]))[0]
        self._ensure_collection_dimension(len(vector))
        sparse_vector = compute_sparse_vector(content)
        payload = {
            "memory_id": int(memory_id),
            "user_id": str(user_id or ""),
            "importance": float(importance),
            "archive_status": archive_status,
            "content": content,
        }
        payload.update(self._sanitize_metadata(metadata))

        with self._client_lock:
            self.client.upsert(
                collection_name=self.collection_name,
                points=[
                    models.PointStruct(
                        id=int(memory_id),
                        vector={
                            DENSE_VECTOR_NAME: vector,
                            SPARSE_VECTOR_NAME: sparse_vector,
                        },
                        payload=payload,
                    )
                ],
            )

    def delete_memory(self, memory_id: int) -> None:
        """
        删除一条向量记忆记录。
        """
        with self._client_lock:
            self.client.delete(
                collection_name=self.collection_name,
                points_selector=models.PointIdsList(points=[int(memory_id)]),
            )

    def update_memory_metadata(self, memory_id: int, **fields: Any) -> None:
        """
        更新已存在向量记录的元数据。
        使用 set_payload 增量更新指定字段，不影响原文档与向量。
        """
        sanitized = self._sanitize_metadata(fields)
        if not sanitized:
            return

        # Qdrant 不允许设置 None 值，若需删除字段应使用 delete_payload；此处仅做覆盖更新
        try:
            with self._client_lock:
                self.client.set_payload(
                    collection_name=self.collection_name,
                    payload=sanitized,
                    points=[int(memory_id)],
                )
        except KeyError:
            # 数据库中可能存在尚未写入向量库的历史记忆，不能因此阻断记忆列表接口。
            logger.warning(
                "向量记录不存在，跳过元数据同步: memory_id={}, collection={}",
                memory_id,
                self.collection_name,
                exc_info=True,
            )

    async def search(
        self,
        query_text: str,
        *,
        user_id: Optional[str] = None,
        limit: int = 10,
        include_archived: bool = False,
    ) -> List[VectorSearchHit]:
        """
        执行混合检索：dense + sparse 双路召回，RRF 融合排序。
        通过 query_filter 实现用户隔离与归档过滤。
        """
        query_filter = self._build_filter(user_id=user_id, include_archived=include_archived)
        # 防御性检查：embedding 返回空列表时 [0] 会触发 IndexError，
        # 此时跳过向量检索返回空结果，避免整个 SSE 流因 numpy 错误中断
        try:
            embedded = await self.embedding_provider.embed_texts([query_text])
        except Exception as exc:
            logger.bind(
                event="vector_search_embedding_error",
                module="vector_store",
                error_type=type(exc).__name__,
            ).opt(exception=True).warning(f"嵌入查询失败，跳过向量检索: {exc}")
            return []
        if not embedded or not embedded[0]:
            logger.bind(
                event="vector_search_empty_embedding",
                module="vector_store",
                query_len=len(query_text),
            ).warning("嵌入返回空结果，跳过向量检索")
            return []
        dense_vector = embedded[0]
        self._ensure_collection_dimension(len(dense_vector))
        sparse_vector = compute_sparse_vector(query_text)

        # 单次调用 Qdrant 原生混合检索：prefetch 双路召回 + RRF 融合
        with self._client_lock:
            response = self.client.query_points(
                collection_name=self.collection_name,
                prefetch=[
                    models.Prefetch(
                        query=dense_vector,
                        using=DENSE_VECTOR_NAME,
                        limit=max(limit * 3, 20),
                        filter=query_filter,
                    ),
                    models.Prefetch(
                        query=sparse_vector,
                        using=SPARSE_VECTOR_NAME,
                        limit=max(limit * 3, 20),
                        filter=query_filter,
                    ),
                ],
                query=models.FusionQuery(fusion=models.Fusion.RRF),
                query_filter=query_filter,
                limit=limit,
                with_payload=True,
                with_vectors=False,
            )

        hits: List[VectorSearchHit] = []
        for point in response.points:
            payload = point.payload or {}
            memory_id = int(payload.get("memory_id") or point.id)
            content = str(payload.get("content") or "")
            # RRF 融合分数范围 [0, 1]，无需额外转换
            score = float(point.score or 0.0)
            hits.append(
                VectorSearchHit(
                    memory_id=memory_id,
                    score=score,
                    content=content,
                    metadata=payload,
                )
            )
        return hits

    def _build_filter(
        self,
        *,
        user_id: Optional[str] = None,
        include_archived: bool = False,
    ) -> Optional[models.Filter]:
        """
        构造 Qdrant 过滤条件：用户隔离 + 归档状态过滤。
        """
        must: List[models.Condition] = []
        if user_id is not None:
            must.append(
                models.FieldCondition(
                    key="user_id",
                    match=models.MatchValue(value=str(user_id)),
                )
            )
        if not include_archived:
            must.append(
                models.FieldCondition(
                    key="archive_status",
                    match=models.MatchValue(value="active"),
                )
            )

        if not must:
            return None
        return models.Filter(must=must)

    def count(self, user_id: Optional[str] = None, include_archived: bool = True) -> int:
        """
        返回向量库中满足条件的记录数量。
        """
        with self._client_lock:
            if user_id is None and include_archived:
                return int(self.client.count(
                    collection_name=self.collection_name,
                    count_filter=None,
                    exact=True,
                ).count)

            count_filter = self._build_filter(user_id=user_id, include_archived=include_archived)
            return int(self.client.count(
                collection_name=self.collection_name,
                count_filter=count_filter,
                exact=True,
            ).count)

    def close(self) -> None:
        """
        关闭 Qdrant 客户端，释放本地文件锁。
        """
        try:
            with self._client_lock:
                self.client.close()
        except Exception as exc:
            logger.warning(f"关闭 Qdrant 客户端时出现异常: {exc}")
