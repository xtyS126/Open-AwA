"""
插件系统模块，负责插件定义、加载、校验、沙箱隔离、生命周期或扩展协议处理。
这一层通常同时涉及可扩展性、安全性与运行时状态管理。
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, List, ClassVar


class BasePlugin(ABC):
    """
    封装与BasePlugin相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    name: str = ""
    version: str = "1.0.0"
    description: str = ""
    enable_count: int = 0
    rollback_events: ClassVar[List[str]] = []

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        处理init相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        self.config = config or {}
        self._initialized = False
        self._state = "registered"
        self.rollback_events = []

    @abstractmethod
    def initialize(self) -> bool:
        """
        处理initialize相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        raise NotImplementedError

    @abstractmethod
    def execute(self, *args, **kwargs) -> Any:
        """
        处理execute相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        raise NotImplementedError

    def cleanup(self) -> None:
        """
        处理cleanup相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        self._initialized = False

    def validate(self) -> bool:
        """
        处理validate相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        return True

    def on_registered(self) -> None:
        """
        处理on、registered相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        self._state = "registered"

    def on_loaded(self) -> None:
        """
        处理on、loaded相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        self._state = "loaded"

    def on_enabled(self) -> None:
        """
        处理on、enabled相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        self._state = "enabled"

    def on_disabled(self) -> None:
        """
        处理on、disabled相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        self._state = "disabled"

    def on_unloaded(self) -> None:
        """
        处理on、unloaded相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        self._state = "unloaded"

    def on_updating(self) -> None:
        """
        处理on、updating相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        self._state = "updating"

    def on_error_state(self) -> None:
        """
        处理on、error、state相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        self._state = "error"

    def on_error(self, error: Exception, from_state: str, to_state: str) -> None:
        """
        处理on、error相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        self._state = "error"

    def rollback(self, previous_state: str, context: Optional[Dict[str, Any]] = None) -> bool:
        """
        处理rollback相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        self._state = previous_state
        return True
