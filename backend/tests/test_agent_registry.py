"""
AIAgentRegistry 实例级缓存注册表单元测试。

覆盖 backend/core/agent_registry.py 的 LRU + TTL 缓存逻辑：
- 同一 user_id 多次调用返回同一 AIAgent 实例
- 不同 user_id 返回不同实例
- 命中缓存时通过 bind_db 更新请求级 db_session
- invalidate(user_id) 后再调用返回新实例
- clear_all() 后所有 user_id 都返回新实例
- TTL 过期后返回新实例

通过预置 MemoryManager._shared_vector_store 避免 AIAgent 构造时触发
真实的 VectorStoreManager/Qdrant 初始化，其余依赖保持真实调用。
"""

import asyncio
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.agent_registry import AIAgentRegistry
import core.agent as agent_module
from memory.manager import MemoryManager


@pytest.fixture(autouse=True)
def _mock_vector_store(monkeypatch) -> None:
    """预置 MemoryManager._shared_vector_store，避免 AIAgent 构造时触发 VectorStoreManager 初始化。

    AIAgentRegistry.get_or_create 在缓存未命中时会构造真实 AIAgent，
    AIAgent.__init__ 在 db_session 非空时会创建 MemoryManager(SessionLocal)，
    MemoryManager.__init__ 会创建 VectorStoreManager（连接 Qdrant、创建嵌入模型）。
    通过预置类变量 _shared_vector_store 跳过重量级初始化。
    """
    fake_vector_store = MagicMock()
    fake_vector_store.search = AsyncMock(return_value=[])
    monkeypatch.setattr(MemoryManager, "_shared_vector_store", fake_vector_store)


def _make_registry() -> AIAgentRegistry:
    """创建一个全新的 AIAgentRegistry 实例，避免用例间共享缓存状态。"""
    return AIAgentRegistry()


def test_get_or_create_returns_same_instance_for_same_user() -> None:
    """同一 user_id 多次调用 get_or_create 应返回同一 AIAgent 实例。"""
    registry = _make_registry()
    db = MagicMock()

    agent1 = registry.get_or_create(user_id=1, db_session=db)
    agent2 = registry.get_or_create(user_id=1, db_session=db)

    assert agent1 is agent2
    # 缓存中应只有一条记录
    assert len(registry._cache) == 1


def test_get_or_create_returns_different_instances_for_different_users() -> None:
    """不同 user_id 应返回不同的 AIAgent 实例。"""
    registry = _make_registry()
    db = MagicMock()

    agent1 = registry.get_or_create(user_id=1, db_session=db)
    agent2 = registry.get_or_create(user_id=2, db_session=db)

    assert agent1 is not agent2
    # 缓存中应有两条记录
    assert len(registry._cache) == 2
    assert 1 in registry._cache
    assert 2 in registry._cache


@pytest.mark.asyncio
async def test_acquire_serializes_same_user_and_keeps_db_binding(monkeypatch) -> None:
    """同一用户的并发请求不得在执行期间互相覆盖数据库会话。"""

    class FakeAgent:
        def __init__(self, db_session) -> None:
            self.db_session = db_session

        def bind_db(self, db_session) -> None:
            self.db_session = db_session

    monkeypatch.setattr(agent_module, "AIAgent", FakeAgent)
    registry = _make_registry()
    first_entered = asyncio.Event()
    release_first = asyncio.Event()
    second_entered = asyncio.Event()

    async def first_request() -> None:
        async with registry.acquire(1, "db-1") as agent:
            first_entered.set()
            await release_first.wait()
            assert agent.db_session == "db-1"

    async def second_request() -> None:
        await first_entered.wait()
        async with registry.acquire(1, "db-2") as agent:
            second_entered.set()
            assert agent.db_session == "db-2"

    first_task = asyncio.create_task(first_request())
    second_task = asyncio.create_task(second_request())
    await first_entered.wait()
    await asyncio.sleep(0)
    assert second_entered.is_set() is False

    release_first.set()
    await asyncio.gather(first_task, second_task)
    assert second_entered.is_set() is True


def test_bind_db_updates_request_db() -> None:
    """缓存命中时 bind_db 应更新 agent._db_session_request 为本次传入的 db。

    初次创建（缓存未命中）时，AIAgent.__init__ 将 db 存入 _db_session_bound，
    _db_session_request 为 None。第二次调用（命中缓存）时，registry 调用
    agent.bind_db(db_session) 将请求级 db 写入 _db_session_request。
    """
    registry = _make_registry()
    db1 = MagicMock()
    db2 = MagicMock()

    # 初次创建：_db_session_request 为 None，_db_session 属性通过 _db_session_bound 兜底
    agent = registry.get_or_create(user_id=1, db_session=db1)
    assert agent._db_session_request is None
    assert agent._db_session is db1  # 兜底返回 _db_session_bound

    # 第二次调用（命中缓存）：应触发 bind_db，更新 _db_session_request
    agent2 = registry.get_or_create(user_id=1, db_session=db2)
    assert agent2 is agent
    assert agent._db_session_request is db2
    assert agent._db_session is db2  # 优先返回 _db_session_request


