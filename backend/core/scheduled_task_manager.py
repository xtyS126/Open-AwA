"""
定时任务调度管理器，基于 APScheduler 4.x 实现周期性 / 一次性任务的调度与执行。

设计要点：
- 业务表 scheduled_tasks 仍是用户可见的"任务配置"真相源（标题、prompt、cron_expression 等）。
- APScheduler 的 AsyncScheduler + SQLAlchemyDataStore 负责实际的触发与去重，
  其内部表（tasks/schedules/jobs/job_results/metadata）由 SQLAlchemyDataStore 自动建表，
  与业务表完全分离，避免污染 scheduled_tasks 业务语义。
- CronTrigger.from_crontab 复用成熟 cron 解析，删除自实现的 _parse_cron_field 与逐分钟遍历。
- 多 worker 部署时，SQLAlchemyDataStore 提供分布式锁语义（同一 job 只被一个 scheduler acquire）。
- register_task / unregister_task 在调度器未启动时静默 no-op，避免测试与启动早期报错。
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from apscheduler import AsyncScheduler, ScheduleLookupError
from apscheduler._enums import ConflictPolicy
from apscheduler.datastores.sqlalchemy import SQLAlchemyDataStore
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from loguru import logger

from core.agent import AIAgent
from db.models import ScheduledTask, ScheduledTaskExecution, SessionLocal, engine as main_engine


# 业务任务在 APScheduler 中的 schedule id 前缀，避免与其他模块潜在 schedule 冲突
_SCHEDULE_ID_PREFIX = "scheduled_task_"


async def _execute_scheduled_task(task_id: int) -> None:
    """
    APScheduler 触发时调用的可执行对象。

    必须为模块级函数（不能是 lambda / 嵌套函数），以便 APScheduler 序列化为
    "core.scheduled_task_manager:_execute_scheduled_task" 引用。
    委托给全局单例 scheduled_task_manager._execute_task 完成实际执行。
    """
    await scheduled_task_manager._execute_task(int(task_id))


class ScheduledTaskManager:
    """
    基于 APScheduler 4.x 的定时任务管理器。

    取代原 DB 轮询 + asyncio.Lock 实现：
    - 不再每 2 秒查 DB 找到期任务，APScheduler 内部基于 trigger 计算下次触发时间。
    - 不再用 asyncio.Lock 防并发领取，APScheduler 的 SQLAlchemyDataStore 提供跨 worker 锁语义。
    - 不再自实现 cron 解析，CronTrigger.from_crontab 提供完整 5 字段 cron 支持。
    """

    def __init__(self) -> None:
        self._scheduler: Optional[AsyncScheduler] = None
        self._data_store: Optional[SQLAlchemyDataStore] = None
        self._started: bool = False
        # 保护 register/unregister 并发，避免同一任务重复注册产生竞态
        self._register_lock = asyncio.Lock()

    @staticmethod
    def _utcnow() -> datetime:
        """统一返回 UTC 当前时间，避免不同调用点出现时间来源不一致。"""
        return datetime.now(timezone.utc)

    @staticmethod
    def _build_schedule_id(task_id: int) -> str:
        """根据业务任务 id 生成 APScheduler schedule id。"""
        return f"{_SCHEDULE_ID_PREFIX}{task_id}"

    @staticmethod
    def _build_trigger(task: Any) -> Optional[Any]:
        """
        根据 ScheduledTask 业务字段构建 APScheduler trigger。

        - 周期任务（is_daily=True 且 cron_expression 非空）：CronTrigger.from_crontab
        - 一次性任务（scheduled_at 为未来时间）：DateTrigger
        - 已过期的一次性任务：返回 None，调用方决定是否立即触发或跳过
        """
        cron_expr = (getattr(task, "cron_expression", None) or "").strip()
        is_daily = bool(getattr(task, "is_daily", False))
        if is_daily and cron_expr:
            # 使用 UTC 时区解析 cron，与项目其他模块时间基准一致
            return CronTrigger.from_crontab(cron_expr, timezone="UTC")

        scheduled_at = getattr(task, "scheduled_at", None)
        if scheduled_at is None:
            return None
        # DateTrigger 接受 timezone-aware datetime
        if scheduled_at.tzinfo is None:
            scheduled_at = scheduled_at.replace(tzinfo=timezone.utc)
        return DateTrigger(scheduled_at)

    async def start(self) -> None:
        """
        启动 APScheduler 调度器并注册所有待执行任务。

        步骤：
        1. 用主数据库 engine 创建 SQLAlchemyDataStore（APScheduler 自动建内部表）。
        2. 进入 AsyncScheduler 上下文（初始化 data store / event broker）。
        3. 回收重启前遗留的 running 任务（与原实现保持一致）。
        4. 扫描 scheduled_tasks 表所有 pending 任务，注册到 APScheduler。
        5. 后台启动调度器。
        """
        if self._started:
            return

        # 复用主数据库 engine，APScheduler 内部表与业务表共库不同名
        self._data_store = SQLAlchemyDataStore(main_engine)
        self._scheduler = AsyncScheduler(data_store=self._data_store)

        # 进入上下文：初始化 data store，创建 apscheduler 内部表
        await self._scheduler.__aenter__()

        # 回收中断前遗留的 running 任务，与原实现行为保持一致
        await self._reset_running_tasks()

        # 注册所有 pending 任务到 APScheduler
        await self._register_all_pending_tasks()

        # 后台启动调度器
        await self._scheduler.start_in_background()

        self._started = True
        logger.bind(
            event="scheduled_task_manager_started",
            module="scheduled_tasks",
        ).info("scheduled task manager started (APScheduler 4.x)")

    async def stop(self) -> None:
        """停止 APScheduler 调度器并释放资源。"""
        if not self._started or self._scheduler is None:
            return

        try:
            await self._scheduler.__aexit__(None, None, None)
        except Exception as exc:
            logger.bind(
                event="scheduled_task_manager_stop_error",
                module="scheduled_tasks",
                error_type=type(exc).__name__,
            ).warning(f"scheduled task manager stop failed: {exc}")

        self._started = False
        self._scheduler = None
        self._data_store = None
        logger.bind(
            event="scheduled_task_manager_stopped",
            module="scheduled_tasks",
        ).info("scheduled task manager stopped")

    async def register_task(self, task: Any) -> None:
        """
        将一个 ScheduledTask 业务对象注册到 APScheduler。

        - 调度器未启动时静默 no-op（用于测试与启动早期）。
        - 使用 conflict_policy=replace，确保 idempotent：重复注册同一任务会更新 trigger 而非报错。
        - 周期任务（is_daily + cron_expression）：CronTrigger。
        - 一次性任务（scheduled_at）：DateTrigger。
        - 已过期的一次性任务：立即触发执行（catch-up 语义，与原轮询实现一致）。
        """
        if not self._started or self._scheduler is None:
            return

        async with self._register_lock:
            task_id = int(task.id)
            schedule_id = self._build_schedule_id(task_id)
            trigger = self._build_trigger(task)

            if trigger is None:
                # 一次性任务的 scheduled_at 已过期 → 立即触发，与原轮询行为一致
                logger.bind(
                    event="scheduled_task_register_no_trigger",
                    module="scheduled_tasks",
                    task_id=task_id,
                ).warning("task has no valid trigger, will execute immediately")
                asyncio.create_task(self._execute_task(task_id))
                return

            try:
                await self._scheduler.add_schedule(
                    _execute_scheduled_task,
                    trigger,
                    id=schedule_id,
                    args=(task_id,),
                    conflict_policy=ConflictPolicy.replace,
                )
            except Exception as exc:
                # 注册失败不影响 API 主流程，仅记录日志
                logger.bind(
                    event="scheduled_task_register_error",
                    module="scheduled_tasks",
                    task_id=task_id,
                    error_type=type(exc).__name__,
                ).warning(f"failed to register task to APScheduler: {exc}")

    async def unregister_task(self, task_id: int) -> None:
        """
        从 APScheduler 移除任务调度。

        - 调度器未启动时静默 no-op。
        - schedule 不存在时静默忽略（ScheduleLookupError）。
        """
        if not self._started or self._scheduler is None:
            return

        async with self._register_lock:
            schedule_id = self._build_schedule_id(int(task_id))
            try:
                await self._scheduler.remove_schedule(schedule_id)
            except ScheduleLookupError:
                # schedule 已不存在（可能已自动过期或从未注册），静默忽略
                pass
            except Exception as exc:
                logger.bind(
                    event="scheduled_task_unregister_error",
                    module="scheduled_tasks",
                    task_id=task_id,
                    error_type=type(exc).__name__,
                ).warning(f"failed to unregister task from APScheduler: {exc}")

    async def _register_all_pending_tasks(self) -> None:
        """
        启动时扫描 scheduled_tasks 表所有 pending 任务，批量注册到 APScheduler。

        DB 操作通过 asyncio.to_thread 执行，避免阻塞事件循环。
        """
        def _sync_list_pending():
            db = SessionLocal()
            try:
                return (
                    db.query(ScheduledTask)
                    .filter(ScheduledTask.status == "pending")
                    .all()
                )
            finally:
                db.close()

        pending_tasks = await asyncio.to_thread(_sync_list_pending)
        for task in pending_tasks:
            await self.register_task(task)

        logger.bind(
            event="scheduled_task_bulk_register",
            module="scheduled_tasks",
            count=len(pending_tasks),
        ).info(f"registered {len(pending_tasks)} pending tasks to APScheduler")

    async def _reset_running_tasks(self) -> None:
        """
        启动时回收中断前遗留的 running 任务，确保重启后可以重新调度。
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
        手动触发执行一个定时任务，不依赖 APScheduler 触发，直接执行并返回结果。
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

        被 APScheduler 的 _execute_scheduled_task 调用，也可被 register_task 用于过期立即触发。
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
        周期任务执行后不修改状态（保持 pending），APScheduler 会按 CronTrigger 自动触发下一次。
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

                # 周期任务保持 pending 状态（APScheduler 按 CronTrigger 自动续程）
                # 一次性任务标记为 completed
                if task.is_daily and task.cron_expression:
                    task.status = "pending"
                    task.last_error_message = None
                    task.completed_at = None
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
    def _calculate_next_cron_execution(cron_expression: str) -> Optional[datetime]:
        """
        根据 cron 表达式计算下一次执行时间。

        委托给 APScheduler CronTrigger.from_crontab，删除原自实现的逐分钟遍历。
        返回 timezone-aware UTC datetime，与项目其他模块时间基准一致。

        Args:
            cron_expression: 标准 5 字段 cron 表达式（分 时 日 月 周）

        Returns:
            下一次执行时间（UTC），无效表达式或无下次匹配时返回 None
        """
        if not cron_expression:
            return None
        try:
            trigger = CronTrigger.from_crontab(cron_expression, timezone="UTC")
        except (ValueError, TypeError):
            return None
        try:
            next_fire = next(trigger)
        except StopIteration:
            # trigger 已耗尽，无下次匹配
            return None
        # CronTrigger.__next__ 返回 timezone-aware datetime，确保转为 UTC
        if next_fire.tzinfo is None:
            next_fire = next_fire.replace(tzinfo=timezone.utc)
        else:
            next_fire = next_fire.astimezone(timezone.utc)
        return next_fire

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
        周期任务失败后仍保持 pending（APScheduler 会按 cron 继续触发下一次）。
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

                # 周期任务失败后仍保持 pending，APScheduler 按 CronTrigger 自动续程
                if task.is_daily and task.cron_expression:
                    task.status = "pending"
                    task.completed_at = None
                else:
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
        """从 Agent 输出中提取最终文本响应。"""
        response = result.get("response")
        if isinstance(response, str):
            return response
        if response is not None:
            return json.dumps(response, ensure_ascii=False, default=str)
        return ""

    @staticmethod
    def _extract_provider_and_model(result: Dict[str, Any]) -> tuple[Optional[str], Optional[str]]:
        """从执行结果中提取实际使用的 provider 和 model。"""
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
        """提取任务页展示所需的轻量执行元数据。"""
        return {
            "status": result.get("status"),
            "skills_executed": result.get("skills_executed", 0),
            "plugins_executed": result.get("plugins_executed", 0),
            "experiences_used": result.get("experiences_used", 0),
            "memories_used": result.get("memories_used", 0),
        }


scheduled_task_manager = ScheduledTaskManager()
