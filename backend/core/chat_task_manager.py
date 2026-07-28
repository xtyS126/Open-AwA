"""
聊天任务管理器。

将 agent 流式任务从 SSE 连接生命周期中解耦：
- 任务在独立 asyncio.Task 中运行，前端断连不终止任务
- 任务输出（事件流）缓存在内存 deque 中，支持前端重连后从断点恢复
- 支持查询任务状态、主动取消任务、自动清理过期任务

设计原则：
1. 单实例进程内共享，多 worker 部署需配合 sticky session 或共享存储
2. 事件缓冲保留全量事件，足够覆盖长时间任务；进程重启会丢失（可接受）
3. 任务异常或正常结束都写入最终状态，前端重连可读到结果
"""

import asyncio
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Dict, List, Optional

from loguru import logger


# 任务状态枚举（字符串字面量，避免 enum 序列化负担）
TASK_STATUS_PENDING = "pending"
TASK_STATUS_RUNNING = "running"
TASK_STATUS_COMPLETED = "completed"
TASK_STATUS_FAILED = "failed"
TASK_STATUS_CANCELLED = "cancelled"

# 已完成任务在内存中的保留时长（秒），超时后自动清理
COMPLETED_TASK_TTL_SECONDS = 600  # 10 分钟

# 单任务事件缓冲上限（防止异常任务吃光内存）
MAX_EVENTS_PER_TASK = 5000


@dataclass
class ChatTaskEvent:
    """任务事件条目，按 seq 顺序持久化在缓冲区中。"""

    seq: int
    payload: Dict[str, Any]


