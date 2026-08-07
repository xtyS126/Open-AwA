"""
插件市场注册表，管理可供浏览和安装的插件元数据。
负责插件的注册、检索、搜索与分类管理。
"""

import json
import os
from pathlib import Path
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

    def discover_from_plugins_dir(
        self,
        plugins_dir: Optional[str] = None,
        db_session_factory=None,
    ) -> None:
        """
        扫描插件目录下的所有 manifest.json，从真实清单动态构造市场插件元数据。

        Args:
            plugins_dir: 插件目录路径。默认为 <repo_root>/plugins。
            db_session_factory: SQLAlchemy Session 工厂，用于查询 PluginDownloadLog 统计真实 install_count。
                若为 None 则所有插件 install_count 为 0。
        """
        # 解析插件目录，默认为仓库根目录下的 plugins
        if plugins_dir is None:
            plugins_dir = os.path.abspath(
                os.path.join(os.path.dirname(__file__), "..", "..", "..", "plugins")
            )

        plugins_path = Path(plugins_dir)
        if not plugins_path.exists() or not plugins_path.is_dir():
            logger.bind(event="marketplace_discover", module="marketplace").warning(
                f"插件目录不存在或非目录: {plugins_dir}"
            )
            return

        # 统计真实 install_count：按 plugin_id 聚合 status='success' 的下载数
        # DB 查询失败时异常自然传播（不伪造 0 次安装），由启动边界显式记录失败
        install_counts: Dict[str, int] = {}
        if db_session_factory is not None:
            session = db_session_factory()
            try:
                # 延迟导入避免循环依赖
                from db.models import PluginDownloadLog
                from sqlalchemy import func

                rows = (
                    session.query(
                        PluginDownloadLog.plugin_id,
                        func.count(PluginDownloadLog.id).label("cnt"),
                    )
                    .filter(PluginDownloadLog.status == "success")
                    .group_by(PluginDownloadLog.plugin_id)
                    .all()
                )
                install_counts = {row.plugin_id: int(row.cnt) for row in rows}
            finally:
                session.close()

        # 遍历插件子目录，从 manifest.json 构造元数据
        registered = 0
        # 系统内置插件目录名集合：由 DB seed 单独管理，跳过市场发现
        # system-tools / bilibili_toolkit_builtin / user_profile_builtin 均为内置
        _BUILTIN_PLUGIN_DIRS = {
            "system_tools",
            "bilibili_toolkit_builtin",
            "user_profile_builtin",
        }
        for sub in plugins_path.iterdir():
            if not sub.is_dir():
                continue
            if sub.name in _BUILTIN_PLUGIN_DIRS:
                # 系统内置插件由 DB 单独管理，跳过市场注册
                continue
            manifest_file = sub / "manifest.json"
            if not manifest_file.exists():
                continue
            try:
                with manifest_file.open("r", encoding="utf-8") as f:
                    manifest = json.load(f)
                plugin_id = manifest.get("name")
                if not plugin_id:
                    logger.bind(
                        event="marketplace_discover",
                        module="marketplace",
                        plugin_dir=sub.name,
                    ).warning(f"manifest.json 缺少 name 字段，跳过: {sub.name}")
                    continue
                metadata = {
                    "id": plugin_id,
                    "name": manifest.get("name"),
                    "version": manifest.get("version", "1.0.0"),
                    "description": manifest.get("description", ""),
                    "author": manifest.get("author", "Unknown"),
                    "category": manifest.get("category", "other"),
                    "tags": manifest.get("tags", []),
                    "download_url": "",
                    "icon": "",
                    "install_count": int(install_counts.get(plugin_id, 0)),
                }
                self.register_plugin(metadata)
                registered += 1
            except (json.JSONDecodeError, OSError, KeyError, ValueError, TypeError) as e:
                logger.bind(
                    event="marketplace_discover",
                    module="marketplace",
                    plugin_dir=sub.name,
                ).warning(f"解析 manifest.json 失败，跳过插件 {sub.name}: {e}")

        logger.bind(event="marketplace_discover", module="marketplace").info(
            f"已从真实清单发现 {registered} 个插件"
        )


# 全局单例
marketplace_registry = MarketplaceRegistry()
