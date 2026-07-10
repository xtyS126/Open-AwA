"""模型目录同步 CLI 入口。

用法：
  python scripts/sync_model_catalog.py [--dry-run] [--source models.dev,openrouter] [--timeout 30]

功能：
  从 models.dev / openrouter.ai 拉取上游模型目录与定价数据，
  合并后写入 backend/config/pricing/pricing_data.json。

  --dry-run 只打印变更统计，不写文件。
  --source 指定数据源（逗号分隔），默认两源都拉。
  --timeout HTTP 超时秒数，默认 30 秒。
"""

import argparse
import asyncio
import sys
from pathlib import Path


def main() -> None:
    """CLI 主入口，解析参数并调用 run_sync。"""
    parser = argparse.ArgumentParser(description="同步模型目录与定价")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印变更不写文件",
    )
    parser.add_argument(
        "--source",
        default="models.dev,openrouter",
        help="数据源，逗号分隔（可选值：models.dev, openrouter）",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="HTTP 超时秒数",
    )
    args = parser.parse_args()

    # 将 backend 加入 sys.path，使 billing.catalog_sync 可被导入
    backend_dir = Path(__file__).resolve().parent.parent / "backend"
    if str(backend_dir) not in sys.path:
        sys.path.insert(0, str(backend_dir))

    from billing.catalog_sync import run_sync

    sources = [s.strip() for s in args.source.split(",") if s.strip()]
    stats = asyncio.run(run_sync(sources=sources, dry_run=args.dry_run, timeout=args.timeout))

    if args.dry_run:
        print(
            f"[Dry-Run] 同步预览: 新增 {stats['added']}, 更新 {stats['updated']}, "
            f"移除 {stats['removed']}, 跳过 {stats['skipped']}"
        )
    else:
        print(
            f"同步完成: 新增 {stats['added']}, 更新 {stats['updated']}, "
            f"保留 {stats['removed']}, 跳过 {stats['skipped']}"
        )
        print(f"同步时间: {stats.get('synced_at', 'N/A')}")


if __name__ == "__main__":
    main()
