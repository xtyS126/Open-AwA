"""
向量模型注册表（Spec memory-model-config-chain）。

集中管理嵌入模型与重排模型的元数据：
- 本地模型（sentence-transformers / cross-encoder）：记录 ModelScope 与 HuggingFace
  仓库 ID、嵌入维度，供下载链与维度探测使用
- 云端模型（OpenAI 兼容 API / DashScope 多模态）：记录 API 模型名与能力标签，
  如 Qwen3-VL-Embedding（多模态嵌入）与 Qwen3-VL-Reranker（多模态重排）

默认下载源为 ModelScope（魔搭社区），网络不可达时降级 HuggingFace。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass(frozen=True)
class EmbeddingModelSpec:
    """嵌入模型规格。"""

    name: str
    kind: str  # local | cloud
    label: str
    description: str = ""
    # 本地模型仓库 ID（ModelScope 优先，HuggingFace 兜底）
    modelscope_id: str = ""
    huggingface_id: str = ""
    # 嵌入向量维度（本地模型已知维度；云端模型 None 表示由 API 探测）
    dimension: Optional[int] = None
    # 能力标签：multimodal 表示支持文本+图像输入
    capabilities: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class RerankModelSpec:
    """重排模型规格。"""

    name: str
    kind: str  # local | cloud
    label: str
    description: str = ""
    modelscope_id: str = ""
    huggingface_id: str = ""
    capabilities: List[str] = field(default_factory=list)


# ---------------- 嵌入模型注册表 ----------------

EMBEDDING_MODELS: Dict[str, EmbeddingModelSpec] = {
    "all-MiniLM-L6-v2": EmbeddingModelSpec(
        name="all-MiniLM-L6-v2",
        kind="local",
        label="all-MiniLM-L6-v2（英文通用，384 维）",
        description="轻量英文通用嵌入模型，384 维，速度最快",
        modelscope_id="sentence-transformers/all-MiniLM-L6-v2",
        huggingface_id="sentence-transformers/all-MiniLM-L6-v2",
        dimension=384,
    ),
    "bge-small-zh-v1.5": EmbeddingModelSpec(
        name="bge-small-zh-v1.5",
        kind="local",
        label="bge-small-zh-v1.5（中文推荐，512 维）",
        description="BAAI 中文语义嵌入模型，512 维，中文效果优于 MiniLM",
        modelscope_id="AI-ModelScope/bge-small-zh-v1.5",
        huggingface_id="BAAI/bge-small-zh-v1.5",
        dimension=512,
    ),
    "bge-m3": EmbeddingModelSpec(
        name="bge-m3",
        kind="local",
        label="bge-m3（多语言，1024 维）",
        description="BAAI 多语言通用嵌入模型，1024 维，支持 100+ 语言",
        modelscope_id="AI-ModelScope/bge-m3",
        huggingface_id="BAAI/bge-m3",
        dimension=1024,
    ),
    "Qwen3-VL-Embedding": EmbeddingModelSpec(
        name="Qwen3-VL-Embedding",
        kind="cloud",
        label="Qwen3-VL-Embedding（多模态云端嵌入）",
        description="Qwen3 系列多模态嵌入模型，支持文本与图像输入，经 OpenAI 兼容 /embeddings 接口调用",
        capabilities=["multimodal", "text", "image"],
    ),
    "text-embedding-3-small": EmbeddingModelSpec(
        name="text-embedding-3-small",
        kind="cloud",
        label="text-embedding-3-small（OpenAI 云端嵌入）",
        description="OpenAI 官方嵌入模型，1536 维，文本输入",
        capabilities=["text"],
    ),
}

# ---------------- 重排模型注册表 ----------------

RERANK_MODELS: Dict[str, RerankModelSpec] = {
    "ms-marco-MiniLM-L6-v2": RerankModelSpec(
        name="ms-marco-MiniLM-L6-v2",
        kind="local",
        label="ms-marco-MiniLM-L6-v2（本地交叉编码重排）",
        description="CrossEncoder 交叉编码重排模型，Query-Document 相关性打分",
        modelscope_id="cross-encoder/ms-marco-MiniLM-L6-v2",
        huggingface_id="cross-encoder/ms-marco-MiniLM-L6-v2",
    ),
    "bge-reranker-v2-m3": RerankModelSpec(
        name="bge-reranker-v2-m3",
        kind="local",
        label="bge-reranker-v2-m3（多语言重排）",
        description="BAAI 多语言重排模型，中文场景效果更优",
        modelscope_id="AI-ModelScope/bge-reranker-v2-m3",
        huggingface_id="BAAI/bge-reranker-v2-m3",
    ),
    "Qwen3-VL-Reranker": RerankModelSpec(
        name="Qwen3-VL-Reranker",
        kind="cloud",
        label="Qwen3-VL-Reranker（多模态云端重排）",
        description="Qwen3 系列多模态重排模型，支持文本与图像相关性打分，经 API 调用",
        capabilities=["multimodal", "text", "image"],
    ),
}


def get_embedding_spec(model_name: str) -> Optional[EmbeddingModelSpec]:
    """按名称查询嵌入模型规格，未注册时返回 None。"""
    return EMBEDDING_MODELS.get(model_name)


def get_rerank_spec(model_name: str) -> Optional[RerankModelSpec]:
    """按名称查询重排模型规格，未注册时返回 None。"""
    return RERANK_MODELS.get(model_name)


def default_embedding_model(kind: str = "local") -> str:
    """返回指定类型的默认嵌入模型名。"""
    if kind == "cloud":
        return "Qwen3-VL-Embedding"
    return "all-MiniLM-L6-v2"


def default_rerank_model(kind: str = "local") -> str:
    """返回指定类型的默认重排模型名。"""
    if kind == "cloud":
        return "Qwen3-VL-Reranker"
    return "ms-marco-MiniLM-L6-v2"
