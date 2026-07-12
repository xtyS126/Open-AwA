"""
POST /api/system/init 与 GET /api/system/init-status 端点单元测试。

覆盖：
- 请求体校验（用户名正则、密码强度）
- 异常映射（PrerequisiteError → 409, LockAcquireError → 409, BootstrapError → 500）
- 成功响应结构
- 初始化状态查询（含 DB 不可用降级）

测试隔离：mock bootstrap 与 initialization 模块的函数，不实际执行初始化
"""

from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

import core.bootstrap as bootstrap_module
import core.initialization as initialization_module
import api.routes.system as system_route
from core.bootstrap import (
    BootstrapError,
    LockAcquireError,
    MarkerWriteError,
    OwnerCreationError,
    PrerequisiteError,
)
from main import app


# ============================================================================
# 测试 fixture
# ============================================================================

@pytest.fixture
def client():
    """创建 TestClient，不触发 lifespan（直接发请求）。"""
    return TestClient(app)


@pytest.fixture
def mock_initialize_system(monkeypatch):
    """Mock bootstrap.initialize_system，返回默认成功结果。"""
    def default_result(**kwargs):
        return {
            "user_id": "test-uuid-1234",
            "username": kwargs.get("username", "alice"),
            "secrets_generated": True,
            "api_key_generated": True,
        }
    
    mock = MagicMock(side_effect=default_result)
    monkeypatch.setattr(bootstrap_module, "initialize_system", mock)
    return mock


@pytest.fixture
def mock_session_local(monkeypatch):
    """Mock api.routes.system.SessionLocal，返回支持 with 语句的伪会话。"""
    class _MockSession:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
    
    def _factory():
        return _MockSession()
    
    monkeypatch.setattr(system_route, "SessionLocal", _factory)
    return _factory


# ============================================================================
# POST /api/system/init 测试
# ============================================================================

class TestInitEndpoint:
    """测试 POST /api/system/init 端点。"""

    def test_returns_200_on_success(self, client, mock_initialize_system):
        """成功初始化返回 200。"""
        response = client.post("/api/system/init", json={
            "username": "alice",
            "password": "StrongPass1",
            "email": "alice@example.com",
            "nickname": "Alice",
        })

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"]["username"] == "alice"
        assert data["data"]["user_id"] == "test-uuid-1234"
        # 验证 mock 被正确调用
        mock_initialize_system.assert_called_once()
        call_kwargs = mock_initialize_system.call_args.kwargs
        assert call_kwargs["username"] == "alice"
        assert call_kwargs["password"] == "StrongPass1"

    def test_returns_422_for_weak_password_missing_uppercase(self, client, mock_initialize_system):
        """密码缺少大写字母返回 422。"""
        response = client.post("/api/system/init", json={
            "username": "alice",
            "password": "lowercase1",
        })

        assert response.status_code == 422
        data = response.json()
        # 路由返回结构化错误：{"success": False, "error": {"code": "weak_password", "message": "..."}}
        assert data["success"] is False
        assert data["error"]["code"] == "weak_password"
        assert "密码" in data["error"]["message"]
        # mock 不应被调用
        mock_initialize_system.assert_not_called()

    def test_returns_422_for_weak_password_missing_digit(self, client, mock_initialize_system):
        """密码缺少数字返回 422。"""
        response = client.post("/api/system/init", json={
            "username": "alice",
            "password": "StrongPassword",
        })

        assert response.status_code == 422
        mock_initialize_system.assert_not_called()

    def test_returns_422_for_short_password(self, client, mock_initialize_system):
        """密码少于 8 字符返回 422（Pydantic 校验）。"""
        response = client.post("/api/system/init", json={
            "username": "alice",
            "password": "Ab1",
        })

        assert response.status_code == 422
        mock_initialize_system.assert_not_called()

    def test_returns_422_for_invalid_username(self, client, mock_initialize_system):
        """用户名含非法字符返回 422（Pydantic 校验）。"""
        response = client.post("/api/system/init", json={
            "username": "alice@home",
            "password": "StrongPass1",
        })

        assert response.status_code == 422
        mock_initialize_system.assert_not_called()

    def test_returns_409_when_already_initialized(self, client, mock_initialize_system):
        """PrerequisiteError 映射为 409。"""
        mock_initialize_system.side_effect = PrerequisiteError("系统已初始化")

        response = client.post("/api/system/init", json={
            "username": "alice",
            "password": "StrongPass1",
        })

        assert response.status_code == 409
        data = response.json()
        assert data["success"] is False
        assert data["error"]["code"] == "prerequisite_failed"
        assert "系统已初始化" in data["error"]["message"]

    def test_returns_409_on_lock_contention(self, client, mock_initialize_system):
        """LockAcquireError 映射为 409。"""
        mock_initialize_system.side_effect = LockAcquireError("另一个初始化进程正在运行")

        response = client.post("/api/system/init", json={
            "username": "alice",
            "password": "StrongPass1",
        })

        assert response.status_code == 409
        data = response.json()
        assert data["success"] is False
        assert data["error"]["code"] == "init_lock_contention"
        assert "另一个初始化进程正在运行" in data["error"]["message"]

    def test_returns_500_on_bootstrap_error(self, client, mock_initialize_system):
        """其他 BootstrapError 子类映射为 500。"""
        mock_initialize_system.side_effect = OwnerCreationError("创建失败")

        response = client.post("/api/system/init", json={
            "username": "alice",
            "password": "StrongPass1",
        })

        assert response.status_code == 500
        data = response.json()
        assert data["success"] is False
        assert data["error"]["code"] == "OwnerCreationError"
        assert "创建失败" in data["error"]["message"]


