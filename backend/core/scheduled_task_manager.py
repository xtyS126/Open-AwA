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
            def _sync_get_due_task_ids():
                db = SessionLocal()
                try:
                    return [
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

            due_task_ids = await asyncio.to_thread(_sync_get_due_task_ids)

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
        DB 操作通过 asyncio.to_thread 执行，避免阻塞事件循环。
        """
        def _sync_reset():
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

        await asyncio.to_thread(_sync_reset)

    async def execute_task_now(self, task, db=None) -> Dict[str, Any]:
        """
        手动触发执行一个定时任务，不依赖 claim 机制，直接执行并返回结果。
        用于 API 手动触发场景。

        Args:
            task: ScheduledTask ORM 对象（含 task_type/prompt/provider/model 等字段）
            db: 可选，已有的数据库会话

        Returns:
            dict: {"status": "success"|"failed", "response": "...", "error": "..."}
        """
        scheduled_task = {
            "id": task.id,
            "title": task.title,
            "prompt": task.prompt,
            "provider": getattr(task, "provider", None),
            "model": getattr(task, "model", None),
            "task_type": getattr(task, "task_type", "ai_prompt"),
            "plugin_name": getattr(task, "plugin_name", None),
            "command_name": getattr(task, "command_name", None),
            "command_params": getattr(task, "command_params", None) or {},
        }
        try:
            if scheduled_task.get("task_type") == "plugin_command":
                result = await self._run_plugin_command(scheduled_task)
            else:
                result = await self._run_agent(scheduled_task)
            return result
        except Exception as exc:
            return {
                "status": "failed",
                "response": "",
                "error": f"{type(exc).__name__}: {str(exc)}",
            }

    async def _execute_task(self, task_id: int) -> None:
        """
        执行单个定时任务，根据任务类型分流到AI Agent或插件命令执行。
        """
        try:
            claimed_task, execution_id = await asyncio.to_thread(self._claim_task_for_execution, task_id)
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
            task_type = claimed_task.get("task_type", "ai_prompt")
            if task_type == "plugin_command":
                result = await self._run_plugin_command(claimed_task)
            else:
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
                        "task_type": task.task_type,
                        "plugin_name": task.plugin_name,
                        "command_name": task.command_name,
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
                    "task_type": task.task_type,
                    "plugin_name": task.plugin_name,
                    "command_name": task.command_name,
                    "command_params": task.command_params,
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
            error_raw = result.get("error")
            if isinstance(error_raw, dict):
                error_message = error_raw.get("message") or result.get("response") or "定时任务执行失败"
            else:
                error_message = str(error_raw) if error_raw else (result.get("response") or "定时任务执行失败")
            raise RuntimeError(str(error_message))

        return result

    async def _run_plugin_command(self, scheduled_task: Dict[str, Any]) -> Dict[str, Any]:
        """
        直接调用插件命令，不经过AI Agent。
        """
        from plugins import plugin_instance

        plugin_name = scheduled_task.get("plugin_name", "")
        command_name = scheduled_task.get("command_name", "")
        command_params = scheduled_task.get("command_params", {})

        if not plugin_name or not command_name:
            raise RuntimeError("插件命令任务缺少 plugin_name 或 command_name")

        pm = plugin_instance.get()
        if plugin_name not in pm.loaded_plugins:
            # 尝试加载插件
            if plugin_name in pm.plugin_metadata:
                success = pm.load_plugin(plugin_name)
                if not success:
                    raise RuntimeError(f"无法加载插件: {plugin_name}")
            else:
                raise RuntimeError(f"插件未找到: {plugin_name}")

        # 移除可能与显式参数冲突的键，避免 TypeError: got multiple values
        safe_params = {
            k: v for k, v in command_params.items()
            if k not in ("plugin_name", "method")
        }

        result = await pm.execute_plugin_async(
            plugin_name=plugin_name,
            method=command_name,
            **safe_params,
        )

        if not isinstance(result, dict):
            return {"status": "completed", "response": str(result)}

        if result.get("status") == "error":
            error_msg = result.get("error", result.get("message", "插件命令执行失败"))
            raise RuntimeError(str(error_msg))

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
        如果是每日任务，则重新排程到下一次执行时间。
        DB 操作通过 asyncio.to_thread 执行，避免阻塞事件循环。
        """
        now = self._utcnow()
        provider, model = self._extract_provider_and_model(result)
        response_text = self._extract_response_text(result)
        execution_metadata = self._build_execution_metadata(result)

        def _sync_mark():
            db = SessionLocal()
            try:
                task = db.query(ScheduledTask).filter(ScheduledTask.id == task_id).first()
                execution = db.query(ScheduledTaskExecution).filter(ScheduledTaskExecution.id == execution_id).first()
                if task is None or execution is None:
                    return None, None

                # 每日任务：执行后重新排程而非标记为完成
                if task.is_daily and task.cron_expression:
                    next_exec = self._calculate_next_cron_execution(task.cron_expression)
                    if next_exec:
                        task.status = "pending"
                        task.scheduled_at = next_exec
                        task.last_error_message = None
                        task.completed_at = None
                    else:
                        task.status = "completed"
                        task.completed_at = now
                        task.last_error_message = "无法计算下一次执行时间，任务已标记为完成"
                else:
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
                return task.title, response_text
            finally:
                db.close()

        task_title, resp_text = await asyncio.to_thread(_sync_mark) or (None, None)

        # 推送任务结果到收件箱（DB 操作已完成，仅做通知）
        if task_title is not None:
            try:
                from api.routes.inbox import add_task_result_notification
                title = task_title or scheduled_task.get("title", "未命名任务")
                summary = (resp_text or "")[:200]
                # 必须传入 user_id 以正确归属消息，否则收件箱会忽略该通知（IDOR 防护）
                add_task_result_notification(
                    task_name=title,
                    success=True,
                    summary=summary,
                    user_id=scheduled_task.get("user_id"),
                )
            except Exception as exc:
                # 收件箱推送失败不影响主流程，但需记录便于排查通知系统异常
                logger.warning(f"[scheduled_task] 收件箱推送失败，task_id={scheduled_task.get('id')}: {exc}", exc_info=exc)

    @staticmethod
    def _parse_cron_field(field: str, min_val: int, max_val: int) -> set:
        """
        解析单个 cron 字段，支持：
        - 通配符 '*' → 所有值
        - 单个值 '5' → {5}
        - 多个值 '1,3,5' → {1,3,5}
        - 步长 '*/5' → 每 5 个值
        - 范围 '1-5' → {1,2,3,4,5}
        """
        field = field.strip()
        if field == '*':
            return set(range(min_val, max_val + 1))

        values = set()
        for part in field.split(','):
            part = part.strip()
            if '/' in part:
                # 步长语法: */5 或 1-10/2
                range_part, step_str = part.split('/', 1)
                step = int(step_str)
                if step <= 0:
                    continue
                if range_part == '*':
                    values.update(range(min_val, max_val + 1, step))
                elif '-' in range_part:
                    r_start, r_end = range_part.split('-', 1)
                    values.update(range(int(r_start), int(r_end) + 1, step))
            elif '-' in part:
                r_start, r_end = part.split('-', 1)
                values.update(range(int(r_start), int(r_end) + 1))
            else:
                values.add(int(part))

        return {v for v in values if min_val <= v <= max_val}

    @staticmethod
    def _calculate_next_cron_execution(cron_expression: str) -> Optional[datetime]:
        """
        根据 cron 表达式计算下一次执行时间。
        支持完整 5 字段格式：分 时 日 月 星期
        支持 */N 步长、逗号分隔多值、范围等语法。

        PERF-09: 使用逐分钟遍历查找下一次匹配时间。
        限制最大迭代次数为一年（525600 分钟），超过则返回 None。
        计算耗时超过 100ms 时记录 warning 日志。

        未来优化方向：引入 croniter 库实现 O(1) 级别的下次时间计算，
        替代当前的逐分钟遍历方案。croniter 基于日历算法直接推算下一匹配，
        无需逐分钟试探，对长周期 cron 表达式（如年度任务）性能提升显著。
        """
        if not cron_expression:
            return None
        import time as _time
        from datetime import timedelta
        parts = cron_expression.strip().split()
        if len(parts) != 5:
            return None
        try:
            target_minutes = ScheduledTaskManager._parse_cron_field(parts[0], 0, 59)
            target_hours = ScheduledTaskManager._parse_cron_field(parts[1], 0, 23)
            target_days = ScheduledTaskManager._parse_cron_field(parts[2], 1, 31)
            target_months = ScheduledTaskManager._parse_cron_field(parts[3], 1, 12)
            target_weekdays = ScheduledTaskManager._parse_cron_field(parts[4], 0, 7)
            # 支持 7 表示周日，统一映射
            if 7 in target_weekdays:
                target_weekdays.discard(7)
                target_weekdays.add(0)
        except (ValueError, IndexError):
            return None

        now = datetime.now(timezone.utc)
        check = now.replace(second=0, microsecond=0) + timedelta(minutes=1)

        # PERF-09: 最大迭代上限为一年的分钟数，防止极端 cron 表达式导致无限遍历
        MAX_CRON_ITERATIONS = 525600  # 365 * 24 * 60
        PERF_WARN_THRESHOLD_MS = 100  # 计算耗时超过 100ms 记录 warning

        _start_ts = _time.monotonic()
        for i in range(MAX_CRON_ITERATIONS):
            # Python weekday(): 0=周一 → cron: 0=周日，需要 +1 取模转换
            weekday = (check.weekday() + 1) % 7
            if (check.minute in target_minutes and
                check.hour in target_hours and
                check.day in target_days and
                check.month in target_months and
                weekday in target_weekdays and
                check > now):
                _elapsed_ms = (_time.monotonic() - _start_ts) * 1000
                if _elapsed_ms > PERF_WARN_THRESHOLD_MS:
                    logger.bind(
                        event="cron_calc_slow",
                        module="scheduled_tasks",
                        cron_expression=cron_expression,
                        elapsed_ms=round(_elapsed_ms, 2),
                        iterations=i + 1,
                    ).warning(
                        f"cron 下次执行时间计算耗时 {_elapsed_ms:.1f}ms "
                        f"(表达式: {cron_expression}, 迭代 {i + 1} 次)"
                    )
                return check
            check += timedelta(minutes=1)

        # 超过最大迭代次数仍未找到匹配，返回 None 并记录 warning
        _elapsed_ms = (_time.monotonic() - _start_ts) * 1000
        logger.bind(
            event="cron_calc_exhausted",
            module="scheduled_tasks",
            cron_expression=cron_expression,
            max_iterations=MAX_CRON_ITERATIONS,
            elapsed_ms=round(_elapsed_ms, 2),
        ).warning(
            f"cron 表达式 '{cron_expression}' 在 {MAX_CRON_ITERATIONS} 次迭代内"
            f"未找到匹配时间，可能为无效表达式或周期超过一年"
        )
        return None

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
        DB 操作通过 asyncio.to_thread 执行，避免阻塞事件循环。
        """
        now = self._utcnow()

        def _sync_mark():
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

        await asyncio.to_thread(_sync_mark)

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