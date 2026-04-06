"""
性能监控模块
实现全链路耗时追踪、结构化日志增强和性能指标收集
"""

from __future__ import annotations

import asyncio
import json
import time
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Callable
from uuid import uuid4

from loguru import logger


@dataclass
class TimingRecord:
    """
    耗时记录数据类
    封装单个操作的耗时信息

    属性:
        name: 操作名称
        start_time: 开始时间戳
        end_time: 结束时间戳（可选）
        duration_ms: 耗时（毫秒，可选）
        metadata: 元数据
        parent_id: 父记录ID（可选）
        record_id: 记录唯一ID
    """

    name: str
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None
    duration_ms: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    parent_id: Optional[str] = None
    record_id: str = field(default_factory=lambda: str(uuid4())[:8])

    def finish(self) -> float:
        """
        结束计时并计算耗时

        返回:
            耗时（毫秒）
        """
        self.end_time = time.time()
        self.duration_ms = (self.end_time - self.start_time) * 1000
        return self.duration_ms

    def to_dict(self) -> Dict[str, Any]:
        """
        将记录转换为字典格式

        返回:
            包含记录信息的字典
        """
        return {
            "record_id": self.record_id,
            "name": self.name,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_ms": self.duration_ms,
            "metadata": self.metadata,
            "parent_id": self.parent_id,
        }


class TraceContext:
    """
    全链路追踪上下文类
    管理一次完整请求的追踪信息

    属性:
        trace_id: 追踪ID
        records: 耗时记录列表
        current_record: 当前活动记录
        metadata: 上下文元数据
    """

    def __init__(self, trace_id: Optional[str] = None) -> None:
        """
        初始化追踪上下文

        参数:
            trace_id: 追踪ID，如果为None则自动生成
        """
        self.trace_id = trace_id or str(uuid4())[:12]
        self.records: List[TimingRecord] = []
        self._current_record: Optional[TimingRecord] = None
        self.metadata: Dict[str, Any] = {}
        self._start_time = time.time()

    def start_span(
        self, name: str, metadata: Optional[Dict[str, Any]] = None
    ) -> TimingRecord:
        """
        开始一个新的追踪段

        参数:
            name: 段名称
            metadata: 元数据

        返回:
            TimingRecord实例
        """
        parent_id = self._current_record.record_id if self._current_record else None
        record = TimingRecord(
            name=name,
            metadata=metadata or {},
            parent_id=parent_id,
        )
        self.records.append(record)
        self._current_record = record
        return record

    def end_span(self, record: TimingRecord) -> float:
        """
        结束追踪段

        参数:
            record: 要结束的记录

        返回:
            耗时（毫秒）
        """
        duration = record.finish()
        if self._current_record == record:
            self._current_record = None
        return duration

    def get_total_duration_ms(self) -> float:
        """
        获取总耗时

        返回:
            总耗时（毫秒）
        """
        return (time.time() - self._start_time) * 1000

    def get_summary(self) -> Dict[str, Any]:
        """
        获取追踪摘要

        返回:
            包含追踪摘要的字典
        """
        completed_records = [r for r in self.records if r.duration_ms is not None]
        total_duration = self.get_total_duration_ms()

        breakdown: Dict[str, float] = {}
        for record in completed_records:
            if record.duration_ms is not None:
                breakdown[record.name] = breakdown.get(record.name, 0) + record.duration_ms

        return {
            "trace_id": self.trace_id,
            "total_duration_ms": round(total_duration, 2),
            "span_count": len(self.records),
            "completed_spans": len(completed_records),
            "breakdown": {k: round(v, 2) for k, v in breakdown.items()},
            "metadata": self.metadata,
        }

    def render_debug_output(self) -> str:
        """
        渲染调试输出格式的追踪信息

        返回:
            格式化的调试输出字符串
        """
        lines = []
        lines.append(f"全链路追踪 trace_id={self.trace_id}")
        lines.append("=" * 50)

        for record in self.records:
            indent = "  " if record.parent_id else ""
            duration_str = (
                f"{record.duration_ms:.1f}ms"
                if record.duration_ms is not None
                else "进行中"
            )
            lines.append(f"{indent}|- {record.name}: {duration_str}")
            if record.metadata:
                for key, value in record.metadata.items():
                    lines.append(f"{indent}|  {key}: {value}")

        total = self.get_total_duration_ms()
        lines.append("=" * 50)
        lines.append(f"总耗时: {total:.1f}ms")

        return "\n".join(lines)


