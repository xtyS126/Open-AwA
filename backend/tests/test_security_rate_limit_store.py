"""
security/rate_limit_store.py 单元测试。
覆盖 MemoryRateLimitStore 和 DatabaseRateLimitStore 的限流行为。
测试滑动窗口、封禁/解封、成功清理和工厂函数。
"""

import time

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.models import Base
from security.rate_limit_store import (
    DatabaseRateLimitStore,
    MemoryRateLimitStore,
    RateLimitStore,
    init_rate_limit_store,
    get_rate_limit_store,
    LOGIN_BLOCK_SECONDS,
    LOGIN_MAX_ATTEMPTS,
)


# ==================== 公共测试夹具 ====================

@pytest.fixture
def memory_store():
    """创建干净的 MemoryRateLimitStore 实例"""
    return MemoryRateLimitStore()


@pytest.fixture
def db_session_factory(tmp_path):
    """创建临时 SQLite 数据库会话工厂"""
    db_path = tmp_path / "test_rate_limit.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    return Session


@pytest.fixture
def db_store(db_session_factory):
    """创建 DatabaseRateLimitStore 实例"""
    return DatabaseRateLimitStore(db_session_factory)


# 参数化 fixture：对两种后端运行同一套测试
@pytest.fixture(params=["memory", "database"])
def store(request, memory_store, db_store):
    """返回两种后端的 store 实例，确保行为一致"""
    if request.param == "memory":
        return memory_store
    return db_store


# ==================== 公共行为测试（两种后端共同验证） ====================

class TestRateLimitCommonBehavior:
    """两种后端共享的限流行为测试"""

    def test_initial_state_allows_login(self, store: RateLimitStore):
        """初始状态下应允许登录（retry_after = 0）"""
        assert store.get_retry_after_seconds("new_key") == 0

    def test_single_failure_does_not_block(self, store: RateLimitStore):
        """单次失败不应触发封禁"""
        store.record_failed_attempt("key1")
        assert store.get_retry_after_seconds("key1") == 0

    def test_max_attempts_minus_one_does_not_block(self, store: RateLimitStore):
        """N-1 次失败不应触发封禁"""
        key = "key_edge"
        for _ in range(LOGIN_MAX_ATTEMPTS - 1):
            store.record_failed_attempt(key)
        assert store.get_retry_after_seconds(key) == 0

    def test_max_attempts_triggers_block(self, store: RateLimitStore):
        """达到最大失败次数应触发封禁（retry_after > 0）"""
        key = "key_block"
        for _ in range(LOGIN_MAX_ATTEMPTS):
            store.record_failed_attempt(key)
        retry_after = store.get_retry_after_seconds(key)
        assert retry_after > 0
        # 封禁时间应接近 LOGIN_BLOCK_SECONDS（向上取整）
        assert retry_after <= LOGIN_BLOCK_SECONDS + 1

    def test_blocked_key_returns_retry_after(self, store: RateLimitStore):
        """已被封禁的 key 再次检查仍返回 retry_after > 0"""
        key = "key_blocked_twice"
        for _ in range(LOGIN_MAX_ATTEMPTS):
            store.record_failed_attempt(key)
        first = store.get_retry_after_seconds(key)
        second = store.get_retry_after_seconds(key)
        assert first > 0
        assert second > 0

    def test_clear_attempts_removes_block(self, store: RateLimitStore):
        """登录成功后清理应移除封禁状态"""
        key = "key_clear"
        for _ in range(LOGIN_MAX_ATTEMPTS):
            store.record_failed_attempt(key)
        # 确认已封禁
        assert store.get_retry_after_seconds(key) > 0
        # 清理后应解封
        store.clear_attempts(key)
        assert store.get_retry_after_seconds(key) == 0

    def test_clear_before_block_works(self, store: RateLimitStore):
        """未触发封禁时清理也应正常工作"""
        key = "key_early_clear"
        store.record_failed_attempt(key)
        store.record_failed_attempt(key)
        store.clear_attempts(key)
        assert store.get_retry_after_seconds(key) == 0

    def test_different_keys_independent(self, store: RateLimitStore):
        """不同 key 的限流状态互相独立"""
        key_a = "192.168.1.1|user_a"
        key_b = "192.168.1.2|user_b"

        # key_b 触发封禁
        for _ in range(LOGIN_MAX_ATTEMPTS):
            store.record_failed_attempt(key_b)

        # key_a 应不受影响
        assert store.get_retry_after_seconds(key_a) == 0
        assert store.get_retry_after_seconds(key_b) > 0

    def test_record_after_block_does_not_crash(self, store: RateLimitStore):
        """已封禁后继续记录失败不应崩溃"""
        key = "key_post_block"
        for _ in range(LOGIN_MAX_ATTEMPTS):
            store.record_failed_attempt(key)
        # 确认封禁状态
        store.get_retry_after_seconds(key)
        # 继续记录不应异常
        store.record_failed_attempt(key)
        store.record_failed_attempt(key)

    def test_empty_key_works(self, store: RateLimitStore):
        """空字符串 key 也可正常使用"""
        store.record_failed_attempt("")
        assert store.get_retry_after_seconds("") == 0


# ==================== MemoryRateLimitStore 专属测试 ====================

