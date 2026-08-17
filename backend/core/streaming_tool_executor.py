"""
流式工具执行器：支持工具调用的并发调度与串行回退。

设计参考 OpenCode StreamingToolExecutor：
- 通过 ToolDefinition 的并发属性（is_concurrency_safe/is_read_only/is_destructive）
  自动判定工具是否可并发执行
- 只读且并发安全的工具可同时执行
- 破坏性工具必须串行执行（队列中有破坏性工具时阻塞其他工具）
- 通过 asyncio.Queue 实现完成事件流，支持 yield_completed 异步生成器

集成到 executor.py，替换原有的同步顺序执行逻辑。
"""

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional

from loguru import logger

from core.abort_controller import AbortController
from core.tool_registry import ToolDefinition, resolve_concurrency_safe


class ToolExecutionState(str, Enum):
    """工具执行状态"""
    QUEUED = "queued"        # 已提交，等待调度
    EXECUTING = "executing"  # 正在执行
    COMPLETED = "completed"  # 执行完成（含成功与失败）
    YIELDED = "yielded"      # 结果已被消费


@dataclass
class TrackedTool:
    """
    跟踪单个工具调用的执行状态。

    abort_controller 字段在 Task 7 中由 StreamingToolExecutor 设置为
    sibling controller 的子 controller，支持级联中止。
    """
    tool_call_id: str
    tool_name: str
    input_params: dict
    state: ToolExecutionState = ToolExecutionState.QUEUED
    task: Optional[asyncio.Task] = None
    # 工具的中止控制器，由 sibling controller 创建子节点
    abort_controller: Optional[AbortController] = None
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    result: Optional[Any] = None
    error: Optional[Exception] = None


def _execute_fn_accepts_abort(execute_fn: Callable) -> bool:
    """
    判断工具执行函数是否接受第三个参数 abort_controller。

    兼容旧签名（tool_name, input_params）与 3 参数签名（含 abort_controller）。
    无法检视签名时（builtin/partial 等）按 3 参数签名处理（生产执行链均使用）。

    Args:
        execute_fn: 工具执行函数

    Returns:
        是否接受 abort_controller 参数
    """
    try:
        import inspect
        sig = inspect.signature(execute_fn)
        params = [
            p for p in sig.parameters.values()
            if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
        ]
        return len(params) >= 3
    except (TypeError, ValueError):
        # 无法检视签名（如 builtin/部分 partial），默认按 3 参数签名处理
        return True


def can_execute_tool(
    tracked: TrackedTool,
    queue: List[TrackedTool],
    tool_definition: ToolDefinition,
) -> bool:
    """
    根据真值表判定新工具是否可在当前执行队列中并发执行。

    真值表（按判定顺序）：
    1. 队列为空：可以执行（返回 True）
    2. 新工具是破坏性的（is_destructive=True）：不能执行（返回 False）
    3. 队列中有破坏性工具在执行：不能执行（返回 False）
    4. 新工具是只读并发安全的（is_read_only=True 且 is_concurrency_safe=True）：可以执行
    5. 其他情况：不能执行（保守策略，返回 False）

    队列中工具的破坏性判定通过全局 tool_registry 查找定义实现。

    Args:
        tracked: 待执行的工具跟踪对象
        queue: 当前正在执行的工具队列
        tool_definition: 待执行工具的定义，包含并发属性

    Returns:
        是否可以并发执行
    """
    # 规则 1：队列为空，可以执行
    if not queue:
        return True

    # 规则 2：新工具是破坏性的，不能并发执行
    if tool_definition.is_destructive:
        return False

    # 规则 3：队列中有破坏性工具在执行，不能并发执行
    # 从全局 tool_registry 查找队列中工具的定义
    from core.tool_registry import tool_registry as global_registry
    for executing in queue:
        exec_def = global_registry.get(executing.tool_name)
        if exec_def is not None and exec_def.is_destructive:
            return False

    # 规则 4：新工具是只读并发安全的，可以并发执行
    # is_read_only 支持输入驱动判定（如 run_command 按命令内容判断）
    is_concurrency_safe = resolve_concurrency_safe(tool_definition, tracked.input_params)
    from core.tool_registry import resolve_read_only
    if resolve_read_only(tool_definition, tracked.input_params) and is_concurrency_safe:
        return True

    # 规则 5：其他情况，保守策略返回 False
    return False


