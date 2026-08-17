"""
任务工具执行策略：处理 task_ 前缀的工具调用（子Agent 生成、任务清单、团队管理等）。
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from loguru import logger

from .base import ToolExecutionStrategy, ToolExecutionContext, ToolExecutionResult


class TaskToolStrategy(ToolExecutionStrategy):
    """任务工具执行策略"""

    def __init__(self, task_runtime=None, mixin=None):
        self._task_runtime = task_runtime
        self._mixin = mixin

    def can_handle(self, tool_name: str) -> bool:
        return tool_name.startswith("task_")

    async def execute(self, context: ToolExecutionContext) -> ToolExecutionResult:
        """通过 TaskRuntime 执行任务工具"""
        func_name = context.tool_name
        func_args = dict(context.tool_input)
        raw_context = context.raw_context
        on_subagent_event = context.extra.get("on_subagent_event")

        task_action = func_name[len("task_"):]

        from core.task_runtime import task_runtime

        await task_runtime.initialize()

        if task_action == "spawn_agent":
            return await self._handle_spawn_agent(
                func_name, func_args, raw_context, on_subagent_event
            )

        elif task_action == "send_message":
            to = func_args.get("to", "")
            message = func_args.get("message", "")
            result = await task_runtime.send_message(to=to, message=message)
            return ToolExecutionResult(
                output={"ok": result.get("ok", True), "result": result, "tool_name": func_name}
            )

        elif task_action == "stop_agent":
            agent_id = func_args.get("agent_id", "")
            result = await task_runtime.stop_agent(agent_id)
            return ToolExecutionResult(
                output={"ok": result.get("ok", True), "result": result, "tool_name": func_name}
            )

        elif task_action == "list_agents":
            state_filter = func_args.get("state")
            result = await task_runtime.list_agents(state=state_filter)
            return ToolExecutionResult(
                output={"ok": True, "result": {"agents": result}, "tool_name": func_name}
            )

        elif task_action == "list_agent_types":
            result = await task_runtime.list_agent_types()
            return ToolExecutionResult(
                output={"ok": True, "result": {"agent_types": result}, "tool_name": func_name}
            )

        elif task_action == "create_task":
            result = await task_runtime.create_task_item(
                list_id=func_args.get("list_id"),
                subject=func_args.get("subject", ""),
                description=func_args.get("description"),
                dependencies=func_args.get("dependencies"),
                owner_agent_id=func_args.get("owner_agent_id"),
            )
            return ToolExecutionResult(
                output={"ok": result.get("ok", True), "result": result, "tool_name": func_name}
            )

        elif task_action == "list_tasks":
            result = await task_runtime.list_task_items(
                list_id=func_args.get("list_id"),
                status=func_args.get("status"),
            )
            return ToolExecutionResult(
                output={"ok": True, "result": {"tasks": result}, "tool_name": func_name}
            )

        elif task_action == "update_task":
            result = await task_runtime.update_task_item(
                func_args.get("task_id", ""),
                status=func_args.get("status"),
                subject=func_args.get("subject"),
                owner_agent_id=func_args.get("owner_agent_id"),
                result_summary=func_args.get("result_summary"),
            )
            return ToolExecutionResult(
                output={"ok": result.get("ok", True), "result": result, "tool_name": func_name}
            )

        elif task_action == "claim_task":
            task_id = func_args.get("task_id", "")
            agent_id = raw_context.get("agent_id", raw_context.get("session_id", "unknown"))
            result = await task_runtime.claim_task_item(task_id=task_id, agent_id=agent_id)
            return ToolExecutionResult(
                output={"ok": result.get("ok", True), "result": result, "tool_name": func_name}
            )

        elif task_action == "get_task":
            task_id = func_args.get("task_id", "")
            result = await task_runtime.get_task_item(task_id)
            if not result:
                return ToolExecutionResult(
                    output=None,
                    error=f"任务不存在: {task_id}",
                )
            return ToolExecutionResult(
                output={"ok": True, "result": result, "tool_name": func_name}
            )

        elif task_action == "create_team":
            result = await task_runtime.create_team(
                lead_agent_id=func_args.get("lead_agent_id", ""),
                name=func_args.get("name", ""),
                teammate_agent_ids=func_args.get("teammate_agent_ids"),
                task_list_id=func_args.get("task_list_id"),
            )
            return ToolExecutionResult(
                output={"ok": result.get("ok", True), "result": result, "tool_name": func_name}
            )

        elif task_action == "delete_team":
            result = await task_runtime.delete_team(func_args.get("team_id", ""))
            return ToolExecutionResult(
                output={"ok": result.get("ok", True), "result": result, "tool_name": func_name}
            )

        elif task_action == "list_teams":
            result = await task_runtime.list_teams(state=func_args.get("state"))
            return ToolExecutionResult(
                output={"ok": True, "result": {"teams": result}, "tool_name": func_name}
            )

        elif task_action == "get_team":
            result = await task_runtime.get_team(func_args.get("team_id", ""))
            if not result:
                return ToolExecutionResult(
                    output=None,
                    error=f"团队不存在: {func_args.get('team_id')}",
                )
            return ToolExecutionResult(
                output={"ok": True, "result": result, "tool_name": func_name}
            )

        elif task_action == "add_teammate":
            result = await task_runtime.add_teammate(
                func_args.get("team_id", ""),
                func_args.get("agent_id", ""),
                func_args.get("name", ""),
            )
            return ToolExecutionResult(
                output={"ok": result.get("ok", True), "result": result, "tool_name": func_name}
            )

        elif task_action == "remove_teammate":
            result = await task_runtime.remove_teammate(
                func_args.get("team_id", ""),
                func_args.get("agent_id", ""),
            )
            return ToolExecutionResult(
                output={"ok": result.get("ok", True), "result": result, "tool_name": func_name}
            )

        elif task_action == "get_mailbox":
            result = await task_runtime.get_mailbox(
                agent_id=func_args.get("agent_id", ""),
                unread_only=func_args.get("unread_only", False),
            )
            return ToolExecutionResult(
                output={"ok": True, "result": {"messages": result}, "tool_name": func_name}
            )

        elif task_action == "todo_write":
            result = await task_runtime.sync_todo_snapshot(
                list_id=func_args.get("list_id"),
                todos=func_args.get("todos", []),
            )
            return ToolExecutionResult(
                output={"ok": result.get("ok", True), "result": result, "tool_name": func_name}
            )

        else:
            return ToolExecutionResult(
                output=None,
                error=f"未知任务运行时工具: {task_action}",
            )

    async def _handle_spawn_agent(
        self,
        func_name: str,
        func_args: Dict[str, Any],
        raw_context: Dict[str, Any],
        on_subagent_event: Any,
    ) -> ToolExecutionResult:
        """处理 task_spawn_agent 子代理生成逻辑"""
        from core.task_runtime import task_runtime

        agent_type = func_args.get("agent_type", "Explore")
        prompt = func_args.get("prompt", "")
        description = func_args.get("description", "")
        provider, model, model_error = self._resolve_model(func_args, raw_context)
        if model_error:
            logger.bind(
                module="executor",
                event="subagent_model_resolution_failed",
                agent_type=agent_type,
            ).warning(model_error)
            return ToolExecutionResult(
                output=None,
                error=model_error,
            )

        background = func_args.get("background", False)
        fork_mode = func_args.get("fork_mode", False)
        logger.bind(
            module="executor",
            event="subagent_spawn_requested",
            agent_type=agent_type,
            provider=provider,
            model=model,
            background=background,
            fork_mode=fork_mode,
        ).info(f"准备启动子代理: {agent_type}")

        result = await task_runtime.spawn_agent(
            agent_type=agent_type,
            prompt=prompt,
            description=description,
            provider=provider,
            model=model,
            background=background,
            fork_mode=fork_mode,
            root_chat_session_id=raw_context.get("session_id"),
            context=raw_context,
        )

        if isinstance(result, dict):
            return ToolExecutionResult(
                output={"ok": result.get("ok", True), "result": result, "tool_name": func_name}
            )

        # 前台子代理流式消费
        if self._mixin is not None and hasattr(self._mixin, "_consume_foreground_subagent_stream"):
            consumed = await self._mixin._consume_foreground_subagent_stream(
                result,
                func_name,
                on_subagent_event=on_subagent_event,
            )
            return ToolExecutionResult(output=consumed)

        return ToolExecutionResult(
            output=None,
            error="无法消费前台子代理流",
        )

    def _resolve_model(
        self,
        func_args: Dict[str, Any],
        raw_context: Dict[str, Any],
    ) -> tuple:
        """解析子代理模型选择"""
        if self._mixin is not None and hasattr(self._mixin, "_resolve_subagent_model_selection"):
            return self._mixin._resolve_subagent_model_selection(
                raw_context,
                func_args.get("provider"),
                func_args.get("model"),
            )
        return None, None, "子代理模型解析不可用"