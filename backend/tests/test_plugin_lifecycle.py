"""
后端测试模块，负责验证对应功能在正常、边界或异常场景下的行为是否符合预期。
保持测试注释清晰，有助于快速分辨各个用例所覆盖的场景。
"""

import io
import zipfile
from pathlib import Path

import pytest

from plugins.plugin_lifecycle import PluginState, PluginStateMachine, TransitionExecutor
from plugins.plugin_manager import PluginManager


@pytest.fixture
def plugin_workspace(tmp_path: Path) -> Path:
    """
    处理plugin、workspace相关逻辑，并为调用方返回对应结果。
    阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
    """
    success_plugin = '''from typing import Optional, Any
from plugins.base_plugin import BasePlugin


class TestPlugin(BasePlugin):
    name = "test_plugin"
    version = "1.0.0"
    description = "test plugin"
    enable_count: int = 0

    def __init__(self, config: Optional[Any] = None) -> None:
        super().__init__(config)

    def initialize(self) -> bool:
        return True

    def execute(self, **kwargs) -> dict:
        return kwargs

    def on_enabled(self) -> None:
        super().on_enabled()
        self.enable_count += 1
'''

    failing_enable_plugin = '''from typing import Optional, Any, List
from plugins.base_plugin import BasePlugin


class FailingEnablePlugin(BasePlugin):
    name = "failing_enable"
    version = "1.0.0"
    description = "failing enable plugin"
    rollback_events: List[str] = []

    def initialize(self) -> bool:
        return True

    def execute(self, **kwargs) -> dict:
        return kwargs

    def on_enabled(self) -> None:
        raise RuntimeError("enable failed")

    def rollback(self, previous_state: str, context: Optional[Any] = None) -> bool:
        self.__class__.rollback_events.append(previous_state)
        self._state = previous_state
        return True
'''

    permission_plugin = '''from plugins.base_plugin import BasePlugin
import requests


class PermissionPlugin(BasePlugin):
    name = "permission_plugin"
    version = "1.0.0"
    description = "permission plugin"

    def initialize(self):
        return True

    def execute(self, **kwargs):
        return requests.__name__
'''

    (tmp_path / "test_plugin.py").write_text(success_plugin, encoding="utf-8")
    (tmp_path / "failing_enable.py").write_text(failing_enable_plugin, encoding="utf-8")
    (tmp_path / "permission_plugin.py").write_text(permission_plugin, encoding="utf-8")
    return tmp_path


def _create_plugin_zip_bytes(plugin_name: str = "zip_plugin") -> bytes:
    """
    处理create、plugin、zip、bytes相关逻辑，并为调用方返回对应结果。
    阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
    """
    plugin_content = f'''from plugins.base_plugin import BasePlugin


class ZipPlugin(BasePlugin):
    name = "{plugin_name}"
    version = "1.0.0"
    description = "zip plugin"

    def initialize(self):
        return True

    def execute(self, **kwargs):
        return kwargs
'''

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(f"{plugin_name}.py", plugin_content)
    return buffer.getvalue()


def test_plugin_manager_state_machine_and_idempotent_enable(plugin_workspace: Path):
    """
    验证plugin、manager、state、machine、and、idempotent、enable相关场景的行为是否符合预期。
    通过断言结果可以帮助定位实现与预期行为之间的偏差。
    """
    manager = PluginManager(plugins_dir=str(plugin_workspace))
    manager.discover_plugins()

    assert manager.load_plugin("test_plugin") is True
    assert manager.state_machine.get_state("test_plugin") == PluginState.ENABLED

    plugin_instance = manager.loaded_plugins["test_plugin"]
    assert plugin_instance.enable_count == 1

    assert manager.enable_plugin("test_plugin") is True
    assert plugin_instance.enable_count == 1

    info = manager.get_plugin_info("test_plugin")
    assert info is not None
    assert info["state"] == PluginState.ENABLED.value

    assert manager.disable_plugin("test_plugin") is True
    assert manager.state_machine.get_state("test_plugin") == PluginState.DISABLED

    assert manager.unload_plugin("test_plugin") is True
    assert manager.state_machine.get_state("test_plugin") == PluginState.UNLOADED


def test_plugin_manager_rollback_when_enable_fails(plugin_workspace: Path):
    """
    验证plugin、manager、rollback、when、enable、fails相关场景的行为是否符合预期。
    通过断言结果可以帮助定位实现与预期行为之间的偏差。
    """
    manager = PluginManager(plugins_dir=str(plugin_workspace))
    manager.discover_plugins()

    assert manager.load_plugin("failing_enable") is False
    assert manager.state_machine.get_state("failing_enable") == PluginState.UNLOADED
    assert "failing_enable" not in manager.loaded_plugins

    plugin_class = manager.loader.loaded_plugins["failing_enable"]
    assert plugin_class.rollback_events[-1] == PluginState.LOADED.value


