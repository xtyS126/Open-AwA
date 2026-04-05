"""
插件系统模块，负责插件定义、加载、校验、沙箱隔离、生命周期或扩展协议处理。
这一层通常同时涉及可扩展性、安全性与运行时状态管理。
"""

from .cli import cli
from .base_plugin import BasePlugin
from .extension_protocol import ExtensionPointType, ExtensionRegistry
from .plugin_lifecycle import PluginState, PluginStateMachine, TransitionExecutor
from .plugin_loader import PluginLoader
from .plugin_logger import LogManager, PluginLogger
from .plugin_manager import PluginManager
from .plugin_sandbox import PluginSandbox
from .plugin_validator import PluginValidator
from .schema_validator import (
    EXTENSION_POINT_VALUES,
    EXTENSION_SCHEMA,
    MANIFEST_SCHEMA,
    JsonSchemaValidator,
    ManifestExtensionSchemaValidator,
    SchemaValidationResult,
)

__all__ = [
    "cli",
    "BasePlugin",
    "PluginState",
    "PluginStateMachine",
    "TransitionExecutor",
    "PluginManager",
    "PluginLoader",
    "PluginLogger",
    "LogManager",
    "PluginValidator",
    "PluginSandbox",
    "ExtensionPointType",
    "ExtensionRegistry",
    "EXTENSION_POINT_VALUES",
    "EXTENSION_SCHEMA",
    "MANIFEST_SCHEMA",
    "JsonSchemaValidator",
    "ManifestExtensionSchemaValidator",
    "SchemaValidationResult",
]
