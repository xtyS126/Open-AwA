"""
MCP 工具执行策略：处理 mcp__ 前缀（三段式 mcp__<server_id>__<tool>）的工具调用。
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from loguru import logger

from .base import ToolExecutionStrategy, ToolExecutionContext, ToolExecutionResult


class MCPToolStrategy(ToolExecutionStrategy):
    """MCP 工具执行策略"""

    def __init__(self, mcp_manager=None, mixin=None):
        self._mcp_manager = mcp_manager
        self._mixin = mixin

    def can_handle(self, tool_name: str) -> bool:
        return tool_name.startswith("mcp_")

    async def execute(self, context: ToolExecutionContext) -> ToolExecutionResult:
        """通过 MCPManager 执行 MCP 工具"""
        func_name = context.tool_name
        func_args = dict(context.tool_input)
        raw_context = context.raw_context

        # 工具名统一为 mcp__<server_id>__<tool>，去掉 mcp__ 前缀后按 __ 拆出 server_id
        remaining = func_name[len("mcp__"):]
        if "__" in remaining:
            server_id, mcp_tool_name = remaining.split("__", 1)
        else:
            return ToolExecutionResult(
                output=None,
                error=f"MCP tool name missing '__' separator: {func_name}",
            )

        # 服务级权限门禁
        if self._mixin is not None and hasattr(self._mixin, "_check_mcp_permission"):
            permission_denial = await self._mixin._check_mcp_permission(
                full_tool_name=func_name,
                server_id=server_id,
                context=raw_context,
            )
            if permission_denial is not None:
                return ToolExecutionResult(output=permission_denial)

        try:
            from mcp_integration.manager import MCPManager

            manager = MCPManager()
            result = await manager.call_tool(server_id, mcp_tool_name, func_args)

            output = {"ok": True, "result": result, "tool_name": func_name}

            # 应用 PostToolUse 钩子
            if self._mixin is not None and hasattr(self._mixin, "_apply_post_tool_use_hooks"):
                output = await self._mixin._apply_post_tool_use_hooks(output, func_name, raw_context)

            return ToolExecutionResult(output=output)

        except Exception as exc:
            logger.bind(
                module="executor",
                event="mcp_execution_error",
                server_id=server_id,
                tool_name=mcp_tool_name,
            ).error(f"MCP工具执行异常: {exc}")
            return ToolExecutionResult(
                output=None,
                error=f"MCP tool execution error: {str(exc)}",
            )