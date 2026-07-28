from plugins.plugin_security_scanner import PluginSecurityScanner


def test_scanner_blocks_command_execution(tmp_path) -> None:
    plugin_path = tmp_path / "plugin.py"
    plugin_path.write_text("import subprocess\nsubprocess.run(['echo', 'ok'])\n", encoding="utf-8")

    result = PluginSecurityScanner().scan(str(plugin_path))

    assert result["blocked"] is True
    assert "command:execute" in result["requested_permissions"]


def test_scanner_reports_network_permission_without_blocking(tmp_path) -> None:
    plugin_path = tmp_path / "plugin.py"
    plugin_path.write_text("import httpx\nhttpx.get('https://example.com')\n", encoding="utf-8")

    result = PluginSecurityScanner().scan(str(plugin_path))

    assert result["blocked"] is False
    assert result["requested_permissions"] == ["network:http"]
