from abc import ABC, abstractmethod
from typing import Dict, Any, Optional


class BasePlugin(ABC):
    name: str = ""
    version: str = "1.0.0"
    description: str = ""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self._initialized = False

    @abstractmethod
    def initialize(self) -> bool:
        pass

    @abstractmethod
    def execute(self, *args, **kwargs) -> Any:
        pass

    def cleanup(self) -> None:
        self._initialized = False

    def validate(self) -> bool:
        return True
