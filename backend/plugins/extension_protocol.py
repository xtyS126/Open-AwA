"""
插件系统模块，负责插件定义、加载、校验、沙箱隔离、生命周期或扩展协议处理。
这一层通常同时涉及可扩展性、安全性与运行时状态管理。
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List

from .schema_validator import ManifestExtensionSchemaValidator


class ExtensionPointType(str, Enum):
    """
    封装与ExtensionPointType相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
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
    """
    封装与ExtensionRegistration相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    plugin_name: str
    point: ExtensionPointType
    name: str
    version: str
    config: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        """
        处理to、dict相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        return {
            "plugin_name": self.plugin_name,
            "point": self.point.value,
            "name": self.name,
            "version": self.version,
            "config": self.config,
        }


class ExtensionRegistry:
    """
    封装与ExtensionRegistry相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    def __init__(self) -> None:
        """
        处理init相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        self._schema_validator = ManifestExtensionSchemaValidator()
        self._registrations: Dict[ExtensionPointType, List[ExtensionRegistration]] = {
            point: [] for point in ExtensionPointType
        }

    def register_extension(self, plugin_name: str, extension: Dict[str, Any]) -> ExtensionRegistration:
        """
        处理register、extension相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
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
        """
        处理register、manifest相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        manifest_validation = self._schema_validator.validate_manifest(manifest)
        if not manifest_validation.valid:
            raise ValueError(f"Invalid manifest: {manifest_validation.errors}")

        registrations: List[ExtensionRegistration] = []
        for extension in manifest["extensions"]:
            registrations.append(self.register_extension(plugin_name, extension))
        return registrations

    def unregister_plugin(self, plugin_name: str) -> None:
        """
        处理unregister、plugin相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        for point in ExtensionPointType:
            self._registrations[point] = [
                item for item in self._registrations[point] if item.plugin_name != plugin_name
            ]

    def list_by_point(self, point: ExtensionPointType) -> List[Dict[str, Any]]:
        """
        列出by、point相关内容，便于调用方查看、筛选或批量处理。
        返回结果通常会被页面展示、审计流程或后续操作复用。
        """
        return [item.to_dict() for item in self._registrations[point]]

    def list_plugin_extensions(self, plugin_name: str) -> List[Dict[str, Any]]:
        """
        列出plugin、extensions相关内容，便于调用方查看、筛选或批量处理。
        返回结果通常会被页面展示、审计流程或后续操作复用。
        """
        result: List[Dict[str, Any]] = []
        for point in ExtensionPointType:
            result.extend(
                item.to_dict()
                for item in self._registrations[point]
                if item.plugin_name == plugin_name
            )
        return result

    def get_registry_snapshot(self) -> Dict[str, List[Dict[str, Any]]]:
        """
        获取registry、snapshot相关数据或当前状态。
        调用方通常依赖该结果继续进行后续判断、渲染或业务编排。
        """
        return {
            point.value: [item.to_dict() for item in registrations]
            for point, registrations in self._registrations.items()
        }

    def register_tool(self, plugin_name: str, name: str, version: str, config: Dict[str, Any]) -> ExtensionRegistration:
        """
        处理register、tool相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        return self.register_extension(plugin_name, {
            "point": ExtensionPointType.TOOL.value,
            "name": name,
            "version": version,
            "config": config,
        })

    def register_hook(self, plugin_name: str, name: str, version: str, config: Dict[str, Any]) -> ExtensionRegistration:
        """
        处理register、hook相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        return self.register_extension(plugin_name, {
            "point": ExtensionPointType.HOOK.value,
            "name": name,
            "version": version,
            "config": config,
        })

    def register_command(self, plugin_name: str, name: str, version: str, config: Dict[str, Any]) -> ExtensionRegistration:
        """
        处理register、command相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        return self.register_extension(plugin_name, {
            "point": ExtensionPointType.COMMAND.value,
            "name": name,
            "version": version,
            "config": config,
        })

    def register_route(self, plugin_name: str, name: str, version: str, config: Dict[str, Any]) -> ExtensionRegistration:
        """
        处理register、route相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        return self.register_extension(plugin_name, {
            "point": ExtensionPointType.ROUTE.value,
            "name": name,
            "version": version,
            "config": config,
        })

    def register_event_handler(self, plugin_name: str, name: str, version: str, config: Dict[str, Any]) -> ExtensionRegistration:
        """
        处理register、event、handler相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        return self.register_extension(plugin_name, {
            "point": ExtensionPointType.EVENT_HANDLER.value,
            "name": name,
            "version": version,
            "config": config,
        })

    def register_scheduler(self, plugin_name: str, name: str, version: str, config: Dict[str, Any]) -> ExtensionRegistration:
        """
        处理register、scheduler相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        return self.register_extension(plugin_name, {
            "point": ExtensionPointType.SCHEDULER.value,
            "name": name,
            "version": version,
            "config": config,
        })

    def register_middleware(self, plugin_name: str, name: str, version: str, config: Dict[str, Any]) -> ExtensionRegistration:
        """
        处理register、middleware相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        return self.register_extension(plugin_name, {
            "point": ExtensionPointType.MIDDLEWARE.value,
            "name": name,
            "version": version,
            "config": config,
        })

    def register_data_provider(self, plugin_name: str, name: str, version: str, config: Dict[str, Any]) -> ExtensionRegistration:
        """
        处理register、data、provider相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        return self.register_extension(plugin_name, {
            "point": ExtensionPointType.DATA_PROVIDER.value,
            "name": name,
            "version": version,
            "config": config,
        })
