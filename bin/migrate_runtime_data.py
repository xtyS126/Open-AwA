"""将迁移后遗留在源码目录的运行时数据安全收拢到 var 目录。"""

from __future__ import annotations

import argparse
import json
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class MigrationOperation:
    """单个运行时目录或文件的迁移定义。"""

    source: str
    destination: str
    description: str

    @property
    def source_path(self) -> Path:
        """返回绝对源路径。"""
        return PROJECT_ROOT / self.source

    @property
    def destination_path(self) -> Path:
        """返回绝对目标路径。"""
        return PROJECT_ROOT / self.destination


OPERATIONS: tuple[MigrationOperation, ...] = (
    MigrationOperation(".vite-cache", "var/cache/vite", "Vite 开发与测试缓存"),
    MigrationOperation(".pytest_cache", "var/cache/pytest/root", "项目根 pytest 缓存"),
    MigrationOperation(
        "backend/.pytest_cache",
        "var/cache/pytest/backend",
        "后端 pytest 缓存",
    ),
    MigrationOperation("data", "var/data", "项目根遗留运行数据目录"),
    MigrationOperation("uploads", "var/data/uploads", "项目根遗留上传目录"),
    MigrationOperation("backend/data", "var/data", "任务记录和旧数据目录"),
    MigrationOperation("backend/downloads", "var/data/downloads", "下载文件"),
    MigrationOperation("backend/logs", "var/logs/legacy-backend", "旧后端日志"),
    MigrationOperation("backend/uploads", "var/data/uploads", "旧上传文件"),
    MigrationOperation("backend/var", "var/legacy-backend", "旧嵌套运行目录"),
    MigrationOperation("backend/workspace", "var/workspace", "旧工作区"),
    MigrationOperation("var/data/pets", "var/pets", "旧宠物运行数据"),
    MigrationOperation(
        "backend/plugins/bilibili_toolkit_builtin/data",
        "var/plugins/bilibili_toolkit_builtin/data",
        "Bilibili Toolkit 插件运行数据",
    ),
    MigrationOperation(
        "plugins/twitter-monitor/data",
        "var/plugins/twitter-monitor/data",
        "Twitter Monitor 插件运行数据",
    ),
    MigrationOperation("backend/tmp_brooks_e2e_codex", "var/test-runs/legacy/tmp_brooks_e2e_codex", "Brooks E2E 临时目录"),
    MigrationOperation("backend/tmp_demo", "var/test-runs/legacy/tmp_demo", "演示临时目录"),
    MigrationOperation("backend/tmp_test_checkpoint", "var/test-runs/legacy/tmp_test_checkpoint", "检查点临时目录"),
    MigrationOperation("backend/openawa.db", "var/data/legacy-backups/openawa.db", "旧 SQLite 数据库"),
    MigrationOperation("backend/openawa.db.bak.20260724081904", "var/data/legacy-backups/openawa.db.bak.20260724081904", "旧 SQLite 备份"),
    MigrationOperation("backend/openawa.db.bak.20260724081917", "var/data/legacy-backups/openawa.db.bak.20260724081917", "旧 SQLite 备份"),
    MigrationOperation("backend/_e2e_sim.db-shm", "var/test-runs/legacy/_e2e_sim.db-shm", "E2E 共享内存文件"),
    MigrationOperation("backend/_e2e_sim.db-wal", "var/test-runs/legacy/_e2e_sim.db-wal", "E2E WAL 文件"),
    MigrationOperation("backend/pytest_full.log", "var/logs/legacy-backend/pytest_full.log", "pytest 日志"),
    MigrationOperation("backend/rename_files.py", "var/archives/legacy-backend/rename_files.py", "本地辅助脚本"),
    MigrationOperation("backend/test_restore.txt", "var/test-runs/legacy/test_restore.txt", "测试写入文件"),
    MigrationOperation("backend/tmp_plugin_write.txt", "var/test-runs/legacy/tmp_plugin_write.txt", "测试写入文件"),
    MigrationOperation("backend/tmp_test_write.txt", "var/test-runs/legacy/tmp_test_write.txt", "测试写入文件"),
    MigrationOperation("backend/合集视频列表.txt", "var/data/downloads/metadata/合集视频列表.txt", "下载任务清单"),
    MigrationOperation("lib/var/data/models", "var/data/legacy-lib-models", "旧模型缓存"),
    MigrationOperation("lib/var/workspace", "var/workspace", "旧 lib 工作区"),
    MigrationOperation("lib/var", "var/legacy-lib", "空的旧 lib 运行时目录"),
    MigrationOperation("openawa", "var/archives/legacy-openawa", "旧 OpenAwA 运行时归档"),
)


