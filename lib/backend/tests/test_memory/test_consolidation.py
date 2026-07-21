"""
Memory consolidation 模块测试。
"""
import pytest
from memory.consolidation import (
    calculate_similarity,
    cluster_memories,
    consolidate_cluster_embeddings,
    MemoryCluster,
    calculate_cluster_stats,
)


class TestCalculateSimilarity:
    """calculate_similarity 函数测试。"""

    def test_calculate_similarity_identical(self):
        """相同向量相似度为 1.0。"""
        emb = [1.0, 2.0, 3.0]
        result = calculate_similarity(emb, emb)
        assert result == pytest.approx(1.0, abs=0.001)

    def test_calculate_similarity_orthogonal(self):
        """正交向量相似度为 0.0。"""
        emb1 = [1.0, 0.0, 0.0]
        emb2 = [0.0, 1.0, 0.0]
        result = calculate_similarity(emb1, emb2)
        assert result == pytest.approx(0.0, abs=0.001)

    def test_calculate_similarity_opposite(self):
        """相反向量相似度为 -1.0。"""
        emb1 = [1.0, 2.0, 3.0]
        emb2 = [-1.0, -2.0, -3.0]
        result = calculate_similarity(emb1, emb2)
        assert result == pytest.approx(-1.0, abs=0.001)

    def test_calculate_similarity_empty(self):
        """空向量相似度为 0.0。"""
        result = calculate_similarity([], [1.0, 2.0])
        assert result == 0.0

    def test_calculate_similarity_different_length(self):
        """不同长度向量相似度为 0.0。"""
        result = calculate_similarity([1.0, 2.0], [1.0, 2.0, 3.0])
        assert result == 0.0

    def test_calculate_similarity_zero_norm(self):
        """零向量相似度为 0.0。"""
        result = calculate_similarity([0.0, 0.0], [1.0, 2.0])
        assert result == 0.0


class TestClusterMemories:
    """cluster_memories 函数测试。"""

    def test_cluster_memories_empty(self):
        """空记忆列表返回空。"""
        result = cluster_memories([], {})
        assert result == []

    def test_cluster_memories_no_embeddings(self):
        """无向量映射返回空。"""
        result = cluster_memories([1, 2, 3], {})
        assert result == []

    def test_cluster_memories_high_similarity(self):
        """高相似度记忆被聚类到一起。"""
        memory_ids = [1, 2]
        embeddings = {
            1: [1.0, 0.0, 0.0],
            2: [0.999, 0.001, 0.0],  # 与 1 高度相似
        }
        result = cluster_memories(memory_ids, embeddings, similarity_threshold=0.8)
        # 两个记忆应合并为一个聚类
        assert len(result) == 1
        assert len(result[0].memory_ids) == 2

    def test_cluster_memories_low_similarity(self):
        """低相似度记忆不聚类。"""
        memory_ids = [1, 2]
        embeddings = {
            1: [1.0, 0.0, 0.0],
            2: [0.0, 1.0, 0.0],  # 正交，相似度低
        }
        result = cluster_memories(memory_ids, embeddings, similarity_threshold=0.8)
        # 相似度低于阈值，不聚类，且 min_cluster_size=2 时单个记忆不保留
        assert len(result) == 0

    def test_cluster_memories_min_size(self):
        """min_cluster_size 过滤小聚类。"""
        memory_ids = [1, 2, 3]
        embeddings = {
            1: [1.0, 0.0],
            2: [0.999, 0.001],
            3: [0.0, 1.0],
        }
        result = cluster_memories(
            memory_ids, embeddings, similarity_threshold=0.8, min_cluster_size=2
        )
        assert len(result) == 1
        assert 1 in result[0].memory_ids
        assert 2 in result[0].memory_ids

    def test_cluster_memories_missing_embedding(self):
        """缺少向量的记忆被忽略。"""
        memory_ids = [1, 2]
        embeddings = {1: [1.0, 0.0]}  # 2 的向量缺失
        result = cluster_memories(memory_ids, embeddings, similarity_threshold=0.5)
        # 只有 1 有向量，但只有 1 个记忆，min_cluster_size=2 过滤掉
        assert len(result) == 0


class TestConsolidateClusterEmbeddings:
    """consolidate_cluster_embeddings 函数测试。"""

    def test_consolidate_cluster_embeddings(self):
        """计算聚类质心。"""
        cluster = MemoryCluster(
            cluster_id="test",
            memory_ids=[1, 2],
        )
        embeddings = {
            1: [1.0, 3.0],
            2: [3.0, 1.0],
        }
        centroid = consolidate_cluster_embeddings(cluster, embeddings)
        assert centroid is not None
        assert centroid == [2.0, 2.0]

    def test_consolidate_cluster_embeddings_empty(self):
        """空聚类返回 None。"""
        cluster = MemoryCluster(cluster_id="empty", memory_ids=[])
        result = consolidate_cluster_embeddings(cluster, {})
        assert result is None

    def test_consolidate_cluster_embeddings_no_matching(self):
        """无匹配向量返回 None。"""
        cluster = MemoryCluster(cluster_id="test", memory_ids=[1, 2])
        result = consolidate_cluster_embeddings(cluster, {})
        assert result is None

    def test_consolidate_cluster_embeddings_single(self):
        """单个记忆的质心即其向量。"""
        cluster = MemoryCluster(cluster_id="test", memory_ids=[1])
        embeddings = {1: [5.0, 10.0]}
        centroid = consolidate_cluster_embeddings(cluster, embeddings)
        assert centroid == [5.0, 10.0]


class TestMemoryCluster:
    """MemoryCluster 数据类测试。"""

    def test_memory_cluster_defaults(self):
        """MemoryCluster 默认值。"""
        cluster = MemoryCluster(cluster_id="test")
        assert cluster.cluster_id == "test"
        assert cluster.memory_ids == []
        assert cluster.centroid_embedding is None
        assert cluster.topic == ""
        assert cluster.avg_importance == 0.0
        assert cluster.avg_access_count == 0


class TestCalculateClusterStats:
    """calculate_cluster_stats 函数测试。"""

    def test_calculate_cluster_stats(self):
        """计算聚类统计信息。"""
        cluster = MemoryCluster(cluster_id="test", memory_ids=[1, 2, 3])
        importance_map = {1: 0.5, 2: 0.7, 3: 0.9}
        access_count_map = {1: 10, 2: 20, 3: 30}
        calculate_cluster_stats(cluster, importance_map, access_count_map)
        assert cluster.avg_importance == pytest.approx(0.7, abs=0.01)
        assert cluster.avg_access_count == 20  # (10+20+30)//3

    def test_calculate_cluster_stats_empty(self):
        """空聚类统计为 0。"""
        cluster = MemoryCluster(cluster_id="empty", memory_ids=[])
        calculate_cluster_stats(cluster, {}, {})
        assert cluster.avg_importance == 0.0
        assert cluster.avg_access_count == 0

    def test_calculate_cluster_stats_missing_mappings(self):
        """缺失映射时使用默认值 0。"""
        cluster = MemoryCluster(cluster_id="test", memory_ids=[1, 2])
        importance_map = {1: 0.5}  # 2 缺失
        access_count_map = {}  # 全部缺失
        calculate_cluster_stats(cluster, importance_map, access_count_map)
        assert cluster.avg_importance == pytest.approx(0.25, abs=0.01)
        assert cluster.avg_access_count == 0