"""Agent 行为、对话与用量记录的后台调度器。"""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Dict, Optional

from loguru import logger
from sqlalchemy.orm import Session

from billing.token_counter import TokenBreakdown
from core.behavior_entry_builder import build_behavior_entries


class BehaviorRecorder:
    """以统一的背压与异常处理策略调度运行记录。"""

    def __init__(
        self,
        behavior_logger: Any,
        conversation_recorder: Any,
        record_with_backpressure: Callable[[Awaitable[Any]], Awaitable[Any]],
        handle_task_result: Callable[[asyncio.Task[Any]], None],
    ) -> None:
        self._behavior_logger = behavior_logger
        self._conversation_recorder = conversation_recorder
        self._record_with_backpressure = record_with_backpressure
        self._handle_task_result = handle_task_result

    def schedule(
        self,
        *,
        node_type: str,
        user_message: str,
        context: Dict[str, Any],
        db_session: Optional[Session],
        status: str = "success",
        error_message: Optional[str] = None,
        llm_input: Any = None,
        llm_output: Any = None,
        llm_tokens_used: Optional[int] = None,
        token_breakdown: Optional[TokenBreakdown] = None,
        execution_duration_ms: Optional[int] = None,
        metadata: Any = None,
    ) -> None:
        """根据上下文异步写入行为、会话和计费用量记录。"""
        if token_breakdown is None and llm_tokens_used is not None:
            token_breakdown = TokenBreakdown(
                output_tokens=llm_tokens_used,
                method="api_usage",
                estimated=False,
            )
        if token_breakdown is not None:
            llm_tokens_used = token_breakdown.total_tokens

        user_id = context.get("user_id")
        if not user_id:
            return
        session_id = context.get("session_id", "default")
        isolated = bool(context.get("scheduled_execution_isolated"))
        disable_behavior = bool(isolated or context.get("disable_behavior_logging"))
        disable_conversation = bool(isolated or context.get("disable_conversation_record"))

        if not disable_behavior:
            entries = build_behavior_entries(
                user_id=user_id,
                node_type=node_type,
                status=status,
                error_message=error_message,
                llm_output=llm_output,
                llm_tokens_used=llm_tokens_used,
                execution_duration_ms=execution_duration_ms,
                metadata=metadata,
            )
            for entry in entries:
                self._schedule_task(self._behavior_logger.record(entry))

        if disable_conversation:
            return

        self._schedule_task(
            self._conversation_recorder.record(
                node_type=node_type,
                session_id=session_id,
                user_message=user_message,
                user_id=user_id,
                provider=context.get("provider"),
                model=context.get("model"),
                llm_input=llm_input,
                llm_output=llm_output,
                llm_tokens_used=llm_tokens_used,
                execution_duration_ms=execution_duration_ms,
                status=status,
                error_message=error_message,
                metadata=metadata,
            )
        )

        if token_breakdown is not None and db_session:
            self._schedule_usage_record(
                db_session=db_session,
                user_id=user_id,
                session_id=session_id,
                provider=context.get("provider") or "",
                model=context.get("model") or "",
                token_breakdown=token_breakdown,
                duration_ms=execution_duration_ms or 0,
            )

    def _schedule_task(self, coro: Awaitable[Any]) -> None:
        task = asyncio.create_task(self._record_with_backpressure(coro))
        task.add_done_callback(self._handle_task_result)

    def _schedule_usage_record(
        self,
        *,
        db_session: Session,
        user_id: Any,
        session_id: str,
        provider: str,
        model: str,
        token_breakdown: TokenBreakdown,
        duration_ms: int,
    ) -> None:
        """延迟导入计费组件，避免无计费记录时增加初始化耦合。"""
        try:
            from billing.usage_tracker import UsageTracker

            usage_tracker = UsageTracker(db_session)
            self._schedule_task(
                usage_tracker.record_llm_call(
                    user_id=str(user_id),
                    session_id=session_id,
                    provider=provider,
                    model=model,
                    token_breakdown=token_breakdown,
                    duration_ms=duration_ms,
                )
            )
        except Exception as exc:
            logger.bind(
                module="agent",
                event="usage_record_schedule_error",
            ).error(f"计费扣减任务调度失败: {exc}")
