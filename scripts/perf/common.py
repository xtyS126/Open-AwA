"""
性能压测公共框架
使用 asyncio + aiohttp 实现轻量级并发压测，不依赖 Locust 等重型框架。

核心功能：
- run_load_test: 执行指定时间的并发负载测试
- PerformanceReport: 测试结果数据类
- format_report: 格式化输出性能摘要
"""

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List

import aiohttp


@dataclass
class PerformanceReport:
    """性能测试报告，包含所有统计指标"""

    endpoint: str = ""
    method: str = "POST"
    concurrency: int = 0
    duration: int = 0
    total_requests: int = 0
    success_count: int = 0
    failure_count: int = 0
    latencies: List[float] = field(default_factory=list)
    rps: float = 0.0
    p50: float = 0.0
    p95: float = 0.0
    p99: float = 0.0
    min_latency: float = 0.0
    max_latency: float = 0.0
    avg_latency: float = 0.0
    total_duration: float = 0.0
    errors: List[Dict[str, Any]] = field(default_factory=list)


async def _worker(
    session: aiohttp.ClientSession,
    url: str,
    method: str,
    headers: Dict[str, str],
    prepare_payload_func: Callable[[], Dict[str, Any]],
    results: List[Dict[str, Any]],
    stop_event: asyncio.Event,
):
    """单个压测工作协程，在持续时间内不断发送请求并记录结果"""
    while not stop_event.is_set():
        payload = prepare_payload_func()
        start = time.perf_counter()

        try:
            if method.upper() == "GET":
                async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    await resp.read()
                    status = resp.status
                    error_msg = None
            else:
                async with session.post(
                    url, headers=headers, json=payload, timeout=aiohttp.ClientTimeout(total=30)
                ) as resp:
                    await resp.read()
                    status = resp.status
                    error_msg = None
        except asyncio.TimeoutError:
            status = 0
            error_msg = "请求超时"
        except aiohttp.ClientError as e:
            status = 0
            error_msg = f"客户端错误: {e}"
        except Exception as e:
            status = 0
            error_msg = f"未知错误: {e}"

        elapsed = (time.perf_counter() - start) * 1000  # 转换为毫秒
        results.append({
            "status": status,
            "latency_ms": elapsed,
            "error": error_msg,
        })


async def run_load_test(
    url: str,
    method: str,
    headers: Dict[str, str],
    concurrency: int,
    duration: int,
    prepare_payload_func: Callable[[], Dict[str, Any]],
) -> PerformanceReport:
    """执行并发负载测试，在指定持续时间内以目标并发数持续发送请求。

    参数:
        url: 请求地址（完整 URL，包含协议和端口）
        method: HTTP 方法，GET 或 POST
        headers: 请求头字典
        concurrency: 并发工作协程数
        duration: 测试持续时间（秒）
        prepare_payload_func: 每次请求前调用的回调，返回请求体字典（POST 时使用）

    返回:
        PerformanceReport 包含所有统计指标
    """
    results: List[Dict[str, Any]] = []
    stop_event = asyncio.Event()

    connector = aiohttp.TCPConnector(limit=concurrency + 10, force_close=True)
    async with aiohttp.ClientSession(connector=connector) as session:
        # 启动所有工作协程
        tasks = [
            asyncio.create_task(
                _worker(session, url, method, headers, prepare_payload_func, results, stop_event)
            )
            for _ in range(concurrency)
        ]

        start_time = time.perf_counter()
        # 运行指定时长
        await asyncio.sleep(duration)
        # 发出停止信号
        stop_event.set()
        # 等待所有工作协程完成
        await asyncio.gather(*tasks, return_exceptions=True)
        total_time = time.perf_counter() - start_time

    # 提取延迟数据
    latencies = [r["latency_ms"] for r in results]
    success_results = [r for r in results if r["status"] > 0 and r["status"] < 400]
    failure_results = [r for r in results if r["status"] == 0 or r["status"] >= 400]

    success_count = len(success_results)
    failure_count = len(failure_results)
    total_requests = len(results)

    # 计算百分位延迟
    sorted_latencies = sorted(latencies)
    if sorted_latencies:
        p50 = sorted_latencies[int(total_requests * 0.50)] if total_requests > 0 else 0.0
        p95 = sorted_latencies[int(total_requests * 0.95)] if total_requests > 0 else 0.0
        p99 = sorted_latencies[int(total_requests * 0.99)] if total_requests > 0 else 0.0
        min_latency = sorted_latencies[0]
        max_latency = sorted_latencies[-1]
        avg_latency = sum(latencies) / total_requests if total_requests > 0 else 0.0
    else:
        p50 = p95 = p99 = min_latency = max_latency = avg_latency = 0.0

    # 计算吞吐量 (RPS)
    rps = total_requests / total_time if total_time > 0 else 0.0

    # 收集错误摘要（最多保留前 10 条）
    error_summary: List[Dict[str, Any]] = []
    for fr in failure_results[:10]:
        if fr.get("error"):
            error_summary.append({
                "status": fr["status"],
                "latency_ms": fr["latency_ms"],
                "error": fr["error"],
            })

    return PerformanceReport(
        endpoint=url,
        method=method,
        concurrency=concurrency,
        duration=duration,
        total_requests=total_requests,
        success_count=success_count,
        failure_count=failure_count,
        latencies=latencies,
        rps=rps,
        p50=p50,
        p95=p95,
        p99=p99,
        min_latency=min_latency,
        max_latency=max_latency,
        avg_latency=avg_latency,
        total_duration=total_time,
        errors=error_summary,
    )


def format_report(report: PerformanceReport) -> str:
    """格式化输出性能测试摘要。

    参数:
        report: PerformanceReport 实例

    返回:
        格式化后的字符串
    """
    success_rate = (
        (report.success_count / report.total_requests * 100)
        if report.total_requests > 0
        else 0.0
    )

    lines = [
        "=" * 60,
        f"  性能压测报告",
        "=" * 60,
        f"  接口:        {report.method} {report.endpoint}",
        f"  并发数:      {report.concurrency}",
        f"  持续时间:    {report.duration}s (实际 {report.total_duration:.2f}s)",
        "-" * 60,
        f"  总请求数:    {report.total_requests}",
        f"  成功:        {report.success_count} ({success_rate:.1f}%)",
        f"  失败:        {report.failure_count} ({100 - success_rate:.1f}%)",
        "-" * 60,
        f"  吞吐量(RPS): {report.rps:.2f} 请求/秒",
        "-" * 60,
        f"  最小延迟:    {report.min_latency:.2f}ms",
        f"  平均延迟:    {report.avg_latency:.2f}ms",
        f"  最大延迟:    {report.max_latency:.2f}ms",
        f"  P50 延迟:    {report.p50:.2f}ms",
        f"  P95 延迟:    {report.p95:.2f}ms",
        f"  P99 延迟:    {report.p99:.2f}ms",
        "=" * 60,
    ]

    if report.errors:
        lines.append("")
        lines.append(f"  错误详情（前 {len(report.errors)} 条）:")
        for i, err in enumerate(report.errors, 1):
            lines.append(f"    {i}. [{err['status']}] {err['error']} ({err['latency_ms']:.0f}ms)")

    return "\n".join(lines)
