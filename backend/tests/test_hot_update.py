from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import pytest

from plugins.hot_update_manager import HotUpdateManager, RollbackManager, RolloutConfig
from plugins.plugin_manager import PluginManager


# ---------------------------------------------------------------------------
# RolloutConfig 测试
# ---------------------------------------------------------------------------

class TestRolloutConfig:
    def test_default_disabled(self):
        rc = RolloutConfig()
        assert rc.enabled is False
        assert rc.should_use_new_version(user_id="u1", region="cn") is False

    def test_percentage_strategy_above_threshold(self):
        rc = RolloutConfig({"enabled": True, "strategy": "percentage", "percentage": 100})
        assert rc.should_use_new_version(user_id="anyone", region="") is True

    def test_percentage_strategy_zero(self):
        rc = RolloutConfig({"enabled": True, "strategy": "percentage", "percentage": 0})
        assert rc.should_use_new_version(user_id="anyone", region="") is False

    def test_user_list_strategy_match(self):
        rc = RolloutConfig(
            {"enabled": True, "strategy": "user_list", "user_list": ["alice", "bob"]}
        )
        assert rc.should_use_new_version(user_id="alice") is True
        assert rc.should_use_new_version(user_id="charlie") is False

    def test_region_strategy_match(self):
        rc = RolloutConfig(
            {"enabled": True, "strategy": "region", "region": ["cn-north"]}
        )
        assert rc.should_use_new_version(region="cn-north") is True
        assert rc.should_use_new_version(region="us-east") is False

    def test_percentage_clamp(self):
        rc = RolloutConfig({"enabled": True, "strategy": "percentage", "percentage": 150})
        assert rc.percentage == 100.0

        rc2 = RolloutConfig({"enabled": True, "strategy": "percentage", "percentage": -10})
        assert rc2.percentage == 0.0

    def test_to_dict_roundtrip(self):
        data = {
            "enabled": True,
            "strategy": "user_list",
            "percentage": 50.0,
            "user_list": ["x"],
            "region": [],
        }
        rc = RolloutConfig(data)
        result = rc.to_dict()
        assert result["enabled"] is True
        assert result["strategy"] == "user_list"
        assert result["user_list"] == ["x"]

    def test_from_dict(self):
        rc = RolloutConfig.from_dict({"enabled": True, "strategy": "region", "region": ["eu"]})
        assert rc.strategy == "region"
        assert "eu" in rc.region

    def test_parse_string_list_single_string(self):
        rc = RolloutConfig({"enabled": True, "strategy": "user_list", "user_list": "alice"})
        assert rc.user_list == ["alice"]

    def test_invalid_percentage_type(self):
        rc = RolloutConfig({"enabled": True, "strategy": "percentage", "percentage": "bad"})
        assert rc.percentage == 0.0


# ---------------------------------------------------------------------------
# RollbackManager 测试
# ---------------------------------------------------------------------------

class TestRollbackManager:
    def test_save_and_restore_latest(self):
        mgr = RollbackManager()
        sid = mgr.save_snapshot("plug", "1.0.0", {"path": "/a"})
        snap = mgr.restore_snapshot("plug")
        assert snap is not None
        assert snap["version"] == "1.0.0"
        assert snap["snapshot_id"] == sid

    def test_restore_by_id(self):
        mgr = RollbackManager()
        sid1 = mgr.save_snapshot("plug", "1.0.0", {"path": "/a"})
        mgr.save_snapshot("plug", "2.0.0", {"path": "/b"})
        snap = mgr.restore_snapshot("plug", snapshot_id=sid1)
        assert snap is not None
        assert snap["version"] == "1.0.0"

    def test_restore_nonexistent_plugin(self):
        mgr = RollbackManager()
        assert mgr.restore_snapshot("no_such") is None

    def test_restore_nonexistent_snapshot_id(self):
        mgr = RollbackManager()
        mgr.save_snapshot("plug", "1.0.0", {})
        assert mgr.restore_snapshot("plug", snapshot_id="fake-id") is None

    def test_max_snapshots_eviction(self):
        mgr = RollbackManager()
        mgr.MAX_SNAPSHOTS = 3
        for i in range(5):
            mgr.save_snapshot("plug", f"{i}.0.0", {})
        snapshots = mgr.list_snapshots("plug")
        assert len(snapshots) == 3
        versions = [s["version"] for s in snapshots]
        assert "4.0.0" in versions
        assert "0.0.0" not in versions

    def test_list_snapshots_order(self):
        mgr = RollbackManager()
        mgr.save_snapshot("plug", "1.0.0", {})
        mgr.save_snapshot("plug", "2.0.0", {})
        snapshots = mgr.list_snapshots("plug")
        assert snapshots[0]["version"] == "2.0.0"

    def test_clear_snapshots(self):
        mgr = RollbackManager()
        mgr.save_snapshot("plug", "1.0.0", {})
        mgr.clear_snapshots("plug")
        assert mgr.list_snapshots("plug") == []

    def test_snapshot_deepcopy(self):
        mgr = RollbackManager()
        meta = {"path": "/original"}
        mgr.save_snapshot("plug", "1.0.0", meta)
        meta["path"] = "/modified"
        snap = mgr.restore_snapshot("plug")
        assert snap["metadata"]["path"] == "/original"


