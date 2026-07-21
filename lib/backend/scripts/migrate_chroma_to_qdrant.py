"""
ChromaDB → Qdrant 数据迁移脚本。

本脚本提供两条迁移路径，默认走"从 LongTermMemory 数据库表重新索引"路径，
因为 Qdrant collection 维度由当前嵌入提供方决定，可能与旧 Chroma 维度不同，
重新嵌入最稳妥，也避免对已从 requirements.txt 移除的 chromadb 包产生依赖。

路径 A（默认）：从 LongTermMemory 表重新嵌入并写入 Qdrant
    优点：不依赖 chromadb，能自动适配当前嵌入维度
    代价：会消耗嵌入调用次数（OpenAI 模式下会产生费用）

路径 B（可选）：直接从 ChromaDB 读取已存向量并迁移
    前提：执行前临时安装 chromadb（pip install chromadb==0.4.22）
    限制：仅当 Qdrant collection 维度与 Chroma 一致时才可用

用法：
    cd backend
    python scripts/migrate_chroma_to_qdrant.py                 # 路径 A
    python scripts/migrate_chroma_to_qdrant.py --from-chroma   # 路径 B
    python scripts/migrate_chroma_to_qdrant.py --dry-run       # 仅打印计划，不写入

注意：
- 数据量较小时建议直接冷启动：删除 var/data/vector_db 目录，
  让系统在启动后通过 MemoryManager 重新写入即可。
- 该脚本不修改 .env、密钥文件或 Alembic 迁移版本。
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List

# 确保可以 import backend 内部模块
_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from loguru import logger

from config.settings import settings
from db.models import LongTermMemory
from memory.vector_store_manager import VectorStoreManager


def _iter_long_term_memories() -> Iterable[Dict[str, Any]]:
    """
    从 LongTermMemory 表流式读取所有记忆记录，避免一次性加载大表导致内存峰值。
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    db_url = os.getenv("DATABASE_URL", "sqlite:///./data/openawa.db")
    engine = create_engine(db_url)
    Session = sessionmaker(bind=engine)

    with Session() as session:
        rows = session.query(LongTermMemory).all()
        for row in rows:
            yield {
                "memory_id": row.id,
                "content": row.content or "",
                "user_id": row.user_id,
                "importance": float(row.importance or 0.5),
                "archive_status": row.archive_status or "active",
                "memory_metadata": row.memory_metadata or {},
            }


async def _migrate_from_db(target_path: str, collection_name: str, dry_run: bool) -> int:
    """
    路径 A：从 LongTermMemory 表读取并重新嵌入到 Qdrant。
    返回写入条数。
    """
    manager = VectorStoreManager(
        persist_directory=target_path,
        collection_name=collection_name,
    )
    logger.info(
        f"开始从 LongTermMemory 表迁移到 Qdrant: collection={collection_name} "
        f"provider={manager.provider_name}"
    )

    count = 0
    for row in _iter_long_term_memories():
        if dry_run:
            logger.info(f"[DRY-RUN] 将写入 memory_id={row['memory_id']}")
            count += 1
            continue

        try:
            await manager.upsert_memory(
                row["memory_id"],
                row["content"],
                user_id=row["user_id"],
                importance=row["importance"],
                archive_status=row["archive_status"],
                metadata=row["memory_metadata"],
            )
            count += 1
            if count % 100 == 0:
                logger.info(f"已迁移 {count} 条")
        except Exception as exc:
            logger.warning(f"迁移 memory_id={row['memory_id']} 失败: {exc}")

    if not dry_run:
        manager.close()
    logger.info(f"迁移完成，共写入 {count} 条记录到 Qdrant")
    return count