def iter_conflicts(source: Path, destination: Path) -> Iterable[Path]:
    """列出会阻止迁移的同名目标路径。"""
    if not source.exists():
        return ()
    if source.is_file():
        return (destination,) if destination.exists() else ()
    if not destination.exists():
        return ()

    conflicts: list[Path] = []
    for source_file in source.rglob("*"):
        if source_file.is_file():
            candidate = destination / source_file.relative_to(source)
            if candidate.exists():
                conflicts.append(candidate)
    return tuple(conflicts)


def move_path(source: Path, destination: Path) -> list[tuple[Path, Path]]:
    """递归移动路径，拒绝覆盖任何既有文件。"""
    conflicts = tuple(iter_conflicts(source, destination))
    if conflicts:
        formatted = ", ".join(str(path) for path in conflicts[:3])
        raise FileExistsError(f"目标路径已存在，拒绝覆盖: {formatted}")

    moved_paths: list[tuple[Path, Path]] = []
    if source.is_file():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(destination))
        return [(source, destination)]

    if not any(source.iterdir()):
        source.rmdir()
        return []

    destination.mkdir(parents=True, exist_ok=True)
    for child in source.iterdir():
        target_child = destination / child.name
        if child.is_dir():
            moved_paths.extend(move_path(child, target_child))
        else:
            target_child.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(child), str(target_child))
            moved_paths.append((child, target_child))
    source.rmdir()
    return moved_paths


def execute_operations(apply: bool) -> list[dict[str, object]]:
    """检查或执行所有定义的迁移，并返回可追溯记录。"""
    records: list[dict[str, object]] = []
    for operation in OPERATIONS:
        source = operation.source_path
        destination = operation.destination_path
        if not source.exists():
            records.append({"source": operation.source, "destination": operation.destination, "status": "missing"})
            continue

        conflicts = tuple(iter_conflicts(source, destination))
        if conflicts:
            records.append({"source": operation.source, "destination": operation.destination, "status": "conflict", "conflicts": [str(path.relative_to(PROJECT_ROOT)) for path in conflicts]})
            continue

        if not apply:
            records.append({"source": operation.source, "destination": operation.destination, "status": "ready"})
            continue

        moved_paths = move_path(source, destination)
        records.append({"source": operation.source, "destination": operation.destination, "status": "moved", "moved_count": len(moved_paths)})
    return records


def write_manifest(records: list[dict[str, object]]) -> Path:
    """写入本次迁移清单，供人工核对和回退。"""
    manifest_dir = PROJECT_ROOT / "var" / "state" / "migrations"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    manifest_path = manifest_dir / f"runtime-layout-{timestamp}.json"
    manifest_path.write_text(json.dumps({"created_at": datetime.now().isoformat(), "records": records}, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest_path


def main() -> int:
    """执行命令行入口。"""
    parser = argparse.ArgumentParser(description="收拢遗留运行时数据到 var 目录")
    parser.add_argument("--apply", action="store_true", help="实际执行移动；默认仅检查")
    args = parser.parse_args()

    records = execute_operations(apply=args.apply)
    for record in records:
        print(f"[{record['status']}] {record['source']} -> {record['destination']}")

    if args.apply:
        manifest_path = write_manifest(records)
        print(f"迁移清单: {manifest_path.relative_to(PROJECT_ROOT)}")
    else:
        print("这是只读检查；确认后执行: python bin/migrate_runtime_data.py --apply")

    return 1 if any(record["status"] == "conflict" for record in records) else 0


if __name__ == "__main__":
    raise SystemExit(main())
