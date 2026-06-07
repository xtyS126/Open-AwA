"""
向量存储管理模块，负责长期记忆的向量化存储与语义检索。
默认使用 ChromaDB 作为持久化后端，并根据环境自动选择可用的嵌入提供方。
"""

from __future__ import annotations

import hashlib
import math
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Protocol

import numpy as np

if not hasattr(np, "float_"):
    # 兼容 ChromaDB 依赖的旧版 NumPy 类型别名。
    np.float_ = np.float64

import chromadb
import httpx
from loguru import logger

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


DEFAULT_COLLECTION_NAME = "long_term_memory"
DEFAULT_HASH_DIMENSION = 32


class EmbeddingProvider(Protocol):
    """
    嵌入提供方协议，统一不同向量化实现的调用方式。
    """

    provider_name: str

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
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

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
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

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        response = httpx.post(
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

        # 优先尝试 HuggingFace
        try:
            self._model = self._SentenceTransformer(self.model_name)
            logger.info(f"从 HuggingFace 加载模型成功: {self.model_name}")
            return
        except Exception as hf_exc:
            logger.warning(f"从 HuggingFace 下载模型失败 ({self.model_name}): {hf_exc}")

        # 降级：尝试从魔搭社区下载
        local_path = self._try_download_from_modelscope()
        if local_path:
            self._model = self._SentenceTransformer(local_path)
            return

        # 两处都失败
        raise RuntimeError(
            f"无法加载模型 {self.model_name}，HuggingFace 和 ModelScope 均下载失败。"
            f"请检查网络连接，或安装 modelscope: pip install modelscope"
        )

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        self._ensure_model()
        vectors = self._model.encode(texts, normalize_embeddings=True)
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


class VectorStoreManager:
    """
    ChromaDB 向量存储封装。
    负责长期记忆的 upsert、删除、混合查询与基础统计。
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
        try:
            from chromadb.config import Settings as ChromaSettings
            chroma_settings = ChromaSettings(
                anonymized_telemetry=False,
                chroma_product_telemetry_impl="memory.chroma_telemetry.NoOpProductTelemetryClient",
                chroma_telemetry_impl="memory.chroma_telemetry.NoOpProductTelemetryClient",
            )
        except Exception as exc:
            logger.warning(f"构建 Chroma 配置失败，回退默认配置: {exc}")
            chroma_settings = None
        client_kwargs = {
            "path": self.persist_directory,
        }
        if chroma_settings is not None:
            client_kwargs["settings"] = chroma_settings

        try:
            self.client = chromadb.PersistentClient(**client_kwargs)
        except TypeError as exc:
            if chroma_settings is None or "settings" not in str(exc):
                raise
            logger.warning(f"PersistentClient 不支持 settings 参数，回退默认初始化: {exc}")
            self.client = chromadb.PersistentClient(path=self.persist_directory)
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info(
            f"VectorStoreManager initialized with provider={self.embedding_provider.provider_name} path={self.persist_directory}"
        )

    @property
    def provider_name(self) -> str:
        return self.embedding_provider.provider_name

    def _document_id(self, memory_id: int) -> str:
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

    def upsert_memory(
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
        """
        vector = embedding or self.embedding_provider.embed_texts([content])[0]
        payload = {
            "memory_id": int(memory_id),
            "user_id": str(user_id or ""),
            "importance": float(importance),
            "archive_status": archive_status,
        }
        payload.update(self._sanitize_metadata(metadata))
        self.collection.upsert(
            ids=[self._document_id(memory_id)],
            documents=[content],
            embeddings=[vector],
            metadatas=[payload],
        )

    def delete_memory(self, memory_id: int) -> None:
        """
        删除一条向量记忆记录。
        """
        self.collection.delete(ids=[self._document_id(memory_id)])

    def update_memory_metadata(self, memory_id: int, **fields: Any) -> None:
        """
        更新已存在向量记录的元数据。
        该方法会保留原文档与向量，仅覆盖元数据字段。
        """
        record = self.collection.get(
            ids=[self._document_id(memory_id)],
            include=["documents", "metadatas", "embeddings"],
        )
        if not record.get("ids"):
            return

        existing_metadata = self._extract_first_item(record.get("metadatas"), default={}) or {}
        existing_metadata.update(self._sanitize_metadata(fields))
        document = self._extract_first_item(record.get("documents"), default="") or ""
        embedding = self._extract_first_item(record.get("embeddings"), default=[]) or []
        self.collection.upsert(
            ids=[self._document_id(memory_id)],
            documents=[document],
            embeddings=[embedding],
            metadatas=[existing_metadata],
        )

    def _extract_first_item(self, values: Any, default: Any = None) -> Any:
        """
        兼容 ChromaDB 在不同接口下返回的一维或二维列表结构。
        """
        if not values:
            return default
        first = values[0]
        if isinstance(first, list) and first and isinstance(first[0], list):
            return first[0] if first else default
        return first

    def search(
        self,
        query_text: str,
        *,
        user_id: Optional[str] = None,
        limit: int = 10,
        include_archived: bool = False,
    ) -> List[VectorSearchHit]:
        """
        执行语义向量搜索，并返回标准化结果。
        """
        where = self._build_where_clause(user_id=user_id, include_archived=include_archived)
        vector = self.embedding_provider.embed_texts([query_text])[0]
        result = self.collection.query(
            query_embeddings=[vector],
            n_results=limit,
            where=where,
            include=["documents", "metadatas", "distances"],
        )

        ids = (result.get("ids") or [[]])[0]
        documents = (result.get("documents") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]

        hits: List[VectorSearchHit] = []
        for index, document_id in enumerate(ids):
            metadata = metadatas[index] if index < len(metadatas) else {}
            distance = distances[index] if index < len(distances) else 1.0
            memory_id = int(metadata.get("memory_id") or str(document_id).split(":")[-1])
            hits.append(
                VectorSearchHit(
                    memory_id=memory_id,
                    score=max(0.0, 1.0 - float(distance)),
                    content=documents[index] if index < len(documents) else "",
                    metadata=metadata or {},
                )
            )
        return hits

    def _build_where_clause(
        self,
        *,
        user_id: Optional[str] = None,
        include_archived: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """
        构造兼容 ChromaDB 的过滤条件。
        """
        conditions: List[Dict[str, Any]] = []
        if user_id is not None:
            conditions.append({"user_id": str(user_id)})
        if not include_archived:
            conditions.append({"archive_status": "active"})

        if not conditions:
            return None
        if len(conditions) == 1:
            return conditions[0]
        return {"$and": conditions}

    def count(self, user_id: Optional[str] = None, include_archived: bool = True) -> int:
        """
        返回向量库中满足条件的记录数量。
        """
        if user_id is None and include_archived:
            return self.collection.count()

        where = self._build_where_clause(user_id=user_id, include_archived=include_archived)
        records = self.collection.get(where=where)
        return len(records.get("ids", []))