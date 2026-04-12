import inspect
from collections import deque

import pytest

from api.routes import auth
from mcp.manager import MCPManager


@pytest.fixture(autouse=True)
def reset_login_rate_limit_state():
    """每个用例前后重置限流状态，避免全局字典互相污染。"""
    with auth._LOGIN_RATE_LIMIT_LOCK:
        auth._LOGIN_ATTEMPTS.clear()
        auth._LOGIN_BLOCKED_UNTIL.clear()
        auth._LOGIN_LAST_CLEANUP_AT = 0.0

    yield

    with auth._LOGIN_RATE_LIMIT_LOCK:
        auth._LOGIN_ATTEMPTS.clear()
        auth._LOGIN_BLOCKED_UNTIL.clear()
        auth._LOGIN_LAST_CLEANUP_AT = 0.0


def test_get_retry_after_seconds_cleans_stale_rate_limit_state(monkeypatch):
    """触发检查时应清理过期封禁和空失败记录，避免全局字典无限增长。"""
    stale_key = "192.168.0.1|stale"
    fresh_key = "192.168.0.2|fresh"
    now = (
        auth._LOGIN_BLOCK_SECONDS
        + auth._LOGIN_ATTEMPT_WINDOW_SECONDS
        + auth._LOGIN_CLEANUP_INTERVAL_SECONDS
        + 10
    )

    with auth._LOGIN_RATE_LIMIT_LOCK:
        auth._LOGIN_ATTEMPTS[stale_key] = deque([0.0])
        auth._LOGIN_BLOCKED_UNTIL[stale_key] = auth._LOGIN_BLOCK_SECONDS / 2

    monkeypatch.setattr(auth.time, "monotonic", lambda: now)

    assert auth._get_retry_after_seconds(fresh_key) == 0
    assert stale_key not in auth._LOGIN_ATTEMPTS
    assert stale_key not in auth._LOGIN_BLOCKED_UNTIL
    assert fresh_key not in auth._LOGIN_ATTEMPTS


def test_get_retry_after_seconds_reports_remaining_block_window(monkeypatch):
    """已封禁状态下应返回剩余秒数，并向上取整避免少报 1 秒。"""
    blocked_key = "192.168.0.3|blocked"
    now = 100.8

    with auth._LOGIN_RATE_LIMIT_LOCK:
        auth._LOGIN_BLOCKED_UNTIL[blocked_key] = now + 899.4

    monkeypatch.setattr(auth.time, "monotonic", lambda: now)

    assert auth._get_retry_after_seconds(blocked_key) == 900


def test_mcp_manager_singleton_init_is_guarded_by_class_lock():
    """回归约束：创建实例与首次初始化都应受同一类级锁保护。"""
    assert MCPManager() is MCPManager()

    new_source = inspect.getsource(MCPManager.__new__)
    init_source = inspect.getsource(MCPManager.__init__)
    class_source = inspect.getsource(MCPManager)

    assert "threading.RLock()" in class_source
    assert new_source.count("if cls._instance is None") >= 2
    assert "with type(self)._instance_lock:" in init_source
