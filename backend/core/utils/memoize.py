"""
记忆化缓存工具模块。

提供三种缓存装饰器：
- memoize_with_ttl: 同步 TTL 缓存（写透 + 后台刷新）
- memoize_with_lru: 同步 LRU 缓存
- memoize_with_ttl_async: 异步 TTL 缓存（in_flight 去重）

每个装饰器返回的包装函数均附加缓存管理方法：
- cache_peek(key): 查看缓存值但不影响 LRU 顺序
- cache_clear(): 清空所有缓存
- cache_size(): 返回缓存项数量
- cache_delete(key): 删除指定 key
- cache_get(key): 直接获取缓存值（不调用函数）
- cache_has(key): 判断 key 是否在缓存中（且未过期）
"""

import asyncio
import threading
import time
from collections import OrderedDict
from functools import wraps
from typing import Any, Callable, Optional


def _make_key(args: tuple, kwargs: dict) -> str:
    """根据函数参数生成缓存 key。"""
    return str(args) + str(sorted(kwargs.items()))


def memoize_with_ttl(ttl: float = 60.0, maxsize: int = 128) -> Callable:
    """
    TTL 缓存装饰器（写透 + 后台刷新）。

    参数:
        ttl: 缓存生存时间（秒）
        maxsize: 最大缓存项数量，超过时淘汰最早插入的项

    缓存命中且未过期（age < ttl*0.8）时直接返回缓存值；
    缓存命中但即将过期（ttl*0.8 <= age < ttl）时返回旧值并后台异步刷新；
    缓存未命中或已过期（age >= ttl）时同步重新计算。
    """
    cache: dict = {}
    lock = threading.Lock()

    def decorator(func: Callable) -> Callable:
        def _refresh(
            target: Callable,
            key: str,
            args: tuple,
            kwargs: dict,
        ) -> None:
            # 后台刷新：失败静默忽略，不影响旧值
            # （任务规范允许的唯一静默吞异常场景）
            try:
                refreshed = target(*args, **kwargs)
            except Exception:
                return
            with lock:
                cache[key] = (refreshed, time.time())

        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            key = _make_key(args, kwargs)
            now = time.time()
            with lock:
                if key in cache:
                    value, ts = cache[key]
                    age = now - ts
                    if age < ttl * 0.8:
                        # 新鲜：直接返回缓存值
                        return value
                    if age < ttl:
                        # 即将过期：返回旧值并后台刷新
                        thread = threading.Thread(
                            target=_refresh,
                            args=(func, key, args, kwargs),
                            daemon=True,
                        )
                        thread.start()
                        return value
                    # 已过期：视为未命中，重新计算
            # 缓存未命中或已过期：在锁外执行实际函数
            value = func(*args, **kwargs)
            with lock:
                cache[key] = (value, time.time())
                if len(cache) > maxsize:
                    # 超容量时淘汰最早插入的项
                    cache.pop(next(iter(cache)))
            return value

        def cache_peek(key: str) -> Any:
            """查看缓存值但不影响 LRU 顺序（TTL 版无 LRU 概念，仅原样返回）。"""
            with lock:
                if key in cache:
                    return cache[key][0]
            return None

        def cache_clear() -> None:
            """清空所有缓存。"""
            with lock:
                cache.clear()

        def cache_size() -> int:
            """返回缓存项数量。"""
            with lock:
                return len(cache)

        def cache_delete(key: str) -> None:
            """删除指定 key。"""
            with lock:
                cache.pop(key, None)

        def cache_get(key: str) -> Any:
            """直接获取缓存值（不调用函数）；过期返回 None。"""
            with lock:
                if key in cache:
                    value, ts = cache[key]
                    if time.time() - ts < ttl:
                        return value
            return None

        def cache_has(key: str) -> bool:
            """判断 key 是否在缓存中且未过期。"""
            with lock:
                if key in cache:
                    _, ts = cache[key]
                    return time.time() - ts < ttl
            return False

        wrapper.cache_peek = cache_peek  # type: ignore[attr-defined]
        wrapper.cache_clear = cache_clear  # type: ignore[attr-defined]
        wrapper.cache_size = cache_size  # type: ignore[attr-defined]
        wrapper.cache_delete = cache_delete  # type: ignore[attr-defined]
        wrapper.cache_get = cache_get  # type: ignore[attr-defined]
        wrapper.cache_has = cache_has  # type: ignore[attr-defined]
        return wrapper

    return decorator


