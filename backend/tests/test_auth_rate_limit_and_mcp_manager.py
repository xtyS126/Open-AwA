"""
auth 登录限流覆盖测试 + MCP Manager 单例回归验证。
限流逻辑已迁移至 security/rate_limit_store.py，本测试通过 MemoryRateLimitStore 直接验证核心行为。
"""

import inspect
import time
from collections import deque

import pytest

from mcp.manager import MCPManager
from security.rate_limit_store import MemoryRateLimitStore


# ==================== 登录限流行为测试 ====================

class TestMemoryRateLimitStore:
    """测试 MemoryRateLimitStore 的核心行为（原 auth 模块级字典测试的等价覆盖）"""

    def test_get_retry_after_seconds_cleans_stale_state(self, monkeypatch):
        """触发检查时应清理过期封禁和空失败记录，避免全局字典无限增长。"""
        from security.rate_limit_store import (
            LOGIN_BLOCK_SECONDS,
            LOGIN_ATTEMPT_WINDOW_SECONDS,
            LOGIN_CLEANUP_INTERVAL_SECONDS,
        )

        store = MemoryRateLimitStore()
        stale_key = "192.168.0.1|stale"
        fresh_key = "192.168.0.2|fresh"
        now = (
            LOGIN_BLOCK_SECONDS
            + LOGIN_ATTEMPT_WINDOW_SECONDS
            + LOGIN_CLEANUP_INTERVAL_SECONDS
            + 10
        )

        # 通过测试辅助方法注入过期状态，避免直接操作私有属性
        store._test_inject_state(stale_key=stale_key, blocked_until=LOGIN_BLOCK_SECONDS / 2)

        monkeypatch.setattr(time, "monotonic", lambda: now)

        assert store.get_retry_after_seconds(fresh_key) == 0
        assert stale_key not in store._attempts
        assert stale_key not in store._blocked_until
        assert fresh_key not in store._attempts

    def test_get_retry_after_seconds_reports_remaining_block_window(self, monkeypatch):
        """已封禁状态下应返回剩余秒数，并向上取整避免少报 1 秒。"""
        store = MemoryRateLimitStore()
        blocked_key = "192.168.0.3|blocked"
        now = 100.8

        store._test_inject_state(stale_key=blocked_key, blocked_until=now + 899.4)

        monkeypatch.setattr(time, "monotonic", lambda: now)

        assert store.get_retry_after_seconds(blocked_key) == 900


# ==================== MCP Manager 单例回归测试 ====================

def test_mcp_manager_singleton_init_is_guarded_by_class_lock():
    """回归约束：创建实例与首次初始化都应受同一类级锁保护。"""
    assert MCPManager() is MCPManager()

    new_source = inspect.getsource(MCPManager.__new__)
    init_source = inspect.getsource(MCPManager.__init__)
    class_source = inspect.getsource(MCPManager)

    assert "threading.RLock()" in class_source
    assert new_source.count("if cls._instance is None") >= 2
    assert "with type(self)._instance_lock:" in init_source
