"""
插件市场注册表，管理可供浏览和安装的插件元数据。
负责插件的注册、检索、搜索与分类管理。
"""

from typing import Dict, List, Optional
from loguru import logger


class MarketplaceRegistry:
    """
    插件市场注册表，维护所有可用插件的元数据信息。
    支持注册、检索、搜索与分页浏览功能。
    """

    def __init__(self):
        # 插件元数据存储，键为插件ID
        self._plugins: Dict[str, dict] = {}

    def register_plugin(self, metadata: dict) -> None:
        """注册一个插件到市场注册表"""
        plugin_id = metadata.get("id")
        if not plugin_id:
            raise ValueError("插件元数据必须包含 id 字段")
        self._plugins[plugin_id] = metadata
        logger.bind(event="marketplace_register", module="marketplace", plugin_id=plugin_id).info(
            f"插件已注册到市场: {metadata.get('name', plugin_id)}"
        )

    def get_plugin(self, plugin_id: str) -> Optional[dict]:
        """根据插件ID获取单个插件的元数据"""
        return self._plugins.get(plugin_id)

    def list_plugins(
        self,
        category: Optional[str] = None,
        page: int = 1,
        page_size: int = 12,
    ) -> dict:
        """
        分页列出插件列表，可按分类筛选。
        返回包含 plugins、total、page、page_size 的字典。
        """
        plugins = list(self._plugins.values())

        # 按分类筛选
        if category and category != "all":
            plugins = [p for p in plugins if p.get("category") == category]

        total = len(plugins)

        # 分页处理
        start = (page - 1) * page_size
        end = start + page_size
        paginated = plugins[start:end]

        return {
            "plugins": paginated,
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    def search_plugins(self, query: str) -> List[dict]:
        """
        根据查询字符串搜索插件，匹配名称、描述和标签。
        采用大小写不敏感的模糊匹配。
        """
        if not query:
            return list(self._plugins.values())

        query_lower = query.lower()
        results = []
        for plugin in self._plugins.values():
            name = plugin.get("name", "").lower()
            description = plugin.get("description", "").lower()
            tags = [t.lower() for t in plugin.get("tags", [])]

            if (
                query_lower in name
                or query_lower in description
                or any(query_lower in tag for tag in tags)
            ):
                results.append(plugin)

        return results

    def get_categories(self) -> List[str]:
        """获取所有已注册插件的分类列表（去重）"""
        categories = set()
        for plugin in self._plugins.values():
            cat = plugin.get("category")
            if cat:
                categories.add(cat)
        return sorted(categories)

    def seed_built_in_plugins(self) -> None:
        """初始化内置示例插件到注册表"""
        built_in = [
            {
                "id": "hello-world",
                "name": "Hello World",
                "description": "最简示例插件，演示插件生命周期与日志输出",
                "author": "Open-AwA Team",
                "version": "1.0.0",
                "category": "tool",
                "tags": ["示例", "入门", "工具"],
                "download_url": "",
                "icon": "",
                "install_count": 128,
            },
            {
                "id": "theme-switcher",
                "name": "Theme Switcher",
                "description": "演示存储API与UI扩展点的主题切换插件",
                "author": "Open-AwA Team",
                "version": "1.0.0",
                "category": "theme",
                "tags": ["主题", "UI", "外观"],
                "download_url": "",
                "icon": "",
                "install_count": 256,
            },
            {
                "id": "data-chart",
                "name": "Data Chart",
                "description": "演示API拦截与权限申请的数据图表插件",
                "author": "Open-AwA Team",
                "version": "1.0.0",
                "category": "data",
                "tags": ["数据", "图表", "可视化"],
                "download_url": "",
                "icon": "",
                "install_count": 512,
            },
            {
                "id": "user-profile-chat",
                "name": "User Profile Chat",
                "description": "基于聊天记录分析并生成用户画像的插件，可识别用户兴趣偏好、交流风格和关注领域",
                "author": "Open-AwA Team",
                "version": "1.0.0",
                "category": "tool",
                "tags": ["用户画像", "聊天分析", "AI"],
                "download_url": "",
                "icon": "",
                "install_count": 64,
            },
        ]

        for plugin_meta in built_in:
            self.register_plugin(plugin_meta)

        logger.bind(event="marketplace_seed", module="marketplace").info(
            f"已注册 {len(built_in)} 个内置示例插件"
        )


# 全局单例
marketplace_registry = MarketplaceRegistry()
