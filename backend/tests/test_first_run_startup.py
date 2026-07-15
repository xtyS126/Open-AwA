"""首次部署启动契约回归测试。"""

from contextlib import contextmanager
from types import SimpleNamespace

import pytest

import core.initialization as initialization_module
import main


class _Profiler:
    """提供启动步骤上下文的最小测试替身。"""

    @contextmanager
    def step(self, _name: str):
        yield


@pytest.mark.asyncio
async def test_uninitialized_startup_does_not_create_fallback_owner(monkeypatch):
    """未初始化启动必须保留空用户表，允许首次部署端点创建 owner。"""
    monkeypatch.setattr(initialization_module, "is_initialized", lambda: False)
    monkeypatch.setattr(main, "_detect_and_log_initialization_status", lambda: None)

    await main._startup_owner_user_init(_Profiler())


@pytest.mark.asyncio
async def test_initialized_startup_ensures_owner_and_admin_role(monkeypatch):
    """已初始化启动继续执行既有 owner 与 RBAC 修复逻辑。"""
    owner = SimpleNamespace(id="owner-id", username="owner")
    calls: list[tuple[str, str]] = []

    def close_db() -> None:
        calls.append(("db", "closed"))

    db = SimpleNamespace(close=close_db)

    async def set_user_role(user_id: str, role: str) -> None:
        calls.append((user_id, role))

    class FakeRBACManager:
        def __init__(self, _db):
            self.set_user_role = set_user_role

    monkeypatch.setattr(initialization_module, "is_initialized", lambda: True)
    monkeypatch.setattr(main, "_detect_and_log_initialization_status", lambda: None)
    monkeypatch.setattr("core.owner.ensure_owner_user", lambda _db: owner)
    monkeypatch.setattr("db.models.SessionLocal", lambda: db)
    monkeypatch.setattr("security.rbac.RBACManager", FakeRBACManager)

    await main._startup_owner_user_init(_Profiler())

    assert calls == [("owner-id", "admin"), ("db", "closed")]
