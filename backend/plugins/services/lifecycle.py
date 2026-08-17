"""
插件生命周期服务：负责插件状态机、加载/启用/禁用/卸载。
"""

import threading
from typing import Any, Dict, List, Optional, Set

from loguru import logger


class PluginState:
    """
    插件状态枚举。

    状态转换规则：
    REGISTERED -> LOADED -> ENABLED <-> DISABLED -> UNLOADED
    ENABLED -> UPDATING -> LOADED
    任意状态 -> ERROR -> UNLOADED
    """
    REGISTERED = "registered"
    LOADED = "loaded"
    ENABLED = "enabled"
    DISABLED = "disabled"
    UNLOADED = "unloaded"
    ERROR = "error"
    UPDATING = "updating"


class PluginLifecycleService:
    """
    插件生命周期服务：管理插件状态转换和实例。

    职责：
    - 管理插件状态（REGISTERED/LOADED/ENABLED/DISABLED/UNLOADED/ERROR/UPDATING）
    - 校验状态转换是否合法
    - 管理插件实例引用
    - 管理插件元数据
    - 线程安全的状态读写
    """

    # 合法的状态转换
    VALID_TRANSITIONS: Dict[str, Set[str]] = {
        PluginState.REGISTERED: {PluginState.LOADED, PluginState.ERROR},
        PluginState.LOADED: {PluginState.ENABLED, PluginState.UNLOADED, PluginState.ERROR},
        PluginState.ENABLED: {PluginState.DISABLED, PluginState.UPDATING, PluginState.ERROR},
        PluginState.DISABLED: {PluginState.ENABLED, PluginState.UNLOADED, PluginState.ERROR},
        PluginState.UPDATING: {PluginState.LOADED, PluginState.UNLOADED, PluginState.ERROR},
        PluginState.ERROR: {PluginState.UNLOADED, PluginState.LOADED},
        PluginState.UNLOADED: {PluginState.LOADED},
    }

    def __init__(self):
        self._states: Dict[str, str] = {}
        self._instances: Dict[str, Any] = {}
        self._metadata: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    # ---- 状态管理 ----

    def get_state(self, plugin_name: str) -> str:
        """
        获取插件当前状态。

        Args:
            plugin_name: 插件名称。

        Returns:
            插件状态字符串，未注册则返回 REGISTERED。
        """
        with self._lock:
            return self._states.get(plugin_name, PluginState.REGISTERED)

    def get_all_states(self) -> Dict[str, str]:
        """
        获取所有插件的状态。

        Returns:
            插件名称到状态的映射（拷贝）。
        """
        with self._lock:
            return dict(self._states)

    def set_state(self, plugin_name: str, new_state: str):
        """
        设置插件状态，校验状态转换合法性。

        Args:
            plugin_name: 插件名称。
            new_state: 新状态。

        Raises:
            ValueError: 状态转换不合法。
        """
        current = self.get_state(plugin_name)
        allowed = self.VALID_TRANSITIONS.get(current, set())

        if new_state not in allowed:
            raise ValueError(
                f"插件 '{plugin_name}' 状态转换不合法: {current} -> {new_state}。"
                f"允许的目标状态: {allowed}"
            )

        with self._lock:
            self._states[plugin_name] = new_state
        logger.debug(f"插件状态变更: {plugin_name} {current} -> {new_state}")

    def transition(self, plugin_name: str, from_state: str, to_state: str) -> bool:
        """
        执行状态转换（原子操作）。

        Args:
            plugin_name: 插件名称。
            from_state: 期望的当前状态。
            to_state: 目标状态。

        Returns:
            转换成功返回 True，当前状态不匹配或转换不合法返回 False。
        """
        with self._lock:
            current = self._states.get(plugin_name, PluginState.REGISTERED)
            if current != from_state:
                return False
            allowed = self.VALID_TRANSITIONS.get(current, set())
            if to_state not in allowed:
                return False
            self._states[plugin_name] = to_state
        logger.debug(f"插件状态转换: {plugin_name} {from_state} -> {to_state}")
        return True

    # ---- 实例管理 ----

    def set_instance(self, plugin_name: str, instance: Any):
        """
        设置插件实例引用。

        Args:
            plugin_name: 插件名称。
            instance: 插件实例。
        """
        with self._lock:
            self._instances[plugin_name] = instance

    def get_instance(self, plugin_name: str) -> Optional[Any]:
        """
        获取插件实例。

        Args:
            plugin_name: 插件名称。

        Returns:
            插件实例，未找到则返回 None。
        """
        with self._lock:
            return self._instances.get(plugin_name)

    def remove_instance(self, plugin_name: str):
        """移除插件实例。"""
        with self._lock:
            self._instances.pop(plugin_name, None)

    def get_all_instances(self) -> Dict[str, Any]:
        """
        获取所有已加载的插件实例。

        Returns:
            插件名称到实例的映射（拷贝）。
        """
        with self._lock:
            return dict(self._instances)

    # ---- 元数据管理 ----

    def set_metadata(self, plugin_name: str, metadata: Dict[str, Any]):
        """
        设置插件元数据。

        Args:
            plugin_name: 插件名称。
            metadata: 元数据字典。
        """
        with self._lock:
            self._metadata[plugin_name] = metadata

    def get_metadata(self, plugin_name: str) -> Optional[Dict[str, Any]]:
        """
        获取插件元数据。

        Args:
            plugin_name: 插件名称。

        Returns:
            元数据字典，未找到则返回 None。
        """
        with self._lock:
            return self._metadata.get(plugin_name)

    # ---- 批量查询 ----

    def get_active_plugins(self) -> List[str]:
        """
        获取所有已启用的插件名称。

        Returns:
            已启用插件名称列表。
        """
        with self._lock:
            return [
                name for name, state in self._states.items()
                if state == PluginState.ENABLED
            ]

    def get_plugins_by_state(self, state: str) -> List[str]:
        """
        获取指定状态的所有插件名称。

        Args:
            state: 插件状态。

        Returns:
            插件名称列表。
        """
        with self._lock:
            return [
                name for name, s in self._states.items()
                if s == state
            ]

    # ---- 清理 ----

    def unregister(self, plugin_name: str):
        """
        注销插件：移除状态、实例和元数据。

        Args:
            plugin_name: 插件名称。
        """
        with self._lock:
            self._states.pop(plugin_name, None)
            self._instances.pop(plugin_name, None)
            self._metadata.pop(plugin_name, None)
        logger.debug(f"插件已注销: {plugin_name}")

    def clear(self):
        """清空所有插件状态、实例和元数据。"""
        with self._lock:
            self._states.clear()
            self._instances.clear()
            self._metadata.clear()
        logger.info("所有插件生命周期状态已清空")