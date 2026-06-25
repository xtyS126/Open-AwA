"""
内建工具条目定义模块，将 BUILTIN_TOOL_DEFINITIONS 中的工具定义
注册到全局 ToolRegistry，并为每个工具声明权限 action/resource。

通过 register_builtin_tools() 将内置工具注册到 ToolRegistry 中，
支持权限感知的工具过滤和统一执行调度。
"""

from typing import Any, Dict, List, Optional

from loguru import logger

from core.tool_factory import build_tool, is_command_read_only
from core.tool_use_context import ToolUseContext, coerce_tool_context
from core.tool_registry import (
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


# 内置工具的并发属性配置（按内部工具名索引）
# 失败关闭：未在此映射中的工具使用 TOOL_DEFAULTS 默认值（偏向不并发执行）
# 字段含义参见 ToolDefinition 的并发属性字段
_TOOL_CONCURRENCY_ATTRS: Dict[str, Dict[str, Any]] = {
    # 只读文件操作：无副作用，可安全并发
    "read_file": {"is_read_only": True, "is_concurrency_safe": True},
    "list_files": {"is_read_only": True, "is_concurrency_safe": True},
    "file_exists": {"is_read_only": True, "is_concurrency_safe": True},
    # 破坏性文件操作：有副作用，不并发执行
    "write_file": {"is_destructive": True, "is_concurrency_safe": False},
    "delete_file": {"is_destructive": True, "is_concurrency_safe": False},
    "create_directory": {"is_destructive": True, "is_concurrency_safe": False},
    # 命令执行：输入驱动判定，仅只读命令并发安全
    "run_command": {"is_concurrency_safe": is_command_read_only},
    # 只读网络操作：无副作用，可安全并发
    "web_search": {"is_read_only": True, "is_concurrency_safe": True},
    "fetch_url": {"is_read_only": True, "is_concurrency_safe": True},
    # 只读系统状态：无副作用，可安全并发
    "get_system_status": {"is_read_only": True, "is_concurrency_safe": True},
    # 只读本地搜索：无副作用，可安全并发
    "local_search": {"is_read_only": True, "is_concurrency_safe": True},
    "search_stats": {"is_read_only": True, "is_concurrency_safe": True},
    # 只读记忆检索：无副作用，可安全并发
    "memory_recall": {"is_read_only": True, "is_concurrency_safe": True},
    "memory_list": {"is_read_only": True, "is_concurrency_safe": True},
    "memory_stats": {"is_read_only": True, "is_concurrency_safe": True},
    # 只读检查点列表：无副作用，可安全并发
    "list_checkpoints": {"is_read_only": True, "is_concurrency_safe": True},
    # 只读浏览器操作：无副作用，可安全并发
    "browser_screenshot": {"is_read_only": True, "is_concurrency_safe": True},
    "browser_snapshot": {"is_read_only": True, "is_concurrency_safe": True},
    "browser_navigate": {"is_read_only": True, "is_concurrency_safe": True},
}


async def _execute_tool_async(parameters: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """通过 builtin_tool_manager 异步执行内置工具。

    context 中的 tool_name 字段用于标识要执行的工具名称。
    渐进式迁移：从 context 中提取 ToolUseContext，用于中止检查与延迟记录。
    """
    tool_name = context.get("tool_name", "")
    if tool_name not in BUILTIN_TOOL_ACTION_MAP:
        return {"success": False, "error": f"未知内置工具: {tool_name}"}

    # 通过适配器从 context 提取 ToolUseContext（支持 Dict 和 ToolUseContext 两种传入形式）
    tool_ctx = coerce_tool_context(context.get("_tool_use_context") or context)

    # 中止检查：若 abort_controller 已触发，跳过工具执行
    if tool_ctx.abort_controller is not None and tool_ctx.abort_controller.is_aborted():
        return {"success": False, "error": f"工具执行已被中止: {tool_name}"}

    import time as _time
    _started = _time.perf_counter()
    try:
        result = await builtin_tool_manager.execute_tool(tool_name, parameters)
        return result
    except Exception as e:
        return {"success": False, "error": f"工具执行异常: {type(e).__name__}: {str(e)}"}
    finally:
        # 通过 ToolUseContext 回调记录工具延迟
        _elapsed_ms = (_time.perf_counter() - _started) * 1000
        if tool_ctx.record_latency is not None:
            try:
                tool_ctx.record_latency(tool_name, _elapsed_ms)
            except Exception as latency_exc:
                # 延迟记录为非关键路径，失败时记录日志但不影响工具结果
                logger.warning(f"工具延迟记录回调异常: {tool_name}: {latency_exc}")


def register_builtin_tools(registry: Optional[ToolRegistry] = None) -> ToolRegistry:
    """将内置工具注册到 ToolRegistry 中。

    每个工具声明：
    - permission_action：用于权限决策
    - permission_resource：资源范围
    - execute：异步执行函数
    - 并发属性：通过 _TOOL_CONCURRENCY_ATTRS 声明，经 build_tool 工厂构造

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

        # 组装工具配置，合并并发属性
        tool_config: Dict[str, Any] = {
            "name": func_name_full,
            "description": func_block.get("description", ""),
            "parameters_schema": func_block.get(
                "parameters", {"type": "object", "properties": {}}
            ),
            "permission_action": permission_action,
            "permission_resource": permission_resource,
            "priority": ToolPriority.LOCATION,
            "execute": _execute_wrapper,
            "metadata": {
                "internal_name": internal_name,
                "category": "builtin",
            },
        }
        # 合并并发属性（缺失时由 build_tool 回退到 TOOL_DEFAULTS）
        tool_config.update(_TOOL_CONCURRENCY_ATTRS.get(internal_name, {}))

        # 通过工厂构造 ToolDefinition，统一并发属性默认值与校验
        tool_def = build_tool(tool_config)
        reg.register(tool_def)

    logger.info(f"已注册 {len(BUILTIN_TOOL_DEFINITIONS)} 个内置工具到 ToolRegistry")
    return reg


def get_builtin_permission(action: str) -> Optional[tuple[str, str]]:
    """根据操作名获取内建工具的权限信息（用于向后兼容）。"""
    return _BUILTIN_PERMISSION_MAP.get(action)
