"""
核心执行编排模块，负责 Agent 主流程中的理解、规划、执行、反馈或记录能力。
这些文件决定了用户请求在内部被如何拆解、编排以及最终落地执行。
"""

import asyncio
import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from loguru import logger

from db.models import ConversationRecord, SessionLocal


class ConversationRecorder:
    """
    封装与ConversationRecorder相关的核心逻辑与运行状态。
    该类通常是当前文件中组织数据与调度行为的主要封装单元。
    """
    def __init__(
        self,
        batch_size: int = 50,
        flush_interval: float = 1.0,
        queue_maxsize: int = 2000,
    ):
        """
        处理init相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self.queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue(maxsize=queue_maxsize)
        self._worker_task: Optional[asyncio.Task] = None
        self._shutdown_event = asyncio.Event()
        self._collection_preferences: Dict[str, bool] = {}
        self._dropped_count = 0

    async def start(self) -> None:
        """
        处理start相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        if self._worker_task and not self._worker_task.done():
            return
        self._shutdown_event.clear()
        self._worker_task = asyncio.create_task(self._worker_loop())

    async def stop(self) -> None:
        """
        处理stop相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        if not self._worker_task:
            return
        self._shutdown_event.set()
        await self._worker_task
        self._worker_task = None

    def set_collection_enabled(self, enabled: bool, current_user: Any = None, user_id: Optional[str] = None) -> bool:
        """
        设置collection、enabled相关配置或运行状态。
        此类方法通常会直接影响后续执行路径或运行上下文中的关键数据。
        """
        resolved_user_id = self._resolve_user_id(current_user=current_user, user_id=user_id)
        if not resolved_user_id:
            return False
        self._collection_preferences[resolved_user_id] = enabled
        return True

    def is_collection_enabled(self, current_user: Any = None, user_id: Optional[str] = None) -> bool:
        """
        处理is、collection、enabled相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        resolved_user_id = self._resolve_user_id(current_user=current_user, user_id=user_id)
        if not resolved_user_id:
            return False
        return self._collection_preferences.get(resolved_user_id, False)

    async def record(
        self,
        *,
        node_type: str,
        session_id: str,
        user_message: str,
        current_user: Any = None,
        user_id: Optional[str] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        llm_input: Any = None,
        llm_output: Any = None,
        llm_tokens_used: Optional[int] = None,
        execution_duration_ms: Optional[int] = None,
        status: str = "success",
        error_message: Optional[str] = None,
        metadata: Any = None,
        timestamp: Optional[datetime] = None,
    ) -> bool:
        """
        处理record相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        resolved_user_id = self._resolve_user_id(current_user=current_user, user_id=user_id)
        if not resolved_user_id:
            return False
        if not self.is_collection_enabled(user_id=resolved_user_id):
            return False

        await self.start()

        payload = {
            "session_id": session_id,
            "user_id": resolved_user_id,
            "node_type": node_type,
            "user_message": user_message,
            "timestamp": timestamp or datetime.now(timezone.utc),
            "provider": provider,
            "model": model,
            "llm_input": self._serialize_optional(llm_input),
            "llm_output": self._serialize_optional(llm_output),
            "llm_tokens_used": llm_tokens_used,
            "execution_duration_ms": execution_duration_ms,
            "status": status,
            "error_message": error_message,
            "record_metadata": self._serialize_optional(metadata),
        }

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
        """
        获取runtime、stats相关数据或当前状态。
        调用方通常依赖该结果继续进行后续判断、渲染或业务编排。
        """
        return {
            "queue_size": self.queue.qsize(),
            "queue_maxsize": self.queue.maxsize,
            "dropped_count": self._dropped_count,
            "tracked_user_count": len(self._collection_preferences),
        }

    async def _worker_loop(self) -> None:
        """
        处理worker、loop相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        while not self._shutdown_event.is_set():
            batch = await self._gather_batch()
            if batch:
                await self._flush_batch(batch)

        tail_batch = []
        while not self.queue.empty():
            try:
                item = self.queue.get_nowait()
                tail_batch.append(item)
            except asyncio.QueueEmpty:
                break

            if len(tail_batch) >= self.batch_size:
                await self._flush_batch(tail_batch)
                tail_batch = []

        if tail_batch:
            await self._flush_batch(tail_batch)

    async def _gather_batch(self) -> list[Dict[str, Any]]:
        """
        处理gather、batch相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
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
        处理flush、batch相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        db = SessionLocal()
        try:
            for item in batch:
                db.add(ConversationRecord(**item))
            db.commit()
        except Exception as e:
            db.rollback()
            logger.error(f"Failed to flush conversation record batch: {e}")
        finally:
            db.close()
            for _ in batch:
                self.queue.task_done()

    def _resolve_user_id(self, current_user: Any = None, user_id: Optional[str] = None) -> Optional[str]:
        """
        处理resolve、user、id相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        if user_id:
            return user_id
        if current_user is None:
            return None
        candidate = getattr(current_user, "id", None)
        if isinstance(candidate, str) and candidate:
            return candidate
        return None

    def _serialize_optional(self, value: Any) -> Optional[str]:
        """
        处理serialize、optional相关逻辑，并为调用方返回对应结果。
        阅读时可结合入参、副作用与返回值理解它在整个链路中的定位。
        """
        if value is None:
            return None
        if isinstance(value, str):
            return value
        try:
            return json.dumps(value, ensure_ascii=False, default=str)
        except TypeError:
            return str(value)


conversation_recorder = ConversationRecorder()
