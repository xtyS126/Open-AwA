"""
记忆化缓存工具模块单元测试。

覆盖三种装饰器的核心行为：
- TTL 缓存（命中、过期、容量限制）
- LRU 缓存（淘汰策略、默认容量）
- 异步 TTL 缓存（并发去重、过期）
- 缓存管理接口（clear/size/delete/has/peek）
"""

import asyncio

import pytest

import core.utils.memoize as memoize_mod
from core.utils.memoize import (
    _make_key,
    memoize_with_lru,
    memoize_with_ttl,
    memoize_with_ttl_async,
)


class TestMemoizeWithTtl:
    """memoize_with_ttl 行为测试。"""

    def test_memoize_with_ttl_caches_result(self):
        """验证相同参数返回缓存值，不重复计算。"""
        call_count = 0

        @memoize_with_ttl(ttl=60.0)
        def expensive(x: int) -> int:
            nonlocal call_count
            call_count += 1
            return x * 2

        assert expensive(5) == 10
        assert expensive(5) == 10
        # 第二次命中缓存，实际函数只执行一次
        assert call_count == 1

    def test_memoize_with_ttl_expires_after_ttl(self, monkeypatch):
        """验证 TTL 过期后重新计算（使用 mock time 避免真实等待）。"""
        current = [1000.0]
        monkeypatch.setattr(memoize_mod.time, "time", lambda: current[0])

        call_count = 0

        @memoize_with_ttl(ttl=10.0)
        def fetch(x: int) -> int:
            nonlocal call_count
            call_count += 1
            return x

        fetch(1)  # 计算并缓存，count=1
        fetch(1)  # 命中缓存，count=1
        assert call_count == 1

        # 时间推进到过期之后（直接跳过即将过期窗口，避免触发后台刷新）
        current[0] = 1011.0
        fetch(1)  # 已过期，重新计算
        assert call_count == 2

    def test_memoize_with_ttl_maxsize_limit(self):
        """验证超过 maxsize 时淘汰缓存项。"""
        @memoize_with_ttl(ttl=60.0, maxsize=2)
        def func(x: int) -> int:
            return x

        func(1)
        func(2)
        func(3)  # 第 3 项超出 maxsize=2，应淘汰一项
        assert func.cache_size() == 2


class TestMemoizeWithLru:
    """memoize_with_lru 行为测试。"""

    def test_memoize_with_lru_evicts_lru(self):
        """验证 LRU 淘汰策略：最久未访问的项被淘汰。"""
        @memoize_with_lru(maxsize=2)
        def func(x: int) -> int:
            return x * 2

        func(1)  # 缓存顺序: [1]
        func(2)  # 缓存顺序: [1, 2]
        func(1)  # 命中 1，移动到末尾: [2, 1]
        func(3)  # 未命中，淘汰最久未使用 (2): [1, 3]

        key2 = _make_key((2,), {})
        key1 = _make_key((1,), {})
        assert func.cache_has(key2) is False  # 2 被淘汰
        assert func.cache_has(key1) is True  # 1 仍存在

    def test_memoize_with_lru_maxsize_default(self):
        """验证默认 maxsize=100。"""
        @memoize_with_lru()
        def func(x: int) -> int:
            return x

        # 填满默认容量 100
        for i in range(100):
            func(i)
        assert func.cache_size() == 100

        # 第 101 项触发淘汰，容量仍为 100
        func(100)
        assert func.cache_size() == 100


class TestMemoizeWithTtlAsync:
    """memoize_with_ttl_async 行为测试。"""

    @pytest.mark.asyncio
    async def test_memoize_with_ttl_async_dedup(self):
        """验证并发请求去重：同一 key 只执行一次实际函数。"""
        call_count = 0

        @memoize_with_ttl_async(ttl=60.0)
        async def fetch(x: int) -> int:
            nonlocal call_count
            call_count += 1
            # 模拟耗时操作，确保多个协程同时等待
            await asyncio.sleep(0.05)
            return x * 2

        # 并发发起 5 个相同参数的请求
        results = await asyncio.gather(
            fetch(1), fetch(1), fetch(1), fetch(1), fetch(1)
        )

        assert all(r == 2 for r in results)
        # 实际函数只执行一次
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_memoize_with_ttl_async_expires(self, monkeypatch):
        """验证异步版 TTL 过期后重新计算。"""
        current = [1000.0]
        monkeypatch.setattr(memoize_mod.time, "time", lambda: current[0])

        call_count = 0

        @memoize_with_ttl_async(ttl=10.0)
        async def fetch(x: int) -> int:
            nonlocal call_count
            call_count += 1
            return x

        await fetch(1)  # 计算并缓存，count=1
        await fetch(1)  # 命中缓存，count=1
        assert call_count == 1

        # 时间推进到过期之后
        current[0] = 1011.0
        await fetch(1)  # 已过期，重新计算
        assert call_count == 2


