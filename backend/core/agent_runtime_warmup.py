"""Agent 重量级共享依赖的异步预热适配器。"""

from __future__ import annotations

import asyncio
from typing import Callable

from sqlalchemy.orm import Session

from memory.manager import MemoryManager


def _prewarm_agent_memory_sync(
    session_factory: Callable[[], Session],
) -> None:
    """在线程内确保共享向量运行时已初始化。"""
    if getattr(MemoryManager, "_shared_vector_store", None) is None:
        MemoryManager(session_factory)


async def prewarm_agent_memory(
    session_factory: Callable[[], Session],
) -> None:
    """预热 Agent 记忆依赖，同时保持调用方事件循环可响应。"""
    await asyncio.to_thread(_prewarm_agent_memory_sync, session_factory)
