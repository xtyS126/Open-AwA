"""插件热更新单一状态源与进程重建恢复测试。"""

from __future__ import annotations

import json
import inspect
from pathlib import Path

from plugins.hot_update_manager import HotUpdateManager
from plugins.plugin_manager import PluginManager


PLUGIN_SOURCE = '''from plugins.base_plugin import BasePlugin


class RecoveryPlugin(BasePlugin):
    name = "recovery_plugin"
    version = "1.0.0"
    description = "recovery test plugin"

    async def initialize(self):
        self.initialize_completed = True
        return True

    def execute(self, **kwargs):
        return {"version": self.version}
'''


def test_plugin_manager_runtime_routes_are_owned_by_hot_update_manager(
    tmp_path: Path,
) -> None:
    """PluginManager 不得再持有独立的热更新状态字典。"""
    manager = PluginManager(
        plugins_dir=str(tmp_path),
        hot_update_state_path=str(tmp_path / "hot-update-state.json"),
    )

    assert "_runtime_routes" not in manager.__dict__
    assert manager._runtime_routes is manager.hot_update_manager.runtime_routes


def test_plugin_manager_hot_update_delegates_state_transition() -> None:
    """PluginManager 不得直接改写 active/standby 状态。"""
    source = inspect.getsource(PluginManager.hot_update_plugin)

    assert "self.hot_update_manager.prepare_runtime_update(" in source
    assert 'route["slots"]["standby"] =' not in source
    assert 'route["slots"]["active"], route["slots"]["standby"]' not in source


def test_hot_update_state_persists_only_serializable_release_descriptors(
    tmp_path: Path,
) -> None:
    """持久化快照不得包含插件实例等运行时对象。"""
    state_path = tmp_path / "hot-update-state.json"
    manager = HotUpdateManager(state_path=state_path)
    manager.register_initial("plug", "1.0.0", {"path": "/v1"}, object())
    manager.prepare_update(
        "plug",
        "2.0.0",
        {"path": "/v2"},
        loader=object,
        rollout_config={
            "enabled": True,
            "strategy": "percentage",
            "percentage": 25,
        },
    )

    payload = json.loads(state_path.read_text(encoding="utf-8"))
    serialized = json.dumps(payload, ensure_ascii=False)
    restarted = HotUpdateManager(state_path=state_path)
    restored = restarted.get_persisted_runtime_route("plug")

    assert restored is not None
    assert restored["slots"]["active"]["metadata"]["path"] == "/v1"
    assert restored["slots"]["standby"]["metadata"]["path"] == "/v2"
    assert "plugin_instance" not in serialized
    assert "sandbox" not in serialized


def test_plugin_manager_recovers_standby_release_after_process_rebuild(
    tmp_path: Path,
) -> None:
    """新管理器实例应从持久化描述恢复灰度槽位和策略。"""
    plugin_path = tmp_path / "recovery_plugin.py"
    plugin_path.write_text(PLUGIN_SOURCE, encoding="utf-8")
    state_path = tmp_path / "hot-update-state.json"

    first = PluginManager(
        plugins_dir=str(tmp_path),
        hot_update_state_path=str(state_path),
    )
    first.discover_plugins()
    assert first.load_plugin("recovery_plugin")
    update = first.hot_update_plugin(
        "recovery_plugin",
        rollout_policy={
            "enabled": True,
            "rollout_percentage": 100,
            "targets": {"user_ids": ["alice"]},
        },
        strategy="gray",
    )
    assert update["success"] is True

    restarted = PluginManager(
        plugins_dir=str(tmp_path),
        hot_update_state_path=str(state_path),
    )
    restarted.discover_plugins()
    assert restarted.load_plugin("recovery_plugin")
    status = restarted.get_plugin_rollout_status("recovery_plugin")

    assert status["standby_release"] is not None
    assert status["rollout_policy"]["enabled"] is True
    assert status["rollout_policy"]["rollout_percentage"] == 100
    assert restarted._runtime_routes["recovery_plugin"]["slots"]["standby"][
        "plugin_instance"
    ].initialize_completed is True

    rollback = restarted.rollback_plugin("recovery_plugin")

    assert rollback["rolled_back_to"] == "1.0.0"
    assert restarted.loaded_plugins["recovery_plugin"].initialize_completed is True
