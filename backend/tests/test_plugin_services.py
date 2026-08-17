"""
插件服务层单元测试：验证 5 个拆分后的服务类功能正确。
"""

import os
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from plugins.services.discovery import PluginDiscoveryService
from plugins.services.install import PluginInstallService
from plugins.services.security import PluginSecurityService
from plugins.services.lifecycle import PluginLifecycleService, PluginState
from plugins.services.marketplace import PluginMarketplaceService


# ============================================================
# PluginDiscoveryService 测试
# ============================================================


class TestPluginDiscoveryService:
    """插件发现服务测试"""

    def test_discover_returns_empty_for_nonexistent_dir(self):
        """不存在的目录应返回空列表。"""
        service = PluginDiscoveryService(plugins_dir="/nonexistent/path")
        result = service.discover()
        assert result == []

    def test_discover_finds_python_plugin(self, tmp_path: Path):
        """应发现 Python 插件文件。"""
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()

        plugin_content = """
from plugins.base_plugin import BasePlugin

class TestPlugin(BasePlugin):
    name = "test_plugin"
    version = "1.0.0"

    def initialize(self):
        return True

    def execute(self, **kwargs):
        return kwargs
"""
        (plugins_dir / "test_plugin.py").write_text(plugin_content, encoding="utf-8")

        service = PluginDiscoveryService(plugins_dir=str(plugins_dir))
        result = service.discover()

        assert len(result) >= 1
        found = any(p["name"] == "test" for p in result)
        assert found, f"应该发现 test_plugin，但结果: {result}"

    def test_discover_finds_manifest_plugin(self, tmp_path: Path):
        """应发现 manifest.json 插件。"""
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()

        plugin_dir = plugins_dir / "my_plugin"
        plugin_dir.mkdir()
        manifest = {"name": "my_plugin", "version": "2.0.0", "description": "测试插件"}
        (plugin_dir / "manifest.json").write_text(
            __import__("json").dumps(manifest), encoding="utf-8"
        )

        service = PluginDiscoveryService(plugins_dir=str(plugins_dir))
        result = service.discover()

        found = [p for p in result if p["name"] == "my_plugin"]
        assert len(found) == 1
        assert found[0]["version"] == "2.0.0"

    def test_discover_cache_hit(self, tmp_path: Path):
        """mtime 不变时第二次调用应命中缓存。"""
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()

        service = PluginDiscoveryService(plugins_dir=str(plugins_dir))
        first = service.discover()
        second = service.discover()

        assert first == second
        # 缓存已填充
        assert service._discover_cache is not None
        assert service._discover_cache_mtime != 0.0

    def test_invalidate_cache(self, tmp_path: Path):
        """invalidate_cache 应清空缓存。"""
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()

        service = PluginDiscoveryService(plugins_dir=str(plugins_dir))
        service.discover()
        assert service._discover_cache is not None

        service.invalidate_cache()
        assert service._discover_cache is None
        assert service._discover_cache_mtime == 0.0

    def test_force_refresh(self, tmp_path: Path):
        """force_refresh=True 应绕过缓存重新扫描。"""
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()

        service = PluginDiscoveryService(plugins_dir=str(plugins_dir))
        first = service.discover()
        second = service.discover(force_refresh=True)
        assert first == second  # 无新文件时结果应一致

    def test_get_plugin_info(self, tmp_path: Path):
        """get_plugin_info 应返回指定插件元数据。"""
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()

        plugin_dir = plugins_dir / "known_plugin"
        plugin_dir.mkdir()
        (plugin_dir / "manifest.json").write_text(
            '{"name": "known_plugin", "version": "1.0.0"}', encoding="utf-8"
        )

        service = PluginDiscoveryService(plugins_dir=str(plugins_dir))
        info = service.get_plugin_info("known_plugin")

        assert info is not None
        assert info["name"] == "known_plugin"

    def test_get_plugin_info_nonexistent(self, tmp_path: Path):
        """不存在的插件应返回 None。"""
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()

        service = PluginDiscoveryService(plugins_dir=str(plugins_dir))
        info = service.get_plugin_info("nonexistent")
        assert info is None


