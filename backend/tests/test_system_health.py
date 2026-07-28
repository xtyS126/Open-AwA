"""
GET /api/system/health 端点单元测试。

覆盖：
- 所有检查项健康时返回 200 + status=healthy
- 数据库不可用时返回 503 + status=unhealthy
- 熔断器存在 open 项时返回 503 + status=unhealthy
- 向量库/ACP 不可用时返回 200 + status=degraded
- 检查项结构包含必要字段
- 端点无需认证即可访问
"""

from typing import Any, Dict
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from main import app


@pytest.fixture
def client():
    """创建 TestClient，不触发 lifespan。"""
    return TestClient(app)


def _make_db_status(ok: bool, latency_ms: float = 1.0) -> Dict[str, Any]:
    return {
        "ok": ok,
        "latency_ms": latency_ms,
        "error": None if ok else "database unavailable",
    }


def _make_vector_status(ok: bool) -> Dict[str, Any]:
    return {
        "ok": ok,
        "latency_ms": 1.0,
        "path": "/tmp/qdrant" if ok else None,
        "error": None if ok else "vector db path not writable",
    }


def _make_acp_status(ok: bool) -> Dict[str, Any]:
    return {
        "ok": ok,
        "available_agents": ["claude_code", "codex"] if ok else [],
        "agent_count": 2 if ok else 0,
        "error": None if ok else "acp module load failed",
    }


def _make_cb_status(ok: bool, open_count: int = 0, half_open_count: int = 0) -> Dict[str, Any]:
    return {
        "ok": ok,
        "breakers": {
            "llm_call": {
                "name": "llm_call",
                "state": "open" if open_count > 0 else "closed",
                "failure_count": open_count,
                "success_count": 0,
                "opened_at": 0,
                "half_open_calls": 0,
            }
        },
        "open_count": open_count,
        "half_open_count": half_open_count,
        "error": None,
    }


class TestHealthEndpoint:
    """GET /api/system/health 端点测试。"""

    def test_health_returns_200_when_all_healthy(self, client):
        """所有检查项健康时返回 200 与 status=healthy。"""
        with patch(
            "api.routes.system._check_database",
            return_value=_make_db_status(True),
        ), patch(
            "api.routes.system._check_vector_db",
            return_value=_make_vector_status(True),
        ), patch(
            "api.routes.system._check_acp_service",
            return_value=_make_acp_status(True),
        ), patch(
            "api.routes.system._check_circuit_breakers",
            return_value=_make_cb_status(True, open_count=0),
        ):
            response = client.get("/api/system/health")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "healthy"
        assert "timestamp" in body
        assert "checks" in body
        assert body["checks"]["database"]["ok"] is True
        assert body["checks"]["vector_db"]["ok"] is True
        assert body["checks"]["acp"]["ok"] is True
        assert body["checks"]["circuit_breakers"]["ok"] is True

    def test_health_returns_503_when_database_unavailable(self, client):
        """数据库不可用时返回 503 与 status=unhealthy。"""
        with patch(
            "api.routes.system._check_database",
            return_value=_make_db_status(False),
        ), patch(
            "api.routes.system._check_vector_db",
            return_value=_make_vector_status(True),
        ), patch(
            "api.routes.system._check_acp_service",
            return_value=_make_acp_status(True),
        ), patch(
            "api.routes.system._check_circuit_breakers",
            return_value=_make_cb_status(True, open_count=0),
        ):
            response = client.get("/api/system/health")

        assert response.status_code == 503
        body = response.json()
        assert body["status"] == "unhealthy"
        assert body["checks"]["database"]["ok"] is False
        assert body["checks"]["database"]["error"] == "database unavailable"

    def test_health_returns_503_when_circuit_breaker_open(self, client):
        """存在 open 状态熔断器时返回 503 与 status=unhealthy。"""
        with patch(
            "api.routes.system._check_database",
            return_value=_make_db_status(True),
        ), patch(
            "api.routes.system._check_vector_db",
            return_value=_make_vector_status(True),
        ), patch(
            "api.routes.system._check_acp_service",
            return_value=_make_acp_status(True),
        ), patch(
            "api.routes.system._check_circuit_breakers",
            return_value=_make_cb_status(False, open_count=1),
        ):
            response = client.get("/api/system/health")

        assert response.status_code == 503
        body = response.json()
        assert body["status"] == "unhealthy"
        assert body["checks"]["circuit_breakers"]["ok"] is False
        assert body["checks"]["circuit_breakers"]["open_count"] == 1

    def test_health_returns_200_degraded_when_vector_db_unavailable(self, client):
        """向量库不可用时返回 200 与 status=degraded（不阻断监控）。"""
        with patch(
            "api.routes.system._check_database",
            return_value=_make_db_status(True),
        ), patch(
            "api.routes.system._check_vector_db",
            return_value=_make_vector_status(False),
        ), patch(
            "api.routes.system._check_acp_service",
            return_value=_make_acp_status(True),
        ), patch(
            "api.routes.system._check_circuit_breakers",
            return_value=_make_cb_status(True, open_count=0),
        ):
            response = client.get("/api/system/health")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "degraded"
        assert body["checks"]["vector_db"]["ok"] is False

    def test_health_returns_200_degraded_when_acp_unavailable(self, client):
        """ACP 不可用时返回 200 与 status=degraded（可选依赖降级）。"""
        with patch(
            "api.routes.system._check_database",
            return_value=_make_db_status(True),
        ), patch(
            "api.routes.system._check_vector_db",
            return_value=_make_vector_status(True),
        ), patch(
            "api.routes.system._check_acp_service",
            return_value=_make_acp_status(False),
        ), patch(
            "api.routes.system._check_circuit_breakers",
            return_value=_make_cb_status(True, open_count=0),
        ):
            response = client.get("/api/system/health")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "degraded"
        assert body["checks"]["acp"]["ok"] is False

    def test_health_does_not_require_auth(self, client):
        """健康端点无需认证即可访问。"""
        with patch(
            "api.routes.system._check_database",
            return_value=_make_db_status(True),
        ), patch(
            "api.routes.system._check_vector_db",
            return_value=_make_vector_status(True),
        ), patch(
            "api.routes.system._check_acp_service",
            return_value=_make_acp_status(True),
        ), patch(
            "api.routes.system._check_circuit_breakers",
            return_value=_make_cb_status(True, open_count=0),
        ):
            response = client.get("/api/system/health")

        # 不应返回 401/403
        assert response.status_code in (200, 503)
        assert response.status_code != 401
        assert response.status_code != 403

    def test_health_response_structure(self, client):
        """响应结构包含必要的顶层字段与所有检查项。"""
        with patch(
            "api.routes.system._check_database",
            return_value=_make_db_status(True),
        ), patch(
            "api.routes.system._check_vector_db",
            return_value=_make_vector_status(True),
        ), patch(
            "api.routes.system._check_acp_service",
            return_value=_make_acp_status(True),
        ), patch(
            "api.routes.system._check_circuit_breakers",
            return_value=_make_cb_status(True, open_count=0),
        ):
            response = client.get("/api/system/health")

        body = response.json()
        # 顶层字段
        assert "status" in body
        assert "timestamp" in body
        assert "checks" in body
        # 检查项完整性
        assert set(body["checks"].keys()) == {"database", "vector_db", "acp", "circuit_breakers"}
        # 每个检查项至少包含 ok 字段
        for name, check in body["checks"].items():
            assert "ok" in check, f"check {name} 缺少 ok 字段"
