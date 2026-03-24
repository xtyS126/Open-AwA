from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List

from .schema_validator import ManifestExtensionSchemaValidator


class ExtensionPointType(str, Enum):
    TOOL = "tool"
    HOOK = "hook"
    COMMAND = "command"
    ROUTE = "route"
    EVENT_HANDLER = "event_handler"
    SCHEDULER = "scheduler"
    MIDDLEWARE = "middleware"
    DATA_PROVIDER = "data_provider"


@dataclass
class ExtensionRegistration:
    plugin_name: str
    point: ExtensionPointType
    name: str
    version: str
    config: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plugin_name": self.plugin_name,
            "point": self.point.value,
            "name": self.name,
            "version": self.version,
            "config": self.config,
        }


class ExtensionRegistry:
    def __init__(self) -> None:
        self._schema_validator = ManifestExtensionSchemaValidator()
        self._registrations: Dict[ExtensionPointType, List[ExtensionRegistration]] = {
            point: [] for point in ExtensionPointType
        }

    def register_extension(self, plugin_name: str, extension: Dict[str, Any]) -> ExtensionRegistration:
        validation = self._schema_validator.validate_extension(extension)
        if not validation.valid:
            raise ValueError(f"Invalid extension: {validation.errors}")

        registration = ExtensionRegistration(
            plugin_name=plugin_name,
            point=ExtensionPointType(extension["point"]),
            name=extension["name"],
            version=extension["version"],
            config=extension.get("config", {}),
        )
        self._registrations[registration.point].append(registration)
        return registration

    def register_manifest(self, plugin_name: str, manifest: Dict[str, Any]) -> List[ExtensionRegistration]:
        manifest_validation = self._schema_validator.validate_manifest(manifest)
        if not manifest_validation.valid:
            raise ValueError(f"Invalid manifest: {manifest_validation.errors}")

        registrations: List[ExtensionRegistration] = []
        for extension in manifest["extensions"]:
            registrations.append(self.register_extension(plugin_name, extension))
        return registrations

    def unregister_plugin(self, plugin_name: str) -> None:
        for point in ExtensionPointType:
            self._registrations[point] = [
                item for item in self._registrations[point] if item.plugin_name != plugin_name
            ]

    def list_by_point(self, point: ExtensionPointType) -> List[Dict[str, Any]]:
        return [item.to_dict() for item in self._registrations[point]]

    def list_plugin_extensions(self, plugin_name: str) -> List[Dict[str, Any]]:
        result: List[Dict[str, Any]] = []
        for point in ExtensionPointType:
            result.extend(
                item.to_dict()
                for item in self._registrations[point]
                if item.plugin_name == plugin_name
            )
        return result

    def get_registry_snapshot(self) -> Dict[str, List[Dict[str, Any]]]:
        return {
            point.value: [item.to_dict() for item in registrations]
            for point, registrations in self._registrations.items()
        }

    def register_tool(self, plugin_name: str, name: str, version: str, config: Dict[str, Any]) -> ExtensionRegistration:
        return self.register_extension(plugin_name, {
            "point": ExtensionPointType.TOOL.value,
            "name": name,
            "version": version,
            "config": config,
        })

    def register_hook(self, plugin_name: str, name: str, version: str, config: Dict[str, Any]) -> ExtensionRegistration:
        return self.register_extension(plugin_name, {
            "point": ExtensionPointType.HOOK.value,
            "name": name,
            "version": version,
            "config": config,
        })

    def register_command(self, plugin_name: str, name: str, version: str, config: Dict[str, Any]) -> ExtensionRegistration:
        return self.register_extension(plugin_name, {
            "point": ExtensionPointType.COMMAND.value,
            "name": name,
            "version": version,
            "config": config,
        })

    def register_route(self, plugin_name: str, name: str, version: str, config: Dict[str, Any]) -> ExtensionRegistration:
        return self.register_extension(plugin_name, {
            "point": ExtensionPointType.ROUTE.value,
            "name": name,
            "version": version,
            "config": config,
        })

    def register_event_handler(self, plugin_name: str, name: str, version: str, config: Dict[str, Any]) -> ExtensionRegistration:
        return self.register_extension(plugin_name, {
            "point": ExtensionPointType.EVENT_HANDLER.value,
            "name": name,
            "version": version,
            "config": config,
        })

    def register_scheduler(self, plugin_name: str, name: str, version: str, config: Dict[str, Any]) -> ExtensionRegistration:
        return self.register_extension(plugin_name, {
            "point": ExtensionPointType.SCHEDULER.value,
            "name": name,
            "version": version,
            "config": config,
        })

    def register_middleware(self, plugin_name: str, name: str, version: str, config: Dict[str, Any]) -> ExtensionRegistration:
        return self.register_extension(plugin_name, {
            "point": ExtensionPointType.MIDDLEWARE.value,
            "name": name,
            "version": version,
            "config": config,
        })

    def register_data_provider(self, plugin_name: str, name: str, version: str, config: Dict[str, Any]) -> ExtensionRegistration:
        return self.register_extension(plugin_name, {
            "point": ExtensionPointType.DATA_PROVIDER.value,
            "name": name,
            "version": version,
            "config": config,
        })
