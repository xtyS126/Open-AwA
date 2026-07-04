"""多源内容发现的核心抽象。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from openbiliclaw.discovery.engine import DiscoveredContent
    from openbiliclaw.soul.profile import SoulProfile


@dataclass
class SourceRecipe:
    """对内容源的持久订阅。

    Recipe 描述*抓什么*与*从哪里抓*。它们可由系统创建
    （内置默认）、由用户创建（设置 UI）或由 agent 创建
    （对话式订阅）。

    Attributes:
        id: 唯一标识符（UUID 字符串）。
        source_type: 平台键，例如 ``"bilibili"``、``"xiaohongshu"``、``"web"``。
        name: 可读标签，例如 "B站-搜索" 或 "小红书-机械键盘"。
        strategy: 适配器内的发现策略，例如 ``"search"``、
            ``"trending"``、``"feed"``、``"explore"``、``"related_chain"``。
        config: 适配器特有参数（搜索词、信息流 URL 等）。
        target_share: 调度器分配池槽位时使用的权重。
        enabled: 此 recipe 是否参与发现循环。
        created_by: 来源 —— ``"system"`` 表示内置默认，
            ``"user"`` 表示手动创建，``"agent"`` 表示对话式创建。
        created_at: ISO-8601 时间戳。
        last_fetched_at: 最近一次成功抓取的 ISO-8601 时间戳。
    """

    id: str
    source_type: str
    name: str
    strategy: str
    config: dict[str, Any] = field(default_factory=dict)
    target_share: int = 4
    enabled: bool = True
    created_by: str = "system"
    created_at: str = ""
    last_fetched_at: str = ""


@runtime_checkable
class SourceAdapter(Protocol):
    """内容源适配器的统一接口。

    每个适配器（Bilibili、小红书、通用 Web、……）均实现此协议。
    发现引擎与调度器仅通过此接口交互 —— 上层一切均与源无关。
    """

    @property
    def source_type(self) -> str:
        """平台标识，例如 ``"bilibili"``。"""
        ...

    async def fetch(
        self,
        recipe: SourceRecipe,
        profile: SoulProfile,
        limit: int = 20,
    ) -> list[DiscoveredContent]:
        """按 *recipe* 抓取内容并返回规范化条目。

        实现可自由使用 API、浏览器自动化或任何其他机制。
        返回的条目**必须**填充 ``content_id``、``content_url``
        与 ``source_platform``。

        Args:
            recipe: 定义抓取内容的订阅 recipe。
            profile: 当前用户 soul 画像，用于相关性引导。
            limit: 返回条目数的上限。

        Returns:
            已就绪供评估的发现内容条目列表。
        """
        ...
