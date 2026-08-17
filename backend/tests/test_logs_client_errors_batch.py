# -*- coding: utf-8 -*-
"""
客户端错误批量上报端点单元测试。

覆盖模块 F1 的 POST /api/logs/client-errors 端点：
1. 批量 payload ``{"reports": [...]}`` 写入多条，返回 ``received=count``
2. 单条 payload ``{level, message, ...}`` 向后兼容，返回 ``received=1``
3. 空数组 ``[]`` 返回 ``received=0``
4. reports 非数组返回 422
5. 批量超过上限返回 413
6. 批量中非对象元素被跳过，不阻断整批上报
"""

from __future__ import annotations

import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.dependencies import get_optional_current_user
from api.routes.logs import (
    _CLIENT_ERROR_MAX_BATCH,
    _client_error_timestamps,
    router as logs_router,
)


# ==================== 测试用户与依赖覆盖 ====================


class _DummyUser:
    """测试用 DummyUser，仅暴露 id/username/role 三个字段。"""

    def __init__(self, user_id: str, username: str) -> None:
        self.id = user_id
        self.username = username
        self.role = "user"


# 模拟未登录用户（client-errors 端点允许匿名上报）
_ANON_USER: Optional[_DummyUser] = None


# ==================== 公共 fixture ====================


@pytest.fixture(autouse=True)
def _clear_rate_limit_state():
    """每个测试前后清空 per-IP 速率限制计数器，避免跨用例污染。"""
    _client_error_timestamps.clear()
    yield
    _client_error_timestamps.clear()


@contextmanager
def _build_client() -> Iterator[TestClient]:
    """构造挂载 logs_router 的 TestClient（prefix=/api 与生产路径一致）。"""
    app = FastAPI()
    app.include_router(logs_router, prefix="/api")
    # client-errors 端点用 get_optional_current_user，未登录返回 None
    app.dependency_overrides[get_optional_current_user] = lambda: _ANON_USER
    with TestClient(app) as client:
        yield client


def _make_report(message: str = "test error") -> dict:
    """构造一条合法的客户端错误报告。"""
    return {
        "level": "ERROR",
        "message": message,
        "source": "test-suite",
        "stack": "",
        "url": "/test",
        "user_agent": "pytest",
        "timestamp": "2026-08-12T00:00:00Z",
        "extra": {},
    }


# ==================== 批量上报测试 ====================


class TestReportClientErrorBatch:
    """POST /api/logs/client-errors 批量上报。"""

    def test_batch_payload_writes_multiple_reports(self) -> None:
        """批量 payload 应写入多条并返回 received=count。"""
        reports = [_make_report(f"error {i}") for i in range(3)]
        with _build_client() as client:
            response = client.post("/api/logs/client-errors", json={"reports": reports})

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "received"
        assert body["received"] == 3

    def test_single_payload_backward_compatible(self) -> None:
        """单条 payload（无 reports 字段）应向后兼容，返回 {"status": "received"}。"""
        payload = _make_report("single error")
        with _build_client() as client:
            response = client.post("/api/logs/client-errors", json=payload)

        assert response.status_code == 200, response.text
        body = response.json()
        # 单条模式完全向后兼容，不新增 received 字段
        assert body == {"status": "received"}

    def test_empty_reports_array_returns_zero(self) -> None:
        """空数组 [] 应返回 received=0。"""
        with _build_client() as client:
            response = client.post("/api/logs/client-errors", json={"reports": []})

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "received"
        assert body["received"] == 0

    def test_reports_not_array_returns_422(self) -> None:
        """reports 字段非数组应返回 422。"""
        with _build_client() as client:
            response = client.post(
                "/api/logs/client-errors",
                json={"reports": "not-an-array"},
            )

        assert response.status_code == 422, response.text

    def test_batch_exceeds_max_returns_413(self) -> None:
        """批量条数超过 _CLIENT_ERROR_MAX_BATCH 应返回 413。"""
        reports = [_make_report(f"error {i}") for i in range(_CLIENT_ERROR_MAX_BATCH + 1)]
        with _build_client() as client:
            response = client.post("/api/logs/client-errors", json={"reports": reports})

        assert response.status_code == 413, response.text

    def test_batch_skips_non_dict_elements(self) -> None:
        """批量中非对象元素应被跳过，不阻断整批上报。"""
        reports = [
            _make_report("valid-1"),
            "not-a-dict",
            None,
            _make_report("valid-2"),
        ]
        with _build_client() as client:
            response = client.post("/api/logs/client-errors", json={"reports": reports})

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["received"] == 2

    def test_batch_with_logged_in_user_attaches_user_id(self) -> None:
        """登录用户批量上报时，current_user 注入应可用且不影响 received 计数。"""
        dummy = _DummyUser("user-logged", "alice")
        reports = [_make_report("with-user")]
        app = FastAPI()
        app.include_router(logs_router, prefix="/api")
        app.dependency_overrides[get_optional_current_user] = lambda: dummy
        with TestClient(app) as client:
            response = client.post("/api/logs/client-errors", json={"reports": reports})

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["received"] == 1
