from typing import Dict, Optional, Type, Any
from loguru import logger
import importlib
import os
import inspect

from .base_plugin import BasePlugin


class PluginLoader:
    LOADING_STATE_NOT_LOADED = "not_loaded"
    LOADING_STATE_LOADING = "loading"
    LOADING_STATE_LOADED = "loaded"
    LOADING_STATE_FAILED = "failed"

    def __init__(self):
        self.loaded_plugins: Dict[str, Type[BasePlugin]] = {}
        self.loading_states: Dict[str, str] = {}

    def load_module(self, plugin_path: str) -> Optional[Type[BasePlugin]]:
        if not os.path.exists(plugin_path):
            logger.error(f"Plugin path does not exist: {plugin_path}")
            self.loading_states[plugin_path] = self.LOADING_STATE_FAILED
            return None

        plugin_name = os.path.splitext(os.path.basename(plugin_path))[0]
        self.loading_states[plugin_name] = self.LOADING_STATE_LOADING
        logger.info(f"Loading plugin module: {plugin_path}")

        try:
            spec = importlib.util.spec_from_file_location(plugin_name, plugin_path)
            if spec is None or spec.loader is None:
                logger.error(f"Failed to create module spec for: {plugin_path}")
                self.loading_states[plugin_name] = self.LOADING_STATE_FAILED
                return None

            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            plugin_classes = []
            for name, obj in inspect.getmembers(module, inspect.isclass):
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
        return self.loading_states.get(plugin_name, self.LOADING_STATE_NOT_LOADED)
