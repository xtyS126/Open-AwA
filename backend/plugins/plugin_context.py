"""
插件上下文注入模块，为插件执行提供统一的运行时上下文。
上下文包含当前用户信息、数据库会话、配置访问和事件总线引用。
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

from loguru import logger


@dataclass
class PluginContext:
    """
    插件运行时上下文，封装插件执行所需的外部资源。
    插件通过上下文访问用户信息、数据库、配置和事件系统，避免直接依赖全局状态。
    """
    # 当前用户信息（只读字典）
    user: Dict[str, Any] = field(default_factory=dict)
    # 数据库会话工厂（调用时返回一个新的 Session 实例）
    db_session_factory: Optional[Callable[[], Any]] = None
    # 插件专属配置
    plugin_config: Dict[str, Any] = field(default_factory=dict)
    # 事件总线引用
    event_bus: Optional[Any] = None
    # 附加元数据（可由中间件或调用方扩展）
    metadata: Dict[str, Any] = field(default_factory=dict)

    def get_db_session(self) -> Any:
        """
        获取一个新的数据库会话实例。
        调用方负责关闭会话以避免连接泄漏。

        Raises:
            RuntimeError: 当上下文中未注入数据库会话工厂时抛出。
        """
        if self.db_session_factory is None:
            raise RuntimeError("插件上下文中未注入数据库会话工厂")
        return self.db_session_factory()

    def get_user_id(self) -> Optional[str]:
        """获取当前用户 ID，未认证时返回 None。"""
        return self.user.get("id")

    def get_username(self) -> Optional[str]:
        """获取当前用户名，未认证时返回 None。"""
        return self.user.get("username")

    def get_user_role(self) -> Optional[str]:
        """获取当前用户角色，未认证时返回 None。"""
        return self.user.get("role")

    def emit_event(self, event_name: str, event_data: Optional[Dict[str, Any]] = None) -> Any:
        """
        通过上下文中的事件总线发布事件。

        Args:
            event_name: 事件名称。
            event_data: 事件数据。

        Returns:
            事件触发结果，若无事件总线返回 None。
        """
        if self.event_bus is None:
            logger.warning("插件上下文中未注入事件总线，事件未发送")
            return None
        return self.event_bus.emit(event_name, event_data)

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典（不含敏感对象），用于日志和调试。"""
        return {
            "user": {k: v for k, v in self.user.items() if k != "password_hash"},
            "has_db_session_factory": self.db_session_factory is not None,
            "has_event_bus": self.event_bus is not None,
            "metadata_keys": list(self.metadata.keys()),
        }


def build_plugin_context(
    user: Optional[Any] = None,
    db_session_factory: Optional[Callable[[], Any]] = None,
    plugin_config: Optional[Dict[str, Any]] = None,
    event_bus: Optional[Any] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> PluginContext:
    """
    构建插件运行时上下文的工厂函数。

    Args:
        user: 当前用户 ORM 对象或字典。
        db_session_factory: 数据库会话工厂函数。
        plugin_config: 插件专属配置。
        event_bus: 事件总线实例。
        metadata: 附加元数据。

    Returns:
        构建好的 PluginContext 实例。
    """
    user_dict: Dict[str, Any] = {}
    if user is not None:
        if isinstance(user, dict):
            user_dict = user
        elif hasattr(user, "id") and hasattr(user, "username"):
            # ORM 模型转换为字典
            user_dict = {
                "id": getattr(user, "id", None),
                "username": getattr(user, "username", None),
                "role": getattr(user, "role", None),
            }

    return PluginContext(
        user=user_dict,
        db_session_factory=db_session_factory,
        plugin_config=plugin_config or {},
        event_bus=event_bus,
        metadata=metadata or {},
    )
