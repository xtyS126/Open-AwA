"""
统一内置工具注册器（兼容层）。
委托给 core.builtin_tools.manager.BuiltInToolManager，保持旧式 API 调用方兼容。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from loguru import logger

from core.builtin_tools.manager import builtin_tool_manager


class BuiltInToolRegistry:
    """
    内置工具注册器（兼容层）。
    委托给 core/builtin_tools/manager.py 的 BuiltInToolManager。
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
    ) -> Dict[str, Any]:
        """执行指定内置工具动作（兼容旧式调用）。"""
        return await builtin_tool_manager.execute_tool(
            tool_name,
            params=params or {},
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