class TracingManager:
    """
    追踪管理器类
    管理多个追踪上下文

    属性:
        contexts: 追踪上下文字典
    """

    def __init__(self) -> None:
        """初始化追踪管理器"""
        self._contexts: Dict[str, TraceContext] = {}
        self._current_context: Optional[TraceContext] = None

    def create_context(self, trace_id: Optional[str] = None) -> TraceContext:
        """
        创建新的追踪上下文

        参数:
            trace_id: 追踪ID

        返回:
            TraceContext实例
        """
        context = TraceContext(trace_id)
        self._contexts[context.trace_id] = context
        self._current_context = context
        return context

    def get_context(self, trace_id: str) -> Optional[TraceContext]:
        """
        获取追踪上下文

        参数:
            trace_id: 追踪ID

        返回:
            TraceContext实例，如果不存在则返回None
        """
        return self._contexts.get(trace_id)

    def get_current_context(self) -> Optional[TraceContext]:
        """
        获取当前活动的追踪上下文

        返回:
            当前TraceContext实例，如果没有则返回None
        """
        return self._current_context

    def finish_context(self, trace_id: str) -> Optional[Dict[str, Any]]:
        """
        完成追踪上下文并返回摘要

        参数:
            trace_id: 追踪ID

        返回:
            追踪摘要字典，如果上下文不存在则返回None
        """
        context = self._contexts.pop(trace_id, None)
        if context:
            if self._current_context == context:
                self._current_context = None
            return context.get_summary()
        return None

    @asynccontextmanager
    async def trace(self, name: str, metadata: Optional[Dict[str, Any]] = None):
        """
        异步追踪上下文管理器

        参数:
            name: 追踪名称
            metadata: 元数据

        使用示例:
            async with tracing_manager.trace("api_call", {"endpoint": "/send"}):
                await some_api_call()
        """
        context = self.create_context()
        span = context.start_span(name, metadata)
        try:
            yield context
        finally:
            context.end_span(span)
            summary = self.finish_context(context.trace_id)
            if summary:
                logger.debug(f"[Trace] {json.dumps(summary, ensure_ascii=False)}")

    @contextmanager
    def trace_sync(self, name: str, metadata: Optional[Dict[str, Any]] = None):
        """
        同步追踪上下文管理器

        参数:
            name: 追踪名称
            metadata: 元数据

        使用示例:
            with tracing_manager.trace_sync("db_query", {"table": "users"}):
                db.execute(query)
        """
        context = self.create_context()
        span = context.start_span(name, metadata)
        try:
            yield context
        finally:
            context.end_span(span)
            summary = self.finish_context(context.trace_id)
            if summary:
                logger.debug(f"[Trace] {json.dumps(summary, ensure_ascii=False)}")


default_tracing_manager = TracingManager()


def get_tracing_manager() -> TracingManager:
    """
    获取默认的追踪管理器实例

    返回:
        TracingManager实例
    """
    return default_tracing_manager


@dataclass
class PerformanceMetrics:
    """
    性能指标数据类
    封装性能指标收集结果

    属性:
        name: 指标名称
        value: 指标值
        unit: 单位
        timestamp: 时间戳
        labels: 标签字典
    """

    name: str
    value: float
    unit: str = "ms"
    timestamp: float = field(default_factory=time.time)
    labels: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """
        将指标转换为字典格式

        返回:
            包含指标信息的字典
        """
        return {
            "name": self.name,
            "value": self.value,
            "unit": self.unit,
            "timestamp": self.timestamp,
            "labels": self.labels,
        }


