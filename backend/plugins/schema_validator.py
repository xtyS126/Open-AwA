"""
插件系统模块，负责插件定义、加载、校验、沙箱隔离、生命周期或扩展协议处理。
这一层通常同时涉及可扩展性、安全性与运行时状态管理。
"""

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


SEMVER_PATTERN = r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-([0-9A-Za-z.-]+))?(?:\+([0-9A-Za-z.-]+))?$"


EXTENSION_POINT_VALUES = [
    "tool",
    "hook",
    "command",
    "route",
    "event_handler",
    "scheduler",
    "middleware",
    "data_provider",
]


EXTENSION_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["point", "name", "version"],
    "properties": {
        "point": {"type": "string", "enum": EXTENSION_POINT_VALUES},
        "name": {"type": "string", "minLength": 1},
        "version": {"type": "string", "pattern": SEMVER_PATTERN},
        "config": {"type": "object"},
    },
    "additionalProperties": False,
}


MANIFEST_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["name", "version", "pluginApiVersion", "extensions"],
    "properties": {
        "name": {"type": "string", "minLength": 1},
        "version": {"type": "string", "pattern": SEMVER_PATTERN},
        "pluginApiVersion": {"type": "string", "pattern": SEMVER_PATTERN},
        "description": {"type": "string"},
        "author": {"type": "string"},
        "permissions": {
            "type": "array",
            "items": {"type": "string"},
        },
        "auto_authorize_permissions": {"type": "boolean"},
        "extensions": {
            "type": "array",
            "minItems": 1,
            "items": EXTENSION_SCHEMA,
        },
    },
    "additionalProperties": False,
}


@dataclass
class SchemaValidationResult:
    """
    封装与SchemaValidationResult相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    valid: bool
    errors: List[str]

    def to_dict(self) -> Dict[str, Any]:
        """
        处理to、dict相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        return {
            "valid": self.valid,
            "errors": self.errors,
        }


class JsonSchemaValidator:
    """
    封装与JsonSchemaValidator相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    TYPE_MAPPING = {
        "object": dict,
        "array": list,
        "string": str,
        "integer": int,
        "number": (int, float),
        "boolean": bool,
    }

    def validate(self, data: Any, schema: Dict[str, Any]) -> SchemaValidationResult:
        """
        处理validate相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        errors: List[str] = []
        self._validate(data=data, schema=schema, path="$", errors=errors)
        return SchemaValidationResult(valid=len(errors) == 0, errors=errors)

    def _validate(self, data: Any, schema: Dict[str, Any], path: str, errors: List[str]) -> None:
        """
        处理validate相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        schema_type = schema.get("type")
        if schema_type:
            expected_type = self.TYPE_MAPPING.get(schema_type)
            if not isinstance(expected_type, (type, tuple)):
                errors.append(f"{path}: unsupported schema type '{schema_type}'")
                return
            if not isinstance(data, expected_type) or (isinstance(data, bool) and expected_type in (int, (int, float))):
                errors.append(f"{path}: expected type {schema_type}")
                return

        enum_values = schema.get("enum")
        if enum_values is not None and data not in enum_values:
            errors.append(f"{path}: value '{data}' is not in enum {enum_values}")

        pattern = schema.get("pattern")
        if pattern is not None and isinstance(data, str) and re.fullmatch(pattern, data) is None:
            errors.append(f"{path}: value '{data}' does not match pattern")

        min_length = schema.get("minLength")
        if min_length is not None and isinstance(data, str) and len(data) < int(min_length):
            errors.append(f"{path}: string length must be >= {min_length}")

        if schema_type == "object":
            required_fields = schema.get("required", [])
            for field in required_fields:
                if field not in data:
                    errors.append(f"{path}: missing required field '{field}'")

            properties = schema.get("properties", {})
            for key, value in data.items():
                if key in properties:
                    self._validate(value, properties[key], f"{path}.{key}", errors)
                elif schema.get("additionalProperties") is False:
                    errors.append(f"{path}: additional property '{key}' is not allowed")

        if schema_type == "array":
            min_items = schema.get("minItems")
            if min_items is not None and len(data) < int(min_items):
                errors.append(f"{path}: array length must be >= {min_items}")

            item_schema: Optional[Dict[str, Any]] = schema.get("items")
            if item_schema:
                for index, item in enumerate(data):
                    self._validate(item, item_schema, f"{path}[{index}]", errors)


class ManifestExtensionSchemaValidator:
    """
    封装与ManifestExtensionSchemaValidator相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    def __init__(self) -> None:
        """
        处理init相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        self._validator = JsonSchemaValidator()

    def validate_manifest(self, manifest: Dict[str, Any]) -> SchemaValidationResult:
        """
        校验manifest相关输入、规则或结构是否合法。
        返回结果通常用于阻止非法输入继续流入后续链路。
        """
        return self._validator.validate(data=manifest, schema=MANIFEST_SCHEMA)

    def validate_extension(self, extension: Dict[str, Any]) -> SchemaValidationResult:
        """
        校验extension相关输入、规则或结构是否合法。
        返回结果通常用于阻止非法输入继续流入后续链路。
        """
        return self._validator.validate(data=extension, schema=EXTENSION_SCHEMA)