class TestMemoryRateLimitStoreSpecific:
    """MemoryRateLimitStore 特有的容量保护和清理行为测试"""

    def test_capacity_protection_prevents_unlimited_growth(self, monkeypatch):
        """容量达到上限后应拒绝记录，不会无限增长"""
        from security.rate_limit_store import LOGIN_STATE_MAX_CAPACITY

        store = MemoryRateLimitStore()
        now = 1000.0
        monkeypatch.setattr(time, "monotonic", lambda: now)

        # 填满容量上限
        for i in range(LOGIN_STATE_MAX_CAPACITY):
            store.record_failed_attempt(f"key_{i}")

        # 再尝试记录溢出 key — 应被拒绝
        store.record_failed_attempt("overflow_key")
        # 验证溢出记录未被接受（容量保护生效）
        assert "overflow_key" not in store._attempts
        total = len(store._attempts) + len(store._blocked_until)
        assert total <= LOGIN_STATE_MAX_CAPACITY

    def test_cleanup_removes_expired_blocked_entries(self, monkeypatch):
        """定期清理应移除已过期的封禁记录"""
        store = MemoryRateLimitStore()
        base_time = 1000.0
        monkeypatch.setattr(time, "monotonic", lambda: base_time)

        key = "key_expired_block"
        for _ in range(LOGIN_MAX_ATTEMPTS):
            store.record_failed_attempt(key)
        assert store.get_retry_after_seconds(key) > 0

        # 时间推进到封禁过期后
        future = base_time + LOGIN_BLOCK_SECONDS + 120
        monkeypatch.setattr(time, "monotonic", lambda: future)

        # 触发检查（用新 key 触发清理逻辑）
        assert store.get_retry_after_seconds("another_key") == 0
        # 旧 key 应已解封
        assert key not in store._blocked_until

    def test_prune_removes_window_expired_attempts(self, monkeypatch):
        """窗口外的旧尝试记录应被剪枝"""
        from security.rate_limit_store import LOGIN_ATTEMPT_WINDOW_SECONDS

        store = MemoryRateLimitStore()
        base_time = 1000.0
        monkeypatch.setattr(time, "monotonic", lambda: base_time)

        store.record_failed_attempt("key_prune")

        # 时间推进到窗口外
        future = base_time + LOGIN_ATTEMPT_WINDOW_SECONDS + 10
        monkeypatch.setattr(time, "monotonic", lambda: future)

        assert store.get_retry_after_seconds("key_prune") == 0


# ==================== DatabaseRateLimitStore 专属测试 ====================

class TestDatabaseRateLimitStoreSpecific:
    """DatabaseRateLimitStore 的特有行为测试"""

    def test_persistence_across_instances(self, db_session_factory):
        """限流状态应持久化，不同实例共享状态"""
        store1 = DatabaseRateLimitStore(db_session_factory)
        store2 = DatabaseRateLimitStore(db_session_factory)

        key = "key_persist"
        # store1 记录失败
        for _ in range(LOGIN_MAX_ATTEMPTS):
            store1.record_failed_attempt(key)

        # store2 应能读到封禁状态
        assert store2.get_retry_after_seconds(key) > 0

        # store2 清理
        store2.clear_attempts(key)
        # store1 也应看到清理结果
        assert store1.get_retry_after_seconds(key) == 0

    def test_multiple_keys_isolation_in_db(self, db_session_factory):
        """数据库中不同 key 互相隔离"""
        store = DatabaseRateLimitStore(db_session_factory)

        key_a = "10.0.0.1|alice"
        key_b = "10.0.0.2|bob"

        # key_a 触发封禁
        for _ in range(LOGIN_MAX_ATTEMPTS):
            store.record_failed_attempt(key_a)

        # key_b 应不受影响
        assert store.get_retry_after_seconds(key_a) > 0
        assert store.get_retry_after_seconds(key_b) == 0


# ==================== 工厂函数测试 ====================

class TestRateLimitStoreFactory:
    """测试 init_rate_limit_store 工厂函数"""

    def test_init_memory_store(self, monkeypatch):
        """初始化 memory 后端"""
        # 重置全局状态
        import security.rate_limit_store as rls
        monkeypatch.setattr(rls, "_rate_limit_store", None)

        store = init_rate_limit_store(backend="memory")
        assert isinstance(store, MemoryRateLimitStore)
        assert get_rate_limit_store() is store

    def test_init_database_store(self, db_session_factory, monkeypatch):
        """初始化 database 后端"""
        import security.rate_limit_store as rls
        monkeypatch.setattr(rls, "_rate_limit_store", None)

        store = init_rate_limit_store(
            backend="database",
            db_session_factory=db_session_factory,
        )
        assert isinstance(store, DatabaseRateLimitStore)
        assert get_rate_limit_store() is store

    def test_init_unknown_backend_raises(self, monkeypatch):
        """不支持的 backend 值应抛出 ValueError"""
        import security.rate_limit_store as rls
        monkeypatch.setattr(rls, "_rate_limit_store", None)

        with pytest.raises(ValueError, match="不支持的 RATE_LIMIT_BACKEND"):
            init_rate_limit_store(backend="redis")

    def test_init_database_without_factory_raises(self, monkeypatch):
        """database 后端缺少 db_session_factory 应抛出 ValueError"""
        import security.rate_limit_store as rls
        monkeypatch.setattr(rls, "_rate_limit_store", None)

        with pytest.raises(ValueError, match="database 后端需要提供"):
            init_rate_limit_store(backend="database", db_session_factory=None)

    def test_get_rate_limit_store_before_init_raises(self, monkeypatch):
        """未初始化时调用 get_rate_limit_store 应抛出 RuntimeError"""
        import security.rate_limit_store as rls
        monkeypatch.setattr(rls, "_rate_limit_store", None)

        with pytest.raises(RuntimeError, match="尚未初始化"):
            get_rate_limit_store()
