import pytest

from plugins.plugin_permission_manager import PluginPermissionManager


@pytest.fixture
def permission_manager() -> PluginPermissionManager:
    return PluginPermissionManager(
        {"demo": {"requested_permissions": ["network:http", "file:read"]}},
        {},
        {},
    )


def test_authorize_normalizes_permissions_and_records_audit(permission_manager: PluginPermissionManager) -> None:
    status = permission_manager.authorize("demo", [" network:http ", "network:http", "", 1])

    assert status == {
        "plugin_name": "demo",
        "requested_permissions": ["file:read", "network:http"],
        "granted_permissions": ["network:http"],
        "missing_permissions": ["file:read"],
    }
    assert permission_manager._audit["demo"] == [
        {"action": "authorize", "permissions": ["network:http"]}
    ]


def test_revoke_and_enforce_missing_permissions(permission_manager: PluginPermissionManager) -> None:
    permission_manager.authorize("demo", ["network:http", "file:read"])
    status = permission_manager.revoke("demo", ["network:http", "unknown"])

    assert status["granted_permissions"] == ["file:read"]
    assert status["missing_permissions"] == ["network:http"]
    with pytest.raises(PermissionError, match="network:http"):
        permission_manager.enforce("demo")


def test_unknown_plugin_is_rejected(permission_manager: PluginPermissionManager) -> None:
    with pytest.raises(ValueError, match="not found"):
        permission_manager.authorize("missing", ["network:http"])


def test_restore_only_keeps_declared_permissions(permission_manager: PluginPermissionManager) -> None:
    status = permission_manager.restore("demo", [" network:http ", "network:http", "obsolete"])

    assert status["granted_permissions"] == ["network:http"]
    assert status["missing_permissions"] == ["file:read"]