class TestCacheManagement:
    """缓存管理接口测试（基于 memoize_with_lru）。"""

    def test_cache_management_clear(self):
        """验证 cache_clear 清空所有缓存。"""
        @memoize_with_lru(maxsize=10)
        def func(x: int) -> int:
            return x

        func(1)
        func(2)
        func(3)
        assert func.cache_size() == 3

        func.cache_clear()
        assert func.cache_size() == 0

    def test_cache_management_size(self):
        """验证 cache_size 返回缓存项数量。"""
        @memoize_with_lru(maxsize=10)
        def func(x: int) -> int:
            return x

        assert func.cache_size() == 0

        func(1)
        assert func.cache_size() == 1

        func(2)
        assert func.cache_size() == 2

        # 命中不增加缓存项
        func(1)
        assert func.cache_size() == 2

    def test_cache_management_delete(self):
        """验证 cache_delete 删除指定 key。"""
        @memoize_with_lru(maxsize=10)
        def func(x: int) -> int:
            return x

        func(1)
        key = _make_key((1,), {})
        assert func.cache_has(key) is True

        func.cache_delete(key)
        assert func.cache_has(key) is False
        assert func.cache_size() == 0

    def test_cache_management_has(self):
        """验证 cache_has 判断 key 是否存在。"""
        @memoize_with_lru(maxsize=10)
        def func(x: int) -> int:
            return x

        func(1)
        assert func.cache_has(_make_key((1,), {})) is True
        assert func.cache_has(_make_key((2,), {})) is False

    def test_cache_management_peek(self):
        """验证 cache_peek 不影响 LRU 顺序。"""
        @memoize_with_lru(maxsize=2)
        def func(x: int) -> int:
            return x * 2

        func(1)  # 缓存顺序: [1]
        func(2)  # 缓存顺序: [1, 2]

        key1 = _make_key((1,), {})
        # peek 查看值但不移动到末尾，顺序仍为 [1, 2]
        assert func.cache_peek(key1) == 2

        func(3)  # 未命中，淘汰最久未使用 (1): [2, 3]
        # 若 peek 影响了顺序，1 会被保留；这里 1 应被淘汰
        assert func.cache_has(key1) is False
        assert func.cache_has(_make_key((2,), {})) is True

    def test_cache_management_set_and_get(self):
        """验证 cache_set 直接写入缓存，cache_get 直接读取缓存。"""
        @memoize_with_lru(maxsize=10)
        def func(x: int) -> int:
            return x * 2

        # 直接写入缓存（不调用函数），使用自定义 key
        custom_key = "client-uuid-123"
        func.cache_set(custom_key, 42)

        # cache_get 应能读取到直接写入的值
        assert func.cache_get(custom_key) == 42
        assert func.cache_has(custom_key) is True
        assert func.cache_size() == 1

        # cache_get 不存在的 key 返回 None
        assert func.cache_get("nonexistent") is None

    def test_cache_set_respects_maxsize(self):
        """验证 cache_set 在超容量时淘汰最久未使用的项。"""
        @memoize_with_lru(maxsize=2)
        def func(x: int) -> int:
            return x

        # 通过 cache_set 写入 3 项，应淘汰第 1 项
        func.cache_set("k1", 1)
        func.cache_set("k2", 2)
        func.cache_set("k3", 3)

        assert func.cache_has("k1") is False  # 被淘汰
        assert func.cache_has("k2") is True
        assert func.cache_has("k3") is True
        assert func.cache_size() == 2
