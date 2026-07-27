"""工具调用分发领域对象与调用上下文。"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Dict, Optional, Type

from loguru import logger

from core.agent_helpers import get_stream_tool_kind
from core.ports.ask_user_port import AskUserPort
from core.streaming_events import emit_ask_user_event, emit_tool_event


DEFAULT_TOOL_CALL_TIMEOUT_SECONDS = 120.0
MAX_TOOL_CALL_TIMEOUT_SECONDS = 600.0


class ToolNames:
    """Agent 特殊工具名的单一事实来源。"""

    ASK_USER = "builtin_ask_user"
    NOTIFY = "builtin_notify"
    BUILTIN_TODO_WRITE = "builtin_todo_write"
    SPAWN_AGENT = "task_spawn_agent"
    CREATE_TASK = "task_create_task"
    UPDATE_TASK = "task_update_task"
    TASK_TODO_WRITE = "task_todo_write"
    CREATE_TEAM = "task_create_team"
    DELETE_TEAM = "task_delete_team"
    ADD_TEAMMATE = "task_add_teammate"
    REMOVE_TEAMMATE = "task_remove_teammate"


@dataclass
class ToolCallContext:
    """封装一次工具调用的解析状态、执行结果与状态转换。"""

    tool_name: str = ""
    tool_id: str = ""
    tool_kind: str = ""
    spawn_agent_type: str = "Explore"
    spawn_description: str = ""
    func_args: Dict[str, Any] = field(default_factory=dict)
    result: Dict[str, Any] = field(default_factory=dict)
    background_subagents_spawned: bool = False

    def mark_running(
        self,
        tool_name: str,
        tool_id: str,
        func_args: Dict[str, Any],
    ) -> None:
        """记录已解析的工具调用并进入运行状态。"""
        self.tool_name = tool_name
        self.tool_id = tool_id
        self.tool_kind = get_stream_tool_kind(tool_name)
        self.func_args = func_args
        if tool_name == ToolNames.SPAWN_AGENT:
            self.spawn_agent_type = str(func_args.get("agent_type") or "Explore")
            self.spawn_description = str(func_args.get("description") or "")

    def set_result(self, result: Dict[str, Any]) -> None:
        """记录工具执行结果。"""
        self.result = result

    def mark_background_subagent(self) -> None:
        """标记本轮产生后台子代理，供流式编排器决定提前退出。"""
        self.background_subagents_spawned = True


class ToolDispatcher:
    """解析并执行 ask_user、子代理和常规工具调用。"""

    def __init__(
        self,
        executor: Any,
        ask_user_port: Optional[AskUserPort],
        early_exit_type: Type[Exception],
    ) -> None:
        self._executor = executor
        self._ask_user_port = ask_user_port
        self._early_exit_type = early_exit_type

    async def dispatch(
        self,
        tool_call: Dict[str, Any],
        context: Dict[str, Any],
        session_id: str,
        call_context: ToolCallContext,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """发射运行事件并按工具类型执行对应策略。"""
        function = tool_call.get("function", {})
        tool_name = str(function.get("name") or "unknown")
        tool_id = str(tool_call.get("id") or "")
        func_args = self._parse_arguments(function.get("arguments", "{}"))
        call_context.mark_running(tool_name, tool_id, func_args)
        yield emit_tool_event({
            "id": tool_id,
            "kind": call_context.tool_kind,
            "name": tool_name,
            "status": "running",
            "input": func_args,
        })
        if tool_name == ToolNames.ASK_USER:
            async for event in self._dispatch_ask_user(context, session_id, call_context):
                yield event
            return
        async for event in self._dispatch_regular_tool(tool_call, context, session_id, call_context):
            yield event

    @staticmethod
    def _parse_arguments(raw_arguments: Any) -> Dict[str, Any]:
        """把工具参数安全解析为字典。"""
        try:
            parsed = json.loads(raw_arguments) if isinstance(raw_arguments, str) else raw_arguments
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    async def _dispatch_ask_user(
        self,
        context: Dict[str, Any],
        session_id: str,
        call_context: ToolCallContext,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """下发问题卡片并等待用户回答。"""
        ask_args = dict(call_context.func_args)
        ask_args.setdefault("user_id", str(context.get("user_id", "") or ""))
        ask_args.setdefault("session_id", str(context.get("session_id", "") or ""))
        if self._ask_user_port is None:
            raise RuntimeError(
                "ask_user_port not configured; main.py lifespan must inject AskUserPortAdapter"
            )
        try:
            request_id, ask_future = await self._ask_user_port.enqueue(
                user_id=ask_args.get("user_id", ""),
                session_id=ask_args.get("session_id", ""),
                question=ask_args.get("question", ""),
                options=ask_args.get("options"),
                allow_multiple=ask_args.get("allow_multiple", False),
                allow_free_text=ask_args.get("allow_free_text", True),
                placeholder=ask_args.get("placeholder", ""),
                timeout=ask_args.get("timeout", 300),
            )
        except ValueError as error:
            call_context.set_result({
                "ok": False,
                "error": f"ask_user 参数校验失败: {error}",
                "tool_name": call_context.tool_name,
            })
            return
        yield emit_ask_user_event({
            "request_id": request_id,
            "user_id": ask_args.get("user_id", ""),
            "session_id": ask_args.get("session_id", ""),
            "question": ask_args.get("question", ""),
            "options": ask_args.get("options") or [],
            "allow_multiple": ask_args.get("allow_multiple", False),
            "allow_free_text": ask_args.get("allow_free_text", True),
            "placeholder": ask_args.get("placeholder", ""),
            "timeout": ask_args.get("timeout", 300),
        })
        try:
            timeout_seconds = float(ask_args.get("timeout", 300))
            timeout_seconds = min(max(timeout_seconds, 1.0), 300.0)
            answer_payload = await asyncio.wait_for(ask_future, timeout=timeout_seconds)
        except asyncio.TimeoutError:
            call_context.set_result({
                "ok": False,
                "error": "ask_user 等待用户回答超时",
                "tool_name": call_context.tool_name,
                "request_id": request_id,
            })
            return
        except asyncio.CancelledError:
            logger.info(f"ask_user cancelled for session {session_id}")
            yield {"type": "cancelled", "content": "任务已被用户取消", "reasoning_content": ""}
            raise self._early_exit_type()
        call_context.set_result({
            "ok": True,
            "result": answer_payload,
            "tool_name": call_context.tool_name,
            "request_id": request_id,
        })

    async def _dispatch_regular_tool(
        self,
        tool_call: Dict[str, Any],
        context: Dict[str, Any],
        session_id: str,
        call_context: ToolCallContext,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """执行子代理工具并转发事件，或直接执行普通工具。"""
        if call_context.tool_name == ToolNames.SPAWN_AGENT:
            event_queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()

            async def on_subagent_event(event: Dict[str, Any]) -> None:
                await event_queue.put(event)

            execution_task = asyncio.create_task(self._executor._execute_tool_call(
                tool_call, context, on_subagent_event=on_subagent_event,
            ))
            while not execution_task.done() or not event_queue.empty():
                try:
                    yield await asyncio.wait_for(event_queue.get(), timeout=0.05)
                except asyncio.TimeoutError:
                    continue
            call_context.set_result(await execution_task)
            return

        timeout_seconds = self._resolve_tool_timeout(call_context.func_args)
        execution_task = asyncio.create_task(
            self._executor._execute_tool_call(tool_call, context)
        )
        try:
            done, _ = await asyncio.wait({execution_task}, timeout=timeout_seconds)
            if not done:
                execution_task.cancel()
                self._consume_background_task_result(execution_task, session_id)
                call_context.set_result({
                    "ok": False,
                    "error": "工具调用超时",
                    "error_code": "tool_call_timeout",
                    "tool_name": call_context.tool_name,
                })
                return
            call_context.set_result(execution_task.result())
        except asyncio.CancelledError:
            execution_task.cancel()
            self._consume_background_task_result(execution_task, session_id)
            logger.info(f"Agent task cancelled for session {session_id}")
            yield {"type": "cancelled", "content": "任务已被用户取消", "reasoning_content": ""}
            raise self._early_exit_type()

    @staticmethod
    def _resolve_tool_timeout(func_args: Dict[str, Any]) -> float:
        """读取并限制单工具执行超时，避免模型参数造成无限等待。"""
        raw_timeout = func_args.get("timeout", DEFAULT_TOOL_CALL_TIMEOUT_SECONDS)
        try:
            timeout_seconds = float(raw_timeout)
        except (TypeError, ValueError):
            timeout_seconds = DEFAULT_TOOL_CALL_TIMEOUT_SECONDS
        return min(max(timeout_seconds, 1.0), MAX_TOOL_CALL_TIMEOUT_SECONDS)

    @staticmethod
    def _consume_background_task_result(task: asyncio.Task[Any], session_id: str) -> None:
        """回收超时或取消后仍在结束中的任务，避免未观察异常。"""
        def consume_result(completed_task: asyncio.Task[Any]) -> None:
            try:
                completed_task.result()
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                logger.bind(
                    event="tool_task_cleanup_error",
                    module="tool_dispatcher",
                    session_id=session_id,
                    error_type=type(exc).__name__,
                ).opt(exception=True).warning("超时工具任务退出时发生异常")

        task.add_done_callback(consume_result)