@dataclass
class ChatTask:
    """单个聊天任务的运行时状态。"""

    task_id: str
    user_id: str
    session_id: str
    request_id: str
    status: str = TASK_STATUS_PENDING
    events: deque = field(default_factory=lambda: deque(maxlen=MAX_EVENTS_PER_TASK))
    next_seq: int = 0
    created_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    error: Optional[Dict[str, Any]] = None
    # 订阅者队列：每个活跃订阅者一个 asyncio.Queue，任务事件广播到所有队列
    subscribers: List[asyncio.Queue] = field(default_factory=list)
    # 后台运行任务引用，用于取消
    background_task: Optional[asyncio.Task] = None
    # 锁：保护 subscribers 列表的并发修改
    subscribers_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class ChatTaskManager:
    """聊天任务管理器单例。"""

    def __init__(self) -> None:
        self._tasks: Dict[str, ChatTask] = {}
        self._lock = asyncio.Lock()
        self._cleanup_task: Optional[asyncio.Task] = None

    def start_cleanup_loop(self) -> None:
        """启动后台清理循环，定期清理过期任务。"""
        if self._cleanup_task is not None and not self._cleanup_task.done():
            return
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            return
        self._cleanup_task = loop.create_task(self._cleanup_loop())

    async def _cleanup_loop(self) -> None:
        """每 60 秒清理一次过期已完成任务。"""
        while True:
            try:
                await asyncio.sleep(60)
                await self._cleanup_expired_tasks()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.bind(
                    event="chat_task_cleanup_error",
                    module="chat_task_manager",
                ).warning(f"任务清理循环异常: {exc}")

    async def _cleanup_expired_tasks(self) -> None:
        """清理超过 TTL 的已完成任务。"""
        now = time.time()
        expired_ids: List[str] = []
        async with self._lock:
            for task_id, task in self._tasks.items():
                if task.status in (
                    TASK_STATUS_COMPLETED,
                    TASK_STATUS_FAILED,
                    TASK_STATUS_CANCELLED,
                ) and task.finished_at is not None:
                    if now - task.finished_at > COMPLETED_TASK_TTL_SECONDS:
                        expired_ids.append(task_id)
            for task_id in expired_ids:
                self._tasks.pop(task_id, None)
        if expired_ids:
            logger.bind(
                event="chat_task_expired_cleaned",
                module="chat_task_manager",
                count=len(expired_ids),
            ).info(f"清理过期任务 {len(expired_ids)} 个")

    async def register_task(
        self,
        task_id: str,
        user_id: str,
        session_id: str,
        request_id: str,
    ) -> ChatTask:
        """注册新任务到管理器（尚未启动后台执行）。"""
        async with self._lock:
            if task_id in self._tasks:
                # 同一 task_id 重复注册：返回已有任务（幂等）
                return self._tasks[task_id]
            task = ChatTask(
                task_id=task_id,
                user_id=user_id,
                session_id=session_id,
                request_id=request_id,
            )
            self._tasks[task_id] = task
            return task

    async def start_task(
        self,
        task_id: str,
        run_fn,
        *args,
        **kwargs,
    ) -> None:
        """启动后台任务执行 run_fn（协程函数），run_fn 应是 async generator。

        run_fn 会被包装为 _task_runner，逐个 yield 事件并广播给所有订阅者。
        """
        async with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                raise KeyError(f"任务未注册: {task_id}")
            if task.background_task is not None and not task.background_task.done():
                # 已在运行，幂等返回
                return
            task.status = TASK_STATUS_RUNNING
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            task.background_task = loop.create_task(
                self._task_runner(task, run_fn, *args, **kwargs)
            )

    async def _task_runner(
        self,
        task: ChatTask,
        run_fn,
        *args,
        **kwargs,
    ) -> None:
        """任务执行器：消费 run_fn 的异步生成器，广播事件到订阅者。"""
        try:
            async for chunk in run_fn(*args, **kwargs):
                await self._emit_event(task, chunk)
            # 任务正常结束：标记完成
            await self._finalize_task(task, TASK_STATUS_COMPLETED, None)
        except asyncio.CancelledError:
            # 用户主动取消
            await self._finalize_task(task, TASK_STATUS_CANCELLED, None)
            raise
        except Exception as exc:
            # 任务异常
            logger.bind(
                event="chat_task_failed",
                module="chat_task_manager",
                task_id=task.task_id,
                error_type=type(exc).__name__,
            ).opt(exception=True).error(f"聊天任务异常: {exc}")
            error_payload = {
                "type": "error",
                "error": {
                    "code": "task_internal_error",
                    "message": str(exc) or "任务执行异常",
                },
            }
            await self._emit_event(task, error_payload)
            await self._finalize_task(
                task,
                TASK_STATUS_FAILED,
                error_payload.get("error"),
            )

    async def _emit_event(self, task: ChatTask, payload: Dict[str, Any]) -> None:
        """向任务追加一个事件，并广播到所有订阅者队列。"""
        seq = task.next_seq
        task.next_seq += 1
        event = ChatTaskEvent(seq=seq, payload=payload)
        task.events.append(event)
        # 广播到所有订阅者队列（非阻塞 put_nowait，队列满时丢弃以防阻塞任务）
        async with task.subscribers_lock:
            for queue in task.subscribers:
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    # 订阅者消费过慢，丢弃事件以保护任务执行
                    logger.bind(
                        event="chat_task_subscriber_queue_full",
                        module="chat_task_manager",
                        task_id=task.task_id,
                    ).warning("订阅者队列满，事件被丢弃")

    async def _finalize_task(
        self,
        task: ChatTask,
        status: str,
        error: Optional[Dict[str, Any]],
    ) -> None:
        """标记任务最终状态，并通知所有订阅者任务结束。"""
        task.status = status
        task.finished_at = time.time()
        if error is not None:
            task.error = error
        # 通知所有订阅者：放入哨兵 None 表示流结束
        async with task.subscribers_lock:
            for queue in task.subscribers:
                try:
                    queue.put_nowait(None)
                except asyncio.QueueFull:
                    pass

    async def subscribe(
        self,
        task_id: str,
        from_seq: int = 0,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """订阅任务事件流。

        - 先添加订阅者队列，再回放历史事件，避免回放与订阅之间的竞态
        - 实时事件通过 queue 消费，跳过已回放的事件（按 seq 去重）
        - 任务结束后（收到 None 哨兵）退出

        Args:
            task_id: 任务 ID
            from_seq: 起始 seq（含），0 表示从头回放

        Yields:
            事件 payload（dict）
        """
        async with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                # 任务不存在：直接结束，调用方会收到空流 + [DONE]
                return

        # 任务已结束：仅回放历史事件后退出
        if task.status in (
            TASK_STATUS_COMPLETED,
            TASK_STATUS_FAILED,
            TASK_STATUS_CANCELLED,
        ):
            for event in list(task.events):
                if event.seq >= from_seq:
                    # 注入 _seq 字段供前端追踪断连重连的 from_seq
                    yield {**event.payload, "_seq": event.seq}
            return

        # 任务仍在运行：先添加 queue 到 subscribers，再回放历史事件
        # 顺序很重要：先订阅再回放，避免回放期间产生的新事件丢失
        queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
        async with task.subscribers_lock:
            task.subscribers.append(queue)
            # 记录订阅时刻的 next_seq，用于去重（queue 中的事件 seq >= 此值才有效）
            subscribed_seq = task.next_seq

        # 回放历史事件（seq < subscribed_seq 的事件已固化在 events 中）
        replayed_max_seq = -1
        for event in list(task.events):
            if event.seq >= from_seq and event.seq < subscribed_seq:
                # 注入 _seq 字段供前端追踪断连重连的 from_seq
                yield {**event.payload, "_seq": event.seq}
                replayed_max_seq = max(replayed_max_seq, event.seq)

        try:
            while True:
                item = await queue.get()
                if item is None:
                    # 哨兵：任务结束
                    break
                # 跳过已回放的事件（seq <= replayed_max_seq 的事件已在历史回放中 yield）
                if item.seq <= replayed_max_seq:
                    continue
                # 注入 _seq 字段供前端追踪断连重连的 from_seq
                yield {**item.payload, "_seq": item.seq}
        finally:
            async with task.subscribers_lock:
                if queue in task.subscribers:
                    task.subscribers.remove(queue)

    async def cancel_task(self, task_id: str) -> bool:
        """取消任务。返回 True 表示已发送取消信号。"""
        async with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return False
            if task.background_task is None or task.background_task.done():
                return False
            task.background_task.cancel()
            return True

    async def get_task_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        """查询任务状态。"""
        async with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return None
            return {
                "task_id": task.task_id,
                "status": task.status,
                "event_count": len(task.events),
                "next_seq": task.next_seq,
                "created_at": task.created_at,
                "finished_at": task.finished_at,
                "error": task.error,
                "session_id": task.session_id,
                "user_id": task.user_id,
            }

    async def list_user_tasks(
        self,
        user_id: str,
        session_id: Optional[str] = None,
        include_finished: bool = False,
    ) -> List[Dict[str, Any]]:
        """列出用户任务（按创建时间倒序）。"""
        result: List[Dict[str, Any]] = []
        async with self._lock:
            for task in self._tasks.values():
                if task.user_id != user_id:
                    continue
                if session_id and task.session_id != session_id:
                    continue
                if not include_finished and task.status in (
                    TASK_STATUS_COMPLETED,
                    TASK_STATUS_FAILED,
                    TASK_STATUS_CANCELLED,
                ):
                    continue
                result.append({
                    "task_id": task.task_id,
                    "status": task.status,
                    "session_id": task.session_id,
                    "created_at": task.created_at,
                    "finished_at": task.finished_at,
                    "event_count": len(task.events),
                })
        result.sort(key=lambda x: x["created_at"], reverse=True)
        return result


# 模块级单例
_singleton: Optional[ChatTaskManager] = None


def get_chat_task_manager() -> ChatTaskManager:
    """获取 ChatTaskManager 单例。"""
    global _singleton
    if _singleton is None:
        _singleton = ChatTaskManager()
    return _singleton


def generate_task_id() -> str:
    """生成任务 ID（uuid4 hex 字符串，无连字符便于 URL 传递）。"""
    return uuid.uuid4().hex
