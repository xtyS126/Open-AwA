"""
简易 Prometheus 指标模块。
这里不引入额外依赖，直接输出 Prometheus 文本格式，满足基础观测需求。
"""

from __future__ import annotations

from collections import defaultdict
from threading import Lock
from typing import Dict, Iterable, Tuple


MetricKey = Tuple[Tuple[str, str], ...]


class SimplePrometheusRegistry:
    """
    维护简单的 Counter 与 Summary 指标，并按 Prometheus 文本格式导出。
    """

    def __init__(self) -> None:
        self._lock = Lock()
        self._counters: Dict[str, Dict[MetricKey, float]] = defaultdict(dict)
        self._summaries: Dict[str, Dict[str, Dict[MetricKey, float]]] = defaultdict(
            lambda: {"count": {}, "sum": {}}
        )
        self._metadata: Dict[str, Dict[str, str]] = {}

    @staticmethod
    def _normalize_labels(labels: Dict[str, str] | None) -> MetricKey:
        normalized = {
            str(key): str(value)
            for key, value in (labels or {}).items()
        }
        return tuple(sorted(normalized.items()))

    def register_counter(self, name: str, description: str) -> None:
        with self._lock:
            self._metadata[name] = {"type": "counter", "description": description}
            self._counters.setdefault(name, {})

    def register_summary(self, name: str, description: str) -> None:
        with self._lock:
            self._metadata[name] = {"type": "summary", "description": description}
            self._summaries.setdefault(name, {"count": {}, "sum": {}})

    def inc(self, name: str, value: float = 1.0, **labels: str) -> None:
        with self._lock:
            label_key = self._normalize_labels(labels)
            current = self._counters.setdefault(name, {}).get(label_key, 0.0)
            self._counters[name][label_key] = current + float(value)

    def observe(self, name: str, value: float, **labels: str) -> None:
        with self._lock:
            label_key = self._normalize_labels(labels)
            summary = self._summaries.setdefault(name, {"count": {}, "sum": {}})
            summary["count"][label_key] = summary["count"].get(label_key, 0.0) + 1.0
            summary["sum"][label_key] = summary["sum"].get(label_key, 0.0) + float(value)

    @staticmethod
    def _format_labels(label_key: MetricKey) -> str:
        if not label_key:
            return ""
        joined = ",".join(f'{key}="{value}"' for key, value in label_key)
        return f"{{{joined}}}"

    @staticmethod
    def _iter_sorted_items(metric_map: Dict[MetricKey, float]) -> Iterable[Tuple[MetricKey, float]]:
        return sorted(metric_map.items(), key=lambda item: item[0])

    def render(self) -> str:
        lines = []
        with self._lock:
            for name in sorted(self._metadata):
                meta = self._metadata[name]
                metric_type = meta["type"]
                description = meta["description"]
                lines.append(f"# HELP {name} {description}")
                lines.append(f"# TYPE {name} {metric_type}")

                if metric_type == "counter":
                    items = self._counters.get(name, {})
                    if not items:
                        lines.append(f"{name} 0")
                    else:
                        for label_key, value in self._iter_sorted_items(items):
                            lines.append(f"{name}{self._format_labels(label_key)} {value}")
                    continue

                summary = self._summaries.get(name, {"count": {}, "sum": {}})
                count_items = summary.get("count", {})
                sum_items = summary.get("sum", {})
                label_keys = sorted(set(count_items) | set(sum_items))
                if not label_keys:
                    lines.append(f"{name}_count 0")
                    lines.append(f"{name}_sum 0")
                    continue
                for label_key in label_keys:
                    lines.append(
                        f"{name}_count{self._format_labels(label_key)} "
                        f"{count_items.get(label_key, 0.0)}"
                    )
                    lines.append(
                        f"{name}_sum{self._format_labels(label_key)} "
                        f"{sum_items.get(label_key, 0.0)}"
                    )

        return "\n".join(lines) + "\n"


prometheus_registry = SimplePrometheusRegistry()
prometheus_registry.register_counter(
    "openawa_model_service_requests_total",
    "模型服务请求总数",
)
prometheus_registry.register_summary(
    "openawa_model_service_request_duration_ms",
    "模型服务请求耗时（毫秒）",
)
prometheus_registry.register_counter(
    "openawa_websocket_messages_total",
    "WebSocket 消息总数",
)
prometheus_registry.register_counter(
    "openawa_tool_execution_total",
    "工具执行总数",
)


def record_model_service_metric(provider: str, purpose: str, status: str, duration_ms: float) -> None:
    """
    记录模型服务请求次数与耗时。
    """

    prometheus_registry.inc(
        "openawa_model_service_requests_total",
        provider=provider,
        purpose=purpose,
        status=status,
    )
    prometheus_registry.observe(
        "openawa_model_service_request_duration_ms",
        duration_ms,
        provider=provider,
        purpose=purpose,
        status=status,
    )


def record_websocket_message_metric(message_type: str, status: str) -> None:
    """
    记录 WebSocket 消息发送或接收情况。
    """

    prometheus_registry.inc(
        "openawa_websocket_messages_total",
        message_type=message_type,
        status=status,
    )


def record_tool_execution_metric(execution_type: str, status: str) -> None:
    """
    记录工具执行次数，用于观察成功率与幂等复用情况。
    """

    prometheus_registry.inc(
        "openawa_tool_execution_total",
        execution_type=execution_type,
        status=status,
    )
