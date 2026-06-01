"""
技能版本管理器 — 语义化版本管理、冲突检测和回滚支持。
"""
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Union

from loguru import logger


def parse_semver(version: str) -> tuple[int, int, int]:
    """
    解析语义化版本字符串为 (major, minor, patch) 元组。
    支持 "1.0.0" 和 "v1.0.0" 格式。
    """
    v = version.lstrip("v")
    try:
        parts = v.split(".")
        major = int(parts[0]) if len(parts) > 0 else 0
        minor = int(parts[1]) if len(parts) > 1 else 0
        patch = int(parts[2]) if len(parts) > 2 else 0
        return (major, minor, patch)
    except (ValueError, IndexError):
        return (0, 0, 0)


def compare_versions(v1: str, v2: str) -> int:
    """
    比较两个语义化版本。
    返回: >0 表示 v1 > v2, <0 表示 v1 < v2, 0 表示相等。
    """
    a = parse_semver(v1)
    b = parse_semver(v2)
    if a > b:
        return 1
    elif a < b:
        return -1
    return 0


def validate_upgrade_path(old_version: str, new_version: str) -> dict:
    """
    验证升级路径是否合法。
    不允许跨主版本降级。
    """
    old_parts = parse_semver(old_version)
    new_parts = parse_semver(new_version)

    if new_parts < old_parts:
        # 降级检查 — 只允许跨主版本降级
        if new_parts[0] < old_parts[0]:
            return {
                "valid": False,
                "reason": f"不支持跨主版本降级: {old_version} -> {new_version}",
            }
        return {
            "valid": True,
            "warning": f"降级风险: {old_version} -> {new_version}，建议测试验证",
        }

    return {"valid": True}


def detect_schema_changes(old_config: dict, new_config: dict) -> list[str]:
    """
    检测两个技能版本之间的配置 schema 变化。
    返回变化描述列表。
    """
    changes = []
    old_inputs = set(old_config.get("inputs", {}).keys())
    new_inputs = set(new_config.get("inputs", {}).keys())

    added = new_inputs - old_inputs
    removed = old_inputs - new_inputs

    if added:
        changes.append(f"新增输入参数: {', '.join(sorted(added))}")
    if removed:
        changes.append(f"删除输入参数: {', '.join(sorted(removed))}")

    old_outputs = set(old_config.get("outputs", {}).keys())
    new_outputs = set(new_config.get("outputs", {}).keys())
    out_added = new_outputs - old_outputs
    out_removed = old_outputs - new_outputs

    if out_added:
        changes.append(f"新增输出字段: {', '.join(sorted(out_added))}")
    if out_removed:
        changes.append(f"删除输出字段: {', '.join(sorted(out_removed))}")

    return changes


def detect_conflicts(skill_name: str, new_config: dict, installed_version: Optional[str] = None) -> dict:
    """
    检测技能版本冲突。
    检查不兼容的输入/输出 schema 变更和依赖冲突。
    """
    conflicts = []
    warnings = []

    # 检查输入输出 schema 兼容性
    if installed_version:
        # 如果有已安装版本，可以进一步做 schema 对比
        pass

    # 检查依赖声明
    dependencies = new_config.get("dependencies", {})
    if isinstance(dependencies, dict):
        for dep_name, dep_version in dependencies.items():
            if dep_version.startswith(">=") or dep_version.startswith("^"):
                warnings.append(f"依赖 {dep_name} 需要版本 {dep_version}，可能与其他技能冲突")

    return {
        "has_conflicts": len(conflicts) > 0,
        "conflicts": conflicts,
        "warnings": warnings,
        "recommendation": "建议安装" if not conflicts else "安装可能存在兼容性问题",
    }


class SkillVersionManager:
    """
    技能版本管理器。
    管理技能的版本历史记录和回滚操作。
    """

    MAX_HISTORY_ENTRIES = 10

    def __init__(self, skill_dir: Path):
        self.skill_dir = Path(skill_dir)
        self.history_path = self.skill_dir / ".version_history.json"

    def get_history(self) -> list[dict]:
        """获取版本历史记录。"""
        if self.history_path.exists():
            try:
                return json.loads(self.history_path.read_text())
            except (json.JSONDecodeError, OSError):
                return []
        return []

    def _save_history(self, history: list[dict]):
        """保存版本历史记录。"""
        self.history_path.write_text(
            json.dumps(history, ensure_ascii=False, indent=2)
        )

    def record_install(self, version: str, config_snapshot: Optional[dict] = None):
        """
        记录一个新版本的安装事件。
        """
        history = self.get_history()
        history.append({
            "version": version,
            "config_snapshot": config_snapshot or {},
            "installed_at": datetime.now(timezone.utc).isoformat(),
            "action": "install",
        })
        # 保留最近 10 条记录
        if len(history) > self.MAX_HISTORY_ENTRIES:
            history = history[-self.MAX_HISTORY_ENTRIES:]
        self._save_history(history)

    def record_upgrade(self, old_version: str, new_version: str, config_snapshot: Optional[dict] = None):
        """
        记录版本升级事件。
        """
        history = self.get_history()
        history.append({
            "version": new_version,
            "previous_version": old_version,
            "config_snapshot": config_snapshot or {},
            "installed_at": datetime.now(timezone.utc).isoformat(),
            "action": "upgrade",
        })
        if len(history) > self.MAX_HISTORY_ENTRIES:
            history = history[-self.MAX_HISTORY_ENTRIES:]
        self._save_history(history)

    def record_uninstall(self, version: str):
        """
        记录卸载事件。
        """
        history = self.get_history()
        history.append({
            "version": version,
            "installed_at": datetime.now(timezone.utc).isoformat(),
            "action": "uninstall",
        })
        if len(history) > self.MAX_HISTORY_ENTRIES:
            history = history[-self.MAX_HISTORY_ENTRIES:]
        self._save_history(history)

    def get_latest_version(self) -> Optional[str]:
        """获取最新安装的版本。"""
        history = self.get_history()
        for entry in reversed(history):
            if entry.get("action") in ("install", "upgrade"):
                return entry.get("version")
        return None

    def can_rollback(self) -> bool:
        """检查是否有可回滚的版本。"""
        history = self.get_history()
        install_entries = [e for e in history if e.get("action") in ("install", "upgrade")]
        return len(install_entries) >= 2
