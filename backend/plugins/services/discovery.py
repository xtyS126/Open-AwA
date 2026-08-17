"""
插件发现服务：负责扫描插件目录、发现可用插件、提取元数据。
"""

import os
import json
import threading
from pathlib import Path
from typing import Dict, List, Optional, Any

from loguru import logger


class PluginDiscoveryService:
    """
    插件发现服务：扫描并发现可用插件。

    职责：
    - 扫描插件目录，发现 Python 插件文件和 manifest 配置文件
    - 提取插件元数据（名称、版本、描述、入口点等）
    - 进程级缓存，按目录 mtime 失效，避免每次对话都 os.walk
    """

    def __init__(self, plugins_dir: str = None):
        """
        初始化插件发现服务。

        Args:
            plugins_dir: 插件目录路径，默认为项目根目录下的 plugins 文件夹。
        """
        self._plugins_dir = plugins_dir or self._get_default_plugins_dir()
        self._discover_cache: Optional[List[Dict[str, Any]]] = None
        self._discover_cache_mtime: float = 0.0
        self._discover_cache_lock = threading.Lock()

    def _get_default_plugins_dir(self) -> str:
        """获取默认插件目录路径，若不存在则自动创建。"""
        default_dir = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..")
        )
        if not os.path.exists(default_dir):
            os.makedirs(default_dir, exist_ok=True)
        return default_dir

    def set_plugins_dir(self, directory: str):
        """设置插件目录并失效缓存。"""
        self._plugins_dir = directory
        self.invalidate_cache()

    def invalidate_cache(self):
        """主动失效发现缓存。"""
        with self._discover_cache_lock:
            self._discover_cache = None
            self._discover_cache_mtime = 0.0
        logger.debug("Plugin discovery cache invalidated")

    def discover(self, force_refresh: bool = False) -> List[Dict[str, Any]]:
        """
        扫描插件目录，返回发现的插件元数据列表。

        缓存策略：按 plugins_dir 的 mtime 失效，短时间内多次调用命中缓存。

        Args:
            force_refresh: 是否强制刷新缓存。

        Returns:
            发现的插件信息列表（拷贝，调用方修改不影响缓存）。
        """
        if not os.path.exists(self._plugins_dir):
            logger.warning(f"插件目录不存在: {self._plugins_dir}")
            return []

        try:
            current_mtime = os.stat(self._plugins_dir).st_mtime
        except OSError as stat_err:
            logger.warning(f"获取插件目录 mtime 失败: {stat_err}")
            current_mtime = 0.0

        with self._discover_cache_lock:
            if (
                not force_refresh
                and self._discover_cache is not None
                and current_mtime == self._discover_cache_mtime
                and current_mtime != 0.0
            ):
                logger.debug(f"discover cache hit (mtime={current_mtime})")
                return list(self._discover_cache)

        logger.info(f"正在扫描插件目录: {self._plugins_dir}")
        discovered = self._scan_directory(self._plugins_dir)
        logger.info(f"插件扫描完成，发现 {len(discovered)} 个插件")

        with self._discover_cache_lock:
            self._discover_cache = list(discovered)
            self._discover_cache_mtime = current_mtime

        return list(discovered)

    def _scan_directory(self, search_dir: str) -> List[Dict[str, Any]]:
        """
        在指定目录中扫描插件。

        支持两种插件格式：
        1. Python 插件：扫描 .py 文件，通过静态分析提取元数据
        2. Manifest 插件：扫描子目录中的 manifest.json 配置文件

        Args:
            search_dir: 搜索目录路径。

        Returns:
            发现的插件信息列表。
        """
        discovered: List[Dict[str, Any]] = []

        if not os.path.exists(search_dir):
            return discovered

        discovered_names: set = set()

        for root, dirs, files in os.walk(search_dir):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__"]

            for file in files:
                if file.endswith(".py") and not file.startswith("_"):
                    plugin_path = os.path.join(root, file)
                    plugin_info = self._extract_python_plugin_info(plugin_path)
                    if plugin_info:
                        discovered.append(plugin_info)
                        discovered_names.add(plugin_info["name"])

            # 扫描子目录中的 manifest 配置文件
            for dir_name in list(dirs):
                subdir_path = os.path.join(root, dir_name)
                manifest_info = self._extract_manifest_plugin_info(subdir_path)
                if manifest_info is None:
                    continue
                name = manifest_info["name"]
                if name in discovered_names:
                    continue
                discovered.append(manifest_info)
                discovered_names.add(name)

        return discovered

    def _extract_python_plugin_info(self, plugin_path: str) -> Optional[Dict[str, Any]]:
        """
        从 Python 插件文件提取元数据。

        通过 AST 静态分析提取类名和模块信息，不执行插件代码。

        Args:
            plugin_path: Python 插件文件路径。

        Returns:
            插件元数据字典，解析失败则返回 None。
        """
        import ast

        try:
            with open(plugin_path, "r", encoding="utf-8") as f:
                source = f.read()
        except (UnicodeDecodeError, OSError):
            return None

        try:
            tree = ast.parse(source)
        except SyntaxError:
            return None

        # 查找 BasePlugin 子类
        plugin_class_name = None
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for base in node.bases:
                    base_name = self._get_node_name(base)
                    if base_name in ("BasePlugin", "base_plugin.BasePlugin"):
                        plugin_class_name = node.name
                        break
                if plugin_class_name:
                    break

        if not plugin_class_name:
            return None

        # 构建模块名
        module_path = os.path.splitext(os.path.relpath(plugin_path, self._plugins_dir))[0]
        module_name = module_path.replace(os.sep, ".")

        return {
            "name": plugin_class_name.lower().replace("plugin", "").strip("_") or plugin_class_name,
            "version": "0.0.1",
            "description": f"插件 {plugin_class_name}",
            "path": plugin_path,
            "root_dir": os.path.dirname(plugin_path),
            "class_name": plugin_class_name,
            "module": module_name,
            "manifest": None,
            "manifest_path": None,
            "config_path": None,
            "schema_path": None,
            "default_config": {},
            "requested_permissions": [],
            "executable": True,
        }

    def _extract_manifest_plugin_info(self, plugin_dir: str) -> Optional[Dict[str, Any]]:
        """
        从 manifest.json 提取插件元数据。

        Args:
            plugin_dir: 插件目录路径。

        Returns:
            插件元数据字典，若无 manifest 文件则返回 None。
        """
        manifest_path = os.path.join(plugin_dir, "manifest.json")
        if not os.path.exists(manifest_path):
            return None

        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
        except (json.JSONDecodeError, OSError):
            return None

        if not isinstance(manifest, dict):
            return None

        name = manifest.get("name", os.path.basename(plugin_dir))
        version = manifest.get("version", "0.0.1")

        # 检查是否已有 Python 插件文件（避免重复）
        has_py = any(
            f.endswith(".py") and not f.startswith("_")
            for f in os.listdir(plugin_dir)
            if os.path.isfile(os.path.join(plugin_dir, f))
        )

        return {
            "name": name,
            "version": version,
            "description": manifest.get("description", f"插件 {name}"),
            "path": None if has_py else None,
            "root_dir": plugin_dir,
            "class_name": None,
            "module": None,
            "manifest": manifest,
            "manifest_path": manifest_path,
            "config_path": os.path.join(plugin_dir, "config.json"),
            "schema_path": os.path.join(plugin_dir, "schema.json"),
            "default_config": manifest.get("config", {}),
            "requested_permissions": manifest.get("permissions", []),
            "executable": bool(manifest.get("executable", True)),
        }

    @staticmethod
    def _get_node_name(node) -> str:
        """从 AST 节点提取可读名称。"""
        import ast
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            base = PluginDiscoveryService._get_node_name(node.value)
            return f"{base}.{node.attr}" if base else node.attr
        return ""

    def get_plugin_info(self, plugin_name: str) -> Optional[Dict[str, Any]]:
        """
        获取指定插件的元数据。

        Args:
            plugin_name: 插件名称。

        Returns:
            插件元数据字典，未找到则返回 None。
        """
        plugins = self.discover()
        for plugin in plugins:
            if plugin.get("name") == plugin_name:
                return plugin
        return None