"""
工作内存模块，提供基于内存缓存的高频记忆层。
该层使用轻量 LRU 策略，并引入访问频率与时间衰减综合决定淘汰对象。
所有公共方法均受 threading.Lock 保护，确保多线程并发安全。
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


@dataclass
class WorkingMemoryEntry:
    """
    工作内存条目，记录内容、最近访问时间与命中次数。
    """

    memory_id: str
    user_id: Optional[str]
    payload: Dict[str, Any]
    last_accessed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    access_count: int = 1

    def touch(self) -> None:
        """
        更新访问统计，便于后续淘汰策略计算。
        """
        self.access_count += 1
        self.last_accessed_at = datetime.now(timezone.utc)


class WorkingMemoryStore:
    """
    工作内存仓库。
    默认按用户维度隔离，每个用户维护独立的有序缓存。
    """

    def __init__(self, capacity_per_user: int = 32):
        self.capacity_per_user = capacity_per_user
        self._entries: Dict[str, OrderedDict[str, WorkingMemoryEntry]] = {}
        self._lock = threading.Lock()

    def _bucket_key(self, user_id: Optional[str]) -> str:
        return str(user_id or "anonymous")

    def _get_bucket(self, user_id: Optional[str]) -> OrderedDict[str, WorkingMemoryEntry]:
        bucket_key = self._bucket_key(user_id)
        if bucket_key not in self._entries:
            self._entries[bucket_key] = OrderedDict()
        return self._entries[bucket_key]

    def _eviction_score(self, entry: WorkingMemoryEntry) -> float:
        """
        综合访问频率与时间衰减计算淘汰优先级。
        分数越低越容易被淘汰。
        """
        age_hours = max(
            0.0,
            (datetime.now(timezone.utc) - entry.last_accessed_at).total_seconds() / 3600,
        )
        return entry.access_count - (age_hours * 0.5)

    def _evict_if_needed(self, user_id: Optional[str]) -> None:
        bucket = self._get_bucket(user_id)
        while len(bucket) > self.capacity_per_user:
            victim_key = min(bucket, key=lambda key: self._eviction_score(bucket[key]))
            bucket.pop(victim_key, None)

    def put(self, memory_id: str, payload: Dict[str, Any], user_id: Optional[str] = None) -> WorkingMemoryEntry:
        """
        写入或刷新工作内存条目。
        """
        with self._lock:
            bucket = self._get_bucket(user_id)
            if memory_id in bucket:
                entry = bucket.pop(memory_id)
                entry.payload = payload
                entry.touch()
            else:
                entry = WorkingMemoryEntry(memory_id=memory_id, user_id=user_id, payload=payload)
            bucket[memory_id] = entry
            self._evict_if_needed(user_id)
            return entry

    def get(self, memory_id: str, user_id: Optional[str] = None) -> Optional[WorkingMemoryEntry]:
        """
        读取工作内存条目，并刷新访问顺序。
        """
        with self._lock:
            bucket = self._get_bucket(user_id)
            entry = bucket.pop(memory_id, None)
            if entry is None:
                return None
            entry.touch()
            bucket[memory_id] = entry
            return entry

    def pop(self, memory_id: str, user_id: Optional[str] = None) -> Optional[WorkingMemoryEntry]:
        """
        删除工作内存条目。
        """
        with self._lock:
            return self._get_bucket(user_id).pop(memory_id, None)

    def list_entries(self, user_id: Optional[str] = None) -> List[WorkingMemoryEntry]:
        """
        返回指定用户的工作内存条目列表。
        """
        with self._lock:
            bucket = self._get_bucket(user_id)
            return list(reversed(bucket.values()))

    def stats(self, user_id: Optional[str] = None) -> Dict[str, Any]:
        """
        返回工作内存容量与当前命中情况。
        """
        with self._lock:
            bucket = self._get_bucket(user_id)
            return {
                "capacity": self.capacity_per_user,
                "count": len(bucket),
                "memory_ids": list(bucket.keys()),
            }


working_memory_store = WorkingMemoryStore()