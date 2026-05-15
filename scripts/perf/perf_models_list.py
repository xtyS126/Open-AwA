"""
模型列表接口（POST /api/billing/models-by-provider/{provider}）并发性能压测脚本。

使用 asyncio + aiohttp 实现轻量级并发压测。

运行示例:
    python scripts/perf/perf_models_list.py --concurrency 50 --duration 30 --base-url http://localhost:8000
    python scripts/perf/perf_models_list.py -c 20 -d 10 --provider anthropic --token my-jwt-token
"""

import argparse
import asyncio
import sys
from pathlib import Path

# 确保项目根目录在 Python 模块搜索路径中，支持直接 `python scripts/perf/xxx.py` 运行
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.perf.common import PerformanceReport, format_report, run_load_test


def build_payload(provider: str = "openai"):
    """生成每次请求的 JSON 体，provider 用于动态设置默认端点"""
    # 根据不同的 provider 设置对应的 API 端点
    default_endpoints = {
        "openai": "https://api.openai.com",
        "anthropic": "https://api.anthropic.com",
        "google": "https://generativelanguage.googleapis.com/v1beta",
        "deepseek": "https://api.deepseek.com/v1",
        "ollama": "http://localhost:11434",
    }
    return {
        "api_endpoint": default_endpoints.get(provider, "https://api.openai.com"),
        "api_key": "test-key-for-perf-test",
    }


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="模型列表接口（POST /api/billing/models-by-provider/{provider}）并发性能压测",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python scripts/perf/perf_models_list.py -c 20 -d 30
  python scripts/perf/perf_models_list.py --concurrency 100 --duration 60 --provider anthropic --base-url http://192.168.1.100:8000 --token eyJ...
        """,
    )
    parser.add_argument(
        "-c", "--concurrency",
        type=int,
        default=50,
        help="并发工作协程数（默认: 50）",
    )
    parser.add_argument(
        "-d", "--duration",
        type=int,
        default=30,
        help="测试持续时间，秒（默认: 30）",
    )
    parser.add_argument(
        "--base-url",
        type=str,
        default="http://localhost:8000",
        help="后端服务基地址（默认: http://localhost:8000）",
    )
    parser.add_argument(
        "--provider",
        type=str,
        default="openai",
        help="供应商名称，用于拼接接口路径（默认: openai）",
    )
    parser.add_argument(
        "--token",
        type=str,
        default="",
        help="认证 Bearer Token（如需鉴权则传入）",
    )
    return parser.parse_args()


async def main():
    args = parse_args()

    # 拼接完整 URL：/api/billing/models-by-provider/{provider}
    endpoint = f"/api/billing/models-by-provider/{args.provider}"
    url = f"{args.base_url.rstrip('/')}{endpoint}"

    # 构建请求头
    headers = {"Content-Type": "application/json"}
    if args.token:
        headers["Authorization"] = f"Bearer {args.token}"

    print(f"\n🚀 开始压测模型列表接口")
    print(f"   地址:       {url}")
    print(f"   供应商:     {args.provider}")
    print(f"   并发数:     {args.concurrency}")
    print(f"   持续时间:   {args.duration}s")
    print(f"   认证:       {'有' if args.token else '无'}")
    print()

    # 构建带闭包的 payload 生成函数
    def payload_func():
        return build_payload(args.provider)

    # 执行负载测试
    report = await run_load_test(
        url=url,
        method="POST",
        headers=headers,
        concurrency=args.concurrency,
        duration=args.duration,
        prepare_payload_func=payload_func,
    )

    # 输出报告
    print(format_report(report))

    # 返回退出码：失败率 > 50% 时返回 1
    if report.total_requests > 0 and report.failure_count / report.total_requests > 0.5:
        sys.exit(1)


if __name__ == "__main__":
    # Windows 上需设置 SelectorEventLoop 以兼容 aiohttp
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