def test_transition_executor_rejects_invalid_transition():
    """
    验证transition、executor、rejects、invalid、transition相关场景的行为是否符合预期。
    通过断言结果可以帮助定位实现与预期行为之间的偏差。
    """
    state_machine = PluginStateMachine()
    executor = TransitionExecutor(state_machine)

    result = executor.execute(
        plugin_name="demo",
        plugin_instance=None,
        to_state=PluginState.ENABLED,
        action=None,
        rollback_action=None,
        idempotency_key="demo:invalid",
    )

    assert result.success is False
    assert "Invalid transition" in result.error
    assert state_machine.get_state("demo") == PluginState.REGISTERED


def test_register_plugin_from_local_zip_and_bind_resource_limits(tmp_path: Path):
    """
    验证register、plugin、from、local、zip、and、bind、resource、limits相关场景的行为是否符合预期。
    通过断言结果可以帮助定位实现与预期行为之间的偏差。
    """
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir(parents=True, exist_ok=True)

    zip_path = tmp_path / "plugin_bundle.zip"
    zip_path.write_bytes(_create_plugin_zip_bytes())

    manager = PluginManager(plugins_dir=str(plugins_dir))
    discovered = manager.register_plugin_from_local_zip(
        str(zip_path),
        resource_limits={"timeout": 5, "memory_limit": "128m", "cpu_limit": 0.5},
    )

    assert len(discovered) == 1
    assert discovered[0]["name"] == "zip_plugin"
    assert discovered[0]["source"] == "local_zip"

    assert manager.load_plugin("zip_plugin") is True

    sandbox = manager._plugin_sandboxes["zip_plugin"]
    assert sandbox.timeout == 5
    assert sandbox.memory_limit == "128m"
    assert sandbox.cpu_limit == 0.5


