"""
内建工具条目定义模块，将 BUILTIN_TOOL_DEFINITIONS 中的工具定义
注册到全局 ToolRegistry，并为每个工具声明权限 action/resource。

通过 register_builtin_tools() 将内置工具注册到 ToolRegistry 中，
支持权限感知的工具过滤和统一执行调度。
"""

from typing import Any, Dict, List, Optional

from loguru import logger

from core.tool_registry import (
    ToolDefinition,
    ToolPriority,
    ToolRegistry,
    tool_registry,
)
from core.builtin_tools.manager import (
    BUILTIN_TOOL_DEFINITIONS,
    BUILTIN_TOOL_ACTION_MAP,
    builtin_tool_manager,
)


# 内建工具的权限映射（action -> resource）
# 文件操作属于 file:* 资源，命令执行属于 command:* 资源，网络操作属于 network:* 资源
_BUILTIN_PERMISSION_MAP: Dict[str, tuple[str, str]] = {
    "read_file": ("read", "file:read"),
    "write_file": ("write", "file:write"),
    "list_files": ("read", "file:list"),
    "delete_file": ("write", "file:delete"),
    "file_exists": ("read", "file:exists"),
    "create_directory": ("write", "file:create"),
    "run_command": ("execute", "command:execute"),
    "get_system_status": ("read", "system:info"),
    "web_search": ("web_search", "network:web_search"),
    "local_search": ("read", "local:search"),
    "index_document": ("write", "local:index"),
    "index_directory": ("write", "local:index"),
    "remove_document": ("write", "local:delete"),
    "search_stats": ("read", "local:stats"),
    "memory_remember": ("write", "memory:write"),
    "memory_recall": ("read", "memory:read"),
    "memory_forget": ("write", "memory:delete"),
    "memory_list": ("read", "memory:list"),
    "memory_stats": ("read", "memory:stats"),
    "list_checkpoints": ("read", "checkpoint:list"),
    "restore_checkpoint": ("write", "checkpoint:restore"),
    "todo_write": ("write", "todo:write"),
    "notify": ("notify", "notification:send"),
    "browser_screenshot": ("read", "browser:screenshot"),
    "browser_snapshot": ("read", "browser:snapshot"),
    "browser_navigate": ("read", "browser:navigate"),
}


async def _execute_tool_async(parameters: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """通过 builtin_tool_manager 异步执行内置工具。

    context 中的 tool_name 字段用于标识要执行的工具名称。
    """
    tool_name = context.get("tool_name", "")
    if tool_name not in BUILTIN_TOOL_ACTION_MAP:
        return {"success": False, "error": f"未知内置工具: {tool_name}"}
    try:
        result = await builtin_tool_manager.execute_tool(tool_name, parameters)
        return result
    except Exception as e:
        return {"success": False, "error": f"工具执行异常: {type(e).__name__}: {str(e)}"}


def register_builtin_tools(registry: Optional[ToolRegistry] = None) -> ToolRegistry:
    """将内置工具注册到 ToolRegistry 中。

    每个工具声明：
    - permission_action：用于权限决策
    - permission_resource：资源范围
    - execute：异步执行函数

    返回注册完成后的 ToolRegistry 实例。
    """
    reg = registry or tool_registry

    for tool_def_dict in BUILTIN_TOOL_DEFINITIONS:
        func_block = tool_def_dict.get("function", {})
        func_name_full = func_block.get("name", "")

        # 去掉 builtin_ 前缀获取内部工具名
        if func_name_full.startswith("builtin_"):
            internal_name = func_name_full[len("builtin_"):]
        else:
            internal_name = func_name_full

        # 获取权限映射
        permission_action, permission_resource = _BUILTIN_PERMISSION_MAP.get(
            internal_name, (internal_name, f"builtin:{internal_name}")
        )
        if internal_name not in _BUILTIN_PERMISSION_MAP:
            logger.warning(f"内置工具 '{internal_name}' 缺少权限映射，使用默认值")

        # 构造执行封装函数（通过闭包捕获循环变量 current_name）
        _current_name = internal_name
        async def _execute_wrapper(params: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
            ctx_with_name = {**(ctx or {}), "tool_name": _current_name}
            return await _execute_tool_async(params, ctx_with_name)

        tool_def = ToolDefinition(
            name=func_name_full,
            description=func_block.get("description", ""),
            parameters_schema=func_block.get("parameters", {"type": "object", "properties": {}}),
            permission_action=permission_action,
            permission_resource=permission_resource,
            priority=ToolPriority.LOCATION,
            execute=_execute_wrapper,
            metadata={
                "internal_name": internal_name,
                "category": "builtin",
            },
        )
        reg.register(tool_def)

    logger.info(f"已注册 {len(BUILTIN_TOOL_DEFINITIONS)} 个内置工具到 ToolRegistry")
    return reg


def get_builtin_permission(action: str) -> Optional[tuple[str, str]]:
    """根据操作名获取内建工具的权限信息（用于向后兼容）。"""
    return _BUILTIN_PERMISSION_MAP.get(action)