class MetricsCollector:
    """
    性能指标收集器类
    收集和聚合性能指标

    属性:
        metrics: 指标列表
        counters: 计数器字典
        gauges: 仪表字典
        histograms: 直方图字典
    """

    def __init__(self, namespace: str = "weixin") -> None:
        """
        初始化指标收集器

        参数:
            namespace: 指标命名空间
        """
        self.namespace = namespace
        self._metrics: List[PerformanceMetrics] = []
        self._counters: Dict[str, float] = {}
        self._gauges: Dict[str, float] = {}
        self._histograms: Dict[str, List[float]] = {}
        self._lock = asyncio.Lock()

    def _make_key(self, name: str, labels: Optional[Dict[str, str]] = None) -> str:
        """
        生成指标键

        参数:
            name: 指标名称
            labels: 标签字典

        返回:
            指标键字符串
        """
        key = f"{self.namespace}_{name}"
        if labels:
            label_str = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
            key = f"{key}{{{label_str}}}"
        return key

    async def record_counter(
        self,
        name: str,
        value: float = 1.0,
        labels: Optional[Dict[str, str]] = None,
    ) -> None:
        """
        记录计数器指标

        参数:
            name: 指标名称
            value: 增量值
            labels: 标签字典
        """
        key = self._make_key(name, labels)
        async with self._lock:
            self._counters[key] = self._counters.get(key, 0) + value

    async def record_gauge(
        self,
        name: str,
        value: float,
        labels: Optional[Dict[str, str]] = None,
    ) -> None:
        """
        记录仪表指标

        参数:
            name: 指标名称
            value: 当前值
            labels: 标签字典
        """
        key = self._make_key(name, labels)
        async with self._lock:
            self._gauges[key] = value

    async def record_histogram(
        self,
        name: str,
        value: float,
        labels: Optional[Dict[str, str]] = None,
    ) -> None:
        """
        记录直方图指标

        参数:
            name: 指标名称
            value: 观测值
            labels: 标签字典
        """
        key = self._make_key(name, labels)
        async with self._lock:
            if key not in self._histograms:
                self._histograms[key] = []
            self._histograms[key].append(value)

    def record_timing(
        self,
        name: str,
        duration_ms: float,
        labels: Optional[Dict[str, str]] = None,
    ) -> None:
        """
        记录耗时指标

        参数:
            name: 指标名称
            duration_ms: 耗时（毫秒）
            labels: 标签字典
        """
        metric = PerformanceMetrics(
            name=f"{self.namespace}_{name}",
            value=duration_ms,
            unit="ms",
            labels=labels or {},
        )
        self._metrics.append(metric)

    def get_counters(self) -> Dict[str, float]:
        """
        获取所有计数器

        返回:
            计数器字典
        """
        return dict(self._counters)

    def get_gauges(self) -> Dict[str, float]:
        """
        获取所有仪表

        返回:
            仪表字典
        """
        return dict(self._gauges)

    def get_histogram_stats(self) -> Dict[str, Dict[str, float]]:
        """
        获取直方图统计信息

        返回:
            直方图统计字典，包含count、sum、avg、min、max、p50、p95、p99
        """
        stats: Dict[str, Dict[str, float]] = {}
        for key, values in self._histograms.items():
            if not values:
                continue
            sorted_values = sorted(values)
            count = len(values)
            total = sum(values)
            stats[key] = {
                "count": count,
                "sum": total,
                "avg": total / count,
                "min": sorted_values[0],
                "max": sorted_values[-1],
                "p50": sorted_values[int(count * 0.5)],
                "p95": sorted_values[int(count * 0.95)] if count > 1 else sorted_values[0],
                "p99": sorted_values[int(count * 0.99)] if count > 1 else sorted_values[0],
            }
        return stats

    def export_prometheus_format(self) -> str:
        """
        导出Prometheus格式的指标

        返回:
            Prometheus文本格式的指标字符串
        """
        lines = []

        for key, value in sorted(self._counters.items()):
            lines.append(f"# TYPE {key.split('{')[0]} counter")
            lines.append(f"{key} {value}")

        for key, value in sorted(self._gauges.items()):
            lines.append(f"# TYPE {key.split('{')[0]} gauge")
            lines.append(f"{key} {value}")

        for key, stats in sorted(self.get_histogram_stats().items()):
            base_name = key.split("{")[0]
            lines.append(f"# TYPE {base_name} summary")
            lines.append(f"{base_name}_count {stats['count']}")
            lines.append(f"{base_name}_sum {stats['sum']:.2f}")
            lines.append(f'{base_name}{{quantile="0.5"}} {stats["p50"]:.2f}')
            lines.append(f'{base_name}{{quantile="0.95"}} {stats["p95"]:.2f}')
            lines.append(f'{base_name}{{quantile="0.99"}} {stats["p99"]:.2f}')

        return "\n".join(lines) + "\n"

    def clear(self) -> None:
        """清空所有指标"""
        self._metrics.clear()
        self._counters.clear()
        self._gauges.clear()
        self._histograms.clear()


