"""
模型服务子进程（独立 FastAPI 服务）。

由主进程按需拉起，加载本地嵌入 / 重排模型并提供推理端点：
- POST /embed    文本或图片 → 向量（list[list[float]]）
- POST /rerank   查询 + 文档 → 相关性分数
- POST /load     加载模型（首次调用时自动加载，也可显式预热）
- POST /unload   释放模型权重（空闲卸载用，进程可继续存活）
- GET  /health   服务与模型加载状态

启动方式（主进程 ModelServiceClient 管理）：
    python -m uvicorn model_service.server:app --host 127.0.0.1 --port <port>
"""
from __future__ import annotations

import os
import sys
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI
from pydantic import BaseModel

# 确保以 backend 为工作目录时可直接运行（模块导入路径）
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger

app = FastAPI(title="Open-AwA Model Service", version="0.1")

# ---------------- 模型持有（延迟加载 + 可卸载） ----------------

_model_lock = threading.Lock()
_embedding_provider: Any = None
_reranker: Any = None
# 模型名由主进程通过环境变量注入（spawn 子进程时设置）
_embedding_model: str = os.getenv("MODEL_SERVICE_EMBEDDING_MODEL", "")
_rerank_model: str = os.getenv("MODEL_SERVICE_RERANK_MODEL", "")


def _load_embedding_provider() -> Any:
    """加载本地嵌入模型（延迟 + 线程锁，幂等）。"""
    global _embedding_provider
    if _embedding_provider is not None:
        return _embedding_provider
    with _model_lock:
        if _embedding_provider is not None:
            return _embedding_provider
        from memory.vector_store_manager import SentenceTransformerEmbeddingProvider

        _embedding_provider = SentenceTransformerEmbeddingProvider(model_name=_embedding_model)
        logger.info(f"模型服务加载嵌入模型: {_embedding_model}")
        return _embedding_provider


def _load_reranker() -> Any:
    """加载本地重排模型（延迟 + 线程锁，幂等）。"""
    global _reranker
    if _reranker is not None:
        return _reranker
    with _model_lock:
        if _reranker is not None:
            return _reranker
        from memory.reranker import LocalCrossEncoderReranker

        _reranker = LocalCrossEncoderReranker(model_name=_rerank_model)
        logger.info(f"模型服务加载重排模型: {_rerank_model}")
        return _reranker


# ---------------- 请求 / 响应模型 ----------------

class EmbedRequest(BaseModel):
    texts: List[str] = []
    images: List[str] = []  # 图片 URL 或 data URI（多模态嵌入）
    model: str = ""


class RerankRequest(BaseModel):
    query: str
    documents: List[str]
    model: str = ""


class UnloadRequest(BaseModel):
    kind: str = "all"  # embedding | rerank | all


# ---------------- 端点 ----------------

@app.get("/health")
async def health() -> Dict[str, Any]:
    """服务与模型加载状态（供主进程探活与诊断）。"""
    return {
        "ok": True,
        "embedding_loaded": _embedding_provider is not None,
        "reranker_loaded": _reranker is not None,
        "embedding_model": _embedding_model,
        "rerank_model": _rerank_model,
    }


@app.post("/embed")
async def embed(req: EmbedRequest) -> Dict[str, Any]:
    """文本（或图片）→ 向量。文本走 embed_texts，图片走多模态 embed_inputs。"""
    provider = _load_embedding_provider()
    if req.images:
        # 多模态输入：文本与图片混合（Qwen3-VL-Embedding 等）
        inputs: List[Any] = []
        if req.texts:
            inputs.extend(req.texts)
        inputs.extend(
            {"content": [{"type": "image_url", "image_url": {"url": url}}]} for url in req.images
        )
        vectors = await provider.embed_inputs(inputs)
    else:
        vectors = await provider.embed_texts(req.texts)
    return {"vectors": vectors, "count": len(vectors)}


@app.post("/rerank")
async def rerank(req: RerankRequest) -> Dict[str, Any]:
    """查询 + 文档 → 相关性分数列表（与 documents 顺序一致）。"""
    reranker = _load_reranker()
    scores = await reranker.rerank(req.query, req.documents)
    return {"scores": scores, "count": len(scores)}


@app.post("/load")
async def load_model(req: EmbedRequest) -> Dict[str, Any]:
    """显式预热模型（主进程启动或按需加载时调用）。"""
    loaded: List[str] = []
    if req.model.lower() in {"", "embedding", "all"}:
        _load_embedding_provider()
        loaded.append("embedding")
    if req.model.lower() in {"rerank", "all"}:
        _load_reranker()
        loaded.append("rerank")
    return {"ok": True, "loaded": loaded}


@app.post("/unload")
async def unload_model(req: UnloadRequest) -> Dict[str, Any]:
    """释放模型权重（空闲卸载）：置空引用触发 GC，进程保持存活供下次加载。"""
    global _embedding_provider, _reranker
    released: List[str] = []
    if req.kind in {"embedding", "all"} and _embedding_provider is not None:
        _embedding_provider = None
        released.append("embedding")
    if req.kind in {"rerank", "all"} and _reranker is not None:
        _reranker = None
        released.append("rerank")
    if released:
        logger.info(f"模型服务卸载模型: {released}")
    return {"ok": True, "released": released}


# ---------------- 启动入口（主进程通过 CLI 拉起） ----------------

def main() -> None:
    """命令行入口：python -m model_service.server（模型名走环境变量）。"""
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=int(os.getenv("MODEL_SERVICE_PORT", "0")))


if __name__ == "__main__":
    main()

