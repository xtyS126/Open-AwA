"""运行时数据迁移脚本测试。"""

import importlib.util
import sys
from pathlib import Path


def _load_migration_module():
    """加载仓库根目录的迁移脚本模块。"""
    script_path = Path(__file__).resolve().parents[2] / "bin" / "migrate_runtime_data.py"
    spec = importlib.util.spec_from_file_location("migrate_runtime_data", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_iter_conflicts_detects_existing_file(tmp_path: Path):
    """迁移前必须识别同名文件，禁止覆盖。"""
    module = _load_migration_module()
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir()
    destination.mkdir()
    (source / "same.txt").write_text("source", encoding="utf-8")
    (destination / "same.txt").write_text("target", encoding="utf-8")

    assert tuple(module.iter_conflicts(source, destination)) == (destination / "same.txt",)


def test_move_path_merges_directory_without_overwrite(tmp_path: Path):
    """无冲突目录可合并移动，源目录在完成后为空。"""
    module = _load_migration_module()
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    (source / "nested").mkdir(parents=True)
    destination.mkdir()
    (source / "nested" / "record.txt").write_text("content", encoding="utf-8")

    moved_paths = module.move_path(source, destination)

    assert not source.exists()
    assert (destination / "nested" / "record.txt").read_text(encoding="utf-8") == "content"
    assert len(moved_paths) == 1


def test_move_path_prunes_empty_source_without_creating_destination(tmp_path: Path):
    """空的遗留目录应移除，且不得制造无意义目标目录。"""
    module = _load_migration_module()
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir()

    assert module.move_path(source, destination) == []
    assert not source.exists()
    assert not destination.exists()


def test_runtime_migration_covers_vite_cache():
    """Vite 缓存必须迁移到统一 var 运行时目录。"""
    module = _load_migration_module()

    assert any(
        operation.source == ".vite-cache" and operation.destination == "var/cache/vite"
        for operation in module.OPERATIONS
    )


def test_runtime_migration_covers_pytest_caches():
    """pytest 缓存必须收拢到统一运行时目录。"""
    module = _load_migration_module()
    operations = {(operation.source, operation.destination) for operation in module.OPERATIONS}

    assert (".pytest_cache", "var/cache/pytest/root") in operations
    assert ("backend/.pytest_cache", "var/cache/pytest/backend") in operations


def test_runtime_migration_covers_twitter_monitor_data():
    """Twitter 插件运行数据必须迁移到统一运行时目录。"""
    module = _load_migration_module()
    operations = {(operation.source, operation.destination) for operation in module.OPERATIONS}

    assert ("plugins/twitter-monitor/data", "var/plugins/twitter-monitor/data") in operations


def test_runtime_migration_covers_legacy_openawa_archive():
    """旧 OpenAwA 运行时目录必须归档到统一运行时目录。"""
    module = _load_migration_module()
    operations = {(operation.source, operation.destination) for operation in module.OPERATIONS}

    assert ("openawa", "var/archives/legacy-openawa") in operations
