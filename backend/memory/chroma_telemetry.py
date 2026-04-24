"""
为 Chroma 提供空 telemetry 实现，避免当前 PostHog 版本组合下的启动噪声。
"""

from chromadb.config import System
from chromadb.telemetry.product import ProductTelemetryClient, ProductTelemetryEvent
from overrides import override


class NoOpProductTelemetryClient(ProductTelemetryClient):
    """
    空实现，不上报任何产品遥测事件。
    """

    def __init__(self, system: System):
        super().__init__(system)

    @override
    def capture(self, event: ProductTelemetryEvent) -> None:
        return None