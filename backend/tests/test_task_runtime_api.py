"""
Task Runtime API 回归测试，覆盖显式鉴权、标准 HTTP 错误语义与 transcript 损坏行告警。
"""

from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.dependencies import get_current_user
from api.routes.task_runtime import router as task_runtime_router
from api.routes import task_runtime as task_runtime_route_module
from core.task_runtime import serializers


def _build_app() -> FastAPI:
    """构造仅挂载 task_runtime 路由的轻量应用，便于聚焦接口语义测试。"""
    app = FastAPI()
    app.include_router(task_runtime_router)
    return app


async def _override_current_user():
    """提供固定登录用户，避免测试依赖真实鉴权链路。"""
    return SimpleNamespace(id="user-1", username="tester", role="user")


def test_task_runtime_routes_require_authentication(monkeypatch):
    """未认证访问 task_runtime 路由时，应明确返回 401。"""

    async def noop_initialize():
        return None

    monkeypatch.setattr(task_runtime_route_module.task_runtime, "initialize", noop_initialize)
    app = _build_app()

    with TestClient(app) as client:
        response = client.get("/api/task-runtime/agents")

    assert response.status_code == 401
    assert response.json()["detail"] == "Could not validate credentials"


def test_get_agent_returns_404_for_missing_resource(monkeypatch):
    """获取不存在的代理时，应返回标准 404，而不是 200 + error 字段。"""

    async def noop_initialize():
        return None

    async def fake_get_agent(agent_id: str):
        return None

    monkeypatch.setattr(task_runtime_route_module.task_runtime, "initialize", noop_initialize)
    monkeypatch.setattr(task_runtime_route_module.task_runtime, "get_agent", fake_get_agent)

    app = _build_app()
    app.dependency_overrides[get_current_user] = _override_current_user

    with TestClient(app) as client:
        response = client.get("/api/task-runtime/agents/agt_missing")

    assert response.status_code == 404
    assert response.json()["detail"] == "代理不存在: agt_missing"


def test_read_message_returns_404_for_missing_resource(monkeypatch):
    """读取不存在的邮箱消息时，应将底层错误提升为标准 404。"""

    async def noop_initialize():
        return None

    async def fake_read_message(message_id: str):
        return {"ok": False, "error": f"消息不存在: {message_id}"}

    monkeypatch.setattr(task_runtime_route_module.task_runtime, "initialize", noop_initialize)
    monkeypatch.setattr(task_runtime_route_module.task_runtime, "read_message", fake_read_message)

    app = _build_app()
    app.dependency_overrides[get_current_user] = _override_current_user

    with TestClient(app) as client:
        response = client.post("/api/task-runtime/mailbox/msg_missing/read")

    assert response.status_code == 404
    assert response.json()["detail"] == "消息不存在: msg_missing"


def test_read_transcript_logs_warning_for_corrupted_lines(tmp_path, monkeypatch):
    """transcript 存在坏行时，应记录告警并继续返回其余有效记录。"""

    class _FakeBoundLogger:
        """记录 bind 上下文与 warning 消息，便于断言告警内容。"""

        def __init__(self):
            self.records = []

        def bind(self, **kwargs):
            self.records.append({"bind": kwargs})
            return self

        def warning(self, message: str):
            self.records.append({"warning": message})

    fake_logger = _FakeBoundLogger()
    transcript_dir = tmp_path / "transcripts"
    transcript_dir.mkdir(parents=True, exist_ok=True)
    transcript_path = transcript_dir / "agt_demo.jsonl"
    transcript_path.write_text(
        '{"type":"start"}\n'
        'not-json-line\n'
        '{"type":"stop"}\n',
        encoding="utf-8",
    )

    monkeypatch.setattr(serializers, "logger", fake_logger)
    monkeypatch.setattr(serializers, "get_transcript_dir", lambda: transcript_dir)

    entries = serializers.read_transcript("agt_demo")

    assert entries == [{"type": "start"}, {"type": "stop"}]
    assert any(
        record.get("bind", {}).get("line_number") == 2
        and record.get("bind", {}).get("agent_id") == "agt_demo"
        for record in fake_logger.records
    )
    assert any(
        "transcript 存在损坏行，已跳过" in record.get("warning", "")
        for record in fake_logger.records
    )