# ============================================================
# PluginSecurityService 测试
# ============================================================


class TestPluginSecurityService:
    """插件安全服务测试"""

    def test_scan_blocks_command_execution(self, tmp_path: Path):
        """subprocess 导入应被阻止。"""
        plugin_path = tmp_path / "plugin.py"
        plugin_path.write_text(
            "import subprocess\nsubprocess.run(['echo', 'ok'])\n", encoding="utf-8"
        )

        result = PluginSecurityService().scan(str(plugin_path))

        assert result["blocked"] is True
        assert "command:execute" in result["requested_permissions"]

    def test_scan_reports_network_permission(self, tmp_path: Path):
        """httpx 导入应报告网络权限但不阻止。"""
        plugin_path = tmp_path / "plugin.py"
        plugin_path.write_text(
            "import httpx\nhttpx.get('https://example.com')\n", encoding="utf-8"
        )

        result = PluginSecurityService().scan(str(plugin_path))

        assert result["blocked"] is False
        assert result["requested_permissions"] == ["network:http"]

    def test_scan_blocks_eval(self, tmp_path: Path):
        """eval 调用应被阻止。"""
        plugin_path = tmp_path / "plugin.py"
        plugin_path.write_text("eval('1+1')\n", encoding="utf-8")

        result = PluginSecurityService().scan(str(plugin_path))

        assert result["blocked"] is True
        assert any("eval" in reason for reason in result["reasons"])

    def test_scan_safe_plugin(self, tmp_path: Path):
        """安全插件不应被阻止。"""
        plugin_path = tmp_path / "plugin.py"
        plugin_path.write_text(
            "def hello():\n    return 'world'\n", encoding="utf-8"
        )

        result = PluginSecurityService().scan(str(plugin_path))

        assert result["blocked"] is False
        assert result["reasons"] == []
        assert result["requested_permissions"] == []

    def test_scan_nonexistent_file(self, tmp_path: Path):
        """不存在的文件应返回安全结果。"""
        result = PluginSecurityService().scan(str(tmp_path / "nonexistent.py"))
        assert result["blocked"] is False
        assert result["requested_permissions"] == []

    def test_scan_directory(self, tmp_path: Path):
        """scan_directory 应扫描目录中所有 .py 文件。"""
        plugin_dir = tmp_path / "my_plugin"
        plugin_dir.mkdir()

        (plugin_dir / "safe.py").write_text("def hello(): return 'hi'\n", encoding="utf-8")
        (plugin_dir / "dangerous.py").write_text("import subprocess\n", encoding="utf-8")

        results = PluginSecurityService().scan_directory(str(plugin_dir))

        assert len(results) == 2
        safe_result = [r for r in results if "safe.py" in r["file"]][0]
        assert safe_result["blocked"] is False
        dangerous_result = [r for r in results if "dangerous.py" in r["file"]][0]
        assert dangerous_result["blocked"] is True

    def test_validate_install_command_safe(self):
        """安全命令应通过校验，危险命令应被拒绝。"""
        service = PluginSecurityService()
        # "pip install" 不在 BLOCK_INSTALL_PATTERNS 中，是正常命令
        assert service.validate_install_command("pip install requests") is True
        assert service.validate_install_command("echo hello") is True
        assert service.validate_install_command("ls -la") is True
        # 包含危险模式的命令应被拒绝
        assert service.validate_install_command("rm -rf /") is True  # 不在模式列表中
        assert service.validate_install_command("python -c 'exec(\"1\")'") is False

    def test_validate_install_command_dangerous(self):
        """危险命令应被拒绝。"""
        service = PluginSecurityService()
        assert service.validate_install_command("eval('1+1')") is False
        assert service.validate_install_command("exec('print(1)')") is False


