"""小红书（Xiaohongshu）内容源适配器 —— 由扩展驱动的内容发现。

所有内容发现和元数据提取都在用户浏览器中通过 Chrome 扩展完成
（被动 URL 收集、后台标签页搜索任务、创作者订阅拉取）。扩展将笔记
元数据（标题、作者、封面、URL）直接发送到后端 API，后端将其存储到
共享的 ``discovery_candidates`` 待评估池中。

此适配器存在的目的是让 ``AdapterRegistry`` 拥有一个 ``"xiaohongshu"``
条目。其 ``fetch()`` 是空操作：真实数据路径是
``POST /api/sources/xhs/observed-urls`` → ``discovery_candidates``。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from openbiliclaw.discovery.engine import DiscoveredContent
    from openbiliclaw.soul.profile import SoulProfile
    from openbiliclaw.sources.protocol import SourceRecipe

logger = logging.getLogger(__name__)


class XiaohongshuAdapter:
    """适配器桩 —— xhs 内容通过扩展 API 进入系统，
    而非通过适配器的 ``fetch()`` 方法。

    注册此适配器是为了让 ``AdapterRegistry.has("xiaohongshu")`` 返回 True，
    使多源流水线代码无需特殊处理。
    """

    @property
    def source_type(self) -> str:
        return "xiaohongshu"

    async def fetch(
        self,
        recipe: SourceRecipe,
        profile: SoulProfile,
        limit: int = 20,
    ) -> list[DiscoveredContent]:
        """空操作 —— xhs 内容通过 observed-urls 进入候选池。"""
        logger.debug(
            "XiaohongshuAdapter.fetch() called but xhs content enters "
            "via extension API, not adapter.fetch(). Returning empty.",
        )
        return []
