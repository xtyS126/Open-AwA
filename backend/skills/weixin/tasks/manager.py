"""
异步任务管理器模块
提供任务创建、状态存储、进度追踪、结果回调、超时清理等功能
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Awaitable

from loguru import logger


class TaskStatus(str, Enum):
    """
    任务状态枚举
    
    属性:
        PENDING: 待执行
        RUNNING: 执行中
        COMPLETED: 已完成
        FAILED: 已失败
        CANCELLED: 已取消
    """
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class AsyncTask:
    """
    异步任务数据类
    封装任务的完整状态信息
    
    属性:
        id: 任务唯一标识符
        type: 任务类型
        status: 任务状态
        progress: 任务进度（0-100）
        result: 任务结果数据
        error: 错误信息
        created_at: 创建时间戳
        updated_at: 更新时间戳
        expires_at: 过期时间戳
        params: 任务参数
        metadata: 任务元数据
    """
    id: str
    type: str
    status: str = TaskStatus.PENDING.value
    progress: int = 0
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    expires_at: float = 0.0
    params: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        """
        初始化后处理
        确保时间戳正确设置
        """
        if self.created_at == 0:
            self.created_at = time.time()
        if self.updated_at == 0:
            self.updated_at = self.created_at
        if self.expires_at == 0:
            self.expires_at = self.created_at + 3600
    
    def to_dict(self) -> Dict[str, Any]:
        """
        将任务转换为字典格式
        
        返回:
            包含任务所有字段的字典
        """
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> AsyncTask:
        """
        从字典创建任务实例
        
        参数:
            data: 包含任务信息的字典
            
        返回:
            AsyncTask实例
        """
        return cls(
            id=str(data.get("id", "")),
            type=str(data.get("type", "")),
            status=str(data.get("status", TaskStatus.PENDING.value)),
            progress=int(data.get("progress", 0)),
            result=data.get("result"),
            error=data.get("error"),
            created_at=float(data.get("created_at", 0)),
            updated_at=float(data.get("updated_at", 0)),
            expires_at=float(data.get("expires_at", 0)),
            params=data.get("params", {}),
            metadata=data.get("metadata", {}),
        )
    
    def is_expired(self) -> bool:
        """
        检查任务是否已过期
        
        返回:
            如果任务已过期则返回True
        """
        return time.time() > self.expires_at
    
    def is_terminal(self) -> bool:
        """
        检查任务是否处于终态
        
        返回:
            如果任务已完成、失败或取消则返回True
        """
        return self.status in {
            TaskStatus.COMPLETED.value,
            TaskStatus.FAILED.value,
            TaskStatus.CANCELLED.value,
        }


class TaskManager:
    """
    任务管理器类
    管理异步任务的生命周期，包括创建、更新、查询和清理
    
    属性:
        state_root: 状态文件根目录
        default_ttl: 默认任务存活时间（秒）
        cleanup_interval: 清理间隔（秒）
    """
    
    def __init__(
        self,
        state_root: str,
        default_ttl: int = 3600,
        cleanup_interval: int = 300,
    ):
        """
        初始化任务管理器
        
        参数:
            state_root: 状态文件根目录
            default_ttl: 默认任务存活时间（秒），默认1小时
            cleanup_interval: 自动清理间隔（秒），默认5分钟
        """
        self.state_root = state_root
        self.default_ttl = default_ttl
        self.cleanup_interval = cleanup_interval
        
        self._tasks: Dict[str, AsyncTask] = {}
        self._callbacks: Dict[str, List[Callable[[AsyncTask], Awaitable[None]]]] = {}
        self._progress_callbacks: Dict[str, List[Callable[[AsyncTask], Awaitable[None]]]] = {}
        self._lock = asyncio.Lock()
        self._cleanup_task: Optional[asyncio.Task] = None
        
        self._tasks_dir = os.path.join(state_root, "tasks")
        os.makedirs(self._tasks_dir, exist_ok=True)
        
        self._load_tasks_from_disk()
    
    def _task_file_path(self, task_id: str) -> str:
        """
        获取任务文件路径
        
        参数:
            task_id: 任务ID
            
        返回:
            任务文件的绝对路径
        """
        safe_id = task_id.replace("/", "-").replace("\\", "-")
        return os.path.join(self._tasks_dir, f"{safe_id}.json")
    
    def _load_tasks_from_disk(self) -> None:
        """
        从磁盘加载所有任务
        """
        if not os.path.isdir(self._tasks_dir):
            return
        
        for filename in os.listdir(self._tasks_dir):
            if not filename.endswith(".json"):
                continue
            
            file_path = os.path.join(self._tasks_dir, filename)
            try:
                with open(file_path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                task = AsyncTask.from_dict(data)
                if not task.is_expired():
                    self._tasks[task.id] = task
            except Exception as exc:
                logger.warning(f"Failed to load task file {file_path}: {exc}")
    
    def _save_task_to_disk(self, task: AsyncTask) -> None:
        """
        将任务保存到磁盘
        
        参数:
            task: 要保存的任务
        """
        file_path = self._task_file_path(task.id)
        try:
            with open(file_path, "w", encoding="utf-8") as fh:
                json.dump(task.to_dict(), fh, ensure_ascii=False, indent=2)
        except Exception as exc:
            logger.warning(f"Failed to save task file {file_path}: {exc}")
    
    def _delete_task_from_disk(self, task_id: str) -> None:
        """
        从磁盘删除任务文件
        
        参数:
            task_id: 任务ID
        """
        file_path = self._task_file_path(task_id)
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
        except Exception as exc:
            logger.warning(f"Failed to delete task file {file_path}: {exc}")
    
    async def start_cleanup_loop(self) -> None:
        """
        启动自动清理循环
        """
        if self._cleanup_task is not None:
            return
        
        async def cleanup_loop():
            while True:
                try:
                    await asyncio.sleep(self.cleanup_interval)
                    cleaned = await self.cleanup_expired()
                    if cleaned > 0:
                        logger.debug(f"Auto cleanup: removed {cleaned} expired tasks")
                except asyncio.CancelledError:
                    break
                except Exception as exc:
                    logger.error(f"Cleanup loop error: {exc}")
        
        self._cleanup_task = asyncio.create_task(cleanup_loop())
    
    async def stop_cleanup_loop(self) -> None:
        """
        停止自动清理循环
        """
        if self._cleanup_task is not None:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None
    
    async def create_task(
        self,
        task_type: str,
        params: Dict[str, Any],
        ttl: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AsyncTask:
        """
        创建新任务
        
        参数:
            task_type: 任务类型
            params: 任务参数
            ttl: 任务存活时间（秒），None使用默认值
            metadata: 任务元数据
            
        返回:
            新创建的AsyncTask实例
        """
        now = time.time()
        task_ttl = ttl if ttl is not None else self.default_ttl
        
        task = AsyncTask(
            id=str(uuid.uuid4()),
            type=task_type,
            status=TaskStatus.PENDING.value,
            progress=0,
            created_at=now,
            updated_at=now,
            expires_at=now + task_ttl,
            params=params,
            metadata=metadata or {},
        )
        
        async with self._lock:
            self._tasks[task.id] = task
            self._callbacks[task.id] = []
            self._progress_callbacks[task.id] = []
            self._save_task_to_disk(task)
        
        logger.debug(f"Created task {task.id} (type={task_type})")
        return task
    
    async def get_task(self, task_id: str) -> Optional[AsyncTask]:
        """
        获取任务信息
        
        参数:
            task_id: 任务ID
            
        返回:
            AsyncTask实例，如果不存在则返回None
        """
        async with self._lock:
            return self._tasks.get(task_id)
    
    async def update_progress(self, task_id: str, progress: int) -> None:
        """
        更新任务进度
        
        参数:
            task_id: 任务ID
            progress: 进度值（0-100）
        """
        progress = max(0, min(100, progress))
        
        async with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                logger.warning(f"Task {task_id} not found for progress update")
                return
            
            if task.is_terminal():
                logger.warning(f"Task {task_id} is in terminal state, cannot update progress")
                return
            
            task.progress = progress
            task.updated_at = time.time()
            
            if task.status == TaskStatus.PENDING.value:
                task.status = TaskStatus.RUNNING.value
            
            self._save_task_to_disk(task)
            
            callbacks = self._progress_callbacks.get(task_id, [])
        
        for callback in callbacks:
            try:
                await callback(task)
            except Exception as exc:
                logger.warning(f"Progress callback error for task {task_id}: {exc}")
    
    async def complete_task(self, task_id: str, result: Dict[str, Any]) -> None:
        """
        标记任务完成
        
        参数:
            task_id: 任务ID
            result: 任务结果数据
        """
        async with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                logger.warning(f"Task {task_id} not found for completion")
                return
            
            task.status = TaskStatus.COMPLETED.value
            task.progress = 100
            task.result = result
            task.updated_at = time.time()
            
            self._save_task_to_disk(task)
            
            callbacks = self._callbacks.get(task_id, [])
        
        for callback in callbacks:
            try:
                await callback(task)
            except Exception as exc:
                logger.warning(f"Completion callback error for task {task_id}: {exc}")
        
        logger.debug(f"Task {task_id} completed")
    
    async def fail_task(self, task_id: str, error: str) -> None:
        """
        标记任务失败
        
        参数:
            task_id: 任务ID
            error: 错误信息
        """
        async with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                logger.warning(f"Task {task_id} not found for failure")
                return
            
            task.status = TaskStatus.FAILED.value
            task.error = error
            task.updated_at = time.time()
            
            self._save_task_to_disk(task)
            
            callbacks = self._callbacks.get(task_id, [])
        
        for callback in callbacks:
            try:
                await callback(task)
            except Exception as exc:
                logger.warning(f"Failure callback error for task {task_id}: {exc}")
        
        logger.debug(f"Task {task_id} failed: {error}")
    
    async def cancel_task(self, task_id: str) -> None:
        """
        取消任务
        
        参数:
            task_id: 任务ID
        """
        async with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                logger.warning(f"Task {task_id} not found for cancellation")
                return
            
            if task.is_terminal():
                logger.warning(f"Task {task_id} is in terminal state, cannot cancel")
                return
            
            task.status = TaskStatus.CANCELLED.value
            task.updated_at = time.time()
            
            self._save_task_to_disk(task)
            
            callbacks = self._callbacks.get(task_id, [])
        
        for callback in callbacks:
            try:
                await callback(task)
            except Exception as exc:
                logger.warning(f"Cancellation callback error for task {task_id}: {exc}")
        
        logger.debug(f"Task {task_id} cancelled")
    
    async def cleanup_expired(self) -> int:
        """
        清理过期任务
        
        返回:
            清理的任务数量
        """
        cleaned = 0
        tasks_to_remove: List[str] = []
        
        async with self._lock:
            for task_id, task in list(self._tasks.items()):
                if task.is_expired() or task.is_terminal():
                    tasks_to_remove.append(task_id)
            
            for task_id in tasks_to_remove:
                self._tasks.pop(task_id, None)
                self._callbacks.pop(task_id, None)
                self._progress_callbacks.pop(task_id, None)
                self._delete_task_from_disk(task_id)
                cleaned += 1
        
        if cleaned > 0:
            logger.debug(f"Cleaned up {cleaned} expired/completed tasks")
        
        return cleaned
    
    async def list_tasks(
        self,
        task_type: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
    ) -> List[AsyncTask]:
        """
        列出任务
        
        参数:
            task_type: 过滤任务类型，None表示不过滤
            status: 过滤任务状态，None表示不过滤
            limit: 返回数量限制
            
        返回:
            符合条件的任务列表
        """
        async with self._lock:
            tasks = list(self._tasks.values())
        
        if task_type is not None:
            tasks = [t for t in tasks if t.type == task_type]
        
        if status is not None:
            tasks = [t for t in tasks if t.status == status]
        
        tasks.sort(key=lambda t: t.created_at, reverse=True)
        return tasks[:limit]
    
    def on_complete(
        self,
        task_id: str,
        callback: Callable[[AsyncTask], Awaitable[None]],
    ) -> None:
        """
        注册任务完成回调
        
        参数:
            task_id: 任务ID
            callback: 回调函数
        """
        if task_id not in self._callbacks:
            self._callbacks[task_id] = []
        self._callbacks[task_id].append(callback)
    
    def on_progress(
        self,
        task_id: str,
        callback: Callable[[AsyncTask], Awaitable[None]],
    ) -> None:
        """
        注册任务进度回调
        
        参数:
            task_id: 任务ID
            callback: 回调函数
        """
        if task_id not in self._progress_callbacks:
            self._progress_callbacks[task_id] = []
        self._progress_callbacks[task_id].append(callback)
    
    async def wait_for_task(
        self,
        task_id: str,
        timeout: Optional[float] = None,
    ) -> Optional[AsyncTask]:
        """
        等待任务完成
        
        参数:
            task_id: 任务ID
            timeout: 超时时间（秒），None表示无限等待
            
        返回:
            完成后的任务，如果超时则返回None
        """
        start_time = time.time()
        
        while True:
            task = await self.get_task(task_id)
            if task is None:
                return None
            
            if task.is_terminal():
                return task
            
            if timeout is not None:
                elapsed = time.time() - start_time
                if elapsed >= timeout:
                    return None
            
            await asyncio.sleep(0.5)
    
    async def get_stats(self) -> Dict[str, Any]:
        """
        获取任务统计信息
        
        返回:
            包含任务统计数据的字典
        """
        async with self._lock:
            tasks = list(self._tasks.values())
        
        stats = {
            "total": len(tasks),
            "pending": 0,
            "running": 0,
            "completed": 0,
            "failed": 0,
            "cancelled": 0,
            "expired": 0,
        }
        
        for task in tasks:
            if task.is_expired():
                stats["expired"] += 1
            elif task.status == TaskStatus.PENDING.value:
                stats["pending"] += 1
            elif task.status == TaskStatus.RUNNING.value:
                stats["running"] += 1
            elif task.status == TaskStatus.COMPLETED.value:
                stats["completed"] += 1
            elif task.status == TaskStatus.FAILED.value:
                stats["failed"] += 1
            elif task.status == TaskStatus.CANCELLED.value:
                stats["cancelled"] += 1
        
        return stats