# ---------------------------------------------------------------------------
# HotUpdateManager 测试
# ---------------------------------------------------------------------------

class TestHotUpdateManager:
    def _make_instance(self, name: str = "plugin_a") -> object:
        class _FakePlugin:
            plugin_name = name
        return _FakePlugin()

    def test_register_initial(self):
        mgr = HotUpdateManager()
        inst = self._make_instance()
        mgr.register_initial("plug", "1.0.0", {"path": "/a"}, inst)
        status = mgr.get_status("plug")
        assert status["active"]["version"] == "1.0.0"
        assert status["standby"] is None

    def test_prepare_update_creates_standby(self):
        mgr = HotUpdateManager()
        inst_v1 = self._make_instance()
        inst_v2 = self._make_instance()
        mgr.register_initial("plug", "1.0.0", {"path": "/a"}, inst_v1)
        mgr.prepare_update(
            "plug",
            "2.0.0",
            {"path": "/b"},
            loader=lambda: inst_v2,
        )
        status = mgr.get_status("plug")
        assert status["active"]["version"] == "1.0.0"
        assert status["standby"]["version"] == "2.0.0"

    def test_commit_update_atomic_switch(self):
        mgr = HotUpdateManager()
        inst_v1 = self._make_instance()
        inst_v2 = self._make_instance()
        mgr.register_initial("plug", "1.0.0", {"path": "/a"}, inst_v1)
        mgr.prepare_update("plug", "2.0.0", {"path": "/b"}, loader=lambda: inst_v2)
        result = mgr.commit_update("plug")
        assert result["committed_version"] == "2.0.0"
        assert result["previous_version"] == "1.0.0"
        status = mgr.get_status("plug")
        assert status["active"]["version"] == "2.0.0"
        assert status["standby"] is None

    def test_commit_without_standby_raises(self):
        mgr = HotUpdateManager()
        mgr.register_initial("plug", "1.0.0", {}, self._make_instance())
        with pytest.raises(ValueError):
            mgr.commit_update("plug")

    def test_prepare_loader_failure_keeps_active(self):
        mgr = HotUpdateManager()
        mgr.register_initial("plug", "1.0.0", {"path": "/a"}, self._make_instance())

        def _bad_loader():
            raise RuntimeError("load failed")

        with pytest.raises(RuntimeError):
            mgr.prepare_update("plug", "2.0.0", {}, loader=_bad_loader)

        status = mgr.get_status("plug")
        assert status["active"]["version"] == "1.0.0"
        assert status["standby"] is None
        assert "load failed" in (status["last_error"] or "")

    def test_rollback_restores_active(self):
        mgr = HotUpdateManager()
        inst_v1 = self._make_instance()
        inst_v2 = self._make_instance()
        mgr.register_initial("plug", "1.0.0", {"path": "/a"}, inst_v1)
        mgr.prepare_update("plug", "2.0.0", {"path": "/b"}, loader=lambda: inst_v2)
        mgr.commit_update("plug")

        result = mgr.rollback("plug", restore_fn=lambda snap: self._make_instance())
        assert result["rolled_back_to"] == "1.0.0"
        status = mgr.get_status("plug")
        assert status["active"]["version"] == "1.0.0"

    def test_rollback_no_snapshot_raises(self):
        mgr = HotUpdateManager()
        with pytest.raises(ValueError):
            mgr.rollback("no_plug")

    def test_rollback_specific_snapshot(self):
        mgr = HotUpdateManager()
        inst = self._make_instance()
        mgr.register_initial("plug", "1.0.0", {"path": "/v1"}, inst)
        sid = mgr.rollback_manager.save_snapshot("plug", "0.9.0", {"path": "/v0"})
        result = mgr.rollback("plug", snapshot_id=sid, restore_fn=lambda _: self._make_instance())
        assert result["rolled_back_to"] == "0.9.0"

    def test_resolve_instance_no_rollout(self):
        mgr = HotUpdateManager()
        inst_v1 = self._make_instance()
        inst_v2 = self._make_instance()
        mgr.register_initial("plug", "1.0.0", {}, inst_v1)
        mgr.prepare_update("plug", "2.0.0", {}, loader=lambda: inst_v2)
        resolved = mgr.resolve_instance("plug", user_id="alice")
        assert resolved is inst_v1

    def test_resolve_instance_user_list_rollout(self):
        mgr = HotUpdateManager()
        inst_v1 = self._make_instance()
        inst_v2 = self._make_instance()
        mgr.register_initial("plug", "1.0.0", {}, inst_v1)
        mgr.prepare_update(
            "plug",
            "2.0.0",
            {},
            loader=lambda: inst_v2,
            rollout_config={"enabled": True, "strategy": "user_list", "user_list": ["alice"]},
        )
        assert mgr.resolve_instance("plug", user_id="alice") is inst_v2
        assert mgr.resolve_instance("plug", user_id="bob") is inst_v1

    def test_resolve_instance_region_rollout(self):
        mgr = HotUpdateManager()
        inst_v1 = self._make_instance()
        inst_v2 = self._make_instance()
        mgr.register_initial("plug", "1.0.0", {}, inst_v1)
        mgr.prepare_update(
            "plug",
            "2.0.0",
            {},
            loader=lambda: inst_v2,
            rollout_config={"enabled": True, "strategy": "region", "region": ["cn-north"]},
        )
        assert mgr.resolve_instance("plug", region="cn-north") is inst_v2
        assert mgr.resolve_instance("plug", region="us-east") is inst_v1

    def test_resolve_instance_percentage_100(self):
        mgr = HotUpdateManager()
        inst_v1 = self._make_instance()
        inst_v2 = self._make_instance()
        mgr.register_initial("plug", "1.0.0", {}, inst_v1)
        mgr.prepare_update(
            "plug",
            "2.0.0",
            {},
            loader=lambda: inst_v2,
            rollout_config={"enabled": True, "strategy": "percentage", "percentage": 100},
        )
        assert mgr.resolve_instance("plug", user_id="any") is inst_v2

    def test_get_status_unknown_plugin(self):
        mgr = HotUpdateManager()
        status = mgr.get_status("unknown")
        assert status["active"] is None
        assert status["standby"] is None

    def test_snapshots_shown_in_status(self):
        mgr = HotUpdateManager()
        mgr.register_initial("plug", "1.0.0", {"path": "/a"}, self._make_instance())
        status = mgr.get_status("plug")
        assert len(status["snapshots"]) >= 1


