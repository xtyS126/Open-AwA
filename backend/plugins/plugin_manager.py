"""
插件系统模块，负责插件定义、加载、校验、沙箱隔离、生命周期或扩展协议处理。
这一层通常同时涉及可扩展性、安全性与运行时状态管理。
"""

import ast
import hashlib
import http.client
import importlib
import inspect
import io
import json
import os
import re
import shutil
import sys
import ssl
import tempfile
import urllib.parse
import zipfile
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

import ipaddress
import socket
import httpx
from loguru import logger

from .base_plugin import BasePlugin
from .extension_protocol import ExtensionRegistry
from .hot_update_manager import HotUpdateManager, RollbackManager
from .plugin_lifecycle import PluginState, PluginStateMachine, TransitionExecutor
from .plugin_loader import PluginLoader
from .plugin_sandbox import PluginSandbox
from .plugin_validator import PluginValidator


class PluginManager:
    """
    插件管理器，负责插件的发现、加载、校验、沙箱隔离和生命周期管理。
    支持从本地文件、远程 URL 和 NPM 源注册插件，提供权限控制和灰度发布能力。
    """
    # 允许下载插件的域名白名单，可通过配置扩展
    ALLOWED_DOWNLOAD_DOMAINS: Set[str] = {
        "github.com",
        "raw.githubusercontent.com",
        "gitlab.com",
        "gitee.com",
        "pypi.org",
        "files.pythonhosted.org",
        "registry.npmjs.org",
    }

    # 最大允许下载的插件包体积（字节），默认 50MB
    MAX_DOWNLOAD_SIZE: int = 50 * 1024 * 1024

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
    RUNTIME_PERMISSION_BYPASS_METHODS = {
        "get_help",
    }

    def __init__(self, plugins_dir: Optional[str] = None, sandbox_defaults: Optional[Dict[str, Any]] = None):
        """
        初始化插件管理器。
        
        Args:
            plugins_dir: 插件目录路径，默认为项目根目录下的 plugins 文件夹。
            sandbox_defaults: 沙箱默认资源配置。
        """
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
        """
        获取默认的插件目录路径，若不存在则自动创建。
        
        Returns:
            插件目录的绝对路径。
        """
        current_dir = os.path.dirname(os.path.abspath(__file__))
        repo_root_dir = os.path.abspath(os.path.join(current_dir, "..", ".."))
        default_dir = os.path.join(repo_root_dir, "plugins")
        if not os.path.exists(default_dir):
            os.makedirs(default_dir, exist_ok=True)
            logger.info(f"Created default plugins directory: {default_dir}")
        return default_dir

    def _normalize_resource_limits(self, resource_limits: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        规范化资源配置参数。
        
        Args:
            resource_limits: 原始资源配置。
            
        Returns:
            规范化后的资源配置字典。
        """
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
        """
        创建插件沙箱实例。
        
        Args:
            resource_limits: 可选的资源限制配置。
            
        Returns:
            配置好的插件沙箱实例。
        """
        merged = dict(self._sandbox_defaults)
        if resource_limits:
            merged.update(self._normalize_resource_limits(resource_limits))
        return PluginSandbox(**merged)

    def _get_node_name(self, node: ast.AST) -> str:
        """
        从 AST 节点中提取可读的标识符名称。
        当前支持 `Name`、`Attribute` 与 `Call` 三类节点，用于静态风险分析时还原导入名、调用名和属性访问链路。
        """
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            base = self._get_node_name(node.value)
            return f"{base}.{node.attr}" if base else node.attr
        if isinstance(node, ast.Call):
            return self._get_node_name(node.func)
        return ""

    def _collect_static_risk_tokens(self, tree: ast.AST) -> Set[str]:
        """
        从 AST 中收集静态风险标记，包括导入名、调用名等。
        
        Args:
            tree: Python 源码的抽象语法树。
            
        Returns:
            风险标记集合。
        """
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
        """
        将收集到的标记与危险模式进行匹配。
        
        Args:
            tokens: 风险标记集合。
            
        Returns:
            匹配到的危险模式集合。
        """
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
        """
        根据匹配的危险模式推导所需的权限。
        
        Args:
            matched_patterns: 匹配到的危险模式集合。
            
        Returns:
            所需权限集合。
        """
        requested: Set[str] = set()
        for permission, patterns in self.PERMISSION_TO_PATTERNS.items():
            for pattern in patterns:
                if any(match == pattern or pattern in match for match in matched_patterns):
                    requested.add(permission)
                    break
        return requested

    def _run_static_security_scan(self, plugin_path: str) -> Dict[str, Any]:
        """
        对插件源码进行静态安全扫描。
        
        Args:
            plugin_path: 插件文件路径。
            
        Returns:
            包含扫描结果的字典，包括是否阻止、原因、匹配模式和所需权限。
        """
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
        """
        为插件授权指定权限。
        
        Args:
            plugin_name: 插件名称。
            permissions: 权限列表。
            
        Returns:
            授权结果，包含已授权和缺失的权限信息。
        """
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
        """
        撤销插件的指定权限。
        
        Args:
            plugin_name: 插件名称。
            permissions: 要撤销的权限列表。
            
        Returns:
            撤销结果，包含当前权限状态。
        """
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
        """
        获取插件的权限状态。
        
        Args:
            plugin_name: 插件名称。
            
        Returns:
            权限状态信息，包含所需、已授权和缺失的权限。
        """
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

    def _enforce_runtime_permissions(self, plugin_name: str) -> None:
        """
        检查并强制执行插件的运行时权限。
        权限不足时直接抛出 PermissionError，避免调用方遗漏检查。
        
        Args:
            plugin_name: 插件名称。
            
        Raises:
            PermissionError: 插件缺少必要的运行权限。
        """
        status = self.get_plugin_permission_status(plugin_name)
        if status["missing_permissions"]:
            raise PermissionError(
                f"Plugin '{plugin_name}' 缺少运行权限: {status['missing_permissions']}"
            )

    def _should_bypass_runtime_permissions(self, method: str) -> bool:
        """
        只读型元信息接口允许在未授权前访问，便于模型先理解插件用途与参数要求。
        """
        return method in self.RUNTIME_PERMISSION_BYPASS_METHODS

    def _safe_extract_zip_archive(self, archive: zipfile.ZipFile, target_dir: str) -> None:
        """
        安全解压 ZIP 压缩包，防止路径遍历攻击。
        
        Args:
            archive: ZIP 文件对象。
            target_dir: 目标解压目录。
            
        Raises:
            ValueError: 若检测到非法路径结构。
        """
        target_dir_abs = os.path.abspath(target_dir)
        os.makedirs(target_dir_abs, exist_ok=True)

        for member_info in archive.infolist():
            normalized_member = member_info.filename.replace("\\", "/")
            if normalized_member.startswith("/") or normalized_member.startswith("//"):
                raise ValueError("Invalid zip file structure")

            parts = [part for part in normalized_member.split("/") if part not in ("", ".")]
            if not parts:
                continue
            if any(part == ".." for part in parts):
                raise ValueError("Invalid zip file structure")

            destination = os.path.abspath(os.path.join(target_dir_abs, *parts))
            if os.path.commonpath([target_dir_abs, destination]) != target_dir_abs:
                raise ValueError("Invalid zip file structure")

            # 阻止解压符号链接，避免写入目标目录外部或覆盖敏感文件
            unix_mode = (member_info.external_attr >> 16) & 0o170000
            if unix_mode == 0o120000:
                raise ValueError("Zip archive contains unsupported symlink entry")

            if member_info.is_dir():
                os.makedirs(destination, exist_ok=True)
                continue

            parent_dir = os.path.dirname(destination)
            if parent_dir:
                os.makedirs(parent_dir, exist_ok=True)

            with archive.open(member_info, "r") as source, open(destination, "wb") as target_file:
                shutil.copyfileobj(source, target_file)

    def _safe_extract_zip_file(self, zip_path: str, target_dir: str) -> None:
        """
        从文件路径安全解压 ZIP 文件。
        
        Args:
            zip_path: ZIP 文件路径。
            target_dir: 目标解压目录。
        """
        with zipfile.ZipFile(zip_path, "r") as archive:
            self._safe_extract_zip_archive(archive, target_dir)

    def _safe_extract_zip_bytes(self, zip_content: bytes, target_dir: str) -> None:
        """
        从字节数据安全解压 ZIP 内容。
        
        Args:
            zip_content: ZIP 文件的字节数据。
            target_dir: 目标解压目录。
        """
        with zipfile.ZipFile(io.BytesIO(zip_content), "r") as archive:
            self._safe_extract_zip_archive(archive, target_dir)

    def _create_source_extract_dir(self, source_name: str) -> str:
        """
        创建用于解压插件的临时目录。
        
        Args:
            source_name: 源文件名称。
            
        Returns:
            临时目录路径。
        """
        base_name = os.path.splitext(os.path.basename(source_name))[0] or "plugin"
        safe_base = re.sub(r"[^a-zA-Z0-9_.-]", "_", base_name)
        extract_dir = tempfile.mkdtemp(prefix=f"{safe_base}_", dir=self.plugins_dir)
        return extract_dir

    def _get_repo_root_dir(self) -> str:
        """
        获取仓库根目录路径。
        扫描插件时需要把仓库根目录加入导入搜索路径，避免示例插件引用 `backend.*` 时报错。
        """
        current_dir = os.path.dirname(os.path.abspath(__file__))
        return os.path.abspath(os.path.join(current_dir, "..", ".."))

    def _resolve_plugin_root_dir(self, plugin_path: str) -> str:
        """
        根据插件入口文件推断插件根目录。
        约定优先支持 <plugin_root>/src/index.py 结构，其余情况回退到入口文件所在目录。
        """
        entry_path = os.path.abspath(plugin_path)
        entry_dir = os.path.dirname(entry_path)
        if os.path.basename(entry_path) == "index.py" and os.path.basename(entry_dir) == "src":
            return os.path.dirname(entry_dir)
        return entry_dir

    def _read_plugin_json_file(self, path: str) -> Optional[Dict[str, Any]]:
        """
        安全读取插件目录中的 JSON 文件，异常时返回 None。
        """
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as json_file:
                payload = json.load(json_file)
            if isinstance(payload, dict):
                return payload
        except Exception as e:
            logger.warning(f"Failed to read plugin json file '{path}': {e}")
        return None

    def _normalize_manifest_version(self, value: Any) -> Any:
        """
        兼容历史 manifest 中使用的 `1.0` 版本写法，统一补齐为 semver 三段式。
        """
        if not isinstance(value, str):
            return value
        normalized = value.strip()
        if re.fullmatch(r"\d+\.\d+", normalized):
            return f"{normalized}.0"
        return normalized

    def _normalize_manifest_payload(self, manifest: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """
        对 manifest 进行轻量兼容处理，避免旧插件因字段格式过旧而无法加载。
        """
        if not isinstance(manifest, dict):
            return manifest

        normalized = deepcopy(manifest)
        normalized["version"] = self._normalize_manifest_version(normalized.get("version"))
        normalized["pluginApiVersion"] = self._normalize_manifest_version(normalized.get("pluginApiVersion"))

        extensions = normalized.get("extensions")
        if isinstance(extensions, list):
            for extension in extensions:
                if isinstance(extension, dict):
                    extension["version"] = self._normalize_manifest_version(extension.get("version"))

        return normalized

    def _build_scan_module_name(self, plugin_path: str) -> str:
        """
        为扫描阶段生成尽量贴近真实包结构的模块名。
        这样在插件使用相对导入或依赖包上下文时，能减少与运行期环境的偏差。
        """
        plugin_path_abs = os.path.abspath(plugin_path)
        repo_root_dir = self._get_repo_root_dir()
        backend_dir = os.path.join(repo_root_dir, "backend")
        candidate_roots = (repo_root_dir, backend_dir, os.path.abspath(self.plugins_dir))

        for root_dir in candidate_roots:
            try:
                if os.path.commonpath([root_dir, plugin_path_abs]) != root_dir:
                    continue
            except ValueError:
                continue

            relative_path = os.path.relpath(plugin_path_abs, root_dir)
            if relative_path.startswith(".."):
                continue

            module_path = os.path.splitext(relative_path)[0]
            module_name = module_path.replace(os.sep, ".")
            if module_name:
                return module_name

        return f"plugins.{os.path.splitext(os.path.basename(plugin_path_abs))[0]}"

    @contextmanager
    def _plugin_scan_import_context(self, plugin_path: str):
        """
        为扫描阶段临时补齐导入搜索路径。
        这里同时加入仓库根目录、后端目录和插件所在目录，兼容示例插件与本地测试插件的导入方式。
        """
        repo_root_dir = self._get_repo_root_dir()
        backend_dir = os.path.join(repo_root_dir, "backend")
        plugin_dir = os.path.dirname(os.path.abspath(plugin_path))

        path_candidates = []
        for path in (repo_root_dir, backend_dir, self.plugins_dir, plugin_dir):
            normalized = os.path.abspath(path)
            if normalized not in path_candidates:
                path_candidates.append(normalized)

        inserted_paths: List[str] = []
        for path in reversed(path_candidates):
            if path and path not in sys.path:
                sys.path.insert(0, path)
                inserted_paths.append(path)

        base_plugin_alias_key = "backend.plugins.base_plugin"
        previous_base_plugin_alias = sys.modules.get(base_plugin_alias_key)
        alias_created = False

        try:
            # 统一 `plugins.base_plugin` 与 `backend.plugins.base_plugin` 的模块身份，
            # 避免同一个 BasePlugin 因为导入路径不同而让 issubclass 判断失效。
            canonical_base_plugin_module = importlib.import_module("plugins.base_plugin")
            if previous_base_plugin_alias is not canonical_base_plugin_module:
                sys.modules[base_plugin_alias_key] = canonical_base_plugin_module
                alias_created = True
            yield
        finally:
            if alias_created:
                if previous_base_plugin_alias is None:
                    sys.modules.pop(base_plugin_alias_key, None)
                else:
                    sys.modules[base_plugin_alias_key] = previous_base_plugin_alias
            for path in inserted_paths:
                if path in sys.path:
                    sys.path.remove(path)

    def _discover_plugins_in_directory(self, search_dir: str) -> List[Dict[str, Any]]:
        """
        在指定目录中搜索并发现插件。
        
        Args:
            search_dir: 搜索目录路径。
            
        Returns:
            发现的插件信息列表。
        """
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
        """
        在插件目录中发现所有可用插件。
        
        Returns:
            发现的插件信息列表。
        """
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
        """
        从本地 ZIP 文件注册插件。
        
        Args:
            zip_path: ZIP 文件路径。
            resource_limits: 可选的资源限制配置。
            
        Returns:
            注册的插件信息列表。
            
        Raises:
            FileNotFoundError: ZIP 文件不存在。
            ValueError: 文件不是 ZIP 格式。
        """
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

    def _resolve_remote_download_ips(self, hostname: str) -> List[str]:
        """
        解析远程下载域名并校验返回地址均为公网地址。
        返回经过去重后的安全 IP 列表，供后续固定 IP 下载使用。
        """
        try:
            resolved_ips = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise ValueError(f"无法解析域名: {hostname}") from exc

        safe_ips: List[str] = []
        for _, _, _, _, sockaddr in resolved_ips:
            ip_str = sockaddr[0]
            ip_addr = ipaddress.ip_address(ip_str)
            if ip_addr.is_private or ip_addr.is_loopback or ip_addr.is_link_local or ip_addr.is_reserved:
                raise ValueError(
                    f"域名 '{hostname}' 解析到不安全的地址 {ip_str}，"
                    "禁止访问内网、回环或链路本地地址"
                )
            if ip_str not in safe_ips:
                safe_ips.append(ip_str)

        try:
            second_resolved = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise ValueError(f"DNS rebinding 校验时无法解析域名: {hostname}") from exc

        second_ips = {sockaddr[0] for _, _, _, _, sockaddr in second_resolved}
        first_ips = set(safe_ips)
        if second_ips != first_ips:
            raise ValueError(
                f"域名 '{hostname}' DNS 解析结果不一致 (可能存在 DNS rebinding 攻击)，"
                f"首次: {first_ips}, 二次: {second_ips}"
            )

        return safe_ips

    def _validate_remote_url(self, source_url: str) -> Optional[List[str]]:
        """
        校验远程插件下载地址的安全性，防止 SSRF 攻击。
        拒绝私有网络、回环地址、链路本地地址，并校验域名白名单。
        
        Args:
            source_url: 待校验的远程 URL。
            
        Raises:
            ValueError: URL 不安全或不在白名单中。
        """
        parsed = urllib.parse.urlparse(source_url)
        hostname = parsed.hostname or ""

        # 校验域名白名单
        if hostname not in self.ALLOWED_DOWNLOAD_DOMAINS:
            raise ValueError(
                f"域名 '{hostname}' 不在允许下载的白名单中。"
                f"允许的域名: {sorted(self.ALLOWED_DOWNLOAD_DOMAINS)}"
            )

        return self._resolve_remote_download_ips(hostname)

    def _download_remote_plugin_via_pinned_ip(
        self,
        source_url: str,
        resolved_ips: List[str],
        timeout: int,
    ) -> Tuple[int, Dict[str, str], bytes]:
        """
        使用已校验的固定 IP 下载远程插件，避免下载阶段再次触发 DNS 解析。
        """
        parsed = urllib.parse.urlparse(source_url)
        hostname = parsed.hostname or ""
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        request_path = parsed.path or "/"
        if parsed.query:
            request_path = f"{request_path}?{parsed.query}"

        last_error: Optional[Exception] = None
        for resolved_ip in resolved_ips:
            socket_obj: Optional[socket.socket] = None
            response: Optional[http.client.HTTPResponse] = None
            try:
                raw_socket = socket.create_connection((resolved_ip, port), timeout=timeout)
                raw_socket.settimeout(timeout)
                socket_obj = raw_socket
                if parsed.scheme == "https":
                    ssl_context = ssl.create_default_context()
                    socket_obj = ssl_context.wrap_socket(raw_socket, server_hostname=hostname)
                    socket_obj.settimeout(timeout)

                request_bytes = (
                    f"GET {request_path} HTTP/1.1\r\n"
                    f"Host: {hostname}\r\n"
                    "User-Agent: OpenAwAPluginManager/1.0\r\n"
                    "Accept: application/zip, application/octet-stream\r\n"
                    "Connection: close\r\n\r\n"
                ).encode("ascii")
                socket_obj.sendall(request_bytes)

                response = http.client.HTTPResponse(socket_obj)
                response.begin()

                content_length = response.getheader("Content-Length")
                if content_length is not None:
                    try:
                        if int(content_length) > self.MAX_DOWNLOAD_SIZE:
                            raise ValueError(
                                f"插件包体积 ({content_length} bytes) 超过限制 ({self.MAX_DOWNLOAD_SIZE} bytes)"
                            )
                    except ValueError:
                        raise

                content = response.read(self.MAX_DOWNLOAD_SIZE + 1)
                if len(content) > self.MAX_DOWNLOAD_SIZE:
                    raise ValueError(
                        f"插件包体积 ({len(content)} bytes) 超过限制 ({self.MAX_DOWNLOAD_SIZE} bytes)"
                    )

                headers = {key.lower(): value for key, value in response.getheaders()}
                return response.status, headers, content
            except Exception as exc:
                last_error = exc
                continue
            finally:
                if response is not None:
                    response.close()
                if socket_obj is not None:
                    socket_obj.close()

        if last_error is None:
            raise ValueError("远程插件下载失败")
        raise ValueError(f"远程插件下载失败: {last_error}") from last_error

    def register_plugin_from_url(
        self,
        source_url: str,
        resource_limits: Optional[Dict[str, Any]] = None,
        timeout: int = 30,
    ) -> List[Dict[str, Any]]:
        """
        从远程 URL 下载并注册插件。
        
        Args:
            source_url: 远程 ZIP 文件的 URL。
            resource_limits: 可选的资源限制配置。
            timeout: 下载超时时间（秒）。
            
        Returns:
            注册的插件信息列表。
            
        Raises:
            ValueError: URL 格式无效或内容为空。
        """
        parsed = urllib.parse.urlparse(source_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Invalid remote plugin URL")

        # SSRF 防护：校验域名白名单与 IP 安全性，并在下载阶段固定到已验证 IP。
        resolved_ips = self._validate_remote_url(source_url)

        if resolved_ips:
            status_code, response_headers, response_content = self._download_remote_plugin_via_pinned_ip(
                source_url=source_url,
                resolved_ips=resolved_ips,
                timeout=timeout,
            )
        else:
            response = httpx.get(
                source_url,
                timeout=timeout,
                follow_redirects=False,
                headers={"Accept": "application/zip, application/octet-stream"},
            )
            status_code = response.status_code
            response_headers = {key.lower(): value for key, value in response.headers.items()}
            response_content = response.content
            if response.is_redirect:
                status_code = 302

        if status_code in (301, 302, 303, 307, 308):
            raise ValueError("远程插件下载不允许重定向，请提供直链地址")
        if status_code >= 400:
            raise ValueError(f"远程插件下载失败，HTTP 状态码: {status_code}")

        if not response_content:
            raise ValueError("Remote plugin package is empty")

        # 校验下载体积限制
        if len(response_content) > self.MAX_DOWNLOAD_SIZE:
            raise ValueError(
                f"插件包体积 ({len(response_content)} bytes) 超过限制 ({self.MAX_DOWNLOAD_SIZE} bytes)"
            )

        # 校验内容类型
        content_type = response_headers.get("content-type", "")
        allowed_types = {"application/zip", "application/octet-stream", "application/x-zip-compressed"}
        if content_type and not any(t in content_type for t in allowed_types):
            raise ValueError(f"不支持的内容类型: {content_type}，仅允许 ZIP 文件")

        source_name = os.path.basename(parsed.path) or "remote_plugin.zip"
        extract_dir = self._create_source_extract_dir(source_name)

        try:
            self._safe_extract_zip_bytes(response_content, extract_dir)
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
        """
        校验 NPM 包名格式是否合法。
        
        Args:
            package_name: 包名。
            
        Returns:
            合法返回 True，否则返回 False。
        """
        return bool(self.NPM_PACKAGE_PATTERN.fullmatch(package_name))

    def validate_npm_version(self, version: str) -> bool:
        """
        校验 NPM 版本号格式是否合法。
        
        Args:
            version: 版本号字符串。
            
        Returns:
            合法返回 True，否则返回 False。
        """
        return bool(self.NPM_VERSION_PATTERN.fullmatch(version))

    def parse_npm_source(self, npm_source: str) -> Dict[str, str]:
        """
        解析npm、source相关输入内容，并转换为内部可用结构。
        它常用于屏蔽外部协议差异并统一上层业务使用的数据格式。
        """
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
        """
        处理register、plugin、from、npm、source相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        npm_info = self.parse_npm_source(npm_source)
        logger.info(
            f"Parsed npm source package={npm_info['package_name']} version={npm_info['version']}"
        )
        return npm_info

    def _build_release_id(self, plugin_name: str, metadata: Dict[str, Any]) -> str:
        """
        处理build、release、id相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        self._rollout_release_counter += 1
        version = str(metadata.get("version", "1.0.0"))
        path = str(metadata.get("path", ""))
        payload = f"{plugin_name}:{version}:{path}:{self._rollout_release_counter}".encode("utf-8")
        digest = hashlib.sha256(payload).hexdigest()[:10]
        return f"{plugin_name}-{version}-{digest}"

    def _normalize_rollout_targets(self, targets: Optional[Dict[str, Any]]) -> Dict[str, List[str]]:
        """
        处理normalize、rollout、targets相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
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
        """
        处理normalize、rollout、policy相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        default_policy = {
            "enabled": False,
            "rollout_percentage": 0.0,
            "targets": {
                "user_ids": [],
                "regions": [],
                "versions": [],
            },
            "updated_at": datetime.now(timezone.utc).isoformat(),
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
        default_policy["updated_at"] = datetime.now(timezone.utc).isoformat()
        return default_policy

    def _ensure_runtime_route(self, plugin_name: str) -> Optional[Dict[str, Any]]:
        """
        处理ensure、runtime、route相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
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
                    "loaded_at": datetime.now(timezone.utc).isoformat(),
                },
                "standby": None,
            },
            "rollout_policy": self._normalize_rollout_policy(None),
            "last_update": datetime.now(timezone.utc).isoformat(),
            "last_error": None,
            "last_rollback": None,
        }
        self._runtime_routes[plugin_name] = route
        return route

    def _version_matches(self, selector_version: str, rule: str) -> bool:
        """
        处理version、matches相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
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
        """
        处理selector、matches、targets相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
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
        """
        处理selector、bucket相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        payload = f"{selector.get('user_id', '')}|{selector.get('region', '')}|{selector.get('version', '')}".encode("utf-8")
        return int(hashlib.sha256(payload).hexdigest()[:8], 16) % 100

    def _resolve_execution_slot(self, plugin_name: str, selector: Dict[str, str], force_slot: Optional[str] = None) -> str:
        """
        处理resolve、execution、slot相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
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
        """
        处理apply、active、route、slot相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
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
        """
        处理load、plugin、release相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
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
        """
        处理cleanup、release、binding相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        if not binding:
            return
        plugin_instance = binding.get("plugin_instance")
        if plugin_instance is not None:
            try:
                plugin_instance.cleanup()
            except Exception as cleanup_error:
                logger.error(f"Plugin '{plugin_name}' cleanup error: {cleanup_error}")

    def set_rollout_policy(self, plugin_name: str, policy: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """
        设置rollout、policy相关配置或运行状态。
        此类方法通常会直接影响后续执行路径或运行上下文中的关键数据。
        """
        route = self._ensure_runtime_route(plugin_name)
        if route is None:
            raise ValueError(f"Plugin '{plugin_name}' is not loaded")

        normalized = self._normalize_rollout_policy(policy)
        route["rollout_policy"] = normalized
        route["last_update"] = datetime.now(timezone.utc).isoformat()
        return self.get_plugin_rollout_status(plugin_name)

    def hot_update_plugin(
        self,
        plugin_name: str,
        rollout_policy: Optional[Dict[str, Any]] = None,
        strategy: str = "gray",
    ) -> Dict[str, Any]:
        """
        处理hot、update、plugin相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
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
                "loaded_at": datetime.now(timezone.utc).isoformat(),
            }
            old_standby = route["slots"].get("standby")
            route["slots"]["standby"] = standby_slot
            self._cleanup_release_binding(plugin_name, old_standby)

            normalized_policy = self._normalize_rollout_policy(rollout_policy)
            route["rollout_policy"] = normalized_policy
            route["last_error"] = None
            route["last_update"] = datetime.now(timezone.utc).isoformat()

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
                "at": datetime.now(timezone.utc).isoformat(),
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
        """
        获取plugin、rollout、status相关数据或当前状态。
        调用方通常依赖该结果继续进行后续判断、渲染或业务编排。
        """
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
        """
        列出rollout、status相关内容，便于调用方查看、筛选或批量处理。
        返回结果通常会被页面展示、审计流程或后续操作复用。
        """
        statuses: List[Dict[str, Any]] = []
        for plugin_name in sorted(self._runtime_routes):
            statuses.append(self.get_plugin_rollout_status(plugin_name))
        return statuses

    def _scan_plugin_file(self, plugin_path: str) -> Optional[Dict[str, Any]]:
        """
        处理scan、plugin、file相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        plugin_name = os.path.splitext(os.path.basename(plugin_path))[0]
        module_name = self._build_scan_module_name(plugin_path)

        try:
            security_scan = self._run_static_security_scan(plugin_path)
            if security_scan["blocked"]:
                logger.warning(f"Plugin '{plugin_name}' blocked by static security scan: {security_scan['reasons']}")
                return None

            spec = importlib.util.spec_from_file_location(module_name, plugin_path)
            if spec is None or spec.loader is None:
                return None

            module = importlib.util.module_from_spec(spec)
            with self._plugin_scan_import_context(plugin_path):
                spec.loader.exec_module(module)

            plugin_classes = []
            for name, obj in inspect.getmembers(module, inspect.isclass):
                if inspect.isclass(obj) and self.loader._is_supported_plugin_class(obj):
                    plugin_classes.append(obj)

            if not plugin_classes:
                return None

            plugin_class = plugin_classes[0]

            plugin_root_dir = self._resolve_plugin_root_dir(plugin_path)
            manifest_path = os.path.join(plugin_root_dir, "manifest.json")
            config_path = os.path.join(plugin_root_dir, "config.json")
            schema_path = os.path.join(plugin_root_dir, "schema.json")

            class_manifest = getattr(plugin_class, "manifest", None)
            if not isinstance(class_manifest, dict):
                class_manifest = None
            file_manifest = self._read_plugin_json_file(manifest_path)
            manifest = deepcopy(class_manifest) if class_manifest else {}
            if file_manifest:
                manifest.update(file_manifest)
            if not manifest:
                manifest = None
            manifest = self._normalize_manifest_payload(manifest)

            default_config = self._read_plugin_json_file(config_path) or {}
            manifest_permissions = []
            if isinstance(manifest, dict):
                raw_permissions = manifest.get("permissions", [])
                if isinstance(raw_permissions, list):
                    manifest_permissions = [
                        permission.strip()
                        for permission in raw_permissions
                        if isinstance(permission, str) and permission.strip()
                    ]

            requested_permissions = sorted(
                set(security_scan["requested_permissions"]) | set(manifest_permissions)
            )

            metadata = {
                "name": (manifest or {}).get("name") or getattr(plugin_class, "name", plugin_name),
                "version": (manifest or {}).get("version") or getattr(plugin_class, "version", "1.0.0"),
                "description": (manifest or {}).get("description") or getattr(plugin_class, "description", ""),
                "path": plugin_path,
                "root_dir": plugin_root_dir,
                "class_name": plugin_class.__name__,
                "module": module_name,
                "manifest": manifest,
                "manifest_path": manifest_path if os.path.exists(manifest_path) else None,
                "config_path": config_path if os.path.exists(config_path) else None,
                "schema_path": schema_path if os.path.exists(schema_path) else None,
                "default_config": default_config,
                "security_scan": security_scan,
                "requested_permissions": requested_permissions,
            }

            return metadata

        except (ModuleNotFoundError, ImportError) as e:
            logger.bind(
                event="plugin_scan_import_skipped",
                plugin_name=plugin_name,
                plugin_path=plugin_path,
                module_name=module_name,
                error_type=type(e).__name__,
                missing_module=getattr(e, "name", None),
            ).warning(f"Skipped plugin metadata scan because imports are unavailable: {e}")
            return None
        except Exception as e:
            logger.bind(
                event="plugin_scan_failed",
                plugin_name=plugin_name,
                plugin_path=plugin_path,
                module_name=module_name,
                error_type=type(e).__name__,
            ).error(f"Error scanning plugin file {plugin_path}: {e}")
            return None

    def load_plugin(self, plugin_name: str) -> bool:
        """
        加载plugin相关资源或运行时对象。
        它通常负责把外部配置、持久化内容或缓存状态转换为内部可用结构。
        """
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
            """
            处理load、action相关逻辑，并为调用方返回对应结果。
            阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
            """
            plugin_class = self.loader.load_module(plugin_path)
            if plugin_class is None:
                raise RuntimeError(f"Failed to load plugin class for '{plugin_name}'")

            config = {
                "name": metadata["name"],
                "version": metadata["version"],
                "description": metadata["description"],
            }

            default_config = metadata.get("default_config")
            if isinstance(default_config, dict):
                config.update(deepcopy(default_config))

            manifest = metadata.get("manifest")
            if isinstance(manifest, dict):
                config["manifest"] = deepcopy(manifest)

            root_dir = metadata.get("root_dir")
            if isinstance(root_dir, str) and root_dir:
                config["plugin_root"] = root_dir

            config["name"] = metadata["name"]
            config["version"] = metadata["version"]
            config["description"] = metadata["description"]

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
            """
            处理load、rollback相关逻辑，并为调用方返回对应结果。
            阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
            """
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

        # 仅在 manifest 显式声明时才自动授权，默认仍保留运行时权限校验。
        manifest = metadata.get("manifest") if isinstance(metadata.get("manifest"), dict) else {}
        auto_authorize_permissions = bool(
            metadata.get("auto_authorize_permissions")
            or manifest.get("auto_authorize_permissions")
        )
        manifest_permissions = metadata.get("requested_permissions", [])
        if auto_authorize_permissions and manifest_permissions:
            self.authorize_plugin_permissions(plugin_name, manifest_permissions)
            logger.info(f"Plugin '{plugin_name}' auto-authorized permissions: {manifest_permissions}")

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
        """
        处理unload、plugin相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        if plugin_name not in self.loaded_plugins:
            logger.warning(f"Plugin '{plugin_name}' is not loaded")
            return False

        plugin_instance = self.loaded_plugins[plugin_name]

        def _unload_action() -> None:
            """
            处理unload、action相关逻辑，并为调用方返回对应结果。
            阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
            """
            try:
                plugin_instance.cleanup()
            finally:
                self._unregister_plugin_tools(plugin_name)
                self.extension_registry.unregister_plugin(plugin_name)
                if plugin_name in self.loaded_plugins:
                    del self.loaded_plugins[plugin_name]
                self._plugin_sandboxes.pop(plugin_name, None)

        def _unload_rollback(previous_state: PluginState) -> None:
            """
            处理unload、rollback相关逻辑，并为调用方返回对应结果。
            阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
            """
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
        """
        处理enable、plugin相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
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
        """
        处理disable、plugin相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
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
        """
        处理reload、plugin相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
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

        if plugin_name in self.plugin_metadata:
            metadata = self.plugin_metadata[plugin_name]
            spec = importlib.util.spec_from_file_location(metadata["module"], metadata["path"])
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                importlib.reload(mod)

        return self.load_plugin(plugin_name)

    def _filter_plugin_method_kwargs(
        self,
        plugin_instance: BasePlugin,
        method: str,
        kwargs: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        根据插件方法签名过滤参数，避免自动注入的上下文字段污染直接方法调用。
        对显式接受 **kwargs 的历史插件保持兼容，不做额外裁剪。
        """
        method_callable = getattr(plugin_instance, method, None)
        if not callable(method_callable):
            return kwargs

        try:
            signature = inspect.signature(method_callable)
        except (TypeError, ValueError):
            return kwargs

        if any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD
            for parameter in signature.parameters.values()
        ):
            return kwargs

        allowed_kwargs = {
            parameter_name
            for parameter_name, parameter in signature.parameters.items()
            if parameter.kind in (
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                inspect.Parameter.KEYWORD_ONLY,
            )
        }
        filtered_kwargs = {
            key: value
            for key, value in kwargs.items()
            if key in allowed_kwargs
        }

        dropped_keys = sorted(key for key in kwargs if key not in allowed_kwargs)
        if dropped_keys:
            logger.debug(
                f"Plugin '{plugin_instance.name}' method '{method}' filtered unsupported kwargs: {dropped_keys}"
            )

        return filtered_kwargs

    def execute_plugin(self, plugin_name: str, method: str, **kwargs) -> Dict[str, Any]:
        """
        处理execute、plugin相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        if plugin_name not in self.loaded_plugins:
            logger.error(f"Plugin '{plugin_name}' is not loaded")
            return {
                "status": "error",
                "message": f"Plugin '{plugin_name}' is not loaded",
            }

        if not self._should_bypass_runtime_permissions(method):
            try:
                self._enforce_runtime_permissions(plugin_name)
            except PermissionError as e:
                logger.warning(f"Plugin '{plugin_name}' runtime permission denied: {e}")
                _perm_status = self.get_plugin_permission_status(plugin_name)
                return {
                    "status": "permission_required",
                    "message": str(e),
                    "required_permissions": _perm_status.get("missing_permissions", []),
                }

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
        filtered_kwargs = self._filter_plugin_method_kwargs(plugin_instance, method, kwargs)
        result = sandbox.execute_plugin_sync(plugin_instance, method, **filtered_kwargs)
        return self._normalize_plugin_execution_result(result)

    async def execute_plugin_async(self, plugin_name: str, method: str, **kwargs) -> Dict[str, Any]:
        """
        处理execute、plugin、async相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        if plugin_name not in self.loaded_plugins:
            logger.error(f"Plugin '{plugin_name}' is not loaded")
            return {
                "status": "error",
                "message": f"Plugin '{plugin_name}' is not loaded",
            }

        if not self._should_bypass_runtime_permissions(method):
            try:
                self._enforce_runtime_permissions(plugin_name)
            except PermissionError as e:
                logger.warning(f"Plugin '{plugin_name}' runtime permission denied: {e}")
                _perm_status = self.get_plugin_permission_status(plugin_name)
                return {
                    "status": "permission_required",
                    "message": str(e),
                    "required_permissions": _perm_status.get("missing_permissions", []),
                }

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
        filtered_kwargs = self._filter_plugin_method_kwargs(plugin_instance, method, kwargs)
        result = await sandbox.execute_plugin(plugin_instance, method, **filtered_kwargs)
        return self._normalize_plugin_execution_result(result)

    def _normalize_plugin_execution_result(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """
        将沙箱执行结果与插件返回值解包为统一结构。
        这样上层无需同时理解沙箱协议与插件内部业务状态。
        """
        if not isinstance(result, dict):
            return {
                "status": "error",
                "message": "Invalid plugin execution result",
            }

        if result.get("status") != "success":
            return result

        payload = result.get("result")
        normalized = dict(result)

        if isinstance(payload, dict):
            payload_status = payload.get("status")
            if isinstance(payload_status, str) and payload_status.strip():
                normalized["status"] = payload_status

            if normalized.get("message") in {None, ""}:
                if isinstance(payload.get("message"), str):
                    normalized["message"] = payload.get("message", "")
                elif payload.get("error") is not None:
                    normalized["message"] = str(payload.get("error"))

            if payload.get("data") is not None:
                normalized["data"] = payload.get("data")
            else:
                normalized["data"] = payload
            return normalized

        normalized["data"] = payload
        return normalized

    def _normalize_tool_definition(
        self,
        plugin_name: str,
        plugin_instance: BasePlugin,
        tool_def: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """
        将插件暴露的工具描述补齐为统一协议。
        对仅声明 name/description 的旧插件，默认映射到 execute(action=<tool_name>)。
        """
        if not isinstance(tool_def, dict):
            return None

        tool_name = str(tool_def.get("name") or "").strip()
        if not tool_name:
            return None

        normalized = deepcopy(tool_def)
        normalized["name"] = tool_name
        normalized["plugin"] = plugin_name

        method_name = str(normalized.get("method") or "").strip()
        default_params = normalized.get("default_params")
        if not isinstance(default_params, dict):
            default_params = {}

        if not method_name:
            if hasattr(plugin_instance, tool_name) and callable(getattr(plugin_instance, tool_name)):
                method_name = tool_name
            else:
                method_name = "execute"
                default_params.setdefault("action", tool_name)

        if not hasattr(plugin_instance, method_name) or not callable(getattr(plugin_instance, method_name)):
            logger.warning(
                f"Plugin '{plugin_name}' tool '{tool_name}' resolved to unavailable method '{method_name}'"
            )
            return None

        normalized["method"] = method_name
        normalized["default_params"] = default_params
        return normalized

    def _build_plugin_help_tool(self, plugin_name: str) -> Dict[str, Any]:
        """
        为每个插件提供统一的帮助工具，便于模型在实际调用前先了解插件用法。
        """
        return {
            "name": "help",
            "method": "get_help",
            "description": (
                f"查看插件 '{plugin_name}' 的用途、配置摘要、可用工具、参数要求和调用建议。"
                "首次使用插件前建议先调用此工具。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "tool_name": {
                        "type": "string",
                        "description": "可选，只查看指定工具的用法",
                    },
                    "include_examples": {
                        "type": "boolean",
                        "description": "是否返回额外调用建议，默认 true",
                    },
                },
                "required": [],
            },
        }

    def _collect_plugin_tools(self, plugin_name: str, plugin_instance: BasePlugin) -> List[Dict[str, Any]]:
        """
        收集并规范化插件工具定义，同时兼容显式声明和约定式方法暴露。
        """
        tools: List[Dict[str, Any]] = []
        seen_signatures: Set[Tuple[str, str]] = set()

        help_tool = self._normalize_tool_definition(
            plugin_name,
            plugin_instance,
            self._build_plugin_help_tool(plugin_name),
        )
        if help_tool is not None:
            help_signature = (help_tool["name"], help_tool["method"])
            seen_signatures.add(help_signature)
            tools.append(help_tool)

        if hasattr(plugin_instance, "get_tools"):
            try:
                plugin_tools = plugin_instance.get_tools()
                if isinstance(plugin_tools, list):
                    for tool_def in plugin_tools:
                        normalized = self._normalize_tool_definition(plugin_name, plugin_instance, tool_def)
                        if normalized is None:
                            continue
                        signature = (normalized["name"], normalized["method"])
                        if signature in seen_signatures:
                            continue
                        seen_signatures.add(signature)
                        tools.append(normalized)
            except Exception as e:
                logger.error(f"Error getting tools from plugin '{plugin_name}': {e}")

        for attr_name in dir(plugin_instance):
            if not (attr_name.startswith("tool_") or attr_name.startswith("get_tool_")):
                continue

            attr = getattr(plugin_instance, attr_name)
            if not callable(attr):
                continue

            tool_def = {
                "name": attr_name.replace("tool_", "").replace("get_tool_", ""),
                "description": getattr(attr, "__doc__", "") or "",
                "method": attr_name,
            }
            normalized = self._normalize_tool_definition(plugin_name, plugin_instance, tool_def)
            if normalized is None:
                continue
            signature = (normalized["name"], normalized["method"])
            if signature in seen_signatures:
                continue
            seen_signatures.add(signature)
            tools.append(normalized)

        return tools

    def get_plugin_tools(self, plugin_name: str) -> List[Dict[str, Any]]:
        """
        获取plugin、tools相关数据或当前状态。
        调用方通常依赖该结果继续进行后续判断、渲染或业务编排。
        """
        if plugin_name in self._tools_registry:
            return self._tools_registry[plugin_name]

        if plugin_name not in self.loaded_plugins:
            logger.warning(f"Plugin '{plugin_name}' is not loaded, cannot get tools")
            return []

        plugin_instance = self.loaded_plugins[plugin_name]
        tools = self._collect_plugin_tools(plugin_name, plugin_instance)

        self._tools_registry[plugin_name] = tools
        return tools

    def get_all_tools(self) -> List[Dict[str, Any]]:
        """
        获取all、tools相关数据或当前状态。
        调用方通常依赖该结果继续进行后续判断、渲染或业务编排。
        """
        all_tools = []
        for plugin_name in self.loaded_plugins:
            tools = self.get_plugin_tools(plugin_name)
            all_tools.extend(tools)
        return all_tools

    def _register_plugin_tools(self, plugin_name: str, plugin_instance: BasePlugin) -> None:
        """
        处理register、plugin、tools相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        try:
            tools = self._collect_plugin_tools(plugin_name, plugin_instance)
            self._tools_registry[plugin_name] = tools
            logger.debug(f"Registered {len(tools)} tools for plugin '{plugin_name}'")
        except Exception as e:
            logger.error(f"Error registering tools for plugin '{plugin_name}': {e}")

    def _unregister_plugin_tools(self, plugin_name: str) -> None:
        """
        处理unregister、plugin、tools相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        if plugin_name in self._tools_registry:
            del self._tools_registry[plugin_name]
            logger.debug(f"Unregistered tools for plugin '{plugin_name}'")

    def list_loaded_plugins(self) -> List[str]:
        """
        列出loaded、plugins相关内容，便于调用方查看、筛选或批量处理。
        返回结果通常会被页面展示、审计流程或后续操作复用。
        """
        return list(self.loaded_plugins.keys())

    def list_available_plugins(self) -> List[str]:
        """
        列出available、plugins相关内容，便于调用方查看、筛选或批量处理。
        返回结果通常会被页面展示、审计流程或后续操作复用。
        """
        return list(self.plugin_metadata.keys())

    def get_plugin_info(self, plugin_name: str) -> Optional[Dict[str, Any]]:
        """
        获取plugin、info相关数据或当前状态。
        调用方通常依赖该结果继续进行后续判断、渲染或业务编排。
        """
        if plugin_name in self.plugin_metadata:
            info = self.plugin_metadata[plugin_name].copy()
            info["loaded"] = plugin_name in self.loaded_plugins
            info["state"] = self.state_machine.get_state(plugin_name).value
            return info
        return None


    def _normalize_manifest_dependencies(self, dependencies: Any) -> Dict[str, str]:
        """
        处理normalize、manifest、dependencies相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
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
        """
        处理normalize、plugin、dependencies相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        normalized = self._normalize_manifest_dependencies(dependencies)
        plugin_only: Dict[str, str] = {}
        for plugin_name, version_range in normalized.items():
            if plugin_name in self.plugin_metadata or plugin_name:
                plugin_only[plugin_name] = version_range
        return plugin_only

    def _parse_semver(self, version: str) -> Tuple[int, int, int]:
        """
        处理parse、semver相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
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
        """
        处理compare、semver相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        if left == right:
            return 0
        if left < right:
            return -1
        return 1

    def _inc_major(self, version: Tuple[int, int, int]) -> Tuple[int, int, int]:
        """
        处理inc、major相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        return version[0] + 1, 0, 0

    def _inc_minor(self, version: Tuple[int, int, int]) -> Tuple[int, int, int]:
        """
        处理inc、minor相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        return version[0], version[1] + 1, 0

    def _inc_patch(self, version: Tuple[int, int, int]) -> Tuple[int, int, int]:
        """
        处理inc、patch相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        return version[0], version[1], version[2] + 1

    def _parse_wildcard_range(self, token: str) -> Optional[List[Tuple[Optional[Tuple[int, int, int]], bool, Optional[Tuple[int, int, int]], bool]]]:
        """
        处理parse、wildcard、range相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
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
        """
        处理intersect、interval相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
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
        """
        处理intersect、interval、list相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
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
        """
        处理parse、semver、range相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
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
        """
        处理satisfies、semver、range相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
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
        """
        处理ranges、compatible相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        left_intervals = self._parse_semver_range(left)
        right_intervals = self._parse_semver_range(right)
        return bool(self._intersect_interval_list(left_intervals, right_intervals))

    def _format_semver(self, version: Tuple[int, int, int]) -> str:
        """
        处理format、semver相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        return f"{version[0]}.{version[1]}.{version[2]}"

    def _format_interval_as_range(
        self,
        interval: Tuple[Optional[Tuple[int, int, int]], bool, Optional[Tuple[int, int, int]], bool],
    ) -> str:
        """
        处理format、interval、as、range相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
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
        """
        处理suggest、common、range相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
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
        """
        构建dependency、graph相关对象、响应或中间结果。
        这类方法常用于统一组装结构，便于后续链路重复复用。
        """
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
        """
        处理detect、dependency、cycles相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
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
            """
            处理dfs相关逻辑，并为调用方返回对应结果。
            阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
            """
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
        """
        处理build、dependency、suggestions相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
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
        """
        处理analyze、dependency、conflicts相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
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
        """
        获取dependency、diagnostics相关数据或当前状态。
        调用方通常依赖该结果继续进行后续判断、渲染或业务编排。
        """
        graph = self.build_dependency_graph()
        analysis = self.analyze_dependency_conflicts()
        return {
            "graph": graph,
            "analysis": analysis,
        }

    def get_plugin_dependency_info(self, plugin_name: str) -> Optional[Dict[str, Any]]:
        """
        获取plugin、dependency、info相关数据或当前状态。
        调用方通常依赖该结果继续进行后续判断、渲染或业务编排。
        """
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
        """
        获取manager、stats相关数据或当前状态。
        调用方通常依赖该结果继续进行后续判断、渲染或业务编排。
        """
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
        """
        处理rollback、plugin相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        if plugin_name not in self.plugin_metadata:
            raise ValueError(f"Plugin '{plugin_name}' not found")

        def _restore(snapshot: Dict[str, Any]) -> Any:
            """
            处理restore相关逻辑，并为调用方返回对应结果。
            阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
            """
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
