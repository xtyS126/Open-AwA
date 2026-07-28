"""工具调用完成事件的领域派发器。"""

from __future__ import annotations

import json
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional

from core.agent_helpers import extract_spawned_subagent_result, summarize_stream_tool_result
from core.streaming_events import (
    emit_subagent_start_event,
    emit_task_created_event,
    emit_task_updated_event,
    emit_team_event,
    emit_tool_event,
)
from core.tool_dispatcher import ToolNames


class ToolEventEmitter:
    """根据工具调用结果生成统一工具事件与后续领域事件。"""

    _SUCCESS_EVENT_BUILDERS: Dict[str, Callable[[Any], Optional[Dict[str, Any]]]]

    def __init__(self) -> None:
        self._SUCCESS_EVENT_BUILDERS = {
            ToolNames.NOTIFY: self._build_notification_event,
            ToolNames.BUILTIN_TODO_WRITE: self._build_todo_update_event,
            ToolNames.CREATE_TASK: self._build_task_created_event,
            ToolNames.UPDATE_TASK: self._build_task_updated_event,
            ToolNames.TASK_TODO_WRITE: self._build_todo_update_event,
            ToolNames.CREATE_TEAM: self._build_team_event,
            ToolNames.DELETE_TEAM: self._build_team_event,
            ToolNames.ADD_TEAMMATE: self._build_team_event,
            ToolNames.REMOVE_TEAMMATE: self._build_team_event,
        }

    async def emit(
        self,
        tool_call: Dict[str, Any],
        context: Dict[str, Any],
        call_state: Any,
        accumulated_events: List[Dict[str, Any]],
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """触发 PostToolUse 钩子并输出工具完成及后续领域事件。"""
        await self._dispatch_post_tool_use_hook(tool_call, context, call_state)
        tool_event = self._build_completed_tool_event(call_state)
        accumulated_events.append(tool_event)
        yield emit_tool_event(tool_event)
        async for event in self._iter_followup_events(call_state):
            yield event

    @staticmethod
    async def _dispatch_post_tool_use_hook(
        tool_call: Dict[str, Any], context: Dict[str, Any], call_state: Any,
    ) -> None:
        """触发可选的 PostToolUse 钩子，缺少运行时模块时保持降级。"""
        try:
            from core.task_runtime.hook_dispatcher import hook_dispatcher, HOOK_POST_TOOL_USE
            arguments = tool_call.get("function", {}).get("arguments", "{}")
            await hook_dispatcher.dispatch(HOOK_POST_TOOL_USE, {
                "tool_name": call_state.tool_name,
                "tool_args": json.loads(arguments) if isinstance(arguments, str) else {},
                "result": call_state.result,
                "context": context,
            })
        except ImportError:
            pass

    @staticmethod
    def _build_completed_tool_event(call_state: Any) -> Dict[str, Any]:
        """构造统一的工具成功或失败事件。"""
        result = call_state.result
        return {
            "id": call_state.tool_id,
            "kind": call_state.tool_kind,
            "name": call_state.tool_name,
            "status": "completed" if result.get("ok") else "error",
            "detail": summarize_stream_tool_result(result),
            "output": result.get("result") if result.get("ok") else result.get("error"),
        }

    async def _iter_followup_events(self, call_state: Any) -> AsyncGenerator[Dict[str, Any], None]:
        """派发后台子代理与成功工具的后续事件。"""
        if call_state.tool_name == ToolNames.SPAWN_AGENT:
            event = self._build_background_subagent_event(call_state)
            if event is not None:
                yield event
        if not call_state.result.get("ok"):
            return
        builder = self._SUCCESS_EVENT_BUILDERS.get(call_state.tool_name)
        if builder is None:
            return
        event = builder(call_state)
        if event is not None:
            yield event

    @staticmethod
    def _build_notification_event(call_state: Any) -> Optional[Dict[str, Any]]:
        """构造前端通知事件。"""
        result = call_state.result.get("result")
        if not isinstance(result, dict):
            return None
        return {
            "type": "notification",
            "title": result.get("title", ""),
            "body": result.get("body", ""),
            "channels": result.get("channels", []),
            "message": result.get("message", ""),
        }

    @staticmethod
    def _build_todo_update_event(call_state: Any) -> Optional[Dict[str, Any]]:
        """构造 Todo 面板更新事件。"""
        result = call_state.result.get("result", call_state.result)
        if not isinstance(result, dict):
            return None
        return {
            "type": "todo_update",
            "todos": result.get("todos", []),
            "counts": result.get("counts", {}),
            "summary": result.get("summary", ""),
        }

    @staticmethod
    def _build_task_created_event(call_state: Any) -> Dict[str, Any]:
        """构造任务创建生命周期事件。"""
        return emit_task_created_event(call_state.result.get("result", call_state.result))

    @staticmethod
    def _build_task_updated_event(call_state: Any) -> Dict[str, Any]:
        """构造任务更新生命周期事件。"""
        return emit_task_updated_event(call_state.result.get("result", call_state.result))

    @staticmethod
    def _build_team_event(call_state: Any) -> Dict[str, Any]:
        """构造团队生命周期事件。"""
        return emit_team_event(call_state.result.get("result", call_state.result))

    @staticmethod
    def _build_background_subagent_event(call_state: Any) -> Optional[Dict[str, Any]]:
        """后台子代理启动时标记状态并构造启动事件。"""
        spawned_subagent = extract_spawned_subagent_result(call_state.result)
        if not spawned_subagent or spawned_subagent.get("run_mode") != "background":
            return None
        call_state.mark_background_subagent()
        return emit_subagent_start_event(
            spawned_subagent["agent_id"],
            call_state.spawn_agent_type,
            call_state.spawn_description,
            run_mode="background",
        )
