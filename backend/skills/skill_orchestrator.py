"""
多技能编排器 — 支持 DAG（有向无环图）方式组合多个技能。

使用拓扑排序确定执行顺序，并行执行无依赖关系的节点。
适用场景：复杂任务需要多个技能按顺序/并行协作完成。

用法:
    orchestrator = SkillOrchestrator()
    pipeline = orchestrator.build_pipeline([
        TaskStep(id="extract", skill="pdf", ...),
        TaskStep(id="analyze", skill="llm", depends_on=["extract"], ...),
    ])
    result = await orchestrator.execute_pipeline(pipeline, context)
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set

from loguru import logger


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------

class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"  # 因上游失败而被跳过


@dataclass
class TaskStep:
    """流水线中的单个任务步骤。"""
    id: str
    skill_name: str
    inputs: Dict[str, Any] = field(default_factory=dict)
    depends_on: List[str] = field(default_factory=list)  # 依赖的步骤 ID 列表
    timeout: float = 120.0
    continue_on_error: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "skill_name": self.skill_name,
            "inputs": self.inputs,
            "depends_on": self.depends_on,
            "timeout": self.timeout,
        }


@dataclass
class StepExecution:
    """步骤执行状态。"""
    step: TaskStep
    status: StepStatus = StepStatus.PENDING
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    start_time: float = 0.0
    end_time: float = 0.0

    @property
    def duration(self) -> float:
        if self.start_time and self.end_time:
            return self.end_time - self.start_time
        return 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.step.id,
            "skill_name": self.step.skill_name,
            "status": self.status.value,
            "result": self.result,
            "error": self.error,
            "duration": round(self.duration, 3),
        }


@dataclass
class PipelineResult:
    """流水线执行结果。"""
    success: bool
    steps: List[StepExecution]
    total_duration: float = 0.0
    summary: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "steps": [s.to_dict() for s in self.steps],
            "total_duration": round(self.total_duration, 3),
            "summary": self.summary,
        }


# ---------------------------------------------------------------------------
# 编排器
# ---------------------------------------------------------------------------

class SkillOrchestrator:
    """
    多技能 DAG 编排器。

    支持：
    - 拓扑排序确定执行顺序
    - 同层并行执行（无依赖步骤同时运行）
    - 失败传播控制（continue_on_error）
    - 结果合并和聚合
    """

    def __init__(self):
        self._executions: Dict[str, StepExecution] = {}

    def build_pipeline(self, steps: List[TaskStep]) -> List[TaskStep]:
        """
        验证并构建执行流水线。

        检查项：
        - 步骤 ID 唯一性
        - 依赖引用有效性（无悬空依赖）
        - 无循环依赖

        Returns:
            验证通过的步骤列表（拓扑排序后）。
        """
        step_ids = {s.id for s in steps}

        # 检查 ID 唯一性
        if len(step_ids) != len(steps):
            duplicates = [s.id for s in steps if list(s.id for s2 in steps if s2.id == s.id).count(s.id) > 1]
            raise ValueError(f"步骤 ID 不唯一: {set(duplicates)}")

        # 检查依赖有效性
        for step in steps:
            for dep_id in step.depends_on:
                if dep_id not in step_ids:
                    raise ValueError(f"步骤 '{step.id}' 依赖不存在的步骤 '{dep_id}'")

        # 检查循环依赖（拓扑排序）
        sorted_ids = self._topological_sort(steps)
        ordered_steps = {s.id: s for s in steps}
        result = [ordered_steps[sid] for sid in sorted_ids if sid in ordered_steps]

        logger.info(f"构建流水线: {len(result)} 个步骤, 拓扑排序完成")
        return result

    async def execute_pipeline(
        self,
        steps: List[TaskStep],
        executor: Callable[[str, Dict, Dict], Any],
        context: Optional[Dict[str, Any]] = None,
        fail_fast: bool = True,
    ) -> PipelineResult:
        """
        执行技能流水线。

        Args:
            steps: 已排序的任务步骤列表。
            executor: 技能执行函数，签名为 async (skill_name, inputs, context) -> result_dict。
            context: 共享上下文，传递给每个步骤。
            fail_fast: 若为 True，任一步骤失败则跳过后续依赖该步骤的所有步骤。

        Returns:
            PipelineResult 包含所有步骤的执行结果。
        """
        if not steps:
            return PipelineResult(success=True, steps=[], summary={"completed": 0})

        start_time = time.time()
        ctx = context or {}

        # 初始化执行状态
        executions: Dict[str, StepExecution] = {}
        for step in steps:
            executions[step.id] = StepExecution(step=step)
        self._executions = executions

        # 构建依赖图
        dependents: Dict[str, List[str]] = defaultdict(list)  # step_id → 被哪些步骤依赖
        pending_deps: Dict[str, Set[str]] = {}  # step_id → 尚未完成的依赖集合
        for step in steps:
            pending_deps[step.id] = set(step.depends_on)
            for dep_id in step.depends_on:
                dependents[dep_id].append(step.id)

        # 找出初始可执行步骤（无依赖）
        ready_queue: deque[str] = deque()
        for step in steps:
            if not pending_deps[step.id]:
                ready_queue.append(step.id)

        # 收集每轮可并行执行的步骤
        while ready_queue:
            # 当前轮次的所有就绪步骤（并行执行）
            current_batch = list(ready_queue)
            ready_queue.clear()

            logger.info(f"并行执行 {len(current_batch)} 个步骤: {current_batch}")

            tasks = []
            for step_id in current_batch:
                step = executions[step_id].step
                task = self._execute_single_step(step, executor, ctx)
                tasks.append((step_id, task))

            # 并行等待当前批次
            results = await asyncio.gather(
                *[t[1] for t in tasks],
                return_exceptions=True,
            )

            for (step_id, _), result in zip(tasks, results):
                if isinstance(result, Exception):
                    executions[step_id].status = StepStatus.FAILED
                    executions[step_id].error = str(result)
                    executions[step_id].end_time = time.time()
                    logger.error(f"步骤 '{step_id}' 执行异常: {result}")
                else:
                    executions[step_id] = result

                # 传播结果到下游
                if executions[step_id].status == StepStatus.COMPLETED:
                    # 将成功步骤的输出合并到上下文，供下游使用
                    step_result = executions[step_id].result or {}
                    ctx[f"step_{step_id}_output"] = step_result

                    for dep_id in dependents.get(step_id, []):
                        if dep_id in pending_deps:
                            pending_deps[dep_id].discard(step_id)
                            if not pending_deps[dep_id]:
                                ready_queue.append(dep_id)

                elif executions[step_id].status == StepStatus.FAILED:
                    if fail_fast:
                        # 跳过依赖此步骤的所有下游步骤
                        for dep_id in dependents.get(step_id, []):
                            if dep_id in pending_deps:
                                pending_deps[dep_id].discard(step_id)
                                executions[dep_id].status = StepStatus.SKIPPED
                                executions[dep_id].error = f"上游步骤 '{step_id}' 执行失败"
                                executions[dep_id].end_time = time.time()

        total_duration = time.time() - start_time

        # 汇总统计
        summary = {
            "total": len(steps),
            "completed": sum(1 for e in executions.values() if e.status == StepStatus.COMPLETED),
            "failed": sum(1 for e in executions.values() if e.status == StepStatus.FAILED),
            "skipped": sum(1 for e in executions.values() if e.status == StepStatus.SKIPPED),
            "pending": sum(1 for e in executions.values() if e.status == StepStatus.PENDING),
        }

        overall_success = summary["failed"] == 0 and summary["pending"] == 0

        logger.info(
            f"流水线执行完成: success={overall_success}, "
            f"completed={summary['completed']}, failed={summary['failed']}, "
            f"skipped={summary['skipped']}, duration={total_duration:.2f}s"
        )

        return PipelineResult(
            success=overall_success,
            steps=list(executions.values()),
            total_duration=total_duration,
            summary=summary,
        )

    async def _execute_single_step(
        self,
        step: TaskStep,
        executor: Callable,
        context: Dict,
    ) -> StepExecution:
        """执行单个步骤（带超时控制和错误处理）。"""
        execution = StepExecution(step=step, start_time=time.time())
        execution.status = StepStatus.RUNNING

        try:
            result = await asyncio.wait_for(
                executor(step.skill_name, step.inputs, context),
                timeout=step.timeout,
            )

            if isinstance(result, dict) and not result.get("success", True):
                execution.status = StepStatus.FAILED
                execution.error = result.get("error", "技能执行返回失败")
                execution.result = result
            else:
                execution.status = StepStatus.COMPLETED
                execution.result = result

        except asyncio.TimeoutError:
            execution.status = StepStatus.FAILED
            execution.error = f"步骤 '{step.id}' 执行超时（{step.timeout}秒）"
            logger.warning(execution.error)

        except Exception as e:
            execution.status = StepStatus.FAILED
            execution.error = f"步骤 '{step.id}' 执行异常: {str(e)}"
            logger.error(execution.error)

        finally:
            execution.end_time = time.time()

        return execution

    @staticmethod
    def _topological_sort(steps: List[TaskStep]) -> List[str]:
        """
        拓扑排序（Kahn 算法）返回步骤 ID 列表。

        若检测到循环依赖，抛出 ValueError。
        """
        adj: Dict[str, List[str]] = defaultdict(list)
        in_degree: Dict[str, int] = defaultdict(int)
        step_ids = {s.id for s in steps}

        for step in steps:
            in_degree.setdefault(step.id, 0)
            for dep_id in step.depends_on:
                adj[dep_id].append(step.id)
                in_degree[step.id] = in_degree.get(step.id, 0) + 1

        # Kahn 算法
        queue: deque[str] = deque(sid for sid in step_ids if in_degree.get(sid, 0) == 0)
        sorted_ids: List[str] = []

        while queue:
            node = queue.popleft()
            sorted_ids.append(node)
            for neighbor in adj[node]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if len(sorted_ids) != len(step_ids):
            remaining = step_ids - set(sorted_ids)
            raise ValueError(f"检测到循环依赖，涉及步骤: {remaining}")

        return sorted_ids
