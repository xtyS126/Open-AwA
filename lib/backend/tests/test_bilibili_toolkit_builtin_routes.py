"""bilibili-toolkit-builtin 内置插件 API 路由层 403 保护测试。

覆盖三个核心场景：
1. 内置插件不可卸载：DELETE /api/plugins/{id} 在 is_uninstallable=True 时返回 403
2. 内置插件不可禁用：PUT /api/plugins/{id}/toggle 在 is_uninstallable=True 时返回 403
3. 内置插件 403 响应应记录审计日志，便于安全审计追溯
4. 普通插件（is_uninstallable=False）不受 403 保护，可正常卸载

测试隔离：
- 使用 in-memory SQLite 与 StaticPool 保证测试间互不干扰
- 通过 dependency_overrides 替换 get_db 与 get_current_admin_user
- PluginManager.delete 等运行时方法全部 mock，避免触发真实文件系统操作
"""

from __future__ import annotations

import os
import sys
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# 将 backend 目录加入 sys.path
_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

# bug 已修复：_migrate_plugin_columns 已补齐 is_uninstallable 列迁移逻辑
# 此处不再设置 SKIP_INIT_DB=true，验证 startup 完整流程能正常执行 schema 迁移
# 若测试因其他 startup 依赖失败，可临时恢复 os.environ.setdefault("SKIP_INIT_DB", "true")

from api.dependencies import get_current_admin_user, get_db  # noqa: E402
from db.models import AuditLog, Base, Plugin  # noqa: E402
from main import app  # noqa: E402
from plugins import plugin_instance  # noqa: E402


# ---------------------------------------------------------------------------
# 测试数据库与依赖注入覆盖
# ---------------------------------------------------------------------------

# 全局 in-memory SQLite 引擎，所有连接共享同一数据库（StaticPool）
_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)
Base.metadata.create_all(bind=_engine)


def _override_get_db():
    """提供独立测试数据库会话，确保事务在请求结束后关闭。"""
    db = _TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


class _DummyAdminUser:
    """模拟已认证的管理员用户，满足路由依赖的最小字段集。"""

    id = "admin-001"
    username = "admin"
    role = "admin"


def _override_get_current_admin_user() -> _DummyAdminUser:
    """返回固定管理员用户，绕过真实认证流程。"""
    return _DummyAdminUser()


@contextmanager
def _test_client() -> Iterator[TestClient]:
    """注入依赖覆盖并构造 TestClient，确保用例间隔离。"""
    previous_overrides = dict(app.dependency_overrides)
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_admin_user] = _override_get_current_admin_user
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides = previous_overrides


# ---------------------------------------------------------------------------
# fixture：数据库清理与插件记录准备
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_plugins_table():
    """每个用例运行前后清理插件表与审计日志表，保证用例间互不干扰。"""
    db = _TestingSessionLocal()
    try:
        db.query(Plugin).delete()
        db.query(AuditLog).delete()
        db.commit()
    finally:
        db.close()
    yield
    db = _TestingSessionLocal()
    try:
        db.query(Plugin).delete()
        db.query(AuditLog).delete()
        db.commit()
    finally:
        db.close()


def _seed_plugin(
    name: str,
    *,
    is_uninstallable: bool = False,
    source: str = "user",
    enabled: bool = True,
) -> str:
    """在测试数据库中插入一条插件记录，返回其 ID。"""
    plugin_id = str(uuid.uuid4())
    db = _TestingSessionLocal()
    try:
        plugin = Plugin(
            id=plugin_id,
            name=name,
            version="1.0.0",
            enabled=enabled,
            config={},
            category="general",
            author="tester",
            source=source,
            dependencies=[],
            is_uninstallable=is_uninstallable,
        )
        db.add(plugin)
        db.commit()
    finally:
        db.close()
    return plugin_id


def _mock_plugin_manager_loaded(plugin_name: str, loaded: bool = False) -> MagicMock:
    """构造一个 mock PluginManager，避免触发真实文件系统与运行时加载。"""
    pm = MagicMock()
    pm.loaded_plugins = set()
    if loaded:
        pm.loaded_plugins.add(plugin_name)
    pm.unload_plugin = MagicMock(return_value=True)
    pm.load_plugin = MagicMock(return_value=True)
    pm.discover_plugins = MagicMock(return_value=[])
    pm.plugin_metadata = {}
    pm.plugins_dir = "/tmp/test_plugins"
    return pm


# ---------------------------------------------------------------------------
# 403 保护测试
# ---------------------------------------------------------------------------


def test_delete_builtin_plugin_returns_403(monkeypatch):
    """DELETE 内置插件应返回 403，且响应包含"内置插件不可卸载"。"""
    plugin_id = _seed_plugin(
        "bilibili-toolkit-builtin", is_uninstallable=True, source="builtin"
    )
    monkeypatch.setattr(plugin_instance, "get", lambda: _mock_plugin_manager_loaded("bilibili-toolkit-builtin"))

    with _test_client() as client:
        response = client.delete(f"/api/plugins/{plugin_id}")

    assert response.status_code == 403
    assert "内置插件不可卸载" in response.text


