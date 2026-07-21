"""
插件管理器全局单例模块，确保整个应用共享同一个 PluginManager 实例。
通过 init() 初始化，通过 get() 获取。
"""

import threading
from typing import Optional
from loguru import logger

_instance = None
_lock = threading.Lock()


def init(manager) -> None:
    """初始化全局插件管理器单例。"""
    global _instance
    with _lock:
        _instance = manager
    logger.info("全局插件管理器单例已初始化")


def get():
    """
    获取全局插件管理器实例（线程安全）。
    如果尚未初始化，则创建一个默认实例并返回。
    """
    global _instance
    if _instance is None:
        with _lock:
            # 双重检查锁定：在锁内再次确认 _instance 未被其他线程初始化
            if _instance is None:
                from .plugin_manager import PluginManager
                _instance = PluginManager()
                logger.warning("插件管理器单例未经 init() 初始化，已自动创建默认实例")
    return _instance


def get_if_initialized():
    """返回已初始化的插件管理器；尚未初始化时不创建默认实例。"""
    with _lock:
        return _instance


def reset():
    """原子移除并返回当前插件管理器，供关闭流程和测试隔离使用。"""
    global _instance
    with _lock:
        previous = _instance
        _instance = None
    return previous
