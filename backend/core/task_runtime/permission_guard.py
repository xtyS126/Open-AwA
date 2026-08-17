"""
Per-agent 权限守卫模块，根据 AgentDefinition.permission_mode 强制执行工具调用权限。
集成现有 PermissionChecker 和 RBACManager 进行细粒度权限评估。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

from loguru import logger

from security.permission import PermissionChecker

# 工具名到操作类别的映射（键为去掉 builtin_ 前缀后的声明名，与 AgentDefinition.tools 一致）
_TOOL_OPERATION_MAP: Dict[str, str] = {
    # 只读
    "read_file": "file:read",
    "list_files": "file:list",
    "file_exists": "file:read",
    "web_search": "network:http",
    "web_fetch": "network:http",
    "local_search": "file:read",
    # 写入
    "write_file": "file:write",
    "edit_file": "file:write",
    "delete_file": "file:delete",
    # 命令执行
    "execute_command": "command:execute",
    "run_command": "command:execute",
    "run_shell": "command:execute",
    # 管理
    "install_plugin": "plugin:install",
    "install_skill": "skill:install",
    "manage_user": "user:manage",
    "system_config": "system:config",
}

# 始终允许的只读工具前缀
_READONLY_PREFIXES = ("read_", "list_", "search_", "get_", "find_", "check_", "query_", "fetch_")

# 高危工具前缀
_DANGEROUS_PREFIXES = ("delete_", "remove_", "drop_", "truncate_", "uninstall_", "purge_")


@dataclass
class PermissionDecision:
    """权限评估结果。"""
    allowed: bool = True
    mode: str = "auto"  # auto / confirm / deny
    reason: str = ""
    require_user_confirm: bool = False


# dont_ask 模式白名单：只允许这些操作类别
_DONT_ASK_ALLOWED_OPERATIONS = {
    "file:read", "file:list", "network:http",
}


class PermissionGuard:
    """
    根据 AgentDefinition.permission_mode 强制执行工具调用权限。

    五种模式：
    - default: 读操作自动通过，写操作需确认
    - accept_edits: 工作目录内编辑自动通过，其他写操作需确认
    - plan: 只读规划模式，拒绝所有写操作
    - dont_ask: 除白名单外一律拒绝（严格模式）
    - bypass_permissions: 全部自动通过（仅安全环境使用）
    """

    def __init__(self):
        self._checker = PermissionChecker()

    def evaluate(
        self,
        tool_name: str,
        tool_args: Optional[Dict[str, Any]] = None,
        *,
        permission_mode: str = "default",
        work_dir: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        allowed_tools: Optional[list] = None,
    ) -> PermissionDecision:
        """
        评估工具调用是否允许执行。

        参数:
            allowed_tools: 显式工具白名单；传入且工具不在其中时拒绝。
                          由子代理执行 bundle 按 AgentDefinition.tools 注入，
                          使 tools/disallowed_tools 声明在默认模式（default）下同样生效。
        """
        operation = self._map_tool_to_operation(tool_name, tool_args)

        if permission_mode == "bypass_permissions":
            return PermissionDecision(allowed=True, mode="auto", reason="bypass_permissions 模式")

        # 白名单优先：显式声明了可用工具集时，白名单之外的工具一律拒绝
        if allowed_tools is not None:
            normalized_name = self._normalize_tool_name(tool_name)
            if normalized_name not in allowed_tools and tool_name not in allowed_tools:
                return PermissionDecision(
                    allowed=False,
                    mode="deny",
                    reason=f"工具不在允许列表: {tool_name}",
                )

        if permission_mode == "dont_ask":
            if operation in _DONT_ASK_ALLOWED_OPERATIONS:
                return PermissionDecision(allowed=True, mode="auto", reason="dont_ask 白名单操作通过")
            return PermissionDecision(
                allowed=False,
                mode="deny",
                reason=f"dont_ask 模式下不允许: {tool_name} ({operation})",
            )

        if permission_mode == "plan":
            # plan 模式只允许只读操作
            if self._is_write_operation(tool_name, operation):
                return PermissionDecision(
                    allowed=False,
                    mode="deny",
                    reason=f"plan 模式下不允许写操作: {tool_name}",
                )
            return PermissionDecision(allowed=True, mode="auto", reason="plan 模式只读操作通过")

        # default / accept_edits 模式
        target = tool_args.get("file_path") or tool_args.get("path") or tool_args.get("target", "") if tool_args else ""
        if isinstance(target, dict):
            target = str(target)

        check_result = self._checker.check_permission(operation, target=target)

        if not check_result.get("allowed", False):
            return PermissionDecision(
                allowed=False,
                mode="deny",
                reason=check_result.get("reason", f"权限不足: {operation}"),
            )

        mode = check_result.get("mode", "auto")

        if permission_mode == "accept_edits" and operation.startswith("file:"):
            # 工作目录内编辑自动通过。
            # 使用 Path.resolve() + relative_to() 判定，防止 ../ 路径穿越
            # 与符号链接绕过工作目录边界（str.startswith 前缀判断可被绕过）。
            if work_dir and target:
                try:
                    target_path = Path(str(target)).resolve()
                    work_path = Path(str(work_dir)).resolve()
                    target_path.relative_to(work_path)
                    return PermissionDecision(allowed=True, mode="auto", reason="工作目录内编辑自动通过")
                except (ValueError, OSError):
                    # 目标不在工作目录内，继续走确认流程
                    pass

        if mode == "auto":
            return PermissionDecision(allowed=True, mode="auto", reason="自动授权")
        elif mode == "confirm":
            return PermissionDecision(
                allowed=True,
                mode="confirm",
                reason=f"需要用户确认: {operation}",
                require_user_confirm=True,
            )

        return PermissionDecision(allowed=True, mode="auto", reason="默认通过")

    @staticmethod
    def _normalize_tool_name(tool_name: str) -> str:
        """剥离 builtin_ 前缀，使执行期工具名与 AgentDefinition.tools 声明名对齐。"""
        name = str(tool_name or "")
        if name.startswith("builtin_"):
            return name[len("builtin_"):]
        return name

    def _map_tool_to_operation(self, tool_name: str, tool_args: Optional[Dict[str, Any]] = None) -> str:
        """将工具名映射到操作类别（先归一化 builtin_ 前缀再映射）。"""
        normalized = self._normalize_tool_name(tool_name)
        if normalized in _TOOL_OPERATION_MAP:
            return _TOOL_OPERATION_MAP[normalized]

        # 根据前缀推断
        for prefix in _DANGEROUS_PREFIXES:
            if normalized.startswith(prefix):
                return "command:execute"

        if normalized.startswith("mcp_"):
            return "network:http"

        if normalized.startswith("task_"):
            return "system:config"

        # 显式只读前缀：read_/list_/search_/get_/find_/check_/query_/fetch_ 等一律视为只读
        if normalized.startswith(_READONLY_PREFIXES):
            return "file:read"

        # 通用映射
        return "command:execute"

    def _is_write_operation(self, tool_name: str, operation: str) -> bool:
        """判断是否为写入操作（基于归一化后的工具名与前缀）。"""
        normalized = self._normalize_tool_name(tool_name)
        if operation in ("file:write", "file:delete", "command:execute",
                         "plugin:install", "skill:install",
                         "user:manage", "system:config"):
            return True
        if any(normalized.startswith(p) for p in _DANGEROUS_PREFIXES):
            return True
        return False

    def get_allowed_tools(self, permission_mode: str) -> Optional[list]:
        """
        根据权限模式返回允许的工具列表。
        plan / dont_ask 模式返回只读工具白名单（同时含声明名与 builtin_ 执行名），
        其他模式返回 None（无限制）。
        """
        if permission_mode in ("plan", "dont_ask"):
            base = [k for k, v in _TOOL_OPERATION_MAP.items()
                    if v in ("file:read", "file:list", "network:http")]
            result: list = []
            for name in base:
                if name not in result:
                    result.append(name)
                prefixed = f"builtin_{name}"
                if prefixed not in result:
                    result.append(prefixed)
            return result
        return None


# 模块级单例
permission_guard = PermissionGuard()
