import ast
from pathlib import Path
from typing import Any, Dict, Set


class PluginSecurityScanner:
    DANGEROUS_IMPORT_MODULES = {
        "subprocess", "socket", "ctypes", "pickle", "marshal", "requests",
        "httpx", "urllib", "urllib.request",
    }
    BLOCK_INSTALL_PATTERNS = {
        "eval", "exec", "compile", "subprocess", "ctypes", "pickle",
        "marshal", "system", "popen",
    }
    DANGEROUS_CALL_NAMES = {"eval", "exec", "compile", "open", "input", "__import__"}
    DANGEROUS_ATTRIBUTE_SUFFIXES = {
        "system", "popen", "remove", "unlink", "rmtree", "run", "call",
        "kill", "post", "get", "request", "urlopen",
    }
    PERMISSION_TO_PATTERNS = {
        "file:read": ["open"],
        "file:write": ["open", "remove", "unlink", "rmtree"],
        "network:http": ["requests", "httpx", "urllib", "urlopen"],
        "command:execute": ["system", "popen", "run", "call", "exec", "eval", "compile"],
    }

    @staticmethod
    def _node_name(node: ast.AST) -> str:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            base = PluginSecurityScanner._node_name(node.value)
            return f"{base}.{node.attr}" if base else node.attr
        if isinstance(node, ast.Call):
            return PluginSecurityScanner._node_name(node.func)
        return ""

    def scan(self, plugin_path: str) -> Dict[str, Any]:
        source_path = Path(plugin_path)
        try:
            source_code = source_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            source_code = source_path.read_text(encoding="latin-1")

        tokens: Set[str] = set()
        for node in ast.walk(ast.parse(source_code)):
            if isinstance(node, ast.Import):
                tokens.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                tokens.add(node.module)
            elif isinstance(node, ast.Call):
                call_name = self._node_name(node.func)
                if call_name:
                    tokens.add(call_name)

        matches: Set[str] = set()
        for token in tokens:
            lowered = token.lower()
            if lowered in self.DANGEROUS_CALL_NAMES:
                matches.add(lowered)
            for module_name in self.DANGEROUS_IMPORT_MODULES:
                if lowered == module_name or lowered.startswith(f"{module_name}."):
                    matches.add(module_name)
            for suffix in self.DANGEROUS_ATTRIBUTE_SUFFIXES:
                if lowered == suffix or lowered.endswith(f".{suffix}"):
                    matches.add(suffix)

        requested_permissions = sorted(
            permission
            for permission, patterns in self.PERMISSION_TO_PATTERNS.items()
            if any(pattern == match or pattern in match for pattern in patterns for match in matches)
        )
        blocked_patterns = sorted(matches & self.BLOCK_INSTALL_PATTERNS)
        return {
            "blocked": bool(blocked_patterns),
            "reasons": [f"检测到危险模式: {pattern}" for pattern in blocked_patterns],
            "matched_patterns": sorted(matches),
            "requested_permissions": requested_permissions,
        }
