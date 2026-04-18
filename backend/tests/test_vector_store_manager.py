"""
向量存储管理器测试，验证向量写入、检索、用户隔离与归档过滤行为。
"""

import math
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from memory.vector_store_manager import VectorStoreManager


class SemanticTestEmbeddingProvider:
    """
    测试专用嵌入提供方。
    通过关键词分组构造确定性向量，便于验证语义检索路径。
    """

    provider_name = "test-semantic"

    def __init__(self):
        self.keyword_groups = [
            ["过拟合", "正则化", "机器学习"],
            ["数据库", "索引", "查询"],
            ["工作流", "自动化", "文件"],
        ]

    def embed_texts(self, texts):
        return [self._embed_single(text) for text in texts]

    def _embed_single(self, text):
        vector = []
        for group in self.keyword_groups:
            vector.append(1.0 if any(keyword in text for keyword in group) else 0.0)
        if not any(vector):
            vector = [1.0, 0.0, 0.0]
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]


def test_vector_store_upsert_search_and_delete(tmp_path):
    """
    验证向量存储支持新增、语义检索和删除。
    """
    manager = VectorStoreManager(
        persist_directory=str(tmp_path / "vector_db"),
        collection_name=f"test_collection_{uuid.uuid4().hex}",
        embedding_provider=SemanticTestEmbeddingProvider(),
    )

    manager.upsert_memory(
        1,
        "讨论过拟合与正则化技术的长期记忆",
        user_id="user-1",
        importance=0.9,
        metadata={"archive_status": "active"},
    )
    manager.upsert_memory(
        2,
        "数据库索引优化经验",
        user_id="user-1",
        importance=0.6,
        metadata={"archive_status": "active"},
    )

    hits = manager.search("机器学习中的过拟合问题", user_id="user-1", limit=5)

    assert hits
    assert hits[0].memory_id == 1
    assert hits[0].score >= hits[-1].score

    manager.delete_memory(1)
    remaining_hits = manager.search("机器学习中的过拟合问题", user_id="user-1", limit=5)

    assert all(hit.memory_id != 1 for hit in remaining_hits)


def test_vector_store_respects_user_filter_and_archive_status(tmp_path):
    """
    验证向量检索会按用户隔离数据，并默认过滤已归档记忆。
    """
    manager = VectorStoreManager(
        persist_directory=str(tmp_path / "vector_db"),
        collection_name=f"test_collection_{uuid.uuid4().hex}",
        embedding_provider=SemanticTestEmbeddingProvider(),
    )

    manager.upsert_memory(
        10,
        "工作流读取文件并写入结果",
        user_id="user-a",
        importance=0.8,
        archive_status="active",
    )
    manager.upsert_memory(
        11,
        "工作流归档版本",
        user_id="user-a",
        importance=0.4,
        archive_status="archived",
    )
    manager.upsert_memory(
        12,
        "工作流隔离到另一个用户",
        user_id="user-b",
        importance=0.9,
        archive_status="active",
    )

    hits = manager.search("文件自动化工作流", user_id="user-a", limit=10)
    archived_hits = manager.search("文件自动化工作流", user_id="user-a", limit=10, include_archived=True)

    assert {hit.memory_id for hit in hits} == {10}
    assert {hit.memory_id for hit in archived_hits} == {10, 11}