# ============================================================================
# GET /api/system/init-status 测试
# ============================================================================

class TestInitStatusEndpoint:
    """测试 GET /api/system/init-status 端点。"""

    def test_returns_not_initialized_when_no_marker(self, client, mock_session_local, monkeypatch):
        """未初始化时返回 initialized=False。"""
        monkeypatch.setattr(
            initialization_module,
            "get_initialization_status",
            lambda: {
                "initialized": False,
                "initialized_at": None,
                "version": None,
                "steps_completed": [],
            },
        )
        monkeypatch.setattr(initialization_module, "has_any_user", lambda db: False)

        response = client.get("/api/system/init-status")

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["initialized"] is False
        assert data["initialized_at"] is None
        assert data["version"] is None
        assert data["steps_completed"] == []
        assert data["has_users"] is False

    def test_returns_initialized_when_marker_exists(self, client, mock_session_local, monkeypatch):
        """已初始化时返回 initialized=True 与完整结构。"""
        monkeypatch.setattr(
            initialization_module,
            "get_initialization_status",
            lambda: {
                "initialized": True,
                "initialized_at": "2026-07-12T08:30:00Z",
                "version": 1,
                "steps_completed": ["prerequisite_check", "generate_secrets"],
            },
        )
        monkeypatch.setattr(initialization_module, "has_any_user", lambda db: True)

        response = client.get("/api/system/init-status")

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["initialized"] is True
        assert data["initialized_at"] == "2026-07-12T08:30:00Z"
        assert data["version"] == 1
        assert "prerequisite_check" in data["steps_completed"]
        assert data["has_users"] is True

    def test_includes_db_error_when_session_unavailable(self, client, monkeypatch):
        """DB 不可用时 has_users 为 None，含 db_error 字段。"""
        monkeypatch.setattr(
            initialization_module,
            "get_initialization_status",
            lambda: {
                "initialized": False,
                "initialized_at": None,
                "version": None,
                "steps_completed": [],
            },
        )
        # 让 SessionLocal() 抛异常
        def broken_session_factory():
            raise RuntimeError("DB connection failed")
        monkeypatch.setattr(system_route, "SessionLocal", broken_session_factory)

        response = client.get("/api/system/init-status")

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["initialized"] is False
        assert data["has_users"] is None
        assert data["db_error"] == "database_unavailable"