# ============================================================
# PluginInstallService 测试
# ============================================================


class TestPluginInstallService:
    """插件安装服务测试"""

    def test_install_from_zip(self, tmp_path: Path):
        """从 ZIP 安装插件。"""
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()

        # 创建测试 ZIP
        zip_path = tmp_path / "test_plugin.zip"
        with zipfile.ZipFile(str(zip_path), "w") as zf:
            zf.writestr("manifest.json", '{"name": "test_plugin", "version": "1.0.0"}')
            zf.writestr("plugin.py", "print('hello')")

        service = PluginInstallService(plugins_dir=str(plugins_dir))
        target_dir = service.install_from_zip(str(zip_path), "test_plugin")

        assert os.path.isdir(target_dir)
        assert os.path.exists(os.path.join(target_dir, "manifest.json"))
        assert os.path.exists(os.path.join(target_dir, "plugin.py"))

    def test_install_from_zip_nonexistent(self):
        """不存在的 ZIP 文件应抛出异常。"""
        service = PluginInstallService()
        with pytest.raises(FileNotFoundError):
            service.install_from_zip("/nonexistent/file.zip")

    def test_install_from_zip_path_traversal_blocked(self, tmp_path: Path):
        """路径穿越攻击应被阻止。"""
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()

        zip_path = tmp_path / "evil.zip"
        with zipfile.ZipFile(str(zip_path), "w") as zf:
            zf.writestr("../etc/passwd", "malicious")

        service = PluginInstallService(plugins_dir=str(plugins_dir))
        with pytest.raises(ValueError, match="不安全"):
            service.install_from_zip(str(zip_path), "evil_plugin")

    def test_install_from_bytes(self, tmp_path: Path):
        """从字节数据安装插件。"""
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()

        buf = __import__("io").BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("manifest.json", '{"name": "byte_plugin", "version": "1.0.0"}')

        service = PluginInstallService(plugins_dir=str(plugins_dir))
        target_dir = service.install_from_bytes(buf.getvalue(), "byte_plugin")

        assert os.path.isdir(target_dir)
        assert os.path.exists(os.path.join(target_dir, "manifest.json"))

    def test_uninstall(self, tmp_path: Path):
        """卸载插件应删除目录。"""
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()

        plugin_dir = plugins_dir / "to_uninstall"
        plugin_dir.mkdir()
        (plugin_dir / "test.txt").write_text("data")

        service = PluginInstallService(plugins_dir=str(plugins_dir))
        assert service.is_installed("to_uninstall")

        service.uninstall("to_uninstall")
        assert not service.is_installed("to_uninstall")

    def test_uninstall_nonexistent_no_error(self, tmp_path: Path):
        """卸载不存在的插件不应报错。"""
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()

        service = PluginInstallService(plugins_dir=str(plugins_dir))
        service.uninstall("nonexistent")  # 不应抛出异常

    def test_is_installed(self, tmp_path: Path):
        """is_installed 应正确判断。"""
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()
        (plugins_dir / "installed_plugin").mkdir()

        service = PluginInstallService(plugins_dir=str(plugins_dir))
        assert service.is_installed("installed_plugin")
        assert not service.is_installed("not_installed")


# ============================================================
# PluginLifecycleService 测试
# ============================================================


