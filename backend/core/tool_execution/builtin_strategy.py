"""
内置工具执行策略：处理 builtin_ 前缀的工具调用。
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from loguru import logger

from .base import ToolExecutionStrategy, ToolExecutionContext, ToolExecutionResult


class BuiltinToolStrategy(ToolExecutionStrategy):
    """内置工具执行策略"""

    def __init__(self, tool_registry=None, mixin=None):
        self._tool_registry = tool_registry
        self._mixin = mixin

    def can_handle(self, tool_name: str) -> bool:
        return tool_name.startswith("builtin_") or (
            not tool_name.startswith("plugin_")
            and not tool_name.startswith("mcp_")
            and not tool_name.startswith("task_")
        )

    async def execute(self, context: ToolExecutionContext) -> ToolExecutionResult:
        """通过 ToolRegistry 执行内置工具"""
        if self._tool_registry is None:
            return ToolExecutionResult(output=None, error="ToolRegistry 未初始化")

        func_name = context.tool_name
        func_args = dict(context.tool_input)
        raw_context = context.raw_context

        # ask_user 特殊处理：注入 user_id 和 session_id 到工具参数
        if func_name == "builtin_ask_user" or func_name == "ask_user":
            func_args.setdefault("user_id", str(raw_context.get("user_id", "") or ""))
            func_args.setdefault("session_id", str(raw_context.get("session_id", "") or ""))

        # 构造包含 ToolUseContext 的工具执行上下文副本
        tool_exec_context = {**raw_context}
        if self._mixin is not None and hasattr(self._mixin, "_build_tool_use_context"):
            _tool_use_context = self._mixin._build_tool_use_context(raw_context)
            tool_exec_context["_tool_use_context"] = _tool_use_context

        from core.tool_registry import tool_registry as _tool_reg

        try:
            registered_tool = _tool_reg.get(func_name)
            if registered_tool is None or not registered_tool.execute:
                logger.bind(
                    module="executor",
                    event="tool_not_registered_denied",
                    tool_name=func_name,
                ).warning(f"工具 {func_name} 未在 ToolRegistry 注册，已拒绝执行")
                return ToolExecutionResult(
                    output=None,
                    error=f"工具 {func_name} 未在 ToolRegistry 注册，已拒绝执行",
                )

            exec_result = await _tool_reg.execute(func_name, func_args, tool_exec_context)
            output = {
                "ok": exec_result.status.value == "completed",
                "result": exec_result.result,
                "error": exec_result.error,
                "tool_name": func_name,
                "truncated": exec_result.truncated,
                "output_path": exec_result.output_path,
                "execution_time_ms": exec_result.execution_time_ms,
            }

            # 应用 PostToolUse 钩子
            if self._mixin is not None and hasattr(self._mixin, "_apply_post_tool_use_hooks"):
                output = await self._mixin._apply_post_tool_use_hooks(output, func_name, raw_context)

            return ToolExecutionResult(output=output)

        except PermissionError:
            # 权限拒绝：尝试通过实时推送队列请求用户授权
            if self._mixin is not None and hasattr(self._mixin, "_request_user_permission"):
                reply = await self._mixin._request_user_permission(
                    tool_name=func_name,
                    tool_args=func_args,
                    context=raw_context,
                )
                if reply == "reject":
                    return ToolExecutionResult(
                        output=None,
                        error=f"用户拒绝权限: {func_name}",
                    )
                # 用户允许（once/always），重新执行工具
                try:
                    exec_result = await _tool_reg.execute(func_name, func_args, tool_exec_context)
                    output = {
                        "ok": exec_result.status.value == "completed",
                        "result": exec_result.result,
                        "error": exec_result.error,
                        "tool_name": func_name,
                        "truncated": exec_result.truncated,
                        "output_path": exec_result.output_path,
                        "execution_time_ms": exec_result.execution_time_ms,
                    }
                    if self._mixin is not None and hasattr(self._mixin, "_apply_post_tool_use_hooks"):
                        output = await self._mixin._apply_post_tool_use_hooks(output, func_name, raw_context)
                    return ToolExecutionResult(output=output)
                except PermissionError:
                    return ToolExecutionResult(
                        output=None,
                        error=f"权限不足: {func_name}",
                    )
            return ToolExecutionResult(
                output=None,
                error=f"权限不足: {func_name}",
            )

        except Exception:
            logger.bind(
                module="executor",
                event="tool_registry_execution_failed",
                tool_name=func_name,
            ).exception(f"ToolRegistry 执行异常，已拒绝回退到直接执行: {func_name}")
            return ToolExecutionResult(
                output=None,
                error=f"Tool registry execution failed for {func_name}",
            )