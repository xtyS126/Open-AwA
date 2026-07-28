"""
密码验证结果缓存模块。

为 Bearer 密码凭证认证提供短 TTL 的内存缓存，避免每个请求都执行
bcrypt 哈希验证（rounds=12，单次约 200-400ms）。

设计要点：
- 缓存 key 为 sha256(password) 的十六进制字符串，不存储明文密码
- 缓存 value 为 (user_id, expire_at) 元组，过期自动失效
- 使用 threading.Lock 保护，因为 bcrypt 验证会通过 asyncio.to_thread
  调用到线程池，缓存读写必须线程安全
- TTL 默认 5 分钟（300 秒），降低密码变更后旧缓存残留风险
- 密码修改时调用 clear() 立即清空所有缓存
"""

import hashlib
import threading
import time
from typing import Dict, Optional, Tuple


class PasswordVerificationCache:
    """
    密码验证结果缓存，线程安全。

    缓存结构：Dict[sha256_hex, (user_id, expire_at_timestamp)]
    """

    def __init__(self) -> None:
        # 内部缓存字典：key=sha256(password) hex，value=(user_id, expire_at)
        self._cache: Dict[str, Tuple[str, float]] = {}
        # 保护 _cache 并发读写的锁
        self._lock = threading.Lock()

    @staticmethod
    def _hash_password(password: str) -> str:
        """
        将明文密码转为 sha256 十六进制摘要作为缓存 key。
        不存储明文密码，降低内存泄露风险。
        """
        return hashlib.sha256(password.encode("utf-8")).hexdigest()

    def get(self, password: str) -> Optional[str]:
        """
        查询缓存中未过期的 user_id。

        Args:
            password: 明文密码（与 set 时一致的输入）

        Returns:
            未过期的 user_id；不存在或已过期返回 None（过期条目会被清理）
        """
        if not password:
            return None

        cache_key = self._hash_password(password)
        now = time.monotonic()

        with self._lock:
            entry = self._cache.get(cache_key)
            if entry is None:
                return None

            user_id, expire_at = entry
            if expire_at <= now:
                # 过期条目惰性清理，避免后台线程
                self._cache.pop(cache_key, None)
                return None

            return user_id

    def set(self, password: str, user_id: str, ttl: int = 300) -> None:
        """
        写入缓存条目。

        Args:
            password: 明文密码
            user_id: 密码验证通过后对应的用户 ID
            ttl: 缓存有效期（秒），默认 300 秒（5 分钟）
        """
        if not password or not user_id:
            return

        cache_key = self._hash_password(password)
        expire_at = time.monotonic() + max(0, ttl)

        with self._lock:
            self._cache[cache_key] = (user_id, expire_at)

    def clear(self) -> None:
        """清空所有缓存条目（用于密码修改、用户登出等场景）。"""
        with self._lock:
            self._cache.clear()

    def __len__(self) -> int:
        """返回当前缓存条目数量（主要用于测试断言）。"""
        with self._lock:
            return len(self._cache)


# 模块级单例，供 dependencies.py 与 auth 路由复用
password_verification_cache = PasswordVerificationCache()