class StreamingToolExecutor:
    """
    流式工具执行器：支持并发调度与串行回退。

    职责：
    1. 接收工具调用提交（submit）
    2. 根据工具并发属性调度执行（process_queue）
    3. 通过异步生成器流式输出完成结果（yield_completed）

    调度策略：
    - 只读且并发安全的工具可同时执行（受 max_concurrent 限制）
    - 破坏性工具必须串行执行
    - 队列中有破坏性工具时，阻塞其他工具
    """

    def __init__(self, tool_registry: Any, max_concurrent: int = 5):
        """
        初始化流式工具执行器。

        Args:
            tool_registry: 工具注册中心，用于查找工具定义
            max_concurrent: 最大并发执行数，默认 5
        """
        self.tool_registry = tool_registry
        self.max_concurrent = max_concurrent
        # 待调度的工具队列
        self._queue: List[TrackedTool] = []
        # 已完成工具的异步队列，供 yield_completed 消费
        self._completed: asyncio.Queue[TrackedTool] = asyncio.Queue()
        # 当前正在执行的工具列表
        self._executing: List[TrackedTool] = []
        # 已提交工具总数（用于判断是否全部完成）
        self._total_submitted: int = 0
        # 已完成工具总数（用于判断是否全部完成）
        self._total_completed: int = 0
        # 当前轮次的 sibling 中止控制器，工具出错时级联中止兄弟工具
        self._sibling_abort_controller: Optional[AbortController] = None

    def submit(self, tool_call_id: str, tool_name: str, input_params: dict) -> None:
        """
        提交工具调用到调度队列。

        Args:
            tool_call_id: 工具调用唯一标识
            tool_name: 工具名称
            input_params: 工具输入参数
        """
        tracked = TrackedTool(
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            input_params=input_params,
        )
        self._queue.append(tracked)
        self._total_submitted += 1
        logger.bind(
            module="streaming_tool_executor",
            event="tool_submitted",
            tool_call_id=tool_call_id,
            tool_name=tool_name,
        ).debug(f"工具已提交: {tool_name} (id={tool_call_id})")

    async def process_queue(self, execute_fn: Callable) -> None:
        """
        调度循环：根据 can_execute_tool 判断是否启动新工具。

        持续运行直到所有已提交的工具都已完成。每次迭代：
        1. 尝试从队列中启动可执行的工具
        2. 等待至少一个执行中的工具完成
        3. 清理已完成的执行中工具

        Args:
            execute_fn: 工具执行函数，签名 (tool_name, input_params) -> result
                        支持同步和异步返回
        """
        # 创建本轮工具调用的 sibling 中止控制器
        # 同一轮工具共享此 controller，工具出错时调用 abort() 级联中止兄弟工具
        self._sibling_abort_controller = AbortController()

        while self._total_completed < self._total_submitted:
            # 尝试启动可执行的工具
            started_any = self._try_start_tools(execute_fn)

            # 死锁保护：没有启动新工具，没有执行中的工具，但队列非空
            # 说明队列中的工具因 can_execute_tool 返回 False 无法启动
            # 此时强制启动队列首个工具以避免死锁
            if not started_any and not self._executing and self._queue:
                logger.bind(
                    module="streaming_tool_executor",
                    event="deadlock_protection_triggered",
                    queue_size=len(self._queue),
                ).warning("触发死锁保护，强制启动队列首个工具")
                self._force_start_first(execute_fn)

            # 等待至少一个执行中的工具完成
            if self._executing:
                await self._wait_for_one_complete()
            elif self._total_completed < self._total_submitted:
                # 没有执行中的工具，但还有未完成的工具
                # 让出控制权避免空转
                await asyncio.sleep(0)

    def _try_start_tools(self, execute_fn: Callable) -> bool:
        """
        尝试从队列中启动可执行的工具。

        Args:
            execute_fn: 工具执行函数

        Returns:
            是否启动了至少一个工具
        """
        started_any = False
        i = 0
        while i < len(self._queue) and len(self._executing) < self.max_concurrent:
            tracked = self._queue[i]
            tool_def = self._get_tool_definition(tracked.tool_name)

            if tool_def is None:
                # 工具未在注册中心注册（如 plugin_/mcp_/task_ 等动态工具）
                # 使用保守的默认定义：非并发安全、非只读、非破坏性
                # 确保未注册工具串行执行，避免并发副作用
                tool_def = ToolDefinition(
                    name=tracked.tool_name,
                    description="未注册工具，使用保守串行策略",
                    is_concurrency_safe=False,
                    is_read_only=False,
                    is_destructive=False,
                )

            if can_execute_tool(tracked, self._executing, tool_def):
                # 可以执行，启动任务
                self._start_tool(tracked, execute_fn)
                self._queue.pop(i)
                started_any = True
            else:
                # 不能执行，检查下一个
                i += 1
        return started_any

    def _start_tool(self, tracked: TrackedTool, execute_fn: Callable) -> None:
        """
        启动单个工具的执行任务。

        Args:
            tracked: 工具跟踪对象
            execute_fn: 工具执行函数
        """
        tracked.state = ToolExecutionState.EXECUTING
        tracked.start_time = time.perf_counter()
        # 为工具创建 sibling controller 的子 controller，支持级联中止
        if self._sibling_abort_controller is not None:
            tracked.abort_controller = self._sibling_abort_controller.create_child()
        tracked.task = asyncio.create_task(
            self._execute_tool(tracked, execute_fn)
        )
        self._executing.append(tracked)
        logger.bind(
            module="streaming_tool_executor",
            event="tool_started",
            tool_call_id=tracked.tool_call_id,
            tool_name=tracked.tool_name,
            executing_count=len(self._executing),
        ).debug(f"工具已启动: {tracked.tool_name} (id={tracked.tool_call_id})")

    def _force_start_first(self, execute_fn: Callable) -> None:
        """
        强制启动队列首个工具（死锁保护）。

        Args:
            execute_fn: 工具执行函数
        """
        if not self._queue:
            return
        tracked = self._queue.pop(0)
        self._start_tool(tracked, execute_fn)

    async def _wait_for_one_complete(self) -> None:
        """
        等待至少一个执行中的任务完成，并清理已完成的工具。
        """
        pending_tasks = [
            t.task for t in self._executing
            if t.task is not None and not t.task.done()
        ]
        if not pending_tasks:
            # 所有任务都已完成，清理执行列表
            self._executing.clear()
            return
        await asyncio.wait(pending_tasks, return_when=asyncio.FIRST_COMPLETED)
        # 清理已完成的执行中工具
        self._executing = [
            t for t in self._executing
            if t.task is not None and not t.task.done()
        ]

    def _get_tool_definition(self, tool_name: str) -> Optional[ToolDefinition]:
        """
        从 tool_registry 查找工具定义。

        Args:
            tool_name: 工具名称

        Returns:
            工具定义，未找到返回 None
        """
        if self.tool_registry is None:
            return None
        return self.tool_registry.get(tool_name)

    async def _execute_tool(self, tracked: TrackedTool, execute_fn: Callable) -> None:
        """
        实际执行工具的协程。

        调用 execute_fn 执行工具，捕获异常并记录结果。
        无论成功或失败，都将 tracked 放入完成队列。

        级联中止策略（参考 ch09 §9.2.2）：仅 Bash 类工具（run_command）出错时
        中止 sibling controller，避免只读工具失败影响无关兄弟工具。

        Args:
            tracked: 工具跟踪对象
            execute_fn: 工具执行函数，签名 (tool_name, input_params, abort_controller) -> result
        """
        try:
            # 将工具级 abort_controller 传入执行函数，使中止信号可到达工具执行链。
            # 兼容旧签名（tool_name, input_params）与 3 参数签名（含 abort_controller）。
            if _execute_fn_accepts_abort(execute_fn):
                result = execute_fn(
                    tracked.tool_name,
                    tracked.input_params,
                    tracked.abort_controller,
                )
            else:
                result = execute_fn(tracked.tool_name, tracked.input_params)
            # 支持异步执行函数
            if asyncio.iscoroutine(result):
                result = await result
            tracked.result = result
        except Exception as e:
            tracked.error = e
            logger.bind(
                module="streaming_tool_executor",
                event="tool_execution_error",
                tool_call_id=tracked.tool_call_id,
                tool_name=tracked.tool_name,
                error_type=type(e).__name__,
            ).error(f"工具执行失败 [{tracked.tool_name}]: {e}")
            # 仅 Bash 类工具出错时级联中止 sibling controller（参考 ch09 §9.2.2）
            if self._is_bash_tool(tracked.tool_name):
                if self._sibling_abort_controller is not None:
                    self._sibling_abort_controller.abort(
                        reason=f"sibling_tool_error:{tracked.tool_name}"
                    )
        finally:
            tracked.end_time = time.perf_counter()
            tracked.state = ToolExecutionState.COMPLETED
            await self._completed.put(tracked)
            self._total_completed += 1

    @staticmethod
    def _is_bash_tool(tool_name: str) -> bool:
        """
        判断工具是否为 Bash 类工具（命令执行）。

        参考 ch09 §9.2.2：仅 Bash 错误取消兄弟工具，独立只读工具失败不应影响其他工具。

        Args:
            tool_name: 工具名称

        Returns:
            是否为 Bash 类工具
        """
        bash_names = {
            "run_command",
            "builtin_run_command",
            "terminal_executor",
        }
        return tool_name in bash_names

    async def yield_completed(self) -> AsyncGenerator[TrackedTool, None]:
        """
        异步生成器：yield 已完成的工具结果。

        持续 yield 直到所有已提交的工具都已被消费。
        与 process_queue 并发运行：process_queue 将完成工具放入 _completed 队列，
        本生成器从队列中读取并 yield。

        Yields:
            TrackedTool: 已完成的工具跟踪对象
        """
        yielded = 0
        while yielded < self._total_submitted:
            tracked = await self._completed.get()
            tracked.state = ToolExecutionState.YIELDED
            yield tracked
            yielded += 1