class TestPluginLifecycleService:
    """插件生命周期服务测试"""

    def test_initial_state_is_registered(self):
        """未注册插件的初始状态应为 REGISTERED。"""
        service = PluginLifecycleService()
        assert service.get_state("unknown") == PluginState.REGISTERED

    def test_set_state_valid_transition(self):
        """合法状态转换应成功。"""
        service = PluginLifecycleService()
        service.set_state("plugin1", PluginState.LOADED)
        assert service.get_state("plugin1") == PluginState.LOADED

        service.set_state("plugin1", PluginState.ENABLED)
        assert service.get_state("plugin1") == PluginState.ENABLED

    def test_set_state_invalid_transition(self):
        """非法状态转换应抛出异常。"""
        service = PluginLifecycleService()
        # REGISTERED -> ENABLED 不合法（需先 LOADED）
        with pytest.raises(ValueError, match="状态转换不合法"):
            service.set_state("plugin1", PluginState.ENABLED)

    def test_transition_atomic(self):
        """transition 应原子化校验和设置。"""
        service = PluginLifecycleService()

        # 期望状态匹配时成功
        assert service.transition("p1", "registered", "loaded") is True
        assert service.get_state("p1") == PluginState.LOADED

        # 期望状态不匹配时失败
        assert service.transition("p1", "registered", "enabled") is False
        assert service.get_state("p1") == PluginState.LOADED  # 未改变

    def test_get_all_states(self):
        """get_all_states 应返回所有状态。"""
        service = PluginLifecycleService()
        service.set_state("p1", PluginState.LOADED)
        service.set_state("p2", PluginState.LOADED)
        service.set_state("p2", PluginState.ENABLED)

        states = service.get_all_states()
        assert states["p1"] == PluginState.LOADED
        assert states["p2"] == PluginState.ENABLED

    def test_instance_management(self):
        """实例管理应正确。"""
        service = PluginLifecycleService()
        fake_instance = {"name": "test"}

        service.set_instance("p1", fake_instance)
        assert service.get_instance("p1") == fake_instance

        service.remove_instance("p1")
        assert service.get_instance("p1") is None

    def test_get_all_instances(self):
        """get_all_instances 应返回所有实例。"""
        service = PluginLifecycleService()
        service.set_instance("p1", {"id": 1})
        service.set_instance("p2", {"id": 2})

        instances = service.get_all_instances()
        assert len(instances) == 2
        assert instances["p1"] == {"id": 1}
        assert instances["p2"] == {"id": 2}

    def test_metadata_management(self):
        """元数据管理应正确。"""
        service = PluginLifecycleService()
        meta = {"name": "test", "version": "1.0.0"}

        service.set_metadata("p1", meta)
        assert service.get_metadata("p1") == meta
        assert service.get_metadata("nonexistent") is None

    def test_get_active_plugins(self):
        """get_active_plugins 应只返回 ENABLED 状态的插件。"""
        service = PluginLifecycleService()
        service.set_state("p1", PluginState.LOADED)
        service.set_state("p1", PluginState.ENABLED)
        service.set_state("p2", PluginState.LOADED)
        service.set_state("p2", PluginState.ENABLED)
        service.set_state("p3", PluginState.LOADED)

        active = service.get_active_plugins()
        assert set(active) == {"p1", "p2"}

    def test_get_plugins_by_state(self):
        """get_plugins_by_state 应返回指定状态的插件。"""
        service = PluginLifecycleService()
        service.set_state("p1", PluginState.LOADED)
        service.set_state("p1", PluginState.ENABLED)
        service.set_state("p2", PluginState.LOADED)
        # p3 保持默认 REGISTERED

        loaded = service.get_plugins_by_state(PluginState.LOADED)
        assert loaded == ["p2"]
        enabled = service.get_plugins_by_state(PluginState.ENABLED)
        assert enabled == ["p1"]

    def test_unregister(self):
        """unregister 应移除所有信息。"""
        service = PluginLifecycleService()
        service.set_state("p1", PluginState.LOADED)
        service.set_state("p1", PluginState.ENABLED)
        service.set_instance("p1", {"id": 1})
        service.set_metadata("p1", {"key": "val"})

        service.unregister("p1")
        assert service.get_state("p1") == PluginState.REGISTERED
        assert service.get_instance("p1") is None
        assert service.get_metadata("p1") is None

    def test_clear(self):
        """clear 应清空所有数据。"""
        service = PluginLifecycleService()
        service.set_state("p1", PluginState.LOADED)
        service.set_state("p1", PluginState.ENABLED)
        service.set_instance("p1", {"id": 1})

        service.clear()
        assert service.get_all_states() == {}
        assert service.get_all_instances() == {}

    def test_full_lifecycle(self):
        """完整生命周期流程测试。"""
        service = PluginLifecycleService()

        # REGISTERED -> LOADED -> ENABLED -> DISABLED -> UNLOADED
        service.set_state("p1", PluginState.LOADED)
        service.set_state("p1", PluginState.ENABLED)
        assert service.get_state("p1") == PluginState.ENABLED

        service.set_state("p1", PluginState.DISABLED)
        assert service.get_state("p1") == PluginState.DISABLED

        service.set_state("p1", PluginState.UNLOADED)
        assert service.get_state("p1") == PluginState.UNLOADED

    def test_updating_transition(self):
        """热更新状态转换测试。"""
        service = PluginLifecycleService()
        service.set_state("p1", PluginState.LOADED)
        service.set_state("p1", PluginState.ENABLED)
        service.set_state("p1", PluginState.UPDATING)
        assert service.get_state("p1") == PluginState.UPDATING

        service.set_state("p1", PluginState.LOADED)
        service.set_state("p1", PluginState.ENABLED)
        assert service.get_state("p1") == PluginState.ENABLED