def _migrate_from_chroma(source_path: str, target_path: str, collection_name: str, dry_run: bool) -> int:
    """
    路径 B：直接从 ChromaDB 读取已存向量与文档迁移到 Qdrant。
    要求执行前临时安装 chromadb 包。
    """
    try:
        import chromadb  # noqa: F401
    except ImportError:
        logger.error(
            "未安装 chromadb。请先临时安装: pip install chromadb==0.4.22，"
            "或改用默认路径 A：python scripts/migrate_chroma_to_qdrant.py"
        )
        return 0

    import chromadb  # type: ignore
    from qdrant_client import QdrantClient, models

    if not Path(source_path).exists():
        logger.error(f"Chroma 数据目录不存在: {source_path}")
        return 0

    chroma_client = chromadb.PersistentClient(path=source_path)
    try:
        chroma_collection = chroma_client.get_collection(name=collection_name)
    except Exception as exc:
        logger.error(f"获取 Chroma collection 失败: {collection_name}: {exc}")
        return 0

    chroma_data = chroma_collection.get(include=["documents", "metadatas", "embeddings"])
    ids = chroma_data.get("ids") or []
    documents = chroma_data.get("documents") or []
    metadatas = chroma_data.get("metadatas") or []
    embeddings = chroma_data.get("embeddings") or []

    if not ids:
        logger.info("Chroma collection 为空，无需迁移")
        return 0

    if dry_run:
        logger.info(f"[DRY-RUN] 计划从 Chroma 迁移 {len(ids)} 条到 Qdrant")
        return len(ids)

    # 直接以 Qdrant 原始客户端写入，使用整型 ID（从 metadata.memory_id 取）
    qdrant_client = QdrantClient(path=target_path)
    dimension = len(embeddings[0]) if embeddings else 32
    if not qdrant_client.collection_exists(collection_name):
        qdrant_client.create_collection(
            collection_name=collection_name,
            vectors_config={"dense": models.VectorParams(size=dimension, distance=models.Distance.COSINE)},
            sparse_vectors_config={"sparse": models.SparseVectorParams()},
        )

    from memory.vector_store_manager import compute_sparse_vector

    points: List[models.PointStruct] = []
    for index, doc_id in enumerate(ids):
        document = documents[index] if index < len(documents) else ""
        metadata = metadatas[index] if index < len(metadatas) else {}
        embedding = embeddings[index] if index < len(embeddings) else []
        memory_id = int(metadata.get("memory_id") or 0)
        if memory_id <= 0:
            logger.warning(f"跳过缺少 memory_id 的记录: {doc_id}")
            continue
        sparse_vector = compute_sparse_vector(document)
        points.append(
            models.PointStruct(
                id=memory_id,
                vector={"dense": embedding, "sparse": sparse_vector},
                payload={**metadata, "content": document},
            )
        )

    if points:
        qdrant_client.upsert(collection_name=collection_name, points=points)
    qdrant_client.close()
    logger.info(f"迁移完成，共写入 {len(points)} 条记录到 Qdrant")
    return len(points)


async def main() -> int:
    parser = argparse.ArgumentParser(description="ChromaDB → Qdrant 数据迁移")
    parser.add_argument(
        "--from-chroma",
        action="store_true",
        help="直接从 ChromaDB 读取已存向量迁移（需 pip install chromadb==0.4.22）",
    )
    parser.add_argument(
        "--source",
        default=str(_BACKEND_DIR / "data" / "vector_db"),
        help="Chroma 数据目录（仅 --from-chroma 模式使用）",
    )
    parser.add_argument(
        "--target",
        default=None,
        help="Qdrant 数据目录，默认使用 settings.VECTOR_DB_PATH",
    )
    parser.add_argument(
        "--collection",
        default="long_term_memory",
        help="Qdrant collection 名称",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅打印计划，不真正写入",
    )
    args = parser.parse_args()

    target_path = args.target or settings.VECTOR_DB_PATH
    os.makedirs(target_path, exist_ok=True)

    logger.info(f"Qdrant 目标路径: {target_path}")
    logger.info(f"collection: {args.collection}")

    if args.from_chroma:
        count = _migrate_from_chroma(args.source, target_path, args.collection, args.dry_run)
    else:
        count = await _migrate_from_db(target_path, args.collection, args.dry_run)

    logger.info(f"总迁移条数: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