def test_register_plugin_from_url(monkeypatch, tmp_path: Path):
    """
    验证register、plugin、from、url相关场景的行为是否符合预期。
    通过断言结果可以帮助定位实现与预期行为之间的偏差。
    """
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir(parents=True, exist_ok=True)

    zip_bytes = _create_plugin_zip_bytes("url_plugin")

    class FakeResponse:
        """
        封装与FakeResponse相关的核心逻辑与运行状态。
        该类通常是当前文件中组织数据与调度行为的主要封装单元。
        """
        is_redirect = False
        status_code = 200
        headers = {"content-type": "application/zip"}

        def __init__(self, content: bytes):
            """
            处理init相关逻辑，并为调用方返回对应结果。
            阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
            """
            self.content = content

        def raise_for_status(self):
            """
            处理raise、for、status相关逻辑，并为调用方返回对应结果。
            阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
            """
            return None

    def fake_get(url: str, timeout: int, follow_redirects: bool, headers=None):
        """
        处理fake、get相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        assert url == "https://github.com/plugin.zip"
        assert timeout == 30
        assert follow_redirects is False
        return FakeResponse(zip_bytes)

    monkeypatch.setattr("plugins.plugin_manager.httpx.get", fake_get)

    manager = PluginManager(plugins_dir=str(plugins_dir))
    # 测试环境跳过 SSRF 安全校验（DNS 解析可能指向内网代理地址）
    monkeypatch.setattr(manager, "_validate_remote_url", lambda url: None)
    discovered = manager.register_plugin_from_url("https://github.com/plugin.zip")

    assert len(discovered) == 1
    assert discovered[0]["name"] == "url_plugin"
    assert discovered[0]["source"] == "remote_url"


def test_parse_npm_source_and_validate():
    """
    验证parse、npm、source、and、validate相关场景的行为是否符合预期。
    通过断言结果可以帮助定位实现与预期行为之间的偏差。
    """
    manager = PluginManager()

    parsed = manager.parse_npm_source("npm:@openawa/sample-plugin@1.2.3")
    assert parsed["source"] == "npm"
    assert parsed["package_name"] == "@openawa/sample-plugin"
    assert parsed["version"] == "1.2.3"
    assert parsed["tarball_url"] == "https://registry.npmjs.org/@openawa%2fsample-plugin/-/sample-plugin-1.2.3.tgz"

    with pytest.raises(ValueError):
        manager.parse_npm_source("npm:@invalid scope/pkg@1.0.0")

    with pytest.raises(ValueError):
        manager.parse_npm_source("npm:@openawa/sample-plugin@latest")


@pytest.fixture
def dependency_workspace(tmp_path: Path) -> Path:
    """
    处理dependency、workspace相关逻辑，并为调用方返回对应结果。
    阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
    """
    plugin_a = '''from plugins.base_plugin import BasePlugin


class PluginA(BasePlugin):
    name = "plugin_a"
    version = "1.0.0"
    description = "plugin a"
    manifest = {
        "name": "plugin_a",
        "version": "1.0.0",
        "pluginApiVersion": "1.0.0",
        "extensions": [{"point": "tool", "name": "tool_a", "version": "1.0.0", "config": {}}],
        "dependencies": {
            "requests": "^2.28.0",
            "httpx": "^0.23.0"
        },
        "pluginDependencies": {
            "plugin_b": "^2.0.0",
            "plugin_missing": "^1.0.0"
        }
    }

    def initialize(self):
        return True

    def execute(self, **kwargs):
        return kwargs
'''

    plugin_b = '''from plugins.base_plugin import BasePlugin


class PluginB(BasePlugin):
    name = "plugin_b"
    version = "2.1.0"
    description = "plugin b"
    manifest = {
        "name": "plugin_b",
        "version": "2.1.0",
        "pluginApiVersion": "1.0.0",
        "extensions": [{"point": "tool", "name": "tool_b", "version": "1.0.0", "config": {}}],
        "dependencies": {
            "requests": "<2.0.0"
        },
        "pluginDependencies": {
            "plugin_c": "^1.0.0"
        }
    }

    def initialize(self):
        return True

    def execute(self, **kwargs):
        return kwargs
'''

    plugin_c = '''from plugins.base_plugin import BasePlugin


class PluginC(BasePlugin):
    name = "plugin_c"
    version = "1.2.0"
    description = "plugin c"
    manifest = {
        "name": "plugin_c",
        "version": "1.2.0",
        "pluginApiVersion": "1.0.0",
        "extensions": [{"point": "tool", "name": "tool_c", "version": "1.0.0", "config": {}}],
        "dependencies": {
            "httpx": "~0.23.0"
        },
        "pluginDependencies": {
            "plugin_a": "^1.0.0"
        }
    }

    def initialize(self):
        return True

    def execute(self, **kwargs):
        return kwargs
'''

    plugin_d = '''from plugins.base_plugin import BasePlugin


class PluginD(BasePlugin):
    name = "plugin_d"
    version = "1.0.0"
    description = "plugin d"
    manifest = {
        "name": "plugin_d",
        "version": "1.0.0",
        "pluginApiVersion": "1.0.0",
        "extensions": [{"point": "tool", "name": "tool_d", "version": "1.0.0", "config": {}}],
        "pluginDependencies": {
            "plugin_b": "^3.0.0"
        }
    }

    def initialize(self):
        return True

    def execute(self, **kwargs):
        return kwargs
'''

    (tmp_path / "plugin_a.py").write_text(plugin_a, encoding="utf-8")
    (tmp_path / "plugin_b.py").write_text(plugin_b, encoding="utf-8")
    (tmp_path / "plugin_c.py").write_text(plugin_c, encoding="utf-8")
    (tmp_path / "plugin_d.py").write_text(plugin_d, encoding="utf-8")
    return tmp_path


def test_semver_range_parser_and_compatibility():
    """
    验证semver、range、parser、and、compatibility相关场景的行为是否符合预期。
    通过断言结果可以帮助定位实现与预期行为之间的偏差。
    """
    manager = PluginManager()

    assert manager._satisfies_semver_range("2.1.0", "^2.0.0") is True
    assert manager._satisfies_semver_range("2.1.0", "~2.1.0") is True
    assert manager._satisfies_semver_range("2.2.0", "~2.1.0") is False
    assert manager._satisfies_semver_range("1.5.0", "1.x") is True

    assert manager._ranges_compatible("^2.0.0", ">=2.1.0 <3.0.0") is True
    assert manager._ranges_compatible("^2.0.0", "<2.0.0") is False


def test_dependency_graph_and_conflict_diagnostics(dependency_workspace: Path):
    """
    验证dependency、graph、and、conflict、diagnostics相关场景的行为是否符合预期。
    通过断言结果可以帮助定位实现与预期行为之间的偏差。
    """
    manager = PluginManager(plugins_dir=str(dependency_workspace))
    discovered = manager.discover_plugins()
    assert len(discovered) == 4

    diagnostics = manager.get_dependency_diagnostics()
    graph = diagnostics["graph"]
    analysis = diagnostics["analysis"]

    assert len(graph["nodes"]) == 4
    assert any(edge["status"] == "missing" and edge["to"] == "plugin_missing" for edge in graph["edges"])
    assert any(
        edge["status"] == "version_mismatch"
        and edge["from"] == "plugin_d"
        and edge["to"] == "plugin_b"
        for edge in graph["edges"]
    )

    assert analysis["has_conflicts"] is True
    assert any(issue["type"] == "missing_plugin" for issue in analysis["plugin_dependency_issues"])
    assert any(issue["type"] == "plugin_version_mismatch" for issue in analysis["plugin_dependency_issues"])

    requests_conflict = next(
        item for item in analysis["external_dependency_conflicts"] if item["package"] == "requests"
    )
    assert len(requests_conflict["pairwise_conflicts"]) >= 1

    assert any(set(cycle[:-1]) == {"plugin_a", "plugin_b", "plugin_c"} for cycle in analysis["cycles"])

    suggestion_types = {item["type"] for item in analysis["suggestions"]}
    assert "install_plugin_dependency" in suggestion_types
    assert "align_plugin_dependency_version" in suggestion_types
    assert "align_external_dependency_range" in suggestion_types
    assert "break_dependency_cycle" in suggestion_types


def test_get_plugin_dependency_info(dependency_workspace: Path):
    """
    验证get、plugin、dependency、info相关场景的行为是否符合预期。
    通过断言结果可以帮助定位实现与预期行为之间的偏差。
    """
    manager = PluginManager(plugins_dir=str(dependency_workspace))
    manager.discover_plugins()

    info = manager.get_plugin_dependency_info("plugin_a")
    assert info is not None
    assert info["plugin"] == "plugin_a"
    assert info["plugin_dependencies"]["plugin_b"] == "^2.0.0"
    assert any(edge["to"] == "plugin_b" for edge in info["resolved"])

    assert manager.get_plugin_dependency_info("not_exists") is None


def test_runtime_permission_intercept_and_authorize(plugin_workspace: Path):
    """
    验证runtime、permission、intercept、and、authorize相关场景的行为是否符合预期。
    通过断言结果可以帮助定位实现与预期行为之间的偏差。
    """
    manager = PluginManager(plugins_dir=str(plugin_workspace))
    discovered = manager.discover_plugins()

    assert any(item["name"] == "permission_plugin" for item in discovered)

    info = manager.get_plugin_info("permission_plugin")
    assert info is not None
    assert "network:http" in info["requested_permissions"]

    assert manager.load_plugin("permission_plugin") is True

    denied_result = manager.execute_plugin("permission_plugin", "execute")
    assert denied_result["status"] == "permission_required"
    assert "network:http" in denied_result["required_permissions"]

    status = manager.authorize_plugin_permissions("permission_plugin", ["network:http"])
    assert "network:http" in status["granted_permissions"]
    assert status["missing_permissions"] == []

    success_result = manager.execute_plugin("permission_plugin", "execute")
    assert success_result["status"] == "success"

    revoked = manager.revoke_plugin_permissions("permission_plugin", ["network:http"])
    assert "network:http" not in revoked["granted_permissions"]
    assert "network:http" in revoked["missing_permissions"]

    denied_after_revoke = manager.execute_plugin("permission_plugin", "execute")
    assert denied_after_revoke["status"] == "permission_required"


def test_static_scan_blocks_dangerous_plugin(tmp_path: Path):
    """
    验证static、scan、blocks、dangerous、plugin相关场景的行为是否符合预期。
    通过断言结果可以帮助定位实现与预期行为之间的偏差。
    """
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir(parents=True, exist_ok=True)

    dangerous_plugin = '''from plugins.base_plugin import BasePlugin
import subprocess


class DangerousPlugin(BasePlugin):
    name = "dangerous_plugin"
    version = "1.0.0"

    def initialize(self):
        return True

    def execute(self, **kwargs):
        return subprocess.run(["echo", "danger"], capture_output=True)
'''

    safe_plugin = '''from plugins.base_plugin import BasePlugin


class SafePlugin(BasePlugin):
    name = "safe_plugin"
    version = "1.0.0"

    def initialize(self):
        return True

    def execute(self, **kwargs):
        return "ok"
'''

    (plugins_dir / "dangerous_plugin.py").write_text(dangerous_plugin, encoding="utf-8")
    (plugins_dir / "safe_plugin.py").write_text(safe_plugin, encoding="utf-8")

    manager = PluginManager(plugins_dir=str(plugins_dir))
    discovered = manager.discover_plugins()

    names = {item["name"] for item in discovered}
    assert "safe_plugin" in names
    assert "dangerous_plugin" not in names
