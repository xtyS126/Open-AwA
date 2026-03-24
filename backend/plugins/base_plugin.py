from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, List


class BasePlugin(ABC):
    name: str = ""
    version: str = "1.0.0"
    description: str = ""
    enable_count: int = 0
    rollback_events: List[str] = []

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self._initialized = False
        self._state = "registered"

    @abstractmethod
    def initialize(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def execute(self, *args, **kwargs) -> Any:
        raise NotImplementedError

    def cleanup(self) -> None:
        self._initialized = False

    def validate(self) -> bool:
        return True

    def on_registered(self) -> None:
        self._state = "registered"

    def on_loaded(self) -> None:
        self._state = "loaded"

    def on_enabled(self) -> None:
        self._state = "enabled"

    def on_disabled(self) -> None:
        self._state = "disabled"

    def on_unloaded(self) -> None:
        self._state = "unloaded"

    def on_updating(self) -> None:
        self._state = "updating"

    def on_error_state(self) -> None:
        self._state = "error"

    def on_error(self, error: Exception, from_state: str, to_state: str) -> None:
        self._state = "error"

    def rollback(self, previous_state: str, context: Optional[Dict[str, Any]] = None) -> bool:
        self._state = previous_state
        return True
