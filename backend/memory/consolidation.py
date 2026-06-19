"""
记忆巩固机制实现。
提供记忆聚类、跨层关联和记忆合并功能。
"""

from typing import Dict, List, Optional, Set
from dataclasses import dataclass, field


@dataclass
class MemoryCluster:
    """
    记忆聚类结构。
    将相似的记忆聚合在一起，形成概念簇。
    """
    cluster_id: str
    memory_ids: List[int] = field(default_factory=list)
    centroid_embedding: Optional[List[float]] = None
    topic: str = ""
    avg_importance: float = 0.0
    avg_access_count: int = 0


def calculate_similarity(
    embedding1: List[float],
    embedding2: List[float]
) -> float:
    """
    计算两个向量的余弦相似度。
    
    Args:
        embedding1: 向量1
        embedding2: 向量2
    
    Returns:
        float: 相似度（-1.0到1.0）
    """
    if not embedding1 or not embedding2 or len(embedding1) != len(embedding2):
        return 0.0
    
    dot_product = sum(a * b for a, b in zip(embedding1, embedding2))
    norm1 = sum(a * a for a in embedding1) ** 0.5
    norm2 = sum(b * b for b in embedding2) ** 0.5
    
    if norm1 == 0 or norm2 == 0:
        return 0.0
    
    return dot_product / (norm1 * norm2)


def cluster_memories(
    memory_ids: List[int],
    embeddings: Dict[int, List[float]],
    similarity_threshold: float = 0.8,
    min_cluster_size: int = 2
) -> List[MemoryCluster]:
    """
    基于向量相似度对记忆进行聚类。
    
    使用简单的单链接聚类算法：
    1. 遍历所有记忆对
    2. 如果相似度超过阈值，将它们合并到同一聚类
    3. 过滤掉小于最小聚类大小的簇
    
    Args:
        memory_ids: 记忆ID列表
        embeddings: 记忆ID到向量的映射
        similarity_threshold: 相似度阈值，默认0.8
        min_cluster_size: 最小聚类大小，默认2
    
    Returns:
        List[MemoryCluster]: 聚类结果列表
    """
    if not memory_ids or not embeddings:
        return []
    
    # 初始化每个记忆为自己的聚类
    clusters: Dict[int, Set[int]] = {mid: {mid} for mid in memory_ids if mid in embeddings}
    
    # 两两比较，合并相似记忆
    memory_list = [mid for mid in memory_ids if mid in embeddings]
    for i in range(len(memory_list)):
        for j in range(i + 1, len(memory_list)):
            mid1 = memory_list[i]
            mid2 = memory_list[j]
            
            similarity = calculate_similarity(embeddings[mid1], embeddings[mid2])
            
            if similarity >= similarity_threshold:
                # 找到各自的聚类并合并
                cluster1 = None
                cluster2 = None
                for cid, members in clusters.items():
                    if mid1 in members:
                        cluster1 = cid
                    if mid2 in members:
                        cluster2 = cid
                
                if cluster1 is not None and cluster2 is not None and cluster1 != cluster2:
                    # 合并聚类
                    clusters[cluster1].update(clusters[cluster2])
                    del clusters[cluster2]
    
    # 转换为 MemoryCluster 对象
    result = []
    for idx, (cid, members) in enumerate(clusters.items()):
        if len(members) >= min_cluster_size:
            cluster = MemoryCluster(
                cluster_id=f"cluster_{idx}",
                memory_ids=list(members)
            )
            result.append(cluster)
    
    return result


def consolidate_cluster_embeddings(
    cluster: MemoryCluster,
    embeddings: Dict[int, List[float]]
) -> Optional[List[float]]:
    """
    计算聚类的中心向量（质心）。
    
    Args:
        cluster: 记忆聚类
        embeddings: 记忆ID到向量的映射
    
    Returns:
        Optional[List[float]]: 质心向量，如果聚类为空则返回None
    """
    if not cluster.memory_ids:
        return None
    
    valid_embeddings = [embeddings[mid] for mid in cluster.memory_ids if mid in embeddings]
    
    if not valid_embeddings:
        return None
    
    # 计算平均值作为质心
    dim = len(valid_embeddings[0])
    centroid = [0.0] * dim
    
    for emb in valid_embeddings:
        for i in range(dim):
            centroid[i] += emb[i]
    
    for i in range(dim):
        centroid[i] /= len(valid_embeddings)
    
    return centroid


def merge_similar_clusters(
    clusters: List[MemoryCluster],
    embeddings: Dict[int, List[float]],
    similarity_threshold: float = 0.85
) -> List[MemoryCluster]:
    """
    合并相似的聚类。
    
    如果两个聚类的质心相似度超过阈值，则合并它们。
    
    Args:
        clusters: 聚类列表
        embeddings: 记忆ID到向量的映射
        similarity_threshold: 相似度阈值，默认0.85
    
    Returns:
        List[MemoryCluster]: 合并后的聚类列表
    """
    if len(clusters) <= 1:
        return clusters
    
    # 计算每个聚类的质心
    for cluster in clusters:
        cluster.centroid_embedding = consolidate_cluster_embeddings(cluster, embeddings)
    
    # 合并相似聚类
    merged = True
    while merged:
        merged = False
        new_clusters = []
        used = set()
        
        for i in range(len(clusters)):
            if i in used:
                continue
            
            current = clusters[i]
            merged_cluster = MemoryCluster(
                cluster_id=current.cluster_id,
                memory_ids=list(current.memory_ids),
                centroid_embedding=current.centroid_embedding
            )
            
            for j in range(i + 1, len(clusters)):
                if j in used:
                    continue
                
                other = clusters[j]
                
                if current.centroid_embedding and other.centroid_embedding:
                    similarity = calculate_similarity(
                        current.centroid_embedding,
                        other.centroid_embedding
                    )
                    
                    if similarity >= similarity_threshold:
                        # 合并聚类
                        merged_cluster.memory_ids.extend(other.memory_ids)
                        merged_cluster.centroid_embedding = consolidate_cluster_embeddings(
                            merged_cluster, embeddings
                        )
                        used.add(j)
                        merged = True
            
            new_clusters.append(merged_cluster)
            used.add(i)
        
        clusters = new_clusters
    
    return clusters


def calculate_cluster_stats(
    cluster: MemoryCluster,
    importance_map: Dict[int, float],
    access_count_map: Dict[int, int]
) -> None:
    """
    计算聚类的统计信息（平均重要度、平均访问次数）。
    
    Args:
        cluster: 记忆聚类
        importance_map: 记忆ID到重要度的映射
        access_count_map: 记忆ID到访问次数的映射
    """
    if not cluster.memory_ids:
        cluster.avg_importance = 0.0
        cluster.avg_access_count = 0
        return
    
    total_importance = sum(importance_map.get(mid, 0.0) for mid in cluster.memory_ids)
    total_access = sum(access_count_map.get(mid, 0) for mid in cluster.memory_ids)
    
    cluster.avg_importance = total_importance / len(cluster.memory_ids)
    cluster.avg_access_count = total_access // len(cluster.memory_ids)
