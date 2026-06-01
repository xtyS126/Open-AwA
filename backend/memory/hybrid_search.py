"""
混合检索模块 — 向量语义搜索 + BM25 全文检索加权融合。
"""
from typing import Optional

from loguru import logger

from memory.bm25_retriever import BM25Retriever


class HybridSearch:
    """
    混合检索引擎。
    同时使用向量语义搜索和 BM25 全文检索，加权融合结果。
    """

    def __init__(
        self,
        bm25_retriever: Optional[BM25Retriever] = None,
        vector_weight: float = 0.7,
        bm25_weight: float = 0.3,
    ):
        self.bm25 = bm25_retriever or BM25Retriever()
        self.vector_weight = vector_weight
        self.bm25_weight = bm25_weight

    def search(
        self,
        query: str,
        vector_results: Optional[list[dict]] = None,
        limit: int = 10,
    ) -> list[dict]:
        """
        混合检索。

        Args:
            query: 查询文本
            vector_results: 向量搜索结果（由外部向量搜索提供）
            limit: 返回数量上限

        Returns:
            融合排序后的结果列表
        """
        # BM25 检索
        bm25_results = self.bm25.search(query, limit=limit * 3)

        # 如果没有向量结果，只返回 BM25 结果
        if not vector_results:
            return [
                {
                    "doc_id": r["doc_id"],
                    "score": r["score"],
                    "source": "bm25",
                    "content_preview": r.get("content_preview", ""),
                }
                for r in bm25_results[:limit]
            ]

        # 合并两路结果
        merged: dict[str, dict] = {}

        # 向量结果
        for r in vector_results:
            doc_id = r.get("doc_id") or r.get("id") or r.get("memory_id", "")
            if not doc_id:
                continue
            merged[doc_id] = {
                "doc_id": str(doc_id),
                "vector_score": r.get("score", 0) or r.get("similarity", 0),
                "bm25_score": 0.0,
                "content_preview": r.get("content", r.get("content_preview", ""))[:300],
            }

        # BM25 结果
        for r in bm25_results:
            doc_id = r["doc_id"]
            if doc_id in merged:
                merged[doc_id]["bm25_score"] = r["score"]
            else:
                merged[doc_id] = {
                    "doc_id": doc_id,
                    "vector_score": 0.0,
                    "bm25_score": r["score"],
                    "content_preview": r.get("content_preview", ""),
                }

        # 加权融合
        for item in merged.values():
            item["final_score"] = (
                item["vector_score"] * self.vector_weight
                + item["bm25_score"] * self.bm25_weight
            )
            # 标记来源
            sources = []
            if item["vector_score"] > 0:
                sources.append("vector")
            if item["bm25_score"] > 0:
                sources.append("bm25")
            item["source"] = "+".join(sources) if sources else "none"

        # 按 final_score 降序排列
        ranked = sorted(merged.values(), key=lambda x: x["final_score"], reverse=True)

        logger.bind(
            event="hybrid_search",
            query=query[:100],
            vector_count=len(vector_results),
            bm25_count=len(bm25_results),
            merged_count=len(ranked),
        ).info("混合检索完成")

        return ranked[:limit]

    def index_document(self, doc_id: str, content: str):
        """索引文档到 BM25。"""
        self.bm25.index_document(doc_id, content)

    def rebuild_index(self, documents: dict[str, str]):
        """
        从文档字典重建 BM25 索引。
        """
        self.bm25.clear()
        for doc_id, content in documents.items():
            self.bm25.index_document(doc_id, content)
        logger.bind(event="bm25_reindex", count=len(documents)).info("BM25 索引已重建")

    def get_stats(self) -> dict:
        """获取检索统计。"""
        return {
            "bm25": self.bm25.get_stats(),
            "vector_weight": self.vector_weight,
            "bm25_weight": self.bm25_weight,
        }
