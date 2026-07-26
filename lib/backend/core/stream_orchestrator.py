"""Agent 流式工具轮次编排对象。"""

from __future__ import annotations

import asyncio
import time
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional, Tuple, Type

from loguru import logger

from core.agent_execution_context import RoundState, StreamFinalizationContext
from core.agent_helpers import build_status_event, map_finish_reason_to_state
from core.agent_state import AgentState
from core.content_replacement import enforce_tool_result_budget
from core.executor import resolve_max_tool_call_rounds
from core.tool_dispatcher import ToolCallContext


class StreamOrchestrator:
    """编排单轮工具执行、消息拼装与后台子代理等待。"""

    def __init__(
        self,
        executor: Any,
        feedback: Any,
        tool_dispatcher: Any,
        tool_event_emitter: Any,
        early_exit_type: Type[Exception],
        budget_tracker: Any,
        content_replacement_state: Any,
        record_budget_usage: Callable[..., None],
        unregister_task: Callable[[str, str, Optional[asyncio.Task]], None],
    ) -> None:
        self._executor = executor
        self._feedback = feedback
        self._tool_dispatcher = tool_dispatcher
        self._tool_event_emitter = tool_event_emitter
        self._early_exit_type = early_exit_type
        self._budget_tracker = budget_tracker
        self._content_replacement_state = content_replacement_state
        self._record_budget_usage = record_budget_usage
        self._unregister_task = unregister_task

    async def run_tool_calls_loop(
        self,
        context: Dict[str, Any],
        current_task: Optional[asyncio.Task],
        session_id: str,
        state: Dict[str, Any],
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """运行模型与工具多轮回环，直到状态终止或预算耗尽。"""
        effective_user_input = state["effective_user_input"]
        max_rounds = resolve_max_tool_call_rounds(context)
        state_machine = AgentState.CONTINUE_TOOL_CALLS
        while (
            not state_machine.is_terminal
            and not self._budget_tracker.is_near_completion()
        ):
            if current_task and current_task.cancelled():
                yield {"type": "cancelled", "content": "", "reasoning_content": ""}
                raise self._early_exit_type()
            state["round_count"] += 1
            tool_calls_detected = False
            round_state = RoundState(
                round_count=state["round_count"],
                round_content="",
                round_reasoning="",
                shared_state=state,
                effective_user_input=effective_user_input,
            )
            self._apply_tool_result_budget(context)
            async for chunk in self._executor._call_llm_api_stream(
                effective_user_input,
                context,
            ):
                if "error" in chunk:
                    yield {"type": "error", "error": chunk["error"]}
                    raise self._early_exit_type()
                if chunk.get("type") == "tool_calls":
                    tool_calls_detected = True
                    async for event in self.handle_tool_calls_in_round(
                        chunk.get("tool_calls", []),
                        context,
                        current_task,
                        session_id,
                        round_state,
                    ):
                        yield event
                    break
                yield self._accumulate_chunk(chunk, round_state)
            state_machine, status_event = self._advance_state_machine(
                round_state,
                tool_calls_detected,
                max_rounds,
                context,
            )
            if status_event is not None:
                yield status_event

    def _apply_tool_result_budget(self, context: Dict[str, Any]) -> None:
        """在模型调用前压缩历史工具结果，限制输入预算。"""
        if not context.get("_tool_messages"):
            return
        context["_tool_messages"] = enforce_tool_result_budget(
            context["_tool_messages"],
            self._content_replacement_state,
            self._budget_tracker.max_input_tokens // 4,
        )

    @staticmethod
    def _accumulate_chunk(
        chunk: Dict[str, Any],
        round_state: RoundState,
    ) -> Dict[str, Any]:
        """累计本轮正文与推理内容，并生成对外流事件。"""
        content = chunk.get("content", "")
        reasoning = chunk.get("reasoning_content", "")
        if content:
            round_state.shared_state["full_content"] += content
            round_state.round_content += content
        if reasoning:
            round_state.shared_state["full_reasoning"] += reasoning
            round_state.round_reasoning += reasoning
        output = {"type": "chunk", "content": content}
        if not round_state.shared_state["final_only_mode"] and reasoning:
            output["reasoning_content"] = reasoning
        return output

    def _advance_state_machine(
        self,
        round_state: RoundState,
        tool_calls_detected: bool,
        max_rounds: int,
        context: Dict[str, Any],
    ) -> Tuple[AgentState, Optional[Dict[str, Any]]]:
        """推进轮次状态机并在预算接近耗尽时发射状态事件。"""
        state_machine = map_finish_reason_to_state(
            finish_reason="tool_calls" if tool_calls_detected else "stop",
            current_round=round_state.round_count,
            max_rounds=max_rounds,
        )
        self._record_budget_usage(
            user_input=round_state.effective_user_input,
            context=context,
            round_content=round_state.round_content,
            round_reasoning=round_state.round_reasoning,
        )
        if not self._budget_tracker.is_near_completion():
            return state_machine, None
        logger.bind(
            event="budget_near_completion",
            module="stream_orchestrator",
            usage_ratio=self._budget_tracker.usage_ratio(),
            total_used=self._budget_tracker.total_used(),
            remaining=self._budget_tracker.remaining(),
        ).info("预算即将耗尽，提前结束本轮对话")
        return (
            AgentState.TERMINAL_BUDGET_EXHAUSTED,
            build_status_event("budget_exhausted", "预算即将耗尽，提前结束本轮对话"),
        )

    async def finalize(self, finalization: StreamFinalizationContext) -> None:
        """完成流式钩子、记忆更新、数据采集及任务资源释放。"""
        state = finalization.state
        try:
            if state.get("main_completed"):
                await self._dispatch_task_completed(finalization.context, state)
                if state["full_content"]:
                    await self._feedback.update_memory(
                        user_input=finalization.user_input,
                        response=state["full_content"],
                        context=finalization.context,
                        reasoning_content=state["full_reasoning"] or None,
                        tool_events=state["accumulated_tool_events"] or None,
                    )
        finally:
            await self._collect_conversation(finalization)
            if finalization.abort_controller is not None:
                finalization.abort_controller.abort(
                    reason="process_stream_finished",
                )
            self._unregister_task(
                finalization.task_user_id,
                finalization.session_id,
                finalization.current_task,
            )

    @staticmethod
    async def _dispatch_task_completed(
        context: Dict[str, Any],
        state: Dict[str, Any],
    ) -> None:
        """触发可选的任务完成钩子。"""
        try:
            from core.task_runtime.hook_dispatcher import (
                HOOK_TASK_COMPLETED,
                hook_dispatcher,
            )

            await hook_dispatcher.dispatch(HOOK_TASK_COMPLETED, {
                "response": state["full_content"],
                "context": context,
                "round_count": state["round_count"],
            })
        except ImportError:
            pass

    @staticmethod
    async def _collect_conversation(
        finalization: StreamFinalizationContext,
    ) -> None:
        """采集流式对话数据，采集失败不得破坏清理链路。"""
        context = finalization.context
        state = finalization.state
        try:
            from data.collector import data_collector

            await data_collector.collect_conversation({
                "conversation_id": context.get("session_id", ""),
                "role_id": context.get("role_id", ""),
                "user_message": finalization.user_input[:2000],
                "assistant_message": state["full_content"][:2000],
                "tools_used": [
                    event.get("name", "")
                    for event in state["accumulated_tool_events"]
                ],
                "model_used": context.get("model", ""),
                "token_count": {},
                "response_time_ms": int(
                    (time.time() - finalization.started_at) * 1000
                ),
            })
        except Exception as error:
            logger.bind(
                event="stream_conversation_collect_error",
                module="stream_orchestrator",
                error_type=type(error).__name__,
            ).opt(exception=True).warning(f"流式数据收集失败: {error}")

    async def handle_tool_calls_in_round(
        self,
        tool_calls: List[Dict[str, Any]],
        context: Dict[str, Any],
        current_task: Optional[asyncio.Task],
        session_id: str,
        round_state: RoundState,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """执行单轮工具调用并把结果消息写回上下文。"""
        logger.info(f"Detected {len(tool_calls)} tool_calls in stream mode, executing...")
        self._save_snapshot(context, round_state.round_count)
        tool_results: List[Dict[str, Any]] = []
        background_subagent_spawned = False
        for tool_call in tool_calls:
            if current_task and current_task.cancelled():
                yield {"type": "cancelled", "content": "", "reasoning_content": ""}
                raise self._early_exit_type()
            call_context = ToolCallContext()
            async for event in self._tool_dispatcher.dispatch(
                tool_call, context, session_id, call_context,
            ):
                yield event
            async for event in self._tool_event_emitter.emit(
                tool_call,
                context,
                call_context,
                round_state.shared_state["accumulated_tool_events"],
            ):
                yield event
            background_subagent_spawned |= call_context.background_subagents_spawned
            tool_results.append({"tool_call": tool_call, "result": call_context.result})
        tool_messages = self._build_tool_messages(
            context,
            tool_calls,
            tool_results,
            round_state.round_content,
            round_state.round_reasoning,
        )
        if background_subagent_spawned:
            context["_tool_messages"] = tool_messages
            context["_pending_background_subagents"] = True
            await self._feedback.update_memory(
                user_input=round_state.shared_state["user_input"],
                response="",
                context=context,
                reasoning_content=round_state.shared_state["full_reasoning"] or None,
                tool_events=round_state.shared_state["accumulated_tool_events"] or None,
            )
            yield build_status_event("waiting_subagents", "子代理已创建，等待运行结果")
            raise self._early_exit_type()
        context["_tool_messages"] = tool_messages

    @staticmethod
    def _save_snapshot(context: Dict[str, Any], round_count: int) -> None:
        """在工具执行前保存回滚快照。"""
        rollback_manager = context.get("_rollback_manager")
        if rollback_manager:
            rollback_manager.save_snapshot(
                step_index=round_count,
                step_action="tool_calls",
                context=context,
                description=f"第 {round_count} 轮工具调用前快照",
            )

    def _build_tool_messages(
        self,
        context: Dict[str, Any],
        tool_calls: List[Dict[str, Any]],
        tool_results: List[Dict[str, Any]],
        round_content: str,
        round_reasoning: str,
    ) -> List[Dict[str, Any]]:
        """构造并保留跨轮次 assistant 与 tool 消息。"""
        tool_messages = list(context.get("_tool_messages", []))
        assistant_tool_calls = [{
            "id": item.get("id", ""),
            "type": "function",
            "function": {
                "name": item.get("function", {}).get("name", ""),
                "arguments": item.get("function", {}).get("arguments", ""),
            },
        } for item in tool_calls]
        tool_messages.append(self._executor.build_assistant_tool_call_message(
            content=round_content,
            reasoning_content=round_reasoning,
            tool_calls=assistant_tool_calls,
        ))
        tool_messages.extend(
            self._executor._build_tool_message(item["tool_call"], item["result"])
            for item in tool_results
        )
        return tool_messages
