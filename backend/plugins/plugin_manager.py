import os
import inspect
import importlib
from typing import Dict, List, Optional, Any, Type

from loguru import logger

from .base_plugin import BasePlugin
from .plugin_loader import PluginLoader
from .plugin_validator import PluginValidator
from .plugin_sandbox import PluginSandbox


class PluginManager:
    def __init__(self, plugins_dir: Optional[str] = None):
        self.plugins_dir = plugins_dir or self._get_default_plugins_dir()
        self.loader = PluginLoader()
        self.validator = PluginValidator()
        self.sandbox = PluginSandbox()
        self.loaded_plugins: Dict[str, BasePlugin] = {}
        self.plugin_metadata: Dict[str, Dict[str, Any]] = {}
        self._tools_registry: Dict[str, List[Dict[str, Any]]] = {}
        logger.info(f"PluginManager initialized with plugins_dir: {self.plugins_dir}")

    def _get_default_plugins_dir(self) -> str:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        default_dir = os.path.join(current_dir, "plugins")
        if not os.path.exists(default_dir):
            os.makedirs(default_dir, exist_ok=True)
            logger.info(f"Created default plugins directory: {default_dir}")
        return default_dir

    def discover_plugins(self) -> List[Dict[str, Any]]:
        discovered_plugins: List[Dict[str, Any]] = []
        logger.info(f"Discovering plugins in directory: {self.plugins_dir}")

        if not os.path.exists(self.plugins_dir):
            logger.warning(f"Plugins directory does not exist: {self.plugins_dir}")
            return discovered_plugins

        for root, dirs, files in os.walk(self.plugins_dir):
            dirs[:] = [d for d in dirs if not d.startswith('.') and d != '__pycache__']

            for file in files:
                if file.endswith('.py') and not file.startswith('_'):
                    plugin_path = os.path.join(root, file)
                    plugin_info = self._scan_plugin_file(plugin_path)
                    if plugin_info:
                        discovered_plugins.append(plugin_info)
                        self.plugin_metadata[plugin_info['name']] = plugin_info
                        logger.debug(f"Discovered plugin: {plugin_info['name']} at {plugin_path}")

        logger.info(f"Plugin discovery completed. Found {len(discovered_plugins)} plugins")
        return discovered_plugins

    def _scan_plugin_file(self, plugin_path: str) -> Optional[Dict[str, Any]]:
        try:
            plugin_name = os.path.splitext(os.path.basename(plugin_path))[0]
            module_name = f"plugins.{plugin_name}"

            spec = importlib.util.spec_from_file_location(module_name, plugin_path)
            if spec is None or spec.loader is None:
                return None

            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            plugin_classes = []
            for name, obj in inspect.getmembers(module, inspect.isclass):
                if inspect.isclass(obj) and issubclass(obj, BasePlugin) and obj is not BasePlugin:
                    plugin_classes.append(obj)

            if not plugin_classes:
                return None

            plugin_class = plugin_classes[0]

            metadata = {
                'name': getattr(plugin_class, 'name', plugin_name),
                'version': getattr(plugin_class, 'version', '1.0.0'),
                'description': getattr(plugin_class, 'description', ''),
                'path': plugin_path,
                'class_name': plugin_class.__name__,
                'module': module_name
            }

            return metadata

        except Exception as e:
            logger.error(f"Error scanning plugin file {plugin_path}: {e}")
            return None

    def load_plugin(self, plugin_name: str) -> bool:
        if plugin_name in self.loaded_plugins:
            logger.warning(f"Plugin '{plugin_name}' is already loaded")
            return True

        if plugin_name not in self.plugin_metadata:
            logger.error(f"Plugin '{plugin_name}' not found in discovered plugins")
            return False

        metadata = self.plugin_metadata[plugin_name]
        plugin_path = metadata['path']

        plugin_class = self.loader.load_module(plugin_path)
        if plugin_class is None:
            logger.error(f"Failed to load plugin class for '{plugin_name}'")
            return False

        config = {
            'name': metadata['name'],
            'version': metadata['version'],
            'description': metadata['description']
        }

        validation_result = self.validator.validate_plugin(plugin_class, config)
        if not validation_result.valid:
            logger.error(f"Plugin '{plugin_name}' validation failed: {validation_result.errors}")
            return False

        if validation_result.warnings:
            logger.warning(f"Plugin '{plugin_name}' validation warnings: {validation_result.warnings}")

        plugin_instance = self.loader.instantiate_plugin(plugin_class, config)
        if plugin_instance is None:
            logger.error(f"Failed to instantiate plugin '{plugin_name}'")
            return False

        if hasattr(plugin_instance, 'initialize'):
            try:
                if not plugin_instance.initialize():
                    logger.error(f"Plugin '{plugin_name}' initialization returned False")
                    return False
            except Exception as e:
                logger.error(f"Plugin '{plugin_name}' initialization error: {e}")
                return False

        plugin_instance._initialized = True
        self.loaded_plugins[plugin_name] = plugin_instance

        self._register_plugin_tools(plugin_name, plugin_instance)

        logger.info(f"Plugin '{plugin_name}' loaded successfully")
        return True

    def unload_plugin(self, plugin_name: str) -> bool:
        if plugin_name not in self.loaded_plugins:
            logger.warning(f"Plugin '{plugin_name}' is not loaded")
            return False

        plugin_instance = self.loaded_plugins[plugin_name]

        if hasattr(plugin_instance, 'cleanup'):
            try:
                plugin_instance.cleanup()
            except Exception as e:
                logger.error(f"Plugin '{plugin_name}' cleanup error: {e}")

        self._unregister_plugin_tools(plugin_name)

        del self.loaded_plugins[plugin_name]
        logger.info(f"Plugin '{plugin_name}' unloaded successfully")
        return True

    def reload_plugin(self, plugin_name: str) -> bool:
        logger.info(f"Reloading plugin '{plugin_name}'")

        if plugin_name in self.loaded_plugins:
            if not self.unload_plugin(plugin_name):
                logger.error(f"Failed to unload plugin '{plugin_name}' before reload")
                return False

        importlib.invalidate_imports()

        if plugin_name in self.plugin_metadata:
            metadata = self.plugin_metadata[plugin_name]
            spec = importlib.util.spec_from_file_location(metadata['module'], metadata['path'])
            if spec and spec.loader:
                importlib.reload(spec.loader.__class__)

        return self.load_plugin(plugin_name)

    def execute_plugin(self, plugin_name: str, method: str, **kwargs) -> Dict[str, Any]:
        if plugin_name not in self.loaded_plugins:
            logger.error(f"Plugin '{plugin_name}' is not loaded")
            return {
                'status': 'error',
                'message': f"Plugin '{plugin_name}' is not loaded"
            }

        plugin_instance = self.loaded_plugins[plugin_name]

        if not hasattr(plugin_instance, method):
            logger.error(f"Plugin '{plugin_name}' does not have method '{method}'")
            return {
                'status': 'error',
                'message': f"Plugin '{plugin_name}' does not have method '{method}'"
            }

        return self.sandbox.execute_plugin_sync(plugin_instance, method, **kwargs)

    async def execute_plugin_async(self, plugin_name: str, method: str, **kwargs) -> Dict[str, Any]:
        if plugin_name not in self.loaded_plugins:
            logger.error(f"Plugin '{plugin_name}' is not loaded")
            return {
                'status': 'error',
                'message': f"Plugin '{plugin_name}' is not loaded"
            }

        plugin_instance = self.loaded_plugins[plugin_name]
        return await self.sandbox.execute_plugin(plugin_instance, method, **kwargs)

    def get_plugin_tools(self, plugin_name: str) -> List[Dict[str, Any]]:
        if plugin_name in self._tools_registry:
            return self._tools_registry[plugin_name]

        if plugin_name not in self.loaded_plugins:
            logger.warning(f"Plugin '{plugin_name}' is not loaded, cannot get tools")
            return []

        plugin_instance = self.loaded_plugins[plugin_name]
        tools = []

        if hasattr(plugin_instance, 'get_tools'):
            try:
                plugin_tools = plugin_instance.get_tools()
                if isinstance(plugin_tools, list):
                    tools = plugin_tools
            except Exception as e:
                logger.error(f"Error getting tools from plugin '{plugin_name}': {e}")

        for attr_name in dir(plugin_instance):
            if attr_name.startswith('tool_') or attr_name.startswith('get_tool_'):
                attr = getattr(plugin_instance, attr_name)
                if callable(attr):
                    tool_def = {
                        'name': attr_name.replace('tool_', '').replace('get_tool_', ''),
                        'description': getattr(attr, '__doc__', ''),
                        'method': attr_name,
                        'plugin': plugin_name
                    }
                    tools.append(tool_def)

        self._tools_registry[plugin_name] = tools
        return tools

    def get_all_tools(self) -> List[Dict[str, Any]]:
        all_tools = []
        for plugin_name in self.loaded_plugins:
            tools = self.get_plugin_tools(plugin_name)
            all_tools.extend(tools)
        return all_tools

    def _register_plugin_tools(self, plugin_name: str, plugin_instance: BasePlugin) -> None:
        if not hasattr(plugin_instance, 'get_tools'):
            return

        try:
            tools = plugin_instance.get_tools()
            if isinstance(tools, list):
                self._tools_registry[plugin_name] = tools
                logger.debug(f"Registered {len(tools)} tools for plugin '{plugin_name}'")
        except Exception as e:
            logger.error(f"Error registering tools for plugin '{plugin_name}': {e}")

    def _unregister_plugin_tools(self, plugin_name: str) -> None:
        if plugin_name in self._tools_registry:
            del self._tools_registry[plugin_name]
            logger.debug(f"Unregistered tools for plugin '{plugin_name}'")

    def list_loaded_plugins(self) -> List[str]:
        return list(self.loaded_plugins.keys())

    def list_available_plugins(self) -> List[str]:
        return list(self.plugin_metadata.keys())

    def get_plugin_info(self, plugin_name: str) -> Optional[Dict[str, Any]]:
        if plugin_name in self.plugin_metadata:
            info = self.plugin_metadata[plugin_name].copy()
            info['loaded'] = plugin_name in self.loaded_plugins
            return info
        return None

    def get_manager_stats(self) -> Dict[str, Any]:
        return {
            'plugins_dir': self.plugins_dir,
            'available_plugins': len(self.plugin_metadata),
            'loaded_plugins': len(self.loaded_plugins),
            'registered_tools': sum(len(tools) for tools in self._tools_registry.values()),
            'sandbox_stats': self.sandbox.get_execution_stats()
        }
