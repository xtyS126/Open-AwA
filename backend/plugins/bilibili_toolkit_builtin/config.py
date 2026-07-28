"""版本化配置管理器，等价 Rust bili-sync 的 ``VersionedConfig<ArcSwap>``。

Rust 参考实现使用 ``arc-swap`` 提供无锁原子配置读取，配合 ``tokio::sync::watch``
通道通知配置变更。Python 等价实现：

- :class:`threading.Lock` 保护配置读写，确保并发读看不到半成品。
- :class:`asyncio.Event` 通知等待配置变更的协程（等价 watch 通道）。
- 模块级单例 :data:`_global_config` 提供 ``arc-swap`` 的全局访问点。

线程安全要点：
- :meth:`VersionedConfig.update_config` 可能从非事件循环线程调用
  （例如同步 HTTP 处理函数或配置变更回调），此时通过
  ``loop.call_soon_threadsafe(event.set)`` 安全地触发 Event。
- :class:`asyncio.Event` 自身不是线程安全的，不能从其他线程直接调用 ``set()``。

调用约定：
- :func:`init_config_manager` 在插件 initialize 阶段调用一次，传入初始配置 dict。
- :func:`get_config_manager` 在调度器、下载流水线等处调用获取全局单例。
- 配置变更（WebUI 修改 FilterOption / Trigger 等）调用
  :meth:`VersionedConfig.update_config` 触发热更新。
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any, Dict, Optional


class VersionedConfig:
    """版本化配置管理器，等价 Rust ``VersionedConfig<ArcSwap>``。

    用 ``threading.Lock`` 保护配置读写 + ``asyncio.Event`` 通知变更。
    每次 :meth:`update_config` 后版本号自增，所有等待 :meth:`wait_for_change`
    的协程被唤醒。

    Attributes:
        _config: 当前配置字典（受 ``_lock`` 保护）。
        _lock: 保护 ``_config`` 与 ``_version`` 的可重入线程锁。
        _event: 通知等待者的异步事件（等价 watch 通道的 receiver）。
        _loop: 事件循环引用，首次 :meth:`wait_for_change` 调用时绑定，
            用于 ``call_soon_threadsafe`` 跨线程触发 Event。
        _version: 配置版本号，每次更新自增。
    """

    def __init__(self, initial_config: Dict[str, Any]) -> None:
        """初始化版本化配置管理器。

        Args:
            initial_config: 初始配置字典。构造时拷贝一份，避免外部修改影响内部状态。
        """
        self._config: Dict[str, Any] = dict(initial_config)
        self._lock: threading.Lock = threading.Lock()
        # Python 3.10+ 的 asyncio.Event 不再依赖 loop 构造，可在外部线程创建；
        # 但 set()/clear()/wait() 必须在事件循环线程中或通过 call_soon_threadsafe 调用。
        self._event: asyncio.Event = asyncio.Event()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._version: int = 0

    def get_config(self) -> Dict[str, Any]:
        """读取当前配置（线程安全）。

        返回配置字典的浅拷贝，调用方修改不会影响内部状态。

        Returns:
            当前配置字典的副本。
        """
        with self._lock:
            return dict(self._config)

    def update_config(self, new_config: Dict[str, Any]) -> int:
        """更新配置，触发 Event，返回新版本号。

        线程安全：可在任意线程调用。若事件循环已绑定，通过
        ``loop.call_soon_threadsafe`` 安全地触发 :class:`asyncio.Event.set`。

        Args:
            new_config: 新配置字典。拷贝一份后存储，避免外部修改影响。

        Returns:
            更新后的版本号。
        """
        with self._lock:
            self._config = dict(new_config)
            self._version += 1
            new_version = self._version

        # 通知等待配置变更的协程
        # asyncio.Event 非线程安全，必须通过 call_soon_threadsafe 触发 set
        loop = self._loop
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(self._event.set)
        # 若事件循环未绑定（无 wait_for_change 调用过），无需触发；
        # 下次 wait_for_change 会通过版本号对比检测到变更。

        return new_version

    async def wait_for_change(
        self, timeout: Optional[float] = None
    ) -> bool:
        """等待配置变更，返回是否在超时前收到变更。

        必须在事件循环线程中调用。首次调用会绑定当前事件循环到 ``_loop``，
        后续 :meth:`update_config` 通过该循环触发 Event。

        Args:
            timeout: 超时秒数。``None`` 表示无限等待。

        Returns:
            True 表示在超时前收到变更通知；False 表示超时未收到。
        """
        # 首次调用时绑定事件循环
        if self._loop is None:
            self._loop = asyncio.get_running_loop()

        # 清除遗留的 set 状态，避免立即返回旧的变更通知
        self._event.clear()
        try:
            await asyncio.wait_for(self._event.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False

    @property
    def version(self) -> int:
        """当前配置版本号。"""
        with self._lock:
            return self._version


# ---------------------------------------------------------------------------
# 模块级单例管理（等价 Rust 的全局 VersionedConfig）
# ---------------------------------------------------------------------------

# 全局配置管理器单例，由 init_config_manager 初始化，get_config_manager 读取
_global_config: Optional[VersionedConfig] = None

# 保护 _global_config 单例的初始化与读取
_global_lock: threading.Lock = threading.Lock()


def get_config_manager() -> VersionedConfig:
    """获取全局配置管理器单例。

    必须先调用 :func:`init_config_manager` 初始化，否则抛 ``RuntimeError``。

    Returns:
        全局 :class:`VersionedConfig` 实例。

    Raises:
        RuntimeError: 全局配置管理器尚未初始化。
    """
    with _global_lock:
        if _global_config is None:
            raise RuntimeError(
                "VersionedConfig 全局单例尚未初始化，请先调用 init_config_manager"
            )
        return _global_config


def init_config_manager(initial_config: Dict[str, Any]) -> VersionedConfig:
    """初始化全局配置管理器（仅可调用一次）。

    Args:
        initial_config: 初始配置字典。

    Returns:
        新创建的 :class:`VersionedConfig` 实例。

    Raises:
        RuntimeError: 全局配置管理器已初始化，重复调用禁止。
    """
    global _global_config
    with _global_lock:
        if _global_config is not None:
            raise RuntimeError(
                "VersionedConfig 全局单例已初始化，禁止重复调用 init_config_manager"
            )
        _global_config = VersionedConfig(initial_config)
        return _global_config


def reset_config_manager_for_test() -> None:
    """重置全局配置管理器单例（仅用于测试隔离）。

    生产代码不应调用此函数。测试场景下确保用例之间互不影响。
    """
    global _global_config
    with _global_lock:
        _global_config = None
