"""
插件服务层：将 PluginManager 的职责拆分为独立的服务类。
每个服务专注于单一职责，保持 <=500 行，便于测试和维护。
后续 Task 8 会将 PluginManager 重构为薄门面层，委托调用这些服务。
"""
from .discovery import PluginDiscoveryService
from .install import PluginInstallService
from .security import PluginSecurityService
from .lifecycle import PluginLifecycleService
from .marketplace import PluginMarketplaceService

__all__ = [
    "PluginDiscoveryService",
    "PluginInstallService",
    "PluginSecurityService",
    "PluginLifecycleService",
    "PluginMarketplaceService",
]