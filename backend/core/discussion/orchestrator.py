"""
多 Agent 讨论任务编排器。

实现 DiscussionOrchestrator 类，负责：
1. 创建讨论任务并触发首轮讨论
2. 顺序调用三个角色（critic -> validator -> approver）进行评审
3. 统计投票结果，决定进入 approved/executing 或 pending_approval（等待修订）
4. 执行被批准的提议动作（plugin_command / tool_call / subagent_delegate）
5. 通过 asyncio.Queue 事件总线向订阅者推送 SSE 事件
6. 提供 stream_discussion_events 异步生成器供 API 层流式消费

设计要点：
- LLM 调用通过注入的 llm_caller 完成解耦，便于测试与多 Provider 支持
- 状态转换全部经过 state_machine.validate_transition 校验
- 事件队列按 task_id 维护订阅列表，队列满时丢弃并记录 WARNING
- 三种执行器分别捕获具体异常并转换为 DiscussionExecutionError
"""

from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Awaitable, Callable, Dict, List, Optional

from loguru import logger
from sqlalchemy.orm import Session

from core.discussion.definitions import (
    BUILTIN_ROLES,
    DiscussionExecutionError,
    DiscussionRoundLimitError,
    DiscussionStateError,
    DiscussionStatus,
    DiscussionTaskData,
    DiscussionVoteData,
    ProposedAction,
    VoteDecision,
)
from core.discussion.roles import build_role_messages
from core.discussion.state_machine import is_terminal, validate_transition


# LLM 调用函数类型：接收 messages 列表，返回 LLM 文本输出
LLMCaller = Callable[[List[Dict[str, str]]], Awaitable[str]]

# 数据库会话工厂类型：调用后返回上下文管理器（支持 with db_session_factory() as db:）
DbSessionFactory = Callable[[], Any]


