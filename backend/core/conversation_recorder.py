import asyncio
import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from loguru import logger

from db.models import ConversationRecord, SessionLocal


class ConversationRecorder:
    def __init__(
        self,
        batch_size: int = 50,
        flush_interval: float = 1.0,
        queue_maxsize: int = 2000,
    ):
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self.queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue(maxsize=queue_maxsize)
        self._worker_task: Optional[asyncio.Task] = None
        self._shutdown_event = asyncio.Event()
        self._collection_preferences: Dict[str, bool] = {}
        self._dropped_count = 0

    async def start(self) -> None:
        if self._worker_task and not self._worker_task.done():
            return
        self._shutdown_event.clear()
        self._worker_task = asyncio.create_task(self._worker_loop())

    async def stop(self) -> None:
        if not self._worker_task:
            return
        self._shutdown_event.set()
        await self._worker_task
        self._worker_task = None

    def set_collection_enabled(self, enabled: bool, current_user: Any = None, user_id: Optional[str] = None) -> bool:
        resolved_user_id = self._resolve_user_id(current_user=current_user, user_id=user_id)
        if not resolved_user_id:
            return False
        self._collection_preferences[resolved_user_id] = enabled
        return True

    def is_collection_enabled(self, current_user: Any = None, user_id: Optional[str] = None) -> bool:
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
        return {
            "queue_size": self.queue.qsize(),
            "queue_maxsize": self.queue.maxsize,
            "dropped_count": self._dropped_count,
            "tracked_user_count": len(self._collection_preferences),
        }

    async def _worker_loop(self) -> None:
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
        if user_id:
            return user_id
        if current_user is None:
            return None
        candidate = getattr(current_user, "id", None)
        if isinstance(candidate, str) and candidate:
            return candidate
        return None

    def _serialize_optional(self, value: Any) -> Optional[str]:
        if value is None:
            return None
        if isinstance(value, str):
            return value
        try:
            return json.dumps(value, ensure_ascii=False, default=str)
        except TypeError:
            return str(value)


conversation_recorder = ConversationRecorder()
