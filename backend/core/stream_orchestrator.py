"""Agent 流式工具轮次编排对象。"""

from __future__ import annotations

import asyncio
import time
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional, Tuple, Type

from loguru import logger

from config.thresholds import STREAM_MAX_RETRIES
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
        finalize_agent_response: Optional[Callable[..., Any]] = None,
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
        self._finalize_agent_response = finalize_agent_response

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
            and not self._budget_tracker.is_diminishing()
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
            # 每轮按当前模型注入上下文窗口，保证预算分母与模型一致
            self._sync_model_context_window(context)
            finish_reason: Optional[str] = None
            round_usage: Optional[Dict[str, Any]] = None
            # 流式错误恢复：413 压缩重试 / 429 退避重试 / 模型错误 fallback model，
            # 最多恢复 N 次，恢复失败才将错误表面化
            max_stream_retries = STREAM_MAX_RETRIES
            for stream_attempt in range(max_stream_retries + 1):
                recovered = False
                async for chunk in self._executor._call_llm_api_stream(
                    effective_user_input,
                    context,
                ):
                    if "error" in chunk:
                        recovery = self._classify_stream_error(chunk["error"])
                        if (
                            recovery is None
                            or stream_attempt >= max_stream_retries
                            or round_state.round_content
                            or round_state.round_reasoning
                        ):
                            yield {"type": "error", "error": chunk["error"]}
                            raise self._early_exit_type()
                        await self._apply_stream_recovery(recovery, context)
                        recovered = True
                        break
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
                    # 透传真实 finish_reason 与 usage（流尾 chunk 携带）
                    if chunk.get("finish_reason"):
                        finish_reason = chunk["finish_reason"]
                    if isinstance(chunk.get("usage"), dict):
                        round_usage = chunk["usage"]
                    yield self._accumulate_chunk(chunk, round_state)
                if not recovered:
                    break
            state_machine, status_event = self._advance_state_machine(
                round_state,
                tool_calls_detected,
                max_rounds,
                context,
                finish_reason=finish_reason,
                usage=round_usage,
            )
            if status_event is not None:
                yield status_event

    def _sync_model_context_window(self, context: Dict[str, Any]) -> None:
        """
        根据当前上下文解析模型上下文窗口并注入预算追踪器，
        保证预算分母（max_input + max_output）与当前模型一致。
        """
        from core.context.token_budget import DEFAULT_MODEL_LIMITS

        model_name = str(context.get("model") or "").strip().lower()
        max_input_tokens = int(DEFAULT_MODEL_LIMITS.get(model_name, DEFAULT_MODEL_LIMITS["default"]))
        max_output_tokens = 8192
        model_config = context.get("model_config_override")
        if isinstance(model_config, dict):
            override_max = model_config.get("max_tokens")
            if isinstance(override_max, int) and override_max > 0:
                max_output_tokens = override_max
        self._budget_tracker.set_model_context_window(
            max_input_tokens=max_input_tokens,
            max_output_tokens=max_output_tokens,
        )

    @staticmethod
    def _classify_stream_error(error: Dict[str, Any]) -> Optional[str]:
        """
        对流式错误分类，决定恢复策略。

        返回:
            - "compact_retry": 413 上下文超限，压缩历史工具结果后重试
            - "backoff_retry": 429 速率限制，退避后重试
            - "fallback_model": 模型服务错误，切换 fallback 模型重试
            - None: 无法恢复，直接表面化错误
        """
        if not isinstance(error, dict):
            return None
        status_code = error.get("status_code")
        code = str(error.get("code") or "")
        # 413 或上下文/长度相关错误：压缩上下文后重试
        if (
            status_code == 413
            or "context_length" in code
            or "too_large" in code
            or ("token" in code and "limit" in code)
        ):
            return "compact_retry"
        # 429 速率限制：退避后重试
        if status_code == 429:
            return "backoff_retry"
        # 模型服务类错误：切换 fallback 模型重试
        if status_code in (500, 502, 503, 504) or "model" in code or "unavailable" in code:
            return "fallback_model"
        return None

    async def _apply_stream_recovery(self, recovery: str, context: Dict[str, Any]) -> None:
        """
        应用流式错误恢复策略。

        - compact_retry: 压缩历史工具结果，缩小输入预算
        - backoff_retry: 退避等待，让速率限制恢复
        - fallback_model: 从角色/上下文配置切换到 fallback 模型
        """
        if recovery == "compact_retry":
            logger.bind(
                event="stream_error_recovery",
                module="stream_orchestrator",
                strategy="compact_retry",
            ).warning("流式请求上下文超限（413），压缩历史工具结果后重试")
            self._apply_tool_result_budget(context)
            return
        if recovery == "backoff_retry":
            delay = 0.5
            logger.bind(
                event="stream_error_recovery",
                module="stream_orchestrator",
                strategy="backoff_retry",
                delay_seconds=delay,
            ).warning("流式请求触发速率限制（429），退避后重试")
            await asyncio.sleep(delay)
            return
        if recovery == "fallback_model":
            fallback_model: Optional[str] = None
            model_config = context.get("model_config_override")
            if isinstance(model_config, dict):
                fallback_model = model_config.get("fallback_model")
            if fallback_model:
                logger.bind(
                    event="stream_error_recovery",
                    module="stream_orchestrator",
                    strategy="fallback_model",
                    fallback_model=fallback_model,
                ).warning(f"流式模型服务错误，切换到 fallback 模型 {fallback_model} 重试")
                context["model"] = fallback_model
            else:
                logger.bind(
                    event="stream_error_recovery",
                    module="stream_orchestrator",
                    strategy="fallback_model",
                ).warning("流式模型服务错误，但上下文未配置 fallback 模型，直接表面化")
            return

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
        *,
        finish_reason: Optional[str] = None,
        usage: Optional[Dict[str, Any]] = None,
    ) -> Tuple[AgentState, Optional[Dict[str, Any]]]:
        """推进轮次状态机并在预算接近耗尽时发射状态事件。

        使用流式透传的真实 finish_reason（length -> CONTINUE_COMPACT、
        content_filter -> TERMINAL_REFUSAL），未透传时回退到 tool_calls/stop 判定。
        """
        if tool_calls_detected:
            resolved_finish_reason = "tool_calls"
        else:
            resolved_finish_reason = finish_reason or "stop"
        state_machine = map_finish_reason_to_state(
            finish_reason=resolved_finish_reason,
            current_round=round_state.round_count,
            max_rounds=max_rounds,
        )
        self._record_budget_usage(
            user_input=round_state.effective_user_input,
            context=context,
            round_content=round_state.round_content,
            round_reasoning=round_state.round_reasoning,
            usage=usage,
        )
        # 工具调用轮属于有实质进展的轮次，重置收益递减窗口，避免误判空转
        if tool_calls_detected:
            self._budget_tracker.mark_progress()
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
                    if self._finalize_agent_response is not None:
                        await self._finalize_agent_response(
                            conv_id=finalization.session_id,
                            user_id=finalization.task_user_id,
                            response_text=state["full_content"],
                            context=finalization.context,
                            reasoning_content=state["full_reasoning"] or None,
                            tool_events=state["accumulated_tool_events"] or None,
                        )
                    else:
                        await self._feedback.update_memory(
                            user_input=finalization.user_input,
                            response=state["full_content"],
                            context=finalization.context,
                            reasoning_content=state["full_reasoning"] or None,
                            tool_events=state["accumulated_tool_events"] or None,
                        )
        finally:
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
        """触发可选的任务完成钩子，使用统一的 hook_manager。"""
        try:
            from core.hook_manager import hook_manager, HookName

            await hook_manager.trigger(HookName.TASK_COMPLETED, data={
                "response": state["full_content"],
                "context": context,
                "round_count": state["round_count"],
            })
        except ImportError:
            pass

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
