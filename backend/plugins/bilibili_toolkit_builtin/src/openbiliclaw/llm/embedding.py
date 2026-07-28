"""带有两层缓存的嵌入服务，用于语义相似度计算。

通过可配置的模型（默认：Gemini）提供文本嵌入，具有 L1 内存缓存和
L2 SQLite 持久化缓存。Discovery 将嵌入写入 L2；recommendation 在
热路径上以零 API 调用从 L2 读取。
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import sqlite3
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Protocol

logger = logging.getLogger(__name__)


class SupportsEmbed(Protocol):
    """支持文本嵌入的 provider 协议。"""

    async def embed(self, text: str, *, model: str = ...) -> list[float]: ...


class SupportsEmbeddingService(Protocol):
    """主流程服务使用的语义嵌入辅助协议。"""

    similarity_threshold: float

    async def embed(self, text: str) -> list[float]: ...

    def lookup_cached(self, text: str) -> list[float]:
        """仅查缓存；为协议兼容默认返回 ``[]``。"""
        return []


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """计算两个向量的余弦相似度（纯 Python 实现）。"""
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class EmbeddingCache:
    """基于 SQLite 的持久化嵌入缓存（L2）。

    将 text → vector 映射存放在专用表中，使 discovery 期间计算的嵌入
    可以跨进程重启保留，并在 recommendation 服务时无需任何 API 调用即可复用。

    线程安全：缓存会被运行在不同线程上的后台 discovery 与
    recommendation 预热 worker 读写，因此单连接以
    ``check_same_thread=False`` 打开，并且每次访问都通过 ``RLock``
    串行化（否则裸 ``sqlite3`` 连接会抛出
    "SQLite objects created in a thread can only be used in that same thread"）。
    """

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.RLock()

    def initialize(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            self._conn = sqlite3.connect(str(self._db_path), timeout=10.0, check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._ensure_schema()
            self._conn.commit()

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("EmbeddingCache not initialized")
        return self._conn

    def _ensure_schema(self) -> None:
        table_exists = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'embedding_cache'"
        ).fetchone()
        if table_exists is None:
            self._create_cache_table()
            return

        columns = self.conn.execute("PRAGMA table_info(embedding_cache)").fetchall()
        column_names = {str(row[1]) for row in columns}
        pk_columns = [
            str(row[1]) for row in sorted(columns, key=lambda row: int(row[5] or 0)) if row[5]
        ]
        if column_names >= {"text_key", "vector", "model"} and pk_columns == ["text_key", "model"]:
            return

        self.conn.execute("ALTER TABLE embedding_cache RENAME TO embedding_cache_legacy")
        self._create_cache_table()
        legacy_columns = {str(row[1]) for row in columns}
        if {"text_key", "vector"} <= legacy_columns:
            model_expr = "COALESCE(model, '')" if "model" in legacy_columns else "''"
            self.conn.execute(
                f"""INSERT OR REPLACE INTO embedding_cache (text_key, model, vector)
                    SELECT text_key, {model_expr}, vector
                    FROM embedding_cache_legacy"""
            )
        self.conn.execute("DROP TABLE embedding_cache_legacy")

    def _create_cache_table(self) -> None:
        self.conn.execute(
            """CREATE TABLE embedding_cache (
                text_key TEXT NOT NULL,
                model    TEXT NOT NULL DEFAULT '',
                vector   TEXT NOT NULL,
                PRIMARY KEY (text_key, model)
            )"""
        )

    def get(self, key: str, model: str = "") -> list[float] | None:
        with self._lock:
            if model:
                row = self.conn.execute(
                    "SELECT vector FROM embedding_cache WHERE text_key = ? AND model = ?",
                    (key, model),
                ).fetchone()
            else:
                row = self.conn.execute(
                    "SELECT vector FROM embedding_cache WHERE text_key = ? ORDER BY model LIMIT 1",
                    (key,),
                ).fetchone()
        if row is None:
            return None
        try:
            return _coerce_embedding_vector(json.loads(row[0]))
        except (json.JSONDecodeError, TypeError):
            return None

    def put(self, key: str, vector: list[float], model: str = "") -> None:
        with self._lock:
            self.conn.execute(
                """INSERT OR REPLACE INTO embedding_cache (text_key, vector, model)
                   VALUES (?, ?, ?)""",
                (key, json.dumps(vector), model),
            )
            self.conn.commit()

    def count(self) -> int:
        with self._lock:
            row = self.conn.execute("SELECT COUNT(*) FROM embedding_cache").fetchone()
        return row[0] if row else 0


class EmbeddingService:
    """用于语义相似度操作的缓存式嵌入服务。

    两层缓存：
    - L1：内存字典（最快，会话级作用域）
    - L2：SQLite 持久化缓存（可跨重启）

    Discovery 同时写入两层；recommendation 先查 L1，再查 L2，最后
    才退回 API 调用。

    所有参数（model、threshold、cache_size）都可通过 config.toml 中
    的 ``[llm.embedding]`` 配置。
    """

    # ``probe()`` 用于 /api/health 实时就绪检查的固定文本。
    _PROBE_TEXT = "openbiliclaw embedding readiness probe"

    def __init__(
        self,
        provider: SupportsEmbed,
        *,
        model: str = "gemini-embedding-001",
        cache_model: str | None = None,
        cache_size: int = 500,
        similarity_threshold: float = 0.82,
        persistent_cache: EmbeddingCache | None = None,
        max_concurrent_provider_calls: int = 2,
    ) -> None:
        self._provider = provider
        self._model = model
        self._cache_model = cache_model or model
        # OrderedDict + 命中时 move_to_end 给我们真正的 LRU，而不是
        # FIFO。500 键缓存配合突发访问模式（delight 打分会反复迭代
        # 同一组 like_texts），FIFO 会在缓存被冷缺失填满时驱逐高频
        # 命中的键。
        self._l1_cache: OrderedDict[str, list[float]] = OrderedDict()
        self._cache_size = cache_size
        self.similarity_threshold = similarity_threshold
        self._l2_cache = persistent_cache
        # 限制并发 provider 调用。本地 CPU 密集型 provider（单 GGUF
        # runner 上的 Ollama bge-m3）在 delight 打分 + topic supergroup
        # 合并 + speculator 的无限制 asyncio.gather 扇出下会崩溃。
        # v0.3.31 抓到过一次真实级联：代理修复落地后守护进程在 1 秒内
        # 派生了 14+ 个并发 embed 调用；Ollama 串行排队，超过 60s
        # 读超时，每个调用都返回 ``[]``。即便是云 provider，小并发上限
        # 也有助于摊薄 TLS 握手成本。默认值 2 在保持单 CPU bge-m3
        # 健康的同时仍能利用双核进行推理 + 分词。
        self._provider_semaphore = asyncio.Semaphore(max_concurrent_provider_calls)

    def lookup_cached(self, text: str) -> list[float]:
        """仅查缓存 —— 绝不触发 provider API 调用。

        未命中返回 ``[]``。调用方（recommendation 热路径）在需要
        硬延迟预算时使用：未命中意味着该条目在本批次中 simply 不
        参与基于嵌入的多样性，预热任务会异步填充缓存以供后续批次使用。
        """
        key = text.strip().lower()[:200]
        if not key:
            return []
        cached = self._l1_cache.get(key)
        if cached is not None:
            self._l1_cache.move_to_end(key)
            return cached
        if self._l2_cache is not None:
            persisted = self._l2_cache.get(key, model=self._cache_model)
            if persisted is not None:
                self._l1_cache[key] = persisted
                return persisted
        return []

    async def embed(self, text: str) -> list[float]:
        """获取文本的嵌入。依次查 L1 → L2 → API。"""
        key = text.strip().lower()[:200]
        if not key:
            return []

        # L1 / L2 缓存查找（也覆盖预热侧的命中）。
        cached = self.lookup_cached(text)
        if cached:
            return cached

        # L3：API 调用（已限流 —— 见 __init__ 中 semaphore 注释）
        async with self._provider_semaphore:
            try:
                vector = await self._provider.embed(key, model=self._model)
            except Exception:
                logger.warning("Embedding failed for: %s", key[:50], exc_info=True)
                return []

        # 绝不缓存空向量。空意味着 provider 透明地失败了（例如吞掉
        # 了超时）并返回 ``[]``；缓存它会把该文本永久钉在"无嵌入"上，
        # 即便上游问题已修复也不变。v0.3.31 在此守卫存在前有约 170
        # 个键被这样污染 —— 游戏攻略 / 洛克王国 / 金铲铲之战 等顶级
        # 用户兴趣受影响，级联悄然把 DelightScorer 中最相关内容的
        # likes_alignment 置零。每次出现都打 WARN，让失败模式在服务层
        # 可见，而不是埋在 provider 级日志里。
        if not vector:
            logger.warning(
                "Embedding service got empty vector for key=%r — "
                "provider returned [] (likely transient failure). "
                "Skipping cache write so the next call retries.",
                key[:80],
            )
            return []

        # 同时写入两层缓存（LRU 驱逐：popitem(last=False) 丢弃
        # 最久未使用的条目 —— 配合上面缓存命中时的 move_to_end，
        # 这是真正的 LRU 而非 FIFO）。
        if len(self._l1_cache) >= self._cache_size:
            self._l1_cache.popitem(last=False)
        self._l1_cache[key] = vector

        if self._l2_cache is not None:
            try:
                self._l2_cache.put(key, vector, model=self._cache_model)
            except Exception:
                logger.debug("L2 cache write failed", exc_info=True)

        return vector

    async def probe(self) -> bool:
        """实时就绪检查 —— 绕过缓存并直接调用一次 provider。

        仅当 provider 当前返回非空向量时才返回 ``True``。L1/L2 缓存
        被故意绕过：之前缓存的成功绝不能掩盖此后已宕机的 provider
        （Ollama 停了、``bge-m3`` 从未拉取导致每次调用 404、远端
        密钥被吊销……）。``/api/health`` 在自身的短 TTL + 单飞机制后
        调用本方法，因此额外的 provider 往返每分钟最多发生几次。
        """
        async with self._provider_semaphore:
            try:
                vector = await self._provider.embed(self._PROBE_TEXT, model=self._model)
            except Exception:
                logger.debug("Embedding readiness probe failed", exc_info=True)
                return False
        return bool(vector)

    async def are_similar(self, text_a: str, text_b: str) -> bool:
        """判断两段文本是否在阈值之上语义相似。"""
        vec_a = await self.embed(text_a)
        vec_b = await self.embed(text_b)
        if not vec_a or not vec_b:
            return False
        return cosine_similarity(vec_a, vec_b) >= self.similarity_threshold

    async def find_similar_cluster(
        self,
        text: str,
        existing_clusters: dict[str, list[float]],
    ) -> str | None:
        """找出文本属于哪个已有聚类，若为新内容则返回 None。

        Args:
            text: 待分类的文本。
            existing_clusters: cluster_label → centroid_vector 的映射。

        Returns:
            最相似聚类的标签（若高于阈值），否则返回 None。
        """
        vec = await self.embed(text)
        if not vec:
            return None
        best_label: str | None = None
        best_sim = 0.0
        for label, centroid in existing_clusters.items():
            sim = cosine_similarity(vec, centroid)
            if sim > best_sim:
                best_sim = sim
                best_label = label
        if best_sim >= self.similarity_threshold:
            return best_label
        return None

    def clear_cache(self) -> None:
        """清空嵌入缓存。"""
        self._l1_cache.clear()


def _coerce_embedding_vector(value: object) -> list[float] | None:
    if not isinstance(value, list):
        return None
    vector: list[float] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            return None
        vector.append(float(item))
    return vector
