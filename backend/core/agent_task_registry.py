"""活跃 Agent 任务的线程安全注册表。"""

from __future__ import annotations

import asyncio
import threading
from typing import Dict, List, Optional, Set, Tuple

from loguru import logger

from config.settings import settings


_active_agent_tasks: Dict[Tuple[str, str], Set[asyncio.Task]] = {}
_active_agent_tasks_lock = threading.RLock()


def register_agent_task(
    user_id: str,
    session_id: str,
    task: asyncio.Task,
) -> None:
    """注册活跃任务，容量不足时先清理终态任务。"""
    with _active_agent_tasks_lock:
        max_active_tasks = settings.MAX_ACTIVE_AGENT_TASKS
        active_count = sum(
            len(tasks) for tasks in _active_agent_tasks.values()
        )
        if active_count >= max_active_tasks:
            _cleanup_completed_tasks()
            active_count = sum(
                len(tasks) for tasks in _active_agent_tasks.values()
            )
        if active_count >= max_active_tasks:
            logger.bind(
                event="agent_task_capacity_reached",
                module="agent_task_registry",
                active_count=active_count,
                max_capacity=max_active_tasks,
            ).warning("活跃 Agent 任务达到容量上限，拒绝注册新任务")
            return
        key = (str(user_id), str(session_id))
        _active_agent_tasks.setdefault(key, set()).add(task)


def unregister_agent_task(
    user_id: str,
    session_id: str,
    task: Optional[asyncio.Task] = None,
) -> None:
    """移除指定用户会话中已完成的任务。"""
    with _active_agent_tasks_lock:
        key = (str(user_id), str(session_id))
        tasks = _active_agent_tasks.get(key)
        if not tasks:
            return
        target = task or asyncio.current_task()
        if target is not None:
            tasks.discard(target)
        if not tasks:
            _active_agent_tasks.pop(key, None)


def get_agent_tasks(
    user_id: str,
    session_id: str,
) -> List[asyncio.Task]:
    """返回指定用户会话的全部活跃任务快照。"""
    with _active_agent_tasks_lock:
        return list(
            _active_agent_tasks.get(
                (str(user_id), str(session_id)),
                set(),
            )
        )


def _cleanup_completed_tasks() -> None:
    """清理已完成或已取消的任务条目。"""
    removed_count = 0
    for key, tasks in list(_active_agent_tasks.items()):
        active_tasks = {task for task in tasks if not task.done()}
        removed_count += len(tasks) - len(active_tasks)
        if active_tasks:
            _active_agent_tasks[key] = active_tasks
        else:
            _active_agent_tasks.pop(key, None)
    if removed_count:
        logger.bind(
            event="agent_tasks_cleanup",
            module="agent_task_registry",
            removed=removed_count,
            remaining=len(_active_agent_tasks),
        ).debug("清理已完成的 Agent 任务条目")
