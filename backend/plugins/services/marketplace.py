"""
插件市场服务：负责插件市场数据的获取和缓存。
"""

import time
from typing import Any, Dict, List, Optional

from loguru import logger


class PluginMarketplaceService:
    """
    插件市场服务。

    职责：
    - 从远程市场 URL 获取插件列表
    - 本地缓存（5 分钟有效期）
    - 插件搜索（按名称和描述）
    """

    def __init__(self, market_url: str = None):
        """
        初始化插件市场服务。

        Args:
            market_url: 市场 API URL。
        """
        self._market_url = market_url
        self._cache: Optional[List[Dict[str, Any]]] = None
        self._cache_timestamp: float = 0

    def set_market_url(self, url: str):
        """设置市场 URL 并失效缓存。"""
        self._market_url = url
        self._invalidate_cache()

    def _invalidate_cache(self):
        """使缓存失效。"""
        self._cache = None
        self._cache_timestamp = 0

    async def fetch_market_listing(self, force_refresh: bool = False) -> List[Dict[str, Any]]:
        """
        从市场获取插件列表。

        缓存策略：5 分钟有效期，force_refresh=True 强制刷新。

        Args:
            force_refresh: 是否强制刷新缓存。

        Returns:
            插件列表（每个元素为插件信息字典）。
        """
        if not force_refresh and self._cache is not None:
            if time.time() - self._cache_timestamp < 300:
                return self._cache

        if not self._market_url:
            return self._cache or []

        try:
            import httpx
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(self._market_url)
                response.raise_for_status()
                data = response.json()
                plugins = data if isinstance(data, list) else data.get("plugins", [])
                self._cache = plugins
                self._cache_timestamp = time.time()
                logger.info(f"市场插件列表已刷新，共 {len(plugins)} 个插件")
                return plugins
        except Exception as e:
            logger.warning(f"获取市场插件列表失败: {e}")
            return self._cache or []

    def search(self, query: str) -> List[Dict[str, Any]]:
        """
        在缓存的市场列表中搜索插件。

        Args:
            query: 搜索关键词（匹配名称和描述）。

        Returns:
            匹配的插件列表。
        """
        if not self._cache:
            return []

        query_lower = query.lower()
        return [
            p for p in self._cache
            if query_lower in p.get("name", "").lower()
            or query_lower in p.get("description", "").lower()
        ]

    def get_cached_listing(self) -> List[Dict[str, Any]]:
        """
        获取缓存的市场列表（不发起网络请求）。

        Returns:
            缓存的插件列表。
        """
        return self._cache or []

    def is_cache_valid(self) -> bool:
        """
        检查缓存是否有效。

        Returns:
            缓存有效返回 True。
        """
        if self._cache is None:
            return False
        return (time.time() - self._cache_timestamp) < 300