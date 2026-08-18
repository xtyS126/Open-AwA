"""
统一内置工具注册器（兼容层）。
委托给 core.builtin_tools.manager.BuiltInToolManager，保持旧式 API 调用方兼容。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from loguru import logger

from core.builtin_tools.manager import BUILTIN_TOOL_ACTION_MAP, builtin_tool_manager

# 反向映射：(内部工具名, action) -> 扁平工具名，用于把旧式调用收敛到 ToolRegistry
_REVERSE_TOOL_ACTION_MAP: Dict[tuple[str, str], str] = {
    (tool_name, action): flat_name
    for flat_name, (tool_name, action) in BUILTIN_TOOL_ACTION_MAP.items()
}


class BuiltInToolRegistry:
    """
    内置工具注册器（兼容层）。
    优先委托给 core/tool_registry.py 的 ToolRegistry（统一权限/截断/统计语义），
    未注册时回退到 core/builtin_tools/manager.py 的 BuiltInToolManager（旧式直连）。
    """

    def __init__(self):
        self._instances: Dict[str, Any] = {}

    async def list_tools(self) -> Dict[str, Dict[str, Any]]:
        """返回全部内置工具的定义与状态。"""
        return await builtin_tool_manager.list_tools()

    async def execute_tool(
        self,
        tool_name: str,
        *,
        action: str,
        params: Optional[Dict[str, Any]] = None,
        config: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """执行指定内置工具动作（兼容旧式调用）。

        收敛策略：若 (tool_name, action) 能映射到已注册的扁平工具，则统一走
        ToolRegistry.execute（获得权限检查/输出截断/执行统计语义），
        否则回退到 BuiltInToolManager 旧式直连路径（保持兼容）。
        """
        params = params or {}
        flat_name = _REVERSE_TOOL_ACTION_MAP.get((tool_name, action))
        if flat_name:
            from core.tool_registry import tool_registry

            registered = tool_registry.get(f"builtin_{flat_name}")
            if registered is not None:
                try:
                    exec_ctx = dict(context or {})
                    if config is not None:
                        # 工具配置（如 allowed_directories）经上下文透传给执行层，
                        # 避免 ToolRegistry 路径丢失 config 导致文件工具误判越权。
                        exec_ctx["_tool_config"] = config
                    exec_result = await tool_registry.execute(
                        f"builtin_{flat_name}", params, exec_ctx
                    )
                    if exec_result.status.value == "completed" and isinstance(exec_result.result, dict):
                        return exec_result.result
                    return {
                        "success": False,
                        "error": exec_result.error or "工具执行失败",
                    }
                except Exception as exc:
                    logger.bind(
                        module="tools",
                        event="tool_registry_execution_error",
                        tool_name=tool_name,
                        action=action,
                    ).error(f"ToolRegistry 执行失败，回退旧式直连: {exc}")
        return await builtin_tool_manager.execute_tool(
            tool_name,
            params=params,
            action=action,
            config=config,
        )

    def seed_built_in_skills(self, db_session) -> int:
        """
        已废弃：内置工具不再以技能配置形式写入数据库。
        保留空方法以避免调用方报错。
        """
        logger.debug("seed_built_in_skills 已废弃，内置工具不再通过技能系统注册")
        return 0


built_in_tool_registry = BuiltInToolRegistry()