def test_disable_builtin_plugin_returns_403(monkeypatch):
    """PUT toggle 内置插件应返回 403，禁止启用/禁用切换。"""
    plugin_id = _seed_plugin(
        "bilibili-toolkit-builtin", is_uninstallable=True, source="builtin"
    )
    monkeypatch.setattr(plugin_instance, "get", lambda: _mock_plugin_manager_loaded("bilibili-toolkit-builtin"))

    with _test_client() as client:
        response = client.put(f"/api/plugins/{plugin_id}/toggle")

    assert response.status_code == 403
    assert "内置插件不可卸载" in response.text


def test_audit_log_recorded_on_forbidden_delete(monkeypatch):
    """DELETE 内置插件被 403 拦截后，应写入 result=blocked 的审计日志。"""
    plugin_id = _seed_plugin(
        "bilibili-toolkit-builtin", is_uninstallable=True, source="builtin"
    )
    monkeypatch.setattr(plugin_instance, "get", lambda: _mock_plugin_manager_loaded("bilibili-toolkit-builtin"))

    with _test_client() as client:
        client.delete(f"/api/plugins/{plugin_id}")

    # 验证审计日志已记录
    db = _TestingSessionLocal()
    try:
        logs = db.query(AuditLog).filter(AuditLog.action == "plugin:uninstall").all()
        assert len(logs) >= 1
        # 应记录被拦截的操作
        blocked_logs = [log for log in logs if log.result == "blocked"]
        assert len(blocked_logs) >= 1
        # 资源应为内置插件名
        assert blocked_logs[0].resource == "bilibili-toolkit-builtin"
    finally:
        db.close()


def test_audit_log_recorded_on_forbidden_toggle(monkeypatch):
    """PUT toggle 内置插件被 403 拦截后，应写入 result=blocked 的审计日志。"""
    plugin_id = _seed_plugin(
        "bilibili-toolkit-builtin", is_uninstallable=True, source="builtin"
    )
    monkeypatch.setattr(plugin_instance, "get", lambda: _mock_plugin_manager_loaded("bilibili-toolkit-builtin"))

    with _test_client() as client:
        client.put(f"/api/plugins/{plugin_id}/toggle")

    db = _TestingSessionLocal()
    try:
        logs = db.query(AuditLog).filter(AuditLog.action == "plugin:toggle").all()
        assert len(logs) >= 1
        blocked_logs = [log for log in logs if log.result == "blocked"]
        assert len(blocked_logs) >= 1
        assert blocked_logs[0].resource == "bilibili-toolkit-builtin"
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 普通插件不受影响测试
# ---------------------------------------------------------------------------


def test_delete_normal_plugin_succeeds(monkeypatch):
    """普通 source=user 插件（is_uninstallable=False）应可被成功删除。"""
    plugin_id = _seed_plugin("normal-demo-plugin", is_uninstallable=False, source="user")

    # mock PluginManager：插件未加载，unload 不会触发
    pm = _mock_plugin_manager_loaded("normal-demo-plugin", loaded=False)
    monkeypatch.setattr(plugin_instance, "get", lambda: pm)

    with _test_client() as client:
        response = client.delete(f"/api/plugins/{plugin_id}")

    assert response.status_code == 200
    assert "uninstalled" in response.json()["message"].lower()

    # 验证数据库中已无该插件记录
    db = _TestingSessionLocal()
    try:
        assert db.query(Plugin).filter(Plugin.id == plugin_id).first() is None
    finally:
        db.close()


def test_toggle_normal_plugin_succeeds(monkeypatch):
    """普通插件的 toggle 操作应正常切换 enabled 状态。"""
    plugin_id = _seed_plugin("normal-toggle-plugin", is_uninstallable=False, source="user", enabled=True)

    pm = _mock_plugin_manager_loaded("normal-toggle-plugin", loaded=False)
    # 切换到 disabled 时不需触发 unload（因 loaded=False）
    monkeypatch.setattr(plugin_instance, "get", lambda: pm)

    with _test_client() as client:
        response = client.put(f"/api/plugins/{plugin_id}/toggle")

    assert response.status_code == 200
    db = _TestingSessionLocal()
    try:
        plugin = db.query(Plugin).filter(Plugin.id == plugin_id).first()
        assert plugin is not None
        # enabled 应从 True 切换为 False
        assert plugin.enabled is False
    finally:
        db.close()


def test_delete_nonexistent_plugin_returns_404(monkeypatch):
    """删除不存在的插件 ID 应返回 404。"""
    monkeypatch.setattr(plugin_instance, "get", lambda: _mock_plugin_manager_loaded("nonexistent"))

    with _test_client() as client:
        response = client.delete("/api/plugins/nonexistent-id-404")

    assert response.status_code == 404
