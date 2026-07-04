"""引导式（GUI）初始化的协调器。

负责在 *活跃* 后端上拥有初始化生命周期（gui-init 规范 §5）：

* 通过 ``init_runs`` 预约实现单次并发启动（TOCTOU），
* 是状态存储 + 进度事件的 **唯一写者**，
* 维护单次运行的 ``enqueued_task_ids`` 集合，writer-gating 据此放行
  初始化自身的引导任务结果，
* 协作式取消后台任务。

它持有 :class:`RuntimeContext`（不是直接的组件引用），并懒读取
``ctx.database`` / ``ctx.event_hub`` / ``ctx.runtime_controller``，
确保在配置驱动的 rebuild 替换组件后仍使用当前实例（评审 R2 A-1）。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Sequence

_TOTAL_STAGES = 4
_STAGE_LABELS = {1: "拉取数据", 2: "分析偏好", 3: "生成画像", 4: "发现内容池"}
_ACTIVE = ("starting", "running")


def _initial_stages() -> list[dict[str, Any]]:
    return [
        {"n": n, "label": _STAGE_LABELS[n], "status": "pending", "reason": None}
        for n in range(1, _TOTAL_STAGES + 1)
    ]


def _utcnow_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")


class InitCoordinator:
    """同一时刻仅允许一次引导式初始化运行的生命周期持有者。"""

    def __init__(self, ctx: Any) -> None:
        self._ctx = ctx
        self._current_task: asyncio.Task[Any] | None = None
        self._enqueued_task_ids: set[str] = set()
        # 串行化状态写入 + 事件发布，避免阶段 3/4 并行进度更新交错或
        # 重排 ``sequence``（规范 §5e）。
        self._write_lock = asyncio.Lock()
        self._seq = 0

    # ── 懒加载组件访问（rebuild 后仍生效） ────────────────────────────────
    @property
    def _db(self) -> Any:
        return self._ctx.database

    @property
    def _event_hub(self) -> Any:
        return getattr(self._ctx, "event_hub", None)

    # ── 启动 / 存活 ────────────────────────────────────────────────────────
    def reconcile_on_boot(self) -> int:
        """把崩溃残留的 starting/running 运行标记为失败。返回数量。"""
        db = self._db
        if db is None:
            return 0
        return int(db.reconcile_init_runs_on_boot())

    def init_active(self) -> bool:
        run = self._db.get_latest_init_run()
        return bool(run and run["status"] in _ACTIVE)

    # ── 启动 / 重置（TOCTOU 在 DB CAS 里；E2 做廉价预检） ──────────────────
    def try_start(self, run_id: str) -> bool:
        """预约一个新运行（单次并发）。成功时初始化阶段列表。"""
        if not self._db.try_reserve_init_starting(run_id):
            return False
        self._enqueued_task_ids = set()
        self._seq = 0
        self._db.update_init_run(
            run_id, stages_json=json.dumps(_initial_stages(), ensure_ascii=False)
        )
        return True

    def reset_to_idle(self, run_id: str, *, reason: str | None = None) -> None:
        """把已预约但未启动的运行回滚（E2 预检拒绝）。"""
        self._db.update_init_run(run_id, status="idle", error_reason=reason)

    # ── 引导任务归属（被 writer-gating 查询，D1） ──────────────────────────
    def register_enqueued_task(self, run_id: str, task_id: str) -> None:
        self._enqueued_task_ids.add(str(task_id))

    def is_owned_bootstrap_task(self, task_id: str) -> bool:
        return self.init_active() and str(task_id) in self._enqueued_task_ids

    def owned_task_ids(self) -> set[str]:
        """活跃运行入队的引导任务 id（空闲时为空）。

        ``next-task`` 据此查询，使扩展只在运行活跃时拿到初始化自身的
        引导工作——绝不会拿到一条陈旧的 pending 任务，否则会让运行的
        采集器饿死（gui-init review）。"""
        if not self.init_active():
            return set()
        return set(self._enqueued_task_ids)

    # ── 后台任务句柄（用于取消） ───────────────────────────────────────────
    def attach_task(self, run_id: str, task: asyncio.Task[Any]) -> None:
        self._current_task = task

    async def cancel_current_run(self, run_id: str) -> bool:
        """请求取消正在运行的任务。包装器的 ``finally`` 会持久化
        ``cancelled`` 状态（单写者；规范 §5f）。"""
        task = self._current_task
        if task is None or task.done():
            return False
        task.cancel()
        return True

    # ── 单一状态写者 ───────────────────────────────────────────────────────
    async def _write(
        self,
        run_id: str,
        *,
        status: str | None = None,
        stage: int | None = None,
        stage_status: str | None = None,
        stage_reason: str | None = None,
        partial_success: bool | None = None,
        error_reason: str | None = None,
        finished: bool = False,
        event_type: str | None = None,
        event_extra: dict[str, Any] | None = None,
    ) -> int:
        async with self._write_lock:
            run = self._db.get_latest_init_run()
            stages = (
                json.loads(run["stages_json"])
                if run and run.get("stages_json")
                else _initial_stages()
            )
            if stage is not None and stage_status is not None:
                for s in stages:
                    if s["n"] == stage:
                        s["status"] = stage_status
                        s["reason"] = stage_reason
            # 终态失败/取消时，把任何仍在 "running" 或 "pending" 的阶段
            # 降级，使状态消费方（以及按阶段状态驱动的扩展 checklist）
            # 不会为已结束的运行展示非终态时间线（gui-init review）。
            if status in ("failed", "cancelled"):
                for s in stages:
                    if s["status"] in ("running", "pending"):
                        s["status"] = status
                        if s.get("reason") is None:
                            s["reason"] = error_reason
            self._seq += 1
            fields: dict[str, Any] = {
                "sequence": self._seq,
                "stages_json": json.dumps(stages, ensure_ascii=False),
            }
            if status is not None:
                fields["status"] = status
            if stage is not None:
                fields["stage"] = stage
            if partial_success is not None:
                fields["partial_success"] = 1 if partial_success else 0
            if error_reason is not None:
                fields["error_reason"] = error_reason
            if finished:
                fields["finished_at"] = _utcnow_iso()
            self._db.update_init_run(run_id, **fields)

            if event_type and self._event_hub is not None:
                event: dict[str, Any] = {
                    "type": event_type,
                    "run_id": run_id,
                    "sequence": self._seq,
                    "stage": stage if stage is not None else _current_stage(stages),
                    "total": _TOTAL_STAGES,
                }
                if event_extra:
                    event.update(event_extra)
                with contextlib.suppress(Exception):
                    await self._event_hub.publish(event)
            return self._seq

    async def mark_running(self, run_id: str) -> None:
        await self._write(run_id, status="running")

    async def stage_started(self, run_id: str, stage: int) -> None:
        await self._write(
            run_id,
            status="running",
            stage=stage,
            stage_status="running",
            event_type="init_progress",
        )

    async def stage_done(
        self, run_id: str, stage: int, *, status: str = "ok", reason: str | None = None
    ) -> None:
        await self._write(
            run_id,
            stage=stage,
            stage_status=status,
            stage_reason=reason,
            event_type="init_progress",
        )

    async def complete(self, run_id: str, *, partial_success: bool = False) -> None:
        await self._write(
            run_id,
            status="completed",
            partial_success=partial_success,
            finished=True,
            event_type="init_completed",
            event_extra={"partial_success": partial_success},
        )

    async def fail(self, run_id: str, reason: str) -> None:
        await self._write(
            run_id,
            status="failed",
            error_reason=reason,
            finished=True,
            event_type="init_failed",
            event_extra={"reason": reason},
        )

    async def cancel(self, run_id: str, reason: str = "cancelled") -> None:
        await self._write(
            run_id,
            status="cancelled",
            error_reason=reason,
            finished=True,
            event_type="init_failed",
            event_extra={"reason": reason},
        )

    # ── 状态读取（运行派生部分；E1 补充 prereqs/can_manage） ───────────────
    def get_status(self) -> dict[str, Any]:
        run = self._db.get_latest_init_run()
        if run is None:
            return {
                "running": False,
                "run_id": None,
                "sequence": 0,
                "current_stage": 0,
                "total_stages": _TOTAL_STAGES,
                "stages": _initial_stages(),
                "partial_success": False,
                "status": "idle",
                "reason": "none",
            }
        stages = json.loads(run["stages_json"]) if run.get("stages_json") else _initial_stages()
        return {
            "running": run["status"] in _ACTIVE,
            "run_id": run["run_id"],
            "sequence": run["sequence"],
            "current_stage": _current_stage(stages),
            "total_stages": _TOTAL_STAGES,
            "stages": stages,
            "partial_success": bool(run["partial_success"]),
            "status": run["status"],
            "reason": run["error_reason"] or "none",
        }


def _current_stage(stages: Sequence[dict[str, Any]]) -> int:
    """仍在运行的最低阶段；否则最高的已完成阶段；否则 0（规范 §5e）。"""
    running = [int(s["n"]) for s in stages if s["status"] == "running"]
    if running:
        return min(running)
    done = [int(s["n"]) for s in stages if s["status"] in ("ok", "warning", "failed")]
    return max(done) if done else 0
