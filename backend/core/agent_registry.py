"""
AIAgent 实例级缓存注册表模块。

按 user_id 维度复用 AIAgent 实例，避免每个请求重复构造
SkillEngine/WorkflowEngine/MemoryManager 等重量级依赖，
从而降低请求延迟与内存抖动。提供 TTL 过期淘汰与 LRU 容量上限保护。
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections import OrderedDict
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, AsyncIterator, Dict, Tuple

from loguru import logger

if TYPE_CHECKING:
    # 仅用于类型标注，运行时延迟导入以避免循环依赖
    from sqlalchemy.orm import Session

    from core.agent import AIAgent


class AIAgentRegistry:
    """
    AIAgent 实例级缓存注册表。

    按 user_id 维度复用 AIAgent 实例，避免每请求重复构造
    SkillEngine/WorkflowEngine/MemoryManager 等重量级组件。

    - TTL 10 分钟过期淘汰：超过该时长未被访问的实例将被移除并在下次访问时重新构造。
    - LRU 上限 100 个实例：超出容量时淘汰最久未访问的实例。
    - 线程安全：使用 threading.Lock 保护并发访问（AIAgent 构造为同步操作）。
    """

    _MAX_INSTANCES = 100
    _TTL_SECONDS = 600  # 10 分钟

    def __init__(self) -> None:
        """初始化缓存注册表，构建空缓存字典与互斥锁。"""
        # user_id -> (AIAgent 实例, 最近访问时间戳)
        self._cache: "OrderedDict[int, Tuple[AIAgent, float]]" = OrderedDict()
        self._lock = threading.Lock()
        # AIAgent 持有请求级数据库会话和可变执行状态，同一用户必须串行使用缓存实例
        self._request_locks: Dict[int, asyncio.Lock] = {}

    @asynccontextmanager
    async def acquire(
        self,
        user_id: int,
        db_session: "Session",
    ) -> AsyncIterator["AIAgent"]:
        """独占租用指定用户的 Agent，并原子完成数据库会话绑定。"""
        with self._lock:
            request_lock = self._request_locks.setdefault(user_id, asyncio.Lock())

        async with request_lock:
            yield self.get_or_create(user_id, db_session)

    def get_or_create(self, user_id: int, db_session: "Session") -> "AIAgent":
        """
        获取或创建指定 user_id 的 AIAgent 实例。

        命中且未过期时复用实例，并通过 agent.bind_db(db_session) 更新数据库会话；
        未命中或已过期时构造新实例并写入缓存；
        实例数超过上限时按 LRU 策略淘汰最旧实例。

        Args:
            user_id: 用户 ID，作为缓存键。
            db_session: SQLAlchemy 数据库会话，用于 AIAgent 构造与 bind_db 更新。

        Returns:
            复用或新建的 AIAgent 实例。
        """
        # 延迟导入 AIAgent，避免与 core.agent 形成循环导入
        from core.agent import AIAgent

        now = time.time()
        with self._lock:
            if user_id in self._cache:
                agent, last_access_time = self._cache[user_id]
                # 判断是否过期：last_access_time + TTL > now 表示未过期
                if now - last_access_time < self._TTL_SECONDS:
                    # 命中且未过期：更新访问时间并移至队尾（标记为最近使用）
                    self._cache[user_id] = (agent, now)
                    self._cache.move_to_end(user_id)
                    logger.bind(
                        event="agent_registry_hit",
                        module="agent_registry",
                        user_id=user_id,
                    ).debug("复用 AIAgent 实例")
                    # 更新 db_session 引用，确保复用实例使用当前请求的会话
                    # bind_db 方法将在 Task 2 中实现
                    agent.bind_db(db_session)
                    return agent
                else:
                    # 已过期：移除旧实例，后续走新建流程
                    logger.bind(
                        event="agent_registry_expired",
                        module="agent_registry",
                        user_id=user_id,
                    ).info("AIAgent 实例已过期，重新构造")
                    del self._cache[user_id]

            # 缓存未命中或已过期淘汰后，需要新建实例
            # 在新建前检查容量上限，按 LRU 淘汰最旧实例
            if len(self._cache) >= self._MAX_INSTANCES:
                # popitem(last=False) 移除队首元素，即最久未访问的实例
                evicted_user_id, _ = self._cache.popitem(last=False)
                logger.bind(
                    event="agent_registry_lru_evict",
                    module="agent_registry",
                    evicted_user_id=evicted_user_id,
                ).warning("AIAgent 实例数超过上限，淘汰最旧实例")

            agent = AIAgent(db_session=db_session)
            self._cache[user_id] = (agent, now)
            # move_to_end 确保新插入的实例位于队尾（最新使用）
            self._cache.move_to_end(user_id)
            logger.bind(
                event="agent_registry_miss",
                module="agent_registry",
                user_id=user_id,
            ).info("新建 AIAgent 实例并缓存")
            return agent

    def invalidate(self, user_id: int) -> None:
        """
        从缓存中移除指定 user_id 的实例。

        供测试与热重载场景使用，确保下次访问该 user_id 时重新构造实例。

        Args:
            user_id: 需要失效的用户 ID。
        """
        with self._lock:
            if self._cache.pop(user_id, None) is not None:
                logger.bind(
                    event="agent_registry_invalidate",
                    module="agent_registry",
                    user_id=user_id,
                ).info("移除指定 user_id 的 AIAgent 缓存实例")

    def clear_all(self) -> None:
        """清空所有缓存实例，释放内存资源。"""
        with self._lock:
            cleared_count = len(self._cache)
            self._cache.clear()
            self._request_locks.clear()
            if cleared_count > 0:
                logger.bind(
                    event="agent_registry_clear_all",
                    module="agent_registry",
                    cleared_count=cleared_count,
                ).info("清空所有 AIAgent 缓存实例")


# 模块级单例：全局共享的注册表实例
_registry_instance = AIAgentRegistry()


def get_registry() -> AIAgentRegistry:
    """
    获取全局 AIAgentRegistry 单例。

    Returns:
        模块级共享的 AIAgentRegistry 实例。
    """
    return _registry_instance
