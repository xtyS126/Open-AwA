"""适配器注册表 —— 将 source_type 解析为对应的 SourceAdapter。"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from openbiliclaw.sources.protocol import SourceAdapter, SourceRecipe

logger = logging.getLogger(__name__)


class AdapterRegistry:
    """将 ``source_type`` 字符串映射至 :class:`SourceAdapter` 实例。"""

    def __init__(self) -> None:
        self._adapters: dict[str, SourceAdapter] = {}

    def register(self, adapter: SourceAdapter) -> None:
        """以适配器的 ``source_type`` 为键注册。"""
        key = adapter.source_type
        self._adapters[key] = adapter
        logger.info("Registered source adapter: %s", key)

    def resolve(self, recipe: SourceRecipe) -> SourceAdapter | None:
        """返回匹配 *recipe.source_type* 的适配器，无则返回 ``None``。"""
        return self._adapters.get(recipe.source_type)

    def has(self, source_type: str) -> bool:
        """检查是否已为 *source_type* 注册适配器。"""
        return source_type in self._adapters

    @property
    def source_types(self) -> list[str]:
        """列出所有已注册的源类型键。"""
        return list(self._adapters)