def memoize_with_lru(maxsize: int = 100) -> Callable:
    """
    LRU 缓存装饰器。

    参数:
        maxsize: 最大缓存项数量，超过时淘汰最久未访问的项

    命中时移动到末尾（最近使用）；超容量时弹出头部（最久未使用）。
    """
    cache: OrderedDict = OrderedDict()
    lock = threading.Lock()

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            key = _make_key(args, kwargs)
            with lock:
                if key in cache:
                    # 命中：移动到末尾（最近使用）并返回
                    cache.move_to_end(key)
                    return cache[key]
            # 未命中：在锁外执行实际函数
            value = func(*args, **kwargs)
            with lock:
                cache[key] = value
                cache.move_to_end(key)
                if len(cache) > maxsize:
                    # 超容量：弹出头部（最久未使用）
                    cache.popitem(last=False)
            return value

        def cache_peek(key: str) -> Any:
            """查看缓存值但不影响 LRU 顺序。"""
            with lock:
                if key in cache:
                    return cache[key]
            return None

        def cache_clear() -> None:
            """清空所有缓存。"""
            with lock:
                cache.clear()

        def cache_size() -> int:
            """返回缓存项数量。"""
            with lock:
                return len(cache)

        def cache_delete(key: str) -> None:
            """删除指定 key。"""
            with lock:
                cache.pop(key, None)

        def cache_get(key: str) -> Any:
            """直接获取缓存值（不调用函数），并标记为最近使用。"""
            with lock:
                if key in cache:
                    cache.move_to_end(key)
                    return cache[key]
            return None

        def cache_set(key: str, value: Any) -> None:
            """直接写入缓存值（不调用函数），并标记为最近使用。"""
            with lock:
                cache[key] = value
                cache.move_to_end(key)
                if len(cache) > maxsize:
                    # 超容量：弹出头部（最久未使用）
                    cache.popitem(last=False)

        def cache_has(key: str) -> bool:
            """判断 key 是否在缓存中。"""
            with lock:
                return key in cache

        wrapper.cache_peek = cache_peek  # type: ignore[attr-defined]
        wrapper.cache_clear = cache_clear  # type: ignore[attr-defined]
        wrapper.cache_size = cache_size  # type: ignore[attr-defined]
        wrapper.cache_delete = cache_delete  # type: ignore[attr-defined]
        wrapper.cache_get = cache_get  # type: ignore[attr-defined]
        wrapper.cache_set = cache_set  # type: ignore[attr-defined]
        wrapper.cache_has = cache_has  # type: ignore[attr-defined]
        return wrapper

    return decorator


def memoize_with_ttl_async(ttl: float = 60.0) -> Callable:
    """
    异步 TTL 缓存装饰器（in_flight 去重）。

    参数:
        ttl: 缓存生存时间（秒）

    使用 in_flight 映射去重并发请求：当多个协程同时请求同一 key 时，
    只有第一个执行实际函数，其他等待 asyncio.Future 结果。
    使用 asyncio.Lock 保证协程安全。
    """
    cache: dict = {}
    in_flight: dict = {}
    lock = asyncio.Lock()

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            key = _make_key(args, kwargs)
            need_compute = False
            future: Optional[asyncio.Future] = None
            async with lock:
                if key in cache:
                    value, ts = cache[key]
                    if time.time() - ts < ttl:
                        # 缓存命中且未过期
                        return value
                if key in in_flight:
                    # 已有协程在计算：等待其 Future 结果
                    future = in_flight[key]
                    need_compute = False
                else:
                    # 第一个请求：创建 Future 并负责计算
                    loop = asyncio.get_running_loop()
                    future = loop.create_future()
                    in_flight[key] = future
                    need_compute = True
            if not need_compute:
                # 等待其他协程的计算结果
                return await future
            # 执行实际函数
            try:
                value = await func(*args, **kwargs)
            except BaseException as exc:
                # 计算失败：清理 in_flight 并传播异常
                async with lock:
                    in_flight.pop(key, None)
                if not future.done():
                    future.set_exception(exc)
                raise
            # 计算成功：写入缓存并通知等待者
            async with lock:
                cache[key] = (value, time.time())
                in_flight.pop(key, None)
            if not future.done():
                future.set_result(value)
            return value

        def cache_peek(key: str) -> Any:
            """查看缓存值但不影响 LRU 顺序（异步版无 LRU 概念，仅原样返回）。"""
            if key in cache:
                return cache[key][0]
            return None

        def cache_clear() -> None:
            """清空所有缓存。"""
            cache.clear()
            in_flight.clear()

        def cache_size() -> int:
            """返回缓存项数量。"""
            return len(cache)

        def cache_delete(key: str) -> None:
            """删除指定 key。"""
            cache.pop(key, None)

        def cache_get(key: str) -> Any:
            """直接获取缓存值（不调用函数）；过期返回 None。"""
            if key in cache:
                value, ts = cache[key]
                if time.time() - ts < ttl:
                    return value
            return None

        def cache_has(key: str) -> bool:
            """判断 key 是否在缓存中且未过期。"""
            if key in cache:
                _, ts = cache[key]
                return time.time() - ts < ttl
            return False

        wrapper.cache_peek = cache_peek  # type: ignore[attr-defined]
        wrapper.cache_clear = cache_clear  # type: ignore[attr-defined]
        wrapper.cache_size = cache_size  # type: ignore[attr-defined]
        wrapper.cache_delete = cache_delete  # type: ignore[attr-defined]
        wrapper.cache_get = cache_get  # type: ignore[attr-defined]
        wrapper.cache_has = cache_has  # type: ignore[attr-defined]
        return wrapper

    return decorator
