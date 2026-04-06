"""
工具函数模块
提供通用辅助函数、错误重试机制和性能监控
"""

from backend.skills.weixin.utils.helpers import (
    sanitize_account_id,
    pick_value,
    build_random_wechat_uin,
    normalize_binding_status,
)

from backend.skills.weixin.utils.retry import (
    CircuitState,
    RetryConfig,
    CircuitBreakerConfig,
    CircuitBreaker,
    ExponentialBackoff,
    calculate_backoff_delay,
    retry_with_backoff,
    CircuitBreakerOpenError,
    ErrorNotification,
    ErrorNotifier,
    send_error_notice,
    get_default_error_notifier,
)

from backend.skills.weixin.utils.metrics import (
    TimingRecord,
    TraceContext,
    TracingManager,
    PerformanceMetrics,
    MetricsCollector,
    StructuredLogger,
    track_performance,
    track_sync_performance,
    WeixinPerformanceMonitor,
    get_tracing_manager,
    get_metrics_collector,
    create_structured_logger,
    get_weixin_monitor,
)

__all__ = [
    "sanitize_account_id",
    "pick_value",
    "build_random_wechat_uin",
    "normalize_binding_status",
    "CircuitState",
    "RetryConfig",
    "CircuitBreakerConfig",
    "CircuitBreaker",
    "ExponentialBackoff",
    "calculate_backoff_delay",
    "retry_with_backoff",
    "CircuitBreakerOpenError",
    "ErrorNotification",
    "ErrorNotifier",
    "send_error_notice",
    "get_default_error_notifier",
    "TimingRecord",
    "TraceContext",
    "TracingManager",
    "PerformanceMetrics",
    "MetricsCollector",
    "StructuredLogger",
    "track_performance",
    "track_sync_performance",
    "WeixinPerformanceMonitor",
    "get_tracing_manager",
    "get_metrics_collector",
    "create_structured_logger",
    "get_weixin_monitor",
]
