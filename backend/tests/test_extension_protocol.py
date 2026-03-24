import pytest

from plugins.extension_protocol import ExtensionPointType, ExtensionRegistry
from plugins.schema_validator import ManifestExtensionSchemaValidator


def _build_manifest(plugin_name: str = "demo_plugin"):
    return {
        "name": plugin_name,
        "version": "1.0.0",
        "pluginApiVersion": "1.0.0",
        "description": "demo",
        "author": "tester",
        "permissions": ["storage.read"],
        "extensions": [
            {"point": "tool", "name": "tool_ext", "version": "1.0.0", "config": {}},
            {"point": "hook", "name": "hook_ext", "version": "1.0.0", "config": {}},
            {"point": "command", "name": "command_ext", "version": "1.0.0", "config": {}},
            {"point": "route", "name": "route_ext", "version": "1.0.0", "config": {}},
            {"point": "event_handler", "name": "event_ext", "version": "1.0.0", "config": {}},
            {"point": "scheduler", "name": "scheduler_ext", "version": "1.0.0", "config": {}},
            {"point": "middleware", "name": "middleware_ext", "version": "1.0.0", "config": {}},
            {"point": "data_provider", "name": "provider_ext", "version": "1.0.0", "config": {}},
        ],
    }


def test_manifest_schema_validator_accepts_valid_manifest():
    validator = ManifestExtensionSchemaValidator()
    result = validator.validate_manifest(_build_manifest())

    assert result.valid is True
    assert result.errors == []


def test_manifest_schema_validator_rejects_invalid_manifest():
    validator = ManifestExtensionSchemaValidator()
    invalid_manifest = {
        "name": "demo_plugin",
        "version": "1.0.0",
        "pluginApiVersion": "1.0.0",
        "extensions": [
            {"point": "invalid_point", "name": "bad", "version": "1.0.0"}
        ],
    }

    result = validator.validate_manifest(invalid_manifest)

    assert result.valid is False
    assert any("enum" in error for error in result.errors)


def test_extension_registry_register_manifest_and_query_by_point():
    registry = ExtensionRegistry()
    manifest = _build_manifest("plugin_alpha")

    registrations = registry.register_manifest("plugin_alpha", manifest)

    assert len(registrations) == 8
    assert len(registry.list_plugin_extensions("plugin_alpha")) == 8

    for point in ExtensionPointType:
        point_items = registry.list_by_point(point)
        assert len(point_items) == 1
        assert point_items[0]["plugin_name"] == "plugin_alpha"
        assert point_items[0]["point"] == point.value


def test_extension_registry_unregister_plugin():
    registry = ExtensionRegistry()
    manifest = _build_manifest("plugin_beta")
    registry.register_manifest("plugin_beta", manifest)

    registry.unregister_plugin("plugin_beta")

    assert registry.list_plugin_extensions("plugin_beta") == []
    snapshot = registry.get_registry_snapshot()
    assert all(items == [] for items in snapshot.values())


def test_extension_registry_rejects_invalid_extension():
    registry = ExtensionRegistry()

    with pytest.raises(ValueError):
        registry.register_extension(
            plugin_name="plugin_bad",
            extension={
                "point": "tool",
                "name": "invalid",
                "version": "1",
                "config": {},
            },
        )