default_metrics_collector = MetricsCollector()


def get_metrics_collector() -> MetricsCollector:
    """
    获取默认的指标收集器实例

    返回:
        MetricsCollector实例
    """
    return default_metrics_collector


class StructuredLogger:
    """
    结构化日志增强类
    提供结构化日志记录功能

    属性:
        context: 日志上下文字典
    """

    def __init__(self, name: str) -> None:
        """
        初始化结构化日志器

        参数:
            name: 日志器名称
        """
        self.name = name
        self._context: Dict[str, Any] = {}

    def set_context(self, **kwargs: Any) -> None:
        """
        设置日志上下文

        参数:
            kwargs: 上下文键值对
        """
        self._context.update(kwargs)

    def clear_context(self) -> None:
        """清空日志上下文"""
        self._context.clear()

    def _build_message(self, message: str, extra: Optional[Dict[str, Any]] = None) -> str:
        """
        构建结构化日志消息

        参数:
            message: 原始消息
            extra: 额外字段

        返回:
            结构化的JSON格式消息
        """
        log_data = {
            "logger": self.name,
            "message": message,
            "context": self._context,
        }
        if extra:
            log_data["extra"] = extra
        return json.dumps(log_data, ensure_ascii=False)

    def debug(self, message: str, **kwargs: Any) -> None:
        """
        记录DEBUG级别日志

        参数:
            message: 日志消息
            kwargs: 额外字段
        """
        logger.debug(self._build_message(message, kwargs if kwargs else None))

    def info(self, message: str, **kwargs: Any) -> None:
        """
        记录INFO级别日志

        参数:
            message: 日志消息
            kwargs: 额外字段
        """
        logger.info(self._build_message(message, kwargs if kwargs else None))

    def warning(self, message: str, **kwargs: Any) -> None:
        """
        记录WARNING级别日志

        参数:
            message: 日志消息
            kwargs: 额外字段
        """
        logger.warning(self._build_message(message, kwargs if kwargs else None))

    def error(self, message: str, **kwargs: Any) -> None:
        """
        记录ERROR级别日志

        参数:
            message: 日志消息
            kwargs: 额外字段
        """
        logger.error(self._build_message(message, kwargs if kwargs else None))


def create_structured_logger(name: str) -> StructuredLogger:
    """
    创建结构化日志器

    参数:
        name: 日志器名称

    返回:
        StructuredLogger实例
    """
    return StructuredLogger(name)


@asynccontextmanager
async def track_performance(
    operation_name: str,
    labels: Optional[Dict[str, str]] = None,
    on_complete: Optional[Callable[[float], None]] = None,
):
    """
    性能追踪上下文管理器

    参数:
        operation_name: 操作名称
        labels: 标签字典
        on_complete: 完成时的回调函数

    使用示例:
        async with track_performance("api_call", {"endpoint": "/send"}):
            await some_api_call()
    """
    start_time = time.time()
    tracing_manager = get_tracing_manager()
    context = tracing_manager.get_current_context()

    span = None
    if context:
        span = context.start_span(operation_name, labels)

    try:
        yield
    finally:
        duration_ms = (time.time() - start_time) * 1000

        if span and context:
            context.end_span(span)

        metrics_collector = get_metrics_collector()
        metrics_collector.record_timing(operation_name, duration_ms, labels)

        if on_complete:
            on_complete(duration_ms)

        logger.debug(
            f"[Performance] {operation_name} 完成，耗时: {duration_ms:.2f}ms"
        )


