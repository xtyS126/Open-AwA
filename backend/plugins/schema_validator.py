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
        "pluginApiVersion": {"type": "string", "minLength": 1},
        "description": {"type": "string"},
        "author": {"type": "string"},
        "permissions": {
            "type": "array",
            "items": {"type": "string"},
        },
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
    valid: bool
    errors: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "valid": self.valid,
            "errors": self.errors,
        }


class JsonSchemaValidator:
    TYPE_MAPPING = {
        "object": dict,
        "array": list,
        "string": str,
        "integer": int,
        "number": (int, float),
        "boolean": bool,
    }

    def validate(self, data: Any, schema: Dict[str, Any]) -> SchemaValidationResult:
        errors: List[str] = []
        self._validate(data=data, schema=schema, path="$", errors=errors)
        return SchemaValidationResult(valid=len(errors) == 0, errors=errors)

    def _validate(self, data: Any, schema: Dict[str, Any], path: str, errors: List[str]) -> None:
        schema_type = schema.get("type")
        if schema_type:
            expected_type = self.TYPE_MAPPING.get(schema_type)
            if not isinstance(expected_type, (type, tuple)):
                errors.append(f"{path}: unsupported schema type '{schema_type}'")
                return
            if not isinstance(data, expected_type) or (isinstance(data, bool) and expected_type is bool):
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
    def __init__(self) -> None:
        self._validator = JsonSchemaValidator()

    def validate_manifest(self, manifest: Dict[str, Any]) -> SchemaValidationResult:
        return self._validator.validate(data=manifest, schema=MANIFEST_SCHEMA)

    def validate_extension(self, extension: Dict[str, Any]) -> SchemaValidationResult:
        return self._validator.validate(data=extension, schema=EXTENSION_SCHEMA)
