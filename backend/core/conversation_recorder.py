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
    对话记录器，负责异步批量记录用户与 AI 的对话数据。
    支持按用户控制数据采集开关，使用队列缓冲和批量写入优化性能。
    """
    def __init__(
        self,
        batch_size: int = 50,
        flush_interval: float = 1.0,
        queue_maxsize: int = 2000,
    ):
        """
        初始化对话记录器。
        
        Args:
            batch_size: 批量写入的记录数量阈值。
            flush_interval: 刷新间隔时间（秒）。
            queue_maxsize: 队列最大容量。
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
        启动后台工作线程，开始处理队列中的记录。
        """
        if self._worker_task and not self._worker_task.done():
            return
        self._shutdown_event.clear()
        self._worker_task = asyncio.create_task(self._worker_loop())

    async def stop(self) -> None:
        """
        停止后台工作线程，等待队列中剩余记录写入完成。
        """
        if not self._worker_task:
            return
        self._shutdown_event.set()
        await self._worker_task
        self._worker_task = None

    def set_collection_enabled(self, enabled: bool, current_user: Any = None, user_id: Optional[str] = None) -> bool:
        """
        设置用户的数据采集开关。
        
        Args:
            enabled: 是否启用采集。
            current_user: 当前用户对象。
            user_id: 用户 ID。
            
        Returns:
            设置成功返回 True，无法识别用户返回 False。
        """
        resolved_user_id = self._resolve_user_id(current_user=current_user, user_id=user_id)
        if not resolved_user_id:
            return False
        self._collection_preferences[resolved_user_id] = enabled
        return True

    def is_collection_enabled(self, current_user: Any = None, user_id: Optional[str] = None) -> bool:
        """
        检查用户是否启用了数据采集。
        
        Args:
            current_user: 当前用户对象。
            user_id: 用户 ID。
            
        Returns:
            启用返回 True，否则返回 False。
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
        记录一条对话数据到队列。
        
        Args:
            node_type: 节点类型。
            session_id: 会话 ID。
            user_message: 用户消息内容。
            current_user: 当前用户对象。
            user_id: 用户 ID。
            provider: 供应商名称。
            model: 模型名称。
            llm_input: LLM 输入数据。
            llm_output: LLM 输出数据。
            llm_tokens_used: 使用的 token 数量。
            execution_duration_ms: 执行耗时（毫秒）。
            status: 执行状态。
            error_message: 错误信息。
            metadata: 元数据。
            timestamp: 时间戳。
            
        Returns:
            记录成功返回 True，否则返回 False。
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
        获取运行时统计信息。
        
        Returns:
            包含队列大小、丢弃数量等统计数据的字典。
        """
        return {
            "queue_size": self.queue.qsize(),
            "queue_maxsize": self.queue.maxsize,
            "dropped_count": self._dropped_count,
            "tracked_user_count": len(self._collection_preferences),
        }

    async def _worker_loop(self) -> None:
        """
        后台工作循环，持续从队列获取记录并批量写入数据库。
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
        从队列中收集一批记录。
        
        Returns:
            记录字典列表。
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
        异步批量写入记录到数据库。
        
        Args:
            batch: 记录字典列表。
        """
        try:
            # 将同步 ORM 提交下沉到线程中，避免在事件循环线程里直接执行 commit。
            await asyncio.to_thread(self._flush_batch_sync, batch)
        finally:
            for _ in batch:
                self.queue.task_done()

    def _flush_batch_sync(self, batch: list[Dict[str, Any]]) -> None:
        """
        在线程中执行同步数据库写入。
        这样可以保留现有同步 SessionLocal 实现，同时避免阻塞 asyncio 主循环。
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

    def _resolve_user_id(self, current_user: Any = None, user_id: Optional[str] = None) -> Optional[str]:
        """
        从用户对象或参数中解析用户 ID。
        
        Args:
            current_user: 当前用户对象。
            user_id: 用户 ID。
            
        Returns:
            用户 ID，无法解析时返回 None。
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
        将可选值序列化为 JSON 字符串。
        
        Args:
            value: 待序列化的值。
            
        Returns:
            JSON 字符串，若输入为 None 则返回 None。
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
