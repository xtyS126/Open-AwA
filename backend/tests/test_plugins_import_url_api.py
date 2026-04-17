"""
验证插件远程 URL 导入接口的核心行为。
"""

import sys
from contextlib import contextmanager
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.dependencies import get_current_admin_user, get_db
from db.models import Base, Plugin
from main import app
from plugins.plugin_manager import PluginManager


engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base.metadata.create_all(bind=engine)


def override_get_db():
    """提供独立测试数据库会话。"""
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


def override_get_current_admin_user():
    """提供固定管理员用户。"""

    class DummyUser:
        id = "admin-1"
        username = "admin"
        role = "admin"

    return DummyUser()


@contextmanager
def _test_client():
    """注入依赖覆盖，隔离本测试模块。"""
    previous_overrides = dict(app.dependency_overrides)
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_admin_user] = override_get_current_admin_user
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides = previous_overrides


def _clear_plugins_table() -> None:
    """清理插件表，确保用例互不干扰。"""
    db = TestingSessionLocal()
    try:
        db.query(Plugin).delete()
        db.commit()
    finally:
        db.close()


def setup_function():
    """每个用例前清理数据。"""
    _clear_plugins_table()


def teardown_function():
    """每个用例后清理数据。"""
    _clear_plugins_table()


def test_import_plugin_from_url_persists_plugin(monkeypatch):
    """远程导入成功时应写入数据库并返回导入摘要。"""

    def fake_register_plugin_from_url(self, source_url: str, timeout: int = 30):
        assert source_url == "https://github.com/example/plugin.zip"
        assert timeout == 20
        return [
            {
                "name": "remote_demo",
                "version": "1.2.3",
                "description": "remote plugin",
                "manifest": {
                    "author": "alice",
                    "dependencies": {
                        "requests": "^2.0.0",
                    },
                },
            }
        ]

    monkeypatch.setattr(PluginManager, "register_plugin_from_url", fake_register_plugin_from_url)

    with _test_client() as client:
        response = client.post(
            "/api/plugins/import-url",
            json={
                "source_url": "https://github.com/example/plugin.zip",
                "timeout_seconds": 20,
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["installed_count"] == 1
    assert data["updated_count"] == 0
    assert data["plugins"] == ["remote_demo"]

    db = TestingSessionLocal()
    try:
        plugin = db.query(Plugin).filter(Plugin.name == "remote_demo").first()
        assert plugin is not None
        assert plugin.version == "1.2.3"
        assert plugin.source == "remote_url"
        assert plugin.author == "alice"
        assert plugin.dependencies == ["requests"]
    finally:
        db.close()


def test_import_plugin_from_url_returns_400_when_manager_rejects(monkeypatch):
    """远程导入被安全校验拒绝时应返回 400。"""

    def fake_register_plugin_from_url(self, source_url: str, timeout: int = 30):
        raise ValueError("域名不在白名单中")

    monkeypatch.setattr(PluginManager, "register_plugin_from_url", fake_register_plugin_from_url)

    with _test_client() as client:
        response = client.post(
            "/api/plugins/import-url",
            json={"source_url": "https://invalid.example.com/plugin.zip"},
        )

    assert response.status_code == 400
    assert "域名不在白名单中" in response.text
