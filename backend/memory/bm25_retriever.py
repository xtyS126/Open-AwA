"""
BM25 全文检索模块 — 纯 Python 实现。
提供基于词频的关键词搜索，与向量搜索互补。
"""
import math
import re
from collections import defaultdict
from typing import Optional


class BM25Retriever:
    """
    纯 Python BM25 全文检索实现。
    支持文档索引、查询和分数计算。
    """

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self._documents: dict[str, str] = {}  # doc_id -> content
        self._doc_lengths: dict[str, int] = {}
        self._avg_doc_length: float = 0.0
        self._term_freqs: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))  # term -> doc_id -> freq
        self._doc_freqs: dict[str, int] = defaultdict(int)  # term -> document count
        self._total_docs: int = 0

    def index_document(self, doc_id: str, content: str):
        """
        索引单个文档。
        """
        tokens = self._tokenize(content)
        self._documents[doc_id] = content
        self._doc_lengths[doc_id] = len(tokens)
        self._total_docs += 1

        seen_terms = set()
        for token in tokens:
            self._term_freqs[token][doc_id] += 1
            seen_terms.add(token)
        for token in seen_terms:
            self._doc_freqs[token] += 1

        self._avg_doc_length = sum(self._doc_lengths.values()) / self._total_docs if self._total_docs > 0 else 0

    def remove_document(self, doc_id: str):
        """
        移除已索引的文档。
        """
        if doc_id not in self._documents:
            return
        tokens = self._tokenize(self._documents[doc_id])
        for token in set(tokens):
            self._term_freqs[token].pop(doc_id, None)
            self._doc_freqs[token] = max(0, self._doc_freqs.get(token, 1) - 1)
        self._doc_lengths.pop(doc_id, None)
        self._documents.pop(doc_id, None)
        self._total_docs -= 1

    def search(self, query: str, limit: int = 10) -> list[dict]:
        """
        搜索并返回匹配的文档。
        """
        tokens = self._tokenize(query)
        if not tokens:
            return []

        scores = {}
        for token in tokens:
            idf = self._compute_idf(token)
            if idf == 0:
                continue
            for doc_id, tf in self._term_freqs[token].items():
                doc_len = self._doc_lengths.get(doc_id, 1)
                score = idf * (tf * (self.k1 + 1)) / (
                    tf + self.k1 * (1 - self.b + self.b * doc_len / max(1, self._avg_doc_length))
                )
                scores[doc_id] = scores.get(doc_id, 0) + score

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:limit]
        return [
            {
                "doc_id": doc_id,
                "score": round(score, 4),
                "content_preview": self._documents.get(doc_id, "")[:300],
            }
            for doc_id, score in ranked
        ]

    def _compute_idf(self, term: str) -> float:
        """计算 IDF（逆文档频率）。"""
        df = self._doc_freqs.get(term, 0)
        if df == 0:
            return 0.0
        return math.log((self._total_docs - df + 0.5) / (df + 0.5) + 1.0)

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """
        分词：小写化 + 正则分割。
        中英文混合分词。
        """
        text = text.lower()
        # 匹配英文单词、中文单字、数字
        tokens = re.findall(r'[a-zA-Z]+|[一-鿿]|\d+', text)
        # 过滤过短 token
        return [t for t in tokens if len(t) >= 1]

    def get_stats(self) -> dict:
        """获取索引统计信息。"""
        return {
            "total_documents": self._total_docs,
            "total_terms": len(self._term_freqs),
            "avg_doc_length": round(self._avg_doc_length, 2),
        }

    def clear(self):
        """清除所有索引。"""
        self._documents.clear()
        self._doc_lengths.clear()
        self._avg_doc_length = 0.0
        self._term_freqs.clear()
        self._doc_freqs.clear()
        self._total_docs = 0