def track_sync_performance(
    operation_name: str,
    labels: Optional[Dict[str, str]] = None,
    on_complete: Optional[Callable[[float], None]] = None,
):
    """
    同步性能追踪上下文管理器

    参数:
        operation_name: 操作名称
        labels: 标签字典
        on_complete: 完成时的回调函数

    使用示例:
        with track_sync_performance("db_query", {"table": "users"}):
            db.execute(query)
    """
    start_time = time.time()

    @contextmanager
    def _tracker():
        try:
            yield
        finally:
            duration_ms = (time.time() - start_time) * 1000

            metrics_collector = get_metrics_collector()
            metrics_collector.record_timing(operation_name, duration_ms, labels)

            if on_complete:
                on_complete(duration_ms)

            logger.debug(
                f"[Performance] {operation_name} 完成，耗时: {duration_ms:.2f}ms"
            )

    return _tracker()


class WeixinPerformanceMonitor:
    """
    微信性能监控类
    封装微信相关的性能监控功能

    属性:
        metrics_collector: 指标收集器
        tracing_manager: 追踪管理器
        logger: 结构化日志器
    """

    def __init__(self) -> None:
        """初始化微信性能监控器"""
        self.metrics_collector = MetricsCollector(namespace="weixin")
        self.tracing_manager = TracingManager()
        self.logger = create_structured_logger("weixin.monitor")

    async def record_api_call(
        self,
        endpoint: str,
        duration_ms: float,
        status: str,
        account_id: Optional[str] = None,
    ) -> None:
        """
        记录API调用指标

        参数:
            endpoint: API端点
            duration_ms: 耗时（毫秒）
            status: 状态（success/error）
            account_id: 账号ID
        """
        labels = {"endpoint": endpoint, "status": status}
        if account_id:
            labels["account_id"] = account_id

        await self.metrics_collector.record_counter("api_calls_total", labels=labels)
        await self.metrics_collector.record_histogram(
            "api_call_duration_ms", duration_ms, labels=labels
        )

        self.logger.info(
            "API调用完成",
            endpoint=endpoint,
            duration_ms=round(duration_ms, 2),
            status=status,
            account_id=account_id,
        )

    async def record_message_processed(
        self,
        message_type: str,
        duration_ms: float,
        status: str,
    ) -> None:
        """
        记录消息处理指标

        参数:
            message_type: 消息类型
            duration_ms: 耗时（毫秒）
            status: 状态
        """
        labels = {"message_type": message_type, "status": status}

        await self.metrics_collector.record_counter(
            "messages_processed_total", labels=labels
        )
        await self.metrics_collector.record_histogram(
            "message_processing_duration_ms", duration_ms, labels=labels
        )

    async def record_circuit_breaker_event(
        self,
        circuit_name: str,
        event: str,
    ) -> None:
        """
        记录熔断器事件

        参数:
            circuit_name: 熔断器名称
            event: 事件类型（opened/closed/half_open）
        """
        labels = {"circuit": circuit_name, "event": event}
        await self.metrics_collector.record_counter(
            "circuit_breaker_events_total", labels=labels
        )

        self.logger.warning(
            "熔断器状态变更",
            circuit=circuit_name,
            event=event,
        )

    def get_metrics_summary(self) -> Dict[str, Any]:
        """
        获取指标摘要

        返回:
            指标摘要字典
        """
        return {
            "counters": self.metrics_collector.get_counters(),
            "gauges": self.metrics_collector.get_gauges(),
            "histograms": self.metrics_collector.get_histogram_stats(),
        }


default_weixin_monitor = WeixinPerformanceMonitor()


def get_weixin_monitor() -> WeixinPerformanceMonitor:
    """
    获取默认的微信性能监控器实例

    返回:
        WeixinPerformanceMonitor实例
    """
    return default_weixin_monitor
