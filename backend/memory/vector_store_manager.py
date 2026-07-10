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
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Protocol

import httpx
from loguru import logger
from qdrant_client import QdrantClient, models

from config.settings import settings

# 模型下载统一存储到项目 data/models/ 目录，不散落到系统各处
def _get_models_dir() -> str:
    _backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _dir = os.path.join(_backend_dir, "data", "models")
    os.makedirs(_dir, exist_ok=True)
    return _dir

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


class SentenceTransformerEmbeddingProvider:
    """
    基于 sentence-transformers 的本地嵌入提供方。

    模型下载策略：优先从 HuggingFace 下载，网络不可达时自动降级到
    魔搭社区（ModelScope）下载，适配国内网络环境。
    """

    provider_name = "sentence-transformers"

    # HuggingFace → ModelScope 模型名称映射
    _MODELSCOPE_MODEL_MAP: Dict[str, str] = {
        "all-MiniLM-L6-v2": "sentence-transformers/all-MiniLM-L6-v2",
        "all-mpnet-base-v2": "sentence-transformers/all-mpnet-base-v2",
        "paraphrase-multilingual-MiniLM-L12-v2": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    }

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError("未安装 sentence-transformers，无法启用本地向量模式") from exc

        self.model_name = model_name
        self._model = None  # 延迟加载
        self._SentenceTransformer = SentenceTransformer

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

        ms_model_name = self._MODELSCOPE_MODEL_MAP.get(
            self.model_name,
            f"sentence-transformers/{self.model_name}",
        )
        try:
            local_path = snapshot_download(ms_model_name)
            logger.info(f"从魔搭社区下载模型成功: {ms_model_name} -> {local_path}")
            return local_path
        except Exception as exc:
            logger.warning(f"从魔搭社区下载模型失败 ({ms_model_name}): {exc}")
            return None

    def _ensure_model(self):
        """
        延迟初始化模型，按优先级尝试下载：
        1. HuggingFace（默认源）
        2. 魔搭社区 ModelScope（国内网络降级）
        """
        if self._model is not None:
            return

        # 使用项目内的模型缓存目录，避免每次重启重复下载
        _cache_dir = os.path.join(_MODELS_DIR, "sentence_transformers")
        os.makedirs(_cache_dir, exist_ok=True)

        # 优先尝试 HuggingFace
        try:
            self._model = self._SentenceTransformer(self.model_name, cache_folder=_cache_dir)
            logger.info(f"从 HuggingFace 加载模型成功: {self.model_name} -> {_cache_dir}")
            return
        except Exception as hf_exc:
            logger.warning(f"从 HuggingFace 下载模型失败 ({self.model_name}): {hf_exc}")

        # 降级：尝试从魔搭社区下载
        local_path = self._try_download_from_modelscope()
        if local_path:
            self._model = self._SentenceTransformer(local_path, cache_folder=_cache_dir)
            return

        # 两处都失败
        raise RuntimeError(
            f"无法加载模型 {self.model_name}，HuggingFace 和 ModelScope 均下载失败。"
            f"请检查网络连接，或安装 modelscope: pip install modelscope"
        )

    async def embed_texts(self, texts: List[str]) -> List[List[float]]:
        self._ensure_model()
        # CPU 密集型推理，放到线程池避免阻塞事件循环
        vectors = await asyncio.to_thread(self._model.encode, texts, normalize_embeddings=True)
        return [list(map(float, vector)) for vector in vectors.tolist()]


def create_embedding_provider(provider_type: Optional[str] = None) -> EmbeddingProvider:
    """
    根据配置选择可用的嵌入提供方。
    优先级：显式配置 > OpenAI > sentence-transformers > 哈希兜底。
    """
    normalized = str(
        provider_type
        or os.getenv("MEMORY_EMBEDDING_PROVIDER", "")
    ).strip().lower()

    if normalized in {"openai"}:
        secret = settings.OPENAI_API_KEY
        api_key = secret.get_secret_value() if secret else ""
        if not api_key:
            raise RuntimeError("OpenAI 嵌入模式已启用，但未配置 OPENAI_API_KEY")
        return OpenAIEmbeddingProvider(api_key=api_key)

    if normalized in {"sentence-transformers", "local"}:
        model_name = os.getenv("MEMORY_LOCAL_EMBEDDING_MODEL", "all-MiniLM-L6-v2")
        return SentenceTransformerEmbeddingProvider(model_name=model_name)

    if normalized in {"hash", "simple"}:
        return HashEmbeddingProvider()

    secret = settings.OPENAI_API_KEY
    api_key = secret.get_secret_value() if secret else ""
    if api_key:
        return OpenAIEmbeddingProvider(api_key=api_key)

    try:
        model_name = os.getenv("MEMORY_LOCAL_EMBEDDING_MODEL", "all-MiniLM-L6-v2")
        return SentenceTransformerEmbeddingProvider(model_name=model_name)
    except Exception as exc:
        logger.warning(f"未检测到可用嵌入模型，已回退到哈希嵌入: {exc}")
        return HashEmbeddingProvider()


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
        logger.warning(f"探测嵌入维度失败，回退到默认维度 {DEFAULT_HASH_DIMENSION}: {exc}")
    return DEFAULT_HASH_DIMENSION


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
        self.persist_directory = persist_directory or settings.VECTOR_DB_PATH
        os.makedirs(self.persist_directory, exist_ok=True)

        self.embedding_provider = embedding_provider or create_embedding_provider(provider_type)
        self.collection_name = collection_name

        # 嵌入式 Qdrant，数据持久化到本地路径
        self.client = QdrantClient(path=self.persist_directory)
        self._ensure_collection()

        logger.info(
            f"VectorStoreManager initialized with provider={self.embedding_provider.provider_name} "
            f"path={self.persist_directory} collection={collection_name}"
        )

    def _ensure_collection(self) -> None:
        """
        确保 Qdrant collection 存在；若不存在则按嵌入维度创建，并配置 dense + sparse 双向量字段。
        """
        if self.client.collection_exists(self.collection_name):
            return

        dimension = _detect_dense_dimension(self.embedding_provider)
        self.client.create_collection(
            collection_name=self.collection_name,
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
        sparse_vector = compute_sparse_vector(content)
        payload = {
            "memory_id": int(memory_id),
            "user_id": str(user_id or ""),
            "importance": float(importance),
            "archive_status": archive_status,
            "content": content,
        }
        payload.update(self._sanitize_metadata(metadata))

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
        dense_vector = (await self.embedding_provider.embed_texts([query_text]))[0]
        sparse_vector = compute_sparse_vector(query_text)

        # 单次调用 Qdrant 原生混合检索：prefetch 双路召回 + RRF 融合
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
            self.client.close()
        except Exception as exc:
            logger.warning(f"关闭 Qdrant 客户端时出现异常: {exc}")