# ---------------------------------------------------------------------------
# PluginManager 集成测试（hot_update_plugin + rollback_plugin）
# ---------------------------------------------------------------------------

PLUGIN_V1 = '''from plugins.base_plugin import BasePlugin


class HotV1Plugin(BasePlugin):
    name = "hot_v1"
    version = "1.0.0"
    description = "hot update v1"

    def initialize(self):
        return True

    def execute(self, **kwargs):
        return {"version": "1.0.0"}
'''


@pytest.fixture
def hot_workspace(tmp_path: Path) -> Path:
    (tmp_path / "hot_v1.py").write_text(PLUGIN_V1, encoding="utf-8")
    return tmp_path


def test_plugin_manager_hot_update_gray(hot_workspace: Path):
    manager = PluginManager(plugins_dir=str(hot_workspace))
    manager.discover_plugins()
    assert manager.load_plugin("hot_v1")

    result = manager.hot_update_plugin(
        "hot_v1",
        rollout_policy={"enabled": False, "rollout_percentage": 0},
        strategy="gray",
    )
    assert result["success"] is True
    assert result["plugin_name"] == "hot_v1"
    assert result["strategy"] == "gray"


def test_plugin_manager_hot_update_immediate(hot_workspace: Path):
    manager = PluginManager(plugins_dir=str(hot_workspace))
    manager.discover_plugins()
    assert manager.load_plugin("hot_v1")

    result = manager.hot_update_plugin(
        "hot_v1",
        rollout_policy=None,
        strategy="immediate",
    )
    assert result["success"] is True
    assert result["rolled_back"] is False


def test_plugin_manager_hot_update_registers_snapshot(hot_workspace: Path):
    manager = PluginManager(plugins_dir=str(hot_workspace))
    manager.discover_plugins()
    manager.load_plugin("hot_v1")
    manager.hot_update_plugin("hot_v1", strategy="gray")
    snapshots = manager.rollback_manager.list_snapshots("hot_v1")
    assert len(snapshots) >= 1


def test_plugin_manager_rollback_after_hot_update(hot_workspace: Path):
    manager = PluginManager(plugins_dir=str(hot_workspace))
    manager.discover_plugins()
    manager.load_plugin("hot_v1")
    manager.hot_update_plugin("hot_v1", strategy="gray")
    result = manager.rollback_plugin("hot_v1")
    assert result["rolled_back_to"] is not None


def test_plugin_manager_rollback_not_found_raises(hot_workspace: Path):
    manager = PluginManager(plugins_dir=str(hot_workspace))
    with pytest.raises(ValueError):
        manager.rollback_plugin("nonexistent_plugin")


def test_hot_update_manager_initial_registered_after_load(hot_workspace: Path):
    manager = PluginManager(plugins_dir=str(hot_workspace))
    manager.discover_plugins()
    manager.load_plugin("hot_v1")
    status = manager.hot_update_manager.get_status("hot_v1")
    assert status["active"] is not None
    assert status["active"]["version"] == "1.0.0"
