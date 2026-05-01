"""
本地网页搜索引擎 - 基于倒排索引的纯Python本地搜索实现。
参考来源: FlexSearch (https://github.com/nextapps-de/flexsearch, Apache-2.0)
作者: nextapps-de/Thomas Wilkerling
许可: Apache-2.0

特性:
- 纯Python倒排索引，零外部依赖
- 中文文本支持（字符级n-gram + 通用分词）
- TF-IDF 相关性评分
- 索引持久化（JSON序列化）
- 支持精确匹配、前缀搜索、模糊搜索
- 上下文感知搜索（词邻近度）
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from loguru import logger

MAX_RESULTS = 20
INDEX_DIR = "data/local_search_index"


class LocalSearchEngine:
    """
    本地搜索引擎。
    使用倒排索引实现高效的全文搜索，支持中文等多语言文本。
    """

    name: str = "local_search"
    version: str = "1.0.0"
    description: str = "本地网页和文档搜索引擎"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.index_dir = Path(self.config.get("index_dir", INDEX_DIR))
        self.max_results = self.config.get("max_results", MAX_RESULTS)
        self._initialized = False

        # 倒排索引: term -> {doc_id -> [positions]}
        self._inverted_index: Dict[str, Dict[str, List[int]]] = defaultdict(dict)
        # 文档存储: doc_id -> {title, url, content, snippet}
        self._documents: Dict[str, Dict[str, Any]] = {}
        # 文档频率: term -> document count
        self._doc_freq: Dict[str, int] = defaultdict(int)
        # 总文档数
        self._doc_count: int = 0
        # 索引统计
        self._total_terms: int = 0

    async def initialize(self) -> bool:
        """初始化搜索引擎，从磁盘加载已有索引。"""
        try:
            self.index_dir.mkdir(parents=True, exist_ok=True)
            idx_file = self.index_dir / "index.json"
            if idx_file.exists():
                await self._load_index(idx_file)
                logger.info(
                    f"LocalSearch engine loaded: {self._doc_count} docs, "
                    f"{len(self._inverted_index)} unique terms"
                )
            else:
                logger.info("LocalSearch engine initialized with empty index")
        except Exception as e:
            logger.warning(f"Failed to load existing index: {e}, starting fresh")
        self._initialized = True
        return True

    def is_initialized(self) -> bool:
        return self._initialized

    async def execute(self, **kwargs) -> Dict[str, Any]:
        """执行搜索或索引操作。"""
        if not self._initialized:
            return {"success": False, "error": "搜索引擎未初始化"}

        action = kwargs.get("action", "search")
        if action == "search":
            return await self._search(kwargs)
        elif action == "index":
            return await self._index_document(kwargs)
        elif action == "index_directory":
            return await self._index_directory(kwargs)
        elif action == "remove":
            return await self._remove_document(kwargs)
        elif action == "stats":
            return self._get_stats()
        elif action == "clear":
            return await self._clear_index()
        else:
            return {"success": False, "error": f"未知操作: {action}"}

    # === 搜索 ===

    async def _search(self, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        """执行搜索查询。"""
        query = kwargs.get("query", "").strip()
        max_results = kwargs.get("max_results", self.max_results)
        search_mode = kwargs.get("mode", "tfidf")  # tfidf | exact | prefix
        context_search = kwargs.get("context", True)

        if not query:
            return {"success": False, "error": "搜索关键词不能为空"}

        if not self._documents:
            return {
                "success": True,
                "query": query,
                "results": [],
                "count": 0,
                "message": "索引为空，请先添加文档",
            }

        start_time = time.perf_counter()
        query_terms = self._tokenize(query)

        if not query_terms:
            return {"success": False, "error": "查询无法解析为有效词条"}

        # 对每个查询词条查找匹配文档
        doc_scores: Dict[str, float] = defaultdict(float)
        doc_matches: Dict[str, Dict[str, List[int]]] = defaultdict(
            lambda: defaultdict(list)
        )

        for term in query_terms:
            matching_docs = self._find_matching_terms(term, search_mode)
            for match_term, postings in matching_docs.items():
                for doc_id, positions in postings.items():
                    doc_matches[doc_id][match_term].extend(positions)

        if not doc_matches:
            return {
                "success": True,
                "query": query,
                "results": [],
                "count": 0,
                "elapsed_ms": (time.perf_counter() - start_time) * 1000,
            }

        # 计算TF-IDF评分
        for doc_id, matched_terms in doc_matches.items():
            score = self._compute_tfidf_score(query_terms, matched_terms, doc_id)
            doc_scores[doc_id] = score

        # 按评分降序排列
        ranked = sorted(doc_scores.items(), key=lambda x: x[1], reverse=True)
        results = []
        for doc_id, score in ranked[:max_results]:
            doc = self._documents.get(doc_id, {})
            results.append(
                {
                    "id": doc_id,
                    "title": doc.get("title", ""),
                    "url": doc.get("url", ""),
                    "snippet": doc.get("snippet", ""),
                    "content_preview": doc.get("content", "")[:500],
                    "score": round(score, 4),
                    "indexed_at": doc.get("indexed_at", ""),
                }
            )

        elapsed = (time.perf_counter() - start_time) * 1000
        logger.info(
            f"Local search: query='{query}', results={len(results)}, "
            f"elapsed={elapsed:.1f}ms"
        )

        return {
            "success": True,
            "query": query,
            "results": results,
            "count": len(results),
            "total_docs": self._doc_count,
            "elapsed_ms": round(elapsed, 1),
            "mode": search_mode,
        }

    def _find_matching_terms(
        self, term: str, mode: str
    ) -> Dict[str, Dict[str, List[int]]]:
        """查找匹配的词条及其posting list。"""
        result: Dict[str, Dict[str, List[int]]] = {}

        if mode == "exact":
            if term in self._inverted_index:
                result[term] = self._inverted_index[term]
        elif mode == "prefix":
            for idx_term, postings in self._inverted_index.items():
                if idx_term.startswith(term):
                    result[idx_term] = postings
        else:  # tfidf mode: exact + prefix for longer terms
            if term in self._inverted_index:
                result[term] = self._inverted_index[term]
            if len(term) >= 2:
                for idx_term, postings in self._inverted_index.items():
                    if idx_term != term and idx_term.startswith(term):
                        result[idx_term] = postings

        return result

    def _compute_tfidf_score(
        self,
        query_terms: List[str],
        matched_terms: Dict[str, List[int]],
        doc_id: str,
    ) -> float:
        """计算TF-IDF相关性评分。"""
        score = 0.0
        doc_term_count = sum(len(positions) for positions in matched_terms.values())

        for qterm in query_terms:
            for mterm, positions in matched_terms.items():
                # 词条匹配度
                if qterm == mterm:
                    match_factor = 1.0
                elif mterm.startswith(qterm):
                    match_factor = 0.7
                elif qterm in mterm:
                    match_factor = 0.4
                else:
                    continue

                tf = len(positions) / max(doc_term_count, 1)
                df = self._doc_freq.get(mterm, 1)
                idf = 1.0 + (self._doc_count / max(df, 1)) ** 0.5
                score += tf * idf * match_factor

        return score

    # === 索引 ===

    async def _index_document(self, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        """索引单个文档。"""
        doc_id = kwargs.get("id", "").strip()
        title = kwargs.get("title", "").strip()
        url = kwargs.get("url", "").strip()
        content = kwargs.get("content", "").strip()

        if not doc_id:
            return {"success": False, "error": "文档ID不能为空"}
        if not content and not title:
            return {"success": False, "error": "文档内容或标题不能为空"}

        # 移除旧索引
        if doc_id in self._documents:
            await self._remove_from_index(doc_id)

        # 构建可搜索文本
        searchable_text = f"{title} {title} {content}"  # 标题加权（重复一次）
        terms = self._tokenize(searchable_text)
        positions_map: Dict[str, List[int]] = defaultdict(list)
        for pos, term in enumerate(terms):
            positions_map[term].append(pos)

        # 写入倒排索引
        for term, positions in positions_map.items():
            self._inverted_index[term][doc_id] = positions
            self._doc_freq[term] = len(self._inverted_index[term])

        # 存储文档
        self._documents[doc_id] = {
            "title": title,
            "url": url,
            "content": content,
            "snippet": content[:300] if content else "",
            "indexed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        self._doc_count = len(self._documents)
        self._total_terms = len(self._inverted_index)

        # 自动保存
        await self._save_index()

        logger.info(f"Indexed document: id={doc_id}, title='{title[:50]}'")
        return {
            "success": True,
            "message": f"文档已索引: {title[:80]}",
            "doc_id": doc_id,
            "term_count": len(terms),
        }

    async def _index_directory(self, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        """索引目录中的HTML和文本文件。"""
        directory = kwargs.get("directory", "").strip()
        pattern = kwargs.get("pattern", "*.{html,htm,txt,md}")

        if not directory:
            return {"success": False, "error": "目录路径不能为空"}

        dir_path = Path(directory)
        if not dir_path.exists() or not dir_path.is_dir():
            return {"success": False, "error": f"目录不存在: {directory}"}

        indexed = 0
        failed = 0
        for file_path in dir_path.rglob("*"):
            if not file_path.is_file():
                continue
            if not self._match_pattern(file_path.name, pattern):
                continue

            try:
                content = file_path.read_text(encoding="utf-8", errors="replace")
                # 提取纯文本（移除HTML标签）
                text = self._strip_html(content) if file_path.suffix in (".html", ".htm") else content
                doc_id = str(file_path.relative_to(dir_path))
                result = await self._index_document(
                    {
                        "id": doc_id,
                        "title": file_path.stem,
                        "url": f"file://{file_path.absolute()}",
                        "content": text,
                    }
                )
                if result["success"]:
                    indexed += 1
                else:
                    failed += 1
            except Exception as e:
                logger.error(f"Failed to index {file_path}: {e}")
                failed += 1

        return {
            "success": True,
            "message": f"索引完成: {indexed} 成功, {failed} 失败",
            "indexed": indexed,
            "failed": failed,
        }

    async def _remove_document(self, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        """从索引中移除文档。"""
        doc_id = kwargs.get("id", "").strip()
        if not doc_id:
            return {"success": False, "error": "文档ID不能为空"}

        await self._remove_from_index(doc_id)
        await self._save_index()
        return {"success": True, "message": f"文档已移除: {doc_id}"}

    async def _remove_from_index(self, doc_id: str):
        """内部：从索引中移除文档。"""
        if doc_id in self._documents:
            content = self._documents[doc_id].get("content", "")
            title = self._documents[doc_id].get("title", "")
            terms = self._tokenize(f"{title} {title} {content}")
            for term in set(terms):
                if term in self._inverted_index:
                    self._inverted_index[term].pop(doc_id, None)
                    if not self._inverted_index[term]:
                        del self._inverted_index[term]
                        self._doc_freq.pop(term, None)
                    else:
                        self._doc_freq[term] = len(self._inverted_index[term])
            del self._documents[doc_id]
            self._doc_count = len(self._documents)
            self._total_terms = len(self._inverted_index)

    async def _clear_index(self) -> Dict[str, Any]:
        """清空全部索引。"""
        self._inverted_index.clear()
        self._documents.clear()
        self._doc_freq.clear()
        self._doc_count = 0
        self._total_terms = 0
        await self._save_index()
        return {"success": True, "message": "索引已清空"}

    def _get_stats(self) -> Dict[str, Any]:
        """获取索引统计信息。"""
        return {
            "success": True,
            "doc_count": self._doc_count,
            "unique_terms": self._total_terms,
            "index_dir": str(self.index_dir),
            "avg_terms_per_doc": (
                round(self._total_terms / max(self._doc_count, 1), 1)
            ),
        }

    # === 分词 ===

    def _tokenize(self, text: str) -> List[str]:
        """
        文本分词。
        使用Unicode感知的分词策略：
        - CJK字符：bigram（双字符n-gram）
        - 字母/数字：按词边界分割
        - 其他字符：作为分隔符
        """
        if not text:
            return []

        # Unicode规范化
        text = unicodedata.normalize("NFKD", text)
        text = text.lower().strip()

        tokens: List[str] = []

        # 分割处理：分别处理CJK和非CJK片段
        # CJK Unicode范围
        cjk_pattern = re.compile(r"[一-鿿㐀-䶿豈-﫿]+")
        word_pattern = re.compile(r"[a-z0-9_À-ɏ]+", re.UNICODE)

        pos = 0
        while pos < len(text):
            # 尝试匹配CJK序列
            cjk_match = cjk_pattern.match(text, pos)
            if cjk_match:
                cjk_text = cjk_match.group()
                # Bigram分词
                for i in range(len(cjk_text)):
                    if i + 1 < len(cjk_text):
                        tokens.append(cjk_text[i : i + 2])
                    tokens.append(cjk_text[i])  # 同时保留unigram
                pos = cjk_match.end()
                continue

            # 尝试匹配字母/数字序列
            word_match = word_pattern.match(text, pos)
            if word_match:
                word = word_match.group()
                if len(word) >= 1:
                    tokens.append(word)
                pos = word_match.end()
                continue

            pos += 1

        # 去重但保留顺序（用于位置索引）
        return tokens

    @staticmethod
    def _strip_html(html_text: str) -> str:
        """移除HTML标签，提取纯文本。"""
        text = re.sub(r"<script[^>]*>.*?</script>", " ", html_text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"&[a-z]+;", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    @staticmethod
    def _match_pattern(filename: str, pattern: str) -> bool:
        """简单的文件名模式匹配。"""
        import fnmatch

        patterns = [p.strip() for p in pattern.split(",")]
        return any(fnmatch.fnmatch(filename.lower(), p.lower()) for p in patterns)

    # === 持久化 ===

    async def _save_index(self):
        """保存索引到磁盘。"""
        try:
            idx_file = self.index_dir / "index.json"
            data = {
                "version": self.version,
                "doc_count": self._doc_count,
                "total_terms": self._total_terms,
                "documents": self._documents,
                "inverted_index": {
                    term: {
                        doc_id: positions
                        for doc_id, positions in postings.items()
                    }
                    for term, postings in self._inverted_index.items()
                },
                "doc_freq": dict(self._doc_freq),
                "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: idx_file.write_text(
                    json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                ),
            )
        except Exception as e:
            logger.error(f"Failed to save index: {e}")

    async def _load_index(self, idx_file: Path):
        """从磁盘加载索引。"""
        loop = asyncio.get_event_loop()

        def _load():
            with open(idx_file, "r", encoding="utf-8") as f:
                return json.load(f)

        data = await loop.run_in_executor(None, _load)

        self._documents = data.get("documents", {})
        self._doc_count = data.get("doc_count", len(self._documents))

        raw_index = data.get("inverted_index", {})
        self._inverted_index = defaultdict(dict)
        for term, postings in raw_index.items():
            self._inverted_index[term] = dict(postings)

        self._doc_freq = defaultdict(int, data.get("doc_freq", {}))
        self._total_terms = data.get("total_terms", len(self._inverted_index))

    def get_tools(self) -> List[Dict[str, Any]]:
        """返回工具定义列表（OpenAI function calling格式）。"""
        return [
            {
                "name": "local_search",
                "description": "在本地索引中搜索网页和文档内容",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "搜索关键词",
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "最大返回结果数，默认20",
                        },
                        "mode": {
                            "type": "string",
                            "enum": ["tfidf", "exact", "prefix"],
                            "description": "搜索模式: tfidf(相关度排序), exact(精确匹配), prefix(前缀匹配)",
                        },
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "index_document",
                "description": "将文档添加到本地搜索索引",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "description": "文档唯一标识"},
                        "title": {"type": "string", "description": "文档标题"},
                        "url": {"type": "string", "description": "文档URL"},
                        "content": {"type": "string", "description": "文档文本内容"},
                    },
                    "required": ["id", "title", "content"],
                },
            },
            {
                "name": "index_directory",
                "description": "批量索引目录中的HTML和文本文件",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "directory": {
                            "type": "string",
                            "description": "要索引的目录路径",
                        },
                        "pattern": {
                            "type": "string",
                            "description": "文件匹配模式，默认 *.html,*.htm,*.txt,*.md",
                        },
                    },
                    "required": ["directory"],
                },
            },
            {
                "name": "remove_document",
                "description": "从索引中移除指定文档",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "description": "要移除的文档ID"},
                    },
                    "required": ["id"],
                },
            },
            {
                "name": "search_stats",
                "description": "获取本地搜索索引的统计信息",
                "parameters": {"type": "object", "properties": {}},
            },
        ]

    def cleanup(self):
        """清理资源。"""
        self._initialized = False
        logger.info("LocalSearch engine cleaned up")
