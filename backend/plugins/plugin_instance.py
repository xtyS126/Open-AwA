"""
插件管理器全局单例模块，确保整个应用共享同一个 PluginManager 实例。
通过 init() 初始化，通过 get() 获取。
"""

from typing import Optional
from loguru import logger

_instance = None


def init(manager) -> None:
    """初始化全局插件管理器单例。"""
    global _instance
    _instance = manager
    logger.info("全局插件管理器单例已初始化")


def get():
    """
    获取全局插件管理器实例。
    如果尚未初始化，则创建一个默认实例并返回。
    """
    global _instance
    if _instance is None:
        from .plugin_manager import PluginManager
        _instance = PluginManager()
        logger.warning("插件管理器单例未经 init() 初始化，已自动创建默认实例")
    return _instance
