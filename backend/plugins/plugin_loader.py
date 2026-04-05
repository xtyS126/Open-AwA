"""
插件系统模块，负责插件定义、加载、校验、沙箱隔离、生命周期或扩展协议处理。
这一层通常同时涉及可扩展性、安全性与运行时状态管理。
"""

from typing import Dict, Optional, Type
from importlib import util as importlib_util
from loguru import logger
import importlib
import os
import inspect

from .base_plugin import BasePlugin


class PluginLoader:
    """
    封装与PluginLoader相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    LOADING_STATE_NOT_LOADED = "not_loaded"
    LOADING_STATE_LOADING = "loading"
    LOADING_STATE_LOADED = "loaded"
    LOADING_STATE_FAILED = "failed"

    def __init__(self):
        """
        处理init相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        self.loaded_plugins: Dict[str, Type[BasePlugin]] = {}
        self.loading_states: Dict[str, str] = {}

    def load_module(self, plugin_path: str) -> Optional[Type[BasePlugin]]:
        """
        加载module相关资源或运行时对象。
        它通常负责把外部配置、持久化内容或缓存状态转换为内部可用结构。
        """
        if not os.path.exists(plugin_path):
            logger.error(f"Plugin path does not exist: {plugin_path}")
            self.loading_states[plugin_path] = self.LOADING_STATE_FAILED
            return None

        plugin_name = os.path.splitext(os.path.basename(plugin_path))[0]
        self.loading_states[plugin_name] = self.LOADING_STATE_LOADING
        logger.info(f"Loading plugin module: {plugin_path}")

        try:
            spec = importlib_util.spec_from_file_location(plugin_name, plugin_path)
            if spec is None or spec.loader is None:
                logger.error(f"Failed to create module spec for: {plugin_path}")
                self.loading_states[plugin_name] = self.LOADING_STATE_FAILED
                return None

            module = importlib_util.module_from_spec(spec)
            spec.loader.exec_module(module)

            plugin_classes = []
            for _, obj in inspect.getmembers(module, inspect.isclass):
                if issubclass(obj, BasePlugin) and obj is not BasePlugin:
                    plugin_classes.append(obj)

            if not plugin_classes:
                logger.warning(f"No plugin class found in module: {plugin_path}")
                self.loading_states[plugin_name] = self.LOADING_STATE_FAILED
                return None

            if len(plugin_classes) > 1:
                logger.warning(f"Multiple plugin classes found in {plugin_path}, using the first one")

            plugin_class = plugin_classes[0]
            self.loaded_plugins[plugin_class.name] = plugin_class
            self.loading_states[plugin_class.name] = self.LOADING_STATE_LOADED
            logger.info(f"Successfully loaded plugin: {plugin_class.name} from {plugin_path}")
            return plugin_class

        except Exception as e:
            logger.error(f"Failed to load plugin module {plugin_path}: {e}")
            self.loading_states[plugin_name] = self.LOADING_STATE_FAILED
            return None

    def instantiate_plugin(self, plugin_class: Type[BasePlugin], config: Dict) -> Optional[BasePlugin]:
        """
        处理instantiate、plugin相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        if not issubclass(plugin_class, BasePlugin):
            logger.error(f"Provided class is not a subclass of BasePlugin: {plugin_class}")
            return None

        try:
            plugin_instance = plugin_class(config=config)
            logger.info(f"Instantiated plugin: {plugin_instance.name}")
            return plugin_instance
        except Exception as e:
            logger.error(f"Failed to instantiate plugin {plugin_class}: {e}")
            return None

    def inject_config(self, plugin_instance: BasePlugin, config: Dict) -> None:
        """
        处理inject、config相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        if not isinstance(plugin_instance, BasePlugin):
            logger.error(f"Provided instance is not a BasePlugin: {plugin_instance}")
            return

        try:
            plugin_instance.config.update(config)
            if hasattr(plugin_instance, '_initialized') and not plugin_instance._initialized:
                logger.debug(f"Config injected for plugin: {plugin_instance.name}")
            else:
                logger.warning(f"Plugin {plugin_instance.name} already initialized, config update may have limited effect")
        except Exception as e:
            logger.error(f"Failed to inject config into plugin {plugin_instance.name}: {e}")

    def get_loading_state(self, plugin_name: str) -> str:
        """
        获取loading、state相关数据或当前状态。
        调用方通常依赖该结果继续进行后续判断、渲染或业务编排。
        """
        return self.loading_states.get(plugin_name, self.LOADING_STATE_NOT_LOADED)
