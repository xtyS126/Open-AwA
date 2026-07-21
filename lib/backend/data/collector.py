"""
异步数据收集器模块，不阻塞主流程地收集 Agent 交互数据。
使用 asyncio.Queue 实现生产者-消费者模式，批量写入数据库。
"""

import asyncio
from typing import Any, Dict, List, Optional, Tuple
from loguru import logger
from db.models import SessionLocal, ConversationData, ToolCallData, ExecutionTrace, RoleSwitchEvent


class DataCollector:
    """异步数据收集器，不阻塞主流程。"""

    def __init__(self, batch_size: int = 50, flush_interval: float = 5.0):
        self._queue: asyncio.Queue[Tuple[str, Dict[str, Any]]] = asyncio.Queue()
        self._batch_size = batch_size
        self._flush_interval = flush_interval
        self._running = False
        self._write_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """启动后台写入任务。"""
        if self._running:
            return
        self._running = True
        self._write_task = asyncio.create_task(self._write_loop())
        logger.bind(event="data_collector_started", module="data").info("数据收集器已启动")

    async def stop(self) -> None:
        """停止数据收集器，等待剩余数据写入完成。"""
        self._running = False
        if self._write_task:
            try:
                await asyncio.wait_for(self._write_task, timeout=10.0)
            except asyncio.TimeoutError:
                logger.bind(event="data_collector_stop_timeout", module="data").warning(
                    "数据收集器停止超时，可能有数据丢失"
                )
        logger.bind(event="data_collector_stopped", module="data").info("数据收集器已停止")

    async def collect_conversation(self, data: Dict[str, Any]) -> None:
        """收集对话数据（非阻塞）。"""
        await self._queue.put(("conversation", data))

    async def collect_tool_call(self, data: Dict[str, Any]) -> None:
        """收集工具调用数据（非阻塞）。"""
        await self._queue.put(("tool_call", data))

    async def collect_execution_trace(self, data: Dict[str, Any]) -> None:
        """收集执行轨迹数据（非阻塞）。"""
        await self._queue.put(("execution_trace", data))

    async def collect_role_switch(self, data: Dict[str, Any]) -> None:
        """收集角色切换事件（非阻塞）。"""
        await self._queue.put(("role_switch", data))

    async def _write_loop(self) -> None:
        """后台批量写入循环。"""
        while self._running or not self._queue.empty():
            batch: List[Tuple[str, Dict[str, Any]]] = []
            try:
                item = await asyncio.wait_for(
                    self._queue.get(), timeout=self._flush_interval
                )
                batch.append(item)
                while not self._queue.empty() and len(batch) < self._batch_size:
                    batch.append(self._queue.get_nowait())
            except asyncio.TimeoutError:
                continue

            if batch:
                await self._write_batch(batch)

    async def _write_batch(self, batch: List[Tuple[str, Dict[str, Any]]]) -> None:
        """批量写入数据库。"""
        try:
            db = SessionLocal()
            try:
                for data_type, data in batch:
                    self._insert_record(db, data_type, data)
                db.commit()
            except Exception as e:
                db.rollback()
                logger.bind(
                    event="data_collector_write_error",
                    module="data",
                    batch_size=len(batch),
                    error=str(e),
                ).error(f"批量写入数据失败: {e}")
            finally:
                db.close()
        except Exception as e:
            logger.bind(
                event="data_collector_db_error",
                module="data",
                error=str(e),
            ).error(f"数据库连接失败: {e}")

    def _insert_record(
        self, db, data_type: str, data: Dict[str, Any]
    ) -> None:
        """根据数据类型创建对应的 ORM 对象并添加到 session。"""
        if data_type == "conversation":
            record = ConversationData(**data)
        elif data_type == "tool_call":
            record = ToolCallData(**data)
        elif data_type == "execution_trace":
            record = ExecutionTrace(**data)
        elif data_type == "role_switch":
            record = RoleSwitchEvent(**data)
        else:
            logger.bind(
                event="data_collector_unknown_type",
                module="data",
                data_type=data_type,
            ).warning(f"未知的数据类型: {data_type}")
            return
        db.add(record)


# 全局单例
data_collector = DataCollector()
