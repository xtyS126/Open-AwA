"""
记忆缓存管理器：负责向量搜索缓存、历史缓存、工作内存同步。
"""

from __future__ import annotations

import time
from collections import OrderedDict
from threading import Lock
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger


class MemoryCacheManager:
    """记忆缓存管理器：管理向量搜索 LRU 缓存和对话历史 TTL 缓存。"""

    def __init__(self, max_vector_cache_size: int = 128, history_cache_maxsize: int = 128, history_cache_ttl: float = 5.0):
        self._vector_search_cache: "OrderedDict[Tuple[str, Optional[str]], List[Any]]" = OrderedDict()
        self._vector_search_cache_lock = Lock()
        self._max_vector_cache_size = max_vector_cache_size
        self._history_cache: "OrderedDict[Tuple[str, int, str], Tuple[List[Any], float]]" = OrderedDict()
        self._history_cache_lock = Lock()
        self._history_cache_maxsize = history_cache_maxsize
        self._history_cache_ttl = history_cache_ttl

    def get_vector_cache(self, key: Tuple[str, Optional[str]]) -> Optional[Any]:
        """获取向量搜索缓存（LRU 命中时移到末尾）。"""
        with self._vector_search_cache_lock:
            if key in self._vector_search_cache:
                self._vector_search_cache.move_to_end(key)
                return self._vector_search_cache[key]
        return None

    def set_vector_cache(self, key: Tuple[str, Optional[str]], value: Any) -> None:
        """设置向量搜索缓存，超容量时淘汰最久未使用条目。"""
        with self._vector_search_cache_lock:
            if key in self._vector_search_cache:
                self._vector_search_cache.move_to_end(key)
            self._vector_search_cache[key] = value
            while len(self._vector_search_cache) > self._max_vector_cache_size:
                self._vector_search_cache.popitem(last=False)

    def get_history_cache(self, key: Tuple[str, int, str]) -> Optional[Any]:
        """获取历史缓存（带 TTL 过期检查）。"""
        now = time.time()
        with self._history_cache_lock:
            cached = self._history_cache.get(key)
            if cached is not None:
                value, expired_at = cached
                if now < expired_at:
                    self._history_cache.move_to_end(key)
                    return value
                self._history_cache.pop(key, None)
        return None

    def set_history_cache(self, key: Tuple[str, int, str], value: Any) -> None:
        """设置历史缓存，超容量时淘汰最久未使用条目。"""
        now = time.time()
        with self._history_cache_lock:
            self._history_cache[key] = (value, now + self._history_cache_ttl)
            self._history_cache.move_to_end(key)
            if len(self._history_cache) > self._history_cache_maxsize:
                self._history_cache.popitem(last=False)

    def invalidate_history_cache(self, session_id: str) -> None:
        """失效指定 session_id 的对话历史缓存（新消息写入后调用）。"""
        with self._history_cache_lock:
            keys_to_remove = [k for k in self._history_cache if k[0] == session_id]
            for k in keys_to_remove:
                self._history_cache.pop(k, None)
            if keys_to_remove:
                logger.bind(
                    event="history_cache_invalidated",
                    module="memory",
                    session_id=session_id,
                    invalidated_count=len(keys_to_remove),
                ).debug("对话历史缓存已失效")

    def clear(self) -> None:
        """清除所有缓存。"""
        with self._vector_search_cache_lock:
            self._vector_search_cache.clear()
        with self._history_cache_lock:
            self._history_cache.clear()