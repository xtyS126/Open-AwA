"""
行为统计埋点异步批量写入器。
用于承接高频埋点，避免在请求链路中为每条日志单独创建线程任务。
"""

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from loguru import logger

from db.models import BehaviorLog, SessionLocal


class BehaviorLogger:
    """
    通过有界队列 + 批量刷盘的方式写入 BehaviorLog。
    这样可以在高并发场景下限制线程池提交数量，并降低数据库提交频率。
    """

    def __init__(
        self,
        batch_size: int = 50,
        flush_interval: float = 0.5,
        queue_maxsize: int = 2000,
    ) -> None:
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self.queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue(maxsize=queue_maxsize)
        self._worker_task: Optional[asyncio.Task] = None
        self._shutdown_event = asyncio.Event()
        self._dropped_count = 0

    async def start(self) -> None:
        """确保后台刷盘 worker 已启动。"""
        if self._worker_task and not self._worker_task.done():
            return
        self._shutdown_event.clear()
        self._worker_task = asyncio.create_task(self._worker_loop())

    async def stop(self) -> None:
        """停止 worker，并在退出前刷完队列中的尾批数据。"""
        if not self._worker_task:
            return
        self._shutdown_event.set()
        await self._worker_task
        self._worker_task = None

    async def record(self, payload: Dict[str, Any]) -> bool:
        """
        将埋点放入队列。
        队列满时丢弃最旧的数据，为最新请求留出空间，避免请求链路阻塞。
        """
        await self.start()

        try:
            self.queue.put_nowait(payload)
            return True
        except asyncio.QueueFull:
            self._dropped_count += 1
            try:
                self.queue.get_nowait()
                self.queue.task_done()
                self.queue.put_nowait(payload)
                return True
            except asyncio.QueueEmpty:
                return False

    def get_runtime_stats(self) -> Dict[str, int]:
        """返回当前队列运行时指标，便于排查积压与丢弃情况。"""
        return {
            "queue_size": self.queue.qsize(),
            "queue_maxsize": self.queue.maxsize,
            "dropped_count": self._dropped_count,
        }

    async def _worker_loop(self) -> None:
        """持续聚合批次，并将同步数据库写入下沉到线程中执行。"""
        while not self._shutdown_event.is_set():
            batch = await self._gather_batch()
            if batch:
                await self._flush_batch(batch)

        tail_batch = []
        while not self.queue.empty():
            try:
                tail_batch.append(self.queue.get_nowait())
            except asyncio.QueueEmpty:
                break

            if len(tail_batch) >= self.batch_size:
                await self._flush_batch(tail_batch)
                tail_batch = []

        if tail_batch:
            await self._flush_batch(tail_batch)

    async def _gather_batch(self) -> list[Dict[str, Any]]:
        """等待首条数据到达后，尽量合并更多数据形成一批。"""
        batch: list[Dict[str, Any]] = []
        try:
            first_item = await asyncio.wait_for(self.queue.get(), timeout=self.flush_interval)
            batch.append(first_item)
        except TimeoutError:
            return batch

        while len(batch) < self.batch_size:
            try:
                batch.append(self.queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        return batch

    async def _flush_batch(self, batch: list[Dict[str, Any]]) -> None:
        """
        将整批行为日志交给线程执行同步 ORM 写入。
        这样不会在 asyncio 事件循环线程中直接执行 commit。
        """
        try:
            await asyncio.to_thread(self._flush_batch_sync, batch)
        finally:
            for _ in batch:
                self.queue.task_done()

    def _flush_batch_sync(self, batch: list[Dict[str, Any]]) -> None:
        """在线程中执行同步写库。"""
        db = SessionLocal()
        try:
            for item in batch:
                db.add(
                    BehaviorLog(
                        user_id=item["user_id"],
                        action_type=item["action_type"],
                        details=item["details"],
                        timestamp=item.get("timestamp") or datetime.now(timezone.utc),
                    )
                )
            db.commit()
        except Exception as exc:
            db.rollback()
            logger.error(f"Failed to flush behavior log batch: {exc}")
        finally:
            db.close()


behavior_logger = BehaviorLogger()
