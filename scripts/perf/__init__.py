"""
性能压测脚本包
使用 asyncio + aiohttp 实现轻量级并发压测，不依赖 Locust 等重型框架。

使用示例:
    python scripts/perf/perf_chat_send.py --concurrency 50 --duration 30 --base-url http://localhost:8000
    python scripts/perf/perf_models_list.py --concurrency 50 --duration 30 --base-url http://localhost:8000
"""

from scripts.perf.common import PerformanceReport, format_report, run_load_test

__all__ = ["PerformanceReport", "format_report", "run_load_test"]
