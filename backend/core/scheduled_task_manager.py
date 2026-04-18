"""
定时任务调度管理器，负责轮询待执行任务并在隔离上下文中调用 AI Agent。
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from loguru import logger

from core.agent import AIAgent
from db.models import ScheduledTask, ScheduledTaskExecution, SessionLocal


class ScheduledTaskManager:
    """
    一次性定时任务调度器。
    使用后台轮询方式查找到期任务，并复用现有 Agent 主链路完成执行。
    """

    def __init__(self, poll_interval_seconds: float = 2.0):
        self.poll_interval_seconds = max(poll_interval_seconds, 1.0)
        self._runner_task: Optional[asyncio.Task] = None
        self._stop_event: Optional[asyncio.Event] = None
        self._processing_lock = asyncio.Lock()

    @staticmethod
    def _utcnow() -> datetime:
        """
        统一返回 UTC 当前时间，避免不同调用点出现时间来源不一致。
        """
        return datetime.now(timezone.utc)

    async def start(self) -> None:
        """
        启动后台轮询任务。
        """
        if self._runner_task and not self._runner_task.done():
            return

        await self._reset_running_tasks()
        self._stop_event = asyncio.Event()
        self._runner_task = asyncio.create_task(self._run_loop())
        logger.bind(event="scheduled_task_manager_started", module="scheduled_tasks").info("scheduled task manager started")

    async def stop(self) -> None:
        """
        停止后台轮询任务。
        """
        if not self._runner_task:
            return

        if self._stop_event:
            self._stop_event.set()

        try:
            await self._runner_task
        except asyncio.CancelledError:
            logger.bind(event="scheduled_task_manager_cancelled", module="scheduled_tasks").warning("scheduled task manager cancelled")
        finally:
            self._runner_task = None
            self._stop_event = None

        logger.bind(event="scheduled_task_manager_stopped", module="scheduled_tasks").info("scheduled task manager stopped")

    async def process_due_tasks(self) -> int:
        """
        处理当前所有到期但尚未执行的任务。
        返回本轮成功领取的任务数量。
        """
        if self._processing_lock.locked():
            return 0

        async with self._processing_lock:
            db = SessionLocal()
            try:
                due_task_ids = [
                    task_id
                    for (task_id,) in (
                        db.query(ScheduledTask.id)
                        .filter(
                            ScheduledTask.status == "pending",
                            ScheduledTask.scheduled_at <= self._utcnow(),
                        )
                        .order_by(ScheduledTask.scheduled_at.asc(), ScheduledTask.id.asc())
                        .all()
                    )
                ]
            finally:
                db.close()

            for task_id in due_task_ids:
                await self._execute_task(task_id)

            return len(due_task_ids)

    async def _run_loop(self) -> None:
        """
        后台循环，持续轮询到期任务直到收到停止信号。
        """
        if self._stop_event is None:
            self._stop_event = asyncio.Event()

        while not self._stop_event.is_set():
            try:
                await self.process_due_tasks()
            except Exception as exc:
                logger.bind(
                    event="scheduled_task_loop_error",
                    module="scheduled_tasks",
                    error_type=type(exc).__name__,
                ).opt(exception=True).error(f"scheduled task loop failed: {exc}")

            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self.poll_interval_seconds)
            except asyncio.TimeoutError:
                continue

    async def _reset_running_tasks(self) -> None:
        """
        启动时回收中断前遗留的运行中任务，确保重启后可以重新调度。
        """
        db = SessionLocal()
        try:
            now = self._utcnow()
            running_tasks = db.query(ScheduledTask).filter(ScheduledTask.status == "running").all()
            for task in running_tasks:
                task.status = "pending"
                task.last_error_message = "服务重启后任务重新进入待执行状态"
                task.completed_at = None

            running_executions = (
                db.query(ScheduledTaskExecution)
                .filter(ScheduledTaskExecution.status == "running")
                .all()
            )
            for execution in running_executions:
                execution.status = "failed"
                execution.error_message = "服务在任务执行过程中重启，请重新查看后续执行记录"
                execution.completed_at = now

            db.commit()
        finally:
            db.close()

    async def _execute_task(self, task_id: int) -> None:
        """
        执行单个定时任务。
        """
        try:
            claimed_task, execution_id = self._claim_task_for_execution(task_id)
        except Exception as exc:
            logger.bind(
                event="scheduled_task_claim_error",
                module="scheduled_tasks",
                task_id=task_id,
                error_type=type(exc).__name__,
            ).opt(exception=True).error(f"failed to claim scheduled task: {exc}")
            return

        if claimed_task is None or execution_id is None:
            return

        try:
            result = await self._run_agent(claimed_task)
            await self._mark_task_completed(
                task_id=claimed_task["id"],
                execution_id=execution_id,
                scheduled_task=claimed_task,
                result=result,
            )
        except Exception as exc:
            await self._mark_task_failed(
                task_id=claimed_task["id"],
                execution_id=execution_id,
                error_message=str(exc),
                error_type=type(exc).__name__,
            )

    def _claim_task_for_execution(self, task_id: int) -> tuple[Optional[Dict[str, Any]], Optional[int]]:
        """
        以显式事务方式领取任务并创建执行记录，避免状态推进与执行记录脱节。
        """
        db = SessionLocal()
        try:
            with db.begin():
                task = (
                    db.query(ScheduledTask)
                    .filter(ScheduledTask.id == task_id, ScheduledTask.status == "pending")
                    .first()
                )
                if task is None:
                    return None, None

                task.status = "running"
                task.last_error_message = None
                task.completed_at = None
                task.cancelled_at = None

                execution = ScheduledTaskExecution(
                    task_id=task.id,
                    user_id=task.user_id,
                    task_title=task.title,
                    prompt=task.prompt,
                    scheduled_for=task.scheduled_at,
                    status="running",
                    provider=task.provider,
                    model=task.model,
                    execution_metadata={
                        "source": "scheduled_task_manager",
                    },
                )
                db.add(execution)
                db.flush()

                claimed_task = {
                    "id": task.id,
                    "user_id": task.user_id,
                    "title": task.title,
                    "prompt": task.prompt,
                    "scheduled_at": task.scheduled_at,
                    "provider": task.provider,
                    "model": task.model,
                }
                execution_id = execution.id

            return claimed_task, execution_id
        finally:
            db.close()

    async def _run_agent(self, scheduled_task: Dict[str, Any]) -> Dict[str, Any]:
        """
        在隔离上下文中运行 Agent，避免把结果写入聊天会话与记忆系统。
        """
        db = SessionLocal()
        try:
            agent = AIAgent(db_session=db)
            context = {
                "user_id": scheduled_task["user_id"],
                "provider": scheduled_task.get("provider"),
                "model": scheduled_task.get("model"),
                "session_id": f"scheduled-task-{scheduled_task['id']}",
                "task_type": "scheduled_task",
                "scheduled_task_id": scheduled_task["id"],
                "scheduled_execution_isolated": True,
            }

            result = await agent.process(scheduled_task["prompt"], context)
        finally:
            db.close()

        if not isinstance(result, dict):
            raise RuntimeError("定时任务执行返回了无效结果")

        if result.get("status") == "error":
            error = result.get("error") or {}
            error_message = error.get("message") or result.get("response") or "定时任务执行失败"
            raise RuntimeError(str(error_message))

        return result

    async def _mark_task_completed(
        self,
        *,
        task_id: int,
        execution_id: int,
        scheduled_task: Dict[str, Any],
        result: Dict[str, Any],
    ) -> None:
        """
        将任务和执行记录更新为成功完成状态。
        """
        now = self._utcnow()
        provider, model = self._extract_provider_and_model(result)
        response_text = self._extract_response_text(result)
        execution_metadata = self._build_execution_metadata(result)

        db = SessionLocal()
        try:
            task = db.query(ScheduledTask).filter(ScheduledTask.id == task_id).first()
            execution = db.query(ScheduledTaskExecution).filter(ScheduledTaskExecution.id == execution_id).first()
            if task is None or execution is None:
                return

            task.status = "completed"
            task.completed_at = now
            task.last_error_message = None
            if provider:
                task.provider = provider
            if model:
                task.model = model

            execution.status = "completed"
            execution.response = response_text
            execution.error_message = None
            execution.completed_at = now
            execution.execution_metadata = execution_metadata
            execution.provider = provider or scheduled_task.get("provider")
            execution.model = model or scheduled_task.get("model")

            db.commit()
        finally:
            db.close()

    async def _mark_task_failed(
        self,
        *,
        task_id: int,
        execution_id: int,
        error_message: str,
        error_type: str,
    ) -> None:
        """
        将任务和执行记录更新为失败状态。
        """
        now = self._utcnow()
        db = SessionLocal()
        try:
            task = db.query(ScheduledTask).filter(ScheduledTask.id == task_id).first()
            execution = db.query(ScheduledTaskExecution).filter(ScheduledTaskExecution.id == execution_id).first()
            if task is None or execution is None:
                return

            task.status = "failed"
            task.completed_at = now
            task.last_error_message = error_message

            execution.status = "failed"
            execution.error_message = error_message
            execution.completed_at = now
            execution.execution_metadata = {
                **(execution.execution_metadata or {}),
                "error_type": error_type,
            }

            db.commit()
        finally:
            db.close()

        logger.bind(
            event="scheduled_task_failed",
            module="scheduled_tasks",
            task_id=task_id,
            error_type=error_type,
        ).warning(f"scheduled task failed: {error_message}")

    @staticmethod
    def _extract_response_text(result: Dict[str, Any]) -> str:
        """
        从 Agent 输出中提取最终文本响应。
        """
        response = result.get("response")
        if isinstance(response, str):
            return response
        if response is not None:
            return json.dumps(response, ensure_ascii=False, default=str)
        return ""

    @staticmethod
    def _extract_provider_and_model(result: Dict[str, Any]) -> tuple[Optional[str], Optional[str]]:
        """
        从执行结果中提取实际使用的 provider 和 model。
        """
        for item in result.get("results", []):
            if not isinstance(item, dict):
                continue

            execution_result = item.get("result", item)
            if not isinstance(execution_result, dict):
                continue

            provider = execution_result.get("provider")
            model = execution_result.get("model")
            if provider or model:
                return provider, model

        return None, None

    @staticmethod
    def _build_execution_metadata(result: Dict[str, Any]) -> Dict[str, Any]:
        """
        提取任务页展示所需的轻量执行元数据。
        """
        return {
            "status": result.get("status"),
            "skills_executed": result.get("skills_executed", 0),
            "plugins_executed": result.get("plugins_executed", 0),
            "experiences_used": result.get("experiences_used", 0),
            "memories_used": result.get("memories_used", 0),
        }


scheduled_task_manager = ScheduledTaskManager()