def test_invalidate_removes_instance() -> None:
    """invalidate(user_id) 后再调用 get_or_create 应返回新实例。"""
    registry = _make_registry()
    db = MagicMock()

    agent1 = registry.get_or_create(user_id=1, db_session=db)
    assert len(registry._cache) == 1

    # 失效缓存
    registry.invalidate(user_id=1)
    assert len(registry._cache) == 0
    assert 1 not in registry._cache

    # 再次调用应返回新实例
    agent2 = registry.get_or_create(user_id=1, db_session=db)
    assert agent2 is not agent1
    assert len(registry._cache) == 1


def test_invalidate_nonexistent_user_is_noop() -> None:
    """invalidate 不存在的 user_id 应安全返回，不抛异常。"""
    registry = _make_registry()
    # 缓存为空时 invalidate 不应抛异常
    registry.invalidate(user_id=999)
    assert len(registry._cache) == 0


def test_clear_all_removes_all() -> None:
    """clear_all() 后所有 user_id 都应返回新实例。"""
    registry = _make_registry()
    db = MagicMock()

    agent1 = registry.get_or_create(user_id=1, db_session=db)
    agent2 = registry.get_or_create(user_id=2, db_session=db)
    agent3 = registry.get_or_create(user_id=3, db_session=db)
    assert len(registry._cache) == 3

    # 清空所有缓存
    registry.clear_all()
    assert len(registry._cache) == 0

    # 再次调用应全部返回新实例
    new_agent1 = registry.get_or_create(user_id=1, db_session=db)
    new_agent2 = registry.get_or_create(user_id=2, db_session=db)
    new_agent3 = registry.get_or_create(user_id=3, db_session=db)

    assert new_agent1 is not agent1
    assert new_agent2 is not agent2
    assert new_agent3 is not agent3


def test_ttl_expiration_returns_new_instance() -> None:
    """TTL 过期后调用 get_or_create 应返回新实例。

    通过直接修改内部缓存的 last_access_time 模拟过期，
    避免真实等待 600 秒。TTL 阈值为 AIAgentRegistry._TTL_SECONDS（600 秒）。
    """
    registry = _make_registry()
    db = MagicMock()

    agent1 = registry.get_or_create(user_id=1, db_session=db)
    assert len(registry._cache) == 1

    # 模拟 TTL 过期：将 last_access_time 回拨到 700 秒前（超过 600 秒 TTL）
    cached_agent, _ = registry._cache[1]
    assert cached_agent is agent1
    registry._cache[1] = (agent1, time.time() - 700)

    # 再次调用应判定为过期，返回新实例
    agent2 = registry.get_or_create(user_id=1, db_session=db)
    assert agent2 is not agent1
    # 旧实例应被移除，新实例写入缓存
    assert len(registry._cache) == 1
    cached_agent2, _ = registry._cache[1]
    assert cached_agent2 is agent2


def test_lru_eviction_when_exceeding_max_instances() -> None:
    """实例数超过上限时按 LRU 策略淘汰最旧实例。

    临时缩小 _MAX_INSTANCES 阈值便于测试，避免构造 100 个真实 AIAgent。
    """
    registry = _make_registry()
    # 临时缩小容量上限
    original_max = AIAgentRegistry._MAX_INSTANCES
    AIAgentRegistry._MAX_INSTANCES = 2
    try:
        db = MagicMock()

        agent1 = registry.get_or_create(user_id=1, db_session=db)
        agent2 = registry.get_or_create(user_id=2, db_session=db)
        assert len(registry._cache) == 2

        # 插入第三个，应淘汰最旧的 user_id=1
        agent3 = registry.get_or_create(user_id=3, db_session=db)
        assert len(registry._cache) == 2
        assert 1 not in registry._cache  # 最旧的被淘汰
        assert 2 in registry._cache
        assert 3 in registry._cache

        # user_id=1 再次调用应返回新实例（旧实例已被淘汰）
        agent1_new = registry.get_or_create(user_id=1, db_session=db)
        assert agent1_new is not agent1
    finally:
        AIAgentRegistry._MAX_INSTANCES = original_max
