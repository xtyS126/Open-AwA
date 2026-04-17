"""
插件事件总线，负责插件间的事件发布与订阅通信。
支持同步与异步事件处理器，提供事件优先级和命名空间隔离。
"""

import asyncio
import inspect
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from loguru import logger


@dataclass
class EventSubscription:
    """
    事件订阅记录，存储订阅者信息和处理器引用。
    """
    plugin_name: str
    handler: Callable[..., Any]
    priority: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典，用于调试和审计。"""
        return {
            "plugin_name": self.plugin_name,
            "handler_name": getattr(self.handler, "__name__", str(self.handler)),
            "priority": self.priority,
        }


@dataclass
class EventResult:
    """
    事件触发结果，汇总所有处理器的执行情况。
    """
    event_name: str
    handler_count: int
    results: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def success(self) -> bool:
        """所有处理器均成功执行时返回 True。"""
        return len(self.errors) == 0

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典。"""
        return {
            "event_name": self.event_name,
            "handler_count": self.handler_count,
            "success": self.success,
            "results_count": len(self.results),
            "errors_count": len(self.errors),
        }


class PluginEventBus:
    """
    插件事件总线，提供发布/订阅机制实现插件间解耦通信。
    事件名称格式建议: "命名空间:事件名"，如 "chat:message_received"。
    """

    def __init__(self) -> None:
        """初始化事件总线。"""
        self._subscribers: Dict[str, List[EventSubscription]] = defaultdict(list)
        self._lock = threading.Lock()

    def subscribe(
        self,
        event_name: str,
        plugin_name: str,
        handler: Callable[..., Any],
        priority: int = 0,
    ) -> None:
        """
        订阅指定事件。

        Args:
            event_name: 事件名称。
            plugin_name: 订阅者插件名称。
            handler: 事件处理函数，接收 event_data 字典参数。
            priority: 优先级，数值越大越先执行。
        """
        subscription = EventSubscription(
            plugin_name=plugin_name,
            handler=handler,
            priority=priority,
        )
        with self._lock:
            self._subscribers[event_name].append(subscription)
            # 按优先级降序排序，高优先级先执行
            self._subscribers[event_name].sort(key=lambda s: s.priority, reverse=True)
        logger.debug(f"插件 '{plugin_name}' 订阅事件 '{event_name}' (优先级: {priority})")

    def unsubscribe(self, event_name: str, plugin_name: str) -> int:
        """
        取消指定插件对某事件的所有订阅。

        Returns:
            被移除的订阅数量。
        """
        with self._lock:
            original = self._subscribers.get(event_name, [])
            filtered = [s for s in original if s.plugin_name != plugin_name]
            removed = len(original) - len(filtered)
            if filtered:
                self._subscribers[event_name] = filtered
            else:
                self._subscribers.pop(event_name, None)
        if removed > 0:
            logger.debug(f"插件 '{plugin_name}' 取消订阅事件 '{event_name}' ({removed} 个处理器)")
        return removed

    def unsubscribe_all(self, plugin_name: str) -> int:
        """
        取消指定插件的所有事件订阅。
        通常在插件卸载或禁用时调用。

        Returns:
            被移除的总订阅数量。
        """
        total_removed = 0
        with self._lock:
            for event_name in list(self._subscribers.keys()):
                original = self._subscribers[event_name]
                filtered = [s for s in original if s.plugin_name != plugin_name]
                total_removed += len(original) - len(filtered)
                if filtered:
                    self._subscribers[event_name] = filtered
                else:
                    del self._subscribers[event_name]
        if total_removed > 0:
            logger.debug(f"插件 '{plugin_name}' 已清除全部 {total_removed} 个事件订阅")
        return total_removed

    def emit(self, event_name: str, event_data: Optional[Dict[str, Any]] = None) -> EventResult:
        """
        同步触发事件，按优先级顺序依次调用所有订阅者的处理器。
        注意：此方法仅支持同步处理器。异步处理器（返回协程的函数）
        在异步上下文中会被跳过并记录警告。

        Args:
            event_name: 事件名称。
            event_data: 事件数据字典。

        Returns:
            EventResult 汇总所有处理器的执行结果。
        """
        with self._lock:
            subscribers = list(self._subscribers.get(event_name, []))

        result = EventResult(event_name=event_name, handler_count=len(subscribers))

        for sub in subscribers:
            try:
                handler_result = sub.handler(event_data or {})
                # 如果处理器返回协程，尝试同步运行
                if inspect.isawaitable(handler_result):
                    try:
                        loop = asyncio.get_running_loop()
                    except RuntimeError:
                        loop = None
                    if loop and loop.is_running():
                        logger.warning(
                            f"事件 '{event_name}' 处理器 '{sub.plugin_name}' 返回协程但当前在异步上下文，跳过"
                        )
                        continue
                    handler_result = asyncio.run(handler_result)
                result.results.append({
                    "plugin_name": sub.plugin_name,
                    "result": handler_result,
                })
            except Exception as exc:
                logger.error(f"事件 '{event_name}' 处理器 '{sub.plugin_name}' 执行失败: {exc}")
                result.errors.append({
                    "plugin_name": sub.plugin_name,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                })

        return result

    def list_events(self) -> Dict[str, List[Dict[str, Any]]]:
        """列出当前所有已注册的事件及其订阅者信息。"""
        with self._lock:
            return {
                event_name: [sub.to_dict() for sub in subs]
                for event_name, subs in self._subscribers.items()
            }

    def list_plugin_subscriptions(self, plugin_name: str) -> List[Dict[str, Any]]:
        """列出指定插件订阅的所有事件。"""
        subscriptions: List[Dict[str, Any]] = []
        with self._lock:
            for event_name, subs in self._subscribers.items():
                for sub in subs:
                    if sub.plugin_name == plugin_name:
                        subscriptions.append({
                            "event_name": event_name,
                            **sub.to_dict(),
                        })
        return subscriptions


# 全局事件总线单例
plugin_event_bus = PluginEventBus()
