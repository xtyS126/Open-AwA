"""冗余运行时退役门禁。"""

import json
from pathlib import Path

from plugins.schema_validator import ManifestExtensionSchemaValidator


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"


def test_data_collector_placeholder_has_no_production_references() -> None:
    """未实现的数据采集器不得继续占用生产生命周期与执行路径。"""

    forbidden_markers = ("data.collector", "_shutdown_data_collector")
    offenders: list[str] = []

    for source_path in BACKEND_ROOT.rglob("*.py"):
        if "tests" in source_path.parts:
            continue
        source = source_path.read_text(encoding="utf-8-sig")
        if any(marker in source for marker in forbidden_markers):
            offenders.append(source_path.relative_to(PROJECT_ROOT).as_posix())

    assert offenders == []


def test_bilibili_placeholder_scheduler_package_is_retired() -> None:
    """未接入插件生命周期的第二调度器实现不得保留。"""

    scheduler_package = (
        BACKEND_ROOT / "plugins" / "bilibili_toolkit_builtin" / "scheduler"
    )

    assert not scheduler_package.exists()


def test_bilibili_public_schema_does_not_advertise_retired_trigger() -> None:
    """公开配置 schema 不得继续引导用户创建无消费者的触发器配置。"""

    schema_path = (
        BACKEND_ROOT / "plugins" / "bilibili_toolkit_builtin" / "schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8-sig"))

    assert "trigger" not in schema.get("properties", {})


def test_scheduler_extension_point_is_rejected_without_runtime_consumer() -> None:
    """只有登记能力而没有执行消费者的 scheduler 扩展点必须拒绝。"""

    validator = ManifestExtensionSchemaValidator()
    result = validator.validate_extension(
        {
            "point": "scheduler",
            "name": "unused_scheduler",
            "version": "1.0.0",
            "config": {},
        }
    )

    assert result.valid is False
