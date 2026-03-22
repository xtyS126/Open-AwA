from typing import Dict, List, Optional, Any, NamedTuple
from loguru import logger
import yaml
import re


class ValidationResult(NamedTuple):
    valid: bool
    errors: List[str]
    warnings: List[str]

    @classmethod
    def success(cls, warnings: Optional[List[str]] = None) -> 'ValidationResult':
        return cls(valid=True, errors=[], warnings=warnings or [])

    @classmethod
    def failure(cls, errors: List[str], warnings: Optional[List[str]] = None) -> 'ValidationResult':
        return cls(valid=False, errors=errors, warnings=warnings or [])

    def merge(self, other: 'ValidationResult') -> 'ValidationResult':
        combined_errors = self.errors + other.errors
        combined_warnings = self.warnings + other.warnings
        return ValidationResult(
            valid=self.valid and other.valid,
            errors=combined_errors,
            warnings=combined_warnings
        )


class SkillValidator:
    REQUIRED_FIELDS = ['name', 'version', 'description']

    VALID_PERMISSIONS = [
        'file:read', 'file:write', 'file:delete', 'file:list',
        'network:read', 'network:write', 'network:http', 'network:ping', 'network:dns',
        'process:read', 'process:write', 'process:kill', 'process:list',
        'memory:read', 'memory:write', 'memory:delete',
        'behavior:read', 'behavior:write',
        'log:read', 'log:write',
        'system:info', 'system:config',
        'command:execute', 'user:manage', 'plugin:install', 'skill:install'
    ]

    def __init__(self):
        logger.info("SkillValidator initialized")

    def validate_yaml_format(self, yaml_content: str) -> bool:
        if not yaml_content or not yaml_content.strip():
            logger.warning("Empty YAML content provided")
            return False

        try:
            yaml.safe_load(yaml_content)
            logger.debug("YAML format validation passed")
            return True
        except yaml.YAMLError as e:
            logger.error(f"YAML parsing error: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error during YAML validation: {e}")
            return False

    def validate_required_fields(self, config: Dict) -> ValidationResult:
        errors = []
        warnings = []

        for field in self.REQUIRED_FIELDS:
            if field not in config:
                errors.append(f"Missing required field: {field}")
            elif not config[field]:
                errors.append(f"Required field '{field}' cannot be empty")

        if 'name' in config:
            name = config['name']
            if not isinstance(name, str):
                errors.append("Field 'name' must be a string")
            elif not re.match(r'^[a-zA-Z0-9_-]+$', name):
                errors.append("Field 'name' must contain only alphanumeric characters, hyphens, and underscores")

        if 'version' in config and isinstance(config['version'], str):
            if not self.validate_version(config['version']):
                errors.append(f"Invalid version format: {config['version']}. Expected semantic versioning (e.g., 1.0.0)")

        if 'description' in config:
            desc = config['description']
            if isinstance(desc, str):
                if len(desc) < 10:
                    warnings.append("Description is too short (recommended: at least 10 characters)")
                elif len(desc) > 500:
                    warnings.append("Description is too long (recommended: at most 500 characters)")

        if errors:
            logger.warning(f"Required fields validation failed: {errors}")
            return ValidationResult.failure(errors, warnings)
        else:
            logger.debug("Required fields validation passed")
            return ValidationResult.success(warnings)

    def validate_permissions(self, permissions: List[str]) -> ValidationResult:
        errors = []
        warnings = []

        if not permissions:
            warnings.append("No permissions declared - skill will have minimal access")
            return ValidationResult.success(warnings)

        if not isinstance(permissions, list):
            errors.append("Permissions must be a list")
            return ValidationResult.failure(errors)

        for permission in permissions:
            if not isinstance(permission, str):
                errors.append(f"Permission must be a string, got: {type(permission).__name__}")
                continue

            if permission not in self.VALID_PERMISSIONS:
                errors.append(f"Unknown permission: '{permission}'")

            if ':' not in permission:
                errors.append(f"Invalid permission format: '{permission}'. Expected format: 'resource:action'")

        dangerous_permissions = ['file:delete', 'system:config', 'user:manage', 'skill:install', 'plugin:install']
        for permission in permissions:
            if permission in dangerous_permissions:
                warnings.append(f"Dangerous permission '{permission}' requires careful handling")

        if errors:
            logger.warning(f"Permissions validation failed: {errors}")
            return ValidationResult.failure(errors, warnings)
        else:
            logger.debug("Permissions validation passed")
            return ValidationResult.success(warnings)

    def validate_dependencies(self, dependencies: List[str]) -> ValidationResult:
        errors = []
        warnings = []

        if not dependencies:
            return ValidationResult.success(warnings)

        if not isinstance(dependencies, list):
            errors.append("Dependencies must be a list")
            return ValidationResult.failure(errors)

        for dep in dependencies:
            if not isinstance(dep, str):
                errors.append(f"Dependency must be a string, got: {type(dep).__name__}")
                continue

            if not dep.strip():
                errors.append("Empty dependency name found")
                continue

            if '@' in dep:
                parts = dep.split('@')
                if len(parts) != 2:
                    errors.append(f"Invalid dependency format: '{dep}'. Expected 'name@version'")
                else:
                    dep_name, dep_version = parts
                    if not dep_name.strip():
                        errors.append(f"Missing dependency name in: '{dep}'")
                    if not self.validate_version(dep_version):
                        errors.append(f"Invalid version in dependency '{dep}': '{dep_version}'")
            else:
                if not re.match(r'^[a-zA-Z0-9_-]+$', dep):
                    errors.append(f"Invalid dependency name: '{dep}'. Expected alphanumeric characters, hyphens, and underscores")

        if len(dependencies) > 10:
            warnings.append(f"Skill has {len(dependencies)} dependencies - consider reducing dependencies")

        circular_patterns = [d for d in dependencies if d.startswith('skill:')]
        if circular_patterns:
            warnings.append(f"Circular dependency warning: {circular_patterns}")

        if errors:
            logger.warning(f"Dependencies validation failed: {errors}")
            return ValidationResult.failure(errors, warnings)
        else:
            logger.debug("Dependencies validation passed")
            return ValidationResult.success(warnings)

    def validate_version(self, version: str) -> bool:
        if not version or not isinstance(version, str):
            return False

        semver_pattern = r'^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-((?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?(?:\+([0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$'
        is_valid = bool(re.match(semver_pattern, version))

        if is_valid:
            logger.debug(f"Version validation passed: {version}")
        else:
            logger.warning(f"Version validation failed: {version}")

        return is_valid

    def validate_skill_config(self, config: Dict) -> ValidationResult:
        if not isinstance(config, dict):
            logger.error("Config must be a dictionary")
            return ValidationResult.failure(["Config must be a dictionary"])

        logger.info(f"Starting validation for skill: {config.get('name', 'unknown')}")

        result = ValidationResult.success()

        required_fields_result = self.validate_required_fields(config)
        result = result.merge(required_fields_result)

        if 'permissions' in config:
            permissions = config['permissions']
            if isinstance(permissions, list):
                permissions_result = self.validate_permissions(permissions)
                result = result.merge(permissions_result)
            else:
                logger.warning("Permissions field is not a list")

        if 'dependencies' in config:
            dependencies = config['dependencies']
            if isinstance(dependencies, list):
                dependencies_result = self.validate_dependencies(dependencies)
                result = result.merge(dependencies_result)
            else:
                logger.warning("Dependencies field is not a list")

        if 'version' in config and isinstance(config['version'], str):
            if not self.validate_version(config['version']):
                result = result.merge(ValidationResult.failure([f"Invalid version format: {config['version']}"]))

        if 'metadata' in config:
            metadata = config['metadata']
            if isinstance(metadata, dict):
                if 'created_at' not in metadata:
                    result.warnings.append("Missing 'created_at' in metadata")
                if 'author' not in metadata and 'author' not in config:
                    result.warnings.append("Missing 'author' information")

        if result.valid:
            logger.info(f"Skill validation passed: {config.get('name', 'unknown')}")
        else:
            logger.error(f"Skill validation failed: {config.get('name', 'unknown')}")

        return result
