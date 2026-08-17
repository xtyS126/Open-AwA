"""
插件安全服务：负责插件安全扫描、AST 分析、危险导入检测。
"""

import ast
from pathlib import Path
from typing import Dict, List, Set, Optional, Any

from loguru import logger


# 危险导入模块列表
DANGEROUS_IMPORT_MODULES: Set[str] = {
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

# 阻止的安装模式
BLOCK_INSTALL_PATTERNS: Set[str] = {
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

# 危险函数调用名
DANGEROUS_CALL_NAMES: Set[str] = {
    "eval",
    "exec",
    "compile",
    "open",
    "input",
    "__import__",
}

# 危险属性后缀
DANGEROUS_ATTRIBUTE_SUFFIXES: Set[str] = {
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

# 权限到危险模式的映射
PERMISSION_TO_PATTERNS: Dict[str, List[str]] = {
    "file:read": ["open"],
    "file:write": ["open", "remove", "unlink", "rmtree"],
    "network:http": ["requests", "httpx", "urllib", "urlopen"],
    "command:execute": ["system", "popen", "run", "call", "exec", "eval", "compile"],
}


class PluginSecurityService:
    """
    插件安全服务：扫描插件代码的安全性。

    职责：
    - 对 Python 插件源码进行 AST 静态分析
    - 检测危险导入、危险函数调用
    - 根据危险模式推导所需权限
    - 校验安装命令是否包含危险模式
    """

    def scan(self, plugin_path: str) -> Dict[str, Any]:
        """
        扫描单个 Python 插件文件的安全性。

        Args:
            plugin_path: 插件文件路径。

        Returns:
            扫描结果字典，包含 blocked、reasons、matched_patterns、requested_permissions 字段。
        """
        source_path = Path(plugin_path)
        try:
            source_code = source_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            source_code = source_path.read_text(encoding="latin-1")
        except OSError as e:
            logger.warning(f"无法读取插件文件进行安全扫描: {plugin_path} — {e}")
            return {
                "blocked": False,
                "reasons": [],
                "matched_patterns": [],
                "requested_permissions": [],
            }

        tokens = self._collect_tokens(source_code)
        matches = self._match_risk_patterns(tokens)
        blocked_patterns = sorted(matches & BLOCK_INSTALL_PATTERNS)
        requested_permissions = self._derive_permissions(matches)

        return {
            "blocked": bool(blocked_patterns),
            "reasons": [f"检测到危险模式: {pattern}" for pattern in blocked_patterns],
            "matched_patterns": sorted(matches),
            "requested_permissions": requested_permissions,
        }

    def scan_directory(self, plugin_dir: str) -> List[Dict[str, Any]]:
        """
        扫描插件目录中所有 Python 文件的安全性。

        Args:
            plugin_dir: 插件目录路径。

        Returns:
            每个文件的扫描结果列表。
        """
        results: List[Dict[str, Any]] = []
        dir_path = Path(plugin_dir)

        if not dir_path.exists():
            return results

        for py_file in dir_path.rglob("*.py"):
            if py_file.name.startswith("_"):
                continue
            result = self.scan(str(py_file))
            result["file"] = str(py_file)
            results.append(result)

        return results

    def _collect_tokens(self, source_code: str) -> Set[str]:
        """
        从源码中收集风险标记（导入名、调用名等）。

        Args:
            source_code: Python 源码字符串。

        Returns:
            风险标记集合。
        """
        tokens: Set[str] = set()
        try:
            tree = ast.parse(source_code)
        except SyntaxError:
            return tokens

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                tokens.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                tokens.add(node.module)
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
            if lowered in DANGEROUS_CALL_NAMES:
                matches.add(lowered)
            for module_name in DANGEROUS_IMPORT_MODULES:
                if lowered == module_name or lowered.startswith(f"{module_name}."):
                    matches.add(module_name)
            for suffix in DANGEROUS_ATTRIBUTE_SUFFIXES:
                if lowered == suffix or lowered.endswith(f".{suffix}"):
                    matches.add(suffix)
        return matches

    def _derive_permissions(self, matched_patterns: Set[str]) -> List[str]:
        """
        根据匹配的危险模式推导所需的权限。

        Args:
            matched_patterns: 匹配到的危险模式集合。

        Returns:
            所需权限列表（已排序）。
        """
        requested: Set[str] = set()
        for permission, patterns in PERMISSION_TO_PATTERNS.items():
            if any(
                pattern == match or pattern in match
                for pattern in patterns
                for match in matched_patterns
            ):
                requested.add(permission)
        return sorted(requested)

    @staticmethod
    def _get_node_name(node) -> str:
        """从 AST 节点提取可读名称。"""
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            base = PluginSecurityService._get_node_name(node.value)
            return f"{base}.{node.attr}" if base else node.attr
        if isinstance(node, ast.Call):
            return PluginSecurityService._get_node_name(node.func)
        return ""

    def validate_install_command(self, command: str) -> bool:
        """
        校验安装命令是否包含危险模式。

        Args:
            command: 安装命令字符串。

        Returns:
            安全返回 True，包含危险模式返回 False。
        """
        command_lower = command.lower()
        for pattern in BLOCK_INSTALL_PATTERNS:
            if pattern in command_lower:
                return False
        return True