class DiscussionOrchestrator:
    """
    讨论任务编排器，管理讨论任务的生命周期与多角色评审流程。

    使用方式：
        orchestrator = DiscussionOrchestrator(
            db_session_factory=SessionLocal,
            llm_caller=my_llm_caller,
        )
        task_id = await orchestrator.create_task(
            user_id="u1",
            title="清理临时文件",
            description="...",
            proposed_action=ProposedAction(type="tool_call", payload={...}),
            context={},
        )
        async for event in orchestrator.stream_discussion_events(task_id):
            handle(event)
    """

    def __init__(
        self,
        db_session_factory: DbSessionFactory,
        llm_caller: LLMCaller,
    ) -> None:
        """
        初始化编排器。

        Args:
            db_session_factory: 返回 SQLAlchemy Session 上下文管理器的可调用对象
            llm_caller: 异步函数 (messages: list[dict]) -> str，由调用方注入
            subagent_delegate 执行器经 core/subagent_task_runtime_bridge.py
            复用 task_runtime.spawn_agent（唯一委派运行时），无需额外注入。
        """
        self._db_session_factory = db_session_factory
        self._llm_caller = llm_caller
        # 事件订阅队列：task_id -> 队列列表
        self._event_queues: Dict[str, List[asyncio.Queue]] = {}
        # 订阅列表并发保护锁
        self._queues_lock = asyncio.Lock()

    # ── 任务创建与讨论触发 ──────────────────────────────────────────

    async def create_task(
        self,
        user_id: str,
        title: str,
        description: str,
        proposed_action: ProposedAction,
        context: Dict[str, Any],
        max_rounds: int = 3,
    ) -> str:
        """
        创建讨论任务并异步触发首轮讨论。

        Args:
            user_id: 发起用户 ID
            title: 任务标题
            description: 任务描述
            proposed_action: 待评审的提议动作
            context: 讨论上下文
            max_rounds: 最大讨论轮次，默认 3

        Returns:
            task_id: 新创建的任务 ID
        """
        if not title or not title.strip():
            raise ValueError("任务标题不能为空")
        if not description or not description.strip():
            raise ValueError("任务描述不能为空")
        if max_rounds < 1:
            raise ValueError("max_rounds 必须 >= 1")

        task_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        # 写入数据库
        with self._db_session_factory() as db:
            from db.models import DiscussionTask
            task = DiscussionTask(
                id=task_id,
                user_id=user_id,
                title=title.strip(),
                description=description.strip(),
                proposed_action=proposed_action.to_dict(),
                context=dict(context),
                status=DiscussionStatus.CREATED.value,
                round=1,
                max_rounds=max_rounds,
                created_at=now,
                updated_at=now,
            )
            db.add(task)
            db.commit()
            db.refresh(task)

        logger.bind(
            event="discussion_task_created",
            task_id=task_id,
            user_id=user_id,
            action_type=proposed_action.type,
        ).info(f"讨论任务已创建: {task_id}")

        # 异步触发首轮讨论，不阻塞 create_task 调用方
        asyncio.create_task(self._safe_run_discussion_round(task_id))
        return task_id

    async def _safe_run_discussion_round(self, task_id: str) -> None:
        """
        包装 run_discussion_round，捕获并记录未预期异常，避免后台任务静默失败。

        关键路径错误通过事件总线通知订阅者，并转为 failed 状态。
        """
        try:
            await self.run_discussion_round(task_id)
        except (DiscussionRoundLimitError, DiscussionStateError, DiscussionExecutionError) as e:
            # 业务级异常：记录并通知订阅者
            logger.bind(
                event="discussion_round_failed",
                task_id=task_id,
                error=str(e),
            ).warning(f"讨论轮次失败: {task_id} - {e}")
            await self._emit_event(
                task_id,
                "discussion_error",
                {"task_id": task_id, "error": str(e), "error_type": type(e).__name__},
            )
        except asyncio.CancelledError:
            logger.bind(event="discussion_round_cancelled", task_id=task_id).info(
                f"讨论轮次被取消: {task_id}"
            )
            raise
        except Exception as e:
            # 未预期异常：兜底处理，转为 failed 状态
            logger.bind(
                event="discussion_round_unexpected_error",
                task_id=task_id,
                error=str(e),
            ).error(f"讨论轮次未预期异常: {task_id}")
            await self._mark_failed(task_id, f"未预期异常: {type(e).__name__}: {e}")
            await self._emit_event(
                task_id,
                "discussion_error",
                {"task_id": task_id, "error": str(e), "error_type": type(e).__name__},
            )

    async def run_discussion_round(self, task_id: str) -> None:
        """
        执行一轮讨论：顺序调用 critic -> validator -> approver 三个角色。

        流程：
        1. 状态转为 discussing
        2. 顺序调用每个角色获取 LLM 投票输出
        3. 每个角色发言后推送 discussion_message 与 vote_cast 事件
        4. 三方投票完成后调用 tally_votes 统计结果

        Args:
            task_id: 讨论任务 ID

        Raises:
            DiscussionStateError: 当前状态不允许进入讨论
            DiscussionExecutionError: LLM 调用或解析失败（关键路径）
        """
        task = self._load_task(task_id)
        if task is None:
            raise DiscussionStateError(f"讨论任务不存在: {task_id}")

        # 校验并执行状态转换
        if not validate_transition(task.status, DiscussionStatus.DISCUSSING.value):
            raise DiscussionStateError(
                f"非法状态转换: {task.status} -> {DiscussionStatus.DISCUSSING.value} (task={task_id})"
            )
        self._transition_task_status(task_id, DiscussionStatus.DISCUSSING.value)
        await self._emit_event(
            task_id,
            "status_changed",
            {"task_id": task_id, "status": DiscussionStatus.DISCUSSING.value},
        )

        round_num = task.round
        prior_votes: List[DiscussionVoteData] = []

        # 顺序调用三个角色
        for role in BUILTIN_ROLES:
            vote_data = await self._run_role(task_id, role, round_num, prior_votes)
            prior_votes.append(vote_data)

        # 统计本轮投票
        await self.tally_votes(task_id, round_num)

    async def _run_role(
        self,
        task_id: str,
        role: DiscussionRole,
        round_num: int,
        prior_votes: List[DiscussionVoteData],
    ) -> DiscussionVoteData:
        """
        调用单个角色进行评审，返回投票数据。

        Args:
            task_id: 讨论任务 ID
            role: 当前角色
            round_num: 当前轮次
            prior_votes: 本轮已发言角色的投票记录

        Returns:
            DiscussionVoteData: 该角色本轮投票数据

        Raises:
            DiscussionExecutionError: LLM 调用失败（关键路径错误必须传播）
        """
        task = self._load_task(task_id)
        if task is None:
            raise DiscussionStateError(f"讨论任务不存在: {task_id}")

        # 构建消息
        messages = build_role_messages(role, task, prior_votes)

        # 推送讨论开始事件
        await self._emit_event(
            task_id,
            "discussion_message",
            {
                "task_id": task_id,
                "role": role.value,
                "round": round_num,
                "phase": "thinking",
            },
        )

        # 调用 LLM
        try:
            llm_output = await self._llm_caller(messages)
        except asyncio.TimeoutError as e:
            raise DiscussionExecutionError(
                f"角色 {role.value} LLM 调用超时 (task={task_id})"
            ) from e
        except (ConnectionError, RuntimeError) as e:
            raise DiscussionExecutionError(
                f"角色 {role.value} LLM 调用失败: {e} (task={task_id})"
            ) from e

        # 解析投票输出
        vote_str, reason = self._parse_llm_vote_output(llm_output)

        # 推送角色发言内容
        await self._emit_event(
            task_id,
            "discussion_message",
            {
                "task_id": task_id,
                "role": role.value,
                "round": round_num,
                "phase": "spoken",
                "content": llm_output,
            },
        )

        # 创建投票记录
        vote_data = self._create_vote_record(
            task_id=task_id,
            role=role,
            round_num=round_num,
            vote=vote_str,
            reason=reason,
            transcript=messages,
        )

        # 推送投票事件
        await self._emit_event(
            task_id,
            "vote_cast",
            {
                "task_id": task_id,
                "role": role.value,
                "round": round_num,
                "vote": vote_str,
                "reason": reason,
                "vote_id": vote_data.id,
            },
        )

        logger.bind(
            event="discussion_vote_cast",
            task_id=task_id,
            role=role.value,
            round=round_num,
            vote=vote_str,
        ).info(f"角色 {role.value} 第{round_num}轮投票: {vote_str}")

        return vote_data

    async def tally_votes(self, task_id: str, round_num: int) -> None:
        """
        统计本轮三个角色的投票结果，决定后续状态。

        规则：
        - 全部 approve：状态转 approved，调用 execute_approved_action
        - 任一 reject 或 abstain：状态转 pending_approval，等待用户 revise
        - 推送 status_changed 事件

        Args:
            task_id: 讨论任务 ID
            round_num: 当前轮次
        """
        votes = self._list_votes(task_id, round_num)
        vote_decisions = [v.vote for v in votes]

        all_approve = bool(votes) and all(
            v == VoteDecision.APPROVE.value for v in vote_decisions
        )

        if all_approve:
            # 三方一致通过，转 approved
            self._transition_task_status(task_id, DiscussionStatus.APPROVED.value)
            await self._emit_event(
                task_id,
                "status_changed",
                {"task_id": task_id, "status": DiscussionStatus.APPROVED.value, "round": round_num},
            )
            logger.bind(
                event="discussion_approved",
                task_id=task_id,
                round=round_num,
            ).info(f"讨论任务第{round_num}轮一致通过: {task_id}")
            # 异步执行批准的动作
            asyncio.create_task(self._safe_execute_approved_action(task_id))
        else:
            # 存在 reject 或 abstain，转 pending_approval 等待修订
            self._transition_task_status(task_id, DiscussionStatus.PENDING_APPROVAL.value)
            await self._emit_event(
                task_id,
                "status_changed",
                {
                    "task_id": task_id,
                    "status": DiscussionStatus.PENDING_APPROVAL.value,
                    "round": round_num,
                    "votes": vote_decisions,
                },
            )
            logger.bind(
                event="discussion_pending_approval",
                task_id=task_id,
                round=round_num,
                votes=vote_decisions,
            ).info(f"讨论任务第{round_num}轮进入待修订: {task_id}")

    async def _safe_execute_approved_action(self, task_id: str) -> None:
        """包装 execute_approved_action，捕获未预期异常并转为 failed 状态。"""
        try:
            await self.execute_approved_action(task_id)
        except DiscussionExecutionError as e:
            logger.bind(
                event="discussion_execute_failed",
                task_id=task_id,
                error=str(e),
            ).warning(f"讨论任务执行失败: {task_id} - {e}")
            await self._mark_failed(task_id, str(e))
            await self._emit_event(
                task_id,
                "status_changed",
                {"task_id": task_id, "status": DiscussionStatus.FAILED.value, "error": str(e)},
            )
        except asyncio.CancelledError:
            logger.bind(event="discussion_execute_cancelled", task_id=task_id).info(
                f"讨论任务执行被取消: {task_id}"
            )
            raise
        except Exception as e:
            logger.bind(
                event="discussion_execute_unexpected_error",
                task_id=task_id,
                error=str(e),
            ).error(f"讨论任务执行未预期异常: {task_id}")
            await self._mark_failed(task_id, f"未预期异常: {type(e).__name__}: {e}")
            await self._emit_event(
                task_id,
                "status_changed",
                {"task_id": task_id, "status": DiscussionStatus.FAILED.value, "error": str(e)},
            )

    async def execute_approved_action(self, task_id: str) -> Dict[str, Any]:
        """
        执行被批准的提议动作。

        流程：
        1. 状态转为 executing
        2. 根据 proposed_action.type 分发到对应执行器
        3. 成功则状态转 completed，结果回写到 context.result
        4. 失败则状态转 failed，错误回写 context.error

        Args:
            task_id: 讨论任务 ID

        Returns:
            执行结果 dict

        Raises:
            DiscussionStateError: 任务不存在或状态非法
            DiscussionExecutionError: 执行器不可用或执行失败
        """
        task = self._load_task(task_id)
        if task is None:
            raise DiscussionStateError(f"讨论任务不存在: {task_id}")

        if not validate_transition(task.status, DiscussionStatus.EXECUTING.value):
            raise DiscussionStateError(
                f"非法状态转换: {task.status} -> {DiscussionStatus.EXECUTING.value} (task={task_id})"
            )
        self._transition_task_status(task_id, DiscussionStatus.EXECUTING.value)
        await self._emit_event(
            task_id,
            "status_changed",
            {"task_id": task_id, "status": DiscussionStatus.EXECUTING.value},
        )

        action = task.proposed_action
        try:
            if action.type == "plugin_command":
                result = await self._execute_plugin_command(action.payload)
            elif action.type == "tool_call":
                result = await self._execute_tool_call(action.payload)
            elif action.type == "subagent_delegate":
                result = await self._execute_subagent_delegate(action.payload)
            else:
                raise DiscussionExecutionError(
                    f"未知执行器类型: {action.type} (task={task_id})"
                )
        except DiscussionExecutionError as e:
            # 执行失败：转 failed，错误回写
            self._transition_task_status(task_id, DiscussionStatus.FAILED.value)
            self._update_task_context(task_id, {"error": str(e)})
            await self._emit_event(
                task_id,
                "status_changed",
                {"task_id": task_id, "status": DiscussionStatus.FAILED.value, "error": str(e)},
            )
            raise

        # 执行成功：转 completed，结果回写
        self._transition_task_status(task_id, DiscussionStatus.COMPLETED.value)
        self._update_task_context(task_id, {"result": result})
        await self._emit_event(
            task_id,
            "status_changed",
            {"task_id": task_id, "status": DiscussionStatus.COMPLETED.value, "result": result},
        )
        logger.bind(
            event="discussion_action_executed",
            task_id=task_id,
            action_type=action.type,
        ).info(f"讨论任务执行完成: {task_id}")
        return result

    async def revise_action(
        self, task_id: str, new_proposed_action: ProposedAction
    ) -> None:
        """
        提交修订后的提议动作，触发新一轮讨论。

        Args:
            task_id: 讨论任务 ID
            new_proposed_action: 修订后的提议动作

        Raises:
            DiscussionStateError: 当前状态不允许修订
            DiscussionRoundLimitError: 已超过最大讨论轮次
        """
        task = self._load_task(task_id)
        if task is None:
            raise DiscussionStateError(f"讨论任务不存在: {task_id}")

        # 校验当前状态：仅 pending_approval 或 discussing 允许修订
        if task.status not in (
            DiscussionStatus.PENDING_APPROVAL.value,
            DiscussionStatus.DISCUSSING.value,
        ):
            raise DiscussionStateError(
                f"当前状态 {task.status} 不允许修订 (task={task_id})"
            )

        # 校验轮次上限
        if task.round >= task.max_rounds:
            # 超过轮次上限，转 rejected 终态
            self._transition_task_status(task_id, DiscussionStatus.REJECTED.value)
            await self._emit_event(
                task_id,
                "status_changed",
                {
                    "task_id": task_id,
                    "status": DiscussionStatus.REJECTED.value,
                    "reason": "超过最大讨论轮次",
                    "round": task.round,
                    "max_rounds": task.max_rounds,
                },
            )
            raise DiscussionRoundLimitError(
                f"已超过最大讨论轮次 {task.max_rounds} (task={task_id})"
            )

        # 更新 proposed_action 与 round
        new_round = task.round + 1
        with self._db_session_factory() as db:
            from db.models import DiscussionTask
            db_task = db.get(DiscussionTask, task_id)
            if db_task is None:
                raise DiscussionStateError(f"讨论任务不存在: {task_id}")
            db_task.proposed_action = new_proposed_action.to_dict()
            db_task.round = new_round
            db_task.status = DiscussionStatus.DISCUSSING.value
            db_task.updated_at = datetime.now(timezone.utc)
            db.commit()

        logger.bind(
            event="discussion_action_revised",
            task_id=task_id,
            round=new_round,
            action_type=new_proposed_action.type,
        ).info(f"讨论任务修订: {task_id} -> 第{new_round}轮")

        await self._emit_event(
            task_id,
            "status_changed",
            {
                "task_id": task_id,
                "status": DiscussionStatus.DISCUSSING.value,
                "round": new_round,
                "revised_action": new_proposed_action.to_dict(),
            },
        )

        # 异步触发新一轮讨论
        asyncio.create_task(self._safe_run_discussion_round(task_id))

    # ── SSE 流式推送 ──────────────────────────────────────────────

    def subscribe(self, task_id: str) -> asyncio.Queue:
        """
        订阅指定讨论任务的事件流。

        Args:
            task_id: 讨论任务 ID

        Returns:
            asyncio.Queue: 事件队列，调用方 await queue.get() 接收事件
        """
        queue: asyncio.Queue = asyncio.Queue(maxsize=100)
        # 同步访问 _event_queues 字典；这里在事件循环内，list.append 是原子的
        if task_id not in self._event_queues:
            self._event_queues[task_id] = []
        self._event_queues[task_id].append(queue)
        logger.bind(event="discussion_subscribe", task_id=task_id).debug(
            f"订阅讨论事件: {task_id} (当前订阅者: {len(self._event_queues[task_id])})"
        )
        return queue

    def unsubscribe(self, task_id: str, queue: asyncio.Queue) -> None:
        """取消订阅，从订阅列表移除指定队列。"""
        queues = self._event_queues.get(task_id)
        if not queues:
            return
        try:
            queues.remove(queue)
        except ValueError:
            # 队列不在列表中，忽略
            pass
        if not queues:
            self._event_queues.pop(task_id, None)

    async def _emit_event(self, task_id: str, event_type: str, data: Dict[str, Any]) -> None:
        """
        向所有订阅者推送事件。

        队列满时丢弃事件并记录 WARNING，避免阻塞讨论主流程。
        """
        event = {
            "type": event_type,
            "data": data,
            "timestamp": time.time(),
        }
        queues = self._event_queues.get(task_id, [])
        for queue in list(queues):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.bind(
                    event="discussion_event_dropped",
                    task_id=task_id,
                    event_type=event_type,
                ).warning(f"事件队列已满，丢弃事件: {event_type} (task={task_id})")

    async def stream_discussion_events(
        self, task_id: str, timeout: float = 300.0
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        SSE 流式推送讨论事件。

        订阅事件队列并持续 yield 事件，直到任务进入终态或超时。

        Args:
            task_id: 讨论任务 ID
            timeout: 单次等待事件的超时秒数，默认 300 秒

        Yields:
            事件 dict，结构为 {"type": str, "data": dict, "timestamp": float}
        """
        queue = self.subscribe(task_id)
        try:
            while True:
                # 检查任务是否已进入终态
                task = self._load_task(task_id)
                if task is not None and is_terminal(task.status):
                    # 推送终态事件后退出
                    yield {
                        "type": "status_changed",
                        "data": {
                            "task_id": task_id,
                            "status": task.status,
                            "terminal": True,
                        },
                        "timestamp": time.time(),
                    }
                    return

                try:
                    event = await asyncio.wait_for(queue.get(), timeout=timeout)
                except asyncio.TimeoutError:
                    # 超时未收到事件，发送心跳保持连接
                    yield {
                        "type": "heartbeat",
                        "data": {"task_id": task_id},
                        "timestamp": time.time(),
                    }
                    continue

                yield event

                # 终态事件后退出循环
                if (
                    event.get("type") == "status_changed"
                    and event.get("data", {}).get("status") in (
                        DiscussionStatus.COMPLETED.value,
                        DiscussionStatus.FAILED.value,
                        DiscussionStatus.REJECTED.value,
                    )
                ):
                    return
        finally:
            self.unsubscribe(task_id, queue)

    # ── LLM 输出解析 ──────────────────────────────────────────────

    def _parse_llm_vote_output(self, output: str) -> tuple[str, str]:
        """
        解析 LLM 输出为 (vote, reason) 元组，容错处理。

        容错策略：
        1. 尝试从输出中提取 JSON 代码块或裸 JSON 对象
        2. 解析 vote 与 reason 字段
        3. vote 不合法时默认 abstain
        4. 解析完全失败时返回 (abstain, 原始输出片段)

        Args:
            output: LLM 原始文本输出

        Returns:
            (vote, reason) 元组，vote 为 approve/reject/abstain 之一
        """
        if not output or not output.strip():
            return VoteDecision.ABSTAIN.value, "LLM 输出为空"

        text = output.strip()

        # 尝试提取 ```json ... ``` 代码块
        json_block_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if json_block_match:
            json_str = json_block_match.group(1)
        else:
            # 尝试提取第一个 { ... } 块
            brace_match = re.search(r"\{[^{}]*\}", text, re.DOTALL)
            if brace_match:
                json_str = brace_match.group(0)
            else:
                # 无 JSON 块，尝试整体解析
                json_str = text

        try:
            parsed = json.loads(json_str)
        except json.JSONDecodeError:
            # 尝试补全括号后重试
            try:
                patched = json_str.rstrip()
                if not patched.endswith("}"):
                    patched += "}"
                parsed = json.loads(patched)
            except json.JSONDecodeError:
                logger.bind(event="discussion_vote_parse_failed").warning(
                    f"LLM 输出解析失败，默认 abstain: {text[:200]}"
                )
                return VoteDecision.ABSTAIN.value, f"解析失败，原始输出: {text[:200]}"

        if not isinstance(parsed, dict):
            return VoteDecision.ABSTAIN.value, f"LLM 输出非 JSON 对象: {text[:200]}"

        vote_raw = str(parsed.get("vote", "")).strip().lower()
        reason = str(parsed.get("reason", "")).strip()

        if vote_raw == VoteDecision.APPROVE.value:
            return VoteDecision.APPROVE.value, reason
        if vote_raw == VoteDecision.REJECT.value:
            return VoteDecision.REJECT.value, reason

        # 未知 vote 值，默认 abstain
        return VoteDecision.ABSTAIN.value, reason or f"未知 vote 值: {vote_raw}"

    # ── 三种执行器 ──────────────────────────────────────────────

    async def _execute_plugin_command(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行插件命令。

        payload 结构：
            {"plugin": str, "method": str, "args": dict}

        通过 plugins.plugin_instance.get() 获取 PluginManager 单例，
        调用 execute_plugin_async 执行插件方法。

        Raises:
            DiscussionExecutionError: 插件未加载、方法不存在或执行失败
        """
        plugin_name = payload.get("plugin")
        method = payload.get("method")
        args = payload.get("args") or {}

        if not plugin_name or not method:
            raise DiscussionExecutionError(
                f"plugin_command 缺少必填字段 plugin/method: {payload}"
            )

        try:
            from plugins.plugin_instance import get as get_plugin_manager
        except ImportError as e:
            raise DiscussionExecutionError(
                f"插件管理器模块不可用: {e}"
            ) from e

        try:
            pm = get_plugin_manager()
        except RuntimeError as e:
            raise DiscussionExecutionError(
                f"插件管理器初始化失败: {e}"
            ) from e

        if plugin_name not in pm.loaded_plugins:
            raise DiscussionExecutionError(
                f"插件 '{plugin_name}' 未加载"
            )

        try:
            result = await pm.execute_plugin_async(plugin_name, method, **args)
        except AttributeError as e:
            raise DiscussionExecutionError(
                f"插件 '{plugin_name}' 不存在方法 '{method}': {e}"
            ) from e
        except (ValueError, TypeError) as e:
            raise DiscussionExecutionError(
                f"插件 '{plugin_name}' 方法 '{method}' 参数非法: {e}"
            ) from e
        except TimeoutError as e:
            raise DiscussionExecutionError(
                f"插件 '{plugin_name}' 方法 '{method}' 执行超时: {e}"
            ) from e

        # execute_plugin_async 返回的 dict 含 status 字段
        if isinstance(result, dict) and result.get("status") in ("error", "permission_required"):
            raise DiscussionExecutionError(
                f"插件 '{plugin_name}' 方法 '{method}' 执行失败: {result.get('message', result)}"
            )

        return result

    async def _execute_tool_call(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行 Agent 工具调用。

        payload 结构：
            {"tool": str, "parameters": dict}

        通过 core.tool_registry.tool_registry 全局实例查找并执行工具。

        Raises:
            DiscussionExecutionError: 工具未注册或执行失败
        """
        tool_name = payload.get("tool")
        parameters = payload.get("parameters") or {}

        if not tool_name:
            raise DiscussionExecutionError(
                f"tool_call 缺少必填字段 tool: {payload}"
            )

        try:
            from core.tool_registry import tool_registry
        except ImportError as e:
            raise DiscussionExecutionError(
                f"工具注册表模块不可用: {e}"
            ) from e

        tool_def = tool_registry.get(tool_name)
        if tool_def is None:
            raise DiscussionExecutionError(
                f"工具 '{tool_name}' 未注册"
            )

        try:
            result = await tool_registry.execute(tool_name, parameters)
        except (ValueError, TypeError) as e:
            raise DiscussionExecutionError(
                f"工具 '{tool_name}' 参数非法: {e}"
            ) from e
        except TimeoutError as e:
            raise DiscussionExecutionError(
                f"工具 '{tool_name}' 执行超时: {e}"
            ) from e

        # tool_registry.execute 返回 ToolExecutionResult 对象
        result_dict = result.to_dict() if hasattr(result, "to_dict") else {"result": str(result)}
        if not result_dict.get("ok", True):
            raise DiscussionExecutionError(
                f"工具 '{tool_name}' 执行失败: {result_dict.get('error', '未知错误')}"
            )

        return result_dict

    async def _execute_subagent_delegate(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        委派任务给子代理执行（经 task_runtime 唯一委派运行时）。

        payload 结构：
            {"agent": str, "instruction": str, "context_snippet": str, "allowed_tools": list}

        通过 core/subagent_task_runtime_bridge.run_task_via_task_runtime 复用
        task_runtime.spawn_agent 派生真实 LLM 子代理，与 subagents 图编排共用同一委派路径。

        Raises:
            DiscussionExecutionError: 委派不可用或执行失败
        """
        agent_name = payload.get("agent")
        instruction = payload.get("instruction")

        if not agent_name or not instruction:
            raise DiscussionExecutionError(
                f"subagent_delegate 缺少必填字段 agent/instruction: {payload}"
            )

        # 上下文片段追加到指令，确保真实 LLM 子代理可见必要上下文
        context_snippet = str(payload.get("context_snippet") or "").strip()
        prompt = str(instruction).strip()
        if context_snippet:
            prompt = f"{prompt}\n\n[上下文]\n{context_snippet}"

        try:
            from core.subagent import SubagentTask
            from core.subagent_task_runtime_bridge import run_task_via_task_runtime
        except ImportError as e:
            raise DiscussionExecutionError(
                f"子代理桥接模块不可用: {e}"
            ) from e

        subagent_task = SubagentTask(
            task_id=str(uuid.uuid4()),
            instruction=prompt,
            context_snippet=context_snippet,
            allowed_tools=list(payload.get("allowed_tools") or []),
            metadata={"agent_name": agent_name},
        )

        try:
            result = await run_task_via_task_runtime(subagent_task)
        except ValueError as e:
            # 任务级隔离级别等非法参数，必须显式失败
            raise DiscussionExecutionError(
                f"子代理委派参数非法: {e}"
            ) from e
        except Exception as e:
            raise DiscussionExecutionError(
                f"子代理 '{agent_name}' 委派执行失败: {e}"
            ) from e

        if result is None:
            raise DiscussionExecutionError(
                f"子代理 '{agent_name}' 未注册或 task_runtime 不可用"
            )
        if not result.success:
            raise DiscussionExecutionError(
                f"子代理 '{agent_name}' 执行失败: {result.error or '未知错误'}"
            )

        return {
            "ok": True,
            "agent": agent_name,
            "output": result.output,
            "tokens_used": result.tokens_used,
            "elapsed_seconds": result.elapsed_seconds,
            "runtime": "task_runtime",
        }

    # ── 数据库访问辅助方法 ──────────────────────────────────────────

    def _load_task(self, task_id: str) -> Optional[DiscussionTaskData]:
        """从数据库加载讨论任务并转换为 dataclass。"""
        with self._db_session_factory() as db:
            from db.models import DiscussionTask
            task = db.get(DiscussionTask, task_id)
            if task is None:
                return None
            return DiscussionTaskData.from_orm(task)

    def _transition_task_status(self, task_id: str, new_status: str) -> None:
        """更新任务状态（已假定经过 validate_transition 校验）。"""
        with self._db_session_factory() as db:
            from db.models import DiscussionTask
            db_task = db.get(DiscussionTask, task_id)
            if db_task is None:
                raise DiscussionStateError(f"讨论任务不存在: {task_id}")
            db_task.status = new_status
            db_task.updated_at = datetime.now(timezone.utc)
            if new_status in (
                DiscussionStatus.COMPLETED.value,
                DiscussionStatus.FAILED.value,
                DiscussionStatus.REJECTED.value,
            ):
                db_task.completed_at = datetime.now(timezone.utc)
            db.commit()

    def _update_task_context(self, task_id: str, patch: Dict[str, Any]) -> None:
        """将 patch 合并到任务的 context 字段。"""
        with self._db_session_factory() as db:
            from db.models import DiscussionTask
            db_task = db.get(DiscussionTask, task_id)
            if db_task is None:
                raise DiscussionStateError(f"讨论任务不存在: {task_id}")
            current_context = dict(db_task.context) if db_task.context else {}
            current_context.update(patch)
            db_task.context = current_context
            db_task.updated_at = datetime.now(timezone.utc)
            db.commit()

    def _create_vote_record(
        self,
        task_id: str,
        role: DiscussionRole,
        round_num: int,
        vote: str,
        reason: str,
        transcript: List[Dict[str, str]],
    ) -> DiscussionVoteData:
        """创建投票数据库记录并返回 dataclass。"""
        vote_id = str(uuid.uuid4())
        with self._db_session_factory() as db:
            from db.models import DiscussionVote
            vote_record = DiscussionVote(
                id=vote_id,
                discussion_id=task_id,
                role=role.value,
                round=round_num,
                vote=vote,
                reason=reason,
                transcript=list(transcript),
            )
            db.add(vote_record)
            db.commit()
            db.refresh(vote_record)
            return DiscussionVoteData.from_orm(vote_record)

    def _list_votes(self, task_id: str, round_num: int) -> List[DiscussionVoteData]:
        """查询指定轮次的所有投票记录。"""
        with self._db_session_factory() as db:
            from db.models import DiscussionVote
            from sqlalchemy import select
            stmt = (
                select(DiscussionVote)
                .where(
                    DiscussionVote.discussion_id == task_id,
                    DiscussionVote.round == round_num,
                )
                .order_by(DiscussionVote.created_at)
            )
            results = db.execute(stmt).scalars().all()
            return [DiscussionVoteData.from_orm(v) for v in results]

    async def _mark_failed(self, task_id: str, error: str) -> None:
        """将任务标记为 failed 并回写错误信息。"""
        try:
            self._transition_task_status(task_id, DiscussionStatus.FAILED.value)
            self._update_task_context(task_id, {"error": error})
        except DiscussionStateError as e:
            # 状态转换失败时仅记录日志，避免掩盖原始异常
            logger.bind(
                event="discussion_mark_failed_error",
                task_id=task_id,
                error=str(e),
            ).error(f"标记 failed 状态失败: {task_id} - {e}")
