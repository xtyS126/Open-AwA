"""
聚焦验证 chat 路由异常分支的类型安全：error 字段必须为 dict（含 code/message），
禁止回退为 str，避免触发 Pydantic ValidationError 二次 500。
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from api.dependencies import get_current_user, get_db
from main import app


def _override_get_current_user():
    """测试用：返回一个最小化的 fake user，绕过真实认证。"""
    return SimpleNamespace(
        id="test-user-1",
        username="tester",
        role="user",
    )


def _override_get_db():
    """测试用：返回未找到会话记录的数据库替身。"""
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None
    yield db


@pytest.fixture
def chat_client(monkeypatch):
    """构造一个绕过认证与 DB 的 TestClient，便于直接测试 chat 路由异常分支。"""
    app.dependency_overrides[get_current_user] = _override_get_current_user
    app.dependency_overrides[get_db] = _override_get_db
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_db, None)


def test_chat_returns_dict_error_when_agent_raises_exception(chat_client, monkeypatch):
    """
    AIAgent.process 抛异常时，chat 路由应返回 error 字段为 dict 类型，
    含 code 和 message 两个键，避免回退为 str 触发二次 500。
    """

    async def fake_process_raise(self, message, context):
        raise RuntimeError("模拟 Agent 内部错误")

    # 直接 patch AIAgent.process 让其抛异常
    from core.agent import AIAgent
    monkeypatch.setattr(AIAgent, "process", fake_process_raise)

    response = chat_client.post(
        "/api/chat",
        json={
            "message": "你好",
            "session_id": "session-error-test",
            "mode": "chat",  # 非流式
        },
    )

    assert response.status_code == 200, f"期望 200（异常被捕获并构造 ChatResponse），实际 {response.status_code}: {response.text}"

    payload = response.json()
    assert payload["status"] == "error"
    # 关键断言：error 必须是 dict，不能是 str
    assert isinstance(payload["error"], dict), f"error 应为 dict 类型，实际为 {type(payload['error']).__name__}: {payload['error']!r}"
    assert "code" in payload["error"]
    assert "message" in payload["error"]
    assert payload["error"]["code"] == "agent_process_failed"
    # message 中应包含原异常信息
    assert "模拟 Agent 内部错误" in payload["error"]["message"]


def test_chat_returns_dict_error_when_agent_raises_cancelled_error(chat_client, monkeypatch):
    """
    asyncio.CancelledError 分支也应返回 dict 类型的 error，
    含 code=task_cancelled 和 message 字段。
    """

    async def fake_process_cancelled(self, message, context):
        raise asyncio.CancelledError()

    from core.agent import AIAgent
    monkeypatch.setattr(AIAgent, "process", fake_process_cancelled)

    response = chat_client.post(
        "/api/chat",
        json={
            "message": "你好",
            "session_id": "session-cancel-test",
            "mode": "chat",
        },
    )

    assert response.status_code == 200, f"期望 200（取消异常被捕获），实际 {response.status_code}: {response.text}"

    payload = response.json()
    assert payload["status"] == "cancelled"
    # 关键断言：error 必须是 dict，不能是 str
    assert isinstance(payload["error"], dict), f"error 应为 dict 类型，实际为 {type(payload['error']).__name__}: {payload['error']!r}"
    assert "code" in payload["error"]
    assert "message" in payload["error"]
    assert payload["error"]["code"] == "task_cancelled"


def test_chat_dict_error_serializes_without_validation_error(chat_client, monkeypatch):
    """
    验证 dict 类型 error 能正常序列化为 JSON 返回客户端，
    不触发 Pydantic ValidationError 二次 500（regression 测试）。
    """

    async def fake_process_raise_value_error(self, message, context):
        raise ValueError("配置参数无效")

    from core.agent import AIAgent
    monkeypatch.setattr(AIAgent, "process", fake_process_raise_value_error)

    response = chat_client.post(
        "/api/chat",
        json={
            "message": "测试",
            "session_id": "session-validation",
            "mode": "chat",
        },
    )

    # 关键：不应返回 500（说明 ChatResponse 构造成功，未触发 ValidationError）
    assert response.status_code == 200, f"不应返回 500（说明 error 字段类型正确），实际 {response.status_code}: {response.text}"

    payload = response.json()
    assert payload["status"] == "error"
    assert isinstance(payload["error"], dict)
    # 验证 error dict 可以正确 JSON 序列化（response.json() 不抛异常即说明结构合法）
    assert payload["error"]["code"] == "agent_process_failed"
    assert "配置参数无效" in payload["error"]["message"]
