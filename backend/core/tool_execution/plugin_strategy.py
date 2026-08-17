"""
插件工具执行策略：处理 plugin_ 前缀的工具调用。
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from loguru import logger

from .base import ToolExecutionStrategy, ToolExecutionContext, ToolExecutionResult


class PluginToolStrategy(ToolExecutionStrategy):
    """插件工具执行策略"""

    def __init__(self, plugin_manager=None, mixin=None):
        self._plugin_manager = plugin_manager
        self._mixin = mixin

    def can_handle(self, tool_name: str) -> bool:
        return tool_name.startswith("plugin_")

    async def execute(self, context: ToolExecutionContext) -> ToolExecutionResult:
        """通过 PluginManager 执行插件工具"""
        func_name = context.tool_name
        func_args = dict(context.tool_input)
        raw_context = context.raw_context

        remaining = func_name[len("plugin_"):]
        if "__" in remaining:
            plugin_name, plugin_method = remaining.split("__", 1)
        else:
            return ToolExecutionResult(
                output=None,
                error=f"plugin tool name missing '__' separator: {func_name}",
            )

        from plugins import plugin_instance

        try:
            pm = plugin_instance.get()
            candidate_names = []
            for candidate in (
                plugin_name,
                plugin_name.replace("_", "-"),
                plugin_name.replace("-", "_"),
            ):
                if candidate and candidate not in candidate_names:
                    candidate_names.append(candidate)

            if not any(pm.has_plugin(candidate) for candidate in candidate_names):
                discovered = pm.discover_plugins()
                logger.bind(
                    module="executor",
                    event="plugin_metadata_refreshed",
                    requested_plugin=plugin_name,
                    discovered_count=len(discovered) if isinstance(discovered, list) else None,
                ).debug(f"工具调用前刷新插件元数据: {plugin_name}")

            resolved_plugin_name = next(
                (
                    candidate
                    for candidate in candidate_names
                    if pm.has_plugin(candidate) or pm.is_plugin_loaded(candidate)
                ),
                plugin_name,
            )

            if (
                resolved_plugin_name not in pm.loaded_plugins
                and not pm.load_plugin(resolved_plugin_name)
            ):
                return ToolExecutionResult(
                    output=None,
                    error=f"Failed to load plugin: {resolved_plugin_name}",
                )

            result = await pm.execute_registered_tool_async(
                resolved_plugin_name,
                plugin_method,
                db=raw_context.get("db"),
                user_id=raw_context.get("user_id"),
                **func_args,
            )

            # 检查插件返回结果状态
            if isinstance(result, dict) and result.get("status") == "error":
                return ToolExecutionResult(
                    output=None,
                    error=result.get("message", "Plugin returned error"),
                )

            output = {"ok": True, "result": result, "tool_name": func_name}

            # 应用 PostToolUse 钩子
            if self._mixin is not None and hasattr(self._mixin, "_apply_post_tool_use_hooks"):
                output = await self._mixin._apply_post_tool_use_hooks(output, func_name, raw_context)

            return ToolExecutionResult(output=output)

        except Exception as exc:
            logger.bind(
                module="executor",
                event="plugin_execution_error",
                plugin_name=plugin_name,
                plugin_method=plugin_method,
            ).error(f"插件执行异常: {exc}")
            return ToolExecutionResult(
                output=None,
                error=f"Plugin execution error: {str(exc)}",
            )