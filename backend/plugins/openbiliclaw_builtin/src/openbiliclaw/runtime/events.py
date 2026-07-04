"""用于弹窗实时状态更新的运行时事件广播。"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RuntimeEventHub:
    """向感兴趣的订阅者广播轻量级运行时事件。"""

    _subscribers: set[asyncio.Queue[dict[str, Any]]] = field(default_factory=set)

    async def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        """注册一个订阅者队列。"""
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._subscribers.add(queue)
        return queue

    async def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        """移除一个订阅者队列。"""
        self._subscribers.discard(queue)

    async def publish(self, event: dict[str, Any]) -> bool:
        """将一个事件扇出给所有当前订阅者。

        当至少一个订阅者队列接受了事件时返回 ``True``。
        需要根据投递结果决定副作用的调用方，在没有运行时流打开时
        可避免把一次性事件标记为已消费。
        """
        delivered = False
        for queue in list(self._subscribers):
            with suppress(asyncio.QueueFull):
                queue.put_nowait(dict(event))
                delivered = True
        return delivered
