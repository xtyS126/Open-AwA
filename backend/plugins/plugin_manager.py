import ast
import hashlib
import importlib
import inspect
import io
import os
import re
import shutil
import tempfile
import urllib.parse
import zipfile
from copy import deepcopy
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

import httpx
from loguru import logger

from .base_plugin import BasePlugin
from .extension_protocol import ExtensionRegistry
from .hot_update_manager import HotUpdateManager, RollbackManager, RolloutConfig
from .plugin_lifecycle import PluginState, PluginStateMachine, TransitionExecutor
from .plugin_loader import PluginLoader
from .plugin_sandbox import PluginSandbox
from .plugin_validator import PluginValidator


class PluginManager:
    NPM_PACKAGE_PATTERN = re.compile(
        r"^(?:@[a-z0-9][a-z0-9._-]*/)?[a-z0-9][a-z0-9._-]*$"
    )
    NPM_VERSION_PATTERN = re.compile(
        r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
        r"(?:-((?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?"
        r"(?:\+([0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$"
    )
    DANGEROUS_IMPORT_MODULES = {
        "subprocess",
        "socket",
        "ctypes",
        "pickle",
        "marshal",
        "requests",
        "httpx",
        "urllib",
        "urllib.request",
    }
    BLOCK_INSTALL_PATTERNS = {
        "eval",
        "exec",
        "compile",
        "subprocess",
        "ctypes",
        "pickle",
        "marshal",
        "system",
        "popen",
    }
    DANGEROUS_CALL_NAMES = {
        "eval",
        "exec",
        "compile",
        "open",
        "input",
        "__import__",
    }
    DANGEROUS_ATTRIBUTE_SUFFIXES = {
        "system",
        "popen",
        "remove",
        "unlink",
        "rmtree",
        "run",
        "call",
        "kill",
        "post",
        "get",
        "request",
        "urlopen",
    }
    PERMISSION_TO_PATTERNS = {
        "file:read": ["open"],
        "file:write": ["open", "remove", "unlink", "rmtree"],
        "network:http": ["requests", "httpx", "urllib", "urlopen"],
        "command:execute": ["system", "popen", "run", "call", "exec", "eval", "compile"],
    }

    def __init__(self, plugins_dir: Optional[str] = None, sandbox_defaults: Optional[Dict[str, Any]] = None):
        self.plugins_dir = plugins_dir or self._get_default_plugins_dir()
        self.loader = PluginLoader()
        self.validator = PluginValidator()
        self._sandbox_defaults = self._normalize_resource_limits(sandbox_defaults)
        self.sandbox = PluginSandbox(**self._sandbox_defaults)
        self._plugin_sandboxes: Dict[str, PluginSandbox] = {}
        self.state_machine = PluginStateMachine()
        self.transition_executor = TransitionExecutor(self.state_machine)
        self.loaded_plugins: Dict[str, BasePlugin] = {}
        self.plugin_metadata: Dict[str, Dict[str, Any]] = {}
        self._tools_registry: Dict[str, List[Dict[str, Any]]] = {}
        self._runtime_permission_store: Dict[str, Set[str]] = {}
        self._runtime_permission_audit: Dict[str, List[Dict[str, Any]]] = {}
        self.extension_registry = ExtensionRegistry()
        self._runtime_routes: Dict[str, Dict[str, Any]] = {}
        self._rollout_release_counter = 0
        self.rollback_manager = RollbackManager()
        self.hot_update_manager = HotUpdateManager(rollback_manager=self.rollback_manager)
        logger.info(f"PluginManager initialized with plugins_dir: {self.plugins_dir}")

    def _get_default_plugins_dir(self) -> str:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        default_dir = os.path.join(current_dir, "plugins")
        if not os.path.exists(default_dir):
            os.makedirs(default_dir, exist_ok=True)
            logger.info(f"Created default plugins directory: {default_dir}")
        return default_dir

    def _normalize_resource_limits(self, resource_limits: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        normalized = {
            "timeout": 30,
            "memory_limit": "512m",
            "cpu_limit": 1.0,
        }
        if not resource_limits:
            return normalized

        timeout = resource_limits.get("timeout")
        if timeout is not None:
            normalized["timeout"] = int(timeout)

        memory_limit = resource_limits.get("memory_limit")
        if memory_limit is not None:
            normalized["memory_limit"] = str(memory_limit)

        cpu_limit = resource_limits.get("cpu_limit")
        if cpu_limit is not None:
            normalized["cpu_limit"] = float(cpu_limit)

        return normalized

    def _create_plugin_sandbox(self, resource_limits: Optional[Dict[str, Any]] = None) -> PluginSandbox:
        merged = dict(self._sandbox_defaults)
        if resource_limits:
            merged.update(self._normalize_resource_limits(resource_limits))
        return PluginSandbox(**merged)

    def _get_node_name(self, node: ast.AST) -> str:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            base = self._get_node_name(node.value)
            return f"{base}.{node.attr}" if base else node.attr
        if isinstance(node, ast.Call):
            return self._get_node_name(node.func)
        return ""

    def _collect_static_risk_tokens(self, tree: ast.AST) -> Set[str]:
        tokens: Set[str] = set()

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    tokens.add(alias.name)
            elif isinstance(node, ast.ImportFrom):
                module_name = node.module or ""
                if module_name:
                    tokens.add(module_name)
            elif isinstance(node, ast.Call):
                call_name = self._get_node_name(node.func)
                if call_name:
                    tokens.add(call_name)

        return tokens

    def _match_risk_patterns(self, tokens: Set[str]) -> Set[str]:
        matches: Set[str] = set()
        for token in tokens:
            lowered = token.lower()
            if lowered in self.DANGEROUS_CALL_NAMES:
                matches.add(lowered)
                continue

            for module_name in self.DANGEROUS_IMPORT_MODULES:
                if lowered == module_name or lowered.startswith(f"{module_name}."):
                    matches.add(module_name)

            for suffix in self.DANGEROUS_ATTRIBUTE_SUFFIXES:
                if lowered.endswith(f".{suffix}") or lowered == suffix:
                    matches.add(suffix)

        return matches

    def _derive_requested_permissions(self, matched_patterns: Set[str]) -> Set[str]:
        requested: Set[str] = set()
        for permission, patterns in self.PERMISSION_TO_PATTERNS.items():
            for pattern in patterns:
                if any(match == pattern or pattern in match for match in matched_patterns):
                    requested.add(permission)
                    break
        return requested

    def _run_static_security_scan(self, plugin_path: str) -> Dict[str, Any]:
        try:
            with open(plugin_path, "r", encoding="utf-8") as plugin_file:
                source_code = plugin_file.read()
        except UnicodeDecodeError:
            with open(plugin_path, "r", encoding="latin-1") as plugin_file:
                source_code = plugin_file.read()

        tree = ast.parse(source_code)
        tokens = self._collect_static_risk_tokens(tree)
        matched_patterns = self._match_risk_patterns(tokens)
        requested_permissions = sorted(self._derive_requested_permissions(matched_patterns))

        blocked = bool(matched_patterns & self.BLOCK_INSTALL_PATTERNS)
        reasons = [f"检测到危险模式: {pattern}" for pattern in sorted(matched_patterns & self.BLOCK_INSTALL_PATTERNS)]

        return {
            "blocked": blocked,
            "reasons": reasons,
            "matched_patterns": sorted(matched_patterns),
            "requested_permissions": requested_permissions,
        }

    def authorize_plugin_permissions(self, plugin_name: str, permissions: List[str]) -> Dict[str, Any]:
        if plugin_name not in self.plugin_metadata:
            raise ValueError(f"Plugin '{plugin_name}' not found")

        current = self._runtime_permission_store.get(plugin_name, set())
        current.update(permission.strip() for permission in permissions if isinstance(permission, str) and permission.strip())
        self._runtime_permission_store[plugin_name] = current

        requested = set(self.plugin_metadata.get(plugin_name, {}).get("requested_permissions", []))
        granted = sorted(current)
        missing = sorted(permission for permission in requested if permission not in current)

        self._runtime_permission_audit.setdefault(plugin_name, []).append(
            {
                "action": "authorize",
                "permissions": sorted(set(permissions)),
            }
        )

        return {
            "plugin_name": plugin_name,
            "requested_permissions": sorted(requested),
            "granted_permissions": granted,
            "missing_permissions": missing,
        }

    def revoke_plugin_permissions(self, plugin_name: str, permissions: List[str]) -> Dict[str, Any]:
        if plugin_name not in self.plugin_metadata:
            raise ValueError(f"Plugin '{plugin_name}' not found")

        current = self._runtime_permission_store.get(plugin_name, set())
        to_remove = {permission.strip() for permission in permissions if isinstance(permission, str) and permission.strip()}
        current = {permission for permission in current if permission not in to_remove}
        self._runtime_permission_store[plugin_name] = current

        requested = set(self.plugin_metadata.get(plugin_name, {}).get("requested_permissions", []))
        granted = sorted(current)
        missing = sorted(permission for permission in requested if permission not in current)

        self._runtime_permission_audit.setdefault(plugin_name, []).append(
            {
                "action": "revoke",
                "permissions": sorted(to_remove),
            }
        )

        return {
            "plugin_name": plugin_name,
            "requested_permissions": sorted(requested),
            "granted_permissions": granted,
            "missing_permissions": missing,
        }

    def get_plugin_permission_status(self, plugin_name: str) -> Dict[str, Any]:
        if plugin_name not in self.plugin_metadata:
            raise ValueError(f"Plugin '{plugin_name}' not found")

        requested = set(self.plugin_metadata.get(plugin_name, {}).get("requested_permissions", []))
        granted = set(self._runtime_permission_store.get(plugin_name, set()))
        missing = sorted(permission for permission in requested if permission not in granted)

        return {
            "plugin_name": plugin_name,
            "requested_permissions": sorted(requested),
            "granted_permissions": sorted(granted),
            "missing_permissions": missing,
        }

    def _enforce_runtime_permissions(self, plugin_name: str) -> Optional[Dict[str, Any]]:
        status = self.get_plugin_permission_status(plugin_name)
        if status["missing_permissions"]:
            return {
                "status": "permission_required",
                "message": f"Plugin '{plugin_name}' 缺少运行权限",
                "required_permissions": status["missing_permissions"],
                "requested_permissions": status["requested_permissions"],
                "granted_permissions": status["granted_permissions"],
            }
        return None

    def _safe_extract_zip_archive(self, archive: zipfile.ZipFile, target_dir: str) -> None:
        target_dir_abs = os.path.abspath(target_dir)
        os.makedirs(target_dir_abs, exist_ok=True)

        for member in archive.namelist():
            normalized_member = member.replace("\\", "/")
            if normalized_member.startswith("/"):
                raise ValueError("Invalid zip file structure")

            parts = [part for part in normalized_member.split("/") if part not in ("", ".")]
            if any(part == ".." for part in parts):
                raise ValueError("Invalid zip file structure")

            destination = os.path.abspath(os.path.join(target_dir_abs, *parts))
            if os.path.commonpath([target_dir_abs, destination]) != target_dir_abs:
                raise ValueError("Invalid zip file structure")

        archive.extractall(target_dir_abs)

    def _safe_extract_zip_file(self, zip_path: str, target_dir: str) -> None:
        with zipfile.ZipFile(zip_path, "r") as archive:
            self._safe_extract_zip_archive(archive, target_dir)

    def _safe_extract_zip_bytes(self, zip_content: bytes, target_dir: str) -> None:
        with zipfile.ZipFile(io.BytesIO(zip_content), "r") as archive:
            self._safe_extract_zip_archive(archive, target_dir)

    def _create_source_extract_dir(self, source_name: str) -> str:
        base_name = os.path.splitext(os.path.basename(source_name))[0] or "plugin"
        safe_base = re.sub(r"[^a-zA-Z0-9_.-]", "_", base_name)
        extract_dir = tempfile.mkdtemp(prefix=f"{safe_base}_", dir=self.plugins_dir)
        return extract_dir

    def _discover_plugins_in_directory(self, search_dir: str) -> List[Dict[str, Any]]:
        discovered_plugins: List[Dict[str, Any]] = []

        if not os.path.exists(search_dir):
            return discovered_plugins

        for root, dirs, files in os.walk(search_dir):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__"]

            for file in files:
                if file.endswith(".py") and not file.startswith("_"):
                    plugin_path = os.path.join(root, file)
                    plugin_info = self._scan_plugin_file(plugin_path)
                    if plugin_info:
                        discovered_plugins.append(plugin_info)
                        plugin_name = plugin_info["name"]
                        self.plugin_metadata[plugin_name] = plugin_info
                        self._runtime_permission_store.setdefault(plugin_name, set())
                        if plugin_name not in self.loaded_plugins:
                            self.state_machine.set_state(plugin_name, PluginState.REGISTERED)
                        logger.debug(f"Discovered plugin: {plugin_name} at {plugin_path}")

        return discovered_plugins

    def discover_plugins(self) -> List[Dict[str, Any]]:
        logger.info(f"Discovering plugins in directory: {self.plugins_dir}")

        if not os.path.exists(self.plugins_dir):
            logger.warning(f"Plugins directory does not exist: {self.plugins_dir}")
            return []

        discovered_plugins = self._discover_plugins_in_directory(self.plugins_dir)
        logger.info(f"Plugin discovery completed. Found {len(discovered_plugins)} plugins")
        return discovered_plugins

    def register_plugin_from_local_zip(
        self,
        zip_path: str,
        resource_limits: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        if not os.path.exists(zip_path):
            raise FileNotFoundError(f"Zip path does not exist: {zip_path}")
        if not zip_path.lower().endswith(".zip"):
            raise ValueError("Only .zip files are supported")

        extract_dir = self._create_source_extract_dir(zip_path)
        try:
            self._safe_extract_zip_file(zip_path, extract_dir)
            discovered = self._discover_plugins_in_directory(extract_dir)
            normalized_limits = self._normalize_resource_limits(resource_limits)
            for plugin_info in discovered:
                plugin_info["source"] = "local_zip"
                plugin_info["source_path"] = zip_path
                plugin_info["resource_limits"] = normalized_limits
                self.plugin_metadata[plugin_info["name"]] = plugin_info
            logger.info(f"Registered {len(discovered)} plugin(s) from local zip: {zip_path}")
            return discovered
        except Exception:
            shutil.rmtree(extract_dir, ignore_errors=True)
            raise

    def register_plugin_from_url(
        self,
        source_url: str,
        resource_limits: Optional[Dict[str, Any]] = None,
        timeout: int = 30,
    ) -> List[Dict[str, Any]]:
        parsed = urllib.parse.urlparse(source_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Invalid remote plugin URL")

        response = httpx.get(source_url, timeout=timeout, follow_redirects=True)
        response.raise_for_status()

        if not response.content:
            raise ValueError("Remote plugin package is empty")

        source_name = os.path.basename(parsed.path) or "remote_plugin.zip"
        extract_dir = self._create_source_extract_dir(source_name)

        try:
            self._safe_extract_zip_bytes(response.content, extract_dir)
            discovered = self._discover_plugins_in_directory(extract_dir)
            normalized_limits = self._normalize_resource_limits(resource_limits)
            for plugin_info in discovered:
                plugin_info["source"] = "remote_url"
                plugin_info["source_url"] = source_url
                plugin_info["resource_limits"] = normalized_limits
                self.plugin_metadata[plugin_info["name"]] = plugin_info
            logger.info(f"Registered {len(discovered)} plugin(s) from remote URL: {source_url}")
            return discovered
        except Exception:
            shutil.rmtree(extract_dir, ignore_errors=True)
            raise

    def validate_npm_package_name(self, package_name: str) -> bool:
        return bool(self.NPM_PACKAGE_PATTERN.fullmatch(package_name))

    def validate_npm_version(self, version: str) -> bool:
        return bool(self.NPM_VERSION_PATTERN.fullmatch(version))

    def parse_npm_source(self, npm_source: str) -> Dict[str, str]:
        source = npm_source.strip()
        if source.startswith("npm:"):
            source = source[4:]

        if source.startswith("@"):
            version_sep = source.rfind("@")
            if version_sep <= 0:
                raise ValueError("npm source must include package name and version")
            package_name = source[:version_sep]
            version = source[version_sep + 1:]
        else:
            if "@" not in source:
                raise ValueError("npm source must include package name and version")
            package_name, version = source.split("@", 1)

        if not package_name or not version:
            raise ValueError("npm source must include package name and version")

        if not self.validate_npm_package_name(package_name):
            raise ValueError(f"Invalid npm package name: {package_name}")

        if not self.validate_npm_version(version):
            raise ValueError(f"Invalid npm version: {version}")

        encoded_name = package_name.replace("/", "%2f")
        package_base_name = package_name.split("/")[-1]
        tarball_url = f"https://registry.npmjs.org/{encoded_name}/-/{package_base_name}-{version}.tgz"

        return {
            "source": "npm",
            "raw": npm_source,
            "package_name": package_name,
            "version": version,
            "registry": "https://registry.npmjs.org",
            "tarball_url": tarball_url,
        }

    def register_plugin_from_npm_source(self, npm_source: str) -> Dict[str, str]:
        npm_info = self.parse_npm_source(npm_source)
        logger.info(
            f"Parsed npm source package={npm_info['package_name']} version={npm_info['version']}"
        )
        return npm_info

    def _build_release_id(self, plugin_name: str, metadata: Dict[str, Any]) -> str:
        self._rollout_release_counter += 1
        version = str(metadata.get("version", "1.0.0"))
        path = str(metadata.get("path", ""))
        payload = f"{plugin_name}:{version}:{path}:{self._rollout_release_counter}".encode("utf-8")
        digest = hashlib.sha256(payload).hexdigest()[:10]
        return f"{plugin_name}-{version}-{digest}"

    def _normalize_rollout_targets(self, targets: Optional[Dict[str, Any]]) -> Dict[str, List[str]]:
        normalized: Dict[str, List[str]] = {
            "user_ids": [],
            "regions": [],
            "versions": [],
        }
        if not isinstance(targets, dict):
            return normalized

        for key in normalized:
            raw_values = targets.get(key, [])
            if isinstance(raw_values, list):
                values = [str(item).strip() for item in raw_values if str(item).strip()]
                normalized[key] = sorted(set(values))
        return normalized

    def _normalize_rollout_policy(self, policy: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        default_policy = {
            "enabled": False,
            "rollout_percentage": 0.0,
            "targets": {
                "user_ids": [],
                "regions": [],
                "versions": [],
            },
            "updated_at": datetime.utcnow().isoformat(),
        }
        if not isinstance(policy, dict):
            return default_policy

        percentage = policy.get("rollout_percentage", 0)
        try:
            rollout_percentage = float(percentage)
        except (TypeError, ValueError):
            rollout_percentage = 0.0
        rollout_percentage = max(0.0, min(100.0, rollout_percentage))

        default_policy["enabled"] = bool(policy.get("enabled", False))
        default_policy["rollout_percentage"] = rollout_percentage
        default_policy["targets"] = self._normalize_rollout_targets(policy.get("targets"))
        default_policy["updated_at"] = datetime.utcnow().isoformat()
        return default_policy

    def _ensure_runtime_route(self, plugin_name: str) -> Optional[Dict[str, Any]]:
        route = self._runtime_routes.get(plugin_name)
        if route:
            return route

        plugin_instance = self.loaded_plugins.get(plugin_name)
        metadata = self.plugin_metadata.get(plugin_name)
        if plugin_instance is None or metadata is None:
            return None

        release_id = self._build_release_id(plugin_name, metadata)
        route = {
            "plugin_name": plugin_name,
            "active_slot": "active",
            "slots": {
                "active": {
                    "slot": "active",
                    "release_id": release_id,
                    "metadata": deepcopy(metadata),
                    "plugin_instance": plugin_instance,
                    "sandbox": self._plugin_sandboxes.get(plugin_name, self.sandbox),
                    "tools": deepcopy(self._tools_registry.get(plugin_name, [])),
                    "loaded_at": datetime.utcnow().isoformat(),
                },
                "standby": None,
            },
            "rollout_policy": self._normalize_rollout_policy(None),
            "last_update": datetime.utcnow().isoformat(),
            "last_error": None,
            "last_rollback": None,
        }
        self._runtime_routes[plugin_name] = route
        return route

    def _version_matches(self, selector_version: str, rule: str) -> bool:
        selector = (selector_version or "").strip()
        target_rule = (rule or "").strip()
        if not target_rule:
            return False
        if target_rule in {"*", "x", "X"}:
            return True
        if target_rule.endswith("*"):
            prefix = target_rule[:-1]
            return selector.startswith(prefix)
        return selector == target_rule

    def _selector_matches_targets(self, selector: Dict[str, str], targets: Dict[str, List[str]]) -> bool:
        user_id = selector.get("user_id", "")
        region = selector.get("region", "")
        version = selector.get("version", "")

        user_targets = targets.get("user_ids", [])
        if user_targets and "*" not in user_targets and user_id not in user_targets:
            return False

        region_targets = targets.get("regions", [])
        if region_targets and "*" not in region_targets and region not in region_targets:
            return False

        version_targets = targets.get("versions", [])
        if version_targets and "*" not in version_targets:
            if not any(self._version_matches(version, item) for item in version_targets):
                return False

        return True

    def _selector_bucket(self, selector: Dict[str, str]) -> int:
        payload = f"{selector.get('user_id', '')}|{selector.get('region', '')}|{selector.get('version', '')}".encode("utf-8")
        return int(hashlib.sha256(payload).hexdigest()[:8], 16) % 100

    def _resolve_execution_slot(self, plugin_name: str, selector: Dict[str, str], force_slot: Optional[str] = None) -> str:
        route = self._runtime_routes.get(plugin_name)
        if route is None:
            return "active"

        if force_slot in {"active", "standby"}:
            standby_slot = route.get("slots", {}).get("standby")
            if force_slot == "standby" and standby_slot is None:
                return "active"
            return force_slot

        policy = route.get("rollout_policy", {})
        standby_slot = route.get("slots", {}).get("standby")
        if standby_slot is None:
            return "active"

        if not policy.get("enabled"):
            return route.get("active_slot", "active")

        percentage = float(policy.get("rollout_percentage", 0.0))
        if percentage <= 0:
            return route.get("active_slot", "active")

        targets = policy.get("targets", {})
        if not self._selector_matches_targets(selector, targets):
            return route.get("active_slot", "active")

        if self._selector_bucket(selector) < int(percentage):
            return "standby"
        return route.get("active_slot", "active")

    def _apply_active_route_slot(self, plugin_name: str) -> None:
        route = self._runtime_routes.get(plugin_name)
        if route is None:
            return

        active_slot_name = route.get("active_slot", "active")
        active_slot = route.get("slots", {}).get(active_slot_name)
        if not active_slot:
            return

        self.loaded_plugins[plugin_name] = active_slot["plugin_instance"]
        self._plugin_sandboxes[plugin_name] = active_slot["sandbox"]
        self._tools_registry[plugin_name] = deepcopy(active_slot.get("tools", []))
        self.plugin_metadata[plugin_name] = deepcopy(active_slot["metadata"])
        self.state_machine.set_state(plugin_name, PluginState.ENABLED)

    def _load_plugin_release(self, plugin_name: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
        plugin_path = metadata["path"]
        plugin_class = self.loader.load_module(plugin_path)
        if plugin_class is None:
            raise RuntimeError(f"Failed to load plugin class for '{plugin_name}'")

        config = {
            "name": metadata["name"],
            "version": metadata["version"],
            "description": metadata.get("description", ""),
        }

        resource_limits = metadata.get("resource_limits")
        if resource_limits:
            config["resource_limits"] = resource_limits

        validation_result = self.validator.validate_plugin(plugin_class, config)
        if not validation_result.valid:
            raise RuntimeError(f"Plugin '{plugin_name}' validation failed: {validation_result.errors}")

        plugin_instance = self.loader.instantiate_plugin(plugin_class, config)
        if plugin_instance is None:
            raise RuntimeError(f"Failed to instantiate plugin '{plugin_name}'")

        init_result = plugin_instance.initialize()
        if inspect.isawaitable(init_result):
            from .plugin_lifecycle import TransitionExecutor
            helper = TransitionExecutor(self.state_machine)
            init_result = helper._run_coroutine(init_result)
        if not init_result:
            raise RuntimeError(f"Plugin '{plugin_name}' initialization returned False")

        plugin_instance._initialized = True
        tools: List[Dict[str, Any]] = []
        if hasattr(plugin_instance, "get_tools"):
            result = plugin_instance.get_tools()
            if isinstance(result, list):
                tools = result

        manifest = metadata.get("manifest")
        if manifest:
            self.extension_registry.register_manifest(plugin_name, manifest)

        return {
            "plugin_instance": plugin_instance,
            "sandbox": self._create_plugin_sandbox(resource_limits),
            "tools": tools,
            "metadata": deepcopy(metadata),
        }

    def _cleanup_release_binding(self, plugin_name: str, binding: Optional[Dict[str, Any]]) -> None:
        if not binding:
            return
        plugin_instance = binding.get("plugin_instance")
        if plugin_instance is not None:
            try:
                plugin_instance.cleanup()
            except Exception as cleanup_error:
                logger.error(f"Plugin '{plugin_name}' cleanup error: {cleanup_error}")

    def set_rollout_policy(self, plugin_name: str, policy: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        route = self._ensure_runtime_route(plugin_name)
        if route is None:
            raise ValueError(f"Plugin '{plugin_name}' is not loaded")

        normalized = self._normalize_rollout_policy(policy)
        route["rollout_policy"] = normalized
        route["last_update"] = datetime.utcnow().isoformat()
        return self.get_plugin_rollout_status(plugin_name)

    def hot_update_plugin(
        self,
        plugin_name: str,
        rollout_policy: Optional[Dict[str, Any]] = None,
        strategy: str = "gray",
    ) -> Dict[str, Any]:
        if plugin_name not in self.plugin_metadata:
            raise ValueError(f"Plugin '{plugin_name}' not found")

        if plugin_name not in self.loaded_plugins:
            if not self.load_plugin(plugin_name):
                raise RuntimeError(f"Plugin '{plugin_name}' failed to load before hot update")

        route = self._ensure_runtime_route(plugin_name)
        if route is None:
            raise RuntimeError(f"Plugin '{plugin_name}' route init failed")

        source_metadata = deepcopy(self.plugin_metadata[plugin_name])
        scanned = self._scan_plugin_file(source_metadata["path"])
        if scanned:
            source_metadata.update(scanned)

        release_id = self._build_release_id(plugin_name, source_metadata)
        previous_active_slot = deepcopy(route["slots"]["active"])

        try:
            binding = self._load_plugin_release(plugin_name, source_metadata)
            standby_slot = {
                "slot": "standby",
                "release_id": release_id,
                "metadata": deepcopy(binding["metadata"]),
                "plugin_instance": binding["plugin_instance"],
                "sandbox": binding["sandbox"],
                "tools": deepcopy(binding["tools"]),
                "loaded_at": datetime.utcnow().isoformat(),
            }
            old_standby = route["slots"].get("standby")
            route["slots"]["standby"] = standby_slot
            self._cleanup_release_binding(plugin_name, old_standby)

            normalized_policy = self._normalize_rollout_policy(rollout_policy)
            route["rollout_policy"] = normalized_policy
            route["last_error"] = None
            route["last_update"] = datetime.utcnow().isoformat()

            if strategy in {"immediate", "force"}:
                route["slots"]["active"], route["slots"]["standby"] = route["slots"]["standby"], route["slots"]["active"]
                route["active_slot"] = "active"
                route["rollout_policy"] = self._normalize_rollout_policy({"enabled": False, "rollout_percentage": 0, "targets": {}})
                self._apply_active_route_slot(plugin_name)

            return {
                "success": True,
                "plugin_name": plugin_name,
                "strategy": strategy,
                "release_id": release_id,
                "active_release_id": route["slots"]["active"]["release_id"],
                "standby_release_id": route["slots"]["standby"]["release_id"] if route["slots"].get("standby") else None,
                "rolled_back": False,
                "rollout_policy": route["rollout_policy"],
            }
        except Exception as exc:
            route["slots"]["active"] = previous_active_slot
            route["last_error"] = str(exc)
            route["last_rollback"] = {
                "at": datetime.utcnow().isoformat(),
                "reason": str(exc),
                "active_release_id": previous_active_slot.get("release_id"),
            }
            self._apply_active_route_slot(plugin_name)
            return {
                "success": False,
                "plugin_name": plugin_name,
                "strategy": strategy,
                "release_id": release_id,
                "rolled_back": True,
                "error": str(exc),
                "active_release_id": previous_active_slot.get("release_id"),
            }

    def get_plugin_rollout_status(self, plugin_name: str) -> Dict[str, Any]:
        route = self._ensure_runtime_route(plugin_name)
        if route is None:
            raise ValueError(f"Plugin '{plugin_name}' is not loaded")

        active_slot = route.get("slots", {}).get("active")
        standby_slot = route.get("slots", {}).get("standby")
        return {
            "plugin_name": plugin_name,
            "active_release": {
                "release_id": active_slot.get("release_id") if active_slot else None,
                "version": active_slot.get("metadata", {}).get("version") if active_slot else None,
                "path": active_slot.get("metadata", {}).get("path") if active_slot else None,
                "loaded_at": active_slot.get("loaded_at") if active_slot else None,
            },
            "standby_release": {
                "release_id": standby_slot.get("release_id") if standby_slot else None,
                "version": standby_slot.get("metadata", {}).get("version") if standby_slot else None,
                "path": standby_slot.get("metadata", {}).get("path") if standby_slot else None,
                "loaded_at": standby_slot.get("loaded_at") if standby_slot else None,
            } if standby_slot else None,
            "rollout_policy": deepcopy(route.get("rollout_policy", {})),
            "last_update": route.get("last_update"),
            "last_error": route.get("last_error"),
            "last_rollback": route.get("last_rollback"),
        }

    def list_rollout_status(self) -> List[Dict[str, Any]]:
        statuses: List[Dict[str, Any]] = []
        for plugin_name in sorted(self._runtime_routes):
            statuses.append(self.get_plugin_rollout_status(plugin_name))
        return statuses

    def _scan_plugin_file(self, plugin_path: str) -> Optional[Dict[str, Any]]:
        try:
            plugin_name = os.path.splitext(os.path.basename(plugin_path))[0]
            module_name = f"plugins.{plugin_name}"

            security_scan = self._run_static_security_scan(plugin_path)
            if security_scan["blocked"]:
                logger.warning(f"Plugin '{plugin_name}' blocked by static security scan: {security_scan['reasons']}")
                return None

            spec = importlib.util.spec_from_file_location(module_name, plugin_path)
            if spec is None or spec.loader is None:
                return None

            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            plugin_classes = []
            for name, obj in inspect.getmembers(module, inspect.isclass):
                if inspect.isclass(obj) and issubclass(obj, BasePlugin) and obj is not BasePlugin:
                    plugin_classes.append(obj)

            if not plugin_classes:
                return None

            plugin_class = plugin_classes[0]

            metadata = {
                "name": getattr(plugin_class, "name", plugin_name),
                "version": getattr(plugin_class, "version", "1.0.0"),
                "description": getattr(plugin_class, "description", ""),
                "path": plugin_path,
                "class_name": plugin_class.__name__,
                "module": module_name,
                "manifest": getattr(plugin_class, "manifest", None),
                "security_scan": security_scan,
                "requested_permissions": security_scan["requested_permissions"],
            }

            return metadata

        except Exception as e:
            logger.error(f"Error scanning plugin file {plugin_path}: {e}")
            return None

    def load_plugin(self, plugin_name: str) -> bool:
        if plugin_name in self.loaded_plugins:
            logger.warning(f"Plugin '{plugin_name}' is already loaded")
            self._ensure_runtime_route(plugin_name)
            self._apply_active_route_slot(plugin_name)
            return True

        if plugin_name not in self.plugin_metadata:
            logger.error(f"Plugin '{plugin_name}' not found in discovered plugins")
            return False

        metadata = self.plugin_metadata[plugin_name]
        plugin_path = metadata["path"]
        holder: Dict[str, Any] = {}

        def _load_action() -> None:
            plugin_class = self.loader.load_module(plugin_path)
            if plugin_class is None:
                raise RuntimeError(f"Failed to load plugin class for '{plugin_name}'")

            config = {
                "name": metadata["name"],
                "version": metadata["version"],
                "description": metadata["description"],
            }

            resource_limits = metadata.get("resource_limits")
            if resource_limits:
                config["resource_limits"] = resource_limits

            validation_result = self.validator.validate_plugin(plugin_class, config)
            if not validation_result.valid:
                raise RuntimeError(f"Plugin '{plugin_name}' validation failed: {validation_result.errors}")

            if validation_result.warnings:
                logger.warning(f"Plugin '{plugin_name}' validation warnings: {validation_result.warnings}")

            plugin_instance = self.loader.instantiate_plugin(plugin_class, config)
            if plugin_instance is None:
                raise RuntimeError(f"Failed to instantiate plugin '{plugin_name}'")

            init_result = plugin_instance.initialize()
            if inspect.isawaitable(init_result):
                from .plugin_lifecycle import TransitionExecutor
                helper = TransitionExecutor(self.state_machine)
                init_result = helper._run_coroutine(init_result)
            if not init_result:
                raise RuntimeError(f"Plugin '{plugin_name}' initialization returned False")

            plugin_instance._initialized = True
            holder["plugin_instance"] = plugin_instance
            self.loaded_plugins[plugin_name] = plugin_instance
            self._plugin_sandboxes[plugin_name] = self._create_plugin_sandbox(resource_limits)
            self._register_plugin_tools(plugin_name, plugin_instance)
            manifest = metadata.get("manifest")
            if manifest:
                self.extension_registry.register_manifest(plugin_name, manifest)

        def _load_rollback(previous_state: PluginState) -> None:
            if plugin_name in self.loaded_plugins:
                instance = self.loaded_plugins[plugin_name]
                try:
                    instance.cleanup()
                except Exception as cleanup_error:
                    logger.error(f"Plugin '{plugin_name}' cleanup error during rollback: {cleanup_error}")
                self._unregister_plugin_tools(plugin_name)
                self.extension_registry.unregister_plugin(plugin_name)
                del self.loaded_plugins[plugin_name]
            self._plugin_sandboxes.pop(plugin_name, None)

        load_result = self.transition_executor.execute(
            plugin_name=plugin_name,
            plugin_instance=lambda: holder.get("plugin_instance"),
            to_state=PluginState.LOADED,
            action=_load_action,
            rollback_action=_load_rollback,
            idempotency_key=f"{plugin_name}:load",
        )

        if not load_result.success:
            logger.error(f"Plugin '{plugin_name}' load transition failed: {load_result.error}")
            return False

        enable_result = self.transition_executor.execute(
            plugin_name=plugin_name,
            plugin_instance=lambda: self.loaded_plugins.get(plugin_name),
            to_state=PluginState.ENABLED,
            action=None,
            rollback_action=lambda previous_state: self.loaded_plugins[plugin_name].rollback(previous_state.value),
            idempotency_key=f"{plugin_name}:enable",
        )

        if not enable_result.success:
            logger.error(f"Plugin '{plugin_name}' enable transition failed: {enable_result.error}")
            self.unload_plugin(plugin_name)
            return False

        logger.info(f"Plugin '{plugin_name}' loaded successfully")
        self._ensure_runtime_route(plugin_name)
        self._apply_active_route_slot(plugin_name)
        _meta = self.plugin_metadata.get(plugin_name, {})
        self.hot_update_manager.register_initial(
            plugin_name=plugin_name,
            version=_meta.get("version", "1.0.0"),
            metadata=_meta,
            plugin_instance=self.loaded_plugins.get(plugin_name),
        )
        return True

    def unload_plugin(self, plugin_name: str) -> bool:
        if plugin_name not in self.loaded_plugins:
            logger.warning(f"Plugin '{plugin_name}' is not loaded")
            return False

        plugin_instance = self.loaded_plugins[plugin_name]

        def _unload_action() -> None:
            try:
                plugin_instance.cleanup()
            finally:
                self._unregister_plugin_tools(plugin_name)
                self.extension_registry.unregister_plugin(plugin_name)
                if plugin_name in self.loaded_plugins:
                    del self.loaded_plugins[plugin_name]
                self._plugin_sandboxes.pop(plugin_name, None)

        def _unload_rollback(previous_state: PluginState) -> None:
            self.loaded_plugins[plugin_name] = plugin_instance
            metadata = self.plugin_metadata.get(plugin_name, {})
            self._plugin_sandboxes[plugin_name] = self._create_plugin_sandbox(metadata.get("resource_limits"))
            self._register_plugin_tools(plugin_name, plugin_instance)
            manifest = metadata.get("manifest")
            if manifest:
                self.extension_registry.register_manifest(plugin_name, manifest)
            plugin_instance.rollback(previous_state.value)

        result = self.transition_executor.execute(
            plugin_name=plugin_name,
            plugin_instance=plugin_instance,
            to_state=PluginState.UNLOADED,
            action=_unload_action,
            rollback_action=_unload_rollback,
            idempotency_key=f"{plugin_name}:unload",
        )

        if not result.success:
            logger.error(f"Plugin '{plugin_name}' unload failed: {result.error}")
            return False

        logger.info(f"Plugin '{plugin_name}' unloaded successfully")
        return True

    def enable_plugin(self, plugin_name: str) -> bool:
        if plugin_name not in self.loaded_plugins:
            logger.error(f"Plugin '{plugin_name}' is not loaded")
            return False

        plugin_instance = self.loaded_plugins[plugin_name]
        result = self.transition_executor.execute(
            plugin_name=plugin_name,
            plugin_instance=plugin_instance,
            to_state=PluginState.ENABLED,
            action=None,
            rollback_action=lambda previous_state: plugin_instance.rollback(previous_state.value),
            idempotency_key=f"{plugin_name}:enable",
        )
        if not result.success:
            logger.error(f"Plugin '{plugin_name}' enable failed: {result.error}")
        return result.success

    def disable_plugin(self, plugin_name: str) -> bool:
        if plugin_name not in self.loaded_plugins:
            logger.error(f"Plugin '{plugin_name}' is not loaded")
            return False

        plugin_instance = self.loaded_plugins[plugin_name]
        result = self.transition_executor.execute(
            plugin_name=plugin_name,
            plugin_instance=plugin_instance,
            to_state=PluginState.DISABLED,
            action=None,
            rollback_action=lambda previous_state: plugin_instance.rollback(previous_state.value),
            idempotency_key=f"{plugin_name}:disable",
        )
        if not result.success:
            logger.error(f"Plugin '{plugin_name}' disable failed: {result.error}")
        return result.success

    def reload_plugin(self, plugin_name: str) -> bool:
        logger.info(f"Reloading plugin '{plugin_name}'")

        if plugin_name in self.loaded_plugins:
            result = self.transition_executor.execute(
                plugin_name=plugin_name,
                plugin_instance=self.loaded_plugins[plugin_name],
                to_state=PluginState.UPDATING,
                action=None,
                rollback_action=lambda previous_state: self.loaded_plugins[plugin_name].rollback(previous_state.value),
                idempotency_key=f"{plugin_name}:updating",
            )
            if not result.success:
                logger.error(f"Failed to set updating state for plugin '{plugin_name}'")
                return False

            if not self.unload_plugin(plugin_name):
                logger.error(f"Failed to unload plugin '{plugin_name}' before reload")
                return False

        importlib.invalidate_imports()

        if plugin_name in self.plugin_metadata:
            metadata = self.plugin_metadata[plugin_name]
            spec = importlib.util.spec_from_file_location(metadata["module"], metadata["path"])
            if spec and spec.loader:
                importlib.reload(spec.loader.__class__)

        return self.load_plugin(plugin_name)

    def execute_plugin(self, plugin_name: str, method: str, **kwargs) -> Dict[str, Any]:
        if plugin_name not in self.loaded_plugins:
            logger.error(f"Plugin '{plugin_name}' is not loaded")
            return {
                "status": "error",
                "message": f"Plugin '{plugin_name}' is not loaded",
            }

        permission_error = self._enforce_runtime_permissions(plugin_name)
        if permission_error:
            logger.warning(
                f"Plugin '{plugin_name}' runtime permission denied: {permission_error['required_permissions']}"
            )
            return permission_error

        plugin_state = self.state_machine.get_state(plugin_name)
        if plugin_state != PluginState.ENABLED:
            logger.error(f"Plugin '{plugin_name}' is not enabled, current state: {plugin_state.value}")
            return {
                "status": "error",
                "message": f"Plugin '{plugin_name}' is not enabled",
            }

        plugin_instance = self.loaded_plugins[plugin_name]

        if not hasattr(plugin_instance, method):
            logger.error(f"Plugin '{plugin_name}' does not have method '{method}'")
            return {
                "status": "error",
                "message": f"Plugin '{plugin_name}' does not have method '{method}'",
            }

        sandbox = self._plugin_sandboxes.get(plugin_name, self.sandbox)
        return sandbox.execute_plugin_sync(plugin_instance, method, **kwargs)

    async def execute_plugin_async(self, plugin_name: str, method: str, **kwargs) -> Dict[str, Any]:
        if plugin_name not in self.loaded_plugins:
            logger.error(f"Plugin '{plugin_name}' is not loaded")
            return {
                "status": "error",
                "message": f"Plugin '{plugin_name}' is not loaded",
            }

        permission_error = self._enforce_runtime_permissions(plugin_name)
        if permission_error:
            logger.warning(
                f"Plugin '{plugin_name}' runtime permission denied: {permission_error['required_permissions']}"
            )
            return permission_error

        plugin_state = self.state_machine.get_state(plugin_name)
        if plugin_state != PluginState.ENABLED:
            logger.error(f"Plugin '{plugin_name}' is not enabled, current state: {plugin_state.value}")
            return {
                "status": "error",
                "message": f"Plugin '{plugin_name}' is not enabled",
            }

        plugin_instance = self.loaded_plugins[plugin_name]
        sandbox = self._plugin_sandboxes.get(plugin_name, self.sandbox)
        return await sandbox.execute_plugin(plugin_instance, method, **kwargs)

    def get_plugin_tools(self, plugin_name: str) -> List[Dict[str, Any]]:
        if plugin_name in self._tools_registry:
            return self._tools_registry[plugin_name]

        if plugin_name not in self.loaded_plugins:
            logger.warning(f"Plugin '{plugin_name}' is not loaded, cannot get tools")
            return []

        plugin_instance = self.loaded_plugins[plugin_name]
        tools = []

        if hasattr(plugin_instance, "get_tools"):
            try:
                plugin_tools = plugin_instance.get_tools()
                if isinstance(plugin_tools, list):
                    tools = plugin_tools
            except Exception as e:
                logger.error(f"Error getting tools from plugin '{plugin_name}': {e}")

        for attr_name in dir(plugin_instance):
            if attr_name.startswith("tool_") or attr_name.startswith("get_tool_"):
                attr = getattr(plugin_instance, attr_name)
                if callable(attr):
                    tool_def = {
                        "name": attr_name.replace("tool_", "").replace("get_tool_", ""),
                        "description": getattr(attr, "__doc__", ""),
                        "method": attr_name,
                        "plugin": plugin_name,
                    }
                    tools.append(tool_def)

        self._tools_registry[plugin_name] = tools
        return tools

    def get_all_tools(self) -> List[Dict[str, Any]]:
        all_tools = []
        for plugin_name in self.loaded_plugins:
            tools = self.get_plugin_tools(plugin_name)
            all_tools.extend(tools)
        return all_tools

    def _register_plugin_tools(self, plugin_name: str, plugin_instance: BasePlugin) -> None:
        if not hasattr(plugin_instance, "get_tools"):
            return

        try:
            tools = plugin_instance.get_tools()
            if isinstance(tools, list):
                self._tools_registry[plugin_name] = tools
                logger.debug(f"Registered {len(tools)} tools for plugin '{plugin_name}'")
        except Exception as e:
            logger.error(f"Error registering tools for plugin '{plugin_name}': {e}")

    def _unregister_plugin_tools(self, plugin_name: str) -> None:
        if plugin_name in self._tools_registry:
            del self._tools_registry[plugin_name]
            logger.debug(f"Unregistered tools for plugin '{plugin_name}'")

    def list_loaded_plugins(self) -> List[str]:
        return list(self.loaded_plugins.keys())

    def list_available_plugins(self) -> List[str]:
        return list(self.plugin_metadata.keys())

    def get_plugin_info(self, plugin_name: str) -> Optional[Dict[str, Any]]:
        if plugin_name in self.plugin_metadata:
            info = self.plugin_metadata[plugin_name].copy()
            info["loaded"] = plugin_name in self.loaded_plugins
            info["state"] = self.state_machine.get_state(plugin_name).value
            return info
        return None


    def _normalize_manifest_dependencies(self, dependencies: Any) -> Dict[str, str]:
        normalized: Dict[str, str] = {}
        if isinstance(dependencies, dict):
            for name, version_range in dependencies.items():
                if isinstance(name, str) and isinstance(version_range, str) and name.strip() and version_range.strip():
                    normalized[name.strip()] = version_range.strip()
            return normalized

        if isinstance(dependencies, list):
            for item in dependencies:
                if isinstance(item, str) and item.strip():
                    normalized[item.strip()] = "*"
                elif isinstance(item, dict):
                    name = item.get("name")
                    version_range = item.get("version") or item.get("range") or "*"
                    if isinstance(name, str) and isinstance(version_range, str) and name.strip() and version_range.strip():
                        normalized[name.strip()] = version_range.strip()
        return normalized

    def _normalize_plugin_dependencies(self, dependencies: Any) -> Dict[str, str]:
        normalized = self._normalize_manifest_dependencies(dependencies)
        plugin_only: Dict[str, str] = {}
        for plugin_name, version_range in normalized.items():
            if plugin_name in self.plugin_metadata or plugin_name:
                plugin_only[plugin_name] = version_range
        return plugin_only

    def _parse_semver(self, version: str) -> Tuple[int, int, int]:
        if not isinstance(version, str):
            raise ValueError("semver must be string")
        value = version.strip()
        if not value:
            raise ValueError("semver is empty")
        core = value.split("+", 1)[0].split("-", 1)[0]
        parts = core.split(".")
        if len(parts) > 3:
            raise ValueError(f"invalid semver: {version}")
        while len(parts) < 3:
            parts.append("0")
        if not all(part.isdigit() for part in parts):
            raise ValueError(f"invalid semver: {version}")
        return int(parts[0]), int(parts[1]), int(parts[2])

    def _compare_semver(self, left: Tuple[int, int, int], right: Tuple[int, int, int]) -> int:
        if left == right:
            return 0
        if left < right:
            return -1
        return 1

    def _inc_major(self, version: Tuple[int, int, int]) -> Tuple[int, int, int]:
        return version[0] + 1, 0, 0

    def _inc_minor(self, version: Tuple[int, int, int]) -> Tuple[int, int, int]:
        return version[0], version[1] + 1, 0

    def _inc_patch(self, version: Tuple[int, int, int]) -> Tuple[int, int, int]:
        return version[0], version[1], version[2] + 1

    def _parse_wildcard_range(self, token: str) -> Optional[List[Tuple[Optional[Tuple[int, int, int]], bool, Optional[Tuple[int, int, int]], bool]]]:
        lowered = token.strip().lower()
        if lowered in {"*", "x"}:
            return [(None, True, None, True)]

        parts = lowered.split(".")
        if not any(part in {"x", "*"} for part in parts):
            return None

        if len(parts) == 1:
            if parts[0] in {"x", "*"}:
                return [(None, True, None, True)]
            major = int(parts[0])
            lower = (major, 0, 0)
            upper = (major + 1, 0, 0)
            return [(lower, True, upper, False)]

        if len(parts) == 2:
            major = int(parts[0])
            if parts[1] in {"x", "*"}:
                return [((major, 0, 0), True, (major + 1, 0, 0), False)]
            minor = int(parts[1])
            return [((major, minor, 0), True, (major, minor + 1, 0), False)]

        if len(parts) == 3:
            major_part, minor_part, patch_part = parts
            if major_part in {"x", "*"}:
                return [(None, True, None, True)]
            major = int(major_part)
            if minor_part in {"x", "*"}:
                return [((major, 0, 0), True, (major + 1, 0, 0), False)]
            minor = int(minor_part)
            if patch_part in {"x", "*"}:
                return [((major, minor, 0), True, (major, minor + 1, 0), False)]
            patch = int(patch_part)
            return [((major, minor, patch), True, (major, minor, patch), True)]

        raise ValueError(f"invalid wildcard semver range: {token}")

    def _intersect_interval(
        self,
        left: Tuple[Optional[Tuple[int, int, int]], bool, Optional[Tuple[int, int, int]], bool],
        right: Tuple[Optional[Tuple[int, int, int]], bool, Optional[Tuple[int, int, int]], bool],
    ) -> Optional[Tuple[Optional[Tuple[int, int, int]], bool, Optional[Tuple[int, int, int]], bool]]:
        left_lower, left_lower_inclusive, left_upper, left_upper_inclusive = left
        right_lower, right_lower_inclusive, right_upper, right_upper_inclusive = right

        lower = left_lower
        lower_inclusive = left_lower_inclusive
        if right_lower is not None:
            if lower is None or self._compare_semver(right_lower, lower) > 0:
                lower = right_lower
                lower_inclusive = right_lower_inclusive
            elif lower is not None and self._compare_semver(right_lower, lower) == 0:
                lower_inclusive = lower_inclusive and right_lower_inclusive

        upper = left_upper
        upper_inclusive = left_upper_inclusive
        if right_upper is not None:
            if upper is None or self._compare_semver(right_upper, upper) < 0:
                upper = right_upper
                upper_inclusive = right_upper_inclusive
            elif upper is not None and self._compare_semver(right_upper, upper) == 0:
                upper_inclusive = upper_inclusive and right_upper_inclusive

        if lower is not None and upper is not None:
            cmp_value = self._compare_semver(lower, upper)
            if cmp_value > 0:
                return None
            if cmp_value == 0 and not (lower_inclusive and upper_inclusive):
                return None

        return lower, lower_inclusive, upper, upper_inclusive

    def _intersect_interval_list(
        self,
        left: List[Tuple[Optional[Tuple[int, int, int]], bool, Optional[Tuple[int, int, int]], bool]],
        right: List[Tuple[Optional[Tuple[int, int, int]], bool, Optional[Tuple[int, int, int]], bool]],
    ) -> List[Tuple[Optional[Tuple[int, int, int]], bool, Optional[Tuple[int, int, int]], bool]]:
        intersections: List[Tuple[Optional[Tuple[int, int, int]], bool, Optional[Tuple[int, int, int]], bool]] = []
        for left_item in left:
            for right_item in right:
                merged = self._intersect_interval(left_item, right_item)
                if merged is not None:
                    intersections.append(merged)
        return intersections

    def _parse_semver_range(
        self,
        version_range: str,
    ) -> List[Tuple[Optional[Tuple[int, int, int]], bool, Optional[Tuple[int, int, int]], bool]]:
        value = (version_range or "*").strip()
        if not value:
            value = "*"

        or_clauses = [item.strip() for item in value.split("||") if item.strip()]
        if not or_clauses:
            or_clauses = ["*"]

        all_intervals: List[Tuple[Optional[Tuple[int, int, int]], bool, Optional[Tuple[int, int, int]], bool]] = []
        for clause in or_clauses:
            wildcard = self._parse_wildcard_range(clause)
            if wildcard is not None:
                all_intervals.extend(wildcard)
                continue

            tokens = [token for token in clause.split() if token]
            if not tokens:
                all_intervals.append((None, True, None, True))
                continue

            clause_intervals: List[Tuple[Optional[Tuple[int, int, int]], bool, Optional[Tuple[int, int, int]], bool]] = [(None, True, None, True)]

            for token in tokens:
                bounds: List[Tuple[Optional[Tuple[int, int, int]], bool, Optional[Tuple[int, int, int]], bool]]
                if token.startswith("^"):
                    lower = self._parse_semver(token[1:])
                    if lower[0] > 0:
                        upper = self._inc_major(lower)
                    elif lower[1] > 0:
                        upper = self._inc_minor(lower)
                    else:
                        upper = self._inc_patch(lower)
                    bounds = [(lower, True, upper, False)]
                elif token.startswith("~"):
                    lower = self._parse_semver(token[1:])
                    upper = self._inc_minor(lower)
                    bounds = [(lower, True, upper, False)]
                elif token.startswith(">="):
                    lower = self._parse_semver(token[2:])
                    bounds = [(lower, True, None, True)]
                elif token.startswith("<="):
                    upper = self._parse_semver(token[2:])
                    bounds = [(None, True, upper, True)]
                elif token.startswith(">"):
                    lower = self._parse_semver(token[1:])
                    bounds = [(lower, False, None, True)]
                elif token.startswith("<"):
                    upper = self._parse_semver(token[1:])
                    bounds = [(None, True, upper, False)]
                elif token.startswith("="):
                    exact = self._parse_semver(token[1:])
                    bounds = [(exact, True, exact, True)]
                else:
                    wildcard_token = self._parse_wildcard_range(token)
                    if wildcard_token is not None:
                        bounds = wildcard_token
                    else:
                        exact = self._parse_semver(token)
                        bounds = [(exact, True, exact, True)]

                clause_intervals = self._intersect_interval_list(clause_intervals, bounds)
                if not clause_intervals:
                    break

            all_intervals.extend(clause_intervals)

        return all_intervals

    def _satisfies_semver_range(self, version: str, version_range: str) -> bool:
        parsed_version = self._parse_semver(version)
        intervals = self._parse_semver_range(version_range)
        for lower, lower_inclusive, upper, upper_inclusive in intervals:
            if lower is not None:
                lower_cmp = self._compare_semver(parsed_version, lower)
                if lower_cmp < 0 or (lower_cmp == 0 and not lower_inclusive):
                    continue
            if upper is not None:
                upper_cmp = self._compare_semver(parsed_version, upper)
                if upper_cmp > 0 or (upper_cmp == 0 and not upper_inclusive):
                    continue
            return True
        return False

    def _ranges_compatible(self, left: str, right: str) -> bool:
        left_intervals = self._parse_semver_range(left)
        right_intervals = self._parse_semver_range(right)
        return bool(self._intersect_interval_list(left_intervals, right_intervals))

    def _format_semver(self, version: Tuple[int, int, int]) -> str:
        return f"{version[0]}.{version[1]}.{version[2]}"

    def _format_interval_as_range(
        self,
        interval: Tuple[Optional[Tuple[int, int, int]], bool, Optional[Tuple[int, int, int]], bool],
    ) -> str:
        lower, lower_inclusive, upper, upper_inclusive = interval
        parts: List[str] = []
        if lower is not None:
            op = ">=" if lower_inclusive else ">"
            parts.append(f"{op}{self._format_semver(lower)}")
        if upper is not None:
            op = "<=" if upper_inclusive else "<"
            parts.append(f"{op}{self._format_semver(upper)}")
        if not parts:
            return "*"
        if lower is not None and upper is not None and lower == upper and lower_inclusive and upper_inclusive:
            return self._format_semver(lower)
        return " ".join(parts)

    def _suggest_common_range(self, ranges: List[str]) -> Optional[str]:
        if not ranges:
            return None
        try:
            merged = self._parse_semver_range(ranges[0])
            for item in ranges[1:]:
                merged = self._intersect_interval_list(merged, self._parse_semver_range(item))
                if not merged:
                    return None
            return self._format_interval_as_range(merged[0])
        except ValueError:
            return None

    def build_dependency_graph(self) -> Dict[str, Any]:
        nodes: List[Dict[str, Any]] = []
        edges: List[Dict[str, Any]] = []
        missing_dependencies: List[Dict[str, str]] = []

        for plugin_name, metadata in self.plugin_metadata.items():
            manifest = metadata.get("manifest") or {}
            version = metadata.get("version", "0.0.0")

            nodes.append(
                {
                    "name": plugin_name,
                    "version": version,
                    "dependencies": self._normalize_manifest_dependencies(manifest.get("dependencies", {})),
                    "plugin_dependencies": self._normalize_plugin_dependencies(manifest.get("pluginDependencies", {})),
                }
            )

            plugin_dependencies = self._normalize_plugin_dependencies(manifest.get("pluginDependencies", {}))
            for dependency_name, version_range in plugin_dependencies.items():
                target = self.plugin_metadata.get(dependency_name)
                if target is None:
                    edges.append(
                        {
                            "from": plugin_name,
                            "to": dependency_name,
                            "version_range": version_range,
                            "status": "missing",
                        }
                    )
                    missing_dependencies.append(
                        {
                            "plugin": plugin_name,
                            "dependency": dependency_name,
                            "version_range": version_range,
                        }
                    )
                    continue

                target_version = str(target.get("version", "0.0.0"))
                satisfied = False
                try:
                    satisfied = self._satisfies_semver_range(target_version, version_range)
                except ValueError:
                    satisfied = False

                edges.append(
                    {
                        "from": plugin_name,
                        "to": dependency_name,
                        "version_range": version_range,
                        "resolved_version": target_version,
                        "status": "satisfied" if satisfied else "version_mismatch",
                    }
                )

        return {
            "nodes": nodes,
            "edges": edges,
            "missing_dependencies": missing_dependencies,
        }

    def _detect_dependency_cycles(self, graph: Dict[str, Any]) -> List[List[str]]:
        adjacency: Dict[str, List[str]] = {}
        for edge in graph.get("edges", []):
            if edge.get("status") == "missing":
                continue
            source = edge.get("from")
            target = edge.get("to")
            if not isinstance(source, str) or not isinstance(target, str):
                continue
            adjacency.setdefault(source, []).append(target)

        visited: Set[str] = set()
        stack: List[str] = []
        stack_set: Set[str] = set()
        cycles: List[List[str]] = []

        def dfs(node: str) -> None:
            visited.add(node)
            stack.append(node)
            stack_set.add(node)

            for next_node in adjacency.get(node, []):
                if next_node not in visited:
                    dfs(next_node)
                elif next_node in stack_set:
                    start_index = stack.index(next_node)
                    cycle = stack[start_index:] + [next_node]
                    if cycle not in cycles:
                        cycles.append(cycle)

            stack.pop()
            stack_set.remove(node)

        for node in adjacency:
            if node not in visited:
                dfs(node)

        return cycles

    def _build_dependency_suggestions(
        self,
        graph: Dict[str, Any],
        plugin_dependency_issues: List[Dict[str, Any]],
        external_conflicts: List[Dict[str, Any]],
        cycles: List[List[str]],
    ) -> List[Dict[str, Any]]:
        suggestions: List[Dict[str, Any]] = []

        for issue in plugin_dependency_issues:
            issue_type = issue.get("type")
            if issue_type == "missing_plugin":
                suggestions.append(
                    {
                        "type": "install_plugin_dependency",
                        "plugin": issue["plugin"],
                        "dependency": issue["dependency"],
                        "target_range": issue.get("version_range", "*"),
                    }
                )
            if issue_type == "plugin_version_mismatch":
                suggestions.append(
                    {
                        "type": "align_plugin_dependency_version",
                        "plugin": issue["plugin"],
                        "dependency": issue["dependency"],
                        "required_range": issue["version_range"],
                        "current_version": issue.get("resolved_version"),
                    }
                )

        for conflict in external_conflicts:
            target_range = self._suggest_common_range([item["range"] for item in conflict.get("requirements", [])])
            suggestions.append(
                {
                    "type": "align_external_dependency_range",
                    "package": conflict["package"],
                    "target_range": target_range,
                    "affected_plugins": [item["plugin"] for item in conflict.get("requirements", [])],
                }
            )

        for cycle in cycles:
            suggestions.append(
                {
                    "type": "break_dependency_cycle",
                    "cycle": cycle,
                    "hint": "调整其中一个插件的 pluginDependencies，解除环形依赖",
                }
            )

        edge_count = len(graph.get("edges", []))
        if edge_count == 0:
            suggestions.append(
                {
                    "type": "no_dependency_declared",
                    "hint": "当前插件未声明依赖，可在 manifest 中添加 dependencies 或 pluginDependencies",
                }
            )

        return suggestions

    def analyze_dependency_conflicts(self) -> Dict[str, Any]:
        graph = self.build_dependency_graph()

        plugin_dependency_issues: List[Dict[str, Any]] = []
        for edge in graph["edges"]:
            if edge["status"] == "missing":
                plugin_dependency_issues.append(
                    {
                        "type": "missing_plugin",
                        "plugin": edge["from"],
                        "dependency": edge["to"],
                        "version_range": edge["version_range"],
                    }
                )
            if edge["status"] == "version_mismatch":
                plugin_dependency_issues.append(
                    {
                        "type": "plugin_version_mismatch",
                        "plugin": edge["from"],
                        "dependency": edge["to"],
                        "version_range": edge["version_range"],
                        "resolved_version": edge.get("resolved_version"),
                    }
                )

        package_requirements: Dict[str, List[Dict[str, str]]] = {}
        for node in graph["nodes"]:
            plugin_name = node["name"]
            for package_name, version_range in node.get("dependencies", {}).items():
                package_requirements.setdefault(package_name, []).append(
                    {
                        "plugin": plugin_name,
                        "range": version_range,
                    }
                )

        external_dependency_conflicts: List[Dict[str, Any]] = []
        for package_name, requirements in package_requirements.items():
            if len(requirements) < 2:
                continue

            has_conflict = False
            pairwise_conflicts: List[Dict[str, Any]] = []
            for index in range(len(requirements)):
                for other_index in range(index + 1, len(requirements)):
                    left = requirements[index]
                    right = requirements[other_index]
                    compatible = False
                    try:
                        compatible = self._ranges_compatible(left["range"], right["range"])
                    except ValueError:
                        compatible = False
                    if not compatible:
                        has_conflict = True
                        pairwise_conflicts.append(
                            {
                                "left_plugin": left["plugin"],
                                "left_range": left["range"],
                                "right_plugin": right["plugin"],
                                "right_range": right["range"],
                            }
                        )

            if has_conflict:
                external_dependency_conflicts.append(
                    {
                        "package": package_name,
                        "requirements": requirements,
                        "pairwise_conflicts": pairwise_conflicts,
                    }
                )

        cycles = self._detect_dependency_cycles(graph)
        suggestions = self._build_dependency_suggestions(
            graph,
            plugin_dependency_issues,
            external_dependency_conflicts,
            cycles,
        )

        has_conflicts = bool(plugin_dependency_issues or external_dependency_conflicts or cycles)
        return {
            "has_conflicts": has_conflicts,
            "plugin_dependency_issues": plugin_dependency_issues,
            "external_dependency_conflicts": external_dependency_conflicts,
            "cycles": cycles,
            "suggestions": suggestions,
        }

    def get_dependency_diagnostics(self) -> Dict[str, Any]:
        graph = self.build_dependency_graph()
        analysis = self.analyze_dependency_conflicts()
        return {
            "graph": graph,
            "analysis": analysis,
        }

    def get_plugin_dependency_info(self, plugin_name: str) -> Optional[Dict[str, Any]]:
        if plugin_name not in self.plugin_metadata:
            return None

        graph = self.build_dependency_graph()
        node = None
        for item in graph["nodes"]:
            if item["name"] == plugin_name:
                node = item
                break

        dependency_edges = [edge for edge in graph["edges"] if edge.get("from") == plugin_name]
        return {
            "plugin": plugin_name,
            "version": self.plugin_metadata[plugin_name].get("version", "0.0.0"),
            "dependencies": node.get("dependencies", {}) if node else {},
            "plugin_dependencies": node.get("plugin_dependencies", {}) if node else {},
            "resolved": dependency_edges,
        }

    def get_manager_stats(self) -> Dict[str, Any]:
        sandbox_stats = self.sandbox.get_execution_stats()
        plugin_sandbox_stats = {
            name: sandbox.get_execution_stats() for name, sandbox in self._plugin_sandboxes.items()
        }
        return {
            "plugins_dir": self.plugins_dir,
            "available_plugins": len(self.plugin_metadata),
            "loaded_plugins": len(self.loaded_plugins),
            "registered_tools": sum(len(tools) for tools in self._tools_registry.values()),
            "registered_extensions": self.extension_registry.get_registry_snapshot(),
            "sandbox_stats": sandbox_stats,
            "plugin_sandbox_stats": plugin_sandbox_stats,
            "states": {name: self.state_machine.get_state(name).value for name in self.plugin_metadata},
            "permission_status": {
                name: {
                    "requested": self.plugin_metadata.get(name, {}).get("requested_permissions", []),
                    "granted": sorted(self._runtime_permission_store.get(name, set())),
                }
                for name in self.plugin_metadata
            },
        }

    def rollback_plugin(
        self,
        plugin_name: str,
        snapshot_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        if plugin_name not in self.plugin_metadata:
            raise ValueError(f"Plugin '{plugin_name}' not found")

        def _restore(snapshot: Dict[str, Any]) -> Any:
            meta = snapshot.get("metadata", {})
            path = meta.get("path", "")
            if not path or not os.path.exists(path):
                raise RuntimeError(
                    f"Cannot restore plugin '{plugin_name}': source path not found: {path}"
                )
            plugin_class = self.loader.load_module(path)
            if plugin_class is None:
                raise RuntimeError(
                    f"Failed to load plugin class from '{path}' during rollback"
                )
            config = {
                "name": meta.get("name", plugin_name),
                "version": meta.get("version", "1.0.0"),
                "description": meta.get("description", ""),
            }
            instance = self.loader.instantiate_plugin(plugin_class, config)
            if instance is None:
                raise RuntimeError(
                    f"Failed to instantiate plugin '{plugin_name}' during rollback"
                )
            instance.initialize()
            instance._initialized = True
            return instance

        result = self.hot_update_manager.rollback(
            plugin_name=plugin_name,
            snapshot_id=snapshot_id,
            restore_fn=_restore,
        )

        restored_instance = self.hot_update_manager._slots.get(plugin_name, {}).get(
            "active", {}
        ).get("plugin_instance")
        if restored_instance is not None:
            self.loaded_plugins[plugin_name] = restored_instance
            self._register_plugin_tools(plugin_name, restored_instance)

        logger.info(
            f"Plugin '{plugin_name}' rolled back to version '{result['rolled_back_to']}'"
        )
        return result

