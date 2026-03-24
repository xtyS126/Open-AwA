from typing import Dict, List, Any, Type
from loguru import logger

from .base_plugin import BasePlugin


class ValidationResult:
    def __init__(self, valid: bool, errors: List[str], warnings: List[str]):
        self.valid = valid
        self.errors = errors
        self.warnings = warnings

    def __repr__(self) -> str:
        return f"ValidationResult(valid={self.valid}, errors={len(self.errors)}, warnings={len(self.warnings)})"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "valid": self.valid,
            "errors": self.errors,
            "warnings": self.warnings
        }


class PluginValidator:
    REQUIRED_METHODS = ["initialize", "execute", "cleanup"]
    REQUIRED_CONFIG_FIELDS = ["name", "version"]
    OPTIONAL_CONFIG_FIELDS = ["description", "author", "dependencies"]

    def __init__(self):
        self.logger = logger

    def validate_base_class(self, plugin_class: Type) -> bool:
        try:
            if not isinstance(plugin_class, type):
                self.logger.error(f"Plugin class must be a type, got {type(plugin_class)}")
                return False

            if not issubclass(plugin_class, BasePlugin):
                self.logger.error(f"Plugin class {plugin_class.__name__} does not inherit from BasePlugin")
                return False

            return True
        except Exception as e:
            self.logger.error(f"Error validating base class: {e}")
            return False

    def validate_required_methods(self, plugin_class: Type) -> bool:
        try:
            missing_methods = []
            for method_name in self.REQUIRED_METHODS:
                if not hasattr(plugin_class, method_name):
                    missing_methods.append(method_name)
                    self.logger.warning(f"Plugin class {plugin_class.__name__} missing required method: {method_name}")

            if missing_methods:
                return False
            return True
        except Exception as e:
            self.logger.error(f"Error validating required methods: {e}")
            return False

    def validate_config_format(self, config: Dict[str, Any]) -> bool:
        try:
            if not isinstance(config, dict):
                self.logger.error("Config must be a dictionary")
                return False

            missing_fields = []
            for field in self.REQUIRED_CONFIG_FIELDS:
                if field not in config:
                    missing_fields.append(field)
                    self.logger.warning(f"Config missing required field: {field}")

            if missing_fields:
                return False

            if "version" in config:
                if not isinstance(config["version"], str):
                    self.logger.error("Config 'version' must be a string")
                    return False

            if "dependencies" in config:
                if not isinstance(config["dependencies"], list):
                    self.logger.error("Config 'dependencies' must be a list")
                    return False

            return True
        except Exception as e:
            self.logger.error(f"Error validating config format: {e}")
            return False

    def validate_dependencies(self, dependencies: List[str]) -> bool:
        try:
            if not isinstance(dependencies, list):
                self.logger.error("Dependencies must be a list")
                return False

            for dep in dependencies:
                if not isinstance(dep, str):
                    self.logger.error(f"Dependency must be a string, got {type(dep)}")
                    return False

                if not dep.strip():
                    self.logger.warning("Empty dependency string found")
                    return False

            return True
        except Exception as e:
            self.logger.error(f"Error validating dependencies: {e}")
            return False

    def validate_plugin(self, plugin_class: Type, config: Dict[str, Any]) -> ValidationResult:
        errors = []
        warnings: list[str] = []

        if not self.validate_base_class(plugin_class):
            errors.append(f"Plugin class {plugin_class.__name__} must inherit from BasePlugin")
            return ValidationResult(valid=False, errors=errors, warnings=warnings)

        if not self.validate_required_methods(plugin_class):
            missing = [m for m in self.REQUIRED_METHODS if not hasattr(plugin_class, m)]
            errors.append(f"Plugin class missing required methods: {', '.join(missing)}")

        if not self.validate_config_format(config):
            missing = [f for f in self.REQUIRED_CONFIG_FIELDS if f not in config]
            errors.append(f"Config missing required fields: {', '.join(missing)}")

        if "dependencies" in config:
            if not self.validate_dependencies(config["dependencies"]):
                errors.append("Invalid dependencies format")

        if hasattr(plugin_class, "__init__"):
            init_signature = plugin_class.__init__
            if init_signature.__code__.co_argcount > 2:
                warnings.append("Plugin __init__ accepts more than 2 parameters (self, config), consider simplifying")

        plugin_instance = None
        try:
            if "name" in config:
                plugin_class.name = config["name"]
            if "version" in config:
                plugin_class.version = config["version"]
            if "description" in config:
                plugin_class.description = config["description"]

            plugin_instance = plugin_class(config=config)
        except TypeError as e:
            warnings.append(f"Plugin instantiation with config may have issues: {str(e)}")
        except Exception as e:
            warnings.append(f"Plugin instantiation warning: {str(e)}")

        if plugin_instance and hasattr(plugin_instance, "validate"):
            try:
                if not plugin_instance.validate():
                    warnings.append("Plugin's own validate() method returned False")
            except Exception as e:
                warnings.append(f"Plugin's validate() method raised exception: {str(e)}")

        valid = len(errors) == 0
        return ValidationResult(valid=valid, errors=errors, warnings=warnings)
