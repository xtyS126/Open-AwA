"""多源内容发现适配器。

本包提供 SourceAdapter 协议与具体适配器，
用于从各平台（Bilibili、小红书、Web 等）抓取内容，
并将其规范化为 DiscoveredContent，供评估/推荐流水线使用。
"""

from openbiliclaw.sources.protocol import SourceAdapter, SourceRecipe
from openbiliclaw.sources.registry import AdapterRegistry

__all__ = [
    "AdapterRegistry",
    "SourceAdapter",
    "SourceRecipe",
]