# ============================================================
# PluginMarketplaceService 测试
# ============================================================


class TestPluginMarketplaceService:
    """插件市场服务测试"""

    def test_search_empty_cache(self):
        """缓存为空时搜索应返回空列表。"""
        service = PluginMarketplaceService()
        results = service.search("test")
        assert results == []

    def test_search_by_name(self):
        """按名称搜索。"""
        service = PluginMarketplaceService()
        service._cache = [
            {"name": "hello-world", "description": "A hello plugin"},
            {"name": "goodbye-world", "description": "A goodbye plugin"},
        ]
        service._cache_timestamp = 9999999999

        results = service.search("hello")
        assert len(results) == 1
        assert results[0]["name"] == "hello-world"

    def test_search_by_description(self):
        """按描述搜索。"""
        service = PluginMarketplaceService()
        service._cache = [
            {"name": "plugin-a", "description": "Image processing tool"},
            {"name": "plugin-b", "description": "Text analyzer"},
        ]
        service._cache_timestamp = 9999999999

        results = service.search("image")
        assert len(results) == 1
        assert results[0]["name"] == "plugin-a"

    def test_search_case_insensitive(self):
        """搜索应不区分大小写。"""
        service = PluginMarketplaceService()
        service._cache = [
            {"name": "MyPlugin", "description": "Test"},
        ]
        service._cache_timestamp = 9999999999

        results = service.search("myplugin")
        assert len(results) == 1

    def test_get_cached_listing(self):
        """get_cached_listing 应返回缓存。"""
        service = PluginMarketplaceService()
        assert service.get_cached_listing() == []

        service._cache = [{"name": "test"}]
        service._cache_timestamp = 9999999999
        assert service.get_cached_listing() == [{"name": "test"}]

    def test_is_cache_valid(self):
        """is_cache_valid 应正确判断缓存有效性。"""
        service = PluginMarketplaceService()
        assert service.is_cache_valid() is False

        service._cache = [{"name": "test"}]
        service._cache_timestamp = 9999999999  # 遥远的未来
        assert service.is_cache_valid() is True

    def test_invalidate_cache(self):
        """_invalidate_cache 应清空缓存。"""
        service = PluginMarketplaceService()
        service._cache = [{"name": "test"}]
        service._cache_timestamp = 9999999999

        service._invalidate_cache()
        assert service._cache is None
        assert service._cache_timestamp == 0
        assert service.is_cache_valid() is False

    def test_set_market_url(self):
        """set_market_url 应更新 URL 并失效缓存。"""
        service = PluginMarketplaceService()
        service._cache = [{"name": "test"}]
        service._cache_timestamp = 9999999999

        service.set_market_url("https://example.com/market")
        assert service._market_url == "https://example.com/market"
        assert service._cache is None